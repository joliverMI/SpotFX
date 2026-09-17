"""THE KNOWN AUDIO BUFFER — River publishes how far his sound is running
behind, and SPECTRA MIRRORS it (card 1ylu, 2026-09-17; Admiral order 30).

His approved words for what this is: "It watches how far your sound is
running behind and reports that number to Spectra, so your lights can line
up with what you actually hear."

THE NAME IS THE INSTRUCTION. The field is `effects_fire_later_by_ms`
everywhere it appears — River's wire, this module, the setting names, the
status key, the help topic. Never rename it, never shorten it, never
abbreviate it in a payload. Its meaning IS its name: a LARGER value means
the sound is FURTHER BEHIND, so effects must fire that many ms LATER to
land on what he actually hears. It is applied as published and NEVER
negated.

ORDER 30 — THE AUDIO LAG IS HIS HEADROOM. Nothing in this module touches
audio, changes a delay, shortens a buffer, or reads or writes
`av_sync_lead_ms`. SPECTRA mirrors the number River publishes. It never
asks for a smaller one.

WHERE THE NUMBER COMES FROM, AND WHAT IT IS NOT
------------------------------------------------
River's surface is loopback-only HTTP on serenity:

    GET {url}/offset               the current value (the slow ramp; poll)
    GET {url}/events               Server-Sent Events — the current value on
                                   connect, then one event per STEP
    GET {url}/samples?since_ms=    raw samples (2 h)  [not consumed here]
    GET {url}/health                                  [not consumed here]

River's own `doc` field states the scope of the number, and it is narrower
than "the audio path": it is "the governor's held delay + kernel pipe
backlog + PulseAudio's parec buffer; snapserver buffer=1000, flac, network
and snapclient latencies are fixed and NOT included." So the published
value covers the SOURCE-side buffer upstream of the snapserver only. That
sentence is load-bearing for the seam question (see THE SEAM below) — do
not restate it from memory, it is quoted here because it decides where the
number may legitimately be applied.

TWO PATHS, ONE RECORD. Nothing is pushed into SPECTRA (there is no inbound
route and none is wanted — River initiates nothing here). The SLOW RAMP is
POLLED every `known_buffer_update_period_s`; the DISCONTINUITY (a drain, a
step in one instant) arrives over the SSE subscriber the moment River
emits it. Both call `record()` and land in the same place, so there is
exactly one idea of "the current reading".

A STEP IS NEVER SMOOTHED ACROSS AN EPOCH CHANGE. River stamps a step with
a new `epoch` plus `discontinuity`/`step_cause`; a reading carrying a new
epoch replaces the old one outright. There is no filter, no ramp and no
averaging anywhere in this module — a mirror that smoothed would stop
being a mirror.

THE STALENESS LADDER — measured from the timestamp, never inferred
-------------------------------------------------------------------
Every reading carries River's own `t_ms` (unix ms, serenity clock — the
same host, so it is directly comparable) and a `source`. Age is computed
from that timestamp; nothing here guesses at freshness from whether a
request succeeded.

    FRESH    age <= 1 x period                      -> apply
    STALE    age <= `stale_periods` x period        -> HOLD the last known
             (default FOUR periods)                    value AND surface
                                                       its age everywhere
                                                       the value is shown
    MISSING  older than that, or never received     -> THE FLOOR

`stale_periods` is a MULTIPLE, not a number of seconds, deliberately: the
period is a setting, and a ladder expressed in seconds would silently
change meaning the first time the period was retuned.

River publishes its OWN freshness view (`stale`, `age_ms`, `source` =
measured|held|floor_fallback). Both views are surfaced side by side and
neither overrides the other — ours is about whether SPECTRA is still
hearing from River, River's is about whether River is still measuring.

STALE IS NOT A FAULT, and on a healthy River it is HALF OF NORMAL. River
re-measures on its own 15 s period, so the value it serves is already up
to one period old the moment it is fetched; our own FRESH window is one
period, so a perfectly healthy steady state oscillates fresh/stale as the
reading ages between River's updates (measured live 2026-09-17: a reading
fetched from /offset reported River `age_ms` 14591). The ladder is
implemented exactly as ratified rather than widened to fit — STALE holds
the value, changes nothing about what is applied, and surfaces its age.
Anything that renders this must say so; a surface that paints STALE as a
problem would cry wolf every other quarter-minute. River's own `stale`
(its 1.5-period threshold) is beside ours for exactly this reason.

ZERO IS FORBIDDEN, AND SO IS EVERY SYNONYM FOR IT
--------------------------------------------------
See `effective_value_ms` below, where the missing case is decided. The two
comment lines that must stay there say it in the required words. The short
form: zero asserts his speakers are in sync with the source, which is the
one thing known to be false; and "uncorrected" / "no correction" is the
same forbidden thing wearing a different word.

THE FLOOR IS HIS HEADROOM, NOT A TUNING PARAMETER
--------------------------------------------------
`known_buffer_floor_ms` (default 500) is read from configuration from the
first commit — he proposed 500 with a question mark, so it is a setting,
never a constant. A published value BELOW the floor is never applied below
it: the floor holds and `below_floor` is flagged.

`known_buffer_ceiling_ms` (default 1500) is a SETTING and NOT a clamp: a
variable buffer tracked accurately is allowed to pass it (the bounding
that would hold it down is River's separate, not-yet-live half). Going
over is flagged `above_ceiling` and surfaced. The dependency note for a
future tuner lives beside the setting in room_controls.py: a lower ceiling
means more frequent drains, which is only safe because the step is
push-driven; if pushes ever become unreliable the ceiling has to rise.

THE APPLICATION GATE — nothing reaches the show while the number is a floor
---------------------------------------------------------------------------
With River's bounding half off, River can only see the parec buffer, so
the number it publishes is the CONTRACTUAL FLOOR and not a measured delay
(the live reading taken 2026-09-17 16:36 EDT: value 500, `floor_clamped`
true, `governed` false). Applying a floor as if it were a measurement
would push his lights 300-500 ms BEHIND the sound — the exact harm this
whole feature exists to avoid.

So compensation is applied ONLY when `floor_clamped == false` (equivalently
`governed == true`). Until then the state block reads
`apply_gate: "waiting for the bounding half (floor_clamped)"`,
`compensation_ms: 0` with the reason, and NOTHING reaches the show clock.
Ingestion, display and logging all run meanwhile — the drift picture is
being built the whole time. `av_sync_lead_ms` is untouched in every case.

THE SEAM — PARKED, and this module does not wire it
----------------------------------------------------
Whether the published value belongs at the show clock at all is a
DECISION, not an implementation detail, because SPECTRA's fire clock
already carries a correction that may or may not have absorbed this
buffer: `effective_position_ms = raw position + shape_offset_ms`, where
`shape_offset_ms` is spot-effects' per-song xcorr lock. That lock
correlates against `snapcast.monitor`, and the measured fact is that
`snapcast.monitor` is the monitor of the sink the SNAPCLIENT plays into —
speaker time, downstream of every buffer including the source-side one
River publishes. See the PR for the full finding.

`compensation_ms` is therefore computed and SURFACED here, and consumed
nowhere. When the seam is ruled, the consumer is added at the ruled seam
and this docstring records which one.

REFERENCE-BASED, so going live changes nothing in his room
-----------------------------------------------------------
`compensation_ms = effective_value_ms - reference_ms`, positive = LATER.
The reference is established from the first reading that PASSES THE GATE
(a floor-clamped reading is not a measurement, so it cannot anchor a
delta), and is RE-BASED whenever his A/V lead is applied through
`av_sync_lead`'s apply path — that measurement absorbed the buffer as it
stood, so the delta must start again from there. The consequence he cares
about: the day this goes live the compensation is 0, and his
`av_sync_lead_ms` reads the same before and after.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from spectra import config as scfg

logger = logging.getLogger(__name__)

# How long a single HTTP read of River's /offset may take. Short on
# purpose: a failed poll records NOTHING and the ladder ages the last good
# reading, which is a better answer than a request that hangs past its own
# period and starts overlapping the next one.
POLL_TIMEOUT_S = 5.0

# SSE reconnect backoff, seconds. River is on loopback, so a failure here
# is River restarting rather than a network problem; the backoff exists so
# a down River is not hammered, not because reconnecting is expensive.
SSE_BACKOFF_MIN_S = 1.0
SSE_BACKOFF_MAX_S = 30.0

# The raw series is kept for the drift picture (amendment 1, item 6) and
# pruned on write. Seven days at River's 15 s period is ~40k lines.
LOG_RETENTION_S = 7 * 24 * 3600

# The gate's own sentence, one definition so the state block, the timing
# page and the help topic cannot describe it three different ways.
APPLY_GATE_WAITING = "waiting for the bounding half (floor_clamped)"
APPLY_GATE_OPEN = ""

STATE_UNCONFIGURED = "unconfigured"
STATE_FRESH = "fresh"
STATE_STALE = "stale"
STATE_MISSING = "missing"


@dataclass
class Reading:
    """One reading, exactly as River published it plus how it reached us.

    Nothing of River's is renamed. `raw` keeps the whole payload so a field
    River adds later is on record even before anything here reads it."""
    effects_fire_later_by_ms: int
    t_ms: int
    source: str = ""
    epoch: Optional[int] = None
    discontinuity: bool = False
    step_cause: str = ""
    floor_clamped: Optional[bool] = None
    governed: Optional[bool] = None
    parec_buffer_ms: Optional[float] = None
    flowing: Optional[bool] = None
    stale: Optional[bool] = None
    age_ms: Optional[float] = None
    held_age_ms: Optional[float] = None
    update_period_ms: Optional[int] = None
    hold_limit_ms: Optional[int] = None
    floor_ms: Optional[int] = None
    via: str = ""          # "poll" | "events" — how this one arrived
    received_ms: int = 0   # our own clock, for the log only
    raw: dict = field(default_factory=dict)

    def gate_open(self) -> bool:
        """THE APPLICATION GATE. `floor_clamped == false` is the ratified
        condition; `governed == true` is the same fact from the other side
        and is accepted when River sent only that one. A reading that says
        NEITHER is treated as still gated — an unknown gate is never read
        as an open one."""
        if self.floor_clamped is not None:
            return self.floor_clamped is False
        if self.governed is not None:
            return self.governed is True
        return False


# ── module state ────────────────────────────────────────────────────────
# In-memory only, deliberately. A restart has no reading, so the ladder
# reports MISSING and the floor applies — which is the honest answer
# (nothing has been heard from River since this process started), and is
# also the safe one. Persisting a reading across a restart would let a
# reading from before the restart be presented as current.
_reading: Optional[Reading] = None
_reference_ms: Optional[int] = None
_last_error: str = ""
_poll_failures: int = 0
_sse_connected: bool = False
_readings_seen: int = 0


def reset_for_tests() -> None:
    """Drop every module global. Colocated with the state it resets so a
    new global cannot be added without this being the obvious place to
    clear it (the fire_history/param_watchdog precedent — this module has
    no DI seam either)."""
    global _reading, _reference_ms, _last_error, _poll_failures
    global _sse_connected, _readings_seen
    _reading = None
    _reference_ms = None
    _last_error = ""
    _poll_failures = 0
    _sse_connected = False
    _readings_seen = 0


# ── settings ────────────────────────────────────────────────────────────
def _settings() -> Any:
    """His room-level tunables, read FRESH (no restart to take effect —
    the same discipline the trigger poll reads scene_change_mode with).
    Imported inside the function: this module must stay importable from
    anywhere, and nothing that can be constructed at import time may touch
    room_controls eagerly (AGENTS.md's light-mode cold-start rule)."""
    from spectra.services.room_controls import load_room_controls
    return load_room_controls()


def base_url(state: Any = None) -> str:
    """River's base address. "" means UNCONFIGURED — a distinct answer from
    MISSING, and the status says so: nobody has been asked, which is not
    the same as having asked and heard nothing."""
    st = state if state is not None else _settings()
    return (st.known_buffer_source_url or "").strip().rstrip("/")


# ── ingestion ───────────────────────────────────────────────────────────
def parse(payload: Any, via: str = "") -> Reading:
    """River's shape, parsed AS-IS. Raises ValueError on anything that is
    not a usable reading — a malformed body records NOTHING and the ladder
    ages the last good one, which is strictly better than admitting a
    reading nobody can stand behind."""
    if not isinstance(payload, dict):
        raise ValueError("payload is not an object")
    if "effects_fire_later_by_ms" not in payload:
        raise ValueError("payload has no effects_fire_later_by_ms")
    raw_value = payload.get("effects_fire_later_by_ms")
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise ValueError("effects_fire_later_by_ms must be a number")
    value = float(raw_value)
    if not math.isfinite(value):
        raise ValueError("effects_fire_later_by_ms must be finite")
    if value < 0:
        # Negative would mean the sound runs AHEAD of the source, which is
        # not a thing a buffer can do, and reading it as "fire earlier"
        # would invert the whole contract.
        raise ValueError("effects_fire_later_by_ms must not be negative")
    t_ms = payload.get("t_ms")
    if isinstance(t_ms, bool) or not isinstance(t_ms, (int, float)) or not math.isfinite(float(t_ms)):
        raise ValueError("t_ms (unix ms) is required on every reading")

    def _opt_bool(key: str) -> Optional[bool]:
        v = payload.get(key)
        return bool(v) if isinstance(v, bool) else None

    def _opt_num(key: str) -> Optional[float]:
        v = payload.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return float(v) if math.isfinite(float(v)) else None

    def _opt_int(key: str) -> Optional[int]:
        v = _opt_num(key)
        return None if v is None else int(v)

    return Reading(
        effects_fire_later_by_ms=int(round(value)),
        t_ms=int(t_ms),
        source=str(payload.get("source") or ""),
        epoch=_opt_int("epoch"),
        discontinuity=bool(payload.get("discontinuity") or False),
        step_cause=str(payload.get("step_cause") or ""),
        floor_clamped=_opt_bool("floor_clamped"),
        governed=_opt_bool("governed"),
        parec_buffer_ms=_opt_num("parec_buffer_ms"),
        flowing=_opt_bool("flowing"),
        stale=_opt_bool("stale"),
        age_ms=_opt_num("age_ms"),
        held_age_ms=_opt_num("held_age_ms"),
        update_period_ms=_opt_int("update_period_ms"),
        hold_limit_ms=_opt_int("hold_limit_ms"),
        floor_ms=_opt_int("floor_ms"),
        via=via,
        received_ms=int(time.time() * 1000),
        raw=dict(payload),
    )


def record(payload: Any, via: str = "") -> Reading:
    """Take one reading from either path. A STEP (a new `epoch`) REPLACES
    the current reading outright — never blended, never averaged toward:
    smoothing across an epoch change is exactly what River's discontinuity
    marking exists to prevent.

    An OLDER reading than the one already held is kept as the log line it
    is but never replaces the current one; the poll and the SSE stream run
    independently, so a slow poll response can land after a step."""
    global _reading, _reference_ms, _readings_seen, _last_error
    reading = parse(payload, via=via)
    _readings_seen += 1
    _log(reading)
    current = _reading
    if current is not None and reading.t_ms < current.t_ms and reading.epoch == current.epoch:
        logger.debug("known buffer: ignoring an out-of-order reading (%d < %d)",
                     reading.t_ms, current.t_ms)
        return current
    if current is not None and reading.epoch is not None \
            and current.epoch is not None and reading.epoch != current.epoch:
        logger.info("known buffer: epoch %s -> %s (%s%s) — applied at once, "
                    "never smoothed", current.epoch, reading.epoch,
                    reading.step_cause or "step",
                    ", discontinuity" if reading.discontinuity else "")
    _reading = reading
    _last_error = ""
    if _reference_ms is None and reading.gate_open():
        # The reference can only be anchored on a reading the gate accepts:
        # a floor-clamped number is the contract's floor, not a measurement,
        # so a delta taken from it would be a delta from a fiction.
        _reference_ms = effective_value_ms(reading, _settings())
        logger.info("known buffer: reference set at %d ms (first ungated "
                    "reading) — compensation starts from zero", _reference_ms)
    return reading


def rebase_reference() -> Optional[int]:
    """Re-anchor the delta. Called when his A/V lead is applied: that
    measurement was taken with the buffer AS IT STOOD, so it already
    absorbed whatever the buffer was at that moment, and the compensation
    must start again from there rather than double-counting it.

    Returns the new reference, or None when there is nothing to anchor on
    (no reading, or the gate is still shut)."""
    global _reference_ms
    reading = _reading
    if reading is None or not reading.gate_open():
        return None
    _reference_ms = effective_value_ms(reading, _settings())
    logger.info("known buffer: reference re-based to %d ms after an A/V "
                "lead apply", _reference_ms)
    return _reference_ms


# ── the ladder ──────────────────────────────────────────────────────────
def age_s(reading: Optional[Reading], now_ms: Optional[float] = None) -> Optional[float]:
    """Seconds since RIVER measured it — from `t_ms`, never from when this
    process happened to receive it. Staleness is detected from the
    timestamp; it is never inferred from whether a request worked."""
    if reading is None:
        return None
    now = now_ms if now_ms is not None else time.time() * 1000.0
    return max(0.0, (now - reading.t_ms) / 1000.0)


def ladder_state(reading: Optional[Reading], st: Any,
                 now_ms: Optional[float] = None) -> str:
    if not base_url(st):
        return STATE_UNCONFIGURED
    if reading is None:
        return STATE_MISSING
    period = float(st.known_buffer_update_period_s)
    age = age_s(reading, now_ms) or 0.0
    if age <= period:
        return STATE_FRESH
    if age <= period * float(st.known_buffer_stale_periods):
        return STATE_STALE
    return STATE_MISSING


def effective_value_ms(reading: Optional[Reading], st: Any) -> int:
    """The value SPECTRA stands behind right now, in ms.

    A published value is never applied BELOW the floor: the floor is his
    headroom, so a smaller published number holds at the floor and is
    flagged `below_floor`. It is never clamped at the CEILING — a variable
    buffer tracked accurately is allowed to pass it (the bounding is
    River's separate half); going over is flagged and surfaced."""
    floor = int(st.known_buffer_floor_ms)
    if reading is None:
        # ZERO IS FORBIDDEN, AND SO IS EVERY SYNONYM FOR IT. Zero asserts
        # his speakers are in sync with the source — the one thing known
        # to be false — so the missing case falls back to THE FLOOR.
        # "Uncorrected" and "no correction" are the SAME forbidden thing:
        # there is deliberately no branch here that returns nothing, skips
        # the value, or leaves the caller to decide.
        return floor
    return max(floor, int(reading.effects_fire_later_by_ms))


def flags(reading: Optional[Reading], st: Any) -> list[str]:
    out: list[str] = []
    if reading is None:
        return out
    if int(reading.effects_fire_later_by_ms) < int(st.known_buffer_floor_ms):
        out.append("below_floor")
    if int(reading.effects_fire_later_by_ms) > int(st.known_buffer_ceiling_ms):
        out.append("above_ceiling")
    if reading.floor_clamped:
        out.append("river_floor_clamped")
    if reading.discontinuity:
        out.append("discontinuity")
    if reading.stale:
        out.append("river_stale")
    return out


# ── the state block ─────────────────────────────────────────────────────
def _sentence(state: str, value_ms: int, reading: Optional[Reading],
              age: Optional[float], st: Any, gate: str) -> str:
    """One plain sentence for a human. Never a bare number he has to
    interpret, and never a claim the ladder does not support."""
    if state == STATE_UNCONFIGURED:
        return ("River's buffer reader is not configured, so effects fire "
                f"against the {int(st.known_buffer_floor_ms)} ms floor.")
    if state == STATE_MISSING:
        heard = ("nothing has been heard from River since this process started"
                 if reading is None else
                 f"the last reading is {age:.0f} s old, past the hold window")
        return (f"Sound behind: falling back to the {int(st.known_buffer_floor_ms)} ms "
                f"floor — {heard}.")
    held = f", held for {age:.0f} s" if state == STATE_STALE and age is not None else ""
    lead = (f"Sound is running {value_ms} ms behind{held}")
    if gate:
        return lead + f" — nothing is applied yet: {gate}."
    return lead + ", and effects fire that much later."


def state() -> dict:
    """THE STATE BLOCK — the one shape, returned by
    `GET /api/timing/effects-fire-later` and folded into
    `GET /api/engine/status` as `known_buffer`."""
    st = _settings()
    reading = _reading
    lad = ladder_state(reading, st)
    age = age_s(reading)
    # A MISSING ladder state means the held value has aged out: the value
    # applied is the floor, and the reading itself is reported as history
    # (published_ms/at stay populated so "we did hear this once, and when"
    # is answerable) rather than being erased.
    applied = effective_value_ms(reading if lad in (STATE_FRESH, STATE_STALE) else None, st)
    gate_open = bool(reading is not None and lad in (STATE_FRESH, STATE_STALE)
                     and reading.gate_open())
    gate = APPLY_GATE_OPEN if gate_open else APPLY_GATE_WAITING
    compensation = 0
    if gate_open and _reference_ms is not None:
        compensation = applied - int(_reference_ms)
    return {
        # THE NAME IS THE INSTRUCTION — this key is River's field name
        # verbatim, and carries the value SPECTRA actually stands behind.
        "effects_fire_later_by_ms": applied,
        "published_ms": None if reading is None else int(reading.effects_fire_later_by_ms),
        "at": None if reading is None else int(reading.t_ms),
        "age_s": None if age is None else round(age, 1),
        "state": lad,
        "source": "" if reading is None else reading.source,
        "via": "" if reading is None else reading.via,
        "floor_ms": int(st.known_buffer_floor_ms),
        "ceiling_ms": int(st.known_buffer_ceiling_ms),
        "update_period_s": float(st.known_buffer_update_period_s),
        "stale_periods": float(st.known_buffer_stale_periods),
        "flags": flags(reading, st),
        "reference_ms": None if _reference_ms is None else int(_reference_ms),
        "compensation_ms": compensation,
        "apply_gate": gate,
        "applied": gate_open,
        "sentence": _sentence(lad, applied, reading, age, st, gate),
        "url": base_url(st),
        # RIVER'S OWN VIEW, beside ours and never collapsed into it: ours
        # says whether SPECTRA is still hearing from River, River's says
        # whether River is still measuring. They can disagree, and when
        # they do that difference is the information.
        "river": ({
            "source": reading.source,
            "stale": reading.stale,
            "age_ms": reading.age_ms,
            "held_age_ms": reading.held_age_ms,
            "epoch": reading.epoch,
            "discontinuity": reading.discontinuity,
            "step_cause": reading.step_cause,
            "floor_clamped": reading.floor_clamped,
            "governed": reading.governed,
            "parec_buffer_ms": reading.parec_buffer_ms,
            "flowing": reading.flowing,
            "update_period_ms": reading.update_period_ms,
            "hold_limit_ms": reading.hold_limit_ms,
            "floor_ms": reading.floor_ms,
        } if reading is not None else None),
        "readings_seen": _readings_seen,
        "sse_connected": _sse_connected,
        "poll_failures": _poll_failures,
        "last_error": _last_error,
    }


# ── the raw series ──────────────────────────────────────────────────────
def _log(reading: Reading) -> None:
    """Append the reading to the drift log and prune to LOG_RETENTION_S.

    Best effort by construction: a log that cannot be written must never
    cost us a reading. Pruning is a rewrite, so it only happens when
    something is actually old enough to drop."""
    path = scfg.KNOWN_BUFFER_LOG_FILE
    line = json.dumps({
        "t_ms": reading.t_ms,
        "received_ms": reading.received_ms,
        "effects_fire_later_by_ms": reading.effects_fire_later_by_ms,
        "parec_buffer_ms": reading.parec_buffer_ms,
        "source": reading.source,
        "epoch": reading.epoch,
        "floor_clamped": reading.floor_clamped,
        "governed": reading.governed,
        "flowing": reading.flowing,
        "via": reading.via,
    }, separators=(",", ":"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        _prune(path)
    except Exception:
        logger.debug("known buffer: could not append to the raw series",
                     exc_info=True)


def _prune(path) -> None:
    cutoff = (time.time() - LOG_RETENTION_S) * 1000.0
    try:
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except Exception:
        return
    keep = []
    dropped = False
    for line in lines:
        try:
            if float(json.loads(line).get("t_ms") or 0) < cutoff:
                dropped = True
                continue
        except Exception:
            # An unparseable line is kept, not silently deleted — this is
            # a record, and a reader that cannot read one line should not
            # cause it to disappear.
            pass
        keep.append(line)
    if not dropped:
        return
    tmp = str(path) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.writelines(keep)
        os.replace(tmp, path)
    except Exception:
        logger.debug("known buffer: prune failed", exc_info=True)


def read_log(limit: int = 500) -> list[dict]:
    """The tail of the raw series, oldest first — the drift picture."""
    path = scfg.KNOWN_BUFFER_LOG_FILE
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except Exception:
        return []
    out: list[dict] = []
    for line in lines[-int(limit):]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


# ── the two feeds ───────────────────────────────────────────────────────
# Both call record(). Neither owns the state; neither can disagree with the
# other about what "the current reading" is.
async def poll_once(client_factory: Optional[Callable[[], Any]] = None) -> Optional[Reading]:
    """One GET of River's /offset — the SLOW RAMP's backstop.

    A failed or malformed poll RECORDS NOTHING: the ladder ages the last
    good reading, which is the honest outcome (we did not hear a new
    number) and is why staleness is measured from River's timestamp rather
    than from whether this call worked."""
    global _last_error, _poll_failures
    url = base_url()
    if not url:
        return None
    try:
        import httpx
        factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=httpx.Timeout(POLL_TIMEOUT_S)))
        async with factory() as client:
            resp = await client.get(url + "/offset")
            resp.raise_for_status()
            payload = resp.json()
        return record(payload, via="poll")
    except Exception as exc:
        _poll_failures += 1
        _last_error = f"poll: {type(exc).__name__}: {exc}"[:200]
        logger.debug("known buffer: poll failed: %s", _last_error)
        return None


async def run_poll_supervised(client_factory: Optional[Callable[[], Any]] = None,
                              iterations: Optional[int] = None) -> None:
    """The ramp backstop, on his own `known_buffer_update_period_s`. Read
    fresh each lap so retuning the period does not need a restart. Never
    raises — a poll loop that dies takes the drift picture with it."""
    count = 0
    while iterations is None or count < iterations:
        count += 1
        period = 15.0
        try:
            st = _settings()
            period = max(1.0, float(st.known_buffer_update_period_s))
            if base_url(st):
                await poll_once(client_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("known buffer: poll loop iteration failed")
        if iterations is not None and count >= iterations:
            return
        await asyncio.sleep(period)


def _sse_events(chunk: str, carry: str) -> tuple[list[str], str]:
    """Split an SSE byte-stream fragment into complete events, returning
    the leftover. Pure, so the framing is testable without a socket."""
    buf = carry + chunk
    parts = buf.split("\n\n")
    return parts[:-1], parts[-1]


def _sse_data(event_text: str) -> Optional[str]:
    """The `data:` payload of one SSE event, joined across continuation
    lines per the spec. Comments (`:` keepalives) and every other field are
    ignored — River's stream is the only thing we parse, and it is JSON."""
    lines = [ln for ln in event_text.replace("\r\n", "\n").split("\n")]
    data: list[str] = []
    for line in lines:
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
    return "\n".join(data) if data else None


async def run_sse_supervised(client_factory: Optional[Callable[[], Any]] = None,
                             connects: Optional[int] = None) -> None:
    """THE STEP PATH — one subscriber on River's /events for as long as
    this process lives.

    River sends the CURRENT VALUE on connect and then one event per STEP,
    so a reconnect re-syncs by itself and there is nothing to replay. A
    step carrying a new epoch is applied AT ONCE by record(); nothing here
    smooths, averages or ramps toward it.

    Reconnects with bounded backoff. Never raises: this loop failing must
    degrade to the poll, never take the process with it."""
    global _sse_connected, _last_error
    backoff = SSE_BACKOFF_MIN_S
    attempts = 0
    while connects is None or attempts < connects:
        attempts += 1
        url = base_url()
        if not url:
            # Unconfigured is not an error and is not retried tightly.
            await asyncio.sleep(SSE_BACKOFF_MAX_S)
            continue
        try:
            import httpx
            factory = client_factory or (
                lambda: httpx.AsyncClient(timeout=httpx.Timeout(
                    connect=POLL_TIMEOUT_S, read=None, write=POLL_TIMEOUT_S,
                    pool=POLL_TIMEOUT_S)))
            async with factory() as client:
                async with client.stream("GET", url + "/events",
                                         headers={"Accept": "text/event-stream"}) as resp:
                    resp.raise_for_status()
                    _sse_connected = True
                    backoff = SSE_BACKOFF_MIN_S
                    carry = ""
                    async for chunk in resp.aiter_text():
                        events, carry = _sse_events(chunk, carry)
                        for event in events:
                            data = _sse_data(event)
                            if not data:
                                continue
                            try:
                                record(json.loads(data), via="events")
                            except Exception as exc:
                                # A malformed event records nothing and
                                # never drops the subscription.
                                logger.debug("known buffer: bad SSE event: %s", exc)
        except asyncio.CancelledError:
            _sse_connected = False
            raise
        except Exception as exc:
            _last_error = f"events: {type(exc).__name__}: {exc}"[:200]
            logger.debug("known buffer: SSE stream ended: %s", _last_error)
        _sse_connected = False
        if connects is not None and attempts >= connects:
            return
        await asyncio.sleep(backoff)
        backoff = min(SSE_BACKOFF_MAX_S, backoff * 2)
