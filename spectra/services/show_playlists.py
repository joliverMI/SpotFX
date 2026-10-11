"""THE SHOW PLAYLIST RUNNER — a program keyed to the Spotify playlist he
plays (the Admiral, 2026-10-11: "Let's make a detailed plan for the
playlist system"; earlier: "I use a playlist and make a script through the
playlist so that when a specific song is played, it arms an action to fire
on the given High/Low Trigger"; plan: /home/javi/fleet-spotfx/data/
playlist-plan/report.md, phases 0-1).

FOLLOW, NEVER DRIVE. A Show Playlist (spectra/models/light_show.py) is a map
song -> steps (a set and a timing), applied when that song STARTS. Spotify
owns the order; nothing here starts, queues, skips or changes playback, so
shuffle, skips, repeats and starting the playlist in the middle need
nothing special. The thing he plays stays his Spotify playlist on Serenity.

ACTIVATION. On every bridge state (`on_state`, from engine._on_track_uri)
the runner sees the playing song and its Spotify context (SpotFX already
reads `context_uri` off Spotify's playback and broadcasts it; the bridge's
`context_uri()` reads it). With the library's global "Follow playlists"
switch on, a program with auto-follow on becomes active when:

  * one of its contexts starts playing (`via="context"`), or
  * with "follow songs anywhere" on, a song it lists starts from any other
    context (`via="song"`) — Liked Songs on shuffle;

or by hand / Sonic / Home Assistant (`start`, `via="manual"`), in which
case it follows whatever plays. On becoming active its ON-START runs first
(the spine sequence starts if one is named — refused and logged when
another sequence is running, unless the program says replace — and its
steps fire or arm), then the playing song's entry. ON-START RUNS ON
ENTERING THE CONTEXT, whichever track it entered on (D4).

EACH SONG (a song START: a URI different from the run's `last_uri`, or a
rewind to under REWIND_REAPPLY_MS into the same song after it had played
past REWIND_MIN_PLAYED_MS — D7, and the honest limit: a repeat Spotify
reports with no position drop is not seen):

  1. the previous song's unfired arms end MISSED, named;
  2. the song is looked up: a listed entry, else the default entry (when
     `unlisted_song` is "default"), else nothing — which one is recorded
     on the run and shown;
  3. one ARM per enabled step (`show_arms.arm`, the Run view's own call,
     `song_uri` set, `source="playlist:<run id>"`); a `song_start` step is
     queued and FIRES once the song's opening scene change has gone
     through (`after_track_state`) — fired earlier, its run would be "the
     show executing" when the opening transition lands and that transition
     would not count for this song's "next scene change" arms.

THE ARMS ARE CREATED BEFORE THE SONG'S OPENING SCENE CHANGE (his answer to
the plan's Q2, verbatim: "count it even if it's the first scene change on a
new song"). `on_state` runs before scene_sequencer / trigger_engine see the
new URI, so a "next scene change" step fires on the automatic song-start
transition when there is one. The opening change is a real scene change;
on a song whose opening change is silenced (My triggers only on a song he
has authored) the step waits for the first one inside the song.

PROGRAM ARMS OBEY THE BOARD (spectra/services/show_arms.py) with the
scripted-source exceptions sequence arms already have: they never replace,
and are never replaced by, a hand-made arm, and they do not expire on the
12 h / idle clocks. Unlike sequence arms they DO go MISSED when their song
ends. On-start arms (no song) live until the run ends; on-end arms are
ordinary arms (`source="playlist-end:<run id>"`) that expire like any.

LEAVING. A run following its context ends (ON-END runs: steps fire or arm,
End show if the program says so) when the context changes to one the
program does not answer to — a song it lists keeps a follow-anywhere
program going — or when nothing has played for ARM_IDLE_EXPIRY_S (30 min,
the board's own number). Pausing the music is not leaving.

STOP FOLLOWING disarms the program's arms and leaves every hold and
setting as the sets left them (End show is the separate button it always
was); ON-END does not run. While that playlist keeps playing auto-follow
does not start it again (`blocked_context`), until the context changes.

THE ROOM. Every fire and arm goes through the Light Show's ONE gate
(`show_output.refusal()`): while SPECTRA does not hold the room, or a
preview / camera run / night run has it, an arm waits and says so, and a
song-start fire is refused and recorded. A room release PAUSES the run,
named, before show_arms expires its arms (show_output.on_release); Resume
re-applies the playing song's entry. Nothing here takes or releases the
room.

RESTART. The run and its arms live in light_show_state.json. A following
run resumes as it was on the first supervisor tick; `last_uri` stops the
song still playing from counting as a new start (its arms persisted with
it). A song-start fire queued in the instant before a crash is lost —
stated, the honest bound.

Every start, song, fire, miss and end is in the show log (`fire_history`,
bucket "show", kinds `playlist_*`) and on the run's own `log`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from spectra.models.light_show import (PLAYLIST_STEP_TIMINGS, UNLISTED_SONG,
                                       PlaylistRun, PlaylistStep, ShowPlaylist,
                                       SongEntry, StepOutcome, now_ms)
from spectra.services import show_store

logger = logging.getLogger(__name__)

FOLLOWING = "following"
PAUSED = "paused"
STOPPED = "stopped"
ENDED = "ended"
ACTIVE_STATES = (FOLLOWING, PAUSED)

SOURCE_PREFIX = "playlist:"
END_SOURCE_PREFIX = "playlist-end:"
REWIND_REAPPLY_MS = 5_000
REWIND_MIN_PLAYED_MS = 10_000
IDLE_END_S = 30 * 60
LOG_KEPT = 80
SONGS_SEEN_KEPT = 60

TIMING_WORDS = {"song_start": "song start", "scene_change": "next scene change",
                "high": "High Trigger", "low": "Low Trigger"}

#: injectable seams (production reads the bridge; tests replace them)
current_context: Callable[[], Optional[str]]
now_playing: Callable[[], tuple[str, str]]


def _bridge_context() -> Optional[str]:
    try:
        from spectra.services import engine
        return engine.bridge.context_uri()
    except Exception:                                    # noqa: BLE001
        return None


def _bridge_now_playing() -> tuple[str, str]:
    try:
        from spectra.services import engine
        t = engine.bridge._track or {}
        return (t.get("title") or "", t.get("artist") or "")
    except Exception:                                    # noqa: BLE001
        return ("", "")


current_context = _bridge_context
now_playing = _bridge_now_playing

_tasks: set[asyncio.Task] = set()
_pending_song_start: list[tuple[str, str, StepOutcome]] = []   # (run id, song uri, outcome)
_last_pos: dict[str, int] = {}
_last_music_mono: float = time.monotonic()
_resumed_after_load = False


class PlaylistError(ValueError):
    pass


def is_playlist_source(source: Optional[str]) -> bool:
    return bool(source) and source.startswith(SOURCE_PREFIX)


# ── validation ─────────────────────────────────────────────────────────────

def step_problems(step: PlaylistStep) -> list[str]:
    out = []
    if step.on not in PLAYLIST_STEP_TIMINGS:
        out.append(f"unknown timing {step.on!r}")
    if not step.set_id:
        out.append("no set chosen")
    else:
        s = show_store.get_set(step.set_id)
        if s is None:
            out.append("its set no longer exists")
        elif not s.actions:
            out.append(f"set {s.name!r} has no steps")
    return out


def problems(pl: ShowPlaylist) -> list[str]:
    out: list[str] = []
    if pl.unlisted_song not in UNLISTED_SONG:
        out.append(f"unknown choice for unlisted songs {pl.unlisted_song!r}")
    if pl.on_start.sequence_id and show_store.get_sequence(pl.on_start.sequence_id) is None:
        out.append("on start: its sequence no longer exists")

    def steps(where: str, items: list[PlaylistStep]) -> None:
        for i, st in enumerate(items):
            for p in step_problems(st):
                out.append(f"{where}, step {i + 1}: {p}")
    steps("on start", pl.on_start.steps)
    steps("on end", pl.on_end.steps)
    if pl.default_song is not None:
        steps("default for other songs", pl.default_song.steps)
    seen: set[str] = set()
    for e in pl.songs:
        name = e.title or e.uri or "a song"
        if not e.uri:
            out.append(f"{name}: no song chosen")
        elif e.uri in seen:
            out.append(f"{name}: listed twice")
        seen.add(e.uri)
        steps(name, e.steps)
    return out


# ── words ──────────────────────────────────────────────────────────────────

def _set_name(set_id: Optional[str]) -> str:
    s = show_store.get_set(set_id) if set_id else None
    return s.name if s else "(missing set)"


def step_title(step: PlaylistStep) -> str:
    if step.label:
        return step.label
    return f"{_set_name(step.set_id)} — {TIMING_WORDS.get(step.on, step.on)}"


def _song_word(title: str, artist: str, uri: Optional[str]) -> str:
    t = title or uri or "a song"
    return f"{t} — {artist}" if artist else t


def entry_summary(entry: Optional[SongEntry]) -> str:
    if entry is None:
        return ""
    on = [st for st in entry.steps if st.enabled]
    if not on:
        return "nothing"
    return "; ".join(step_title(st) for st in on)


# ── state helpers ──────────────────────────────────────────────────────────

def run() -> Optional[PlaylistRun]:
    return show_store.state().playlist_run


def _active() -> Optional[PlaylistRun]:
    r = run()
    return r if r is not None and r.state in ACTIVE_STATES else None


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
            await ws_manager.broadcast({"type": "light_show_playlist", "run": status()["run"]})
        except Exception:                                # noqa: BLE001
            pass
    _spawn(loop, push())


def _spawn(loop, coro) -> asyncio.Task:
    task = loop.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def _log(r: PlaylistRun, what: str, detail: str = "", **data: Any) -> None:
    entry = {"at_ms": now_ms(), "what": what, "detail": detail,
             "song": r.song_title or r.song_uri or "", **data}
    r.log.append(entry)
    del r.log[:-LOG_KEPT]
    try:
        from spectra.services import fire_history
        fire_history.record_fire("show", f"playlist_{what}", {
            "playlist": r.name, "run": r.id,
            **{k: v for k, v in entry.items() if k != "at_ms"}})
    except Exception:                                    # noqa: BLE001
        pass


def _refusal() -> Optional[str]:
    from spectra.services import show_output
    return show_output.refusal()


def _playing_uri() -> Optional[str]:
    from spectra.services import show_arms
    return show_arms.current_uri()


def _is_playing() -> Optional[bool]:
    from spectra.services import show_arms
    return show_arms.is_playing()


def _touch_music() -> None:
    global _last_music_mono
    _last_music_mono = time.monotonic()


def _program(r: PlaylistRun) -> Optional[ShowPlaylist]:
    return show_store.get_playlist(r.playlist_id)


def _lists(pl: ShowPlaylist, uri: Optional[str]) -> bool:
    return bool(uri) and any(e.uri == uri and e.enabled for e in pl.songs)


def _entry_for(pl: ShowPlaylist, uri: Optional[str]) -> tuple[Optional[SongEntry], str]:
    hit = next((e for e in pl.songs if e.uri == uri), None) if uri else None
    if hit is not None:
        return (hit, "listed") if hit.enabled else (None, "off")
    if pl.unlisted_song == "default" and pl.default_song is not None \
            and pl.default_song.enabled:
        return pl.default_song, "default"
    return None, "none"


# ── outcomes (read back from the arms) ─────────────────────────────────────

def _arm_status(a) -> tuple[str, str]:
    from spectra.services import show_arms
    if a.status == show_arms.ACTIVE:
        reason = _refusal()
        if reason:
            return "armed", f"waiting: {reason}"
        lo = a.last_outcome or {}
        if lo.get("status") == "waiting":
            return "armed", f"waited: {lo.get('reason', '')}"
        return "armed", ""
    if a.status == show_arms.FIRED:
        return "fired", a.end_reason
    return a.status, a.end_reason


def _sync(outcomes: list[StepOutcome]) -> bool:
    """Refresh each armed step's status from its arm. Returns whether
    anything changed. An arm that aged out of the board's history keeps the
    last status recorded here."""
    if not outcomes:
        return False
    arms = {a.id: a for a in show_store.state().arms}
    changed = False
    for o in outcomes:
        if not o.arm_id or o.status not in ("armed", "pending"):
            continue
        a = arms.get(o.arm_id)
        if a is None:
            continue
        status, detail = _arm_status(a)
        if status != o.status or detail != o.detail:
            o.status = status
            o.detail = detail
            if status != "armed":
                o.at_ms = a.ended_ms or now_ms()
            changed = True
    return changed


def _end_arms(r: PlaylistRun, *, song_only: bool, status: str, reason: str) -> int:
    """End this run's still-armed arms (only the song-scoped ones with
    `song_only`) with `status` ("missed" / "disarmed"), named."""
    from spectra.services import show_arms
    src = f"{SOURCE_PREFIX}{r.id}"
    n = 0
    for a in show_arms.active_arms():
        if a.source != src or (song_only and a.song_uri is None):
            continue
        show_arms._end(a, status, reason)
        n += 1
    if n:
        show_arms._save()
    return n


def _finish_song(r: PlaylistRun, reason: str, *, status: str = "missed") -> None:
    """The current song is over: its unfired arms are MISSED, its pending
    song-start fire is dropped, and its line on songs_seen is closed."""
    from spectra.services import show_arms
    _sync(r.song_steps)
    for o in r.song_steps:
        if o.status in ("armed", "pending"):
            o.status = status
            o.detail = reason
            o.at_ms = now_ms()
    _end_arms(r, song_only=True,
              status=show_arms.MISSED if status == "missed" else show_arms.DISARMED,
              reason=reason)
    _drop_pending(r.id)
    if r.songs_seen and r.songs_seen[-1].get("uri") == r.song_uri \
            and r.songs_seen[-1].get("open"):
        line = r.songs_seen[-1]
        line["open"] = False
        line["fired"] = sum(1 for o in r.song_steps if o.status == "fired")
        line["missed"] = sum(1 for o in r.song_steps if o.status in ("missed", "refused", "failed"))
        line["ended_ms"] = now_ms()
        missed = [o for o in r.song_steps if o.status == "missed"]
        if missed:
            _log(r, "song_missed", f"{len(missed)} step(s) did not fire: "
                 + "; ".join(o.set_name for o in missed))


def _drop_pending(run_id: str) -> None:
    _pending_song_start[:] = [p for p in _pending_song_start if p[0] != run_id]


# ── steps ──────────────────────────────────────────────────────────────────

def _outcome_for(step: PlaylistStep) -> StepOutcome:
    return StepOutcome(step_id=step.id, set_id=step.set_id,
                       set_name=_set_name(step.set_id), on=step.on)


def _apply_steps(r: PlaylistRun, steps: list[PlaylistStep], *, song_uri: Optional[str],
                 source: str, queue_fires: bool,
                 queue_uri: Optional[str] = None) -> list[StepOutcome]:
    """Arm each enabled step (or queue / fire it, for `song_start`).
    `queue_fires` holds song-start fires until the opening scene change has
    gone through; otherwise they are spawned at once."""
    from spectra.services import show_arms
    out: list[StepOutcome] = []
    for st in steps:
        if not st.enabled:
            continue
        o = _outcome_for(st)
        bad = step_problems(st)
        if bad:
            o.status = "failed"
            o.detail = "; ".join(bad)
            out.append(o)
            continue
        if st.on == "song_start":
            if queue_fires:
                _pending_song_start.append((r.id, song_uri or queue_uri or "", o))
            else:
                _spawn_fire(r.id, o)
            out.append(o)
            continue
        try:
            a = show_arms.arm(set_id=st.set_id, on=st.on, repeat=st.repeat,
                              finish_on_mark=st.finish_on_mark, song_uri=song_uri,
                              source=source)
            o.status = "armed"
            o.arm_id = a.id
            reason = _refusal()
            if reason:
                o.detail = f"waiting: {reason}"
        except show_arms.ArmError as exc:
            o.status = "failed"
            o.detail = str(exc)
        out.append(o)
    return out


def _spawn_fire(run_id: str, o: StepOutcome) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        o.status = "refused"
        o.detail = "the engine is not running"
        return
    _spawn(loop, _fire_step(run_id, o))


async def _fire_step(run_id: str, o: StepOutcome, *, by_hand: bool = False) -> None:
    from spectra.services import show_actions
    reason = _refusal()
    r = run()
    if reason:
        o.status = "refused"
        o.detail = f"the Light Show was standing down: {reason}"
        o.at_ms = now_ms()
        if r is not None and r.id == run_id:
            _log(r, "step_refused", o.detail, set=o.set_name)
            _save()
        return
    try:
        res = await show_actions.fire_set(o.set_id, source=f"{SOURCE_PREFIX}{run_id}")
        o.status = "fired"
        o.detail = ("fired by hand" if by_hand else "") or f"ran: {res.get('state')}"
    except Exception as exc:                             # noqa: BLE001
        logger.exception("show playlist: firing a step failed")
        o.status = "failed"
        o.detail = str(exc)
    o.at_ms = now_ms()
    r = run()
    if r is not None and r.id == run_id:
        _log(r, "step_fired" if o.status == "fired" else "step_failed",
             o.detail, set=o.set_name, on=o.on)
        _save()


# ── the song ───────────────────────────────────────────────────────────────

def _apply_song(r: PlaylistRun, uri: str, *, why: str = "started",
                queue_fires: bool = True) -> None:
    pl = _program(r)
    if pl is None:
        _end(r, ENDED, "its program was deleted", run_on_end=False)
        return
    title, artist = now_playing()
    entry, source = _entry_for(pl, uri)
    if entry is not None and source == "listed":
        title = title or entry.title
        artist = artist or entry.artist
    r.song_uri = uri
    r.song_title = title
    r.song_artist = artist
    r.song_started_ms = now_ms()
    r.entry_source = source
    r.last_uri = uri
    r.songs_count += 1
    r.song_steps = []
    if r.state == FOLLOWING and entry is not None:
        r.song_steps = _apply_steps(r, entry.steps, song_uri=uri,
                                    source=f"{SOURCE_PREFIX}{r.id}", queue_fires=queue_fires)
    r.songs_seen.append({"uri": uri, "title": title, "artist": artist,
                         "entry_source": source, "started_ms": r.song_started_ms,
                         "steps": len(r.song_steps), "open": True,
                         "fired": 0, "missed": 0})
    del r.songs_seen[:-SONGS_SEEN_KEPT]
    words = {"listed": "its own entry", "default": "the default entry",
             "none": "nothing listed", "off": "its entry is switched off"}[source]
    _log(r, "song", f"{_song_word(title, artist, uri)} {why} — {words}"
         + (f" ({len(r.song_steps)} step(s))" if r.song_steps else ""),
         song_uri=uri, entry_source=source)


def after_track_state() -> None:
    """engine._on_track_uri, AFTER scene_sequencer / trigger_engine have
    handled the bridge state: fire the song-start steps queued for the song
    now playing (so its opening scene change has already counted)."""
    if not _pending_song_start:
        return
    r = _active()
    uri = _playing_uri()
    due = [p for p in _pending_song_start
           if r is not None and p[0] == r.id and r.state == FOLLOWING and p[1] == (uri or "")]
    _pending_song_start.clear()
    for _run_id, _uri, o in due:
        _spawn_fire(_run_id, o)


# ── events ─────────────────────────────────────────────────────────────────

def on_state(uri: Optional[str], context_uri: Optional[str] = None,
             position_ms: Optional[int] = None) -> None:
    """engine._on_track_uri, on EVERY bridge state, before the sequencer and
    the trigger engine see it."""
    if _is_playing() is True:
        _touch_music()
    r = _active()
    # a context change clears a "stopped by hand" block
    last = run()
    if last is not None and last.blocked_context and context_uri != last.blocked_context:
        last.blocked_context = None
        show_store.save_state()
    if r is not None:
        if uri is not None and _left(r, uri, context_uri):
            _end(r, ENDED, "the music left the playlist", run_on_end=True)
            r = None
        elif uri is not None:
            if context_uri and r.via != "manual":
                r.context_uri = context_uri
            if uri != r.last_uri:
                _new_song(r, uri, "started")
                _save()
            elif _rewound(uri, position_ms):
                _new_song(r, uri, "restarted")
                _save()
    if r is None and uri is not None:
        _maybe_activate(uri, context_uri)
    if uri is not None and position_ms is not None:
        _last_pos.clear()
        _last_pos[uri] = int(position_ms)


def _rewound(uri: str, position_ms: Optional[int]) -> bool:
    prev = _last_pos.get(uri)
    return (position_ms is not None and prev is not None
            and position_ms < REWIND_REAPPLY_MS and prev >= REWIND_MIN_PLAYED_MS)


def _new_song(r: PlaylistRun, uri: str, why: str) -> None:
    if r.song_uri is not None:
        _finish_song(r, "the song restarted" if uri == r.song_uri
                     else "its song ended before the trigger")
    if r.state == PAUSED:
        r.last_uri = uri
        r.song_uri = uri
        r.song_steps = []
        title, artist = now_playing()
        r.song_title, r.song_artist = title, artist
        return
    _apply_song(r, uri, why=why)


def _left(r: PlaylistRun, uri: str, context_uri: Optional[str]) -> bool:
    if r.via == "manual":
        return False
    pl = _program(r)
    if pl is None:
        return True
    if context_uri and context_uri in pl.contexts:
        return False
    if pl.follow_songs_anywhere and _lists(pl, uri):
        return False
    if r.via == "song" and uri == r.last_uri:
        return False
    if r.via == "context" and not context_uri and uri == r.last_uri:
        # the same song with no context reported (a transient read): stay
        return False
    return True


def _maybe_activate(uri: str, context_uri: Optional[str]) -> None:
    lib = show_store.load_playlists()
    if not lib.follow_enabled:
        return
    last = run()
    blocked = last.blocked_context if last is not None else None
    if context_uri and context_uri != blocked:
        pl = next((p for p in lib.playlists if p.auto_follow and context_uri in p.contexts), None)
        if pl is not None:
            _begin(pl, via="context", by="auto-follow", context_uri=context_uri, uri=uri)
            return
    if blocked is not None and context_uri == blocked:
        return
    pl = next((p for p in lib.playlists
               if p.auto_follow and p.follow_songs_anywhere and _lists(p, uri)), None)
    if pl is not None:
        _begin(pl, via="song", by="a listed song started", context_uri=context_uri or "", uri=uri)


def _begin(pl: ShowPlaylist, *, via: str, by: str, context_uri: str,
           uri: Optional[str], deferred: bool = True) -> PlaylistRun:
    """`deferred` (the auto-follow path, inside on_state): song-start fires
    wait for after_track_state, past the song's opening scene change. A
    start by hand has no opening change pending and fires at once."""
    global _resumed_after_load
    _resumed_after_load = True
    r = PlaylistRun(playlist_id=pl.id, name=pl.name, via=via, started_by=by,
                    context_uri=context_uri)
    show_store.state().playlist_run = r
    _log(r, "started", f"by {by}" + (f", from {context_uri}" if context_uri else ""),
         via=via)
    _on_start(r, pl, uri=uri, deferred=deferred)
    if uri is not None:
        _apply_song(r, uri, queue_fires=deferred)
    _save()
    return r


def _on_start(r: PlaylistRun, pl: ShowPlaylist, *, uri: Optional[str],
              deferred: bool) -> None:
    if pl.on_start.sequence_id:
        from spectra.services import show_sequence
        try:
            show_sequence.start(pl.on_start.sequence_id,
                                replace=pl.on_start.replace_running_sequence,
                                source=f"the playlist program {pl.name!r}")
            _log(r, "sequence_started", _sequence_name(pl.on_start.sequence_id))
        except show_sequence.SequenceError as exc:
            _log(r, "sequence_refused", str(exc))
    r.start_steps = _apply_steps(r, pl.on_start.steps, song_uri=None,
                                 source=f"{SOURCE_PREFIX}{r.id}", queue_fires=deferred,
                                 queue_uri=uri)


def _sequence_name(seq_id: str) -> str:
    s = show_store.get_sequence(seq_id)
    return s.name if s else seq_id


def _end(r: PlaylistRun, state: str, reason: str, *, run_on_end: bool) -> None:
    from spectra.services import show_arms
    if r.song_uri is not None:
        if state == ENDED:
            _finish_song(r, "the playlist ended")
        else:
            _finish_song(r, "following was stopped", status="disarmed")
    _end_arms(r, song_only=False, status=show_arms.DISARMED,
              reason="the playlist program ended" if state == ENDED
              else "following was stopped")
    _drop_pending(r.id)
    _sync(r.start_steps)
    r.state = state
    r.ended_ms = now_ms()
    r.end_reason = reason
    _log(r, "ended" if state == ENDED else "stopped", reason)
    pl = _program(r) if run_on_end else None
    if pl is not None:
        if pl.on_end.steps:
            _apply_steps(r, pl.on_end.steps, song_uri=None,
                         source=f"{END_SOURCE_PREFIX}{r.id}", queue_fires=False)
            _log(r, "on_end", f"{sum(1 for s in pl.on_end.steps if s.enabled)} step(s)")
        if pl.on_end.end_show:
            _spawn_end_show(r)
    _save()


def _spawn_end_show(r: PlaylistRun) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def go():
        from spectra.services import show_actions
        try:
            await show_actions.end_show()
        except Exception:                                # noqa: BLE001
            logger.exception("show playlist: End show on leaving failed")
    _log(r, "end_show", "End show (the program's on-end)")
    _spawn(loop, go())


def on_arm_fired(arm) -> None:
    """show_arms._fire, after an arm made by a playlist run fired."""
    r = run()
    if r is None or arm.source != f"{SOURCE_PREFIX}{r.id}":
        return
    if _sync(r.song_steps) or _sync(r.start_steps):
        _log(r, "step_fired", f"on the {TIMING_WORDS.get(arm.on, arm.on)}", set=arm.label,
             on=arm.on)
        _save()


def on_release() -> None:
    """The room is being released (show_output.on_release, before the arms
    expire): pause, named."""
    r = _active()
    if r is None or r.state != FOLLOWING:
        return
    _drop_pending(r.id)
    r.state = PAUSED
    r.paused_reason = "the room was released — resume when SPECTRA holds it again"
    _log(r, "paused", r.paused_reason)
    _save()


def tick() -> None:
    """The Light Show supervisor's pass: the restart log, the idle end, and
    the steps' statuses read back from their arms."""
    global _resumed_after_load
    r = _active()
    if r is None:
        _resumed_after_load = True
        return
    if not _resumed_after_load:
        _resumed_after_load = True
        _log(r, "resumed", "after a restart, as it was")
        _save()
    if _is_playing() is True:
        _touch_music()
    if time.monotonic() - _last_music_mono >= IDLE_END_S:
        _end(r, ENDED, "30 minutes without music", run_on_end=True)
        return
    if _sync(r.song_steps) | _sync(r.start_steps):
        _save()


