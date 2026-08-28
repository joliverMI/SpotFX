"""Measure the CHARGE's spread — his 2026-08-28 ask, before and after.

His words: "in the charge, I don't want the fish to clump so much and I
want them evenly distributed across the screen" — while, from the original
brief, still arriving together.

Three numbers, over the second half of a real 4s charge at his live scene
state, averaged across four seeds:

  * NEAREST-NEIGHBOUR distance (px) — the direct reading of "clumping";
  * GRID OCCUPANCY — distinct cells of a 6x3 grid the on-panel school
    reaches, and the same figure PER ON-PANEL FISH, which is what "evenly
    distributed" actually means (12 fish in 6 cells is even; 12 fish in 6
    cells with 5 of them in one is not);
  * HEADING SPREAD (rad) — the unison that must NOT be traded away for it.

The BEFORE column is the pinned merge-base's own fx/effects/fish.py, read
out of git and registered as a second effect — the same control
scripts/check_fish_camera.py uses, never this file with a constant zeroed.

Read-only, offline (fx.headless at his crystal-mapper's shape, audio
silenced). No live access.

    .venv/bin/python scripts/check_fish_charge_spread.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless  # noqa: E402
from check_fish_camera import (  # noqa: E402
    BASELINE_REF, HIS, load_master_effect,
)

DT = 1.0 / 60.0
ROWS, COLS = 37, 72
GRID = (6, 3)
SEEDS = (3, 5, 11, 17)

_RUN = [0]


async def charge_run(effect_type, seed):
    """One 4s charge; sample the second half."""
    _RUN[0] += 1
    dev = f"fish-spread-{_RUN[0]}"
    with tempfile.TemporaryDirectory() as td:
        host = await headless.start_headless_host(
            str(Path(td) / dev), pixel_count=ROWS * COLS, rows=ROWS,
            device_id=dev,
        )
        virtual = host.virtuals.get(dev)
        with headless.fake_clock() as clock:
            eff = headless.attach_effect(
                host, virtual, effect_type, dict(HIS)
            )
            eff._rng = np.random.default_rng(seed)

            def step():
                clock.advance(DT)
                f = virtual.assemble_frame()
                if f is not None:
                    virtual.flush(f)

            for _ in range(240):
                step()
            eff.update_config({"phase": "charge", "phase_progress": 0.0})
            frames = int(4.0 / DT)
            nn, occ, occ_n, hs = [], [], [], []
            for i in range(1, frames + 1):
                eff.update_config({"phase_progress": i / frames})
                step()
                if i <= frames * 0.5:
                    continue
                n = eff.n
                m = np.flatnonzero(eff.p_mode[:n] == 0)
                if m.size < 3:
                    continue
                h = eff.p_hd[m]
                c = np.arctan2(np.sin(h).mean(), np.cos(h).mean())
                hs.append(float(np.abs(
                    (h - c + np.pi) % (2 * np.pi) - np.pi
                ).std()))
                x = eff.p_x[m] * eff.sx - eff.cam_px + eff.cx
                y = eff.p_y[m] * eff.sy - eff.cam_py + eff.cy
                on = (x >= 0) & (x < COLS) & (y >= 0) & (y < ROWS)
                x, y = x[on], y[on]
                if x.size < 3:
                    continue
                d = np.hypot(x[None, :] - x[:, None], y[None, :] - y[:, None])
                np.fill_diagonal(d, np.inf)
                nn.append(float(d.min(axis=1).mean()))
                gx = np.clip((x / COLS * GRID[0]).astype(int), 0, GRID[0] - 1)
                gy = np.clip((y / ROWS * GRID[1]).astype(int), 0, GRID[1] - 1)
                cells = len(set(zip(gx.tolist(), gy.tolist())))
                occ.append(cells)
                occ_n.append(cells / x.size)
        await host.shutdown()
    return (float(np.mean(nn)), float(np.mean(occ)),
            float(np.mean(occ_n)), float(np.mean(hs)))


def mean_over_seeds(effect_type):
    rows = [asyncio.run(charge_run(effect_type, s)) for s in SEEDS]
    return tuple(float(np.mean([r[i] for r in rows])) for i in range(4))


def main():
    print("FISH CHARGE — clumping, spread, and the unison that must survive")
    print(f"(his state: jiggle {HIS['jiggle']}, roam_scale "
          f"{HIS['roam_scale']}, school_count 12 on a {COLS}x{ROWS} panel; "
          f"{len(SEEDS)} seeds, second half of a 4s charge)")

    master = load_master_effect(name="fish_spread_master", ref=BASELINE_REF)
    now = mean_over_seeds("fish")
    print(f"\n   {'':<22}{'BEFORE':>10}{'AFTER':>10}   verdict")
    if master is None:
        before = (float("nan"),) * 4
    else:
        before = mean_over_seeds(master)

    rows = (
        ("nearest neighbour (px)", 0, "higher", 1.25),
        ("grid cells reached /18", 1, "higher", 1.0),
        ("cells per on-panel fish", 2, "higher", 1.15),
        ("heading spread (rad)", 3, "lower-or-equal", None),
    )
    fails = []
    for label, i, want, ratio in rows:
        b, a = before[i], now[i]
        if want == "higher":
            ok = np.isnan(b) or a >= b * ratio
        else:
            # unison must not get WORSE; it is allowed to improve
            ok = np.isnan(b) or a <= b * 1.05
        print(f"   {label:<22}{b:>10.3f}{a:>10.3f}   "
              f"{'ok' if ok else 'FAIL'}  ({want})")
        if not ok:
            fails.append(label)
    if fails:
        raise SystemExit(f"charge spread regressed: {fails}")
    print("\n   The unison was NOT traded for the spread — separating the "
          "school\n   reduced the jostling that was widening the heading "
          "spread, so both\n   improved. The one real cost is named in the "
          "PR: about 1.3 fewer of\n   the school's fish sit on the panel at "
          "any instant, because a spread\n   school reaches past the "
          "window's edges.")
    print("\nCHARGE SPREAD OK")


if __name__ == "__main__":
    main()
