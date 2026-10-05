"""HOUSE LIGHTING phase 2 — the wire (spectra/api/house.py's phase-2
routes, docs/HOUSE_HA_SEAM.md): the calls Home Assistant makes on :8010.

The room is not SPECTRA's in this process (the stack is down), so nothing
here is ACTED on — these are the wire's own rules: every report is
RECORDED and answered with a status word, a bad request is a 4xx naming the
field, and the heartbeat says plainly what state the engine is in. With the
stack down a fixture is named from the stored fx-live config.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from spectra import config as scfg
    from spectra.app import create_app
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    fx_dir = tmp_path / "fx-live"
    fx_dir.mkdir()
    (fx_dir / "config.json").write_text(json.dumps({"devices": [
        {"id": "crystal", "type": "wled", "config": {"name": "Crystal"}},
        {"id": "tv-backlight", "type": "wled", "config": {"name": "TV Mapper"}},
        {"id": "sconce-kitchen-left", "type": "wled",
         "config": {"name": "Sconce, Kitchen, Left"}},
        {"id": "hue-lights", "type": "hue", "config": {"name": "Hue Lights"}},
    ], "virtuals": []}))
    monkeypatch.setattr(scfg, "FX_LIVE_CONFIG_DIR", fx_dir)
    from fx import light_ownership
    monkeypatch.setattr(light_ownership, "load",
                        lambda: SimpleNamespace(owner=light_ownership.RELEASED))
    return TestClient(create_app())


def test_heartbeat_is_one_word_and_cheap(client):
    t0 = time.monotonic()
    r = client.get("/api/house/heartbeat")
    assert r.status_code == 200
    body = r.json()
    assert time.monotonic() - t0 < 1.0
    assert body["state"] == "released"
    assert body["lighting_ok"] is False
    for key in ("at_ms", "uptime_s", "owner", "mode", "withheld", "tv_strip",
                "voice"):
        assert key in body, key


def test_heartbeat_reports_down_and_driving(client, monkeypatch):
    from fx import light_ownership
    from spectra.services import engine, house, house_store
    from spectra.models.house_mode import HouseMode
    from spectra.services.live_host import live
    monkeypatch.setattr(light_ownership, "load",
                        lambda: SimpleNamespace(owner=light_ownership.SPECTRA))
    assert client.get("/api/house/heartbeat").json()["state"] == "down"
    monkeypatch.setattr(live, "host", SimpleNamespace(devices={}, virtuals={}))
    monkeypatch.setattr(engine, "executor", SimpleNamespace(mode="facade"))
    monkeypatch.setattr(house, "gate", lambda: (None, None))
    assert client.get("/api/house/heartbeat").json()["state"] == "idle"
    mode = house_store.put_mode(HouseMode(name="Standard"))
    house_store.state().mode_id = mode.id
    body = client.get("/api/house/heartbeat").json()
    assert body["state"] == "driving" and body["lighting_ok"] is True
    assert body["mode"] == "Standard"
    monkeypatch.setattr(engine, "executor", SimpleNamespace(mode="recording"))
    assert client.get("/api/house/heartbeat").json()["state"] == "on_paper"


def test_a_fixture_request_is_recorded_and_says_it_is_not_acted_on(client):
    r = client.put("/api/house/fixture/crystal", json={"state": "off"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "recorded" and body["acting"] is False
    assert "not acted on" in body["note"]
    assert body["override"]["power"] == "off"
    r = client.post("/api/house/fixture/TV Mapper", json={"lent_to": "hyperion"})
    assert r.json()["fixture"] == "tv-backlight"
    r = client.put("/api/house/fixture/crystal", json={"state": "off"})
    assert r.json()["status"] == "unchanged"
    # leaving a field out leaves it alone
    r = client.put("/api/house/fixture/crystal", json={"lent_to": None})
    assert r.json()["override"]["power"] == "off"
    r = client.get("/api/house/fixtures")
    assert r.status_code == 200
    assert {f["device"] for f in r.json()["fixtures"]} >= {"crystal", "tv-backlight"}


def test_fixture_errors_name_the_problem(client):
    assert client.put("/api/house/fixture/nope", json={"state": "off"}).status_code == 404
    r = client.put("/api/house/fixture/crystal", json={"state": "dim"})
    assert r.status_code == 422
    r = client.put("/api/house/fixture/hue-lights", json={"state": "off"})
    assert r.status_code == 422 and "Hue" in r.json()["detail"]
    r = client.put("/api/house/fixture/crystal", json={})
    assert r.status_code == 422


def test_tv_music_media_voice_and_recheck(client):
    r = client.put("/api/house/tv-music", json={"on": False})
    assert r.status_code == 200 and r.json()["status"] == "recorded"
    assert r.json()["tv_strip"]["devices"] == ["tv-backlight"]
    r = client.post("/api/house/media", json={"source": "roku", "state": "playing"})
    assert r.status_code == 200 and r.json()["status"] == "recorded"
    assert client.post("/api/house/media",
                       json={"source": "roku", "state": "ff"}).status_code == 422
    r = client.post("/api/house/voice", json={"state": "listening"})
    assert r.status_code == 200 and r.json()["status"] == "skipped"
    assert client.post("/api/house/voice", json={"state": "x"}).status_code == 422
    r = client.post("/api/house/recheck", json={"fixtures": ["sconce-kitchen-left"]})
    assert r.status_code == 200 and r.json()["status"] == "skipped"
    assert client.post("/api/house/recheck", json={"fixtures": []}).status_code == 422
    lighting = client.get("/api/house/mode").json()
    assert lighting["tv_music"] is False
    assert lighting["media"]["source"] == "roku"
    assert lighting["seam_active"] is False


def test_settings_round_trip_and_refuse_nonsense(client):
    r = client.get("/api/house/settings")
    s = r.json()["settings"]
    assert s["tv_strips"] == ["tv-backlight"] and s["owned_brightness"] == 255
    assert s["voice_looks"]["listening"]["color"] == "#0000ff"
    r = client.put("/api/house/settings", json={"owned_brightness": 200,
                                                 "voice_looks": {"listening": {"color": "#112233"}}})
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert s["owned_brightness"] == 200
    assert s["voice_looks"]["listening"]["color"] == "#112233"
    assert s["voice_looks"]["processing"]["color"] == "#26a269", "others kept"
    r = client.put("/api/house/settings",
                   json={"voice_looks": {"processing": {"level": 50}}})
    s = r.json()["settings"]
    assert s["voice_looks"]["listening"]["color"] == "#112233", \
        "editing one state keeps his other edits"
    assert s["voice_looks"]["processing"] == {"color": "#26a269", "level": 50.0}
    assert client.put("/api/house/settings",
                      json={"owned_brightness": 999}).status_code == 422
    assert client.put("/api/house/settings",
                      json={"voice_looks": {"singing": {"color": "#000000"}}}).status_code == 422
    # the modes in the same file are untouched by a settings edit
    assert client.get("/api/house/modes").status_code == 200


# ═══ phase 3: mains and the energy settings ══════════════════════════════════

def test_mains_off_and_on_are_recorded_and_named(client):
    r = client.put("/api/house/mains", json={
        "fixtures": ["sconce-kitchen-left", "Sconce, Kitchen, Left"], "on": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "recorded" and body["acting"] is False
    assert "not acted on" in body["note"]
    assert set(body["mains_off"]) == {"sconce-kitchen-left"}
    hb = client.get("/api/house/heartbeat").json()
    assert hb["mains_off"] == ["sconce-kitchen-left"]
    # the same report again is a no-op
    assert client.post("/api/house/mains", json={
        "fixtures": ["sconce-kitchen-left"], "on": False}).json()["status"] == "unchanged"
    r = client.put("/api/house/mains", json={"fixtures": ["sconce-kitchen-left"], "on": True})
    body = r.json()
    assert body["status"] == "recorded" and body["mains_off"] == {}
    assert body["recheck"]["status"] == "skipped", "the room is released"
    assert client.put("/api/house/mains", json={
        "fixtures": ["nope"], "on": False}).status_code == 404
    assert client.put("/api/house/mains", json={"fixtures": [], "on": False}).status_code == 422
    assert client.put("/api/house/mains", json={"fixtures": ["crystal"]}).status_code == 422


def test_energy_settings_merge_partially(client):
    s = client.get("/api/house/settings").json()["settings"]["energy"]
    assert s["resting_fps"] == {"Matrix": 20, "Strips": 20, "Singles": 10}
    assert s["park_idle"] is True and s["send_on_change"] is True
    assert s["keepalive_s"] == 1.0 and s["audio_pause_after_s"] == 120.0
    r = client.put("/api/house/settings", json={"energy": {
        "resting_fps": {"Matrix": 15, "Strips": None}, "keepalive_s": 0.5}})
    assert r.status_code == 200, r.text
    e = r.json()["settings"]["energy"]
    assert e["resting_fps"] == {"Matrix": 15, "Singles": 10}, "one cap, one removed"
    assert e["keepalive_s"] == 0.5 and e["park_idle"] is True, "the rest kept"
    assert client.put("/api/house/settings", json={"energy": {
        "keepalive_s": 3.0}}).status_code == 422, "outside the sconces' timeout"
    assert client.put("/api/house/settings", json={"energy": {
        "resting_fps": {"Matrix": 0}}}).status_code == 422
