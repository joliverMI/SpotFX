"""THE PRE-DROP LOOKS (predrop plan steps 6-9): Fireworks' rockets and
Pulse's burst and dim swell (step 6), Orbits' jitter-and-grow return and
Black Hole's infall ring (step 7), the Fish's dart, Star's outline growing
out of the centre and Sauron's dimmed glare (step 8), and the strips (step
9: the shared layer's twinkle, the Fireworks strip's rockets), on the real
effects, driven by the lull arm the real engine writes
(tests/pre_drop_look_harness.py).

The acceptance (report 3.7, step 6): without a pre-drop each effect is
today's, frame for frame, against its own module before the looks (pinned
out of git); with one, Fireworks' panel is dark until the pre-drop, black in
every frame of the breath before it, and its rockets fire on it and burst on
the drop, its light over the lull below today's; Pulse is truly black
through the breath and through the dark span before the drop (a flare's
flash included), the dark span is a quarter of the gap clamped to 100-500
ms, the spike bursts to full and the vocal intro swells to about 30%, and
the flash budget still holds. Step 7 (the same shape): untold, Orbits and
Black Hole are today's frame for frame against their modules before step
7; told, Orbits dims to its floor by the breath, holds there, and is back at
full on the pre-drop, jittering harder and growing until the drop; Black
Hole is dark from its dark point, black through the breath, and its infall
ring falls from the hex edge to the centre over the gap, in the set's
colours, its light over the lull below today's. Step 8 (the same shape):
untold, the Fish, Star and Sauron are today's frame for frame against their
modules before step 8; told, the Fish's searching lull ends on the pre-drop,
the keeper darts to the centre and waits poised there, its head quivering
harder toward the drop, never dark; Star is dark from its dark point and
black through the breath, its outline grows out of the centre as it spins
up, in the set's colours, and the drop's pieces wear the set as it is at the
drop; Sauron is black through the breath, its lids part to the glare and
hold, flames held down, brightening, and the drop opens them without a slam.
Step 9 (the same shape): untold, every strip is today's frame for frame
against itself AND the shared strip phase layer before step 9; told, a
twinkle strip is its own lull up to the pre-drop, then a sparse twinkle in
the set's colours, each at the effect's own brightness, thickening toward
the drop; the Fireworks strip is dark until the pre-drop, black through the
breath, and its two rockets fire from the ends on it, bright, and burst on
the drop; every strip's light over the lull is below today's.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pre_drop_look_harness as H  # noqa: E402
from fx.effects import fireworks as fw_mod  # noqa: E402
from fx.effects import phase_grammar  # noqa: E402
from fx.effects import pulse as pulse_mod  # noqa: E402

DT = H.DT
EPS = 1e-6
MASK = H.crystal_real_mask()


def _pinned(module):
    try:
        return H.load_pinned(module, f"{module}_prelook", "pre_drop")
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _fw(tmp_path, effect_type, arms, **kw):
    return H.run_async(H.fireworks_run(tmp_path, effect_type, arms, **kw))


def _today(arms, effect_type):
    return {k: H.todays_arm(a, effect_type) for k, a in arms.items()}


# ═══ Fireworks ═════════════════════════════════════════════════════════════

FLARE_IN_LULL = {("lull", 60): {"burst_rockets": 2}}


def test_an_untold_fireworks_is_todays_frame_for_frame(tmp_path):
    pinned = _pinned("fireworks")
    arms = H.engine_arms("fireworks", 3.2)          # no pre-drop: NOT_TOLD
    now = _fw(tmp_path, "fireworks", arms, pokes=FLARE_IN_LULL)
    then = _fw(tmp_path, pinned, _today(arms, "fireworks"), pokes=FLARE_IN_LULL)
    assert len(now.frames) == len(then.frames)
    assert all(np.array_equal(a, b) for a, b in zip(now.frames, then.frames))
    assert max(i["rockets"] for i in now.info) == fw_mod.LULL_ROCKETS


def _told_fw(tmp_path, lull_s=3.2, gap_s=0.8, kind="spike", pokes=None):
    at = lull_s - gap_s
    arms = H.engine_arms("fireworks", lull_s, at_s=at, gap_s=gap_s, kind=kind)
    p = arms["lull"].params
    breath_at = p[phase_grammar.BREATH_AT_KEY]
    assert breath_at + p[phase_grammar.BREATH_KEY] == pytest.approx(at)
    return _fw(tmp_path, "fireworks", arms, lull_s=lull_s, pokes=pokes), at, breath_at


def test_a_told_lull_is_dark_until_the_pre_drop_and_black_through_the_breath(tmp_path):
    run, at, breath_at = _told_fw(tmp_path)
    lull = H.lull_frames(run)
    before = [(t, f, i) for t, f, i in lull if t < at - EPS]
    assert all(i["rockets"] == 0 for _, _, i in before), "no rockets before it"
    breath = [f for t, f, _ in before if t >= breath_at + DT - EPS]
    assert breath and all(float(f.max()) == 0.0 for f in breath), \
        "black in every frame of the breath"


def test_the_rockets_fire_on_the_pre_drop_and_burst_on_the_drop(tmp_path):
    run, at, _ = _told_fw(tmp_path)
    lull = H.lull_frames(run)
    t0, _, i0 = next((t, f, i) for t, f, i in lull if i["rockets"])
    assert at - EPS <= t0 <= at + DT + EPS, "the look starts on the pre-drop"
    assert i0["rockets"] == fw_mod.LULL_ROCKETS
    tail = [i for t, _, i in lull if t >= t0]
    assert all(i["rockets"] == fw_mod.LULL_ROCKETS for i in tail)
    assert min(i["rocket_bright"] for i in tail) >= \
        1.0 - fw_mod.pre_drop_rocket_fade(0.8) - EPS, "they stay bright"
    assert fw_mod.pre_drop_rocket_fade(0.8) == pytest.approx(0.25)
    assert tail[-1]["pd_frac"] == pytest.approx(1.0, abs=2 * DT / 0.8)
    drop = [i for (ph, _), i in zip(run.phase, run.info) if ph == "drop"]
    assert drop[0]["rockets"] == 0 and drop[0]["n"] > 0, "burst on the drop"


def test_a_vocal_intro_flies_the_rockets_over_the_whole_entry(tmp_path):
    # Dopamine drop 1: the lull 6.0 s before the drop, the entry 3.3 s
    run, at, _ = _told_fw(tmp_path, lull_s=6.0, gap_s=3.3, kind="intro")
    lull = H.lull_frames(run)
    t0 = next(t for t, _, i in lull if i["rockets"])
    assert at - EPS <= t0 <= at + DT + EPS
    fracs = [i["pd_frac"] for t, _, i in lull if t >= t0]
    assert fracs[0] < 0.01 and fracs[-1] == pytest.approx(1.0, abs=0.01)
    assert all(b >= a for a, b in zip(fracs, fracs[1:]))


def test_a_flare_landing_in_the_breath_is_swallowed(tmp_path):
    # the breath is 2.0-2.4 s into a 3.2 s lull; a two-burst flare at 2.2 s
    run, at, breath_at = _told_fw(tmp_path, pokes={("lull", 132): {"burst_rockets": 2}})
    breath = [f for t, f, _ in H.lull_frames(run)
              if breath_at + DT - EPS <= t < at - EPS]
    assert all(float(f.max()) == 0.0 for f in breath)


@pytest.mark.parametrize("lull_s,gap_s,kind", [(3.2, 0.8, "spike"),
                                               (2.4, 2.0, "spike"),
                                               (3.2, 2.0, "spike"),
                                               (6.0, 3.3, "intro")])
def test_the_light_over_the_lull_is_below_todays(tmp_path, lull_s, gap_s, kind):
    told = H.engine_arms("fireworks", lull_s, at_s=lull_s - gap_s, gap_s=gap_s,
                         kind=kind)
    plain = H.engine_arms("fireworks", lull_s)
    with_pd = _fw(tmp_path, "fireworks", told, lull_s=lull_s)
    today = _fw(tmp_path, "fireworks", plain, lull_s=lull_s)
    lit = [sum(H.light(f, MASK) for _, f, _ in H.lull_frames(r))
           for r in (with_pd, today)]
    assert lit[0] < lit[1], lit


# ═══ Pulse ═════════════════════════════════════════════════════════════════

PULSE_POKES = {("lull", 30): {"flash": 1.0},
               ("lull", 120): {"flare_punch": 1, "flare_punch_hold_s": 0.4}}


def test_an_untold_pulse_is_todays_frame_for_frame():
    pinned = _pinned("pulse")
    arms = H.engine_arms("pulse", 3.2)
    now = H.pulse_run(arms, pokes=PULSE_POKES)
    then = H.pulse_run(_today(arms, "pulse"), module=pinned, pokes=PULSE_POKES)
    assert [i["level"] for i in now.info] == [i["level"] for i in then.info]
    assert all(np.array_equal(a, b) for a, b in zip(now.frames, then.frames))


def _told_pulse(lull_s=3.2, gap_s=0.8, kind="spike", pokes=None, look=None):
    at = lull_s - gap_s
    arms = H.engine_arms("pulse", lull_s, at_s=at, gap_s=gap_s, kind=kind)
    if look is not None:
        arms["lull"].params["pre_drop_look"] = look
    p = arms["lull"].params
    return (H.pulse_run(arms, lull_s=lull_s, pokes=pokes), at,
            p[phase_grammar.BREATH_AT_KEY])


def _levels(run, start, stop):
    return [(t, i["level"]) for t, _, i in H.lull_frames(run)
            if start - EPS <= t < stop - EPS]


@pytest.mark.parametrize("gap_s", [0.35, 0.627, 0.8, 2.0])
def test_a_spike_bursts_fades_and_is_dark_for_its_span(gap_s):
    lull_s = 3.2
    run, at, breath_at = _told_pulse(lull_s, gap_s)
    assert all(lv == 0.0 for _, lv in _levels(run, breath_at + DT, at)), \
        "black through the breath"
    gap = _levels(run, at, lull_s + DT)
    peak_t, peak = max(gap, key=lambda x: x[1])
    assert peak >= 0.99 and peak_t <= at + 2 * DT + EPS, "full on the pre-drop"
    lit = [t for t, lv in gap if lv > 0.0]
    dark = lull_s - (lit[-1] + DT)                   # the black before the drop
    assert dark == pytest.approx(pulse_mod.pre_drop_dark_s(gap_s), abs=DT + EPS)
    falling = [lv for t, lv in gap if peak_t <= t <= lit[-1]]
    assert all(b <= a + EPS for a, b in zip(falling, falling[1:])), "a fade"


def test_the_dark_span_is_a_quarter_of_the_gap_clamped():
    assert pulse_mod.pre_drop_dark_s(2.0) == pytest.approx(0.5)
    assert pulse_mod.pre_drop_dark_s(0.627) == pytest.approx(0.15675)
    assert pulse_mod.pre_drop_dark_s(0.35) == pytest.approx(0.1)
    assert pulse_mod.pre_drop_dark_s(3.3) == pytest.approx(0.5)


def test_a_flash_in_the_breath_or_the_dark_span_stays_black():
    lull_s, gap_s = 3.2, 2.0                        # breath 0.8-1.2, dark 2.7-3.2
    pokes = {("lull", 60): {"flash": 1.0},          # 1.0 s: the breath
             ("lull", 174): {"flash": 1.0},         # 2.9 s: the dark span
             ("lull", 186): {"flare_punch": 1, "flare_punch_hold_s": 0.3}}
    run, at, breath_at = _told_pulse(lull_s, gap_s, pokes=pokes)
    assert all(lv == 0.0 for _, lv in _levels(run, breath_at + DT, at))
    dark_from = lull_s - pulse_mod.pre_drop_dark_s(gap_s)
    assert all(lv == 0.0 for _, lv in _levels(run, dark_from + DT, lull_s))


def test_a_vocal_intro_swells_to_its_ceiling_then_goes_dark():
    lull_s, gap_s = 6.0, 3.295                      # Dopamine drop 1
    run, at, breath_at = _told_pulse(lull_s, gap_s, kind="intro")
    assert all(lv == 0.0 for _, lv in _levels(run, breath_at + DT, at))
    gap = [lv for _, lv in _levels(run, at, lull_s + DT)]
    assert max(gap) <= pulse_mod.PRE_DROP_SWELL_TOP + EPS
    assert max(gap) >= pulse_mod.PRE_DROP_SWELL_TOP * 0.95
    dark_from = lull_s - pulse_mod.pre_drop_dark_s(gap_s)
    assert all(lv == 0.0 for _, lv in _levels(run, dark_from + DT, lull_s))


@pytest.mark.parametrize("kind,top", [("spike", 1.0),
                                      ("intro", pulse_mod.PRE_DROP_SWELL_TOP)])
def test_a_look_pulse_does_not_know_plays_the_kinds_own(kind, top):
    run, at, _ = _told_pulse(3.2, 0.8, kind=kind, look="")
    peak = max(lv for _, lv in _levels(run, at, 3.2 + DT))
    assert peak == pytest.approx(top, abs=0.02)


@pytest.mark.parametrize("gap_s,kind", [(0.35, "spike"), (0.8, "spike"),
                                        (2.0, "spike"), (3.3, "intro")])
def test_the_flash_budget_still_holds(gap_s, kind):
    lull_s = max(3.2, gap_s + 1.0)
    run, _, _ = _told_pulse(lull_s, gap_s, kind=kind)
    lins = [i["lin"] for i in run.info]
    rises = [max(0.0, b - a) for a, b in zip(lins, lins[1:])]
    window = int(round(1.0 / DT))
    cap = pulse_mod.PulseAudioEffect.CONFIG_SCHEMA({})["max_flash_rate"]
    worst = max(sum(rises[k:k + window]) for k in range(len(rises)))
    assert worst <= cap + 1e-6, worst


# ═══ Step 7: Orbits and Black Hole ═════════════════════════════════════════

from fx.effects import blackhole as bh_mod  # noqa: E402
from fx.effects import orbits as ob_mod  # noqa: E402

CRYSTAL_CFG = H.STEP7_CFG
# a flare's ordinary write in the lull (no punch): the untold path carries it
FLARE_WRITE = {("lull", 60): {"brightness": 0.7},
               ("lull", 120): {"brightness": 1.0}}
GAPS7 = [(3.2, 0.8, "spike"), (3.2, 2.0, "spike"), (6.0, 3.3, "intro")]


def _pinned7(module):
    try:
        return H.load_pinned(module, f"{module}_prelook7",
                             H.STEP7_LACKS[module], ref=H.STEP7_REF)
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _run7(tmp_path, effect_type, arms, effect=None, **kw):
    cfg = CRYSTAL_CFG[effect or effect_type]
    return H.run_async(H.crystal_run(tmp_path, effect_type, arms, cfg, **kw))


def _told7(tmp_path, effect, lull_s=3.2, gap_s=0.8, kind="spike"):
    arms = H.engine_arms(effect, lull_s, at_s=lull_s - gap_s, gap_s=gap_s,
                         kind=kind)
    return _run7(tmp_path, effect, arms, lull_s=lull_s)


def _segment(run, name):
    return [(t, f, inf) for (ph, t), f, inf in zip(run.phase, run.frames,
                                                   run.info)
            if ph == "lull" and inf["segment"] == name]


def _lull_light(run):
    return sum(H.light(f, MASK) for (ph, _t), f in zip(run.phase, run.frames)
               if ph == "lull") * DT


@pytest.mark.parametrize("effect", ["orbits", "blackhole"])
def test_an_untold_step7_member_is_todays_frame_for_frame(tmp_path, effect):
    pinned = _pinned7(effect)
    arms = H.engine_arms(effect, 3.2)              # no pre-drop: NOT_TOLD
    now = _run7(tmp_path, effect, arms, pokes=FLARE_WRITE)
    then = _run7(tmp_path, pinned, _today(arms, effect), effect=effect,
                 pokes=FLARE_WRITE)
    assert len(now.frames) == len(then.frames)
    assert max(float(f.max()) for f in now.frames) > 0.0
    for i, (a, b) in enumerate(zip(now.frames, then.frames)):
        assert np.array_equal(a, b), (effect, i, now.phase[i])


# ── Orbits: dims to its floor, then jitters and grows ─────────────────────

@pytest.mark.parametrize("lull_s,gap_s,kind", GAPS7)
def test_orbits_is_one_curve_down_to_its_floor_then_full_on_the_pre_drop(
        tmp_path, lull_s, gap_s, kind):
    """The look's gain times the base render's breath IS the plan's curve:
    smoothstepping from full to the 25% floor by the breath's start, held
    there through the breath (never dimmed twice), full on the pre-drop."""
    run = _told7(tmp_path, "orbits", lull_s, gap_s, kind)
    floor = ob_mod.BREATH_FLOOR_DIM
    breath_at = None
    for (ph, t), inf in zip(run.phase, run.info):
        if ph != "lull":
            continue
        total = inf["pd_gain"] * inf["breath"]
        seg = inf["segment"]
        if seg == "breath":
            breath_at = breath_at if breath_at is not None else t
            assert total == pytest.approx(floor, abs=EPS), t
        elif seg == "pre_drop":
            assert total == pytest.approx(1.0, abs=EPS), t
        else:
            assert breath_at is None, "the approach comes before the breath"
            assert floor - EPS <= total <= 1.0 + EPS, t
    assert breath_at is not None


def test_orbits_is_dim_never_black_in_the_breath_and_back_at_full_on_it(
        tmp_path):
    run = _told7(tmp_path, "orbits")
    breath = [H.light(f, MASK) for _t, f, _i in _segment(run, "breath")]
    pre = [H.light(f, MASK) for _t, f, _i in _segment(run, "pre_drop")]
    assert breath and pre
    assert min(breath) > 0.0, "his dim blob, never black"
    assert pre[0] > 2.0 * max(breath), "the look starts on the pre-drop"


@pytest.mark.parametrize("lull_s,gap_s,kind", [(3.2, 0.8, "spike"),
                                               (6.0, 3.3, "intro")])
def test_orbits_jitters_harder_and_grows_toward_the_drop(tmp_path, lull_s,
                                                         gap_s, kind):
    run = _told7(tmp_path, "orbits", lull_s, gap_s, kind)
    frames = _segment(run, "pre_drop")
    k = len(frames)
    assert k >= 12
    jit = [float(np.hypot(*inf["jitter"])) for _t, _f, inf in frames]
    assert max(jit) <= ob_mod.PRE_DROP_JITTER_TO_PX + EPS
    third = k // 3
    assert np.mean(jit[-third:]) > 2.0 * np.mean(jit[:third]), \
        "harder and harder toward the drop"
    changes = sum(1 for a, b in zip(frames, frames[1:])
                  if a[2]["jitter"] != b[2]["jitter"])
    assert abs(changes - k / 2) <= 2, "a fresh offset every other frame"
    area = [int(((f.reshape(-1, 3).max(axis=1) > 25.0) & MASK).sum())
            for _t, f, _i in frames]
    assert np.mean(area[-third:]) > 1.2 * np.mean(area[:third]), \
        "it grows as it jitters"


def test_orbits_light_over_the_lull_at_the_plans_gap_is_below_todays(
        tmp_path):
    told = _told7(tmp_path, "orbits", 3.2, 0.8, "spike")
    today = _run7(tmp_path, "orbits", H.engine_arms("orbits", 3.2),
                  lull_s=3.2)
    assert _lull_light(told) < _lull_light(today)


@pytest.mark.parametrize("lull_s,gap_s,kind", [(3.2, 2.0, "spike"),
                                               (6.0, 3.3, "intro")])
def test_orbits_light_at_a_longer_gap_stays_within_its_named_bound(
        tmp_path, lull_s, gap_s, kind):
    """A NAMED DEVIATION, bounded: the blob is back at full and growing for
    the whole gap, so a 2 s spike measures +1% and a 3.3 s vocal intro +14%
    against today's lull (the plan's own prototype measured only 0.8 s).
    This holds it there; it never claims at-or-below."""
    told = _told7(tmp_path, "orbits", lull_s, gap_s, kind)
    today = _run7(tmp_path, "orbits", H.engine_arms("orbits", lull_s),
                  lull_s=lull_s)
    assert _lull_light(told) <= 1.20 * _lull_light(today)


# ── Black Hole: dark, black through the breath, the infall ring ───────────

@pytest.mark.parametrize("lull_s,gap_s,kind", GAPS7)
def test_black_hole_is_dark_from_its_dark_point_through_the_breath(
        tmp_path, lull_s, gap_s, kind):
    run = _told7(tmp_path, "blackhole", lull_s, gap_s, kind)
    dark = _segment(run, "dark") + _segment(run, "breath")
    assert dark
    for t, f, _inf in dark:
        assert H.light(f, MASK) == 0.0, t
    pre = _segment(run, "pre_drop")
    assert H.light(pre[0][1], MASK) > 0.0, "the ring lights on the pre-drop"


@pytest.mark.parametrize("lull_s,gap_s,kind", [(3.2, 0.8, "spike"),
                                               (6.0, 3.3, "intro")])
def test_the_infall_ring_falls_from_the_hex_edge_to_the_centre(
        tmp_path, lull_s, gap_s, kind):
    run = _told7(tmp_path, "blackhole", lull_s, gap_s, kind)
    radii = []
    for _t, f, inf in _segment(run, "pre_drop"):
        v = f.reshape(-1, 3).max(axis=1) * MASK
        assert v.sum() > 0.0
        radii.append(float((v * inf["grid_r"].ravel()).sum() / v.sum()))
    assert radii[0] > 0.9, "it lights at the hex edge"
    assert radii[-1] < 0.15, "it lands on the centre on the drop"
    assert all(b <= a + 0.02 for a, b in zip(radii, radii[1:])), \
        "it only ever falls inward"


def test_the_infall_ring_wears_the_sets_colours_never_white(tmp_path):
    run = _told7(tmp_path, "blackhole")
    hues = set()
    for _t, f, _inf in _segment(run, "pre_drop"):
        px = f.reshape(-1, 3)[MASK]
        assert phase_grammar.white_cells(px) == 0
        lit = px[px.max(axis=1) > 40.0]
        hues.update(int(np.degrees(np.arctan2(
            np.sqrt(3.0) * (p[1] - p[2]), 2.0 * p[0] - p[1] - p[2])) // 15)
            for p in lit)
    assert len(hues) >= 3, "coloured round the set by angle"


@pytest.mark.parametrize("lull_s,gap_s,kind", GAPS7)
def test_black_hole_light_over_the_lull_is_below_todays(tmp_path, lull_s,
                                                        gap_s, kind):
    told = _told7(tmp_path, "blackhole", lull_s, gap_s, kind)
    today = _run7(tmp_path, "blackhole", H.engine_arms("blackhole", lull_s),
                  lull_s=lull_s)
    assert _lull_light(told) < _lull_light(today)
    assert bh_mod.PRE_DROP_RING_R0 > bh_mod.HEX_FILL_RADIUS


# ═══ Step 8: the Fish, Star and Sauron ═════════════════════════════════════

from fx.effects import fish as fish_mod  # noqa: E402
from fx.effects import radial as star_mod  # noqa: E402
from fx.effects import sauron as sauron_mod  # noqa: E402

GAPS8 = GAPS7
INFO8 = {"fish": H._fish_info, "sauron": H._sauron_info}
# a far set (warm) the drop's colour change lands on in the colour test
NEW_SET = "linear-gradient(90deg, #ff2000 0%, #ffa000 100%)"


def _pinned8(module):
    try:
        return H.load_pinned(module, f"{module}_prelook8",
                             H.STEP8_LACKS[module], ref=H.STEP8_REF)
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _run8(tmp_path, effect_type, arms, effect=None, **kw):
    effect = effect or effect_type
    return H.run_async(H.crystal_run(tmp_path, effect_type, arms,
                                     H.STEP8_CFG[effect], info=INFO8[effect],
                                     **kw))


def _told8(tmp_path, effect, lull_s=3.2, gap_s=0.8, kind="spike"):
    arms = H.engine_arms(effect, lull_s, at_s=lull_s - gap_s, gap_s=gap_s,
                         kind=kind)
    return _run8(tmp_path, effect, arms, lull_s=lull_s)


def _star(tmp_path, star_type, lull_s=3.2, gap_s=None, kind="spike",
          today=False, **kw):
    scene = H.star_scene()
    at = None if gap_s is None else lull_s - gap_s
    arms = H.engine_arms("radial", lull_s, at_s=at, gap_s=gap_s, kind=kind,
                         scene=scene)
    if today:
        arms = _today(arms, "radial")
    strip = H.engine_arms("melt", lull_s, at_s=at, gap_s=gap_s, kind=kind,
                          scene=scene)
    return H.run_async(H.star_run(tmp_path, star_type, arms, strip,
                                  lull_s=lull_s, **kw))


@pytest.mark.parametrize("effect", ["fish", "sauron"])
def test_an_untold_step8_member_is_todays_frame_for_frame(tmp_path, effect):
    pinned = _pinned8(effect)
    arms = H.engine_arms(effect, 3.2)              # no pre-drop: NOT_TOLD
    now = _run8(tmp_path, effect, arms, pokes=FLARE_WRITE)
    then = _run8(tmp_path, pinned, _today(arms, effect), effect=effect,
                 pokes=FLARE_WRITE)
    assert len(now.frames) == len(then.frames)
    assert max(float(f.max()) for f in now.frames) > 0.0
    for i, (a, b) in enumerate(zip(now.frames, then.frames)):
        assert np.array_equal(a, b), (effect, i, now.phase[i])


def test_an_untold_star_is_todays_frame_for_frame(tmp_path):
    pinned = _pinned8("radial")
    now = _star(tmp_path, "radial", pokes=FLARE_WRITE)
    then = _star(tmp_path, pinned, today=True, pokes=FLARE_WRITE)
    assert len(now.frames) == len(then.frames)
    assert max(float(f.max()) for f in now.frames) > 0.0
    for i, (a, b) in enumerate(zip(now.frames, then.frames)):
        assert np.array_equal(a, b), (i, now.phase[i])


# ── the Fish: the searcher darts to the centre and waits there poised ─────

@pytest.mark.parametrize("lull_s,gap_s,kind", GAPS8)
def test_the_fish_searching_lull_ends_on_the_pre_drop(tmp_path, lull_s,
                                                      gap_s, kind):
    """Told, the half-way mark is half the way to the pre-drop: every other
    fish has left by it and the keeper is there to go (on a 3.2 s lull with
    a 2 s gap the untold mark, 1.6 s, would land 0.4 s after it)."""
    run = _told8(tmp_path, "fish", lull_s, gap_s, kind)
    first = _segment(run, "pre_drop")[0][2]
    assert first["keepers"] >= 1
    assert first["others"] == 0, "the lone searcher, no one else"


@pytest.mark.parametrize("lull_s,gap_s,kind", GAPS8)
def test_the_fish_darts_to_the_centre_and_waits_there_poised(
        tmp_path, lull_s, gap_s, kind):
    run = _told8(tmp_path, "fish", lull_s, gap_s, kind)
    gap = _segment(run, "pre_drop")
    at = lull_s - gap_s
    assert all(inf["turn"] == fish_mod.PRE_DROP_TURN for _t, _f, inf in gap)
    arrived = gap[-1][2]["arrived"]
    assert arrived is not None
    assert arrived - at <= fish_mod.PRE_DROP_DART_MAX_S + 2 * DT + EPS
    body = gap[0][2]["body_px"]
    d = [inf["keep_d_px"] for _t, _f, inf in gap]
    assert np.mean(d) <= 2.0 * body, "it waits at the centre of view"
    assert max(d) <= 3.0 * body
    before = [inf for (ph, _t), inf in zip(run.phase, run.info)
              if ph == "lull" and inf["segment"] != "pre_drop"]
    assert all(inf["turn"] is None for inf in before), "the gap's alone"


@pytest.mark.parametrize("lull_s,gap_s,kind", [(3.2, 2.0, "spike"),
                                               (6.0, 3.3, "intro")])
def test_the_fish_head_quivers_harder_toward_the_drop(tmp_path, lull_s,
                                                      gap_s, kind):
    run = _told8(tmp_path, "fish", lull_s, gap_s, kind)
    looks = [inf["look"] for _t, _f, inf in _segment(run, "pre_drop")
             if inf["arrived"] is not None]
    third = len(looks) // 3
    assert third >= 10
    assert max(looks) <= fish_mod.PRE_DROP_QUIVER[1] + EPS
    assert max(looks[-third:]) > 1.5 * max(looks[:third])


@pytest.mark.parametrize("lull_s,gap_s,kind", GAPS8)
def test_the_fish_lull_is_never_dark_and_its_light_is_within_the_plans(
        tmp_path, lull_s, gap_s, kind):
    """The Fish takes no breath, so every lull frame is lit; its light over
    the lull stays within the plan's own named +4% (report 3.5: "every
    idea stays at or below today's lull except Fish (+4%)")."""
    told = _told8(tmp_path, "fish", lull_s, gap_s, kind)
    assert all(H.light(f, MASK) > 0.0 for _t, f, _i in H.lull_frames(told))
    today = _run8(tmp_path, "fish", H.engine_arms("fish", lull_s),
                  lull_s=lull_s)
    assert _lull_light(told) <= 1.04 * _lull_light(today)


