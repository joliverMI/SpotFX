"""The Jukebox's post-party report (services/jukebox/night_report.py; the
plan's PR 3.3 "post-party report (the night's ledger next to the §3 bands)",
a skeleton). Held: it measures what a night records — what played, the line,
the credits ledger when there is one — and says by name what it can't
measure yet, never a zero; a guest night's measures sit beside the model's
nights (services/jukebox/simulator.py, the same rows); the ledger's own
integrity check rides along; and it reads only."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.jukebox import EconomyConfig, JukeboxNight, LineEntry, PlayedItem
from routers import jukebox_router
from services.jukebox import ledger as ledger_mod, night as night_mod, night_report as R
from services.jukebox import simulator, store
from tests.jukebox_world import World

T0 = 1_800_000_000_000
MIN = 60_000


def _run(coro):
    return asyncio.run(coro)


def _guest_night() -> tuple[JukeboxNight, ledger_mod.Ledger]:
    """A two-hour night: four set songs, three jukebox songs from two of
    three guests, one skipped, and their credits."""
    n = JukeboxNight(id="n-guests", state="ended", started_ms=T0, ended_ms=T0 + 120 * MIN,
                     playlist_name="Saturday")
    n.line = [
        LineEntry(id="a", uri="u:a", added_by="p1", added_ms=T0 + 5 * MIN, state="played",
                  played_ms=T0 + 15 * MIN),
        LineEntry(id="b", uri="u:b", added_by="p2", added_ms=T0 + 10 * MIN, state="played",
                  played_ms=T0 + 40 * MIN),
        LineEntry(id="c", uri="u:c", added_by="p1", added_ms=T0 + 20 * MIN, state="played",
                  played_ms=T0 + 50 * MIN),
        LineEntry(id="d", uri="u:d", added_by="p3", added_ms=T0 + 100 * MIN, state="queued"),
        LineEntry(id="e", uri="u:e", added_by="host", added_ms=T0 + 30 * MIN, state="removed"),
    ]
    n.played = ([PlayedItem(kind="set", uri=f"s{i}", at_ms=T0 + i * MIN) for i in range(4)]
                + [PlayedItem(kind="jukebox", uri=u, at_ms=T0) for u in ("u:a", "u:b", "u:c")]
                + [PlayedItem(kind="skipped", uri="s9", at_ms=T0)])
    led = ledger_mod.Ledger(n.id, EconomyConfig(), persist=False, now_ms=lambda: T0)
    for p in ("p1", "p2", "p3"):
        led.grant(p, "start", 8)
    led.spend("p1", "add", 4, "a")
    led.spend("p2", "add", 6, "b")
    led.spend("p1", "add", 4, "c")
    led.vote("p2", "a", own_song=False)
    led.vote("p3", "a", own_song=False)
    led.tip("p3", "p1", "a", 1, adder_is_host=False)
    led.spend("p3", "skip", 5, "s9")
    return n, led


# ═══ 1. a night with no guests: measured what it holds, the rest by name ═══

def test_no_night_yet():
    r = R.build(None, None, EconomyConfig(), now_ms=T0)
    assert r["status"] == "none"


def test_a_song_still_playing_when_the_night_ends_counts_separately_from_waiting():
    """night.py's `_end` never resolves a `playing` entry back to `played`
    (that only happens when the next song starts), so a night stopped
    mid-song stores one line entry stuck in `playing` forever — it must
    still be counted, or `added` no longer equals the sum of the states."""
    n = JukeboxNight(id="n-mid-song", state="ended", started_ms=T0, ended_ms=T0 + 60 * MIN)
    n.line = [
        LineEntry(id="a", uri="u:a", added_by="p1", added_ms=T0, state="played",
                  played_ms=T0 + 10 * MIN),
        LineEntry(id="b", uri="u:b", added_by="p2", added_ms=T0 + 5 * MIN, state="playing"),
        LineEntry(id="c", uri="u:c", added_by="p1", added_ms=T0 + 8 * MIN, state="queued"),
        LineEntry(id="d", uri="u:d", added_by="host", added_ms=T0 + 9 * MIN, state="removed"),
    ]
    line = R.night_section(n, T0 + 60 * MIN)["line"]
    assert line["playing_at_end"] == 1
    assert line["added"] == (line["played"] + line["removed"] + line["skipped"]
                             + line["playing_at_end"] + line["waiting_at_end"])


def test_wait_to_play_median_names_not_played_yet_when_the_ledger_has_no_finished_song():
    """Credits already spent but no guest song finished playing yet (a
    running night) is a different fact from no guest ever using credits —
    it must not read as NO_GUESTS."""
    n = JukeboxNight(id="n-running", state="running", started_ms=T0)
    n.line = [LineEntry(id="x", uri="u:x", added_by="p1", added_ms=T0 + 5 * MIN, state="queued")]
    led = ledger_mod.Ledger(n.id, EconomyConfig(), persist=False, now_ms=lambda: T0)
    led.grant("p1", "start", 8)
    led.spend("p1", "add", 4, "x")
    m = R.measures(n, list(led.entries), T0 + 10 * MIN)
    assert m["wait_to_play_median"]["value"] is None
    assert m["wait_to_play_median"]["why"] == R.NOT_PLAYED_YET

    m_no_ledger = R.measures(n, None, T0 + 10 * MIN)
    assert m_no_ledger["wait_to_play_median"]["why"] == R.NO_GUESTS


def test_a_night_without_guests_reports_what_played_and_names_the_rest():
    w = World()

    async def go():
        await w.start()
        await w.add(0)
        await w.run(6 * 120)
        await w.runner.stop()
    _run(go())
    n = w.runner.night
    r = R.build(n, None, EconomyConfig(), now_ms=int(w.clock.t * 1000))
    ns = r["night"]
    assert ns["played"]["set"] == sum(1 for p in n.played if p.kind == "set") > 0
    assert ns["played"]["jukebox"] == 1 and ns["line"]["by_host"] == 1
    assert r["credits"] is None and r["comparison"] is None and r["guests"] is None
    assert all(row["this_night"] is None and row["why"] == R.NO_GUESTS for row in r["rows"])
    assert "no guest credits" in r["summary"]


def test_a_named_party_size_brings_the_models_nights_alongside():
    n, _ = _guest_night()
    r = R.build(n, None, EconomyConfig(), now_ms=T0, guests=8, nights=3)
    rows = {x["key"]: x for x in r["comparison"]["rows"]}
    assert r["guests"] == 8 and r["guests_from"] == "you"
    assert rows["juke_played"]["yours"] > 0 and rows["juke_played"]["this_night"] is None


# ═══ 2. a guest night: the ledger measured, beside the model ═══════════════

def test_a_guest_night_is_measured_from_its_ledger():
    n, led = _guest_night()
    r = R.build(n, list(led.entries), EconomyConfig(), now_ms=T0, nights=3, verify=led.verify())
    m = {k: v["value"] for k, v in r["measures"].items()}
    assert r["guests"] == 3 and r["guests_from"] == "the ledger"
    assert m["juke_played"] == 3.0
    assert m["wait_to_play_median"] == 30.0                     # 10, 30 and 30 min
    assert m["got_played"] == pytest.approx(2 / 3)               # p3 asked and is still waiting
    assert m["skips_hr"] == 0.5 and m["tips_hr"] == 0.5          # one each in two hours
    assert m["add_price_median"] == 4.0                          # 4, 6 and 4
    cs = r["credits"]
    assert cs["phones"] == 3 and cs["minted"] == 24 + 2 + 1      # starts, two votes, the tip bonus
    assert cs["held_at_end"] == 8                                # p1 2, p2 3, p3 3
    assert cs["unspent_share"] == round(8 / 27, 3)
    assert r["integrity"] == []
    assert {x["key"] for x in r["comparison"]["rows"]} == {k for k, *_ in simulator.ROWS}
    assert r["measures"]["jails"]["why"] == R.NOT_RECORDED


def test_a_tampered_ledger_is_named_in_the_report(tmp_path):
    n, led = _guest_night()
    path = ledger_mod.LEDGER_DIR / f"{n.id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [e.as_line() for e in led.entries]
    lines.append(lines[-1].replace('"seq":', '"seq":9').replace('"delta":-5', '"delta":-500'))
    path.write_text("\n".join(lines) + "\n")
    entries, verify = R.load_entries(n.id, EconomyConfig())
    assert entries is not None and verify


# ═══ 3. the route reads only ═══════════════════════════════════════════════

def test_the_route_reports_the_latest_night_and_writes_nothing(monkeypatch):
    w = World()
    w.deps.load_config = store.load_config
    w.runner = night_mod.JukeboxRunner(w.deps)
    monkeypatch.setattr(night_mod, "runner", w.runner)
    app = FastAPI()
    app.include_router(jukebox_router.router)
    with TestClient(app) as c:
        assert c.get("/api/jukebox/report").json()["status"] == "none"
        store.save_config(store.load_config().model_copy(update={"playlist": w.cfg.playlist}))
        assert c.post("/api/jukebox/night/start", json={}).json()["status"] == "running"
        c.post("/api/jukebox/night/stop", json={})
        before = {p: p.read_bytes() for p in (store.NIGHT_FILE, store.CONFIG_FILE)}
        r = c.get("/api/jukebox/report").json()
        assert r["status"] == "ok" and r["credits"] is None
        r = c.get("/api/jukebox/report?guests=8&nights=2").json()
        assert r["comparison"]["guests"] == 8
        assert c.get("/api/jukebox/report?guests=99").status_code == 422
        assert {p: p.read_bytes() for p in before} == before
        assert not store.SHOW_FILE.exists()


def test_the_harness_snapshot_is_the_reports_own_answer():
    """spectra/web/harness/jukeboxReportSnapshot.json is generated output (the
    Live tab's render mock): the report of `_guest_night` above, its party
    size read from its ledger. It must still equal what the report says."""
    import json
    import pathlib
    path = pathlib.Path(__file__).resolve().parent.parent / "spectra/web/harness/jukeboxReportSnapshot.json"
    snap = json.loads(path.read_text(encoding="utf-8"))
    n, led = _guest_night()
    live = R.build(n, list(led.entries), EconomyConfig(), now_ms=T0, nights=20, verify=led.verify())
    assert snap == json.loads(json.dumps({"program_from": "your saved program and credits settings", **live}))
