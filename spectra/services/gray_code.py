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

WHAT THE INVERSE CANNOT CANCEL, learned in his room on 2026-09-01 and the
reason `resolution_report` exists: comparing a pattern against its own
inverse removes every unknown about brightness, but it assumes the camera
can RESOLVE the pattern in the first place. Where one camera pixel
integrates many LEDs, a pattern and its inverse deliver the same light to
the same pixel and cancel each other instead of the unknowns — |p - q|
goes to zero, no bit is confident, and a room full of light decodes to
nothing at all. That is a fact about the pose and the frame size, not about
his fixtures, and it is measurable from the reference pair alone. See
MIN_CAMERA_PX_PER_INDEX and `docs/commissioning-field-decode-failure.md`.

AND THE STATE BETWEEN THE TWO, which is the dangerous one: a target imaged
just ABOVE that bar decodes, and decodes WRONG — gray code's own guarantee
that a flipped low bit lands on a NEIGHBOUR means a marginal pose produces
a confident, plausible, wrong arrangement rather than a visible failure. So
`resolution_report` has three states and refuses two of them, saying which.
See RESOLUTION_SAFETY_FACTOR.

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
#: bright-end level (see PEAK_SAMPLE) before it is considered to be looking
#: at the composition at all. Everything below it is wall, ceiling, spill
#: and sensor noise — a region where `pattern` and `inverse` differ only by
#: noise and every bit would be a coin toss.
LIT_FRACTION = 0.15
#: HOW THE FRAME'S BRIGHT END IS TAKEN: the mean of the this-many brightest
#: camera pixels of `full - dark`, NOT a percentile.
#:
#: THE FIELD FAILURE THIS EXISTS FOR (2026-09-01, his tv-mapper, both runs):
#: this was `np.percentile(bright, 99.0)`, which silently assumes the
#: composition covers more than 1% of the frame. His does not — the whole
#: 736-pixel composition images into about 66 camera pixels of 57,600
#: (0.11%), so the 99th percentile of full-minus-dark was ZERO. The gate
#: then collapsed to `bright >= 1e-9`, i.e. "anything at all above the dark
#: reference", and reported 3,165 lit pixels in one run (averaging noise,
#: not light) and 0 in the next. Neither number described the room. A mean
#: over a handful of the brightest pixels is robust to a hot pixel and does
#: not care what fraction of the frame the composition covers.
PEAK_SAMPLE = 25
#: An absolute floor, in grey levels, under which `full - dark` is not a
#: measurement. This is NOT a scene-brightness assumption — the whole
#: reason for capturing the inverse is that scene levels are unknowable —
#: it is the SENSOR's own quantisation: a camera pixel whose full-on
#: average sits less than one grey level above its dark average has been
#: rounded, not measured. Without it, averaging noise reads as light (see
#: PEAK_SAMPLE).
MIN_BRIGHT_LEVELS = 1.0
#: A bit is confident when |pattern - inverse| is at least this fraction of
#: that camera pixel's own full-minus-dark brightness. Relative, never an
#: absolute byte count: the whole reason for capturing the inverse is that
#: absolute levels are unknowable.
BIT_CONFIDENCE = 0.20
#: Camera pixels that must agree on an index before it counts as SEEN.
MIN_SUPPORT = 1
#: CAMERA PIXELS PER COMPOSITION INDEX the decode needs along the imaged
#: strip, and the reason a run can now refuse before spending the room's
#: dark time.
#:
#: It is Nyquist, on the finest structure the stack contains: gray bit 0
#: alternates in runs of TWO indices (0,1,1,0,0,1,1,0 ...), so a pattern
#: and its inverse differ over a two-index period. A camera that puts fewer
#: than about two pixels on each index cannot see that period at all — the
#: pattern and its inverse land on the SAME camera pixels and average to
#: the same brightness, |p - q| goes to zero, no bit is confident, and
#: EVERY lit pixel comes back undecodable however much light is in the
#: frame. That is exactly what his room produced: 736 pixels imaged into
#: ~66 camera pixels (0.09 per index, ~22x short), 0 decoded, 0 out of
#: range, and every lit pixel undecodable.
#:
#: A run at or above this bar can still fail for other reasons; a run below
#: it cannot succeed for any.
MIN_CAMERA_PX_PER_INDEX = 2.0
#: THE MARGIN, and it is the whole reason a per-target run does not erode
#: the honesty the whole-composition run bought.
#:
#: MIN_CAMERA_PX_PER_INDEX is the Nyquist limit — the point below which the
#: low bits carry no information AT ALL. A run sitting exactly ON that limit
#: is not a run that works: its lowest bit is sampled at one sample per
#: half-period, where a fraction of a pixel of registration error, one LED's
#: worth of vignette, or the grey8 rounding on the wire flips it. And a
#: flipped LOW bit does not look like a failure — gray code guarantees it
#: decodes to a NEIGHBOUR, which is a confident, plausible, WRONG answer.
#: That is the one outcome an instrument judged against pre-registered
#: ground truth must never produce.
#:
#: So the boundary is deliberately conservative: a target that images at
#: less than this multiple of the Nyquist bar REFUSES as MARGINAL, in those
#: words, rather than attempting a decode that would look like it worked.
#: 1.25x buys a quarter of a camera pixel of headroom on the finest
#: structure in the stack (gray bit 0's two-index period).
#:
#: The captain's ruling that fixed the number (2026-09-01, on splitting the
#: run per fixture): "marginal is the state that produces a confident wrong
#: answer". His own ring — 560 pixels, needing ~1120 camera pixels of a
#: frame whose entire border is ~1000 — is the case this exists to refuse.
#:
#: It is NOT a knob for getting a run to pass. Lowering it does not make a
#: marginal pose readable; it only stops the instrument saying so.
RESOLUTION_SAFETY_FACTOR = 1.25