# ── Star: dark, the outline grows out of the centre, the drop's colours ────

def _lit_radius(frame):
    """The lit cells' brightness-weighted mean distance from the panel's
    centre (px), over his real cells."""
    v = frame.reshape(H.ROWS, H.COLS, 3).max(axis=2)
    yy, xx = np.indices(v.shape)
    r = np.hypot(xx - H.COLS * 0.5, yy - H.ROWS * 0.5)
    w = v * MASK.reshape(v.shape)
    return float((w * r).sum() / w.sum()) if w.sum() > 0 else 0.0


@pytest.mark.parametrize("lull_s,gap_s,kind", GAPS8)
def test_star_is_dark_from_its_dark_point_through_the_breath(
        tmp_path, lull_s, gap_s, kind):
    run = _star(tmp_path, "radial", lull_s, gap_s, kind)
    dark = _segment(run, "dark") + _segment(run, "breath")
    assert dark
    for t, f, _inf in dark:
        assert H.light(f, MASK) == 0.0, t
    assert H.light(_segment(run, "pre_drop")[0][1], MASK) > 0.0


@pytest.mark.parametrize("lull_s,gap_s,kind", [(3.2, 0.8, "spike"),
                                               (6.0, 3.3, "intro")])
def test_star_outline_grows_out_of_the_centre_as_it_spins_up(
        tmp_path, lull_s, gap_s, kind):
    """His approval: "the star predrop should grow from the center as it
    spins, so it doesn't just pop in" — it starts as a dot at the centre and
    reaches its full size on the drop, turning faster as it goes."""
    run = _star(tmp_path, "radial", lull_s, gap_s, kind)
    gap = _segment(run, "pre_drop")
    radii = [_lit_radius(f) for _t, f, _i in gap]
    assert radii[0] < 3.0, "a dot at the centre on the pre-drop"
    full = star_mod.PRE_DROP_OUTLINE_R * H.ROWS
    assert radii[-1] > 0.6 * full, "full size on the drop"
    assert radii[0] < 0.25 * radii[-1]
    assert all(b >= a - 0.5 for a, b in zip(radii, radii[1:])), \
        "it only ever grows"
    steps = [(b["spin"] - a["spin"]) % 1.0
             for (_t, _f, a), (_u, _g, b) in zip(gap, gap[1:])]
    third = len(steps) // 3
    assert np.mean(steps[-third:]) > 2.0 * np.mean(steps[:third]), \
        "it spins up"


