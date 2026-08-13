"""SPECTRA S2 evolution engine — the OFFLINE INTEGRATION PROOF (report
§2.8): the same conductor + response engine production wires (dark) run
here against the FacadeExecutor on the vendored render pipeline — real
effects, real tween engine, dummy device, fake clock, audio silenced.

The proofs:
  1. drift trajectories — a creep leg and a follow slew interpolate frame
     by frame in the real effect config and land exactly on target,
  2. a surge jump lands on the next render frame and CARRIES (creep
     resumes from the surged point, reflected at its bounds),
  3. the pulse gain envelope spikes and returns to the baseline,
  4. the flare colour jump is a JUMP (target palette after one frame, no
     crossfade), the room wheel moves to the pick, and the journey RESUMES
     from the new point on the next conductor leg,
  5. the seven Mid Group scenes animate: their seeded bindings resolve and
     land in the real effects, and each scene's top flare band executes
     its patch on the rendering effect.

No LedFX service, no HTTP, no audio hardware (fx.headless.silence_audio).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from random import Random

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import facade, headless
from fx import device_model

REPO_ROOT = Path(__file__).resolve().parent.parent
VID = headless.DEFAULT_VIRTUAL_ID


def _run(coro):
    return asyncio.run(coro)


def _categories_fixture(tmp_path) -> None:
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"], "role": None}}))


async def _host(tmp_path, sub: str):
    host = await headless.start_headless_host(str(tmp_path / sub))
    facade.set_host(host)
    return host, host.virtuals.get(VID)


def _engine(clock, *, intensity=1.0, room=None, set_positions=None):
    """Conductor + response engine on the FacadeExecutor with an in-memory
    room — the exact production wiring with the executor swapped, which is
    the whole S3 delta."""
    from spectra.models.sequencer import SequencerConfig, SelectorEntry
    from spectra.services import color_journey as cj
    from spectra.services.color_sets import ColorSetCard
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine

    room_box = [room or cj.RoomColorState()]
    positions = set_positions or {}
    cards = [ColorSetCard(id=sid, name=sid, entries=[]) for sid in positions]
    seq_config = SequencerConfig(color_set_entries={
        sid: SelectorEntry() for sid in positions if sid != "current"})
    executor = FacadeExecutor(clock=lambda: clock.now)
    conductor = DriftConductor(
        executor=executor, clock=lambda: clock.now, leg_s=20.0,
        intensity=lambda: intensity,
        drift_profiles=lambda: {}, curve_profiles=lambda: {},
        room_load=lambda: room_box[0],
        room_save=lambda st: room_box.__setitem__(0, st),
        set_position=lambda sid: positions.get(sid),
        set_cards=lambda: cards,
        sequencer_config=lambda: seq_config,
        rng=Random(11))
    responder = ResponseEngine(
        conductor=conductor, executor=executor, rng=Random(7),
        clock=lambda: clock.now,
        sequencer_config=lambda: seq_config,
        curve_profiles=lambda: {},
        eligible_sets=lambda sc: dict(positions),
        room_load=lambda: room_box[0],
        room_save=lambda st: room_box.__setitem__(0, st))
    return executor, conductor, responder, room_box


def _fire(conductor, scene, config):
    """Hand the conductor a fire's writes for the headless virtual."""
    dev = scene.devices[0]
    conductor.on_scene_fire(scene, [{
        "virtual_id": VID, "effect_type": dev.effect_type,
        "config": dict(config), "entry_id": dev.id,
        "color_mode": dev.color.mode}])


# ── proof 1: drift trajectories interpolate and land ─────────────────────────

def test_drift_trajectories_on_the_harness(tmp_path):
    from spectra.models.scene import (CurveMapPoint, DriftRef, DriftSpec,
                                      SceneDeviceConfig, SceneV2)
    _categories_fixture(tmp_path)
    scene = SceneV2(name="Drifting", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric",
        params={"gradient_scale": 1.0, "power_multiplier": 0.2},
        drift={
            "gradient_scale": DriftRef(inline=DriftSpec(
                kind="creep", rate_per_min=1.5, lo=0.5, hi=2.0)),
            "power_multiplier": DriftRef(inline=DriftSpec(
                kind="follow", slew_s=5.0,
                inline_points=[CurveMapPoint(x=0.0, y=0.1),
                               CurveMapPoint(x=1.0, y=0.9)])),
        }, brightness=0.65)])

    async def main():
        host, virtual = await _host(tmp_path, "drift")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient_scale": 1.0, "power_multiplier": 0.2,
                          "brightness": 0.65}
                effect = headless.attach_effect(host, virtual, "concentric",
                                                config)
                _, conductor, _, _ = _engine(clock)
                _fire(conductor, scene, config)
                leg = await conductor.tick()
                assert {l["kind"] for l in leg["legs"]} == {"creep", "follow"}

                # One second in: both params are mid-glide, between start
                # and target — interpolation, not snapping.
                frames = headless.render_frames(virtual, 60, clock=clock,
                                                dt=1 / 60)
                assert 1.0 < effect._config["gradient_scale"] < 1.5
                assert 0.2 < effect._config["power_multiplier"] < 0.9
                assert any(float(np.abs(f).sum()) > 0 for f in frames)

                # Past the 5 s slew: the follow has landed; the 20 s creep
                # leg is still travelling.
                headless.render_frames(virtual, 300, clock=clock, dt=1 / 60)
                assert effect._config["power_multiplier"] == pytest.approx(0.9)
                assert effect._config["gradient_scale"] < 1.5

                # Past the leg: the creep lands exactly on its target.
                headless.render_frames(virtual, 900, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.5)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── proof 2: a surge jump lands next frame and carries into the drift ────────

