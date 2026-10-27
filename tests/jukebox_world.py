"""A fake world for the Jukebox's program engine (services/jukebox/night.py):
a Spotify player, its queue and the clock, all in memory.

Nothing here touches the network or his storage. The engine is driven
exactly as production drives it: `step()` reads `current_track` (what the
SpotFX poll would report) and reaches Spotify only through the gateway.

The player follows Spotify's documented queue rule (the study's §2.3):
"Add to queue" items play before the context's next track, then the context
resumes where it was. `lock_ms` models the one timing risk the study names
(risk 5): a player that has already picked its next track that long before
a song ends (a crossfade) plays that pick even if a song is queued later —
the late song then plays one track later.
"""
from __future__ import annotations

from typing import Any, Optional

from models.jukebox import ProgramConfig
from models.state import SpotifyTrackInfo
from services.jukebox.night import JukeboxDeps, JukeboxRunner

DEVICE = "Serenity"
PLAYLIST_ID = "SETPLAYLIST000000001"
PLAYLIST_URI = f"spotify:playlist:{PLAYLIST_ID}"


def set_uri(n: int) -> str:
    return f"spotify:track:set{n:03d}aaaaaaaaaaaaaa"


def jb_uri(n: int) -> str:
    return f"spotify:track:jbx{n:03d}bbbbbbbbbbbbbb"


