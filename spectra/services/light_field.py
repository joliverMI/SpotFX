"""THE MAP — derive an emitter's measured light field from camera frames,
store it, and serve it to effects through ONE interface.

READ spectra/models/room_map.py's docstring first: it is the binding
statement of what this map is (where each emitter's light LANDS and how
much) and what it must never become (where the LEDs are). This module is
the arithmetic and the store; it holds no opinion about fixtures.

THREE THINGS LIVE HERE
----------------------
1. DERIVATION (footprint_from_frames): dark reference and lit average, both
   already downsampled to the stored GRID_H x GRID_W, differenced and
   clipped at zero. That difference IS the footprint: everything the room
   contributes with the emitter off cancels, so a window, a standby LED or
   a neighbour's porch light subtracts itself out. Values are relative
   luminance 0..1 in the camera's own scale — comparable across emitters
   from the same pose and the same LOCKED exposure, and meaningless across
   anything else, which is why capture_ctx exists and why the session
   refuses an unlocked camera outright.

2. THE AXIS (axis_positions / axis_profile): every grid cell's position
   along the room's floor->ceiling vector, by plain projection of the cell
   centre onto that vector, clipped to [0, 1]. Two taps, a direction in the
   image, no metres.

3. THE EFFECT INTERFACE (per_emitter_scalar) — the whole reason the 2-D
   grid is stored rather than only the axis profile:

       gain(e, t) = sum_i w_i * field(sample_i, t) / sum_i w_i

   with w_i and sample_i the emitter's own footprint cells. A field is any
   callable over the SAMPLES of one emitter; the four kinds his plan names
   (dim wave, travelling colour rotation, implode, explode) are all just
   different `field` functions over the same samples, and three of them
   need x/y, not axis. Only the Dim Wave is wired to the lights in this
   slice (spectra/services/room_effects.py); the other three exist as pure
   fields (spectra/services/light_field_fields.py) so the interface is
   proven to serve them from day one rather than being retrofitted.

   A broad emitter AVERAGES the field across everything it lights — which
   is why a wave over a wall sconce reads as a soft swell rather than a
   hard edge. That softness is physics falling out of the measurement, not
   a smoothing hack, and it is the reason the weighted average is the right
   reduction and a centroid lookup is not.

WHAT THIS MODULE NEVER DOES: write lights (that is room_effects.py over
fx_seam), touch a camera (that is mapping_session.py), or persist an image.
The store holds numbers only.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

import numpy as np

from spectra import config
from spectra.models.room_map import (AXIS_BINS, GRID_H, GRID_W, AxisCalibration,
                                     CaptureContext, EmitterFootprint, RoomMap)

logger = logging.getLogger(__name__)

#: The greyscale frame size the phone uploads. GRID_W x GRID_H divides it
#: exactly (5x5 blocks), so downsampling is a box mean with no remainder and
#: no interpolation to explain.
FRAME_W = GRID_W * 5      # 320
FRAME_H = GRID_H * 5      # 180
#: A camera byte at or above this reads as clipped — the footprint's shape
#: survives, its weight understates the fixture. Reported, never corrected.
SATURATION_LEVEL = 254


# ── derivation ─────────────────────────────────────────────────────────────

def downsample(frame: np.ndarray) -> np.ndarray:
    """One greyscale frame -> the stored GRID_H x GRID_W grid, as an exact
    box mean. Accepts any frame whose dimensions are whole multiples of the
    grid; anything else is a programming error at the wire, not something to
    silently resample."""
    frame = np.asarray(frame, dtype=np.float64)
    if frame.ndim != 2:
        raise ValueError(f"expected a 2-D greyscale frame, got shape {frame.shape}")
    h, w = frame.shape
    if h % GRID_H or w % GRID_W:
        raise ValueError(
            f"frame {w}x{h} does not divide into the {GRID_W}x{GRID_H} grid — "
            "the phone page sends exactly FRAME_W x FRAME_H")
    return frame.reshape(GRID_H, h // GRID_H, GRID_W, w // GRID_W).mean(axis=(1, 3))


def average_frames(frames: Iterable[np.ndarray]) -> Optional[np.ndarray]:
    """Mean of already-downsampled grids. None when handed nothing — the
    caller reports "no frames" by name rather than mapping a black room."""
    grids = [np.asarray(f, dtype=np.float64) for f in frames]
    if not grids:
        return None
    return np.mean(np.stack(grids, axis=0), axis=0)


def footprint_grid(dark: np.ndarray, lit: np.ndarray) -> np.ndarray:
    """lit - dark, clipped at zero, scaled from camera bytes into 0..1.

    The clip is not cosmetic: sensor noise makes about half the cells the
    emitter does NOT light come out very slightly negative, and a negative
    weight in per_emitter_scalar's average would pull a gain the wrong way
    for a region the emitter cannot even reach."""
    diff = np.asarray(lit, dtype=np.float64) - np.asarray(dark, dtype=np.float64)
    return np.clip(diff, 0.0, None) / 255.0


def saturated_fraction(lit_frames: Iterable[np.ndarray]) -> float:
    """Fraction of RAW lit-frame samples at the camera's ceiling. Measured
    on the frames, not on the averaged grid, because averaging hides
    exactly the clipping this is meant to expose."""
    total = 0
    hot = 0
    for f in lit_frames:
        a = np.asarray(f)
        total += a.size
        hot += int(np.count_nonzero(a >= SATURATION_LEVEL))
    return (hot / total) if total else 0.0


# ── the axis ───────────────────────────────────────────────────────────────

def _cell_centres() -> tuple[np.ndarray, np.ndarray]:
    """Normalized (x, y) of every grid cell's centre, row-major, flattened."""
    ys = (np.arange(GRID_H) + 0.5) / GRID_H
    xs = (np.arange(GRID_W) + 0.5) / GRID_W
    gx, gy = np.meshgrid(xs, ys)
    return gx.reshape(-1), gy.reshape(-1)