def test_surge_jump_lands_next_frame_and_carries(tmp_path):
    from spectra.models.scene import (DriftRef, DriftSpec, FlareBand,
                                      ResponseSpec, SceneDeviceConfig, SceneV2)
    _categories_fixture(tmp_path)
    scene = SceneV2(name="Surging", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric",
        params={"gradient_scale": 1.0},
        drift={"gradient_scale": DriftRef(inline=DriftSpec(
            kind="creep", rate_per_min=1.5, lo=0.5, hi=2.0))})],
        responses={"drop": ResponseSpec(bands=[
            FlareBand(intensity_min=0.7, intensity_max=1.0,
                      param_patch={"gradient_scale": 1.8})],
            reroll_dice=False)})

    async def main():
        host, virtual = await _host(tmp_path, "surge")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient_scale": 1.0}
                effect = headless.attach_effect(host, virtual, "concentric",
                                                config)
                executor, conductor, responder, _ = _engine(clock)
                _fire(conductor, scene, config)

                record = await responder.on_event("drop", 0.9)
                assert record["result"] == "applied"
                # The 1 ms tween lands on the NEXT render frame — the jump.
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.8)

                # CARRY: the wander resumes from the surged point and the
                # next leg reflects at the hi bound (1.8 + 0.5 → 1.7 back).
                mech = conductor.mechanisms[0]
                assert mech.position == pytest.approx(1.8)
                await conductor.tick()
                leg_write = [w for w in executor.writes
                             if w["kind"] == "glide"][-1]
                assert leg_write["params"]["gradient_scale"] == pytest.approx(1.7)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── proof 3: the pulse envelope spikes and returns ───────────────────────────

def test_pulse_envelope_spikes_and_returns(tmp_path):
    from spectra.models.scene import (FlareBand, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    _categories_fixture(tmp_path)
    scene = SceneV2(name="Pulsing", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric",
        params={}, brightness=0.4)],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0, curve="pulse",
                      gain=2.0)], reroll_dice=False)})

    async def main():
        host, virtual = await _host(tmp_path, "pulse")
        try:
            with headless.fake_clock() as clock:
                config = {"brightness": 0.4}
                effect = headless.attach_effect(host, virtual, "concentric",
                                                config)
                _, conductor, responder, _ = _engine(clock)
                _fire(conductor, scene, config)

                await responder.on_event("flare", 0.5)
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["brightness"] == pytest.approx(0.8)

                # The spike landed; release glides back over 1.5 s.
                assert await responder.flush_releases() == 1
                headless.render_frames(virtual, 45, clock=clock, dt=1 / 60)
                assert 0.4 < effect._config["brightness"] < 0.8
                headless.render_frames(virtual, 60, clock=clock, dt=1 / 60)
                assert effect._config["brightness"] == pytest.approx(0.4)
                # Momentary: the carried baseline never moved.
                assert conductor.virtuals[VID].brightness_baseline == 0.4
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── proof 4: colour jump is a JUMP; the journey resumes from the pick ────────

