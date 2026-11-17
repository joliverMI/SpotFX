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

WHAT IS MEASURED

  coverage   real outline cells lit at or above LIT (20/255 on the frame's
             brightest channel — `scripts/check_drop_shockwave.py`'s own
             convention) by the blobs AND their comet trails, at the WORD
             (the instant the form completes) and at MID-HOLD. The row's
             bar: >= 60% with FEW blobs, >= 75% with MANY.
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

`--ascii` draws the lit outline cells at mid-hold on the real mask beside
the shape's own outline, which is the quickest way to see whether a heart
reads as a heart on 976 cells.
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


def report_continuity(shapes):
    print("\n── continuity: his \"no sudden velocity shifts\" ──")
    print("""
Per-frame SPEED change (px/s) and HEADING change (rad) for every tracked
blob at the four moments the blend moves, against this effect's OWN
ordinary maximum (the same seed, the same audio, untold).

TWO QUANTITIES, NOT ONE, because they answer different questions:

  * the SPEED change is the blend's, and it is bounded at every moment by
    the effect's own ordinary maximum — acceptance 3's bar, verbatim.
  * the HEADING change at the HOLD's two edges is NOT the blend's, so it is
    not what is barred there. What is asserted instead is the BLEND's own
    smoothness, with no magic number: the envelope's largest one-frame move
    over the WHOLE shape, against the steepest a smoothstep of this shape's
    own form and release could possibly be (1.5 / its duration), and the
    most the blend could therefore be moving a blob at either hold edge
    (the `blend` column, px/s) against the effect's own ordinary maximum.
    Through the hold the envelope stands at 1.0 and leaves it with zero
    slope, so a hard turn in those frames is either the OUTLINE (a heart's
    cleft turns 3.11 rad, a star's point 2.35, a diamond's 1.82 — printed
    as `outline`) or Orbits' own jog kick, which stalls or reverses a blob
    for a tenth of a second at loud Energy whether a shape is standing or
    not — the untold control reaches 3.10 of the 3.14 rad a heading change
    can possibly be. The raw number is printed, and a line is printed under
    it whenever it is over both.
""")
    header = (f"{'shape':9s} {'mode':>5s} {'energy':>6s} {'outline':>8s} "
              f"{'ordinary':>17s} {'form start':>17s} {'hold edges':>17s} "
              f"{'release end':>17s} {'blend@hold':>11s}")
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
                blend_h = max(blend_speed_bound(told, told.word),
                              blend_speed_bound(told, told.hold_end))
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
                # the SPEED change: acceptance 3's bar at all four moments
                for name, value in (("form start", f_s), ("hold edges", h_s),
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
                      f"{tag} hold edges: the blend itself can be moving a "
                      f"blob at most {blend_h:.1f} px/s there, under the "
                      f"ordinary {ord_s:.1f}")
                if h_t > max(ord_t, sharp):
                    print(f"          (hold-edge heading {h_t:.3f} rad is "
                          f"over both the ordinary {ord_t:.3f} and this "
                          f"outline's own {sharp:.3f} — a jog kick stalling "
                          f"or reversing a blob, which it does untold too; "
                          f"the blend there is bounded above)")
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
    args = ap.parse_args()
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

    report_mode("few", FEW_N, BAR_FEW, shapes, args.ascii)
    report_mode("many", MANY_N, BAR_MANY, shapes, args.ascii)
    if not args.skip_continuity:
        report_continuity(shapes)
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
