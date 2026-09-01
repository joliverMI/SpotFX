"""THE AMBIENT-STABILITY GATE — did the light in the room stay still while
the instrument was reading?

THE LIVE FAILURE THIS EXISTS FOR (2026-09-01, his first per-fixture run,
the right sconce): the camera was pointed at the fixture WITH A WINDOW IN
VIEW, in daylight, with cloud moving. The resolution gate passed honestly
(5.375 camera pixels per index, peak 49.3, floor 7.4) — the pose could read
that fixture. The decode still came back 34 of 88, 22 of those 34 in the
wrong order, 392 of 473 lit camera pixels unconfident, and
`out_of_range_pixels = 30`.

That last number is the whole point. `docs/SPECTRA_SPEC.md` §98 froze the
dichotomy: an UNRESOLVABLE pose has zero confident bits with the high bits
near 1.0, while a stack that compared two DIFFERENT SCENES keeps real
low-bit contrast and decodes CONFIDENTLY to indices that do not exist. The
second signature is what his run produced, and the scene that differed was
the daylight — cloud moved between a pattern and its inverse, and
lit-minus-dark cannot subtract a reference that changed underneath it.

The frozen table then judged that as an instrument-indicted FAIL, which is
true and useless: someone has to remember today to read it as "the window".
THE CAPTAIN'S RULING: an instrument that cannot name its own defeated
condition makes every future user depend on someone remembering today. So
this module measures the condition and the run REFUSES BY NAME
(`mapping_refusals.ambient_drift`), with the measured drift carried so the
boundary is inspectable.

HOW IT MEASURES, and the one trap it has to avoid: the composition's own
light changes on purpose, every capture — that is the instrument working,
not ambient drift. So the gate never looks at the composition. It picks a
FIXED SET of camera pixels ONCE, from the reference pair, as the dimmer
half of `full - dark` (`BACKGROUND_QUANTILE`), and then measures the SAME
pixels in every later capture. Those pixels are wall, ceiling and window —
the composition contributes essentially nothing to them by construction,
whatever pattern is currently lit.

A QUANTILE, DELIBERATELY, NOT A THRESHOLD. A brightness threshold is
defined against `full - dark`, so a genuine ambient step BETWEEN those two
reference captures inflates the difference everywhere and the "background"
set collapses to nothing — the gate would go blind exactly when it is most
needed. Which camera pixels sit in the dimmer half does not move when the
whole frame shifts by a constant, so the set survives the thing it is
measuring.

TWO COMPARISONS ARE GATED, AND BOTH ARE STRUCTURALLY FREE OF THE LAMP.
This is the part that took a redesign, so it is written down:

  THE PAIR DELTA — a pattern against its OWN inverse. Those two captures
  light COMPLEMENTARY halves of the composition, so the fixture's own
  contribution to the background is the same in both and cancels exactly.
  Whatever is left is the room. It is also the physically exact corrupting
  quantity: a bit is read as `pattern - inverse`, so light that changed
  between those two shots lands in the bit's own arithmetic. Checked on
  every pair, which is what makes the refusal EARLY.

  DARK AGAINST DARK — the opening reference against a CLOSING one taken
  with the composition off again. No lamp in either, so nothing to argue
  about. It costs one capture of about twenty-three and it is the only
  reading in the stack that is unarguable.

Each is measured two ways: WHOLE (the median of the background set) and
REGIONAL (the same per tile of a `TILE_GRID` x `TILE_GRID` grid, worst
tile reported). A window is a REGION — cloud moving off the sun can lift
one corner of the frame by twenty grey levels while the whole-frame median
barely moves.

WHAT IS MEASURED BUT NOT GATED, deliberately: a lamp-ON capture against
the opening dark. That difference contains the fixture's own spill into
the background as well as the room, and the two cannot be told apart from
one frame. Gating it would refuse a room whose fixture simply lights the
walls — a wall, not a gate. It is reported, because it is worth seeing.

The gap this leaves is small and it is the right size: a room-light change
that arrives and STAYS is invisible to the pair deltas (it cancels in
`pattern - inverse` exactly as it does in the bit), so it corrupts no bit —
only the brightness reference — and the closing dark catches it at the end
of the pass. A change that MOVES is what wrecks the decode, and that is the
one caught immediately.

THE BOUND, and why it is this number (`drift_bound`):

    bound = max(DRIFT_FLOOR_LEVELS, DRIFT_FRACTION_OF_PEAK x peak)

`peak` is the composition's own signal in this frame — the same quantity
`gray_code.BIT_CONFIDENCE` (0.20) is relative to. A drift of D shifts
`pattern - inverse` by D at every camera pixel. At D = 0.10 x peak, drift
ALONE cannot manufacture a confident bit: it reaches half of the confidence
bar, so a truly-dark pair still reads as unconfident rather than as a
confident wrong bit. Above it, it can. That is the whole derivation, and it
is why the fraction is half of BIT_CONFIDENCE rather than a tuned number.

`DRIFT_FLOOR_LEVELS` is the other half of the honesty. A gate with no
absolute floor refuses on sensor noise in a dim frame, and a gate that
refuses everything is a wall — the same two-sided bar the marginal
resolution boundary is held to. Two grey levels is twice
`gray_code.MIN_BRIGHT_LEVELS`, the sensor's own quantisation.

IT IS THE SAME GATE AT EVERY WIRE RUNG AND UNDER EITHER MANUAL LEVER
(`spectra/services/capture_settings.py`, 2026-09-01). None of it is
free — each piece is a property of the design rather than a coincidence,
so it is written down:

  FRAME SIZE. A commissioning read now asks for 1920x1080 and settles for
  whatever rung the camera actually has. Nothing here is expressed in
  camera pixels of a particular frame: the background set is a QUANTILE
  (half the frame at every rung), the tile minimum is a FRACTION of a tile,
  and the bound is a fraction of `peak`, which is measured from the frames
  in hand. What IS bounded, deliberately, is how many pixels a level is
  taken over (`SAMPLE_PX`) — otherwise the gate would cost thirty-six times
  more at 1080p than at 320x180 for an answer that does not improve.

  GAIN. A manual gain scales the signal and the room together, so
  `drift / peak` is unchanged and the bound moves with it. Nothing to do.

  INTEGRATION TIME. This one genuinely changes the physics and the gate
  gets it right by measuring rather than assuming. A long exposure both
  averages the room's movement WITHIN a capture and — because the run
  widens its capture windows to keep averaging `MIN_FRAMES`
  (`commissioning.capture_window`) — puts MORE time between a pattern and
  its own inverse, which is more room for cloud to move in. The pair delta
  is measured on the frames that were actually taken, so a widened window
  that let more weather in is seen as more weather. The bound does not move
  because the bound is about what corrupts a bit, not about how long the
  shot took.

WHAT IT WILL NOT DO. It never refuses because it could not measure: a frame
whose background set is too small (`MIN_BACKGROUND_PX`) reports
`measurable=False` with a note, and the run carries on. "We could not check"
and "we checked and it was fine" are different facts — the same distinction
`witness.py` draws with `witness_unavailable` and `night_exit.py` draws
between DARK and UNKNOWN. And it never absorbs a failure it did not measure:
when the gate PASSES and the confident-wrong signature still appears, the
existing instrument-indicted fail stands exactly as it did, with a note
saying the ambient was measured steady so the fail is not explained by it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from spectra.services import gray_code

#: The dimmer fraction of `full - dark` that is taken as background. See the
#: module docstring for why this is a quantile and not a threshold.
BACKGROUND_QUANTILE = 0.5
#: Camera pixels the background set must hold before a level means
#: anything. RUNG-INDEPENDENT on purpose: `BACKGROUND_QUANTILE` makes the
#: set half the frame at every wire rung, so this is a guard against a
#: degenerate frame, never a knob that behaves differently at 1080p.
MIN_BACKGROUND_PX = 256
#: The regional grid. A window is a region, not a whole frame.
TILE_GRID = 4
#: A tile is reported only when this FRACTION of it is background — a
#: fraction rather than a count precisely so the rule means the same thing
#: at 320x180 and at 1920x1080 (`capture_settings.PROFILES`), where a tile
#: is 3,600 and 129,600 camera pixels respectively. What is being asked is
#: "is enough of this tile actually room", and that is a proportion.
MIN_TILE_BACKGROUND_FRACTION = 0.02
#: ...with an absolute floor under it for the smallest rung.
MIN_TILE_BACKGROUND_PX = 64

#: HOW MANY CAMERA PIXELS THE LEVELS ARE ACTUALLY TAKEN OVER, whole-frame
#: and per tile — the reason this gate costs the same at every rung.
#:
#: MEASURED before it was added: a median over the full background set costs
#: ~1.9 ms a capture at 320x180 and ~45 ms at 1920x1080, i.e. about a second
#: of the SPECTRA process's own event loop across a 23-capture pass, in
#: 45 ms blocks — the shape this codebase already knows to keep out of a
#: live loop. Bounded, it is a few milliseconds at every rung.
#:
#: IT COSTS NOTHING IN ACCURACY, and the reason is not the sample size but
#: that the SAME pixels are used for every capture in the pass: the two
#: levels being subtracted carry the identical sampling error, so it is
#: common-mode and cancels in the difference. (The size is generous anyway
#: — the standard error of a median over 20,000 samples is ~0.009 sigma,
#: three orders below `DRIFT_FLOOR_LEVELS`.)
SAMPLE_PX = 20_000
TILE_SAMPLE_PX = 4_000
#: Fixed, so two runs of the same pose measure the same pixels and a
#: reported drift is reproducible.
SAMPLE_SEED = 20260901

#: HALF of `gray_code.BIT_CONFIDENCE`, and the module docstring carries the
#: derivation: at this much drift, ambient alone reaches half the bar a bit
#: must clear to be believed, so it cannot manufacture a confident wrong
#: bit on its own. It is not a tuned number and lowering it does not make a
#: drifting room readable — it only stops the instrument saying so.
DRIFT_FRACTION_OF_PEAK = 0.10
#: The absolute floor, in grey levels: twice `gray_code.MIN_BRIGHT_LEVELS`,
#: the sensor's own quantisation. Without it a dim frame refuses on noise,
#: and a gate that refuses everything is a wall.
DRIFT_FLOOR_LEVELS = 2.0


def drift_bound(peak: float) -> float:
    """The bound this frame's own signal justifies. See the module
    docstring — `peak` is `gray_code.bright_and_lit`'s bright end, the same
    quantity `BIT_CONFIDENCE` is relative to."""
    return max(DRIFT_FLOOR_LEVELS, DRIFT_FRACTION_OF_PEAK * float(peak or 0.0))


def background_mask(dark: np.ndarray, full: np.ndarray, *,
                    quantile: float = BACKGROUND_QUANTILE) -> np.ndarray:
    """WHICH CAMERA PIXELS ARE NOT LOOKING AT THE COMPOSITION — chosen once,
    from the reference pair, and never recomputed.

    The dimmer `quantile` of `full - dark`. A constant shift of the whole
    frame does not reorder it, which is exactly the property a brightness
    threshold lacks and the reason this is a quantile."""
    bright = np.clip(np.asarray(full, dtype=np.float64)
                     - np.asarray(dark, dtype=np.float64), 0.0, None)
    if not bright.size:
        return np.zeros(bright.shape, dtype=bool)
    cut = float(np.quantile(bright, quantile))
    return bright <= cut


def _tile_slices(shape: tuple[int, int], grid: int):
    height, width = shape
    for ty in range(grid):
        y0, y1 = (ty * height) // grid, ((ty + 1) * height) // grid
        for tx in range(grid):
            x0, x1 = (tx * width) // grid, ((tx + 1) * width) // grid
            if y1 > y0 and x1 > x0:
                yield f"{tx},{ty}", (slice(y0, y1), slice(x0, x1))


def _draw(flat_indices: np.ndarray, limit: int, rng) -> np.ndarray:
    """A bounded, FIXED sample of a background set. Sorted, so the picked
    pixels are the same regardless of how numpy orders a choice."""
    if flat_indices.size <= limit:
        return flat_indices
    return np.sort(rng.choice(flat_indices, size=limit, replace=False))


def _sample_plan(mask: np.ndarray, *, grid: int = TILE_GRID
                 ) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """WHICH camera pixels every level in this pass is taken over — chosen
    ONCE, bounded, and then never changed. See `SAMPLE_PX`."""
    rng = np.random.default_rng(SAMPLE_SEED)
    height, width = mask.shape
    rows, cols = np.nonzero(mask)
    whole = _draw((rows * width + cols).astype(np.int64), SAMPLE_PX, rng)
    tiles: dict[str, np.ndarray] = {}
    for name, (ys, xs) in _tile_slices(mask.shape, grid):
        sub = mask[ys, xs]
        tile_px = int(sub.size)
        floor = max(MIN_TILE_BACKGROUND_PX,
                    int(tile_px * MIN_TILE_BACKGROUND_FRACTION))
        if int(sub.sum()) < floor:
            continue
        ty, tx = np.nonzero(sub)
        flat = ((ty + ys.start) * width + (tx + xs.start)).astype(np.int64)
        tiles[name] = _draw(flat, TILE_SAMPLE_PX, rng)
    return whole, tiles


def _levels(frame: np.ndarray, whole_idx: np.ndarray,
            tile_idx: dict[str, np.ndarray]
            ) -> tuple[float, dict[str, float]]:
    """The background level of one capture: the median over the sampled
    background set, whole-frame and per tile. A MEDIAN, not a mean — one
    hot pixel, or a fixture's spill leaking into a corner of the set, must
    not move it."""
    flat = np.asarray(frame, dtype=np.float64).reshape(-1)
    whole = (float(np.median(flat[whole_idx])) if whole_idx.size
             else float("nan"))
    return whole, {name: float(np.median(flat[idx]))
                   for name, idx in tile_idx.items() if idx.size}


@dataclass
class Reading:
    """One capture's ambient, and how far it has moved.

    `whole`/`regional` are against the OPENING DARK. `pair` is against the
    other half of this bit's pattern/inverse pair when there is one — the
    quantity that lands in the bit's own arithmetic."""
    label: str
    level: float
    tiles: dict[str, float] = field(default_factory=dict)
    whole: float = 0.0
    regional: float = 0.0
    worst_tile: str = ""
    pair: float = 0.0
    pair_regional: float = 0.0
    pair_label: str = ""
    #: TRUE when this capture was taken with the composition OFF, which is
    #: what makes its comparison against the opening dark gateable at all.
    lamp_free: bool = False
    exceeded: bool = False
    #: which comparison broke the bound, for the sentence
    kind: str = ""

    @property
    def drift(self) -> float:
        """The largest measured movement, whichever comparison it came
        from — including the ungated one, for the record."""
        return max(self.whole, self.regional, self.pair, self.pair_regional)

    @property
    def gated_drift(self) -> float:
        """The largest movement this reading was actually JUDGED on."""
        pair = max(self.pair, self.pair_regional)
        return (max(pair, self.whole, self.regional) if self.lamp_free
                else pair)

    def as_dict(self) -> dict:
        return {"label": self.label, "level": round(self.level, 3),
                "whole": round(self.whole, 3),
                "regional": round(self.regional, 3),
                "worst_tile": self.worst_tile,
                "pair": round(self.pair, 3),
                "pair_regional": round(self.pair_regional, 3),
                "pair_label": self.pair_label,
                "lamp_free": self.lamp_free,
                "exceeded": self.exceeded, "kind": self.kind}