def test_star_outline_wears_the_sets_colours_never_white(tmp_path):
    run = _star(tmp_path, "radial", 3.2, 0.8)
    hues = set()
    for _t, f, _inf in _segment(run, "pre_drop"):
        px = f.reshape(-1, 3)[MASK]
        assert phase_grammar.white_cells(px) == 0
        lit = px[px.max(axis=1) > 40.0]
        hues.update(int(np.degrees(np.arctan2(
            np.sqrt(3.0) * (p[1] - p[2]), 2.0 * p[0] - p[1] - p[2])) // 15)
            for p in lit)
    assert len(hues) >= 3, "coloured round the set by angle"


@pytest.mark.parametrize("lull_s,gap_s,kind", GAPS8)
def test_star_light_over_the_lull_is_below_todays(tmp_path, lull_s, gap_s,
                                                  kind):
    told = _star(tmp_path, "radial", lull_s, gap_s, kind)
    today = _star(tmp_path, "radial", lull_s)
    assert _lull_light(told) < _lull_light(today)


def _old_hue_cells(run, within_s=0.35):
    """Lit real cells in the drop's first `within_s` whose hue is the OLD
    set's (FIREWORKS_CFG's blue to purple) rather than NEW_SET's warm."""
    import colorsys
    count = 0
    for (ph, t), f in zip(run.phase, run.frames):
        if ph != "drop" or t > within_s:
            continue
        px = f.reshape(-1, 3)[MASK]
        for r, g, b in px[px.max(axis=1) > 60.0]:
            h = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0] * 360.0
            count += 170.0 <= h <= 300.0
    return count


