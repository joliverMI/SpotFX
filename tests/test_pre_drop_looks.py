"""THE PRE-DROP LOOKS (predrop plan steps 6-7): Fireworks' rockets and
Pulse's burst and dim swell (step 6), Orbits' jitter-and-grow return and
Black Hole's infall ring (step 7), on the real effects, driven by the lull arm
the real engine writes (tests/pre_drop_look_harness.py).

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
colours, its light over the lull below today's.
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
