"""THE LIGHT SHOW's ARMS — a set (or one action) waiting for its trigger
(phase 2 of 3; plan: /home/javi/fleet-spotfx/data/light-show-plan/report.md
§5.2 and §6; his spec: "armed to execute on the next scene change ... on the
next High Trigger, or on the next Low Trigger").

THREE TRIGGERS, an open list:

  scene_change  the next REAL change to a DIFFERENT scene — any path that
                really fires one (the sequencer, a trigger, the automatic
                transition, his own Fire button), read at engine.
                on_scene_fired BEFORE the conductor takes the new scene. A
                same-scene re-fire never counts, and neither does a scene
                change the Light Show caused itself (a Forced scene or
                Fire-a-scene step) — a repeat arm would otherwise loop.
  high / low    this song's High / Low Trigger (spectra/services/
                show_cues.py), crossed on the trigger clock: TriggerEngine.
                tick() asks `cue_plan()` for the song's cues and calls
                `on_cue()` exactly once per crossing (its own fired-keys
                memory, rearmed on a rewind or a song change). Independent
                of the scene-change tier — a cue exists on every analysed
                song, his own triggers or not.

FINISH ON THE MARK (an approved add-on). A set armed on High/Low that FADES
(a Device state fade, a Level fade-in) starts early by its longest fade —
counted over the steps before its first pause — so the fade COMPLETES on the
mark. The trigger clock fires the cue at the largest lead any armed set needs
and each set waits out the difference to its own, so two arms with different
fades each land on the mark. The WHOLE set moves early (an instant step in
it lands that much early too) — stated on the arm card, his to switch off
per arm. Capped at MAX_FINISH_LEAD_MS. Ambient's own ~15-22 s ease is not
a fade this counts: it is the bulbs' physics, it STARTS on the trigger.

QUEUE, NOT REPLACE — EXCEPT THE SAME SET ON THE SAME TRIGGER. Several arms
wait side by side; arming the set that is already armed on that trigger
replaces the earlier arm (a double tap never stacks). Two arms on one
trigger fire in the order they were armed.

ONE-SHOT OR REPEAT. One-shot fires once and is done; repeat stays armed and
counts its fires.

THIS SONG ONLY, OR IT CARRIES. "This song only" scopes the arm to the song
playing when it was armed: it fires only there, and the first time a
different song plays it is recorded MISSED. Otherwise it carries to the next
song that has its trigger.

EXPIRY: when the room is released (release.release_room calls on_release
before the fade), 12 h after arming, or after 30 min with no music playing —
each recorded with its reason, never a silent disappearance.

THE GATE, AND IT NEVER CONSUMES. A trigger crossing while SPECTRA does not
hold the room, or while a preview / camera run / night run has it
(`show_output.refusal()`, the ONE gate every show step asks), fires
nothing and LEAVES THE ARM ARMED, with the reason on its card — it waits for
the next occurrence.

RESTART: arms live in light_show_state.json (show_store) and reload; an arm
whose 12 h passed while the process was down is expired on the first tick.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from spectra.models.light_show import ShowAction, ShowArm, now_ms
from spectra.services import show_cues, show_output, show_store

logger = logging.getLogger(__name__)

TRIGGERS = ("scene_change", "high", "low")
ARM_MAX_AGE_S = 12 * 3600
ARM_IDLE_EXPIRY_S = 30 * 60
"""An arm expires after this long with no music playing."""
MAX_FINISH_LEAD_MS = 30_000
HISTORY_KEPT = 30
"""Ended arms kept on the board's history (fired / missed / disarmed /
expired), newest first."""

ACTIVE = "armed"
FIRED = "fired"
MISSED = "missed"
DISARMED = "disarmed"
EXPIRED = "expired"

#: injectable seams (production reads the bridge; tests replace them)
current_uri: Callable[[], Optional[str]]
is_playing: Callable[[], Optional[bool]]


def _bridge_uri() -> Optional[str]:
    try:
        from spectra.services import engine
        return engine.bridge.track_uri()
    except Exception:                                    # noqa: BLE001
        return None


def _bridge_playing() -> Optional[bool]:
    try:
        from spectra.services import engine
        return engine.bridge.is_playing()
    except Exception:                                    # noqa: BLE001
        return None


current_uri = _bridge_uri
is_playing = _bridge_playing

_last_music_mono: float = time.monotonic()
_last_crossed: dict[str, dict] = {}
_plan_uri: Optional[str] = None
_tasks: set[asyncio.Task] = set()


class ArmError(ValueError):
    pass


# ── reading ────────────────────────────────────────────────────────────────

def active_arms() -> list[ShowArm]:
    return [a for a in show_store.state().arms if a.status == ACTIVE]


def _steps(arm: ShowArm) -> list[ShowAction]:
    if arm.action is not None:
        return [arm.action]
    s = show_store.get_set(arm.set_id) if arm.set_id else None
    return list(s.actions) if s else []


def lead_ms(arm: ShowArm) -> int:
    """How early this arm must start so its fades COMPLETE on a High/Low
    mark: the longest fade among its steps before the first pause."""
    if not arm.finish_on_mark or arm.on not in ("high", "low"):
        return 0
    best = 0
    for a in _steps(arm):
        if not a.enabled:
            continue
        if a.kind == "pause":
            break
        p = a.params or {}
        try:
            if a.kind == "device_state":
                best = max(best, int(float(p.get("fade_ms") or 0)))
            elif a.kind == "level":
                best = max(best, int(float(p.get("fade_in_ms", 500) or 0)))
        except (TypeError, ValueError):
            continue
    return max(0, min(MAX_FINISH_LEAD_MS, best))


def _applies_to_song(arm: ShowArm, uri: Optional[str]) -> bool:
    return arm.song_uri is None or arm.song_uri == uri


# ── arming ─────────────────────────────────────────────────────────────────

def arm(*, set_id: Optional[str] = None, action: Optional[ShowAction] = None,
        on: str = "scene_change", repeat: bool = False,
        this_song_only: bool = False, finish_on_mark: bool = True,
        source: str = "manual") -> ShowArm:
    if on not in TRIGGERS:
        raise ArmError(f"trigger must be one of {', '.join(TRIGGERS)}")
    if (set_id is None) == (action is None):
        raise ArmError("arm either a set or one action")
    label = ""
    if set_id is not None:
        s = show_store.find_set(set_id)
        if s is None:
            raise ArmError(f"no set called {set_id!r}")
        if not s.actions:
            raise ArmError(f"set {s.name!r} has no steps")
        set_id, label = s.id, s.name
    else:
        from spectra.services import show_actions
        try:
            show_actions.validate(action.kind, action.params)
        except show_actions.ActionError as exc:
            raise ArmError(str(exc))
        label = action.label or show_actions.ACTION_KINDS[action.kind].label
    song = None
    if this_song_only:
        song = current_uri()
        if not song:
            raise ArmError("nothing is playing, so there is no song to scope this arm to")
    st = show_store.state()
    t = now_ms()
    if set_id is not None:
        for old in st.arms:
            if old.status == ACTIVE and old.set_id == set_id and old.on == on:
                _end(old, DISARMED, "replaced by a new arm of the same set on the same trigger")
    new = ShowArm(set_id=set_id, action=action, label=label, on=on,
                  repeat=bool(repeat), song_uri=song, source=source,
                  finish_on_mark=bool(finish_on_mark), created_ms=t,
                  expires_ms=t + ARM_MAX_AGE_S * 1000)
    st.arms.append(new)
    _touch_music()
    _save()
    _record("armed", new, {})
    return new


def disarm(arm_id: str) -> bool:
    a = next((x for x in show_store.state().arms
              if x.id == arm_id and x.status == ACTIVE), None)
    if a is None:
        return False
    _end(a, DISARMED, "disarmed")
    _save()
    return True


def disarm_all(reason: str = "disarmed") -> list[str]:
    ids = []
    for a in active_arms():
        _end(a, DISARMED, reason)
        ids.append(a.id)
    if ids:
        _save()
    return ids


def _end(a: ShowArm, status: str, reason: str) -> None:
    a.status = status
    a.ended_ms = now_ms()
    a.end_reason = reason
    if status != FIRED:
        _record(status, a, {"reason": reason})


def _save() -> None:
    st = show_store.state()
    live = [a for a in st.arms if a.status == ACTIVE]
    ended = sorted((a for a in st.arms if a.status != ACTIVE),
                   key=lambda a: a.ended_ms or 0, reverse=True)[:HISTORY_KEPT]
    st.arms = live + ended
    show_store.save_state()
    _notify()


def _notify() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def push():
        try:
            from spectra.services import show_actions
            from spectra.services.ws import ws_manager
            await ws_manager.broadcast({"type": "light_show", **show_actions.brief()})
        except Exception:                                # noqa: BLE001
            pass
    _spawn(loop, push())


def _spawn(loop, coro) -> asyncio.Task:
    task = loop.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def _record(what: str, a: ShowArm, data: dict) -> None:
    try:
        from spectra.services import fire_history
        fire_history.record_fire("show", f"arm_{what}", {
            "arm": a.id, "set": a.label, "on": a.on, **data})
    except Exception:                                    # noqa: BLE001
        pass


# ── firing ─────────────────────────────────────────────────────────────────

async def _fire(a: ShowArm, trigger: dict) -> None:
    """Run one arm now. Re-checks the gate at the moment it lands (a
    finish-on-the-mark wait can straddle a release)."""
    from spectra.services import show_actions
    if a.status != ACTIVE:
        return
    reason = show_output.refusal()
    if reason:
        a.last_outcome = {"at_ms": now_ms(), "status": "waiting", "reason": reason,
                          **trigger}
        _save()
        return
    try:
        if a.set_id is not None:
            if show_store.get_set(a.set_id) is None:
                _end(a, EXPIRED, "its set was deleted")
                _save()
                return
            run = await show_actions.fire_set(a.set_id, source=f"arm:{a.id}")
        else:
            run = await show_actions.fire([a.action], name=a.label or "armed action",
                                          source=f"arm:{a.id}")
        outcome = {"at_ms": now_ms(), "status": "fired", "run": run.get("id"),
                   "run_state": run.get("state"), **trigger}
    except Exception as exc:                             # noqa: BLE001
        logger.exception("light show: arm %s failed", a.id)
        outcome = {"at_ms": now_ms(), "status": "failed", "reason": str(exc), **trigger}
    a.last_outcome = outcome
    a.fire_count += 1
    _record("fired", a, outcome)
    if not a.repeat:
        _end(a, FIRED, f"fired on {a.on.replace('_', ' ')}")
    _save()


def _wait_or_fire(arms: list[ShowArm], trigger: dict) -> list[str]:
    """Fire `arms` (in arming order) unless the gate is shut, in which case
    each stays armed and SAYS why. Returns the ids scheduled."""
    reason = show_output.refusal()
    if reason:
        for a in arms:
            a.last_outcome = {"at_ms": now_ms(), "status": "waiting",
                              "reason": reason, **trigger}
        if arms:
            _save()
        return []
    return [a.id for a in arms]


def on_scene_change(previous_scene_id: Optional[str], scene_id: Optional[str]) -> list[str]:
    """engine.on_scene_fired, before the conductor takes the new scene."""
    from spectra.services import show_actions
    if not scene_id or scene_id == previous_scene_id:
        return []
    if show_actions.executing():
        return []
    uri = current_uri()
    arms = sorted((a for a in active_arms()
                   if a.on == "scene_change" and _applies_to_song(a, uri)),
                  key=lambda a: a.created_ms)
    trigger = {"trigger": "scene_change", "scene_id": scene_id}
    ids = _wait_or_fire(arms, trigger)
    if not ids:
        return []
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return []

    async def run_in_order():
        for a in arms:
            if a.id in ids:
                await _fire(a, trigger)
    _spawn(loop, run_in_order())
    return ids


def cue_plan(uri: Optional[str]) -> list[tuple[str, int, int]]:
    """(level, cue_ms, lead_ms) for this song's High and Low — what the
    trigger clock watches. The lead is the largest any armed set on that
    level needs (0 with nothing armed). Never blocks: an uncomputed song
    returns [] while its cues are derived in a thread."""
    global _plan_uri
    if uri != _plan_uri:
        # A new play re-derives (a setting or ranking change since the last
        # time this song played must not be served from a stale cache).
        _plan_uri = uri
        show_cues.invalidate(uri)
    cues = show_cues.cached(uri)
    if cues is None:
        return []
    arms = [a for a in active_arms() if _applies_to_song(a, uri)]
    out = []
    for level in show_cues.LEVELS:
        cue = cues.get(level)
        if cue is None:
            continue
        lead = max((lead_ms(a) for a in arms if a.on == level), default=0)
        out.append((level, int(cue.timestamp_ms), lead))
    return out


async def on_cue(level: str, cue_ms: int, ahead_ms: int) -> list[str]:
    """The trigger clock crossed this song's High/Low (`ahead_ms` before the
    mark — the finish-on-the-mark lead it fired early by, or ~0)."""
    uri = current_uri()
    _last_crossed[level] = {"uri": uri, "cue_ms": cue_ms, "at_ms": now_ms()}
    arms = sorted((a for a in active_arms()
                   if a.on == level and _applies_to_song(a, uri)),
                  key=lambda a: a.created_ms)
    trigger = {"trigger": level, "cue_ms": cue_ms}
    ids = _wait_or_fire(arms, trigger)
    if not ids:
        return []
    loop = asyncio.get_running_loop()
    for a in arms:
        if a.id not in ids:
            continue
        delay_s = max(0.0, (ahead_ms - lead_ms(a)) / 1000.0)

        async def later(arm=a, d=delay_s):
            if d > 0:
                await asyncio.sleep(d)
            await _fire(arm, {**trigger, "lead_ms": lead_ms(arm)})
        _spawn(loop, later())
    return ids


# ── expiry ─────────────────────────────────────────────────────────────────

def _touch_music() -> None:
    global _last_music_mono
    _last_music_mono = time.monotonic()


def on_release() -> list[str]:
    """The room is being released: every arm expires (named)."""
    ids = []
    for a in active_arms():
        _end(a, EXPIRED, "the room was released")
        ids.append(a.id)
    if ids:
        _save()
    return ids


def tick() -> None:
    """Expiry pass (the Light Show supervisor calls this every tick)."""
    arms = active_arms()
    if is_playing() is True:
        _touch_music()
    if not arms:
        return
    changed = False
    t = now_ms()
    # Release expiry is the release EVENT (on_release, called by
    # release.release_room) — not the released STATE, or an arm made while
    # the room is released (it waits, and says so) would vanish at once.
    idle = time.monotonic() - _last_music_mono >= ARM_IDLE_EXPIRY_S
    uri = current_uri()
    for a in arms:
        if a.expires_ms is not None and t >= a.expires_ms:
            _end(a, EXPIRED, "armed 12 hours ago")
        elif idle:
            _end(a, EXPIRED, "30 minutes without music")
        elif a.song_uri is not None and uri is not None and uri != a.song_uri:
            _end(a, MISSED, "its song ended before the trigger")
        else:
            continue
        changed = True
    if changed:
        _save()


# ── status ─────────────────────────────────────────────────────────────────

def status() -> dict:
    """The armed board: every waiting arm (with its lead and the next time
    its trigger is due on this song, when known), recent history, and this
    song's High/Low for the countdowns."""
    uri = current_uri()
    cues = show_cues.cached(uri) if uri else None
    position = None
    try:
        from spectra.services.trigger_engine import trigger_engine
        if trigger_engine._uri == uri:
            position = trigger_engine._last_position_ms
    except Exception:                                    # noqa: BLE001
        pass
    waiting = []
    for a in sorted(active_arms(), key=lambda a: a.created_ms):
        row = a.model_dump()
        row["lead_ms"] = lead_ms(a)
        row["this_song"] = _applies_to_song(a, uri)
        due = None
        if a.on in ("high", "low") and cues is not None and row["this_song"]:
            cue = cues.get(a.on)
            if cue is not None and (position is None or cue.timestamp_ms > position):
                due = cue.timestamp_ms - row["lead_ms"]
        row["due_ms"] = due
        waiting.append(row)
    history = [a.model_dump() for a in show_store.state().arms if a.status != ACTIVE]
    # The scene's own minimum hold (dwell.py) is a FLOOR, never a real
    # prediction of when the next scene change happens — it only says the
    # room CANNOT change before this many seconds. `None` when nothing is
    # tracked (cold start, or no fire yet this process life) rather than a
    # fabricated zero.
    try:
        from spectra.services import dwell
        expected_s = dwell.status()["remaining_s"]
    except Exception:                                    # noqa: BLE001
        expected_s = None
    return {"armed": waiting, "history": history,
            "song": {"uri": uri, "position_ms": position,
                     "cues": cues.as_dict() if cues else None,
                     "expected_scene_change_s": expected_s,
                     "expected_scene_change_is_floor": True},
            "last_crossed": dict(_last_crossed),
            "refusal": show_output.refusal()}


def reset() -> None:
    """Tests."""
    global current_uri, is_playing, _plan_uri
    _plan_uri = None
    _last_crossed.clear()
    for t in list(_tasks):
        t.cancel()
    _tasks.clear()
    current_uri = _bridge_uri
    is_playing = _bridge_playing
    _touch_music()
