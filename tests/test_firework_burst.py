"""The FIREWORK BURST flare (owner ask, 2026-08-21 — verbatim spec in
scripts/add_fireworks_burst_flare.py's own docstring). Same offline
integration-proof shape as test_color_rotate.py (real response engine on
the FacadeExecutor against the real vendored fireworks effects,
fx.headless dummy device, deterministic fake clock) scoped to this one
kind:

  - the model rejects any authored knob (the color_rotate shape);
  - the rocket count scales linearly between his exact numbers (3 at
    intensity 0.0, 6 at 1.0), clamped, never extrapolated;
  - the write targets ONLY virtuals whose live effect is a fireworks
    effect (fx.device_model.FIREWORK_BURST_EFFECTS) and the band's own
    x-scale steers the effective intensity;
  - the burst lands as REAL payoff particles on the next rendered frame
    of both vendored effects (the "line up" proof — never queued for a
    beat the way beat_burst is), ignore_cap so the max_blobs density cap
    can never swallow it;
  - it is purely ADDITIVE: the scene's own live particles keep flying,
    aging, and are never restarted, reset, or replaced ("on top of the
    standard ones" — proven, not assumed);
  - the effect self-resets burst_rockets to 0, so an identical later
    fire edges again (repeat-fire proof), and a stale persisted count on
    a fresh instance never explodes (the phase-key creation-baseline
    rule) but is still reset to an honest 0;
  - a shape-targeting kind attached to the same band fires independently
    in the same pass (the concurrency proof, mirroring color_rotate's).

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

from fx import device_model, facade, headless

REPO_ROOT = Path(__file__).resolve().parent.parent
VID = headless.DEFAULT_VIRTUAL_ID


def _run(coro):
    return asyncio.run(coro)


def _categories_fixture(tmp_path, effects) -> None:
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [VID], "effects": list(effects), "role": None}}))


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


def _burst_scene(effect_type: str, band_scale: float = 1.0,
                 with_shape_kind: bool = False):
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = [FlareKind(name="Firework Burst", type="firework_burst")]
    band_kinds = {"Firework Burst": band_scale}
    if with_shape_kind:
        kinds.append(FlareKind(
            name="Shape Nudge", type="momentary", hold_ms=300,
            params={"burst_speed": {"mode": "absolute", "value": 1.4}}))
        band_kinds["Shape Nudge"] = 1.0
    return SceneV2(
        name="Burst Test",
        devices=[SceneDeviceConfig(
            target_kind="virtual", target=VID, effect_type=effect_type)],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0, kinds=band_kinds),
        ])})


def _fire(conductor, scene, config, effect_type):
    dev = scene.devices[0]
    conductor.on_scene_fire(scene, [{
        "virtual_id": VID, "effect_type": effect_type,
        "config": dict(config), "entry_id": dev.id, "color_mode": "set"}])


# ── model shape ────────────────────────────────────────────────────────────

def test_firework_burst_kind_carries_no_authored_knobs():
    from spectra.models.scene import FlareKind

    with pytest.raises(Exception):
        FlareKind(name="bad", type="firework_burst", gain=0.7)
    with pytest.raises(Exception):
        FlareKind(name="bad2", type="firework_burst", hold_ms=500)
    with pytest.raises(Exception):
        FlareKind(name="bad3", type="firework_burst",
                  params={"beat_burst": {"mode": "absolute", "value": 2.0}})
    with pytest.raises(Exception):
        FlareKind(name="bad4", type="firework_burst", jump="dice")
    # A bare declaration is exactly what's expressible.
    ok = FlareKind(name="ok", type="firework_burst")
    assert ok.params == {}
    assert ok.gain == 1.0
    assert ok.hold_ms is None
    assert ok.jump is None


# ── his exact numbers ──────────────────────────────────────────────────────

def test_rocket_count_scales_linearly_between_his_exact_numbers():
    from spectra.services import scene_response as sr

    assert sr.firework_burst_rockets(0.0) == 3
    assert sr.firework_burst_rockets(1.0) == 6
    # whole rockets, same int(round()) convention as the ramp-ms families
    for i in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert sr.firework_burst_rockets(i) == round(3.0 + 3.0 * i)
    # clamped past either end, not extrapolated
    assert sr.firework_burst_rockets(-1.0) == 3
    assert sr.firework_burst_rockets(2.0) == 6


# ── targeting + scale (recording level, no hardware) ───────────────────────

def test_burst_write_targets_only_fireworks_effects(tmp_path):
    from spectra.models.scene import SceneDeviceConfig
    from spectra.services.fx_executor import RecordingExecutor

    scene = _burst_scene("fireworks1d")
    scene.devices.append(SceneDeviceConfig(
        target_kind="virtual", target="single-1", effect_type="power"))

    async def main():
        clock_now = 100.0
        from random import Random as _R

        from spectra.services import room_controls as rc
        from spectra.services.drift_conductor import DriftConductor
        from spectra.services.scene_response import ResponseEngine
        executor = RecordingExecutor(
            clock=lambda: clock_now,
            room_controls_load=lambda: rc.RoomControlState())
        conductor = DriftConductor(
            executor=executor, clock=lambda: clock_now, leg_s=20.0,
            intensity=lambda: 1.0, drift_profiles=lambda: {},
            curve_profiles=lambda: {}, gradient_profiles=lambda: {},
            room_controls=lambda: rc.RoomControlState(), rng=_R(3))
        responder = ResponseEngine(
            conductor=conductor, executor=executor, rng=_R(5),
            clock=lambda: clock_now, curve_profiles=lambda: {})
        conductor.on_scene_fire(scene, [
            {"virtual_id": VID, "effect_type": "fireworks1d",
             "config": {}, "entry_id": scene.devices[0].id,
             "color_mode": "set"},
            {"virtual_id": "single-1", "effect_type": "power",
             "config": {}, "entry_id": scene.devices[1].id,
             "color_mode": "set"},
        ])

        record = await responder.on_event("flare", 1.0)
        info = record["firework_burst"]
        assert info == {"rockets": 6, "virtuals": 1}
        burst_writes = [w for w in executor.writes
                        if "burst_rockets" in w["params"]]
        assert len(burst_writes) == 1
        assert burst_writes[0]["virtual_id"] == VID
        assert burst_writes[0]["kind"] == "jump"
        assert burst_writes[0]["params"] == {"burst_rockets": 6}
        # the power virtual never sees the key
        assert not any("burst_rockets" in w["params"] for w in executor.writes
                       if w["virtual_id"] == "single-1")

    _run(main())


def test_band_scale_steers_the_effective_intensity(tmp_path):
    from random import Random as _R

    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor
    from spectra.services.scene_response import ResponseEngine

    scene = _burst_scene("fireworks1d", band_scale=0.5)

    async def main():
        executor = RecordingExecutor(
            clock=lambda: 0.0, room_controls_load=lambda: rc.RoomControlState())
        conductor = DriftConductor(
            executor=executor, clock=lambda: 0.0, leg_s=20.0,
            intensity=lambda: 1.0, drift_profiles=lambda: {},
            curve_profiles=lambda: {}, gradient_profiles=lambda: {},
            room_controls=lambda: rc.RoomControlState(), rng=_R(3))
        responder = ResponseEngine(
            conductor=conductor, executor=executor, rng=_R(5),
            clock=lambda: 0.0, curve_profiles=lambda: {})
        _fire(conductor, scene, {}, "fireworks1d")
        record = await responder.on_event("flare", 1.0)
        # intensity 1.0 x scale 0.5 -> effective 0.5 -> round(4.5) = 4
        assert record["firework_burst"]["rockets"] == 4

    _run(main())


# ── the real spawn, next frame, on both vendored effects ───────────────────

def test_burst_lands_next_frame_and_is_additive_1d(tmp_path):
    _categories_fixture(tmp_path, ["fireworks1d"])
    scene = _burst_scene("fireworks1d")

    async def main():
        host, virtual = await _host(tmp_path, "burst1d")
        try:
            with headless.fake_clock() as clock:
                config = {"spawn_rate": 0.0, "beat_burst": 0, "max_blobs": 6}
                effect = headless.attach_effect(
                    host, virtual, "fireworks1d", config)
                executor, conductor, responder = _engine(clock)
                _fire(conductor, scene, config, "fireworks1d")

                # seed the scene's OWN show: two ordinary fireworks
                headless.render_frames(virtual, 2, clock=clock, dt=1 / 60)
                effect._spawn_firework()
                effect._spawn_firework()
                pre_n = effect.n
                assert pre_n == 4
                pre_age = effect.f_age[:pre_n].copy()
                pre_life = effect.f_life[:pre_n].copy()
                pre_grad = effect.f_grad[:pre_n].copy()
                pre_phase = effect._phase

                record = await responder.on_event("flare", 1.0)
                assert record["firework_burst"] == {"rockets": 6,
                                                    "virtuals": 1}
                # ONE rendered frame is all it takes to land — the whole
                # point vs beat_burst's wait-for-the-next-beat. (Frame 1
                # lands the 1 ms jump tween; frame 2's spawn consumes it.)
                headless.render_frames(virtual, 2, clock=clock, dt=1 / 60)
                # 6 rockets x two staggered pairs x two particles, on top
                # of the 4 already flying — despite max_blobs=6 (his real
                # strips value): ignore_cap means the cap can't swallow it
                assert effect.n == pre_n + 24
                # ADDITIVE: the original particles are still the same ones,
                # aged two frames, lives/colors untouched, still first in
                # the buffer — nothing was restarted or replaced
                assert effect.f_age[:pre_n] == pytest.approx(
                    pre_age + 2 / 60, abs=1e-4)
                assert effect.f_life[:pre_n] == pytest.approx(pre_life)
                assert effect.f_grad[:pre_n] == pytest.approx(pre_grad)
                assert effect._phase == pre_phase
                # the payoff shape: full-bright, PAYOFF_LIFE-stretched lives
                from fx.effects.fireworks1d import PAYOFF_LIFE
                fresh = slice(pre_n, effect.n)
                assert (effect.f_bright[fresh] == 1.0).all()
                min_life = 1.2 * PAYOFF_LIFE * 0.8  # burst_life x jitter lo
                assert (effect.f_life[fresh] >= min_life - 1e-6).all()
                # self-reset: the key reads 0 again, edge re-armed
                assert effect._config["burst_rockets"] == 0

                # a SECOND identical fire edges again (the self-reset is
                # what makes an equal count a fresh edge)
                n_before = effect.n
                await responder.on_event("flare", 1.0)
                headless.render_frames(virtual, 2, clock=clock, dt=1 / 60)
                assert effect.n == n_before + 24
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_burst_lands_next_frame_2d(tmp_path):
    _categories_fixture(tmp_path, ["fireworks"])
    scene = _burst_scene("fireworks")

    async def main():
        host, virtual = await _host(tmp_path, "burst2d")
        try:
            with headless.fake_clock() as clock:
                config = {"spawn_rate": 0.0, "beat_burst": 0,
                          "burst_size": 12}
                effect = headless.attach_effect(
                    host, virtual, "fireworks", config)
                executor, conductor, responder = _engine(clock)
                _fire(conductor, scene, config, "fireworks")

                headless.render_frames(virtual, 2, clock=clock, dt=1 / 60)
                pre_n = effect.n
                record = await responder.on_event("flare", 0.0)
                assert record["firework_burst"] == {"rockets": 3,
                                                    "virtuals": 1}
                headless.render_frames(virtual, 2, clock=clock, dt=1 / 60)
                # 3 giant payoff bursts of burst_size*2.5=30 particles each
                assert effect.n == pre_n + 3 * 30
                fresh = slice(pre_n, effect.n)
                assert (effect.p_bright[fresh] == 1.0).all()
                assert effect._config["burst_rockets"] == 0
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_stale_persisted_count_never_fires_on_a_fresh_instance(tmp_path):
    """The phase-key creation-baseline rule: an instance built from a
    config that already carries burst_rockets=5 (a crash between the flare
    write and the next frame's self-reset) must NOT explode on its first
    frame — and must still reset the key to an honest 0 so a LATER write
    of the same count edges normally."""
    _categories_fixture(tmp_path, ["fireworks1d"])

    async def main():
        host, virtual = await _host(tmp_path, "stale")
        try:
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(
                    host, virtual, "fireworks1d",
                    {"spawn_rate": 0.0, "beat_burst": 0,
                     "burst_rockets": 5})
                headless.render_frames(virtual, 3, clock=clock, dt=1 / 60)
                assert effect.n == 0                      # nothing exploded
                assert effect._config["burst_rockets"] == 0   # honest reset

                # the same count arriving as a REAL write now edges fine
                effect.start_param_transitions({"burst_rockets": 5}, 1)
                headless.render_frames(virtual, 2, clock=clock, dt=1 / 60)
                assert effect.n == 5 * 4
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── concurrency with a shape kind in the same band ─────────────────────────

def test_burst_and_shape_kind_in_one_band_both_land(tmp_path):
    """His color_rotate concurrency requirement, applied here: a
    shape-targeting momentary kind in the same band still executes its own
    write in the same pass — burst_rockets never enters the param kinds'
    shared jumps/glides dicts (it is deliberately unregistered), so
    neither gates or overwrites the other."""
    from random import Random as _R

    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor
    from spectra.services.scene_response import ResponseEngine

    scene = _burst_scene("fireworks1d", with_shape_kind=True)

    async def main():
        executor = RecordingExecutor(
            clock=lambda: 0.0, room_controls_load=lambda: rc.RoomControlState())
        conductor = DriftConductor(
            executor=executor, clock=lambda: 0.0, leg_s=20.0,
            intensity=lambda: 1.0, drift_profiles=lambda: {},
            curve_profiles=lambda: {}, gradient_profiles=lambda: {},
            room_controls=lambda: rc.RoomControlState(), rng=_R(3))
        responder = ResponseEngine(
            conductor=conductor, executor=executor, rng=_R(5),
            clock=lambda: 0.0, curve_profiles=lambda: {})
        _fire(conductor, scene, {"burst_speed": 0.5}, "fireworks1d")

        record = await responder.on_event("flare", 1.0)
        assert record["firework_burst"]["rockets"] == 6
        moved = [w for w in executor.writes if "burst_speed" in w["params"]]
        burst = [w for w in executor.writes if "burst_rockets" in w["params"]]
        assert len(moved) == 1 and len(burst) == 1
        assert moved[0]["params"]["burst_speed"] == pytest.approx(1.4)
        kinds_fired = {k["name"] for k in record["kinds"]}
        assert kinds_fired == {"Firework Burst", "Shape Nudge"}

    _run(main())