def test_flare_color_jump_and_journey_resume(tmp_path):
    from spectra.models.scene import (FlareBand, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    from spectra.services import color_journey as cj
    from spectra.services import color_rotate
    from spectra.services.color_sets import (ColorSetCard, ColorSetEntry,
                                             SetScope)
    _categories_fixture(tmp_path)
    BLUE = "linear-gradient(90deg, #0000ff 0%, #8000ff 100%)"
    scene = SceneV2(name="Jumping", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric",
        params={})],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0)],
            reroll_dice=False, color_set_jump=True)})
    red_card = ColorSetCard(id="set-red", name="Reds", entries=[
        ColorSetEntry(scope=SetScope(categories=["Headless"]),
                      color_kind="solid", color_value="#ff0000")])

    async def main():
        host, virtual = await _host(tmp_path, "jump")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient": BLUE}
                effect = headless.attach_effect(host, virtual, "concentric",
                                                config)
                executor, conductor, responder, room_box = _engine(
                    clock,
                    room=cj.RoomColorState(wheel_position_deg=220.0,
                                           active_set_id="set-blue"),
                    set_positions={"set-red": 10.0, "set-blue": 220.0})
                responder._set_card = lambda sid: (
                    red_card if sid == "set-red" else None)
                _fire(conductor, scene, config)

                record = await responder.on_event("flare", 0.6)
                assert record["color_jump"]["result"] == "jumped"
                assert record["color_jump"]["picked_id"] == "set-red"
                # A JUMP, not a blend: the palette is the pick after ONE
                # frame (a crossfade would still be travelling at 16 ms).
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["gradient"] == "#ff0000"
                # The room's wheel moved to the pick...
                assert room_box[0].wheel_position_deg == pytest.approx(10.0)
                assert room_box[0].active_set_id == "set-red"

                # ...the teleport cleared the journey's bearing...
                assert room_box[0].destination is None
                # ...and the journey RESUMES from the new point: the next
                # leg picks a fresh destination (only Blues is eligible —
                # Reds is now the active set), travels toward it at the
                # pace that destination fixes from its distance, and
                # rotates the jumped palette with the wheel.
                await conductor.tick()
                dest = room_box[0].destination
                assert dest is not None and dest.set_id == "set-blue"
                travel = abs(cj.signed_travel(10.0, 220.0))          # 150°
                pace = cj.destination_pace(30.0, travel)             # 50°/min
                delta = -pace * (20.0 / 60.0)   # shortest arc goes down
                assert dest.pace_deg_per_min == pytest.approx(pace)
                assert room_box[0].wheel_position_deg == pytest.approx(
                    (10.0 + delta) % 360.0)
                rotation = [w for w in executor.writes
                            if w["kind"] == "glide"
                            and "gradient" in w["params"]][-1]
                assert rotation["params"]["gradient"] == \
                    color_rotate.rotate_color_value("#ff0000", delta)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── proof 5: the seven Mid Group scenes animate ──────────────────────────────

MID_GROUP_PRIMARY = {
    "Black Hole V2": "blackhole",
    "Orbits V2": "orbits",
    "Mid Star V2": "radial",
    "Fireworks V2": "fireworks",
    "Squiggles V2": "squiggles",
    "Dancers V2": "dancer",
    "Eye V2": "eye",
}
# Effects that draw under silent audio (the others spawn on beats — black
# frames without a feed is their correct behavior, not a failure).
DRAWS_IN_SILENCE = {"orbits", "eye"}


def test_mid_group_scenes_animate_on_the_harness(tmp_path):
    from spectra.models.scene import SceneV2
    from spectra.services import scene_compiler
    from spectra.services.binding_resolver import FireContext
    _categories_fixture(tmp_path)
    live = {v["name"]: SceneV2(**v) for v in json.loads(
        (REPO_ROOT / "storage" / "spectra" / "scenes.json").read_text()
    ).values()}

    async def main():
        host, virtual = await _host(tmp_path, "midgroup")
        try:
            for name, effect_type in MID_GROUP_PRIMARY.items():
                scene = live[name]
                resolved = scene_compiler.resolve_scene(
                    scene, FireContext(0.9, rng=Random(5)))
                dev = next(d for d in resolved.devices
                           if d.effect_type == effect_type)
                orig = next(d for d in scene.devices
                            if d.effect_type == effect_type)
                with headless.fake_clock() as clock:
                    effect = headless.attach_effect(host, virtual,
                                                    effect_type,
                                                    dict(dev.params))
                    # The seeded bindings resolved and landed in the real
                    # effect (schema-validated on attach).
                    for pname, value in dev.params.items():
                        got = effect._config[pname]
                        if isinstance(value, (int, float)) \
                                and not isinstance(value, bool):
                            assert float(got) == pytest.approx(
                                float(value), abs=1e-6), (name, pname)
                        else:
                            assert got == value, (name, pname)

                    executor, conductor, responder, _ = _engine(clock)
                    conductor.on_scene_fire(scene, [{
                        "virtual_id": VID, "effect_type": effect_type,
                        "config": dict(dev.params), "entry_id": orig.id,
                        "color_mode": orig.color.mode}])
                    # The top flare band executes its patch on the
                    # rendering effect — the S2 half of the migration.
                    top = max(scene.responses["flare"].bands,
                              key=lambda b: b.intensity_max)
                    record = await responder.on_event("flare", 0.97)
                    assert record["result"] == "applied", name
                    frames = headless.render_frames(virtual, 15,
                                                    clock=clock, dt=1 / 60)
                    assert len(frames) == 15, name
                    int_keys = effect._integer_param_keys()
                    for key, value in top.param_patch.items():
                        if device_model.get_param_meta(effect_type,
                                                       key) is None:
                            continue
                        expected = (int(round(value)) if key in int_keys
                                    else value)
                        assert float(effect._config[key]) == pytest.approx(
                            float(expected)), (name, key)
                    if effect_type in DRAWS_IN_SILENCE:
                        assert any(float(np.abs(f).sum()) > 0
                                   for f in frames), name
                virtual._active_effect = None
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── offline guarantee ────────────────────────────────────────────────────────

def test_no_audio_hardware_was_touched():
    from fx.compat_sounddevice import _LazySounddevice

    assert _LazySounddevice._module is None
