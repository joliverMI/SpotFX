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

THE TWO COORDINATE SYSTEMS, and why both are needed (the first version of
this script used neither, and drew every shape squashed to about half its
width — caught in review of PR 519):

- **Normalized space** is where the shape is PLACED, because it is where
  every Twod effect works: a cell is `(col - cx) / ((cols - 1) / 2)`,
  `(row - cy) / ((rows - 1) / 2)` — the effect's own `sx`/`sy` — so x and
  y each run -1..1 across the panel. `SIZE` is a FRACTION of the panel's
  half-height (the plan's `word_shape_size`, default 0.62), never a number
  of cells: one unit of shape height is 0.62 x 18 = 11.2 ROWS, while one
  unit of shape width is 0.62 x 35.5 = 22.0 COLUMNS.
- **Physical pitch units** are where every DISTANCE here is measured,
  because a crystal column is half a real-cell pitch and a row is
  sqrt(3)/2 of one (that is what a hex lattice with the parity flip means:
  real cells sit 2 columns apart along a row, and the next row is offset
  by one column). A cell is `(col - cx) * 0.5`, `(row - cy) * 0.866`, and
  one cell pitch is 1.0 — the distance between two neighbouring real
  cells, in any of the six directions.

So a shape drawn with one SIZE comes out about 14% wider than tall in the
room — the panel's own aspect, which the effect's `sx`/`sy` carry, the same
way every other effect's circle does. That is the thing being measured, not
an error to correct here.

WHAT EACH NUMBER MEANS

- **Outline cells**: real cells within one cell pitch of the outline.
  **This count is the DENOMINATOR every wave-1 "outline coverage" check
  uses** ("at the hold, captives light at least 65% of the outline
  cells"), so it is printed per shape and pinned by
  tests/test_word_shapes.py: it must not drift silently, because every
  clarity bar in the plan is a fraction of it.
- **Inside cells**: real cells strictly inside the outline — the
  denominator for "the inside of the shape is black / lit" bars.
- **Thinnest point**: the fewest real cells within one cell pitch of ANY
  point along the outline (OUTLINE_SAMPLES samples by arc length; the
  verdict is the same from 720 to 2,880). It must be at least 2: the hex
  lattice loses a one-cell stroke on alternate rows (the device profile's
  own `min_stroke_px: 2`), so a place on the outline with only one real
  cell near it is a place where the shape breaks into dashes. Measured
  along the outline rather than per row on purpose — per row, a tip row
  holds one cell because it IS the tip, which says nothing about whether
  the stroke survives. `--rows` prints the per-row counts as well.
- **Star-shaped**: re-measured here INDEPENDENTLY of the library. This
  script walks each ray outward in small steps counting sign changes of
  `sdf`; the library's own verdict comes from an analytic ray/segment
  cast. A shape whose entry claims `star_shaped` but fails the walk is a
  FAILURE, because `polar()` — Black Hole's shaped horizon, STAR's shaped
  radius — is only meaningful for a shape that has one radius per angle.

`--ascii` draws each shape on the real mask: `o` an outline cell, `+` a
cell inside it, `.` a real cell that is neither, a space a gap cell. It is
the quickest way to see that a new shape is representational before
anything renders in the room.

Pass `--size-fraction` to measure another size, or `--path` another device
profile. This script never writes anything.
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

# The plan's default shape size: SIZE as a fraction of the panel's
# half-height, in the effects' own normalized coordinates.
DEFAULT_SIZE_FRACTION = 0.62

# One addressable step in physical units, where 1.0 is one real-cell pitch
# (the hex lattice: real cells 2 columns apart along a row, the next row
# offset by one column, so rows are sqrt(3)/2 of a pitch apart).
COLUMN_PITCH = 0.5
ROW_PITCH = math.sqrt(3.0) / 2.0

# "Within one cell pitch of the outline", in those units.
CELL_PITCH = 1.0

# The hex lattice loses a one-cell stroke on alternate rows, so two is the
# floor everywhere along the outline (the profile's own min_stroke_px).
MIN_LIT_CELLS = 2

# Samples along the outline. The verdict is unchanged from 720 to 2,880
# (measured), so this is comfortably past the knee.
OUTLINE_SAMPLES = 1440

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
        """Half the panel's height in ROWS, the denominator every Twod
        effect's `sy` uses: `cy = (r_height - 1) * 0.5`."""
        return (self.rows - 1) / 2.0

    @property
    def half_width(self) -> float:
        """Half the panel's width in COLUMNS — `sx`'s own denominator."""
        return (self.cols - 1) / 2.0

    def normalized(self) -> tuple[np.ndarray, np.ndarray]:
        """Every cell in the effects' normalized space (-1..1 per axis)."""
        cols = (np.arange(self.cols) - self.half_width) / self.half_width
        rows = (np.arange(self.rows) - self.half_height) / self.half_height
        return np.meshgrid(cols, rows)

    def real_physical(self) -> tuple[np.ndarray, np.ndarray]:
        """Every REAL cell's position in physical pitch units."""
        rows_idx, cols_idx = np.nonzero(self.grid)
        return ((cols_idx - self.half_width) * COLUMN_PITCH,
                (rows_idx - self.half_height) * ROW_PITCH)

    def to_physical(self, x: np.ndarray, y: np.ndarray,
                    size: float) -> tuple[np.ndarray, np.ndarray]:
        """A point in the SHAPE's unit box, drawn at `size` (its
        normalized half-height), in physical pitch units."""
        return (x * size * self.half_width * COLUMN_PITCH,
                y * size * self.half_height * ROW_PITCH)


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


def load_panel(path: Path = DEFAULT_PROFILE) -> Panel:
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
            size: float) -> tuple[Measurement, np.ndarray, np.ndarray]:
    """Measure one shape drawn at `size` — its half-height as a fraction
    of the panel's, in the effects' normalized space — on the panel's real
    mask. Returns the measurement, the outline-cell mask and the
    inside-cell mask, so a caller can draw them."""
    # inside: a topological test, so it is done in the shape's own space
    norm_x, norm_y = panel.normalized()
    inside = (shape.sdf(norm_x / size, norm_y / size) < 0.0) & panel.grid

    # every distance below is in physical pitch units
    real_x, real_y = panel.real_physical()
    s = np.linspace(0.0, 1.0, OUTLINE_SAMPLES, endpoint=False)
    unit_x, unit_y = shape.at(s)
    out_x, out_y = panel.to_physical(unit_x, unit_y, size)
    near = np.hypot(real_x[None, :] - out_x[:, None],
                    real_y[None, :] - out_y[:, None]) <= CELL_PITCH

    outline = np.zeros_like(panel.grid)
    rows_idx, cols_idx = np.nonzero(panel.grid)
    hit = near.any(axis=0)
    outline[rows_idx[hit], cols_idx[hit]] = True

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
    ), outline, inside


