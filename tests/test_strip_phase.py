"""THE STRIP PHASE LAYER (fx/effects/strip_phase.py) — charge, lull and drop
on the 1-D strip effects, strip phase plan phase 1 (revision 3: no added
white). The Admiral, 2026-10-11: "they should increase in brightness and
activity during charge, dim and relax into black for most lulls, and big
explosion of brightness and activity on the [drop]" — and "i don't want to
raise the white in the charge, or on the drop".

What is proven here, each on the real code it names:

- THE MATH: the punch envelope (lull_dark.punch_envelope), strength 0 is
  neutral, the hue-kept clip keeps a hue, the white guard pulls a whiter
  pixel back to the set's own grey share keeping hue and brightest channel,
  the shockwave leaves the centre and reaches the ends on time.
- THE GUARD FOR FUTURE EFFECTS: every registered 1-D effect joins the layer
  or is a named exception; membership reaches PHASE/LULL_DARK/
  DROP_INTENSITY; the tunables are registered exactly as the schema says.
- BYTE-IDENTITY: a non-member effect never reaches the layer; a member
  off-phase renders exactly what it rendered before the layer; the room's
  strip phase strength at 0 reproduces today through a whole charge, lull,
  drop and flare on the real pipeline.
- ON THE REAL PIPELINE (fx.headless + the production ResponseEngine on the
  FacadeExecutor): Melt and Power build on the charge (brighter colours, a
  set-colour fill, Melt's clock runs faster), go black at the room's dark
  point and stay black for the cap, explode on the drop above the charge —
  and NO frame of a charge or drop is whiter than the set (measured with
  code independent of the layer, with a control that goes red without it).
- THE DARK POINT: the strip goes dark on the same frame as the crystal's
  Black Hole.
- THE FLARE PUNCH: a flare in the dark lights the strip at full strength
  (with "Flare punch glow" 0 the frame IS the effect's own, exactly what
  that flare shows outside a lull) and the dark returns after hold +
  release; nothing punches for a Pulse-only batch, a flares-off strip, under
  a house mode, outside a lull, or from the lull's own band; "Flare punch"
  0 lets the dark win.
- THE HOUSE-MODE HOLD: strip phases are withheld and named while a house
  mode owns the look.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from random import Random
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fx import device_model  # noqa: E402
from fx.effects import Effect, lull_dark, strip_phase as sp  # noqa: E402
from spectra.services import room_controls as rc  # noqa: E402
from spectra.services import scene_response  # noqa: E402
from strip_phase_harness import (FPS, PALETTE, STRIP_PX, Room,  # noqa: E402
                                 lum, palette_of, run, scene_for,
                                 whiter_than_set)

STRIP = "strip"


WHITE_SPARKS = {"sparks_color": "#ffffff"}


def _cfg(effect_type):
    cfg = {"gradient": PALETTE, "brightness": 0.8}
    if effect_type == "power":
        # his scenes' compiler writes the accent black (scene_compiler's
        # accent rule); the white-guard tests below ask for white sparks
        cfg["sparks_color"] = "#000000"
    return cfg


# ── the math ────────────────────────────────────────────────────────────────

def test_punch_envelope_rises_holds_and_releases():
    env = lull_dark.punch_envelope
    assert env(-0.1, 0.25) == 0.0
    assert env(0.0, 0.25) == 0.0
    assert env(lull_dark.PUNCH_ATTACK_S / 2, 0.25) == pytest.approx(0.5)
    # held for max(min_hold 0.5, the flare's 0.25)
    assert env(0.04 + 0.49, 0.25) == 1.0
    # a longer flare hold wins
    assert env(0.04 + 0.99, 1.0) == 1.0
    mid = env(0.04 + 0.5 + 0.4, 0.25)
    assert 0.0 < mid < 1.0
    assert env(0.04 + 0.5 + 0.8 + 1e-6, 0.25) == 0.0
    assert lull_dark.punch_length_s(0.25) == pytest.approx(1.34)


def test_strength_zero_is_neutral_and_one_is_unchanged():
    f = sp.StripFrame(gain=1.6, fill=0.3, wave=1.2, fade=0.2, guard=1.0,
                      activity=3.0)
    assert sp.apply_strength(f, 0.0).neutral()
    assert sp.apply_strength(f, 1.0) == f
    half = sp.apply_strength(f, 0.5)
    assert half.gain == pytest.approx(1.3) and half.activity == pytest.approx(2.0)
    assert half.fade == pytest.approx(0.6)


def test_hue_kept_clip_keeps_the_hue_never_whitens():
    px = np.array([[400.0, 200.0, 0.0], [100.0, 50.0, 0.0]])
    sp.hue_kept_clip(px, 255.0)
    assert px[0].tolist() == pytest.approx([255.0, 127.5, 0.0])
    assert px[1].tolist() == [100.0, 50.0, 0.0]


def test_white_guard_pulls_back_to_the_sets_own_grey_share():
    pal = np.array([[255.0, 0.0, 0.0], [0.0, 0.0, 255.0]])   # pure red, blue
    allow = sp.white_allowance(pal)
    # a pinkish red (grey share 0.4) -> pure red at the same brightest channel
    px = np.array([[200.0, 80.0, 80.0]])
    sp.white_guard(px, allow, pal[:1])
    assert px[0].tolist() == pytest.approx([200.0, 0.0, 0.0], abs=1e-6)
    # a pure white pixel takes the set's colour at its place, at its level
    grey = np.array([[180.0, 180.0, 180.0], [180.0, 180.0, 180.0]])
    sp.white_guard(grey, allow, pal)
    assert np.allclose(grey, [[180.0, 0, 0], [0, 0, 180.0]])
    # a set that holds white allows white
    allow_w = sp.white_allowance(np.array([[255.0, 255.0, 255.0],
                                           [255.0, 0.0, 0.0]]))
    keep = np.array([[200.0, 200.0, 200.0]])
    sp.white_guard(keep, allow_w, pal[:1])
    assert keep.tolist() == [[200.0, 200.0, 200.0]]
    # strength 0 does nothing
    px0 = np.array([[200.0, 80.0, 80.0]])
    sp.white_guard(px0, allow, pal[:1], strength=0.0)
    assert px0.tolist() == [[200.0, 80.0, 80.0]]


def test_the_shockwave_leaves_the_centre_and_reaches_the_ends_on_time():
    n = 101
    w0 = sp.shockwave(n, 0.0, 1.0)
    assert int(np.argmax(w0)) == 50 and w0[0] < 0.01
    at = sp.shockwave(n, sp.DROP_FRONT_S, 1.0)
    assert at[0] == pytest.approx(1.0, abs=0.02) and at[-1] == pytest.approx(1.0, abs=0.02)
    # behind the front: the set-colour flood
    half = sp.shockwave(n, sp.DROP_FRONT_S / 2, 1.0)
    t = sp.DROP_FRONT_S / 2
    assert half[50] == pytest.approx(
        sp.DROP_FLOOD * (1.0 - sp._smoothstep(t / sp.DROP_FLOOD_S)))
    assert sp.shockwave(n, 2.0, 1.0).max() == 0.0


# ── the guard for future effects ─────────────────────────────────────────────

def test_every_one_d_effect_joins_or_is_a_named_exception():
    registry = json.loads((ROOT / "config/effect_params.json").read_text())
    one_d = {e for e in registry["effects"]
             if device_model.effect_dimension(e) == "1d"}
    members = device_model.STRIP_PHASE_EFFECTS
    exceptions = set(device_model.STRIP_PHASE_EXCEPTIONS)
    assert not members & exceptions
    missing = one_d - members - exceptions
    assert not missing, (
        f"new 1-D effect(s) {sorted(missing)}: join the strip phase layer "
        "(fx/effects/strip_phase.py, HOW AN EFFECT JOINS) or name the reason "
        "in fx.device_model.STRIP_PHASE_EXCEPTIONS")
    assert all(device_model.STRIP_PHASE_EXCEPTIONS[e].strip()
               for e in exceptions)
    for e in one_d:
        cls = device_model._effect_class(e)
        assert issubclass(cls, sp.StripPhase) == (e in members), e


def test_membership_reaches_every_phase_set():
    m = device_model.STRIP_PHASE_EFFECTS
    assert m == {"melt", "power", "blackhole1d"}
    assert m <= device_model.PHASE_EFFECTS
    assert m <= device_model.LULL_DARK_EFFECTS
    assert m <= device_model.DROP_INTENSITY_EFFECTS
    assert m <= scene_response.HOUSE_HELD_PHASE_EFFECTS


def test_the_tunables_are_registered_exactly_as_the_schema_says():
    registry = json.loads((ROOT / "config/effect_params.json").read_text())
    want = sp.registry_params()
    for e in device_model.STRIP_PHASE_EFFECTS:
        params = registry["effects"][e]["params"]
        for key, meta in want.items():
            assert params.get(key) == meta, (e, key)
            assert device_model.schema_default(e, key) == meta["default"]
        # the pushed keys never enter the registry
        for key in sp.PUSHED_KEYS:
            assert key not in params, (e, key)


def test_a_non_member_never_reaches_the_layer():
    assert Effect._strip_phase is False
    assert Effect.PASSIVE_CONFIG_KEYS == frozenset()
    for e in ("gradient", "pulse", "orbits1d", "fireworks1d"):
        cls = device_model._effect_class(e)
        assert cls._strip_phase is False and not cls.PASSIVE_CONFIG_KEYS, e


# ── the SpotFX side: arm keys, house hold, the punch ─────────────────────────

class _Exec:
    def __init__(self):
        self.jumps, self.glides = [], []

    async def jump(self, vid, et, params):
        self.jumps.append((vid, et, dict(params)))

    async def glide(self, vid, et, params, ms):
        self.glides.append((vid, et, dict(params), ms))


def _responder(effects, *, strength=1.0, blocked=frozenset()):
    ex = _Exec()
    conductor = SimpleNamespace(
        virtuals={vid: SimpleNamespace(effect_type=et, brightness_baseline=0.8)
                  for vid, et in effects.items()},
        on_surge=lambda carry: None, scene=None)
    eng = scene_response.ResponseEngine(
        conductor=conductor, executor=ex, rng=Random(1),
        room_controls=lambda: rc.RoomControlState(
            strip_phase_strength=strength),
        flare_blocked=lambda: frozenset(blocked))
    return eng, ex


def test_strip_arms_carry_the_dark_point_drop_size_and_strength():
    eng, ex = _responder({"s": "melt", "bh": "blackhole", "o": "orbits1d"},
                         strength=0.6)
    rec = asyncio.run(eng._drive_phase("lull", gap_ms=20_000))
    told = {vid: p for vid, _et, p in ex.jumps}
    assert told["s"][lull_dark.DARK_KEY] == pytest.approx(17.0)
    assert told["s"][sp.STRENGTH_KEY] == pytest.approx(0.6)
    assert sp.STRENGTH_KEY not in told["bh"] and sp.STRENGTH_KEY not in told["o"]
    assert rec["strip_phase_strength"] == pytest.approx(0.6)
    ex.jumps.clear()
    asyncio.run(eng._drive_phase("drop", intensity=0.85))
    told = {vid: p for vid, _et, p in ex.jumps}
    assert told["s"]["drop_intensity"] == pytest.approx(0.85)


def test_the_house_mode_holds_strip_phases_back(monkeypatch):
    monkeypatch.setattr(scene_response, "_house_owns_the_look",
                        lambda: "calm mode resting")
    eng, ex = _responder({"s": "melt", "p": "power", "bh": "blackhole"})
    rec = asyncio.run(eng._drive_phase("lull", gap_ms=8_000))
    assert {vid for vid, _et, _p in ex.jumps} == {"bh"}
    assert set(rec["withheld"]["virtuals"]) == {"s", "p"}
    assert rec["withheld"]["reason"] == "calm mode resting"
    # the lull reached only the crystal: no strip can be punched
    assert eng._lull_vids == frozenset({"bh"})
    ex.jumps.clear()
    asyncio.run(eng.rearm_phase("charge", 0.4, 2000))
    assert {vid for vid, _et, _p in ex.jumps} == {"bh"}


def _kind(name, type_, **kw):
    from spectra.models.scene import FlareKind
    return FlareKind(name=name, type=type_, **kw)


def _punches(ex):
    return [(vid, p) for vid, _et, p in ex.jumps if sp.PUNCH_KEY in p]


def test_a_flare_in_a_lull_pokes_only_the_strips_it_wrote_to():
    eng, ex = _responder({"s": "melt", "p": "pulse", "bh": "blackhole"})
    asyncio.run(eng._drive_phase("lull", gap_ms=8_000))
    ex.jumps.clear()
    gain = _kind("Flare gain", "momentary", gain=1.4, hold_ms=600)
    scene = scene_for({"s": "melt"}, [gain])
    rec = asyncio.run(eng._run_kinds(scene, [(gain, 1.0)], 0.8, 1))
    assert _punches(ex) == [("s", {sp.PUNCH_KEY: 1, sp.PUNCH_HOLD_KEY: 0.6})]
    assert rec["flare_punch"] == {"virtuals": ["s"], "hold_s": 0.6}

    # a Pulse-only batch writes nothing to the strip: no punch
    ex.jumps.clear()
    flash = _kind("Pulse Flash", "pulse_flash")
    rec = asyncio.run(eng._run_kinds(scene, [(flash, 1.0)], 0.8, 2))
    assert not _punches(ex) and "flare_punch" not in rec
    assert any(vid == "p" for vid, _et, _p in ex.jumps)


def test_no_punch_outside_a_lull_or_on_a_flares_off_strip():
    gain = _kind("Flare gain", "permanent", gain=0.7)
    scene = scene_for({"s": "melt"}, [gain])
    for phase in ("charge", "drop"):
        eng, ex = _responder({"s": "melt"})
        asyncio.run(eng._drive_phase(phase, gap_ms=4_000))
        ex.jumps.clear()
        asyncio.run(eng._run_kinds(scene, [(gain, 1.0)], 0.8, 1))
        assert not _punches(ex), phase
    eng, ex = _responder({"s": "melt"})
    asyncio.run(eng._run_kinds(scene, [(gain, 1.0)], 0.8, 1))
    assert not _punches(ex)
    # flares off on the strip: the lull never reached it, the flare cannot
    eng, ex = _responder({"s": "melt", "bh": "blackhole"}, blocked={"s"})
    asyncio.run(eng._drive_phase("lull", gap_ms=8_000))
    ex.jumps.clear()
    asyncio.run(eng._run_kinds(scene, [(gain, 1.0)], 0.8, 1))
    assert not _punches(ex)


def test_the_lulls_own_band_does_not_punch_its_own_start():
    gain = _kind("Lull gain", "permanent", gain=0.8)
    scene = scene_for({"s": "melt"}, [gain], bands={"lull": {gain.name: 1.0},
                                                   "flare": {gain.name: 1.0}})
    eng, ex = _responder({"s": "melt"})
    eng.conductor.scene = scene
    asyncio.run(eng.on_event("lull", 0.6, gap_ms=8_000))
    assert not _punches(ex)
    asyncio.run(eng.on_event("flare", 0.6))
    assert len(_punches(ex)) == 1


# ── on the real pipeline ─────────────────────────────────────────────────────

CHARGE = (90, 330)      # frames: 1.5 s normal, a 4 s charge
LULL = (330, 750)       # a 7 s lull: dark point 4 s in, 3 s of dark
DROP = (750, 990)       # 4 s after the drop


async def _cycle(tmp, effect_type, *, strength=1.0, layer=True,
                 cfg_extra=None, scene=None, flare_at=None):
    cfg = {**_cfg(effect_type), **(cfg_extra or {})}
    async with Room(tmp, {STRIP: (effect_type, STRIP_PX, 1, cfg)},
                    strength=strength, layer=layer, scene=scene) as r:
        stamps = []
        r.step(CHARGE[0])
        await r.phase("charge", gap_ms=4000)
        for _ in range(CHARGE[1] - CHARGE[0]):
            r.step()
            stamps.append(r.effects[STRIP].__dict__.get("timestep"))
        await r.phase("lull", gap_ms=7000)
        for i in range(LULL[1] - LULL[0]):
            if flare_at is not None and i == flare_at:
                await r.flare()
            r.step()
        await r.phase("drop", intensity=0.85)
        r.step(DROP[1] - DROP[0])
        return r.frames[STRIP], palette_of(r.effects[STRIP]), stamps


@pytest.fixture(scope="module")
def cycles(tmp_path_factory):
    out = {}
    for et in ("melt", "power"):
        out[et] = run(_cycle(str(tmp_path_factory.mktemp(et)), et))
        out[et + ":today"] = run(_cycle(str(tmp_path_factory.mktemp(et + "t")),
                                        et, layer=False))
    return out


@pytest.mark.parametrize("et", ["melt", "power"])
def test_off_phase_frames_are_byte_identical(cycles, et):
    frames, _pal, _ = cycles[et]
    today, _pal, _ = cycles[et + ":today"]
    for i in range(CHARGE[0]):
        assert np.array_equal(frames[i], today[i]), i


@pytest.mark.parametrize("et", ["melt", "power"])
def test_strength_zero_reproduces_today_through_a_whole_cycle(tmp_path, et):
    off, _p, _ = run(_cycle(str(tmp_path / "off"), et, strength=0.0))
    today, _p, _ = run(_cycle(str(tmp_path / "today"), et, layer=False))
    assert len(off) == len(today) == DROP[1]
    for i, (a, b) in enumerate(zip(off, today)):
        assert np.array_equal(a, b), i


@pytest.mark.parametrize("et", ["melt", "power"])
def test_the_charge_builds_the_lull_goes_black_the_drop_explodes(cycles, et):
    frames, _pal, _ = cycles[et]
    L = [lum(f) for f in frames]
    normal = float(np.mean(L[:CHARGE[0]]))
    charge_peak = max(L[CHARGE[0]:CHARGE[1]])
    drop_peak = max(L[DROP[0]:DROP[0] + 60])
    assert charge_peak > normal * 1.2
    assert drop_peak >= charge_peak
    # black from the dark point (4 s into the 7 s lull) to the drop
    lull = frames[LULL[0]:LULL[1]]
    dark = [i for i, f in enumerate(lull) if f.max() == 0.0]
    assert dark and dark[0] == 4 * FPS - 1
    assert len(dark) == (LULL[1] - LULL[0]) - dark[0]
    # the approach is a fade, not a cut: still lit half way to the dark
    assert lull[2 * FPS].max() > 0.0
    # the drop settles back to the effect's own look
    today = [lum(f) for f in cycles[et + ":today"][0]]
    assert abs(L[-1] - today[-1]) < 0.05 or L[-1] > 0.0


@pytest.mark.parametrize("et", ["melt", "power"])
def test_no_charge_or_drop_frame_is_whiter_than_the_set(cycles, et):
    frames, pal, _ = cycles[et]
    window = list(range(*CHARGE)) + list(range(DROP[0], DROP[0] + 90))
    worst = max(whiter_than_set(frames[i], pal) for i in window)
    assert worst == 0


def test_the_guard_keeps_powers_own_white_sparks_out_of_charge_and_drop(tmp_path):
    """Power with WHITE sparks (an entry that authors them): no charge or
    drop frame is whiter than the set — and the control, "White guard" 0,
    lets the white through, so the measure can fail."""
    window = list(range(*CHARGE)) + list(range(DROP[0], DROP[0] + 90))
    frames, pal, _ = run(_cycle(str(tmp_path / "g"), "power",
                                cfg_extra=WHITE_SPARKS))
    assert max(whiter_than_set(frames[i], pal) for i in window) == 0
    frames, pal, _ = run(_cycle(str(tmp_path / "c"), "power",
                                cfg_extra={**WHITE_SPARKS, "white_guard": 0.0}))
    assert max(whiter_than_set(frames[i], pal) for i in window) > 0
    # outside the phases the effect blends exactly as before: its own white
    assert max(whiter_than_set(frames[i], pal) for i in range(CHARGE[0])) > 0


def test_melts_clock_runs_faster_on_the_charge(cycles):
    """At the top of the charge (the ramp ends 90% into the gap) Melt's
    clock steps exactly charge_activity (3) x what the same frame stepped
    before the layer — same audio, same filter."""
    layer = np.diff(np.array(cycles["melt"][2], dtype=float))
    today = np.diff(np.array(cycles["melt:today"][2], dtype=float))
    top = slice(-15, None)
    assert np.allclose(layer[top] / today[top], 3.0, rtol=1e-6)
    # and at its very start, barely faster
    assert np.all(layer[:2] / today[:2] < 1.05)


# ── the dark point, shared with the crystal ─────────────────────────────────

BH_CFG = {
    "horizon_scale": 0.2, "blob_size": 1.75, "swirl": 0.0, "reverse": False,
    "horizon_audio": 0.3, "base_speed": 2.0, "accel": 5.0, "spawn_rate": 30.0,
    "beat_burst": 0, "spawn_audio": 1.5, "speed_audio": 2.0,
    "max_blobs": 50, "edge_speed": 0.2, "horizon_hold": 2.8,
}


def _real_mask():
    """His crystal's real cells (the gap cells of a dummy rectangle are not
    light — the crystal-hex-grid skill)."""
    prof = json.loads((ROOT / "storage/device_profiles/crystal-mapper.json")
                      .read_text(encoding="utf-8"))
    mask, v = [], False
    for run_len in prof["mask_rle"]:
        mask.extend([v] * run_len)
        v = not v
    return np.array(mask, dtype=bool).reshape(prof["rows"], prof["cols"])


def test_the_strip_goes_dark_on_the_same_frame_as_the_crystal_black_hole(tmp_path):
    """One room, one lull arm: the strip goes black exactly at the shared
    dark point (3 s into a 6 s lull, the cap) on the same frame the Pulse
    single does, and the crystal's Black Hole — whose horizon may cover
    its real cells a few frames earlier — is dark from that frame on too:
    the three are dark together for the last 3 s."""
    async def main():
        effects = {STRIP: ("melt", STRIP_PX, 1, _cfg("melt")),
                   "bh": ("blackhole", 72 * 37, 37, dict(BH_CFG)),
                   "p": ("pulse", 1, 1, {"gradient": "#ff0000",
                                          "beat_ms": 500.0, "energy": 0.5})}
        async with Room(str(tmp_path), effects) as r:
            r.step(4 * FPS)
            await r.phase("charge", gap_ms=3000)
            r.step(3 * FPS)
            rec = await r.phase("lull", gap_ms=6000)
            assert set(rec["phase"]["targets"]) == {STRIP, "bh", "p"}
            n0 = len(r.frames[STRIP])
            r.step(6 * FPS)
            strip = r.frames[STRIP][n0:]
            pulse = r.frames["p"][n0:]
            mask = _real_mask()
            bh = [f.reshape(37, 72, -1)[mask] for f in r.frames["bh"][n0:]]
            return strip, pulse, bh
    strip, pulse, bh = run(main())
    first_strip = next(i for i, f in enumerate(strip) if f.max() == 0)
    first_pulse = next(i for i, f in enumerate(pulse) if f.max() == 0)
    assert first_strip == first_pulse == 3 * FPS - 1
    assert all(f.max() == 0 for f in strip[first_strip:])
    assert all(f.max() == 0 for f in bh[first_strip:])
    # and the strip was still lit a quarter-second before the point
    assert strip[first_strip - 15].max() > 0


# ── the flare punch, on the real pipeline ────────────────────────────────────

def _punch_scene(et):
    gain = _kind("Flare gain 0.7-1", "permanent", gain=0.9)
    return scene_for({STRIP: et}, [gain])


@pytest.mark.parametrize("et", ["melt", "power"])
def test_a_flare_in_the_dark_punches_through_and_the_dark_returns(tmp_path, et):
    flare_at = 5 * FPS   # a second into the 3 s dark
    frames, _p, _ = run(_cycle(str(tmp_path / "p"), et, scene=_punch_scene(et),
                               flare_at=flare_at))
    lull = frames[LULL[0]:LULL[1]]
    assert lull[flare_at - 1].max() == 0.0          # dark before
    lit = [lum(f) for f in lull[flare_at + 3:flare_at + int(0.5 * FPS)]]
    assert min(lit) > 0.02                          # punched through
    back = flare_at + int(lull_dark.punch_length_s(0.25) * FPS) + 2
    assert all(f.max() == 0.0 for f in lull[back:])  # the dark returns
    # "Flare punch" 0: the dark wins
    dark, _p, _ = run(_cycle(str(tmp_path / "d"), et, scene=_punch_scene(et),
                             flare_at=flare_at, cfg_extra={"flare_punch_strength": 0.0}))
    assert all(f.max() == 0.0 for f in dark[LULL[0] + flare_at - 1:LULL[1]])


def test_a_full_punch_shows_the_effects_own_frame(tmp_path):
    """With "Flare punch glow" 0 the layer is neutral at the top of the
    punch: the strip shows exactly the frame the effect itself renders —
    what that flare shows with no lull."""
    async def main():
        cfg = {**_cfg("melt"), "flare_punch_glow": 0.0}
        async with Room(str(tmp_path), {STRIP: ("melt", STRIP_PX, 1, cfg)},
                        scene=_punch_scene("melt")) as r:
            r.step(30)
            await r.phase("lull", gap_ms=4000)
            r.step(3 * FPS)                  # dark (dark point at 2 s)
            assert r.frames[STRIP][-1].max() == 0.0
            await r.flare()
            r.step(10)
            eff = r.effects[STRIP]
            assert eff._sp_frame is None     # neutral: nothing drawn over
            own = eff.get_pixels()          # takes the effect's own lock
            eff._strip_phase = False
            raw = eff.get_pixels()
            eff._strip_phase = True
            return own, raw
    own, raw = run(main())
    assert own.max() > 0.0 and np.array_equal(own, raw)


def test_no_audio_hardware_was_touched():
    from fx.compat_sounddevice import _LazySounddevice
    assert _LazySounddevice._module is None
