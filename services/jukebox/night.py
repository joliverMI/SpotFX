"""
SpotFX — the Jukebox's program engine at RUN time: one night at a time
(data/jukebox-plan/report.md §5 and §9 phase 1, PR 1.1). The rules — where
the slots are, what fills them — are services/jukebox/program.py, pure;
every Spotify call is services/jukebox/gateway.py, blocking, spaced, and
reached only through `deps.to_thread`.

HOW IT PLAYS (the study's option D). The set playlist plays as Spotify's
own context, shuffle off. The jukebox line is Spectra's, and Spotify never
sees it: about `commit_lead_s` (45 s) before the song in front of a slot
ends, the engine sends the song that fills the slot into Spotify's queue
("Add to queue" items play before the context's next track, then the
context resumes) and reads `/me/player/queue` back to confirm it is next.
ONE song is committed at a time — everything not yet committed can still be
moved or removed freely; the committed one can't move, because Spotify's
queue can't be reordered. Two slots in a row: the second is sent the same
way, `commit_lead_s` before the first one ends.

OBSERVE, NEVER ASSUME. The program moves only on what Spotify is SEEN to
start (`deps.current_track`, the poll SpotFX already runs):
  - our committed song        a slot used (program.on_jukebox_start)
  - a committed song he removed   the REPAIR path: it can't be taken out of
                              Spotify's queue, so it is skipped as it starts
  - a set song                the next set position, wherever it is
                              (program.resolve_set_index); the gap after it
                              is sized by the rule
  - anything else             "off the set" — the engine waits, commits
                              nothing, and picks the set up when it returns
A MISSED commit (a failed call, a stalled engine, a commit that landed after
the player had already picked its next track) therefore re-syncs by itself:
the next set song is recognised where it is, a committed song still in
Spotify's queue is left to play after it (never sent twice), and the slot is
owed to the next gap (program.py's module docstring). A read-back that
doesn't show the song is read again once before the song goes back in line.

HOUSE RULES. Order 27: a night never starts while `input_boolean.sleeping`
is on — or unreadable, River's own rule — and a night that sees it go on
ends (a confirmed "on" at once; "unreadable" on the second reading in a row,
so one blip can't end a party), pausing the music only if the engine
started it. It never starts while Absorb Music has a window open, and
Absorb refuses to open while a night runs (services/absorb.py's
`jukebox_night` gate). It only ever acts on the device it was started for.

A night is a record: every start, refusal and ending is in the night file
with its reason, and `status()` answers what is playing, the next 20 program
items with their start times, the line, and any warning.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from models.jukebox import (
    Cursor, JukeboxNight, LineEntry, NowItem, PlayedItem, ProgramConfig, SetItem,
)
from services.jukebox import program, store
from services.jukebox.gateway import default_gateway, parse_track_uri

logger = logging.getLogger(__name__)

# ── timing (seconds) ─────────────────────────────────────────────────────────
TICK_S = 1.0                  # the engine's own clock between polls (interpolated progress)
COMMIT_RETRY_S = 10.0         # after a failed commit call, before trying again
MAX_COMMIT_ATTEMPTS = 3       # per gap slot, before the slot is left to be owed
READBACK_RECHECK_S = 2.0      # a read-back that didn't show the song is read again after this
SKIP_RETRY_S = 3.0
MAX_SKIP_ATTEMPTS = 3
SLEEP_CHECK_S = 60.0          # how often a running night re-reads `sleeping`
SLEEP_UNREADABLE_STRIKES = 2  # "unreadable" this many readings in a row ends the night
SHUFFLE_CHECK_S = 300.0       # how often a running night re-checks shuffle
PLAY_SETTLE_S = 12.0          # after a Start, how long Spotify may still report the old song
RAN_OUT_IDLE_S = 30.0         # the program is done and nothing has played this long: the night ends
MAX_NIGHT_S = 12 * 3600.0     # a night older than this ends itself
SET_CACHE_S = 60.0            # an editor's read of the set is reused this long

# ── refusals and endings: ONE sentence per code ──────────────────────────────
SENTENCES: dict[str, str] = {
    "already_running": "A Jukebox night is already running.",
    "not_running": "No Jukebox night is running.",
    "no_playlist": "No set playlist is linked — link one first.",
    "absorb_window": "Absorb Music has a window open, so the Jukebox won't start.",
    "sleeping": "The house is sleeping, so the Jukebox won't play.",
    "sleeping_unreadable": "Couldn't confirm the house isn't sleeping, so the Jukebox won't play.",
    "device_unreachable": "{device} isn't available as a Spotify Connect device.",
    "playlist_unresolved": "The set playlist couldn't be read.",
    "playlist_empty": "The set playlist has no playable songs.",
    "bad_start": "The set has no song number {n}.",
    "playback_failed": "Spotify refused to start the set.",
    "spotify_error": "Spotify didn't answer.",
    "stopped": "Stopped.",
    "set_ran_out": "The set ran out, so the night ended.",
    "stale": "The night had run for over {hours} hours, so it ended.",
    "playlist_locked": "A night is running on this set — stop it before linking another playlist.",
    "not_a_track": "That isn't a Spotify song link.",
    "track_unknown": "Spotify doesn't know that song.",
    "no_entry": "That song isn't in the line.",
    "committed_fixed": ("That song has already been sent to Spotify, so it can't move. "
                        "Remove it to have it skipped as it starts."),
    "already_played": "That song has already played.",
    "bad_position": "That place isn't in the set any more — the set changed; reload it.",
    "too_close": ("Only set songs at least two ahead of the one playing can move during "
                  "the night — Spotify may already have the next one lined up."),
}


def sentence(code: str, detail: str = "", **fmt: Any) -> str:
    base = SENTENCES.get(code, code)
    try:
        base = base.format(**fmt)
    except (KeyError, IndexError):
        pass
    return f"{base} ({detail})" if detail else base


Refusal = tuple[str, str]


def _err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:120]}"


# ── dependencies ─────────────────────────────────────────────────────────────

async def _default_to_thread(fn: Callable, *args: Any) -> Any:
    return await asyncio.to_thread(fn, *args)


async def _no_guest_link(night_id: str) -> None:
    return None


async def _never_sleeping() -> Optional[bool]:
    return False


def _sign_in_status() -> dict:
    from services import spotify_auth_age
    return spotify_auth_age.status()


@dataclass
class JukeboxDeps:
    gateway: Any
    current_track: Callable[[], Any] = lambda: None
    device_name: Callable[[], str] = lambda: "Serenity"
    sleeping: Callable[[], Awaitable[Optional[bool]]] = _never_sleeping
    absorb_busy: Callable[[], bool] = lambda: False
    to_thread: Callable[..., Awaitable[Any]] = _default_to_thread
    clock: Callable[[], float] = time.monotonic          # same timebase as track.fetched_at
    now_ms: Callable[[], int] = lambda: int(time.time() * 1000)
    load_config: Callable[[], ProgramConfig] = store.load_config
    # SpotFX's Spotify sign-in age (services/spotify_auth_age.py): every
    # night and the line all stop when it lapses, so the master status
    # carries its warning line.
    sign_in: Callable[[], dict] = lambda: _sign_in_status()
    # The guest link (services/jukebox/guest_link.py, N1): opened when a
    # night starts and closed when it ends — when it is switched on. Each
    # answers (ok, sentence) or None for "nothing was done"; never raises.
    # The defaults do nothing: only production_deps() wires the real one.
    guest_link_start: Callable[[str], Awaitable[Any]] = _no_guest_link
    guest_link_end: Callable[[str], Awaitable[Any]] = _no_guest_link
    # Do the lights already know this song (its audio shape is captured)?
    # The line's "Ready" badge. Blocking (it may read the shape index), so
    # only ever called through `to_thread`; production_deps() wires the
    # library's own answer.
    known: Callable[[str], bool] = lambda uri: False


def production_deps() -> JukeboxDeps:
    from config import settings
    from models.state import state

    def device_name() -> str:
        return (settings.spotify_device_names or ["Serenity"])[0]

    async def sleeping() -> Optional[bool]:
        from api import ha_client
        reading = await ha_client.from_settings().read()
        return reading.sleeping

    def absorb_busy() -> bool:
        from services import absorb
        return bool(absorb.runner.open_window)

    from services.jukebox import guest_link

    from services.jukebox import library

    return JukeboxDeps(gateway=default_gateway(), current_track=lambda: state.current_track,
                       device_name=device_name, sleeping=sleeping, absorb_busy=absorb_busy,
                       known=library.known,
                       guest_link_start=lambda nid: guest_link.controller.on_night_start(nid),
                       guest_link_end=lambda nid: guest_link.controller.on_night_end(nid))


def brief(night: Optional[JukeboxNight]) -> Optional[dict]:
    if night is None:
        return None
    return {"id": night.id, "state": night.state, "started_ms": night.started_ms,
            "started_by": night.started_by, "ended_ms": night.ended_ms,
            "end_reason": night.end_reason, "end_detail": night.end_detail,
            "playlist_name": night.playlist_name, "playlist_uri": night.playlist_uri,
            "played": sum(1 for p in night.played if p.kind in ("set", "jukebox")),
            "jukebox_played": sum(1 for p in night.played if p.kind == "jukebox")}


@dataclass
class _Runtime:
    """What a night needs between ticks that is never worth a file write.
    Reset at every start, and (the per-item part) at every song change."""
    window_observed: bool = False       # a tick ran inside the commit window of the current item
    fill_seen: bool = False             # ... and a song was waiting for the slot after it
    commit_attempts: int = 0
    retry_at: float = 0.0
    recheck_entry: str = ""
    recheck_at: float = 0.0
    skip_pending: bool = False
    skip_attempts: int = 0
    skip_retry_at: float = 0.0
    last_sleep_check: float = 0.0
    sleep_strikes: int = 0
    last_shuffle_check: float = 0.0
    done_after_current: bool = False
    idle_since: Optional[float] = None
    settle_until: float = 0.0
    expect_uri: str = ""                # until settle_until, only this song counts as started
    resync_needed: bool = False
    device_id: str = ""
    warnings: dict = field(default_factory=dict)

    def new_item(self) -> None:
        self.window_observed = False
        self.fill_seen = False
        self.commit_attempts = 0
        self.retry_at = 0.0
        self.skip_pending = False
        self.skip_attempts = 0
        self.skip_retry_at = 0.0
        self.idle_since = None


class JukeboxRunner:
    def __init__(self, deps: Optional[JukeboxDeps] = None) -> None:
        self._deps = deps
        self.night: Optional[JukeboxNight] = None
        self.history: list[dict] = []
        self.cfg: ProgramConfig = ProgramConfig()
        self.rt = _Runtime()
        self._lock: Optional[asyncio.Lock] = None
        self._persist_lock: Optional[asyncio.Lock] = None
        self._kick: Optional[asyncio.Event] = None
        self._loaded = False
        self._set_cache: dict[str, tuple[float, dict, list[SetItem]]] = {}

    # ── plumbing ────────────────────────────────────────────────────────────

    @property
    def deps(self) -> JukeboxDeps:
        if self._deps is None:
            self._deps = production_deps()
        return self._deps

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _get_kick(self) -> asyncio.Event:
        if self._kick is None:
            self._kick = asyncio.Event()
        return self._kick

    @property
    def running(self) -> bool:
        return self.night is not None and self.night.state == "running"

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        nights = store.load_nights()
        self.night, self.history = nights.night, list(nights.history)

    def _log(self, text: str) -> None:
        if self.night is None:
            return
        stamp = time.strftime("%H:%M:%S", time.localtime(self.deps.now_ms() / 1000))
        self.night.log.append(f"{stamp} {text}")
        logger.info("Jukebox: %s", text)

    def _warn(self, key: str, text: Optional[str]) -> None:
        """Set (text) or clear (None) one named warning; the night carries
        the current set, in a stable order."""
        if text:
            if self.rt.warnings.get(key) != text:
                self.rt.warnings[key] = text
                self._log(f"warning: {text}")
        else:
            self.rt.warnings.pop(key, None)
        if self.night is not None:
            self.night.warnings = list(self.rt.warnings.values())

    async def _persist(self) -> None:
        if self._persist_lock is None:
            self._persist_lock = asyncio.Lock()
        async with self._persist_lock:
            if self.night is not None:
                store.bound(self.night)
            snapshot = self.night.model_dump(mode="json") if self.night else None
            try:
                await self.deps.to_thread(store.save_night_dict, snapshot, list(self.history))
            except Exception as exc:
                logger.warning("Jukebox: could not save the night: %s", exc)

    async def _call(self, method: str, *args: Any) -> Any:
        """Every Spotify call, off the event loop."""
        return await self.deps.to_thread(getattr(self.deps.gateway, method), *args)

    # ── the program, as the runner sees it ──────────────────────────────────

    def _live_commits(self) -> list[LineEntry]:
        return [e for e in self.night.line if e.state == "committed" and not e.doomed]

    def _doomed_pending(self) -> list[LineEntry]:
        return [e for e in self.night.line if e.state == "committed" and e.doomed]

    def _fills(self) -> list[program.Fill]:
        line = self.night.line
        live = [e for e in line if e.state == "committed" and not e.doomed]
        queued = [e for e in line if e.state == "queued" and e.ready and not e.held]
        return ([program.Fill(e.id, e.uri, e.title, e.artist, e.duration_ms, True) for e in live]
                + [program.Fill(e.id, e.uri, e.title, e.artist, e.duration_ms, False)
                   for e in queued])

    def _project(self, count: int) -> list[program.ProgramItem]:
        n = self.night
        return program.project(self.cfg, n.set_items, n.cursor, self._fills(), count)

    def _entry(self, entry_id: str) -> Optional[LineEntry]:
        for e in self.night.line:
            if e.id == entry_id:
                return e
        return None

    def _entry_by_uri(self, uri: str, *states: str) -> Optional[LineEntry]:
        for e in self.night.line:
            if e.uri == uri and e.state in states:
                return e
        return None

    def _remaining_ms(self, track: Any, now: float) -> int:
        progress = int(getattr(track, "progress_ms", 0) or 0)
        if getattr(track, "is_playing", False):
            progress += int((now - float(getattr(track, "fetched_at", now))) * 1000)
        duration = int(getattr(track, "duration_ms", 0) or 0)
        progress = max(0, min(progress, duration)) if duration > 0 else max(0, progress)
        return max(0, duration - progress)

    def _played(self, kind: str, uri: str, title: str = "", **kw: Any) -> None:
        self.night.played.append(PlayedItem(kind=kind, uri=uri, title=title,
                                            at_ms=self.deps.now_ms(), **kw))

    # ── starting and stopping a night ───────────────────────────────────────

    async def start(self, play: bool = True, start_index: int = 0,
                    started_by: str = "press") -> dict:
        """Start a night: read the set, take shuffle off, set repeat to the
        run-out policy, and (with `play`) start the set on the device. Every
        refusal is RECORDED and answered with its reason, never a silence."""
        async with self._get_lock():
            self._ensure_loaded()
            if self.running:
                return {"status": "already_running", "reason": "already_running",
                        "detail": sentence("already_running"), "night": brief(self.night)}
            d = self.deps
            self.cfg = d.load_config()
            if self.night is not None:
                self.history.insert(0, brief(self.night))
            self.night = JukeboxNight(id=uuid.uuid4().hex[:12], state="running",
                                      started_ms=d.now_ms(), started_by=started_by,
                                      device_name=d.device_name(),
                                      owns_playback=bool(play))
            self.rt = _Runtime()
            refusal = await self._gates(play, start_index)
            if refusal is not None:
                return await self._refuse(refusal)
            n, now = self.night, d.clock()
            if play:
                try:              # before the start too, so the first pick isn't shuffled
                    await self._call("set_shuffle", False, self.rt.device_id)
                except Exception as exc:
                    self._log(f"couldn't take shuffle off before starting ({_err(exc)})")
                try:
                    await self._call("start_context", self.rt.device_id, n.playlist_uri,
                                     int(start_index))
                except Exception as exc:
                    return await self._refuse(("playback_failed",
                                               sentence("playback_failed", _err(exc))))
                self.rt.settle_until = now + PLAY_SETTLE_S
                self.rt.expect_uri = n.set_items[int(start_index)].uri
                n.start_index = int(start_index)
            await self._shuffle_and_repeat(first=True)
            self.rt.last_sleep_check = now
            self.rt.last_shuffle_check = d.clock()
            what = (f"playing from song {start_index + 1}" if play
                    else "following what plays")
            self._log(f"night started ({started_by}) on {n.playlist_name or n.playlist_uri}: "
                      f"{len(n.set_items)} set songs, {self._rules_line()}; {what}")
            await self._guest_link(d.guest_link_start, n.id)
            await self._persist()
            return {"status": "running", "reason": "", "detail": "", "night": brief(n)}

    def _rules_line(self) -> str:
        c = self.cfg
        if c.mode == "jukebox_first":
            rule = "jukebox first"
        elif c.mode == "manual":
            rule = f"manual slots after {len(c.manual)} set song(s)"
        else:
            rule = f"{c.run} jukebox slot(s) after every {c.every} set song(s)"
        return f"{rule}, when the set runs out: {c.run_out}"

    async def _gates(self, play: bool, start_index: int) -> Optional[Refusal]:
        d, n, cfg = self.deps, self.night, self.cfg
        if not cfg.playlist.strip():
            return ("no_playlist", sentence("no_playlist"))
        if d.absorb_busy():
            return ("absorb_window", sentence("absorb_window"))
        try:
            asleep = await d.sleeping()
        except Exception:                                         # noqa: BLE001
            asleep = None
        if asleep is True:
            return ("sleeping", sentence("sleeping"))
        if asleep is None:
            return ("sleeping_unreadable", sentence("sleeping_unreadable"))
        try:
            self.rt.device_id = await self._call("device_id", n.device_name) or ""
        except Exception as exc:
            return ("spotify_error", sentence("spotify_error", _err(exc)))
        if not self.rt.device_id:
            return ("device_unreachable", sentence("device_unreachable", device=n.device_name))
        try:
            info = await self._call("resolve_playlist", cfg.playlist)
            if not info:
                return ("playlist_unresolved", sentence("playlist_unresolved"))
            items = await self._call("playlist_items", info["id"])
        except Exception as exc:
            return ("playlist_unresolved", sentence("playlist_unresolved", _err(exc)))
        if not items:
            return ("playlist_empty", sentence("playlist_empty"))
        if play and not 0 <= int(start_index) < len(items):
            return ("bad_start", sentence("bad_start", n=int(start_index) + 1))
        n.playlist_id, n.playlist_uri = info["id"], info["uri"]
        n.playlist_name, n.snapshot_id = info.get("name") or "", info.get("snapshot_id") or ""
        n.set_items = [SetItem(**it) for it in items]
        return None

    async def _refuse(self, refusal: Refusal) -> dict:
        code, text = refusal
        n = self.night
        n.state, n.ended_ms, n.end_reason, n.end_detail = "refused", self.deps.now_ms(), code, text
        self._log(f"refused: {text}")
        await self._persist()
        return {"status": "refused", "reason": code, "detail": text, "night": brief(n)}

    async def _shuffle_and_repeat(self, first: bool) -> None:
        """Shuffle off (the set must play in order) and repeat set to the
        run-out policy ("again" loops the set in Spotify itself). Read back;
        a shuffle that won't turn off is a WARNING, not a failure: the slot
        rhythm counts set songs, not positions, so it still works — only the
        preview's order and the run-out can't be trusted."""
        dev = self.rt.device_id or None
        want_repeat = "context" if self.cfg.run_out == "again" else "off"
        if first:
            for method, arg in (("set_shuffle", False), ("set_repeat", want_repeat)):
                try:
                    await self._call(method, arg, dev)
                except Exception as exc:
                    self._log(f"couldn't {method.replace('_', ' ')} ({_err(exc)})")
        try:
            pb = await self._call("playback")
        except Exception as exc:
            self._log(f"couldn't read the player's shuffle state ({_err(exc)})")
            return
        if not pb:
            return
        if pb.get("shuffle") and first:
            try:
                await self._call("set_shuffle", False, dev)
                pb = await self._call("playback") or pb
            except Exception as exc:
                self._log(f"couldn't turn shuffle off ({_err(exc)})")
        self._warn("shuffle", "Shuffle is on in Spotify, so the set won't play in order."
                   if pb.get("shuffle") else None)
        self._warn("smart_shuffle", "Smart shuffle is on in Spotify, so it adds its own songs."
                   if pb.get("smart_shuffle") else None)

    async def stop(self, pause: bool = False, reason: str = "stopped") -> dict:
        async with self._get_lock():
            self._ensure_loaded()
            if not self.running:
                return {"status": "not_running", "reason": "not_running",
                        "detail": sentence("not_running"), "night": brief(self.night)}
            pending = self._live_commits()
            if pending:
                self._log(f"{pending[0].title or pending[0].uri} is already in Spotify's queue "
                          "and will still play")
            await self._end(reason, sentence(reason), pause=pause)
            return {"status": "ended", "reason": reason, "detail": self.night.end_detail,
                    "night": brief(self.night)}

    async def _end(self, code: str, text: str, pause: bool) -> None:
        n = self.night
        n.state, n.ended_ms, n.end_reason, n.end_detail = "ended", self.deps.now_ms(), code, text
        self._log(f"night ended: {text}")
        if pause:
            try:
                await self._call("pause", self.rt.device_id or None)
                self._log("paused the music")
            except Exception as exc:
                self._log(f"couldn't pause the music ({_err(exc)})")
        await self._guest_link(self.deps.guest_link_end, n.id)
        await self._persist()

    async def _guest_link(self, hook: Callable[[str], Awaitable[Any]], night_id: str) -> None:
        """The guest link's step, logged; a failure is a warning on a night
        that plays on, never a stopped night."""
        try:
            out = await hook(night_id)
        except Exception as exc:                                  # noqa: BLE001
            out = (False, f"the guest link step failed ({_err(exc)})")
        if not out:
            return
        ok, said = out
        self._log(said)
        self._warn("guest_link", None if ok else said)

    # ── the tick ────────────────────────────────────────────────────────────

    def on_track_state(self, track: Any = None) -> None:
        """Called on every Spotify poll (main.py). Never blocks and never
        raises: it only wakes the engine's own task, which does any Spotify
        I/O off the poll loop."""
        try:
            if self.running:
                self._get_kick().set()
        except Exception:                                         # noqa: BLE001
            logger.exception("Jukebox: poll hook failed")

    async def run_supervised(self) -> None:
        """The engine's own task: a step on every poll, and every TICK_S in
        between (progress is interpolated, so the commit lands near its mark
        without polling Spotify faster). Idle cost with no night: one
        attribute check a second."""
        kick = self._get_kick()
        while True:
            try:
                try:
                    await asyncio.wait_for(kick.wait(), timeout=TICK_S)
                except asyncio.TimeoutError:
                    pass
                kick.clear()
                await self.step()
            except asyncio.CancelledError:
                raise
            except Exception:                                     # noqa: BLE001
                logger.exception("Jukebox: step failed")
                await asyncio.sleep(TICK_S)

    async def step(self) -> None:
        if not self.running:
            return
        async with self._get_lock():
            if not self.running:
                return
            d = self.deps
            now = d.clock()
            if await self._safety(now):
                return
            if self.rt.resync_needed:
                self.rt.resync_needed = False
                await self._resync_queue("after a restart")
            track = d.current_track()
            changed = await self._observe(track, now)
            if not self.running:
                return
            changed |= await self._retry_skip(now)
            changed |= await self._recheck_readback(now)
            changed |= await self._maybe_commit(track, now)
            await self._maybe_check_shuffle(now)
            self.rt.done_after_current = self.night.cursor.started and not self._project(1)
            if await self._ran_out_idle(track, now):
                return
            if changed:
                await self._persist()

    async def _safety(self, now: float) -> bool:
        """Order 27 and the age limit. True = the night ended."""
        n, d, rt = self.night, self.deps, self.rt
        if d.now_ms() - n.started_ms > MAX_NIGHT_S * 1000:
            await self._end("stale", sentence("stale", hours=int(MAX_NIGHT_S // 3600)),
                            pause=False)
            return True
        if now - rt.last_sleep_check < SLEEP_CHECK_S:
            return False
        rt.last_sleep_check = now
        try:
            asleep = await d.sleeping()
        except Exception:                                         # noqa: BLE001
            asleep = None
        if asleep is True:
            await self._end("sleeping", sentence("sleeping"), pause=n.owns_playback)
            return True
        if asleep is None:
            rt.sleep_strikes += 1
            if rt.sleep_strikes >= SLEEP_UNREADABLE_STRIKES:
                await self._end("sleeping_unreadable", sentence("sleeping_unreadable"),
                                pause=n.owns_playback)
                return True
            self._log("couldn't read whether the house is sleeping; reading again in a minute")
        else:
            rt.sleep_strikes = 0
        return False

    async def _observe(self, track: Any, now: float) -> bool:
        n, d = self.night, self.deps
        if track is None:
            return False
        target = n.device_name or d.device_name()
        device = str(getattr(track, "device_name", "") or "")
        on_device = device.lower() == target.lower()
        self._warn("off_device", None if on_device else
                   f"Playback is on {device or 'another device'}, not {target} — the Jukebox waits.")
        if not on_device:
            return False
        uri = str(getattr(track, "spotify_uri", "") or "")
        if not uri or uri == n.now.uri:
            return False
        return await self._on_new_song(track, now)

    async def _on_new_song(self, track: Any, now: float) -> bool:
        n, cfg, rt = self.night, self.cfg, self.rt
        uri = str(track.spotify_uri)
        title = str(getattr(track, "title", "") or "")
        context = str(getattr(track, "context_uri", "") or "")
        if now < rt.settle_until and uri != rt.expect_uri:
            return False            # the old song, reported before the Start took
        prev = n.now
        prev_entry = self._entry(prev.entry_id) if prev.entry_id else None
        if prev.kind == "jukebox" and prev_entry is not None and prev_entry.state == "playing":
            prev_entry.state, prev_entry.played_ms = "played", self.deps.now_ms()

        committed = self._entry_by_uri(uri, "committed")
        if committed is not None and committed.doomed:
            committed.state = "skipped"
            n.now = NowItem(kind="skipping", uri=uri, title=committed.title or title,
                            entry_id=committed.id, started_ms=self.deps.now_ms())
            self._played("skipped", uri, committed.title or title, entry_id=committed.id)
            self._log(f"skipping {committed.title or uri}: it was removed after it was "
                      "sent to Spotify")
            rt.new_item()
            await self._skip(now)
            return True
        idx = None
        if not context or context == n.playlist_uri:
            idx = program.resolve_set_index(cfg, n.set_items, n.cursor, uri)
        waiting = None if committed is not None else self._entry_by_uri(uri, "queued")
        if waiting is not None and idx is not None:
            # The set itself reached a song someone has waiting: it plays as a
            # set song, and the request is fulfilled — it won't play twice.
            waiting.state, waiting.played_ms = "played", self.deps.now_ms()
            self._log(f"{waiting.title or uri} played as part of the set, so it leaves the line")
            waiting = None
        line_song = committed or waiting
        if line_song is not None:
            if committed is None:
                self._log(f"{line_song.title or uri} started without being sent — "
                          "counted as its jukebox play")
            n.cursor = program.on_jukebox_start(n.cursor)
            line_song.state = "playing"
            n.now = NowItem(kind="jukebox", uri=uri, title=line_song.title or title,
                            entry_id=line_song.id, started_ms=self.deps.now_ms())
            self._played("jukebox", uri, line_song.title or title, entry_id=line_song.id)
            self._warn("off_set", None)
            rt.new_item()
            return True

        if rt.done_after_current and n.cursor.started:
            is_set = (not context or context == n.playlist_uri) and any(
                s.uri == uri for s in n.set_items)
            await self._end("set_ran_out", sentence("set_ran_out"),
                            pause=n.owns_playback and not is_set)
            return True

        if idx is None:
            n.now = NowItem(kind="foreign", uri=uri, title=title, started_ms=self.deps.now_ms())
            self._played("foreign", uri, title)
            self._warn("off_set", f"Playing {title or uri}, which isn't in the set — the "
                       "Jukebox waits until the set plays again.")
            rt.new_item()
            return True

        owe, carried = self._gap_owes()
        n.cursor = program.on_set_start(cfg, n.set_items, n.cursor, idx, owe=owe)
        item = n.set_items[idx]
        n.now = NowItem(kind="set", uri=uri, title=item.title or title, set_index=idx,
                        started_ms=self.deps.now_ms())
        self._played("set", uri, item.title or title, set_index=idx)
        self._warn("off_set", None)
        rt.settle_until = 0.0
        if owe:
            self._log("a jukebox slot was missed; it is owed to the next gap")
        rt.new_item()
        await self._check_snapshot()
        if carried:
            await self._resync_queue("a committed song was carried past a set song")
        return True

    def _gap_owes(self) -> tuple[bool, bool]:
        """At a set song's start: did the gap that just closed MISS a slot?
        (owed, carried) — carried = a committed song is still waiting in
        Spotify's queue and will play after this set song."""
        c = self.night.cursor
        if not 0 < c.gap_left < program.UNBOUNDED:
            return False, False
        if self._live_commits():
            return True, True
        if self.rt.fill_seen:
            return True, False
        if not self.rt.window_observed and self._fills():
            return True, False
        return False, False

    async def _check_snapshot(self) -> None:
        """He may edit the set playlist mid-night: one cheap snapshot read
        per set song, and a full re-read only when it changed."""
        n = self.night
        try:
            snap = await self._call("playlist_snapshot", n.playlist_id)
            if not snap or snap == n.snapshot_id:
                return
            items = await self._call("playlist_items", n.playlist_id)
        except Exception as exc:
            self._log(f"couldn't re-read the set ({_err(exc)})")
            return
        if not items:
            self._log("the set playlist read back empty; keeping the set as it was")
            return
        n.set_items = [SetItem(**it) for it in items]
        n.snapshot_id = snap
        n.cursor = program.reanchor(n.set_items, n.cursor)
        self._log(f"the set changed in Spotify: now {len(n.set_items)} songs")

    async def _resync_queue(self, why: str) -> None:
        """Compare what we committed with what Spotify's queue holds. A
        committed song that is neither playing nor queued any more went
        missing: back in the line (or, if he had removed it, gone)."""
        n = self.night
        pending = [e for e in n.line if e.state == "committed"]
        if not pending:
            return
        try:
            q = await self._call("queue")
        except Exception as exc:
            self._log(f"couldn't read Spotify's queue {why} ({_err(exc)})")
            return
        present = set(q.get("queue") or []) | {q.get("current") or ""}
        for e in pending:
            if e.uri in present:
                continue
            if e.doomed:
                e.state = "removed"
                self._log(f"{e.title or e.uri} is no longer in Spotify's queue")
            else:
                e.state, e.committed_ms, e.commit_check = "queued", None, ""
                self._log(f"{e.title or e.uri} is no longer in Spotify's queue, so it is "
                          f"back in the line ({why})")

    # ── committing a slot ───────────────────────────────────────────────────

    async def _maybe_commit(self, track: Any, now: float) -> bool:
        n, rt = self.night, self.rt
        if track is None or not getattr(track, "is_playing", False):
            return False
        if self.rt.warnings.get("off_device") or n.now.kind in ("", "foreign", "skipping"):
            return False
        if str(getattr(track, "spotify_uri", "")) != n.now.uri or rt.recheck_entry:
            return False
        if self._remaining_ms(track, now) > self.cfg.commit_lead_s * 1000:
            return False
        rt.window_observed = True
        nxt = self._project(1)
        if not nxt or nxt[0].kind != "jukebox" or nxt[0].committed:
            return False
        rt.fill_seen = True
        if rt.commit_attempts >= MAX_COMMIT_ATTEMPTS or now < rt.retry_at:
            return False
        entry = self._entry(nxt[0].entry_id)
        if entry is None or entry.state != "queued":
            return False
        return await self._commit(entry, now)

    async def _commit(self, entry: LineEntry, now: float) -> bool:
        rt = self.rt
        ahead = len(self._doomed_pending())
        rt.commit_attempts += 1
        try:
            await self._call("add_to_queue", entry.uri)
        except Exception as exc:
            rt.retry_at = now + COMMIT_RETRY_S
            self._log(f"couldn't send {entry.title or entry.uri} to Spotify ({_err(exc)})")
            return True
        entry.state, entry.committed_ms, entry.commit_check = "committed", self.deps.now_ms(), ""
        self._log(f"sent {entry.title or entry.uri} to Spotify's queue (plays after "
                  f"{self.night.now.title or self.night.now.uri})")
        await self._read_back(entry, ahead, now)
        return True

    async def _read_back(self, entry: LineEntry, ahead: int, now: float,
                        second: bool = False) -> None:
        try:
            q = await self._call("queue")
        except Exception as exc:
            entry.commit_check = "unread"
            self._log(f"couldn't read Spotify's queue back ({_err(exc)}); the send was accepted")
            return
        uris = list(q.get("queue") or [])
        pos = uris.index(entry.uri) if entry.uri in uris else None
        if pos is None:
            entry.commit_check = "missing"
            if second:
                entry.state, entry.committed_ms = "queued", None
                self.rt.retry_at = now + COMMIT_RETRY_S
                self._log(f"Spotify's queue still doesn't show {entry.title or entry.uri}, "
                          "so it is back in the line and will be sent again")
            else:
                self.rt.recheck_entry, self.rt.recheck_at = entry.id, now + READBACK_RECHECK_S
                self._log(f"Spotify's queue doesn't show {entry.title or entry.uri} yet; "
                          "looking again")
            return
        if pos <= ahead:
            entry.commit_check = "next"
            self._warn("queue_ahead", None)
        else:
            entry.commit_check = "later"
            self._warn("queue_ahead", f"{pos - ahead} song(s) added in Spotify itself play "
                       f"before {entry.title or entry.uri}.")

    async def _recheck_readback(self, now: float) -> bool:
        rt = self.rt
        if not rt.recheck_entry or now < rt.recheck_at:
            return False
        entry = self._entry(rt.recheck_entry)
        rt.recheck_entry = ""
        if entry is None or entry.state != "committed":
            return False
        await self._read_back(entry, len(self._doomed_pending()), now, second=True)
        return True

    # ── the repair path ─────────────────────────────────────────────────────

    async def _skip(self, now: float) -> None:
        rt = self.rt
        rt.skip_attempts += 1
        try:
            await self._call("next_track")
            rt.skip_pending = False
        except Exception as exc:
            rt.skip_pending = True
            rt.skip_retry_at = now + SKIP_RETRY_S
            self._log(f"couldn't skip it ({_err(exc)})")

    async def _retry_skip(self, now: float) -> bool:
        rt = self.rt
        if (not rt.skip_pending or self.night.now.kind != "skipping"
                or now < rt.skip_retry_at or rt.skip_attempts >= MAX_SKIP_ATTEMPTS):
            return False
        await self._skip(now)
        return True

    async def _maybe_check_shuffle(self, now: float) -> None:
        if now - self.rt.last_shuffle_check < SHUFFLE_CHECK_S:
            return
        self.rt.last_shuffle_check = now
        await self._shuffle_and_repeat(first=False)

    async def _ran_out_idle(self, track: Any, now: float) -> bool:
        """The program is done (nothing after the item playing) and the
        music has stopped: the night ends instead of waiting forever."""
        rt = self.rt
        playing = track is not None and getattr(track, "is_playing", False)
        if not rt.done_after_current or playing:
            rt.idle_since = None
            return False
        if rt.idle_since is None:
            rt.idle_since = now
            return False
        if now - rt.idle_since < RAN_OUT_IDLE_S:
            return False
        await self._end("set_ran_out", sentence("set_ran_out"), pause=False)
        return True

    # ── the line (the host's controls for now; guests come in phase 2) ──────

    async def add(self, link: str, added_by: str = "host") -> dict:
        uri = parse_track_uri(link)
        if not uri:
            return {"status": "refused", "reason": "not_a_track", "detail": sentence("not_a_track")}
        self._ensure_loaded()
        if not self.running:
            return {"status": "refused", "reason": "not_running", "detail": sentence("not_running")}
        try:
            meta = await self._call("track", uri)
        except Exception as exc:
            return {"status": "refused", "reason": "spotify_error",
                    "detail": sentence("spotify_error", _err(exc))}
        if not meta:
            return {"status": "refused", "reason": "track_unknown", "detail": sentence("track_unknown")}
        known = await self._known(meta["uri"])
        async with self._get_lock():
            if not self.running:
                return {"status": "refused", "reason": "not_running",
                        "detail": sentence("not_running")}
            entry = LineEntry(id=uuid.uuid4().hex[:10], uri=meta["uri"], title=meta["title"],
                              artist=meta.get("artist", ""),
                              duration_ms=int(meta.get("duration_ms") or 0),
                              image=meta.get("image") or "", thumb=meta.get("thumb") or "",
                              explicit=bool(meta.get("explicit")), known=known,
                              added_ms=self.deps.now_ms(), added_by=added_by)
            self.night.line.append(entry)
            self._log(f"{added_by} added {entry.title or entry.uri}")
            await self._persist()
            return {"status": "added", "entry": entry.model_dump(mode="json")}

    async def _known(self, uri: str) -> bool:
        try:
            return bool(await self.deps.to_thread(self.deps.known, uri))
        except Exception:                                         # noqa: BLE001
            return False

    def fair_index(self, rnd: int, fair: bool) -> int:
        """Where a new song of round `rnd` goes in the line: ahead of the
        first WAITING song with a higher round (fair order: 1st songs before
        2nd songs), else at the back. Never ahead of a song already sent to
        Spotify or playing — those aren't waiting."""
        line = self.night.line
        if fair:
            for i, e in enumerate(line):
                if e.state == "queued" and e.round > rnd:
                    return i
        return len(line)

    def _starts_in(self, entry_id: str) -> Optional[int]:
        """When an entry in the line would start, from now (None: not within
        the projection — far beyond anything the night will reach)."""
        n = self.night
        track = self.deps.current_track()
        on = track is not None and str(getattr(track, "spotify_uri", "")) == n.now.uri
        remaining = self._remaining_ms(track, self.deps.clock()) if on else 0
        waiting = sum(1 for e in n.line if e.state in ("queued", "committed"))
        items = program.with_start_times(self._project(min(600, 3 * waiting + 60)), remaining)
        for it in items:
            if it.entry_id == entry_id:
                return it.starts_in_ms
        return None

    async def add_entry(self, entry: LineEntry, *, fair: bool = True,
                        latest_start_ms: Optional[int] = None) -> dict:
        """A guest's song (services/jukebox/guests.py): placed by fair order
        (its `round`), then refused — and taken back out — if it would start
        later than `latest_start_ms` from now (it would play after the night
        ends). Answers where it landed and when it plays."""
        async with self._get_lock():
            self._ensure_loaded()
            if not self.running:
                return {"status": "refused", "reason": "not_running",
                        "detail": sentence("not_running")}
            idx = self.fair_index(entry.round, fair)
            self.night.line.insert(idx, entry)
            starts = self._starts_in(entry.id)
            if latest_start_ms is not None and (starts is None or starts > latest_start_ms):
                self.night.line.remove(entry)
                return {"status": "refused", "reason": "too_late", "starts_in_ms": starts}
            self._log(f"{entry.added_by if entry.added_by == 'host' else 'a guest'} added "
                      f"{entry.title or entry.uri} (song {entry.round} of theirs tonight)")
            await self._persist()
            return {"status": "added", "entry": entry.model_dump(mode="json"),
                    "starts_in_ms": starts}

    async def hold(self, entry_id: str, held: bool) -> dict:
        """The host holds a waiting song (it keeps its place; slots pass it)
        or lets it go. A song already sent to Spotify can't be held — remove
        it to have it skipped as it starts."""
        async with self._get_lock():
            self._ensure_loaded()
            if not self.running:
                return {"status": "refused", "reason": "not_running",
                        "detail": sentence("not_running")}
            e = self._entry(entry_id)
            if e is None:
                return {"status": "refused", "reason": "no_entry", "detail": sentence("no_entry")}
            if e.state == "committed":
                return {"status": "refused", "reason": "committed_fixed",
                        "detail": sentence("committed_fixed")}
            if e.state != "queued":
                return {"status": "refused", "reason": "already_played",
                        "detail": sentence("already_played")}
            if e.held != held:
                e.held = held
                self._log(f"{'held' if held else 'let go of'} {e.title or e.uri}")
                await self._persist()
            return {"status": "held" if held else "released", "entry": e.model_dump(mode="json")}

    async def remove(self, entry_id: str) -> dict:
        async with self._get_lock():
            self._ensure_loaded()
            if not self.running:
                return {"status": "refused", "reason": "not_running",
                        "detail": sentence("not_running")}
            e = self._entry(entry_id)
            if e is None:
                return {"status": "refused", "reason": "no_entry", "detail": sentence("no_entry")}
            name = e.title or e.uri
            if e.state == "queued":
                e.state = "removed"
                self._log(f"removed {name} from the line")
                result = "removed"
            elif e.state == "committed":
                e.doomed = True
                self._log(f"removed {name}; it is already in Spotify's queue, so it will be "
                          "skipped as it starts")
                result = "will_skip"
            elif e.state == "playing":
                e.state = "skipped"
                self._log(f"removed {name} while it played; skipping it now")
                self.rt.skip_attempts = 0
                await self._skip(self.deps.clock())
                result = "skipped"
            else:
                return {"status": "refused", "reason": "already_played",
                        "detail": sentence("already_played")}
            await self._persist()
            return {"status": result, "entry": e.model_dump(mode="json")}

    async def move(self, entry_id: str, to: int) -> dict:
        """Move a waiting song to place `to` among the WAITING songs (0 =
        next to be sent). A committed song can't move, and nothing can be
        moved in front of it: it is already in Spotify's queue."""
        async with self._get_lock():
            self._ensure_loaded()
            if not self.running:
                return {"status": "refused", "reason": "not_running",
                        "detail": sentence("not_running")}
            e = self._entry(entry_id)
            if e is None:
                return {"status": "refused", "reason": "no_entry", "detail": sentence("no_entry")}
            if e.state == "committed":
                return {"status": "refused", "reason": "committed_fixed",
                        "detail": sentence("committed_fixed")}
            if e.state != "queued":
                return {"status": "refused", "reason": "already_played",
                        "detail": sentence("already_played")}
            line = self.night.line
            waiting = [x for x in line if x.state == "queued" and x.id != e.id]
            to = max(0, min(int(to), len(waiting)))
            waiting.insert(to, e)
            self.night.line = [x for x in line if x.state != "queued"] + waiting
            self._log(f"moved {e.title or e.uri} to place {to + 1} in the line")
            await self._persist()
            return {"status": "moved", "line": self.line_view()}

    # ── program settings, and reads ─────────────────────────────────────────

    def apply_config(self, cfg: ProgramConfig) -> Optional[Refusal]:
        """A saved program-settings edit, applied live from the next set
        song. The set playlist itself can't change under a running night."""
        self._ensure_loaded()
        if self.running and cfg.playlist.strip() != self.cfg.playlist.strip():
            return ("playlist_locked", sentence("playlist_locked"))
        if self.running:
            self.cfg = cfg
            self._log(f"program settings changed: {self._rules_line()}")
        return None

    def line_view(self) -> list[dict]:
        n = self.night
        if n is None:
            return []
        order = {"playing": 0, "committed": 1, "queued": 2}
        live = [e for e in n.line if e.state in order]
        live.sort(key=lambda e: order[e.state])
        return [e.model_dump(mode="json") for e in live]

    def status(self, count: int = 20) -> dict:
        self._ensure_loaded()
        n = self.night
        try:
            sign_in = self.deps.sign_in()
        except Exception as exc:                                  # noqa: BLE001
            sign_in = {"state": "unreadable", "warning": f"Couldn't read the Spotify sign-in's "
                       f"age ({type(exc).__name__})."}
        account = [sign_in["warning"]] if sign_in.get("warning") else []
        if n is None:
            return {"night": None, "running": False, "now": None, "next": [], "line": [],
                    "warnings": account, "spotify_auth": sign_in, "log": [],
                    "history": self.history[:5]}
        items = self._project(count) if n.state == "running" else []
        track = self.deps.current_track() if n.state == "running" else None
        remaining = (self._remaining_ms(track, self.deps.clock())
                     if track is not None and str(getattr(track, "spotify_uri", "")) == n.now.uri
                     else 0)
        program.with_start_times(items, remaining)
        lap = program.lap(self.cfg, n.set_items)
        return {"night": brief(n), "running": n.state == "running",
                "now": n.now.model_dump(mode="json"), "remaining_ms": remaining,
                "next": [i.as_dict() for i in items], "line": self.line_view(),
                "cursor": n.cursor.model_dump(mode="json"),
                "lap": {"set_songs": lap.set_songs, "slots": lap.slots,
                        "unbounded": lap.unbounded, "notes": lap.notes},
                "warnings": account + list(n.warnings), "spotify_auth": sign_in,
                "log": n.log[-60:], "history": self.history[:5]}

    def guest_state(self, count: int = 12) -> dict:
        """What the guest page needs (services/jukebox/guests.py) and nothing
        more: the night, what is playing with its progress, and the next
        `count` program items with their start times. Reads only — no
        Spotify call, no lock (one event loop; the projection is pure), no
        sign-in read — because every phone at the party asks every few
        seconds."""
        self._ensure_loaded()
        n = self.night
        if n is None or n.state != "running":
            return {"running": False}
        track = self.deps.current_track()
        on = track is not None and str(getattr(track, "spotify_uri", "")) == n.now.uri
        remaining = self._remaining_ms(track, self.deps.clock()) if on else 0
        items = program.with_start_times(self._project(count), remaining)
        duration = int(getattr(track, "duration_ms", 0) or 0) if on else 0
        return {"running": True, "night_id": n.id, "started_ms": n.started_ms, "now": n.now,
                "is_playing": bool(on and getattr(track, "is_playing", False)),
                "duration_ms": duration, "remaining_ms": remaining,
                "next": items, "line": list(n.line), "set_items": n.set_items}

    async def read_set(self, cfg: ProgramConfig, refresh: bool = False) -> tuple[dict, list[SetItem]]:
        """The set for `cfg`: the running night's own copy when the night is
        on this playlist (no Spotify call), else a read cached for
        SET_CACHE_S so an editor click never waits on Spotify — `refresh`
        reads again. Raises LookupError when the playlist can't be read."""
        n = self.night
        if (self.running and n is not None and not refresh
                and cfg.playlist.strip() == self.cfg.playlist.strip()):
            return ({"id": n.playlist_id, "uri": n.playlist_uri, "name": n.playlist_name,
                     "snapshot_id": n.snapshot_id}, list(n.set_items))
        key = cfg.playlist.strip()
        hit = self._set_cache.get(key)
        if hit and not refresh and self.deps.clock() - hit[0] < SET_CACHE_S:
            return hit[1], list(hit[2])
        info = await self._call("resolve_playlist", cfg.playlist)
        if not info:
            raise LookupError(sentence("playlist_unresolved"))
        items = [SetItem(**it) for it in await self._call("playlist_items", info["id"])]
        self._set_cache[key] = (self.deps.clock(), info, items)
        return info, list(items)

    async def preview(self, cfg: ProgramConfig, count: int = 20, refresh: bool = False) -> dict:
        """What the editor draws for `cfg`: the whole set, one pass of the
        program with its slots (`lap_items`), the next `count` items from the
        first song with an empty line, the Auto pattern written as Manual
        slots (what "edit by hand" copies), and — with a night running — the
        set song playing now. Reads the set; changes nothing."""
        try:
            info, items = await self.read_set(cfg, refresh=refresh)
        except LookupError as exc:
            return {"status": "refused", "reason": "playlist_unresolved", "detail": str(exc)}
        lap = program.lap(cfg, items)
        lap_items = program.project(cfg, items, Cursor(), [], len(items) + lap.slots)
        out = program.with_start_times(program.project(cfg, items, Cursor(), [], count), 0)
        n = self.night
        playhead = (n.cursor.set_pos if self.running and n is not None and n.cursor.started
                    and n.playlist_id == info.get("id") else None)
        return {"status": "ok", "playlist_name": info.get("name") or "",
                "playlist_uri": info.get("uri") or "", "set_songs": len(items),
                "set": [it.model_dump(mode="json") for it in items],
                "lap_items": [i.as_dict() for i in lap_items],
                "next": [i.as_dict() for i in out],
                "manual_equivalent": [m.model_dump(mode="json")
                                      for m in program.as_manual(cfg, items)],
                "playhead": playhead,
                "lap": {"set_songs": lap.set_songs, "slots": lap.slots,
                        "unbounded": lap.unbounded, "notes": lap.notes}}

    async def move_set_song(self, from_index: int, to_index: int) -> dict:
        """Reorder the SET PLAYLIST in Spotify: the song at `from_index` to
        `to_index`. During a night, only songs at least two ahead of the one
        playing may move (report §5: a playing client may hold its old
        snapshot of the next song), and the positions are checked against a
        fresh read so a stale editor can't move the wrong song. Before the
        cursor confirms the playing song (the settle window right after a
        Start), the chosen start index stands in for it; a follow-mode night
        (no chosen start) refuses every move until its cursor starts."""
        cfg = self.cfg if self.running else self.deps.load_config()
        async with self._get_lock():
            try:
                info = await self._call("resolve_playlist", cfg.playlist)
                if not info:
                    raise LookupError(sentence("playlist_unresolved"))
                items = [SetItem(**it) for it in await self._call("playlist_items", info["id"])]
            except Exception as exc:
                return {"status": "refused", "reason": "playlist_unresolved",
                        "detail": sentence("playlist_unresolved", _err(exc))}
            frm, to = int(from_index), int(to_index)
            if not (0 <= frm < len(items) and 0 <= to < len(items)):
                return {"status": "refused", "reason": "bad_position",
                        "detail": sentence("bad_position")}
            if frm == to:
                return {"status": "moved", "set": [it.model_dump(mode="json") for it in items]}
            n = self.night
            if self.running and n is not None:
                if n.cursor.started:
                    floor = n.cursor.set_pos + 2
                elif n.start_index is not None:
                    floor = n.start_index + 2
                else:
                    floor = len(items)
                if min(frm, to) < floor:
                    return {"status": "refused", "reason": "too_close",
                            "detail": sentence("too_close")}
            insert_before = to + 1 if to > frm else to
            try:
                snap = await self._call("reorder", info["id"], frm, insert_before,
                                        info.get("snapshot_id") or "")
            except Exception as exc:
                return {"status": "refused", "reason": "spotify_error",
                        "detail": sentence("spotify_error", _err(exc))}
            moved = items.pop(frm)
            items.insert(to, moved)
            self._set_cache[cfg.playlist.strip()] = (
                self.deps.clock(), {**info, "snapshot_id": snap or ""}, list(items))
            if self.running and n is not None and n.playlist_id == info["id"]:
                n.set_items = list(items)
                n.snapshot_id = snap or n.snapshot_id
                n.cursor = program.reanchor(n.set_items, n.cursor)
                self._log(f"moved {moved.title or moved.uri} from set song {frm + 1} to {to + 1}")
                await self._persist()
            return {"status": "moved", "set": [it.model_dump(mode="json") for it in items]}

    # ── a restart ───────────────────────────────────────────────────────────

    def recover(self) -> None:
        """At startup: a night a previous process left running is followed
        again (its committed song may still be in Spotify's queue, so the
        first step re-reads the queue before anything is sent), unless it
        is older than MAX_NIGHT_S. Nothing here calls Spotify or plays, and
        it never raises into the startup that calls it."""
        try:
            self._recover()
        except Exception:                                         # noqa: BLE001
            logger.exception("Jukebox: recovering the last night failed")

    def _recover(self) -> None:
        self._ensure_loaded()
        n = self.night
        if n is None or n.state != "running":
            return
        self.cfg = self.deps.load_config()
        if self.deps.now_ms() - n.started_ms > MAX_NIGHT_S * 1000:
            n.state, n.ended_ms = "ended", self.deps.now_ms()
            n.end_reason = "stale"
            n.end_detail = sentence("stale", hours=int(MAX_NIGHT_S // 3600))
            self._log(f"night ended: {n.end_detail}")
            store.save_night_dict(n.model_dump(mode="json"), list(self.history))
            return
        self.rt = _Runtime(resync_needed=True, last_sleep_check=-SLEEP_CHECK_S)
        self.rt.warnings = {}
        self._log("SpotFX restarted; following the night again")
        store.save_night_dict(n.model_dump(mode="json"), list(self.history))


runner = JukeboxRunner()


def night_running() -> bool:
    """Is a Jukebox night running? (Absorb's `jukebox_night` gate.)"""
    try:
        runner._ensure_loaded()
    except Exception:                                             # noqa: BLE001
        return False
    return runner.running
