"""The star improve plan (2026-11-12, data/star-improve-plan/plan.md) — the
Admiral: "I want it to be able to spin from the beginning. It should also
cap the max speed it can spin to 70% of what it is now, but it shouldn't
slow down at lower speeds. Also, the amount of star should dynamically
change with the music ... flares should change the number of edges, but do
it visually smoothly like we have. The melt ... should have more "dark
blobs" ... [the TV] make it work more radially, like the other round
strips (sconces)"; "let's do -.2 to +.4 as the standard range they sway
between. I want it to go through 0".

  1. THE FIRE-TIME DEFECT: a random_sign binding on a param with no
     negative side (radial `spin`, 0..1) never lands the floor any more —
     2,000 seeded fires of STAR's live binding, zero spin == 0 (it was
     ~52%); a genuinely signed param (`star`, -1..1) still flips.
  2. THE EASE-IN: the first second's rotation climbs monotonically to the
     song's own speed; spin_ease_in_s 0 is today frame for frame.
  3. THE CAP: no frame advances faster than 3.36 rev/s however hard the
     audio and the charge push; a frame below the cap is untouched.
  4. THE STAR WAVE: bounded by lo..hi, continuous, never parked, crosses 0
     without a step in the picture larger than the plain turning star's;
     starts at the value the fire landed; off = today.
  5. EDGE MORPH: a random_other target never picks the current count and a
     permanent kind holds it (the real ResponseEngine, through the rig);
     the morph runs.
  6. MELT'S DARK FLOOR: 0 is byte-identical; 0.5 lights fewer pixels.
  7. THE TV RING: a device pixel_map permutes the frame (after the roll),
     a bad map is ignored; the ring table is a permutation that puts the
     strip's angle order round the real layout.
  8. THE SCENE-DATA SCRIPT and THE TV SCRIPT: dry run touches nothing,
     apply changes exactly the planned paths on a STAR-shaped fixture,
     revert restores it byte-identical, a foreign shape is refused.
"""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from random import Random

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model, headless                                 # noqa: E402
from fx.effects import radial                                         # noqa: E402
from spectra.models.binding import ValueBinding                      # noqa: E402
from spectra.models.scene import FlareKind, ParamTarget, SceneV2     # noqa: E402
from spectra.services import binding_resolver as br                  # noqa: E402
from spectra.services.binding_resolver import FireContext            # noqa: E402
from star_harness import STAR, star_room, PALETTE                    # noqa: E402
from strip_phase_harness import DT, Room, run, scene_for             # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. the fire-time defect ────────────────────────────────────────────────

LIVE_SPIN = ValueBinding(bind="signal", signal="trigger_intensity", mode="map",
                         in_min=0, in_max=1, out_min=0.4, out_max=1.0,
                         fallback=0.55, random_sign=True)


def test_random_sign_never_lands_the_floor_of_a_magnitude_param():
    meta = device_model.get_param_meta("radial", "spin")
    kind, lo, hi = br.kind_for_meta(meta)
    assert (kind, lo, hi) == (br.KIND_NUMERIC, 0, 1)
    seen = set()
    for seed in range(2000):
        v = br.apply_binding(LIVE_SPIN, FireContext(0.5, rng=Random(seed)), kind, lo, hi)
        assert v > 0.0, seed
        seen.add(v)
    assert seen == {0.7}          # intensity 0.5 -> 0.4 + 0.5 * 0.6, every time
    for inten in (None, 0.0, 0.9):
        assert br.apply_binding(LIVE_SPIN, FireContext(inten, rng=Random(1)), kind, lo, hi) > 0.0


def test_random_sign_still_flips_a_signed_param():
    star = ValueBinding(bind="signal", signal="random", mode="steps",
                        steps=[{"threshold": 0.0, "value": 0.3}],
                        fallback=0.3, random_sign=True, dice="a")
    meta = device_model.get_param_meta("radial", "star")
    kind, lo, hi = br.kind_for_meta(meta)
    vals = {br.apply_binding(star, FireContext(0.5, rng=Random(s)), kind, lo, hi)
            for s in range(200)}
    assert vals == {0.3, -0.3}


# ── the rig: the live rotation law driven per frame ────────────────────────

CEIL = 6.0 * radial.ROTATION_SPEED_SCALE          # 4.8 rev/s


