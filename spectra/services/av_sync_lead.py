"""THE A/V-SYNC LEAD — the one place a measured room offset becomes a
change to when SPECTRA's lights fire (owner ask 2026-08-28,
corr=6b8097aa97a3cd28: "when I run avsync how do I update the offset
value based on that data?").

This module is BOTH halves of that sentence, deliberately in one file so
the sign law is written once:

  * the CLOCK half — show_clock_ms(), the single point where the setting
    reaches the show (spectra/services/engine.py's trigger poll);
  * the TRANSLATION half — proposal(), which turns a measurement the
    instrument stood behind into the value his press would write.

WHY THIS SETTING EXISTS AT ALL (read before adding a second one)
----------------------------------------------------------------
The AV-sync instrument (spectra/services/av_sync_session.py) was built
measure-only: "his authored offsets are his; the result is presented for
him to accept, never written into settings." When the apply loop was
asked for, the target was hunted for in code and **did not exist** —
SPECTRA's fire clock had exactly ONE correction term, and it isn't
authored: bridge.effective_position_ms() = raw position +
shape_offset_ms, spot-effects' machine-learned per-song xcorr number,
which WANDERS mid-song (docs/SPECTRA_TIMING_CONVENTIONS.md, failure case
2 is someone reading it as a measurement).

The two pre-existing numbers that LOOK like candidates are different
jobs, not older values of this one. Nothing here reads or adjusts
either, and no copy anywhere may imply it does:

  * settings.audio_latency_ms (root config.py, live) — how long the audio
    pipeline takes to deliver sound after Spotify reports a timestamp,
    used ONLY to align WAV capture boundaries when building the xcorr
    training corpus. It is not a fire-time offset. It is also, per a live
    check 2026-08-28, the number he remembers as "150".
  * settings.ledfx_trigger_buffer_ms (root config.py, LEAD family) —
    LedFX-HTTP write-transport compensation for a write path SPECTRA's
    executor does not share (bridge.py's docstring calls this "a genuine
    mechanism-differs-in-kind case, not a value worth guessing at"). Read
    only by the RETIRED legacy engine (legacy_trigger_engine_enabled
    defaults False); it holds an inert -800 on his live box. Seeding a
    calibration from it would be seeding from a dead knob.

Neither is reachable from here in any case: nothing under spectra/ may
import spot-effects runtime internals (scripts/check_process_split.py
§1) and the bridge is one-directional by contract.

THE SIGN LAW — LEAD family, stated once
----------------------------------------
`RoomControlState.av_sync_lead_ms` is **LEAD family: positive = fire
EARLIER, negative = fire LATER.** It is the same family and the same
mechanism as the shape_offset_ms it sits beside — expressed as a clock
shift, which is algebraically identical to subtracting the same amount
from every target (`now + lead >= target` iff `now >= target - lead`):

    show_clock_ms = effective_position_ms + av_sync_lead_ms

A positive lead makes the song read as further along, so the engine
reaches each trigger mark sooner, so the lights fire earlier.

`None` (the default) is NOT the number zero: it means NEVER CALIBRATED.
Nothing about his show changes until his first apply, and the dialogue
shows "none yet" rather than a "0 ms" that would read like a measured
result. Both resolve to no shift at the clock (`_effective`).

THE TRANSLATION — why the measurement is ADDED, never assigned
---------------------------------------------------------------
av_offset_ms is a MEASUREMENT of the room AS IT IS RIGHT NOW — taken
with whatever lead is already in effect. Positive means the light
reached the phone LATER than the sound it was meant to land with. So the
correction is layered on top of what is already applied:

    proposed_lead_ms = current_lead_ms + round(av_offset_ms)

Assigning instead of adding would silently undo an earlier calibration
every time he re-measured: with a 50 ms lead already applied and a
residual +120 ms still measured, the room needs 170 ms of lead, not 120.

Worked, both directions (the same two examples as the master table's
`av_sync_lead_ms` row in docs/SPECTRA_TIMING_CONVENTIONS.md):

    current None, measured +120 (lights BEHIND)  -> proposed +120
        delta +120 -> "lights will fire 120 ms EARLIER than they do now"
    current +120, measured  -45 (lights AHEAD)   -> proposed  +75
        delta  -45 -> "lights will fire 45 ms LATER than they do now"

The delta a human reads is always `proposed - current`, and it always
equals the measurement — but it is stated as a DIRECTION SENTENCE, never
a bare signed number he has to sign-infer. Direction errors are this
fleet's most repeated failure (that table's whole reason for existing);
the sentence is as much the deliverable as the number.

NOTHING TO APPLY WITHOUT A NUMBER
----------------------------------
proposal() refuses exactly where the instrument refuses. A refused
estimate (weak / ambiguous / unstable / no_data / clock / audio / light)
carries `applicable: False` and the instrument's OWN reason forward — it
never substitutes a guess, a last-known value, or a zero. The apply
surface renders the reason and offers no apply path.

This module never writes. The write is his press, and it goes through
PUT /api/room-controls — the same save path every other room control
uses — followed by a read-back.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# The bound the setting itself declares (RoomControlState.av_sync_lead_ms).
# A measurement that would propose past it is reported as out_of_range with
# the clamped value NAMED, never silently clamped and applied.
LEAD_MIN_MS = -2000
LEAD_MAX_MS = 2000

# How many stored measurements the apply surface shows him so run-to-run
# stability is visible (the store keeps MEASUREMENTS_KEEP=100).
RECENT_RUNS = 5


def _effective(lead_ms: Optional[int]) -> int:
    """The clock shift a stored setting actually applies. None (never
    calibrated) and 0 (calibrated to no shift) both mean no shift — they
    differ only in what the DIALOGUE says, never in what the room does."""
    return int(lead_ms or 0)


def show_clock_ms(position_ms: Optional[int], lead_ms: Optional[int]) -> Optional[int]:
    """THE ONE PLACE the setting reaches the show (called from
    spectra/services/engine.py's trigger poll, nowhere else — a second
    application point could quietly disagree with this one).

    LEAD family: positive lead => the position reads further along =>
    trigger marks are reached sooner => the lights fire EARLIER. Exactly
    the shape bridge.effective_position_ms() already applies for
    shape_offset_ms; this term is layered on top of that one.

    A position of None (bridge down / no track) stays None — a missing
    clock is never invented from a lead."""
    if position_ms is None:
        return None
    return int(position_ms) + _effective(lead_ms)


def current_lead_ms() -> Optional[int]:
    """The stored setting, read fresh (no restart to take effect — the
    same discipline scene_change_mode is read with, one line above this
    one in the same tick)."""
    from spectra.services.room_controls import load_room_controls
    return load_room_controls().av_sync_lead_ms


def direction_sentence(delta_ms: int) -> str:
    """His terms, never a bare delta. The subject is always the lights and
    the reference is always "than they do now", so the sentence reads the
    same whichever direction it goes."""
    if delta_ms == 0:
        return "No change: the lights already fire where this measurement says they should."
    if delta_ms > 0:
        return f"Lights will fire {delta_ms} ms EARLIER than they do now."
    return f"Lights will fire {abs(delta_ms)} ms LATER than they do now."


def current_phrase(lead_ms: Optional[int]) -> str:
    """What the dialogue prints for the CURRENT value. `None` prints as
    "none yet" — never a borrowed number from another setting, and never
    a "0 ms" that would read like a measured result (see the module
    docstring: the two numbers that look like candidates are different
    jobs, not previous values of this one)."""
    if lead_ms is None:
        return "none yet — never calibrated"
    if lead_ms == 0:
        return "0 ms (no shift)"
    return f"{abs(lead_ms)} ms {'earlier' if lead_ms > 0 else 'later'}"


@dataclass
class Proposal:
    """What the apply dialogue renders. `applicable` is the single gate:
    False means the instrument did not stand behind a number, and the
    surface must offer no apply path at all."""
    applicable: bool
    reason: str = ""
    measured_av_offset_ms: Optional[float] = None
    sigma_ms: Optional[float] = None
    systematic_later_ms: float = 0.0
    systematic_earlier_ms: float = 0.0
    systematic_bound_ms: float = 0.0
    systematics: list = field(default_factory=list)
    current_lead_ms: Optional[int] = None
    current_phrase: str = ""
    proposed_lead_ms: Optional[int] = None
    delta_ms: Optional[int] = None
    direction_sentence: str = ""
    out_of_range: bool = False
    statement: str = ""
    recent: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "applicable": self.applicable,
            "reason": self.reason,
            "measured_av_offset_ms": self.measured_av_offset_ms,
            "sigma_ms": self.sigma_ms,
            "systematic_later_ms": self.systematic_later_ms,
            "systematic_earlier_ms": self.systematic_earlier_ms,
            "systematic_bound_ms": self.systematic_bound_ms,
            "systematics": self.systematics,
            "current_lead_ms": self.current_lead_ms,
            "current_phrase": self.current_phrase,
            "proposed_lead_ms": self.proposed_lead_ms,
            "delta_ms": self.delta_ms,
            "direction_sentence": self.direction_sentence,
            "out_of_range": self.out_of_range,
            "statement": self.statement,
            "recent": self.recent,
        }


def _directional(estimate: dict, key: str) -> float:
    """A LIVE estimate carries the systematics split by direction; a STORED
    record (av_sync_session._record) keeps only the total
    systematic_bound_ms. Fall back to that total on BOTH directions rather
    than reporting zero — an unknown split is not an absent uncertainty,
    and understating it here is the one direction this dialogue must never
    err in."""
    value = estimate.get(key)
    if value is not None:
        return float(value)
    return float(estimate.get("systematic_bound_ms") or 0.0)


def proposal(estimate: Optional[dict], current: Optional[int],
             recent: Optional[list] = None) -> Proposal:
    """Turn an estimate dict (av_sync_session.Estimate.as_dict(), or a
    stored measurement record of the same shape) into what his press
    would write.

    REFUSAL IS CARRIED FORWARD, NEVER PAPERED OVER: no estimate at all,
    `ok: False`, or a null `av_offset_ms` all return applicable=False with
    the instrument's own reason. Nothing here re-derives, re-tries, or
    falls back to a previous run's number."""
    recent = list(recent or [])
    current_text = current_phrase(current)
    if not estimate:
        return Proposal(applicable=False, reason="no_measurement",
                        current_lead_ms=current, current_phrase=current_text,
                        recent=recent,
                        statement="No measurement yet — run one first.")
    measured = estimate.get("av_offset_ms")
    base = Proposal(
        applicable=False,
        reason=str(estimate.get("reason") or ""),
        measured_av_offset_ms=measured,
        sigma_ms=estimate.get("sigma_ms"),
        systematic_later_ms=_directional(estimate, "systematic_later_ms"),
        systematic_earlier_ms=_directional(estimate, "systematic_earlier_ms"),
        systematic_bound_ms=float(estimate.get("systematic_bound_ms") or 0.0),
        systematics=list(estimate.get("systematics") or []),
        current_lead_ms=current, current_phrase=current_text,
        statement=str(estimate.get("statement") or ""),
        recent=recent,
    )
    if not estimate.get("ok") or measured is None:
        # The instrument refused. Its reason is the whole answer; there is
        # nothing to propose and no apply path to offer.
        base.reason = base.reason or "refused"
        return base

    delta = int(round(float(measured)))
    proposed = _effective(current) + delta
    base.delta_ms = delta
    base.direction_sentence = direction_sentence(delta)
    if proposed < LEAD_MIN_MS or proposed > LEAD_MAX_MS:
        # NAMED, not silently clamped: a proposal past the setting's own
        # declared bound is a result worth him seeing, not one to quietly
        # round into range and apply as if it were what was measured.
        base.out_of_range = True
        base.reason = "out_of_range"
        base.proposed_lead_ms = max(LEAD_MIN_MS, min(LEAD_MAX_MS, proposed))
        return base
    base.applicable = True
    base.reason = ""
    base.proposed_lead_ms = proposed
    return base


