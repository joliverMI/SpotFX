"""The BIG FISH flare (2026-10-08, phase 1 — the look only; the ordinary
fish do not avoid it yet).

His ask, verbatim: "add a flare to fish, where a really large fish swims
directly across the screen, in the background of the others, and at 60%
brightness (tuneable). ... The speed it goes at is dependant on intensity.
the color should be the 120 to 180 degree rotation of the central color of
the scene, so it contrasts. at .5 intensity or higher 180 degrees, scale
linearly to .2 insesity = 120 degrees (either direction)."

Proven on the real vendored pipeline (fx.headless, his crystal's 72x37
shape) for the effect, on a recording engine for the flare write, and on a
temp store for the migration script. fx/effects/fish.py's BIG FISH block is
the binding statement.
"""
from __future__ import annotations

import asyncio
import colorsys
import json
import sys
from pathlib import Path
from random import Random

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fx import device_model  # noqa: E402
from fx.effects import fish as FX  # noqa: E402
from test_fish import HIS_MATRIX, _close, _room  # noqa: E402

DT = 1.0 / 60.0
RED = "#ff0000"


def _run(coro):
    return asyncio.run(coro)


# ── the two curves he named ─────────────────────────────────────────────────

@pytest.mark.parametrize("intensity,degrees", [
    (0.0, 120.0), (0.1, 120.0), (0.2, 120.0), (0.35, 150.0), (0.5, 180.0),
    (0.75, 180.0), (1.0, 180.0)])
def test_the_colour_turn_is_120_at_0_2_and_180_from_0_5(intensity, degrees):
    assert FX.big_fish_hue_degrees(intensity) == pytest.approx(degrees)


def test_the_crossing_is_faster_at_higher_intensity_speed_linear():
    slow, fast = 7.0, 2.5
    assert FX.big_fish_cross_s(0.0, slow, fast) == pytest.approx(slow)
    assert FX.big_fish_cross_s(1.0, slow, fast) == pytest.approx(fast)
    times = [FX.big_fish_cross_s(i / 10, slow, fast) for i in range(11)]
    assert all(a > b for a, b in zip(times, times[1:]))
    speeds = [1.0 / t for t in times]
    steps = np.diff(speeds)
    assert np.allclose(steps, steps[0])        # the SPEED is linear


def test_rotate_hue_keeps_saturation_and_value():
    out = FX.rotate_hue(np.array([255.0, 0.0, 0.0]), 180.0)
    assert out == pytest.approx([0.0, 255.0, 255.0], abs=1e-3)
    out = FX.rotate_hue(np.array([200.0, 100.0, 50.0]), 120.0)
    h0, s0, v0 = colorsys.rgb_to_hsv(200 / 255, 100 / 255, 50 / 255)
    h1, s1, v1 = colorsys.rgb_to_hsv(*(out / 255.0))
    assert (s1, v1) == pytest.approx((s0, v0), abs=1e-4)
    assert (h1 - h0) % 1.0 == pytest.approx(1 / 3, abs=1e-4)


# ── the effect, on the real pipeline ────────────────────────────────────────

def _cfg(**over):
    # his Orbits-copied Matrix entry, solid red, no wake: every pixel the
    # ordinary fish light is pure red, so green/blue belong to the big fish
    return dict(HIS_MATRIX, gradient=RED, ripple_amount=0.0, **over)


def _cross(tmp_path, intensity, seed=5, **cfg):
    """Fire one big fish and render until it has gone; returns the effect,
    its record and every frame (H, W, 3 float) of the crossing."""
    async def main():
        room = await _room(tmp_path, "m", _cfg(**cfg), seed=seed)
        try:
            room.step(30)
            eff = room.effect
            # as the engine writes it: floored so a fire at 0 still edges
            eff.update_config(
                {"big_fish": max(intensity, FX.BIG_FISH_POKE_FLOOR)})
            frames = []
            for _ in range(60 * 40):
                room.step(1)
                frames.append(np.asarray(eff.matrix, dtype=np.float32).copy())
                if not eff._big:
                    break
            return eff, dict(eff.big_fish_last), frames, dict(eff._config)
        finally:
            await _close(room)
    return _run(main())


