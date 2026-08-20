"""The two-dimensional drift gradient's leg mechanics inside DriftConductor
(owner ask 2026-08-20, spectra/services/drift_conductor.py "gradient
drift" docstring section). Uses RecordingExecutor (models/records, never
writes) — no live device needed. Every constructor injectable is passed
explicitly so nothing here touches real storage."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra.models.gradient2d import GradientProfile
from spectra.services import color_journey as cj
from spectra.services.drift_conductor import DriftConductor
from spectra.services.fx_executor import RecordingExecutor
from spectra.services.room_controls import RoomControlState


def _run(coro):
    return asyncio.run(coro)


class _Clock:
    def __init__(self):
        self.now = 0.0


def _harness(*, active_gradient_id, intensity=0.5, x_period_s=100.0,
            y_slew_s=20.0, x_mode="loop", room=None):
    clock = _Clock()
    room_box = [room or cj.RoomColorState()]
    profile = GradientProfile(id="g1", name="Test", top="#ffff00",
                              bottom="#0000ff", x_mode=x_mode)
    profiles = {"g1": profile}
    room_controls = RoomControlState(
        active_gradient_id=active_gradient_id,
        gradient_x_period_s=x_period_s, gradient_y_slew_s=y_slew_s)
    executor = RecordingExecutor(
        clock=lambda: clock.now,
        room_controls_load=lambda: room_controls)
    conductor = DriftConductor(
        executor=executor, clock=lambda: clock.now, leg_s=20.0,
        intensity=lambda: intensity,
        drift_profiles=lambda: {}, curve_profiles=lambda: {},
        room_load=lambda: room_box[0],
        room_save=lambda st: room_box.__setitem__(0, st),
        set_position=lambda sid: None,
        set_cards=lambda: [],
        sequencer_config=lambda: __import__(
            "spectra.models.sequencer", fromlist=["SequencerConfig"]).SequencerConfig(),
        gradient_profiles=lambda: profiles,
        room_controls=lambda: room_controls,
        rng=Random(1))
    return clock, conductor, executor, room_box


def _fire_set_mode_scene(conductor):
    """A minimal on_scene_fire so a set-mode virtual with a gradient param
    exists for the leg to write to."""
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    scene = SceneV2(name="s", devices=[SceneDeviceConfig(
        target_kind="virtual", target="v1", effect_type="concentric")])
    conductor.on_scene_fire(scene, [{
        "virtual_id": "v1", "effect_type": "concentric",
        "config": {"gradient": "#ffffff"}, "entry_id": scene.devices[0].id,
        "color_mode": "set"}])
    return scene


# ── off by default: journey runs, gradient inert ────────────────────────────

def test_inactive_gradient_leaves_journey_running():
    clock, conductor, executor, room_box = _harness(active_gradient_id=None)
    _fire_set_mode_scene(conductor)
    record = _run(conductor.tick())
    assert record["gradient"]["active"] is False
    assert record["journey"].get("held_for") != "gradient_drift"


# ── active gradient holds the journey and advances x/y ──────────────────────

def test_active_gradient_holds_journey():
    clock, conductor, executor, room_box = _harness(active_gradient_id="g1")
    _fire_set_mode_scene(conductor)
    record = _run(conductor.tick())
    assert record["journey"]["held_for"] == "gradient_drift"
    assert record["gradient"]["active"] is True


def test_x_advances_by_leg_over_period():
    # leg_s=20, x_period_s=100 -> delta 0.2 per leg
    clock, conductor, executor, room_box = _harness(
        active_gradient_id="g1", x_period_s=100.0)
    _fire_set_mode_scene(conductor)
    _run(conductor.tick())
    assert room_box[0].gradient_x == pytest.approx(0.2, abs=1e-6)
    _run(conductor.tick())
    assert room_box[0].gradient_x == pytest.approx(0.4, abs=1e-6)


def test_x_loops_past_one():
    clock, conductor, executor, room_box = _harness(
        active_gradient_id="g1", x_period_s=40.0, x_mode="loop")
    _fire_set_mode_scene(conductor)
    for _ in range(3):   # 3 legs * 0.5 = 1.5 -> wraps to 0.5
        _run(conductor.tick())
    assert room_box[0].gradient_x == pytest.approx(0.5, abs=1e-6)


def test_x_bounces_past_one():
    clock, conductor, executor, room_box = _harness(
        active_gradient_id="g1", x_period_s=40.0, x_mode="bounce")
    _fire_set_mode_scene(conductor)
    for _ in range(3):   # 0.5, 1.0(reflect), 0.5
        _run(conductor.tick())
    assert 0.0 <= room_box[0].gradient_x <= 1.0


def test_y_drifts_toward_target_not_snaps():
    room = cj.RoomColorState(gradient_y=0.0, gradient_target_y=1.0)
    clock, conductor, executor, room_box = _harness(
        active_gradient_id="g1", y_slew_s=100.0, room=room)
    _fire_set_mode_scene(conductor)
    _run(conductor.tick())   # leg_s=20, slew=100 -> step 0.2
    assert 0.0 < room_box[0].gradient_y < 1.0
    assert room_box[0].gradient_y == pytest.approx(0.2, abs=1e-6)


def test_color_lands_on_set_mode_virtual():
    clock, conductor, executor, room_box = _harness(active_gradient_id="g1")
    _fire_set_mode_scene(conductor)
    _run(conductor.tick())
    assert executor.current["v1"]["gradient"] is not None
    assert executor.current["v1"]["gradient"] != "#ffffff"   # overwritten by the gradient sample


# ── on_intensity_event: retarget without snapping ────────────────────────────

def test_on_intensity_event_sets_target_not_current_y():
    clock, conductor, executor, room_box = _harness(
        active_gradient_id="g1", intensity=0.75)
    conductor.on_intensity_event()
    assert room_box[0].gradient_target_y == pytest.approx(0.75, abs=1e-6)
    assert room_box[0].gradient_y == 0.5   # unchanged — still drifts toward it


def test_on_intensity_event_clamps_to_unit_range():
    clock, conductor, executor, room_box = _harness(active_gradient_id="g1")
    room_box[0] = room_box[0].model_copy(update={"gradient_target_y": 0.5})
    # inject an out-of-range intensity via the injectable
    conductor._intensity = lambda: 1.5
    conductor.on_intensity_event()
    assert room_box[0].gradient_target_y == 1.0


# ── missing profile: holds, never crashes ────────────────────────────────────

def test_missing_gradient_profile_holds_gracefully():
    clock, conductor, executor, room_box = _harness(active_gradient_id="does-not-exist")
    _fire_set_mode_scene(conductor)
    record = _run(conductor.tick())
    assert record["gradient"]["active"] is False
    assert record["gradient"]["missing"] == "does-not-exist"
