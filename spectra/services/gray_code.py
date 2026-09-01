"""GRAY-CODE PIXEL ADDRESSING — the patterns to light, and the decode that
turns a stack of camera captures back into "which pixel is this?".

PURE. No camera, no light, no store, no clock. Everything here is arrays in
and arrays out, which is why the whole instrument can be proven against a
SYNTHETIC room where the answer is known in advance
(`tests/test_gray_code.py`, `scripts/check_commissioning.py`) before it is
ever pointed at his television.

WHY GRAY CODE AND NOT A PIXEL WALK (the plan, §8): lighting 736 pixels one
at a time is minutes of a dark room. Lighting them in `bits_needed(736)` =
10 patterns identifies EVERY pixel's camera position simultaneously — 10
patterns plus their inverses plus a dark and a full reference is 22
captures, about 35 seconds, and the count is logarithmic in the pixel count
rather than linear.

WHY GRAY CODE RATHER THAN PLAIN BINARY: adjacent indices differ in exactly
ONE bit, so a camera pixel that straddles the boundary between two LEDs
misreads at most one bit and lands on a NEIGHBOUR, never on a far-away
index. Under plain binary the 255/256 boundary flips every bit at once and
a straddling camera pixel can decode to anything at all — which would show
up as scattered nonsense in the very ordering row this test exists to
judge.

WHY EVERY PATTERN IS CAPTURED WITH ITS INVERSE, and it is not belt and
braces: a camera pixel's brightness depends on the surface it is looking
at, the lens vignette, and the fixture's own output — none of which are
known. Comparing a pattern against a fixed threshold would need all three.
Comparing it against its own INVERSE cancels every one of them: the bit is
1 wherever `pattern > inverse`, and the CONFIDENCE is how far apart the two
came out relative to that pixel's own full-on brightness. A pixel whose two
captures came out too close to call is reported UNDECODABLE rather than
guessed — the whole point of an instrument that can fail honestly.

WHAT "SEEN" MEANS HERE, precisely, because a row of the frozen comparison
is judged on it: an index is SEEN when at least `MIN_SUPPORT` camera pixels
decoded to it with every bit confident. One camera pixel agreeing is not a
measurement; it is a coin landing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

#: A camera pixel must be at least this fraction of the frame's own
#: bright-end level (the 99th percentile of full-minus-dark) before it is
#: considered to be looking at the composition at all. Everything below it
#: is wall, ceiling, spill and sensor noise — a region where `pattern` and
#: `inverse` differ only by noise and every bit would be a coin toss.
LIT_FRACTION = 0.15
#: A bit is confident when |pattern - inverse| is at least this fraction of
#: that camera pixel's own full-minus-dark brightness. Relative, never an
#: absolute byte count: the whole reason for capturing the inverse is that
#: absolute levels are unknowable.
BIT_CONFIDENCE = 0.20
#: Camera pixels that must agree on an index before it counts as SEEN.
MIN_SUPPORT = 1


def bits_needed(total: int) -> int:
    """How many patterns address `total` pixels. 1 for a single pixel (a
    pattern of one bit still distinguishes it from "not lit"), otherwise
    ceil(log2(total))."""
    if total <= 1:
        return 1
    return int(np.ceil(np.log2(total)))


def gray(index: np.ndarray | int):
    """Standard reflected binary gray code: g = i ^ (i >> 1)."""
    i = np.asarray(index, dtype=np.int64)
    return i ^ (i >> 1)


def pattern_bits(indices: np.ndarray, bit: int) -> np.ndarray:
    """Bit `bit` of each index's gray code, as 0/1."""
    return ((gray(indices) >> int(bit)) & 1).astype(np.uint8)


def pattern_string(indices: np.ndarray | list[int], bit: int, *,
                   invert: bool = False) -> str:
    """The wire form `fx/effects/pixelPattern.py` lights: one character per
    effect pixel, in the virtual's OWN buffer order, for the composition
    indices those pixels carry.

    `indices` is index-aligned with the virtual's effect pixels; a pixel
    that belongs to no composition index is passed as -1 and is always
    dark (it is not part of the thing being commissioned, so lighting it
    would put unattributable light in the frame)."""
    idx = np.asarray(indices, dtype=np.int64)
    bits = pattern_bits(np.clip(idx, 0, None), bit)
    if invert:
        bits = 1 - bits
    bits = np.where(idx < 0, 0, bits)
    return "".join("1" if b else "0" for b in bits)


def from_gray(value: np.ndarray) -> np.ndarray:
    """Gray code back to a plain index, MSB down. Vectorised over a whole
    camera frame."""
    v = np.asarray(value, dtype=np.int64).copy()
    shift = 32
    while shift:
        v ^= v >> shift
        shift //= 2
    return v


