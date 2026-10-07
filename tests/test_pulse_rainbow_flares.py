"""Pulse, phase 3 of the single-led-power plan: the rainbow walk, the two
Pulse flares (flash, colour flip), a flare kind's minimum intensity, and the
preview.

Four halves:

- THE EFFECT (synthetic, the real class on one pixel): a rainbow walks a
  seventh per solid hit and drifts 2% a bar, a solid colour never walks; a
  flash jumps at once and is back to a tenth in 180 ms, spent from the flash
  budget (with a control that goes red without it); a colour flip turns
  180° at once and returns round the wheel — saturation and value held on
  every frame, with a control showing a straight RGB return would have
  passed through grey.
- THE ENGINE: pulse_flash / pulse_flip reach only Pulse virtuals; the flip's
  minimum intensity is 0.4 and strict; a kind below its minimum leaves its
  lane's pool; the explicit preview says so; the flare-preview ruler shows
  the effect's own animation; and on the real fx pipeline the pokes land on
  the light and in the device preview's frames.
- HIS SONGS (tests/fixtures/pulse — the effect's own audio input recorded
  from his WAVs): rainbow steps land on hits; his authored flares, fired
  through the real response engine, flip only above 0.4 and flash always;
  flares on top of the music never flash past the budget.
- SONIC + THE SCRIPT: set_flare_kind makes the two kinds with their
  defaults; scripts/add_pulse_flares.py touches only a Pulse scene.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pulse_song_harness as h  # noqa: E402
from fx import device_model, facade, headless  # noqa: E402
from fx.effects import pulse as pulse_mod  # noqa: E402

FPS = h.FPS
DT = h.DT
RAINBOW = ("linear-gradient(90deg, #ff0000 0%, #ff7800 16%, #ffc800 33%, "
           "#00ff00 50%, #00c78c 66%, #0078ff 83%, #7800ff 100%)")
ORANGE = "#ff8000"
VID = headless.DEFAULT_VIRTUAL_ID


def _run(coro):
    return asyncio.run(coro)


class Rig:
    """One standalone Pulse on one pixel with its own fixed frame clock;
    audio frame first, then render (the live order)."""

    def __init__(self, **config):
        cfg = {"gradient": "#ff0000", "beat_ms": 500.0}
        cfg.update(config)
        self.e = h.new_effect(cfg)

        def log_sec():
            self.e.now += DT
            self.e.passed = DT

        self.e.log_sec = log_sec
        self.levels: list[float] = []
        self.out: list[np.ndarray] = []
        self.colours: list[np.ndarray] = []
        self.offsets: list[float] = []

    def frame(self, x: float | None = 0.1):
        if x is not None:
            self.e.ingest_signal(x, DT)
        self.e._render()
        self.levels.append(self.e.level)
        self.out.append(self.e.get_pixels()[0].copy())
        self.colours.append(np.array(self.e.shown_colour, dtype=float))
        self.offsets.append(self.e.hue_offset)

    def feed(self, xs):
        for x in xs:
            self.frame(x)

    def settle(self, seconds=3.0, x=0.1):
        self.feed([x] * int(round(seconds * FPS)))

    def write(self, **cfg):
        self.e.update_config(cfg)

    def tween(self, **cfg):
        with self.e.lock:
            self.e._apply_config(cfg, validate=False, fire_event=False)

    def out_level(self) -> np.ndarray:
        return np.max(np.asarray(self.out), axis=1) / 255.0


def _hsv(rgb):
    r, g, b = (float(v) / 255.0 for v in rgb)
    return colorsys.rgb_to_hsv(r, g, b)


# ── the rainbow walk ────────────────────────────────────────────────────────

def test_rainbow_is_the_journeys_own_test():
    assert pulse_mod.chromatic_span_deg(RAINBOW) > 180.0
    assert pulse_mod.chromatic_span_deg("#ff0000") == 0.0
    narrow = "linear-gradient(90deg, #00ff00 0%, #00c78c 100%)"
    assert pulse_mod.chromatic_span_deg(narrow) < 180.0
    # the same answer as the compiler's own measure of a single value
    from spectra.services import color_wheel
    for value in (RAINBOW, narrow, "#ff0000"):
        assert pulse_mod.chromatic_span_deg(value) == pytest.approx(
            color_wheel.value_span_deg(value), abs=0.5)


@pytest.mark.parametrize("gradient", [
    "#ff0000", "linear-gradient(90deg, #00ff00 0%, #00c78c 100%)"])
def test_a_solid_or_narrow_colour_never_walks(gradient):
    r = Rig(gradient=gradient, energy=1.0)
    r.settle(1.0)
    for _ in range(6):
        r.frame(1.0)
        r.settle(0.5)
    assert len(r.e.hits) >= 6
    assert not r.e.steps
    first = r.colours[0]
    assert all(np.allclose(c, first) for c in r.colours)


def test_a_rainbow_steps_a_seventh_on_each_solid_hit():
    r = Rig(gradient=RAINBOW, energy=1.0, rainbow_drift=0.0)
    r.settle(2.0)
    for _ in range(5):
        r.frame(1.0)                      # a hard hit
        r.settle(0.5)                     # > 0.45 beat apart at 120 bpm
    assert len(r.e.steps) == 5
    targets = [t for _a, t in r.e.steps]
    assert np.diff(targets) == pytest.approx([1 / 7] * 4, abs=1e-5)
    assert r.e._walk_pos == pytest.approx(5 / 7, abs=1e-3)   # glided there
    # the colour shown is the strips' own gradient at that position
    expect = np.asarray(r.e.get_gradient_color((5 / 7) % 1.0), dtype=float)
    assert r.colours[-1] == pytest.approx(expect, abs=2.0)


def test_weak_hits_and_crowded_hits_do_not_step():
    r = Rig(gradient=RAINBOW, energy=1.0)
    r.settle(1.0)
    r.e._maybe_step(0.30)                 # weaker than 0.35
    assert not r.e.steps
    r.e._maybe_step(0.80)
    r.frame()                             # one frame later: 0.017 s
    r.e._maybe_step(0.80)                 # inside 0.45 beat (0.225 s)
    assert len(r.e.steps) == 1
    r.settle(0.25)
    r.e._maybe_step(0.80)
    assert len(r.e.steps) == 2


def test_between_hits_it_drifts_two_percent_a_bar():
    r = Rig(gradient=RAINBOW, energy=0.5, beat_ms=500.0)
    r.settle(16.0, x=0.1)                 # 8 bars of 2 s, no hits
    assert not r.e.steps
    assert r.e._walk_target == pytest.approx(8 * 0.02, rel=1e-3)
    assert r.e._walk_pos == pytest.approx(8 * 0.02, abs=0.002)


def test_rainbow_walk_off_holds_the_first_colour():
    r = Rig(gradient=RAINBOW, energy=1.0, rainbow_walk=False)
    r.settle(1.0)
    for _ in range(4):
        r.frame(1.0)
        r.settle(0.5)
    assert not r.e.steps
    assert r.colours[-1] == pytest.approx([255.0, 0.0, 0.0], abs=1e-6)


# ── the flash ───────────────────────────────────────────────────────────────

def test_a_flash_jumps_at_once_and_is_back_to_a_tenth_in_180_ms():
    r = Rig(energy=0.0)
    r.settle(2.0, x=None)
    rest = r.e.level
    assert rest == pytest.approx(0.40, abs=1e-6)
    r.write(flash=1.0)
    r.frame(None)
    assert r.e.level == pytest.approx(rest + 0.45, abs=1e-6)   # this frame
    assert r.e._config["flash"] == 0.0                        # self-reset
    r.feed([None] * int(round(0.180 * FPS)))
    lift = r.e.level - rest
    assert lift == pytest.approx(0.045, abs=0.006)            # a tenth
    r.settle(0.5, x=None)
    assert r.e.level == pytest.approx(rest, abs=1e-3)


def test_a_flash_is_scaled_by_its_strength_and_its_size():
    r = Rig(energy=0.0, flash_size=0.3)
    r.settle(1.0, x=None)
    rest = r.e.level
    r.write(flash=0.5)
    r.frame(None)
    assert r.e.level - rest == pytest.approx(0.15, abs=1e-6)


def test_an_identical_later_flash_edges_again():
    r = Rig(energy=0.0)
    r.settle(1.0, x=None)
    for _ in range(3):
        r.write(flash=0.8)
        r.frame(None)
        assert r.e.flashes[-1][2] > 0.3
        r.settle(1.0, x=None)
    assert len(r.e.flashes) == 3


def test_a_stale_persisted_flash_or_flip_never_fires():
    r = Rig(energy=0.0, flash=0.9, flip=3)
    assert r.e._config["flash"] == 0.0 and r.e._config["flip"] == 0
    r.settle(1.0, x=None)
    r.write(gradient="#00ff00")
    r.settle(0.5, x=None)
    assert max(r.levels) == pytest.approx(0.40, abs=1e-6)
    assert max(r.offsets) == 0.0 and not r.e.flashes


def _flash_train(r: Rig, per_s: float, seconds: float):
    every = int(round(FPS / per_s))
    for k in range(int(seconds * FPS)):
        if k % every == 0:
            r.write(flash=1.0)
        r.frame(0.1)


def test_flash_flares_never_strobe_past_the_budget():
    r = Rig(energy=1.0, flash_size=1.0)
    r.settle(2.0)
    _flash_train(r, 10.0, 4.0)
    assert h.max_rise_per_second(r.out_level()) <= 3.0 + 1e-6
    assert any(landed < wanted - 1e-6 for _t, wanted, landed in r.e.flashes)


def test_the_flash_budget_control_goes_red_without_it():
    r = Rig(energy=1.0, flash_size=1.0, max_flash_rate=20.0)
    r.settle(2.0)
    _flash_train(r, 10.0, 4.0)
    assert h.max_rise_per_second(r.out_level()) > 6.0


def test_the_budget_runs_on_the_render_clock_without_audio():
    """A flash lands with or without audio: with NO audio frames at all,
    the budget window must still expire and flashes keep landing."""
    r = Rig(energy=1.0, flash_size=1.0)
    r.settle(1.0, x=None)
    for _ in range(12):                   # one full flash every 2 s, 24 s
        r.write(flash=1.0)
        r.frame(None)
        r.settle(2.0, x=None)
    assert all(landed > 0.9 for _t, _w, landed in r.e.flashes)


def test_a_flash_in_a_lull_still_lands_black():
    r = Rig(energy=0.5)
    r.settle(2.0)
    r.write(phase="lull", phase_progress=0.0)
    i0 = len(r.levels)
    n = int(1.0 * FPS)
    for k in range(n):
        r.tween(phase_progress=min(1.0, (k + 1) / n))
        if k == n // 2:
            r.write(flash=1.0)
        r.frame(0.1)
    lull = r.levels[i0:]
    assert lull[-1] == pytest.approx(0.0, abs=1e-9)
    assert lull[n // 2] > lull[n // 2 - 1] + 0.1     # the flash showed


# ── the colour flip ─────────────────────────────────────────────────────────

def _flip_run(beat_ms=500.0, colour=ORANGE, **cfg):
    r = Rig(gradient=colour, beat_ms=beat_ms, energy=0.0, **cfg)
    r.settle(1.0, x=None)
    start = len(r.offsets)
    r.write(flip=1)
    r.settle(2.0, x=None)
    return r, start


def test_a_flip_turns_180_at_once_and_returns_round_the_wheel():
    r, i0 = _flip_run()
    offs = np.asarray(r.offsets[i0:])
    assert offs[0] == pytest.approx(180.0)            # the frame it lands
    assert r.e._config["flip"] == 0                    # self-reset
    assert np.all(np.diff(offs) <= 1e-9)               # one way back, no bounce
    schema = pulse_mod.PulseAudioEffect.schema()({})
    span = int(round((schema["flip_hold_s"] + schema["flip_fade_s"]) * FPS))
    assert offs[span] == 0.0 and offs[span - 2] > 0.0  # done at hold + fade
    base_h, base_s, base_v = _hsv(r.colours[i0 - 1])
    h0, _s, _v = _hsv(r.colours[i0])
    assert (h0 - base_h) % 1.0 == pytest.approx(0.5, abs=1e-6)   # complement
    for col, off in zip(r.colours[i0:i0 + span + 1], offs):
        hh, ss, vv = _hsv(col)
        # saturation and value held on every frame: never grey, never white
        assert ss == pytest.approx(base_s, abs=1e-6)
        assert vv == pytest.approx(base_v, abs=1e-6)
        assert (hh - base_h) % 1.0 == pytest.approx((off / 360.0) % 1.0, abs=1e-6)


def test_the_wheel_path_control_a_straight_return_would_go_through_grey():
    """The red control: what the flip must NOT do. A straight RGB line from
    the flipped colour back to the original passes through grey (saturation
    near 0 at the middle) — which is why the flip turns the hue instead."""
    base = np.array([255.0, 128.0, 0.0])
    flipped = pulse_mod.rotate_hue(base, 180.0)
    mid = 0.5 * (base + flipped)
    assert _hsv(mid)[1] < 0.05
    r, i0 = _flip_run()
    sats = [_hsv(c)[1] for c in r.colours[i0:i0 + 25]]
    assert min(sats) > 0.99


def test_the_flip_hold_and_fade_are_fixed_seconds_not_beats():
    """Task 3 (2026-10-06 tuning feedback): the flip's hold+fade are FIXED
    SECONDS, unlike the rest of the effect's timing — two wildly different
    tempos must land the flip's own end at the SAME wall-clock moment."""
    r_fast, i0_fast = _flip_run(beat_ms=250.0)    # 240 bpm
    r_slow, i0_slow = _flip_run(beat_ms=2000.0)   # 30 bpm
    offs_fast = np.asarray(r_fast.offsets[i0_fast:])
    offs_slow = np.asarray(r_slow.offsets[i0_slow:])
    schema = pulse_mod.PulseAudioEffect.schema()({})
    span = int(round((schema["flip_hold_s"] + schema["flip_fade_s"]) * FPS))
    assert offs_fast[span - 2] > 0.0 and offs_fast[span] == 0.0
    assert offs_slow[span - 2] > 0.0 and offs_slow[span] == 0.0
    assert offs_fast[:span].tolist() == pytest.approx(offs_slow[:span].tolist())