_CX, _CY = _cell_centres()


def axis_positions(axis: AxisCalibration) -> np.ndarray:
    """Every grid cell's position along the room's axis, 0 at `floor` and 1
    at `ceiling`, by projection onto the floor->ceiling vector and clipped
    to [0, 1]. An UNCALIBRATED axis falls back to plain image height (top of
    frame = 1.0) — stated, not silent: a wave still runs, and the Room
    Builder shows the axis as uncalibrated so the reason is visible."""
    if not axis.calibrated:
        return 1.0 - _CY
    fx, fy = axis.floor.x, axis.floor.y
    vx, vy = axis.ceiling.x - fx, axis.ceiling.y - fy
    denom = vx * vx + vy * vy
    t = ((_CX - fx) * vx + (_CY - fy) * vy) / denom
    return np.clip(t, 0.0, 1.0)


def axis_profile(grid: np.ndarray, axis: AxisCalibration,
                 bins: int = AXIS_BINS) -> list[float]:
    """The footprint collapsed onto the axis: total relative luminance the
    emitter lands in each slice. A projection of the SAME measurement, kept
    alongside it for reading and for the 1-D fields — never a substitute for
    the grid, which is what the 2-D fields sample."""
    pos = axis_positions(axis)
    idx = np.clip((pos * bins).astype(int), 0, bins - 1)
    out = np.zeros(bins, dtype=np.float64)
    np.add.at(out, idx, np.asarray(grid, dtype=np.float64).reshape(-1))
    return [float(v) for v in out]


def footprint_from_frames(*, emitter_id: str, virtual_ids: list[str],
                          dark_frames: list[np.ndarray],
                          lit_frames: list[np.ndarray],
                          axis: AxisCalibration,
                          capture: CaptureContext,
                          label: str = "") -> EmitterFootprint:
    """The whole per-emitter derivation, in one place so the check script,
    the live run and the tests all measure the same way. Frames are ALREADY
    downsampled grids (the session downsamples on arrival — a full-size
    frame is never held longer than it takes to reduce it)."""
    dark = average_frames(dark_frames)
    lit = average_frames(lit_frames)
    if dark is None or lit is None:
        raise ValueError(
            f"emitter {emitter_id!r}: need both a dark reference and a lit "
            f"capture (got {len(dark_frames)} dark, {len(lit_frames)} lit)")
    grid = footprint_grid(dark, lit)
    ctx = capture.model_copy(update={
        "dark_frames": len(dark_frames), "lit_frames": len(lit_frames),
        "saturated_fraction": round(saturated_fraction(lit_frames), 5),
        "frame_width": FRAME_W, "frame_height": FRAME_H,
        "captured_at": time.time()})
    return EmitterFootprint(
        emitter_id=emitter_id, label=label, virtual_ids=list(virtual_ids),
        grid=[float(v) for v in grid.reshape(-1)],
        axis_profile=axis_profile(grid, axis),
        weight=float(grid.sum()),
        capture=ctx)


# ── the effect interface ───────────────────────────────────────────────────

@dataclass(frozen=True)
class EmitterSamples:
    """One emitter's footprint as the arrays a field is evaluated over.
    Every array is the SAME length (the non-zero cells of the footprint):

      x, y   normalized camera-frame position of the cell — what the 2-D
             fields (implode/explode, and any future point-anchored one)
             need, and the reason the full grid is stored.
      axis   the cell's position along the room's axis, 0..1.
      weight the cell's relative luminance: how much of THIS emitter's light
             lands there. The weights of the average, not a mask.
    """
    emitter_id: str
    x: np.ndarray
    y: np.ndarray
    axis: np.ndarray
    weight: np.ndarray

    @property
    def total_weight(self) -> float:
        return float(self.weight.sum())


