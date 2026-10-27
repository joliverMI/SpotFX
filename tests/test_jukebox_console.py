"""Sonic's jukebox domain (spectra/services/jukebox_console.py) — the
Jukebox reached through SpotFX's own routes (data/jukebox-plan/report.md
PR 3.4). The fake `http` answers from the REAL SpotFX router
(routers/jukebox_router.py) in-process, with the runner wired to the fake
world (tests/jukebox_world.py: Spotify's player and queue and the clock, all
in memory) — so Sonic is proven against the same validator, store and start
gate the /jukebox page uses. No live process, Spotify account or room is
touched; no night is ever started anywhere but the fake world.

The bar (firstmate's, for this domain): every change asks first, and
starting or stopping a night REFUSES unless it carries his explicit yes to
exactly that question."""
from __future__ import annotations

import asyncio
import typing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models import jukebox as m
from routers import jukebox_router
from services.jukebox import night as night_mod, show, store
from spectra.services import jukebox_console as jc
from tests.jukebox_world import PLAYLIST_URI, World


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_confirmations(monkeypatch):
    monkeypatch.setattr(jc, "_PENDING", {})
    clock = [1000.0]
    monkeypatch.setattr(jc, "_clock", lambda: clock[0])
    return clock


@pytest.fixture
def spotfx(monkeypatch):
    w = World()
    w.deps.load_config = store.load_config
    w.runner = night_mod.JukeboxRunner(w.deps)
    monkeypatch.setattr(night_mod, "runner", w.runner)
    app = FastAPI()
    app.include_router(jukebox_router.router)
    client = TestClient(app)
    client.__enter__()
    calls: list[tuple] = []

    async def fake_http(method, path, *, params=None, json=None, timeout=None):
        calls.append((method, path, params, json))
        return client.request(method, path, params=params, json=json)

    monkeypatch.setattr(jc, "http", fake_http)
    client.world = w
    client.calls = calls
    yield client
    client.__exit__(None, None, None)


def _writes(c) -> list[tuple]:
    return [x for x in c.calls if x[0] in ("PUT", "POST")
            and not (x[2] or {}).get("dry_run") and x[1] != "/api/jukebox/simulate"]


# ═══ 1. the mirrors ══════════════════════════════════════════════════════════

def test_the_mirrors_match_spotfx():
    assert set(jc.PROGRAM_KEYS) <= set(m.ProgramConfig.model_fields)
    assert set(jc.MODES) == set(typing.get_args(m.SlotMode)) - {"manual"}
    assert set(jc.RUN_OUTS) == set(typing.get_args(m.RunOut))
    assert set(jc.PRESETS) == set(show.PRESETS)
    assert set(jc.SHOW_KEYS) <= set(m.ShowConfig.model_fields)
    assert set(jc.SIM_PROGRAMS) == set(typing.get_args(
        jukebox_router.SimulateBody.model_fields["program"].annotation))


def test_every_operation_is_in_the_jukebox_domain_and_every_write_asks():
    for op in jc.OPERATIONS.values():
        assert op.domain == "jukebox"
        if op.kind == "write":
            assert "confirm_id" in op.input_schema["properties"]


# ═══ 2. reads ═══════════════════════════════════════════════════════════════

def test_status_says_no_night_and_then_the_running_night(spotfx):
    r = _run(jc._op_jukebox_status())
    assert r["status"] == "ok" and r["running"] is False and r["summary"] == "No night is running."
    spotfx.put("/api/jukebox/config", json={"playlist": PLAYLIST_URI})
    spotfx.post("/api/jukebox/night/start", json={})
    r = _run(jc._op_jukebox_status())
    assert r["running"] is True and "A night is running" in r["summary"]
    assert r["guests"] == {"phones": 0, "joined": 0, "pending": 0}
    assert "guest page" not in r["summary"]