def test_a_flip_turns_the_rainbow_walk_colour():
    r = Rig(gradient=RAINBOW, energy=1.0, rainbow_drift=0.0)
    r.settle(1.0)
    r.frame(1.0)
    r.settle(0.3)
    walked = np.array(r.colours[-1])
    r.write(flip=1)
    r.frame(0.1)
    assert (_hsv(r.colours[-1])[0] - _hsv(walked)[0]) % 1.0 == pytest.approx(0.5, abs=0.02)


# ── the model: types and minimum intensity ─────────────────────────────────

def test_pulse_kinds_carry_no_knobs_and_the_flip_defaults_to_0_4():
    from spectra.models.scene import FlareKind
    flash = FlareKind(name="f", type="pulse_flash")
    flip = FlareKind(name="p", type="pulse_flip")
    assert flash.min_intensity is None and flip.min_intensity == 0.4
    assert FlareKind(name="p2", type="pulse_flip", min_intensity=0.6).min_intensity == 0.6
    for bad in ({"gain": 0.5}, {"hold_ms": 200}, {"jump": "dice"},
                {"params": {"flash_size": 0.9}}):
        for t in ("pulse_flash", "pulse_flip"):
            with pytest.raises(Exception):
                FlareKind(name="bad", type=t, **bad)
    assert FlareKind(name="g", type="momentary", gain=1.4).min_intensity is None


