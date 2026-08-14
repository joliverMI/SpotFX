"""Fire-history counter proof: persistence round-trip in isolation, then
each of the four production choke points (scene fires, response events,
colour applies, trigger firings) actually records through
spectra.services.fire_history — cheap by construction (durable counts,
never an event log). See spectra/services/fire_history.py.
"""
from __future__ import annotations

import asyncio
from random import Random

import pytest

from spectra import config


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FIRE_HISTORY_FILE",
                        tmp_path / "fire_history.json")


# ── persistence round-trip ────────────────────────────────────────────────

def test_record_creates_and_stamps_first_last():
    from spectra.services import fire_history

    fire_history.record("scenes", "s1", now_ms=1000)
    data = fire_history.load_all()
    entry = data["scenes"]["s1"]
    assert entry == {"count": 1, "first_fire_ms": 1000, "last_fire_ms": 1000}


def test_record_increments_and_moves_last_only():
    from spectra.services import fire_history

    fire_history.record("scenes", "s1", now_ms=1000)
    fire_history.record("scenes", "s1", now_ms=2000)
    entry = fire_history.load_all()["scenes"]["s1"]
    assert entry == {"count": 2, "first_fire_ms": 1000, "last_fire_ms": 2000}


def test_record_round_trips_across_fresh_loads():
    from spectra.services import fire_history

    fire_history.record("responses", "flare", now_ms=1)
    # a fresh load (new process, in effect) sees exactly what was written
    reloaded = fire_history.load_all()
    fire_history.record("responses", "flare", now_ms=2)
    again = fire_history.load_all()
    assert reloaded["responses"]["flare"]["count"] == 1
    assert again["responses"]["flare"]["count"] == 2


def test_buckets_stay_independent():
    from spectra.services import fire_history

    fire_history.record("scenes", "x", now_ms=1)
    fire_history.record("responses", "x", now_ms=1)
    data = fire_history.load_all()
    assert data["scenes"]["x"]["count"] == 1
    assert data["responses"]["x"]["count"] == 1
    assert "x" not in data["color_sets"]
    assert "x" not in data["triggers"]


def test_record_never_raises_on_bad_bucket():
    from spectra.services import fire_history

    fire_history.record("not-a-real-bucket", "k")  # must not raise
    data = fire_history.load_all()
    assert "not-a-real-bucket" not in data


def test_corrupt_file_falls_back_to_empty(tmp_path, monkeypatch):
    from spectra.services import fire_history

    monkeypatch.setattr(config, "FIRE_HISTORY_FILE", tmp_path / "bad.json")
    config.FIRE_HISTORY_FILE.write_text("{not json")
    fire_history.record("scenes", "s1", now_ms=1)
    data = fire_history.load_all()
    assert data["scenes"]["s1"]["count"] == 1


# ── choke point 1: scene_sequencer.fire_scene_by_id ───────────────────────

def test_scene_fire_records_by_scene_id(monkeypatch):
    from spectra.services import fire_history, scene_sequencer

    class FakeScene:
        id = "scene-1"

    monkeypatch.setattr("spectra.services.scene_store.get_by_id",
                        lambda sid: FakeScene())

    async def fake_fire_scene(scene, *, intensity, color_set, dry_run):
        return {"fired": True}

    monkeypatch.setattr("spectra.services.scene_compiler.fire_scene",
                        fake_fire_scene)

    _run(scene_sequencer.fire_scene_by_id("scene-1", None, 0.7))
    data = fire_history.load_all()
    assert data["scenes"]["scene-1"]["count"] == 1


def test_scene_fire_not_found_does_not_record(monkeypatch):
    from spectra.services import fire_history, scene_sequencer

    monkeypatch.setattr("spectra.services.scene_store.get_by_id",
                        lambda sid: None)
    with pytest.raises(ValueError):
        _run(scene_sequencer.fire_scene_by_id("missing", None, 0.5))
    assert fire_history.load_all()["scenes"] == {}


# ── choke point 2: engine.fire_response_event ─────────────────────────────

def test_response_event_records_when_full_tier(monkeypatch):
    from spectra.services import engine, fire_history
    from spectra.services.room_controls import RoomControlState

    monkeypatch.setattr("spectra.services.room_controls.load_room_controls",
                        lambda: RoomControlState(scene_change_mode="full"))

    async def fake_on_event(event_class, intensity):
        return None

    monkeypatch.setattr(engine.responses, "on_event", fake_on_event)
    monkeypatch.setattr(engine.responses, "_pending_releases", [])

    _run(engine.fire_response_event("charge", 0.6))
    data = fire_history.load_all()
    assert data["responses"]["charge"]["count"] == 1


def test_response_event_gated_tier_does_not_record(monkeypatch):
    from spectra.services import engine, fire_history
    from spectra.services.room_controls import RoomControlState

    monkeypatch.setattr("spectra.services.room_controls.load_room_controls",
                        lambda: RoomControlState(scene_change_mode="analysed"))

    _run(engine.fire_response_event("charge", 0.6))
    assert fire_history.load_all()["responses"] == {}


# ── choke point 3: drift_conductor.apply_set_directly ─────────────────────

def _conductor():
    from spectra.services import color_journey as cj
    from spectra.services.drift_conductor import DriftConductor

    room_box = [cj.RoomColorState()]
    return DriftConductor(
        executor=None, rng=Random(1),
        room_load=lambda: room_box[0],
        room_save=lambda st: room_box.__setitem__(0, st),
        set_position=lambda sid: 90.0)


def test_color_set_apply_records_by_set_id():
    from spectra.services import fire_history

    class FakeCard:
        id = "set-a"
        name = "Set A"
        entries = []

    conductor = _conductor()
    _run(conductor.apply_set_directly(FakeCard()))
    data = fire_history.load_all()
    assert data["color_sets"]["set-a"]["count"] == 1


# ── choke point 4: trigger_engine's own fires (source + action kind) ──────

def test_trigger_fire_records_source_and_action_kind():
    from spectra.models.trigger import FireResponseAction, SpectraTrigger
    from spectra.services import fire_history
    from spectra.services.trigger_engine import TriggerEngine

    async def fake_fire_response(event_class, intensity):
        return None

    trig = SpectraTrigger(timestamp_ms=1000, source="generated",
                          action=FireResponseAction(event_class="drop",
                                                    intensity=0.5))
    te = TriggerEngine(fire_response=fake_fire_response)
    _run(te._fire(trig))
    data = fire_history.load_all()
    assert data["triggers"]["generated:fire_response"]["count"] == 1


def test_trigger_fire_failure_does_not_record():
    from spectra.models.trigger import FireResponseAction, SpectraTrigger
    from spectra.services import fire_history
    from spectra.services.trigger_engine import TriggerEngine

    async def failing_fire_response(event_class, intensity):
        raise RuntimeError("boom")

    trig = SpectraTrigger(timestamp_ms=1000, source="authored",
                          action=FireResponseAction(event_class="drop",
                                                    intensity=0.5))
    te = TriggerEngine(fire_response=failing_fire_response)
    _run(te._fire(trig))
    assert fire_history.load_all()["triggers"] == {}
