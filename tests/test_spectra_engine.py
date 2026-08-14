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
     its patch on the rendering effect,
  7. intensity-conditional effect selection resolves per fire: one entry
     attaches melt below the boundary and power at/above it on the real
     pipeline, with the dry-run preview's writes byte-identical to the
     live pair — the preview IS the selection's honest window,
  6. charge/lull/drop drive the REAL vendored phase machinery end to end:
     the effect's own state machine enters the phase on the arm write, the
     phase_progress ramp interpolates across render frames, the drop's
     choreography SELF-RESETS to "none" (the vendored release grammar),
     and a track-change release frees an armed lull.

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


def _absolute_params(kind) -> dict:
    """A FlareKind's params as plain floats — every kind these fixtures
    build or migrate is absolute-mode-only (ParamTarget's legacy-compatible
    default)."""
    return {name: t.value for name, t in kind.params.items()
            if t.mode == "absolute"}


def _categories_fixture(tmp_path) -> None:
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"], "role": None}}))


async def _host(tmp_path, sub: str):
    host = await headless.start_headless_host(str(tmp_path / sub))
    facade.set_host(host)
    return host, host.virtuals.get(VID)


def _engine(clock, *, intensity=1.0, room=None, set_positions=None,
           brightness_multiplier=1.0):
    """Conductor + response engine on the FacadeExecutor with an in-memory
    room — the exact production wiring with the executor swapped, which is
    the whole S3 delta."""
    from spectra.models.sequencer import SequencerConfig, SelectorEntry
    from spectra.services import color_journey as cj
    from spectra.services import room_controls as rc
    from spectra.services.color_sets import ColorSetCard
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine

    room_box = [room or cj.RoomColorState()]
    positions = set_positions or {}
    cards = [ColorSetCard(id=sid, name=sid, entries=[]) for sid in positions]
    seq_config = SequencerConfig(color_set_entries={
        sid: SelectorEntry() for sid in positions if sid != "current"})
    executor = FacadeExecutor(
        clock=lambda: clock.now,
        room_controls_load=lambda: rc.RoomControlState(
            brightness_multiplier=brightness_multiplier))
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


# ── proof 2b: UPDATE glides (never jumps), carries, and bypasses band ────────
# ── gating entirely (data/spectra-trigger-migration-scoping RULING.md) ───────

def test_update_glides_and_carries_bypassing_bands(tmp_path):
    """The owner's UPDATE definition, proved frame-by-frame: "a major change
    within the scene, bigger than a flare, overriding the drift, going
    somewhere new on a ramp-in transition." This scene has NO response
    bands at all (proving update doesn't need band/intensity-gate setup)
    and update_kind names a type="permanent" kind directly."""
    from spectra.models.scene import (DriftRef, DriftSpec, FlareKind,
                                      ParamTarget, SceneDeviceConfig, SceneV2)
    from spectra.services.scene_response import update_ramp_ms
    _categories_fixture(tmp_path)
    scene = SceneV2(
        name="Updating",
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="concentric",
            params={"gradient_scale": 1.0},
            drift={"gradient_scale": DriftRef(inline=DriftSpec(
                kind="creep", rate_per_min=1.5, lo=0.5, hi=2.0))})],
        flare_kinds=[FlareKind(
            name="Big Shift", type="permanent",
            params={"gradient_scale": ParamTarget(mode="absolute", value=1.8)})],
        update_kind="Big Shift")

    async def main():
        host, virtual = await _host(tmp_path, "update")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient_scale": 1.0}
                effect = headless.attach_effect(host, virtual, "concentric",
                                                config)
                executor, conductor, responder, _ = _engine(clock)
                _fire(conductor, scene, config)

                # intensity 1.0 lands the declared target VERBATIM (same
                # ×1-scale convention as on_event's band-driven kinds) —
                # the clean case to prove the glide lands where authored.
                record = await responder.on_update(1.0)
                assert record["result"] == "updated"
                expected_ramp = update_ramp_ms(1.0)
                assert record["ramp_ms"] == expected_ramp

                glide_write = [w for w in executor.writes if w["kind"] == "glide"][-1]
                assert glide_write["duration_ms"] == expected_ramp
                assert glide_write["params"]["gradient_scale"] == pytest.approx(1.8)
                # never an instant jump — the ramp-in is the whole point
                assert not any(w["kind"] == "jump" for w in executor.writes)

                # Nothing has landed on the render pipeline until frames
                # advance past the ramp — a real glide, not a same-frame snap.
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] < 1.8
                headless.render_frames(virtual, int(expected_ramp / 1000 * 60) + 5,
                                       clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.8)

                # CARRY: the creep resumes its wander from the landed point,
                # not from 1.0 — same proof shape as the band-driven surge.
                mech = conductor.mechanisms[0]
                assert mech.position == pytest.approx(1.8)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_update_is_a_silent_noop_without_an_authored_update_kind(tmp_path):
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    _categories_fixture(tmp_path)
    scene = SceneV2(name="No Update Authored", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric",
        params={"gradient_scale": 1.0})])  # no flare_kinds, no update_kind

    async def main():
        host, virtual = await _host(tmp_path, "no-update")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient_scale": 1.0}
                headless.attach_effect(host, virtual, "concentric", config)
                executor, conductor, responder, _ = _engine(clock)
                _fire(conductor, scene, config)

                record = await responder.on_update(0.9)
                assert record["result"] == "no_update_kind"
                assert list(executor.writes) == []
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_update_is_a_silent_noop_with_no_active_scene(tmp_path):
    async def main():
        host, _ = await _host(tmp_path, "no-scene")
        try:
            with headless.fake_clock() as clock:
                executor, _conductor, responder, _ = _engine(clock)
                record = await responder.on_update(0.5)
                assert record["result"] == "no_active_scene"
                assert list(executor.writes) == []
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
                # The RAMP-IN (owner refinement of jump-not-blend): at
                # intensity 0.6 the colours ease in over 1090 ms — the
                # tween holds the old palette string mid-blend (hue-arc at
                # LUT level, no crossfade re-creation) and finalizes on
                # the pick when the ramp lands.
                assert record["color_jump"]["ramp_ms"] == 1090
                headless.render_frames(virtual, 30, clock=clock, dt=1 / 60)
                assert effect._config["gradient"] == BLUE      # mid-ramp
                headless.render_frames(virtual, 40, clock=clock, dt=1 / 60)
                assert effect._config["gradient"] == "#ff0000"  # landed
                # The room's wheel moved to the pick AT SELECTION...
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


