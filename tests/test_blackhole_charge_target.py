"""The Black Hole CHARGE builds to a MEASURED visible-blob target, and its
build rate carries through the lull until the horizon takes the screen.

His words, verbatim (2026-09-10):

    "the black hole charge should be more pronounced. there should be a
    steady increase in particles following. it should be about 80 percent
    as bright in terms of blob count not in the event horizon (visible
    blobs) as the drop by the end of the charge. then, that rate continues
    as the lull reaches the point where the event horizon has fully taken
    the screen. then the drop is as before"

Frame-level, on the real vendored effect (fx.headless, dummy device at his
crystal's 72x37 shape). scripts/check_blackhole_charge_target.py is the
measured, printed version of the same runs — it carries the whole condition
sweep, the denominator argument and the before/after on the drop; these are
the assertions that must not regress.

VERIFIED RED against the previous constants: with CHARGE_SPAWN_RATE_MAX /
CHARGE_SPAWN_CURVE set back to 12.0 / 2.0 in the module SOURCE (not
monkeypatched — a fresh import), the two calibration claims fail and say
why ("charge ended at 9 visible blobs = 0.19 of the drop's 48-blob payoff";
"the build is too small to read: [2, 2, 1, 5, 8, 9]"). The rest of the
claims here are STRUCTURAL — the seam, the lull's own limit, the drop's
invariance, the scoping — and correctly hold in BOTH worlds; a proof bar
that cannot fail on the defect it was written for is decoration, and those
two are the bar.

The quantity is defined once, in `_visible` below, and matches the check
script byte for byte: a live particle NOT captured by the horizon
(`p_cap < 0` — his own "not in the event horizon") and inside the panel's
own light field (`r <= HEX_FILL_RADIUS`). `p_is_burst` is what separates the
drop's payoff from the charge's blobs; `p_nocap` is the cap-arithmetic tag
and is TRUE for both (AGENTS.md's Black Hole section)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless
from fx.effects import blackhole as bh
from fx.effects import blackhole1d as bh1d

DT = 1.0 / 60.0
CHARGE_S = 4.0
LULL_S = 2.5

# his real Black Hole V2 Matrix entry; `spawn_rate` binds to
# trigger_intensity over 0.5..2.0 with a 1.0 fallback, so the ordinary
# music-driven spawn running under the charge is small
CFG = {
    "horizon_scale": 0.2, "blob_size": 1.75, "swirl": 0.0, "reverse": False,
    "x_offset": 0.5, "y_offset": 0.5, "horizon_audio": 0.3, "base_speed": 2.0,
    "accel": 5.0, "spawn_rate": 1.0, "beat_burst": 0, "spawn_audio": 1.5,
    "speed_audio": 2.0, "impulse_decay": 0.06, "max_blobs": 50,
    "edge_speed": 0.2, "horizon_hold": 2.8,
}


def _visible(e):
    """Blobs on screen and NOT in the event horizon — the quantity his
    sentence names."""
    n = e.n
    if n == 0:
        return 0
    free = e.p_cap[:n] < 0.0
    return int((free & (e.p_r[:n] <= bh.HEX_FILL_RADIUS)).sum())


def _visible_payoff(e):
    """…restricted to the DROP's own payoff blobs (p_is_burst)."""
    n = e.n
    if n == 0:
        return 0
    free = e.p_cap[:n] < 0.0
    return int((free & (e.p_r[:n] <= bh.HEX_FILL_RADIUS)
                & e.p_is_burst[:n]).sum())