@pytest.mark.parametrize("lull_s,gap_s,kind", [(3.2, 0.8, "spike"),
                                               (6.0, 3.3, "intro")])
def test_star_drop_pieces_wear_the_set_as_it_is_at_the_drop(
        tmp_path, lull_s, gap_s, kind):
    """The plan's 2.2/3.5: "Star re-samples its palette as the colour
    fades". The set changes at the pre-drop; the pieces the lull swallowed
    fly back out on the drop in the NEW set. Today's module (the control,
    no pre-drop) throws them out in the colours they fell in with."""
    at = lull_s - gap_s
    change = {("lull", int(round(at / DT))): {"gradient": NEW_SET}}
    told = _star(tmp_path, "radial", lull_s, gap_s, kind, strip_pokes=change)
    drop = [i for (ph, _t), i in zip(told.phase, told.info) if ph == "drop"]
    assert drop[0]["snap"] and drop[0]["snap_resampled"]
    assert _old_hue_cells(told) == 0
    control = _star(tmp_path, _pinned8("radial"), lull_s, today=True,
                    strip_pokes=change)
    assert _old_hue_cells(control) > 100, "the control shows the defect"


# ── Sauron: black, the lids part to a dimmed glare, no slam on the drop ───

@pytest.mark.parametrize("lull_s,gap_s,kind", GAPS8)
def test_sauron_is_black_through_the_breath_then_parts_to_the_glare(
        tmp_path, lull_s, gap_s, kind):
    run = _told8(tmp_path, "sauron", lull_s, gap_s, kind)
    breath = _segment(run, "breath")
    assert breath
    for t, f, _inf in breath:
        assert H.light(f, MASK) == 0.0, t
    gap = _segment(run, "pre_drop")
    at = lull_s - gap_s
    open_to = sauron_mod.PRE_DROP_LID_OPEN_TO
    assert gap[0][2]["lid"] > open_to and gap[0][2]["glare"]
    parted = [t for t, _f, inf in gap if inf["lid"] <= open_to + EPS]
    assert parted and parted[0] - at <= sauron_mod.PRE_DROP_PART_S + DT + EPS
    assert all(inf["lid"] == pytest.approx(open_to) for t, _f, inf in gap
               if t >= parted[0]), "the glare holds until the drop"


