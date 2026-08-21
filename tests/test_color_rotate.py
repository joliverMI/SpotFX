"""The colour ROTATE-AND-BACK flare (owner ask, 2026-08-20 — verbatim spec
in scripts/add_color_rotate_flares.py's own docstring). Same offline
integration-proof shape as test_spectra_engine.py (real conductor +
response engine on the FacadeExecutor against the real vendored blackhole
effect, fx.headless dummy device, deterministic fake clock) scoped to this
one kind: the four intensity-scaled quantities land exactly as specified,
the ramp/dwell/fade-back sequence executes and releases through its own
queue, a shape-targeting kind attached to the same band fires independently
(the colour/shape concurrency his ask requires), and the model rejects any
authored knob on the kind. Real-async-timing dwell measurement and the
trigger-engine anchoring wiring live in scripts/check_color_rotate.py — see
that module's own docstring for why those need a genuine wall clock rather
than this file's deterministic fake one.

No LedFX service, no HTTP, no audio hardware (fx.headless.silence_audio).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import facade, headless
from fx import device_model

REPO_ROOT = Path(__file__).resolve().parent.parent
VID = headless.DEFAULT_VIRTUAL_ID
ORIGINAL_GRADIENT = "#3366cc"


def _run(coro):
    return asyncio.run(coro)


def _categories_fixture(tmp_path) -> None:
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [VID], "effects": ["blackhole"], "role": None}}))


async def _host(tmp_path, sub: str):
    host = await headless.start_headless_host(str(tmp_path / sub))
    facade.set_host(host)
    return host, host.virtuals.get(VID)


def _engine(clock):
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine

    executor = FacadeExecutor(
        clock=lambda: clock.now,
        room_controls_load=lambda: rc.RoomControlState())
    conductor = DriftConductor(
        executor=executor, clock=lambda: clock.now, leg_s=20.0,
        intensity=lambda: 1.0, drift_profiles=lambda: {},
        curve_profiles=lambda: {}, gradient_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(), rng=Random(11))
    responder = ResponseEngine(
        conductor=conductor, executor=executor, rng=Random(7),
        clock=lambda: clock.now, curve_profiles=lambda: {})
    return executor, conductor, responder


def _fire(conductor, scene, config, color_mode="set"):
    dev = scene.devices[0]
    conductor.on_scene_fire(scene, [{
        "virtual_id": VID, "effect_type": dev.effect_type,
        "config": dict(config), "entry_id": dev.id, "color_mode": color_mode}])


def _rotate_scene(with_shape_kind: bool = False):
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = [FlareKind(name="Colour Rotate & Back", type="color_rotate")]
    band_kinds = {"Colour Rotate & Back": 1.0}
    if with_shape_kind:
        kinds.append(FlareKind(
            name="Shape Nudge", type="momentary", hold_ms=300,
            params={"swirl": {"mode": "absolute", "value": -2.0}}))
        band_kinds["Shape Nudge"] = 1.0
    return SceneV2(
        name="Rotate Test",
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type="blackhole",
            params={"swirl": 3.0})],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0, kinds=band_kinds),
        ])})


# ── model shape ────────────────────────────────────────────────────────────

def test_color_rotate_kind_carries_no_authored_knobs():
    from spectra.models.scene import FlareKind

    with pytest.raises(Exception):
        FlareKind(name="bad", type="color_rotate", gain=0.7)
    with pytest.raises(Exception):
        FlareKind(name="bad2", type="color_rotate", hold_ms=500)
    with pytest.raises(Exception):
        FlareKind(name="bad3", type="color_rotate",
                 params={"swirl": {"mode": "absolute", "value": 1.0}})
    with pytest.raises(Exception):
        FlareKind(name="bad4", type="color_rotate", jump="dice")
    # A bare declaration is exactly what's expressible.
    ok = FlareKind(name="ok", type="color_rotate")
    assert ok.params == {}
    assert ok.gain == 1.0
    assert ok.hold_ms is None
    assert ok.jump is None


# ── the four scaled quantities ───────────────────────────────────────────

def test_all_four_quantities_scale_linearly_between_his_exact_numbers():
    from spectra.services import scene_response as sr

    assert sr.color_rotate_degrees(0.0) == 60.0
    assert sr.color_rotate_degrees(1.0) == 180.0
    assert sr.color_rotate_degrees(0.5) == 120.0

    assert sr.color_rotate_ramp_ms(0.0) == 1000
    assert sr.color_rotate_ramp_ms(1.0) == 250

    assert sr.color_rotate_dwell_ms(0.0) == 1000
    assert sr.color_rotate_dwell_ms(1.0) == 400

    assert sr.color_rotate_fade_ms(0.0) == 1500
    assert sr.color_rotate_fade_ms(1.0) == 375
    # fade is always exactly 1.5x the (already-scaled) ramp, at any intensity.
    for i in (0.0, 0.2, 0.5, 0.73, 1.0):
        assert sr.color_rotate_fade_ms(i) == round(sr.color_rotate_ramp_ms(i) * 1.5)

    # clamped past either end, not extrapolated.
    assert sr.color_rotate_degrees(-1.0) == 60.0
    assert sr.color_rotate_degrees(2.0) == 180.0


# ── the real ramp -> dwell -> fade-back sequence, on the real effect ────────

def test_rotate_ramps_in_dwells_then_fades_back_to_the_exact_original(tmp_path):
    from spectra.services import color_rotate

    _categories_fixture(tmp_path)
    scene = _rotate_scene()
    intensity = 1.0
    degrees = 180.0  # color_rotate_degrees(1.0)
    expected_rotated = color_rotate.rotate_color_value(ORIGINAL_GRADIENT, degrees)

    async def main():
        host, virtual = await _host(tmp_path, "rotate")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient": ORIGINAL_GRADIENT}
                effect = headless.attach_effect(host, virtual, "blackhole", config)
                executor, conductor, responder = _engine(clock)
                _fire(conductor, scene, config)

                record = await responder.on_event("flare", intensity)
                info = record["color_rotate"]
                assert info["virtuals"] == 1
                assert info["ramp_ms"] == 250
                assert info["dwell_ms"] == 400
                assert info["fade_ms"] == 375
                assert info["degrees"] == 180.0

                # Render past the ramp's own duration (250ms) for the tween
                # to actually land, not just be heading there.
                headless.render_frames(virtual, int(250 / 1000 * 60) + 5,
                                       clock=clock, dt=1 / 60)
                assert effect._config["gradient"] == expected_rotated

                # Not due yet at anything less than its own dwell.
                released = await responder.flush_color_rotates(0.399)
                assert released == 0
                assert responder.pending_color_rotate_holds() == [0.4]

                released = await responder.flush_color_rotates(0.4)
                assert released == 1
                assert responder.pending_color_rotate_holds() == []
                headless.render_frames(virtual, int(375 / 1000 * 60) + 5,
                                       clock=clock, dt=1 / 60)
                assert effect._config["gradient"] == ORIGINAL_GRADIENT
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_rotate_release_never_touches_pending_releases_queue(tmp_path):
    """The two release queues are genuinely independent — draining one must
    never drain or affect the other."""
    _categories_fixture(tmp_path)
    scene = _rotate_scene(with_shape_kind=True)

    async def main():
        host, virtual = await _host(tmp_path, "independent-queues")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient": ORIGINAL_GRADIENT, "swirl": 3.0}
                headless.attach_effect(host, virtual, "blackhole", config)
                executor, conductor, responder = _engine(clock)
                _fire(conductor, scene, config)

                await responder.on_event("flare", 1.0)
                assert responder.pending_hold_groups() == [0.3]        # Shape Nudge
                assert responder.pending_color_rotate_holds() == [0.4]  # rotate's own

                # Draining the param-release queue must not touch rotate's.
                await responder.flush_releases(0.3)
                assert responder.pending_color_rotate_holds() == [0.4]
                assert responder.pending_hold_groups() == []

                # And vice versa.
                await responder.flush_color_rotates(0.4)
                assert responder.pending_color_rotate_holds() == []
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── colour/shape concurrency ─────────────────────────────────────────────

def test_color_rotate_and_a_shape_kind_land_as_independent_writes(tmp_path):
    """His requirement, not a preference: 'should be a color flare and
    concur with some shape flares.' A band carrying both a color_rotate
    kind and a shape param-move kind fires both in the same on_event pass,
    landing as two SEPARATE executor writes — the rotate never displaces
    the shape move or vice versa."""
    _categories_fixture(tmp_path)
    scene = _rotate_scene(with_shape_kind=True)

    async def main():
        host, virtual = await _host(tmp_path, "concurrency")
        try:
            with headless.fake_clock() as clock:
                config = {"gradient": ORIGINAL_GRADIENT, "swirl": 3.0}
                effect = headless.attach_effect(host, virtual, "blackhole", config)
                executor, conductor, responder = _engine(clock)
                _fire(conductor, scene, config)

                await responder.on_event("flare", 1.0)
                # Render past both the rotate's ramp (250ms) and the shape
                # kind's own DICE_REROLL_GLIDE_MS glide (220ms) so each
                # tween has actually landed, not just started.
                headless.render_frames(virtual, int(250 / 1000 * 60) + 5,
                                       clock=clock, dt=1 / 60)

                # Both landed independently on the real effect.
                assert effect._config["gradient"] != ORIGINAL_GRADIENT
                assert effect._config["swirl"] == -2.0

                gradient_writes = [w for w in executor.writes
                                   if "gradient" in w["params"]]
                swirl_writes = [w for w in executor.writes
                                if "swirl" in w["params"]]
                assert len(gradient_writes) == 1
                assert len(swirl_writes) == 1
                # Genuinely separate executor calls, not one write carrying
                # both keys.
                assert "swirl" not in gradient_writes[0]["params"]
                assert "gradient" not in swirl_writes[0]["params"]
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── nothing to rotate ────────────────────────────────────────────────────

def test_no_live_gradient_or_not_set_mode_is_a_silent_skip(tmp_path):
    _categories_fixture(tmp_path)
    scene = _rotate_scene()

    async def main():
        host, virtual = await _host(tmp_path, "no-gradient")
        try:
            with headless.fake_clock() as clock:
                config = {}  # no gradient authored
                headless.attach_effect(host, virtual, "blackhole", config)
                executor, conductor, responder = _engine(clock)
                _fire(conductor, scene, config, color_mode="fixed")

                record = await responder.on_event("flare", 1.0)
                assert record["color_rotate"]["virtuals"] == 0
                assert responder.pending_color_rotate_holds() == []
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── lead-time anchoring: the pure function ───────────────────────────────

def test_color_rotate_lead_ms_equals_its_own_ramp_at_every_intensity():
    from spectra.services import scene_response as sr

    scene = _rotate_scene()
    for intensity in (0.0, 0.35, 0.72, 1.0):
        lead = sr.color_rotate_lead_ms(scene, "flare", intensity, {})
        assert lead == sr.color_rotate_ramp_ms(intensity)
        # THE ANCHORING IDENTITY: firing lead ms early means the ramp's own
        # completion lands exactly on the trigger mark.
        mark_ms = 50_000
        assert (mark_ms - lead) + sr.color_rotate_ramp_ms(intensity) == mark_ms


def test_color_rotate_lead_ms_is_zero_when_not_attached():
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    from spectra.services import scene_response as sr

    bare = SceneV2(name="Bare", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="blackhole")],
        flare_kinds=[FlareKind(name="Shape Nudge", type="momentary", hold_ms=300,
                              params={"swirl": {"mode": "absolute", "value": -2.0}})],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds={"Shape Nudge": 1.0})])})
    assert sr.color_rotate_lead_ms(bare, "flare", 0.8, {}) == 0


def test_no_audio_hardware_was_touched():
    from fx.compat_sounddevice import _LazySounddevice

    assert _LazySounddevice._module is None