async def _drive(tmp_path, sub, *, spawn_rate=1.0, charge_s=CHARGE_S,
                 lull_s=LULL_S, warm_s=10.0):
    host = await headless.start_headless_host(
        str(tmp_path / sub), device_id=sub, pixel_count=72 * 37, rows=37)
    virtual = host.virtuals.get(sub)
    out = {"charge": [], "lull": [], "drop": [], "settled": 0.0,
           "forced": [], "payoff_n": [], "horizon": []}
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(
            host, virtual, "blackhole", dict(CFG, spawn_rate=spawn_rate))
        where = {"phase": "none", "p": 0.0}
        orig_spawn = effect._spawn

        def logged_spawn(count, beat_count, *a, _o=orig_spawn, **kw):
            before = effect.n
            _o(count, beat_count, *a, **kw)
            if effect.n > before and kw.get("ignore_cap"):
                out["forced"].append(
                    (where["phase"], where["p"], effect.n - before))

        effect._spawn = logged_spawn
        burst_frame = [None]
        orig_burst = effect._phase_burst

        def logged_burst(*a, _o=orig_burst, **kw):
            burst_frame[0] = len(out["drop"])
            return _o(*a, **kw)

        effect._phase_burst = logged_burst

        def step(k=1):
            for _ in range(k):
                clock.advance(DT)
                f = virtual.assemble_frame()
                if f is not None:
                    virtual.flush(f)

        settled = []
        for i in range(1, int(warm_s / DT) + 1):
            step(1)
            if i > int(7.0 / DT):
                settled.append(_visible(effect))
        out["settled"] = float(np.mean(settled))

        for phase, secs in (("charge", charge_s), ("lull", lull_s)):
            effect.update_config({"phase": phase, "phase_progress": 0.0})
            frames = int(secs / DT)
            for i in range(1, frames + 1):
                p = i / frames
                effect.update_config({"phase_progress": p})
                where.update(phase=phase, p=p)
                step(1)
                out[phase].append((p, _visible(effect),
                                   effect._phase_spawn_rate(),
                                   effect._horizon_radius()))

        where.update(phase="drop", p=0.0)
        effect.update_config({"phase": "drop", "phase_progress": 0.0})
        frames = int(0.5 / DT)
        for i in range(1, frames + 1):
            effect.update_config({"phase_progress": i / frames})
            step(1)
            out["drop"].append((i / frames, _visible(effect),
                                _visible_payoff(effect)))
            n = effect.n
            out["payoff_n"].append(int(effect.p_is_burst[:n].sum()))
            out["horizon"].append(round(float(effect._horizon_radius()), 6))
        step(int(0.4 / DT))
        out["burst_frame"] = burst_frame[0]
        out["end_phase"] = effect._phase
        out["end_reverse"] = effect.reverse
    await host.shutdown()
    return out


def _at(rows, p):
    return min(rows, key=lambda r: abs(r[0] - p))[1]


def test_the_drop_payoff_is_the_stable_denominator(tmp_path):
    """"as the drop" is measured against the drop's OWN payoff — and that
    measures exactly PHASE_BURST_N visible blobs.

    Deliberately NOT the drop's total visible peak: entering "drop" releases
    every captive (_phase_step sets p_cap = -1), so the total is the payoff
    PLUS whatever the charge and lull just fed the horizon, and it therefore
    grows with CHARGE_SPAWN_RATE_MAX. An 80% target anchored on it is a
    divergent fixed point. Both numbers are asserted here so the difference
    can never quietly stop being true."""
    res = asyncio.run(_drive(tmp_path, "denom"))
    payoff_peak = max(x[2] for x in res["drop"])
    total_peak = max(x[1] for x in res["drop"])
    assert payoff_peak == bh.PHASE_BURST_N
    # a definitional invariant, not a calibration claim: it has to hold in
    # both worlds, which is why the margin is "genuinely more" rather than
    # a multiple of whatever this calibration happens to produce
    assert total_peak >= payoff_peak + 20, (
        "the drop's total visible peak is the payoff PLUS released "
        f"captives — payoff {payoff_peak}, total {total_peak}")


def test_the_charge_ends_at_about_80_percent_of_the_drops_payoff(tmp_path):
    """His number, measured — never integrated from the spawn rate.

    Blobs are captured by the horizon and retire, so the live population is
    Little's law (count ~= rate x how long a blob stays visible) and the
    charge's own accelerating fall speed keeps shortening that time."""
    res = asyncio.run(_drive(tmp_path, "target"))
    end = res["charge"][-1][1]
    ratio = end / bh.PHASE_BURST_N
    assert 0.65 <= ratio <= 0.95, (
        f"charge ended at {end} visible blobs = {ratio:.2f} of the drop's "
        f"{bh.PHASE_BURST_N}-blob payoff")


def test_the_charge_is_a_steady_increase_never_a_late_jump(tmp_path):
    """"a steady increase in particles following": monotone at every
    sampled point, and most of the build already delivered before the last
    fifth. At the previous 12.0/2.0 constants this read [15, 14, 14, 14,
    15, 19] — flat, with 4 of its 19 blobs arriving in the last fifth."""
    res = asyncio.run(_drive(tmp_path, "steady"))
    ps = (0.2, 0.4, 0.6, 0.8, 1.0)
    counts = [int(round(res["settled"]))] + [_at(res["charge"], p) for p in ps]
    inc = [counts[i + 1] - counts[i] for i in range(len(counts) - 1)]
    assert min(inc) >= -2, f"the build goes backwards: {counts} -> {inc}"
    span = counts[-1] - counts[0]
    assert span >= 20, f"the build is too small to read: {counts}"
    assert (counts[3] - counts[0]) / span >= 0.25, (
        f"back-loaded, not steady: {counts}")