#: The three states `resolution_report` reports, and only the first one
#: runs. MARGINAL and IMPOSSIBLE both refuse, and the refusal says WHICH —
#: they are different findings and a different act clears each: a marginal
#: target wants a closer pose or a smaller target, an impossible one cannot
#: be read at this frame size however the phone is held.
RESOLUTION_OK = "ok"
RESOLUTION_MARGINAL = "marginal"
RESOLUTION_IMPOSSIBLE = "impossible"


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
    #: WHERE A DECODE DIED, per bit, so a failed field run answers that
    #: question in its own response instead of needing a desk investigation
    #: against frames nobody kept. Each entry is
    #: {bit, median_strength, confident_fraction} over the LIT pixels —
    #: `median_strength` is |pattern - inverse| / that pixel's own
    #: full-minus-dark brightness, the exact quantity BIT_CONFIDENCE gates
    #: on. A bit whose median strength is ~0 is a bit the camera could not
    #: see at all (its pattern and inverse cancelled); a bit hovering near
    #: BIT_CONFIDENCE is a threshold question. They are not the same
    #: finding and must not read the same.
    bit_contrast: list[dict] = field(default_factory=list)
    #: The imaged extent of the composition, from the reference pair alone
    #: (see `resolution_report`).
    resolution: dict = field(default_factory=dict)

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
                "out_of_range_pixels": self.out_of_range_pixels,
                "bit_contrast": self.bit_contrast,
                "resolution": self.resolution}