@dataclass
class Decode:
    """One decoded capture stack.

    `index_map` is per CAMERA pixel (flattened, frame order): the
    composition index that camera pixel decoded to, or -1 for "not lit" /
    "not confident" / "out of range". `positions` is the answer the
    comparison is judged on: composition index -> (x, y) in NORMALISED
    frame coordinates, 0..1, x left->right and y top->bottom — the same
    convention `spectra/models/room_map.py`'s `Point` uses, and, exactly
    as there, a place in a PICTURE and never a place in the room."""
    total: int
    width: int
    height: int
    index_map: np.ndarray
    positions: dict[int, tuple[float, float]] = field(default_factory=dict)
    support: dict[int, int] = field(default_factory=dict)
    brightness: dict[int, float] = field(default_factory=dict)
    lit_pixels: int = 0
    undecodable_pixels: int = 0
    out_of_range_pixels: int = 0

    @property
    def seen(self) -> list[int]:
        return sorted(i for i, n in self.support.items() if n >= MIN_SUPPORT)

    @property
    def missing(self) -> list[int]:
        seen = set(self.seen)
        return [i for i in range(self.total) if i not in seen]

    @property
    def seen_fraction(self) -> float:
        return (len(self.seen) / self.total) if self.total else 0.0

    def as_dict(self) -> dict:
        return {"total": self.total, "seen": len(self.seen),
                "seen_fraction": round(self.seen_fraction, 5),
                "missing": self.missing[:64],
                "missing_count": len(self.missing),
                "lit_pixels": self.lit_pixels,
                "undecodable_pixels": self.undecodable_pixels,
                "out_of_range_pixels": self.out_of_range_pixels}


def decode_stack(dark: np.ndarray, full: np.ndarray,
                 pairs: list[tuple[np.ndarray, np.ndarray]], *,
                 total: int,
                 lit_fraction: float = LIT_FRACTION,
                 bit_confidence: float = BIT_CONFIDENCE) -> Decode:
    """The whole decode, in one place so the synthetic proof, the live run
    and the tests all measure the same way.

    Every argument is an averaged capture at FULL camera resolution (not
    the stored 64x36 map grid — 736 pixels cannot be resolved by 2304 grid
    cells). `pairs` is [(pattern, inverse)] in BIT ORDER, least significant
    first.

    A pixel is decoded only when it is lit AND every bit is confident.
    Anything else is -1 and counted, so "we could not read this" is a
    number the report carries rather than a silence."""
    dark = np.asarray(dark, dtype=np.float64)
    full = np.asarray(full, dtype=np.float64)
    if dark.shape != full.shape:
        raise ValueError(f"dark {dark.shape} and full {full.shape} differ")
    height, width = dark.shape
    bright = np.clip(full - dark, 0.0, None)
    peak = float(np.percentile(bright, 99.0)) if bright.size else 0.0
    lit = bright >= max(1e-9, peak * lit_fraction)

    value = np.zeros(bright.shape, dtype=np.int64)
    confident = lit.copy()
    for bit, (pat, inv) in enumerate(pairs):
        p = np.asarray(pat, dtype=np.float64)
        q = np.asarray(inv, dtype=np.float64)
        if p.shape != bright.shape or q.shape != bright.shape:
            raise ValueError(
                f"bit {bit}: pattern {p.shape} / inverse {q.shape} do not "
                f"match the reference frames {bright.shape}")
        diff = p - q
        # Relative to THIS pixel's own brightness — see the module
        # docstring for why an absolute threshold cannot be right here.
        with np.errstate(divide="ignore", invalid="ignore"):
            strength = np.abs(diff) / np.where(bright > 0, bright, np.nan)
        confident &= np.nan_to_num(strength, nan=0.0) >= bit_confidence
        value |= (diff > 0).astype(np.int64) << bit

    index = from_gray(value)
    in_range = (index >= 0) & (index < total)
    ok = confident & in_range

    out = Decode(total=total, width=width, height=height,
                 index_map=np.where(ok, index, -1).reshape(-1),
                 lit_pixels=int(lit.sum()),
                 undecodable_pixels=int((lit & ~confident).sum()),
                 out_of_range_pixels=int((lit & confident & ~in_range).sum()))

    ys, xs = np.mgrid[0:height, 0:width]
    nx = (xs + 0.5) / width
    ny = (ys + 0.5) / height
    flat_idx = index[ok]
    if flat_idx.size:
        w = bright[ok]
        wx = nx[ok] * w
        wy = ny[ok] * w
        counts = np.bincount(flat_idx, minlength=total)
        sw = np.bincount(flat_idx, weights=w, minlength=total)
        sx = np.bincount(flat_idx, weights=wx, minlength=total)
        sy = np.bincount(flat_idx, weights=wy, minlength=total)
        for i in np.nonzero(counts)[0]:
            n = int(counts[i])
            if n < MIN_SUPPORT or sw[i] <= 0:
                continue
            out.support[int(i)] = n
            out.brightness[int(i)] = float(sw[i])
            out.positions[int(i)] = (float(sx[i] / sw[i]), float(sy[i] / sw[i]))
    return out