def test_minimum_intensity_is_strictly_above():
    from spectra.models.scene import FlareKind
    flip = FlareKind(name="p", type="pulse_flip")
    assert not flip.fires_at(0.0) and not flip.fires_at(0.4)
    assert flip.fires_at(0.4001) and flip.fires_at(1.0)
    assert FlareKind(name="g", type="momentary", gain=1.4).fires_at(0.0)


# ── the engine ──────────────────────────────────────────────────────────────

SINGLE = "single-color-effect"
STRIP = "strip-1"


def _scene(*, lanes=False, extra_kinds=()):
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    kinds = [FlareKind(name="Pulse Flash", type="pulse_flash"),
             FlareKind(name="Pulse Colour Flip", type="pulse_flip"),
             *extra_kinds]
    band_kinds = {k.name: 1.0 for k in kinds}
    kind_lanes = ({"Pulse Flash": "Shape", "Pulse Colour Flip": "Shape"}
                  if lanes else {})
    return SceneV2(
        name="Pulse Flares",
        devices=[SceneDeviceConfig(target_kind="virtual", target=SINGLE,
                                   effect_type="pulse"),
                 SceneDeviceConfig(target_kind="virtual", target=STRIP,
                                   effect_type="orbits1d")],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds=band_kinds,
            kind_lanes=kind_lanes)])})


