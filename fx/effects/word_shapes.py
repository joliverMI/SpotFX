"""THE SHAPE LIBRARY — the one source of every shape a Word Shapes effect
can draw, and the three views an effect needs to draw it.

Built 2026-11-15 (Word Shapes plan row W0.1, section 2.1, approved by the
Admiral 2026-11-15; his words for the row: "Some starting shapes would be a
heart, star, and diamond. The effects would form an outline that represents
those. ... Make it easy to add more shapes and associations down the road").

A shape is ONE ENTRY: an id, a name, a closed outline, its starting sung
words, and whether it must stand upright. Everything else — the radius per
angle, the walk along the outline, the signed distance field, the Sung
labels card, Claude's shape labels, every effect's rendering — is DERIVED
from that one outline, so adding a shape later is one entry and nothing
else. `SHAPES` is the registry, in declaration order.

THE UNIT BOX. `points` is a dense closed polyline (no repeated closing
point) in a unit box: centred on (0, 0) with height exactly 2.0 (y from -1
to +1) and whatever width the shape needs — the heart is wider than it is
tall, the diamond narrower. **y points DOWN**, as it does on the panel and
in every effect here, so a shape's "up" is -y and `theta = atan2(y, x)`
is the same angle an effect already computes. The outline runs
counter-clockwise in the coordinate algebra (a positive shoelace area,
the direction of increasing `theta`); drawn on the panel with y downward
that reads as clockwise. `build()` enforces the box and the orientation, so
a new entry can be written in whatever units and winding are natural for it.

THE CONVENTION AN EFFECT USES. A view is in unit coordinates; an effect
scales it to its own size, with SIZE the shape's half-height in that
effect's own coordinates:

    r      = SIZE * shape.polar(theta)        # radius per angle
    x, y   = SIZE * shape.at(s)               # a point along the outline
    d      = shape.sdf(x / SIZE, y / SIZE) * SIZE   # distance in cells

The plan's default SIZE is 0.62 of the panel's half-height
(`word_shape_size`, a per-effect registered param added in wave 1) — on his
live crystal-mapper that is 0.62 * (37 - 1) / 2 = 11.16 cells. Nothing in
this module knows about a panel, a device or a told key: it is pure
geometry, and `scripts/check_word_shapes.py` is what measures a shape
against the real hex mask.

ACCURACY AND COST, measured (both pinned by tests/test_word_shapes.py, so
a change that makes either worse is a visible one):

- `polar` is exact to 1e-13 at every whole degree (its own bin) and within
  1.0% of a direct ray cast at the worst half-bin offset — a tenth of a
  cell at the plan's default size, and only across a kink.
- `sdf` over the whole crystal panel (2,664 cells) costs ~10 ms for the
  heart, ~11 ms for the star and ~8 ms for the diamond in float64, and
  about 60% of that in float32 (pass float32 arrays and the pass stays
  float32). That is per CALL, not per frame: an effect that needs the
  field every frame should hold it and rebuild it only when the shape,
  size or offset actually moves.

THE THREE VIEWS, each built once per shape at import and cached on the
entry (numpy throughout — no per-frame Python loops):

- `polar(theta)` — the radius of the outline along the ray at `theta`, from
  a POLAR_BINS-bin table built by bisection on the signed distance and
  linearly interpolated, plus `polar_mean`. Black Hole's shaped horizon and
  STAR's shaped radius read this. It is only defined for a shape that is
  STAR-SHAPED about its own centre (every ray from (0, 0) crosses the
  outline exactly once); `build()` measures that and records it as
  `star_shaped`, and `polar()` raises ValueError for a shape that is not.
  All three shipped shapes are star-shaped — the heart's cleft is a notch,
  not a fold, which is measured here rather than assumed.
- `at(s)` — the point a fraction `s` of the way round the outline BY ARC
  LENGTH (`s` wraps, so `at(1.0) == at(0.0)`), from a cumulative-length
  table, plus `tangent(s)` (a unit heading). Orbits' tethers, Fish's
  procession and Fireworks' spark targets read these.
- `sdf(x, y)` — the signed distance to the outline, negative inside,
  vectorised over arrays of any shape (an even-odd inside test plus the
  minimum distance to the polyline's segments). Sauron's shaped iris and
  pupil, and Fireworks' fill test, read this.

`ray_radius()` is the independent reference the star-shaped check and the
tests use: a direct ray/segment cast over the polyline, which is NOT how
the polar table is built (bisection on the sdf), so the two agreeing is
real evidence rather than one implementation checking itself.

WHO READS THE WORDS. `words` are the shape's STARTING sung words, exactly
as `spectra/services/sung_labels.py`'s `EFFECT_SEEDS` holds an effect's —
seeds, never the live set: his own edits are stored as deltas on top, so a
re-seed never undoes them (W0.2 wires this up; nothing reads `words` yet).

ADDING A SHAPE (the whole job):
  1. one `build(...)` call in `_SHAPES` below, with the outline in whatever
     units suit it and its starting words;
  2. run `.venv/bin/python scripts/check_word_shapes.py` — the outline must
     be at least `min_stroke_px` lit cells thick everywhere on the real hex
     mask, and the script says whether it is star-shaped;
  3. if it is not star-shaped that is fine, but no effect may call
     `polar()` on it — it has the outline and distance views only;
  4. update `.claude/skills/word-shapes/SKILL.md` in the same change.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from numpy.typing import ArrayLike, NDArray

# The radius-per-angle table's resolution: the plan's own figure. 720 bins
# is half a degree, so every WHOLE degree is a table entry read exactly.
# Between two bins the radius is interpolated linearly, which is exact
# wherever the outline is straight and errs only across a kink (the heart's
# cleft, a star's points): measured worst case 1.0% of the radius at a
# half-bin offset, 0.1 of a cell at the plan's default size — see ACCURACY
# in the module docstring.
POLAR_BINS = 720

# Bisection depth for one table entry. The bracket is at most ~1.2 unit
# lengths wide, so 60 halvings is machine precision, and the whole table is
# one vectorised pass per halving.
_BISECT_ITERS = 60

# How finely the star-shaped verdict is measured (one ray cast per angle).
_STAR_CHECK_RAYS = 1440

# Two hits this close together along the same ray are the same crossing
# (a ray through a vertex), not two.
_SAME_HIT_EPS = 1e-6

# Points this close together are the same point (a repeated closing point).
_SAME_POINT_EPS = 1e-9

# How many points `sdf` handles at once. Small on purpose: the whole
# (points x segments) working set then stays in cache, which measured 5x
# faster than one big pass over the crystal's 2,664 cells.
_SDF_CHUNK = 128


def _as_points(points: ArrayLike) -> NDArray[np.float64]:
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError("points must be an (N, 2) array of x, y")
    if len(pts) >= 2 and np.linalg.norm(pts[-1] - pts[0]) <= _SAME_POINT_EPS:
        pts = pts[:-1]          # closed implicitly; no duplicate end point
    if len(pts) < 3:
        raise ValueError("points must hold at least 3 distinct points")
    return pts


def _normalise_box(pts: NDArray[np.float64]) -> NDArray[np.float64]:
    """Centre on (0, 0) and scale so the height is exactly 2.0."""
    lo = pts.min(axis=0)
    hi = pts.max(axis=0)
    height = float(hi[1] - lo[1])
    if height <= 0.0:
        raise ValueError("points have no height")
    return (pts - (lo + hi) / 2.0) * (2.0 / height)


def _signed_area(pts: NDArray[np.float64]) -> float:
    x, y = pts[:, 0], pts[:, 1]
    return float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y) / 2.0)


def _orient(pts: NDArray[np.float64]) -> NDArray[np.float64]:
    """Counter-clockwise in the coordinate algebra (positive shoelace area),
    keeping the declared first point first."""
    if _signed_area(pts) >= 0.0:
        return pts
    return np.concatenate([pts[:1], pts[1:][::-1]])


def _cum_lengths(pts: NDArray[np.float64]) -> NDArray[np.float64]:
    """Cumulative arc length at each point, with the closing point last, so
    `cum[-1]` is the perimeter."""
    closed = np.concatenate([pts, pts[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(seg)])


def _segments(pts: NDArray[np.float64]) -> tuple:
    """The per-segment constants `sdf` needs, worked out once: each
    segment's start, its step, 1/|step|^2, the dx/dy slope the even-odd
    test crosses with, and the end's y."""
    ax, ay = pts[:, 0].copy(), pts[:, 1].copy()
    bx, by = np.roll(ax, -1), np.roll(ay, -1)
    dx, dy = bx - ax, by - ay
    d2 = dx * dx + dy * dy
    inv_d2 = 1.0 / np.where(d2 > 0.0, d2, 1.0)
    slope = dx / np.where(by != ay, by - ay, 1.0)
    return (ax, ay, dx, dy, inv_d2, slope, by)


