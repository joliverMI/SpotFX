"""Absorb-then-queue (services/jukebox/learning.py, the Jukebox plan's phase
4, PR 4.2): a song the lights haven't learned waits — keeping its place —
while the hidden player learns it, and plays once it is. Driven over the
fake Jukebox world (tests/jukebox_world.py) with a fake capture lane, so
what plays is what the engine plays. Nothing here reaches the real lane,
Spotify or a speaker.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from models.jukebox import ShowConfig
from services.jukebox import learning as L
from services.jukebox.lane_client import LaneBusy, LaneUnavailable
from tests.jukebox_world import World, jb_uri


def _run(coro):
    return asyncio.run(coro)


async def _inline(fn, *args):
    return fn(*args)


class FakeLane:
    """The capture lane as SpotFX sees it: one job at a time; the test
    finishes it."""

    def __init__(self, w: World) -> None:
        self.w = w
        self.up = True
        self.job: Optional[dict] = None
        self.job_started_at_ms: Optional[int] = None
        self.outcomes: list[dict] = []
        self.learned_jobs: list[dict] = []
        self.cancelled: list[str] = []
        self.busy_next = False

    async def status(self) -> dict:
        if not self.up:
            raise LaneUnavailable("the capture lane isn't answering (ConnectError)")
        return {"state": "capturing" if self.job else "idle", "job": self.job,
                "job_started_at_ms": self.job_started_at_ms, "progress_ms": 0,
                "outcomes": list(self.outcomes),
                "sentences": {"device_missing": "The hidden player isn't online."}}

    async def learn(self, job: dict) -> dict:
        if not self.up:
            raise LaneUnavailable("down")
        if self.busy_next or self.job:
            self.busy_next = False
            raise LaneBusy("x")
        self.job = dict(job)
        self.job_started_at_ms = int(self.w.clock.t * 1000)
        self.learned_jobs.append(dict(job))
        return {"job_id": job["job_id"], "state": "preparing"}

    async def cancel(self, job_id: str) -> bool:
        self.cancelled.append(job_id)
        if self.job and self.job["job_id"] == job_id:
            self.finish("cancelled", "cancelled")
            return True
        return False

    def finish(self, status: str = "ok", reason: str = "", learned: Optional[set] = None) -> str:
        job = self.job
        assert job is not None, "no job running"
        now = int(self.w.clock.t * 1000)
        self.outcomes.append({"job_id": job["job_id"], "uri": job["uri"], "status": status,
                              "reason": reason, "detail": "", "started_at_ms": self.job_started_at_ms,
                              "ended_at_ms": now, "covered_ms": job["duration_ms"]})
        if status == "ok" and learned is not None:
            learned.add(job["uri"])
        self.job = None
        return job["uri"]


class Rig:
    def __init__(self, *, learn_first: bool = True, signed_in: bool = True, known=(),
                 genres_for=None, **world):
        self.w = World(**world)
        self.lane = FakeLane(self.w)
        self.learned: set[str] = set(known)
        self.signed = signed_in
        self.show = ShowConfig(learn_first=learn_first, play_mode="free")
        self.followups: list[str] = []

        async def after(uri: str) -> None:
            self.followups.append(uri)

        self.learner = L.Learner(L.LearnerDeps(
            lane=self.lane, runner=lambda: self.w.runner, known=lambda uri: uri in self.learned,
            signed_in=lambda: self.signed, show=lambda: self.show, after_learned=after,
            genres_for=genres_for or (lambda uri: []),
            clock=self.w.clock, now_ms=lambda: int(self.w.clock.t * 1000), to_thread=_inline))
        self.w.deps.ready_at_add = self.learner.ready_at_add
        self.w.deps.learning_view = self.learner.view
        self.w.deps.known = lambda uri: uri in self.learned

    async def start(self) -> None:
        await self.w.start()
        await self.w.run(2)
        await self.learner.tick()

    async def add(self, n: int) -> str:
        out = await self.w.add(n)
        assert out["status"] == "added", out
        await self.learner.tick()
        return out["entry"]["id"]

    async def run(self, seconds: int) -> None:
        for _ in range(seconds):
            await self.w.run(1)
            await self.learner.tick()

    def entry(self, entry_id: str):
        return self.w.runner._entry(entry_id)

    async def until(self, uri: str, limit: int = 1500) -> None:
        for _ in range(limit):
            if self.w.player.current == uri:
                return
            await self.run(1)
        raise AssertionError(f"{uri} never played; played {self.w.played()}")


# ── the rule ─────────────────────────────────────────────────────────────────

def test_an_unlearned_song_waits_while_it_is_learned_then_plays():
    async def go():
        r = Rig()
        await r.start()
        eid = await r.add(0)
        e = r.entry(eid)
        assert e.ready is False and e.learn.state == "learning"
        assert [j["uri"] for j in r.lane.learned_jobs] == [jb_uri(0)]
        await r.run(400)                       # slots pass it: only set songs play
        assert "J0" not in r.w.played() and r.w.played()[-1].startswith("S")
        assert len(r.lane.learned_jobs) == 1   # one job, not one per tick
        r.lane.finish("ok", learned=r.learned)
        await r.learner.tick()
        assert e.known and e.ready and e.learn.state == "learned"
        assert r.followups == [jb_uri(0)]      # the main-account follow-ups, once
        await r.until(jb_uri(0))
    _run(go())


def test_a_learned_song_never_waits_and_never_goes_to_the_lane():
    async def go():
        r = Rig(known={jb_uri(0)})
        await r.start()
        eid = await r.add(0)
        assert r.entry(eid).ready and r.lane.learned_jobs == []
        await r.until(jb_uri(0), limit=300)
    _run(go())


def test_a_waiting_song_keeps_its_place_and_a_learned_one_behind_it_plays_first():
    async def go():
        r = Rig(known={jb_uri(1)})
        await r.start()
        first = await r.add(0)
        await r.add(1)
        line = [x.uri for x in r.w.runner.night.line if x.state == "queued"]
        assert line == [jb_uri(0), jb_uri(1)]   # its place is kept
        await r.until(jb_uri(1), limit=400)    # the slot slides past it
        assert r.entry(first).state == "queued"
        r.lane.finish("ok", learned=r.learned)
        await r.until(jb_uri(0))
    _run(go())


def test_songs_are_learned_one_at_a_time_in_line_order():
    async def go():
        r = Rig()
        await r.start()
        a = await r.add(0)
        b = await r.add(1)
        assert r.entry(a).learn.state == "learning" and r.entry(b).learn.state == "waiting"
        await r.run(3)
        assert [j["uri"] for j in r.lane.learned_jobs] == [jb_uri(0)]
        r.lane.finish("ok", learned=r.learned)
        await r.learner.tick()
        assert [j["uri"] for j in r.lane.learned_jobs] == [jb_uri(0), jb_uri(1)]
        assert r.entry(b).learn.state == "learning"
    _run(go())


# ── the lane job's genres ────────────────────────────────────────────────────

def test_the_dispatched_job_carries_the_looked_up_genres():
    async def go():
        seen: list[str] = []

        def lookup(uri: str) -> list[str]:
            seen.append(uri)
            return ["edm", "house"]

        r = Rig(genres_for=lookup)
        await r.start()
        await r.add(0)
        assert seen == [jb_uri(0)]
        assert r.lane.learned_jobs[0]["genres"] == ["edm", "house"]
    _run(go())


def test_a_failed_genre_lookup_still_dispatches_the_job_with_no_genres():
    async def go():
        def lookup(uri: str) -> list[str]:
            raise RuntimeError("no network here")

        r = Rig(genres_for=lookup)
        await r.start()
        eid = await r.add(0)
        assert r.entry(eid).learn.state == "learning"
        assert r.lane.learned_jobs[0]["genres"] == []
    _run(go())


# ── without a hidden player, the plan's own fallback ────────────────────────

def test_with_no_lane_running_a_new_song_plays_un_analysed():
    async def go():
        r = Rig()
        r.lane.up = False
        await r.start()
        eid = await r.add(0)
        assert r.entry(eid).ready and not r.learner.available
        assert "isn't running" in r.learner.reason
        await r.until(jb_uri(0), limit=400)
    _run(go())


def test_with_account_b_signed_out_nothing_waits():
    async def go():
        r = Rig(signed_in=False)
        await r.start()
        eid = await r.add(0)
        assert r.entry(eid).ready and r.lane.learned_jobs == []
        assert "isn't signed in" in r.learner.reason
    _run(go())


def test_learn_first_off_plays_at_once():
    async def go():
        r = Rig(learn_first=False)
        await r.start()
        eid = await r.add(0)
        assert r.entry(eid).ready and r.lane.learned_jobs == []
        assert "off" in r.learner.reason
    _run(go())


def test_a_lane_that_reports_the_hidden_player_missing_is_left_alone_a_while():
    async def go():
        r = Rig()
        await r.start()
        eid = await r.add(0)
        r.lane.finish("failed", "device_missing")
        await r.learner.tick()
        e = r.entry(eid)
        assert e.learn.state == "waiting" and e.learn.attempts == 0     # not the song's fault
        await r.learner.tick()
        assert not r.learner.available and "isn't online" in r.learner.reason
        assert e.ready                                                 # it plays un-analysed meanwhile
        assert len(r.lane.learned_jobs) == 1
        r.w.clock.t += L.DOWN_BACKOFF_S + 1
        await r.learner.tick()
        assert r.learner.available
    _run(go())


def test_a_lane_that_comes_back_takes_the_waiting_songs_again():
    async def go():
        r = Rig()
        r.lane.up = False
        await r.start()
        eid = await r.add(0)
        assert r.entry(eid).ready
        r.lane.up = True
        await r.learner.tick()
        assert r.entry(eid).ready is False and r.entry(eid).learn.state == "learning"
    _run(go())


# ── failures, parking, the host's buttons ───────────────────────────────────

def test_three_failed_tries_park_the_song_for_the_host():
    async def go():
        r = Rig()
        await r.start()
        eid = await r.add(0)
        e = r.entry(eid)
        for n in range(L.MAX_ATTEMPTS):
            assert e.learn.state == "learning"
            r.lane.finish("failed", "gap")
            await r.learner.tick()
            assert e.learn.attempts == n + 1
        assert e.learn.state == "parked" and e.ready is False and e.learn.reason == "gap"
        assert len(r.lane.learned_jobs) == L.MAX_ATTEMPTS
        st = r.learner.status()
        assert [p["entry_id"] for p in st["parked"]] == [eid] and st["queue"] == []
        out = await r.learner.relearn(eid)
        assert out["status"] == "waiting"
        await r.learner.tick()
        assert e.learn.state == "learning" and e.learn.attempts == 0
    _run(go())


def test_a_cancelled_or_already_learned_job_does_not_use_a_try():
    async def go():
        r = Rig()
        await r.start()
        eid = await r.add(0)
        r.lane.finish("cancelled", "cancelled")
        await r.learner.tick()
        assert r.entry(eid).learn.attempts == 0
    _run(go())


def test_the_host_lets_a_waiting_song_through_and_its_job_is_cancelled():
    async def go():
        r = Rig()
        await r.start()
        eid = await r.add(0)
        job_id = r.entry(eid).learn.job_id
        out = await r.learner.play_unanalysed(eid)
        assert out["status"] == "unanalysed"
        e = r.entry(eid)
        assert e.ready and e.learn.state == "unanalysed" and e.learn.why == "host"
        await r.learner.tick()
        assert r.lane.cancelled == [job_id]
        await r.until(jb_uri(0), limit=400)
        assert (await r.learner.play_unanalysed("nope"))["status"] == "refused"
    _run(go())


def test_a_removed_song_being_learned_has_its_job_cancelled():
    async def go():
        r = Rig()
        await r.start()
        eid = await r.add(0)
        job_id = r.entry(eid).learn.job_id
        await r.w.runner.remove(eid)
        await r.learner.tick()
        assert r.lane.cancelled == [job_id]
    _run(go())


def test_when_nothing_else_would_play_the_first_waiting_song_plays_un_analysed():
    async def go():
        r = Rig(n_set=2, set_s=60, run_out="jukebox_only")
        await r.start()
        eid = await r.add(0)
        assert r.entry(eid).ready is False
        await r.until(jb_uri(0), limit=400)        # the set ran out: it plays
        e = r.entry(eid)
        assert e.learn.state == "unanalysed" and e.learn.why == "dry"
    _run(go())


def test_a_lane_that_forgot_the_job_puts_the_song_back_in_line_to_learn():
    async def go():
        r = Rig()
        await r.start()
        eid = await r.add(0)
        r.lane.job = None                    # the lane restarted
        await r.learner.tick()               # forgot it -> waiting; dispatched again
        assert len(r.lane.learned_jobs) == 2
        assert r.entry(eid).learn.state == "learning" and r.entry(eid).learn.attempts == 0
    _run(go())


def test_a_lane_that_wont_take_the_song_leaves_it_waiting():
    async def go():
        r = Rig()
        r.lane.busy_next = True
        await r.start()
        eid = await r.add(0)
        assert r.entry(eid).learn.state == "waiting"
        await r.learner.tick()
        assert r.entry(eid).learn.state == "learning"
    _run(go())


# ── ETAs ────────────────────────────────────────────────────────────────────

def test_etas_follow_the_study_formula_with_priors_and_then_measured_numbers():
    async def go():
        r = Rig(jb_s=200)
        await r.start()
        a = await r.add(0)
        b = await r.add(1)
        st = r.learner.status()
        rows = {q["entry_id"]: q for q in st["queue"]}
        assert rows[a]["state"] == "learning" and rows[b]["state"] == "waiting"
        assert rows[a]["eta_s"] == round(200 + L.DEFAULT_OVERHEAD_S)
        assert rows[b]["eta_s"] == round(200 + L.DEFAULT_OVERHEAD_S
                                         + (200 + L.DEFAULT_OVERHEAD_S) / L.DEFAULT_SUCCESS)
        view = r.learner.view()
        assert view[b]["state"] == "waiting" and view[b]["eta_s"] == rows[b]["eta_s"]
    _run(go())


def test_lane_numbers_come_from_its_own_outcomes():
    outs = [{"status": "ok", "reason": "", "started_at_ms": 0, "ended_at_ms": 260_000,
             "covered_ms": 200_000},
            {"status": "ok", "reason": "", "started_at_ms": 0, "ended_at_ms": 280_000,
             "covered_ms": 200_000},
            {"status": "failed", "reason": "gap"},
            {"status": "failed", "reason": "device_missing"},     # not a try
            {"status": "cancelled", "reason": "cancelled"}]       # not a try
    overhead, success = L.lane_numbers(outs)
    assert overhead == 70.0 and success == 2 / 3
    assert L.lane_numbers([]) == (L.DEFAULT_OVERHEAD_S, L.DEFAULT_SUCCESS)


def test_the_guest_page_sees_its_own_waiting_song():
    async def go():
        r = Rig()
        await r.start()
        eid = await r.add(0)
        gs = r.w.runner.guest_state()
        assert gs["learning"][eid]["state"] == "learning"
    _run(go())


# ── last call, and the refund ───────────────────────────────────────────────

def test_a_new_song_is_judged_against_last_call_by_its_place_not_refused_for_waiting():
    async def go():
        r = Rig()
        await r.start()
        from models.jukebox import LineEntry
        e = LineEntry(id=uuid.uuid4().hex[:10], uri=jb_uri(3), title="J3", duration_ms=100_000,
                      added_by="phone-a")
        out = await r.w.runner.add_entry(e, latest_start_ms=3_600_000)
        assert out["status"] == "added" and out["starts_in_ms"] is not None
        assert r.entry(e.id).ready is False
    _run(go())


def test_a_paid_song_that_couldnt_be_learned_is_refunded_once():
    from tests.test_jukebox_credits_play import _bal, _phones, _setup, _sound
    from tests.test_jukebox_credits_play import _show as credits_show

    async def go():
        r = Rig(set_s=600)
        await r.start()
        r.show = credits_show()
        g = _setup(r.w, r.show)
        (ana,) = await _phones(g, 1)
        found = (await g.search(ana, "Song"))[1]
        price = {x["uri"]: x["price"] for x in found["results"]}[jb_uri(0)]
        from tests.test_jukebox_credits_play import _gift
        _gift(g, r.w, ana, 10)
        before = _bal(g, r.w, ana)
        code, out = await g.add(ana, jb_uri(0), price=price)
        assert code == 200, out
        await r.learner.tick()
        eid = out["added"]["entry_id"] if "entry_id" in out["added"] else r.w.runner.night.line[-1].id
        assert _bal(g, r.w, ana) == before - price
        for _ in range(L.MAX_ATTEMPTS):
            r.lane.finish("failed", "stalled")
            await r.learner.tick()
        e = r.entry(eid)
        assert e.learn.state == "parked" and e.learn.refund_due
        await g.view(ana)
        assert _bal(g, r.w, ana) == before                      # its price back
        await r.learner.play_unanalysed(eid)                    # the host lets it play anyway
        await g.view(ana)
        await r.w.runner.remove(eid)                            # ... or removes it: no second refund
        await g.view(ana)
        assert _bal(g, r.w, ana) == before
        _sound(g, r.w)
    _run(go())


# ── the lane client, against the real lane app ──────────────────────────────

def test_the_client_talks_to_the_real_lane_app_with_its_key(tmp_path, monkeypatch):
    import httpx

    from capture_lane.app import create_app
    from services.jukebox.lane_client import LaneClient
    from tests.test_capture_lane import make

    lane, sp, *_ = make(tmp_path, monkeypatch, complete={jb_uri(0)})
    app = create_app(lane=lane, key="k" * 24)

    async def go():
        ok = LaneClient("http://lane", "k" * 24, transport=httpx.ASGITransport(app=app))
        st = await ok.status()
        assert st["state"] == "idle" and st["outcomes"] == []
        out = await ok.learn({"job_id": "j1", "uri": jb_uri(0), "title": "J0", "artist": "",
                              "duration_ms": 100_000})
        assert out["job_id"] == "j1"
        await lane.wait()
        st = await ok.status()
        assert st["outcomes"][-1]["job_id"] == "j1" and st["outcomes"][-1]["reason"] == "already_learned"
        assert await ok.cancel("j1") is False
        wrong = LaneClient("http://lane", "nope", transport=httpx.ASGITransport(app=app))
        for call in (wrong.status(), wrong.cancel("j1")):
            try:
                await call
                raise AssertionError("a wrong key was answered")
            except LaneUnavailable as exc:
                assert "401" in str(exc)
    _run(go())


def test_every_way_the_lane_cant_be_reached_is_one_exception():
    import httpx

    from services.jukebox.lane_client import LaneClient

    def reply(status, body):
        return httpx.MockTransport(lambda req: httpx.Response(status, content=body))

    def refuse(req):
        raise httpx.ConnectError("refused")

    async def go():
        for transport in (httpx.MockTransport(refuse), reply(500, b"{}"), reply(200, b"not json"),
                          reply(200, b'{"state": "idle"}'), reply(200, b"[1]")):
            try:
                await LaneClient("http://lane", "k", transport=transport).status()
                raise AssertionError("expected LaneUnavailable")
            except LaneUnavailable:
                pass
        busy = LaneClient("http://lane", "k", transport=reply(409, b'{"detail": "busy", "uri": "u"}'))
        try:
            await busy.learn({"uri": "u"})
            raise AssertionError("expected LaneBusy")
        except LaneBusy:
            pass
    _run(go())


# ── the routes ──────────────────────────────────────────────────────────────

def test_the_learning_routes(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import jukebox_router

    async def go():
        r = Rig()
        await r.start()
        eid = await r.add(0)
        return r, eid
    r, eid = _run(go())
    monkeypatch.setattr(L, "learner", r.learner)
    app = FastAPI()
    app.include_router(jukebox_router.router)
    with TestClient(app) as c:
        st = c.get("/api/jukebox/learning").json()
        assert st["available"] is True and st["queue"][0]["entry_id"] == eid
        assert st["queue"][0]["state"] == "learning"
        assert c.post(f"/api/jukebox/line/{eid}/unanalysed").json()["status"] == "unanalysed"
        assert r.entry(eid).ready and r.entry(eid).learn.why == "host"
        assert c.post(f"/api/jukebox/line/{eid}/relearn").json()["status"] == "waiting"
        assert r.entry(eid).ready is False
        assert c.post("/api/jukebox/line/nope/unanalysed").json()["status"] == "refused"
