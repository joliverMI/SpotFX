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

ONE HOLD, MANY PROGRAMS (2026-08-27, fm/flare-preview-offsets-everywhere).
His own sequencing for this system was "start with the flares, then we will
do lull charge drop", and the second half adds two more previews that must
hold his room: a scene-to-scene TRANSITION and the charge/lull/drop
SEQUENCE. Everything genuinely hard here — the once-per-session snapshot,
the deadline that lapses on its own, the independent sweep, the absolute
ceiling a heartbeating client cannot push out, the persisted snapshot a
restart lands back, both release queues, the 1ms tween-safe revert — was
learned expensively (13m54s of his room, 85 refused scene changes) and
stays in ONE implementation. What varies is factored into PreviewProgram
below: which scene backs the hold, which extra virtuals it may touch, and
what each named STEP does. open_hold() is now the thinnest such program
(FlareKindProgram) and is byte-identical in behaviour to what it always
did. A new preview supplies a program; it never supplies a second hold.

THE PROOF BAR: firing + reverting must be proven against a REAL headless
render pipeline (fx.headless + fx.facade, ownership=spectra — the same rig
test_room_preview.py already uses) — a written config value on a live
`virtual.active_effect.config`, not a call recorded on a RecordingExecutor.
See tests/test_flare_preview_hold.py.

MAXIMUM HOLD CEILING (2026-08-21, PR fm/preview-hold-needs-a-ceiling): his
live room was held for 13m54s in one continuous window (2026-08-21,
17:23:19-17:37:12), refusing 85 scene changes, because a client (a
headless browser left running by mistake — human error, not a code
defect) never stopped heartbeating. HEARTBEAT_TIMEOUT_S/SWEEP_INTERVAL_S
above bound ABANDONMENT — how long a hold survives once heartbeats STOP —
they say nothing about a client that keeps heartbeating forever, which is
exactly what happened: a bound a live client can push out forever is not
a bound.

MAX_HOLD_DURATION_S is the fix: an ABSOLUTE ceiling on one continuous
hold, counted from when it actually started controlling his fixtures
(the first real fire — `_session_started_at` below), never reset by a
heartbeat or a re-fire that arrives before it. `_rearm()` caps every
requested deadline against `_session_started_at + MAX_HOLD_DURATION_S`,
so heartbeats can push the deadline right up to the ceiling and no
further — the clock starts once and never moves. His use of this feature
is looking at ONE flare against his room — seconds to a couple of minutes
of real judging, per his own framing, never a stretch he'd plan to sit
through. 180s (3 minutes) comfortably covers a real, unhurried look (open,
watch several loops, nudge the intensity slider, watch again) while
making a forgotten/minimised tab a brief, self-correcting nuisance instead
of a lost show — nowhere near the 14 minutes that actually happened.

Reaching the ceiling runs the SAME revert the heartbeat-lapse path already
does, but it ALSO locks the session (`_locked_until_reopen`) so a client
that keeps calling /fire or /heartbeat afterward — exactly the reported
failure mode, no further /open calls, just the loop and the heartbeat
ticking on — cannot silently re-establish a new hold and restart the
clock: `open_hold()`/`capped_pause_s()` become no-ops while locked. Only a
genuine fresh `/open` (a real mount, or him moving the intensity slider —
never a bare heartbeat) calls `clear_ceiling_lock()` and lets a new
session begin. The SAME ceiling is exposed to spectra/api/flare_preview.py
via `capped_pause_s()`/`locked_until_reopen()` so its own, separately
armed `preview_pause.start()` calls — what actually blocks his scene
changes, fire_history's "deferred"/"preview" bucket — can never outlive
this module's own light-hold deadline; the two must expire together, or
"the preview released" is still a lie for however long preview_pause
stays armed on its own.
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