class FakeClock:
    def __init__(self, t: float = 10_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class FakePlayer:
    def __init__(self, clock: FakeClock, context: list[str], durations: dict[str, int]) -> None:
        self.clock = clock
        self.context = list(context)
        self.context_uri = PLAYLIST_URI
        self.durations = durations
        self.ctx_pos = -1
        self.repeat = "off"
        self.shuffle = True              # a player left on shuffle: the engine must turn it off
        self.smart_shuffle = False
        self.user_queue: list[str] = []
        self.current: Optional[str] = None
        self.progress_ms = 0
        self.is_playing = False
        self.device = DEVICE
        self.lock_ms = 0
        self.decided: Optional[tuple[str, Any]] = None
        self.started: list[str] = []     # every song that started, in order
        self.foreign_context: Optional[str] = None

    # what plays next, by Spotify's rule
    def _pick(self) -> Optional[tuple[str, Any]]:
        if self.user_queue:
            return ("q", self.user_queue[0])
        nxt = self.ctx_pos + 1
        if nxt >= len(self.context):
            if self.repeat != "context":
                return None
            nxt = 0
        return ("c", nxt)

    def _begin(self, uri: str) -> None:
        self.current, self.progress_ms, self.is_playing = uri, 0, True
        self.decided = None
        self.started.append(uri)

    def start_context(self, pos: int) -> None:
        self.user_queue.clear()
        self.ctx_pos = pos
        self._begin(self.context[pos])

    def go_next(self) -> None:
        choice = self.decided or self._pick()
        self.decided = None
        if choice is None:
            self.is_playing = False
            self.progress_ms = self.durations.get(self.current or "", 0)
            return
        kind, val = choice
        if kind == "q":
            self.user_queue.remove(val)
            self._begin(val)
        else:
            self.ctx_pos = val
            self._begin(self.context[val])

    def advance_1s(self) -> None:
        if not self.is_playing or self.current is None:
            return
        dur = self.durations[self.current]
        self.progress_ms = min(dur, self.progress_ms + 1000)
        left = dur - self.progress_ms
        if self.lock_ms and self.decided is None and 0 < left <= self.lock_ms:
            self.decided = self._pick()
        if self.progress_ms >= dur:
            self.go_next()

    def queue_view(self) -> list[str]:
        out = list(self.user_queue)
        pos = self.ctx_pos
        for _ in range(10):
            pos += 1
            if pos >= len(self.context):
                if self.repeat != "context":
                    break
                pos = 0
            out.append(self.context[pos])
        return out


class FakeGateway:
    """The JukeboxGateway's methods, over the FakePlayer. Records every call
    with the fake time it was made at."""

    def __init__(self, player: FakePlayer, clock: FakeClock, titles: dict[str, str]) -> None:
        self.p = player
        self.clock = clock
        self.titles = titles
        self.calls: list[tuple[float, str, tuple]] = []
        self.fail: dict[str, int] = {}          # method -> how many calls fail
        self.hide_from_queue: set[str] = set()  # a read-back that doesn't show these
        self.devices = {DEVICE: "dev-serenity"}
        self.snapshot = "snap-1"

    def _rec(self, name: str, *args: Any) -> None:
        self.calls.append((self.clock.t, name, args))
        if self.fail.get(name, 0) > 0:
            self.fail[name] -= 1
            raise RuntimeError(f"{name} failed")

    def names(self) -> list[str]:
        return [c[1] for c in self.calls]

    def device_id(self, name):
        self._rec("device_id", name)
        return self.devices.get(name)

    def playback(self):
        self._rec("playback")
        if self.p.current is None:
            return None
        return {"uri": self.p.current, "is_playing": self.p.is_playing,
                "progress_ms": self.p.progress_ms,
                "duration_ms": self.p.durations[self.p.current],
                "device_name": self.p.device, "context_uri": self.p.context_uri,
                "shuffle": self.p.shuffle, "smart_shuffle": self.p.smart_shuffle,
                "repeat": self.p.repeat}

    def start_context(self, device_id, context_uri, position=0):
        self._rec("start_context", device_id, context_uri, position)
        self.p.start_context(position)

    def set_shuffle(self, on, device_id=None):
        self._rec("set_shuffle", on)
        if not getattr(self, "shuffle_stuck", False):
            self.p.shuffle = bool(on)

    def set_repeat(self, mode, device_id=None):
        self._rec("set_repeat", mode)
        self.p.repeat = mode

    def pause(self, device_id=None):
        self._rec("pause")
        self.p.is_playing = False

    def add_to_queue(self, uri):
        self._rec("add_to_queue", uri)
        self.p.user_queue.append(uri)

    def queue(self):
        self._rec("queue")
        return {"current": self.p.current or "",
                "queue": [u for u in self.p.queue_view() if u not in self.hide_from_queue]}

    def next_track(self):
        self._rec("next_track")
        self.p.go_next()

    def resolve_playlist(self, link):
        self._rec("resolve_playlist", link)
        if PLAYLIST_ID not in link:
            return None
        return {"id": PLAYLIST_ID, "name": "Saturday set", "uri": PLAYLIST_URI,
                "snapshot_id": self.snapshot}

    def playlist_snapshot(self, pid):
        self._rec("playlist_snapshot", pid)
        return self.snapshot

    def playlist_items(self, pid):
        self._rec("playlist_items", pid)
        return [{"uri": u, "title": self.titles.get(u, u[-17:-14]), "artist": "Set",
                 "duration_ms": self.p.durations[u]} for u in self.p.context]

    def track(self, uri):
        self._rec("track", uri)
        if uri not in self.p.durations:
            return None
        return {"uri": uri, "title": self.titles.get(uri, uri[-17:-14]), "artist": "Guest",
                "duration_ms": self.p.durations[uri], "explicit": False}


async def _inline(fn, *args):
    return fn(*args)


class World:
    def __init__(self, n_set: int = 12, set_s: int = 120, n_jb: int = 12, jb_s: int = 100,
                 **cfg: Any) -> None:
        self.clock = FakeClock()
        sets = [set_uri(i) for i in range(n_set)]
        jbs = [jb_uri(i) for i in range(n_jb)]
        durations = {u: set_s * 1000 for u in sets}
        durations.update({u: jb_s * 1000 for u in jbs})
        titles = {u: f"S{i}" for i, u in enumerate(sets)}
        titles.update({u: f"J{i}" for i, u in enumerate(jbs)})
        self.titles = titles
        self.player = FakePlayer(self.clock, sets, durations)
        self.gw = FakeGateway(self.player, self.clock, titles)
        self.cfg = ProgramConfig(playlist=PLAYLIST_URI, **cfg)
        self.asleep: Optional[bool] = False
        self.absorb = False
        self.on_device = True
        self.deps = JukeboxDeps(
            gateway=self.gw, current_track=self.track, device_name=lambda: DEVICE,
            sleeping=self._sleeping, absorb_busy=lambda: self.absorb, to_thread=_inline,
            clock=self.clock, now_ms=lambda: int(self.clock.t * 1000),
            load_config=lambda: self.cfg)
        self.runner = JukeboxRunner(self.deps)
        self.ticks_paused = False

    async def _sleeping(self) -> Optional[bool]:
        return self.asleep

    def track(self) -> Optional[SpotifyTrackInfo]:
        p = self.player
        if p.current is None:
            return None
        ctx = p.context_uri
        if p.foreign_context:
            ctx = p.foreign_context
        return SpotifyTrackInfo(
            spotify_uri=p.current, title=self.titles.get(p.current, ""), artist="",
            duration_ms=p.durations[p.current], progress_ms=p.progress_ms,
            is_playing=p.is_playing, fetched_at=self.clock.t,
            device_name=p.device if self.on_device else "Javi's phone", context_uri=ctx,
            context_type="playlist")

    async def start(self, play: bool = True, start_index: int = 0) -> dict:
        return await self.runner.start(play=play, start_index=start_index)

    async def add(self, n: int) -> dict:
        return await self.runner.add(jb_uri(n))

    async def run(self, seconds: int, *, engine: bool = True) -> None:
        """Advance the world one second at a time; the engine steps each
        second unless `engine` is False (a stalled engine)."""
        for _ in range(int(seconds)):
            self.player.advance_1s()
            self.clock.t += 1.0
            if engine:
                await self.runner.step()

    def played(self) -> list[str]:
        """Every song that started, by its short title (S3, J1, ...)."""
        return [self.titles.get(u, u) for u in self.player.started]
