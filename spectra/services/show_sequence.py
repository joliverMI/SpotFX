"""THE SHOW SEQUENCE RUNNER — a sequence of pre-armed sets, run in order
(the Admiral, 2026-10-09: "A 'Show Sequence' is a sequence of pre-armed
sets ... When we run a show sequence, it goes in order, running the sets
when they trigger, but never skipping ahead").

WHAT A SEQUENCE IS (spectra/models/light_show.py): a name and an ordered
list of items. An item is a SET plus how it is armed — `instant`,
`scene_change`, `high`, `low`, the same four timings as the Run view's
one-tap buttons — or a WAIT: a fixed time, a count of one trigger kind
(scene changes / High Triggers / Low Triggers), a count of songs, or "until
one of these songs plays".

STRICTLY IN ORDER. Exactly one item is current. Item k is armed only once
item k-1 has COMPLETED, and nothing about item k+1 exists until then:

  * a Set item ARMS THROUGH show_arms.arm() — the very call the Run view's
    bunny / up / down buttons make — and completes when that arm FIRES
    (`on_arm_fired`, called from show_arms._fire). An instant item fires
    through show_actions.fire_set(), the bolt's own call, and completes
    when the fire returns (every step up to its first pause has landed; a
    set's own pauses keep running in the background, exactly as a bolt
    press does). A sequence arm is an ordinary arm on the armed board,
    tagged `source="sequence:<run id>"`, exempt from the board's 12 h /
    30-min-idle expiry and from "same set, same trigger replaces"
    (show_arms) — so a manual arm and the sequence's never cancel each
    other.
  * A Wait COUNTS ONLY WHILE IT IS CURRENT. The trigger that completed the
    previous item happened before this Wait existed, so it is never
    counted (show_arms reports a trigger to `on_trigger` synchronously,
    before the arm it fires has run). A trigger crossing while the Light
    Show is standing down (`show_output.refusal()`, the ONE gate every show
    step asks) is not counted either — the show could not act on it, so a
    Wait counting it would run ahead of the sets it gates.
  * Songs are counted on a song START after the Wait became current
    (`on_track_change`, from engine._on_track_uri). A song-list Wait is
    satisfied by a listed song starting — or by a listed song ALREADY
    playing when it becomes current (SONG_LIST_ACCEPTS_PLAYING).

THE HUMAN OVERRIDE: pause / resume, stop, Next (skip the current item
unfired), Previous (back one item, re-armed; an instant item stepped back
onto waits for Fire now rather than firing by surprise), Fire now (run the
current Set item at once, whatever its arming, and move on). Pause disarms
the current arm and freezes a duration Wait's remaining time; triggers and
songs that pass while paused are not counted.

END: the run FINISHES after its last item, or — with `loop` on and at least
one item that waits for something — starts again from the top.

ONE AT A TIME. Starting a sequence while another runs is refused by name;
`replace=True` stops the running one first.

THE ROOM. A room release PAUSES the run, named, before show_arms expires
its arm (show_output.on_release). Nothing here takes or releases the room;
an instant fire refused by the gate leaves the item current with the reason
and is retried on the next supervisor tick.

RESTART. The run lives in light_show_state.json (show_store), and so does
its arm. On the first supervisor tick of a new process a running sequence
RESUMES AT ITS CURRENT ITEM, logged as such: a duration Wait keeps its wall
deadline, counts are kept, an arm that did not survive is re-armed, and an
instant item that had not fired fires. `last_uri` stops the song still
playing from counting as a new song start. A run that was mid-instant-fire
when the process died had not been marked fired, so it fires once more —
stated in the log, the honest bound.

Every step is in the show log (`fire_history`, bucket "show", kinds
`sequence_*`) and in the run's own `log` (the Run view's history).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from spectra.models.light_show import (SEQUENCE_ARMS, WAIT_KINDS, WAIT_TRIGGERS,
                                       SequenceItem, SequenceRun, ShowSequence,
                                       now_ms)
from spectra.services import show_store

logger = logging.getLogger(__name__)

RUNNING = "running"
PAUSED = "paused"
FINISHED = "finished"
STOPPED = "stopped"
ACTIVE_STATES = (RUNNING, PAUSED)

SONG_LIST_ACCEPTS_PLAYING = True
"""A song-list Wait is satisfied at once when a listed song is already
playing as it becomes current (he likely lined that song up)."""

LOG_KEPT = 60
MAX_WAIT_SECONDS = 6 * 3600
MAX_WAIT_COUNT = 500
TRIGGER_WORDS = {"scene_change": ("scene change", "scene changes"),
                 "high": ("High Trigger", "High Triggers"),
                 "low": ("Low Trigger", "Low Triggers")}
ARM_WORDS = {"instant": "fires at once", "scene_change": "next scene change",
             "high": "next High Trigger", "low": "next Low Trigger"}

_tasks: set[asyncio.Task] = set()
_resumed_after_load = False


class SequenceError(ValueError):
    pass


# ── validation ─────────────────────────────────────────────────────────────

def item_problems(item: SequenceItem) -> list[str]:
    out: list[str] = []
    if item.kind == "set":
        if item.arm not in SEQUENCE_ARMS:
            out.append(f"unknown arming {item.arm!r}")
        if not item.set_id:
            out.append("no set chosen")
        else:
            s = show_store.get_set(item.set_id)
            if s is None:
                out.append("its set no longer exists")
            elif not s.actions:
                out.append(f"set {s.name!r} has no steps")
    elif item.kind == "wait":
        w = item.wait
        if w is None or w.kind not in WAIT_KINDS:
            out.append("a Wait needs a kind")
        elif w.kind == "duration" and not (0 < w.seconds <= MAX_WAIT_SECONDS):
            out.append("a timed Wait needs between 1 second and 6 hours")
        elif w.kind == "trigger_count" and (w.trigger not in WAIT_TRIGGERS
                                            or not 1 <= w.count <= MAX_WAIT_COUNT):
            out.append("a trigger Wait needs a trigger and a count of at least 1")
        elif w.kind == "songs" and not 1 <= w.count <= MAX_WAIT_COUNT:
            out.append("a songs Wait needs a count of at least 1")
        elif w.kind == "song_list" and not w.songs:
            out.append("a song-list Wait needs at least one song")
    else:
        out.append(f"unknown item kind {item.kind!r}")
    return out


def problems(seq: ShowSequence) -> list[str]:
    out = []
    for i, it in enumerate(seq.items):
        for p in item_problems(it):
            out.append(f"item {i + 1} ({item_title(it)}): {p}")
    if seq.loop and seq.items and not _has_a_wait(seq.items):
        out.append("Loop needs at least one item that waits for something "
                   "(an armed set or a Wait), or it would never stop")
    return out


def _has_a_wait(items: list[SequenceItem]) -> bool:
    return any(it.kind == "wait" or it.arm != "instant" for it in items)


# ── words ──────────────────────────────────────────────────────────────────

def _plural(n: int, pair: tuple[str, str]) -> str:
    return f"{n} {pair[0] if n == 1 else pair[1]}"


def _clock(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _song_word(ref) -> str:
    t = ref.title or ref.uri
    return f"{t} — {ref.artist}" if ref.artist else t


def item_title(item: SequenceItem) -> str:
    """One line naming an item, his label first."""
    if item.label:
        return item.label
    if item.kind == "set":
        s = show_store.get_set(item.set_id) if item.set_id else None
        name = s.name if s else "(missing set)"
        return f"{name} — {ARM_WORDS.get(item.arm, item.arm)}"
    w = item.wait
    if w is None:
        return "Wait"
    if w.kind == "duration":
        return f"Wait {_clock(w.seconds)}"
    if w.kind == "trigger_count":
        return f"Wait for {_plural(w.count, TRIGGER_WORDS.get(w.trigger, (w.trigger, w.trigger)))}"
    if w.kind == "songs":
        return f"Wait for {_plural(w.count, ('song', 'songs'))}"
    if w.kind == "song_list":
        return f"Wait for one of {len(w.songs)} song{'s' if len(w.songs) != 1 else ''}"
    return "Wait"


def waiting_for(run: SequenceRun) -> str:
    """What the current item is waiting for, in his words — the Run view's
    headline for the highlighted item."""
    item = _current(run)
    if item is None:
        return ""
    if run.state == PAUSED:
        return f"paused — {run.paused_reason}" if run.paused_reason else "paused"
    gate = f" (waiting: {run.waiting_reason})" if run.waiting_reason else ""
    if item.kind == "set":
        if run.awaiting_fire:
            return "ready — tap Fire now, or Next to skip it"
        if item.arm == "instant":
            return ("firing…" if run.firing else "about to fire") + gate
        return f"armed for the {ARM_WORDS[item.arm]}{gate}"
    w = item.wait
    if w.kind == "duration":
        left = ((run.wait_deadline_ms or now_ms()) - now_ms()) / 1000.0
        return f"waiting {_clock(left)} more"
    if w.kind == "trigger_count":
        left = max(0, w.count - run.wait_count)
        more = "" if left == w.count else " more"
        word = TRIGGER_WORDS[w.trigger]
        return f"waiting for {left}{more} {word[0] if left == 1 else word[1]}"
    if w.kind == "songs":
        left = max(0, w.count - run.wait_count)
        more = "" if left == w.count else " more"
        return f"waiting for {left}{more} song{'s' if left != 1 else ''} to start"
    if w.kind == "song_list":
        names = ", ".join(_song_word(s) for s in w.songs[:6])
        extra = f" (+{len(w.songs) - 6} more)" if len(w.songs) > 6 else ""
        return f"waiting for one of: {names}{extra}"
    return ""


# ── state helpers ──────────────────────────────────────────────────────────

def run() -> Optional[SequenceRun]:
    return show_store.state().sequence_run


def _active() -> Optional[SequenceRun]:
    r = run()
    return r if r is not None and r.state in ACTIVE_STATES else None


def _current(r: SequenceRun) -> Optional[SequenceItem]:
    return r.items[r.index] if 0 <= r.index < len(r.items) else None


def _save() -> None:
    show_store.save_state()
    _notify()


def _notify() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def push():
        try:
            from spectra.services.ws import ws_manager
            await ws_manager.broadcast({"type": "light_show_sequence", "run": status()["run"]})
        except Exception:                                # noqa: BLE001
            pass
    _spawn(loop, push())


def _spawn(loop, coro) -> asyncio.Task:
    task = loop.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def _log(r: SequenceRun, what: str, detail: str = "", **data: Any) -> None:
    item = _current(r)
    entry = {"at_ms": now_ms(), "what": what, "index": r.index,
             "item": item_title(item) if item else "", "detail": detail, **data}
    r.log.append(entry)
    del r.log[:-LOG_KEPT]
    try:
        from spectra.services import fire_history
        fire_history.record_fire("show", f"sequence_{what}", {
            "sequence": r.name, "run": r.id, **{k: v for k, v in entry.items()
                                                 if k != "at_ms"}})
    except Exception:                                    # noqa: BLE001
        pass


def _refusal() -> Optional[str]:
    from spectra.services import show_output
    return show_output.refusal()


def _playing_uri() -> Optional[str]:
    from spectra.services import show_arms
    return show_arms.current_uri()


def _clear_item(r: SequenceRun) -> None:
    r.arm_id = None
    r.fired = False
    r.firing = False
    r.awaiting_fire = False
    r.waiting_reason = ""
    r.wait_count = 0
    r.wait_deadline_ms = None
    r.wait_remaining_ms = None
    r.item_entered_ms = None


def _disarm(r: SequenceRun, reason: str) -> None:
    if not r.arm_id:
        return
    from spectra.services import show_arms
    a = next((x for x in show_arms.active_arms() if x.id == r.arm_id), None)
    if a is not None:
        show_arms._end(a, show_arms.DISARMED, reason)
        show_arms._save()
    r.arm_id = None


# ── entering an item ───────────────────────────────────────────────────────

def _enter(r: SequenceRun, *, manual_back: bool = False, keep_progress: bool = False) -> None:
    """Make item `r.index` current and start waiting for it. With
    `keep_progress` (resume / restart) counts and the remaining time are
    kept rather than started fresh."""
    if r.index >= len(r.items):
        _end_of_sequence(r)
        return
    item = _current(r)
    if not keep_progress:
        _clear_item(r)
        r.item_entered_ms = now_ms()
        _log(r, "entered")
    if item.kind == "set":
        if item.arm == "instant":
            if manual_back:
                r.awaiting_fire = True
                return
            if r.fired:
                # it fired while the run was paused (an in-flight fire that
                # landed after Pause): it is done, move on
                _complete(r, "fired")
                return
            if not r.awaiting_fire:
                _fire_instant(r)
            return
        _arm(r, item)
        return
    w = item.wait
    if w.kind == "duration":
        if keep_progress and r.wait_remaining_ms is not None:
            r.wait_deadline_ms = now_ms() + r.wait_remaining_ms
            r.wait_remaining_ms = None
        elif r.wait_deadline_ms is None:
            r.wait_deadline_ms = now_ms() + int(w.seconds * 1000)
    elif w.kind == "song_list" and not keep_progress and SONG_LIST_ACCEPTS_PLAYING:
        uri = _playing_uri()
        if uri and any(s.uri == uri for s in w.songs):
            _complete(r, "a listed song was already playing", song=uri)


def _arm(r: SequenceRun, item: SequenceItem) -> None:
    from spectra.services import show_arms
    if r.arm_id and any(a.id == r.arm_id for a in show_arms.active_arms()):
        return
    try:
        a = show_arms.arm(set_id=item.set_id, on=item.arm,
                          source=f"sequence:{r.id}")
    except show_arms.ArmError as exc:
        _pause(r, f"item {r.index + 1} could not be armed: {exc}")
        return
    r.arm_id = a.id
    r.waiting_reason = ""


def _fire_instant(r: SequenceRun) -> None:
    item = _current(r)
    reason = _refusal()
    if reason:
        r.waiting_reason = reason
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        r.waiting_reason = "waiting for the engine to run"
        return
    r.firing = True
    r.waiting_reason = ""
    run_id, index = r.id, r.index

    async def go():
        from spectra.services import show_actions
        outcome: dict = {}
        try:
            res = await show_actions.fire_set(item.set_id, source=f"sequence:{run_id}")
            outcome = {"run": res.get("id"), "run_state": res.get("state")}
        except Exception as exc:                         # noqa: BLE001
            logger.exception("show sequence: instant fire failed")
            outcome = {"error": str(exc)}
        cur = _active()
        if cur is None or cur.id != run_id or cur.index != index:
            return
        cur.firing = False
        cur.fired = True
        if cur.state != RUNNING:
            _save()
            return
        _complete(cur, "fired", **outcome)
        _save()
    _spawn(loop, go())


def _complete(r: SequenceRun, detail: str, **data: Any) -> None:
    """The current item is done: log it and move to the next."""
    _log(r, "completed", detail, **data)
    r.arm_id = None
    r.index += 1
    _enter(r)


def _end_of_sequence(r: SequenceRun) -> None:
    if r.loop and r.items and _has_a_wait(r.items):
        r.loops_done += 1
        r.index = 0
        _log(r, "looped", f"pass {r.loops_done + 1}")
        _enter(r)
        return
    r.index = len(r.items)
    _clear_item(r)
    r.state = FINISHED
    r.ended_ms = now_ms()
    r.end_reason = "every item ran"
    _log(r, "finished")


def _pause(r: SequenceRun, reason: str) -> None:
    item = _current(r)
    _disarm(r, "the sequence paused")
    if item is not None and item.kind == "wait" and item.wait.kind == "duration" \
            and r.wait_deadline_ms is not None:
        r.wait_remaining_ms = max(0, r.wait_deadline_ms - now_ms())
        r.wait_deadline_ms = None
    r.state = PAUSED
    r.paused_reason = reason
    _log(r, "paused", reason)


# ── controls ───────────────────────────────────────────────────────────────

def start(seq_id_or_name: str, *, replace: bool = False, source: str = "button") -> SequenceRun:
    global _resumed_after_load
    _resumed_after_load = True       # a run begun in this process needs no resume
    seq = show_store.find_sequence(seq_id_or_name)
    if seq is None:
        raise SequenceError(f"no sequence called {seq_id_or_name!r}")
    if not seq.items:
        raise SequenceError(f"sequence {seq.name!r} has no items")
    bad = problems(seq)
    if bad:
        raise SequenceError("fix these first: " + "; ".join(bad))
    cur = _active()
    if cur is not None:
        if not replace:
            raise SequenceError(f"{cur.name!r} is already running — stop it first")
        stop(reason=f"replaced by {seq.name!r}")
    r = SequenceRun(sequence_id=seq.id, name=seq.name,
                    items=[it.model_copy(deep=True) for it in seq.items],
                    loop=seq.loop, last_uri=_playing_uri())
    show_store.state().sequence_run = r
    _log(r, "started", f"by {source}")
    _enter(r)
    _save()
    return r


def _require(states=ACTIVE_STATES) -> SequenceRun:
    r = run()
    if r is None or r.state not in states:
        raise SequenceError("no sequence is running")
    return r


def pause(reason: str = "paused by hand") -> SequenceRun:
    r = _require((RUNNING,))
    _pause(r, reason)
    _save()
    return r


def resume() -> SequenceRun:
    r = _require((PAUSED,))
    r.state = RUNNING
    r.paused_reason = ""
    _log(r, "resumed")
    if r.awaiting_fire:
        r.awaiting_fire = False
    _enter(r, keep_progress=True)
    _save()
    return r


def stop(reason: str = "stopped by hand") -> SequenceRun:
    r = _require()
    _disarm(r, "the sequence stopped")
    r.state = STOPPED
    r.ended_ms = now_ms()
    r.end_reason = reason
    _log(r, "stopped", reason)
    r.firing = False
    _save()
    return r


def next_item() -> SequenceRun:
    """Skip the current item without running it."""
    r = _require()
    if r.index >= len(r.items):
        raise SequenceError("already past the last item")
    _disarm(r, "skipped by hand")
    _log(r, "skipped", "Next pressed")
    r.index += 1
    if r.state == RUNNING:
        _enter(r)
    else:
        _clear_item(r)
        if r.index >= len(r.items):
            _end_of_sequence(r)
    _save()
    return r


def previous_item() -> SequenceRun:
    """Back one item (nothing it did is undone); it is re-armed. An instant
    item stepped back onto waits for Fire now."""
    r = _require()
    if r.index <= 0:
        raise SequenceError("already at the first item")
    _disarm(r, "stepped back by hand")
    _log(r, "stepped_back", "Previous pressed")
    r.index -= 1
    _clear_item(r)
    r.item_entered_ms = now_ms()
    _log(r, "entered", "by Previous")
    if r.state == RUNNING:
        _enter(r, manual_back=True, keep_progress=True)
    else:
        item = _current(r)
        r.awaiting_fire = item.kind == "set" and item.arm == "instant"
    _save()
    return r


async def fire_now() -> SequenceRun:
    """Run the current Set item at once, whatever its arming, and move on.
    On a Wait it means "the wait is over"."""
    from spectra.services import show_actions
    r = _require((RUNNING,))
    item = _current(r)
    if item is None:
        raise SequenceError("nothing is current")
    if item.kind == "wait":
        _complete(r, "ended by hand")
        _save()
        return r
    reason = _refusal()
    if reason:
        raise SequenceError(f"The Light Show is standing down: {reason}")
    _disarm(r, "fired by hand from the sequence")
    run_id, index = r.id, r.index
    r.firing = True
    try:
        res = await show_actions.fire_set(item.set_id, source=f"sequence:{run_id}")
        outcome = {"run": res.get("id"), "run_state": res.get("state")}
    except show_actions.ActionError as exc:
        r.firing = False
        raise SequenceError(str(exc))
    cur = _active()
    if cur is None or cur.id != run_id or cur.index != index:
        return r
    cur.firing = False
    cur.fired = True
    _complete(cur, "fired by hand (Fire now)", **outcome)
    _save()
    return cur


# ── events ─────────────────────────────────────────────────────────────────

def on_arm_fired(arm) -> None:
    """show_arms._fire, after a set armed by this run has fired."""
    r = _active()
    if r is None or r.state != RUNNING or not arm.source.startswith("sequence:"):
        return
    if r.arm_id != arm.id:
        return
    outcome = arm.last_outcome or {}
    _complete(r, f"fired on the {ARM_WORDS.get(arm.on, arm.on)}",
              run_state=outcome.get("run_state") or outcome.get("status"))
    _save()


def on_trigger(kind: str) -> None:
    """show_arms: a real scene change, or this song's High/Low crossed."""
    r = _active()
    if r is None or r.state != RUNNING:
        return
    item = _current(r)
    if item is None or item.kind != "wait" or item.wait.kind != "trigger_count" \
            or item.wait.trigger != kind:
        return
    if _refusal():
        return
    r.wait_count += 1
    if r.wait_count >= item.wait.count:
        _complete(r, f"counted {_plural(item.wait.count, TRIGGER_WORDS[kind])}")
    else:
        _log(r, "counted", f"{r.wait_count} of {item.wait.count}")
    _save()


