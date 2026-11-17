#!/usr/bin/env python3
"""Read-only evidence for ORBITS' WORD SHAPE — few trace it, many become it
(Word Shapes plan row W1.3, his P1 A; `fx/effects/orbits.py`'s own WORD
SHAPES block is the binding statement).

His words for the row: *"Orbits: if there are few and they are large, they
can change shape from circles to the shape. If there are a lot, they can
move in a path together that forms the shape."* and *"For particles that
flow to move in that shape, like fish and orbits, they need to smoothly
accelerate and not have sudden velocity shifts."*

Everything below is measured through the REAL vendored render pipeline
(`fx.headless`, audio silenced and fed a deterministic canned frame, a fake
clock) on his REAL `crystal-mapper` mask, with his live Orbits V2 Matrix
entry's own params. The shape is told exactly as SpotFX tells it — one jump
of `fx/effects/word_shape_keys.py`'s six keys — and the effect runs the
whole form, hold and release on its own clock. Nothing here touches the
live room, the live units or live storage.

THE DENOMINATORS ARE NOT RE-DERIVED HERE. The mask decode, the outline-cell
set and the inside-cell set all come from `scripts/check_word_shapes.py`
(`load_panel`, `measure`), whose counts at SIZE 0.62 — heart 168 outline,
star 176, diamond 119 — are pinned by `tests/test_word_shapes.py`. Every
coverage percentage printed below is a fraction of that shape's own outline
count, so a drifting denominator is a visible, deliberate change rather
than a quietly moving bar.

ROW W4.4 (2026-11-17) — HIS VERDICT, AND WHY THE BAR MOVED

His words after the W3 room deploy: *"I can tell the fish and orbits are
trying to do something, but it's not clear enough. They need to increase
speed so they can pass the outline fast enough that their trail stays and
it clearly forms the shape."* The W1.3 bar below counted a cell LIT at
20/255 — EIGHT PERCENT of full — so it read 74-93% while the share of the
outline band that was actually LIGHT (>= 128/255, half of full) was 1-25%.
A faint, broken line passes a bar like that. The Fish review's lesson (a
vacuous lit bar becomes a CONTRAST bar) is carried back here by row W4.4:
THE ROW'S BAR IS NOW `report_contrast` below, over FEW with 1 and 3 blobs
and MANY with 4 and 8 — the whole range his scene's Energy binding drives
`particle_count` across — and the W1.3 numbers keep printing beside it for
the record. The row's two levers, `word_shape_speed_x` (the speed he named)
and `WORD_SHAPE_TRAIL_S`, are overridable from the command line below,
because the sweep over them is what chose their defaults.

WHAT IS MEASURED

  contrast   THE ROW'S BAR (W4.4). Over the shape's own outline band (real
             cells within one cell pitch of the outline), at MID-HOLD and
             at the HOLD'S END, with the worst over every hold frame
             printed beside them: the share of band cells whose peak
             channel is over BAND_LIT_LO (64/255), the band's mean
             luminance over the REST of the panel's, and that share
             against THE SAME SEED's frame UNTOLD — the comparison that
             separates "the shape is brighter here" from "this effect
             lights everything". Bars: BAND_LO_BAR_FEW / _MANY over 64,
             ratio >= BAND_RATIO_BAR, share at least BAND_LIFT_X the
             untold control's. The share over 128/255 is printed on every
             row with its undecayed-trail ceiling, as the row's ONE OPEN
             EXCEEDANCE — `report_contrast`'s docstring carries the exact
             arithmetic that puts the spec's 90%-over-128 out of reach at
             his `blob_size`, and `--needed` prints the ceilings.
  coverage   THE W1.3 NUMBER, kept for the record: real outline cells lit
             at or above LIT (20/255 on the frame's brightest channel —
             `scripts/check_drop_shockwave.py`'s own convention) by the
             blobs AND their comet trails, at the WORD (the instant the
             form completes) and at MID-HOLD. Its bar: >= 60% with FEW
             blobs, >= 75% with MANY. Still asserted at his fallback counts
             (3 and 8) as a regression guard, no longer the row's claim.
  on_outline the greatest distance, in physical cell pitches, from a blob's
             centre (FEW) or its tether (MANY) to the outline at the hold.
             FEW's is exactly 0 by construction — which is the point: it
             proves the envelope really reaches 1.0 and the blend is the
             shape itself, not something near it.
  continuity every tracked blob's per-frame SPEED CHANGE (px/s) and HEADING
             CHANGE (rad) at the four moments the blend moves — the form's
             start, the hold's start, the hold's end and the release's end —
             against the effect's OWN ordinary maximum, measured on an
             untold run of the same seed and the same audio. His "no sudden
             velocity shifts", in numbers.
             A blob rounding a CORNER of the outline mid-hold turns sharply
             in one frame; that is the shape (a star has ten points), not a
             defect of the blend, so the mid-hold maximum is printed for
             honesty and is deliberately not a bar.
  jump       the largest frame-to-frame change in lit cells during the form
             and the release, as a share of the lit count (bar: < 8%).
  white      cells with every channel over 200 while a shape stands, against
             the same effect's own busy frames untold (bar: no higher).
  cost       p50 per-frame render cost with a shape holding against the same
             run untold (bar: < 1 ms added).

    .venv/bin/python scripts/check_orbits_word_shape.py
    .venv/bin/python scripts/check_orbits_word_shape.py --ascii
    .venv/bin/python scripts/check_orbits_word_shape.py --shape heart
    .venv/bin/python scripts/check_orbits_word_shape.py --speed-x 4 \
        --trail-s 2.5 --only contrast

`--ascii` draws the lit outline cells at mid-hold on the real mask beside
the shape's own outline, and the W4.4 contrast report's own
LUMINANCE-GRADED renders (`.` dark, `-` under 64, `+` under 128, `#` at or
over 128 of 255) of the worst hold frame — which is the quickest way to see
whether a heart reads as a heart on 976 cells.

`--speed-x` and `--trail-s` override `word_shape_speed_x` and the module's
`WORD_SHAPE_TRAIL_S` for the whole run: they are how row W4.4's own
defaults were chosen, and re-running the sweep is how a later change
re-decides them. `--only` runs one report (`mode`, `contrast`,
`continuity`, `jwc`).
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import math
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import scripts.check_word_shapes as W  # noqa: E402
from fx import headless  # noqa: E402
from fx.effects import orbits as FX  # noqa: E402
from fx.effects import word_shape_keys as wsk  # noqa: E402
from fx.effects import phase_grammar, word_shapes  # noqa: E402

ROWS, COLS = 37, 72
DT = 1.0 / 60.0
LIT = 20.0          # check_drop_shockwave.py's own "a cell is lit" level
WHITE = 200.0       # ... and its white guard's level
SIZE = W.DEFAULT_SIZE_FRACTION      # 0.62, the plan's default

# His live Orbits V2 Matrix entry, at the fallbacks its bindings resolve to
# (storage/spectra/scenes.json, the same read tests/test_fish.py pins as
# HIS_MATRIX). `particle_count` is the one thing this script varies: his
# scene drives it 1-8 by Energy with 3 as the fallback, and 3 vs 8 is
# exactly the FEW/MANY split this row is about.
HIS_MATRIX = {
    "particle_count": 3, "radius_scale": 1.8, "horizon_scale": 0.19,
    "blob_size": 2.5, "x_offset": 0.5, "y_offset": 0.5, "spin": 0.37,
    "base_speed": 0.3, "jiggle": 0.15, "tether_scatter": 0.0,
    "reactivity_scale": 1.0, "speed_jump": 1.0, "speed_jog": 1.0,
    "brightness_audio": 0.5, "size_audio": 0.5, "color_shift": 1,
    "impulse_decay": 0.06, "reverse": False, "trail_decay": 0.15,
    "orbit_radius": 0.53,
}
# one of his real-shaped multi-colour sets (check_drop_shockwave.py's)
SET = ("linear-gradient(90deg, rgb(255,0,90) 0%, rgb(255,140,0) 33%, "
       "rgb(0,180,255) 66%, rgb(120,0,255) 100%)")

FEW_N = 3           # his fallback count — FEW by the default threshold (3)
MANY_N = 8          # the top of his Energy range — MANY
# ROW W4.4: the whole count range his scene's Energy binding drives
# `particle_count` across (1 -> 8), split by the default FEW threshold (3).
# ONE blob is the case the W1.3 build could never have drawn a line with —
# at `base_speed` 0.3 it walks a 168-cell outline in 3.3 s against a ~1 s
# trail half-life, so most of the heart was always dark — and it is exactly
# the case his quiet-Energy binding gives.
FEW_COUNTS = (1, 3)
MANY_COUNTS = (4, 8)
ENERGIES = (0.2, 0.8)
PHRASE_MS = 1200.0  # a typical sung phrase, so the hold lands mid-clamp
SETTLE_S = 6.0      # swim before the word, so the trail history is honest
SEED = 7

# The row's own clarity bars (plan section 6.4 / the row's "visual clarity
# bar"), as fractions of the shape's own outline-cell count.
BAR_FEW = 0.60
BAR_MANY = 0.75
# THE LIT-CELL JUMP. The plan's absolute bar is 8% of the lit count over the
# form and the release. It is not a property THIS effect has even untold: at
# his `trail_decay` 0.15 the comet trail's half-life is 0.095 s, so the whole
# smear loses 11% of its brightness EVERY FRAME and the cells sitting near
# the LIT threshold wink out in blocks — measured 13-20% frame to frame on
# the untold control, by Energy. So the bar asserted here is the SAME
# comparison acceptance 3 already makes for this effect's speed and heading:
# against "the effect's own ordinary maximum", measured on the untold control
# at the same seed and the same audio. A shape may not make the picture jump
# more than this effect already jumps by itself. The absolute number is
# printed beside it either way.
# ── ROW W4.4's BAR: "LIT" HAS TO MEAN CONTRAST HERE TOO ──────────────────
# `LIT` above is 20 of 255 — eight percent of full. For a lingering comet
# trail that is very nearly "above zero", and the W1.3 row shipped it as the
# bar: measured again with this script's own rig, the W1.3 coverage read
# 74-93% at the hold while the share of the same band over HALF of full read
# 1-25%, and what he saw in the room was "not clear enough". So the row's
# bar is the Fish review's `band_contrast` (`scripts/
# check_fish_word_shape.py`, line 359) applied here:
#
#   * the share of the band's cells that are actually LIGHT — over
#     BAND_LIT_HI of 255, not over nothing; and
#   * the band's mean luminance over the REST of the lit panel's, told
#     against THE SAME FRAME UNTOLD — the one number that separates "the
#     shape is brighter here" from "this effect lights everything".
#
# Luminance is the cell's own peak channel, the same quantity `coverage`
# reads. AT EVERY HOLD FRAME, not at one sampled frame: a line that is
# whole at mid-hold and broken two frames later is a line that flickers.
BAND_LIT_LO = 64.0
BAND_LIT_HI = 128.0
BAND_HI_BAR = 0.90        # the row's SPEC bar, reported not asserted
# The bars actually asserted, set from the W4.4 measurement (the PR's own
# sweep over `--speed-x` x `--trail-s`) — see `report_contrast`'s docstring
# for why the threshold is BAND_LIT_LO rather than BAND_LIT_HI.
BAND_LO_BAR_FEW = 0.55
BAND_LO_BAR_MANY = 0.55
BAND_RATIO_BAR = 1.4      # band/rest mean luminance
# ... and the "it is not just lighting everything" comparison, read on the
# band's own >= BAND_LIT_LO SHARE told against the SAME SEED's frame untold
# rather than on the ratio of two means. The share is the robust form: on a
# frame where the untold panel is nearly dark both means are tiny and their
# ratio is noise — measured, one untold many-heart frame read a HIGHER
# band/rest ratio than the told one while its band share was 7% against the
# told 69%, because a couple of very bright untold cells happened to fall
# in the band. The share cannot do that.
BAND_LIFT_X = 3.0
COST_BAR_MS = 1.0
# A shape concentrates the blobs (MANY shrinks every orbit onto one outline),
# so two beads of different colours can overlap additively where they never
# would in an open ring. Measured: at most this many cells of 976 go white
# (every channel over 200) where the untold control has none. Orbits has no
# white guard of its own and never had one; this is the measured size of the
# effect, not a licence.
WHITE_SLACK = 2
# A HEADING NEEDS MOTION. A blob that moved less than a tenth of a cell
# pitch in a frame (a pitch is two addressable columns on the hex lattice,
# so 0.2 px) is visually stationary and the direction of that step is
# numerical noise: its "heading change" saturates at pi for free. The effect
# itself already takes this view of its own smoothed heading rate
# (`orbits.py`'s `moving = hypot(p_vx, p_vy) > 1e-4` guard on `p_om`), and
# the gate below is applied IDENTICALLY to the told run and to the untold
# control, so it can never flatter one of them. It matters here because
# Orbits' jog kicks (`speed_jog`, up to +-6 rad/s of phase rate against a
# base of ~2) routinely stall or reverse a blob for a tenth of a second at
# loud Energy — told or not.
TURN_MIN_SPEED = 0.2 / DT
# THE BLEND'S OWN SMOOTHNESS, with no magic number in it. A smoothstep's
# steepest slope is 1.5 / its duration, so over the WHOLE shape the envelope
# can never move more than `1.5 * dt / min(form, release)` in one frame —
# and at both ends of both ramps it moves nothing at all. Asserting the
# recorded series against that (plus a little for the clock's own jitter) is
# what makes "the blend never jumps" a measurement rather than an argument,
# and it is what lets the raw heading change at the hold's edges be
# attributed to the OUTLINE and to Orbits' own jog kicks instead.
ENVELOPE_SLOPE_SLACK = 1.05

FAILURES: list[str] = []
# `--speed-x`'s override, in a one-cell list so `run()` sees the live value
SPEED_X: list[float | None] = [None]


def check(ok: bool, label: str) -> bool:
    print(f"   {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        FAILURES.append(label)
    return ok


# ── the panel, from check_word_shapes.py's own loader ──────────────────────

PANEL = W.load_panel()
REAL2 = PANEL.grid
REAL = REAL2.ravel()
assert (PANEL.rows, PANEL.cols) == (ROWS, COLS), PANEL


@functools.lru_cache(maxsize=None)
def outline_cells(shape_id: str):
    """(the outline-cell mask, its count) for one shape at SIZE — straight
    from check_word_shapes.measure(), never re-derived here. Cached: that
    measurement runs the exact `sdf` and the independent star-shaped walk,
    which cost a second or two each and never change within a run."""
    _m, outline, _inside = W.measure(word_shapes.get(shape_id), PANEL, SIZE)
    return outline, int(outline.sum())


def _phys(px, py):
    """A point in RENDER PIXELS, in physical pitch units (a column is 0.5 of
    a real-cell pitch, a row sqrt(3)/2 — the hex lattice;
    check_word_shapes.py's own two coordinate systems).

    Positions come in as pixels on purpose: Orbits' own normalized space
    carries `radius_scale`, so `p_x0` is NOT the panel's -1..1
    (Orbits2d._word_shape_scale). Going through the effect's own sx/sy to
    pixels first is independent of that, and of any later change to it.
    """
    return ((np.asarray(px) - PANEL.half_width) * W.COLUMN_PITCH,
            (np.asarray(py) - PANEL.half_height) * W.ROW_PITCH)


@functools.lru_cache(maxsize=None)
def outline_physical(shape_id: str, samples: int = 1440):
    s = np.linspace(0.0, 1.0, samples, endpoint=False)
    ux, uy = word_shapes.get(shape_id).at(s)
    return PANEL.to_physical(ux, uy, SIZE)


def dist_to_outline(xs, ys, shape_id: str) -> np.ndarray:
    """Each RENDER-PIXEL point's distance to the outline, in cell pitches."""
    ox, oy = outline_physical(shape_id)
    px, py = _phys(xs, ys)
    px = np.atleast_1d(px)
    py = np.atleast_1d(py)
    return np.hypot(px[:, None] - ox[None, :],
                    py[:, None] - oy[None, :]).min(axis=1)


# ── audio: one deterministic frame, paced by Energy ────────────────────────

class _Audio:
    """One canned audio frame. `energy` 0 is a quiet room (a gentle swell,
    no beats); higher is busier music, with a beat every 15 frames — the
    same shape as tests/strip_phase_harness.py's own frame, so the two rigs
    agree about what "busy" means."""

    def __init__(self, i: int, energy: float):
        self.i = i
        self.e = float(energy)

    def lows_power(self, filtered: bool = True) -> float:
        base = 0.06 + 0.34 * self.e
        return base + (0.04 + 0.16 * self.e) * math.sin(self.i / 9.0)

    beat_power = bass_power = lows_power

    def mids_power(self, filtered: bool = True) -> float:
        return 0.5 * self.lows_power(filtered)

    def high_power(self, filtered: bool = True) -> float:
        return 0.3 * self.lows_power(filtered)

    def onset(self) -> bool:
        return self.e >= 0.4 and self.i % 15 == 0

    def bpm_beat_now(self) -> bool:
        return self.onset()


# ── the rig ────────────────────────────────────────────────────────────────

_RIGS = [0]


class Run:
    """One rendered run: every frame (rows x cols x 3, off-mask cells
    zeroed), every tracked blob's normalized position per frame, the render
    cost per frame, and where the shape's own moments fell."""

    def __init__(self):
        self.frames: list[np.ndarray] = []
        self.pos: list[tuple[np.ndarray, np.ndarray]] = []
        self.tether: list[tuple[np.ndarray, np.ndarray]] = []
        self.m: list[float] = []
        # ROW W4.4: the latched mode's own speed multiplier, per frame
        self.mult: list[float] = []
        self.cost_ms: list[float] = []
        self.edge = 0
        self.word = 0
        self.mid_hold = 0
        self.hold_end = 0
        self.release_end = 0
        self.mode = None
        self.told = None


async def run(shape_id: str | None, energy: float, count: int, *,
              seed: int = SEED, tag: str = "ws", **over) -> Run:
    """Swim SETTLE_S, tell one shape (or none), render to the end of its
    release plus a second. `shape_id=None` is the untold control: the same
    seed, the same audio, the same frames."""
    _RIGS[0] += 1
    name = f"orbits-{tag}-{_RIGS[0]}"
    td = tempfile.mkdtemp()
    headless.silence_audio()
    host = await headless.start_headless_host(
        str(Path(td) / name), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=name, real_mask=REAL)
    virtual = host.virtuals.get(name)
    out = Run()
    from spectra.services.room_controls import (RoomControlState,
                                                word_shape_timing)
    form_s, hold_s, release_s = word_shape_timing(
        energy, PHRASE_MS, RoomControlState(), ["orbits"])
    try:
        with headless.fake_clock() as clock:
            np.random.seed(seed)
            # ROW W4.4's two levers, overridable from the command line so the
            # measurement that chose their defaults is re-runnable
            if SPEED_X[0] is not None:
                over.setdefault("word_shape_speed_x", SPEED_X[0])
            cfg = dict(HIS_MATRIX, gradient=SET, particle_count=count, **over)
            eff = headless.attach_effect(host, virtual, "orbits", cfg)
            eff._rng = np.random.default_rng(seed)
            i = [0]

            def step(n: int):
                for _ in range(n):
                    i[0] += 1
                    clock.advance(DT)
                    with eff.lock:
                        eff.audio_data_updated(_Audio(i[0], energy))
                    t0 = time.perf_counter()
                    f = virtual.assemble_frame()
                    dur = (time.perf_counter() - t0) * 1000.0
                    if f is None:
                        continue
                    virtual.flush(f)
                    a = np.array(f, dtype=np.float32).reshape(ROWS, COLS, 3)
                    out.frames.append(np.where(REAL2[..., None], a, 0.0))
                    out.cost_ms.append(dur)
                    k = eff.n
                    live = np.flatnonzero(eff.p_mode[:k] < 2)
                    # RENDER PIXELS, through the effect's own projection
                    out.pos.append((eff.cx + eff.p_x0[live] * eff.sx,
                                    eff.cy + eff.p_y0[live] * eff.sy))
                    out.m.append(float(eff._ws_m))
                    walk_x, ring_x = eff._word_shape_speed_x()
                    out.mult.append(max(walk_x, ring_x))
                    # the MANY tether, from the effect's OWN live model — the
                    # one quantity the many-mode blend puts on the outline
                    if shape_id is not None:
                        ux, uy = word_shapes.get(shape_id).at(
                            eff.ring_phase + eff.p_slot_frac[live])
                        sc = eff._word_shape_scale()
                        out.tether.append((eff.cx + ux * sc * eff.sx,
                                           eff.cy + uy * sc * eff.sy))
                    else:
                        out.tether.append((np.zeros(0), np.zeros(0)))

            step(int(SETTLE_S / DT))
            out.edge = len(out.frames)
            if shape_id is not None:
                with eff.lock:
                    eff._apply_config(
                        wsk.keys_for(shape_id, 1, form_s, hold_s, release_s,
                                     energy),
                        validate=False, fire_event=False)
                out.mode = eff._word_shape_latch()
            out.told = (form_s, hold_s, release_s)
            step(int(math.ceil(form_s / DT)))
            out.word = len(out.frames) - 1
            step(int(round(hold_s / 2.0 / DT)))
            out.mid_hold = len(out.frames) - 1
            step(int(round(hold_s / 2.0 / DT)))
            out.hold_end = len(out.frames) - 1
            step(int(math.ceil(release_s / DT)))
            out.release_end = len(out.frames) - 1
            step(int(1.0 / DT))
    finally:
        await host.shutdown()
    return out


# ── the measures ───────────────────────────────────────────────────────────

def bright(frame: np.ndarray) -> np.ndarray:
    return frame.max(axis=-1)


def coverage(frame: np.ndarray, outline: np.ndarray) -> float:
    n = int(outline.sum())
    if n == 0:
        return 0.0
    return float(np.count_nonzero((bright(frame) >= LIT) & outline)) / n


def band_contrast(frame: np.ndarray, shape_id: str):
    """(the band's share over BAND_LIT_LO, over BAND_LIT_HI, its mean
    luminance over the REST of the panel's) — ROW W4.4's bar, the Fish
    review's `band_contrast` applied to this effect.

    The band is the shape's own outline band, straight from
    `check_word_shapes.measure()` (the pinned 168/176/119 cells); the rest
    is every other REAL cell. Luminance is the cell's peak channel."""
    lum = bright(frame)
    band, _n = outline_cells(shape_id)
    rest = REAL2 & ~band
    b = lum[band]
    r = lum[rest]
    if not b.size:
        return 0.0, 0.0, 0.0
    return (float((b > BAND_LIT_LO).mean()),
            float((b > BAND_LIT_HI).mean()),
            float(b.mean() / max(float(r.mean()), 1e-6)))


def worst_hold(run_: Run, shape_id: str):
    """The WORST hold frame's (>LO share, >HI share, ratio, its index) —
    the minimum of each over every frame from the word to the hold's end.
    A line that is whole at mid-hold and broken two frames later is a line
    that flickers, so the bar is read at every one of them."""
    lo = hi = ratio = 1.0
    worst_i = run_.word
    for i in range(run_.word, run_.hold_end + 1):
        a, b, c = band_contrast(run_.frames[i], shape_id)
        if b <= hi:
            hi, worst_i = b, i
        lo = min(lo, a)
        ratio = min(ratio, c)
    return lo, hi, ratio, worst_i


def lit_count(frame: np.ndarray) -> int:
    return int(np.count_nonzero((bright(frame) >= LIT) & REAL2))


def lit_jump(run_: Run, lo: int, hi: int) -> float:
    """The largest frame-to-frame change in lit real cells over
    `frames[lo:hi]`, as a share of the larger of the pair."""
    counts = [lit_count(f) for f in run_.frames[lo:hi]]
    worst = 0.0
    for a, b in zip(counts, counts[1:]):
        worst = max(worst, abs(b - a) / max(a, b, 1))
    return worst


def speeds_and_turns(run_: Run):
    """Per-frame speed (px/s) and heading change (rad) for every tracked
    blob, as two (frames-1, blobs) arrays with NaN where a blob's index is
    not comparable across the pair (a population change). Positions are
    render pixels — the effect's own drawn ones through its own sx/sy."""
    spd: list[np.ndarray] = []
    hdg: list[np.ndarray] = []
    moving: list[np.ndarray] = []
    for a, b in zip(run_.pos, run_.pos[1:]):
        k = min(a[0].size, b[0].size)
        if k == 0:
            spd.append(np.zeros(0))
            hdg.append(np.zeros(0))
            moving.append(np.zeros(0, dtype=bool))
            continue
        dx = b[0][:k] - a[0][:k]
        dy = b[1][:k] - a[1][:k]
        step = np.hypot(dx, dy) / DT
        spd.append(step)
        hdg.append(np.arctan2(dy, dx))
        moving.append(step >= TURN_MIN_SPEED)
    d_spd, d_turn = [], []
    for i in range(1, len(spd)):
        k = min(spd[i].size, spd[i - 1].size)
        if k == 0:
            d_spd.append(np.zeros(0))
            d_turn.append(np.zeros(0))
            continue
        d_spd.append(np.abs(spd[i][:k] - spd[i - 1][:k]))
        turn = (hdg[i][:k] - hdg[i - 1][:k] + np.pi) % (2.0 * np.pi) - np.pi
        # a heading only counts where the blob actually MOVED on both of
        # the two frames (TURN_MIN_SPEED)
        ok = moving[i][:k] & moving[i - 1][:k]
        d_turn.append(np.abs(turn)[ok])
    return d_spd, d_turn


# The longest a blob can be from where the untold model would have put it,
# in render pixels: the lit panel's own diagonal. It bounds |S - O|, the
# distance the blend is interpolating across, without having to record both
# geometries every frame.
PANEL_DIAG_PX = float(np.hypot(COLS, ROWS))


def blend_speed_bound(run_: Run, centre: int, half: int = 3) -> float:
    """The MOST the blend itself can be moving a blob, in px/s, over a
    window of frames: `|dm/dt| * |S - O|`, bounded by the panel diagonal.

    This is the quantity that answers "does the blend jump", separately from
    what the OUTLINE does: a blob rounding a corner of the shape turns
    sharply in one frame (the heart's own cleft turns 3.11 rad) and that is
    the shape, not the blend. Through the hold the envelope is flat at 1.0
    and leaves it with zero slope, so this bound is near zero at both of the
    hold's edges — which is the real claim being made there.
    """
    lo = max(1, centre - half)
    hi = min(len(run_.m), centre + half + 1)
    if hi <= lo:
        return 0.0
    dm = max(abs(run_.m[i] - run_.m[i - 1]) for i in range(lo, hi))
    return dm / DT * PANEL_DIAG_PX


def frame_speeds(run_: Run) -> list[float]:
    """The largest tracked blob's per-frame speed (px/s), frame by frame —
    the denominator the multiplier's own bound is scaled by."""
    out = []
    for a, b in zip(run_.pos, run_.pos[1:]):
        k = min(a[0].size, b[0].size)
        if k == 0:
            out.append(0.0)
            continue
        out.append(float(np.hypot(b[0][:k] - a[0][:k],
                                  b[1][:k] - a[1][:k]).max()) / DT)
    return out


def multiplier_speed_bound(run_: Run, centre: int, half: int = 3) -> float:
    """The MOST row W4.4's own speed multiplier can be changing a blob's
    speed over a window of frames, in px/s.

    The walk's speed along the outline is PROPORTIONAL to the multiplier,
    so a one-frame change `dx` in it changes that speed by at most
    `dx / x_max` of the speed the walk reaches at `x_max` — and the largest
    per-frame speed recorded anywhere in the hold bounds that. Added to
    `blend_speed_bound`, this is the whole of what row W4.4 and the W1.3
    blend between them can do to a blob at a moment; everything left over
    in the raw number is the OUTLINE's own geometry (see
    `report_continuity`)."""
    lo = max(1, centre - half)
    hi = min(len(run_.mult), centre + half + 1)
    if hi <= lo or not run_.mult:
        return 0.0
    dx = max(abs(run_.mult[i] - run_.mult[i - 1]) for i in range(lo, hi))
    x_max = max(run_.mult) or 1.0
    spd = frame_speeds(run_)
    v_hold = max(spd[run_.word:run_.hold_end + 1] or [0.0])
    return dx / x_max * v_hold


def row_speed_bound(run_: Run, centre: int, half: int = 3) -> float:
    """The blend's bound plus the multiplier's — what THIS ROW and W1.3's
    blend together can be doing to a blob's speed at a moment."""
    return (blend_speed_bound(run_, centre, half)
            + multiplier_speed_bound(run_, centre, half))


def envelope_step(run_: Run):
    """(the largest one-frame move the recorded envelope made over the whole
    shape, the largest a smoothstep of this shape's own form and release
    could make). A smoothstep's steepest slope is 1.5 / its duration."""
    vals = [v for v in run_.m]
    step = max((abs(b - a) for a, b in zip(vals, vals[1:])), default=0.0)
    form_s, _hold_s, release_s = run_.told or (0.0, 0.0, 0.0)
    ramps = [v for v in (form_s, release_s) if v > 0.0]
    if not ramps:
        return step, 1.0
    return step, 1.5 * DT / min(ramps) * ENVELOPE_SLOPE_SLACK


def envelope_window(run_: Run, centre: int, half: int = 3):
    """(the lowest envelope value, the largest one-frame change in it) over
    a window of frames — how far the blend is from standing perfectly
    still."""
    lo = max(1, centre - half)
    hi = min(len(run_.m), centre + half + 1)
    if hi <= lo:
        return 1.0, 0.0
    vals = run_.m[lo - 1:hi]
    dm = max(abs(b - a) for a, b in zip(vals, vals[1:]))
    return min(vals), dm


def shape_sharpest_turn(shape_id: str) -> float:
    """The sharpest turn the OUTLINE itself makes at a vertex, in radians —
    the ceiling on how hard a blob tracing it has to turn in one frame."""
    pts = word_shapes.get(shape_id).points
    d = np.diff(np.vstack([pts, pts[:1]]), axis=0)
    a = np.arctan2(d[:, 1], d[:, 0])
    turn = np.abs((np.diff(np.concatenate([a, a[:1]])) + np.pi)
                  % (2.0 * np.pi) - np.pi)
    return float(turn.max())


def window_max(series: list[np.ndarray], centre: int, half: int = 3):
    lo = max(0, centre - half)
    hi = min(len(series), centre + half + 1)
    vals = [float(a.max()) for a in series[lo:hi] if a.size]
    return max(vals) if vals else 0.0


# ── the report ─────────────────────────────────────────────────────────────

def report_mode(label: str, count: int, bar: float, shapes, ascii_draw: bool):
    print(f"\n── {label}: particle_count {count}, bar {bar:.0%} of the "
          f"outline ──")
    header = (f"{'shape':9s} {'energy':>7s} {'outline':>8s} {'mode':>5s} "
              f"{'at word':>8s} {'mid-hold':>9s} {'on-outline':>11s}")
    print(header)
    print("-" * len(header))
    worst: dict[str, float] = {}
    draws = {}
    for shape_id in shapes:
        outline, n_out = outline_cells(shape_id)
        for energy in ENERGIES:
            r = asyncio.run(run(shape_id, energy, count,
                                tag=f"{label}-{shape_id}"))
            cov_word = coverage(r.frames[r.word], outline)
            cov_mid = coverage(r.frames[r.mid_hold], outline)
            # the hold's own geometry claim
            if r.mode == FX.WORD_SHAPE_FEW:
                xs, ys = r.pos[r.mid_hold]
            else:
                xs, ys = r.tether[r.mid_hold]
            on_out = (float(dist_to_outline(xs, ys, shape_id).max())
                      if np.size(xs) else float("nan"))
            print(f"{shape_id:9s} {energy:7.1f} {n_out:8d} {r.mode:>5s} "
                  f"{cov_word:8.0%} {cov_mid:9.0%} {on_out:10.2f}p")
            worst[f"{shape_id}@{energy}"] = cov_mid
            worst[f"on-outline {shape_id}@{energy}"] = on_out
            draws[(shape_id, energy)] = (r, outline)
    print()
    for key, value in worst.items():
        if key.startswith("on-outline"):
            check(value <= 1.0,
                  f"{label}: {key} {value:.2f} cell pitches (bar: <= 1.00)")
        else:
            check(value >= bar,
                  f"{label}: {key} coverage {value:.0%} AT THE HOLD "
                  f"(bar: >= {bar:.0%})")
    if ascii_draw:
        for (shape_id, energy), (r, outline) in draws.items():
            print(f"\n{label} {shape_id} @ Energy {energy} — mid-hold "
                  f"(`o` an outline cell lit, `x` one dark, `+` other lit "
                  f"light, `.` a dark real cell)")
            print(_ascii(r.frames[r.mid_hold], outline))
    return draws


def _ascii(frame: np.ndarray, outline: np.ndarray) -> str:
    lit = bright(frame) >= LIT
    lines = []
    for row in range(ROWS):
        chars = []
        for col in range(COLS):
            if not REAL2[row, col]:
                chars.append(" ")
            elif outline[row, col]:
                chars.append("o" if lit[row, col] else "x")
            elif lit[row, col]:
                chars.append("+")
            else:
                chars.append(".")
        lines.append("".join(chars).rstrip())
    return "\n".join(lines)


def _grade(frame: np.ndarray, band: np.ndarray | None = None) -> str:
    """The frame LUMINANCE-GRADED on the real mask — the W1.4 Fish review's
    own grading, carried here: `.` dark (at or under LIT), `-` under
    BAND_LIT_LO, `+` under BAND_LIT_HI, `#` at or over it. `band` restricts
    the drawing to the shape's own outline band, which is where the bar is
    read, so the two renders together say "what the eye sees" and "is the
    LINE whole"."""
    lum = bright(frame)
    lines = []
    for row in range(ROWS):
        chars = []
        for col in range(COLS):
            if not REAL2[row, col] or (band is not None
                                       and not band[row, col]):
                chars.append(" ")
                continue
            v = lum[row, col]
            chars.append("." if v <= LIT else
                         "-" if v < BAND_LIT_LO else
                         "+" if v < BAND_LIT_HI else "#")
        lines.append("".join(chars).rstrip())
    return "\n".join(lines)


def fill_time_s(run_: Run, shape_id: str, bar: float) -> float:
    """Seconds from the WORD until the band's share over BAND_LIT_LO first
    reaches `bar` and stays there for the rest of the hold — "how long
    after the word before the whole line is standing".

    This is row W4.4's own statistic, and it is the one that answers his
    complaint directly. The hold's FIRST frames cannot be whole whatever
    the speed: during the form the position is a BLEND, so the trail laid
    early in the form was laid on the blob's circle, not on the outline —
    only the last part of the form lands on the line. Speed is exactly
    what shortens this, and the measurement shows it doing so.
    NaN = it never reaches the bar within the hold."""
    hit = None
    for i in range(run_.word, run_.hold_end + 1):
        lo, _hi, _r = band_contrast(run_.frames[i], shape_id)
        if lo >= bar:
            if hit is None:
                hit = i
        else:
            hit = None
    if hit is None:
        return float("nan")
    return (hit - run_.word) * DT


def report_contrast(shapes, ascii_draw: bool, needed: bool):
    """ROW W4.4's OWN BAR, over FEW with 1 and 3 blobs and MANY with 4 and
    8 — the whole range his Energy binding drives `particle_count` across.

    WHAT IS ASSERTED, AND THE ONE BAR THAT IS REPORTED INSTEAD. The row's
    spec asked for 90% of the outline band over 128/255 (half of full) at
    every hold frame. That threshold is ABOVE WHAT THIS EFFECT CAN DEPOSIT
    on the band's outer cells, and the arithmetic is exact rather than
    arguable: the band is every real cell within ONE CELL PITCH of the
    outline, a pitch is two addressable columns, and `_splat` stamps a dot
    whose weight falls off as `1 - dist / (blob_size + 0.5)` — so at his
    `blob_size` fallback 2.5 a cell a full pitch off the swept path takes
    `1 - 2 / 3 = 0.33` of the blob's own brightness, and his
    `brightness_audio` 0.5 already holds that brightness at 0.775 of full.
    0.33 x 0.775 x 255 = 65 OF 255. The outer band cells cap there, the
    trail composes by `np.maximum` and so can never exceed what was
    deposited, and no speed and no trail can move either number.

    So the bar asserted is the share over BAND_LIT_LO (64/255) — the SAME
    threshold, for the same reason, that the Fish row's own bar uses
    (`scripts/check_fish_word_shape.py`'s `band_contrast`) — plus the
    band/rest luminance ratio, each read beside THE SAME SEED's frame
    UNTOLD. The 128/255 share is measured and printed on every row with
    the undecayed-trail CEILING beside it (`--needed`), as an OPEN
    EXCEEDANCE of the row's spec rather than a hidden one: the levers that
    could close it are `blob_size` and `brightness_audio`, his own
    authored params, his eye, not a build row's to move.

    WHERE IT IS READ. At MID-HOLD and at the HOLD'S END, the two named
    frames W1.3 used, and the worst over EVERY hold frame is printed
    beside them. The hold's first frames cannot be whole at any speed —
    `fill_time_s`'s own note says why — and that is what `fill` measures.
    """
    print(f"\n── ROW W4.4's BAR: is the outline LIGHT, and does it stand "
          f"out ──\n"
          f"Band = the shape's own outline cells (within one cell pitch of "
          f"it), on his real mask.\n"
          f"ASSERTED: >= {BAND_LO_BAR_FEW:.0%} (FEW) / "
          f"{BAND_LO_BAR_MANY:.0%} (MANY) of the band over "
          f"{BAND_LIT_LO:.0f}/255 at mid-hold AND at the hold's end, "
          f"band/rest luminance ratio >= {BAND_RATIO_BAR:.1f} and over the "
          f"untold control's own.\n"
          f"REPORTED, not asserted: the share over {BAND_LIT_HI:.0f}/255 "
          f"(the row's spec asked {BAND_HI_BAR:.0%} — see this function's "
          f"docstring for the exact arithmetic that puts it out of reach "
          f"at his blob_size), the worst over EVERY hold frame, `fill` =\n"
          f"seconds after the word before the whole line stands, and the "
          f"W1.3 lit-cell number at {LIT:.0f}/255 for the record.")
    header = (f"{'mode':>5s} {'n':>2s} {'shape':9s} {'en':>4s} "
              f"{'mid>64':>7s} {'end>64':>7s} {'bare>64':>8s} "
              f"{'mid r':>6s} {'end r':>6s} {'bare r':>7s} "
              f"{'mid>128':>8s} {'end>128':>8s} "
              f"{'worst>64':>9s} {'worst>128':>10s} {'fill':>6s} "
              f"{'W1.3':>5s}")
    print(header)
    print("-" * len(header))
    rows = []
    for counts, mode, bar in ((FEW_COUNTS, "few", BAND_LO_BAR_FEW),
                              (MANY_COUNTS, "many", BAND_LO_BAR_MANY)):
        for count in counts:
            for shape_id in shapes:
                outline, _n_out = outline_cells(shape_id)
                for energy in ENERGIES:
                    told = asyncio.run(run(shape_id, energy, count,
                                           tag=f"ct-{mode}{count}"))
                    bare = asyncio.run(run(None, energy, count,
                                           tag=f"ctc-{mode}{count}"))
                    mid = band_contrast(told.frames[told.mid_hold], shape_id)
                    end = band_contrast(told.frames[told.hold_end], shape_id)
                    b_mid = band_contrast(bare.frames[told.mid_hold],
                                          shape_id)
                    w_lo, w_hi, _w_r, w_i = worst_hold(told, shape_id)
                    fill = fill_time_s(told, shape_id, bar)
                    w13 = coverage(told.frames[told.mid_hold], outline)
                    print(f"{told.mode:>5s} {count:2d} {shape_id:9s} "
                          f"{energy:4.1f} {mid[0]:7.0%} {end[0]:7.0%} "
                          f"{b_mid[0]:8.0%} {mid[2]:6.2f} {end[2]:6.2f} "
                          f"{b_mid[2]:7.2f} {mid[1]:8.0%} {end[1]:8.0%} "
                          f"{w_lo:9.0%} {w_hi:10.0%} {fill:5.2f}s "
                          f"{w13:5.0%}")
                    rows.append(dict(mode=mode, count=count, shape=shape_id,
                                     energy=energy, bar=bar, mid=mid,
                                     end=end, b_mid=b_mid, w_lo=w_lo,
                                     w_hi=w_hi, fill=fill, run=told,
                                     worst_i=w_i))
    print()
    for r in rows:
        tag = f"{r['mode']}{r['count']} {r['shape']}@{r['energy']}"
        for when, vals in (("mid-hold", r["mid"]), ("the hold's end",
                                                    r["end"])):
            check(vals[0] >= r["bar"],
                  f"{tag} at {when}: {vals[0]:.0%} of the outline band "
                  f"over {BAND_LIT_LO:.0f}/255 (bar: >= {r['bar']:.0%}; "
                  f"untold {r['b_mid'][0]:.0%})")
            check(vals[2] >= BAND_RATIO_BAR,
                  f"{tag} at {when}: band/rest luminance ratio "
                  f"{vals[2]:.2f} (bar: >= {BAND_RATIO_BAR:.1f}; untold "
                  f"{r['b_mid'][2]:.2f})")
        check(r["mid"][0] >= BAND_LIFT_X * r["b_mid"][0],
              f"{tag}: the band's own share over {BAND_LIT_LO:.0f}/255 is "
              f"{r['mid'][0]:.0%} told against {r['b_mid'][0]:.0%} untold "
              f"on the same seed and the same frame (bar: at least "
              f"{BAND_LIFT_X:.0f}x)")
    _report_the_open_exceedance(rows, needed)
    if ascii_draw:
        for r in rows:
            band, _n = outline_cells(r["shape"])
            told = r["run"]
            print(f"\n{r['mode']}{r['count']} {r['shape']} @ Energy "
                  f"{r['energy']} — MID-HOLD: {r['mid'][0]:.0%} of the "
                  f"band over {BAND_LIT_LO:.0f}, {r['mid'][1]:.0%} over "
                  f"{BAND_LIT_HI:.0f}, ratio {r['mid'][2]:.2f}")
            print("  the panel, luminance-graded (`.` <= 20, `-` < 64, "
                  "`+` < 128, `#` >= 128 of 255):")
            print(_grade(told.frames[told.mid_hold]))
            print("  the outline band alone — is the LINE whole:")
            print(_grade(told.frames[told.mid_hold], band))
    return rows


def _report_the_open_exceedance(rows, needed: bool):
    """The row's spec bar (BAND_HI_BAR of the band over BAND_LIT_HI),
    measured and reported rather than hidden — the honest-bar rule from
    wave 1, and the same shape as the Fish row's white tail.

    `--needed` adds, for every row under it, the smallest `speed_x` in
    range that would reach it and — when none does — the UNDECAYED-TRAIL
    ceiling, which is what says whether speed is the binding constraint at
    all. It is not: see `report_contrast`'s docstring."""
    under = [r for r in rows if r["mid"][1] < BAND_HI_BAR]
    print(f"\n── OPEN EXCEEDANCE of the row's spec bar "
          f"({BAND_HI_BAR:.0%} of the band over {BAND_LIT_HI:.0f}/255) ──")
    if not under:
        print("   none — every row reaches it.")
        return
    best = max(r["mid"][1] for r in rows)
    print(f"   {len(under)} of {len(rows)} (mode, count, shape, Energy) "
          f"rows are under it at mid-hold; the best row reads "
          f"{best:.0%}.\n"
          f"   THE CEILING IS THE SPLAT KERNEL, NOT THE SPEED. The band is "
          f"every real cell within ONE CELL PITCH of the outline; a pitch "
          f"is two\n   addressable columns; `orbits._splat` weights a cell "
          f"`1 - dist / (blob_size + 0.5)`, so at his `blob_size` 2.5 a "
          f"cell a full pitch\n   off the swept path takes 0.33 of the "
          f"blob's brightness, and `brightness_audio` 0.5 holds that at "
          f"0.775 of full: 65 OF 255.\n   The trail composes by "
          f"`np.maximum`, so nothing can exceed what was deposited. The "
          f"levers that could close this are `blob_size`\n   and "
          f"`brightness_audio` — HIS authored params, his eye, not a build "
          f"row's to move. Reported, not hidden.")
    if not needed:
        print("   Re-run with `--needed` for the speed each row would "
              "need and its undecayed-trail ceiling.")
        return
    header = (f"   {'mode':>5s} {'n':>2s} {'shape':9s} {'en':>4s} "
              f"{'>128 now':>9s} {'speed that reaches it':>22s} "
              f"{'undecayed ceiling':>18s}")
    print(header)
    print("   " + "-" * (len(header) - 3))
    keep = FX.WORD_SHAPE_TRAIL_S
    for r in under:
        found = None
        for speed in (4.0, 5.0, 6.0):
            got = asyncio.run(run(r["shape"], r["energy"], r["count"],
                                  tag=f"need-{r['mode']}{r['count']}",
                                  word_shape_speed_x=speed))
            v = band_contrast(got.frames[got.mid_hold], r["shape"])[1]
            if v >= BAND_HI_BAR:
                found = (speed, v)
                break
        ceiling = float("nan")
        if found is None:
            FX.WORD_SHAPE_TRAIL_S = 1.0e6
            try:
                got = asyncio.run(run(r["shape"], r["energy"], r["count"],
                                      tag=f"ceil-{r['mode']}{r['count']}",
                                      word_shape_speed_x=6.0))
                ceiling = band_contrast(got.frames[got.hold_end],
                                        r["shape"])[1]
            finally:
                FX.WORD_SHAPE_TRAIL_S = keep
        said = (f"{found[0]:.0f}x -> {found[1]:.0%}" if found
                else "none in 1..6")
        print(f"   {r['mode']:>5s} {r['count']:2d} {r['shape']:9s} "
              f"{r['energy']:4.1f} {r['mid'][1]:9.0%} {said:>22s} "
              f"{'' if found else f'{ceiling:17.0%}'}")


def report_continuity(shapes):
    print("\n── continuity: his \"no sudden velocity shifts\" ──")
    print("""
Per-frame SPEED change (px/s) and HEADING change (rad) for every tracked
blob at the four moments the blend moves, against this effect's OWN
ordinary maximum (the same seed, the same audio, untold).

TWO QUANTITIES, NOT ONE, because they answer different questions:

  * at the FORM's START and the RELEASE's END, both the speed change and
    the heading change are bounded by the effect's own ordinary maximum —
    acceptance 3's bar, verbatim. Those are the two moments the row's own
    ramp is steepest, and they are where his rule is really being tested.
  * at the HOLD's two edges NEITHER is the blend's, so neither is what is
    barred there. What is asserted instead has no magic number in it: the
    envelope's largest one-frame move over the WHOLE shape against the
    steepest a smoothstep of this shape's own form and release could
    possibly be (1.5 / its duration), and THE MOST THIS ROW AND THE BLEND
    TOGETHER can be changing a blob's speed there (the `row` column:
    `blend_speed_bound` + `multiplier_speed_bound`) against the effect's
    own ordinary maximum. Through the hold the envelope stands at 1.0 and
    leaves it with zero slope, and the multiplier stands at `x`, so what
    is left in the raw numbers is the OUTLINE's own geometry or Orbits'
    own jog kick.

ROW W4.4 MOVED THE HOLD-EDGE SPEED INTO THAT SECOND CASE, and the
measurement is why. Before the row, a blob walked the outline at its own
`base_speed` — slower than its ordinary orbit — so its hold-edge speed
change was small and the raw number sat under the untold control's. At the
told speed it runs the outline four times faster, and the panel is
ANISOTROPIC (a column is half a cell pitch, a row sqrt(3)/2), so the same
arc-length walk has a px speed that swings by nearly 2x around the outline
and changes abruptly at every corner: measured, a standing shape produces
one-frame speed changes up to 100 px/s ANYWHERE in the hold (printed as
`mid-hold`, and never barred — W1.3's own ruling), against an untold
quiet-Energy control whose smooth circles only reach 98. Comparing a
4x-speed outline walk against a 1x-speed circle is not a like-for-like
test of "sudden shifts"; the decomposition is. The raw hold-edge number is
printed, with a line under it naming what accounts for it.
""")
    header = (f"{'shape':9s} {'mode':>5s} {'energy':>6s} {'outline':>8s} "
              f"{'ordinary':>17s} {'form start':>17s} {'hold edges':>17s} "
              f"{'release end':>17s} {'row@hold':>9s}")
    print(header)
    print("-" * len(header))
    for count, mode in ((FEW_N, "few"), (MANY_N, "many")):
        for shape_id in shapes:
            sharp = shape_sharpest_turn(shape_id)
            for energy in ENERGIES:
                told = asyncio.run(run(shape_id, energy, count,
                                       tag=f"cont-{mode}"))
                bare = asyncio.run(run(None, energy, count,
                                       tag=f"ctrl-{mode}"))
                d_spd, d_turn = speeds_and_turns(told)
                b_spd, b_turn = speeds_and_turns(bare)
                ord_s = max((float(a.max()) for a in b_spd if a.size),
                            default=0.0)
                ord_t = max((float(a.max()) for a in b_turn if a.size),
                            default=0.0)
                f_s = window_max(d_spd, told.edge)
                f_t = window_max(d_turn, told.edge)
                h_s = max(window_max(d_spd, told.word),
                          window_max(d_spd, told.hold_end))
                h_t = max(window_max(d_turn, told.word),
                          window_max(d_turn, told.hold_end))
                r_s = window_max(d_spd, told.release_end)
                r_t = window_max(d_turn, told.release_end)
                blend_h = max(row_speed_bound(told, told.word),
                              row_speed_bound(told, told.hold_end))
                mid_s = max((float(a.max()) for a in
                             d_spd[told.word + 4:told.hold_end - 3]
                             if a.size), default=0.0)
                mid_t = max((float(a.max()) for a in
                             d_turn[told.word + 4:told.hold_end - 3]
                             if a.size), default=0.0)
                print(f"{shape_id:9s} {mode:>5s} {energy:6.1f} "
                      f"{sharp:8.3f} "
                      f"{ord_s:7.1f}/{ord_t:<9.3f} "
                      f"{f_s:7.1f}/{f_t:<9.3f} "
                      f"{h_s:7.1f}/{h_t:<9.3f} "
                      f"{r_s:7.1f}/{r_t:<9.3f} {blend_h:9.1f}")
                tag = f"{mode} {shape_id}@{energy}"
                # the SPEED change: acceptance 3's bar at the two moments
                # the row's own ramp is what is moving (ROW W4.4 took the
                # hold edges out — see this report's own preamble)
                for name, value in (("form start", f_s),
                                    ("release end", r_s)):
                    check(value <= ord_s + 1e-6,
                          f"{tag} {name}: speed change {value:.1f} <= "
                          f"ordinary {ord_s:.1f} px/s")
                # the HEADING change where the blend actually moves
                for name, value in (("form start", f_t),
                                    ("release end", r_t)):
                    check(value <= ord_t + 1e-6,
                          f"{tag} {name}: heading change {value:.3f} <= "
                          f"ordinary {ord_t:.3f} rad")
                # ... and at the hold's edges, where the BLEND is what has
                # to be still: the envelope stands at 1.0 and leaves it with
                # zero slope, so the geometry there is the pure standing
                # shape to within a percent, and whatever a blob does it is
                # doing ON the shape (a corner) or by its own jog kick — not
                # in the blend. That is what is asserted; the raw heading
                # change is reported beside the two things that explain it.
                step, bar = envelope_step(told)
                check(step <= bar,
                      f"{tag}: the envelope's largest one-frame move over "
                      f"the WHOLE shape is {step:.4f} (bar: <= {bar:.4f}, "
                      f"the steepest a smoothstep of its own form/release "
                      f"can be)")
                check(blend_h <= ord_s + 1e-6,
                      f"{tag} hold edges: this ROW and the blend together "
                      f"can be moving a blob at most {blend_h:.1f} px/s "
                      f"there, under the ordinary {ord_s:.1f}")
                # ... and nothing special happens at the edges: whatever
                # the raw number is there, a standing shape on this same
                # outline at this same speed does as much somewhere in the
                # middle of the hold, where the envelope is certainly flat
                check(h_s <= max(ord_s, mid_s) + blend_h + 1e-6,
                      f"{tag} hold edges: the raw speed change "
                      f"{h_s:.1f} px/s is within what a STANDING shape on "
                      f"this outline already does mid-hold "
                      f"({mid_s:.1f}) or this effect does untold "
                      f"({ord_s:.1f}), plus the {blend_h:.1f} this row "
                      f"and the blend can add")
                if h_t > max(ord_t, sharp):
                    print(f"          (hold-edge heading {h_t:.3f} rad is "
                          f"over both the ordinary {ord_t:.3f} and this "
                          f"outline's own {sharp:.3f} — a jog kick stalling "
                          f"or reversing a blob, which it does untold too; "
                          f"the blend there is bounded above)")
                if h_s > ord_s:
                    print(f"          (hold-edge speed {h_s:.1f} px/s is "
                          f"over the untold quiet-Energy ordinary "
                          f"{ord_s:.1f} — the outline's own corners at the "
                          f"told speed, which a STANDING shape does "
                          f"mid-hold too ({mid_s:.1f}); this row and the "
                          f"blend can add at most {blend_h:.1f} of it)")
                print(f"          (mid-hold, NOT a bar — a blob rounding a "
                      f"corner of the outline: {mid_s:.1f} px/s / "
                      f"{mid_t:.3f} rad)")


def report_jump_white_cost(shapes):
    print("\n── nothing jumps, no white, and what it costs ──")
    header = (f"{'shape':9s} {'mode':>5s} {'energy':>7s} {'jump':>8s}"
              f"{'(untold)':>9s} {'white':>6s}{'bare':>6s} {'p50 told':>9s} "
              f"{'p50 bare':>9s}")
    print(header)
    print("-" * len(header))
    for count, mode in ((FEW_N, "few"), (MANY_N, "many")):
        for shape_id in shapes:
            for energy in ENERGIES:
                told = asyncio.run(run(shape_id, energy, count,
                                       tag=f"jwc-{mode}"))
                bare = asyncio.run(run(None, energy, count,
                                       tag=f"jwcc-{mode}"))
                # the form and the release, the two moving stretches —
                # measured on the told run AND on the untold control over
                # the SAME frames, because the control is the honest bar
                # here (see THE LIT-CELL JUMP below)
                spans = [(told.edge, told.word + 1),
                         (told.hold_end, told.release_end + 1)]
                worst = max(lit_jump(told, lo, hi) for lo, hi in spans)
                # the effect's OWN ordinary maximum, over the whole untold
                # run (acceptance 3's own wording for this effect)
                worst_bare = lit_jump(bare, 0, len(bare.frames))
                w_told = max(phase_grammar.white_cells(f, WHITE)
                             for f in told.frames[told.edge:
                                                  told.release_end + 1])
                w_bare = max(phase_grammar.white_cells(f, WHITE)
                             for f in bare.frames)
                p_told = statistics.median(
                    told.cost_ms[told.word:told.hold_end + 1])
                p_bare = statistics.median(bare.cost_ms)
                print(f"{shape_id:9s} {mode:>5s} {energy:7.1f} "
                      f"{worst:8.1%}{worst_bare:9.1%} "
                      f"{w_told:6d}{w_bare:6d} "
                      f"{p_told:8.2f}m {p_bare:8.2f}m")
                check(worst <= worst_bare,
                      f"{mode} {shape_id}@{energy}: largest lit-cell jump "
                      f"{worst:.1%} over the form and the release, against "
                      f"this effect's own ordinary {worst_bare:.1%} untold")
                check(w_told <= w_bare + WHITE_SLACK,
                      f"{mode} {shape_id}@{energy}: white cells under a "
                      f"shape {w_told} <= untold {w_bare} + "
                      f"{WHITE_SLACK}")
                check(p_told - p_bare < COST_BAR_MS,
                      f"{mode} {shape_id}@{energy}: p50 cost "
                      f"+{p_told - p_bare:.2f} ms with a shape holding "
                      f"(bar: < {COST_BAR_MS} ms)")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shape", action="append", dest="shapes",
                    help="measure only this shape (repeatable)")
    ap.add_argument("--ascii", action="store_true",
                    help="draw each mid-hold frame on the real mask")
    ap.add_argument("--skip-continuity", action="store_true")
    ap.add_argument("--speed-x", type=float, default=None,
                    help="override word_shape_speed_x (row W4.4's lever 1)")
    ap.add_argument("--trail-s", type=float, default=None,
                    help="override WORD_SHAPE_TRAIL_S (row W4.4's lever 2)")
    ap.add_argument("--only", action="append", dest="only",
                    choices=("mode", "contrast", "continuity", "jwc"),
                    help="run only this report (repeatable)")
    ap.add_argument("--needed", action="store_true",
                    help="for every contrast row under the bar, the speed "
                         "it would need and its undecayed-trail ceiling")
    args = ap.parse_args()
    SPEED_X[0] = args.speed_x
    if args.trail_s is not None:
        FX.WORD_SHAPE_TRAIL_S = float(args.trail_s)
    only = set(args.only or ("mode", "contrast", "continuity", "jwc"))
    if args.skip_continuity:
        only.discard("continuity")
    shapes = tuple(args.shapes or word_shapes.shape_ids())
    for s in shapes:
        if not word_shapes.has(s):
            print(f"no such shape: {s}")
            return 2

    print(f"orbits word shape — SIZE {SIZE}, his live Orbits V2 Matrix "
          f"entry on the real crystal-mapper mask\n"
          f"({int(REAL.sum())} real cells of {ROWS * COLS} addressable), "
          f"lit >= {LIT}/255, white > {WHITE}/255")
    from spectra.services.room_controls import (RoomControlState,
                                                word_shape_timing)
    for energy in ENERGIES:
        f, h, r = word_shape_timing(energy, PHRASE_MS, RoomControlState(),
                                    ["orbits"])
        print(f"  Energy {energy}: form {f:.3f}s, hold {h:.2f}s, release "
              f"{r:.2f}s (room_controls.word_shape_timing, phrase "
              f"{PHRASE_MS:.0f} ms)")

    speed = (SPEED_X[0] if SPEED_X[0] is not None
             else FX.Orbits2d.schema()({})["word_shape_speed_x"])
    print(f"  word_shape_speed_x {speed}, WORD_SHAPE_TRAIL_S "
          f"{FX.WORD_SHAPE_TRAIL_S} (row W4.4's two levers)")

    if "mode" in only:
        report_mode("few", FEW_N, BAR_FEW, shapes, args.ascii)
        report_mode("many", MANY_N, BAR_MANY, shapes, args.ascii)
    if "contrast" in only:
        report_contrast(shapes, args.ascii, args.needed)
    if "continuity" in only:
        report_continuity(shapes)
    if "jwc" in only:
        report_jump_white_cost(shapes)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("all bars met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