def _cross(ax, ay, bx, by):
    return ax * by - ay * bx


def ray_radius(points: ArrayLike, theta: ArrayLike,
               ) -> tuple[NDArray[np.float64], NDArray[np.int_]]:
    """Cast a ray from (0, 0) at each `theta` against the closed polyline
    `points`; return (nearest hit distance, hit count) per angle.

    The reference implementation for the radius per angle, independent of
    `Shape.polar`'s bisection table — the tests and the star-shaped verdict
    both lean on that independence. A hit exactly on a vertex is counted
    once: a segment owns its start point and not its end (half-open), so
    two neighbours sharing a vertex do not both report it.
    """
    pts = _as_points(points)
    th = np.atleast_1d(np.asarray(theta, dtype=np.float64))
    ax, ay = pts[:, 0], pts[:, 1]
    bx, by = np.roll(ax, -1), np.roll(ay, -1)
    dx, dy = bx - ax, by - ay

    ux = np.cos(th)[:, None]
    uy = np.sin(th)[:, None]
    denom = _cross(ux, uy, dx[None, :], dy[None, :])
    safe = np.where(np.abs(denom) > 1e-300, denom, 1.0)
    r = _cross(ax[None, :], ay[None, :], dx[None, :], dy[None, :]) / safe

    # s along the segment, from the hit point itself
    px = r * ux
    py = r * uy
    d2 = np.where(dx * dx + dy * dy > 0.0, dx * dx + dy * dy, 1.0)[None, :]
    s = ((px - ax[None, :]) * dx[None, :]
         + (py - ay[None, :]) * dy[None, :]) / d2

    ok = (np.abs(denom) > 1e-12) & (r > _SAME_POINT_EPS)
    ok &= (s >= -1e-12) & (s < 1.0 - 1e-12)

    hits = np.where(ok, r, np.nan)
    with np.errstate(invalid="ignore"):
        count = np.sum(ok, axis=1)
        nearest = np.where(count > 0, np.nanmin(np.where(ok, hits, np.inf),
                                                axis=1), np.nan)
        # a ray through a vertex, or grazing one, is one crossing
        spread = np.where(count > 0,
                          np.nanmax(np.where(ok, hits, -np.inf), axis=1)
                          - np.where(count > 0, nearest, 0.0), 0.0)
    count = np.where((count > 1) & (spread <= _SAME_HIT_EPS), 1, count)
    return nearest.astype(np.float64), count.astype(np.int_)