def _turn(room, rev_s_fn, frames, on_frame=None):
    """Drive Star's rotation the way its audio callback would (rev/s from
    the scripted law) and return the per-frame advance the picture actually
    made (unwrapped, revolutions)."""
    adv = []
    for i in range(frames):
        room.rev_s = float(rev_s_fn(i * DT))
        before = room.star.spin_total
        if on_frame:
            on_frame(i)
        room.step(1)
        d = (room.star.spin_total - before + 0.5) % 1.0 - 0.5
        adv.append(d)
    return np.array(adv)


# ── 2. the ease-in ─────────────────────────────────────────────────────────

def test_entry_eases_up_to_the_songs_speed_over_a_second():
    async def go():
        with tempfile.TemporaryDirectory() as tmp:
            async with star_room(tmp, radial={"spin_ease_in_s": 1.0}) as room:
                adv = _turn(room, lambda t: 1.0, 90)        # a steady 1 rev/s song
        return adv
    adv = run(go())
    per = adv / DT                                             # rev/s per frame
    first = per[1:60]                                          # the first second (frame 0 ungoverned)
    assert first[0] < 0.05
    assert np.all(np.diff(first) >= -1e-9)                     # monotone climb
    assert abs(per[75:].mean() - 1.0) < 0.02                   # the song's own speed after


def test_ease_in_zero_is_today():
    async def go(ease):
        with tempfile.TemporaryDirectory() as tmp:
            async with star_room(tmp, radial={"spin_ease_in_s": ease}) as room:
                return _turn(room, lambda t: 0.6, 30)
    a = run(go(0.0))
    assert np.allclose(a[1:] / DT, 0.6, atol=1e-6)


# ── 3. the cap ─────────────────────────────────────────────────────────────

def test_cap_holds_the_total_advance_and_is_identity_below():
    cap = radial.ROTATION_CAP_REV_S
    assert abs(cap - 0.7 * CEIL) < 1e-9 and abs(cap - 3.36) < 1e-9

    async def go():
        with tempfile.TemporaryDirectory() as tmp:
            async with star_room(tmp, radial={"spin_ease_in_s": 0.0}) as room:
                slow = _turn(room, lambda t: 2.0, 30)
                fast = _turn(room, lambda t: CEIL, 30)           # today's ceiling, all the way
                # the charge spin-up on top of the loud drive
                room.star.update_config({"phase": "charge", "phase_progress": 1.0})
                charged = _turn(room, lambda t: CEIL, 30)
        return slow, fast, charged
    slow, fast, charged = run(go())
    assert np.allclose(slow[1:] / DT, 2.0, atol=1e-6)            # untouched below the cap
    assert np.all(fast[1:] / DT <= cap + 1e-6)
    assert abs(fast[5:].mean() / DT - cap) < 1e-6
    assert np.all(charged / DT <= cap + 1e-6)


def test_cap_clamps_forward_when_a_frame_stall_advances_more_than_half_a_turn():
    """A render stall (dt up to the 0.1s clamp in draw()) combined with a
    loud drive can advance the pattern by more than half a revolution in
    one governed frame. The governor must still clamp FORWARD to +cap*dt —
    never misread the advance's sign and spin the star backward."""
    cap = radial.ROTATION_CAP_REV_S

    async def go():
        with tempfile.TemporaryDirectory() as tmp:
            async with star_room(tmp, radial={"spin_ease_in_s": 0.0}) as room:
                room.rev_s = 2.0
                room.step(2)                       # past the first, ungoverned frame
                eff = room.star
                before = eff.spin_total
                dt = 0.1
                rev_s = 6.0                         # rev_s * dt == 0.6 > half a turn
                eff._frame_adv = rev_s * dt
                eff.spin_total = (before + rev_s * dt) % 1.0
                eff._govern_rotation(dt)
                after = eff.spin_total
        return before, after, dt
    before, after, dt = run(go())
    adv = (after - before + 0.5) % 1.0 - 0.5
    assert adv > 0.0                                # forward, never a misread reversal
    assert abs(adv / dt - cap) < 1e-6                # clamped to exactly the cap


# ── 4. the star wave ───────────────────────────────────────────────────────

WAVE = {"star_wave": True, "star_wave_lo": -0.2, "star_wave_hi": 0.4,
        "star_wave_period_slow_s": 2.0, "star_wave_period_fast_s": 1.0}