# ── proof 6: charge/lull/drop drive the REAL vendored phase machinery ────────

def test_charge_lull_drop_drive_the_real_phase_machinery(tmp_path):
    """The build/suspend/release grammar is the vendored effects' own code
    (docs/SPECTRA_RESPONSES.md); this proves the response engine's drive
    reaches it frame-accurately on the headless harness: blackhole's state
    machine enters the charge, the ramp interpolates, the drop bursts and
    self-resets, and the lifecycle release frees an armed lull."""
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    _categories_fixture(tmp_path)
    scene = SceneV2(name="Phased", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="blackhole",
        params={})])

    async def main():
        host, virtual = await _host(tmp_path, "phase")
        try:
            with headless.fake_clock() as clock:
                config: dict = {}
                effect = headless.attach_effect(host, virtual, "blackhole",
                                                config)
                executor, conductor, responder, room_box = _engine(clock)
                _fire(conductor, scene, config)

                # Charge: arm + 4000 ms build ramp. One frame consumes the
                # edge — the REAL state machine enters the phase.
                record = await responder.on_event("charge", 0.8)
                assert record["phase"] == {"targets": [VID], "ramp_ms": 4000}
                assert record["result"] == "phase_only"
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._phase == "charge"
                # The ramp interpolates across render frames (the vendored
                # tween engine), still mid-build after 1 s and 2 s.
                headless.render_frames(virtual, 60, clock=clock, dt=1 / 60)
                p1 = float(effect._config["phase_progress"])
                headless.render_frames(virtual, 60, clock=clock, dt=1 / 60)
                p2 = float(effect._config["phase_progress"])
                assert 0.0 < p1 < p2 < 1.0
                assert effect._phase == "charge"

                # Drop: the 400 ms snap. The vendored choreography pinches,
                # bursts, and SELF-RESETS phase to "none" — the release is
                # the effect's own grammar, not the engine's.
                record = await responder.on_event("drop", 0.9)
                assert record["phase"]["ramp_ms"] == 400
                headless.render_frames(virtual, 90, clock=clock, dt=1 / 60)
                assert effect._phase == "none"
                assert effect._config["phase"] == "none"
                assert float(effect._config["phase_progress"]) == 0.0

                # Lull arms; a track change releases it deliberately (the
                # lifecycle guard) — no waiting on the orphan watchdog.
                await responder.on_event("lull", 0.5)
                headless.render_frames(virtual, 30, clock=clock, dt=1 / 60)
                assert effect._phase == "lull"
                assert await responder.release_phases() == 1
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._phase == "none"
                assert await responder.release_phases() == 0
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_phase_blend_overrides_charge_lull_ramp(tmp_path):
    """OVERRIDE BLEND equivalent (spectra-kept-equivalents): a scene's
    phase_blend.charge_ramp_ms/lull_ramp_ms overrides the fixed class
    default; drop is never overridden (the snap stays fixed); a scene
    with no override keeps today's PHASE_RAMP_MS behaviour unchanged."""
    from spectra.models.scene import PhaseBlend, SceneDeviceConfig, SceneV2
    _categories_fixture(tmp_path)
    scene = SceneV2(name="Blended", phase_blend=PhaseBlend(
        charge_ramp_ms=9000, lull_ramp_ms=1000),
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="blackhole",
            params={})])

    async def main():
        host, virtual = await _host(tmp_path, "phase-blend")
        try:
            with headless.fake_clock() as clock:
                config: dict = {}
                headless.attach_effect(host, virtual, "blackhole", config)
                executor, conductor, responder, room_box = _engine(clock)
                _fire(conductor, scene, config)

                charge = await responder.on_event("charge", 0.8)
                assert charge["phase"]["ramp_ms"] == 9000
                lull = await responder.on_event("lull", 0.5)
                assert lull["phase"]["ramp_ms"] == 1000
                drop = await responder.on_event("drop", 0.9)
                assert drop["phase"]["ramp_ms"] == 400
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── proof 5: the seven Mid Group scenes animate ──────────────────────────────