@dataclass(frozen=True, eq=False)
class Shape:
    """One shape: an id, a name, a closed outline in the unit box, its
    starting sung words, and whether it must stand upright (a heart or a
    star read as upside down if an effect spins it; the diamond does not).

    Build one with `build()`, never by hand: the derived views below are
    computed there, once, and cached on the entry.
    """

    id: str
    name: str
    points: NDArray[np.float64]
    words: tuple[str, ...]
    upright: bool = True

    # ── derived, filled in by build() ──────────────────────────────────
    star_shaped: bool = field(default=False, repr=False)
    perimeter: float = field(default=0.0, repr=False)
    polar_mean: float = field(default=float("nan"), repr=False)
    _cum: NDArray[np.float64] = field(default=None, repr=False)  # type: ignore[assignment]
    _seg: tuple = field(default=(), repr=False)
    _closed: NDArray[np.float64] = field(default=None, repr=False)  # type: ignore[assignment]
    _polar_table: Optional[NDArray[np.float64]] = field(default=None, repr=False)

    # ── the radius per angle ───────────────────────────────────────────
    def polar(self, theta: ArrayLike) -> NDArray[np.float64]:
        """The radius of the outline along the ray at `theta` (radians,
        0 = +x, y DOWN as the effects use), linearly interpolated from the
        POLAR_BINS table. Raises ValueError for a shape that is not
        star-shaped about its centre, where no such radius exists."""
        if self._polar_table is None:
            raise ValueError(
                f"shape {self.id!r} is not star-shaped about its centre: it "
                f"has no radius per angle. Use at(s) or sdf(x, y) instead."
            )
        table = self._polar_table
        f = np.asarray(theta, dtype=np.float64) / (2.0 * math.pi) * POLAR_BINS
        i0 = np.floor(f)
        frac = f - i0
        lo = (i0.astype(np.int64)) % POLAR_BINS
        hi = (lo + 1) % POLAR_BINS
        return table[lo] * (1.0 - frac) + table[hi] * frac

    # ── the walk along the outline ─────────────────────────────────────
    def at(self, s: ArrayLike) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """The point a fraction `s` of the way round the outline BY ARC
        LENGTH, measured from `points[0]` in the outline's own direction.
        `s` wraps, so `at(1.0) == at(0.0)` and `at(-0.25) == at(0.75)`."""
        d = (np.asarray(s, dtype=np.float64) % 1.0) * self.perimeter
        x = np.interp(d, self._cum, self._closed[:, 0])
        y = np.interp(d, self._cum, self._closed[:, 1])
        return x, y

    def tangent(self, s: ArrayLike) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """The unit heading along the outline at `s` — the direction
        `at(s)` is travelling, for anything that needs to point the way it
        is going (a fish's nose, a spark's drift)."""
        d = (np.asarray(s, dtype=np.float64) % 1.0) * self.perimeter
        i = np.clip(np.searchsorted(self._cum, d, side="right") - 1,
                    0, len(self.points) - 1)
        step = self._closed[i + 1] - self._closed[i]
        norm = np.linalg.norm(step, axis=-1)
        norm = np.where(norm > 0.0, norm, 1.0)
        return step[..., 0] / norm, step[..., 1] / norm

    # ── the signed distance field ──────────────────────────────────────
    def sdf(self, x: ArrayLike, y: ArrayLike) -> NDArray[np.floating]:
        """The signed distance from (x, y) to the outline in unit
        coordinates — negative inside, positive outside, zero on it.

        Vectorised over arrays of any shape (they broadcast together); the
        result has the broadcast shape. The dtype follows the inputs, at
        least float32: pass float32 and the whole pass runs in float32,
        which is the lever an effect has if it needs the speed (COST, in
        the module docstring).
        """
        dtype = np.result_type(np.asarray(x).dtype, np.asarray(y).dtype,
                               np.float32)
        if dtype.kind != "f":
            dtype = np.dtype(np.float64)
        xa, ya = np.broadcast_arrays(np.asarray(x, dtype=dtype),
                                     np.asarray(y, dtype=dtype))
        px = np.ascontiguousarray(xa).reshape(-1)
        py = np.ascontiguousarray(ya).reshape(-1)
        out = np.empty(px.shape, dtype=dtype)
        ax, ay, dx, dy, inv_d2, slope, by = (
            a.astype(dtype, copy=False) for a in self._seg)
        for start in range(0, len(px), _SDF_CHUNK):
            cx = px[start:start + _SDF_CHUNK, None]
            cy = py[start:start + _SDF_CHUNK, None]
            rx = cx - ax
            ry = cy - ay
            t = np.clip((rx * dx + ry * dy) * inv_d2, 0.0, 1.0)
            qx = rx - t * dx
            qy = ry - t * dy
            dist = np.sqrt(np.min(qx * qx + qy * qy, axis=1))
            # even-odd: a segment straddling this row, crossed to the right
            crossing = (ay > cy) != (by > cy)
            inside = np.sum(crossing & (rx < ry * slope), axis=1) % 2 == 1
            out[start:start + _SDF_CHUNK] = np.where(inside, -dist, dist)
        return out.reshape(xa.shape)


