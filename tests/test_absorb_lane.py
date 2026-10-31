"""Absorb's backlog on the hidden player (services/absorb_lane.py, the Jukebox
plan's phase 4, PR 4.4): while it is switched on and nothing else wants the
hidden player, the capture lane learns the linked playlist's never-captured
songs, one at a time. Driven over a fake lane, a fake playlist and a fake
clock; nothing here reaches Spotify, the lane or a speaker.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import pytest

from models.absorb import AbsorbConfig
from services import absorb_lane as AL
from services.absorb_bar import Verdict
from services.jukebox.lane_client import LaneUnavailable

PLAYLIST = "spotify:playlist:absorbtest"


def u(n: int) -> str:
    return f"spotify:track:absorblane{n:012d}"


def _run(coro):
    return asyncio.run(coro)


async def _inline(fn, *args):
    return fn(*args)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class Lane:
    def __init__(self) -> None:
        self.up = True
        self.job: Optional[dict] = None
        self.outcomes: list[dict] = []
        self.jobs: list[dict] = []
        self.cancelled: list[str] = []
        self.status_calls = 0

    async def status(self) -> dict:
        self.status_calls += 1
        if not self.up:
            raise LaneUnavailable("the capture lane isn't answering")
        return {"state": "capturing" if self.job else "idle", "job": self.job,
                "outcomes": list(self.outcomes),
                "sentences": {"device_missing": "The hidden player isn't online."}}

    async def learn(self, job: dict) -> dict:
        self.job = dict(job)
        self.jobs.append(dict(job))
        return {"job_id": job["job_id"]}

    async def cancel(self, job_id: str) -> bool:
        self.cancelled.append(job_id)
        if self.job and self.job["job_id"] == job_id:
            self.finish("cancelled", "cancelled")
            return True
        return False

    def finish(self, status: str = "ok", reason: str = "") -> None:
        self.outcomes.append({"job_id": self.job["job_id"], "uri": self.job["uri"],
                              "status": status, "reason": reason})
        self.job = None


class World:
    def __init__(self, **cfg) -> None:
        self.clock = Clock()
        self.lane = Lane()
        self.cfg = AbsorbConfig(use_capture_lane=True, source_playlist_uri=PLAYLIST, **cfg)
        # songs 0-5: 1 already captured, 2 needs a re-capture, the rest fresh
        self.kinds = {u(0): "fresh", u(1): "skip", u(2): "recapture", u(3): "fresh",
                      u(4): "fresh", u(5): "fresh"}
        self.playlist_reads = 0
        self.night = False
        self.window = False
        self.asleep: Optional[bool] = False
        self.sleep_reads = 0
        self.signed = True
        self.recording: Optional[str] = None
        self.track_fails: set[str] = set()
        self.after: list[str] = []

        def playlist(link: str) -> list[dict]:
            self.playlist_reads += 1
            return [{"uri": x, "title": f"Artist — Song {i}", "duration_ms": 200_000}
                    for i, x in enumerate(self.kinds)]

        def classify(uri: str, head: int) -> Verdict:
            return Verdict(uri=uri, kind=self.kinds[uri])

        def track(uri: str) -> Optional[dict]:
            if uri in self.track_fails:
                return None
            n = list(self.kinds).index(uri)
            return {"title": f"Song {n}", "artist": "Artist", "duration_ms": 200_000}

        async def sleeping() -> Optional[bool]:
            self.sleep_reads += 1
            return self.asleep

        async def after(uri: str) -> None:
            self.after.append(uri)

        self.backlog = AL.LaneBacklog(AL.BacklogDeps(
            lane=self.lane, config=lambda: self.cfg, playlist=playlist, classify=classify,
            track=track, genres=lambda uri: ["disco"], night_running=lambda: self.night,
            absorb_busy=lambda: self.window, sleeping=sleeping, signed_in=lambda: self.signed,
            recording_uri=lambda: self.recording, after_learned=after,
            clock=self.clock, now_ms=lambda: int(self.clock.t * 1000), to_thread=_inline))

    async def tick(self, advance: float = AL.POLL_S) -> None:
        self.clock.t += advance
        await self.backlog.tick()


def test_off_by_default_and_off_touches_nothing():
    assert AbsorbConfig().use_capture_lane is False

    async def go():
        w = World()
        w.cfg = w.cfg.model_copy(update={"use_capture_lane": False})
        await w.tick()
        assert w.backlog.state == "off" and w.lane.status_calls == 0 and w.lane.jobs == []
        assert w.playlist_reads == 0 and w.sleep_reads == 0
    _run(go())


def test_it_learns_the_never_captured_songs_one_at_a_time_in_playlist_order():
    async def go():
        w = World()
        await w.tick()
        assert [j["uri"] for j in w.lane.jobs] == [u(0)]
        job = w.lane.jobs[0]
        assert job["title"] == "Song 0" and job["artist"] == "Artist" and job["genres"] == ["disco"]
        assert job["duration_ms"] == 200_000
        await w.tick()
        assert len(w.lane.jobs) == 1 and w.backlog.state == "learning"
        w.lane.finish("ok")
        w.kinds[u(0)] = "skip"                       # its shape is on disk now
        await w.tick()
        assert w.after == [u(0)] and w.backlog.learned[-1]["uri"] == u(0)
        # the next fresh song: 1 is captured and 2 needs Absorb's own re-capture
        assert [j["uri"] for j in w.lane.jobs] == [u(0), u(3)]
    _run(go())


def test_the_playlist_is_read_at_most_every_fifteen_minutes():
    async def go():
        w = World()
        for _ in range(5):
            await w.tick()
            if w.lane.job:
                w.lane.finish("ok")
                w.kinds[w.lane.jobs[-1]["uri"]] = "skip"
        assert w.playlist_reads == 1
        await w.tick(AL.PLAYLIST_TTL_S)
        assert w.playlist_reads == 2
    _run(go())


@pytest.mark.parametrize("what,why", [
    ("night", "A Jukebox night"), ("window", "An Absorb window"),
    ("asleep", "asleep"), ("unknown", "can't be read"), ("signed_out", "isn't signed in"),
])
def test_it_rests_and_stops_its_song_when_something_else_wants_the_hidden_player(what, why):
    async def go():
        w = World()
        await w.tick()
        job_id = w.lane.jobs[0]["job_id"]
        if what == "night":
            w.night = True
        elif what == "window":
            w.window = True
        elif what == "asleep":
            w.asleep = True
        elif what == "unknown":
            w.asleep = None
        else:
            w.signed = False
        await w.tick(AL.SLEEP_CHECK_S)
        assert w.backlog.state == "resting" and why in w.backlog.reason
        assert w.lane.cancelled == [job_id] and w.backlog.job is None
        await w.tick(AL.SLEEP_CHECK_S)
        assert len(w.lane.jobs) == 1                   # nothing new while it rests
    _run(go())


def test_sleep_is_read_at_most_once_a_minute():
    async def go():
        w = World()
        for _ in range(6):
            await w.tick()
        assert w.sleep_reads == 1
        await w.tick(AL.SLEEP_CHECK_S)
        assert w.sleep_reads == 2
    _run(go())


def test_a_lane_that_isnt_running_is_a_rest_not_a_failure():
    async def go():
        w = World()
        w.lane.up = False
        await w.tick()
        assert w.backlog.state == "resting" and "isn't running" in w.backlog.reason
        assert w.lane.jobs == [] and w.backlog.attempts == {}
    _run(go())


def test_a_song_that_fails_its_tries_is_passed_over_until_switched_off_and_on():
    async def go():
        w = World(max_attempts=2)
        for _ in range(2):
            await w.tick()
            assert w.lane.jobs[-1]["uri"] == u(0)
            w.lane.finish("failed", "gap")
            await w.tick()
        assert w.backlog.attempts[u(0)] == 2 and u(0) in w.backlog.status()["passed_over"]
        assert w.lane.jobs[-1]["uri"] == u(3)        # moved on
        w.cfg = w.cfg.model_copy(update={"use_capture_lane": False})
        await w.tick()
        assert w.lane.cancelled                       # switched off: its song stopped
        w.cfg = w.cfg.model_copy(update={"use_capture_lane": True})
        await w.tick()
        assert w.backlog.attempts == {} and w.lane.jobs[-1]["uri"] == u(0)
    _run(go())


def test_a_hidden_player_that_cant_be_used_backs_off_without_using_a_try():
    async def go():
        w = World()
        await w.tick()
        w.lane.finish("failed", "device_missing")
        await w.tick()
        assert w.backlog.attempts == {} and "isn't online" in w.backlog.reason
        assert len(w.lane.jobs) == 1
        await w.tick(AL.DOWN_BACKOFF_S + 1)
        assert len(w.lane.jobs) == 2 and w.lane.jobs[-1]["uri"] == u(0)
    _run(go())


def test_a_song_the_house_is_capturing_is_left_to_the_house():
    async def go():
        w = World()
        w.recording = u(0)
        await w.tick()
        assert w.lane.jobs[0]["uri"] == u(3)           # never picks the house's song
        w.recording = u(3)
        job_id = w.lane.jobs[0]["job_id"]
        await w.tick()
        assert w.lane.cancelled == [job_id]            # the house started it: its capture learns it
    _run(go())


def test_a_song_spotify_cant_describe_uses_a_try_and_is_never_sent():
    async def go():
        w = World()
        w.track_fails.add(u(0))
        await w.tick()
        assert w.lane.jobs == [] and w.backlog.attempts == {u(0): 1}
        await w.tick()
        await w.tick()
        assert w.lane.jobs == []
        await w.tick()                                  # 3 tries used: the next song
        assert [j["uri"] for j in w.lane.jobs] == [u(3)]
    _run(go())


def test_when_every_fresh_song_is_learned_it_says_so():
    async def go():
        w = World()
        for x in list(w.kinds):
            if w.kinds[x] == "fresh":
                w.kinds[x] = "skip"
        await w.tick()
        assert w.backlog.state == "idle" and "has been tried" in w.backlog.reason
        assert w.lane.jobs == []
    _run(go())


def test_no_linked_playlist_is_a_rest():
    async def go():
        w = World()
        w.cfg = w.cfg.model_copy(update={"source_playlist_uri": ""})
        await w.tick()
        assert w.backlog.state == "resting" and "No playlist" in w.backlog.reason
        assert w.lane.status_calls == 0
    _run(go())


def test_the_route_reads_it_and_a_switch_change_kicks_it(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import absorb_router
    from services import absorb_store

    w = World()
    monkeypatch.setattr(AL, "backlog", w.backlog)
    kicks = []
    monkeypatch.setattr(w.backlog, "kick", lambda: kicks.append(1))
    app = FastAPI()
    app.include_router(absorb_router.router)
    with TestClient(app) as c:
        st = c.get("/api/absorb/lane").json()
        assert st["enabled"] is False and st["state"] == "off"
        assert c.put("/api/absorb/config?dry_run=true", json={"use_capture_lane": True}).status_code == 200
        assert kicks == [] and absorb_store.load_config().use_capture_lane is False
        assert c.put("/api/absorb/config", json={"use_capture_lane": True}).status_code == 200
        assert kicks == [1] and absorb_store.load_config().use_capture_lane is True
        assert c.get("/api/absorb/lane").json()["enabled"] is True