def _recording_engine(scene, seed=5):
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
                               rng=Random(seed), clock=lambda: 0.0,
                               curve_profiles=lambda: {})
    conductor.on_scene_fire(scene, [
        {"virtual_id": SINGLE, "effect_type": "pulse", "config": {},
         "entry_id": scene.devices[0].id, "color_mode": "set"},
        {"virtual_id": STRIP, "effect_type": "orbits1d", "config": {},
         "entry_id": scene.devices[1].id, "color_mode": "set"}])
    return executor, responder


def _pokes(executor, key):
    return [w for w in executor.writes if key in w["params"]]


@pytest.mark.parametrize("intensity,flips", [
    (0.0, 0), (0.3, 0), (0.4, 0), (0.41, 1), (0.9, 1)])
def test_the_flip_fires_only_above_0_4_and_the_flash_always(intensity, flips):
    from spectra.services import scene_response as sr
    executor, responder = _recording_engine(_scene())
    record = _run(responder.on_event("flare", intensity))
    flashes = _pokes(executor, "flash")
    assert len(flashes) == 1 and flashes[0]["virtual_id"] == SINGLE
    assert flashes[0]["kind"] == "jump"
    assert flashes[0]["params"]["flash"] == pytest.approx(
        sr.pulse_flash_strength(intensity))
    assert len(_pokes(executor, "flip")) == flips
    assert all(w["virtual_id"] == SINGLE for w in _pokes(executor, "flip"))
    if not flips:
        gated = [p for p in record.get("lane_picks", [])
                 if "below_min_intensity" in p]
        assert gated and gated[0]["below_min_intensity"] == ["Pulse Colour Flip"]


