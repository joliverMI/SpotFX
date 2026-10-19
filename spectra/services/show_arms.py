"""THE LIGHT SHOW's ARMS — a set (or one action) waiting for its trigger
(phase 2 of 3; plan: /home/javi/fleet-spotfx/data/light-show-plan/report.md
§5.2 and §6; his spec: "armed to execute on the next scene change ... on the
next High Trigger, or on the next Low Trigger").

SIX TRIGGERS, an open list:

  scene_change  the next REAL change to a DIFFERENT scene — any path that
                really fires one (the sequencer, a trigger, the automatic
                transition, his own Fire button), read at engine.
                on_scene_fired BEFORE the conductor takes the new scene. A
                same-scene re-fire never counts, and neither does a scene
                change the Light Show caused itself (a Forced scene or
                Fire-a-scene step) — a repeat arm would otherwise loop.
                Under Force Scene, "scene_id" here is the scene a caller
                actually asked for, not the pinned scene that actually
                fired (engine.on_scene_fired's own requested_scene_id,
                2026-10-09) — so an arm still releases at the moment a
                scene change would have happened, even while the room
                keeps wearing the pin.
  high / low    this song's High / Low Trigger (spectra/services/
                show_cues.py), crossed on the trigger clock: TriggerEngine.
                tick() asks `cue_plan()` for the song's cues and calls
                `on_cue()` exactly once per crossing (its own fired-keys
                memory, rearmed on a rewind or a song change). Independent
                of the scene-change tier — a cue exists on every analysed
                song, his own triggers or not.
  drop / lull /
  charge        this song's NEXT drop, lull or charge (PHASE_TRIGGERS, the
                Admiral 2026-10-19: "add a button for next drop, lull, and
                charge"). See THE PHASE TRIGGERS below.

FINISH ON THE MARK (an approved add-on). A set armed on High/Low that FADES
(a Device state fade, a Level fade-in) starts early by its longest fade —
counted over the steps before its first pause — so the fade COMPLETES on the
mark. The trigger clock fires the cue at the largest lead any armed set needs
and each set waits out the difference to its own, so two arms with different
fades each land on the mark. The WHOLE set moves early (an instant step in
it lands that much early too) — stated on the arm card, his to switch off
per arm. Capped at MAX_FINISH_LEAD_MS. Ambient's own ~15-22 s ease is not
a fade this counts: it is the bulbs' physics, it STARTS on the trigger.

THE PHASE TRIGGERS — "the next drop / lull / charge". Where the High and
Low come from show_cues.py, these come from the SAME drop-sequence data
the Timeline draws as gold/sky/magenta shapes: drop_firing.phase_moments
over drop_sequences.view — every firing sequence's own members plus his
own authored charge/lull/drop triggers, his winning a collision. Unlike
High/Low there can be SEVERAL of each in one song (his real EDM songs
carry a dozen drops), so `cue_plan` returns one entry per moment and an
ordinary one-shot arm fires on the FIRST one its clock crosses and is
then done — "the next drop", exactly as named. Everything else is the
High/Low path unchanged: the same `cue_plan`/`on_cue` pair, the same
exactly-once-per-crossing memory in trigger_engine._tick_show_cues, the
same show clock (`av_sync_lead` + `known_buffer` — nothing here touches
the audio offset), the same finish-on-the-mark lead, the same gate that
never consumes an arm, and the same house wrong-device gate in
services/engine._show_cue.

  THE MOMENTS ARE READ, NEVER COMPUTED HERE. `phase_moments` is a seam
  whose default asks the trigger engine for the list it already memoises
  per tick (TriggerEngine.phase_cue_moments) — the view costs a full
  triggers.json parse, and `cue_plan` is asked every tick. `None` from
  that seam means "not worked out for this song yet", which the armed
  board reports differently from an empty list ("none on this song").

  THEY ARE MODE-INDEPENDENT and sit on the MARK. A phase cue is a moment
  in the music, like a High: it is not narrowed by the room's
  scene-change tier, and it is not relocated by the drop timing offset
  (drop_timing.py, default -400 ms). drop_firing.phase_moments' own
  docstring carries the reasoning for both.

  A SONG WITH NO DROP SEQUENCES still takes the arm: it simply never
  crosses one, so the arm waits exactly as an arm on a High waits on a
  song with no High — `status()["song"]["phases"]` says so, and nothing
  about the arm is used up.

QUEUE, NOT REPLACE — EXCEPT THE SAME SET ON THE SAME TRIGGER. Several arms
wait side by side; arming the set that is already armed on that trigger
replaces the earlier arm (a double tap never stacks). Two arms on one
trigger fire in the order they were armed. A SHOW SEQUENCE's arm
(`source="sequence:<run>"`, spectra/services/show_sequence.py) and a
hand-made arm never replace each other — the sequence must not lose its
place to a tap, nor a tap to the sequence — and a sequence arm never
expires on its own (no 12 h / idle expiry): the sequence owns it. A SHOW
PLAYLIST's arm (`source="playlist:<run>"`, spectra/services/
show_playlists.py) is scripted the same way — it never replaces and is
never replaced (not even by another of the program's own steps), and has no
12 h / idle expiry — but it is SONG-SCOPED, so it still goes MISSED when
its song ends, unlike a sequence arm, which carries.

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

PHASE_TRIGGERS = ("drop", "lull", "charge")
"""The drop-sequence phases, in the order the Run view's one button cycles
through them (the Admiral's own words: "next drop, lull, and charge")."""

TRIGGERS = ("scene_change", "high", "low") + PHASE_TRIGGERS

MARK_TRIGGERS = ("high", "low") + PHASE_TRIGGERS
"""The triggers that sit at a KNOWN song-time moment — so a countdown and
the finish-on-the-mark lead both mean something. "scene_change" is the
one that does not (it fires on whichever change happens next)."""
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
#: where this song plays a charge/lull/drop — the trigger engine's own
#: per-tick memo (THE PHASE TRIGGERS above). None = not worked out yet.
phase_moments: Callable[[Optional[str]], Optional[list]]


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


def _engine_phase_moments(uri: Optional[str]) -> Optional[list]:
    """The trigger engine's already-memoised phase moments for `uri`
    (drop_firing.PhaseMoment). A tuple compare, no I/O; None whenever the
    engine has not worked this song out yet (and on any failure, which is
    the same honest "not known" rather than a fabricated empty list)."""
    try:
        from spectra.services.trigger_engine import trigger_engine
        return trigger_engine.phase_cue_moments(uri)
    except Exception:                                    # noqa: BLE001
        return None


current_uri = _bridge_uri
is_playing = _bridge_playing
phase_moments = _engine_phase_moments

_last_music_mono: float = time.monotonic()
_last_crossed: dict[str, dict] = {}
_plan_uri: Optional[str] = None
_tasks: set[asyncio.Task] = set()


class ArmError(ValueError):
    pass


def is_sequence_arm_source(source: Optional[str]) -> bool:
    return bool(source) and source.startswith("sequence:")


def is_playlist_arm_source(source: Optional[str]) -> bool:
    return bool(source) and source.startswith("playlist:")


def is_scripted_arm_source(source: Optional[str]) -> bool:
    """A sequence's or a playlist program's own arm: owned by its script,
    so the 12 h / idle clocks never end it."""
    return is_sequence_arm_source(source) or is_playlist_arm_source(source)


def _replace_class(source: Optional[str]) -> Optional[str]:
    """Arms of the same class replace each other ("same set, same
    trigger"); a playlist arm is in a class of its own (None: never)."""
    if is_playlist_arm_source(source):
        return None
    return "sequence" if is_sequence_arm_source(source) else "hand"


# ── reading ────────────────────────────────────────────────────────────────

def active_arms() -> list[ShowArm]:
    return [a for a in show_store.state().arms if a.status == ACTIVE]


def _steps(arm: ShowArm) -> list[ShowAction]:
    if arm.action is not None:
        return [arm.action]
    s = show_store.get_set(arm.set_id) if arm.set_id else None
    if s is None:
        return []
    # A called set's steps count where the call sits (show_refs: inline), so
    # a fade inside a shared "defaults" set still finishes on the mark.
    from spectra.services import show_refs
    return [e.action for e in show_refs.expand(s.actions, show_store.list_sets(),
                                               root_id=s.id) if not e.problem]


def lead_ms(arm: ShowArm) -> int:
    """How early this arm must start so its fades COMPLETE on its mark:
    the longest fade among its steps before the first pause. Every
    MARK_TRIGGERS arm (High, Low and the three phases) gets it — a phase
    sits at a known song-time moment exactly as a High does; only
    "scene_change", which has no known time, never does."""
    if not arm.finish_on_mark or arm.on not in MARK_TRIGGERS:
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
        source: str = "manual", song_uri: Optional[str] = None) -> ShowArm:
    """`song_uri` scopes the arm to that song explicitly (a playlist
    program's step); `this_song_only` scopes it to the song playing now."""
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
    song = song_uri or None
    if this_song_only and song is None:
        song = current_uri()
        if not song:
            raise ArmError("nothing is playing, so there is no song to scope this arm to")
    st = show_store.state()
    t = now_ms()
    scripted = is_scripted_arm_source(source)
    cls = _replace_class(source)
    if set_id is not None and cls is not None:
        for old in st.arms:
            if old.status == ACTIVE and old.set_id == set_id and old.on == on \
                    and _replace_class(old.source) == cls:
                _end(old, DISARMED, "replaced by a new arm of the same set on the same trigger")
    new = ShowArm(set_id=set_id, action=action, label=label, on=on,
                  repeat=bool(repeat), song_uri=song, source=source,
                  finish_on_mark=bool(finish_on_mark), created_ms=t,
                  expires_ms=None if scripted else t + ARM_MAX_AGE_S * 1000)
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
    if is_sequence_arm_source(a.source):
        try:
            from spectra.services import show_sequence
            show_sequence.on_arm_fired(a)
        except Exception:                                # noqa: BLE001
            logger.exception("light show: sequence advance after an arm fired failed")
    elif is_playlist_arm_source(a.source):
        try:
            from spectra.services import show_playlists
            show_playlists.on_arm_fired(a)
        except Exception:                                # noqa: BLE001
            logger.exception("light show: playlist outcome after an arm fired failed")


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
    _tell_sequence("scene_change")
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