def test_sauron_glare_holds_the_flames_down_and_brightens(tmp_path):
    run = _told8(tmp_path, "sauron", 6.0, 3.3, "intro")
    approach = [inf["flame_cells"] for _t, _f, inf in _segment(run, "approach")]
    gap = _segment(run, "pre_drop")
    assert max(inf["flame_cells"] for _t, _f, inf in gap) < 0.5 * np.mean(
        approach), "the flames are held down"
    held = [H.light(f, MASK) for t, f, _i in gap
            if t >= gap[0][0] + sauron_mod.PRE_DROP_PART_S + DT]
    third = len(held) // 3
    assert np.mean(held[-third:]) > 1.2 * np.mean(held[:third]), \
        "brightening toward the drop"


@pytest.mark.parametrize("lull_s,gap_s,kind", [(3.2, 0.8, "spike"),
                                               (6.0, 3.3, "intro")])
def test_the_drop_opens_sauron_from_the_glare_without_a_slam(
        tmp_path, lull_s, gap_s, kind):
    run = _told8(tmp_path, "sauron", lull_s, gap_s, kind)
    drop = [inf for (ph, _t), inf in zip(run.phase, run.info) if ph == "drop"]
    first = drop[0]
    assert first["slam"] is False
    assert first["burst"] > 0.9, "the eruption fires on the mark"
    lids = [inf["lid"] for inf in drop[:8]]
    assert lids[0] < sauron_mod.PRE_DROP_LID_OPEN_TO
    assert all(b <= a + EPS for a, b in zip(lids, lids[1:])), "opening"


