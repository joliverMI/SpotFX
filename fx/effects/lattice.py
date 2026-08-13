"""Shared device-lattice API for shape-mapped matrices.

Effects that draw pixel-exact on a shaped device (squiggles, pacman) use a
LatticeView instead of hand-rolling the device geometry. The view is derived
from the virtual's compiled shape map (ledfx/shapemap.py via
Virtual._compile_shape) and expressed in the effect's RENDER coordinates —
the effect's composited rotation/flips are inverted with the exact same PIL
transpose chain Twod.image_to_pixels applies, so the view can never drift
from the output convention.

Without a shape map the view falls back to a full-rectangle mask with the
classic crystal checkerboard ring — the behavior lattice-native effects
already had on unmapped matrices.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

# The checkerboard ("hex") ring: live cells at one (col+row) parity, six
# directed moves sorted by angle (y down) — four diagonals + two verticals,
# no horizontal. The vertical pair (not horizontal) matches the crystal's
# strip geometry: rows are strips with 2-column pitch, so (0, ±2) is a real
# nearest neighbor while (±2, 0) skips over a live column's dead twin.
RING = ((-1, -1), (0, -2), (1, -1), (1, 1), (0, 2), (-1, 1))
RING_ANGLES = tuple(math.atan2(dr, dc) for dc, dr in RING)
AVG_MOVE_PX = 1.6  # mean render-px length of a ring move

_VIEW_CACHE: dict = {}


def _render_mask(mask: np.ndarray, rotate_t, flip2d: bool, mirror2d: bool):
    """Transform a virtual-grid mask into the effect's render space by
    inverting Twod.image_to_pixels' transpose chain (flip → mirror → rotate)
    with PIL itself, guaranteeing identical semantics."""
    img = Image.fromarray(mask.astype(np.uint8) * 255, "L")
    if rotate_t != 0:
        inverse = {
            Image.Transpose.ROTATE_90: Image.Transpose.ROTATE_270,
            Image.Transpose.ROTATE_180: Image.Transpose.ROTATE_180,
            Image.Transpose.ROTATE_270: Image.Transpose.ROTATE_90,
        }[rotate_t]
        img = img.transpose(inverse)
    if mirror2d:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if flip2d:
        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return np.asarray(img) > 0


class LatticeView:
    """Read-only device-lattice geometry in an effect's render coordinates."""

    def __init__(self, mask: np.ndarray, has_real_shape: bool):
        self.mask = mask
        self.height, self.width = mask.shape
        self.has_real_shape = has_real_shape
        rs, cs = np.nonzero(mask)
        par = (rs + cs) % 2 if len(rs) else np.array([1])
        self.is_checkerboard = bool(len(rs) == 0 or np.all(par == par[0]))
        # per-row extents; empty rows get (0, -1) so lo > hi
        self._lo = np.zeros(self.height, dtype=np.int32)
        self._hi = np.full(self.height, -1, dtype=np.int32)
        for r in range(self.height):
            cols = np.flatnonzero(mask[r])
            if cols.size:
                self._lo[r] = cols[0]
                self._hi[r] = cols[-1]
        self._nearest = None  # lazy (H,W,2) nearest-live LUT
        self._shells = None
        self._edge = None

    # ── geometry queries ──────────────────────────────────────────────

    def ring_moves(self):
        """The 6 directed nearest-neighbor moves (dc, dr), angle-sorted."""
        return RING

    def row_extents(self):
        """(lo, hi) int32 arrays per row; lo > hi on empty rows."""
        return self._lo, self._hi

    def inside(self, c: int, r: int) -> bool:
        """True when (c, r) is a live LED cell."""
        return (
            0 <= r < self.height
            and 0 <= c < self.width
            and bool(self.mask[r, c])
        )

    def in_extent(self, c, r) -> bool:
        """True when (c, r) lies within the row's silhouette extent (dead
        parity twins and holes included — matches the historical squiggles
        `_inside` semantics used for offscreen checks)."""
        return 0 <= r < self.height and self._lo[r] <= c <= self._hi[r]

    def snap_col(self, c, r, direction: int = +1) -> int:
        """Nearest live column at row r, stepping `direction` first (matches
        squiggles' historical parity snap on checkerboards)."""
        r = int(min(max(r, 0), self.height - 1))
        c = int(c)
        if self.inside(c, r):
            return c
        for step in range(1, self.width):
            for d in (direction, -direction):
                cc = c + d * step
                if self.inside(cc, r):
                    return cc
        return c

    def snap(self, x, y):
        """Nearest live cell to an arbitrary float render point → (c, r)."""
        if self._nearest is None:
            self._build_nearest()
        r = int(min(max(round(y), 0), self.height - 1))
        c = int(min(max(round(x), 0), self.width - 1))
        rr, cc = self._nearest[r, c]
        return int(cc), int(rr)

    def _build_nearest(self):
        rs, cs = np.nonzero(self.mask)
        pts = np.stack([rs, cs], axis=1).astype(np.float32)
        gy, gx = np.mgrid[0 : self.height, 0 : self.width]
        centers = np.stack([gy.ravel(), gx.ravel()], axis=1).astype(np.float32)
        try:
            from scipy.spatial import cKDTree

            _, owner = cKDTree(pts).query(centers, k=1)
        except ImportError:
            owner = np.empty(len(centers), dtype=np.int64)
            step = 4096
            for s in range(0, len(centers), step):
                d = np.linalg.norm(
                    centers[s : s + step, None, :] - pts[None, :, :], axis=2
                )
                owner[s : s + step] = d.argmin(axis=1)
        self._nearest = (
            pts[owner].astype(np.int32).reshape(self.height, self.width, 2)
        )

    def edge_pool(self):
        """Boundary live cells [(c, r), ...]: live cells missing at least one
        ring neighbor. Excludes dead holes by construction — no phantom
        spawn slots."""
        if self._edge is None:
            pool = []
            rs, cs = np.nonzero(self.mask)
            for r, c in zip(rs.tolist(), cs.tolist()):
                for dc, dr in RING:
                    if not self.inside(c + dc, r + dr):
                        pool.append((c, r))
                        break
            self._edge = sorted(set(pool))
        return self._edge

    def thick_offsets(self, t: int) -> np.ndarray:
        """Cumulative brush shells 1..6 on the checkerboard sublattice —
        parity-preserving offsets sorted into shells of increasing Euclidean
        radius (identical member sets to the historical THICK_OFFSETS)."""
        if self._shells is None:
            offs = []
            for dc in range(-4, 5):
                for dr in range(-4, 5):
                    if (dc + dr) % 2 == 0 and dc * dc + dr * dr <= 16:
                        offs.append((dc * dc + dr * dr, dc, dr))
            offs.sort()
            shells: list[list[tuple[int, int]]] = []
            cur_r = None
            for d2, dc, dr in offs:
                if d2 != cur_r:
                    shells.append([])
                    cur_r = d2
                shells[-1].append((dc, dr))
            cumulative = []
            acc: list[tuple[int, int]] = []
            for shell in shells[:6]:
                acc = acc + shell
                cumulative.append(np.array(acc, dtype=np.int32))
            self._shells = cumulative
        t = int(min(max(t, 1), len(self._shells)))
        return self._shells[t - 1]