def build(id: str, name: str, points: ArrayLike, words: tuple[str, ...],
          upright: bool = True) -> Shape:
    """One shape entry, normalised into the unit box and oriented, with all
    three views derived and cached (module docstring). This is the only way
    a Shape is made — `SHAPES` uses it, and so does any test or script that
    wants a shape the registry does not ship."""
    pts = _orient(_normalise_box(_as_points(points)))
    cum = _cum_lengths(pts)
    closed = np.concatenate([pts, pts[:1]])
    perimeter = float(cum[-1])

    shape = Shape(id=id, name=name, points=pts, words=tuple(words),
                  upright=bool(upright), star_shaped=False,
                  perimeter=perimeter, polar_mean=float("nan"),
                  _cum=cum, _seg=_segments(pts), _closed=closed,
                  _polar_table=None)

    # Star-shaped? Every ray from the centre crosses the outline exactly
    # once (measured, never assumed — the heart's cleft is the case this
    # exists for).
    rays = np.arange(_STAR_CHECK_RAYS) * (2.0 * math.pi / _STAR_CHECK_RAYS)
    _, counts = ray_radius(pts, rays)
    star_shaped = bool(np.all(counts == 1))
    object.__setattr__(shape, "star_shaped", star_shaped)

    if star_shaped:
        table = _polar_table(shape)
        object.__setattr__(shape, "_polar_table", table)
        object.__setattr__(shape, "polar_mean", float(table.mean()))
    return shape


