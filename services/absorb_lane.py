"""
ABSORB'S BACKLOG ON THE HIDDEN PLAYER (the Jukebox plan's phase 4, PR 4.4;
the study's Q9: "let the capture lane work through Absorb's backlog when the
Jukebox is idle? — yes, Absorb no longer needs silent evenings"): while
nothing else wants the hidden player, it learns the linked playlist's songs
that have never been captured, one at a time, through the capture lane
(capture_lane/, services/jukebox/lane_client.py).

IT SHIPS OFF (`AbsorbConfig.use_capture_lane`) and acts only when ALL hold:
  * the switch is on and a playlist is linked;
  * no Jukebox night runs (the night's learning queue owns the lane then —
    services/jukebox/learning.py) and no Absorb window is open (that plays
    the same playlist on Serenity, and two captures of one song would write
    the same files);
  * the house reads AWAKE — `sleeping` on, or unreadable, is a stop. The
    lane is inaudible, but Order 27's only exception is his grant for
    Absorb's own proven-silent windows, so this conservative rule holds
    until he says otherwise;
  * account B is signed in, the second account's switch on SPECTRA's
    Settings page is ON (fx/second_account.py — it ships off, and off or
    unreadable is a rest), and the lane answers.
When any of them stops holding while a song is being learned, that song is
cancelled (the lane lets go on its way out, pausing only its own song).

WHAT IT TAKES: Absorb's own bar (services/absorb_bar.py) calls a song
"fresh" (no complete shape) or "recapture" (a complete shape that fails the
bar). The lane only ever learns FRESH songs — it never captures over a shape
(capture_lane/lane.py) — so a headless or analysis-less shape stays Absorb's
own forced re-capture, whose realign moves his triggers with it. A song the
house is capturing right now is left alone.

WHAT IT DOESN'T DO: it never writes his playlists. A song it learns passes
Absorb's bar from then on, so Absorb files it into Recently Captured as
"already captured" on its next window — the playlist bookkeeping stays
Absorb's, which already asks first about it.

One song at a time, in playlist order; a song that fails `max_attempts`
times (Absorb's own setting) is passed over until the switch is turned off
and on again or SpotFX restarts. Every lane call and file read is off the
event loop; the playlist is read at most every PLAYLIST_TTL_S.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

POLL_S = 5.0
IDLE_POLL_S = 30.0
PLAYLIST_TTL_S = 15 * 60
DOWN_BACKOFF_S = 300.0
SLEEP_CHECK_S = 60.0

# the lane's outcomes that say the hidden player can't be used (not the song's fault)
LANE_DOWN = frozenset({"not_signed_in", "wrong_account", "cannot_check_account",
                       "device_missing", "device_ambiguous", "device_restricted", "no_audio"})
NOT_A_TRY = frozenset({"cancelled", "already_learned", "account_locked"})

WORDS = {
    "off": "Off: the hidden player only learns songs during a Jukebox night.",
    "no_playlist": "No playlist is linked.",
    "night": "A Jukebox night is running; the hidden player is the night's.",
    "window": "An Absorb window is open; it captures the playlist itself.",
    "sleeping": "The house is asleep, so the hidden player rests.",
    "sleep_unknown": "Whether the house is asleep can't be read, so the hidden player rests.",
    "signed_out": "The capture account isn't signed in.",
    "account_locked": "The second Spotify account is switched off on SPECTRA's Settings page, "
                      "so the hidden player rests.",
    "lane_off": "The hidden player isn't running.",
    "busy": "The hidden player is busy.",
    "done": "Every song in the playlist that was never captured has been tried.",
}


def _second_account_unlocked() -> bool:
    from fx import second_account
    return second_account.write_allowed()


@dataclass
class BacklogDeps:
    lane: Any
    config: Callable[[], Any]                              # AbsorbConfig
    playlist: Callable[[str], list[dict]]                  # blocking: source uri -> [{uri, title, duration_ms}]
    classify: Callable[[str, int], Any]                    # blocking: absorb_bar.classify
    track: Callable[[str], Optional[dict]]                 # blocking: {title, artist, duration_ms}
    genres: Callable[[str], list[str]]                     # blocking, best-effort
    night_running: Callable[[], bool]
    absorb_busy: Callable[[], bool]
    sleeping: Callable[[], Awaitable[Optional[bool]]]
    signed_in: Callable[[], bool]
    recording_uri: Callable[[], Optional[str]]
    after_learned: Callable[[str], Awaitable[None]]
    # the second account's lock (fx/second_account.py), read fresh every tick
    unlocked: Callable[[], bool] = _second_account_unlocked
    clock: Callable[[], float] = time.monotonic
    now_ms: Callable[[], int] = lambda: int(time.time() * 1000)
    to_thread: Callable[..., Awaitable[Any]] = asyncio.to_thread


def production_deps() -> BacklogDeps:
    from api import spotify_capture
    from services import absorb, absorb_bar, absorb_spotify, absorb_store
    from services.audio_shape_service import audio_shape_service
    from services.jukebox import gateway as jb_gateway
    from services.jukebox import night
    from services.jukebox.lane_client import LaneClient

    def playlist(link: str) -> list[dict]:
        pid = absorb_spotify.parse_playlist_id(link)
        return absorb_spotify.default_gateway().playlist_tracks(pid) if pid else []

    async def sleeping() -> Optional[bool]:
        from api import ha_client
        return (await ha_client.from_settings().read()).sleeping

    async def after_learned(uri: str) -> None:
        # what a normal capture does on success (audio_shape_service)
        from models.state import state as app_state
        from services import audio_shape_service as shapes
        await shapes._after_successful_capture(uri)
        if app_state.auto_generate_enabled:
            asyncio.create_task(shapes._auto_generate_for_uri(uri))

    return BacklogDeps(
        lane=LaneClient(), config=absorb_store.load_config, playlist=playlist,
        classify=lambda uri, head: absorb_bar.classify(uri, head),
        track=lambda uri: jb_gateway.default_gateway().track(uri),
        genres=lambda uri: jb_gateway.default_gateway().track_genres(uri),
        night_running=night.night_running, absorb_busy=lambda: bool(absorb.runner.open_window),
        sleeping=sleeping, signed_in=lambda: bool(spotify_capture.status()["signed_in"]),
        recording_uri=lambda: audio_shape_service.recording_uri, after_learned=after_learned)


class LaneBacklog:
    def __init__(self, deps: Optional[BacklogDeps] = None) -> None:
        self._deps = deps
        self.state = "off"           # "off" | "resting" | "learning" | "idle"
        self.reason = WORDS["off"]
        self.job: Optional[dict] = None
        self.attempts: dict[str, int] = {}
        self.learned: list[dict] = []
        self.failed: list[dict] = []
        self.down_until = 0.0
        self.log: list[str] = []
        self._songs: list[dict] = []
        self._songs_for = ""
        self._songs_at = -1e9
        self._sleep_at = -1e9
        self._asleep: Optional[bool] = None
        self._was_on = False
        self._kick: Optional[asyncio.Event] = None

    @property
    def deps(self) -> BacklogDeps:
        if self._deps is None:
            self._deps = production_deps()
        return self._deps

    def _note(self, text: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')} {text}")
        del self.log[:-40]
        logger.info("Absorb on the hidden player: %s", text)

    def kick(self) -> None:
        try:
            if self._kick is None:
                self._kick = asyncio.Event()
            self._kick.set()
        except Exception:                                         # noqa: BLE001
            pass

    def status(self) -> dict:
        return {"state": self.state, "reason": self.reason, "job": self.job,
                "learned": self.learned[-20:], "failed": self.failed[-20:],
                "passed_over": sorted(u for u, n in self.attempts.items()
                                      if n >= self._max_attempts()),
                "log": self.log[-20:]}

    def _max_attempts(self) -> int:
        try:
            return int(self.deps.config().max_attempts)
        except Exception:                                         # noqa: BLE001
            return 3

    async def _rest(self, why: str, state: str = "resting") -> None:
        """Not now: say why, and cancel a song this worker started."""
        self.state, self.reason = state, WORDS.get(why, why)
        if self.job is not None:
            from services.jukebox.lane_client import LaneUnavailable
            job, self.job = self.job, None
            try:
                await self.deps.lane.cancel(job["job_id"])
                self._note(f"stopped learning {job['title'] or job['uri']} ({why})")
            except LaneUnavailable:
                pass

    async def _house_asleep(self) -> Optional[bool]:
        d = self.deps
        if d.clock() - self._sleep_at >= SLEEP_CHECK_S:
            self._sleep_at = d.clock()
            try:
                self._asleep = await d.sleeping()
            except Exception:                                     # noqa: BLE001
                self._asleep = None
        return self._asleep

    async def tick(self) -> None:
        d = self.deps
        cfg = d.config()
        on = bool(cfg.use_capture_lane)
        if on and not self._was_on:
            self.attempts.clear()             # switched on again: every song gets its tries back
            self._songs_at = -1e9
        self._was_on = on
        if not on:
            return await self._rest("off", "off")
        if not cfg.source_playlist_uri:
            return await self._rest("no_playlist")
        if d.night_running():
            return await self._rest("night")
        if d.absorb_busy():
            return await self._rest("window")
        asleep = await self._house_asleep()
        if asleep is not False:
            return await self._rest("sleeping" if asleep else "sleep_unknown")
        if not d.signed_in():
            return await self._rest("signed_out")
        if not d.unlocked():
            return await self._rest("account_locked")
        from services.jukebox.lane_client import LaneBusy, LaneUnavailable
        try:
            lane = await d.lane.status()
        except LaneUnavailable:
            self.state, self.reason = "resting", WORDS["lane_off"]
            return
        if d.clock() < self.down_until:
            self.state = "resting"
            return
        if self.job is not None:
            done = next((o for o in lane.get("outcomes") or [] if o.get("job_id") == self.job["job_id"]), None)
            running = (lane.get("job") or {}).get("job_id") == self.job["job_id"]
            if done is not None:
                await self._finish(self.job, done, lane)
                self.job = None
                if d.clock() < self.down_until:
                    self.state = "resting"     # the hidden player can't be used: nothing new now
                    return
            elif running:
                if d.recording_uri() == self.job["uri"]:
                    # the house started playing it: its own capture learns it
                    return await self._rest("the house is playing this song now", "learning")
                self.state, self.reason = "learning", ""
                return
            else:
                self.job = None                # the lane forgot it (a restart): try again later
        if lane.get("state") != "idle":
            self.state, self.reason = "resting", WORDS["busy"]
            return
        song = await self._next_song(cfg)
        if song is None:
            self.state, self.reason = "idle", WORDS["done"]
            return
        meta = None
        try:
            meta = await d.to_thread(d.track, song["uri"])
        except Exception as exc:                                  # noqa: BLE001
            logger.debug("Absorb on the hidden player: track read failed: %s", exc)
        if not meta:
            self.attempts[song["uri"]] = self.attempts.get(song["uri"], 0) + 1
            self._note(f"couldn't read {song.get('title') or song['uri']} from Spotify")
            return
        try:
            genres = list(await d.to_thread(d.genres, song["uri"]) or [])
        except Exception:                                         # noqa: BLE001
            genres = []
        job = {"job_id": uuid.uuid4().hex[:12], "uri": song["uri"], "title": meta.get("title") or "",
               "artist": meta.get("artist") or "",
               "duration_ms": int(meta.get("duration_ms") or song.get("duration_ms") or 0),
               "genres": genres}
        try:
            await d.lane.learn(job)
        except (LaneBusy, LaneUnavailable) as exc:
            self._note(f"the hidden player didn't take {job['title'] or job['uri']} ({exc})")
            return
        self.job = {**job, "started_ms": d.now_ms()}
        self.state, self.reason = "learning", ""
        self._note(f"learning {job['artist']} — {job['title']}")

    async def _finish(self, job: dict, o: dict, lane: dict) -> None:
        d = self.deps
        reason = o.get("reason") or ""
        name = f"{job['artist']} — {job['title']}" if job.get("artist") else job["title"] or job["uri"]
        if o.get("status") == "ok":
            self.attempts.pop(job["uri"], None)
            self.learned.append({"uri": job["uri"], "title": name, "at_ms": d.now_ms()})
            del self.learned[:-50]
            self._note(f"learned {name}")
            try:
                await d.after_learned(job["uri"])
            except Exception as exc:                              # noqa: BLE001
                logger.warning("Absorb on the hidden player: follow-up for %s failed: %s", job["uri"], exc)
            return
        if reason in LANE_DOWN:
            self.down_until = d.clock() + DOWN_BACKOFF_S
            said = (lane.get("sentences") or {}).get(reason, reason)
            self.reason = f"{said} Trying again in a few minutes."
            self._note(f"the hidden player can't learn right now ({reason})")
            return
        if reason in NOT_A_TRY:
            return
        n = self.attempts.get(job["uri"], 0) + 1
        self.attempts[job["uri"]] = n
        self.failed.append({"uri": job["uri"], "title": name, "reason": reason, "attempt": n,
                            "at_ms": d.now_ms()})
        del self.failed[:-50]
        self._note(f"learning {name} failed ({reason}), try {n}")

    async def _next_song(self, cfg) -> Optional[dict]:
        """The first song in the linked playlist that has never been captured,
        hasn't used up its tries, and isn't being captured by the house."""
        d = self.deps
        if self._songs_for != cfg.source_playlist_uri or d.clock() - self._songs_at >= PLAYLIST_TTL_S:
            try:
                self._songs = list(await d.to_thread(d.playlist, cfg.source_playlist_uri) or [])
                self._songs_for, self._songs_at = cfg.source_playlist_uri, d.clock()
            except Exception as exc:                              # noqa: BLE001
                self._note(f"couldn't read the playlist ({type(exc).__name__})")
                self._songs_at = d.clock()
                return None
        max_tries = int(cfg.max_attempts)
        recording = d.recording_uri()
        for song in self._songs:
            uri = song.get("uri") or ""
            if not uri.startswith("spotify:track:") or uri == recording:
                continue
            if self.attempts.get(uri, 0) >= max_tries:
                continue
            verdict = await d.to_thread(d.classify, uri, int(cfg.head_max_ms))
            if getattr(verdict, "kind", "") == "fresh":
                return song
        return None

    async def run_supervised(self) -> None:
        """Its own task: a pass every POLL_S while switched on, IDLE_POLL_S
        while off (a single config read)."""
        if self._kick is None:
            self._kick = asyncio.Event()
        while True:
            try:
                on = bool(self.deps.config().use_capture_lane)
                try:
                    await asyncio.wait_for(self._kick.wait(), timeout=POLL_S if on else IDLE_POLL_S)
                except asyncio.TimeoutError:
                    pass
                self._kick.clear()
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:                                     # noqa: BLE001
                logger.exception("Absorb on the hidden player: a pass failed")
                await asyncio.sleep(POLL_S)


backlog = LaneBacklog()