def samples_for(footprint: EmitterFootprint,
                axis: AxisCalibration) -> EmitterSamples:
    """The footprint as evaluation arrays. Only cells with ZERO weight are
    dropped, and dropping those is exact — a zero weight contributes exactly
    nothing to a weighted average, so the gain is bit-identical either way.

    A brightness FLOOR (keep only cells above some fraction of the peak) was
    tried and REMOVED: it is a real, if small, bias against broad dim spill
    — exactly the ceiling-and-floor light this whole design exists to
    capture — bought for a saving that does not exist. The full 2304-cell
    reduction over four emitters measures well under a millisecond
    (scripts/check_room_effect_wave.py reports it against the real code),
    against a 67 ms tick."""
    grid = np.asarray(footprint.grid, dtype=np.float64)
    pos = axis_positions(axis)
    keep = grid > 0.0
    return EmitterSamples(emitter_id=footprint.emitter_id,
                          x=_CX[keep], y=_CY[keep], axis=pos[keep],
                          weight=grid[keep])


FieldFn = Callable[[EmitterSamples, float], Any]


def per_emitter_scalar(field_fn: FieldFn, t: float = 0.0, *,
                       samples: Iterable[EmitterSamples]) -> dict[str, float]:
    """THE interface, and the only one an effect ever needs:

        {emitter_id: weighted average of `field_fn` over that emitter's
                     measured footprint}

    `field_fn(samples, t)` returns either one value per sample (an array,
    the normal case) or a single scalar (a constant field). The reduction is
    the plan's own formula, sum(w*f)/sum(w) — a broad emitter therefore
    averages the field across everything it lights, which is where the
    softness comes from.

    An emitter with no measured light contributes NOTHING to the result
    rather than a default gain: a caller must be able to tell "mapped and
    the field says 1.0" from "never mapped", and a fabricated 1.0 makes
    those identical."""
    out: dict[str, float] = {}
    for s in samples:
        total = s.total_weight
        if total <= 0.0:
            continue
        values = field_fn(s, t)
        arr = np.asarray(values, dtype=np.float64)
        if arr.ndim == 0:
            out[s.emitter_id] = float(arr)
            continue
        if arr.shape != s.weight.shape:
            raise ValueError(
                f"field returned {arr.shape} values for {s.emitter_id!r}'s "
                f"{s.weight.shape} samples")
        out[s.emitter_id] = float((arr * s.weight).sum() / total)
    return out


# ── the store ──────────────────────────────────────────────────────────────

def _path(path: Optional[os.PathLike] = None):
    return config.ROOM_MAPS_FILE if path is None else path


def load_rooms(path: Optional[os.PathLike] = None) -> list[RoomMap]:
    p = _path(path)
    try:
        if not os.path.exists(p):
            return []
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [RoomMap(**r) for r in (data.get("rooms") or [])]
    except Exception:
        logger.exception("light_field: unreadable room map store %s", p)
        return []


def save_rooms(rooms: list[RoomMap], path: Optional[os.PathLike] = None) -> None:
    """Atomic tmp+replace, the store convention across spectra/ — a mapping
    run that dies mid-write must not leave a half-written map behind."""
    p = _path(path)
    os.makedirs(os.path.dirname(str(p)) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(str(p)) or ".",
                               prefix="room_maps", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"rooms": [r.model_dump() for r in rooms]}, fh, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_room(room_id: str, path: Optional[os.PathLike] = None) -> Optional[RoomMap]:
    for r in load_rooms(path):
        if r.id == room_id:
            return r
    return None


def put_room(room: RoomMap, path: Optional[os.PathLike] = None) -> RoomMap:
    rooms = load_rooms(path)
    room.updated_at = time.time()
    rooms = [r for r in rooms if r.id != room.id] + [room]
    save_rooms(rooms, path)
    return room


def delete_room(room_id: str, path: Optional[os.PathLike] = None) -> bool:
    rooms = load_rooms(path)
    kept = [r for r in rooms if r.id != room_id]
    if len(kept) == len(rooms):
        return False
    save_rooms(kept, path)
    return True


def thumbnail(footprint: EmitterFootprint, w: int = 16, h: int = 9) -> list[list[float]]:
    """A tiny normalized heat grid for the Room Builder's "mapped vs not"
    thumbnails — normalized to its OWN peak, because a thumbnail answers
    "what shape is this footprint", never "how bright is this fixture"
    (that is `weight`, shown as its own number)."""
    grid = np.asarray(footprint.grid, dtype=np.float64)
    if grid.size != GRID_W * GRID_H:
        return []
    grid = grid.reshape(GRID_H, GRID_W)
    ys = np.array_split(np.arange(GRID_H), h)
    xs = np.array_split(np.arange(GRID_W), w)
    peak = float(grid.max()) or 1.0
    return [[round(float(grid[np.ix_(yr, xr)].mean() / peak), 4) for xr in xs]
            for yr in ys]
