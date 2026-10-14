"""THE ONE SHOW CLOCK (song-layout-plan, data/ui-layout-plan/report.md
§4.1/§7): `engine.current_show_clock_ms()` must be a second READER of the
exact application point `_run_trigger_engine` already feeds `tick()` with
— `av_sync_lead.show_clock_ms(bridge.effective_position_ms(),
av_sync_lead.current_lead_ms(), known_buffer.compensation_ms())` — never a
second idea of it, and `run_clock_push_supervised` must broadcast exactly
that number once a second."""
from __future__ import annotations

import asyncio

import pytest

from spectra.services import engine
from spectra.services.bridge import SpotEffectsBridge


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")


def test_none_with_no_track(monkeypatch):
    monkeypatch.setattr(engine, "bridge", SpotEffectsBridge())
    assert engine.current_show_clock_ms() is None


def test_matches_the_tick_application_point_exactly(monkeypatch):
    from spectra.services import av_sync_lead, known_buffer, room_controls

    fake_bridge = SpotEffectsBridge()
    _run(fake_bridge.handle_message({
        "type": "state", "paused": False,
        "track": {"spotify_uri": "spotify:track:x", "is_playing": True,
                 "progress_ms": 10_000},
    }))
    monkeypatch.setattr(engine, "bridge", fake_bridge)

    room_controls.save_room_controls(
        room_controls.RoomControlState(av_sync_lead_ms=120))
    monkeypatch.setattr(known_buffer, "compensation_ms", lambda: 0)

    effective = fake_bridge.effective_position_ms()
    expected = av_sync_lead.show_clock_ms(
        effective, av_sync_lead.current_lead_ms(), known_buffer.compensation_ms())
    assert expected == effective + 120
    assert engine.current_show_clock_ms() == expected


def test_bridge_status_with_clock_folds_it_into_the_track_block(monkeypatch):
    from spectra.services import known_buffer
    monkeypatch.setattr(known_buffer, "compensation_ms", lambda: 0)
    fake_bridge = SpotEffectsBridge()
    _run(fake_bridge.handle_message({
        "type": "state", "paused": False,
        "track": {"spotify_uri": "spotify:track:x", "is_playing": True,
                 "progress_ms": 1000},
    }))
    monkeypatch.setattr(engine, "bridge", fake_bridge)
    body = engine._bridge_status_with_clock()
    assert body["track"]["show_clock_ms"] == engine.current_show_clock_ms()


def test_clock_push_broadcasts_show_clock_position_and_playing(monkeypatch):
    from spectra.services import known_buffer
    monkeypatch.setattr(known_buffer, "compensation_ms", lambda: 0)
    fake_bridge = SpotEffectsBridge()
    _run(fake_bridge.handle_message({
        "type": "state", "paused": False,
        "track": {"spotify_uri": "spotify:track:x", "is_playing": True,
                 "progress_ms": 2000},
    }))
    monkeypatch.setattr(engine, "bridge", fake_bridge)

    sent = []

    async def fake_broadcast(payload):
        sent.append(payload)
        raise asyncio.CancelledError  # stop the loop after one push

    monkeypatch.setattr(engine.ws_manager, "broadcast", fake_broadcast)

    async def run():
        try:
            await engine.run_clock_push_supervised()
        except asyncio.CancelledError:
            pass
    _run(run())

    assert len(sent) == 1
    msg = sent[0]
    assert msg["type"] == "clock"
    assert msg["show_clock_ms"] == engine.current_show_clock_ms()
    assert msg["position_ms"] == fake_bridge.effective_position_ms()
    assert msg["is_playing"] is True
    assert isinstance(msg["server_ms"], int)