# ── controls ───────────────────────────────────────────────────────────────

def start(name_or_id: str, *, replace: bool = False, source: str = "button") -> PlaylistRun:
    """Follow a program now, whatever is playing (`via="manual"`)."""
    pl = show_store.find_playlist(name_or_id)
    if pl is None:
        raise PlaylistError(f"no playlist program called {name_or_id!r}")
    cur = _active()
    if cur is not None:
        if not replace:
            raise PlaylistError(f"{cur.name!r} is already following — stop it first")
        stop(reason=f"replaced by {pl.name!r}")
    uri = _playing_uri()
    return _begin(pl, via="manual", by=source, context_uri=current_context() or "", uri=uri,
                  deferred=False)


def _require(states=ACTIVE_STATES) -> PlaylistRun:
    r = run()
    if r is None or r.state not in states:
        raise PlaylistError("no playlist program is following")
    return r


def stop(reason: str = "stopped by hand") -> PlaylistRun:
    r = _require()
    _end(r, STOPPED, reason, run_on_end=False)
    r.blocked_context = current_context() or r.context_uri or None
    _save()
    return r


def resume() -> PlaylistRun:
    r = _require((PAUSED,))
    r.state = FOLLOWING
    r.paused_reason = ""
    _log(r, "resumed")
    uri = _playing_uri()
    if uri is not None:
        r.song_uri = None
        _apply_song(r, uri, why="resumed", queue_fires=False)
    _save()
    return r