def _lit_delta(frames):
    f = np.stack(frames).astype(np.int16)
    return np.abs(np.diff(f, axis=0)).mean(axis=tuple(range(1, f.ndim)))


def test_star_wave_is_bounded_continuous_and_starts_where_the_fire_landed():
    async def go():
        with tempfile.TemporaryDirectory() as tmp:
            async with star_room(tmp, radial={**WAVE, "star": 0.1, "energy": 0.0,
                                               "spin_ease_in_s": 0.0}) as room:
                stars, frames = [], []
                for i in range(150):                           # 2.5 s: more than one 2 s sway
                    room.rev_s = 0.3
                    room.step(1)
                    stars.append(float(room.star.star))
                    frames.append(room.matrix())
                assert room.star._config["star"] == 0.1        # the stored value untouched
        return np.array(stars), frames
    stars, frames = run(go())
    assert abs(stars[0] - 0.1) < 0.02                           # starts at the picked value, heading up
    assert stars[1] > stars[0]
    assert stars.min() >= -0.2 - 1e-6 and stars.max() <= 0.4 + 1e-6
    assert stars.min() < -0.15 and stars.max() > 0.35          # it reaches both ends
    step = np.abs(np.diff(stars))
    assert step.max() < 0.6 / (1.0 * 60) * 3.5                 # never a jump (a cosine's steepest slope)
    assert np.all(step[:140] > 0.0) or (step == 0).sum() < 3   # never parked
    # crossing 0 (the points swap from edge-midpoints to corners) is no
    # bigger a change in the picture than any other frame of the sway
    d = _lit_delta(frames)
    crossing = [i for i in range(1, len(stars) - 1) if stars[i - 1] * stars[i] <= 0.0]
    assert crossing
    at_cross = max(d[max(0, i - 1)] for i in crossing)
    assert at_cross <= np.percentile(d, 90)


def test_star_wave_pace_follows_energy_and_off_is_today():
    async def go(cfg):
        with tempfile.TemporaryDirectory() as tmp:
            async with star_room(tmp, radial={"star": 0.0, "spin_ease_in_s": 0.0, **cfg}) as room:
                out = []
                for _ in range(60):
                    room.rev_s = 0.3
                    room.step(1)
                    out.append(float(room.star.star))
        return np.array(out)
    calm = run(go({**WAVE, "energy": 0.0}))
    loud = run(go({**WAVE, "energy": 1.0}))
    assert loud[8] > calm[8]                                    # a 1 s period climbs faster than a 2 s one
    off = run(go({"star_wave": False}))
    assert np.all(off == 0.0)


# ── 5. Edge Morph ──────────────────────────────────────────────────────────

def test_random_other_target_validates_and_never_repeats():
    t = ParamTarget(mode="random_other", lo=3, hi=6)
    with pytest.raises(ValueError):
        ParamTarget(mode="random_other", lo=4, hi=4)
    from spectra.services.scene_response import ResponseEngine
    eng = ResponseEngine.__new__(ResponseEngine)
    eng._rng = Random(3)
    picks = {eng._roll_other(t, 6) for _ in range(200)}
    assert picks == {3, 4, 5}
    assert eng._roll_other(ParamTarget(mode="random_other", lo=3, hi=4), 3) == 4


def test_edge_morph_flare_changes_the_count_and_holds():
    kind = FlareKind(name="Edge Morph", type="permanent",
                     params={"edges": ParamTarget(mode="random_other", lo=3, hi=6)})

    async def go():
        with tempfile.TemporaryDirectory() as tmp:
            spec = {"radial-dummy": ("melt", 280, 1, {"gradient": PALETTE}),
                    STAR: ("radial", 72 * 37, 37,
                           {"source_virtual": "radial-dummy", "edges": 6, "star": 0.2,
                            "spin": 0.5, "gradient": PALETTE})}
            scene = scene_for({"radial-dummy": "melt", STAR: "radial"}, kinds=[kind])
            async with Room(tmp, spec, scene=scene) as room:
                eff = room.effects[STAR]
                counts = []
                for _ in range(4):
                    await room.flare(0.8)
                    room.step(3)
                    counts.append(int(eff.edges))
                    assert eff._morph is not None or counts[-1] == counts[0]
                    room.step(60)                            # past the 0.6 s morph
                    assert int(eff.edges) == counts[-1]      # it holds
        return counts
    counts = run(go())
    assert all(c in (3, 4, 5, 6) for c in counts)
    assert counts[0] != 6                                       # the first flare left 6
    assert all(a != b for a, b in zip(counts, counts[1:]))      # never the same twice in a row