def test_a_poke_sends_one_big_fish_across_and_self_resets(tmp_path):
    eff, fish, frames, config = _cross(tmp_path, 0.6)
    assert eff.big_fish_spawned == 1 and config["big_fish"] == 0.0
    big = [float(f[..., 1:].max()) for f in frames]
    # it ENTERS from off the panel and LEAVES off the other side: nothing of
    # it on the first frame, nothing on the last, the panel crossed between
    assert big[0] < 5.0 and big[-1] < 5.0 and max(big) > 100.0
    # and it took its own crossing time to do it
    assert len(frames) * DT == pytest.approx(fish["cross_s"], abs=3 * DT)
    # really large: two thirds of the panel long, near the middle
    assert fish["length"] == pytest.approx(0.65 * 71, rel=1e-3)
    assert abs(fish["y"] - 18.0) <= FX.BIG_FISH_Y_SPREAD * 37 + 1e-6


def test_it_crosses_straight_through_the_middle(tmp_path):
    _eff, fish, frames, _ = _cross(tmp_path, 0.6)
    mid = frames[len(frames) // 2][..., 1]
    rows = np.flatnonzero(mid.max(axis=1) > 50)
    cols = np.flatnonzero(mid.max(axis=0) > 50)
    assert rows.size and cols.size > 20            # a long body across
    assert abs(rows.mean() - fish["y"]) < 3.0      # centred on its row


@pytest.mark.parametrize("intensity", [0.0, 0.5, 1.0])
def test_the_speed_follows_the_intensity(tmp_path, intensity):
    _eff, fish, frames, _ = _cross(tmp_path, intensity)
    expect = FX.big_fish_cross_s(max(intensity, FX.BIG_FISH_POKE_FLOOR), 7.0, 2.5)
    assert fish["cross_s"] == pytest.approx(expect)
    assert len(frames) * DT == pytest.approx(expect, abs=3 * DT)


@pytest.mark.parametrize("intensity,degrees", [(0.2, 120.0), (0.35, 150.0),
                                               (0.5, 180.0)])
def test_its_colour_is_the_centre_turned_and_60_percent(tmp_path, intensity,
                                                        degrees):
    for seed in (5, 6, 7, 8):
        eff, fish, frames, _ = _cross(tmp_path / str(seed), intensity, seed=seed)
        assert fish["degrees"] == pytest.approx(degrees)
        expect = FX.rotate_hue(np.array([255.0, 0.0, 0.0]),
                               fish["turn"] * degrees) * 0.6
        # its brightest unoccluded pixel is exactly the turned colour at 60%
        # (the silhouette is a MAX, never a sum, so 0.6 is what shows)
        peak = max(frames, key=lambda f: f[..., 1:].sum())
        gb = peak[..., 1:].reshape(-1, 2)
        assert gb.max(axis=0) == pytest.approx(expect[1:], abs=1.5)


def test_either_direction_both_ways_turn_up(tmp_path):
    turns = set()
    sides = set()
    for seed in range(12):
        _eff, fish, _f, _ = _cross(tmp_path / str(seed), 0.3, seed=seed,
                                   big_fish_cross_fast_s=0.5,
                                   big_fish_cross_slow_s=0.5)
        turns.add(fish["turn"])
        sides.add(fish["travel"])
    assert turns == {-1.0, 1.0} and sides == {-1.0, 1.0}


def test_the_brightness_is_tunable(tmp_path):
    _eff, fish, frames, _ = _cross(tmp_path, 0.6, big_fish_brightness=0.3)
    peak = max(frames, key=lambda f: f[..., 1:].sum())
    assert peak[..., 1:].max() == pytest.approx(255 * 0.3, abs=1.5)


def test_it_swims_behind_the_ordinary_fish(tmp_path):
    """Wherever an ordinary fish is fully lit, the big fish is hidden —
    it reads as BEHIND. And it never hides one: red stays red."""
    _eff, _fish, frames, _ = _cross(tmp_path, 0.3, particle_count=8,
                                    blob_size=3.0)
    overlaps = 0
    for f in frames:
        over = f[..., 0] >= FX.BIG_FISH_OCCLUDE_AT
        overlaps += int(np.count_nonzero(over))
        assert np.all(f[..., 1:][over] < 1e-3)
    assert overlaps > 0


def test_the_ordinary_fish_render_is_untouched_without_a_poke(tmp_path):
    """No poke, no big fish: the layer is never even built, so every frame
    is exactly the frame the effect drew before this flare existed."""
    async def main():
        room = await _room(tmp_path, "m", _cfg())
        try:
            room.step(240)
            assert room.effect._big == []
            assert room.effect._big_fish_layer(DT, None) is None
        finally:
            await _close(room)
    _run(main())


def test_a_stale_persisted_poke_never_swims(tmp_path):
    async def main():
        room = await _room(tmp_path, "m", _cfg(big_fish=0.8))
        try:
            room.step(60)
            assert room.effect.big_fish_spawned == 0
        finally:
            await _close(room)
    _run(main())


def test_at_most_three_cross_at_once(tmp_path):
    async def main():
        room = await _room(tmp_path, "m", _cfg())
        try:
            eff = room.effect
            for i in range(5):
                eff.update_config({"big_fish": 0.5 + i * 0.01})
                room.step(1)
            assert len(eff._big) == FX.BIG_FISH_MAX
            assert eff.big_fish_spawned == 3 and eff.big_fish_dropped == 2
            # an identical later poke edges again once the key has reset
            for _ in range(60 * 10):
                room.step(1)
            assert eff._big == []
            eff.update_config({"big_fish": 0.5})
            room.step(1)
            assert eff.big_fish_spawned == 4
        finally:
            await _close(room)
    _run(main())


def test_the_lull_darkness_darkens_it_too(tmp_path):
    async def main():
        room = await _room(tmp_path, "m", _cfg(big_fish_cross_slow_s=30.0,
                                               big_fish_cross_fast_s=30.0))
        try:
            eff = room.effect
            eff.update_config({"lull_keep": 0})
            eff.update_config({"phase": "lull", "phase_progress": 0.0})
            frames = 240
            for i in range(1, frames + 1):
                eff.update_config({"phase_progress": i / frames})
                room.step(1)
            eff.update_config({"big_fish": 0.5})
            room.step(30)
            assert eff._big and eff._lull_state.get("dark", 1.0) == 0.0
            assert np.asarray(eff.matrix, dtype=np.float32)[..., 1:].max() == 0.0
        finally:
            await _close(room)
    _run(main())


# ── the flare kind and the engine write ─────────────────────────────────────

def test_the_kind_carries_no_knobs():
    from spectra.models.scene import FlareKind
    kind = FlareKind(name="Big Fish", type="big_fish")
    assert kind.min_intensity is None
    for bad in ({"gain": 0.5}, {"hold_ms": 200}, {"jump": "dice"},
                {"params": {"big_fish_size": 0.9}}):
        with pytest.raises(Exception):
            FlareKind(name="bad", type="big_fish", **bad)


MATRIX = "crystal-mapper"
STRIP = "strip-1"


def _scene():
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = [FlareKind(name="Big Fish", type="big_fish")]
    return SceneV2(
        name="Fishy",
        devices=[SceneDeviceConfig(target_kind="virtual", target=MATRIX,
                                   effect_type="fish"),
                 SceneDeviceConfig(target_kind="virtual", target=STRIP,
                                   effect_type="orbits1d")],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds={"Big Fish": 1.0})])})