@dataclass
class AmbientTrack:
    """The gate, held open across one gray-code stack.

    Opened on the stack's own reference pair; every later capture is handed
    to `observe`, which returns a `Reading` and says whether the stack is
    still readable. The caller refuses on the first `exceeded` — that is the
    check-before-the-cost half: a drifting pair mid-stack must not spend the
    rest of the room's dark time to reach a verdict about the weather."""
    peak: float = 0.0
    bound: float = DRIFT_FLOOR_LEVELS
    background_px: int = 0
    frame_px: int = 0
    measurable: bool = False
    note: str = ""
    baseline: float = 0.0
    baseline_tiles: dict[str, float] = field(default_factory=dict)
    #: how far the composition's own light reaches into the background set.
    #: Reported only — see the module docstring for why it is never gated.
    spill: float = 0.0
    readings: list[Reading] = field(default_factory=list)
    #: how many camera pixels each level is actually taken over — bounded,
    #: so this gate costs the same at 320x180 and at 1920x1080.
    sampled_px: int = 0
    tiles_tracked: int = 0
    _whole_idx: Optional[np.ndarray] = None
    _tile_idx: dict = field(default_factory=dict)

    @classmethod
    def open(cls, dark: np.ndarray, full: np.ndarray, *,
             lit_fraction: float = gray_code.LIT_FRACTION) -> "AmbientTrack":
        dark = np.asarray(dark, dtype=np.float64)
        _bright, _lit, peak, _floor = gray_code.bright_and_lit(
            dark, full, lit_fraction=lit_fraction)
        mask = background_mask(dark, full)
        count = int(mask.sum())
        track = cls(peak=float(peak), bound=drift_bound(peak),
                    background_px=count, frame_px=int(mask.size))
        if count < MIN_BACKGROUND_PX:
            track.note = (
                f"only {count} camera pixels of {mask.size} sit outside the "
                f"composition's own light, which is too few to measure the "
                f"room's ambient against — the ambient was NOT checked on "
                f"this stack.")
            return track
        # HOW FAR THE FIXTURE'S OWN LIGHT REACHES into the background set.
        # REPORTED, never a stand-down and never gated: it is exactly the
        # quantity the two gated comparisons are built to cancel, and
        # refusing on it would refuse a room whose fixture lights the walls.
        bright = np.clip(np.asarray(full, dtype=np.float64) - dark, 0.0, None)
        track.spill = float(np.median(bright[mask]))
        track._whole_idx, track._tile_idx = _sample_plan(mask)
        track.sampled_px = int(track._whole_idx.size)
        track.tiles_tracked = len(track._tile_idx)
        track.measurable = True
        track.baseline, track.baseline_tiles = _levels(
            dark, track._whole_idx, track._tile_idx)
        # THE OPENING DARK IS THE BASELINE AND IS ALSO A READING, so a run
        # that never drifts still carries a row saying what was measured
        # rather than an empty list that reads as "not checked".
        track.readings.append(Reading(label="dark", level=track.baseline,
                                     lamp_free=True))
        return track

    def observe(self, label: str, frame: np.ndarray, *,
                pair_with: Optional[Reading] = None,
                lamp_free: bool = False) -> Reading:
        """One capture, measured. Returns the reading; the caller decides
        what to do with `exceeded`.

        `lamp_free` says the composition was OFF for this capture (the
        opening and closing dark references). Only then is the comparison
        against the opening dark gated — see the module docstring."""
        if not self.measurable or self._whole_idx is None:
            return Reading(label=label, level=float("nan"),
                           lamp_free=lamp_free)
        level, tiles = _levels(frame, self._whole_idx, self._tile_idx)
        reading = Reading(label=label, level=level, tiles=tiles,
                          lamp_free=lamp_free)
        reading.whole = abs(level - self.baseline)
        for name, value in tiles.items():
            base = self.baseline_tiles.get(name)
            if base is None:
                continue
            delta = abs(value - base)
            if delta > reading.regional:
                reading.regional, reading.worst_tile = delta, name
        if pair_with is not None and pair_with.tiles is not None:
            reading.pair_label = pair_with.label
            reading.pair = abs(level - pair_with.level)
            for name, value in tiles.items():
                other = pair_with.tiles.get(name)
                if other is None:
                    continue
                reading.pair_regional = max(reading.pair_regional,
                                            abs(value - other))
        # ONLY THE LAMP-FREE COMPARISONS ARE GATED, and the order names the
        # strictest true thing first: a pair delta is the quantity that
        # lands in the bit's own arithmetic, so when both are broken it is
        # the one the sentence should describe.
        checks = [(reading.pair, "pair"),
                  (reading.pair_regional, "pair_regional")]
        if lamp_free:
            # WHOLE BEFORE REGIONAL, so a room-wide change reads as
            # room-wide. A uniform shift makes both true and equal, and
            # "strongest in one corner (tile 0,0)" would then be a
            # misleading sentence about a change that was everywhere. A
            # genuine corner never breaks the whole-frame median, so it
            # still falls through to `regional`.
            checks += [(reading.whole, "whole"),
                       (reading.regional, "regional")]
        for value, kind in checks:
            if value > self.bound:
                reading.exceeded, reading.kind = True, kind
                break
        self.readings.append(reading)
        return reading

    @property
    def worst(self) -> Optional[Reading]:
        """The reading that moved most BY A GATED COMPARISON. A lamp-on
        capture's distance from the opening dark is reported per reading but
        never ranked here — it carries the fixture's own spill, and a
        `max_drift` nobody was judged against is a number that misleads."""
        real = [r for r in self.readings if r.tiles or r.label == "dark"]
        return max(real, key=lambda r: r.gated_drift) if real else None

    def as_dict(self) -> dict:
        worst = self.worst
        return {"measurable": self.measurable, "note": self.note,
                "bound": round(self.bound, 3), "peak": round(self.peak, 3),
                "fraction_of_peak": DRIFT_FRACTION_OF_PEAK,
                "floor_levels": DRIFT_FLOOR_LEVELS,
                "background_px": self.background_px,
                "frame_px": self.frame_px, "spill": round(self.spill, 3),
                "sampled_px": self.sampled_px,
                "tiles_tracked": self.tiles_tracked,
                "baseline": round(self.baseline, 3),
                "captures": len(self.readings),
                "max_drift": round(worst.gated_drift, 3) if worst else 0.0,
                "max_seen": round(max((r.drift for r in self.readings),
                                      default=0.0), 3),
                "worst": worst.as_dict() if worst else {},
                "exceeded": any(r.exceeded for r in self.readings),
                "readings": [r.as_dict() for r in self.readings]}