def test_status_counts_the_phones_on_the_guest_page(spotfx):
    """Sonic reads how many phones are on the guest page; their acts (names,
    votes) stay theirs (the module's off-limits list)."""
    from services.jukebox import guest_link, guests

    async def go():
        spotfx.put("/api/jukebox/config", json={"playlist": PLAYLIST_URI})
        spotfx.post("/api/jukebox/night/start", json={})
        guest_link.GuestLink().ensure_token()
        token = store.load_guest_link()[1].token
        for join in (True, False):
            code, out = await guests.book.hello(None, token)
            assert code == 200
            if join:
                await guests.book.join(out["phone"])
    _run(go())
    r = _run(jc._op_jukebox_status())
    assert r["guests"] == {"phones": 2, "joined": 1, "pending": 0}
    assert "2 phones on the guest page (1 joined)." in r["summary"]
    assert not any(n.startswith("vote") or "guest" in n for n in jc.OPERATIONS)


def test_settings_read_the_program_and_every_economy_field(spotfx):
    r = _run(jc._op_get_jukebox_settings())
    assert r["program"]["mode"] == "auto" and r["program"]["words"] == "a jukebox slot after every set song"
    keys = {f["key"] for f in r["economy_fields"]}
    assert "add_base" in keys and r["economy"]["add_base"] == m.EconomyConfig().add_base
    assert {p["name"] for p in r["presets"]} == set(jc.PRESETS)


def test_price_check_follows_the_room(spotfx):
    small = _run(jc._op_jukebox_price_check(4))
    big = _run(jc._op_jukebox_price_check(30))
    assert small["guests"] == 4 and big["skip"][0]["price"] > small["skip"][0]["price"]


def test_the_simulator_is_a_read_that_writes_nothing(spotfx):
    r = _run(jc._op_simulate_jukebox_party(guests=20, nights=3))
    assert r["status"] == "ok" and r["guests"] == 20 and r["nights"] == 3
    assert r["same_as_tuned"] is True
    assert not store.SHOW_FILE.exists() and not store.CONFIG_FILE.exists()
    assert not store.NIGHT_FILE.exists()
    # every other at 20 guests misses the plan's wait promise, and says which preset fits
    assert "large" in r["summary"]
    pre = _run(jc._op_simulate_jukebox_party(guests=20, nights=3, program="preset"))
    assert pre["mix_is_plans"] is True
    assert _run(jc._op_simulate_jukebox_party(program="mine"))["status"] == "rejected"


# ═══ 3. a setting change asks first ═════════════════════════════════════════

def test_a_setting_asks_then_applies_on_his_yes(spotfx):
    ask = _run(jc._op_set_jukebox_setting("add_base", 5))
    assert ask["status"] == "needs_confirmation" and "4 → 5" in ask["question"]
    assert store.load_show().economy.add_base == 4 and not _writes(spotfx)
    done = _run(jc._op_set_jukebox_setting("add_base", 5, confirm_id=ask["confirm_id"]))
    assert done["status"] == "applied" and done["new"] == {"add_base": 5}
    assert store.load_show().economy.add_base == 5


def test_an_out_of_range_value_is_refused_before_he_is_asked(spotfx):
    r = _run(jc._op_set_jukebox_setting("add_base", 999))
    assert r["status"] == "rejected" and "add_base" in r["reason"]
    assert not _writes(spotfx) and not jc._PENDING


def test_a_guest_rule_asks_first_and_is_validated_by_spotfx(spotfx):
    """The guests' own rules (phase 2.2: last call, explicit songs, phones,
    renames) are settings like any other: asked first, the one validator."""
    r = _run(jc._op_get_jukebox_settings())
    assert r["guest_rules"]["last_call_min"] == 20 and r["guest_rules"]["explicit"] == "no"
    ask = _run(jc._op_set_jukebox_setting("last_call_min", 30))
    assert ask["status"] == "needs_confirmation" and "20 → 30" in ask["question"]
    assert "last call" in ask["question"] and not _writes(spotfx)
    done = _run(jc._op_set_jukebox_setting("last_call_min", 30, confirm_id=ask["confirm_id"]))
    assert done["status"] == "applied" and store.load_show().last_call_min == 30
    for key, bad in (("last_call_min", 90), ("explicit", "sometimes"), ("night_ends", "midnight")):
        r = _run(jc._op_set_jukebox_setting(key, bad))
        assert r["status"] == "rejected" and key in r["reason"]
    assert set(jc.GUEST_RULE_KEYS) <= set(m.ShowConfig.model_fields)