def _recording_engine(scene):
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor
    from spectra.services.scene_response import ResponseEngine
    executor = RecordingExecutor(clock=lambda: 0.0,
                                 room_controls_load=lambda: rc.RoomControlState())
    conductor = DriftConductor(
        executor=executor, clock=lambda: 0.0, leg_s=20.0,
        intensity=lambda: 1.0, drift_profiles=lambda: {},
        curve_profiles=lambda: {}, gradient_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(), rng=Random(3))
    responder = ResponseEngine(conductor=conductor, executor=executor,
                               rng=Random(5), clock=lambda: 0.0,
                               curve_profiles=lambda: {})
    conductor.on_scene_fire(scene, [
        {"virtual_id": MATRIX, "effect_type": "fish", "config": {},
         "entry_id": scene.devices[0].id, "color_mode": "set"},
        {"virtual_id": STRIP, "effect_type": "orbits1d", "config": {},
         "entry_id": scene.devices[1].id, "color_mode": "set"}])
    return executor, responder


@pytest.mark.parametrize("intensity,written", [
    (0.0, FX.BIG_FISH_POKE_FLOOR), (0.3, 0.3), (1.0, 1.0)])
def test_the_flare_pokes_fish_only_with_its_intensity(intensity, written):
    assert device_model.BIG_FISH_EFFECTS == frozenset({"fish"})
    executor, responder = _recording_engine(_scene())
    record = _run(responder.on_event("flare", intensity))
    pokes = [w for w in executor.writes if "big_fish" in w["params"]]
    assert len(pokes) == 1 and pokes[0]["virtual_id"] == MATRIX
    assert pokes[0]["kind"] == "jump"
    assert pokes[0]["params"]["big_fish"] == pytest.approx(written)
    assert record["big_fish"] == {"intensity": pytest.approx(written),
                                  "virtuals": 1}
    # nothing carries and nothing releases
    assert responder.pending_hold_groups() == []
    assert responder.pending_color_rotate_holds() == []


