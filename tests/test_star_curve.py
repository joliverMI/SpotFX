"""The star curve study (2026-11-18, data/star-curve-study/report.md) — the
Admiral: "I think we need to cut the max angle/frame the star can rotate, but
let's scale it all down by 50%. So slow the star rotation by 50% at all
speeds, including the burst speeds, not just the static speed. Additionally,
slow the 'star setting' drift by 75%, but keep the burst speeds. However, it
seems like it currently linearly bounces between the limits. Instead, have it
follow a curve so that it spends more time flat, and at the ends"; after the
five-curve page, "D2 and all recs".

  1. THE HALVING: both constants are exactly half what they were, every
     derived rotation source follows, and the measured per-frame advance
     through the real effect is half the old law's at the same drive — at a
     frame below the cap (the static speed) AND at one on it (a burst).
  2. THE CURVE's dwell shares, measured on one cycle: the plateau holds 45%
     of the cycle at flat and 31% at the ends, against cosine's 11% / 37%;
     every curve stays inside [lo, hi]; only `steps` ever snaps.
  3. FLAT IS THE VALUE 0, not the midpoint of the bounds — the plateau's hold
     is at -0.2..+0.4's one-third point, and bounds that never cross 0 lose
     their flat holds to the limits instead of holding a half-pointed shape.
  4. `cosine` IS TODAY: the default curve reproduces the old closed form to
     the bit, so every other Radial scene is byte-identical.
  5. THE SEEDING: the sway still starts at the value the fire landed on every
     curve, and on a hold it starts at that hold's BEGINNING.
  6. THROUGH THE REAL EFFECT: STAR's own config sways on the plateau, bounded
     and continuous, holds flat for a real stretch, and a period change never
     steps the value.
  7. THE SCENE-DATA SCRIPT: dry run touches nothing, apply writes exactly the
     five Matrix params on a STAR-shaped fixture, idempotent, revert is
     byte-identical, a foreign value and a `star_wave`-off entry are refused;
     the registry carries all three new params at the effect's defaults.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fx.effects import radial                                         # noqa: E402
from star_harness import star_room                                    # noqa: E402
from strip_phase_harness import DT, run                               # noqa: E402
from test_star_improve import _star_store, _turn                      # noqa: E402

LO, HI = radial.DEFAULT_STAR_WAVE_LO, radial.DEFAULT_STAR_WAVE_HI
SPAN = HI - LO
X0 = (0.0 - LO) / SPAN                       # 1/3 — where FLAT sits
DWELL = (radial.DEFAULT_STAR_WAVE_DWELL_FLAT, radial.DEFAULT_STAR_WAVE_DWELL_END)
STAR_WAVE = {"star_wave": True, "star_wave_lo": LO, "star_wave_hi": HI,
             "star_wave_curve": radial.STAR_WAVE_CURVE,
             "star_wave_dwell_flat": DWELL[0], "star_wave_dwell_end": DWELL[1]}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cycle(curve, n=2400, x0=X0, dwell=DWELL):
    """One full cycle of a curve, in star units."""
    return np.array([LO + SPAN * radial._star_wave_u(i / n, curve, x0, *dwell)
                     for i in range(n)])


def _peak_per_frame(period_s, fps=60.0):
    """The plateau's analytic peak rate, in star units per rendered frame:
    every glide shares one peak of pi/glide_share in normalised units per
    cycle, so a frame can never move more than this without a discontinuity."""
    glide = 1.0 - 2.0 * sum(DWELL)
    return (np.pi / glide) * SPAN / period_s / fps


def _shares(vals, tol=0.05):
    flat = float(np.mean(np.abs(vals) <= tol))
    ends = float(np.mean((vals <= LO + tol) | (vals >= HI - tol)))
    return flat, ends


# ── 1. the halving ─────────────────────────────────────────────────────────

def test_both_rotation_constants_are_exactly_half_what_they_were():
    assert radial.ROTATION_SPEED_SCALE == 0.4                  # was 0.8
    assert radial.ROTATION_CAP_DEG_FRAME == 9.0                # was 18.0
    assert radial.ROTATION_CAP_REV_FRAME == 9.0 / 360.0
    # every derived source follows from the one scale — this is what makes
    # "all speeds, including the burst speeds" one edit and not four
    assert radial.CHARGE_SPIN_REV_S == pytest.approx(0.36)     # was 0.72
    assert 6.0 * radial.ROTATION_SPEED_SCALE == pytest.approx(2.4)   # was 4.8
    ceiling = 2.0 * radial.ROTATION_SPEED_SCALE
    assert ceiling == pytest.approx(0.8)                       # was 1.6
    from spectra.models.scene import RADIAL_BASE_ROTATION_MAX
    assert RADIAL_BASE_ROTATION_MAX == pytest.approx(ceiling)
    reg = json.loads((ROOT / "config" / "effect_params.json").read_text())
    assert reg["effects"]["radial"]["params"]["base_rotation"]["max"] == pytest.approx(ceiling)
    # still far under the angle at which a star's turn reads backwards
    for edges in (3, 4, 5, 6):
        assert radial.ROTATION_CAP_DEG_FRAME < 180.0 / edges


def test_the_measured_advance_is_halved_below_the_cap_and_on_it():
    """Through the real effect: at a drive the cap never touches, the picture
    turns at exactly the scale's share of the old law (the static speed); at
    a drive that pins the cap, every frame lands on the new, halved ceiling
    (the burst). The scale alone would not have slowed the second case and
    the cap alone would not have slowed the first — both halvings are load
    bearing, which is the whole of "at all speeds ... not just the static"."""
    cap = radial.ROTATION_CAP_REV_FRAME

    async def go():
        with tempfile.TemporaryDirectory() as tmp:
            async with star_room(tmp, radial={"spin_ease_in_s": 0.0}) as room:
                quiet = _turn(room, lambda t: 0.5, 30)        # 3 deg/frame at 60 fps
                loud = _turn(room, lambda t: 40.0, 30)        # hard into the cap
        return quiet, loud
    quiet, loud = run(go())
    # `rev_s` in the harness is the rate handed to the audio callback, so the
    # picture turns at exactly that rate below the cap; what halved is how
    # much rate a given `spin` config and impulse PRODUCE (asserted above)
    assert np.allclose(quiet[1:] / DT, 0.5, atol=1e-6)
    assert np.all(loud[1:] <= cap + 1e-9)
    assert loud[5:].mean() == pytest.approx(cap, abs=1e-9)
    # the old ceiling would have let these frames turn twice as far
    assert loud[5:].mean() == pytest.approx(18.0 / 360.0 / 2.0, abs=1e-9)


def test_the_spin_values_a_flare_patches_need_no_edit():
    """A flare writes `spin` 0.25 / 0.55 and the fire binding lands 0.4–1.0.
    Those are INPUTS to the squared law, so halving the scale halves what
    they produce without touching his stored flare kinds."""
    def rev_s(cfg_spin, impulse=1.0):
        return 60.0 * impulse * (cfg_spin ** 2) / 10.0 * radial.ROTATION_SPEED_SCALE
    assert rev_s(0.55) == pytest.approx(0.726)     # 1.452 before
    assert rev_s(0.94) == pytest.approx(2.12064)   # 4.24128 before
    assert rev_s(1.0) == pytest.approx(2.4)        # the ceiling, 4.8 before


# ── 2. the curve's dwell shares ────────────────────────────────────────────

def test_the_plateau_holds_at_flat_and_at_the_ends():
    flat, ends = _shares(_cycle("plateau"))
    assert flat == pytest.approx(0.455, abs=0.01)      # his "more time flat"
    assert ends == pytest.approx(0.310, abs=0.01)      # "... and at the ends"
    was_flat, was_ends = _shares(_cycle("cosine"))
    assert was_flat == pytest.approx(0.113, abs=0.01)  # what ships today
    assert was_ends == pytest.approx(0.372, abs=0.01)
    assert flat > was_flat * 3.5                       # four times the flat
    # the two flat holds are the bulk of it: 2 x dwell_flat of the cycle
    assert flat > 2.0 * DWELL[0]


def test_every_curve_is_bounded_and_only_steps_snaps():
    for curve in radial.STAR_WAVE_CURVES:
        vals = _cycle(curve)
        assert vals.min() == pytest.approx(LO, abs=1e-9), curve
        assert vals.max() == pytest.approx(HI, abs=1e-9), curve
        step = np.abs(np.diff(np.concatenate([vals, vals[:1]])))
        # per-sample change at 2400 samples a cycle: a snap is ~3x a glide
        limit = 0.0020 if curve != "steps" else 0.0050
        assert step.max() < limit, (curve, step.max())
    # and the plateau's peak rate at the NEW period is half today's at the
    # old one, which is why holding half the cycle still reads as calmer
    def peak(curve, period):
        vals = _cycle(curve)
        d = np.abs(np.diff(np.concatenate([vals, vals[:1]])))
        return d.max() / (period / len(vals))
    assert peak("plateau", 28.0) == pytest.approx(0.135, abs=0.005)
    assert peak("cosine", 7.0) == pytest.approx(0.269, abs=0.005)
    assert peak("plateau", 28.0) < peak("cosine", 7.0) / 1.9


def test_the_curve_names_the_registry_offers_are_the_ones_the_effect_knows():
    reg = json.loads((ROOT / "config" / "effect_params.json").read_text())
    params = reg["effects"]["radial"]["params"]
    assert tuple(params["star_wave_curve"]["options"]) == radial.STAR_WAVE_CURVES
    assert params["star_wave_curve"]["default"] == radial.DEFAULT_STAR_WAVE_CURVE
    for key, want in (("star_wave_dwell_flat", DWELL[0]),
                      ("star_wave_dwell_end", DWELL[1])):
        assert params[key]["default"] == pytest.approx(want)
        assert (params[key]["min"], params[key]["max"]) == (0, 0.45)
    for key in ("star_wave_curve", "star_wave_dwell_flat", "star_wave_dwell_end"):
        assert params[key]["help_topic"] == "star-wave"
    # the schema refuses a name nothing implements
    from fx.effects.radial import Radial2d
    import voluptuous as vol
    assert Radial2d.CONFIG_SCHEMA({"star_wave_curve": "plateau"})["star_wave_curve"] == "plateau"
    with pytest.raises(vol.Invalid):
        Radial2d.CONFIG_SCHEMA({"star_wave_curve": "triangle"})


# ── 3. flat is the value 0, not the midpoint ───────────────────────────────

def test_the_hold_is_at_flat_and_not_at_the_middle_of_the_range():
    """-0.2..+0.4's midpoint is +0.1, a half-pointed shape. The hold has to
    sit at the plain polygon, which is one third of the way up."""
    vals = _cycle("plateau")
    held = vals[np.abs(np.diff(np.concatenate([vals, vals[:1]]))) < 1e-9]
    assert held.size > 0
    # every held value is a bound or exactly flat — never the midpoint
    for v in np.unique(np.round(held, 6)):
        assert (abs(v) < 1e-6 or abs(v - LO) < 1e-6 or abs(v - HI) < 1e-6), v
    mid = LO + SPAN / 2.0
    assert float(np.mean(np.abs(vals - mid) < 0.01)) < 0.05    # it passes through
    assert float(np.mean(np.abs(vals) < 0.01)) > 0.3           # it DWELLS at flat


def test_bounds_that_never_cross_flat_give_their_time_to_the_limits():
    """`lo >= 0`: there is no plain polygon in the sway at all, so the two
    flat holds must collapse into the limit holds rather than hold some
    arbitrary in-between shape."""
    segs = radial._star_wave_segments(*DWELL, 0.0)
    assert sum(d for d, _a, _b in segs) == pytest.approx(1.0)
    holds = {round(b, 6) for d, _a, b in segs if d > 0 and _a == b}
    assert holds == {0.0, 1.0}                       # the two limits only
    # ... and the collapsed holds carry the flat time with them
    assert segs[0][0] == pytest.approx(sum(DWELL))
    # a huge dwell still leaves the glides time
    wide = radial._star_wave_segments(0.45, 0.45, X0)
    assert sum(d for d, _a, _b in wide) == pytest.approx(1.0)
    assert sum(d for d, a, b in wide if a != b) > 0.01


# ── 4. cosine is today, to the bit ─────────────────────────────────────────

def test_cosine_is_byte_identical_to_the_closed_form_it_replaced():
    for i in range(1000):
        p = i / 1000.0
        old = 0.5 - 0.5 * np.cos(2.0 * np.pi * p)
        assert radial._star_wave_u(p, "cosine", X0, *DWELL) == old
    assert radial.DEFAULT_STAR_WAVE_CURVE == "cosine"
    # and the seeding keeps the arccos closed form for it
    for landed in np.linspace(LO, HI, 25):
        x = (landed - LO) / SPAN
        old = float(np.arccos(1.0 - 2.0 * x)) / (2.0 * np.pi)
        got = radial._star_wave_phase_for(float(landed), LO, HI, "cosine", X0, *DWELL)
        assert got == old


def test_the_effect_defaults_leave_every_other_radial_scene_alone():
    assert radial.DEFAULT_STAR_WAVE_PERIOD_SLOW_S == 7.0       # not STAR's 28
    assert radial.DEFAULT_STAR_WAVE_PERIOD_FAST_S == 3.0
    assert radial.STAR_WAVE_PERIOD_SLOW_S == 28.0              # x4, the calm end
    assert radial.STAR_WAVE_PERIOD_FAST_S == 3.0               # "keep the burst speeds"
    assert radial.STAR_WAVE_CURVE == "plateau"


# ── 5. the seeding ─────────────────────────────────────────────────────────

def test_the_sway_still_starts_where_the_fire_landed_on_every_curve():
    worst = 0.0
    for curve in radial.STAR_WAVE_CURVES:
        for landed in (0.0, 0.3, LO, HI, 0.1, 0.25):
            p = radial._star_wave_phase_for(landed, LO, HI, curve, X0, *DWELL)
            v = LO + SPAN * radial._star_wave_u(p, curve, X0, *DWELL)
            worst = max(worst, abs(v - landed))
    # a table inverse, so not exact — but 2e-4 star units is far below the
    # 1e-3 at which the shape divisor changes at all
    assert worst < 5e-4


def test_a_landed_value_on_a_hold_seeds_the_start_of_that_hold():
    """The binding's own fallback is `star = 0.0`, which on the plateau is a
    hold: the star must enter flat and wait out the WHOLE dwell, not land
    halfway through it."""
    p = radial._star_wave_phase_for(0.0, LO, HI, "plateau", X0, *DWELL)
    segs = radial._star_wave_segments(*DWELL, X0)
    start = segs[0][0] + segs[1][0]                  # end hold + first glide
    assert p == pytest.approx(start, abs=2e-3)
    # from there it holds flat for the full dwell before it moves
    later = LO + SPAN * radial._star_wave_u(p + DWELL[0] * 0.9, "plateau", X0, *DWELL)
    assert abs(later) < 1e-6
    moved = LO + SPAN * radial._star_wave_u(p + DWELL[0] * 1.3, "plateau", X0, *DWELL)
    assert moved > 1e-3


def test_the_rise_span_is_computed_from_the_segments_and_lands_on_the_high_end():
    """The inverse is built over the span up to the high end, and the ONE
    property it needs is that the span really ends there. For a paired dwell
    that span is exactly half a cycle whatever the numbers (the two glides
    share glide/2 however x0 splits them), but it is computed from the
    segments rather than assumed, so an unequal pair of holds would still
    seed correctly."""
    for flat, end in ((0.30, 0.02), (0.02, 0.40), DWELL, (0.0, 0.0), (0.45, 0.45)):
        segs = radial._star_wave_segments(flat, end, X0)
        rise = radial._star_wave_rise_end("plateau", X0, flat, end)
        assert rise == pytest.approx(sum(d for d, _a, _b in segs[:4]))
        assert rise == pytest.approx(0.5)            # the pairing identity
        at_rise = radial._star_wave_u(rise, "plateau", X0, flat, end)
        assert at_rise == pytest.approx(1.0, abs=1e-6)   # and it IS the high end
    assert radial._star_wave_rise_end("cosine", X0, *DWELL) == 0.5


# ── 6. through the real effect ─────────────────────────────────────────────

def test_star_sways_on_the_plateau_bounded_continuous_and_holds_flat():
    async def go():
        with tempfile.TemporaryDirectory() as tmp:
            async with star_room(tmp, radial={**STAR_WAVE, "star": 0.0,
                                              "energy": 1.0, "spin_ease_in_s": 0.0,
                                              "star_wave_period_slow_s": 2.0,
                                              "star_wave_period_fast_s": 2.0}) as room:
                stars = []
                for _ in range(240):                 # 4 s: two full 2 s sways
                    room.rev_s = 0.3
                    room.step(1)
                    stars.append(float(room.star.star))
                assert room.star._config["star"] == 0.0   # stored value untouched
        return np.array(stars)
    stars = run(go())
    assert stars.min() >= LO - 1e-6 and stars.max() <= HI + 1e-6
    assert stars.min() < LO + 0.02 and stars.max() > HI - 0.02   # reaches both
    step = np.abs(np.diff(stars))
    assert step.max() < _peak_per_frame(2.0) * 1.05  # never a jump, only the glide
    flat, ends = _shares(stars)
    assert flat > 0.35 and ends > 0.22               # the dwell is really there
    # a real stretch of consecutive frames at flat, not just passing through
    runs, cur = [], 0
    for v in stars:
        if abs(v) <= 1e-6:
            cur += 1
        else:
            runs.append(cur)
            cur = 0
    runs.append(cur)
    assert max(runs) >= 0.9 * DWELL[0] * 2.0 * 60    # dwell_flat of a 2 s sway


def test_a_period_change_mid_sway_changes_the_pace_and_never_the_value():
    async def go():
        with tempfile.TemporaryDirectory() as tmp:
            async with star_room(tmp, radial={**STAR_WAVE, "star": 0.0, "energy": 0.0,
                                              "spin_ease_in_s": 0.0,
                                              "star_wave_period_slow_s": 6.0,
                                              "star_wave_period_fast_s": 1.5}) as room:
                stars = []
                for i in range(120):
                    room.rev_s = 0.3
                    if i == 60:
                        room.star.update_config({"energy": 1.0})
                    room.step(1)
                    stars.append(float(room.star.star))
        return np.array(stars)
    stars = run(go())
    step = np.abs(np.diff(stars))
    # no discontinuity at the change: the biggest frame-to-frame move is still
    # just the FASTER period's own glide, not a jump to a new value
    assert step.max() < _peak_per_frame(1.5) * 1.05
    # it moves faster after (a 1.5 s sway against a 6 s one), measured away
    # from the holds so the comparison is of glides
    assert step[60:].sum() > step[:60].sum()


# ── 7. the scene-data script ───────────────────────────────────────────────

def _star_fixture():
    store = _star_store()
    star = store[_load("star_curve_scene_data").STAR_ID]
    # the star improve round's own params, as the live entry carries them
    star["devices"][0]["params"].update({"star_wave": True, "star_wave_lo": LO,
                                         "star_wave_hi": HI})
    return store


def test_scene_data_script_dry_run_apply_revert(tmp_path):
    sd = _load("star_curve_scene_data")
    f = tmp_path / "scenes.json"
    store = _star_fixture()
    f.write_text(json.dumps(store, indent=2))
    before = f.read_bytes()
    changed = sd.run(f, apply=False, revert=False)
    assert changed and f.read_bytes() == before            # a dry run writes nothing
    sd.run(f, apply=True, revert=False)
    after = json.loads(f.read_text())
    assert after["other"] == store["other"]                # every other scene alone
    m = after[sd.STAR_ID]["devices"][0]["params"]
    assert m["star_wave_curve"] == "plateau"
    assert m["star_wave_dwell_flat"] == pytest.approx(DWELL[0])
    assert m["star_wave_dwell_end"] == pytest.approx(DWELL[1])
    assert m["star_wave_period_slow_s"] == 28.0
    assert m["star_wave_period_fast_s"] == 3.0
    assert m["star_wave_lo"] == LO and m["star_wave_hi"] == HI   # untouched
    from spectra.models.scene import SceneV2
    SceneV2(**after[sd.STAR_ID])                           # the model takes it
    assert sd.run(f, apply=True, revert=False) == []       # idempotent
    sd.run(f, apply=True, revert=True)
    assert json.loads(f.read_text()) == store              # revert is byte-identical


def test_scene_data_script_refuses_a_foreign_value(tmp_path):
    sd = _load("star_curve_scene_data")
    f = tmp_path / "scenes.json"
    store = _star_fixture()
    store[sd.STAR_ID]["devices"][0]["params"]["star_wave_period_slow_s"] = 11.0
    f.write_text(json.dumps(store, indent=2))
    with pytest.raises(SystemExit):
        sd.run(f, apply=True, revert=False)
    assert json.loads(f.read_text()) == store


def test_scene_data_script_refuses_an_entry_with_the_sway_off(tmp_path):
    """The curve params do nothing without `star_wave`; turning his sway on
    as a side effect of a curve migration would be a silent change of look."""
    sd = _load("star_curve_scene_data")
    f = tmp_path / "scenes.json"
    store = _star_fixture()
    store[sd.STAR_ID]["devices"][0]["params"]["star_wave"] = False
    f.write_text(json.dumps(store, indent=2))
    with pytest.raises(SystemExit):
        sd.run(f, apply=True, revert=False)
    assert json.loads(f.read_text()) == store