def agreement(a: Decode, b: Decode) -> dict:
    """TWO INDEPENDENT DECODES, COMPARED — the plan's own "run it twice
    back-to-back" (the brief's point 4). Not one of the frozen rows: this
    bounds the INSTRUMENT's own noise, so a later disagreement with the
    stored truth can be read against how much this instrument wobbles when
    nothing at all has changed.

    Both runs see the same room from the same pose, so every index they
    both saw should land in the same place. The median displacement between
    the two is the instrument's own repeatability, in the same normalised
    frame units the arrangement row is judged in."""
    both = sorted(set(a.positions) & set(b.positions))
    only_a = sorted(set(a.positions) - set(b.positions))
    only_b = sorted(set(b.positions) - set(a.positions))
    if not both:
        return {"compared": 0, "median_shift": None, "p95_shift": None,
                "only_first": len(only_a), "only_second": len(only_b),
                "note": "the two runs share no decoded pixel at all"}
    d = np.array([np.hypot(a.positions[i][0] - b.positions[i][0],
                           a.positions[i][1] - b.positions[i][1])
                  for i in both])
    return {"compared": len(both),
            "median_shift": float(np.median(d)),
            "p95_shift": float(np.percentile(d, 95)),
            "only_first": len(only_a), "only_second": len(only_b),
            "note": ""}


def render_frame(layout: dict[int, tuple[float, float]], on, *,
                 width: int, height: int, radius_px: float = 2.5,
                 dark_level: float = 8.0, lit_level: float = 220.0,
                 noise: float = 0.0, rng=None,
                 dead: Optional[set[int]] = None,
                 blobs: Optional[dict] = None) -> np.ndarray:
    """One camera frame of a KNOWN arrangement with `on` lit — the shared
    renderer behind every offline proof of this instrument.

    `layout` is the truth: composition index -> (x, y) in normalised frame
    coordinates. `dead` names indices that emit nothing however they are
    patterned — his hardware being wrong, which the frozen table calls out
    as a real outcome to REPORT rather than a commissioning failure."""
    dead = dead or set()
    ys, xs = np.mgrid[0:height, 0:width]
    if blobs is None:
        blobs = {}
    frame = np.full((height, width), float(dark_level), dtype=np.float64)
    for i in on:
        if i in dead or i not in layout:
            continue
        blob = blobs.get(i)
        if blob is None:
            cx, cy = layout[i][0] * width, layout[i][1] * height
            blob = np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) /
                            (2.0 * radius_px ** 2)))
            blobs[i] = blob
        frame += blob * (lit_level - dark_level)
    if noise:
        gen = rng if rng is not None else np.random.default_rng(0)
        frame += gen.normal(0.0, noise, size=frame.shape)
    return np.clip(frame, 0.0, 255.0)


def synthetic_stack(layout: dict[int, tuple[float, float]], *,
                    width: int, height: int, radius_px: float = 2.5,
                    dark_level: float = 8.0, lit_level: float = 220.0,
                    noise: float = 0.0, seed: int = 7,
                    dead: Optional[set[int]] = None
                    ) -> tuple[np.ndarray, np.ndarray,
                               list[tuple[np.ndarray, np.ndarray]]]:
    """A camera looking at a KNOWN arrangement, one whole capture stack —
    the whole reason this instrument can be proven without a room.

    The returned stack is exactly what `decode_stack` consumes, so a test
    can assert that the decode recovers the arrangement it was handed and
    that a DELIBERATELY CORRUPTED stack fails the row it should."""
    rng = np.random.default_rng(seed)
    total = (max(layout) + 1) if layout else 0
    cache: dict[int, np.ndarray] = {}

    def render(on: set[int]) -> np.ndarray:
        return render_frame(layout, on, width=width, height=height,
                            radius_px=radius_px, dark_level=dark_level,
                            lit_level=lit_level, noise=noise, rng=rng,
                            dead=dead, blobs=cache)

    everything = set(layout)
    dark_frame = render(set())
    full_frame = render(everything)
    pairs = []
    for bit in range(bits_needed(total)):
        on = {i for i in everything if pattern_bits(np.array([i]), bit)[0]}
        pairs.append((render(on), render(everything - on)))
    return dark_frame, full_frame, pairs