@pytest.mark.parametrize("lull_s,gap_s,kind", GAPS8)
def test_sauron_light_over_the_lull_is_below_todays(tmp_path, lull_s, gap_s,
                                                    kind):
    """The plan's prototype measured Sauron at +3% over today's lull and
    said it would ship at a dimmer setting: at PRE_DROP_GLARE it is below
    today's at every gap."""
    told = _told8(tmp_path, "sauron", lull_s, gap_s, kind)
    today = _run8(tmp_path, "sauron", H.engine_arms("sauron", lull_s),
                  lull_s=lull_s)
    assert _lull_light(told) < _lull_light(today)


# ═══ Step 9: the strips ════════════════════════════════════════════════════

from fx.effects import fireworks1d as fw1d_mod  # noqa: E402
from fx.effects import pre_drop as pre_drop_mod  # noqa: E402
from fx.effects import strip_phase as strip_mod  # noqa: E402

GAPS9 = GAPS7
# an ordinary write and a flare punch in the lull: the untold path carries
# both, the punch through the layer's own envelope
STRIP_POKES = {**FLARE_WRITE,
               ("lull", 90): {"flare_punch": 1, "flare_punch_hold_s": 0.3}}


def _pinned9(module):
    try:
        return H.load_pinned_strip(module, f"{module}_prelook9")
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _run9(tmp_path, effect_type, arms, effect=None, config=None, **kw):
    cfg = {**H.STEP9_CFG[effect or effect_type], **(config or {})}
    return H.run_async(H.strip_run(tmp_path, effect_type, arms, cfg, **kw))