# ── 6. Melt's dark floor ───────────────────────────────────────────────────

def test_melt_dark_floor_zero_is_today_and_half_is_darker():
    async def go(floor):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"gradient": PALETTE, "speed": 0.2, "reactivity": 0.23, "blur": 0.0}
            if floor is not None:
                cfg["dark_floor"] = floor
            async with Room(tmp, {"s": ("melt", 560, 1, cfg)}) as room:
                room.step(120)
                return np.stack(room.frames["s"][60:])
    plain = run(go(None))
    zero = run(go(0.0))
    half = run(go(0.5))
    assert np.array_equal(plain, zero)
    lit = lambda f: (f.max(axis=2) > 20).mean()                 # noqa: E731
    assert lit(half) < 0.85 * lit(plain)                        # fewer pixels lit ...
    dark = lambda f: (f.max(axis=2) <= 20).mean()               # noqa: E731
    assert dark(half) > 1.5 * dark(plain)                       # ... and real gaps between the blobs
    assert half.max() == pytest.approx(plain.max(), abs=2)      # the peaks stay full


# ── 7. the TV ring ─────────────────────────────────────────────────────────

def test_pixel_map_permutes_the_device_frame_after_the_roll():
    from fx.host import FxHost
    from fx import facade

    async def go():
        with tempfile.TemporaryDirectory() as tmp:
            n = 8
            headless.write_headless_config(tmp, pixel_count=n, rows=1, device_id="tv")
            host = FxHost(tmp)
            await host.start()
            try:
                dev = host.devices.get("tv")
                dev.update_config({"center_offset": 1, "pixel_map": [7, 6, 5, 4, 3, 2, 1, 0]})
                dev._pixels = np.arange(n * 3, dtype=float).reshape(n, 3)
                out = dev.assemble_frame()
                rolled = np.roll(dev._pixels, 1, axis=0)
                assert np.array_equal(out, rolled[::-1])
                dev.update_config({"pixel_map": [1, 2]})       # wrong length: ignored
                assert np.array_equal(dev.assemble_frame(), rolled)
                dev.update_config({"pixel_map": []})
                assert np.array_equal(dev.assemble_frame(), rolled)
            finally:
                facade.set_host(None)
                await host.shutdown()
    asyncio.run(go())


def test_ring_map_is_a_permutation_in_angle_order():
    tv = _load("tv_ring_pixel_map")
    centres = tv.load_layout()
    assert len(centres) == 560
    table = tv.ring_map(centres)
    assert sorted(table) == list(range(560))
    # the LED nearest the top centre shows pixel ~0, the bottom centre ~280
    near = lambda x, y: min(range(560), key=lambda i: (centres[i][0] - x) ** 2 + (centres[i][1] - y) ** 2)  # noqa: E731
    top, bottom = near(0.5, 0.2), near(0.5, 0.8)
    assert table[top] < 10 or table[top] > 550
    assert abs(table[bottom] - 280) < 12
    # physical LEDs 0..199 run right->left along the bottom: clockwise from
    # the top that is INCREASING angle, so the effect pixel index climbs
    assert table[10] < table[190]
    # ... and the left edge (200..259, bottom->top) keeps climbing to the top-left
    assert table[200] < table[259] < table[300]


# ── 8. the scripts ─────────────────────────────────────────────────────────

def _color():
    return {"mode": "set", "color_kind": None, "color_value": None, "bg_color": None, "bg_mode": None}


def _kind(name, type_="permanent", params=None, **kw):
    return {"name": name, "type": type_, "jump": None, "params": params or {}, "gain": 1.0,
            "hold_ms": None, "trigger_offset_ms": 0, "min_intensity": None, "enabled": True, **kw}


def _band(lo, hi, kinds):
    return {"intensity_min": lo, "intensity_max": hi, "curve": "linear", "gain": 1.0,
            "param_patch": {}, "kinds": kinds, "kind_lanes": {}}