MID_GROUP_PRIMARY = {
    "Black Hole V2": "blackhole",
    "Orbits V2": "orbits",
    "STAR": "radial",   # the owner's rename of Mid Star V2
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
                    # The top flare band executes its patch — now the
                    # auto-named PERMANENT kind the legacy param_patch
                    # loads as — on the rendering effect.
                    top = max(scene.responses["flare"].bands,
                              key=lambda b: b.intensity_max)
                    declared = {k.name: k for k in scene.flare_kinds}
                    top_patch: dict[str, float] = {}
                    for kname in top.kinds:
                        if declared[kname].type == "permanent":
                            top_patch.update(_absolute_params(declared[kname]))
                    assert top_patch, name   # the migration named the patch
                    record = await responder.on_event("flare", 0.97)
                    assert record["result"] == "applied", name
                    frames = headless.render_frames(virtual, 15,
                                                    clock=clock, dt=1 / 60)
                    assert len(frames) == 15, name
                    int_keys = effect._integer_param_keys()
                    for key, value in top_patch.items():
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


# ── proof 7: intensity-conditional effect selection on the harness ───────────

def test_effect_selection_on_the_harness(tmp_path, monkeypatch):
    """decision: star-fold-entry-growth — one entry, two effects: melt below
    ⚡ 0.7, power (bass_decay_rate 0.6) at/above — the STAR strips shape.
    fire_scene is BOTH the preview and the live entry, so the dry-run at a
    chosen intensity is the selection's honest window: its writes are the
    exact resolve+compile pair a live fire hands the seam, and they attach
    and render on the real pipeline."""
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services import scene_compiler
    from spectra.services.binding_resolver import FireContext
    _categories_fixture(tmp_path)
    monkeypatch.setattr(scene_compiler, "room_active_set", lambda: None)
    scene = SceneV2(name="Star strips", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="melt",
        params={},
        effect_steps=[{"threshold": 0.7, "effect_type": "power",
                       "params": {"bass_decay_rate": 0.6}}])])

    async def main():
        host, virtual = await _host(tmp_path, "select")
        try:
            for intensity, expected in ((0.3, "melt"), (0.69, "melt"),
                                        (0.7, "power"), (0.9, "power")):
                preview = await scene_compiler.fire_scene(
                    scene, intensity=intensity, rng=Random(3))
                assert preview["dry_run"] is True
                write = preview["writes"][0]
                assert write["effect_type"] == expected, intensity
                assert any(r["param"] == "effect" and r["value"] == expected
                           for r in preview["resolved_bindings"])
                # Preview parity: an independent resolve+compile at the same
                # intensity/seed reproduces the preview's writes exactly.
                resolved = scene_compiler.resolve_scene(
                    scene, FireContext(intensity, rng=Random(3)))
                assert scene_compiler.compile_scene(resolved) == [dict(write)]
                with headless.fake_clock() as clock:
                    effect = headless.attach_effect(
                        host, virtual, write["effect_type"],
                        dict(write["config"]))
                    frames = headless.render_frames(virtual, 5, clock=clock,
                                                    dt=1 / 60)
                    assert len(frames) == 5
                    if expected == "power":
                        assert float(effect._config["bass_decay_rate"]) == \
                            pytest.approx(0.6)
                virtual._active_effect = None
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── proof 8: NAMED FLARE KINDS — the three semantics, band select + scale ────
# The owner's item-8 shape on the real render pipeline: a band SELECTS its
# named kinds and SCALES their strength; MOMENTARY spikes return exactly to
# the carried baseline (including a creep's current wander position);
# PERMANENT lands become the baseline drift carries from.