def test_the_flash_strength_follows_the_flares_intensity():
    from spectra.services import scene_response as sr
    assert sr.pulse_flash_strength(0.0) == pytest.approx(0.4)
    assert sr.pulse_flash_strength(1.0) == pytest.approx(1.0)
    assert sr.pulse_flash_strength(0.5) == pytest.approx(0.7)
    assert sr.pulse_flash_strength(2.0) == pytest.approx(1.0)


def test_a_kind_below_its_minimum_leaves_its_lane_pool():
    picks = {"flash": 0, "flip": 0}
    for seed in range(40):
        executor, responder = _recording_engine(_scene(lanes=True), seed=seed)
        _run(responder.on_event("flare", 0.3))
        picks["flash"] += len(_pokes(executor, "flash"))
        picks["flip"] += len(_pokes(executor, "flip"))
    assert picks == {"flash": 40, "flip": 0}       # the lane-mate fires
    both = {"flash": 0, "flip": 0}
    for seed in range(40):
        executor, responder = _recording_engine(_scene(lanes=True), seed=seed)
        _run(responder.on_event("flare", 0.9))
        both["flash"] += len(_pokes(executor, "flash"))
        both["flip"] += len(_pokes(executor, "flip"))
    assert both["flash"] + both["flip"] == 40 and min(both.values()) > 5


def test_a_minimum_intensity_gates_any_kind():
    from spectra.models.scene import FlareKind
    spike = FlareKind(name="Spike", type="momentary", gain=1.5, min_intensity=0.5)
    for intensity, fires in ((0.5, False), (0.6, True)):
        executor, responder = _recording_engine(_scene(extra_kinds=[spike]))
        record = _run(responder.on_event("flare", intensity))
        names = [k["name"] for k in record.get("kinds", [])]
        assert ("Spike" in names) is fires


def test_the_explicit_preview_honours_the_minimum_and_says_so():
    from spectra.models.scene import FlareKind
    executor, responder = _recording_engine(_scene())
    flip = FlareKind(name="Pulse Colour Flip", type="pulse_flip")
    rec = _run(responder.fire_kind(flip, 0.3))
    assert rec["result"] == "below_min_intensity" and rec["min_intensity"] == 0.4
    assert not executor.writes
    rec = _run(responder.fire_kind(flip, 0.8))
    assert rec["result"] == "applied" and len(_pokes(executor, "flip")) == 1


def test_the_flare_preview_ruler_shows_the_effects_own_animation(monkeypatch):
    from spectra.models.scene import FlareKind
    from spectra.services import flare_preview, pulse_feed
    monkeypatch.setattr(pulse_feed.feed, "status", lambda: {"beat_ms": 400.0})
    scene = _scene()
    flash = _run(flare_preview.build_timeline(
        scene, FlareKind(name="Pulse Flash", type="pulse_flash"), 0.8))
    assert flash["effect_animation_ms"] == pytest.approx(180.0)
    assert flash["animation_end_s"] == pytest.approx(0.18, abs=1e-3)
    flip = _run(flare_preview.build_timeline(
        scene, FlareKind(name="Pulse Colour Flip", type="pulse_flip"), 0.8))
    # fixed seconds (task 3, 2026-10-06), not beat-scaled: the monkeypatched
    # beat_ms above has no effect on this one
    assert flip["effect_animation_ms"] == pytest.approx((0.5 + 1.0) * 1000.0)
    low = _run(flare_preview.build_timeline(
        scene, FlareKind(name="Pulse Colour Flip", type="pulse_flip"), 0.2))
    assert low["result"] == "below_min_intensity" and low["writes"] == []


# ── the real pipeline, and what the device preview receives ───────────────

def _categories_fixture(tmp_path):
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Singles", "parent_id": None,
               "virtuals": [VID], "effects": ["pulse"], "role": None}}))