def test_the_rate_continues_through_the_lull_to_the_fill_point(tmp_path):
    """"then, that rate continues as the lull reaches the point where the
    event horizon has fully taken the screen" — the charge's own final
    formation rate carries across the phase seam with no step down, and
    stops exactly at LULL_FILL_PROGRESS, which IS that point."""
    res = asyncio.run(_drive(tmp_path, "lull"))
    pre = sum(c for ph, p, c in res["forced"]
              if ph == "lull" and p < bh.LULL_FILL_PROGRESS)
    post = sum(c for ph, p, c in res["forced"]
               if ph == "lull" and p >= bh.LULL_FILL_PROGRESS)
    rate = pre / (LULL_S * bh.LULL_FILL_PROGRESS)
    assert abs(rate - bh.CHARGE_SPAWN_RATE_MAX) <= 2.0, (
        f"the lull formed {rate:.1f}/s, not the charge's final "
        f"{bh.CHARGE_SPAWN_RATE_MAX}/s")
    assert post == 0, "blobs were formed behind an already-dark panel"
    fill = [x for x in res["lull"] if x[0] >= bh.LULL_FILL_PROGRESS][0]
    assert fill[3] >= bh.HEX_FILL_RADIUS, (
        "LULL_FILL_PROGRESS is not where the horizon takes the screen")


def test_the_lull_cannot_hold_the_count_up_and_that_is_structural(tmp_path):
    """The honest limit, pinned so it is never quietly claimed away: a free
    blob lives from the hex boundary down to the horizon, and the lull's
    expansion collapses that distance to zero — so the VISIBLE COUNT reaches
    0 at the fill however hard the rate is driven. What continues is the
    RATE (asserted above), not the count."""
    res = asyncio.run(_drive(tmp_path, "limit"))
    assert _at(res["lull"], 0.1) > _at(res["lull"], 0.3) > 0
    fill = [x for x in res["lull"] if x[0] >= bh.LULL_FILL_PROGRESS][0]
    assert fill[1] == 0


def test_the_drop_is_as_before(tmp_path):
    """"then the drop is as before". Driven twice through the identical
    sequence — once with this module's charge constants set back to their
    previous 12.0/2.0 — and the payoff compared frame for frame."""
    after = asyncio.run(_drive(tmp_path, "after"))
    new = (bh.CHARGE_SPAWN_RATE_MAX, bh.CHARGE_SPAWN_CURVE)
    try:
        bh.CHARGE_SPAWN_RATE_MAX, bh.CHARGE_SPAWN_CURVE = 12.0, 2.0
        before = asyncio.run(_drive(tmp_path, "before"))
    finally:
        bh.CHARGE_SPAWN_RATE_MAX, bh.CHARGE_SPAWN_CURVE = new

    assert before["payoff_n"] == after["payoff_n"], (
        "the payoff's blob count changed")
    assert before["horizon"] == after["horizon"], (
        "the horizon's post-burst ease-back changed")
    for res in (before, after):
        assert res["burst_frame"] == 0, "the payoff no longer fires on the "\
            "drop's first frame"
        assert res["end_phase"] == "none"
        assert res["end_reverse"] is False
    assert (bh.PHASE_BURST_N, bh.DROP_RESET_S, bh.PHASE_BURST_SPEED_MULT) == (
        48, 0.5, 2.0), "a drop constant moved"


def test_the_calibration_is_scoped_to_the_matrix_effect():
    """The strip keeps its own numbers: it has no event horizon and no
    capture at all (its blobs fall to the centre and die — there is no
    p_cap), so "blob count not in the event horizon" has no referent there,
    its own drop payoff is separately scaled, and 45 blobs/second on a 7-17
    pixel strip is mush rather than a build."""
    assert (bh1d.CHARGE_SPAWN_RATE_MAX, bh1d.CHARGE_SPAWN_CURVE) == (12.0, 2.0)
    assert not hasattr(bh1d.Blackhole1d, "_horizon_radius")
    assert bh1d.PHASE_BURST_N != bh.PHASE_BURST_N
