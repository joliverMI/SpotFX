"""Sonic's absorb domain (spectra/services/absorb_console.py) — Absorb Music,
reached through SpotFX's own routes. The fake `http` here answers from the
REAL SpotFX router (routers/absorb_router.py) in-process, with the runner
wired to the fake world (tests/absorb_world.py: Spotify, the capture service,
the shape disk and the clock, all in memory) — so Sonic is proven against the
same validator, the same store and the same start gate the /absorb page uses.
No live process, house, Spotify account or light is touched.

The bar for the gates (his "Sonic must not be able to bypass any gate the UI
has"): a start through Sonic is refused with the route's OWN reason by every
gate the route has — the music-playing check, River's hard block, the
sleeping-house rule, Home Assistant unreadable (the silence proof) — and the
house volume is never written when it is."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.absorb import AbsorbConfig, AbsorbRun, HeadRate, HeadTally, LedgerEntry
from routers import absorb_router
from services import absorb, absorb_schedule, absorb_store
from spectra.services import absorb_console as ac
from tests.absorb_world import SOURCE, SOURCE_ID, World, uri

REPO = Path(__file__).resolve().parents[1]


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_confirmations(monkeypatch):
    monkeypatch.setattr(ac, "_PENDING", {})
    clock = [1000.0]
    monkeypatch.setattr(ac, "_clock", lambda: clock[0])
    return clock


def _wire(monkeypatch, w: World) -> TestClient:
    monkeypatch.setattr(absorb, "runner", w.runner)
    app = FastAPI()
    app.include_router(absorb_router.router)
    client = TestClient(app)
    client.__enter__()
    calls: list[tuple] = []

    async def fake_http(method, path, *, params=None, json=None, timeout=None):
        calls.append((method, path, params, json))
        return client.request(method, path, params=params, json=json)

    monkeypatch.setattr(ac, "http", fake_http)
    client.world = w
    client.calls = calls
    return client


@pytest.fixture
def spotfx(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, warm_up=False)
    w.gw.playlists[SOURCE_ID] = [uri(1), uri(2), uri(3)]
    w.gw.names["CHILL0000000000000001"] = "Chill"
    w.gw.playlists["CHILL0000000000000001"] = [uri(7), uri(8)]
    w.gw.names["FOLLOWED000000000001"] = "Someone Else's Mix"
    w.gw.playlists["FOLLOWED000000000001"] = [uri(9)]
    w.gw.followed.add("FOLLOWED000000000001")
    c = _wire(monkeypatch, w)
    yield c
    c.__exit__(None, None, None)


def _ha_writes(house) -> list:
    return [e for e in house.events if e[0] == "ha.set_volume"]


# ═══ 1. the mirrors ══════════════════════════════════════════════════════════

def test_the_mirrors_match_spotfx():
    from models import absorb as m
    assert set(ac.SETTING_KEYS) <= set(AbsorbConfig.model_fields)
    assert ac.DAYS == m.DAYS
    assert ac.HOUSE_TZ == absorb_schedule.HOUSE_TZ
    for w in (m.AbsorbWindow(), m.AbsorbWindow(days=["mon", "fri"], start="22:00", end="01:15"),
              m.AbsorbWindow(days=["sun"], start="08:00", end="09:00")):
        assert ac.window_label(w.model_dump()) == absorb_schedule.window_label(w)


def test_the_reason_words_are_the_absorb_pages_own():
    ts = (REPO / "spectra/web/src/absorb/absorbSummary.ts").read_text()
    block = ts.split("const REASONS: Record<string, string> = {", 1)[1].split("};", 1)[0]
    page = dict(re.findall(r"(\w+): '([^']*)'", block))
    assert page == ac.REASON_WORDS


# ═══ 2. reads ════════════════════════════════════════════════════════════════

def test_status_before_anything_ran(spotfx):
    out = _run(ac._op_absorb_status())
    assert "status" not in out                   # a read never reads as a refusal
    assert out["state"] == "idle" and out["running"] is False
    assert "never run" in out["summary"] and "schedule is off" in out["summary"]


def test_status_names_the_live_window_and_the_playlist_split(spotfx):
    spotfx.post("/api/absorb/start")
    out = _run(ac._op_absorb_status(include_playlist=True))
    assert out["running"] is True and "Absorb is running on “Absorb me”" in out["summary"]
    assert out["playlist"]["counts"]["total"] == 3


def test_settings_read(spotfx):
    out = _run(ac._op_get_absorb_settings())
    assert "status" not in out
    assert out["settings"]["source_playlist_uri"] == SOURCE
    assert out["changeable_by_voice"] == list(ac.SETTING_KEYS)
    assert "force recapture off" in out["summary"]


# ═══ 3. start — asks first, then goes through the route's own gate ══════════

def test_start_asks_first_and_does_nothing_until_he_says_yes(spotfx):
    w = spotfx.world
    asked = _run(ac._op_start_absorb())
    assert asked["status"] == "needs_confirmation" and asked["confirm_id"]
    assert "“Absorb me”" in asked["question"] and "house volume to 0" in asked["question"]
    assert "3 songs: 0 already captured" in asked["question"]
    assert asked["reason"].startswith("Not done yet")
    assert w.gw.writes() == [] and w.runner.run is None           # nothing happened
    assert not [c for c in spotfx.calls if c[0] == "POST"]

    out = _run(ac._op_start_absorb(confirm_id=asked["confirm_id"]))
    assert out["status"] == "applied" and out["state"] == "running"
    assert w.runner.run.started_by == "sonic"
    assert w.last_play == [uri(1), uri(2), uri(3)]
    assert ("POST", "/api/absorb/start", None, {"started_by": "sonic"}) in spotfx.calls


def test_a_confirmation_is_single_use_bound_and_expires(spotfx, _fresh_confirmations):
    first = _run(ac._op_start_absorb())
    # another operation's id is not this one's
    other = _run(ac._op_set_absorb_force_recapture(True))
    assert _run(ac._op_start_absorb(confirm_id=other["confirm_id"]))["status"] == "rejected"
    assert _run(ac._op_start_absorb(confirm_id="made-up"))["status"] == "rejected"
    # expired
    _fresh_confirmations[0] += ac.CONFIRM_TTL_S + 1
    out = _run(ac._op_start_absorb(confirm_id=first["confirm_id"]))
    assert out["status"] == "rejected" and "expired" in out["reason"]
    assert spotfx.world.runner.run is None
    # used once only
    again = _run(ac._op_start_absorb())
    assert _run(ac._op_start_absorb(confirm_id=again["confirm_id"]))["status"] == "applied"
    _run(ac._op_stop_absorb())
    assert _run(ac._op_start_absorb(confirm_id=again["confirm_id"]))["status"] == "rejected"


def test_a_yes_does_not_cover_settings_that_changed_after_he_was_asked(spotfx):
    asked = _run(ac._op_start_absorb())
    absorb.apply_config_patch({"force_recapture": True})        # e.g. on the page meanwhile
    out = _run(ac._op_start_absorb(confirm_id=asked["confirm_id"]))
    assert out["status"] == "rejected" and "changed since he was asked" in out["reason"]
    assert spotfx.world.runner.run is None
    asked = _run(ac._op_start_absorb())
    assert "Force recapture is ON" in asked["question"]


def test_already_running_and_no_playlist_are_said_without_asking(spotfx):
    spotfx.post("/api/absorb/start")
    out = _run(ac._op_start_absorb())
    assert out["status"] == "rejected" and out["code"] == "already_running"
    assert ac._PENDING == {}
    spotfx.post("/api/absorb/stop")
    absorb.apply_config_patch({"source_playlist_uri": ""})
    out = _run(ac._op_start_absorb())
    assert out["code"] == "no_playlist" and ac._PENDING == {}


def _start_yes() -> dict:
    asked = _run(ac._op_start_absorb())
    assert asked["status"] == "needs_confirmation"
    return _run(ac._op_start_absorb(confirm_id=asked["confirm_id"]))


def _assert_refused_by_the_route(out: dict, code: str) -> None:
    run = absorb.runner.run
    assert out["status"] == "rejected" and out["code"] == code
    assert run is not None and run.state == "refused" and run.end_reason == code
    assert out["reason"] == run.end_detail                   # the route's own words
    assert run.started_by == "sonic"


def test_music_playing_refuses_with_the_routes_reason(spotfx):
    spotfx.world.playing(uri(42))
    out = _start_yes()
    _assert_refused_by_the_route(out, "music_playing")
    assert spotfx.world.gw.writes() == []


def test_anchors_off_refuses_with_the_routes_reason(spotfx):
    spotfx.world.anchors = False
    _assert_refused_by_the_route(_start_yes(), "anchor_disabled")


@pytest.fixture
def house_world(tmp_path, monkeypatch):
    from tests.test_absorb_silence import FakeHouse, make_guard
    from services.absorb_silence import read_hard_block
    w = World(tmp_path, monkeypatch, warm_up=False)
    w.gw.playlists[SOURCE_ID] = [uri(1), uri(2)]
    house = FakeHouse()
    block = tmp_path / ".audio-hard-block"
    make_guard(w, house, tmp_path, hard_block=lambda: read_hard_block(str(block)))
    c = _wire(monkeypatch, w)
    c.house, c.block = house, block
    yield c
    c.__exit__(None, None, None)


def test_rivers_hard_block_refuses_through_sonic_and_the_house_is_untouched(house_world):
    house_world.block.write_text("Unconditional audio hard block.\n")
    _assert_refused_by_the_route(_start_yes(), "hard_block")
    assert _ha_writes(house_world.house) == [] and house_world.house.snap_volume == 34.0


def test_the_sleeping_house_rule_refuses_through_sonic(house_world):
    absorb.apply_config_patch({"run_while_sleeping": False})
    house_world.house.sleeping = True
    out = _start_yes()
    assert out["status"] == "rejected" and absorb.runner.run.state == "refused"
    assert out["reason"] == absorb.runner.run.end_detail
    assert _ha_writes(house_world.house) == []


def test_an_unreadable_home_assistant_refuses_through_sonic(house_world):
    house_world.house.ha_fail_reads = True
    out = _start_yes()
    assert out["status"] == "rejected" and out["reason"] == absorb.runner.run.end_detail
    assert _ha_writes(house_world.house) == []


def test_a_proven_silence_opens_and_stop_gives_the_house_back(house_world):
    out = _start_yes()
    assert out["status"] == "applied"
    assert house_world.house.audible_rooms() == []
    stopped = _run(ac._op_stop_absorb())
    assert stopped["status"] == "applied" and "given back" in stopped["summary"]
    assert house_world.house.snap_volume == 34.0
    again = _run(ac._op_stop_absorb())
    assert again["status"] == "rejected" and again["code"] == "not_running"


def test_there_is_no_argument_that_skips_a_gate():
    from spectra.services import settings_agent as sa
    assert set(ac.OPERATIONS["start_absorb"].input_schema["properties"]) == {"confirm_id"}
    out = _run(sa._dispatch("start_absorb", {"force": True}))
    assert out["status"] == "rejected" and "bad arguments" in out["reason"]


def test_a_start_that_outlasts_the_wait_never_claims_either_way(monkeypatch):
    import httpx

    class R:
        status_code = 200

        def __init__(self, body):
            self._b = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._b

    async def fake(method, path, *, params=None, json=None, timeout=None):
        if path == "/api/absorb/start":
            raise httpx.ReadTimeout("slow")
        if path == "/api/absorb/run":
            return R({"brief": {"state": "idle"}})
        if path == "/api/absorb/config":
            return R({"source_playlist_uri": SOURCE})
        return R({})

    monkeypatch.setattr(ac, "http", fake)
    asked = _run(ac._op_start_absorb())
    out = _run(ac._op_start_absorb(confirm_id=asked["confirm_id"]))
    assert out["status"] == "rejected" and out["code"] == "no_answer"
    assert "may still have opened" in out["reason"]
    assert ac.START_TIMEOUT_S < 60          # inside the CLI forwarder's own 60 s


# ═══ 4. skip ═════════════════════════════════════════════════════════════════

def test_skip_with_nothing_playing_then_with_a_song(spotfx):
    out = _run(ac._op_absorb_skip_song())
    assert out["status"] == "rejected" and out["code"] == "nothing_playing"
    spotfx.post("/api/absorb/start")
    w = spotfx.world
    w.playing(uri(1), progress_ms=1000)
    spotfx.portal.call(w.poll)
    assert w.runner.run.now_playing is not None
    out = _run(ac._op_absorb_skip_song())
    assert out["status"] == "applied" and out["skipped_uri"] == uri(1)
    assert "comes back after the next song" in out["summary"]
    assert w.runner.run.queue.index(uri(1)) > w.runner.run.queue.index(uri(2))


# ═══ 5. settings ═════════════════════════════════════════════════════════════

def test_a_plain_number_applies_at_once_and_reads_back(spotfx):
    out = _run(ac._op_set_absorb_setting("max_attempts", 4))
    assert out["status"] == "applied" and (out["old"], out["new"]) == (
        {"max_attempts": 3}, {"max_attempts": 4})
    assert absorb_store.load_config().max_attempts == 4
    assert _run(ac._op_get_absorb_settings())["settings"]["max_attempts"] == 4


@pytest.mark.parametrize("key,value", [("max_attempts", 0), ("play_window_size", 500),
                                       ("overrun_grace_min", -1)])
def test_out_of_range_is_refused_with_spotfxs_own_reason(spotfx, key, value):
    before = absorb_store.load_config().model_dump()
    out = _run(ac._op_set_absorb_setting(key, value))
    assert out["status"] == "rejected" and key in out["reason"]
    assert absorb_store.load_config().model_dump() == before
    assert ac._PENDING == {}


def test_unknown_key_is_refused_before_any_request(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("no request for an unknown key")
    monkeypatch.setattr(ac, "http", boom)
    for key in ("head_max_ms", "silence_recheck_s", "max_atempts"):
        out = _run(ac._op_set_absorb_setting(key, 5))
        assert out["status"] == "rejected" and "unknown setting" in out["reason"]


def test_lowering_recently_captureds_cap_asks_raising_does_not(spotfx):
    out = _run(ac._op_set_absorb_setting("recently_captured_max", 50))
    assert out["status"] == "needs_confirmation" and "from 200 to 50" in out["question"]
    assert absorb_store.load_config().recently_captured_max == 200
    yes = _run(ac._op_set_absorb_setting("recently_captured_max", 50,
                                         confirm_id=out["confirm_id"]))
    assert yes["status"] == "applied" and absorb_store.load_config().recently_captured_max == 50
    assert _run(ac._op_set_absorb_setting("recently_captured_max", 80))["status"] == "applied"


def test_running_while_asleep_off_at_once_on_asks(spotfx):
    off = _run(ac._op_set_absorb_setting("run_while_sleeping", False))
    assert off["status"] == "applied" and "on → off" in off["summary"]
    on = _run(ac._op_set_absorb_setting("run_while_sleeping", True))
    assert on["status"] == "needs_confirmation" and "Order 27" in on["question"]
    assert absorb_store.load_config().run_while_sleeping is False
    yes = _run(ac._op_set_absorb_setting("run_while_sleeping", True, confirm_id=on["confirm_id"]))
    assert yes["status"] == "applied" and absorb_store.load_config().run_while_sleeping is True


def test_force_recapture_on_asks_off_applies(spotfx):
    on = _run(ac._op_set_absorb_force_recapture(True))
    assert on["status"] == "needs_confirmation" and "head and all" in on["question"]
    assert absorb_store.load_config().force_recapture is False
    yes = _run(ac._op_set_absorb_force_recapture(True, confirm_id=on["confirm_id"]))
    assert yes["status"] == "applied" and absorb_store.load_config().force_recapture is True
    off = _run(ac._op_set_absorb_force_recapture(False))
    assert off["status"] == "applied" and absorb_store.load_config().force_recapture is False


# ═══ 6. the schedule ═════════════════════════════════════════════════════════

def test_every_night_from_nine_thirty_asks_then_applies(spotfx):
    out = _run(ac._op_set_absorb_window(windows=[{"start": "21:30", "end": "00:30"}],
                                        schedule_on=True))
    assert out["status"] == "needs_confirmation"
    assert "every day 21:30–00:30" in out["question"]
    assert absorb_store.load_config().windows == [] and not absorb_store.load_config().enabled
    yes = _run(ac._op_set_absorb_window(windows=[{"start": "21:30", "end": "00:30"}],
                                        schedule_on=True, confirm_id=out["confirm_id"]))
    assert yes["status"] == "applied"
    cfg = absorb_store.load_config()
    assert cfg.enabled and cfg.windows[0].days == list(ac.DAYS)
    st = _run(ac._op_absorb_status())
    assert st["schedule"]["on"] is True and "The schedule is on" in st["summary"]
    # the same schedule again asks nothing
    again = _run(ac._op_set_absorb_window(windows=[{"start": "21:30", "end": "00:30"}],
                                          schedule_on=True))
    assert again["status"] == "applied" and "already" in again["summary"]
    # a different window while on asks again; switching off never asks
    moved = _run(ac._op_set_absorb_window(windows=[{"days": ["fri"], "start": "22:00",
                                                    "end": "23:00"}]))
    assert moved["status"] == "needs_confirmation"
    off = _run(ac._op_set_absorb_window(schedule_on=False))
    assert off["status"] == "applied" and not absorb_store.load_config().enabled


@pytest.mark.parametrize("window", [{"start": "21:30", "end": "21:30"},
                                    {"start": "25:00", "end": "00:30"},
                                    {"days": [], "start": "21:30", "end": "23:00"},
                                    {"days": ["someday"], "start": "21:30", "end": "23:00"}])
def test_an_impossible_window_is_refused_before_he_is_asked(spotfx, window):
    out = _run(ac._op_set_absorb_window(windows=[window], schedule_on=True))
    assert out["status"] == "rejected" and out["reason"]
    assert ac._PENDING == {} and absorb_store.load_config().windows == []


def test_windows_while_the_schedule_is_off_apply_at_once(spotfx):
    out = _run(ac._op_set_absorb_window(windows=[{"days": ["mon"], "start": "21:00",
                                                  "end": "23:00"}]))
    assert out["status"] == "applied" and "off (windows kept" in out["summary"]
    assert _run(ac._op_set_absorb_window())["status"] == "rejected"


# ═══ 7. the playlist ═════════════════════════════════════════════════════════

def test_link_by_exact_name(spotfx):
    out = _run(ac._op_set_absorb_playlist("chill"))
    assert out["status"] == "applied"
    assert absorb_store.load_config().source_playlist_uri == "spotify:playlist:CHILL0000000000000001"
    assert "“Absorb me” → “Chill” (2 songs)" in out["summary"]


def test_a_close_name_is_refused_naming_the_candidate(spotfx):
    out = _run(ac._op_set_absorb_playlist("Chil"))
    assert out["status"] == "rejected" and out["close_matches"] == ["Chill"]
    assert absorb_store.load_config().source_playlist_uri == SOURCE
    nothing = _run(ac._op_set_absorb_playlist("Workout Bangers"))
    assert nothing["status"] == "rejected" and "Chill" in nothing.get("known_names", [])


def test_a_followed_playlist_is_refused(spotfx):
    out = _run(ac._op_set_absorb_playlist("Someone Else's Mix"))
    assert out["status"] == "rejected" and "does not own" in out["reason"]
    assert absorb_store.load_config().source_playlist_uri == SOURCE


def test_a_link_is_accepted(spotfx):
    out = _run(ac._op_set_absorb_playlist(
        "https://open.spotify.com/playlist/CHILL0000000000000001?si=abc"))
    assert out["status"] == "applied"
    stranger = _run(ac._op_set_absorb_playlist("spotify:playlist:NOTHIS00000000000001"))
    assert stranger["status"] == "rejected" and "not in his Spotify library" in stranger["reason"]


def test_changing_the_playlist_while_the_schedule_is_on_asks(spotfx):
    absorb.apply_config_patch({"enabled": True, "windows": [
        {"days": ["mon"], "start": "21:30", "end": "23:00"}]})
    out = _run(ac._op_set_absorb_playlist("Chill"))
    assert out["status"] == "needs_confirmation" and "out of “Chill”" in out["question"]
    assert absorb_store.load_config().source_playlist_uri == SOURCE
    yes = _run(ac._op_set_absorb_playlist("Chill", confirm_id=out["confirm_id"]))
    assert yes["status"] == "applied"


def test_spotify_unreadable_is_a_stated_rejection(spotfx):
    spotfx.world.gw.fail_list = True
    out = _run(ac._op_set_absorb_playlist("Chill"))
    assert out["status"] == "rejected" and "Spotify didn't answer" in out["reason"]


# ═══ 8. parked songs ═════════════════════════════════════════════════════════

def _park(u: str, title: str, reason: str, ms: int) -> None:
    ledger = absorb_store.load_ledger()
    ledger.entries[u] = LedgerEntry(uri=u, title=title, parked=True, parked_reason=reason,
                                    parked_ms=ms, lifetime_attempts=3, last_failure="head_missed")
    absorb_store.save_ledger(ledger)


def test_parked_in_plain_words_and_retry_by_title(spotfx):
    assert _run(ac._op_list_absorb_parked())["summary"] == "No song is parked."
    _park(uri(1), "Fleetwood Mac — Dreams", "head_unreachable", 2000)
    _park(uri(2), "Queen — Bohemian Rhapsody", "gap", 1000)
    out = _run(ac._op_list_absorb_parked())
    assert "status" not in out
    assert "Fleetwood Mac — Dreams (its head never arrived, 3 attempts)" in out["summary"]
    done = _run(ac._op_retry_absorb_song("Bohemian Rhapsody"))
    assert done["status"] == "applied" and done["uri"] == uri(2)
    assert [p["uri"] for p in _run(ac._op_list_absorb_parked())["parked"]] == [uri(1)]
    out = _run(ac._op_retry_absorb_song("Stairway to Heaven"))
    assert out["status"] == "rejected"


# ═══ 9. the head report ══════════════════════════════════════════════════════

def _save_run(rid: str, state: str, opened_ms: int, *, attempted=0, with_head=0,
              by_mode=None, label="", detail="", head_missed=0) -> None:
    run = AbsorbRun(id=rid, state=state, started_ms=opened_ms or 5_000, opened_ms=opened_ms,
                    end_detail=detail, window={"label": label} if label else {},
                    head_rate=HeadRate(attempted=attempted, with_head=with_head,
                                       by_mode={k: HeadTally(attempted=a, with_head=h)
                                                for k, (a, h) in (by_mode or {}).items()}))
    run.counts.head_missed = head_missed
    run.counts.captured = with_head
    absorb_store.save_run(run)


def test_last_nights_head_rate(spotfx):
    _save_run("r1", "ended", 1_000, attempted=30, with_head=23, label="Mon 21:30–00:30",
              by_mode={"recapture": (21, 15), "fresh": (9, 8)}, head_missed=7)
    _save_run("r2", "refused", 0, detail="A night run has the room.")
    out = _run(ac._op_absorb_head_report())
    assert "status" not in out
    assert [w["run_id"] for w in out["windows"]] == ["r1"]
    assert out["windows"][0]["rate_pct"] == 77
    assert out["windows"][0]["by_mode"]["recapture"] == {"attempted": 21, "with_head": 15,
                                                         "rate_pct": 71}
    assert out["not_opened"][0]["detail"] == "A night run has the room."
    s = out["summary"]
    assert s.startswith("Newer than that,") and "was refused: A night run has the room." in s
    assert "the Mon 21:30–00:30 window: 23 of 30 committed captures landed their head (77%)" in s
    assert "re-captures 15 of 21 (71%)" in s and "fresh captures 8 of 9 (89%)" in s


def test_no_committed_capture_is_no_rate_never_zero_percent(spotfx):
    _save_run("r1", "ended", 1_000, label="Tue 21:30–00:30")
    out = _run(ac._op_absorb_head_report())
    assert out["windows"][0]["rate_pct"] is None
    assert "no capture committed, so there is no head rate yet" in out["summary"]
    assert "0%" not in out["summary"]


def test_several_windows_add_up(spotfx):
    _save_run("r1", "ended", 1_000, attempted=10, with_head=5, label="Mon 21:30–00:30")
    _save_run("r2", "ended", 2_000, attempted=10, with_head=9, label="Tue 21:30–00:30")
    out = _run(ac._op_absorb_head_report(runs=2))
    assert [w["run_id"] for w in out["windows"]] == ["r2", "r1"]
    assert out["total"] == {"attempted": 20, "with_head": 14, "rate_pct": 70}
    assert "Together: 14 of 20 (70%)" in out["summary"]
    assert _run(ac._op_absorb_head_report(runs=0))["status"] == "rejected"


def test_a_head_report_with_nothing_opened_says_so(spotfx):
    out = _run(ac._op_absorb_head_report())
    assert out["windows"] == [] and "no window that opened yet" in out["summary"]


# ═══ 10. the boundary ════════════════════════════════════════════════════════

def test_an_unreachable_spotfx_is_a_stated_rejection(monkeypatch):
    async def down(*a, **k):
        raise ConnectionError("connection refused")
    monkeypatch.setattr(ac, "http", down)
    for coro in (ac._op_absorb_status(), ac._op_absorb_head_report(), ac._op_start_absorb(),
                 ac._op_stop_absorb(), ac._op_absorb_skip_song(), ac._op_list_absorb_parked(),
                 ac._op_retry_absorb_song("x"), ac._op_get_absorb_settings(),
                 ac._op_set_absorb_setting("max_attempts", 4),
                 ac._op_set_absorb_force_recapture(True),
                 ac._op_set_absorb_window(schedule_on=False),
                 ac._op_set_absorb_playlist("Chill")):
        out = _run(coro)
        assert out["status"] == "rejected" and "did not answer" in out["reason"]


def test_discoverable_through_list_operations():
    from spectra.services import settings_agent as sa
    assert set(ac.OPERATIONS) <= set(sa.ALL_OPERATIONS)
    idx = _run(sa._dispatch("list_operations", {"domain": "absorb"}))
    assert {o["name"] for o in idx.get("operations", [])} == set(ac.OPERATIONS)
    assert {"absorb_status", "start_absorb", "stop_absorb", "set_absorb_playlist",
            "set_absorb_window", "set_absorb_force_recapture", "absorb_skip_song",
            "list_absorb_parked", "get_absorb_settings", "set_absorb_setting",
            "absorb_head_report"} <= set(ac.OPERATIONS)
    for name, op in ac.OPERATIONS.items():
        assert op.domain == "absorb"


def test_the_mcp_wrappers_take_exactly_the_declared_arguments():
    import inspect
    from spectra.services import settings_mcp_server as srv
    for name, op in ac.OPERATIONS.items():
        fn = getattr(srv, name)
        assert set(inspect.signature(fn).parameters) == set(op.input_schema["properties"]), name


# ═══ 11. the SpotFX side this phase added ════════════════════════════════════

def test_a_dry_run_config_put_validates_and_writes_nothing(spotfx):
    path = absorb_store.CONFIG_FILE
    before = path.read_bytes()
    r = spotfx.put("/api/absorb/config", params={"dry_run": "true"}, json={"max_attempts": 7})
    assert r.status_code == 200 and r.json()["max_attempts"] == 7
    assert path.read_bytes() == before
    bad = spotfx.put("/api/absorb/config", params={"dry_run": "true"}, json={"max_attempts": 70})
    assert bad.status_code == 422 and path.read_bytes() == before


def test_the_playlists_route_reads_his_library(spotfx):
    body = spotfx.get("/api/absorb/playlists").json()
    by_name = {p["name"]: p for p in body["playlists"]}
    assert by_name["Chill"]["editable"] is True
    assert by_name["Someone Else's Mix"]["editable"] is False
    assert spotfx.world.gw.writes() == []
    spotfx.world.gw.fail_list = True
    body = spotfx.get("/api/absorb/playlists").json()
    assert body["playlists"] is None and "Spotify didn't answer" in body["detail"]


def test_a_bool_is_not_a_number_and_a_number_is_not_a_bool(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("refused before any request")
    monkeypatch.setattr(ac, "http", boom)
    assert "whole number" in _run(ac._op_set_absorb_setting("max_attempts", True))["reason"]
    assert "true or false" in _run(ac._op_set_absorb_setting("run_while_sleeping", 1))["reason"]
