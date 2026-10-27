"""THE PRE-DROP LOOKS (predrop plan step 6): Fireworks' rockets and Pulse's
burst and dim swell, on the real effects, driven by the lull arm the real
engine writes (tests/pre_drop_look_harness.py).

The acceptance (report 3.7, step 6): without a pre-drop each effect is
today's, frame for frame, against its own module before the looks (pinned
out of git); with one, Fireworks' panel is dark until the pre-drop, black in
every frame of the breath before it, and its rockets fire on it and burst on
the drop, its light over the lull below today's; Pulse is truly black
through the breath and through the dark span before the drop (a flare's
flash included), the dark span is a quarter of the gap clamped to 100-500
ms, the spike bursts to full and the vocal intro swells to about 30%, and
the flash budget still holds.
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
