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
in every effect here, so -y is the frame's top and `theta = atan2(y, x)`
is the same angle an effect already computes. The outline runs
counter-clockwise in the coordinate algebra (a positive shoelace area,
the direction of increasing `theta`); drawn on the panel with y downward
that reads as clockwise. `build()` enforces the box and the orientation, so
a new entry can be written in whatever units and winding are natural for it.

THE DEFAULT ORIENTATION IS A HALF TURN (`PANEL_ROTATION_DEG`, 2026-11-18).
`build()` rotates every shape 180 degrees about the centre, AFTER the box
and the winding, as the library's default for every shape — his verdict in
the room: *"the shapes should be 'flipped' because they are visually
upside-down on this device. Rotate 180 degrees, and make that the 'default'
orientation."* So in the FRAME a star's and a diamond's own point now sits
at the MAXIMUM y (the frame's bottom row) and a heart's single point at the
MINIMUM y with its cleft at the bottom — and on his panel, which shows this
frame inverted, that reads the right way up. An ASCII render of the frame
(`scripts/check_word_shapes.py --ascii`) therefore looks upside-down on
purpose; the script says so at the top of every render. Every derived view
(`polar`, `at`, `tangent`, `sdf`, `sdf_fast`, every table) follows for free
because each is built from `points`, and NO effect module knows about the
flip at all.

AND THE TURN KEEPS THE ARC-LENGTH ORIGIN WHERE IT WAS. `at(s)` is a
PHASE, not just a point: Orbits' bead hops, a walk's start and every
arc-length number a test reads are measured from `at(0)`. The squadron
leader's ruling on row W5.7 — "the flip is a rotation of the PICTURE and
nothing else" — is what the ROLL in `_rotate_for_panel` is for, and it
applies exactly where it can:

- A SHAPE THAT IS ITS OWN HALF TURN is rolled, and comes back
  BYTE-IDENTICAL. The diamond is one: the turned outline passes through
  the origin's old place, so the roll lands on it exactly. That identity
  is the strongest proof this is a pure rotation, and it is why all 24 of
  Orbits' contrast rows read exactly W4.4's numbers. Without the roll the
  diamond's own row fell from 60% of the outline band to 54% against a
  55% bar — the measurement that put the roll here.
- A SHAPE THAT IS NOT keeps `at(0)` on its own MATERIAL point (the
  declared vertex, carried round by the turn). For the heart and the star
  no turned point sits on the old place at all — the nearest is 0.249 and
  0.339 unit lengths off — so rolling to it would preserve neither the
  physical nor the material phase. Measured, rolling them moved Orbits'
  `many4 heart @ Energy 0.8` band/rest ratio from 1.53 to 1.26 against a
  1.4 bar; leaving them keeps every row green.

Either way the library's convention is untouched: `at(0) == points[0]`,
winding counter-clockwise.

WHAT DOES MOVE, and why no effect had to change: for the heart and the
star the flip lands the outline on a DIFFERENT set of real cells (same
168 and 176 of them — the lattice is centrally symmetric — but only 30
and 60 shared with the old set), so any measurement of the band itself is
of a new band. Nothing anchors to a shape BY INDEX: Orbits FEW anchors to
each blob's own phase, Fish enters on each fish's bearing, Fireworks
samples `at(s)` at random, and STAR, Black Hole and Sauron read `polar`
by angle.

THE CONVENTION AN EFFECT USES — NORMALIZED SPACE, NOT CELLS. A view is in
unit coordinates; an effect scales it by SIZE, **the shape's half-height in
the effect's own NORMALIZED coordinates, where 1.0 is the panel's own
half-height**:

    r      = SIZE * shape.polar(theta)        # radius per angle
    x, y   = SIZE * shape.at(s)               # a point along the outline
    d      = shape.sdf(x / SIZE, y / SIZE) * SIZE   # distance, normalized

Those are the coordinates every Twod effect already works in: it turns a
cell into `(col - cx) / ((cols - 1) / 2)`, `(row - cy) / ((rows - 1) / 2)`
— the familiar `sx`/`sy` pair — so x and y each run -1..1 across the panel
whatever its shape. SIZE is therefore a FRACTION (the plan's default 0.62,
`word_shape_size`, a per-effect registered param added in wave 1), never a
number of cells: on his crystal `SIZE = 0.62` means 0.62 x 35.5 = 22.0
columns of half-width and 0.62 x 18 = 11.2 rows of half-height for the
same unit length.

**The effect's own sx/sy carry the panel's anisotropy, and so does the
shape.** A crystal column is half a real-cell pitch and a row is sqrt(3)/2
of one (the hex lattice: `.claude/skills/crystal-hex-grid/SKILL.md`), so a
shape drawn with one SIZE in normalized space comes out about 14% wider
than tall in the room — the panel's own aspect, the same way every other
effect's circle is. Measuring it in raw grid cells instead, with one size
for both axes, draws it squashed to barely half its width: that was a real
bug in this module's check script (caught in review of PR 519), and
`scripts/check_word_shapes.py` now measures in normalized space with
distances in PHYSICAL pitch units.

Nothing in this module knows about a panel, a device or a told key: it is
pure geometry, and that check script is what measures a shape against the
real hex mask.

ACCURACY AND COST, measured (all pinned by tests/test_word_shapes.py, so a
change that makes any of them worse is a visible one):

- `polar` is exact at every whole degree (every one is its own bin, and
  the table is the analytic ray cast) and within 1.0% of that cast at the
  worst half-bin offset — a tenth of a cell at the plan's default size,
  and only across a kink.
- `sdf` is EXACT and costs ~10 ms (heart), ~11 ms (star), ~8 ms (diamond)
  over the whole crystal panel (2,664 cells) in float64, about 60% of that
  in float32 (the dtype follows the inputs). Right for a check, a
  measurement or a one-off target; far too slow for a frame.
- `sdf_fast` is the per-frame field: ~0.13 ms for the same 2,664 cells at
  any size, within FAST_TOLERANCE (0.01 units; measured worst 0.009, the
  star's) of `sdf` inside its grid, and within FAR_FIELD_TOLERANCE
  relatively outside it (a lower bound, never negative, never for a
  sub-cell decision). Its grid costs ~200 ms to build, once, on first use
  — `prime()` moves that off the render path. FAST_SPACING is 0.02 rather
  than 0.01 on purpose: 0.01 is four times the build for an error already
  well inside the bar.

LAZY ON PURPOSE. `build()` does only the cheap work (normalise, orient,
arc lengths, segment constants); the star-shaped verdict, the polar table
and the `sdf_fast` grid are each built on first use and kept on the entry.
Importing this module is ~3 ms however many shapes it ships — it used to
be 0.5 s, which every LedFX start and every SPECTRA import of the word
seeds would have paid for shapes it never draws (PR 519 review).

THE THREE VIEWS (numpy throughout — no per-frame Python loops):

- `polar(theta)` — the radius of the outline along the ray at `theta`, from
  a POLAR_BINS-bin table (the analytic `ray_radius` at each bin) read with
  linear interpolation, plus `polar_mean`. Black Hole's shaped horizon and
  STAR's shaped radius read this. It is only defined for a shape that is
  STAR-SHAPED about its own centre (every ray from (0, 0) crosses the
  outline exactly once); `star_shaped` measures that on first read, and
  `polar()` raises ValueError for a shape that is not. All three shipped
  shapes are star-shaped — the heart's cleft is a notch, not a fold, which
  is measured rather than assumed.
- `at(s)` — the point a fraction `s` of the way round the outline BY ARC
  LENGTH (`s` wraps, so `at(1.0) == at(0.0)`), from a cumulative-length
  table, plus `tangent(s)` (a unit heading). Orbits' tethers, Fish's
  procession and Fireworks' spark targets read these.
- `sdf(x, y)` / `sdf_fast(x, y)` — the signed distance to the outline,
  negative inside, vectorised over arrays of any shape (an even-odd inside
  test plus the minimum distance to the polyline's segments; the fast one
  is bilinear from a lookup grid of that same field). Sauron's shaped iris
  and pupil, and Fireworks' fill test, read these.

TWO IMPLEMENTATIONS, ON PURPOSE. `ray_radius()` — a direct ray/segment
cast over the polyline — is what the polar table is built from, and
`polar_table_by_bisection()` is the same quantity found the slow way, by
bisecting the signed distance along each ray. They share no code, so the
tests holding them to 1e-12 of each other is real evidence rather than one
implementation checking itself; `scripts/check_word_shapes.py` re-measures
the star-shaped verdict a third way (an sdf step-walk).

WHO READS THE WORDS. `words` are the shape's STARTING sung words, exactly
as `spectra/services/sung_labels.py`'s `EFFECT_SEEDS` holds an effect's —
seeds, never the live set: his own edits are stored as deltas on top, so a
re-seed never undoes them (W0.2 wires this up; nothing reads `words` yet).

ADDING A SHAPE (the whole job):
  1. one `build(...)` call in `_SHAPES` below, with the outline in whatever
     units suit it and its starting words;
  2. run `.venv/bin/python scripts/check_word_shapes.py` — the outline must
     have at least `min_stroke_px` real cells within one pitch everywhere
     on the real hex mask (`--ascii` draws it), and the script says
     whether it is star-shaped;
  3. if it is not star-shaped that is fine, but no effect may call
     `polar()` on it — it has the outline and distance views only;
  4. re-pin the new shape's numbers in tests/test_word_shapes.py, and
     update `.claude/skills/word-shapes/SKILL.md`, in the same change.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
import numpy as np
from numpy.typing import ArrayLike, NDArray

# EVERY SHAPE IS ROTATED BY THIS, AS THE DEFAULT, in `build()`. His verdict
# in the room, 2026-11-18: "the shapes should be 'flipped' because they are
# visually upside-down on this device. Rotate 180 degrees, and make that the
# 'default' orientation." The crystal is the ONLY fixture that draws a shape
# (the strips and singles have no shape code), so "this device" is the one
# surface and the flip belongs here, as the library's own default, not as a
# per-shape or per-device option nobody else needs. 180 degrees about the
# centre is exactly `x -> -x, y -> -y`, which preserves the shoelace sign,
# so the winding `_orient` enforces survives it untouched; the hex lattice
# is centrally symmetric (row r <-> row 36-r keeps the half-column offset
# parity), so the outline's real-cell counts are unchanged too — both
# asserted, in `build()` and in the tests.
PANEL_ROTATION_DEG = 180

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

# The lookup grid behind `sdf_fast`: spacing in unit coordinates, and how
# far out it reaches in both axes. The extent covers the whole crystal
# panel for any shape size down to 0.5 of the panel's half-height (a panel
# corner is 1/SIZE out in shape coordinates); past it, `sdf_fast` falls
# back to the exact field. The spacing is measured, not guessed — see
# ACCURACY AND COST in the module docstring.
FAST_SPACING = 0.02
FAST_EXTENT = 2.0
# What `sdf_fast` is worth: the measured worst error of the bilinear
# lookup against the exact field, rounded up. Pinned by the tests.
FAST_TOLERANCE = 0.01
# And what its FAR FIELD is worth, past the grid's own box: the measured
# worst RELATIVE error of `hypot(x, y) - circumradius` against the exact
# distance, rounded up (worst 34%, the heart's, right at the boundary;
# mean 7%, falling off with distance). Also pinned by the tests.
FAR_FIELD_TOLERANCE = 0.35

# The roll only happens when the turned outline actually PASSES THROUGH
# the arc-length origin's old place (a shape that is its own half turn).
# Farther than this and there is no same-physical-point to return to.
_ORIGIN_LANDS_EPS = 1e-9

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


def _rotate_for_panel(pts: NDArray[np.float64]) -> NDArray[np.float64]:
    """Rotate every point by `PANEL_ROTATION_DEG` about the centre, and
    ROLL the list so `at(0)` sits on the same PHYSICAL point it sat on
    before the turn WHEN SUCH A POINT EXISTS — the library's DEFAULT
    orientation (his verdict; see the constant).

    THE ROLL SERVES "A ROTATION OF THE PICTURE AND NOTHING ELSE" (the
    squadron leader's ruling on row W5.7). The turn alone would leave the
    ARC-LENGTH ORIGIN half a perimeter from where it was, and `at(s)` is a
    PHASE: Orbits' bead hops, a walk's start and every arc-length number a
    test reads are measured from it. Measured, that cost Orbits' `many4
    diamond @ Energy 0.8` contrast row 6 points of outline band (60% to
    54% against a 55% bar) for a change meant to be invisible.

    THE ROLL ONLY HAPPENS FOR A SHAPE THAT IS ITS OWN HALF TURN, because
    only then is there a same-physical-point to return to. A diamond is:
    the turned outline passes exactly through the origin's old place
    (distance 0), the roll lands on it, and the points array comes back
    BYTE-IDENTICAL. A heart and a star are not — the nearest turned point
    to the old place is 0.249 and 0.339 unit lengths away, so a roll there
    would land on NEITHER the old physical point nor the shape's own
    material one, moving the phase for nothing. Measured: rolling them to
    the nearest point moved Orbits' `many4 heart @ Energy 0.8` band/rest
    ratio from 1.53 to 1.26 against a 1.4 bar, while leaving them alone
    keeps all 24 rows green. So for those `at(0)` stays on the same
    MATERIAL point of the shape (the declared vertex, carried round by the
    turn), which is the only phase a moved outline still has.

    Both steps preserve the winding (a rotation is a rigid motion with
    positive determinant; a roll is a relabelling of the same cycle), so
    `_orient` is a no-op after this — the caller re-runs it and asserts so.
    """
    if PANEL_ROTATION_DEG % 360 != 180:
        raise NotImplementedError(
            f"PANEL_ROTATION_DEG={PANEL_ROTATION_DEG} is not a half turn. "
            "Only 180 is implemented, because a half turn is exactly "
            "`x -> -x, y -> -y` and needs no rotation matrix (so no "
            "sin(pi) epsilon in the unit box), AND because the hex lattice "
            "is centrally symmetric and symmetric under nothing else: any "
            "other angle also means re-measuring every pinned cell count "
            "in tests/test_word_shapes.py.")
    turned = -pts      # x -> -x, y -> -y, exact: no epsilon skew
    d = np.linalg.norm(turned - pts[0], axis=1)
    lead = int(d.argmin())
    if d[lead] > _ORIGIN_LANDS_EPS:
        return turned
    return np.roll(turned, -lead, axis=0)


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
    perimeter: float = field(default=0.0, repr=False)
    # The outline's farthest point from (0, 0) — the one number `sdf_fast`
    # needs for its far field, and the bracket a ray cast or a bisection
    # starts from.
    circumradius: float = field(default=0.0, repr=False)
    _cum: NDArray[np.float64] = field(default=None, repr=False)  # type: ignore[assignment]
    _seg: tuple = field(default=(), repr=False)
    _closed: NDArray[np.float64] = field(default=None, repr=False)  # type: ignore[assignment]
    # Everything expensive lives here, built on first use and kept (LAZY, in
    # the module docstring): "star_shaped", "polar_table", "fast". A frozen
    # entry with one mutable cache is what lets import stay cheap. Two
    # threads racing to build the same key both compute the same value and
    # the dict write is atomic, so the race is harmless.
    _lazy: dict = field(default_factory=dict, repr=False)

    # ── the star-shaped verdict (lazy) ─────────────────────────────────
    @property
    def star_shaped(self) -> bool:
        """Whether every ray from (0, 0) crosses the outline exactly once,
        so the shape HAS a radius per angle. Measured on first read, from
        _STAR_CHECK_RAYS rays, and kept."""
        verdict = self._lazy.get("star_shaped")
        if verdict is None:
            rays = np.arange(_STAR_CHECK_RAYS) * (2.0 * math.pi
                                                  / _STAR_CHECK_RAYS)
            _, counts = ray_radius(self.points, rays)
            verdict = bool(np.all(counts == 1))
            self._lazy["star_shaped"] = verdict
        return verdict

    @property
    def polar_mean(self) -> float:
        """The mean radius over the whole table — NaN for a shape that is
        not star-shaped, which has no radius per angle at all."""
        if not self.star_shaped:
            return float("nan")
        return float(self._polar_table().mean())

    def prime(self) -> "Shape":
        """Build everything lazy now and return self — for a caller that
        wants the cost on ITS thread (a config write, a test, a check
        script) rather than on the first frame that needs it."""
        if self.star_shaped:
            self._polar_table()
        self._fast_grid()
        return self

    # ── the radius per angle ───────────────────────────────────────────
    def polar(self, theta: ArrayLike) -> NDArray[np.float64]:
        """The radius of the outline along the ray at `theta` (radians,
        0 = +x, y DOWN as the effects use), linearly interpolated from the
        POLAR_BINS table. Raises ValueError for a shape that is not
        star-shaped about its centre, where no such radius exists."""
        table = self._polar_table()
        f = np.asarray(theta, dtype=np.float64) / (2.0 * math.pi) * POLAR_BINS
        i0 = np.floor(f)
        frac = f - i0
        lo = (i0.astype(np.int64)) % POLAR_BINS
        hi = (lo + 1) % POLAR_BINS
        return table[lo] * (1.0 - frac) + table[hi] * frac

    def _polar_table(self) -> NDArray[np.float64]:
        """The POLAR_BINS-bin radius table, built on first use from
        `ray_radius` — the analytic ray/segment cast, which is exact at a
        bin and costs a few milliseconds once.
        `polar_table_by_bisection()` is the independent second
        implementation the tests check this one against."""
        table = self._lazy.get("polar_table")
        if table is None:
            if not self.star_shaped:
                raise ValueError(
                    f"shape {self.id!r} is not star-shaped about its "
                    f"centre: it has no radius per angle. Use at(s) or "
                    f"sdf(x, y) instead."
                )
            thetas = np.arange(POLAR_BINS) * (2.0 * math.pi / POLAR_BINS)
            table, _ = ray_radius(self.points, thetas)
            self._lazy["polar_table"] = table
        return table

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

    # ── the per-frame-safe signed distance ─────────────────────────────
    def _fast_grid(self) -> tuple:
        """The lookup grid `sdf_fast` reads, built on first use: the exact
        field sampled every FAST_SPACING over [-FAST_EXTENT, FAST_EXTENT]
        in both axes, in float32."""
        grid = self._lazy.get("fast")
        if grid is None:
            n = int(round(2.0 * FAST_EXTENT / FAST_SPACING)) + 1
            axis = np.linspace(-FAST_EXTENT, FAST_EXTENT, n)
            gx, gy = np.meshgrid(axis, axis)
            table = self.sdf(gx, gy).astype(np.float32)
            grid = (table, np.float32(axis[0]),
                    np.float32(axis[1] - axis[0]), n)
            self._lazy["fast"] = grid
        return grid

    def sdf_fast(self, x: ArrayLike, y: ArrayLike) -> NDArray[np.float32]:
        """`sdf` for a render frame: bilinear from the lookup grid, always
        float32, within FAST_TOLERANCE of the exact field (measured; the
        tests pin it).

        Use `sdf` for a check, a measurement or a one-off target, and this
        one for a field evaluated every frame (Sauron's shaped iris and
        pupil under a moving gaze). Its only real cost is the first call,
        which builds the grid — call `prime()` off the render path if that
        matters.

        OUTSIDE THE GRID'S OWN BOX it is a cheap FAR-FIELD ESTIMATE,
        `hypot(x, y) - circumradius` floored at 0: never negative, never
        larger than the true distance (it is a strict lower bound, by the
        triangle inequality), and within FAR_FIELD_TOLERANCE of it
        relatively — worst right at the boundary, where it also steps down
        from the bilinear value by that much. It is for "how far out am I",
        never for a sub-cell decision and never for inside/outside.

        That matters because the grid's box is a fixed +-FAST_EXTENT in
        SHAPE coordinates, so how much of a panel falls outside it depends
        entirely on the size the effect draws at: at SIZE 0.62 none of the
        crystal does, while at SIZE 0.27 (Sauron's pupil) about 70% does.
        The exact `sdf` as a fallback therefore put the per-frame cost
        straight back to ~8 ms for a small shape — the reason this estimate
        exists (PR 519 re-review).

        Within about FAST_TOLERANCE of the outline the interpolated sign
        can differ from the exact one; that is what the tolerance means,
        and nothing should decide "inside" from this at sub-cell distances.
        """
        table, origin, step, n = self._fast_grid()
        xa, ya = np.broadcast_arrays(np.asarray(x, dtype=np.float32),
                                     np.asarray(y, dtype=np.float32))
        fx = (xa - origin) / step
        fy = (ya - origin) / step
        i0 = np.clip(fx.astype(np.int32), 0, n - 2)
        j0 = np.clip(fy.astype(np.int32), 0, n - 2)
        tx = np.clip(fx - i0, 0.0, 1.0).astype(np.float32)
        ty = np.clip(fy - j0, 0.0, 1.0).astype(np.float32)
        out = (table[j0, i0] * (1.0 - tx) * (1.0 - ty)
               + table[j0, i0 + 1] * tx * (1.0 - ty)
               + table[j0 + 1, i0] * (1.0 - tx) * ty
               + table[j0 + 1, i0 + 1] * tx * ty)
        outside = (fx < 0.0) | (fx > n - 1) | (fy < 0.0) | (fy > n - 1)
        if outside.any():
            out = np.array(out, dtype=np.float32, copy=True)
            out[outside] = np.maximum(
                np.hypot(xa[outside], ya[outside]) - self.circumradius, 0.0)
        return out



def build(id: str, name: str, points: ArrayLike, words: tuple[str, ...],
          upright: bool = True) -> Shape:
    """One shape entry, normalised into the unit box and oriented. This is
    the only way a Shape is made — `SHAPES` uses it, and so does any test
    or script that wants a shape the registry does not ship. It does only
    the cheap work: every derived view is built on first use (LAZY, in the
    module docstring), so importing this module stays a few milliseconds
    however many shapes it ships."""
    pts = _orient(_normalise_box(_as_points(points)))
    # His default orientation, applied AFTER normalisation and orientation
    # so a new entry is still written in whatever units and winding suit
    # it. `_rotate_for_panel` turns the picture and then rolls the arc-
    # length origin back onto the physical point it held, so this is a
    # rotation of the PICTURE and nothing else.
    before = _signed_area(pts)
    rotated = _rotate_for_panel(pts)
    pts = _orient(rotated)
    if not np.array_equal(pts, rotated):   # neither a turn nor a roll can
        raise AssertionError(
            f"shape {id!r}: PANEL_ROTATION_DEG={PANEL_ROTATION_DEG} changed "
            "the winding, which a rotation about the centre followed by a "
            "roll of the same cycle cannot do")
    after = _signed_area(pts)
    if not math.isclose(after, before, rel_tol=1e-12, abs_tol=1e-12):
        raise AssertionError(
            f"shape {id!r}: PANEL_ROTATION_DEG={PANEL_ROTATION_DEG} changed "
            f"the shoelace area ({before!r} -> {after!r}); a rotation about "
            "the centre preserves it")
    cum = _cum_lengths(pts)
    closed = np.concatenate([pts, pts[:1]])
    perimeter = float(cum[-1])

    return Shape(id=id, name=name, points=pts, words=tuple(words),
                 upright=bool(upright), perimeter=perimeter,
                 circumradius=float(np.linalg.norm(pts, axis=1).max()),
                 _cum=cum, _seg=_segments(pts), _closed=closed)


def polar_table_by_bisection(shape: Shape) -> NDArray[np.float64]:
    """The radius per angle the SLOW, independent way: for every bin, the r
    where `sdf` changes sign along that bin's ray, found by bisection.

    Not what `Shape.polar` uses (that is the analytic `ray_radius`, which
    is exact and cheap) — this is the second implementation the tests check
    the live table against, and the reason a wrong outline cannot agree
    with itself.
    """
    thetas = np.arange(POLAR_BINS) * (2.0 * math.pi / POLAR_BINS)
    ux, uy = np.cos(thetas), np.sin(thetas)
    if shape.sdf(0.0, 0.0) >= 0.0:
        raise ValueError(f"shape {shape.id!r}: its own centre is not inside it")
    lo = np.zeros(POLAR_BINS)
    hi = np.full(POLAR_BINS, shape.circumradius * 1.05)
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
    formula's +y is up), normalised by `build()`.

    As DECLARED here the cleft is at the frame's top and the point at the
    bottom; `build()`'s `PANEL_ROTATION_DEG` half turn then puts the cleft
    at the frame's bottom, which is the way up his panel shows."""
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
    """A `points`-pointed star with one point at -y as DECLARED here,
    alternating outer and inner radii, in increasing-theta order.
    `build()`'s `PANEL_ROTATION_DEG` half turn then sends that point to +y
    in the frame, which is upright on his panel."""
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
    "FAR_FIELD_TOLERANCE", "FAST_EXTENT", "FAST_SPACING", "FAST_TOLERANCE",
    "PANEL_ROTATION_DEG", "POLAR_BINS", "Shape",
    "SHAPES", "build", "get", "has", "polar_table_by_bisection",
    "ray_radius", "shape_ids",
]
