"""Flare preview LIVE hold (owner ask 2026-08-20, corrected same day — his
words: "previewing a flare should temporarily call the scene, and hold it
while the preview window is open. then release when it is closed." — his
transcription dropped a letter; "hold" is the only reading that fits).

THE CORRECTION THIS MODULE EXISTS TO CLOSE: the flare scrubbing-preview
(spectra/services/flare_preview.py) computes a timeline against a SCRATCH
DriftConductor/ResponseEngine wired to a RecordingExecutor — by that
module's own docstring, "no fx_seam/executor.facade call of any kind is
reachable from this path." Holding the scene alone (firing it, doing
nothing else) would NOT have made a flare visible: the flare's own writes
still had nowhere real to land. His own live test confirmed exactly this —
"i have tested some of the flares and they do not actually change anything
on the lights." So this module does BOTH halves as ONE behaviour: firing
the scene onto his real fixtures and holding it there, THEN firing the
same flare kind for real too (against a live executor, not the scratch
recording one) — open means his room shows the thing; close means it goes
back. The browser's scrub timeline (markers, animation_start_s/end_s) is
UNCHANGED and stays purely computed — see flare_preview.py's own
docstring for why that's still the right instrument for the UI, and
flare_preview.build_timeline / this module's open_hold both call the
SAME `flare_preview._scratch_engine` resolve/compile/seed path so the two
can never silently diverge in what they predict vs. what actually fires.

WHAT OPENING A PREVIEW DOES TO HIS ROOM: the trigger engine is already
paused for the duration (spectra/services/preview_pause.py, unchanged) —
so if music is playing and his triggers are firing, THEY GO SILENT the
moment the preview opens: no scene changes, no other flares, nothing but
the previewed scene + kind, until the preview closes. This is a real,
visible interruption of his live show, not a side channel — it belongs in
the help copy (spectra/web/src/help/helpContent.ts), not just here.
"No scene changes" here was only half true until 2026-08-21 (fm/
preview-must-hold-scene-changes) — scene_sequencer.fire_scene_by_id, the
ONE choke point his fire_scene triggers actually route through, never
consulted preview_pause at all, so a trigger-driven scene fire sailed
through a paused, open preview while responses/flares correctly went
silent. See preview_pause.py's own docstring for the fix.

TRUE SIMULATION (2026-08-21, data/preview-loops-and-fires-on-the-trigger):
open_hold() is no longer called once, on /open — it's called once per loop
cycle, from spectra/api/flare_preview.py's own /fire endpoint, timed by
the frontend's playhead loop to land exactly when it crosses
flare_preview.animation_anchor_s(). This is what makes the preview a real
simulation of a trigger crossing rather than an instant flash the moment
the window opens: the FIRST fire waits for the mark same as every fire
after it. open_hold() itself needed no change for this — it was already
safe to call repeatedly in one session (see its own docstring: "a later
call in the SAME session... re-fires both at the new value"); the only
thing that changed is WHO calls it and WHEN.

A SEPARATE, SCRATCH conductor+responder pair (flare_preview._scratch_engine)
does the firing — NEVER the production engine.conductor/engine.responses
singletons, and NEVER scene_compiler.fire_scene's live branch (which also
calls engine.on_scene_fired, persisting active_set_id and replacing the
production conductor's whole internal model with no way back). Both would
make "release" require deep-copying and restoring engine-internal state —
the same trap room_preview.py's own docstring names ("a preview must never
touch the room's persisted active_set_id/wheel position"). With a scratch
pair there is NOTHING on the engine side to give back: production
conductor/responses are never touched, so once preview_pause clears they
resume exactly where they left off, unaware anything happened. The ONLY
thing that ever needs reverting is the raw light bytes — read once via
fx_seam.get_virtuals() before the first write, exactly like room_preview.py's
own snapshot/revert contract ("what we take, we give back").

Writes reach fx_seam (not a bespoke live executor) via _SeamExecutor below —
the scratch pair's Executor is swapped for one that adapts fx_seam.apply_writes
onto the glide/jump protocol ResponseEngine/DriftConductor already speak, so
a preview's writes get the SAME ownership-routing/handover-refusal/
brightness-carry-forward every other explicit owner write (room_preview,
dark_light, ambient) already gets — never a hand-rolled facade call that
would bypass that gate.

RELEASE IS THE HIGH-RISK HALF OF THIS FEATURE — a hold that outlives its
window now leaves REAL writes on his fixtures, not a browser simulation.
Three named failure cases, each with its own answer:

  1. Browser closed (not just the overlay/tab's own unmount handler firing
     a real /close). No explicit close ever arrives.
  2. Connection drops mid-preview (a killed network, a sleeping phone).
     Identical from the server's point of view to (1) — it can't reach
     /heartbeat either way.
  Both (1) and (2) are handled the SAME way, and it is DEADLINE-driven, not
  close-driven: _deadline is a plain monotonic timestamp (the exact shape
  spectra/services/preview_pause.py's own `_until` already uses) —
  open()/touch() write it, nothing has to actively run for it to lapse,
  and it is checked independently every SWEEP_INTERVAL_S by
  run_supervised()'s own always-on sweep task, never by anything a close
  call triggers. A lapsed heartbeat therefore reverts on its own, worst
  case HEARTBEAT_TIMEOUT_S (15s) + SWEEP_INTERVAL_S (2s) = 17s after the
  last heartbeat arrived, whether or not /close is ever called — no
  distinction is drawn between "closed" and "dropped" because none is
  observable from here; both degrade to the same 17s ceiling. See
  sweep_once()'s own docstring for why this is a real, independent check
  and not simply "a task that hasn't fired yet."

  3. The SPECTRA process restarts while a hold is live. The deadline above
     is in-memory only (same as preview_pause's own `_until`) — a restart
     wipes it, and with it the sweep's ability to know a hold was ever
     open, so "a restart fixes it" is NOT true here the way it would be
     for a purely in-memory mechanism: the light bytes a restart leaves
     behind are real, and nothing in memory remembers they need reverting.
     The PRECEDENT for this exact
     shape already exists in this codebase: fx/light_ownership.py's
     recover_stale_handover() — a durable, timestamped record, checked at
     process startup, landed back at a known-safe state because a
     restart is proof the thing that was managing it is gone. This module
     follows the SAME SHAPE: the pre-fire snapshot is persisted
     (FLARE_PREVIEW_HOLD_FILE, tmp+os.replace atomic, mirroring
     dark_light.py's own pre-dark snapshot survival) the instant a hold
     starts and cleared the instant it reverts; recover_stale_hold(),
     called once from spectra/app.py's own startup lifespan (after the
     live stack activates — the SAME point resume_own_room() already
     re-lights the room from), reverts any snapshot still on disk before
     anything else touches the lights. Deliberately NOT age-gated the way
     recover_stale_handover() is: that gate exists because a YOUNG
     handing-over record might be a live orchestrator in the OTHER
     process, still legitimately mid-transition — there is no second
     process here that could still legitimately hold a flare preview open,
     so a leftover snapshot found at startup is unconditionally stale
     (its own process is what would have been keeping it alive) and
     always gets landed back, never treated as "maybe still in progress."

THE PROOF BAR: firing + reverting must be proven against a REAL headless
render pipeline (fx.headless + fx.facade, ownership=spectra — the same rig
test_room_preview.py already uses) — a written config value on a live
`virtual.active_effect.config`, not a call recorded on a RecordingExecutor.
See tests/test_flare_preview_hold.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from typing import Any

from spectra import config
from spectra.models.scene import FlareKind, SceneV2
from spectra.services import flare_preview, fx_seam, room_controls

logger = logging.getLogger(__name__)

# The frontend's own heartbeat interval is well under this — reused
# verbatim (not a second, different number to explain) as both the
# preview_pause window (spectra/api/flare_preview.py) and the deadline
# below. One window, one sentence: a lapsed heartbeat releases his room
# within HEARTBEAT_TIMEOUT_S + SWEEP_INTERVAL_S at the worst.
HEARTBEAT_TIMEOUT_S = 15.0
# How often the sweep below checks the deadline — deliberately short and
# "dumb" (his own word): an over-eager release costs one interrupted
# preview; a late one costs a wrong room. See run_supervised()'s docstring
# for why THIS timer, not the per-session one it replaced, is the actual
# safety mechanism.
SWEEP_INTERVAL_S = 2.0

_lock = asyncio.Lock()
_snapshot: dict[str, dict] | None = None
# The deadline this hold expires at — a plain monotonic timestamp, the
# SAME shape as spectra/services/preview_pause.py's own `_until`: nothing
# has to run for a deadline to lapse, "active" is just a comparison against
# time.monotonic() evaluated wherever it's read. THIS is what makes the
# hold self-healing under a lapsed heartbeat (browser closed, connection
# dropped, a wedged tab) without depending on any one asyncio task having
# correctly fired — see run_supervised()'s own docstring for the earlier,
# weaker design this replaced.
_deadline: float | None = None
_release_tasks: list["asyncio.Task"] = []

# A revert must NOT use transition_ms=0: fx/effects/__init__.py's
# start_param_transitions only cancels/replaces an in-flight tween on a
# key when it's given a POSITIVE duration (the tween-retarget branch) — a
# duration<=0 calls _apply_config directly and never touches self._tweens,
# so a still-glide-ing param (e.g. this module's own DICE_REROLL_GLIDE_MS/
# PULSE_RELEASE_S writes) would silently resume overwriting the reverted
# value on the very next rendered frame, landing on the FLARE's target
# instead of the true pre-preview baseline. 1ms (fx_executor.py's own
# JUMP_MS convention for "instant but tween-safe") always takes the
# retarget branch — from wherever any dangling tween currently sits, no
# snap — and lands within one rendered frame either way.
REVERT_TRANSITION_MS = 1


class _SeamExecutor:
    """Adapts fx_seam.apply_writes onto the glide/jump Executor protocol
    ResponseEngine/DriftConductor speak. Every write this scratch pair
    issues therefore reaches fx_seam's own ownership routing (HTTP vs.
    in-process facade), handover refusal, and brightness carry-forward —
    the SAME seam room_preview.py/dark_light.py/ambient.py already use for
    their own explicit-owner writes, never a bespoke live-write path."""

    mode = "seam"

    async def glide(self, virtual_id: str, effect_type: str,
                    params: dict[str, Any], duration_ms: int) -> None:
        if not params:
            return
        await fx_seam.apply_writes(
            [{"virtual_id": virtual_id, "effect_type": effect_type,
              "config": dict(params)}], transition_ms=duration_ms)

    async def jump(self, virtual_id: str, effect_type: str,
                   params: dict[str, Any]) -> None:
        if not params:
            return
        await fx_seam.apply_writes(
            [{"virtual_id": virtual_id, "effect_type": effect_type,
              "config": dict(params)}], transition_ms=0)


def _load_snapshot() -> dict | None:
    path = config.FLARE_PREVIEW_HOLD_FILE
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        return record.get("snapshot")
    except Exception:
        logger.exception("flare_preview_hold: unreadable snapshot %s — "
                         "treating as empty", path)
        return None


def _save_snapshot(snapshot: dict) -> None:
    path = config.FLARE_PREVIEW_HOLD_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"snapshot": snapshot, "started_at": time.time()}
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _clear_snapshot_file() -> None:
    try:
        config.FLARE_PREVIEW_HOLD_FILE.unlink()
    except FileNotFoundError:
        pass


def active() -> bool:
    """A pure, always-current read — the SAME shape as preview_pause.active()
    (compares against the deadline right now, no dependency on the sweep
    having already ticked) — so a caller never sees a hold reported "active"
    past its own deadline just because run_supervised() hasn't gotten to it
    yet. The actual light revert still only happens via sweep_once()/
    close_hold(); this function only ever reports, never reverts."""
    return (_snapshot is not None and _deadline is not None
           and time.monotonic() < _deadline)


async def _revert_locked() -> None:
    """Caller must hold _lock. Writes the snapshot back and clears every
    piece of session state (in-memory and persisted) — safe to call with
    no active hold (idempotent, mirroring room_preview._revert_locked)."""
    global _snapshot, _deadline
    for task in _release_tasks:
        task.cancel()
    _release_tasks.clear()
    snap = _snapshot
    _snapshot = None
    _deadline = None
    _clear_snapshot_file()
    if not snap:
        return
    writes = [{"virtual_id": vid, "effect_type": s["type"], "config": s["config"]}
             for vid, s in snap.items()]
    try:
        await fx_seam.apply_writes(writes, transition_ms=REVERT_TRANSITION_MS)
    except Exception:
        logger.exception("flare_preview_hold: revert failed for %s", sorted(snap))


def _rearm(duration_s: float) -> None:
    global _deadline
    _deadline = time.monotonic() + duration_s


async def sweep_once() -> bool:
    """The dumb, timer-driven check run_supervised() below calls on
    SWEEP_INTERVAL_S: if a hold is active AND its deadline has passed,
    revert it. This is the ACTUAL safety mechanism for a lapsed heartbeat
    (browser closed / connection dropped / a wedged tab) — not the earlier
    design this replaced, which scheduled ONE asyncio task per open() call
    to sleep-then-revert. That task-based shape self-heals too in the
    common case, but it ties the room's actual release to that ONE task
    correctly existing and firing — any bug in re-arming it (a missed
    cancel/recreate on some code path, an exception escaping in a way
    untested here) has no independent backstop. This sweep decouples "is
    the deadline correctly set" (a plain variable write, _rearm above, hard
    to get wrong) from "does the revert actually happen" (checked
    independently, on its own clock, every SWEEP_INTERVAL_S) — the exact
    shape spectra/services/ambient_music_gate.py's own status-honesty fix
    already established in this codebase: a write-time confirmation proves
    only the moment it was taken, so a standing guarantee needs its own
    recheck loop. Returns True if a revert happened."""
    async with _lock:
        if _snapshot is None or _deadline is None or time.monotonic() < _deadline:
            return False
        await _revert_locked()
        return True


async def run_supervised() -> None:
    """Own asyncio task, started once from spectra/app.py's lifespan
    alongside frame_watchdog/ownership_reconciler/ambient_music_gate's own
    — same discipline: a crashing tick is logged and retried, never lets a
    stuck hold go unchecked forever just because one tick errored. THIS,
    not close_hold(), is what makes the hold safe: a close that never
    arrives (browser closed rather than the tab's own unmount handler
    firing, a dropped connection) still gets caught here, worst case
    HEARTBEAT_TIMEOUT_S + SWEEP_INTERVAL_S after the last heartbeat — a
    service restart is the one case this can't cover (the deadline is
    in-memory, gone with the old process) and is handled separately by
    recover_stale_hold() at the next startup."""
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("flare_preview_hold: sweep tick crashed (retrying)")
        await asyncio.sleep(SWEEP_INTERVAL_S)


async def _release_after_hold(responder, hold_s: float) -> None:
    try:
        await asyncio.sleep(hold_s)
    except asyncio.CancelledError:
        return
    await responder.flush_releases(hold_s)


async def open_hold(scene: SceneV2, kind: FlareKind, intensity: float, *,
                    heartbeat_timeout_s: float) -> dict:
    """Fire `scene` live (the "call the scene" step) then `kind` live on
    top of it, against a scratch pair seeded fresh every call — a later
    call in the SAME session (an intensity-slider change) re-fires both at
    the new value, matching flare_preview.build_timeline's own "call again
    whenever the intensity changes" contract, but only SNAPSHOTS on the
    first call of a session: the pre-preview live bytes, read once via
    fx_seam.get_virtuals() before anything is written, are what a later
    revert restores — never a mid-session state. Any release task still
    pending from a PRIOR call in this session is cancelled first, so an
    intensity change mid-hold can't race its own earlier momentary release
    against the new fire. Re-arms the release deadline (module docstring,
    "deadline-driven, not close-driven") either way — an /open call is at
    least as much a heartbeat as an explicit /heartbeat ping. Raises on a
    live-write failure (ownership refusal, an unreachable LedFX) — the
    caller surfaces that to the owner rather than silently arming a pause
    with nothing actually shown."""
    global _snapshot
    async with _lock:
        for task in _release_tasks:
            task.cancel()
        _release_tasks.clear()
        first_open = _snapshot is None
        live = await fx_seam.get_virtuals() if first_open else None
        clock = time.monotonic
        executor = _SeamExecutor()
        conductor, responder, writes = flare_preview._scratch_engine(
            scene, intensity, clock, executor)
        if not writes:
            _rearm(heartbeat_timeout_s)
            return {"held": False, "fire_record": {"result": "no_writes"}}
        if first_open:
            snapshot: dict[str, dict] = {}
            for w in writes:
                vid = w["virtual_id"]
                effect = (live.get(vid) or {}).get("effect") or {}
                effect_type = effect.get("type")
                if not effect_type:
                    continue
                snapshot[vid] = {"type": effect_type,
                                 "config": dict(effect.get("config") or {})}
            _snapshot = snapshot
            _save_snapshot(snapshot)
        room = room_controls.load_room_controls()
        entry_ramp_ms = (scene.entry_ramp_ms or room.global_transition_ms
                        or room_controls.scene_transition_ms(room, intensity))
        await fx_seam.apply_writes(writes, transition_ms=entry_ramp_ms)
        fire_record = await responder.fire_kind(kind, intensity)
        for hold_s in responder.pending_hold_groups():
            _release_tasks.append(asyncio.create_task(
                _release_after_hold(responder, hold_s)))
        _rearm(heartbeat_timeout_s)
        return {"held": True, "first_open": first_open, "fire_record": fire_record}


async def touch(heartbeat_timeout_s: float) -> None:
    """The heartbeat's own re-arm — no recompute, no re-fire. A no-op once
    the session has already ended (deadline lapsed and swept / explicit
    close), so a straggling heartbeat can't resurrect a dead session."""
    async with _lock:
        if _snapshot is not None:
            _rearm(heartbeat_timeout_s)


async def close_hold() -> dict:
    """Explicit release — the overlay's own close / unmount / sendBeacon.
    Idempotent: releasing with nothing active is a harmless no-op."""
    was_active = active()
    async with _lock:
        await _revert_locked()
    return {"reverted": was_active}


async def recover_stale_hold() -> bool:
    """Land any hold left over from a prior process life — see the module
    docstring's failure case 3. Called once from spectra/app.py's startup
    lifespan, after the live stack activates. A leftover snapshot is
    unconditionally stale (see docstring for why no age gate applies here)
    so this always reverts and clears it; never treated as still-in-flight.
    Returns True if a landing happened."""
    snapshot = _load_snapshot()
    if not snapshot:
        return False
    logger.critical(
        "flare_preview_hold: stale hold found at startup (%d virtual(s)) — "
        "landing it back", len(snapshot))
    writes = [{"virtual_id": vid, "effect_type": s["type"], "config": s["config"]}
             for vid, s in snapshot.items()]
    try:
        await fx_seam.apply_writes(writes, transition_ms=REVERT_TRANSITION_MS)
    except Exception:
        logger.exception("flare_preview_hold: startup revert failed for %s",
                         sorted(snapshot))
    _clear_snapshot_file()
    return True