def test_program_keys_and_approval_go_to_their_own_stores(spotfx):
    ask = _run(jc._op_set_jukebox_setting("every", 3))
    assert _run(jc._op_set_jukebox_setting("every", 3, confirm_id=ask["confirm_id"]))["status"] == "applied"
    assert store.load_config().every == 3
    ask = _run(jc._op_set_jukebox_setting("approve_new_phones", True))
    assert "off → on" in ask["question"]
    _run(jc._op_set_jukebox_setting("approve_new_phones", True, confirm_id=ask["confirm_id"]))
    assert store.load_show().approve_new_phones is True


def test_manual_mode_unknown_keys_and_unchanged_values(spotfx):
    assert "placed by hand" in _run(jc._op_set_jukebox_setting("mode", "manual"))["reason"]
    assert _run(jc._op_set_jukebox_setting("playlist", PLAYLIST_URI))["status"] == "rejected"
    assert _run(jc._op_set_jukebox_setting("add_base", 4))["status"] == "unchanged"
    assert not jc._PENDING and not _writes(spotfx)


def test_a_yes_covers_only_the_question_he_was_asked(spotfx, _fresh_confirmations):
    ask = _run(jc._op_set_jukebox_setting("add_base", 5))
    other = _run(jc._op_set_jukebox_setting("add_base", 6, confirm_id=ask["confirm_id"]))
    assert other["status"] == "rejected" and "changed" in other["reason"]
    assert store.load_show().economy.add_base == 4
    # used up: the same id can't be spent again
    again = _run(jc._op_set_jukebox_setting("add_base", 5, confirm_id=ask["confirm_id"]))
    assert again["status"] == "rejected"
    # the settings moving under the question voids it
    ask = _run(jc._op_set_jukebox_setting("add_base", 5))
    spotfx.put("/api/jukebox/show", json={"economy": {"add_cap": 50}})
    r = _run(jc._op_set_jukebox_setting("add_base", 5, confirm_id=ask["confirm_id"]))
    assert r["status"] == "rejected" and store.load_show().economy.add_base == 4
    # and it expires
    ask = _run(jc._op_set_jukebox_setting("add_base", 5))
    _fresh_confirmations[0] += jc.CONFIRM_TTL_S + 1
    assert "expired" in _run(jc._op_set_jukebox_setting("add_base", 5, confirm_id=ask["confirm_id"]))["reason"]


def test_a_preset_asks_and_sets_the_program(spotfx):
    ask = _run(jc._op_apply_jukebox_preset("large"))
    assert ask["status"] == "needs_confirmation" and "jukebox first" in ask["question"]
    assert store.load_config().mode == "auto"
    done = _run(jc._op_apply_jukebox_preset("large", confirm_id=ask["confirm_id"]))
    assert done["status"] == "applied"
    assert store.load_config().mode == "jukebox_first" and store.load_show().approve_new_phones is True
    assert _run(jc._op_apply_jukebox_preset("huge"))["status"] == "rejected"


# ═══ 4. starting and stopping a night need his explicit yes ═════════════════

