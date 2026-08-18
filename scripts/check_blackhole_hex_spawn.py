#!/usr/bin/env python3
"""Read-only evidence script for the Black Hole hex-spawn fix
(fx/effects/blackhole.py SPAWN_ANNULUS_MIN/MAX, PR fm/spectra-blackhole-hex-spawn).

Blackhole2d (`fx/effects/blackhole.py`) has no idea a matrix virtual's
addressable rectangle can be mostly gap cells — it spawns particles purely in
normalized (r, theta) space and lets fx/virtuals.py's segment routing decide,
per pixel, whether that lands on a real device or the `gap-*` dummy. On his
live `crystal-mapper` virtual (72x37 = 2664 addressable cells, 976 real —
storage/device_profiles/crystal-mapper.json, built by
tools/gifsmith/device_profiles.py from the live LedFX segment list) the real
cells form a hex-lattice silhouette: a flat, exact 50% real-pixel density out
to r<=0.85 (r=1 is the panel's own rectangular edge, same normalized units as
`radius_scale`), collapsing to ~20% by r=1.0, ~7% by r=1.1, and 0% past
r=1.2 — the rectangle's corners are pure gap.

Blackhole2d's infall-mode (`reverse=False`, the mode his real "Black Hole V2"
scene uses on Matrix/crystal-mapper — storage/spectra/scenes.json) spawn
annulus used to be a fixed (0.90, 1.05): almost entirely inside that
near-zero-density corner band, so a freshly spawned blob was invisible until
it had fallen most of the way to the horizon. The fix pulls the annulus in to
SPAWN_ANNULUS_MIN..MAX = 0.70..0.85 (see the constant's own comment in
blackhole.py) — inside the flat 50% interior, not a uniform shrink of the
whole effect (radius_scale/sx/sy, which set the overall panel-filling scale
and the fall/travel distance, are untouched).

This script re-derives the same real-cell-density-by-radius numbers against
the real device profile and Monte-Carlo-samples both the old and new spawn
annuli, so this remains checkable evidence rather than a claim. Never writes
anything; pass --path to check a different device profile (e.g. a future
Matrix virtual) instead of the default crystal-mapper.json.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fx.effects.blackhole import SPAWN_ANNULUS_MAX, SPAWN_ANNULUS_MIN  # noqa: E402

DEFAULT_PROFILE = REPO_ROOT / "storage" / "device_profiles" / "crystal-mapper.json"

# The annulus this script proves the fix replaced. Not imported from
# blackhole.py on purpose — it no longer exists there; restating it here is
# what makes this a *regression* check (old band stays visibly worse) rather
# than only a "new band looks fine in isolation" one.
OLD_ANNULUS_MIN = 0.90
OLD_ANNULUS_MAX = 1.05


def rle_to_mask(runs: list[int]) -> list[bool]:
    mask: list[bool] = []
    value = False
    for run in runs:
        mask.extend([value] * run)
        value = not value
    return mask


def load_grid(path: Path) -> tuple[list[list[bool]], int, int]:
    profile = json.loads(path.read_text())
    rows, cols = profile["rows"], profile["cols"]
    mask = rle_to_mask(profile["mask_rle"])
    grid = [mask[r * cols : (r + 1) * cols] for r in range(rows)]
    return grid, rows, cols


def density_by_radius(grid: list[list[bool]], rows: int, cols: int, step: float = 0.05):
    cx = cy = None
    sx = (cols - 1) / 2.0
    sy = (rows - 1) / 2.0
    cx = sx
    cy = sy
    buckets: dict[float, list[int]] = {}
    for r in range(rows):
        for c in range(cols):
            dx = (c - cx) / sx
            dy = (r - cy) / sy
            rad = math.sqrt(dx * dx + dy * dy)
            b = round(rad / step) * step
            tot_real = buckets.setdefault(round(b, 2), [0, 0])
            tot_real[0] += 1
            if grid[r][c]:
                tot_real[1] += 1
    return buckets


def annulus_real_fraction(
    grid: list[list[bool]], rows: int, cols: int, lo: float, hi: float,
    samples: int = 200_000, seed: int = 20260817,
) -> float:
    sx = (cols - 1) / 2.0
    sy = (rows - 1) / 2.0
    cx, cy = sx, sy
    rng = random.Random(seed)
    hits = 0
    for _ in range(samples):
        r = rng.uniform(lo, hi)
        theta = rng.uniform(0.0, 2.0 * math.pi)
        x = cx + r * sx * math.cos(theta)
        y = cy + r * sy * math.sin(theta)
        xi, yi = round(x), round(y)
        if 0 <= xi < cols and 0 <= yi < rows and grid[yi][xi]:
            hits += 1
    return hits / samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PROFILE,
                        help="Path to a device_profiles/<virtual>.json file "
                             "(default: storage/device_profiles/crystal-mapper.json)")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"no device profile at {args.path}", file=sys.stderr)
        return 2

    grid, rows, cols = load_grid(args.path)
    real_total = sum(sum(1 for v in row if v) for row in grid)
    print(f"{args.path.name}: {cols}x{rows} = {cols * rows} addressable, "
          f"{real_total} real ({real_total / (cols * rows):.1%})")

    print("\nreal-cell density by normalized radius (r=1 = panel edge):")
    buckets = density_by_radius(grid, rows, cols)
    for b in sorted(buckets):
        tot, real = buckets[b]
        print(f"  r~{b:.2f}: total={tot:4d} real={real:4d} frac={real / tot:.3f}")

    old_frac = annulus_real_fraction(grid, rows, cols, OLD_ANNULUS_MIN, OLD_ANNULUS_MAX)
    new_frac = annulus_real_fraction(grid, rows, cols, SPAWN_ANNULUS_MIN, SPAWN_ANNULUS_MAX)
    print(f"\nold spawn annulus [{OLD_ANNULUS_MIN}, {OLD_ANNULUS_MAX}]: "
          f"{old_frac:.1%} of spawns land on a real pixel")
    print(f"new spawn annulus [{SPAWN_ANNULUS_MIN}, {SPAWN_ANNULUS_MAX}]: "
          f"{new_frac:.1%} of spawns land on a real pixel")

    ok = True
    if not (new_frac >= 0.45):
        print(f"FAIL: new annulus real-hit fraction {new_frac:.1%} is not "
              f"solidly inside the flat ~50% interior (expected >= 45%)")
        ok = False
    if not (new_frac > old_frac * 1.5):
        print(f"FAIL: new annulus ({new_frac:.1%}) is not a decisive "
              f"improvement over the old one ({old_frac:.1%})")
        ok = False

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