def _tell_sequence(kind: str) -> None:
    """A Show Sequence's Wait counts this trigger. ONE TRIGGER, ONE STEP:
    the arms this trigger fires are chosen BEFORE the sequence is told, so a
    Wait it completes can never also fire the set armed right after it on
    the same trigger; and the sequence is told BEFORE those arms fire, so
    the trigger that completes a sequence's armed set is never also counted
    by the Wait that follows it."""
    try:
        from spectra.services import show_sequence
        show_sequence.on_trigger(kind)
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: sequence trigger hook failed")


def cue_plan(uri: Optional[str]) -> list[tuple[str, int, int]]:
    """(level, cue_ms, lead_ms) for every moment on this song the trigger
    clock watches: its High and its Low (show_cues.py), and every charge,
    lull and drop (THE PHASE TRIGGERS — several of each is normal). The
    lead is the largest any armed set on that level needs (0 with nothing
    armed). Never blocks: a song whose cues are not derived yet
    contributes none of them while they are computed in a thread, and a
    song whose phases the engine has not worked out yet contributes no
    phase."""
    global _plan_uri
    if uri != _plan_uri:
        # A new play re-derives (a setting or ranking change since the last
        # time this song played must not be served from a stale cache).
        _plan_uri = uri
        show_cues.invalidate(uri)
    arms = [a for a in active_arms() if _applies_to_song(a, uri)]

    def lead_for(level: str) -> int:
        return max((lead_ms(a) for a in arms if a.on == level), default=0)

    out: list[tuple[str, int, int]] = []
    cues = show_cues.cached(uri)
    if cues is not None:
        for level in show_cues.LEVELS:
            cue = cues.get(level)
            if cue is None:
                continue
            out.append((level, int(cue.timestamp_ms), lead_for(level)))
    for m in phase_moments(uri) or []:
        if m.cls in PHASE_TRIGGERS:
            out.append((m.cls, int(m.ms), lead_for(m.cls)))
    return out


