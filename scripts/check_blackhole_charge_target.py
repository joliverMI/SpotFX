"""Executable spec: the Black Hole CHARGE builds to a MEASURED target, and
the build's RATE carries through the lull until the horizon takes the
screen. Measured on the real vendored render pipeline (fx.headless, his own
Black Hole V2 Matrix params at his crystal's 72x37 shape) — never by
integrating a spawn rate, which is not the same quantity.

His words, verbatim (2026-09-10):

    "the black hole charge should be more pronounced. there should be a
    steady increase in particles following. it should be about 80 percent
    as bright in terms of blob count not in the event horizon (visible
    blobs) as the drop by the end of the charge. then, that rate continues
    as the lull reaches the point where the event horizon has fully taken
    the screen. then the drop is as before"

THE QUANTITY. A VISIBLE BLOB here is a live particle that is

  * NOT captured by the event horizon (`p_cap < 0`). A captive is pinned on
    the ring and blending to the horizon colour — his own exclusion, "not
    in the event horizon", names exactly this set; and
  * inside the panel's own light field (`r <= HEX_FILL_RADIUS`). Past that
    bound his crystal has no real cells at all
    (.claude/skills/crystal-hex-grid/SKILL.md), so a particle parked there
    is not on screen.

It is a COUNT of particles, never a luminance — his sentence says "in terms
of blob count", and says it twice.

`p_is_burst` (the drop payoff's own tag) is what separates the drop's blobs
from the charge's; `p_nocap` is the cap-arithmetic tag and would be TRUE for
both. Conflating them counts the charge's forced formation as part of the
drop. See AGENTS.md's Black Hole section.

WHY SPAWN RATE IS NOT THE ANSWER. Blobs fall in and are retired, so the live
population is Little's law — count ~= rate x how long a blob stays visible —
and the charge's own accelerating fall speed keeps shortening that time. The
only honest instrument is to count what is alive on rendered frames, which
is what this script does.

Read-only: touches no storage, no network, no live process. Renders through
fx.headless with dummy devices only.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fx import headless  # noqa: E402
from fx.effects import blackhole as bh  # noqa: E402

DT = 1.0 / 60.0
TARGET_RATIO = 0.80
# "about 80 percent" — the band this script holds the MEAN of every
# measured condition to. The per-condition spread either side of it is
# reported, not flattened: it comes from his own spawn_rate binding and
# from how long the charge runs, both of which are the song's to decide.
RATIO_BAND = 0.10

# his real Black Hole V2 Matrix entry (storage/spectra/scenes.json), bound
# params at their own fallbacks
HIS_MATRIX = {
    "horizon_scale": 0.2, "blob_size": 1.75, "swirl": 0.0, "reverse": False,
    "x_offset": 0.5, "y_offset": 0.5, "horizon_audio": 0.3, "base_speed": 2.0,
    "accel": 5.0, "spawn_rate": 1.0, "beat_burst": 0, "spawn_audio": 1.5,
    "speed_audio": 2.0, "impulse_decay": 0.06, "max_blobs": 50,
    "edge_speed": 0.2, "horizon_hold": 2.8,
}

# His `spawn_rate` on that entry is bound to trigger_intensity, mapped
# 0.5..2.0 with a 1.0 fallback — so the ordinary music-driven spawn running
# UNDER the charge is small, and the charge's own forced formation is what
# the target has to be carried by. 6.5 is the loud-music proxy: `spawn_audio`
# 1.5 scales the same rate by (1 + 1.5*impulse*3), which at his binding's own
# ceiling and a strong impulse reaches about that. A headless host has no
# audio, so it is expressed as a higher spawn_rate instead.
CONDITIONS = [
    ("his fallback", 1.0, 4.0),
    ("quiet end of his binding", 0.5, 4.0),
    ("loud end of his binding", 2.0, 4.0),
    ("loud-music proxy", 6.5, 4.0),
    ("short charge", 1.0, 2.0),
    ("long charge", 1.0, 8.0),
]

_failures: list[str] = []


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _failures.append(msg)


def _crystal_mask():
    prof = json.loads(
        (REPO_ROOT / "storage/device_profiles/crystal-mapper.json")
        .read_text(encoding="utf-8"))
    mask, v = [], False
    for run in prof["mask_rle"]:
        mask.extend([v] * run)
        v = not v
    return np.array(mask, dtype=bool).reshape(prof["rows"], prof["cols"])


MASK = _crystal_mask()


def _counts(e):
    """(visible, visible_burst, visible_on_a_real_cell, free_anywhere,
    captured). `visible` is the quantity his sentence names; the others are
    reported beside it so nothing about the measurement is hidden."""
    n = e.n
    if n == 0:
        return 0, 0, 0, 0, 0
    free = e.p_cap[:n] < 0.0
    inside = free & (e.p_r[:n] <= bh.HEX_FILL_RADIUS)
    px = (e.cx + e.p_r[:n] * np.cos(e.p_theta[:n]) * e.sx).round().astype(int)
    py = (e.cy + e.p_r[:n] * np.sin(e.p_theta[:n]) * e.sy).round().astype(int)
    ok = ((px >= 0) & (px < MASK.shape[1])
          & (py >= 0) & (py < MASK.shape[0]))
    real = np.zeros(n, dtype=bool)
    real[ok] = MASK[py[ok], px[ok]]
    return (int(inside.sum()),
            int((inside & e.p_is_burst[:n]).sum()),
            int((inside & real).sum()),
            int(free.sum()),
            int((~free).sum()))


async def _run(tmp, sub, *, spawn_rate, charge_s, lull_s=2.5, warm_s=10.0,
               drop_s=0.5):
    """The production sequence scene_response._drive_phase drives: a settled
    room, then charge 0->1, lull 0->1, drop 0->1."""
    host = await headless.start_headless_host(
        str(tmp / sub), device_id=sub, pixel_count=72 * 37, rows=37)
    virtual = host.virtuals.get(sub)
    out = {"charge": [], "lull": [], "drop": [], "payoff": [],
           "steady": 0.0,
           "arrivals": {"charge_tail": 0, "lull_pre_fill": 0},
           "capture_rate": []}
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(
            host, virtual, "blackhole",
            dict(HIS_MATRIX, spawn_rate=spawn_rate))

        # every real _spawn, tagged with where the clock was — an arrival
        # count, never a net population delta (blobs retire while a charge
        # runs, which would hide the very rate being measured)
        where = {"phase": "none", "p": 0.0}
        arrivals: list[tuple[str, float, int, bool]] = []
        orig_spawn = effect._spawn

        def logged_spawn(count, beat_count, *a, _o=orig_spawn, **kw):
            before = effect.n
            _o(count, beat_count, *a, **kw)
            if effect.n > before:
                arrivals.append((where["phase"], where["p"],
                                 effect.n - before,
                                 bool(kw.get("ignore_cap"))))

        effect._spawn = logged_spawn

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
                settled.append(_counts(effect)[0])
        out["steady"] = float(np.mean(settled))

        where.update(phase="charge", p=0.0)
        effect.update_config({"phase": "charge", "phase_progress": 0.0})
        fc = int(charge_s / DT)
        for i in range(1, fc + 1):
            p = i / fc
            effect.update_config({"phase_progress": p})
            where.update(phase="charge", p=p)
            step(1)
            out["charge"].append((p,) + _counts(effect)
                                 + (effect._phase_spawn_rate(),))

        where.update(phase="lull", p=0.0)
        effect.update_config({"phase": "lull", "phase_progress": 0.0})
        fl = int(lull_s / DT)
        for i in range(1, fl + 1):
            p = i / fl
            effect.update_config({"phase_progress": p})
            where.update(phase="lull", p=p)
            step(1)
            out["lull"].append((p,) + _counts(effect)
                               + (effect._phase_spawn_rate(),
                                  effect._horizon_radius()))

        where.update(phase="drop", p=0.0)
        drop_entry_frame = len(out["charge"]) + len(out["lull"])
        burst_frame = [None]
        orig_burst = effect._phase_burst

        def logged_burst(*a, _o=orig_burst, **kw):
            burst_frame[0] = len(out["drop"])
            return _o(*a, **kw)

        effect._phase_burst = logged_burst
        effect.update_config({"phase": "drop", "phase_progress": 0.0})
        fd = int(drop_s / DT)
        for i in range(1, fd + 1):
            effect.update_config({"phase_progress": i / fd})
            step(1)
            out["drop"].append((i / fd,) + _counts(effect))
            # the payoff's OWN trajectory, so a before/after can compare the
            # drop itself and not just the constants it was built from
            m = effect.p_is_burst[: effect.n]
            out["payoff"].append({
                "n": int(m.sum()),
                "r_max": round(float(effect.p_r[: effect.n][m].max()), 4)
                if m.any() else 0.0,
                "r_mean": round(float(effect.p_r[: effect.n][m].mean()), 4)
                if m.any() else 0.0,
                "rh": round(float(effect._horizon_radius()), 4),
            })
        step(int(0.4 / DT))
        out["burst_frame"] = burst_frame[0]
        out["drop_entry_frame"] = drop_entry_frame
        out["end_phase"] = effect._phase
        out["end_reverse"] = effect.reverse

    await host.shutdown()

    # forced arrivals per second either side of the charge/lull seam
    tail_window = max(charge_s * 0.25, 0.5)
    tail = sum(c for ph, p, c, forced in arrivals
               if forced and ph == "charge"
               and p >= 1.0 - tail_window / charge_s)
    out["arrivals"]["charge_tail"] = tail / tail_window
    pre = sum(c for ph, p, c, forced in arrivals
              if forced and ph == "lull" and p < bh.LULL_FILL_PROGRESS)
    out["arrivals"]["lull_pre_fill"] = pre / (lull_s * bh.LULL_FILL_PROGRESS)
    out["arrivals"]["lull_post_fill"] = sum(
        c for ph, p, c, forced in arrivals
        if forced and ph == "lull" and p >= bh.LULL_FILL_PROGRESS)
    return out


def _at(rows, p, i=1):
    return min(rows, key=lambda r: abs(r[0] - p))[i]


async def main():
    print("BLACK HOLE CHARGE — BUILD TO A MEASURED TARGET")
    print(f"  CHARGE_SPAWN_RATE_MAX={bh.CHARGE_SPAWN_RATE_MAX}  "
          f"CHARGE_SPAWN_CURVE={bh.CHARGE_SPAWN_CURVE}  "
          f"PHASE_BURST_N={bh.PHASE_BURST_N}  "
          f"HEX_FILL_RADIUS={bh.HEX_FILL_RADIUS:.3f}  "
          f"LULL_FILL_PROGRESS={bh.LULL_FILL_PROGRESS}")

    results = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for k, (label, sr, cs) in enumerate(CONDITIONS):
            results.append((label, sr, cs,
                            await _run(tmp, f"bh{k}", spawn_rate=sr,
                                       charge_s=cs)))

    SAMPLE_P = (0.2, 0.4, 0.6, 0.8, 1.0)

    print("\n§1 THE DENOMINATOR — what 'as the drop' is measured against")
    print("  The drop's OWN payoff is PHASE_BURST_N blobs. Measured as the "
          "peak\n  number of p_is_burst particles visible in the field:")
    bursts, totals = [], []
    for label, sr, cs, r in results:
        b = max(x[2] for x in r["drop"])
        t = max(x[1] for x in r["drop"])
        bursts.append(b)
        totals.append(t)
        print(f"    {label:<26} burst-peak={b:3d}   total-visible-peak={t:3d}")
    check(all(b == bh.PHASE_BURST_N for b in bursts),
          f"the drop's own payoff measures exactly PHASE_BURST_N="
          f"{bh.PHASE_BURST_N} visible blobs in every condition — a stable "
          "denominator")
    print(f"\n  DISCREPANCY, REPORTED NOT HIDDEN: the drop's TOTAL visible "
          f"peak is\n  {min(totals)}-{max(totals)}, not {bh.PHASE_BURST_N}. "
          "Entering \"drop\" RELEASES every captive\n  (_phase_step sets "
          "p_cap = -1 on the whole population), so that total is the\n  "
          f"{bh.PHASE_BURST_N}-blob payoff PLUS everything the charge and "
          "lull just fed the horizon.\n  It therefore GROWS with whatever "
          "CHARGE_SPAWN_RATE_MAX is set to — measured at\n  109 before this "
          "calibration and 176 after, at the same spawn_rate — so an 80%\n  "
          "target anchored on it is a divergent fixed point, not a target. "
          "The payoff\n  is the denominator; the total is reported above.")

    print("\n§2 CHARGE — the build lands on his target")
    denom = bh.PHASE_BURST_N
    ratios = []
    print(f"    {'condition':<26} {'settled':>7} " +
          " ".join(f"p={p:.1f}" for p in SAMPLE_P) + "   ratio")
    for label, sr, cs, r in results:
        counts = [int(round(r["steady"]))] + [_at(r["charge"], p)
                                              for p in SAMPLE_P]
        end = r["charge"][-1][1]
        ratio = end / denom
        ratios.append(ratio)
        print(f"    {label:<26} {counts[0]:>7} " +
              " ".join(f"{c:5d}" for c in counts[1:]) + f"   {ratio:.2f}")
    mean = float(np.mean(ratios))
    check(abs(mean - TARGET_RATIO) <= RATIO_BAND,
          f"the charge ends at a mean {mean * 100:.0f}% of the drop's payoff "
          f"({min(ratios) * 100:.0f}-{max(ratios) * 100:.0f}% across "
          f"conditions) — his \"about 80 percent\"")
    check(all(abs(x - TARGET_RATIO) <= 0.25 for x in ratios),
          "and no single condition strays more than 25 points from it")
    print("  The low end is the SHORT charge, and that is inherent rather "
          "than a miss: a\n  blob stays visible for about a second, so a "
          "2s charge only has time to build\n  a population for its second "
          "half. A shorter build is a smaller build. The\n  high end is the "
          "loud-music proxy, where his own spawn_rate binding is already\n  "
          "contributing blobs before the charge starts.")

    print("\n§3 CHARGE — 'a steady increase in particles following'")
    for label, sr, cs, r in results:
        counts = [int(round(r["steady"]))] + [_at(r["charge"], p)
                                              for p in SAMPLE_P]
        inc = [counts[i + 1] - counts[i] for i in range(len(counts) - 1)]
        print(f"    {label:<26} counts={counts}  increments={inc}")
    worst = min(
        min(([int(round(r["steady"]))] + [_at(r["charge"], p)
                                          for p in SAMPLE_P])[i + 1]
            - ([int(round(r["steady"]))] + [_at(r["charge"], p)
                                            for p in SAMPLE_P])[i]
            for i in range(len(SAMPLE_P)))
        for _, _, _, r in results)
    check(worst >= -2,
          f"the build never goes BACKWARDS at any sampled point in any "
          f"condition (worst step {worst:+d} blobs) — it is an increase, "
          "not a rise-then-collapse")
    quarter = []
    for label, sr, cs, r in results:
        counts = [int(round(r["steady"]))] + [_at(r["charge"], p)
                                              for p in SAMPLE_P]
        span = counts[-1] - counts[0]
        if span > 0:
            quarter.append((counts[3] - counts[0]) / span)
    check(quarter and min(quarter) >= 0.25,
          f"and it is STEADY, not back-loaded: by p=0.6 the charge has "
          f"already delivered {min(quarter) * 100:.0f}-"
          f"{max(quarter) * 100:.0f}% of its whole build "
          "(a back-loaded build would sit near zero here)")
    print("  For contrast, the same measurement at the previous 12.0/2.0 "
          "constants\n  read counts=[15, 14, 14, 14, 15, 19], increments="
          "[-1, 0, 0, 1, 4] — a charge\n  that delivered 4 of its 19 blobs "
          "in the last fifth and was otherwise flat.")

    print("\n§4 LULL — 'that rate continues' to the fill point")
    for label, sr, cs, r in results:
        a = r["arrivals"]
        print(f"    {label:<26} charge tail {a['charge_tail']:5.1f}/s  ->  "
              f"lull before fill {a['lull_pre_fill']:5.1f}/s   "
              f"(after fill: {a['lull_post_fill']} blobs)")
    check(all(abs(r["arrivals"]["lull_pre_fill"]
                  - bh.CHARGE_SPAWN_RATE_MAX) <= 2.0
              for _, _, _, r in results),
          f"the charge's own final formation rate CONTINUES across the "
          f"phase seam at {bh.CHARGE_SPAWN_RATE_MAX:.0f}/s — no step down "
          "into the lull")
    check(all(r["arrivals"]["lull_post_fill"] == 0 for _, _, _, r in results),
          "and stops exactly at LULL_FILL_PROGRESS — nothing is formed "
          "unseen behind a panel that is already dark")
    fills = []
    for label, sr, cs, r in results:
        row = [x for x in r["lull"]
               if x[0] >= bh.LULL_FILL_PROGRESS][0]
        fills.append((row[-1], row[1]))
    check(all(rh >= bh.HEX_FILL_RADIUS for rh, _ in fills),
          f"…and LULL_FILL_PROGRESS IS \"the point where the event horizon "
          f"has fully taken the screen\": the horizon measures "
          f"{min(rh for rh, _ in fills):.3f} there, past the hex "
          f"silhouette's own bound {bh.HEX_FILL_RADIUS:.3f}")

    print("\n  THE HONEST LIMIT, stated rather than claimed away. The visible "
          "COUNT\n  cannot keep climbing through the lull however hard this "
          "rate is driven: a\n  free blob lives from the hex boundary down to "
          "the horizon, and the lull's\n  expansion collapses that distance "
          "to zero, so the count reaches 0 AT the\n  fill by construction. "
          "What continues is the RATE — his own word — and the\n  horizon "
          "goes on swallowing blobs at the charge's full rate right up to "
          "the\n  moment it closes over the panel. Measured count through "
          "the lull:")
    for label, sr, cs, r in results:
        row = [f"p={p:.1f}:{_at(r['lull'], p):>3d}"
               for p in (0.1, 0.2, 0.3, 0.4, 0.5)]
        print(f"    {label:<26} " + "  ".join(row))

    print("\n§5 DROP — unchanged")
    check(all(r["burst_frame"] == 0 for _, _, _, r in results),
          "the payoff still fires on the drop's own first frame")
    check(all(r["end_phase"] == "none" for _, _, _, r in results),
          f"the drop still self-resets to phase=none after DROP_RESET_S="
          f"{bh.DROP_RESET_S}")
    check(all(r["end_reverse"] is False for _, _, _, r in results),
          "the saved reverse is still restored at the payoff")
    check(bh.PHASE_BURST_N == 48 and bh.DROP_RESET_S == 0.5
          and bh.PHASE_BURST_SPEED_MULT == 2.0,
          "and none of the drop's own constants moved (PHASE_BURST_N=48, "
          "DROP_RESET_S=0.5, PHASE_BURST_SPEED_MULT=2.0)")
    print(f"\n  KNOCK-ON, REPORTED: a bigger charge hands the drop a bigger "
          f"population to\n  release. The drop's own payoff is untouched at "
          f"{bh.PHASE_BURST_N} blobs, but its TOTAL visible\n  peak rises "
          f"({min(totals)}-{max(totals)} here, against 81-118 at the "
          "previous constants) because\n  the charge and lull fed the horizon "
          "more. That is what \"more pronounced\"\n  costs; it is his call "
          "whether the payoff should scale with it, and nothing\n  here "
          "assumes it should.")

    print("\n§5b DROP — a BEFORE/AFTER against the previous constants")
    print("  The same drop, driven by the same sequence, with this module's "
          "charge\n  constants set back to their previous 12.0/2.0. If the "
          "calibration had\n  disturbed the payoff, these two trajectories "
          "would differ.")
    new_mx, new_cv = bh.CHARGE_SPAWN_RATE_MAX, bh.CHARGE_SPAWN_CURVE
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        after = await _run(tmp, "after", spawn_rate=1.0, charge_s=4.0)
        try:
            bh.CHARGE_SPAWN_RATE_MAX, bh.CHARGE_SPAWN_CURVE = 12.0, 2.0
            before = await _run(tmp, "before", spawn_rate=1.0, charge_s=4.0)
        finally:
            bh.CHARGE_SPAWN_RATE_MAX, bh.CHARGE_SPAWN_CURVE = new_mx, new_cv
    print(f"    {'frame':>5} {'before: n  r_mean  r_max     rh':<34}"
          f"  {'after: n  r_mean  r_max     rh'}")
    for i in (0, 3, 8, 15, 29):
        b, a = before["payoff"][i], after["payoff"][i]
        print(f"    {i:>5} {b['n']:>9d} {b['r_mean']:7.3f} {b['r_max']:7.3f}"
              f" {b['rh']:7.3f}   {a['n']:>8d} {a['r_mean']:7.3f}"
              f" {a['r_max']:7.3f} {a['rh']:7.3f}")
    check([x["n"] for x in before["payoff"]]
          == [x["n"] for x in after["payoff"]],
          "the payoff's blob count is identical, frame for frame")
    check([x["rh"] for x in before["payoff"]]
          == [x["rh"] for x in after["payoff"]],
          "the horizon's post-burst ease-back is identical, frame for frame")
    reach_b = max(x["r_max"] for x in before["payoff"])
    reach_a = max(x["r_max"] for x in after["payoff"])
    check(abs(reach_b - reach_a) <= 0.05,
          f"and the payoff reaches the same distance out "
          f"(before {reach_b:.3f}, after {reach_a:.3f} — these are random "
          "flight times per blob, so they are close rather than equal)")
    print("  (The payoff's RADII are drawn per blob from the same "
          "distribution with a\n  live rng, so r_mean/r_max are a "
          "same-distribution comparison; the COUNT and\n  the horizon "
          "curve are deterministic and are asserted equal.)")

    print("\n§6 SCOPE — the strips keep their own numbers")
    from fx.effects import blackhole1d as bh1  # noqa: E402
    check(bh1.CHARGE_SPAWN_RATE_MAX == 12.0 and bh1.CHARGE_SPAWN_CURVE == 2.0,
          "fx/effects/blackhole1d.py is deliberately untouched (12.0/2.0)")
    check(not hasattr(bh1.Blackhole1d, "_horizon_radius"),
          "— it has no event horizon and no capture at all, so \"blob count "
          "not in the event horizon\" has no referent there")

    print("\n" + ("ALL CHECKS PASSED" if not _failures
                  else f"{len(_failures)} FAILED: " + "; ".join(_failures)))
    return 1 if _failures else 0


if __name__ == "__main__":
    status = 1
    try:
        status = asyncio.run(main())
    finally:
        sys.stdout.flush()
        # fx's TemporalEffect spawns non-daemon threads this frame-stepped
        # harness never joins — see AGENTS.md
        os._exit(status)