def on_track_change(uri: Optional[str]) -> None:
    """engine._on_track_uri: a different song started."""
    r = _active()
    if r is None or not uri or uri == r.last_uri:
        return
    r.last_uri = uri
    if r.state != RUNNING:
        show_store.save_state()
        return
    item = _current(r)
    if item is None or item.kind != "wait":
        show_store.save_state()
        return
    w = item.wait
    if w.kind == "songs":
        r.wait_count += 1
        if r.wait_count >= w.count:
            _complete(r, f"{_plural(w.count, ('song', 'songs'))} started", song=uri)
        else:
            _log(r, "counted", f"{r.wait_count} of {w.count} songs", song=uri)
    elif w.kind == "song_list":
        hit = next((s for s in w.songs if s.uri == uri), None)
        if hit is not None:
            _complete(r, f"{_song_word(hit)} started", song=uri)
    _save()


def on_release() -> None:
    """The room is being released (show_output.on_release, before the arms
    expire): pause, named."""
    r = _active()
    if r is None or r.state != RUNNING:
        return
    _pause(r, "the room was released — resume when SPECTRA holds it again")
    _save()


def tick() -> None:
    """The Light Show supervisor's pass: the restart resume, a duration
    Wait's deadline, a refused instant fire's retry, and an arm that ended
    without firing."""
    global _resumed_after_load
    r = _active()
    if r is None:
        _resumed_after_load = True
        return
    if not _resumed_after_load:
        _resumed_after_load = True
        if r.state == RUNNING:
            _log(r, "resumed", "after a restart, at its current item")
            r.firing = False
            _enter(r, keep_progress=True)
            _save()
            return
    if r.state != RUNNING:
        return
    item = _current(r)
    if item is None:
        return
    changed = False
    if item.kind == "wait" and item.wait.kind == "duration":
        if r.wait_deadline_ms is not None and now_ms() >= r.wait_deadline_ms:
            _complete(r, f"waited {_clock(item.wait.seconds)}")
            changed = True
    elif item.kind == "set" and item.arm == "instant":
        if not r.fired and not r.firing and not r.awaiting_fire:
            before = r.waiting_reason
            _fire_instant(r)
            changed = before != r.waiting_reason or r.firing
    elif item.kind == "set" and r.arm_id:
        from spectra.services import show_arms
        arm = next((a for a in show_store.state().arms if a.id == r.arm_id), None)
        if arm is None or arm.status != show_arms.ACTIVE:
            if arm is not None and arm.status == show_arms.FIRED:
                _complete(r, f"fired on the {ARM_WORDS.get(arm.on, arm.on)}")
            else:
                why = arm.end_reason if arm is not None else "it vanished"
                _pause(r, f"its arm ended without firing ({why})")
            changed = True
        else:
            wait = (arm.last_outcome or {}).get("reason") \
                if (arm.last_outcome or {}).get("status") == "waiting" else ""
            if wait != r.waiting_reason:
                r.waiting_reason = wait or ""
                changed = True
    if changed:
        _save()


# ── status ─────────────────────────────────────────────────────────────────

def run_view(r: Optional[SequenceRun]) -> Optional[dict]:
    if r is None:
        return None
    d = r.model_dump()
    d["items"] = [{**it.model_dump(), "title": item_title(it)} for it in r.items]
    d["waiting_for"] = waiting_for(r) if r.state in ACTIVE_STATES else ""
    d["active"] = r.state in ACTIVE_STATES
    d["log"] = list(reversed(r.log))
    if r.wait_deadline_ms is not None:
        d["wait_left_s"] = max(0.0, (r.wait_deadline_ms - now_ms()) / 1000.0)
    elif r.wait_remaining_ms is not None:
        d["wait_left_s"] = r.wait_remaining_ms / 1000.0
    return d


def status() -> dict:
    from spectra.services import show_output
    return {"run": run_view(run()), "refusal": show_output.refusal(),
            "playing_uri": _playing_uri()}


def reset() -> None:
    """Tests."""
    global _resumed_after_load
    for t in list(_tasks):
        t.cancel()
    _tasks.clear()
    _resumed_after_load = False