def test_the_explicit_preview_fires_it_and_the_ruler_shows_the_crossing():
    from spectra.models.scene import FlareKind
    from spectra.services import flare_preview
    kind = FlareKind(name="Big Fish", type="big_fish")
    executor, responder = _recording_engine(_scene())
    rec = _run(responder.fire_kind(kind, 0.7))
    assert rec["result"] == "applied" and rec["big_fish"]["virtuals"] == 1
    for intensity in (0.0, 1.0):
        timeline = _run(flare_preview.build_timeline(_scene(), kind, intensity))
        expect = 1000.0 * FX.big_fish_cross_s(
            max(intensity, FX.BIG_FISH_POKE_FLOOR), 7.0, 2.5)
        assert timeline["effect_animation_ms"] == pytest.approx(expect, abs=0.1)
        assert timeline["animation_end_s"] == pytest.approx(expect / 1000.0,
                                                            abs=1e-3)
        assert timeline["lead_ms"] == 0


def test_the_four_settings_are_registered_for_sonic_and_the_editor():
    params = device_model.effect_params("fish") if hasattr(
        device_model, "effect_params") else None
    registry = json.loads((ROOT / "config/effect_params.json").read_text())
    fish = registry["effects"]["fish"]
    schema = FX.Fish2d.schema()({})
    for key in ("big_fish_brightness", "big_fish_size",
                "big_fish_cross_slow_s", "big_fish_cross_fast_s"):
        assert fish["params"][key]["default"] == schema[key]
        assert fish["defaults"][key] == schema[key]
        assert fish["params"][key]["help_topic"] == "fish-big-fish"
    assert schema["big_fish_brightness"] == 0.6
    # the poke key rides only the flare write, never an editor surface
    assert "big_fish" not in fish["params"]
    assert params is None or "big_fish" not in params


def test_sonic_can_make_the_kind():
    from spectra.services import scene_console
    schema = scene_console.OPERATIONS["set_flare_kind"].input_schema["properties"]
    assert "big_fish" in schema["type"]["enum"]


# ── the migration script ────────────────────────────────────────────────────

def _fish_scene(*, shape_lane=True, effect="fish"):
    from spectra.models.scene import (FlareBand, FlareKind, ParamTarget,
                                      ResponseSpec, SceneDeviceConfig, SceneV2)
    kinds = [FlareKind(name="Fish Swim Burst", type="momentary",
                       params={"swim_burst": ParamTarget(mode="absolute",
                                                         value=1.0)},
                       hold_ms=300),
             FlareKind(name="Reverse Momentarily (500ms)", type="momentary",
                       params={"reverse": ParamTarget(mode="absolute",
                                                      value=1.0)},
                       hold_ms=500),
             FlareKind(name="Colour Jump", type="drift_jump", jump="color_set")]
    lanes = ({"Fish Swim Burst": "Shape",
              "Reverse Momentarily (500ms)": "Shape"} if shape_lane else {})
    bands = [FlareBand(intensity_min=lo, intensity_max=hi,
                       kinds={k.name: 1.0 for k in kinds}, kind_lanes=lanes)
             for lo, hi in ((0.0, 0.35), (0.35, 0.7), (0.7, 1.0))]
    return SceneV2(
        name="Fish",
        devices=[SceneDeviceConfig(target_kind="category", target="Matrix",
                                   effect_type=effect)],
        flare_kinds=kinds, responses={"flare": ResponseSpec(bands=bands)})


