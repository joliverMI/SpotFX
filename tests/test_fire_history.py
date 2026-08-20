"""Fire-history proof: persistence round-trip for both surfaces (counts +
bounded show log) in isolation, then each of the four production choke
points (scene fires, response events, colour applies, trigger firings)
actually records through spectra.services.fire_history — both the durable
count AND a show-log timeline entry, cheap by construction (bounded log,
no analytics). See spectra/services/fire_history.py.

Storage isolation for FIRE_HISTORY_FILE/SHOW_LOG_FILE is provided globally
by tests/conftest.py's autouse _isolated_fire_history fixture — no test
here needs its own.
"""
from __future__ import annotations

import asyncio
from random import Random

import pytest

from spectra import config


def _run(coro):
    return asyncio.run(coro)


# ── persistence round-trip: counts ────────────────────────────────────────

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


# ── persistence round-trip: show log ──────────────────────────────────────

def test_show_log_append_and_load_round_trip():
    from spectra.services import fire_history

    fire_history.append_show_log("scenes", "s1", {"scene_name": "Drift"},
                                 uri="spotify:track:a", position_ms=1234,
                                 now_ms=1000)
    log = fire_history.load_show_log()
    assert log == [{
        "wall_ms": 1000, "uri": "spotify:track:a", "position_ms": 1234,
        "bucket": "scenes", "key": "s1", "detail": {"scene_name": "Drift"},
    }]


def test_show_log_filters_by_uri_and_since():
    from spectra.services import fire_history

    fire_history.append_show_log("scenes", "a", uri="track:1", now_ms=100)
    fire_history.append_show_log("scenes", "b", uri="track:2", now_ms=200)
    fire_history.append_show_log("scenes", "c", uri="track:1", now_ms=300)

    assert [e["key"] for e in fire_history.load_show_log(uri="track:1")] == ["a", "c"]
    assert [e["key"] for e in fire_history.load_show_log(since_ms=200)] == ["b", "c"]
    assert [e["key"] for e in
           fire_history.load_show_log(uri="track:1", since_ms=200)] == ["c"]


def test_show_log_bounded_evicts_oldest(monkeypatch):
    from spectra.services import fire_history

    monkeypatch.setattr(fire_history, "SHOW_LOG_MAX_ENTRIES", 3)
    for i in range(5):
        fire_history.append_show_log("scenes", f"s{i}", now_ms=i)
    log = fire_history.load_show_log()
    assert [e["key"] for e in log] == ["s2", "s3", "s4"]


def test_show_log_missing_track_state_defaults_to_none(monkeypatch):
    from spectra.services import fire_history

    monkeypatch.setattr(fire_history, "_current_track_state",
                        lambda: (None, None))
    fire_history.append_show_log("responses", "flare", now_ms=1)
    entry = fire_history.load_show_log()[0]
    assert entry["uri"] is None and entry["position_ms"] is None


def test_show_log_append_never_raises_on_corrupt_file(monkeypatch):
    from spectra.services import fire_history

    config.SHOW_LOG_FILE.write_text("not json")
    fire_history.append_show_log("scenes", "s1", now_ms=1)  # must not raise
    assert fire_history.load_show_log()[0]["key"] == "s1"


def test_record_fire_writes_both_surfaces():
    from spectra.services import fire_history

    fire_history.record_fire("scenes", "s1", {"scene_name": "Drift"},
                             uri="track:1", position_ms=42)
    assert fire_history.load_all()["scenes"]["s1"]["count"] == 1
    log = fire_history.load_show_log()
    assert len(log) == 1
    assert log[0]["key"] == "s1" and log[0]["uri"] == "track:1"


# ── read API: GET /api/fire-history + GET /api/show-log ───────────────────

def test_api_endpoints_expose_both_surfaces():
    from spectra.api.fire_history import get_fire_history, get_show_log
    from spectra.services import fire_history

    fire_history.record_fire("scenes", "s1", uri="track:1", position_ms=1)
    fire_history.record_fire("scenes", "s2", uri="track:2", position_ms=2)

    counts = _run(get_fire_history())
    assert counts["scenes"]["s1"]["count"] == 1

    full_log = _run(get_show_log(uri=None, since=None))
    assert len(full_log) == 2

    sliced = _run(get_show_log(uri="track:1", since=None))
    assert [e["key"] for e in sliced] == ["s1"]


# ── choke point 1: scene_sequencer.fire_scene_by_id ───────────────────────