def get_view(effect) -> LatticeView:
    """The device-lattice view for a Twod effect, in its render coordinates.
    Call from do_once() AFTER super().do_once() (so orientation attrs and
    r_width/r_height are current). Cached per (shape digest, orientation,
    dims); unmapped virtuals get a full-rectangle fallback view."""
    virtual = getattr(effect, "_virtual", None)
    shape = getattr(virtual, "_shape", None) if virtual is not None else None
    w = getattr(effect, "r_width", 1)
    h = getattr(effect, "r_height", 1)
    rotate_t = getattr(effect, "rotate_t", 0)
    flip2d = bool(getattr(effect, "flip2d", False))
    mirror2d = bool(getattr(effect, "mirror2d", False))

    if shape is None:
        key = ("rect", w, h)
        if key not in _VIEW_CACHE:
            _VIEW_CACHE[key] = LatticeView(
                np.ones((h, w), dtype=bool), has_real_shape=False
            )
        return _VIEW_CACHE[key]

    key = (shape.digest, int(rotate_t), flip2d, mirror2d, w, h)
    view = _VIEW_CACHE.get(key)
    if view is None:
        mask = _render_mask(shape.mask, rotate_t, flip2d, mirror2d)
        if mask.shape != (h, w):
            # dims mismatch (stale shape vs virtual) — fall back safely
            mask = np.ones((h, w), dtype=bool)
            view = LatticeView(mask, has_real_shape=False)
        else:
            view = LatticeView(mask, has_real_shape=True)
        if len(_VIEW_CACHE) > 32:
            _VIEW_CACHE.clear()
        _VIEW_CACHE[key] = view
    return view