# The ABSOLUTE ceiling on one continuous hold — see the module docstring's
# "MAXIMUM HOLD CEILING" section for the incident this closes and why 180s
# (3 minutes) was chosen. Unlike HEARTBEAT_TIMEOUT_S, no number of
# heartbeats or re-fires can push this further out.
MAX_HOLD_DURATION_S = 180.0

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
# When the CURRENT session's first real fire happened — the anchor
# MAX_HOLD_DURATION_S counts from. Set once per session (alongside
# _snapshot, on first_open) and cleared on every revert, whatever the
# reason, so a genuinely new session always starts its own fresh ceiling.
_session_started_at: float | None = None
# Sticky once the ceiling fires (_revert_locked(reason="max_duration"));
# only clear_ceiling_lock() — called from a genuine POST /open, never a
# heartbeat or a re-fire — clears it. See "MAXIMUM HOLD CEILING" above.
_locked_until_reopen: bool = False
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


async def _revert_locked(reason: str = "explicit_close") -> None:
    """Caller must hold _lock. Writes the snapshot back and clears every
    piece of session state (in-memory and persisted) — safe to call with
    no active hold (idempotent, mirroring room_preview._revert_locked).
    `reason` distinguishes what triggered this: only "max_duration" (the
    ceiling firing) locks the session against a client that keeps
    heartbeating/re-firing afterward — an explicit close or a plain
    abandoned/lapsed heartbeat leaves it free to start fresh on its own
    next open, exactly as before this ceiling existed."""
    global _snapshot, _deadline, _session_started_at, _locked_until_reopen
    for task in _release_tasks:
        task.cancel()
    _release_tasks.clear()
    snap = _snapshot
    _snapshot = None
    _deadline = None
    _session_started_at = None
    _locked_until_reopen = (reason == "max_duration")
    _clear_snapshot_file()
    if not snap:
        return
    writes = [{"virtual_id": vid, "effect_type": s["type"], "config": s["config"]}
             for vid, s in snap.items()]
    try:
        await fx_seam.apply_writes(writes, transition_ms=REVERT_TRANSITION_MS)
    except Exception:
        logger.exception("flare_preview_hold: revert failed for %s", sorted(snap))
    if reason == "max_duration":
        logger.warning(
            "flare_preview_hold: MAX_HOLD_DURATION_S (%.0fs) reached while "
            "still heartbeating — releasing his room regardless (%d "
            "virtual(s)); locked until a fresh /open", MAX_HOLD_DURATION_S,
            len(snap))


def _rearm(duration_s: float) -> None:
    """(Re)arm the release deadline `duration_s` from now — capped so the
    deadline can never cross the ABSOLUTE ceiling
    (_session_started_at + MAX_HOLD_DURATION_S) once a real session has
    begun. This is what makes the ceiling immune to heartbeats: a
    heartbeat/re-fire arriving before the ceiling can still push the
    deadline UP TO it, never past it — see the module docstring's
    "MAXIMUM HOLD CEILING" section."""
    global _deadline
    deadline = time.monotonic() + duration_s
    if _session_started_at is not None:
        deadline = min(deadline, _session_started_at + MAX_HOLD_DURATION_S)
    _deadline = deadline


def locked_until_reopen() -> bool:
    """Pure read — True once the ceiling has fired and no fresh /open has
    cleared it yet. spectra/api/flare_preview.py's /fire and /heartbeat
    consult this before doing anything, so a client that keeps calling
    either — exactly the reported failure mode: no further /open calls,
    just the RAF fire-loop and the heartbeat ticking on — can never
    silently re-establish a new hold and restart the ceiling's clock."""
    return _locked_until_reopen


def clear_ceiling_lock() -> None:
    """Called from a genuine POST /open — a real mount, or him moving the
    intensity slider — never from /fire or /heartbeat. A fresh open is a
    deliberate new look, not a passive heartbeat, so it's allowed to start
    a new session even if the ceiling just fired on the previous one."""
    global _locked_until_reopen
    _locked_until_reopen = False