async def on_cue(level: str, cue_ms: int, ahead_ms: int) -> list[str]:
    """The trigger clock crossed this song's High/Low (`ahead_ms` before the
    mark — the finish-on-the-mark lead it fired early by, or ~0)."""
    uri = current_uri()
    _last_crossed[level] = {"uri": uri, "cue_ms": cue_ms, "at_ms": now_ms()}
    arms = sorted((a for a in active_arms()
                   if a.on == level and _applies_to_song(a, uri)),
                  key=lambda a: a.created_ms)
    _tell_sequence(level)
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
        if is_sequence_arm_source(a.source):
            continue                     # the sequence owns its arm's life
        if is_playlist_arm_source(a.source):
            # the program owns its arm's life, but it is song-scoped: the
            # runner ends it MISSED on a song change; this is the backstop
            if a.song_uri is not None and uri is not None and uri != a.song_uri:
                _end(a, MISSED, "its song ended before the trigger")
                changed = True
            continue
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

def _source_tag(source: Optional[str]) -> Optional[str]:
    """Where a scripted arm came from, in his words ("Playlist · 40!
    Lightshow", "Sequence · Standard Start"), for the armed board."""
    try:
        if is_playlist_arm_source(source):
            r = show_store.state().playlist_run
            name = r.name if r is not None and source == f"playlist:{r.id}" else "a program"
            return f"Playlist · {name}"
        if is_sequence_arm_source(source):
            r = show_store.state().sequence_run
            name = r.name if r is not None and source == f"sequence:{r.id}" else "a sequence"
            return f"Sequence · {name}"
        if source and source.startswith("playlist-end:"):
            return "Playlist end"
    except Exception:                                    # noqa: BLE001
        return None
    return None


