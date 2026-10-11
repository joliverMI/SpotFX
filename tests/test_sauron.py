"""The Sauron effect (fx/effects/sauron.py), its sauron_surge flare kind and
its scene copy script.

The picture itself — the slit on the lattice, the hottest rim, the reach,
the surge's eruption and burn-back, the beat's dilation, the palette sort,
no NaNs, the frame cost — is proven on the real render pipeline and his
crystal's real mask by scripts/check_sauron.py, run here as a subprocess
(it os._exit()s, AGENTS.md's rule for a script rendering through
fx.headless). This file holds the plumbing: the registry, the device-model
sets, the flare kind's shape, the engine write, the preview ruler, Sonic's
reach and the hand-off pairs. The scene copy script's tests are
tests/test_seed_sauron_scene.py (scene data, the sauron-scene skill).
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from random import Random

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fx import device_model  # noqa: E402
from fx.effects import sauron as S  # noqa: E402

HYPE_1 = ("linear-gradient(90deg, rgb(255,0,0) 0%, rgb(255,120,0) 14%, "
          "rgb(255,200,0) 28%, rgb(0,255,0) 42%, rgb(0,199,140) 56%, "
          "rgb(0,0,255) 70%, rgb(128,0,128) 84%, rgb(255,0,178) 98%)")
MID_ICE = "linear-gradient(90deg, rgb(0, 255, 255) 0%, rgb(0, 0, 255) 100%)"


def _run(coro):
    return asyncio.run(coro)


def _order(gradient):
    out = []
    for c, _p in S._stops(gradient) or []:
        if not out or out[-1] != c:
            out.append(c)
    return out


# ── the picture, on the real pipeline ──────────────────────────────────────

def test_check_sauron_passes_on_the_real_pipeline():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_sauron.py"), "--quick"],
        cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
    assert "all checks passed" in proc.stdout


# ── the palette sort (pure) ────────────────────────────────────────────────

def test_auto_sorts_a_rainbow_cold_to_warm_and_everything_else_by_brightness():
    assert S.resolve_palette_sort("auto", HYPE_1) == "warm"
    assert S.resolve_palette_sort("auto", MID_ICE) == "brightness"
    assert S.resolve_palette_sort("authored", HYPE_1) == "authored"
    cols = _order(S.palette_gradient(HYPE_1, "auto"))
    warmths = [S.warmth(c) for c in cols]
    assert warmths == sorted(warmths)
    assert len(cols) == 8                       # every colour kept


def test_brightness_puts_the_brightest_colour_at_the_rim():
    cols = _order(S.palette_gradient(MID_ICE, "auto"))
    assert cols == [(0, 0, 255), (0, 255, 255)]
    lums = [S.luminance(c) for c in _order(
        S.ordered_gradient(HYPE_1, "brightness"))]
    assert lums == sorted(lums)


def test_the_sort_is_the_identity_on_a_dark_to_bright_set_and_a_solid():
    db = ("linear-gradient(90deg, rgb(40,0,0) 0%, rgb(255,0,0) 50%, "
          "rgb(255,255,255) 100%)")
    assert _order(S.palette_gradient(db, "auto")) == _order(db)
    assert S.palette_gradient("#ff4400", "auto") == "#ff4400"
    one = "linear-gradient(90deg, rgb(9,9,9) 0%, rgb(9,9,9) 100%)"
    assert S.palette_gradient(one, "brightness") == one


def test_authored_and_angle_leave_the_set_as_written():
    for how in ("authored", "angle"):
        assert S.palette_gradient(HYPE_1, how) == HYPE_1


def test_a_sorted_gradient_parses_and_keeps_each_colours_share():
    from fx.color import parse_gradient
    out = S.palette_gradient(HYPE_1, "auto")
    parsed = parse_gradient(out)
    pos = [p for _c, p in parsed.colors]
    assert pos[0] == 0.0 and pos[-1] == 1.0 and pos == sorted(pos)


def test_white_counts_as_the_hottest_colour():
    assert S.warmth((255, 255, 255)) > S.warmth((255, 128, 0))
    assert S.warmth((0, 128, 255)) == pytest.approx(-1.0, abs=0.02)


def test_the_effect_samples_the_sorted_curve(tmp_path):
    """The curve GradientEffect builds for this effect is the SORTED one:
    heat 0 (the tips) is the set's darkest colour for Mid - Ice."""
    from fx import headless

    async def main():
        headless.silence_audio()
        host = await headless.start_headless_host(
            str(tmp_path / "h"), pixel_count=72 * 37, rows=37,
            device_id="sauron-curve")
        try:
            v = host.virtuals.get("sauron-curve")
            with headless.fake_clock():
                e = headless.attach_effect(host, v, "sauron",
                                           {"gradient": MID_ICE})
                lo = e.get_gradient_color_vectorized1d([0.0])[0]
                hi = e.get_gradient_color_vectorized1d([1.0])[0]
                assert tuple(int(x) for x in lo) == (0, 0, 255)
                assert tuple(int(x) for x in hi) == (0, 255, 255)
                e.update_config({"palette_sort": "authored"})
                lo = e.get_gradient_color_vectorized1d([0.0])[0]
                assert tuple(int(x) for x in lo) == (0, 255, 255)
        finally:
            await host.shutdown()

    _run(main())


