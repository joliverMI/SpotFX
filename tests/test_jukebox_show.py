"""The Jukebox's show settings (services/jukebox/show.py, the routes in
routers/jukebox_router.py) — phase 3 PR 3.3's settings half: one validator
for every economy setting, the party-size presets, the price check."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.jukebox import EconomyConfig, ManualSlot, ProgramConfig, ShowConfig
from routers import jukebox_router
from services.jukebox import night as night_mod, show, store
from tests.jukebox_world import PLAYLIST_URI, World


def test_every_economy_setting_has_exactly_one_row_with_its_models_range():
    rows = show.fields()
    keys = [r["key"] for r in rows]
    assert sorted(keys) == sorted(EconomyConfig.model_fields) and len(keys) == len(set(keys))
    row = {r["key"]: r for r in rows}
    assert (row["start_credits"]["min"], row["start_credits"]["max"]) == (0, 20)
    assert (row["max_waiting"]["min"], row["max_waiting"]["max"], row["max_waiting"]["default"]) == (1, 3, 2)
    assert row["tips"]["kind"] == "bool" and row["skip_down_pct"]["kind"] == "float"
    assert {r["card"] for r in rows} == {"Free credits", "Earning", "Add a song", "Bumps",
                                         "Play next", "Skip", "Jail"}


def test_a_partial_edit_changes_only_what_it_names():
    new = show.apply_patch(ShowConfig(), {"economy": {"add_base": 5}})
    assert new.economy.add_base == 5 and new.economy.skip_max == 40
    new = show.apply_patch(new, {"approve_new_phones": True})
    assert new.approve_new_phones and new.economy.add_base == 5


@pytest.mark.parametrize("patch, word", [
    ({"nope": 1}, "unknown setting"),
    ({"economy": {"nope": 1}}, "unknown economy setting"),
    ({"economy": {"max_waiting": 4}}, "max_waiting"),
    ({"economy": {"topup_every_min": 10}}, "topup_every_min"),
    ({"economy": 3}, "economy"),
])
def test_a_bad_edit_is_refused_by_name(patch, word):
    with pytest.raises(ValueError) as e:
        show.apply_patch(ShowConfig(), patch)
    assert word in str(e.value)


def test_presets_set_the_program_and_large_turns_on_approval():
    prog = ProgramConfig(playlist=PLAYLIST_URI, mode="manual",
                         manual=[ManualSlot(after_uri="spotify:track:aaaaaaaaaaaaaaaaaaaaaa")])
    s, p = show.apply_preset("medium", ShowConfig(), prog)
    assert (p.mode, p.every, p.run) == ("auto", 1, 2) and s.preset == "medium"
    assert p.manual == prog.manual                    # his hand-placed slots are kept
    s, p = show.apply_preset("large", s, p)
    assert p.mode == "jukebox_first" and s.approve_new_phones is True
    s, p = show.apply_preset("small", s, p)
    assert (p.mode, p.every, p.run, s.approve_new_phones) == ("auto", 1, 1, False)
    with pytest.raises(ValueError):
        show.apply_preset("huge", s, p)


def test_the_price_check_is_the_economy_on_real_examples():
    pc = show.price_check(EconomyConfig(), 15)
    assert [x["price"] for x in pc["skip"]] == [55, 30, 18, 15]   # §1's worked row at 15
    assert [x["price"] for x in pc["add"]] == [4, 4, 5, 8, 16, 32]
    assert [x["price"] for x in pc["play_next"]] == [11, 13, 16, 23]
    assert pc["jail"] == {"threshold": 8, "fee": 10}
    assert pc["start"] == {"now": 4, "later": 4, "after_min": 20.0}
    cheap = show.price_check(EconomyConfig(add_base=2), 15)
    assert cheap["add"][0]["price"] == 2                           # it reads the settings it is given


# ── the routes ──────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    w = World()
    w.deps.load_config = store.load_config
    w.runner = night_mod.JukeboxRunner(w.deps)
    monkeypatch.setattr(night_mod, "runner", w.runner)
    app = FastAPI()
    app.include_router(jukebox_router.router)
    with TestClient(app) as c:
        yield w, c


def test_show_routes(client):
    _, c = client
    r = c.get("/api/jukebox/show").json()
    assert r["show"]["economy"]["start_credits"] == 8 and len(r["fields"]) == len(EconomyConfig.model_fields)
    assert [p["name"] for p in r["presets"]] == ["small", "medium", "large"]
    r = c.put("/api/jukebox/show?dry_run=true", json={"economy": {"jail_fee": 12}})
    assert r.status_code == 200 and r.json()["show"]["economy"]["jail_fee"] == 12
    assert not store.SHOW_FILE.exists()
    r = c.put("/api/jukebox/show", json={"economy": {"jail_fee": 12}})
    assert store.load_show().economy.jail_fee == 12
    r = c.put("/api/jukebox/show", json={"economy": {"jail_fee": 99}})
    assert r.status_code == 422 and "jail_fee" in r.json()["detail"]
    assert c.get("/api/jukebox/price-check?guests=15").json()["jail"]["fee"] == 12


def test_a_preset_saves_the_program_and_reaches_a_running_night(client):
    w, c = client
    c.put("/api/jukebox/config", json={"playlist": PLAYLIST_URI})
    import asyncio
    asyncio.run(w.runner.start())
    r = c.post("/api/jukebox/show/preset", json={"preset": "medium"})
    assert r.status_code == 200 and r.json()["config"]["run"] == 2
    assert store.load_config().run == 2 and store.load_show().preset == "medium"
    assert w.runner.cfg.run == 2                        # live from the next set song
    assert c.post("/api/jukebox/show/preset", json={"preset": "huge"}).status_code == 422


def test_the_harness_snapshot_is_the_servers_own_answer():
    """spectra/web/harness/jukeboxShowSnapshot.json is generated output (the
    Credits tab's render mock); it must still equal what the server says."""
    import json
    import pathlib
    path = pathlib.Path(__file__).resolve().parent.parent / "spectra/web/harness/jukeboxShowSnapshot.json"
    snap = json.loads(path.read_text(encoding="utf-8"))
    assert snap["fields"] == show.fields()
    assert snap["presets"] == show.presets()
    assert snap["price_check"] == {str(g): json.loads(json.dumps(show.price_check(EconomyConfig(), g)))
                                   for g in (4, 8, 15, 30)}