def _star_store():
    """STAR as the live store holds it (2026-11-12), the fields the script
    reads, plus a second scene that must stay byte-identical."""
    sd = _load("star_improve_scene_data")
    star_target = dict(sd.STAR_PARAM_TARGET)
    spin_target = {"mode": "absolute", "value": 0.55, "offset": None, "lo": None, "hi": None}
    star = {
        "id": sd.STAR_ID, "name": "STAR", "labels": [],
        "devices": [
            {"id": sd.MATRIX_ENTRY, "target_kind": "category", "target": "Matrix",
             "effect_type": "radial",
             "params": {"polygon": True, "star": copy.deepcopy(sd.OLD_STAR_BINDING),
                        "edges": 6, "twist": 0, "x_offset": 0.5, "y_offset": 0.5, "spin": 0.55},
             "effect_steps": [], "color": _color(), "drift": {}},
            {"id": sd.STRIPS_ENTRY, "target_kind": "category", "target": "Strips",
             "effect_type": "melt", "params": {}, "effect_steps": [], "color": _color(), "drift": {}},
        ],
        "flare_kinds": [
            _kind("Flare patch 0–0.35", params={"spin": {**spin_target, "value": 0.25}}),
            _kind("Flare patch 0.7–1", params={"spin": spin_target, "star": star_target}),
            _kind("Drop patch 0.7–1", params={"spin": spin_target, "star": star_target}),
            _kind("Colour Jump", type_="drift_jump", jump="color_set"),
        ],
        "responses": {
            "flare": {"bands": [
                _band(0.0, 0.35, {"Flare patch 0–0.35": 1.0, "Colour Jump": 1.0}),
                _band(0.35, 0.7, {"Colour Jump": 1.0}),
                _band(0.7, 1.0, {"Flare patch 0.7–1": 1.0, "Colour Jump": 1.0}),
            ], "reroll_dice": False, "color_set_jump": False},
            "drop": {"bands": [_band(0.7, 1.0, {"Drop patch 0.7–1": 1.0})],
                     "reroll_dice": False, "color_set_jump": False},
        },
    }
    other = {"id": "other", "name": "Orbits V2", "labels": [], "devices": [
        {"id": "o1", "target_kind": "category", "target": "Matrix", "effect_type": "orbits",
         "params": {}, "effect_steps": [], "color": _color(), "drift": {}}],
        "flare_kinds": [], "responses": {}}
    return {sd.STAR_ID: star, "other": other}


def test_scene_data_script_dry_run_apply_revert(tmp_path):
    sd = _load("star_improve_scene_data")
    f = tmp_path / "scenes.json"
    store = _star_store()
    f.write_text(json.dumps(store, indent=2))
    before = f.read_bytes()
    changed = sd.run(f, apply=False, revert=False)
    assert changed and f.read_bytes() == before                 # a dry run writes nothing
    sd.run(f, apply=True, revert=False)
    after = json.loads(f.read_text())
    star = after[sd.STAR_ID]
    assert after["other"] == store["other"]
    m = star["devices"][0]["params"]
    assert m["star_wave"] is True and m["star_wave_lo"] == -0.2 and m["star_wave_hi"] == 0.4
    assert m["spin_ease_in_s"] == 1.0
    assert m["star"]["random_sign"] is False and m["star"]["steps"][1]["value"] == 0.3
    assert star["devices"][1]["params"]["dark_floor"] == 0.5
    by = {k["name"]: k for k in star["flare_kinds"]}
    assert "star" not in by["Flare patch 0.7–1"]["params"]
    assert "star" not in by["Drop patch 0.7–1"]["params"]
    assert by["Flare patch 0.7–1"]["params"]["spin"]["value"] == 0.55
    assert by["Edge Morph"]["params"]["edges"]["mode"] == "random_other"
    bands = star["responses"]["flare"]["bands"]
    assert "Edge Morph" not in bands[0]["kinds"]
    assert bands[1]["kinds"]["Edge Morph"] == 1.0 and bands[2]["kinds"]["Edge Morph"] == 1.0
    scene = SceneV2(**star)                                     # the model takes it
    assert any(k.name == "Edge Morph" for k in scene.flare_kinds)
    # every fire now lands star inside the standard range
    from spectra.services import scene_compiler
    for seed in range(50):
        res = scene_compiler.resolve_scene(scene, FireContext(0.5, rng=Random(seed)))
        assert -0.2 <= res.devices[0].params["star"] <= 0.4
    # idempotent, then revert is byte-identical
    assert sd.run(f, apply=True, revert=False) == []
    sd.run(f, apply=True, revert=True)
    assert json.loads(f.read_text()) == store