def test_scene_fire_records_by_scene_id(monkeypatch):
    from spectra.services import fire_history, scene_sequencer

    class FakeScene:
        id = "scene-1"
        name = "Scene One"

    monkeypatch.setattr("spectra.services.scene_store.get_by_id",
                        lambda sid: FakeScene())

    async def fake_fire_scene(scene, *, intensity, color_set, dry_run):
        return {"fired": True}

    monkeypatch.setattr("spectra.services.scene_compiler.fire_scene",
                        fake_fire_scene)

    _run(scene_sequencer.fire_scene_by_id("scene-1", None, 0.7))
    data = fire_history.load_all()
    assert data["scenes"]["scene-1"]["count"] == 1
    entry = fire_history.load_show_log()[0]
    assert entry["bucket"] == "scenes" and entry["key"] == "scene-1"
    assert entry["detail"]["scene_name"] == "Scene One"
    assert entry["detail"]["intensity"] == 0.7


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

    async def fake_on_event(event_class, intensity, gap_ms=None):
        return None

    monkeypatch.setattr(engine.responses, "on_event", fake_on_event)
    monkeypatch.setattr(engine.responses, "_pending_releases", [])

    _run(engine.fire_response_event("charge", 0.6))
    data = fire_history.load_all()
    assert data["responses"]["charge"]["count"] == 1
    entry = fire_history.load_show_log()[0]
    assert entry["bucket"] == "responses" and entry["key"] == "charge"
    assert entry["detail"] == {"event_class": "charge", "intensity": 0.6}


def test_response_event_gated_tier_does_not_record(monkeypatch):
    from spectra.services import engine, fire_history
    from spectra.services.room_controls import RoomControlState

    monkeypatch.setattr("spectra.services.room_controls.load_room_controls",
                        lambda: RoomControlState(scene_change_mode="analysed"))

    _run(engine.fire_response_event("charge", 0.6))
    assert fire_history.load_all()["responses"] == {}


def test_response_event_triggers_only_bridge_path_stays_silent(monkeypatch):
    """via_trigger=False (the default, the bridge's own call site) still
    requires literally scene_change_mode=="full" under "triggers_only" —
    a bridge-relayed event is never "his own trigger" (room_controls.py's
    scene_change_mode docstring, THE fire_response_event DUAL-PATH)."""
    from spectra.services import engine, fire_history
    from spectra.services.room_controls import RoomControlState

    monkeypatch.setattr("spectra.services.room_controls.load_room_controls",
                        lambda: RoomControlState(scene_change_mode="triggers_only"))

    _run(engine.fire_response_event("charge", 0.6))
    assert fire_history.load_all()["responses"] == {}


def test_response_event_triggers_only_trigger_path_records(monkeypatch):
    """via_trigger=True (trigger_engine's own call site) IS allowed at
    "triggers_only" — this is what lets his own authored fire_response
    trigger fire under this tier while the bridge-relayed duplicate
    (the double-fire proven in data/charge-lull-drop-timing-blends-and-a-
    sus-7fm2/report.md §1) stays silent."""
    from spectra.services import engine, fire_history
    from spectra.services.room_controls import RoomControlState

    monkeypatch.setattr("spectra.services.room_controls.load_room_controls",
                        lambda: RoomControlState(scene_change_mode="triggers_only"))

    async def fake_on_event(event_class, intensity, gap_ms=None):
        return None

    monkeypatch.setattr(engine.responses, "on_event", fake_on_event)
    monkeypatch.setattr(engine.responses, "_pending_releases", [])

    _run(engine.fire_response_event("charge", 0.6, via_trigger=True))
    data = fire_history.load_all()
    assert data["responses"]["charge"]["count"] == 1


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
    entry = fire_history.load_show_log()[0]
    assert entry["bucket"] == "color_sets" and entry["key"] == "set-a"
    assert entry["detail"]["set_name"] == "Set A"


# ── choke point 4: trigger_engine's own fires (source + action kind) ──────

def test_trigger_fire_records_source_and_action_kind():
    from spectra.models.trigger import FireResponseAction, SpectraTrigger
    from spectra.services import fire_history
    from spectra.services.trigger_engine import TriggerEngine

    async def fake_fire_response(event_class, intensity, gap_ms=None):
        return None

    trig = SpectraTrigger(timestamp_ms=1000, source="generated",
                          action=FireResponseAction(event_class="drop",
                                                    intensity=0.5))
    te = TriggerEngine(fire_response=fake_fire_response)
    te._uri = "spotify:track:xyz"
    te._last_position_ms = 5000
    _run(te._fire(trig))
    data = fire_history.load_all()
    assert data["triggers"]["generated:fire_response"]["count"] == 1
    entry = fire_history.load_show_log()[0]
    assert entry["bucket"] == "triggers"
    assert entry["key"] == "generated:fire_response"
    assert entry["uri"] == "spotify:track:xyz"
    assert entry["position_ms"] == 5000
    assert entry["detail"]["trigger_id"] == trig.id


def test_trigger_fire_failure_does_not_record():
    from spectra.models.trigger import FireResponseAction, SpectraTrigger
    from spectra.services import fire_history
    from spectra.services.trigger_engine import TriggerEngine

    async def failing_fire_response(event_class, intensity, gap_ms=None):
        raise RuntimeError("boom")

    trig = SpectraTrigger(timestamp_ms=1000, source="authored",
                          action=FireResponseAction(event_class="drop",
                                                    intensity=0.5))
    te = TriggerEngine(fire_response=failing_fire_response)
    _run(te._fire(trig))
    assert fire_history.load_all()["triggers"] == {}
