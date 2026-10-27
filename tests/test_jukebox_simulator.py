"""The master view's party simulator (services/jukebox/simulator.py's
`simulate()` and `POST /api/jukebox/simulate`) — phase 3 PR 3.4 of
data/jukebox-plan/report.md.

Held: recording a night draws nothing from the random stream (a watched
night IS the night the executable spec simulates); the playback is
internally consistent (credits never negative, the last frame is how the
night ended, every event is one the night counted); his settings and the
tuned ones are compared on the same nights, so a change shows as a
difference and no change shows as none; his program is the slot pattern
(Manual says it is played as the plan's mix); and the route reads his SAVED
settings, refuses a bad request by name, and runs one at a time.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.jukebox import EconomyConfig, ProgramConfig, ShowConfig
from routers import jukebox_router
from services.jukebox import simulator as S
from services.jukebox import store


def test_recording_a_night_changes_nothing_about_it():
    p = S.params_for(15)
    plain = S.Party(15, p, 4242).run()
    rec = S.Party(15, p, 4242, record=True)
    assert S._clean(rec.run()) == S._clean(plain)
    assert rec.frames and rec.events and rec.songs_log


def test_the_playback_adds_up():
    party = S.Party(20, S.night_params(20, EconomyConfig(), S.program(20)), 7, record=True)
    summary = party.run()
    night = S.recording(party, summary)
    ts = [f["t"] for f in night["frames"]]
    assert ts == sorted(ts) and ts[-1] <= night["minutes"] + 20
    assert all(c >= 0 for f in night["frames"] for c in f["cr"])
    assert night["frames"][-1]["cr"] == [g["end_credits"] for g in night["guests"]]
    kinds = {}
    for e in night["events"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    assert kinds.get("add", 0) == party.c["adds"]
    assert kinds.get("skip", 0) == party.c["skip"]
    assert kinds.get("jail", 0) == party.c["jail"]
    assert kinds.get("tip", 0) == party.c["tips"]
    assert len(night["songs"]) == summary["songs"]
    played = sum(1 for s in night["songs"] if s["by"] is not None)
    assert played == summary["juke_played"]
    assert sum(g["played"] for g in night["guests"]) == played


def test_the_watched_night_is_the_first_of_the_averaged_ones():
    r = S.simulate(8, EconomyConfig(), nights=1, seed=3)
    one = S.run_many(8, S.night_params(8, EconomyConfig(), S.program(8)), seeds=1, base_seed=3)
    assert r["night"]["summary"]["juke_played"] == one["juke_played"]
    assert {x["key"]: x["yours"] for x in r["rows"]}["juke_played"] == one["juke_played"]


def test_the_tuned_settings_are_compared_on_the_same_nights():
    same = S.simulate(15, EconomyConfig(), nights=4, seed=2)
    assert same["same_as_tuned"] and all(r["yours"] == r["tuned"] for r in same["rows"])
    cheap = S.simulate(15, EconomyConfig(add_double_min=0), nights=4, seed=2)
    assert not cheap["same_as_tuned"]
    rows = {r["key"]: r for r in cheap["rows"]}
    assert rows["price_mid"]["tuned"] == {r["key"]: r for r in same["rows"]}["price_mid"]["yours"]
    assert rows["price_mid"]["yours"] < rows["price_mid"]["tuned"]      # a flat price stays at the base


def test_the_checks_are_the_plans_promises():
    r = S.simulate(4, EconomyConfig(), nights=6, seed=1)
    by = {c["key"]: c for c in r["checks"]}
    assert set(by) == {"got_played", "wait_to_play_median", "back_wait_p90", "songs_per_lurk", "skips_hr"}
    assert by["got_played"]["ok"] is True
    # at 4 guests nobody is quiet enough to count as one: the check says so, not "failed"
    if by["songs_per_lurk"]["value"] is None:
        assert by["songs_per_lurk"]["ok"] is None


def test_too_few_slots_for_the_room_shows_in_the_checks():
    """§3.3: every other at 20 guests leaves too few slots; the plan's own
    preset (jukebox first) does not."""
    tight = S.simulate(20, EconomyConfig(), mode="auto", every=1, run=1, nights=10, seed=1)
    roomy = S.simulate(20, EconomyConfig(), mode="jukebox_first", nights=10, seed=1)
    w = lambda r: {c["key"]: c["value"] for c in r["checks"]}["wait_to_play_median"]
    assert w(tight) > w(roomy)
    assert tight["plan_preset"] == "large" and not tight["mix_is_plans"] and roomy["mix_is_plans"]


@pytest.mark.parametrize("mode, every, run, mix, words", [
    ("auto", 1, 1, dict(set_per_slot=1, juke_per_slot=1), "a jukebox song after every set song"),
    ("auto", 3, 2, dict(set_per_slot=3, juke_per_slot=2), "2 jukebox songs after every 3 set songs"),
    ("jukebox_first", 1, 1, dict(set_per_slot=0, juke_per_slot=1), "jukebox first; the set fills any gap"),
])
def test_his_program_is_the_slot_pattern(mode, every, run, mix, words):
    assert S.program_mix(mode, every, run, 15) == (mix, words)


def test_a_manual_program_says_it_plays_the_plans_mix():
    mix, words = S.program_mix("manual", 1, 1, 15)
    assert mix == S.program(15) and "Manual" in words and "2 jukebox songs after every set song" in words


@pytest.mark.parametrize("kw", [dict(guests=1), dict(guests=41), dict(nights=0), dict(nights=41)])
def test_out_of_range_is_refused(kw):
    args = dict(guests=10, nights=1) | kw
    with pytest.raises(ValueError):
        S.simulate(args.pop("guests"), EconomyConfig(), **args)


# ── the route ───────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(jukebox_router.router)
    with TestClient(app) as c:
        yield c


def test_the_route_reads_the_saved_settings(client):
    store.save_show(ShowConfig(economy=EconomyConfig(add_double_min=0)))
    store.save_config(ProgramConfig(mode="jukebox_first"))
    r = client.post("/api/jukebox/simulate", json={"guests": 12, "nights": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["program"] == "jukebox first; the set fills any gap" and body["program_source"] == "saved"
    assert body["same_as_tuned"] is False
    pre = client.post("/api/jukebox/simulate", json={"guests": 12, "nights": 2, "program": "preset"}).json()
    assert pre["program"] == "2 jukebox songs after every set song" and pre["mix_is_plans"]


def test_the_route_refuses_a_bad_request_by_name(client):
    r = client.post("/api/jukebox/simulate", json={"guests": 99})
    assert r.status_code == 422 and "guests" in r.text
    r = client.post("/api/jukebox/simulate", json={"program": "mine"})
    assert r.status_code == 422


def test_one_simulation_at_a_time(client):
    async def hold():
        await jukebox_router._simulating.acquire()
    asyncio.run(hold())
    try:
        r = client.post("/api/jukebox/simulate", json={"guests": 4, "nights": 1})
        assert r.status_code == 409 and "already running" in r.json()["detail"]
    finally:
        jukebox_router._simulating.release()
    assert client.post("/api/jukebox/simulate", json={"guests": 4, "nights": 1}).status_code == 200


def test_the_harness_snapshot_is_the_servers_own_answer(client):
    """spectra/web/harness/jukeboxSimSnapshot.json is generated output (the
    Simulate tab's render mock): the route's answer for 20 guests under the
    shipped settings, seed 1. It must still equal what the server says."""
    import json
    import pathlib
    path = pathlib.Path(__file__).resolve().parent.parent / "spectra/web/harness/jukeboxSimSnapshot.json"
    snap = json.loads(path.read_text(encoding="utf-8"))
    live = client.post("/api/jukebox/simulate",
                       json={"guests": 20, "nights": 20, "seed": 1, "program": "saved"}).json()
    assert snap == live