def render_ascii(panel: Panel, outline: np.ndarray,
                 inside: np.ndarray) -> str:
    """The shape on the real mask: `o` outline, `+` inside, `.` a real cell
    that is neither, a space a gap cell. One character per addressable
    column, so the hex lattice itself shows."""
    lines = []
    for row in range(panel.rows):
        chars = []
        for col in range(panel.cols):
            if not panel.grid[row, col]:
                chars.append(" ")
            elif outline[row, col]:
                chars.append("o")
            elif inside[row, col]:
                chars.append("+")
            else:
                chars.append(".")
        lines.append("".join(chars).rstrip())
    return "\n".join(lines)


def print_rows(shape_id: str, outline: np.ndarray) -> None:
    print(f"  {shape_id}: outline cells per row")
    for row in range(outline.shape[0]):
        n = int(outline[row].sum())
        if n:
            cols = np.nonzero(outline[row])[0]
            print(f"    row {row:2d}: {n:2d} cells, columns "
                  f"{cols.min():2d}-{cols.max():2d}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--path", type=Path, default=DEFAULT_PROFILE,
                    help="device profile to measure against")
    ap.add_argument("--size-fraction", type=float,
                    default=DEFAULT_SIZE_FRACTION,
                    help="the shape's half-height as a fraction of the "
                         "panel's, in the effects' normalized space (the "
                         "plan's word_shape_size, default 0.62)")
    ap.add_argument("--rows", action="store_true",
                    help="also print each shape's outline cells per row")
    ap.add_argument("--ascii", action="store_true",
                    help="also draw each shape on the real mask")
    args = ap.parse_args()

    panel = load_panel(args.path)
    size = args.size_fraction
    real = int(panel.grid.sum())
    cells = panel.rows * panel.cols
    print(f"{args.path.name}: {panel.rows}x{panel.cols} = {cells} "
          f"addressable cells, {real} real ({real / cells:.1%}), "
          f"min_stroke_px {panel.min_stroke_px}")
    print(f"SIZE {size} = {size} x the panel's half-height, in the effects' "
          f"normalized space: {size * panel.half_width:.1f} columns of "
          f"half-width, {size * panel.half_height:.1f} rows of half-height")
    print(f"distances in physical pitch units (column {COLUMN_PITCH}, row "
          f"{ROW_PITCH:.3f}); one cell pitch = {CELL_PITCH}\n")

    header = (f"{'shape':9s} {'outline':>8s} {'inside':>7s} "
              f"{'thinnest':>9s} {'rows':>8s} {'star-shaped':>13s}")
    print(header)
    print("-" * len(header))

    measurements = []
    drawings = {}
    for shape in word_shapes.SHAPES.values():
        m, outline, inside = measure(shape, panel, size)
        measurements.append(m)
        drawings[shape.id] = (outline, inside)
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
            print_rows(m.shape_id, drawings[m.shape_id][0])

    if args.ascii:
        for m in measurements:
            outline, inside = drawings[m.shape_id]
            print(f"\n{m.shape_id} at SIZE {size} "
                  f"(o outline, + inside, . real, ' ' gap)")
            print(render_ascii(panel, outline, inside))

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