def test_scene_data_script_refuses_a_foreign_shape(tmp_path):
    sd = _load("star_improve_scene_data")
    store = _star_store()
    store[sd.STAR_ID]["devices"][0]["params"]["star"] = 0.3     # not the known binding
    f = tmp_path / "scenes.json"
    f.write_text(json.dumps(store))
    with pytest.raises(SystemExit):
        sd.run(f, apply=True, revert=False)
    assert json.loads(f.read_text()) == store


def test_tv_ring_script_dry_run_apply_revert(tmp_path):
    tv = _load("tv_ring_pixel_map")
    f = tmp_path / "config.json"
    cfg = {"devices": [{"id": "tv-backlight", "type": "wled",
                        "config": {"name": "WLED", "pixel_count": 560, "center_offset": 90}},
                       {"id": "crystal", "type": "wled", "config": {"name": "Crystal", "pixel_count": 976}}],
           "virtuals": []}
    f.write_text(json.dumps(cfg))
    tv.run(f, apply=False, revert=False)
    assert json.loads(f.read_text()) == cfg
    tv.run(f, apply=True, revert=False)
    after = json.loads(f.read_text())
    d = after["devices"][0]["config"]
    assert d["center_offset"] == 0 and sorted(d["pixel_map"]) == list(range(560))
    assert after["devices"][1] == cfg["devices"][1]
    tv.run(f, apply=True, revert=True)
    back = json.loads(f.read_text())
    assert back["devices"][0]["config"]["center_offset"] == 90
    assert back["devices"][0]["config"]["pixel_map"] == []


def test_energy_feed_reaches_star_with_energy_only():
    from spectra.services import pulse_feed
    assert "radial" in device_model.ENERGY_FED_EFFECTS
    assert pulse_feed.PulseFeed._values_for("radial", {"energy": 0.7, "beat_ms": 500}) == {"energy": 0.7}
    assert pulse_feed.PulseFeed._values_for("pulse", {"energy": 0.7, "beat_ms": 500}) == {"energy": 0.7, "beat_ms": 500}


def test_patch_tolerates_a_values_dict_missing_beat_ms():
    from spectra.services import pulse_feed
    f = pulse_feed.PulseFeed()
    assert f._patch({}, {"energy": 0.6}) == {"energy": 0.6}
    assert f._patch({"energy": 0.6}, {"energy": 0.6}) == {}
    assert f._patch({}, {"energy": 0.6, "beat_ms": 500.0}) == {
        "energy": 0.6, "beat_ms": 500.0}
    assert f._patch({"energy": 0.6, "beat_ms": 500.0},
                    {"energy": 0.6, "beat_ms": 500.0}) == {}


def test_tick_pushes_energy_only_to_a_radial_virtual_without_raising(monkeypatch):
    from spectra.services import pulse_feed
    from spectra.services import room_controls as rc
    from spectra.services import color_journey as cj
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor

    f = pulse_feed.PulseFeed(loader=lambda uri: pulse_feed.SongFeed(uri=uri))
    monkeypatch.setattr(
        f, "values",
        lambda uri, position_ms, genres=(lambda: []): {"energy": 0.6})

    room = [cj.RoomColorState()]
    ex = RecordingExecutor(room_controls_load=lambda: rc.RoomControlState())
    c = DriftConductor(
        executor=ex, drift_profiles=lambda: {}, curve_profiles=lambda: {},
        room_load=lambda: room[0], room_save=lambda st: room.__setitem__(0, st),
        set_cards=lambda: [], gradient_profiles=lambda: {},
        room_controls=lambda: rc.RoomControlState(), rng=Random(1))
    c.on_scene_fire(SceneV2(name="t"), [
        {"virtual_id": STAR, "effect_type": "radial",
         "config": {"gradient": "#ff0000"}, "entry_id": "", "color_mode": "set"}])

    written = asyncio.run(f.tick("spotify:track:star-energy-tick", 1_000, conductor=c))
    assert written == 1
    pushed = c.executor.writes[-1]
    assert set(pushed["params"]) == {"energy"}
    assert c.virtuals[STAR].param_baseline["energy"] == 0.6