def test_pulse_flares_land_on_the_light_and_in_the_device_preview(tmp_path, monkeypatch):
    """FacadeExecutor -> fx.facade -> the real vendored Pulse on a one-pixel
    headless virtual: the response engine's writes land on the next rendered
    frame, and the frame the device preview taps (VIRTUAL_UPDATE pixels,
    encoded by device_preview._facade_frame_payload and by the protocol-2
    stream's SourceFrame) carries exactly what the light shows."""
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    from spectra.services import device_preview, preview_stream
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine

    monkeypatch.setattr(device_model, "CATEGORIES_FILE",
                        tmp_path / "device_categories.json")
    _categories_fixture(tmp_path)
    scene = SceneV2(
        name="P", devices=[SceneDeviceConfig(target_kind="virtual", target=VID,
                                             effect_type="pulse")],
        flare_kinds=[FlareKind(name="F", type="pulse_flash"),
                     FlareKind(name="C", type="pulse_flip")],
        responses={"flare": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds={"F": 1.0, "C": 1.0})])})

    async def main():
        host = await headless.start_headless_host(str(tmp_path / "fx"),
                                                  pixel_count=1, rows=1)
        facade.set_host(host)
        virtual = host.virtuals.get(VID)
        frames = []
        remove = host.events.add_listener(
            lambda ev: frames.append(np.array(ev.pixels, copy=True)),
            headless.Event.VIRTUAL_UPDATE)
        try:
            with headless.fake_clock() as clock:
                config = {"gradient": ORANGE, "beat_ms": 500.0, "energy": 0.0}
                effect = headless.attach_effect(host, virtual, "pulse", config)
                executor = FacadeExecutor(
                    clock=lambda: clock.now,
                    room_controls_load=lambda: rc.RoomControlState())
                conductor = DriftConductor(
                    executor=executor, clock=lambda: clock.now, leg_s=20.0,
                    intensity=lambda: 1.0, drift_profiles=lambda: {},
                    curve_profiles=lambda: {}, gradient_profiles=lambda: {},
                    room_controls=lambda: rc.RoomControlState(), rng=Random(1))
                responder = ResponseEngine(
                    conductor=conductor, executor=executor, rng=Random(2),
                    clock=lambda: clock.now, curve_profiles=lambda: {})
                conductor.on_scene_fire(scene, [{
                    "virtual_id": VID, "effect_type": "pulse", "config": config,
                    "entry_id": scene.devices[0].id, "color_mode": "set"}])
                headless.render_frames(virtual, 30, clock=clock)
                rest = effect.level
                await responder.on_event("flare", 1.0)
                frame = headless.render_frames(virtual, 1, clock=clock)[-1]
                assert effect.level == pytest.approx(rest + 0.45, abs=1e-6)
                assert effect.hue_offset == pytest.approx(180.0)
                assert effect._config["flash"] == 0.0 and effect._config["flip"] == 0
                virtual._fire_update_event(frame)
                await asyncio.sleep(0)            # listeners run on the loop
                tapped = frames[-1]
                # the light: the complement of orange at the flashed level
                comp = pulse_mod.rotate_hue(np.array([255.0, 128.0, 0.0]), 180.0)
                want = comp * effect.level ** 2.2
                assert tapped[0] == pytest.approx(want, abs=1.0)
                # the preview's two encoders carry the same pixel
                payload = device_preview._facade_frame_payload(VID, tapped, host)
                decoded = device_preview._decode_ledfx_pixels(payload["pixels"])
                assert decoded[0] == pytest.approx(np.clip(tapped[0], 0, 255).astype(int), abs=1)
                sf = preview_stream.SourceFrame(
                    seq=1, at=0.0, rgb=np.clip(tapped, 0, 255).astype(np.uint8),
                    layout=preview_stream.DeviceLayout(rows=1, cols=1,
                                                       cell_index=None, cells=1))
                assert list(sf.full()) == list(np.clip(tapped[0], 0, 255).astype(np.uint8))
                # and it settles back: flash gone, colour home (100 frames,
                # not 60 — the flip's hold+fade (1.5s default) is longer
                # than 60 frames/1s, task 3, 2026-10-06)
                headless.render_frames(virtual, 100, clock=clock)
                assert effect.level == pytest.approx(rest, abs=1e-3)
                assert effect.hue_offset == 0.0
        finally:
            remove()
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── his songs ───────────────────────────────────────────────────────────────

SONGS = ["dopamine", "contra", "soypeor"]


@pytest.fixture(scope="module")
def rainbow_runs():
    out = {}
    for slug in SONGS:
        meta, arrays = h.load_fixture(slug)
        tr = h.run(meta, arrays, scale=h.SONGS[slug]["scale"],
                   config={"gradient": RAINBOW})
        out[slug] = (meta, tr)
    return out


