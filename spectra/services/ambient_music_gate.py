"""Ambient's mode precedence gate — three settings, in the Admiral's own
language (2026-08-15 ruling, refined the same day after his first "music
wins always" framing turned out to be wrong):

  "off"    Ambient never holds. The whole room performs, Hue included.
  "always" Hue is held lit at ambient_color UNCONDITIONALLY — music playing
           or not. His own words: "Ambient mode should run even while the
           music is playing so that my Hue Lights are lit and bright but
           the other lights are still running the show." This is NOT the
           precedence bug re-introduced — it's a mode he explicitly wants,
           proven live 2026-08-14/15 to leave every non-Hue device
           untouched (services/ambient.py's device filter is Hue-only,
           architecturally; also grep-confirmed zero references to ambient
           state anywhere in selection_kernel.py/scene_sequencer.py/
           trigger_engine.py — Hue holding can never double-penalise or
           starve the show elsewhere, because nothing in scene selection
           or rendering even knows Ambient exists).
  "auto"   The 2026-08-15 music-precedence fix: holds only when playback is
           CONFIRMED not-playing, releases the instant it's confirmed
           playing, carries an unresolved read forward rather than
           guessing either way. Proven live the same day: hold engaging on
           a genuine pause (17/17 lights confirmed at the exact target
           colour), and release GLIDING back — a two-phase ease across
           colour and brightness, ~16s wall-clock, never a snap — when he
           resumed. THAT MEASURED SHAPE IS NOW THE REGRESSION BASELINE:
           any future change to this module must re-prove the glide
           survives, not assume it does.

The earlier, narrower framing this module shipped under first ("music
always wins") is superseded by the three-setting model above, not deleted
— "auto" is exactly that original fix, kept as one of the three choices
rather than the only one.

RoomControlState.ambient_mode is the STANDING PREFERENCE and this module
never flips it. What this module owns is the LIVE PHYSICAL hold, which
tracks a second, independent signal — bridge.is_playing() — used only by
"auto"; "off" and "always" never consult it at all.

Which COLOUR is held is a THIRD, orthogonal input (2026-08-15, his second
ambient-colour ruling): room_controls.effective_ambient_color() resolves
ambient_color_dark vs. ambient_color from dark_mode_enabled, and every write
(_apply, via reconcile()/reconcile_now()), every read-back (verify_now()'s
own verify_held call), AND verify_now()'s straggler REPAIR write
(services.ambient.repair_stragglers, 2026-08-16) below goes through that
one resolver rather than reading ambient_color directly — so a stale
hard-coded reference here can never verify OR repair against the wrong
target colour while dark mode is on (a straggler repaired back to the
normal colour while a distinct dark colour is actually held would be a
self-inflicted "unlit" on the very next tick). dark_mode_enabled flipping
while already held reaches this module exactly like a plain colour edit
does: room_controls.reconcile_ambient_if_changed diffs the RESOLVED colour,
so a dark toggle that changes what's effectively held triggers the same
reconcile_now() -> reconcile() -> _apply() path as picking a new colour by
hand, which is what gives the swap its ease (see _apply()'s own "colour
changed while holding" branch — the identical mechanism, no separate
transition code was added for this). Every caller that can
change either input funnels through reconcile()/reconcile_now() rather
than calling services.ambient.reconcile() directly, so mode precedence can
never be bypassed by one path (a human PUT, a bridge broadcast, process
startup/resume) reaching the Hue write seam on its own:
  - spectra/services/engine.py's _on_track_uri — every bridge "state"
    broadcast (several times a minute), the primary trigger for "auto".
  - spectra/services/room_controls.py's reconcile_ambient_if_changed — a
    human PUT /api/room-controls save (covers "always" too — flipping the
    setting to "always" holds immediately regardless of what's playing).
  - spectra/app.py's _standalone_lifespan — process startup/resume.
This module never talks to a Hue bridge itself — every actual write still
goes through services.ambient.reconcile(), the exact function a human
toggling the room-bar control always drove — so Ambient's release/
ease-back fidelity (the thing the Admiral explicitly praised, "way
better") is untouched BY CONSTRUCTION, not merely re-tested.

Fail-safe direction for "auto", on purpose, and NOT symmetric with
"confirmed playing": an UNKNOWN playback read (is_playing() returns None —
bridge.py docstring: only when no signal has EVER arrived) never ACTIVELY
changes the live hold either way — _desired_hold() returns whatever is
already held. Collapsing "unknown" onto "confirmed playing" (both ->
release) was an earlier, tempting shortcut, and it's wrong: it would make
a transient bridge blip actively RELEASE an already-quiet, already-held
room — a flicker regression against the ease-back-must-survive-unharmed
bar this fix is judged against, for a case (bridge hiccup) that has
nothing to do with music actually starting. The only asymmetry left is at
the OTHER edge, first engagement: a room that has never yet been confirmed
quiet starts unheld (module-load default), so "unknown" there means "stay
unheld," not "start holding blind." That bounds the cost to a narrow
window at process start/resume, before the first bridge broadcast
arrives, where "auto" briefly does not hold a truly quiet room even
though the setting says so — one bridge message wide, and VISIBLE
(status() below) rather than silently wrong the other way. Switching the
setting to "off" is the one thing that always wins regardless of any
playback reading, confirmed or not. A track loaded but genuinely not
playing (paused, or nothing loaded at all) reads as "not playing" —
bridge.is_playing() docstring — so a deliberate pause also lets "auto"
resume, matching "when music ends" read literally.

Visibility (the fix's other half, the Admiral's own words: "a control that
reads as ON while doing nothing is the exact pattern this project has
spent the week killing"): status() reports which of five MODES is
currently true — "off" (setting is "off"), "holding" (every claimed light
CONFIRMED lit at ambient_color right now — true throughout "always", and
only when confirmed quiet under "auto"), "partial" (Ambient believes it
should be holding but the last check found at least one light not lit —
see "Status honesty" below), "yielding" (setting isn't "off", but standing
aside for music or an unresolved playback read — only reachable under
"auto"), or "transitioning" (a hold/release is physically in flight) —
folded into GET /api/engine/status's own "ambient" key so the existing 3s
room-bar/top-bar poll (spectra/web/src/queries.ts useEngineStatus) shows it
live with no new endpoint. reconcile()/reconcile_now() themselves keep
returning services.ambient.reconcile()'s own {"status": ...} shape (or an
honest "on"/"off"/"yielding" synthesized when nothing needed to change) —
the SAME shape spectra/api/room_controls.py's PUT response and
RoomControlsBar.tsx's ambient_result badge already expect — status() is
the separate, always-current surface for the room-bar's live indicator.

Status honesty (found live 2026-08-15, overnight, THE defect this section
exists to prevent): status() used to report `_held` — a bare "did the last
write succeed" flag — forever, with no re-check. Under "always" mode
_apply()'s own short-circuit (below) means a genuinely held room never
gets written to again once desired stops changing, so nothing ever
re-verified it either; his room sat reporting `held: true,
lights_set: 17/17` all night while he'd switched every bulb off before
bed. Two independent things now feed a SEPARATE `_verified_ok` flag,
kept apart from `_held` (the write-intent bookkeeping `_apply()`'s
short-circuit still needs) precisely so the PUBLIC `held` in status() can
be gated on it: (1) a real write's own read-back (services.ambient's
`_hold_and_confirm`) — immediate, since a write already proves the moment
it lands; (2) `verify_now()`'s independent periodic recheck (`run_
supervised()`, VERIFY_TICK_S cadence, started alongside frame_watchdog/
ownership_reconciler in app.py's lifespan) — a GET-only bridge read-back
(services.ambient.verify_held(), NEVER a write) that runs regardless of
whether anything else has changed, so a claimed hold can't go stale for
longer than that cadence. `held` in status() is `_held AND _verified_ok is
not False` — a light found not-lit (or the live stack no longer even
owning the room) downgrades `_verified_ok` to False, which flips the
PUBLIC `held` false and `mode` to "partial" immediately, even though the
internal `_held` write-intent flag (and therefore the "don't re-fire an
identical write" short-circuit) is untouched. status() also reports
`verified_age_s` (seconds since whichever check — write or periodic — most
recently ran) and the raw `verify` result whenever there's one to show, so
a caller can always tell "confirmed 4s ago" from "confirmed 20 minutes
ago" rather than treating every `result` as equally live.

verify_now() used to be read-only end to end — the GET-only recheck ran,
but a light it found broken was only ever named, never fixed (2026-08-15
live incident: two bulbs sat wrong for hours through repeated verify
cycles that correctly named them every time and repaired neither —
"detects but does not repair" is only marginally better than not
noticing). 2026-08-16: an off-target light now gets one paced,
read-back-confirmed repair attempt (services.ambient.repair_stragglers())
before this reports "partial". The one thing that stayed deliberately
NOT built: repair_stragglers() never re-lights a light that reads OFF
right now — a bulb he turned off himself must stay off; this module
reports reality, it does not fight him for control of it (services/
ambient.py's own module docstring frames the analogous choice on the
release path) — the "never fight him" rule survives, narrowed to the one
case it was ever actually about.

Concurrency: _apply_lock serialises this module's own decisions (a burst
of bridge broadcasts must not fire a burst of redundant Hue reconciles);
services.ambient.reconcile()'s own lock still serialises the underlying
Hue I/O regardless of how many callers overlap. reconcile() only ever
AWAITS the full reconcile and returns its honest final result — it never
backgrounds anything itself. A caller on a hot path that must not block
for the several seconds a hold/release can take (engine.py's
_on_track_uri, called on every bridge broadcast) wraps the call in
asyncio.create_task instead of awaiting it inline; a caller where blocking
is expected and desired (a PUT response, startup) awaits it directly.
verify_now() checks the SAME lock (non-blocking — `lock.locked()`, never
`async with`) and skips its tick entirely while a write is in flight,
rather than reading bridge state mid-change: the write's own read-back is
already a fresher, more authoritative check than anything a concurrent GET
could add, and blocking on the lock instead would make every "transitioning"
badge include the periodic verifier's own GET round-trip as if it were part
of the hold/release itself.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from spectra.services import ambient
from spectra.services.room_controls import AmbientMode, effective_ambient_color, load_room_controls

logger = logging.getLogger(__name__)

VERIFY_TICK_S = 30.0   # matches frame_watchdog / ownership_reconciler cadence
                       # — GET-only, cheap; see "Status honesty" above for why
                       # this needs its own independent clock at all.

_held = False
_held_color: Optional[str] = None
_last_result: dict = {}
_apply_lock: Optional[asyncio.Lock] = None

# Status-honesty bookkeeping (module docstring). Kept apart from _held/
# _held_color above: those are write-INTENT (what _apply()'s short-circuit
# compares "desired" against), these are the most recent CONFIRMATION of
# physical reality, from either a write's own read-back or an independent
# periodic verify — never advanced by a short-circuited no-op reconcile.
_verified_ok: Optional[bool] = None
_last_verified_ms: Optional[float] = None
_last_verify: dict = {}


def _get_apply_lock() -> asyncio.Lock:
    global _apply_lock
    if _apply_lock is None:
        _apply_lock = asyncio.Lock()
    return _apply_lock


def _desired_hold(ambient_mode: AmbientMode, is_playing: Optional[bool],
                  currently_held: bool) -> bool:
    """The full precedence rule, one branch per setting.

    "off" always releases, regardless of playback. "always" always holds,
    regardless of playback — his own requested mode, not a bypass of
    anything. "auto" is the music-precedence rule: a CONFIRMED read
    (True/False) always wins even over an existing hold — that's the whole
    point: music starting releases an already-held room, music stopping
    re-engages one that wasn't held. An UNKNOWN read (None) never actively
    changes anything under "auto" — it returns whatever is already held,
    so a bridge blip can neither release an already-quiet hold nor
    spuriously start one (see module docstring)."""
    if ambient_mode == "off":
        return False
    if ambient_mode == "always":
        return True
    # "auto"
    if is_playing is None:
        return currently_held
    return is_playing is False


async def reconcile(is_playing: Optional[bool]) -> dict:
    """The core decision point — reconcile the live hold against the
    room's CURRENT ambient_mode/_color preference and the given playback
    read (playback only matters for "auto"). Always resolves synchronously
    to the honest final result (services.ambient.reconcile()'s own
    read-back retries can take several seconds) — see module docstring for
    who should await this inline vs. background it. Returns the same
    {"status": ...} shape services.ambient.reconcile() returns when it
    actually acts; when nothing needed to change it synthesizes an equally
    honest "on" / "off" / "yielding" rather than replaying a stale prior
    result."""
    controls = load_room_controls()
    desired = _desired_hold(controls.ambient_mode, is_playing, _held)
    return await _apply(controls.ambient_mode, desired, effective_ambient_color(controls))


async def reconcile_now() -> dict:
    """Convenience wrapper for callers with no playback read of their
    own — a human PUT save (room_controls.reconcile_ambient_if_changed) or
    process startup/resume (app.py) — reads the live bridge singleton's
    current is_playing() itself. Deferred import: spectra.services.engine
    imports this module (for status(), folded into engine.status()), so a
    module-level import here would cycle."""
    from spectra.services.engine import bridge
    return await reconcile(bridge.is_playing())


def _record_verify(status_: str, lights_lit: int = 0, lights_total: int = 0,
                   unlit: Optional[list] = None) -> None:
    """Stamp a fresh confirmation — from either a real write's own
    read-back or the independent periodic verifier — into the SAME pair of
    fields, so status() has one place to read "how stale is what we know"
    regardless of which path last confirmed it (module docstring, "Status
    honesty")."""
    global _verified_ok, _last_verified_ms, _last_verify
    _last_verified_ms = time.monotonic()
    if status_ == "verified":
        _last_verify = {"status": "verified", "lights_lit": lights_lit,
                        "lights_total": lights_total, "unlit": sorted(unlit or [])}
        _verified_ok = not unlit
    else:
        # "dark" / "no-hue-devices" — nothing physically held, whatever
        # _held still says.
        _last_verify = {"status": status_}
        _verified_ok = False


def _clear_verify() -> None:
    global _verified_ok, _last_verified_ms, _last_verify
    _verified_ok = None
    _last_verified_ms = None
    _last_verify = {}


async def _apply(ambient_mode: AmbientMode, desired: bool, color: Optional[str]) -> dict:
    global _held, _held_color, _last_result
    async with _get_apply_lock():
        # Re-check after acquiring the lock: a caller queued behind an
        # in-flight reconcile may already have what it wants once its turn
        # comes, and must not re-fire an identical Hue write.
        if desired != _held or (desired and color != _held_color):
            _last_result = await ambient.reconcile(desired, color)
            status_ = _last_result.get("status")
            if status_ != "failed":
                _held = desired
                _held_color = color if desired else None
            if desired and status_ in ("on", "partial"):
                # A write's own read-back (services.ambient's
                # _hold_and_confirm) IS a fresh confirmation — feed it into
                # the same status-honesty bookkeeping verify_now() uses,
                # rather than waiting up to VERIFY_TICK_S for the periodic
                # check to say what this call already knows.
                _record_verify("verified", _last_result.get("lights_set", 0),
                               _last_result.get("lights_total", 0),
                               _last_result.get("unconfirmed"))
            elif desired and status_ in ("dark", "no-hue-devices"):
                # _held above is still set True (the room-control save must
                # never fail just because there's nothing to drive right
                # now — services/ambient.py's own docstring) — but nothing
                # was actually touched, so the PUBLIC `held` in status()
                # must not read true just because the intent was recorded.
                # Same defect family as the overnight one, caught here at
                # write time rather than waiting for the periodic verifier.
                _record_verify(status_)
            elif not desired:
                _clear_verify()
            return _last_result
    if desired:
        return {"status": "on"}
    return {"status": "off"} if ambient_mode == "off" else {"status": "yielding"}


async def verify_now() -> dict:
    """The independent periodic recheck (module docstring, "Status
    honesty"). Skips entirely when nothing is currently claimed held
    (nothing to check) or a write is already in flight (its own read-back
    is fresher than anything this could add — see the concurrency note in
    the module docstring). The GET-only recheck itself is unconditional
    (services.ambient.verify_held's own docstring); what follows is NOT —
    a light it finds off-target gets one paced, read-back-confirmed REPAIR
    attempt (services.ambient.repair_stragglers, 2026-08-16) before this
    reports "partial", the fix for the live defect this module's docstring
    used to describe as deliberate: two bulbs sat wrong for hours while
    verify_now() named them correctly on every tick and repaired neither —
    "detects but does not repair" is only marginally better than not
    noticing. repair_stragglers() itself still never touches a light that
    reads OFF right now (checked fresh, immediately before writing) — a
    bulb he turned off himself stays off; only an ON-but-wrong-colour
    straggler (the burst-drop/drift shape) gets rewritten, so "reports
    reality, does not fight him for control" still holds for the one case
    it was ever meant to protect. A confirmed miss that repair could not
    fully clear downgrades `_verified_ok` (status()'s `held`/`mode` react
    immediately) but never touches `_held` itself — the write-intent
    short-circuit above is untouched, so a colour/mode change still
    re-applies exactly as before."""
    if not _held:
        return {}
    lock = _get_apply_lock()
    if lock.locked():
        return {}
    controls = load_room_controls()
    target_color = effective_ambient_color(controls)
    result = await ambient.verify_held(target_color)
    status_ = result.get("status")
    if status_ == "verified":
        unlit = result.get("unlit") or []
        lights_lit = result.get("lights_lit", 0)
        if unlit:
            repair = await ambient.repair_stragglers(unlit, target_color)
            result["repair"] = repair
            if repair["repaired"]:
                lights_lit += len(repair["repaired"])
                logger.warning(
                    "Ambient: repaired %d straggler(s) the periodic verifier "
                    "found off-target: %s", len(repair["repaired"]), repair["repaired"])
            unlit = sorted(set(unlit) - set(repair["repaired"]))
        _record_verify("verified", lights_lit, result.get("lights_total", 0), unlit)
        if unlit:
            logger.error(
                "Ambient: verification found %d/%d light(s) no longer at "
                "the ambient colour — status will report the hold as "
                "partial, not holding: %s",
                result.get("lights_total", 0) - len(unlit),
                result.get("lights_total", 0), unlit)
    else:
        # "dark" (SPECTRA no longer owns the live stack) or
        # "no-hue-devices" — there is nothing left to be holding, whatever
        # the stale _held flag still says.
        logger.warning(
            "Ambient: verification found nothing to hold (%s) — status "
            "will stop reporting the room as held", status_)
        _record_verify(status_)
    return result


async def run_supervised() -> None:
    """Own asyncio task (started alongside frame_watchdog/
    ownership_reconciler in app.py's lifespan) — same discipline as those:
    a crashing tick is logged and retried, never lets a claimed hold go
    unchecked forever just because one tick errored."""
    while True:
        try:
            await verify_now()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Ambient verifier tick crashed (retrying): %r", exc)
        await asyncio.sleep(VERIFY_TICK_S)


def status() -> dict:
    """The room-bar's honest, always-live read of what Ambient is
    ACTUALLY doing right now — not just what the setting says, and not
    just what the last WRITE said (module docstring, "Status honesty").
    Folded into GET /api/engine/status by services/engine.py. `held` is
    gated on the most recent confirmation (write read-back or periodic
    verify), not the bare write-intent flag, so it can never keep reading
    true for a light that's actually off."""
    controls = load_room_controls()
    setting = controls.ambient_mode
    lock = _apply_lock
    confirmed_held = _held and _verified_ok is not False
    if setting == "off":
        mode = "off"
    elif lock is not None and lock.locked():
        mode = "transitioning"
    elif _held and _verified_ok is False:
        mode = "partial"
    elif confirmed_held:
        mode = "holding"
    else:
        mode = "yielding"
    out = {"setting": setting, "mode": mode, "held": confirmed_held}
    if _last_result:
        out["result"] = _last_result
    if _last_verified_ms is not None:
        out["verified_age_s"] = round(time.monotonic() - _last_verified_ms, 1)
        out["verify"] = _last_verify
    return out