def phase_summary(uri: Optional[str], position_ms: Optional[int] = None) -> dict:
    """This song's charge/lull/drop for the armed board: the NEXT moment of
    each class ahead of `position_ms` (the first one when the position is
    unknown), how many the song holds at all, and a `reason` when there is
    nothing to say yet — the phase half of `song.cues`, read the same way
    an arm board reads "none on this song" for a missing High.

    `known` tells the two empty cases apart: False while the engine has
    not worked this song out yet, True when it has and the song genuinely
    plays no charge, lull or drop."""
    moments = phase_moments(uri) if uri else None
    out: dict = {"known": moments is not None, "next": {}, "counts": {},
                 "reason": None}
    for cls in PHASE_TRIGGERS:
        mine = sorted((int(m.ms) for m in (moments or []) if m.cls == cls))
        out["counts"][cls] = len(mine)
        ahead = [ms for ms in mine
                 if position_ms is None or ms > position_ms]
        out["next"][cls] = ahead[0] if ahead else None
    if moments is None:
        out["reason"] = ("this song's drops have not been worked out yet"
                         if uri else "nothing is playing")
    elif not any(out["counts"].values()):
        out["reason"] = "this song has no charge, lull or drop"
    return out


def status() -> dict:
    """The armed board: every waiting arm (with its lead and the next time
    its trigger is due on this song, when known), recent history, and this
    song's High/Low and its charge/lull/drop for the countdowns."""
    uri = current_uri()
    cues = show_cues.cached(uri) if uri else None
    position = None
    try:
        from spectra.services.trigger_engine import trigger_engine
        if trigger_engine._uri == uri:
            position = trigger_engine._last_position_ms
    except Exception:                                    # noqa: BLE001
        pass
    phases = phase_summary(uri, position)
    waiting = []
    for a in sorted(active_arms(), key=lambda a: a.created_ms):
        row = a.model_dump()
        row["lead_ms"] = lead_ms(a)
        row["this_song"] = _applies_to_song(a, uri)
        due = None
        if row["this_song"]:
            mark = None
            if a.on in ("high", "low") and cues is not None:
                cue = cues.get(a.on)
                if cue is not None and (position is None or cue.timestamp_ms > position):
                    mark = int(cue.timestamp_ms)
            elif a.on in PHASE_TRIGGERS:
                # the NEXT one of its class ahead of the playhead — a song
                # can hold a dozen drops, and a one-shot arm takes the first
                mark = phases["next"].get(a.on)
            if mark is not None:
                due = mark - row["lead_ms"]
        row["due_ms"] = due
        row["tag"] = _source_tag(a.source)
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
                     "phases": phases,
                     "expected_scene_change_s": expected_s,
                     "expected_scene_change_is_floor": True},
            "last_crossed": dict(_last_crossed),
            "refusal": show_output.refusal()}


def reset() -> None:
    """Tests."""
    global current_uri, is_playing, phase_moments, _plan_uri
    _plan_uri = None
    _last_crossed.clear()
    for t in list(_tasks):
        t.cancel()
    _tasks.clear()
    current_uri = _bridge_uri
    is_playing = _bridge_playing
    phase_moments = _engine_phase_moments
    _touch_music()