def _store(tmp_path, *scenes):
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps(
        {s.id: s.model_dump(mode="json") for s in scenes}, indent=2))
    return path


def _script():
    sys.path.insert(0, str(ROOT / "scripts"))
    import add_fish_big_fish_flare as script
    return script


def test_the_script_pools_it_in_the_shape_lane_and_reverts_exactly(tmp_path):
    from spectra.models.scene import SceneV2
    script = _script()
    scene = _fish_scene()
    other = _fish_scene()
    other.name = "Not Fish"
    path = _store(tmp_path, scene, other)
    original = path.read_text()
    assert script.main(["--scenes-file", str(path)]) == 0       # dry run
    assert path.read_text() == original
    assert script.main(["--scenes-file", str(path), "--apply"]) == 0
    stored = json.loads(path.read_text())
    written = SceneV2(**stored[scene.id])
    big = [k for k in written.flare_kinds if k.name == "Big Fish"]
    assert len(big) == 1 and big[0].type == "big_fish"
    assert big[0].trigger_offset_ms == 0
    for band in written.responses["flare"].bands:
        assert band.kinds["Big Fish"] == 1.0
        pool = sorted(k for k, lane in band.kind_lanes.items()
                      if lane == "Shape")
        assert pool == ["Big Fish", "Fish Swim Burst",
                        "Reverse Momentarily (500ms)"]
    assert stored[other.id] == json.loads(original)[other.id]
    # idempotent
    assert script.main(["--scenes-file", str(path), "--apply"]) == 0
    assert json.loads(path.read_text()) == stored
    assert script.main(["--scenes-file", str(path), "--apply", "--revert"]) == 0
    assert json.loads(path.read_text()) == json.loads(original)


def test_after_the_script_about_one_flare_in_three_is_a_big_fish(tmp_path):
    from spectra.models.scene import SceneV2
    from spectra.services.scene_response import resolve_lane_picks
    script = _script()
    scene = _fish_scene()
    path = _store(tmp_path, scene)
    script.main(["--scenes-file", str(path), "--apply"])
    written = SceneV2(**json.loads(path.read_text())[scene.id])
    band = written.responses["flare"].bands[1]
    declared = {k.name: k for k in written.flare_kinds}
    rng = Random(0)
    counts = {"Big Fish": 0, "Fish Swim Burst": 0,
              "Reverse Momentarily (500ms)": 0}
    n = 3000
    for _ in range(n):
        picked, _rec = resolve_lane_picks(band, rng, declared, 0.5)
        assert "Colour Jump" in picked       # an unpooled kind still fires
        hits = [p for p in picked if p in counts]
        assert len(hits) == 1                # exactly one shape flare
        counts[hits[0]] += 1
    for name, c in counts.items():
        assert c / n == pytest.approx(1 / 3, abs=0.04), name


def test_the_script_refuses_a_band_with_no_shape_lane(tmp_path):
    script = _script()
    path = _store(tmp_path, _fish_scene(shape_lane=False))
    original = path.read_text()
    with pytest.raises(SystemExit, match="no 'Shape' lane"):
        script.main(["--scenes-file", str(path), "--apply"])
    assert path.read_text() == original


def test_the_script_refuses_a_scene_that_does_not_run_fish(tmp_path):
    script = _script()
    path = _store(tmp_path, _fish_scene(effect="orbits"))
    original = path.read_text()
    with pytest.raises(SystemExit, match="no Fish entry"):
        script.main(["--scenes-file", str(path), "--apply"])
    assert path.read_text() == original


def test_the_script_never_overwrites_a_kind_of_another_type(tmp_path):
    from spectra.models.scene import FlareKind
    script = _script()
    scene = _fish_scene()
    scene.flare_kinds.append(FlareKind(name="Big Fish", type="momentary",
                                       gain=1.5))
    path = _store(tmp_path, scene)
    original = path.read_text()
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        script.main(["--scenes-file", str(path), "--apply"])
    assert path.read_text() == original