# ── the registry and the device-model sets ─────────────────────────────────

def test_every_setting_is_registered_with_the_schemas_default():
    registry = json.loads((ROOT / "config/effect_params.json").read_text())
    entry = registry["effects"]["sauron"]
    schema = S.Sauron2d.schema()({})
    for key, meta in entry["params"].items():
        if key in ("gradient", "background_color", "background_brightness",
                   "brightness", "frequency_range"):
            continue
        assert meta["default"] == schema[key], key
        assert entry["defaults"][key] == schema[key], key
    for key in ("palette_sort", "pupil_width", "pupil_beat", "core_white",
                "streaks", "flame_speed", "tongues", "sky"):
        assert key in entry["params"]
    assert entry["params"]["palette_sort"]["options"] == S.PALETTE_SORTS
    # the poke and phase keys ride only their dedicated writes
    for key in ("surge", "phase", "phase_progress"):
        assert key not in entry["params"]
    assert "sauron" in registry["morph"]["supported_effects"]
    assert sum(1 for m in entry["params"].values() if m.get("motion")) == 1


def test_the_settled_defaults_are_the_plans():
    d = S.Sauron2d.schema()({})
    assert d["palette_sort"] == "auto"
    assert d["sky"] == 0.14
    assert d["iris_size"] == 0.62 and d["gaze_radius"] == 0.36
    assert d["pupil_size"] == 0.80 and d["pupil_width"] == 0.17
    assert S.SLIT_HEIGHT_BEAT == 0.3


def test_it_is_a_phase_effect_and_the_only_surge_effect():
    assert "sauron" in device_model.PHASE_EFFECTS
    assert device_model.SAURON_SURGE_EFFECTS == frozenset({"sauron"})
    assert device_model.effect_dimension("sauron") == "2d"


def test_eyes_hand_off_partners_treat_sauron_as_they_treat_eye():
    from fx.effects import fish
    from spectra.services import transition_phases as tp
    assert "sauron" in fish.TRANSITION_ADOPTERS
    for a, b in (("sauron", "radial"), ("radial", "sauron"),
                 ("pacman", "sauron"), ("dancer", "sauron"),
                 ("sauron", "dancer")):
        ref = tp.find(a.replace("sauron", "eye"), b.replace("sauron", "eye"))
        got = tp.find(a, b)
        assert got is not None and ref is not None
        assert got.anchor_frac == ref.anchor_frac


# ── the snap threshold's saturating >= is fixed here ───────────────────────

def test_snap_threshold_one_means_never_even_at_a_saturated_impulse(tmp_path):
    from fx import headless

    async def main():
        headless.silence_audio()
        host = await headless.start_headless_host(
            str(tmp_path / "h"), pixel_count=72 * 37, rows=37,
            device_id="sauron-snap")
        try:
            v = host.virtuals.get("sauron-snap")
            with headless.fake_clock():
                e = headless.attach_effect(host, v, "sauron",
                                           {"snap_threshold": 1.0})
                e.impulse = 1.0
                for _ in range(20):
                    e._update_gaze(1 / 60, beat=True)
                    assert e._rush < 1.0
                e.update_config({"snap_threshold": 0.5})
                e._update_gaze(1 / 60, beat=True)
                assert e._rush == 1.0
        finally:
            await host.shutdown()

    _run(main())