def test_flare_kinds_semantics_on_the_harness(tmp_path):
    from spectra.models.scene import (DriftRef, DriftSpec, FlareBand,
                                      FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    _categories_fixture(tmp_path)
    scene = SceneV2(
        name="Kinds",
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="concentric",
            params={"gradient_scale": 1.0, "power_multiplier": 0.2},
            brightness=0.5,
            drift={"power_multiplier": DriftRef(inline=DriftSpec(
                kind="creep", rate_per_min=0.3, lo=0.0, hi=1.0))})],
        flare_kinds=[
            FlareKind(name="Anchor", type="permanent",
                      params={"power_multiplier": 0.8}),
            FlareKind(name="Slam", type="momentary",
                      params={"gradient_scale": 1.8}, gain=1.4),
            FlareKind(name="Nudge", type="momentary",
                      params={"power_multiplier": 1.0}),
        ],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=0.8,
                      kinds={"Anchor": 1.0}),
            FlareBand(intensity_min=0.8, intensity_max=1.0,
                      kinds={"Slam": 1.3, "Nudge": 1.0}),
        ])})

    async def main():
        host, virtual = await _host(tmp_path, "kinds")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient_scale": 1.0, "power_multiplier": 0.2,
                          "brightness": 0.5}
                effect = headless.attach_effect(host, virtual, "concentric",
                                                config)
                executor, conductor, responder, _ = _engine(clock)
                _fire(conductor, scene, config)

                # PERMANENT: the value lands and BECOMES the baseline —
                # the creep resumes its wander from the landed point.
                record = await responder.on_event("flare", 0.5)
                assert record["result"] == "applied"
                assert [k["name"] for k in record["kinds"]] == ["Anchor"]
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["power_multiplier"] == pytest.approx(0.8)
                mech = conductor.mechanisms[0]
                assert mech.position == pytest.approx(0.8)
                await conductor.tick()
                leg = [w for w in executor.writes if w["kind"] == "glide"
                       and "power_multiplier" in w["params"]][-1]
                # 0.3/min over the 20 s leg = +0.1 FROM THE NEW BASELINE.
                assert leg["params"]["power_multiplier"] == pytest.approx(0.9)
                headless.render_frames(virtual, 1200, clock=clock, dt=1 / 60)

                # MOMENTARY at band scale ×1.3: the spike lands at
                # baseline + (declared − baseline)·1.3, the envelope at
                # 1 + (gain − 1)·1.3 — and everything RETURNS exactly.
                record = await responder.on_event("flare", 0.9)
                assert {k["name"] for k in record["kinds"]} \
                    == {"Slam", "Nudge"}
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] \
                    == pytest.approx(1.0 + (1.8 - 1.0) * 1.3)   # 2.04
                assert effect._config["brightness"] \
                    == pytest.approx(0.5 * (1.0 + 0.4 * 1.3))   # 0.76
                # Nudge (scale ×1) spiked the creeping param verbatim.
                assert effect._config["power_multiplier"] == pytest.approx(1.0)

                # The baselines never moved — momentary is momentary.
                state = conductor.virtuals[VID]
                assert state.param_baseline["gradient_scale"] == 1.0
                assert state.brightness_baseline == 0.5

                # The release returns gradient_scale/brightness to their
                # baselines and the creeping param to the WANDER POSITION
                # drift carried it to (0.9), not its fire-time value.
                assert await responder.flush_releases() == 1
                headless.render_frames(virtual, 120, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.0)
                assert effect._config["brightness"] == pytest.approx(0.5)
                assert effect._config["power_multiplier"] \
                    == pytest.approx(mech.position) \
                    and mech.position == pytest.approx(0.9)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── proof 9: momentary target expressions — offset + random, CHOSEN HOLD,
#            exact return on a creeping parameter ────────────────────────────
# The owner's five-ways extension on the real render pipeline: an OFFSET
# spike measures from wherever a creep currently sits (not its static
# declared baseline), a RANDOM spike rolls once and broadcasts, different
# kinds hold their spike for their OWN authored duration
# (pending_hold_groups → one release per group), and every release still
# returns EXACTLY to the baseline AS CARRIED AT RELEASE TIME — including
# a creep that kept wandering DURING the hold.