def capped_pause_s(requested_s: float) -> float:
    """Cap a proposed spectra.services.preview_pause arm/re-arm duration
    against the SAME ceiling _rearm applies to this module's own deadline —
    exposed because preview_pause is armed independently, by
    spectra/api/flare_preview.py, and is what actually blocks his scene
    changes (fire_history's "deferred"/"preview" bucket). Without this, his
    scene changes could stay refused for up to another HEARTBEAT_TIMEOUT_S
    after the lights already reverted at the ceiling — "the preview
    released" would still be a lie for however long preview_pause stayed
    armed on its own. Returns 0.0 once the ceiling has already passed, or
    while locked (see locked_until_reopen())."""
    if _locked_until_reopen:
        return 0.0
    if _session_started_at is None:
        return requested_s
    remaining = (_session_started_at + MAX_HOLD_DURATION_S) - time.monotonic()
    return max(0.0, min(requested_s, remaining))


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
    recheck loop. Returns True if a revert happened.

    Distinguishes WHY the deadline lapsed for _revert_locked's own
    reason param: if the ceiling (_session_started_at + MAX_HOLD_DURATION_S)
    has itself been reached, this is the absolute ceiling firing (lock the
    session) — otherwise it's an ordinary abandoned-heartbeat lapse at an
    earlier, uncapped deadline (no lock; a fresh open next time is not a
    circumvention of anything)."""
    async with _lock:
        if _snapshot is None or _deadline is None or time.monotonic() < _deadline:
            return False
        reached_ceiling = (
            _session_started_at is not None
            and time.monotonic() >= _session_started_at + MAX_HOLD_DURATION_S - 1e-6)
        reason = "max_duration" if reached_ceiling else "heartbeat_lapsed"
        await _revert_locked(reason)
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


async def _release_group(responder, group) -> None:
    # Same shape as engine._release_group: sleep until the group's ABSOLUTE
    # due time (stamped when the spike write went out), then drain only the
    # entries that fire created — the preview's hold measures from the
    # spike exactly like the real show's now does.
    try:
        await asyncio.sleep(responder.seconds_until(group.due_at))
    except asyncio.CancelledError:
        return
    await responder.flush_releases(group.hold_s, fire_seq=group.fire_seq,
                                   due_by=group.due_at)


async def _release_color_rotates_after_dwell(responder, dwell_s: float) -> None:
    # The colour ROTATE-AND-BACK flare's own release queue — engine.py's
    # _release_color_rotate_after_dwell mirrored onto the scratch responder.
    # Its fade-back duration is intensity-scaled per fire, so it can't share
    # _release_after_hold's fixed-PULSE_RELEASE_S queue (see
    # scene_response._color_rotate's own docstring). Left unscheduled here
    # until 2026-08-21 (his report: the previewed rotation ramped in and
    # never came back, so every later lap re-targeted the already-rotated
    # gradient — zero visible change on every crossing after the first).
    try:
        await asyncio.sleep(dwell_s)
    except asyncio.CancelledError:
        return
    await responder.flush_color_rotates(dwell_s)


class PreviewContext:
    """What a preview program is handed for one step. Everything expensive
    or dangerous — the scratch conductor/responder pair, the compiled
    writes, the live-write seam — is built ONCE by the hold and passed in,
    so a program never opens its own path to his fixtures and can never
    acquire one this module's revert doesn't know how to undo."""

    def __init__(self, *, conductor, responder, writes: list[dict],
                 intensity: float, entry_ramp_ms: int, first_open: bool) -> None:
        self.conductor = conductor
        self.responder = responder
        self.writes = writes
        self.intensity = intensity
        self.entry_ramp_ms = entry_ramp_ms
        self.first_open = first_open

    async def apply_scene(self, writes: list[dict] | None = None,
                          transition_ms: int | None = None) -> None:
        """Land the held scene's compiled writes (or another set of writes
        the program compiled itself — a transition's incoming scene) at the
        real blend duration. The ONE way a program reaches the lights."""
        payload = self.writes if writes is None else writes
        if not payload:
            return
        await fx_seam.apply_writes(
            payload,
            transition_ms=(self.entry_ramp_ms if transition_ms is None
                           else transition_ms))


class PreviewProgram:
    """WHAT a preview hold actually does when it fires, factored out of the
    hold itself (2026-08-27, fm/flare-preview-offsets-everywhere).

    THE RULE THIS EXISTS TO KEEP: never a second bespoke hold. Everything
    genuinely hard about holding his room live — the snapshot taken once
    per session, the deadline that lapses on its own, the independent sweep
    that reverts a hold nobody closed, the absolute 3-minute ceiling a
    heartbeating client cannot push out, the persisted snapshot a service
    restart lands back, the two release queues, the 1ms tween-safe revert —
    was learned the expensive way (see this module's own docstring: a real
    13m54s hold on his room, 85 refused scene changes) and belongs to ONE
    implementation. A new kind of preview supplies only the part that is
    genuinely new: which scene backs the hold, which virtuals it may touch,
    and what happens on each named step.

    STEPS. A program declares the cues its frontend will schedule
    (`steps`), and the SERVER decides when each one fires — the frontend
    only ever schedules against times the server returned. The flare
    preview has one step ("fire"); a transition has two (put the room back
    at the outgoing scene, then cross to the incoming one); a drop sequence
    has four (charge, lull, drop, release). The hold neither knows nor
    cares what they mean."""

    #: the scene held live — its compiled writes are the snapshot basis and
    #: what apply_scene() lands by default
    hold_scene: SceneV2
    #: the cue names execute() accepts, in ruler order
    steps: tuple[str, ...] = ("fire",)

    def extra_snapshot_writes(self, intensity: float) -> list[dict]:
        """Writes this program may land on virtuals the held scene never
        touches (a transition's INCOMING scene is the real case). Their
        pre-preview state has to enter the snapshot too, or closing the
        preview leaves those virtuals wherever the program left them —
        the exact "what we take, we give back" contract room_preview.py
        states and this module inherits."""
        return []

    async def execute(self, step: str, ctx: PreviewContext) -> dict:
        raise NotImplementedError


class FlareKindProgram(PreviewProgram):
    """The original program, unchanged in behaviour: hold the scene, fire
    ONE declared flare kind on top of it. Every /fire re-lands the scene
    first, which is what lets a mid-session intensity change re-fire both
    at the new value (see open_hold's docstring)."""

    steps = ("fire",)

    def __init__(self, scene: SceneV2, kind: FlareKind) -> None:
        self.hold_scene = scene
        self.kind = kind

    async def execute(self, step: str, ctx: PreviewContext) -> dict:
        await ctx.apply_scene()
        return await ctx.responder.fire_kind(self.kind, ctx.intensity)


async def open_program_hold(program: PreviewProgram, intensity: float, *,
                            step: str = "fire",
                            heartbeat_timeout_s: float) -> dict:
    """Run one named STEP of `program` live, against a scratch pair seeded
    fresh every call from the program's own held scene — a later
    call in the SAME session (an intensity-slider change) re-runs the step at
    the new value, matching flare_preview.build_timeline's own "call again
    whenever the intensity changes" contract, but only SNAPSHOTS on the
    first call of a session: the pre-preview live bytes, read once via
    fx_seam.get_virtuals() before anything is written, are what a later
    revert restores — never a mid-session state. Any release task still
    pending from a PRIOR call in this session is cancelled first, so an
    intensity change mid-hold can't race its own earlier momentary release
    against the new fire. BOTH release queues are scheduled — the fixed
    momentary one (take_release_schedule) and the colour rotate-and-back
    flare's own intensity-scaled one (pending_color_rotate_holds),
    mirroring engine.fire_response_event's pair of scheduling loops; the
    rotate queue was missed here until 2026-08-21 (his report: a previewed
    rotation never faded back, so every crossing after the first showed
    nothing). Re-arms the release deadline (module docstring,
    "deadline-driven, not close-driven") either way — an /open call is at
    least as much a heartbeat as an explicit /heartbeat ping. Raises on a
    live-write failure (ownership refusal, an unreachable LedFX) — the
    caller surfaces that to the owner rather than silently arming a pause
    with nothing actually shown.

    Refuses outright (no fire, no snapshot, {"held": False, "expired":
    True, "reason": "max_duration"}) while locked_until_reopen() is True —
    the ceiling above having fired and no fresh /open having cleared it
    yet. This is what stops a client that keeps calling /fire after the
    ceiling (the reported failure mode) from silently re-establishing a
    new hold; see the module docstring's "MAXIMUM HOLD CEILING" section."""
    global _snapshot, _session_started_at
    async with _lock:
        if _locked_until_reopen:
            return {"held": False, "expired": True, "reason": "max_duration"}
        for task in _release_tasks:
            task.cancel()
        _release_tasks.clear()
        scene = program.hold_scene
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
            # The held scene's own writes PLUS anything else the program
            # may land (a transition's incoming scene can reach virtuals
            # the outgoing one never touches) — the snapshot must cover
            # every virtual the session could move, or close() hands some
            # of them back and silently keeps the rest.
            for w in list(writes) + program.extra_snapshot_writes(intensity):
                vid = w["virtual_id"]
                if vid in snapshot:
                    continue
                effect = (live.get(vid) or {}).get("effect") or {}
                effect_type = effect.get("type")
                if not effect_type:
                    continue
                snapshot[vid] = {"type": effect_type,
                                 "config": dict(effect.get("config") or {})}
            _snapshot = snapshot
            _session_started_at = time.monotonic()
            _save_snapshot(snapshot)
        room = room_controls.load_room_controls()
        entry_ramp_ms = (scene.entry_ramp_ms or room.global_transition_ms
                        or room_controls.scene_transition_ms(room, intensity))
        ctx = PreviewContext(conductor=conductor, responder=responder,
                             writes=writes, intensity=intensity,
                             entry_ramp_ms=entry_ramp_ms, first_open=first_open)
        fire_record = await program.execute(step, ctx)
        for group in responder.take_release_schedule():
            _release_tasks.append(asyncio.create_task(
                _release_group(responder, group)))
        for dwell_s in responder.pending_color_rotate_holds():
            _release_tasks.append(asyncio.create_task(
                _release_color_rotates_after_dwell(responder, dwell_s)))
        _rearm(heartbeat_timeout_s)
        return {"held": True, "first_open": first_open, "step": step,
                "fire_record": fire_record}


async def open_hold(scene: SceneV2, kind: FlareKind, intensity: float, *,
                    heartbeat_timeout_s: float) -> dict:
    """The FLARE preview's entry point — hold `scene`, fire `kind` on top.
    Unchanged in behaviour; it is now the thinnest possible program
    (FlareKindProgram) over the general hold above, so the flare preview,
    the transition preview and the drop-sequence preview share ONE
    snapshot/deadline/sweep/ceiling/restart-recovery implementation rather
    than growing a second bespoke hold each."""
    return await open_program_hold(
        FlareKindProgram(scene, kind), intensity, step="fire",
        heartbeat_timeout_s=heartbeat_timeout_s)


async def touch(heartbeat_timeout_s: float) -> None:
    """The heartbeat's own re-arm — no recompute, no re-fire. A no-op once
    the session has already ended (deadline lapsed and swept / explicit
    close), so a straggling heartbeat can't resurrect a dead session.
    _rearm() itself caps against the absolute ceiling, so an actively
    heartbeating client still can't push the deadline past it — see
    capped_pause_s() above for the sibling cap spectra/api/flare_preview.py
    applies to its own, separately armed preview_pause window."""
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