@pytest.mark.parametrize("slug", SONGS)
def test_his_songs_rainbow_steps_land_on_hits(rainbow_runs, slug):
    meta, tr = rainbow_runs[slug]
    beat_s = 60.0 / meta["tempo_bpm"]
    hit_t = {round(x[0], 6): x for x in tr.hits}
    assert len(tr.steps) / (tr.t[-1] / 60.0) > 20     # it moves on the beat
    for t, _target in tr.steps:                       # every step IS a solid hit
        hit = hit_t.get(round(t, 6))
        assert hit is not None and hit[1] > pulse_mod.RAINBOW_STEP_MIN_STRENGTH
    gaps = np.diff([t for t, _ in tr.steps])
    assert gaps.min() >= pulse_mod.RAINBOW_MIN_GAP_BEATS * beat_s - DT - 1e-6
    # and the light's travel happens in those jumps: most of the walk's
    # movement comes within 0.2 s after a step, the rest is the slow drift
    move = np.abs(np.diff(tr.walk))
    near = np.zeros(len(move), dtype=bool)
    for t, _ in tr.steps:
        i = int(round(t * FPS))
        near[max(0, i - 2):i + int(0.2 * FPS)] = True
    assert move[near].sum() / move.sum() >= 0.75


def _authored_flare_pokes(meta):
    """Each of his authored flares fired through the REAL response engine
    (pulse_flash + pulse_flip attached to one band): the flare's song time
    (WAV frame, as the harness keeps it), its intensity, and the poke keys
    the engine wrote to the Pulse virtual."""
    out = []
    for t, cls, intensity in meta["events"]:
        if cls != "flare":
            continue
        executor, responder = _recording_engine(_scene())
        _run(responder.on_event("flare", float(intensity)))
        pokes = {}
        for w in executor.writes:
            if w["virtual_id"] == SINGLE:
                pokes.update({k: v for k, v in w["params"].items()
                              if k in ("flash", "flip")})
        out.append((float(t), float(intensity), pokes))
    return out


def _hook(flares):
    queue = sorted(flares)

    def hook(effect, t):
        while queue and queue[0][0] <= t:
            _ft, _it, pokes = queue.pop(0)
            if pokes:
                effect.update_config(pokes)
    return hook


@pytest.mark.parametrize("slug", SONGS)
def test_his_flares_flip_only_above_0_4_and_flash_every_time(slug):
    meta, arrays = h.load_fixture(slug)
    flares = _authored_flare_pokes(meta)
    above = [f for f in flares if f[1] > 0.4]
    assert above and len(above) < len(flares)    # both sides of 0.4 occur
    assert all(("flip" in p) is (i > 0.4) for _t, i, p in flares)
    assert all("flash" in p for _t, _i, p in flares)
    tr = h.run(meta, arrays, scale=h.SONGS[slug]["scale"],
               config={"gradient": ORANGE}, hook=_hook(flares))
    # on the OUTPUT: a flip STARTS (offset jumps to the full angle) exactly
    # at the flares above 0.4, and nowhere else
    off = tr.hue_offset
    starts = [i for i in range(1, len(off)) if off[i] == 180.0 and off[i - 1] < 180.0]
    started_t = [tr.t[i] for i in starts]
    expect = [t for t, i, _p in flares if i > 0.4 and t <= tr.t[-1]]
    # A re-trigger landing WHILE the previous flip is still HELD flat at the
    # full angle (flip_hold_s, 0.5s default — task 3, 2026-10-06) never
    # produces a fresh <180->180 edge: the offset was already 180. One
    # landing during the FADE instead (offset already <180, easing back)
    # DOES still show a fresh jump back up to 180 — it restarts the clock,
    # which reads t=0 < hold on the very next frame.
    flip_hold_s = pulse_mod.PulseAudioEffect.schema()({})["flip_hold_s"]
    visible_expect = []
    for t in expect:
        if visible_expect and t - visible_expect[-1] < flip_hold_s:
            continue
        visible_expect.append(t)
    assert len(started_t) == len(visible_expect)
    for t in visible_expect:
        assert any(abs(s - t) <= 2 * DT for s in started_t)
    assert len(tr.flashes) == len([f for f in flares if f[0] <= tr.t[-1]])


@pytest.mark.parametrize("slug", SONGS)
def test_his_songs_with_flares_never_flash_past_the_budget(slug):
    meta, arrays = h.load_fixture(slug)
    flares = _authored_flare_pokes(meta)
    # his flares plus a dense run of full flashes on top of the music
    dense = [(t, 1.0, {"flash": 1.0}) for t in np.arange(20.0, 40.0, 0.15)]
    tr = h.run(meta, arrays, scale=h.SONGS[slug]["scale"],
               config={"gradient": ORANGE, "flash_size": 1.0},
               hook=_hook(flares + dense))
    assert h.max_rise_per_second(tr.out) <= 3.0 + 1e-6
    shrunk = [f for f in tr.flashes if f[2] < f[1] - 1e-6]
    assert shrunk


