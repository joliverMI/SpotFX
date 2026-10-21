"""Absorb Music phase 2's transports, against mocked HTTP only:

  api/ha_client.py            the house volume — via SPECTRA (default) or
                              Home Assistant directly; never raises, never
                              logs the token, never sends the .env.template
                              placeholder as one
  services/snapcast_status.py Server.GetStatus / Client.SetVolume, fail closed
  spectra/api/house_audio.py  SPECTRA's narrow route: two reads, one SNAPPED
                              volume write through the one ramp owner
  api/spotify_client          poll_ok (an unknown read is not "quiet") and
                              the fast poll while the house is silent
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from api import ha_client
from services import snapcast_status


def _go(coro):
    return asyncio.run(coro)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ═══ api/ha_client.py ══════════════════════════════════════════════════════

def test_via_spectra_reads_and_writes_the_narrow_route():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, req.content))
        if req.method == "GET":
            return httpx.Response(200, json={
                "configured": True,
                "snap_volume": {"ok": True, "value": 34.0, "detail": ""},
                "sleeping": {"ok": True, "value": True, "detail": ""}})
        return httpx.Response(200, json={"ok": True, "detail": "HA volume set to 0"})

    async def main():
        audio = ha_client.SpectraHouseAudio(
            "http://127.0.0.1:8010/spectra/api/house-audio", client=_client(handler))
        r = await audio.read()
        assert (r.volume, r.sleeping) == (34.0, True)
        w = await audio.set_volume(0)
        assert w.ok

    _go(main())
    assert seen[0][:2] == ("GET", "/spectra/api/house-audio")
    assert seen[1][:2] == ("PUT", "/spectra/api/house-audio/volume")
    assert json.loads(seen[1][2]) == {"volume": 0}


def test_via_spectra_an_unconfigured_or_unreachable_ha_is_unreadable_never_a_guess():
    def unconfigured(req):
        return httpx.Response(200, json={
            "configured": False,
            "snap_volume": {"ok": False, "value": None, "detail": "not configured"},
            "sleeping": {"ok": False, "value": None, "detail": "not configured"}})

    def down(req):
        raise httpx.ConnectError("refused")

    async def main():
        r = await ha_client.SpectraHouseAudio("http://x", client=_client(unconfigured)).read()
        assert r.volume is None and r.sleeping is None and "not configured" in r.detail
        r = await ha_client.SpectraHouseAudio("http://x", client=_client(down)).read()
        assert r.volume is None and "unreachable" in r.detail
        w = await ha_client.SpectraHouseAudio("http://x", client=_client(down)).set_volume(0)
        assert not w.ok

    _go(main())


def test_via_spectra_a_refused_write_is_not_ok():
    def handler(req):
        return httpx.Response(200, json={"ok": False, "detail": "Home Assistant answered 401"})

    w = _go(ha_client.SpectraHouseAudio("http://x", client=_client(handler)).set_volume(0))
    assert not w.ok and "401" in w.detail


def test_direct_reads_both_entities_and_calls_the_volume_script():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, req.headers.get("authorization"), req.content))
        if req.url.path.endswith("snap_volume"):
            return httpx.Response(200, json={"state": "34.0"})
        if req.url.path.endswith("sleeping"):
            return httpx.Response(200, json={"state": "off"})
        return httpx.Response(200, json=[])

    async def main():
        audio = ha_client.DirectHouseAudio("http://ha:8123", "tok", client=_client(handler))
        r = await audio.read()
        assert (r.volume, r.sleeping) == (34.0, False)
        assert (await audio.set_volume(-5)).ok

    _go(main())
    assert seen[-1][1] == "/api/services/script/music_volume_set"
    assert json.loads(seen[-1][3]) == {"volume": 0}          # clamped
    assert seen[0][2] == "Bearer tok"


def test_the_token_is_never_logged(caplog):
    def down(req):
        raise httpx.ConnectError("refused with Bearer secret-token-xyz")

    async def main():
        audio = ha_client.DirectHouseAudio("http://ha:8123", "secret-token-xyz",
                                           client=_client(down))
        await audio.read()
        await audio.set_volume(0)

    with caplog.at_level(logging.DEBUG):
        _go(main())
    assert "secret-token-xyz" not in caplog.text


def test_the_template_placeholder_is_never_sent_as_a_token(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "absorb_ha_via", "direct")
    monkeypatch.setattr(settings, "home_assistant_host", "http://ha:8123")
    monkeypatch.setattr(settings, "home_assistant_token", ha_client.TEMPLATE_PLACEHOLDER_TOKEN)
    audio = ha_client.from_settings()
    assert isinstance(audio, ha_client.DirectHouseAudio) and audio._headers() == {}
    monkeypatch.setattr(settings, "absorb_ha_via", "spectra")
    audio = ha_client.from_settings()
    assert isinstance(audio, ha_client.SpectraHouseAudio)
    assert audio.base_url.endswith(f":{settings.spectra_port}/spectra/api/house-audio")


# ═══ services/snapcast_status.py ═══════════════════════════════════════════

def _snap_body():
    return {"jsonrpc": "2.0", "id": 1, "result": {"server": {
        "groups": [{"id": "g1", "muted": False, "stream_id": "Spotify", "clients": [
            {"id": "eh", "connected": True, "host": {"name": "serenity"},
             "config": {"name": "Effects Host", "volume": {"percent": 100, "muted": False}}},
            {"id": "kit", "connected": True, "host": {"name": "kitchen-pi"},
             "config": {"name": "", "volume": {"percent": 8, "muted": False}}}]}],
        "streams": [{"id": "Spotify", "status": "playing"}, {"id": "TTS", "status": "idle"}]}}}


def test_snapcast_reads_the_status_on_a_fresh_connection():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json=_snap_body())

    st = _go(snapcast_status.SnapcastClient("http://snap/jsonrpc",
                                            client=_client(handler)).read_status())
    assert seen[0]["method"] == "Server.GetStatus"
    assert st.find("Effects Host").percent == 100
    assert st.find("kitchen-pi").percent == 8          # a client with no name: its host name
    assert st.streams == {"Spotify": "playing", "TTS": "idle"}


def test_snapcast_fails_closed():
    def err(req):
        return httpx.Response(200, json={"jsonrpc": "2.0", "error": {"code": -32601}})

    def empty(req):
        return httpx.Response(200, content=b"")

    def down(req):
        raise httpx.ConnectError("refused")

    for handler in (err, empty, down):
        with pytest.raises(snapcast_status.SnapcastUnreadable):
            _go(snapcast_status.SnapcastClient("http://snap", client=_client(handler))
                .read_status())


def test_snapcast_set_client_volume_sends_both_halves_and_raises_on_refusal():
    seen = []

    def ok(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})

    _go(snapcast_status.SnapcastClient("http://snap", client=_client(ok))
        .set_client_volume("kit", 8, True))
    assert seen[0]["method"] == "Client.SetVolume"
    assert seen[0]["params"] == {"id": "kit", "volume": {"percent": 8, "muted": True}}

    def refused(req):
        return httpx.Response(200, json={"jsonrpc": "2.0", "error": {"code": -1}})

    with pytest.raises(snapcast_status.SnapcastUnreadable):
        _go(snapcast_status.SnapcastClient("http://snap", client=_client(refused))
            .set_client_volume("kit", 8, True))


# ═══ spectra/api/house_audio.py ════════════════════════════════════════════

@pytest.fixture
def spectra_client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from spectra.api import house_audio
    from spectra.services import ha_client as sha, ha_volume_ease
    states = {"input_number.snap_volume": "34.0", "input_boolean.sleeping": "on"}
    calls = []

    async def get_state(entity, **kw):
        if entity not in states:
            return sha.HAEntityState(status=sha.STATUS_FAILED, detail="no such entity")
        return sha.HAEntityState(status=sha.STATUS_SENT, http_status=200, state=states[entity])

    async def set_absolute(volume, ease_s=1.0):
        calls.append((volume, ease_s))
        return ha_volume_ease.EaseResult(sha.HAResult(status=sha.STATUS_SENT, http_status=200),
                                         f"HA volume set to {volume:g}", {})

    monkeypatch.setattr(sha, "get_state", get_state)
    monkeypatch.setattr(sha, "configured", lambda: True)
    monkeypatch.setattr(ha_volume_ease, "set_absolute", set_absolute)
    app = FastAPI()
    app.include_router(house_audio.router)
    c = TestClient(app)
    c.states, c.calls = states, calls
    return c


def test_the_route_reads_the_two_entities(spectra_client):
    body = spectra_client.get("/api/house-audio").json()
    assert body["snap_volume"] == {"ok": True, "value": 34.0, "detail": ""}
    assert body["sleeping"]["value"] is True and body["configured"] is True
    spectra_client.states["input_boolean.sleeping"] = "unavailable"
    body = spectra_client.get("/api/house-audio").json()
    assert body["sleeping"]["ok"] is False and body["sleeping"]["value"] is None


def test_the_route_writes_one_snapped_volume_and_nothing_else(spectra_client):
    r = spectra_client.put("/api/house-audio/volume", json={"volume": 0})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert spectra_client.calls == [(0.0, 0.0)]          # ease 0: one write, stops any ramp
    assert spectra_client.put("/api/house-audio/volume",
                              json={"volume": 101}).status_code == 422
    assert spectra_client.put("/api/house-audio/volume",
                              json={"volume": -1}).status_code == 422


def test_the_route_is_mounted_on_spectra(spectra_client):
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    real = TestClient(create_app())
    assert real.get("/api/house-audio").json()["snap_volume"]["value"] == 34.0
    assert real.put("/api/house-audio/volume", json={"volume": 0}).json()["ok"] is True


# ═══ api/spotify_client ════════════════════════════════════════════════════

def test_a_failed_poll_is_unknown_and_an_answer_is_known(monkeypatch):
    from api import spotify_client
    from models.state import state

    class Boom:
        def current_playback(self):
            raise RuntimeError("Spotify 503")

    class Nothing:
        def current_playback(self):
            return None

    monkeypatch.setattr(state, "current_track", None)
    monkeypatch.setattr(spotify_client, "get_spotify", lambda: Boom())
    spotify_client.fetch_current_track()
    assert state.poll_ok is False
    monkeypatch.setattr(spotify_client, "get_spotify", lambda: Nothing())
    spotify_client.fetch_current_track()
    assert state.poll_ok is True


def test_the_poll_is_fast_while_absorb_holds_the_house_silent(monkeypatch):
    from api import spotify_client
    from config import settings
    from models.state import state
    monkeypatch.setattr(state, "current_track", None)
    monkeypatch.setattr(spotify_client, "_burst_until", 0.0)
    monkeypatch.setattr(state, "absorb_fast_poll", False)
    slow = spotify_client._poll_interval_ms()
    monkeypatch.setattr(state, "absorb_fast_poll", True)
    assert spotify_client._poll_interval_ms() == min(slow, settings.absorb_poll_interval_ms)
    assert settings.absorb_poll_interval_ms <= 1000