def test_momentary_target_expressions_and_chosen_hold_on_the_harness(tmp_path):
    from spectra.models.scene import (DriftRef, DriftSpec, FlareBand,
                                      FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    _categories_fixture(tmp_path)
    scene = SceneV2(
        name="Targets",
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="concentric",
            params={"gradient_scale": 1.0, "power_multiplier": 0.2},
            brightness=0.5,
            drift={"power_multiplier": DriftRef(inline=DriftSpec(
                kind="creep", rate_per_min=0.3, lo=0.0, hi=1.0))})],
        flare_kinds=[
            FlareKind(name="Anchor", type="permanent",
                      params={"power_multiplier": 0.8}),
            FlareKind(name="Dip", type="momentary", hold_ms=600,
                      params={"power_multiplier": {
                          "mode": "offset", "offset": -0.15}}),
            FlareKind(name="Flash", type="momentary",
                      params={"gradient_scale": {
                          "mode": "random", "lo": 1.4, "hi": 1.6}}),
        ],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=0.8,
                      kinds={"Anchor": 1.0}),
            FlareBand(intensity_min=0.8, intensity_max=1.0,
                      kinds={"Dip": 1.0, "Flash": 1.0}),
        ])})

    async def main():
        host, virtual = await _host(tmp_path, "targets")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient_scale": 1.0, "power_multiplier": 0.2,
                          "brightness": 0.5}
                effect = headless.attach_effect(host, virtual, "concentric",
                                                config)
                executor, conductor, responder, _ = _engine(clock)
                _fire(conductor, scene, config)

                # Warm the creep off its static baseline exactly as proof 8
                # does: Anchor lands 0.8, one leg carries it to 0.9.
                await responder.on_event("flare", 0.5)
                await conductor.tick()
                headless.render_frames(virtual, 1200, clock=clock, dt=1 / 60)
                mech = conductor.mechanisms[0]
                assert mech.position == pytest.approx(0.9)

                # Dip (offset -0.15) and Flash (random 1.4–1.6) fire together.
                record = await responder.on_event("flare", 0.9)
                assert {k["name"] for k in record["kinds"]} == {"Dip", "Flash"}
                dip_rec = next(k for k in record["kinds"] if k["name"] == "Dip")
                flash_rec = next(k for k in record["kinds"] if k["name"] == "Flash")
                dip_target = dip_rec["moved"][0]["params"]["power_multiplier"]
                flash_target = flash_rec["moved"][0]["params"]["gradient_scale"]
                # Offset measures from the creep's CURRENT wander position
                # (0.9), not the static declared/param baseline (0.2).
                assert dip_target == pytest.approx(0.9 - 0.15)
                assert 1.4 <= flash_target <= 1.6

                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["power_multiplier"] == pytest.approx(dip_target)
                assert effect._config["gradient_scale"] == pytest.approx(flash_target)

                # Two kinds, two CHOSEN HOLDS: Dip's authored 600 ms and
                # Flash's default PULSE_HOLD_S (250 ms) are separate groups.
                from spectra.services.scene_response import PULSE_HOLD_S
                assert responder.pending_hold_groups() == \
                    sorted([0.6, PULSE_HOLD_S])

                # The creep keeps wandering DURING the hold — a second leg
                # carries the MODEL's position from 0.9 to 1.0 (the leg's
                # own glide retargets the effect independently of the
                # pending spike) before either release fires.
                await conductor.tick()
                assert mech.position == pytest.approx(1.0)

                # Flash's shorter (default) hold releases first: its own
                # group only — Dip's separate hold group is untouched.
                released = await responder.flush_releases(PULSE_HOLD_S)
                assert released == 1
                assert responder.pending_hold_groups() == [0.6]
                headless.render_frames(virtual, 120, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.0)

                # Dip's release returns EXACTLY to the creep's position AS
                # CARRIED NOW (1.0 — where the second leg left it) once its
                # own CHOSEN HOLD elapses, never the 0.9 it was measured
                # from at spike time.
                released = await responder.flush_releases(0.6)
                assert released == 1
                assert responder.pending_hold_groups() == []
                headless.render_frames(virtual, 120, clock=clock, dt=1 / 60)
                assert effect._config["power_multiplier"] == pytest.approx(1.0)
                assert mech.position == pytest.approx(1.0)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── offline guarantee ────────────────────────────────────────────────────────

def test_no_audio_hardware_was_touched():
    from fx.compat_sounddevice import _LazySounddevice

    assert _LazySounddevice._module is None
