"""GET /api/analysed-plan — the planned analysed events the debug page's
shape canvas draws (spectra/api/analysed_plan.py). Proves it serves the ONE
plan (analysed_flares.plan_for_song / the trigger engine's own cache), the
stored generated scene cues when they exist, and nothing under the modes
where analysed events never fire."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from spectra.models.trigger import FireSceneAction, SpectraTrigger
from spectra.services import midsong_generator, trigger_store

URI = "spotify:track:analysed-plan-api"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    kept = [midsong_generator.CandidateMoment(10_000, 0.6, "section:10000")]
    unselected = [midsong_generator.CandidateMoment(40_000, 0.3, "section:40000")]
    monkeypatch.setattr(midsong_generator, "plan_moments",
                        lambda uri: midsong_generator.MomentPlan(kept, unselected))


def _client():
    from spectra.app import create_app
    return TestClient(create_app())


def _mode(mode):
    from spectra.services import room_controls
    room_controls.save_room_controls(room_controls.RoomControlState(scene_change_mode=mode))


def test_untriggered_song_serves_planned_scene_cues_and_flares():
    _mode("analysed")
    body = _client().get("/api/analysed-plan", params={"uri": URI}).json()
    assert body["applies"] is True
    assert body["scene_source"] == "planned"
    assert [e["timestamp_ms"] for e in body["scene_changes"]] == [10_000]
    assert [e["timestamp_ms"] for e in body["flares"]] == [40_000]
    assert isinstance(body["show_clock_shift_ms"], int)


def test_stored_generated_scene_cues_are_what_is_drawn():
    _mode("analysed")
    trigger_store.upsert(URI, SpectraTrigger(
        timestamp_ms=12_000, source="generated", generator_key="section:10000",
        trigger_offset_ms=-200, action=FireSceneAction(scene_id=None, intensity=0.6)))
    body = _client().get("/api/analysed-plan", params={"uri": URI}).json()
    assert body["scene_source"] == "stored"
    assert [e["timestamp_ms"] for e in body["scene_changes"]] == [11_800]


def test_transitions_mode_draws_nothing():
    _mode("transitions")
    body = _client().get("/api/analysed-plan", params={"uri": URI}).json()
    assert body["applies"] is False and body["reason"]
    assert body["scene_changes"] == [] and body["flares"] == []


def test_authored_song_under_triggers_only_draws_nothing():
    _mode("triggers_only")
    trigger_store.upsert(URI, SpectraTrigger(
        timestamp_ms=5_000, source="authored", action=FireSceneAction(scene_id="s")))
    body = _client().get("/api/analysed-plan", params={"uri": URI}).json()
    assert body["applies"] is False
    assert body["flares"] == []


def test_serves_the_engine_cached_plan_for_the_playing_song(monkeypatch):
    """No second copy: while the engine holds a plan for this song, the
    markers are that exact list."""
    _mode("analysed")
    from spectra.services.trigger_engine import trigger_engine
    from spectra.models.trigger import FireResponseAction
    cached = [SpectraTrigger(id="analysed-flare:x", timestamp_ms=55_555, source="generated",
                             action=FireResponseAction(event_class="flare", intensity=0.4))]
    monkeypatch.setattr(trigger_engine, "cached_flare_triggers",
                        lambda uri: cached if uri == URI else None)
    body = _client().get("/api/analysed-plan", params={"uri": URI}).json()
    assert [e["timestamp_ms"] for e in body["flares"]] == [55_555]


def test_engine_cache_is_the_list_tick_fires():
    import asyncio
    from spectra.services.analysed_flares import FlareMoment, SongPlan
    from spectra.services.trigger_engine import TriggerEngine
    te = TriggerEngine(list_triggers=lambda uri: [],
                       analysed_plan=lambda uri, st: SongPlan(
                           [], [FlareMoment(40_000, 0.3, "section:40000")]))

    async def run():
        await te.on_track_state(URI)
        assert te.cached_flare_triggers(URI) is None
        await te.plan_analysed_flares(URI)
    asyncio.run(run())
    assert [t.timestamp_ms for t in te.cached_flare_triggers(URI)] == [40_000]
    assert te.cached_flare_triggers("spotify:track:other") is None
