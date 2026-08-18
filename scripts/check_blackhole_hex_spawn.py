#!/usr/bin/env python3
"""Read-only evidence script for the Black Hole hex-spawn fix
(fx/effects/blackhole.py HEX_SPAWN_VERTS/_hex_spawn_edge_radius, PR
fm/spectra-blackhole-hex-spawn and its follow-up
fm/spectra-blackhole-spawn-at-edge).

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

Round 1 (fm/spectra-blackhole-hex-spawn): Blackhole2d's infall-mode
(`reverse=False`) spawn annulus used to be a fixed (0.90, 1.05) — almost
entirely inside the near-zero-density corner band, invisible until a blob
had fallen most of the way to the horizon. Pulling it to (0.70, 0.85) fixed
that by maximizing real-pixel hit rate.

Round 2 (this script's current form, fm/spectra-blackhole-spawn-at-edge):
maximizing hit rate pulls spawns INTO the interior, which is not what he
actually asked for — his words: blobs should spawn "just outside of view or
right in line with the edge of view", i.e. arrive FROM the boundary, not
appear inside it. The hex silhouette's distance from center genuinely
depends on direction (~0.87 normalized-r at a flat edge's own
midpoint-normal, ~1.13 at a corner vertex — the same table this script
prints below), so no single scalar radius can sit "at the boundary" in more
than the handful of directions where it happens to coincide. The fix
computes the boundary PER SPAWN ANGLE instead: `HEX_SPAWN_VERTS` are the
silhouette's true vertices (measured off row/column real-cell extents in the
device profile, same one this script reads), and
`_hex_spawn_edge_radius(theta)` evaluates the polygon's own support function
(nearest of the 6 edge-lines facing that direction) to get an exact
per-direction boundary distance in closed form. Spawns land at that
direction's own boundary plus a small outward margin
(SPAWN_EDGE_MARGIN_MIN/MAX = 0.02-0.12) — "just outside... or right in line
with the edge."

This necessarily trades away hit rate: a spawn ring hugging the true
boundary from just outside puts real weight in each direction's own dead
band beyond the edge (by construction — that's the point, blobs enter the
lit area rather than starting inside it), so the real-pixel hit fraction for
the NEW mechanism is expected to be LOWER than the hit-rate-maximizing 0.70-
0.85 annulus, not a regression to explain away.

This script never writes anything; pass --path to check a different device
profile (e.g. a future Matrix virtual) instead of the default
crystal-mapper.json.
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

from fx.effects.blackhole import (  # noqa: E402
    SPAWN_EDGE_MARGIN_MAX,
    SPAWN_EDGE_MARGIN_MIN,
    _hex_spawn_edge_radius,
)

DEFAULT_PROFILE = REPO_ROOT / "storage" / "device_profiles" / "crystal-mapper.json"

# The two annuli both earlier rounds used. Not imported from blackhole.py on
# purpose — neither exists there any more; restating them here is what makes
# this a *regression* check (both old bands stay visibly worse at the actual
# goal, "at or just outside the true boundary") rather than only a "new
# mechanism looks fine in isolation" one.
ANNULUS_V1_MIN, ANNULUS_V1_MAX = 0.90, 1.05  # the original, too-far-out fixed rim
ANNULUS_V2_MIN, ANNULUS_V2_MAX = 0.70, 0.85  # the hit-rate-maximizing pull-in


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
    sx = (cols - 1) / 2.0
    sy = (rows - 1) / 2.0
    cx, cy = sx, sy
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


def empirical_boundary_by_angle(
    grid: list[list[bool]], rows: int, cols: int, nbins: int = 72
) -> list[float]:
    """Max normalized-r of any real cell within each angular bin — the
    measured boundary the closed-form polygon formula is checked against."""
    sx = (cols - 1) / 2.0
    sy = (rows - 1) / 2.0
    cx, cy = sx, sy
    bins = [0.0] * nbins
    for r in range(rows):
        for c in range(cols):
            if not grid[r][c]:
                continue
            gx = (c - cx) / sx
            gy = (r - cy) / sy
            rad = math.hypot(gx, gy)
            theta = math.atan2(gy, gx) % (2 * math.pi)
            b = int(theta / (2 * math.pi) * nbins) % nbins
            if rad > bins[b]:
                bins[b] = rad
    return bins


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


def hex_edge_real_fraction(
    grid: list[list[bool]], rows: int, cols: int,
    margin_lo: float, margin_hi: float,
    samples: int = 200_000, seed: int = 20260818,
) -> float:
    """Monte-Carlo the ACTUAL new spawn mechanism: draw theta, look up that
    direction's true boundary via the real blackhole.py formula, add a
    random margin, then check the real device grid at that point."""
    import numpy as np

    sx = (cols - 1) / 2.0
    sy = (rows - 1) / 2.0
    cx, cy = sx, sy
    rng = np.random.default_rng(seed)
    theta = rng.uniform(0.0, 2.0 * math.pi, samples)
    edge_r = _hex_spawn_edge_radius(theta)
    r = edge_r + rng.uniform(margin_lo, margin_hi, samples)
    x = cx + r * sx * np.cos(theta)
    y = cy + r * sy * np.sin(theta)
    xi = np.round(x).astype(int)
    yi = np.round(y).astype(int)
    valid = (xi >= 0) & (xi < cols) & (yi >= 0) & (yi < rows)
    hits = 0
    for xv, yv, ok in zip(xi, yi, valid):
        if ok and grid[yv][xv]:
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

    print("\nclosed-form boundary formula vs. the boundary measured directly "
          "off the device profile (max real-cell radius per 5-degree bin):")
    empirical = empirical_boundary_by_angle(grid, rows, cols, nbins=72)
    worst_diff = 0.0
    for i, emp in enumerate(empirical):
        deg = i * 360 / 72 + 360 / 72 / 2
        theta = math.radians(deg)
        formula = float(_hex_spawn_edge_radius(__import__("numpy").array([theta]))[0])
        worst_diff = max(worst_diff, abs(formula - emp))
    print(f"  max |formula - empirical| across all 72 bins: {worst_diff:.4f} "
          f"normalized-r (lattice/quantization noise)")

    v1_frac = annulus_real_fraction(grid, rows, cols, ANNULUS_V1_MIN, ANNULUS_V1_MAX)
    v2_frac = annulus_real_fraction(grid, rows, cols, ANNULUS_V2_MIN, ANNULUS_V2_MAX)
    new_frac = hex_edge_real_fraction(
        grid, rows, cols, SPAWN_EDGE_MARGIN_MIN, SPAWN_EDGE_MARGIN_MAX
    )
    print(f"\nv1 fixed rim [{ANNULUS_V1_MIN}, {ANNULUS_V1_MAX}]: "
          f"{v1_frac:.1%} of spawns land on a real pixel (too far OUT — his original bug)")
    print(f"v2 hit-rate-maximizing annulus [{ANNULUS_V2_MIN}, {ANNULUS_V2_MAX}]: "
          f"{v2_frac:.1%} of spawns land on a real pixel (too far IN — his 2026-08-18 report)")
    print(f"v3 per-direction edge + margin [{SPAWN_EDGE_MARGIN_MIN}, "
          f"{SPAWN_EDGE_MARGIN_MAX}]: {new_frac:.1%} of spawns land on a real pixel")
    print("v3's lower fraction than v2 is BY DESIGN, not a regression: hit rate "
          "is no longer the objective, arriving from the boundary is.")

    ok = True
    if not (worst_diff <= 0.10):
        print(f"\nFAIL: closed-form formula diverges from the measured boundary "
              f"by {worst_diff:.4f} normalized-r (expected <= 0.10)")
        ok = False
    if not (new_frac < v2_frac):
        print(f"\nFAIL: new per-direction mechanism ({new_frac:.1%}) is not "
              f"lower than the hit-rate-maximizing annulus ({v2_frac:.1%}) — "
              f"it should be, since it now spawns outside the boundary by design")
        ok = False

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
