"""A fake world for the Absorb Music runner (services/absorb.py): Spotify,
the capture service, the shape disk and the clock, all in memory.

Nothing here touches the network, an audio device or his storage. The
runner is driven exactly as production drives it: `on_track_state(track)` on
every "poll", condemnations through the capture service's listener list,
outcomes through its outcome listeners.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from models.state import SpotifyTrackInfo
from services import absorb, absorb_bar, absorb_store
from services.audio_shape_service import CaptureOutcome
from services.capture_watch import Condemnation

DEVICE = "Serenity"
SOURCE = "spotify:playlist:SOURCEPLAYLIST00001"
SOURCE_ID = "SOURCEPLAYLIST00001"


def uri(n: int) -> str:
    return f"spotify:track:song{n:03d}"


class FakeGateway:
    """Spotify, in memory. Records every call."""

    def __init__(self) -> None:
        self.devices = {DEVICE: "dev-serenity"}
        self.playlists: dict[str, list[str]] = {SOURCE_ID: []}
        self.names: dict[str, str] = {SOURCE_ID: "Absorb me"}
        self.snapshots: dict[str, int] = {SOURCE_ID: 1}
        self.calls: list[tuple] = []
        self.plays: list[list[str]] = []
        self.pauses = 0
        self.fail_remove_from: set[str] = set()
        self.fail_play = False
        self.titles: dict[str, str] = {}
        self.now_playing: Optional[dict] = None    # {uri, is_playing, device_name}
        self.playback_unknown = False

    def _bump(self, pid: str) -> str:
        self.snapshots[pid] = self.snapshots.get(pid, 0) + 1
        return f"{pid}-snap{self.snapshots[pid]}"

    def device_id(self, name):
        self.calls.append(("device_id", name))
        return self.devices.get(name)

    def play(self, device_id, uris):
        self.calls.append(("play", list(uris)))
        if self.fail_play:
            raise RuntimeError("Spotify said no")
        self.plays.append(list(uris))

    def pause(self, device_id):
        self.calls.append(("pause",))
        self.pauses += 1
        if self.now_playing is not None:
            self.now_playing["is_playing"] = False

    def current_playback(self):
        """What Spotify says is playing (absorb_silence's "is absorb's song
        still on" read); `playback_unknown` makes it raise."""
        self.calls.append(("current_playback",))
        if self.playback_unknown:
            raise RuntimeError("Spotify can't say")
        if self.now_playing is None:
            return None
        return dict(self.now_playing)

    def resolve_playlist(self, link):
        self.calls.append(("resolve_playlist", link))
        pid = link.split(":")[-1]
        if pid not in self.playlists:
            return None
        return {"id": pid, "name": self.names.get(pid, ""), "snapshot_id": self.snapshot(pid)}

    def snapshot(self, pid):
        return f"{pid}-snap{self.snapshots.get(pid, 0)}"

    def playlist_snapshot(self, pid):
        self.calls.append(("playlist_snapshot", pid))
        return self.snapshot(pid)

    def playlist_tracks(self, pid):
        self.calls.append(("playlist_tracks", pid))
        return [{"uri": u, "title": self.titles.get(u, u[-6:]), "duration_ms": 200_000}
                for u in self.playlists.get(pid, [])]

    def remove_tracks(self, pid, uris):
        self.calls.append(("remove_tracks", pid, list(uris)))
        if pid in self.fail_remove_from:
            raise RuntimeError("remove failed")
        self.playlists[pid] = [u for u in self.playlists.get(pid, []) if u not in set(uris)]
        return self._bump(pid)

    def add_tracks_top(self, pid, uris):
        self.calls.append(("add_tracks_top", pid, list(uris)))
        self.playlists[pid] = list(uris) + self.playlists.get(pid, [])
        return self._bump(pid)

    def tracks_beyond(self, pid, keep):
        self.calls.append(("tracks_beyond", pid, keep))
        return self.playlists.get(pid, [])[keep:]

    def find_or_create_playlist(self, name, known_id=""):
        self.calls.append(("find_or_create_playlist", name))
        for pid, n in self.names.items():
            if n == name:
                return pid
        pid = "RECENTLYCAPTURED001"
        self.names[pid] = name
        self.playlists[pid] = []
        return pid

    def writes(self) -> list[tuple]:
        return [c for c in self.calls
                if c[0] in ("remove_tracks", "add_tracks_top", "play", "pause")]

    @property
    def rc(self) -> list[str]:
        for pid, n in self.names.items():
            if n == "Recently Captured":
                return self.playlists[pid]
        return []


class FakeCapture:
    """audio_shape_service's surface the runner uses."""

    def __init__(self) -> None:
        self.force_uris: set[str] = set()
        self.preroll_uris: set[str] = set()
        self.condemn_listeners: list = []
        self.outcome_listeners: list = []
        self.recording_uri: Optional[str] = None
        self.started_at: dict[str, float] = {}

    def start(self, u: str, at: float) -> None:
        self.recording_uri = u
        self.started_at[u] = at

    def condemn(self, u: str, reason: str = "gap", detail: str = "9373 ms gap") -> None:
        for fn in list(self.condemn_listeners):
            fn(Condemnation(u, reason, detail))

    def outcome(self, u: str, status: str = "ok", reason: str = "", realign=None,
                started_at: Optional[float] = None) -> None:
        o = CaptureOutcome(u, status, reason, forced=False, realign=realign,
                           capture_started_at=self.started_at.get(u) if started_at is None
                           else started_at)
        if self.recording_uri == u:
            self.recording_uri = None
        for fn in list(self.outcome_listeners):
            fn(o)


class Disk:
    """The shape disk as the bar sees it: uri -> (kind, reasons, head_ms)."""

    def __init__(self) -> None:
        self.shapes: dict[str, tuple[str, list[str], Optional[int]]] = {}

    def set(self, u: str, kind: str, reasons=(), head_ms: Optional[int] = None) -> None:
        self.shapes[u] = (kind, list(reasons), head_ms)

    def classify(self, u: str, head_max_ms: int, force: bool = False) -> absorb_bar.Verdict:
        kind, reasons, head = self.shapes.get(u, ("fresh", ["no_shape"], None))
        if kind == "skip" and force:
            kind, reasons = "recapture", ["force_recapture"]
        return absorb_bar.Verdict(uri=u, kind=kind, reasons=list(reasons), head_ms=head,
                                  duration_ms=200_000, title=u[-6:])

    def has_head(self, u: str, head_max_ms: int):
        v = self.classify(u, head_max_ms, False)
        return v.kind == "skip", v


class World:
    def __init__(self, tmp_path, monkeypatch, guard: Optional[absorb.HouseGuard] = None,
                 capture=None, **cfg) -> None:
        monkeypatch.setattr(absorb_store, "CONFIG_FILE", tmp_path / "absorb.json")
        monkeypatch.setattr(absorb_store, "RUN_FILE", tmp_path / "absorb_run.json")
        monkeypatch.setattr(absorb_store, "LEDGER_FILE", tmp_path / "absorb_ledger.json")
        from services import absorb_silence
        monkeypatch.setattr(absorb_silence, "SNAPSHOT_FILE", tmp_path / "absorb_silence.json")
        self.gw = FakeGateway()
        self.cap = capture if capture is not None else FakeCapture()
        self.disk = Disk()
        self.clock = [1000.0]
        self.track: Optional[SpotifyTrackInfo] = None
        self.analysis = True
        self.anchors = True
        self.spectra: Optional[tuple] = None
        self.governor_reading: Optional[dict] = {"seq": 24, "dropped_total_ms": 14243}
        self.bursts: list[float] = []
        self.poll_ok: Optional[bool] = True
        self.fast_polls: list[bool] = []

        async def inline(fn, *a):
            return fn(*a)

        async def spectra_runs():
            return self.spectra

        self.deps = absorb.AbsorbDeps(
            gateway=self.gw, capture=self.cap,
            guard=guard if guard is not None else absorb.HouseGuard(),
            spectra_runs=spectra_runs,
            governor=lambda: self.governor_reading,
            classify=self.disk.classify, has_head=self.disk.has_head,
            analysis_enabled=lambda: self.analysis,
            anchor_enabled=lambda: self.anchors,
            current_track=lambda: self.track,
            device_name=lambda: DEVICE,
            to_thread=inline,
            request_burst=self.bursts.append,
            monotonic=lambda: self.clock[0],
            now_ms=lambda: int(self.clock[0] * 1000),
            poll_ok=lambda: self.poll_ok,
            set_fast_poll=self.fast_polls.append,
        )
        self.runner = absorb.AbsorbRunner(self.deps)
        self.runner.install()
        base = {"source_playlist_uri": SOURCE, "warm_up": True}
        base.update(cfg)
        absorb_store.save_config(absorb_store.load_config().model_copy(update=base))

    # ── driving ─────────────────────────────────────────────────────────────

    def run_(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def advance(self, seconds: float) -> None:
        self.clock[0] += seconds

    def playing(self, u: Optional[str], *, progress_ms: int = 5000, is_playing: bool = True,
                device: str = DEVICE, duration_ms: int = 200_000) -> None:
        if u is None:
            self.track = None
            self.gw.now_playing = None
            return
        self.gw.now_playing = {"uri": u, "is_playing": is_playing, "device_name": device}
        self.track = SpotifyTrackInfo(
            spotify_uri=u, title=u[-6:], artist="A", duration_ms=duration_ms,
            progress_ms=progress_ms, is_playing=is_playing, fetched_at=time.monotonic(),
            device_name=device)

    async def poll(self) -> None:
        await self.runner.on_track_state(self.track)
        await self.runner.settle()

    async def arrive(self, u: str, *, capture: bool = True) -> None:
        """Spotify starts `u`; on the following poll the capture is running."""
        self.playing(u, progress_ms=1000)
        await self.poll()
        if capture:
            self.cap.start(u, self.clock[0] + 0.5)
        self.advance(5)
        self.playing(u, progress_ms=6000)
        await self.poll()

    async def finish(self, u: str) -> None:
        """`u` plays to its end (the last poll sees it at its tail)."""
        self.playing(u, progress_ms=199_000)
        await self.poll()

    async def outcome(self, u: str, status: str = "ok", reason: str = "", **kw) -> None:
        self.cap.outcome(u, status, reason, **kw)
        await self.runner.settle()

    async def condemn(self, u: str, reason: str = "gap") -> None:
        self.cap.condemn(u, reason)
        await self.runner.settle()

    @property
    def run(self):
        return self.runner.run

    @property
    def last_play(self) -> list[str]:
        return self.gw.plays[-1] if self.gw.plays else []