def _told9(tmp_path, effect, lull_s=3.2, gap_s=0.8, kind="spike", look=None,
           strength=None, **kw):
    arms = H.strip_arms(effect, lull_s, at_s=lull_s - gap_s, gap_s=gap_s,
                        kind=kind)
    if look is not None:
        arms["lull"].params[pre_drop_mod.LOOK_KEY] = look
    if strength is not None:
        for arm in arms.values():
            arm.params[strip_mod.STRENGTH_KEY] = strength
    return _run9(tmp_path, effect, arms, lull_s=lull_s, **kw)


def _strip_lull_light(run):
    return sum(H.light(f) for (ph, _t), f in zip(run.phase, run.frames)
               if ph == "lull") * DT


def _twinkle_lit(inf, level=0.25):
    tw = inf["twinkle"]
    return 0.0 if tw is None else float((tw > level).mean())


@pytest.mark.parametrize("effect", H.STRIPS)
def test_an_untold_strip_is_todays_frame_for_frame(tmp_path, effect):
    """Against the strip AND the shared layer as they were before step 9
    (both pinned out of git): no clock, no twinkle, no lift."""
    pinned = _pinned9(effect)
    arms = H.strip_arms(effect, 3.2)               # no pre-drop: NOT_TOLD
    now = _run9(tmp_path, effect, arms, pokes=STRIP_POKES)
    then = _run9(tmp_path, pinned, _today(arms, effect), effect=effect,
                 pokes=STRIP_POKES)
    assert len(now.frames) == len(then.frames)
    assert max(float(f.max()) for f in now.frames) > 0.0
    for i, (a, b) in enumerate(zip(now.frames, then.frames)):
        assert np.array_equal(a, b), (effect, i, now.phase[i])


# ── the twinkle (the shared layer: Melt, Power, the Black Hole and Orbits
# strips) ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("effect", H.TWINKLE_STRIPS)
def test_a_strip_keeps_its_own_lull_until_the_pre_drop_then_twinkles(
        tmp_path, effect):
    """Told the same pre-drop with a look the layer does not draw, the
    strip is the same frame for frame up to the pre-drop: the twinkle is
    the only thing that changes, and only from the pre-drop on."""
    tw = _told9(tmp_path, effect)
    plain = _told9(tmp_path, effect, look="none-such")
    added = 0.0
    for (ph, t), a, b, inf in zip(tw.phase, tw.frames, plain.frames,
                                  tw.info):
        if ph != "lull":
            continue
        if inf["segment"] != "pre_drop":
            assert inf["twinkle"] is None, (effect, t)
            assert np.array_equal(a, b), (effect, t)
        else:
            added += float(np.maximum(a - b, 0.0).sum())
    assert added > 0.0
    assert max(_twinkle_lit(inf) for _t, _f, inf in _segment(tw, "pre_drop")) > 0.0


@pytest.mark.parametrize("bright", [1.0, 0.5])
@pytest.mark.parametrize("effect", ["power", "blackhole1d", "orbits1d"])
def test_each_twinkle_peaks_at_the_effects_own_brightness(tmp_path, effect,
                                                          bright):
    """His approval: "make the twinkles max brightness match the effect
    brightness (don't dim, just use twinkle to "dim")". A twinkle born this
    frame shows the set's own colour at its place times the effect's own
    brightness, never less; every colour of this set has a channel at full,
    so the gap's brightest pixel is 255 x the effect's brightness. (Melt is
    left out: its own blur, applied after the layer to everything it draws,
    softens a one-pixel twinkle's peak.)"""
    run = _told9(tmp_path, effect, config={"brightness": bright})
    born = 0
    peak = 0.0
    for (ph, _t), f, inf in zip(run.phase, run.frames, run.info):
        if ph != "lull" or inf["segment"] != "pre_drop" or inf["twinkle"] is None:
            continue
        peak = max(peak, float(f.max()))
        for j in np.flatnonzero(inf["twinkle"] >= 1.0 - EPS):
            born += 1
            assert np.all(f[j] >= run.palette[j] * bright - 0.6), (j, f[j])
    assert born > 10
    assert peak == pytest.approx(255.0 * bright, abs=0.6)


