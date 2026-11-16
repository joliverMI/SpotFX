#!/usr/bin/env python3
"""Read-only evidence script for the Word Shapes shape library
(`fx/effects/word_shapes.py`, Word Shapes plan row W0.1 section 2.1).

It measures every shape in the library AGAINST THE REAL HEX MASK of his
live `crystal-mapper` virtual — `storage/device_profiles/
crystal-mapper.json`, 72x37 = 2,664 addressable cells of which only 976
are real light, arranged as a hexagon with the real-column parity flipping
row to row (`.claude/skills/crystal-hex-grid/SKILL.md`). Geometry that
looks right in the unit box can still be invisible there, so this is the
check that stands between a new shape and the room.

WHY THESE NUMBERS

- **Outline cells** are the real cells within ONE CELL PITCH of the
  outline. On this lattice a real cell's nearest real neighbour is one
  column AND one row away — the parity flip means the cell two columns
  along is its own row's neighbour at distance 2, while the diagonal one is
  at sqrt(2) — so the pitch is sqrt(2) addressable cells, not 1.
  **This count is the DENOMINATOR every wave-1 "outline coverage" check
  uses** ("at the hold, captives light at least 65% of the outline cells"),
  so it is printed per shape and pinned by tests/test_word_shapes.py: it
  must not drift silently, because every clarity bar in the plan is a
  fraction of it.
- **Inside cells** are the real cells strictly inside the outline — the
  denominator for "the inside of the shape is black / lit" bars.
- **Thinnest point** is the fewest real cells within one cell pitch of ANY
  point along the outline (720 samples by arc length). It must be at least
  2: the hex lattice loses a one-cell stroke on alternate rows (the device
  profile's own `min_stroke_px: 2`), so a place on the outline with only
  one real cell near it is a place where the shape breaks into dashes. This
  is measured along the outline rather than per row on purpose — per row,
  a tip row holds one cell because it IS the tip (the stroke is thick
  vertically there), which says nothing about whether the stroke survives.
  `--rows` prints the per-row cell counts as well.
- **Star-shaped** is re-measured here INDEPENDENTLY of the library: this
  script walks each ray outward in small steps counting sign changes of
  `sdf`, where `word_shapes.build()` uses an analytic ray/segment cast. A
  shape whose entry claims `star_shaped` but fails the walk is a FAILURE,
  because `polar()` — Black Hole's shaped horizon, STAR's shaped radius —
  is only meaningful for a shape that has one radius per angle.

The size is the plan's default: `SIZE = 0.62 x the panel's half-height`
(`word_shape_size`), which is 0.62 x (37 - 1) / 2 = 11.16 cells on
crystal-mapper. Pass `--size-fraction` to measure another one, or `--path`
another device profile.

This script never writes anything.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fx.effects import word_shapes  # noqa: E402

DEFAULT_PROFILE = REPO_ROOT / "storage" / "device_profiles" / "crystal-mapper.json"

# The plan's default shape size, as a fraction of the panel's half-height.
DEFAULT_SIZE_FRACTION = 0.62

# One cell pitch on a hex lattice whose real-column parity flips per row:
# the nearest real neighbour is one column and one row away.
CELL_PITCH = math.sqrt(2.0)

# The hex lattice loses a one-cell stroke on alternate rows, so two is the
# floor everywhere along the outline (the profile's own min_stroke_px).
MIN_LIT_CELLS = 2

# Samples along the outline for the thinnest-point measurement. The verdict
# is stable from 360 up (measured), so this is comfortably past the knee.
OUTLINE_SAMPLES = 720

# The independent star-shaped walk: rays, and the step along each.
WALK_RAYS = 1440
WALK_STEP = 0.002


@dataclass
class Panel:
    rows: int
    cols: int
    grid: np.ndarray            # (rows, cols) bool — True = real light
    min_stroke_px: int

    @property
    def half_height(self) -> float:
        """The panel's own half-height in cells, in the same convention
        every Twod effect uses: `cy = (r_height - 1) * 0.5`."""
        return (self.rows - 1) / 2.0

    @property
    def centre(self) -> tuple[float, float]:
        return (self.cols - 1) / 2.0, (self.rows - 1) / 2.0


@dataclass
class Measurement:
    shape_id: str
    outline_cells: int
    inside_cells: int
    thinnest: int
    thinnest_s: float
    row_span: tuple[int, int]
    claims_star_shaped: bool
    walked_star_shaped: bool
    worst_ray_crossings: int

    @property
    def ok(self) -> bool:
        return (self.thinnest >= MIN_LIT_CELLS
                and (self.walked_star_shaped or not self.claims_star_shaped))


def load_panel(path: Path) -> Panel:
    prof = json.loads(path.read_text())
    rows, cols = int(prof["rows"]), int(prof["cols"])
    flat: list[bool] = []
    value = False
    for run in prof["mask_rle"]:
        flat.extend([value] * int(run))
        value = not value
    grid = np.asarray(flat, dtype=bool)
    if grid.size != rows * cols:
        raise ValueError(f"{path}: mask_rle decodes to {grid.size} cells, "
                         f"expected {rows * cols}")
    return Panel(rows=rows, cols=cols, grid=grid.reshape(rows, cols),
                 min_stroke_px=int(prof.get("min_stroke_px", MIN_LIT_CELLS)))


def walk_star_shaped(shape: word_shapes.Shape) -> tuple[bool, int]:
    """Re-measure star-shapedness INDEPENDENTLY of the library: step
    outward along each ray and count sign changes of `sdf`. Returns
    (every ray crosses exactly once, the worst ray's crossing count)."""
    thetas = np.arange(WALK_RAYS) * (2.0 * math.pi / WALK_RAYS)
    r_max = float(np.linalg.norm(shape.points, axis=1).max()) * 1.1
    radii = np.arange(0.0, r_max, WALK_STEP)
    xs = np.cos(thetas)[:, None] * radii[None, :]
    ys = np.sin(thetas)[:, None] * radii[None, :]
    inside = shape.sdf(xs, ys) < 0.0
    crossings = np.sum(inside[:, :-1] != inside[:, 1:], axis=1)
    return bool(np.all(crossings == 1)), int(crossings.max())


def measure(shape: word_shapes.Shape, panel: Panel,
            size: float) -> tuple[Measurement, np.ndarray]:
    """Measure one shape at `size` (its half-height in cells) on the
    panel's real mask. Returns the measurement and the outline-cell mask
    itself, so a caller can draw or reuse it."""
    cx, cy = panel.centre
    xs, ys = np.meshgrid(np.arange(panel.cols) - cx,
                         np.arange(panel.rows) - cy)
    dist = shape.sdf(xs / size, ys / size) * size
    outline = (np.abs(dist) <= CELL_PITCH) & panel.grid
    inside = (dist < 0.0) & panel.grid

    # the thinnest place along the outline, in real cells within one pitch
    rows_idx, cols_idx = np.nonzero(panel.grid)
    real_x = cols_idx - cx
    real_y = rows_idx - cy
    s = np.linspace(0.0, 1.0, OUTLINE_SAMPLES, endpoint=False)
    ox, oy = shape.at(s)
    near = np.hypot(real_x[None, :] - ox[:, None] * size,
                    real_y[None, :] - oy[:, None] * size) <= CELL_PITCH
    per_sample = near.sum(axis=1)
    worst = int(np.argmin(per_sample))

    occupied = np.nonzero(outline.sum(axis=1))[0]
    span = ((int(occupied[0]), int(occupied[-1])) if occupied.size
            else (-1, -1))
    walked, worst_rays = walk_star_shaped(shape)
    return Measurement(
        shape_id=shape.id,
        outline_cells=int(outline.sum()),
        inside_cells=int(inside.sum()),
        thinnest=int(per_sample.min()),
        thinnest_s=float(s[worst]),
        row_span=span,
        claims_star_shaped=bool(shape.star_shaped),
        walked_star_shaped=walked,
        worst_ray_crossings=worst_rays,
    ), outline


def print_rows(shape_id: str, outline: np.ndarray) -> None:
    print(f"  {shape_id}: outline cells per row")
    for row in range(outline.shape[0]):
        n = int(outline[row].sum())
        if n:
            cols = np.nonzero(outline[row])[0]
            print(f"    row {row:2d}: {n:2d} cells, columns "
                  f"{cols.min():2d}-{cols.max():2d}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--path", type=Path, default=DEFAULT_PROFILE,
                    help="device profile to measure against")
    ap.add_argument("--size-fraction", type=float,
                    default=DEFAULT_SIZE_FRACTION,
                    help="shape half-height as a fraction of the panel's "
                         "(the plan's word_shape_size, default 0.62)")
    ap.add_argument("--rows", action="store_true",
                    help="also print each shape's outline cells per row")
    args = ap.parse_args()

    panel = load_panel(args.path)
    size = args.size_fraction * panel.half_height
    real = int(panel.grid.sum())
    print(f"{args.path.name}: {panel.rows}x{panel.cols} = "
          f"{panel.rows * panel.cols} addressable cells, {real} real "
          f"({real / (panel.rows * panel.cols):.1%}), "
          f"min_stroke_px {panel.min_stroke_px}")
    print(f"shape size: {args.size_fraction} x half-height "
          f"{panel.half_height:.1f} = {size:.2f} cells; one cell pitch = "
          f"{CELL_PITCH:.4f} cells\n")

    header = (f"{'shape':9s} {'outline':>8s} {'inside':>7s} "
              f"{'thinnest':>9s} {'rows':>8s} {'star-shaped':>13s}")
    print(header)
    print("-" * len(header))

    measurements = []
    outlines = {}
    for shape in word_shapes.SHAPES.values():
        m, outline = measure(shape, panel, size)
        measurements.append(m)
        outlines[shape.id] = outline
        verdict = ("yes" if m.walked_star_shaped else
                   f"NO (worst ray {m.worst_ray_crossings}x)")
        if m.claims_star_shaped != m.walked_star_shaped:
            verdict += " != entry"
        print(f"{m.shape_id:9s} {m.outline_cells:8d} {m.inside_cells:7d} "
              f"{m.thinnest:9d} {m.row_span[0]:3d}-{m.row_span[1]:<4d} "
              f"{verdict:>13s}")

    print("\nthinnest point: the fewest real cells within one cell pitch of "
          f"any point along the outline (bar: >= {MIN_LIT_CELLS})")
    for m in measurements:
        print(f"  {m.shape_id:9s} {m.thinnest} cells, at s={m.thinnest_s:.3f} "
              f"of the way round")

    if args.rows:
        print()
        for m in measurements:
            print_rows(m.shape_id, outlines[m.shape_id])

    failures = [m for m in measurements if not m.ok]
    if failures:
        print()
        for m in failures:
            if m.thinnest < MIN_LIT_CELLS:
                print(f"FAIL: {m.shape_id}: its thinnest point has "
                      f"{m.thinnest} real cell(s) within one cell pitch "
                      f"(needs >= {MIN_LIT_CELLS}); at this size its "
                      f"outline breaks into dashes on the hex lattice. "
                      f"Make the shape rounder, or draw it larger.")
            if m.claims_star_shaped and not m.walked_star_shaped:
                print(f"FAIL: {m.shape_id}: its entry claims star_shaped, "
                      f"but a ray crosses its outline "
                      f"{m.worst_ray_crossings} times — polar() would lie. "
                      f"Fix the outline, or let the entry report "
                      f"star_shaped False (at(s) and sdf() still work).")
        print("\nFAIL")
        return 1

    print("\nPASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
