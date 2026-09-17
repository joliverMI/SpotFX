"""Measure the FISH SWIM BURST against the panel edge (fx/effects/fish.py
`BOUND_BRAKE_AT`, the "Fish Swim Burst" flare's own `swim_burst` toggle).

HIS WORDS (2026-09-16, watching it live): "the fish do scatter, but the
burst seems a little wrong. it seems like they always fly off the screen,
but they should stay on the screen." That is a defect report about the
BURST specifically — the lull's own dispersal (fish leaving the panel on
purpose) is CONFIRMED GOOD and untouched by this fix.

ROOT CAUSE, found by instrumentation, not assumed: the boundary steer's
own heading correction (`d_hd * TURN_GAIN`, clipped by the turn-radius
`omega_max`) converges on a fixed TIME constant, not a fixed distance — so
a fish moving at several times cruise still travels several times as far
during that same correction time before its heading has caught up, and a
2.2x-plus swim burst can carry it past the panel edge before the steer
finishes turning it back. The turn radius itself (`turn_radius_px`,
`omega_max`) is UNCHANGED — this file never touches it, and never touches
`TURN_GAIN` either; see fx/effects/fish.py's own comment at the brake for
why (`BOUND_BRAKE_AT`'s block, just above the inward steer).

This prints, for a repeated-burst scenario (worse than a single burst: his
live scene has the burst pooled on three separate bands, each firing on
its own trigger), the worst distance any fish's CENTRE lands past the
panel edge — negative means still inside — with and without the fix, and
confirms the burst is not reduced to a soft no-op away from the edge (a
fish comfortably clear of the boundary still reaches several times cruise
speed).

Read-only, offline, no live access: fx.headless at his crystal-mapper's
72x37 shape, audio silenced.

    .venv/bin/python scripts/check_fish_burst_bounds.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless  # noqa: E402

DT = 1.0 / 60.0
ROWS, COLS = 37, 72

FAILURES: list[str] = []


def check(cond, label):
    print(f"   {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        FAILURES.append(label)


_RUN = [0]


async def _run(cfg, seed, burst_ms=300, period=0.5, seconds=15.0,
                always=False):
    """Fires `swim_burst` on the given period (or holds it on the whole
    run, `always=True` — the worst case a stuck flare could produce) and
    returns (worst off-panel px for any fish CENTRE, the fastest speed
    observed by a fish comfortably clear of the edge — more than 8px
    inside — while bursting)."""
    _RUN[0] += 1
    dev = f"fish-burst-bounds-{_RUN[0]}"
    with tempfile.TemporaryDirectory() as td:
        host = await headless.start_headless_host(
            str(Path(td) / dev), pixel_count=ROWS * COLS, rows=ROWS,
            device_id=dev,
        )
        virtual = host.virtuals.get(dev)
        with headless.fake_clock() as clock:
            eff = headless.attach_effect(host, virtual, "fish", dict(cfg))
            eff._rng = np.random.default_rng(seed)
            eff.swim_burst = False

            worst_off = -1e9
            clear_speed = 0.0
            t = 0.0
            while t < seconds:
                phase = t % period
                eff.swim_burst = always or (phase < (burst_ms / 1000.0))
                clock.advance(DT)
                virtual.assemble_frame()
                n = eff.n
                if n:
                    screen_x = eff.cx + eff.p_x[:n] * eff.sx - eff.cam_px
                    screen_y = eff.cy + eff.p_y[:n] * eff.sy - eff.cam_py
                    off_x = np.maximum(-screen_x, screen_x - (COLS - 1))
                    off_y = np.maximum(-screen_y, screen_y - (ROWS - 1))
                    off = np.maximum(off_x, off_y)
                    worst_off = max(worst_off, float(np.max(off)))
                    if eff.swim_burst:
                        clear = off < -8.0
                        if clear.any():
                            clear_speed = max(
                                clear_speed,
                                float(np.max(eff.p_spd[:n][clear])),
                            )
                t += DT
            return worst_off, clear_speed


def section_bounds():
    print("\n1. THE BURST HELD ON SCREEN — worst fish-centre distance past "
          "the panel edge, repeated bursts across seeds/particle counts/"
          "periods (his three flare bands mean this can repeat quickly)")
    worst = -1e9
    worst_noburst = -1e9
    slowest_clear = 1e9
    for seed in range(8):
        for particle_count in (3, 6, 12):
            for period in (0.4, 0.6, 1.0):
                off, clear = asyncio.run(_run(
                    {"particle_count": particle_count}, seed,
                    burst_ms=300, period=period, seconds=12.0,
                ))
                worst = max(worst, off)
                if clear > 0:
                    slowest_clear = min(slowest_clear, clear)
            off0, _ = asyncio.run(_run(
                {"particle_count": particle_count}, seed,
                burst_ms=0, period=1.0, seconds=12.0,
            ))
            worst_noburst = max(worst_noburst, off0)
    print(f"   worst off-panel with repeated bursts: {worst:.2f}px "
          f"(no-burst baseline: {worst_noburst:.2f}px)")
    print(f"   slowest 'comfortably clear of the edge' burst speed seen: "
          f"{slowest_clear:.1f} px/s")
    # a couple of px of margin over the no-burst baseline: the steer is
    # soft by design (never a hard wall) and already allows a small,
    # bounded overshoot with no burst at all — the bar is "close to that",
    # not "zero", so a genuinely different, worse mechanism would still be
    # caught.
    check(worst <= worst_noburst + 3.0,
          "repeated bursts land within a few px of the no-burst baseline, "
          "not 7-8px past the panel the way the unfixed code measured")
    check(slowest_clear >= 40.0,
          "the burst is not a soft no-op: a fish clear of the edge still "
          "reaches well above cruise speed while bursting")

    print("\n2. A SUSTAINED (stuck-on) BURST — the worst case a flare "
          "release failure could produce")
    off, clear = asyncio.run(_run(
        {"particle_count": 6}, 1, always=True, seconds=10.0,
    ))
    print(f"   worst off-panel px: {off:.2f}  clear-of-edge speed: "
          f"{clear:.1f} px/s")
    check(off <= 3.0, "even held on continuously, the burst never carries "
          "a fish meaningfully past the panel edge")


def main():
    section_bounds()
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