def _polar_table(shape: Shape) -> NDArray[np.float64]:
    """The radius per angle, by bisection on the signed distance: for every
    bin, the r where `sdf` changes sign along that bin's ray."""
    thetas = np.arange(POLAR_BINS) * (2.0 * math.pi / POLAR_BINS)
    ux, uy = np.cos(thetas), np.sin(thetas)
    if shape.sdf(0.0, 0.0) >= 0.0:
        raise ValueError(f"shape {shape.id!r}: its own centre is not inside it")
    lo = np.zeros(POLAR_BINS)
    hi = np.full(POLAR_BINS,
                 float(np.linalg.norm(shape.points, axis=1).max()) * 1.05)
    for _ in range(_BISECT_ITERS):
        mid = (lo + hi) / 2.0
        inside = shape.sdf(mid * ux, mid * uy) < 0.0
        lo = np.where(inside, mid, lo)
        hi = np.where(inside, hi, mid)
    return (lo + hi) / 2.0


# ── the shapes ─────────────────────────────────────────────────────────────

def _heart_points(n: int = 360) -> NDArray[np.float64]:
    """The parametric heart `x = 16 sin^3 t`, `y = 13 cos t - 5 cos 2t -
    2 cos 3t - cos 4t`, with y negated for the panel's y-DOWN box (the
    formula's +y is up), normalised by `build()`."""
    t = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    x = 16.0 * np.sin(t) ** 3
    y = -(13.0 * np.cos(t) - 5.0 * np.cos(2 * t)
          - 2.0 * np.cos(3 * t) - np.cos(4 * t))
    return np.column_stack([x, y])


def _polygon_points(verts: ArrayLike, per_edge: int) -> NDArray[np.float64]:
    """A polygon as a dense polyline: every vertex exactly, each edge cut
    into `per_edge` equal steps (so a corner is never rounded off)."""
    v = np.asarray(verts, dtype=np.float64)
    out = []
    for i in range(len(v)):
        a, b = v[i], v[(i + 1) % len(v)]
        f = np.linspace(0.0, 1.0, per_edge, endpoint=False)[:, None]
        out.append(a + f * (b - a))
    return np.concatenate(out)


def _star_verts(points: int = 5, outer: float = 1.0, inner: float = 0.45,
                ) -> NDArray[np.float64]:
    """A `points`-pointed star with one point straight UP (-y on the panel),
    alternating outer and inner radii, in increasing-theta order."""
    step = 2.0 * math.pi / points
    out = []
    for k in range(points):
        a = -math.pi / 2.0 + k * step
        out.append((outer * math.cos(a), outer * math.sin(a)))
        b = a + step / 2.0
        out.append((inner * math.cos(b), inner * math.sin(b)))
    return np.asarray(out, dtype=np.float64)


_SHAPES: tuple[Shape, ...] = (
    build(
        "heart", "Heart", _heart_points(),
        ("love", "heart", "corazón", "amor", "kiss", "beso"),
    ),
    build(
        "star", "Star", _polygon_points(_star_verts(), per_edge=40),
        ("star", "stars", "estrella", "shine", "twinkle", "night sky"),
    ),
    build(
        "diamond", "Diamond",
        _polygon_points([(0.0, -1.0), (0.78, 0.0), (0.0, 1.0), (-0.78, 0.0)],
                        per_edge=60),
        ("diamond", "diamante", "jewel", "ring", "sparkle", "crystal"),
    ),
)

SHAPES: dict[str, Shape] = {s.id: s for s in _SHAPES}


def shape_ids() -> tuple[str, ...]:
    """Every shape id, in declaration order."""
    return tuple(SHAPES)


def get(id: str) -> Shape:
    """One shape by id. Raises KeyError for an id the library does not know
    (a told key naming an unknown shape is "not told" — see
    `fx/effects/word_shape_keys.py`, which never calls this blind)."""
    return SHAPES[id]


def has(id: str) -> bool:
    """Whether this library knows `id`."""
    return id in SHAPES


__all__ = [
    "POLAR_BINS", "Shape", "SHAPES", "build", "get", "has", "ray_radius",
    "shape_ids",
]