def skip_song(reason: str = "skipped by hand") -> PlaylistRun:
    """Disarm this song's entry (named) — the rest of the program carries on."""
    from spectra.services import show_arms
    r = _require()
    _sync(r.song_steps)
    for o in r.song_steps:
        if o.status in ("armed", "pending"):
            o.status = "skipped"
            o.detail = reason
            o.at_ms = now_ms()
    n = _end_arms(r, song_only=True, status=show_arms.DISARMED, reason=reason)
    _drop_pending(r.id)
    _log(r, "song_skipped", f"{n} armed step(s) disarmed")
    _save()
    return r


async def fire_step(step_id: str) -> PlaylistRun:
    """Fire one of this song's (or on-start's) steps at once; its arm, if
    any, is disarmed so it cannot fire again."""
    from spectra.services import show_arms
    r = _require((FOLLOWING,))
    o = next((x for x in r.song_steps + r.start_steps if x.step_id == step_id), None)
    if o is None:
        raise PlaylistError("that step is not part of the song playing")
    reason = _refusal()
    if reason:
        raise PlaylistError(f"The Light Show is standing down: {reason}")
    if o.arm_id:
        a = next((x for x in show_arms.active_arms() if x.id == o.arm_id), None)
        if a is not None:
            show_arms._end(a, show_arms.DISARMED, "fired by hand from the playlist")
            show_arms._save()
    _pending_song_start[:] = [p for p in _pending_song_start if p[2] is not o]
    await _fire_step(r.id, o, by_hand=True)
    return r