def bright_and_lit(dark: np.ndarray, full: np.ndarray, *,
                   lit_fraction: float = LIT_FRACTION
                   ) -> tuple[np.ndarray, np.ndarray, float, float]:
    """`full - dark`, and WHICH camera pixels are looking at the
    composition — one definition, used by the decode and by the
    resolution report, so the run cannot refuse on one count and decode
    against another.

    Returns (bright, lit, peak, floor). See PEAK_SAMPLE for why the bright
    end is a mean over the brightest few pixels rather than a percentile,
    and MIN_BRIGHT_LEVELS for why there is an absolute floor under it."""
    dark = np.asarray(dark, dtype=np.float64)
    full = np.asarray(full, dtype=np.float64)
    if dark.shape != full.shape:
        raise ValueError(f"dark {dark.shape} and full {full.shape} differ")
    bright = np.clip(full - dark, 0.0, None)
    if bright.size:
        k = int(min(PEAK_SAMPLE, bright.size))
        peak = float(np.mean(np.sort(bright, axis=None)[-k:]))
    else:
        peak = 0.0
    floor = max(MIN_BRIGHT_LEVELS, peak * lit_fraction)
    return bright, bright >= floor, peak, floor


def resolution_report(dark: np.ndarray, full: np.ndarray, *, total: int,
                      lit_fraction: float = LIT_FRACTION) -> dict:
    """CAN THIS CAMERA, FROM WHERE IT IS STANDING, RESOLVE THIS
    COMPOSITION AT ALL? — answered from the dark and full reference pair
    alone, which is two captures and about four seconds into a run.

    THE FIELD FAILURE THIS EXISTS FOR: a run that cannot possibly decode
    still spent ~42 s holding his room dark, then reported 0 of 736 and
    handed the frozen table an attribution ("occlusion or blob-merge")
    that read as a fault in his room rather than as an instrument pointed
    at something it cannot see. The arithmetic that settles it needs no
    patterns: how many camera pixels does the whole composition light,
    and how many does it need (MIN_CAMERA_PX_PER_INDEX per index)?

    Reported on every run, refused on only the ones below the bar — the
    number is worth carrying even when it passes, because it says how much
    margin the pose had.

    THREE STATES, NOT TWO (`verdict`), and only the first one runs:

      ok          at or above RESOLUTION_SAFETY_FACTOR x the Nyquist bar.
      marginal    above the Nyquist bar but inside the margin. REFUSES.
                  This is the state that produces a CONFIDENT WRONG ANSWER
                  — a low bit flipped by a fraction of a pixel decodes, by
                  gray code's own guarantee, to a plausible NEIGHBOUR — so
                  the conservative act is to say no. See
                  RESOLUTION_SAFETY_FACTOR.
      impossible  below the Nyquist bar. Cannot succeed for any reason.

    `resolvable` follows `verdict == RESOLUTION_OK`, so every existing
    caller inherits the conservative boundary rather than opting into it."""
    bright, lit, peak, floor = bright_and_lit(dark, full,
                                              lit_fraction=lit_fraction)
    total = int(max(0, total))
    lit_pixels = int(lit.sum())
    per_index = (lit_pixels / total) if total else 0.0
    needed = int(np.ceil(total * MIN_CAMERA_PX_PER_INDEX))
    safe = int(np.ceil(total * MIN_CAMERA_PX_PER_INDEX
                       * RESOLUTION_SAFETY_FACTOR))
    if lit_pixels >= safe:
        verdict = RESOLUTION_OK
    elif lit_pixels >= needed:
        verdict = RESOLUTION_MARGINAL
    else:
        verdict = RESOLUTION_IMPOSSIBLE
    return {"total": total, "lit_pixels": lit_pixels,
            "camera_px_per_index": round(per_index, 4),
            "needed_camera_px": needed,
            "safe_camera_px": safe,
            "min_camera_px_per_index": MIN_CAMERA_PX_PER_INDEX,
            "safety_factor": RESOLUTION_SAFETY_FACTOR,
            "safe_camera_px_per_index": round(
                MIN_CAMERA_PX_PER_INDEX * RESOLUTION_SAFETY_FACTOR, 4),
            "frame_pixels": int(bright.size),
            "peak": round(peak, 3), "floor": round(floor, 3),
            "verdict": verdict,
            "resolvable": bool(verdict == RESOLUTION_OK),
            "any_light": bool(lit_pixels > 0)}


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
    height, width = dark.shape
    bright, lit, _peak, _floor = bright_and_lit(dark, full,
                                                lit_fraction=lit_fraction)

    value = np.zeros(bright.shape, dtype=np.int64)
    confident = lit.copy()
    contrast: list[dict] = []
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
        strength = np.nan_to_num(strength, nan=0.0)
        ok_bit = strength >= bit_confidence
        confident &= ok_bit
        value |= (diff > 0).astype(np.int64) << bit
        seen_here = strength[lit]
        contrast.append({
            "bit": bit,
            "median_strength": (round(float(np.median(seen_here)), 4)
                                if seen_here.size else None),
            "confident_fraction": (round(float(ok_bit[lit].mean()), 4)
                                   if seen_here.size else None)})

    index = from_gray(value)
    in_range = (index >= 0) & (index < total)
    ok = confident & in_range

    out = Decode(total=total, width=width, height=height,
                 index_map=np.where(ok, index, -1).reshape(-1),
                 lit_pixels=int(lit.sum()),
                 undecodable_pixels=int((lit & ~confident).sum()),
                 out_of_range_pixels=int((lit & confident & ~in_range).sum()),
                 bit_contrast=contrast,
                 resolution=resolution_report(dark, full, total=total,
                                              lit_fraction=lit_fraction))

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
                 blobs: Optional[dict] = None,
                 window_sigmas: Optional[float] = None) -> np.ndarray:
    """One camera frame of a KNOWN arrangement with `on` lit — the shared
    renderer behind every offline proof of this instrument.

    `layout` is the truth: composition index -> (x, y) in normalised frame
    coordinates. `dead` names indices that emit nothing however they are
    patterned — his hardware being wrong, which the frozen table calls out
    as a real outcome to REPORT rather than a commissioning failure.

    `window_sigmas` bounds each cached blob to that many radii around its
    own centre instead of a whole frame's worth of array. It exists for the
    FIELD REGIME proof — his real composition is 736 pixels, and a
    full-frame cache for 736 blobs of a 320x180 frame is ~340 MB, where
    5-sigma windows are ~3 MB. Left at None the renderer is byte-for-byte
    what it always was, so nothing already proven against it moves."""
    dead = dead or set()
    if blobs is None:
        blobs = {}
    frame = np.full((height, width), float(dark_level), dtype=np.float64)
    gain = lit_level - dark_level
    if window_sigmas is None:
        ys, xs = np.mgrid[0:height, 0:width]
        for i in on:
            if i in dead or i not in layout:
                continue
            blob = blobs.get(i)
            if blob is None:
                cx, cy = layout[i][0] * width, layout[i][1] * height
                blob = np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) /
                                (2.0 * radius_px ** 2)))
                blobs[i] = blob
            frame += blob * gain
    else:
        span = max(1, int(np.ceil(window_sigmas * radius_px)))
        for i in on:
            if i in dead or i not in layout:
                continue
            got = blobs.get(i)
            if got is None:
                cx, cy = layout[i][0] * width, layout[i][1] * height
                x0, x1 = max(0, int(cx) - span), min(width, int(cx) + span + 1)
                y0, y1 = max(0, int(cy) - span), min(height, int(cy) + span + 1)
                if x1 <= x0 or y1 <= y0:      # centred off the frame
                    blobs[i] = (0, 0, 0, 0, np.zeros((0, 0)))
                    continue
                wy, wx = np.mgrid[y0:y1, x0:x1]
                patch = np.exp(-(((wx - cx) ** 2 + (wy - cy) ** 2) /
                                 (2.0 * radius_px ** 2)))
                got = (y0, y1, x0, x1, patch)
                blobs[i] = got
            y0, y1, x0, x1, patch = got
            frame[y0:y1, x0:x1] += patch * gain
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
