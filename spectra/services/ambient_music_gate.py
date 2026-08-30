"""Ambient's transition owner and its intent/phase contract.

THE TOGGLE IS BINARY (2026-08-30, his ruling: "let's only ever toggle
between Off and On"). This module used to carry a three-setting mode
surface ("off"/"always"/"auto"); that is retired. Two plain switches on
RoomControlState replace it:

  ambient_enabled         On means the room's Hue devices are held lit at
                          the ambient colour, music playing or not (what
                          "always" meant). Off means they are not.
  ambient_on_music_pause  The retired "auto" BEHAVIOUR, preserved in code
                          and gated behind its own switch rather than
                          deleted: while Ambient is off, a CONFIRMED
                          not-playing read turns the hold on and a
                          confirmed playing read releases it. SHIPS FALSE
                          on every migration by his explicit word ("set it
                          to false for now"), so nothing automatic happens
                          on deploy.

Every non-Hue device is architecturally untouched by Ambient under either
switch (services/ambient.py's device filter is Hue-only, and grep confirms
zero references to ambient state anywhere in selection_kernel.py/
scene_sequencer.py/trigger_engine.py) — holding Hue can never starve the
show elsewhere.

═══ WHAT HE ACTUALLY REPORTED, AND WHAT THIS MODULE NOW DOES ABOUT IT ═══

His words: "The main issue is when I turn on ambient in a room, there is a
lag between when i turn it on and when it finishes, so I don't know if it
has started or not, and I keep accidentally toggling it multiple times...
give the butt[on]s in HA and in spectra some clarity that they are
'turning on' or 'Turning off' ... Interrupting should snap the state. So if
is gradually turning ambient off, and I turn it back on, it should just
snap to being full brightness."

Measured live on his room before the rework — design against these, they
are not re-derived here: turn-OFF 22.6s end to end (services/ambient.py's
deliberate two-phase fade, AMBIENT_TRANSITION_MS dim + AMBIENT_CATCHUP_MS
catch-up, plus 300ms-staggered confirmed writes); turn-ON ~15s across his
17 bulbs; and a press MID-transition took 38s to win, because it queued
behind services.ambient's own I/O lock with nothing able to interrupt the
sequence already inside it. Three things follow, and all three are the
point of this module:

1. THE PHASE CONTRACT — a FROZEN interface (another captain builds Home
   Assistant against these exact names and values; do not rename or extend
   the value sets without going back to him). status() below publishes it
   on GET /api/engine/status's `ambient` key and pushes the identical
   payload over the SPECTRA websocket as {"type": "ambient_status", ...}:

     intent  "on" | "off"
             Where the room is being driven RIGHT NOW — the toggle as
             resolved through ambient_on_music_pause, not the raw stored
             bool. While a transition is in flight it is that transition's
             own end state, so intent and phase never disagree about which
             way the room is moving.
     phase   "on" | "off" | "turning_on" | "turning_off" | "unavailable"
             "unavailable" means the room is released or owned by
             spot-effects, so a press cannot act on lights at all (the
             intent is still stored and still applies on the next take-back
             — see "THE RELEASED ROOM" below). Otherwise "turning_on"/
             "turning_off" while a transition task is running, and "on"/
             "off" for a settled room.

   phase must update within 1s of any change, which a 3s status poll alone
   cannot promise — so every transition START, END and CANCEL pushes the
   broadcast itself (_broadcast_status). The poll stays as the backstop, it
   is no longer the mechanism.

   phase deliberately reports the TRANSITION's outcome, not the bulbs':
   a hold that landed and was later broken out of band (he switched a bulb
   off at the wall) still reads phase "on" — Ambient is on, the room is
   wrong — and the pre-existing `held`/`mode`/`verify`/`verified_age_s`
   keys below carry that honesty exactly as before. Collapsing the two
   would make "is Ambient on" unanswerable.

2. INTERRUPTION SNAPS — at most ONE transition task exists at a time
   (_transition), stamped with a generation counter. A new intent CANCELS
   the in-flight one at its next safe write boundary (never mid-write to
   one bulb — services/ambient.py's CancelToken owns where those boundaries
   are) and applies the new end state with every RAMP dropped: no colour
   glide on a hold, no dim fade and no catch-up on a release, just the
   staggered confirmed writes, because the stagger is zigbee physics and
   the ramps are choreography he has stopped watching. The queue is
   abolished — a superseded task's remaining writes are abandoned, it never
   writes again, and it never touches the bookkeeping below (every write is
   guarded on `_transition is tr`). His example holds literally: interrupt
   a gradual turn-off with ON and the bulbs go to full ambient brightness
   as fast as the confirmed writes can land — bounded by bulb count, not by
   the 22.6s sequence he changed his mind about.

   An UNINTERRUPTED turn-off keeps its two-phase ease in full. His
   complaint was the interruption, not the fade.

3. THE PRESS RETURNS IMMEDIATELY — room_controls.reconcile_ambient_if_changed
   now STARTS the transition and returns (reconcile_now(wait=False)) rather
   than blocking his PUT for the whole sequence. That blocking PUT is where
   "I don't know if it has started" began.

THE RELEASED ROOM: a press while phase is "unavailable" is never a silent
nothing. The intent is durable the moment it is saved (it IS
RoomControlState.ambient_enabled), and it is applied on the next take-back
— spectra/app.py's startup/resume lifespan and, since this rework,
handover.run_handover's own commit when SPECTRA becomes the owner. Both go
through reconcile_now(), so the music-pause switch is honoured there too.

═══ THE PARTS THAT DID NOT CHANGE ═══

WHICH COLOUR is held is orthogonal: room_controls.effective_ambient_color()
resolves ambient_color_dark vs. ambient_color from display_mode == "dark",
and every write, every read-back and the straggler REPAIR write all go
through that one resolver, so a stale reference here can never verify or
repair against the wrong target while dark mode is on. A dark toggle that
changes the effective colour reaches this module exactly like a plain
colour edit does (room_controls.reconcile_ambient_if_changed diffs the
RESOLVED colour), which is what gives the swap its ease. Brightness is
DERIVED from whichever colour is resolved (services.ambient's
`_hsv_value_pct`), not a fourth input.

Fail-safe direction for the music-pause branch, on purpose, and NOT
symmetric with "confirmed playing": an UNKNOWN playback read (is_playing()
returns None — only when no signal has EVER arrived) never ACTIVELY changes
the live hold — _desired_hold returns whatever is already held. Collapsing
"unknown" onto "confirmed playing" (both -> release) would make a transient
bridge blip actively release an already-quiet, already-held room. The only
asymmetry left is at first engagement: a room that has never been confirmed
quiet starts unheld, so "unknown" there means "stay unheld", not "start
holding blind". ambient_enabled=True is unconditional and never consults
playback at all.

Status honesty (found live 2026-08-15, overnight, THE defect this section
exists to prevent): status() used to report `_held` — a bare "did the last
write succeed" flag — forever, with no re-check. Once desired stops
changing, a genuinely held room never gets written to again, so nothing
ever re-verified it either; his room sat reporting `held: true, lights_set:
17/17` all night while he had switched every bulb off before bed. Two
independent things feed a SEPARATE `_verified_ok` flag, kept apart from
`_held` (the write-intent bookkeeping the short-circuit still needs)
precisely so the PUBLIC `held` can be gated on it: (1) a real write's own
read-back (services.ambient's `_hold_and_confirm`); (2) `verify_now()`'s
independent periodic recheck (`run_supervised()`, VERIFY_TICK_S cadence,
started alongside frame_watchdog/ownership_reconciler in app.py's
lifespan) — a GET-only bridge read-back that runs regardless of whether
anything else changed. `held` is `_held AND _verified_ok is not False`.
status() also reports `verified_age_s` so a caller can tell "confirmed 4s
ago" from "confirmed 20 minutes ago" rather than treating every result as
equally live.

verify_now() also REPAIRS (2026-08-16): an off-target light gets one paced,
read-back-confirmed repair attempt (services.ambient.repair_stragglers())
before this reports "partial" — the fix for "detects but does not repair"
(two bulbs sat wrong for hours through repeated correct detections).
repair_stragglers() never re-lights a light that reads OFF right now: a
bulb he turned off himself must stay off; this module reports reality, it
does not fight him for control of it.

Concurrency: `_apply_lock` now guards only the SHORT decision section (is a
transition needed, and cancel-then-start if so) — never the I/O, which is
exactly the queue that made an interrupting press take 38s. The long work
lives in the transition task, and services.ambient's own lock still
serialises the underlying Hue I/O; a superseded sequence releases that lock
on its way out (AmbientCancelled propagates through the `async with`), so
the newer intent waits one write slot rather than one whole sequence.
verify_now() skips its tick entirely while a transition is in flight rather
than reading bridge state mid-change.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from spectra.services import ambient
from spectra.services.room_controls import (RoomControlState, effective_ambient_color,
                                            load_room_controls)

logger = logging.getLogger(__name__)

VERIFY_TICK_S = 30.0   # matches frame_watchdog / ownership_reconciler cadence
                       # — GET-only, cheap; see "Status honesty" above for why
                       # this needs its own independent clock at all.

# The frozen phase vocabulary (see the module docstring's PHASE CONTRACT).
PHASE_ON = "on"
PHASE_OFF = "off"
PHASE_TURNING_ON = "turning_on"
PHASE_TURNING_OFF = "turning_off"
PHASE_UNAVAILABLE = "unavailable"

# What actually landed, most recently, on the bulbs.
_held = False
_held_color: Optional[str] = None
# The RAW selection input (RoomControlState.ambient_hue_group_ids, possibly
# []) — write-INTENT, compared for the short-circuit only. NOT what
# status() reports as "groups": [] here means "every device" (services.
# ambient's own resolution), not "nothing selected", so reporting this raw
# value directly would read as an empty hold under the default selection.
_held_group_ids: frozenset = frozenset()
# The RESOLVED device ids actually held right now — status()'s "groups" is
# this, not _held_group_ids above. Sourced from the reconcile result's own
# "devices" list (services.ambient.reconcile already resolved [] to every
# live Hue device) rather than re-deriving the resolution here.
_held_resolved_groups: frozenset = frozenset()
_last_result: dict = {}
_apply_lock: Optional[asyncio.Lock] = None

# The most recent playback read any reconcile() saw — status() resolves the
# published `intent` through the same _desired_hold the writer used, so the
# two can never disagree about what the music-pause switch currently wants.
_last_is_playing: Optional[bool] = None

# Status-honesty bookkeeping (module docstring). Kept apart from _held/
# _held_color above: those are write-INTENT (what the short-circuit
# compares "desired" against), these are the most recent CONFIRMATION of
# physical reality, from either a write's own read-back or an independent
# periodic verify — never advanced by a short-circuited no-op reconcile.
_verified_ok: Optional[bool] = None
_last_verified_ms: Optional[float] = None
_last_verify: dict = {}


# ── the single transition ───────────────────────────────────────────────────

@dataclass
class _Transition:
    """One in-flight (or just-finished) run toward a target state. At most
    one exists at a time — `_transition`. `generation` is the tie-break the
    bookkeeping guards on: only the CURRENT transition may write `_held` and
    friends, so a superseded run can never land stale state after the newer
    one already has."""
    generation: int
    #  (desired hold, colour, resolved group ids) — the whole end state.
    target: tuple
    token: "ambient.CancelToken"
    # True when this run SUPERSEDED another: every ramp is dropped so the
    # new end state lands as fast as the confirmed writes allow.
    snap: bool
    task: Optional[asyncio.Task] = field(default=None, repr=False)
    result: Optional[dict] = None
    superseded: bool = False
    # Set by _run_transition the moment the room has stopped moving, BEFORE
    # its end broadcast — a task is not `done()` while it is still inside
    # its own body, so without this the END push would still describe the
    # room as "turning_on".
    finished: bool = False

    @property
    def intent(self) -> bool:
        return bool(self.target[0])

    @property
    def in_flight(self) -> bool:
        return not self.finished and (self.task is None or not self.task.done())


_transition: Optional[_Transition] = None
_generation = 0


def _get_apply_lock() -> asyncio.Lock:
    global _apply_lock
    if _apply_lock is None:
        _apply_lock = asyncio.Lock()
    return _apply_lock


def transition_in_flight() -> bool:
    return _transition is not None and _transition.in_flight


def _desired_hold(ambient_enabled: bool, on_music_pause: bool,
                  is_playing: Optional[bool], currently_held: bool) -> bool:
    """The whole rule, in his own two switches.

    Enabled always holds, regardless of playback — that is what the toggle
    means. Off holds nothing UNLESS ambient_on_music_pause is on, in which
    case the retired "auto" rule applies verbatim: a CONFIRMED read
    (True/False) always wins even over an existing hold (music starting
    releases a held room, music stopping re-engages one that wasn't), and an
    UNKNOWN read (None) never actively changes anything — it returns
    whatever is already held, so a bridge blip can neither release an
    already-quiet hold nor spuriously start one (see module docstring)."""
    if ambient_enabled:
        return True
    if not on_music_pause:
        return False
    if is_playing is None:
        return currently_held
    return is_playing is False


def _target_landed(target: tuple) -> bool:
    """Is the room ALREADY in this exact state, as most recently confirmed
    by a real write. The pre-rework short-circuit, unchanged in meaning:
    compared against what LANDED (`_held*`), never against what was merely
    requested, so a failed transition is retried by the next caller rather
    than silently short-circuited forever."""
    desired, color, group_ids = target
    if desired != _held:
        return False
    if not desired:
        return True
    return color == _held_color and group_ids == _held_group_ids


def _current_target(desired: bool, color: Optional[str], group_ids: frozenset) -> tuple:
    # A released room has no colour or group selection to compare — folding
    # them to the empty values keeps "off is off" a single state rather than
    # one per colour he happened to have set when he turned it off.
    return (desired, color if desired else None,
            group_ids if desired else frozenset())


async def _broadcast_status() -> None:
    """Push the phase contract the moment it changes — the module
    docstring's "within 1s" requirement, which the 3s poll cannot promise.
    Best-effort: a websocket fan-out failure must never be able to stop or
    fail a real light transition."""
    try:
        from spectra.services.ws import ws_manager
        await ws_manager.broadcast({"type": "ambient_status", **status()})
    except Exception:
        logger.exception("Ambient: status broadcast failed (the transition "
                         "itself is unaffected)")


def _start_transition(target: tuple) -> _Transition:
    """Cancel whatever is in flight and start the one transition toward
    `target`. Called under `_apply_lock` — the decision is short and never
    does I/O, so an interrupting press is never queued behind one."""
    global _transition, _generation
    prev = _transition
    snap = False
    if prev is not None and prev.in_flight:
        # THE INTERRUPT. Cancelling is cooperative: services.ambient stops
        # at its next write boundary, never mid-write to one bulb.
        prev.token.cancel()
        prev.superseded = True
        snap = True
        logger.warning(
            "Ambient: intent changed mid-%s (generation %d) — cancelling it "
            "and SNAPPING to %s, no ramps",
            "turn-on" if prev.intent else "turn-off", prev.generation,
            "on" if target[0] else "off")
    _generation += 1
    tr = _Transition(generation=_generation, target=target,
                     token=ambient.CancelToken(), snap=snap)
    _transition = tr
    tr.task = asyncio.create_task(
        _run_transition(tr), name=f"ambient-transition-{tr.generation}")
    return tr


async def _run_transition(tr: _Transition) -> None:
    """The whole long sequence, off the caller's thread of control. Never
    raises: every outcome (including being superseded) lands on
    `tr.result`, and only the CURRENT transition is allowed to touch the
    module's landed-state bookkeeping."""
    global _held, _held_color, _held_group_ids, _held_resolved_groups, _last_result
    desired, color, group_ids = tr.target
    # START: the phase is already "turning_on"/"turning_off" by the time
    # this runs (_transition was set before the task was created), so this
    # push carries the real new phase, not a stale one.
    await _broadcast_status()
    try:
        result = await ambient.reconcile(desired, color, group_ids,
                                         token=tr.token, snap=tr.snap)
    except ambient.AmbientCancelled:
        tr.finished = True
        tr.result = {"status": "superseded",
                     "intent": PHASE_ON if desired else PHASE_OFF}
        logger.info("Ambient: transition %d abandoned — a newer intent owns "
                    "the room now", tr.generation)
        # No broadcast: the superseding transition published its own start,
        # which IS the cancel notification (the phase flipped to its own
        # turning_*). Broadcasting here would push a phase this generation
        # no longer owns.
        return
    except Exception as exc:                      # pragma: no cover - defensive
        tr.finished = True
        tr.result = {"status": "failed", "error": repr(exc)}
        logger.exception("Ambient: transition %d crashed", tr.generation)
        if _transition is tr:
            await _broadcast_status()
        return

    tr.finished = True
    if _transition is not tr:
        # Superseded between the last write boundary and here — the newer
        # transition owns the bookkeeping; landing this one's outcome would
        # overwrite it with a state the room is already leaving.
        tr.result = result
        return

    _last_result = result
    status_ = result.get("status")
    if status_ == "dark":
        # The room stopped being ours mid-transition. NOTHING landed, so
        # the target must NOT be recorded as landed — otherwise the
        # short-circuit would swallow the take-back that is supposed to
        # finally apply it (see _apply's own unavailable branch). The
        # confirmation is still stamped, so `held` reads false immediately
        # rather than waiting for the periodic verifier.
        _record_verify("dark")
    else:
        if status_ != "failed":
            _held = desired
            _held_color = color if desired else None
            _held_group_ids = group_ids if desired else frozenset()
            _held_resolved_groups = (
                frozenset(result.get("devices", []))
                if desired and status_ in ("on", "partial") else frozenset())
        if desired and status_ in ("on", "partial"):
            # A write's own read-back (services.ambient's _hold_and_confirm)
            # IS a fresh confirmation — feed it into the same status-honesty
            # bookkeeping verify_now() uses, rather than waiting up to
            # VERIFY_TICK_S for the periodic check to say what this already
            # knows.
            _record_verify("verified", result.get("lights_set", 0),
                           result.get("lights_total", 0), result.get("unconfirmed"))
        elif desired and status_ == "no-hue-devices":
            # _held above is still set True (the room-control save must
            # never fail just because there's nothing to drive right now —
            # services/ambient.py's own docstring) — but nothing was
            # actually touched, so the PUBLIC `held` must not read true just
            # because the intent was recorded.
            _record_verify(status_)
        elif not desired:
            _clear_verify()
    tr.result = result
    # END.
    await _broadcast_status()


async def _await_transition(tr: _Transition) -> dict:
    """_run_transition never raises, so awaiting the task is purely waiting
    for the room to settle; the outcome (including "superseded") is on
    tr.result."""
    if tr.task is not None:
        await tr.task
    return tr.result or {"status": PHASE_ON if tr.intent else PHASE_OFF}


def reset_state() -> None:
    """Test-only: drop every module global back to a fresh-process state.
    This module has no constructor DI seam (same class as fire_history.py),
    so a leaked transition task or a stale `_held` would carry between
    tests — tests/conftest.py's autouse fixture calls this."""
    global _held, _held_color, _held_group_ids, _held_resolved_groups
    global _last_result, _apply_lock, _last_is_playing, _transition, _generation
    if _transition is not None and _transition.in_flight:
        _transition.token.cancel()
        assert _transition.task is not None
        _transition.task.cancel()
    _held = False
    _held_color = None
    _held_group_ids = frozenset()
    _held_resolved_groups = frozenset()
    _last_result = {}
    _apply_lock = None
    _last_is_playing = None
    _transition = None
    _generation = 0
    _clear_verify()


# ── the decision ────────────────────────────────────────────────────────────

async def reconcile(is_playing: Optional[bool], *, wait: bool = True) -> dict:
    """The core decision point — reconcile the live hold against the room's
    CURRENT ambient_enabled/ambient_on_music_pause/colour preference and the
    given playback read (playback only matters while ambient_on_music_pause
    is on).

    `wait=True` (the default, and what every automatic caller uses) resolves
    to the honest final result once the room has finished moving.
    `wait=False` is the human-press path: it starts the transition and
    returns the immediate {"status": "turning_on"/"turning_off", ...} shape
    so his PUT does not block for 15-22s — the outcome still reaches him
    through the pushed status broadcast and GET /api/engine/status."""
    global _last_is_playing
    controls = load_room_controls()
    _last_is_playing = is_playing
    desired = _desired_hold(controls.ambient_enabled, controls.ambient_on_music_pause,
                            is_playing, _held)
    return await _apply(controls, desired, effective_ambient_color(controls),
                        frozenset(controls.ambient_hue_group_ids), wait=wait)


async def reconcile_now(*, wait: bool = True) -> dict:
    """Convenience wrapper for callers with no playback read of their own —
    a human PUT save (room_controls.reconcile_ambient_if_changed), process
    startup/resume (app.py), and a take-back commit (handover.py) — reads
    the live bridge singleton's current is_playing() itself. Deferred
    import: spectra.services.engine imports this module (for status(),
    folded into engine.status()), so a module-level import here would
    cycle."""
    from spectra.services.engine import bridge
    return await reconcile(bridge.is_playing(), wait=wait)


async def _apply(controls: RoomControlState, desired: bool, color: Optional[str],
                 group_ids: frozenset = frozenset(), *, wait: bool = True) -> dict:
    target = _current_target(desired, color, group_ids)
    if not ambient.room_available():
        # THE RELEASED ROOM (module docstring). Nothing physical can move,
        # so no transition is started and NOTHING is recorded as landed —
        # the intent is already durable in RoomControlState, and the next
        # take-back reconcile (app.py's startup/resume, or handover's own
        # commit) finds the target un-landed and applies it for real. Not a
        # silent nothing: the caller is told exactly this.
        if desired:
            # Same write-time honesty as before: something WANTS a hold and
            # there is demonstrably nothing holding it, so `held` must read
            # false and `mode` "partial" right now — not wait for the
            # periodic verifier to say what this call already knows.
            _record_verify("dark")
        else:
            _clear_verify()
        return {"status": "dark", "intent": PHASE_ON if desired else PHASE_OFF,
                "phase": PHASE_UNAVAILABLE, "stored": True}
    async with _get_apply_lock():
        # Short and I/O-free by design: this is the section an interrupting
        # press must never queue behind (module docstring, Concurrency).
        tr = _transition
        if tr is not None and tr.in_flight and tr.target == target:
            # Already on its way to exactly this state — pressing again is
            # not a reason to cancel and restart it (and a burst of bridge
            # broadcasts must never be able to restart a transition
            # forever, which is what comparing against `_held` alone would
            # have done: `_held` does not move until the run lands).
            return _in_flight_result(tr)
        if (tr is None or not tr.in_flight) and _target_landed(target):
            return _settled_result(controls, desired)
        tr = _start_transition(target)
    if wait:
        return await _await_transition(tr)
    return _in_flight_result(tr)


def _in_flight_result(tr: _Transition) -> dict:
    return {"status": PHASE_TURNING_ON if tr.intent else PHASE_TURNING_OFF,
            "intent": PHASE_ON if tr.intent else PHASE_OFF,
            "phase": PHASE_TURNING_ON if tr.intent else PHASE_TURNING_OFF,
            "generation": tr.generation, "snap": tr.snap}


def _settled_result(controls: RoomControlState, desired: bool) -> dict:
    """Nothing needed to change. Synthesized honestly rather than replaying
    a stale prior result: "yielding" only when the music-pause switch is
    what is holding Ambient back, never as a stand-in for plain off."""
    if desired:
        return {"status": PHASE_ON, "intent": PHASE_ON, "phase": PHASE_ON}
    if controls.ambient_on_music_pause and not controls.ambient_enabled:
        return {"status": "yielding", "intent": PHASE_OFF, "phase": PHASE_OFF}
    return {"status": PHASE_OFF, "intent": PHASE_OFF, "phase": PHASE_OFF}


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


async def verify_now() -> dict:
    """The independent periodic recheck (module docstring, "Status
    honesty"). Skips entirely when nothing is currently claimed held
    (nothing to check) or a transition is in flight (its own read-back is
    fresher than anything this could add, and reading bridge state
    mid-change would only report a room that is deliberately moving). The
    GET-only recheck itself is unconditional (services.ambient.verify_held's
    own docstring); what follows is NOT — a light it finds off-target gets
    one paced, read-back-confirmed REPAIR attempt
    (services.ambient.repair_stragglers, 2026-08-16) before this reports
    "partial", the fix for the live defect this module's docstring used to
    describe as deliberate: two bulbs sat wrong for hours while verify_now()
    named them correctly on every tick and repaired neither.
    repair_stragglers() itself still never touches a light that reads OFF
    right now (checked fresh, immediately before writing) — a bulb he turned
    off himself stays off. A confirmed miss that repair could not clear
    downgrades `_verified_ok` (status()'s `held`/`mode` react immediately)
    but never touches `_held` itself — the write-intent short-circuit is
    untouched, so a colour/toggle change still re-applies exactly as
    before."""
    if not _held:
        return {}
    if transition_in_flight():
        return {}
    controls = load_room_controls()
    target_color = effective_ambient_color(controls)
    result = await ambient.verify_held(target_color, frozenset(controls.ambient_hue_group_ids))
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
    """The room's honest, always-live read of what Ambient is ACTUALLY
    doing — folded into GET /api/engine/status by services/engine.py and
    pushed verbatim over the SPECTRA websocket at every transition start/
    end/cancel.

    `intent` and `phase` are the FROZEN contract (module docstring); every
    other key is SPECTRA's own richer detail and may grow.

    `held` is gated on the most recent confirmation (write read-back or
    periodic verify), not the bare write-intent flag, so it can never keep
    reading true for a light that's actually off. `mode` keeps its five
    pre-rework values for the room bar's existing badge — note "yielding"
    is now only reachable while ambient_on_music_pause is on, since nothing
    else can want a hold the room is not doing. `groups` names the
    currently-held device ids (empty when not held, or when the selection is
    "every live Hue device" — the default)."""
    controls = load_room_controls()
    tr = _transition
    in_flight = tr is not None and tr.in_flight
    confirmed_held = _held and _verified_ok is not False

    if in_flight:
        assert tr is not None
        intent_on = tr.intent
        phase = PHASE_TURNING_ON if intent_on else PHASE_TURNING_OFF
    else:
        intent_on = _desired_hold(controls.ambient_enabled,
                                  controls.ambient_on_music_pause,
                                  _last_is_playing, _held)
        # A room that is not ours cannot be moved by a press — say so
        # rather than reporting a settled on/off the lights are not in.
        phase = (PHASE_ON if _held else PHASE_OFF) if ambient.room_available() \
            else PHASE_UNAVAILABLE

    if not controls.ambient_enabled and not controls.ambient_on_music_pause:
        mode = "off"
    elif in_flight:
        mode = "transitioning"
    elif (_held or intent_on) and _verified_ok is False:
        # `_held or intent_on`: a room that is not ours never records a
        # landed hold (see _apply's unavailable branch), but something still
        # wants one and demonstrably has not got it — that is exactly what
        # "partial" has always meant here ("or nothing left to hold at all").
        mode = "partial"
    elif confirmed_held:
        mode = "holding"
    else:
        mode = "yielding"

    out = {
        "intent": PHASE_ON if intent_on else PHASE_OFF,
        "phase": phase,
        "enabled": controls.ambient_enabled,
        "on_music_pause": controls.ambient_on_music_pause,
        "mode": mode,
        "held": confirmed_held,
        "groups": sorted(_held_resolved_groups) if _held else [],
    }
    if in_flight:
        assert tr is not None
        out["generation"] = tr.generation
        out["snap"] = tr.snap
    if _last_result:
        out["result"] = _last_result
    if _last_verified_ms is not None:
        out["verified_age_s"] = round(time.monotonic() - _last_verified_ms, 1)
        out["verify"] = _last_verify
    return out