def recent_runs(measurements: list, limit: int = RECENT_RUNS) -> list[dict]:
    """The last few stored runs, newest first — so run-to-run stability is
    something he can SEE rather than take on trust. Refused runs are kept
    in the list (a run that produced no number is itself information about
    the conditions); each carries its own ok/reason."""
    rows: list[dict] = []
    for rec in list(measurements)[-int(limit):][::-1]:
        rows.append({
            "id": rec.get("id"),
            "at_iso": rec.get("at_iso"),
            "mode": rec.get("mode"),
            "ok": bool(rec.get("ok")),
            "av_offset_ms": rec.get("av_offset_ms"),
            "sigma_ms": rec.get("sigma_ms"),
        })
    return rows


def spread_ms(recent: list[dict]) -> Optional[float]:
    """Max-minus-min across the recent runs that produced a number, or
    None when fewer than two did. This is the run-to-run wobble he can
    actually check the sigma against — deliberately NOT folded into the
    sigma or the systematics, which measure different things."""
    values = [float(r["av_offset_ms"]) for r in recent
              if r.get("ok") and r.get("av_offset_ms") is not None]
    if len(values) < 2:
        return None
    return round(max(values) - min(values), 1)


TWO_RUNS_NOTE = ("A difference between two runs on this same phone is far tighter "
                 "than either absolute number — if you are chasing a change, compare "
                 "runs rather than trusting one figure.")