def set_follow(on: bool) -> bool:
    return show_store.set_follow_enabled(on)


# ── status ─────────────────────────────────────────────────────────────────

def _outcome_row(o: StepOutcome) -> dict:
    return o.model_dump()


def up_next() -> Optional[dict]:
    """The next song in Spotify's queue and what this run's program would
    arm for it — a PREVIEW only (arms are made when the song starts)."""
    try:
        from spectra.services import engine
        nt = engine.bridge.next_track()
    except Exception:                                    # noqa: BLE001
        nt = None
    if not nt:
        return None
    out = {"uri": nt["uri"], "title": nt.get("title") or nt["uri"],
           "entry_source": None, "summary": ""}
    r = _active()
    pl = _program(r) if r is not None else None
    if pl is not None:
        entry, source = _entry_for(pl, nt["uri"])
        out["entry_source"] = source
        out["summary"] = entry_summary(entry) if entry is not None else ""
    return out


def run_view(r: Optional[PlaylistRun]) -> Optional[dict]:
    if r is None:
        return None
    d = r.model_dump()
    d["active"] = r.state in ACTIVE_STATES
    d["log"] = list(reversed(r.log))
    d["song_steps"] = [_outcome_row(o) for o in r.song_steps]
    d["start_steps"] = [_outcome_row(o) for o in r.start_steps]
    d["songs_seen"] = list(reversed(r.songs_seen))
    return d


