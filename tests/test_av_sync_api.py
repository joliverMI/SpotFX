"""Route-shape proofs for spectra/api/av_sync.py over FastAPI's TestClient:
the WebSocket session opens with a welcome that carries the privacy
summary and an HONEST audio-reference availability (False here — no live
hub in a test process), ping/pong pairs the clocks, the frame tap is OFF
by default and ignores frames until enabled, a tapped frame is served
back with its timestamps, a refused pattern (no room) is a stated error
not a crash, and a closed session leaves nothing behind."""
from __future__ import annotations

import base64

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import av_sync_session as sessions
    monkeypatch.setattr(scfg, "AV_SYNC_MEASUREMENTS_FILE", tmp_path / "m.json")
    monkeypatch.setattr(scfg, "AV_SYNC_PATTERN_FILE", tmp_path / "p.json")
    sessions.current = None
    yield
    sessions.current = None


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _recv_until(ws, kind, limit=30):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == kind:
            return msg
    raise AssertionError(f"never received {kind!r}")


def test_session_opens_with_privacy_summary_and_honest_audio_ref():
    client = _client()
    with client.websocket_connect("/api/av-sync/ws") as ws:
        welcome = ws.receive_json()
        assert welcome["type"] == "welcome"
        assert welcome["privacy"]["raw_media_leaves_phone"] is False
        assert "av_sync_measurements.json" in welcome["privacy"]["written_to_disk"]
        assert welcome["audio_ref"]["available"] is False
        assert "not open" in (welcome["audio_ref"]["reason"] or "")
        assert welcome["frame_tap"]["enabled"] is False
        ws.send_json({"type": "hello", "user_agent": "test", "video": {"fps": 30}})
        assert _recv_until(ws, "hello_ack")["session_id"] == welcome["session_id"]
        status = client.get("/api/av-sync/status").json()
        assert status["session"]["session_id"] == welcome["session_id"]
        assert status["privacy"]["raw_media_leaves_phone"] is False
    assert client.get("/api/av-sync/status").json()["session"] is None


def test_ping_pong_pairs_clocks_and_estimate_refuses_without_audio_ref():
    client = _client()
    with client.websocket_connect("/api/av-sync/ws") as ws:
        ws.receive_json()
        ping = _recv_until(ws, "ping")
        ws.send_json({"type": "pong", "seq": ping["seq"], "t_phone_ms": 123456.0})
        # the loop may have emitted an estimate before the pong was handled —
        # read until one reflects the paired clock
        for _ in range(10):
            est = _recv_until(ws, "estimate", limit=60)
            if est["clock"]["ready"]:
                break
        assert est["ok"] is False
        assert est["clock"]["ready"] is True
        assert est["reason"] == "no_audio_ref"
        assert "not driving the room" in est["statement"]


def test_frame_tap_off_by_default_then_enabled_serves_latest_frame():
    client = _client()
    jpeg = base64.b64encode(b"\xff\xd8fakejpeg\xff\xd9").decode()
    with client.websocket_connect("/api/av-sync/ws") as ws:
        ws.receive_json()
        assert client.get("/api/av-sync/frame/latest").status_code == 404
        ws.send_json({"type": "frame", "captured_at_ms": 1.0, "width": 8, "height": 6,
                      "data": jpeg})
        ping = _recv_until(ws, "ping")
        ws.send_json({"type": "pong", "seq": ping["seq"], "t_phone_ms": 5000.0})
        # ignored while off
        _recv_until(ws, "estimate", limit=60)
        assert client.get("/api/av-sync/frame/latest").status_code == 404
        r = client.post("/api/av-sync/frame-tap", json={"enabled": True, "fps": 2, "width": 160})
        assert r.status_code == 200 and r.json()["frame_tap"]["enabled"] is True
        cfg = _recv_until(ws, "config", limit=60)
        assert cfg["frame_tap"] == {"enabled": True, "fps": 2.0, "width": 160}
        ws.send_json({"type": "frame", "captured_at_ms": 6000.0, "width": 8, "height": 6,
                      "data": jpeg, "mime": "image/jpeg"})
        _recv_until(ws, "estimate", limit=60)
        got = client.get("/api/av-sync/frame/latest")
        assert got.status_code == 200
        assert got.content == b"\xff\xd8fakejpeg\xff\xd9"
        assert got.headers["x-captured-at-phone-ms"] == "6000.0"
        assert got.headers["cache-control"] == "no-store"
        meta = client.get("/api/av-sync/frame/meta").json()
        assert meta["held"] == 1 and meta["latest"]["width"] == 8
        assert meta["latest"]["captured_at_server_s"] is not None
    # cleared on close
    assert client.get("/api/av-sync/frame/latest").status_code == 404
    assert client.post("/api/av-sync/frame-tap", json={"enabled": True}).status_code == 409


def test_measure_pattern_refused_cleanly_when_no_room(monkeypatch):
    from spectra.services import av_sync_pattern

    async def no_room():
        raise RuntimeError("no room in tests")
    monkeypatch.setattr(av_sync_pattern.driver, "_get_virtuals", no_room)
    client = _client()
    with client.websocket_connect("/api/av-sync/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "measure", "mode": "pattern"})
        err = _recv_until(ws, "error", limit=60)
        assert "pattern refused" in err["message"] and "no room in tests" in err["message"]
        ws.send_json({"type": "measure", "mode": "bogus"})
        assert "unknown mode" in _recv_until(ws, "error", limit=60)["message"]
    from spectra.services import preview_pause
    assert not preview_pause.active()


def test_measurements_endpoint_lists_records_and_privacy(tmp_path):
    from spectra import config as scfg
    from spectra.services import av_sync_session as sessions
    sessions.append_measurement({"id": "a", "av_offset_ms": -120.0})
    sessions.append_measurement({"id": "b", "av_offset_ms": -118.0})
    client = _client()
    data = client.get("/api/av-sync/measurements?limit=1").json()
    assert [m["id"] for m in data["measurements"]] == ["b"]
    assert data["privacy"]["raw_media_leaves_phone"] is False
    assert scfg.AV_SYNC_MEASUREMENTS_FILE.exists()
