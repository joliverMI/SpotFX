"""HOUSE LIGHTING — the wire (spectra/api/house.py): the call Home Assistant
makes on port 8010, its read-back, and the library routes.

  * POST /api/house/modes refuses a mode naming a scene or colour set that
    does not exist (it would silently do nothing) and a duplicate name.
  * POST /api/house/mode {"ha_mode": ..., "source": "ha"} selects by HA's
    own word, is idempotent, and answers 200 with a status word even when
    nothing maps (HA's heartbeat must never error); PUT is the same call.
  * An unknown mode NAME is 404 — a typo, not a heartbeat.
  * GET /api/house/mode and engine status's `lighting` key read it back.
  * Deleting the live mode clears it.

The room is not SPECTRA's in this process, so the layer stays inert: these
are the wire's own rules, nothing physical.
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from spectra import config as scfg
    from spectra.app import create_app
    from spectra.models.scene import SceneV2
    from spectra.services import scene_store
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    (tmp_path / "color_sets.json").write_text(json.dumps({
        "calm": {"id": "calm", "name": "Calm", "kind": "set", "entries": []}}))
    star = SceneV2(name="Star")
    scene_store.save(star)
    c = TestClient(create_app())
    c.star_id = star.id
    return c


def _standard(client, **extra):
    body = {"name": "Standard", "ha_aliases": ["Daytime"],
            "scenes": [{"scene_id": client.star_id}],
            "color_sets": [{"card_id": "calm"}], **extra}
    r = client.post("/api/house/modes", json=body)
    assert r.status_code == 200, r.text
    return r.json()["mode"]


def test_a_mode_naming_a_missing_scene_or_colour_set_is_refused(client):
    r = client.post("/api/house/modes", json={
        "name": "Bad", "scenes": [{"scene_id": "nope"}],
        "color_sets": [{"card_id": "gone"}]})
    assert r.status_code == 422
    assert "no scene" in r.text and "no colour set" in r.text


def test_a_malformed_mode_is_422_with_the_field(client):
    r = client.post("/api/house/modes", json={
        "name": "Bad", "hue": [{"area": "*", "look": "hold"}]})
    assert r.status_code == 422
    assert "colour temperature" in r.json()["detail"]


def test_duplicate_names_and_aliases_are_409(client):
    _standard(client)
    r = client.post("/api/house/modes", json={"name": "Other", "ha_aliases": ["daytime"]})
    assert r.status_code == 409


def test_ha_selects_by_its_own_word_and_reads_it_back(client):
    mode = _standard(client)
    r = client.post("/api/house/mode", json={"ha_mode": "Daytime", "source": "ha"})
    assert r.status_code == 200 and r.json()["status"] == "applied"
    lighting = r.json()["lighting"]
    assert lighting["mode"]["id"] == mode["id"] and lighting["source"] == "ha"
    assert lighting["manual"] is False and lighting["ha_value"] == "Daytime"
    # the room is not SPECTRA's here: recorded, inert, and it says why
    assert lighting["active"] is False and lighting["phase"] == "inactive"
    again = client.put("/api/house/mode", json={"ha_mode": "Daytime", "source": "ha"})
    assert again.status_code == 200 and again.json()["status"] == "unchanged"
    read = client.get("/api/house/mode").json()
    assert read["mode"]["name"] == "Standard"
    status = client.get("/api/engine/status").json()
    assert status["lighting"]["mode"]["name"] == "Standard"


def test_an_unmapped_ha_word_is_200_with_a_status(client):
    _standard(client)
    r = client.post("/api/house/mode", json={"ha_mode": "Party", "source": "ha"})
    assert r.status_code == 200 and r.json()["status"] == "unmapped"


def test_an_unknown_mode_name_is_404(client):
    r = client.post("/api/house/mode", json={"mode": "Nope"})
    assert r.status_code == 404


def test_modes_list_carries_every_alias(client):
    _standard(client)
    data = client.get("/api/house/modes").json()
    assert data["aliases"] == {"Daytime": "Standard"}
    assert [m["name"] for m in data["modes"]] == ["Standard"]


def test_deleting_the_live_mode_clears_it(client):
    mode = _standard(client)
    client.post("/api/house/mode", json={"mode": "Standard"})
    r = client.delete(f"/api/house/modes/{mode['id']}")
    assert r.status_code == 200 and r.json()["cleared"] is True
    assert client.get("/api/house/mode").json()["mode"] is None
    assert client.delete(f"/api/house/modes/{mode['id']}").status_code == 404


def test_targets_lists_fixtures_categories_and_hue_areas(client):
    data = client.get("/api/house/targets").json()
    assert set(data) >= {"fixtures", "categories", "hue_areas", "live"}