@pytest.mark.parametrize("effect", H.TWINKLE_STRIPS)
def test_the_twinkle_is_sparse_and_thickens_toward_the_drop(tmp_path, effect):
    """"A few pixels twinkle ... thickening slightly toward the drop":
    under an eighth of the strip lit (above a quarter of full) on average
    over a vocal intro's long gap, never a fifth, and the last third
    clearly denser than the first."""
    run = _told9(tmp_path, effect, lull_s=6.0, gap_s=3.3, kind="intro")
    lit = np.array([_twinkle_lit(inf) for _t, _f, inf
                    in _segment(run, "pre_drop")])
    third = len(lit) // 3
    assert 0.0 < lit.mean() < 0.125
    assert lit.max() < 0.2
    assert lit[-third:].mean() > 1.3 * lit[:third].mean()


@pytest.mark.parametrize("effect", H.TWINKLE_STRIPS)
def test_the_twinkle_wears_the_sets_colours_never_white(tmp_path, effect):
    from strip_phase_harness import whiter_than_set
    run = _told9(tmp_path, effect)
    gap = _segment(run, "pre_drop")
    assert gap
    for t, f, _inf in gap:
        assert whiter_than_set(f, run.palette) == 0, (effect, t)


def test_at_strength_zero_no_twinkle_is_born(tmp_path):
    """The room's master at 0 is today's effect exactly (the rollback
    lever): its strength scales the twinkle's birth rate, so none is born
    and the strip is the same as one told no look at all."""
    tw = _told9(tmp_path, "melt", strength=0.0)
    plain = _told9(tmp_path, "melt", look="none-such", strength=0.0)
    for (ph, t), a, b, inf in zip(tw.phase, tw.frames, plain.frames,
                                  tw.info):
        assert inf["twinkle"] is None or float(inf["twinkle"].max()) == 0.0
        assert np.array_equal(a, b), (ph, t)


def test_the_strip_star_reads_never_twinkles(tmp_path):
    """The strip a Radial reads leaves its lull to Star (strip_phase's THE
    STRIP STAR READS), so it is "none" through it: Star draws its own
    pre-drop, the strip no twinkle."""
    run = _star(tmp_path, "radial", gap_s=0.8)
    lull = [inf for (ph, _t), inf in zip(run.phase, run.info) if ph == "lull"]
    assert any(inf["segment"] == "pre_drop" for inf in lull)
    assert not any(inf["strip_twinkle"] for inf in lull)


# ── the Fireworks strip: the crystal's idea on the strip ──────────────────

@pytest.mark.parametrize("lull_s,gap_s,kind", GAPS9)
def test_the_fireworks_strip_is_dark_until_the_pre_drop_and_black_in_the_breath(
        tmp_path, lull_s, gap_s, kind):
    run = _told9(tmp_path, "fireworks1d", lull_s, gap_s, kind)
    breath = _segment(run, "breath")
    assert breath, "a breath before the pre-drop"
    for (ph, t), f, inf in zip(run.phase, run.frames, run.info):
        if ph != "lull" or inf["segment"] == "pre_drop":
            continue
        assert inf["rockets"] == 0, ("no rockets at the lull's start", t)
    for t, f, _inf in breath:
        assert float(f.max()) == 0.0, ("black through the breath", t)
    # the control: today's lull launches its two rockets at its start
    today = _run9(tmp_path, "fireworks1d", H.strip_arms("fireworks1d", lull_s),
                  lull_s=lull_s)
    first = next(inf for (ph, _t), inf in zip(today.phase, today.info)
                 if ph == "lull")
    assert first["rockets"] == 2


@pytest.mark.parametrize("lull_s,gap_s,kind", [(3.2, 0.8, "spike"),
                                               (6.0, 3.3, "intro")])
def test_the_strip_rockets_fire_from_the_ends_on_the_pre_drop_and_burst_on_the_drop(
        tmp_path, lull_s, gap_s, kind):
    run = _told9(tmp_path, "fireworks1d", lull_s, gap_s, kind)
    gap = _segment(run, "pre_drop")
    first, last = gap[0][2], gap[-1][2]
    assert first["rockets"] == 2
    lo, hi = sorted(first["rocket_pos"])
    assert lo < 0.1 and hi > 0.9, "from the strip's ends"
    assert all(0.3 < p < 0.7 for p in last["rocket_pos"]), "past the middle"
    # bright: the layer lifts the lull's 12% ember for them (today's rockets
    # fly the dark at the ember, under a fifth of full)
    assert max(float(f.max()) for _t, f, _i in gap) > 0.5 * 255.0
    drop = [inf for (ph, _t), inf in zip(run.phase, run.info) if ph == "drop"]
    assert drop[0]["rockets"] == 0 and drop[0]["particles"] >= 8, \
        "each rocket bursts into the payoff's two pairs on the drop"


def test_a_flare_burst_in_the_strips_breath_is_swallowed(tmp_path):
    at = 3.2 - 0.8
    k = int(round((at - 0.2) / DT))                # inside the 0.4 s breath
    run = _told9(tmp_path, "fireworks1d",
                 pokes={("lull", k): {"burst_rockets": 2}})
    for t, f, inf in _segment(run, "breath"):
        assert float(f.max()) == 0.0, t
        assert inf["particles"] == 0, t


@pytest.mark.parametrize("gap_s", [0.8, 2.0, 3.3])
def test_a_strip_rocket_dims_by_the_crystals_rule(gap_s):
    assert fw1d_mod.pre_drop_rocket_fade(gap_s) == pytest.approx(
        fw_mod.pre_drop_rocket_fade(gap_s))


# ── the light over the lull (his "keep the total lighting output low") ────

@pytest.mark.parametrize("lull_s,gap_s,kind", GAPS9)
@pytest.mark.parametrize("effect", H.STRIPS)
def test_a_strips_light_over_the_lull_is_below_todays(tmp_path, effect,
                                                      lull_s, gap_s, kind):
    """The plan measured the twinkle at a 15% peak and set its sparseness
    here, at the effect's full brightness, to keep the strip's whole lull
    at or below today's: it is below at every gap, as is the Fireworks
    strip's."""
    told = _told9(tmp_path, effect, lull_s, gap_s, kind)
    today = _run9(tmp_path, effect, H.strip_arms(effect, lull_s),
                  lull_s=lull_s)
    assert _strip_lull_light(told) < _strip_lull_light(today)