# ── Sonic ───────────────────────────────────────────────────────────────────

@pytest.fixture
def scene_store_tmp(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "SCENE_AGENT_LOG_FILE", tmp_path / "scene_agent_log.json")
    monkeypatch.setattr(scfg, "SCENE_BACKUPS_FILE", tmp_path / "scene_backups.json")
    monkeypatch.setattr(scfg, "SCENE_GENESIS_FILE", tmp_path / "scene_genesis.json")
    from spectra.services import scene_store
    scene = _scene()
    scene.flare_kinds = []
    scene.responses["flare"].bands[0].kinds = {}
    scene_store.save(scene)
    return scene.id


def test_sonic_makes_the_pulse_kinds_with_their_defaults(scene_store_tmp):
    from spectra.services import scene_console, scene_store
    sid = scene_store_tmp
    _run(scene_console.apply_flare_kind(sid, name="Flip", type="pulse_flip"))
    _run(scene_console.apply_flare_kind(sid, name="Flash", type="pulse_flash"))
    kinds = {k.name: k for k in scene_store.get_by_id(sid).flare_kinds}
    assert kinds["Flip"].min_intensity == 0.4 and kinds["Flash"].min_intensity is None
    # a minimum, then an unrelated edit keeps it
    _run(scene_console.apply_flare_kind(sid, name="Flip", type="pulse_flip",
                                        min_intensity=0.6))
    _run(scene_console.apply_flare_kind(sid, name="Flip", type="pulse_flip",
                                        trigger_offset_ms=-20))
    flip = next(k for k in scene_store.get_by_id(sid).flare_kinds if k.name == "Flip")
    assert flip.min_intensity == 0.6 and flip.trigger_offset_ms == -20
    listed = scene_console.list_flare_kinds(sid)["flare_kinds"]
    assert {k["name"]: k["min_intensity"] for k in listed} == {"Flip": 0.6, "Flash": None}
    with pytest.raises(scene_console.SceneOpError):
        _run(scene_console.apply_flare_kind(sid, name="Bad", type="pulse_flash",
                                            gain=1.3))


def test_sonics_tool_schema_offers_the_pulse_kinds():
    from spectra.services import scene_console
    schema = scene_console.OPERATIONS["set_flare_kind"].input_schema["properties"]
    assert {"pulse_flash", "pulse_flip"} <= set(schema["type"]["enum"])
    assert schema["min_intensity"] == {"type": "number", "minimum": 0, "maximum": 1}


# ── the script ──────────────────────────────────────────────────────────────

def _store_file(tmp_path, scene):
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps({scene.id: scene.model_dump(mode="json")}, indent=2))
    return path


def _bare_scene(effect: str):
    from spectra.models.scene import (FlareBand, ResponseSpec, SceneDeviceConfig,
                                      SceneV2)
    return SceneV2(
        name="Pulse Test (Orbits V2)",
        devices=[SceneDeviceConfig(target_kind="category", target="Singles",
                                   effect_type=effect)],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=0.5, kinds={}),
            FlareBand(intensity_min=0.5, intensity_max=1.0, kinds={})])})


def test_the_script_declares_and_attaches_on_a_pulse_scene_and_reverts(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import add_pulse_flares as script
    from spectra.models.scene import SceneV2
    scene = _bare_scene("pulse")
    path = _store_file(tmp_path, scene)
    original = path.read_text()
    assert script.main(["--scenes-file", str(path)]) == 0       # dry run
    assert path.read_text() == original
    assert script.main(["--scenes-file", str(path), "--apply"]) == 0
    written = SceneV2(**json.loads(path.read_text())[scene.id])
    assert {k.name: (k.type, k.min_intensity) for k in written.flare_kinds} == {
        "Pulse Flash": ("pulse_flash", None),
        "Pulse Colour Flip": ("pulse_flip", 0.4)}
    for band in written.responses["flare"].bands:
        assert band.kinds == {"Pulse Flash": 1.0, "Pulse Colour Flip": 1.0}
        assert band.kind_lanes == {}
    assert script.main(["--scenes-file", str(path), "--apply", "--revert"]) == 0
    assert json.loads(path.read_text()) == json.loads(original)


def test_the_script_refuses_a_scene_that_does_not_run_pulse(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import add_pulse_flares as script
    path = _store_file(tmp_path, _bare_scene("power"))
    original = path.read_text()
    with pytest.raises(SystemExit, match="no Pulse entry"):
        script.main(["--scenes-file", str(path), "--apply"])
    assert path.read_text() == original
