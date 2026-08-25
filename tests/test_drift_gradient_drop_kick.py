"""The 2D drift gradient's DROP kick — the two proofs the unit-level kick
math in tests/test_drift_conductor_gradient.py can't make:

  1. REAL PIPELINE: a drop's colour change actually lands in the running
     effect's config on the vendored render pipeline (fx.headless dummy
     device, real tween engine, fake clock) — immediately, not one ~20 s
     leg later.
  2. THE GATED PATH: services/engine.py's fire_response_event — the ONE
     already-mode-gated/preview-gated response choke point — is what calls
     conductor.on_drop_event, only for event_class "drop", and a failure
     there never breaks the drop's own flare.

Owner ask 2026-08-24, order item 2. No live device, no HTTP, no audio.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model, facade, headless

VID = headless.DEFAULT_VIRTUAL_ID


def _run(coro):
    return asyncio.run(coro)


def _categories_fixture(tmp_path) -> None:
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"], "role": None}}))


# ── proof 1: the drop's colour lands on the real render pipeline ─────────────

def test_drop_lands_an_immediate_gradient_write_on_the_real_pipeline(tmp_path):
    from spectra.models.gradient2d import GradientProfile
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services import color_journey as cj
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import (DROP_COLOR_GLIDE_MS,
                                                  DROP_Y_KICK, DriftConductor)
    from spectra.services.fx_executor import FacadeExecutor

    _categories_fixture(tmp_path)
    START = "#ffffff"
    profile = GradientProfile(id="g1", name="Test", top="#ffff00",
                              bottom="#0000ff", x_mode="loop")
    scene = SceneV2(name="Gradient", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric",
        params={})])

    async def main():
        host = await headless.start_headless_host(str(tmp_path / "drop"))
        facade.set_host(host)
        virtual = host.virtuals.get(VID)
        try:
            with headless.fake_clock() as clock:
                config = {"gradient": START}
                effect = headless.attach_effect(host, virtual, "concentric",
                                                config)
                room_box = [cj.RoomColorState(gradient_x=0.0, gradient_y=0.25,
                                              gradient_target_y=0.25)]
                controls = rc.RoomControlState(
                    active_gradient_id="g1", gradient_x_period_s=100.0,
                    gradient_y_slew_s=20.0)
                executor = FacadeExecutor(
                    clock=lambda: clock.now,
                    room_controls_load=lambda: controls)
                conductor = DriftConductor(
                    executor=executor, clock=lambda: clock.now, leg_s=20.0,
                    intensity=lambda: 0.8,
                    drift_profiles=lambda: {}, curve_profiles=lambda: {},
                    room_load=lambda: room_box[0],
                    room_save=lambda st: room_box.__setitem__(0, st),
                    set_position=lambda sid: None, set_cards=lambda: [],
                    gradient_profiles=lambda: {"g1": profile},
                    room_controls=lambda: controls, rng=Random(3))
                conductor.on_scene_fire(scene, [{
                    "virtual_id": VID, "effect_type": "concentric",
                    "config": dict(config), "entry_id": scene.devices[0].id,
                    "color_mode": "set"}])

                rec = await conductor.on_drop_event(0.8)
                assert rec["active"] is True and rec["color"] is not None
                # X jumped one full leg-step (20 s over a 100 s span)...
                assert room_box[0].gradient_x == pytest.approx(0.2, abs=1e-6)
                # ...the TARGET moved up by the drop's energy, Y did not...
                assert room_box[0].gradient_target_y == pytest.approx(
                    0.25 + 0.8 * DROP_Y_KICK, abs=1e-6)
                assert room_box[0].gradient_y == pytest.approx(0.25, abs=1e-6)
                # ...and the colour is on the real effect within the drop's
                # own short glide, nothing like a ~20 s leg away.
                headless.render_frames(
                    virtual, int(DROP_COLOR_GLIDE_MS / 1000 * 60) + 6,
                    clock=clock, dt=1 / 60)
                assert effect._config["gradient"] == rec["color"]
                assert effect._config["gradient"] != START
        finally:
            await host.shutdown()
            facade.set_host(None)

    headless.silence_audio()
    _run(main())


# ── proof 2: it rides the already-gated response choke point ────────────────

class _RecordingConductor:
    def __init__(self, boom: bool = False):
        self.calls: list[float] = []
        self._boom = boom

    async def on_drop_event(self, intensity=None):
        self.calls.append(intensity)
        if self._boom:
            raise RuntimeError("gradient exploded")
        return None


def _patched_engine(monkeypatch, *, mode="full", preview=False, boom=False):
    from spectra.services import engine, preview_pause, room_controls
    from spectra.services import fire_history

    stub = _RecordingConductor(boom=boom)
    fired: list[tuple] = []
    monkeypatch.setattr(engine, "conductor", stub)
    monkeypatch.setattr(engine.responses, "on_event",
                        lambda *a, **k: _noop(fired, a))
    monkeypatch.setattr(engine.responses, "take_release_schedule", lambda: [])
    monkeypatch.setattr(engine.responses, "pending_color_rotate_holds",
                        lambda: [])
    monkeypatch.setattr(preview_pause, "active", lambda: preview)
    monkeypatch.setattr(room_controls, "load_room_controls",
                        lambda: room_controls.RoomControlState(
                            scene_change_mode=mode))
    monkeypatch.setattr(fire_history, "record_fire", lambda *a, **k: None)
    return engine, stub, fired


async def _noop(fired, args):
    fired.append(args)


def test_a_drop_through_the_response_choke_point_kicks_the_gradient(monkeypatch):
    engine, stub, fired = _patched_engine(monkeypatch)
    _run(engine.fire_response_event("drop", 0.7))
    assert fired and stub.calls == [0.7]


def test_a_non_drop_response_never_kicks_the_gradient(monkeypatch):
    engine, stub, fired = _patched_engine(monkeypatch)
    _run(engine.fire_response_event("flare", 0.7))
    _run(engine.fire_response_event("charge", 0.7))
    assert fired and stub.calls == []


def test_a_mode_gated_out_drop_never_reaches_the_gradient(monkeypatch):
    # "transitions" silences flares entirely — the kick must not sneak
    # through on a second, differently-gated route.
    engine, stub, fired = _patched_engine(monkeypatch, mode="transitions")
    _run(engine.fire_response_event("drop", 1.0))
    assert fired == [] and stub.calls == []


def test_a_preview_gated_drop_never_reaches_the_gradient(monkeypatch):
    engine, stub, fired = _patched_engine(monkeypatch, preview=True)
    _run(engine.fire_response_event("drop", 1.0))
    assert fired == [] and stub.calls == []


def test_a_failing_gradient_kick_never_breaks_the_drop(monkeypatch):
    engine, stub, fired = _patched_engine(monkeypatch, boom=True)
    _run(engine.fire_response_event("drop", 0.9))   # must not raise
    assert fired and stub.calls == [0.9]