def playing_from() -> Optional[dict]:
    try:
        from spectra.services import engine
        uri = engine.bridge.context_uri()
        if not uri:
            return None
        pl = show_store.playlist_for_context(uri)
        return {"uri": uri, "type": engine.bridge.context_type(),
                "name": engine.bridge.context_name() or (pl.context_names.get(uri) if pl else None),
                "program": pl.name if pl else None}
    except Exception:                                    # noqa: BLE001
        return None


def status() -> dict:
    r = run()
    if r is not None and r.state in ACTIVE_STATES:
        _sync(r.song_steps)
        _sync(r.start_steps)
    return {"run": run_view(r), "refusal": _refusal(),
            "follow_enabled": show_store.load_playlists().follow_enabled,
            "playing_uri": _playing_uri(), "playing_from": playing_from(),
            "up_next": up_next()}


def brief() -> Optional[dict]:
    """The small line the Light Show brief / engine status carries."""
    r = _active()
    if r is None:
        return None
    return {"name": r.name, "state": r.state, "song": r.song_title or r.song_uri,
            "entry_source": r.entry_source, "songs": r.songs_count,
            "up_next": (up_next() or {}).get("title")}


def reset() -> None:
    """Tests."""
    global current_context, now_playing, _resumed_after_load
    for t in list(_tasks):
        t.cancel()
    _tasks.clear()
    _pending_song_start.clear()
    _last_pos.clear()
    _resumed_after_load = False
    current_context = _bridge_context
    now_playing = _bridge_now_playing
    _touch_music()
