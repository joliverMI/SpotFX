"""Absorb Music's routes (routers/absorb_router.py) over a real FastAPI app,
with the runner wired to the fake world (tests/absorb_world.py)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import absorb_router
from services import absorb, absorb_store
from tests.absorb_world import SOURCE_ID, World, uri


@pytest.fixture
def client(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, warm_up=False)
    monkeypatch.setattr(absorb, "runner", w.runner)
    app = FastAPI()
    app.include_router(absorb_router.router)
    with TestClient(app) as c:
        c.world = w
        yield c


def test_config_round_trip_is_partial_and_validated(client):
    cfg = client.get("/api/absorb/config").json()
    assert cfg["enabled"] is False and cfg["captured_playlist_name"] == "Recently Captured"
    r = client.put("/api/absorb/config", json={"max_attempts": 4, "order": "playlist"})
    assert r.status_code == 200 and r.json()["max_attempts"] == 4
    assert r.json()["source_playlist_uri"].endswith(SOURCE_ID)     # untouched
    assert client.put("/api/absorb/config", json={"max_atempts": 4}).status_code == 422
    bad = client.put("/api/absorb/config", json={"order": "random"})
    assert bad.status_code == 422 and bad.json()["detail"][0]["field"] == "order"
    assert client.put("/api/absorb/config", json={
        "windows": [{"days": ["Mon"], "start": "25:00", "end": "00:30"}]}).status_code == 422
    assert absorb_store.load_config().max_attempts == 4


def test_a_refused_start_is_a_200_with_its_reason(client):
    client.world.anchors = False
    r = client.post("/api/absorb/start")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "refused" and body["reason"] == "anchor_disabled"
    run = client.get("/api/absorb/run").json()
    assert run["brief"]["state"] == "refused"


def test_start_skip_stop(client):
    w = client.world
    w.gw.playlists[SOURCE_ID] = [uri(1), uri(2)]
    body = client.post("/api/absorb/start").json()
    assert body["status"] == "running"
    assert client.post("/api/absorb/start").json()["status"] == "already_running"
    assert client.post("/api/absorb/skip-song").json()["status"] == "nothing_playing"
    run = client.get("/api/absorb/run").json()
    assert run["brief"]["queue_len"] == 2 and run["run"]["queue"] == [uri(1), uri(2)]
    assert client.post("/api/absorb/stop").json()["status"] == "ended"
    assert client.post("/api/absorb/stop").json()["status"] == "not_running"


def test_preview_counts_the_linked_playlist(client):
    w = client.world
    w.gw.playlists[SOURCE_ID] = [uri(1), uri(2), uri(3)]
    w.disk.set(uri(1), "skip", head_ms=0)
    w.disk.set(uri(2), "recapture", ["headless"], head_ms=5000)
    p = client.get("/api/absorb/preview").json()
    assert p["counts"] == {"total": 3, "skip": 1, "fresh": 1, "recapture": 1, "parked": 0}
    assert p["reasons"]["headless"] == 1
    assert w.gw.writes() == []                       # a preview writes nothing


def test_preview_with_nothing_linked(client):
    absorb.apply_config_patch({"source_playlist_uri": ""})
    assert client.get("/api/absorb/preview").json()["linked"] is False


def test_retry_unparks(client):
    from models.absorb import LedgerEntry
    ledger = absorb_store.load_ledger()
    ledger.entries[uri(1)] = LedgerEntry(uri=uri(1), parked=True)
    absorb_store.save_ledger(ledger)
    assert client.post("/api/absorb/retry", json={"uri": uri(1)}).json()["unparked"] is True
    assert client.post("/api/absorb/retry", json={"uri": uri(1)}).json()["unparked"] is False


def test_the_websocket_state_carries_the_absorb_brief(client, monkeypatch):
    import asyncio
    from models.state import AppState
    from services.websocket_manager import WebSocketManager
    sent = []
    mgr = WebSocketManager()

    async def capture(payload):
        sent.append(payload)

    monkeypatch.setattr(mgr, "broadcast", capture)
    asyncio.run(mgr.broadcast_state(AppState()))
    assert "absorb" in sent[0] and "state" in sent[0]["absorb"]