# ── the flare kind and the engine write ────────────────────────────────────

def test_the_kind_carries_no_knobs():
    from spectra.models.scene import FlareKind
    kind = FlareKind(name="Sauron Surge", type="sauron_surge")
    assert kind.min_intensity is None
    for bad in ({"gain": 0.5}, {"hold_ms": 200}, {"jump": "dice"},
                {"params": {"flames": 0.9}}):
        with pytest.raises(Exception):
            FlareKind(name="bad", type="sauron_surge", **bad)


MATRIX = "crystal-mapper"
PARTICLES = "particles-1"


def _scene():
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = [FlareKind(name="Sauron Surge", type="sauron_surge")]
    return SceneV2(
        name="Sauron",
        devices=[SceneDeviceConfig(target_kind="virtual", target=MATRIX,
                                   effect_type="sauron"),
                 SceneDeviceConfig(target_kind="virtual", target=PARTICLES,
                                   effect_type="eye")],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0,
            kinds={"Sauron Surge": 1.0})])})


def _recording_engine(scene, blocked=frozenset()):
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
                               curve_profiles=lambda: {},
                               flare_blocked=lambda: frozenset(blocked))
    conductor.on_scene_fire(scene, [
        {"virtual_id": MATRIX, "effect_type": "sauron", "config": {},
         "entry_id": scene.devices[0].id, "color_mode": "set"},
        {"virtual_id": PARTICLES, "effect_type": "eye", "config": {},
         "entry_id": scene.devices[1].id, "color_mode": "set"}])
    return executor, responder


@pytest.mark.parametrize("intensity,written", [
    (0.0, S.SURGE_POKE_FLOOR), (0.4, 0.4), (1.0, 1.0)])
def test_the_flare_pokes_sauron_only_with_its_intensity(intensity, written):
    executor, responder = _recording_engine(_scene())
    record = _run(responder.on_event("flare", intensity))
    pokes = [w for w in executor.writes if "surge" in w["params"]]
    assert len(pokes) == 1 and pokes[0]["virtual_id"] == MATRIX
    assert pokes[0]["kind"] == "jump"
    assert pokes[0]["params"]["surge"] == pytest.approx(written)
    assert record["sauron_surge"] == {"intensity": pytest.approx(written),
                                      "virtuals": 1}
    assert responder.pending_hold_groups() == []
    assert responder.pending_color_rotate_holds() == []


def test_a_flares_off_target_gets_no_surge():
    executor, responder = _recording_engine(_scene(), blocked={MATRIX})
    record = _run(responder.on_event("flare", 0.8))
    assert not [w for w in executor.writes if "surge" in w["params"]]
    assert record["sauron_surge"]["virtuals"] == 0


def test_the_explicit_preview_fires_it_and_the_ruler_shows_the_burn_back():
    from spectra.models.scene import FlareKind
    from spectra.services import flare_preview
    kind = FlareKind(name="Sauron Surge", type="sauron_surge")
    _executor, responder = _recording_engine(_scene())
    rec = _run(responder.fire_kind(kind, 0.7))
    assert rec["result"] == "applied" and rec["sauron_surge"]["virtuals"] == 1
    timeline = _run(flare_preview.build_timeline(_scene(), kind, 1.0))
    expect = 1000.0 * S.surge_visible_s(1.0)
    assert expect == pytest.approx(1000.0 * S.SURGE_TAU * 2.9957, rel=1e-3)
    assert timeline["effect_animation_ms"] == pytest.approx(expect, abs=0.1)
    assert timeline["lead_ms"] == 0
    weak = _run(flare_preview.build_timeline(_scene(), kind, 0.2))
    assert weak["effect_animation_ms"] < timeline["effect_animation_ms"]


def test_sonic_can_make_the_kind():
    from spectra.services import scene_console
    schema = scene_console.OPERATIONS["set_flare_kind"].input_schema["properties"]
    assert "sauron_surge" in schema["type"]["enum"]
    src = (ROOT / "spectra/services/settings_mcp_server.py").read_text()
    assert '"sauron_surge"' in src