def test_a_start_refuses_without_his_yes_and_starts_on_it(spotfx):
    spotfx.put("/api/jukebox/config", json={"playlist": PLAYLIST_URI})
    ask = _run(jc._op_start_jukebox_night())
    assert ask["status"] == "needs_confirmation" and "Start a Jukebox night" in ask["question"]
    assert not spotfx.world.runner.running
    assert not [x for x in spotfx.calls if x[1] == "/api/jukebox/night/start"]
    bogus = _run(jc._op_start_jukebox_night(confirm_id="not-one-of-ours"))
    assert bogus["status"] == "rejected" and not spotfx.world.runner.running
    done = _run(jc._op_start_jukebox_night(confirm_id=ask["confirm_id"]))
    assert done["status"] == "applied" and spotfx.world.runner.running
    assert spotfx.world.runner.night.started_by == "sonic"


def test_a_start_from_another_song_is_a_different_question(spotfx):
    spotfx.put("/api/jukebox/config", json={"playlist": PLAYLIST_URI})
    ask = _run(jc._op_start_jukebox_night(from_song=1))
    r = _run(jc._op_start_jukebox_night(from_song=5, confirm_id=ask["confirm_id"]))
    assert r["status"] == "rejected" and not spotfx.world.runner.running


def test_a_start_is_refused_by_the_routes_own_gates(spotfx):
    r = _run(jc._op_start_jukebox_night())
    assert r["status"] == "rejected" and "no set playlist" in r["reason"]   # nothing linked
    spotfx.put("/api/jukebox/config", json={"playlist": PLAYLIST_URI})
    spotfx.world.asleep = True
    ask = _run(jc._op_start_jukebox_night())
    r = _run(jc._op_start_jukebox_night(confirm_id=ask["confirm_id"]))
    assert r["status"] == "rejected" and r["refusal"] == "sleeping"
    assert not spotfx.world.runner.running


def test_a_stop_asks_and_a_yes_covers_only_that_night(spotfx):
    assert _run(jc._op_stop_jukebox_night())["reason"] == "no Jukebox night is running"
    spotfx.put("/api/jukebox/config", json={"playlist": PLAYLIST_URI})
    spotfx.post("/api/jukebox/night/start", json={})
    ask = _run(jc._op_stop_jukebox_night())
    assert ask["status"] == "needs_confirmation" and spotfx.world.runner.running
    # that night ends and another starts: the old yes does not stop the new one
    spotfx.post("/api/jukebox/night/stop", json={})
    spotfx.post("/api/jukebox/night/start", json={})
    r = _run(jc._op_stop_jukebox_night(confirm_id=ask["confirm_id"]))
    assert r["status"] == "rejected" and spotfx.world.runner.running
    ask = _run(jc._op_stop_jukebox_night(pause=True))
    assert "Spotify is paused" in ask["question"]
    done = _run(jc._op_stop_jukebox_night(pause=True, confirm_id=ask["confirm_id"]))
    assert done["status"] == "applied" and not spotfx.world.runner.running


def test_an_unreachable_spotfx_is_said_so(monkeypatch):
    async def down(*a, **k):
        raise ConnectionError("refused")
    monkeypatch.setattr(jc, "http", down)
    r = _run(jc._op_start_jukebox_night())
    assert r["status"] == "rejected" and "did not answer" in r["reason"]


def test_the_night_report_is_a_read(spotfx):
    r = _run(jc._op_jukebox_night_report())
    assert r["status"] == "ok" and r["summary"] == "No night has been played yet."
    spotfx.put("/api/jukebox/config", json={"playlist": PLAYLIST_URI})
    spotfx.post("/api/jukebox/night/start", json={})
    spotfx.post("/api/jukebox/night/stop", json={})
    r = _run(jc._op_jukebox_night_report())
    assert r["status"] == "ok" and r["credits"] is None and r["guests"] is None
    assert r["rows"] and all(x["this_night"] is None and x["why"] for x in r["rows"])
    r = _run(jc._op_jukebox_night_report(guests=8))
    assert r["guests"] == 8 and all(x["yours"] is not None or x["key"] == "songs_per_lurk" for x in r["rows"])
    assert not _writes(spotfx)
