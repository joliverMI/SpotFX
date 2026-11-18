#!/usr/bin/env python3
"""Read-only evidence script for FIREWORKS' SHAPED PAYOFF BURST (Word Shapes
plan row W1.2, section 3.6; the Admiral's words for the row: "have a flare
style firework (so the ones that are bigger) explode into the given shape and
hang longer than the others. It should form a slightly more solid outline
than the filling, but it also needs to still appear random").

It drives the REAL vendored `fireworks` effect (fx/effects/fireworks.py) on a
headless host wearing HIS crystal's real 976-cell mask, writes the six told
keys (fx/effects/word_shape_keys.py) the way SpotFX's Word Shape kind writes
them, renders real frames, and measures the picture on the mask:

  * ON THE WORD (the frame the form ends): what share of the shape's OUTLINE
    cells are lit, and how bright the inside is against the outline;
  * AT MID-HOLD: the same two numbers, so "it hangs" is measured and not
    assumed;
  * ARRIVAL: the worst spark's distance from the target it was launched at,
    in real-cell pitches — the claim the velocity solve exists for;
  * THE SPLIT: how many sparks went to the outline against the told share;
  * WHITE: the shape alone lights no white-ish cell at all; over a live
    show, the highest share of lit cells that are white-ish beside the same
    measure over an untold twin AND over the effect's own Firework Burst
    flare (six payoff bursts — the busiest thing it does today). THAT
    SECOND NUMBER IS REPORTED, NOT A BAR THIS SCRIPT CALLS PASSED: the
    worst frame of a busy run carries about ten washed-out cells more than
    the same show without a shape, and the cause is the TRAIL's channel-wise
    max over TIME rather than anything a per-frame composite or a brightness
    reaches — the block this script prints at the end has all of it;
  * COST: the p50 per-frame render cost with a shape holding, against the
    same show without one;
  * W5.6, his second room verdict (2026-11-18): THE DIM BAR that replaces
    W4.3's dark canvas (the ordinary light on the word against the SAME
    SEED's untold frame — bounded on both sides, because "dimmer, so
    fading out already" is not "clear of other fireworks"); THE FLIGHT'S
    OWN SPEED CURVE at 25/50/75/100% of the 2.0 s flight (falling all the
    way, still moving at the word); THE RESIDUAL DRIFT over the hold
    (never exactly zero on any frame) and THE BREAK-APART over the release
    (the outline's own mean radius growing as the sparks loosen).

THE DENOMINATORS ARE NOT THIS SCRIPT'S. The outline- and inside-cell sets
come from `scripts/check_word_shapes.py` (`load_panel`, `measure`) — the one
place they are defined and the numbers `tests/test_word_shapes.py` pins
(heart 168/332, star 176/196, diamond 119/191 at SIZE 0.62). A clarity bar
measured against a denominator this script re-derived by hand would drift
silently; this one cannot.

THE BARS (plan section 3.6, and the simulation they come from):

  * sparks light at least 70% of the outline cells ON THE WORD;
  * the inside's mean brightness is at most 0.70 of the outline's (an
    outline, not a blob — the star's fill sits closest to this one).

The plan's simulation, quiet / loud: heart 72% / 87% coverage (fill ratio
0.46 / 0.47), star 76% / 86% (0.65 / 0.65), diamond 81% / 90% (0.50 / 0.53).
Those are the targets the real effect has to reproduce or beat.

The run is offline by construction: `fx.headless` dummy devices, no audio
hardware (`silence_audio`), a fake clock, no network, nothing written. The
busy-music feed is a deterministic canned impulse, not a recording.

Usage:
  .venv/bin/python scripts/check_fireworks_word_shape.py
  .venv/bin/python scripts/check_fireworks_word_shape.py --ascii
  .venv/bin/python scripts/check_fireworks_word_shape.py --shape heart --energy 0.8
"""
from __future__ import annotations

import argparse
import asyncio
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fx.effects import word_shape_keys as wsk  # noqa: E402
from fx.effects import word_shapes  # noqa: E402
from scripts.check_word_shapes import (COLUMN_PITCH, DEFAULT_SIZE_FRACTION,  # noqa: E402
                                       ROW_PITCH, Panel, load_panel, measure)

ROWS, COLS = 37, 72
DT = 1.0 / 30.0        # his crystal renders at 30 fps (the radial note)

# A cell counts as LIT at 8/255 of full on its brightest channel: real
# light on the panel, well above the trail's own floor, and the same
# threshold both sides of every ratio below.
LIT = 8.0 / 255.0
# W4.3 — THE CANVAS. "Mostly dark" needs a threshold a viewer would call
# light rather than the trail's own floor, so the canvas measure reads
# 20/255: what share of his real cells still carry ORDINARY (non-shaped)
# light at the moment the shape arrives. The bar is 5% of the real cells,
# and the same-seed UNTOLD frame's share is printed beside it — that
# difference IS the clutter the hush takes away.
CANVAS_LIT = 20.0 / 255.0
CANVAS_BAR = 0.05
CANVAS_SEEDS = 20
# W5.6 — THE CANVAS BAR IS NOW A *DIM* BAR, because his second verdict
# retires the dark one: "The background doesn't need to be clear of other
# fireworks, just they need to be dimmer, so fading out already." So the
# measured quantity is a RATIO rather than a share — the ORDINARY light on
# the panel at the word against THE SAME SEED'S UNTOLD frame — and it is
# bounded on BOTH sides: at most this much of the untold light (the dim is
# really dimming), and more than zero (it is a dim bar, never a 0% one).
# The light is the panel's own mean luminance over his real cells
# (`panel_light`), not a cell count: a share of cells above a threshold
# cannot see a cell that merely went dimmer, which is the whole of what
# this row does.
DIM_BAR = 0.45
# ... and the lit-cell share the dark bar used to assert is still PRINTED
# beside it, so the two rows' numbers are comparable at a glance.
# W4.3 — AND CONTRAST, because legibility on that canvas is the whole
# point of the row. A ">= LIT" share is vacuous once anything is trailing
# (the W1.4 Fish review, carried to every wave-4 row): grade the panel by
# luminance and read the shape's own outline BAND against the rest of it.
# Luminance is the cell's own peak channel, the same quantity `white_share`
# and the coverage measure read.
BAND_LIT_LO = 64.0 / 255.0
BAND_LIT_HI = 128.0 / 255.0
CONTRAST_BAR = 3.0
# WHITE-ISH: every channel at least this bright AND the channels within
# this much of each other — the same "is it white" shape the other
# no-white checks here use.
WHITE_MIN = 0.55
WHITE_SPREAD = 0.18

# HIS OWN FIREWORKS V2 MATRIX ENTRY (config/effect_params.json's
# `fireworks.defaults` — the starter set his scene carries). spawn_rate 0
# is the live regime: beat bursts are the only ordinary launch source, so
# the shaped burst must not depend on the launch rate for anything.
HIS_CFG = {
    "x_offset": 0.5, "y_offset": 0.5, "radius_scale": 1.0, "blob_size": 2.0,
    "trail_decay": 0.27, "spawn_rate": 0.0, "beat_burst": 4,
    "spawn_audio": 2.0, "burst_size": 8, "burst_speed": 1.8,
    "burst_life": 1.9, "speed_audio": 3.2, "brightness_audio": 2.0,
    "max_blobs": 100, "drag": 0.69, "impulse_decay": 0.06,
    "frequency_range": "Lows (beat+bass)", "burst_audio": 1.0,
    "gradient": ("linear-gradient(90deg, #ff0000 0.00%,#ff7800 14.00%,"
                 "#ffc800 28.00%,#00ff00 42.00%,#00c78c 56.00%,"
                 "#0000ff 70.00%,#800080 84.00%,#ff00b2 98.00%)"),
}

# HIS SCENE AT ITS BUSIEST (W4.3's own worst case). His Fireworks V2 Matrix
# entry binds `beat_burst` 1->6 and `burst_size` 5->14 by Energy, so at
# Energy 1.0 a beat throws six fireworks of fourteen sparks each, every one
# living ~1.9 s into a `max_blobs` of 100 — which is the clutter his verdict
# is about. The canvas measure runs here, not at the starter set's 4 x 8.
WORST_CFG = {"beat_burst": 6, "burst_size": 14}

# The room's own timing (room_controls.word_shape_timing's defaults: the
# form paces 0.9 s quiet to 0.5 s loud, the hold is the phrase clamped to
# 0.8..2.0, the release 1.5x the form), FLOORED at this effect's own
# minimum form — 2.0 s since row W4.3, read from fx.device_model rather
# than written out, so the script cannot drift from the engine's own rule.
# Written out otherwise so this script needs no SPECTRA import.
def room_timing(energy: float, phrase_s: float = 1.1) -> tuple[float, float, float]:
    from fx import device_model
    fast_at = 0.75
    form = 0.9 + (0.5 - 0.9) * min(1.0, max(0.0, energy) / fast_at)
    form = max(form, device_model.word_shape_form_min_s(["fireworks"]))
    hold = min(2.0, max(0.8, phrase_s))
    return form, hold, 1.5 * form


class BusyAudio:
    """A deterministic busy-music feed: lows 0.55 +/- 0.30 with a lift on
    each beat, a beat every `BEAT` frames at 30 fps — the same shape
    tests/test_blackhole_infall_through_transition.py feeds. `BEAT` 14 is
    ~128 bpm (W1.2's own feed); the W4.3 canvas runs use a subclass at 15,
    which is exactly 120 bpm.
    """

    BEAT = 14

    def __init__(self, i: int):
        self.i = i

    def _lift(self) -> float:
        return 0.35 if (self.i % self.BEAT) < 2 else 0.0

    def lows_power(self, filtered: bool = True) -> float:
        v = 0.55 + 0.30 * math.sin(self.i / 5.0) + self._lift()
        return float(np.clip(v, 0.0, 1.5))

    beat_power = bass_power = lows_power

    def mids_power(self, filtered: bool = True) -> float:
        return 0.30 + 0.12 * math.sin(self.i / 7.0)

    def high_power(self, filtered: bool = True) -> float:
        return 0.20 + 0.10 * math.sin(self.i / 9.0)

    def bpm_beat_now(self) -> bool:
        return self.i % self.BEAT == 0


class Beat120Audio(BusyAudio):
    """120 bpm exactly at 30 fps — the W4.3 canvas measure's own feed."""

    BEAT = 15


class QuietAudio(BusyAudio):
    """A quiet room: a little low end, no beats at all — the 'nothing else
    is launching' case the shape has to stand up in on its own."""

    def lows_power(self, filtered: bool = True) -> float:
        return 0.08

    beat_power = bass_power = lows_power

    def bpm_beat_now(self) -> bool:
        return False


@dataclass
class ShapeRun:
    """One told shape, rendered. `frames` are (rows, cols, 3) in 0..1."""

    shape_id: str
    energy: float
    form_s: float
    hold_s: float
    release_s: float
    frames: list = field(default_factory=list)
    state: list = field(default_factory=list)   # word_shape_state() per frame
    lit: list = field(default_factory=list)     # lit real cells per frame
    frame_ms: list = field(default_factory=list)
    edge_frame: int = 0            # the frame the told write landed on
    launch_frame: int = -1         # the frame the burst left the centre
    word_frame: int = 0            # the frame the form ends on (the word)
    hold_end_frame: int = 0
    release_end_frame: int = 0
    targets: Optional[np.ndarray] = None   # (k, 2) normalized launch targets
    arrival_pitch: float = 0.0     # the worst spark's error, in cell pitches
    outline_sparks: int = 0
    total_sparks: int = 0
    # the mean whole LIFE the burst gave its sparks, in seconds — the flight
    # plus the hold plus each one's own share of the release
    sparks_life_mean: float = 0.0
    # W4.3: ORDINARY launches (`_spawn_burst` calls) per frame, counted by
    # the rig itself — the one number that says the hush really is a hush
    launches: list = field(default_factory=list)
    canvas: list = field(default_factory=list)   # real cells >= CANVAS_LIT
    # W5.6: the SHAPED sparks' own kinematics per frame, in real cell
    # pitches — (min, mean, max) speed a second, and their mean distance
    # from the centre. The flight's deceleration curve, the hold's residual
    # drift and the release's break-apart are all read off these.
    ws_speed: list = field(default_factory=list)
    ws_spread: list = field(default_factory=list)


def crystal_mask(panel: Panel) -> np.ndarray:
    return panel.grid.reshape(-1)


async def _host(tmp: Path, tag: str, mask: np.ndarray):
    from fx import headless
    host = await headless.start_headless_host(
        str(tmp / tag), pixel_count=ROWS * COLS, rows=ROWS, device_id=tag,
        real_mask=mask)
    return host, host.virtuals.get(tag)


_TAG = [0]


def run_shape(panel: Panel, shape_id: str, energy: float, *,
              tmp: Optional[Path] = None, config: Optional[dict] = None,
              busy: bool = True, dt: float = DT, settle_frames: int = 90,
              tail_frames: int = 20, seed: int = 7,
              phrase_s: float = 1.1, size: Optional[float] = None,
              second_word_at: Optional[int] = None,
              told: bool = True, flare: bool = False,
              audio_cls=None, no_burst: bool = False,
              stop_at_hold_end: bool = False,
              poke_at: Optional[int] = None,
              form_override: Optional[float] = None) -> ShapeRun:
    """Drive the real effect through one told shape and return the run.

    `settle_frames` of the ordinary show first (so everything measured
    happens UNDERNEATH a live firework show, never on a convenient black
    panel), then the one told write, then the whole form, hold and release
    plus `tail_frames`. `second_word_at` tells a SECOND word that many
    frames after the first's edge.

    `told=False` is the UNTOLD TWIN: the same show over the same frames with
    no shape at all, which is the only honest baseline for "is the shape
    whiter than the effect's own busy frames" — a window BEFORE the word is
    a different, shorter window and catches fewer beats. `flare=True` fires
    the effect's OWN Firework Burst flare (`burst_rockets`, six payoff
    bursts) on the same frame instead of a shape: the busiest thing this
    effect does today, and the volley this row's burst is modelled on.

    W4.3's own options. `no_burst=True` tells the shape exactly as the
    engine does — so THE HUSH runs, the lives are capped, the clock turns —
    but stubs the shaped burst out, which is the only way to read the
    ORDINARY light left on the canvas at the word without guessing which
    cells were whose. `poke_at` writes a `burst_rockets` flare that many
    frames after the edge (the hush must drop it). `audio_cls` swaps the
    feed (Beat120Audio for the canvas runs), and `stop_at_hold_end` ends
    the run at the hold rather than rendering a release nothing reads."""
    import tempfile
    from fx import headless
    tmp = tmp or Path(tempfile.mkdtemp())
    _TAG[0] += 1
    tag = f"fwws{_TAG[0]}"
    form_s, hold_s, release_s = room_timing(energy, phrase_s)
    if form_override is not None:
        # a told form other than the room's own — the engine tells the time
        # LEFT to the word, so a long phrase gives a longer one than the
        # floor and a (contract-impossible) short one gives less
        form_s, release_s = float(form_override), 1.5 * float(form_override)
    cfg = dict(HIS_CFG)
    cfg.update(config or {})
    if size is not None:
        cfg["word_shape_size"] = size
    audio = audio_cls or (BusyAudio if busy else QuietAudio)

    async def main() -> ShapeRun:
        host, virtual = await _host(tmp, tag, crystal_mask(panel))
        run = ShapeRun(shape_id=shape_id, energy=energy, form_s=form_s,
                       hold_s=hold_s, release_s=release_s)
        cm = headless.fake_clock()
        clock = cm.__enter__()
        try:
            eff = headless.attach_effect(host, virtual, "fireworks", cfg)
            eff._rng = np.random.default_rng(seed)
            # count ORDINARY launches per frame: the rig wraps the effect's
            # own `_spawn_burst`, so "zero launches inside the hush" is
            # counted at the call rather than inferred from the picture
            spawned = [0]
            real_spawn = eff._spawn_burst

            def counting_spawn(*a, **kw):
                spawned[0] += 1
                return real_spawn(*a, **kw)

            eff._spawn_burst = counting_spawn
            if no_burst:
                eff._word_shape_burst = (
                    lambda *a, **kw: None)   # the canvas, with no shape on it
            form_frames = max(2, int(round(form_s / dt)))
            hold_frames = int(round(hold_s / dt))
            rel_frames = int(round(release_s / dt))
            total = (settle_frames + form_frames + hold_frames + rel_frames
                     + tail_frames)
            run.edge_frame = settle_frames
            run.word_frame = settle_frames + form_frames
            run.hold_end_frame = run.word_frame + hold_frames
            run.release_end_frame = run.hold_end_frame + rel_frames
            if stop_at_hold_end:
                total = run.hold_end_frame + 1
            seq = 0
            for i in range(total):
                if flare and i == settle_frames:
                    eff.update_config({"burst_rockets": 6})
                if poke_at is not None and i == settle_frames + poke_at:
                    eff.update_config({"burst_rockets": 6})
                if told and (i == settle_frames
                             or (second_word_at is not None and i
                                 == settle_frames + second_word_at)):
                    seq += 1
                    eff.update_config(wsk.keys_for(
                        shape_id, seq, form_s, hold_s, release_s,
                        max(wsk.LEVEL_FLOOR, energy)))
                spawned[0] = 0
                eff.audio_data_updated(audio(i))
                clock.advance(dt)
                t0 = time.perf_counter()
                out = virtual.assemble_frame()
                run.frame_ms.append((time.perf_counter() - t0) * 1000.0)
                if out is not None:
                    virtual.flush(out)
                frame = (np.asarray(out, dtype=np.float32).reshape(ROWS, COLS, 3)
                         / 255.0)
                run.frames.append(frame)
                run.state.append(eff.word_shape_state())
                bright = frame.max(axis=2)
                run.lit.append(int(((bright >= LIT) & panel.grid).sum()))
                run.canvas.append(int(((bright >= CANVAS_LIT)
                                       & panel.grid).sum()))
                run.launches.append(spawned[0])
                # W5.6: the shaped sparks' own speed and spread this frame
                wsi = np.flatnonzero(eff.p_wfade[:eff.n] > 0.0)
                if wsi.size:
                    pit = max(float(eff._ws_pitch), 1e-9)
                    sp = np.hypot(eff.p_vx[wsi], eff.p_vy[wsi]) / pit
                    rad = np.hypot(eff.p_x[wsi], eff.p_y[wsi]) / pit
                    run.ws_speed.append((float(sp.min()), float(sp.mean()),
                                         float(sp.max())))
                    run.ws_spread.append(float(rad.mean()))
                else:
                    run.ws_speed.append((0.0, 0.0, 0.0))
                    run.ws_spread.append(0.0)
                if (told and not no_burst and run.targets is None
                        and int(np.count_nonzero(eff.p_wfade[:eff.n] > 0.0))):
                    # THE LAUNCH FRAME (W4.3: no longer the edge). Its
                    # sparks are at the centre and their velocities still
                    # carry the targets.
                    run.launch_frame = i
                    held = np.flatnonzero(eff.p_wfade[:eff.n] > 0.0)
                    # the FLIGHT the burst was given: the time left to the
                    # word on the effect's own clock at the launch. A clock
                    # reading, not the solve — `_drag_span` re-derives the
                    # geometric sum from it independently.
                    span = _drag_span(eff, eff._ws_form - eff._ws_t, dt)
                    # target = where it was launched from + what the drag
                    # lets its launch velocity cover over the FLIGHT
                    run.targets = np.stack(
                        [eff.p_x[held] + eff.p_vx[held] * span,
                         eff.p_y[held] + eff.p_vy[held] * span], axis=1)
                    run.total_sparks = held.size
                    run.sparks_life_mean = float(eff.p_life[held].mean())
                    from fx.effects.fireworks import \
                        WORD_SHAPE_OUTLINE_BRIGHT
                    run.outline_sparks = int(np.count_nonzero(
                        eff.p_bright[held]
                        >= WORD_SHAPE_OUTLINE_BRIGHT - 1e-6))
                if told and i == run.word_frame and run.targets is not None:
                    held = np.flatnonzero(eff.p_wfade[:eff.n] > 0.0)
                    k = min(held.size, len(run.targets))
                    dx = (eff.p_x[held[:k]] - run.targets[:k, 0]) * eff.sx
                    dy = (eff.p_y[held[:k]] - run.targets[:k, 1]) * eff.sy
                    run.arrival_pitch = float(np.hypot(
                        dx * COLUMN_PITCH, dy * ROW_PITCH).max()) if k else 0.0
            return run
        finally:
            cm.__exit__(None, None, None)
            await host.shutdown()

    return asyncio.run(main())


def _drag_span(eff, flight_s: float, dt: float) -> float:
    """The distance one unit of launch speed covers over the FLIGHT under
    THE SHAPED SPARKS' OWN DRAG — `_word_shape_burst`'s own solve, re-derived
    here independently so the targets this script measures against are not
    read out of the effect's own working. Since W4.3 the flight is the time
    left to the word at the launch, not the whole told form; since W5.6 the
    half-life is `WORD_SHAPE_FLIGHT_HL_S` (0.65 s) rather than the effect's
    own `0.6 - 0.5 * drag`, which over a 2 s flight would saturate in its
    first fifth."""
    from fx.effects.fireworks import (WORD_SHAPE_FLIGHT_HL_S,
                                      WORD_SHAPE_MIN_FORM_S)
    step = float(min(max(dt, 1e-3), 0.1))
    form = max(float(flight_s), WORD_SHAPE_MIN_FORM_S)
    frames = max(2, int(round(form / step)))
    hl = max(WORD_SHAPE_FLIGHT_HL_S, 0.05)
    decel = 0.5 ** (step / hl)
    return step * (1.0 - decel ** frames) / max(1.0 - decel, 1e-9)


@dataclass
class ShapeMeasure:
    shape_id: str
    energy: float
    at: str                     # "word" or "mid-hold"
    outline_cells: int
    inside_cells: int
    coverage: float             # lit share of the outline cells
    fill_ratio: float           # the inside's mean brightness / the outline's
    outline_mean: float
    inside_mean: float


def cell_sets(shape, panel: Panel, size: float) -> tuple[np.ndarray, np.ndarray]:
    """The OUTLINE and FILL cell masks, from check_word_shapes' own
    measurement. FILL is 'inside and not on the outline band', so the two
    sets are disjoint and 'the inside's brightness' is the filling's."""
    _m, outline, inside = measure(shape, panel, size)
    return outline, inside & ~outline


def measure_frame(frame: np.ndarray, panel: Panel, outline: np.ndarray,
                  fill: np.ndarray) -> tuple[float, float, float, float]:
    bright = frame.max(axis=2)
    out_cells = outline & panel.grid
    fill_cells = fill & panel.grid
    lit = (bright >= LIT) & out_cells
    coverage = float(lit.sum()) / max(int(out_cells.sum()), 1)
    out_mean = float(bright[out_cells].mean()) if out_cells.any() else 0.0
    fill_mean = float(bright[fill_cells].mean()) if fill_cells.any() else 0.0
    ratio = fill_mean / out_mean if out_mean > 1e-9 else 0.0
    return coverage, ratio, out_mean, fill_mean


def white_share(frame: np.ndarray, panel: Panel) -> float:
    """The share of this frame's LIT real cells that are white-ish."""
    bright = frame.max(axis=2)
    lit = (bright >= LIT) & panel.grid
    if not lit.any():
        return 0.0
    rgb = frame[lit]
    white = ((rgb.min(axis=1) >= WHITE_MIN)
             & ((rgb.max(axis=1) - rgb.min(axis=1)) <= WHITE_SPREAD))
    return float(white.sum()) / float(lit.sum())


def measure_run(run: ShapeRun, panel: Panel, size: float) -> list[ShapeMeasure]:
    shape = word_shapes.get(run.shape_id)
    outline, fill = cell_sets(shape, panel, size)
    out_n, fill_n = int((outline & panel.grid).sum()), int((fill & panel.grid).sum())
    mid_hold = (run.word_frame + run.hold_end_frame) // 2
    out = []
    for label, idx in (("word", run.word_frame), ("mid-hold", mid_hold)):
        cov, ratio, om, fm = measure_frame(run.frames[idx], panel, outline, fill)
        out.append(ShapeMeasure(run.shape_id, run.energy, label, out_n, fill_n,
                                cov, ratio, om, fm))
    return out


def panel_light(frame: np.ndarray, panel: Panel) -> float:
    """The panel's own MEAN LIGHT: the mean luminance (peak channel) over
    his real cells, in 0..1."""
    return float(frame.max(axis=2)[panel.grid].mean())


def shape_windows(run: "ShapeRun", n_frames: int) -> list:
    """The four stretches of the shape, as (name, first, last) frame
    ranges: THE DIM COMING IN and the quiet with it (the edge to the
    launch), THE FLIGHT (the launch to the word), THE HOLD, and THE
    RELEASE — over which the shape breaks apart and the ordinary fireworks
    come back up (W5.6; W4.3's own first stretch was the panel emptying)."""
    launch = run.launch_frame if run.launch_frame >= 0 else run.word_frame
    end = min(run.release_end_frame, n_frames - 1)
    out = []
    for name, a, b in (("the dim comes in", run.edge_frame, launch),
                       ("the flight", launch, run.word_frame),
                       ("the hold", run.word_frame, run.hold_end_frame),
                       ("the release", run.hold_end_frame, end)):
        out.append((name, a, max(b, a + 1)))
    return out


def light_jumps(run: "ShapeRun", panel: Panel, windows: list) -> dict:
    """THE "NOTHING JUMPS" BAR, READ ON LIGHT RATHER THAN ON A LIT COUNT
    (W4.3). W1.2's own bar is the frame-to-frame change in LIT CELLS as a
    share of the lit count, and the hush makes that form arithmetically
    unreachable: it drives the lit count to ZERO on purpose, so the
    denominator vanishes and the first spark of the burst is an unbounded
    relative change. That number is still printed — a bar is not quietly
    dropped — but what it measures there is the threshold, not a jump.

    So the bar is asserted on the panel's own MEAN LIGHT: the largest
    one-frame change in it over each window, against THE EFFECT'S OWN
    ORDINARY MAXIMUM — row W1.3's own wording for this bar — which is the
    SAME SEED's untold worst over the whole shape's span. Per-window untold
    numbers are printed beside it, but the span is what the bar is read
    against, deliberately: the hush MOVES when the effect's busiest frames
    happen (the release's return lands on an emptied panel instead of a
    full one), so holding each stretch to the untold's worst in that same
    stretch would compare a shifted show against an unshifted one. A smooth
    fade from a full panel to a dark one has a steepest frame whatever its
    length; what says it is not a jump is that the steepest frame is no
    steeper than the ones this effect already renders."""
    light = np.array([panel_light(f, panel) for f in run.frames])
    out = {}
    for name, a, b in windows:
        b = min(b, len(light) - 1)
        d = light[a + 1:b + 1] - light[a:b]
        out[name] = float(np.abs(d).max()) if d.size else 0.0
    return out


def band_contrast(frame: np.ndarray, panel: Panel,
                  outline: np.ndarray) -> tuple[float, float, float]:
    """W4.3's contrast bar, the Fish `band_contrast` pattern
    (scripts/check_fish_word_shape.py:359): the share of the shape's own
    OUTLINE BAND cells that are actually LIGHT (above BAND_LIT_LO, and
    above BAND_LIT_HI), and the band's mean luminance over the rest of his
    real panel's.

    A ">= LIT" share is vacuous the moment anything else is trailing — the
    whole reason this row exists is that the room's own bursts light the
    band too. What a viewer sees is the band standing out from what is
    around it, so the ratio is the number that separates "the shape is
    brighter here" from "the panel is lit everywhere"."""
    lum = frame.max(axis=2)
    band = outline & panel.grid
    rest = panel.grid & ~outline
    b, r = lum[band], lum[rest]
    return (float((b >= BAND_LIT_LO).mean()) if b.size else 0.0,
            float((b >= BAND_LIT_HI).mean()) if b.size else 0.0,
            float(b.mean() / max(float(r.mean()), 1e-9)) if b.size else 0.0)


def render_graded(panel: Panel, frame: np.ndarray,
                  outline: np.ndarray) -> str:
    """The frame GRADED BY LUMINANCE on the real mask, the measurement
    discipline every wave-4 row inherits from the W1.4 Fish review: `.`
    dark, `-` below 64/255, `+` below 128/255, `#` at or above it; an
    outline-band cell is drawn in upper case (`#`/`+`) and the rest in
    lower (`*`/`:`) so the band is readable without a second picture."""
    lum = frame.max(axis=2)
    lines = []
    for row in range(panel.rows):
        chars = []
        for col in range(panel.cols):
            if not panel.grid[row, col]:
                chars.append(" ")
                continue
            v = lum[row, col]
            on_band = bool(outline[row, col])
            if v < LIT:
                chars.append(".")
            elif v < BAND_LIT_LO:
                chars.append("-")
            elif v < BAND_LIT_HI:
                chars.append("+" if on_band else ":")
            else:
                chars.append("#" if on_band else "*")
        lines.append("".join(chars).rstrip())
    return "\n".join(lines)


def render_ascii(panel: Panel, frame: np.ndarray, outline: np.ndarray) -> str:
    """The rendered frame on the real mask: `#` a lit outline cell, `o` a lit
    cell elsewhere, `-` an unlit outline cell, `.` an unlit real cell."""
    bright = frame.max(axis=2)
    lines = []
    for row in range(panel.rows):
        chars = []
        for col in range(panel.cols):
            if not panel.grid[row, col]:
                chars.append(" ")
            elif bright[row, col] >= LIT:
                chars.append("#" if outline[row, col] else "o")
            else:
                chars.append("-" if outline[row, col] else ".")
        lines.append("".join(chars).rstrip())
    return "\n".join(lines)


COVERAGE_BAR = 0.70
FILL_BAR = 0.70
SIM = {  # the plan's simulation: coverage / fill ratio, quiet then loud
    "heart": ((0.72, 0.46), (0.87, 0.47)),
    "star": ((0.76, 0.65), (0.86, 0.65)),
    "diamond": ((0.81, 0.50), (0.90, 0.53)),
}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size-fraction", type=float, default=DEFAULT_SIZE_FRACTION)
    ap.add_argument("--shape", action="append", default=None,
                    help="measure only this shape (repeatable)")
    ap.add_argument("--energy", action="append", type=float, default=None,
                    help="measure only this Energy (repeatable)")
    ap.add_argument("--ascii", action="store_true",
                    help="draw the frame on the word on the real mask")
    ap.add_argument("--room-energy", type=float, default=0.8,
                    help="the Energy the busy-room runs are measured at")
    args = ap.parse_args()

    panel = load_panel()
    size = args.size_fraction
    shapes = args.shape or list(word_shapes.SHAPES)
    energies = args.energy or [0.2, 0.8]
    print(f"crystal-mapper: {panel.rows}x{panel.cols}, "
          f"{int(panel.grid.sum())} real cells; SIZE {size}; "
          f"{1 / DT:.0f} fps; lit >= {LIT:.3f}")
    print(f"his Fireworks V2 Matrix entry, spawn_rate "
          f"{HIS_CFG['spawn_rate']} (beat bursts only), drag "
          f"{HIS_CFG['drag']}, blob_size {HIS_CFG['blob_size']}\n")

    # ── THE CLARITY BAR, on the shape itself ──────────────────────────────
    # Measured with NO ordinary show underneath, which is a real state of
    # his scene and not a convenience: at spawn_rate 0 a quiet passage
    # launches nothing at all, so this is the shape as his room draws it.
    # The bar is about the SHAPE's own picture; what the room's own beat
    # bursts add on top is measured separately below, because a burst that
    # happens to land inside the outline is not the shape failing to be one.
    print("THE CLARITY BAR — the shape alone (no ordinary show underneath)")
    header = (f"{'shape':9s} {'energy':>6s} {'at':>9s} {'sparks':>7s} "
              f"{'outline':>8s} {'fill':>5s} {'coverage':>9s} {'bar':>5s} "
              f"{'ratio':>6s} {'bar':>5s} {'sim':>12s}")
    print(header)
    print("-" * len(header))
    failures: list[str] = []
    # numbers ABOVE THE PLAN'S LETTER, printed rather than moved (see the
    # white note below). A bar this script cannot honestly call passed is
    # neither quietly redefined nor quietly dropped: it is reported here.
    reported: list[str] = []
    quiet_runs: dict[tuple[str, float], ShapeRun] = {}
    for shape_id in shapes:
        for energy in energies:
            run = run_shape(panel, shape_id, energy, size=size, busy=False,
                            settle_frames=10)
            quiet_runs[(shape_id, energy)] = run
            sim = SIM.get(shape_id)
            sim_at = sim[0 if energy < 0.5 else 1] if sim else None
            for m in measure_run(run, panel, size):
                cov_ok = m.coverage >= COVERAGE_BAR
                fill_ok = m.fill_ratio <= FILL_BAR
                sim_txt = (f"{sim_at[0]:.0%}/{sim_at[1]:.2f}" if sim_at
                           else "-")
                print(f"{m.shape_id:9s} {m.energy:6.2f} {m.at:>9s} "
                      f"{run.total_sparks:7d} {m.outline_cells:8d} "
                      f"{m.inside_cells:5d} "
                      f"{m.coverage:8.1%} {'ok' if cov_ok else 'FAIL':>5s} "
                      f"{m.fill_ratio:6.2f} {'ok' if fill_ok else 'FAIL':>5s} "
                      f"{sim_txt:>12s}")
                if m.at == "word":
                    if not cov_ok:
                        failures.append(
                            f"{m.shape_id} at Energy {m.energy}: the sparks "
                            f"light {m.coverage:.1%} of the outline cells on "
                            f"the word (bar {COVERAGE_BAR:.0%})")
                    if not fill_ok:
                        failures.append(
                            f"{m.shape_id} at Energy {m.energy}: the inside "
                            f"is {m.fill_ratio:.2f} of the outline's "
                            f"brightness (bar {FILL_BAR:.2f}) — a blob, not "
                            f"an outline")
    print("\ncoverage = the share of the shape's OUTLINE cells (real cells "
          "within one cell pitch\n  of the outline) that are lit; ratio = "
          "the mean brightness of the FILL cells\n  (real cells deeper than "
          "one pitch inside) over the outline cells'. Both cell\n  sets are "
          "scripts/check_word_shapes.py's own, the denominators "
          "tests/test_word_shapes.py pins.")

    print("\nARRIVAL — the worst spark's distance from the target it was "
          "launched at, on the word (in real-cell pitches; bar: 1.0)")
    for (shape_id, energy), run in quiet_runs.items():
        bad = run.arrival_pitch > 1.0
        share = run.outline_sparks / max(run.total_sparks, 1)
        print(f"  {shape_id:9s} energy {energy:.2f}: "
              f"{run.arrival_pitch:.3f} pitches  "
              f"{'FAIL' if bad else 'ok'}   "
              f"{run.total_sparks} sparks, {run.outline_sparks} on the "
              f"outline ({share:.0%}, told 70%), form {run.form_s:.2f}s "
              f"hold {run.hold_s:.2f}s release {run.release_s:.2f}s")
        if bad:
            failures.append(f"{shape_id} at Energy {energy}: a spark is "
                            f"{run.arrival_pitch:.2f} cell pitches from its "
                            f"target on the word")

    print("\nTHE HANG — shaped sparks alive through the shape, and the form "
          "fraction on the word")
    for (shape_id, energy), run in quiet_runs.items():
        mid = (run.word_frame + run.hold_end_frame) // 2
        end = min(run.release_end_frame, len(run.frames) - 1)
        print(f"  {shape_id:9s} energy {energy:.2f}: "
              f"edge {run.state[run.edge_frame]['sparks']:3d} -> "
              f"word {run.state[run.word_frame]['sparks']:3d} -> "
              f"mid-hold {run.state[mid]['sparks']:3d} -> "
              f"release end {run.state[end]['sparks']:3d}; "
              f"form fraction on the word "
              f"{run.state[run.word_frame]['form_fraction']:.3f}")

    # ── W5.6: THE FLIGHT'S OWN SPEED CURVE ───────────────────────────────
    # "Slow the burst by 60% so we can see the blobs moving out to the
    # outline, and then decelerating to almost a stop, but not quite a
    # stop." Read on the sparks themselves: their mean speed at a quarter,
    # a half, three quarters and all of the flight. The bar is SHAPE, not a
    # number he gave — monotonically falling, and still moving at the word.
    from fx.effects import fireworks as FXM
    print(f"\nTHE FLIGHT'S SPEED CURVE (W5.6) — the shaped sparks' own mean "
          f"speed in real cell pitches a second, at 25/50/75/100% of the "
          f"{FXM.WORD_SHAPE_FLIGHT_S:.1f} s flight.")
    print(f"  His ask was a SPEED: \"slow the burst by 60%\" = x0.4, so "
          f"W4.3's 0.8 s flight became {FXM.WORD_SHAPE_FLIGHT_S:.1f} s. The "
          f"deceleration is the shaped sparks' OWN velocity half-life\n"
          f"  (WORD_SHAPE_FLIGHT_HL_S {FXM.WORD_SHAPE_FLIGHT_HL_S:.2f} s, "
          f"about a third of the flight) rather than this effect's "
          f"{0.6 - 0.5 * HIS_CFG['drag']:.3f} s at his drag "
          f"{HIS_CFG['drag']}, which over a\n  2 s flight would land every "
          f"spark in its first fifth and leave it sitting. Bars: falling all "
          f"the way, and NOT stopped at the word.")
    head_f = (f"{'shape':9s} {'energy':>6s} {'25%':>8s} {'50%':>8s} "
              f"{'75%':>8s} {'arrival':>8s} {'kept':>7s} {'falling':>8s} "
              f"{'moving':>7s}")
    print(head_f)
    print("-" * len(head_f))
    for (shape_id, energy), run in quiet_runs.items():
        launch = run.launch_frame if run.launch_frame >= 0 else run.word_frame
        # 100% of the flight is its LAST frame — the word's own frame is
        # already the hang, where WORD_SHAPE_DRIFT_KEEP has taken 4% of the
        # arrival speed; both are printed, the curve read on the flight
        span = run.word_frame - launch
        marks = [launch + int(round(f * span)) for f in (0.25, 0.5, 0.75)]
        marks.append(max(launch, run.word_frame - 1))
        means = [run.ws_speed[min(m, len(run.ws_speed) - 1)][1]
                 for m in marks]
        kept = run.ws_speed[min(run.word_frame,
                                len(run.ws_speed) - 1)][1]
        falling = all(b < a for a, b in zip(means, means[1:]))
        moving = means[-1] > 0.0 and kept > 0.0
        print(f"{shape_id:9s} {energy:6.2f} "
              + " ".join(f"{v:8.2f}" for v in means)
              + f" {kept:7.3f} {'ok' if falling else 'FAIL':>8s} "
              f"{'ok' if moving else 'FAIL':>7s}")
        if not falling:
            failures.append(f"{shape_id} at Energy {energy}: the flight's "
                            f"speed curve does not fall all the way "
                            f"({means})")
        if not moving:
            failures.append(f"{shape_id} at Energy {energy}: the sparks are "
                            f"stopped dead on the word")

    # ── W5.6: THE RESIDUAL DRIFT, AND THE BREAK-APART ────────────────────
    # "decelerating to almost a stop, but not quite a stop. The blobs should
    # always be slightly drifting" ... "at the end, the blobs should lightly
    # break apart and fade out". So: the SLOWEST shaped spark's speed over
    # the hold (never zero for more than a frame), and what the release does
    # to the drift and to the outline's own radius.
    print(f"\nTHE RESIDUAL DRIFT AND THE BREAK-APART (W5.6) — "
          f"WORD_SHAPE_DRIFT_KEEP {FXM.WORD_SHAPE_DRIFT_KEEP:.2f} of the "
          f"arrival speed, then a mean-reverting walk of "
          f"WORD_SHAPE_DRIFT {FXM.WORD_SHAPE_DRIFT:.2f}\n  cell pitches a "
          f"second (half-life {FXM.WORD_SHAPE_DRIFT_HL_S:.1f} s), growing to "
          f"WORD_SHAPE_BREAK_DRIFT {FXM.WORD_SHAPE_BREAK_DRIFT:.2f} outward-"
          f"and-random over the release.\n  Bars: no shaped spark's speed is "
          f"EXACTLY zero on any frame of the hold, and the sparks' own mean "
          f"radius GROWS over the release.")
    print(f"  THE BREAK-APART IS READ ON THE COMPLETE POPULATION, not at the "
          f"release's end: WORD_SHAPE_FADE_FRAC "
          f"{FXM.WORD_SHAPE_FADE_FRAC} guarantees that NO spark is gone "
          f"before\n  "
          f"{FXM.WORD_SHAPE_FADE_FRAC[0]:.0%} of the release, so the frame "
          f"just inside that is the same sparks as the hold's end and the "
          f"radius there is a travel rather than a survivorship\n  "
          f"effect. The last-lit frame's radius is printed beside it with "
          f"that caveat — by then a handful of sparks are left and WHICH "
          f"ones is random.")
    head_d = (f"{'shape':9s} {'energy':>6s} {'hold min':>9s} "
              f"{'hold mean':>10s} {'frozen':>7s} {'rel mean':>9s} "
              f"{'rel end':>8s} {'radius (all lit)':>18s} {'apart':>6s} "
              f"{'last lit':>16s}")
    print(head_d)
    print("-" * len(head_d))
    for (shape_id, energy), run in quiet_runs.items():
        hold = slice(run.word_frame, run.hold_end_frame + 1)
        rel_end = min(run.release_end_frame, len(run.ws_speed) - 1)
        # the LAST FRAME THAT STILL HAS A SHAPED SPARK: a frame past the
        # last one is empty, and an empty frame's radius would read 0 and
        # make the break-apart look like a collapse
        lit = [i for i in range(run.hold_end_frame, rel_end + 1)
               if run.ws_spread[i] > 0.0]
        last = lit[-1] if lit else run.hold_end_frame
        rel = slice(run.hold_end_frame + 1, last + 1)
        hold_sp = run.ws_speed[hold] or [(0.0, 0.0, 0.0)]
        rel_sp = run.ws_speed[rel] or [(0.0, 0.0, 0.0)]
        frozen = sum(1 for v in hold_sp if v[0] <= 0.0)
        hold_min = min(v[0] for v in hold_sp)
        hold_mean = float(np.mean([v[1] for v in hold_sp]))
        rel_mean = float(np.mean([v[1] for v in rel_sp]))
        rel_last = run.ws_speed[last][1]
        r0 = run.ws_spread[run.hold_end_frame]
        # the last frame on which EVERY spark is still lit: no spark's own
        # fade window is shorter than WORD_SHAPE_FADE_FRAC[0] of the
        # release, so up to there the population is the hold's end's
        full = min(
            run.hold_end_frame
            + int(FXM.WORD_SHAPE_FADE_FRAC[0] * run.release_s / DT) - 1,
            len(run.ws_spread) - 1)
        r_full = run.ws_spread[full]
        r1 = run.ws_spread[last]
        apart = r_full > r0
        print(f"{shape_id:9s} {energy:6.2f} {hold_min:9.3f} "
              f"{hold_mean:10.3f} "
              f"{('FAIL' if frozen else 'ok'):>7s} {rel_mean:9.3f} "
              f"{rel_last:8.3f} "
              f"{f'{r0:.3f}->{r_full:.3f}':>18s} "
              f"{'ok' if apart else 'FAIL':>6s} "
              f"{f'{r1:.2f}':>16s}")
        if frozen:
            failures.append(f"{shape_id} at Energy {energy}: a shaped spark "
                            f"was exactly stopped on {frozen} frames of the "
                            f"hold")
        if not apart:
            failures.append(f"{shape_id} at Energy {energy}: the shape did "
                            f"not break apart over the release "
                            f"({r0:.3f} -> {r_full:.3f} pitches over the "
                            f"complete population)")
    print(f"  hold min/mean and rel mean/end are the slowest and the mean "
          f"shaped spark's speed, in cell pitches a second; radius is the "
          f"sparks' own mean distance from\n  the centre, at the hold's end "
          f"and on the last frame all of them are still lit, in the same "
          f"pitches — the break-apart's own measure.")

    # ── W5.6: THE DIM BAR (W4.3's dark canvas, retired by his verdict) ────
    # His second verdict's own words: "The background doesn't need to be
    # clear of other fireworks, just they need to be dimmer, so fading out
    # already." W4.3's bar was a DARK one — the share of his real cells
    # still carrying ordinary light on the word, measured at 0.00%. That bar
    # is exactly what he overturned, so the measure is now a RATIO: the
    # ordinary LIGHT on the panel at the word against the SAME SEED's untold
    # frame. Bounded both ways — dim enough, and never a 0% bar.
    real_cells = int(panel.grid.sum())
    print(f"\nTHE DIM BAR (W5.6, replacing W4.3's dark canvas) — ORDINARY "
          f"(non-shaped) LIGHT still on the panel ON THE WORD, as a share of "
          f"the SAME SEED's UNTOLD light.")
    print(f"  {CANVAS_SEEDS} seeds at Energy 1.0, 120 bpm, HIS SCENE AT ITS "
          f"BUSIEST (beat_burst {WORST_CFG['beat_burst']} x burst_size "
          f"{WORST_CFG['burst_size']} a beat, each spark living "
          f"~{HIS_CFG['burst_life']} s,\n  max_blobs "
          f"{HIS_CFG['max_blobs']}). The shape is TOLD exactly as the engine "
          f"tells it (the 0.25 s quiet running, the lives capped, the dim "
          f"ramped, the clock\n  turning) and the shaped burst itself is "
          f"stubbed out, which is the only way to read the ORDINARY light "
          f"without guessing which cells were whose.\n  Light is the mean "
          f"luminance over his {real_cells} real cells, not a cell count: a "
          f"share of cells above a threshold cannot SEE a cell that merely "
          f"went\n  dimmer, which is the whole of what this row does. Bars: "
          f"<= {DIM_BAR:.0%} of the untold light POOLED over the seeds, and "
          f"> 0 on every one of them (a DIM\n  bar, never a 0% one); and "
          f"zero ordinary launches inside the "
          f"{FXM.WORD_SHAPE_HUSH_S:.2f} s quiet.")
    print(f"  THE BAR IS THE POOLED RATIO, and the per-seed worst is "
          f"REPORTED BESIDE IT RATHER THAN ASSERTED. One frame of one seed "
          f"compares two shows whose last\n  beat landed differently — the "
          f"quiet withholds a beat's launches on some seeds and not others "
          f"— so a single seed's ratio is a noisy\n  estimate of a "
          f"{FXM.WORD_SHAPE_BACKGROUND_DIM:.2f} dim rather than a "
          f"measurement of it. Pooled over {CANVAS_SEEDS} seeds the "
          f"estimate IS the dim; the worst single seed is printed,\n  and "
          f"is above the {DIM_BAR:.0%} letter.")
    ratios, lights, twin_lights = [], [], []
    shares, twin_shares, launch_counts = [], [], []
    for seed in range(1, CANVAS_SEEDS + 1):
        kw = dict(energy=1.0, config=WORST_CFG, audio_cls=Beat120Audio,
                  settle_frames=60, stop_at_hold_end=True, seed=seed,
                  size=size)
        run = run_shape(panel, shapes[0], no_burst=True, **kw)
        twin = run_shape(panel, shapes[0], told=False, **kw)
        light = panel_light(run.frames[run.word_frame], panel)
        twin_light = panel_light(twin.frames[twin.word_frame], panel)
        lights.append(light)
        twin_lights.append(twin_light)
        ratios.append(light / max(twin_light, 1e-9))
        shares.append(run.canvas[run.word_frame] / max(real_cells, 1))
        twin_shares.append(twin.canvas[twin.word_frame] / max(real_cells, 1))
        # the QUIET is now the 0.25 s in front of the launch, not the whole
        # stretch to the hold's end: that is where zero launches is the bar
        launch_f = (run.launch_frame if run.launch_frame >= 0
                    else run.word_frame
                    - int(round(FXM.WORD_SHAPE_FLIGHT_S / DT)))
        quiet_from = max(run.edge_frame,
                         launch_f - int(round(FXM.WORD_SHAPE_HUSH_S / DT)))
        launch_counts.append(sum(run.launches[quiet_from:launch_f]))
    worst = max(ratios)
    least = min(ratios)
    pooled = sum(lights) / max(sum(twin_lights), 1e-9)
    print(f"  the ordinary light on the word, POOLED over the seeds: "
          f"{pooled:.1%} of the untold light  "
          f"{'FAIL' if pooled > DIM_BAR else 'ok'}  "
          f"(WORD_SHAPE_BACKGROUND_DIM is "
          f"{FXM.WORD_SHAPE_BACKGROUND_DIM:.2f})")
    print(f"  per seed: worst {worst:.1%}, median "
          f"{float(np.median(ratios)):.1%}, least {least:.1%}  "
          + ('(the worst ABOVE the letter — reported)'
             if worst > DIM_BAR else 'ok'))
    print(f"  in absolute light: told median "
          f"{float(np.median(lights)):.4f} against untold median "
          f"{float(np.median(twin_lights)):.4f} (mean luminance over the "
          f"real cells)")
    print(f"  ... and it is still a SHOW: told lit-cell share (W4.3's own "
          f"measure at >= {CANVAS_LIT:.3f}) median "
          f"{float(np.median(shares)):.2%} of real cells against the same "
          f"seeds untold's {float(np.median(twin_shares)):.2%}  "
          f"{'FAIL (dark, not dim)' if least <= 0.0 else 'ok'}")
    print(f"  ordinary launches inside the quiet "
          f"({FXM.WORD_SHAPE_HUSH_S:.2f} s before the launch): "
          f"{max(launch_counts)} at worst over {CANVAS_SEEDS} seeds  "
          f"{'FAIL' if max(launch_counts) else 'ok'}")
    if pooled > DIM_BAR:
        failures.append(
            f"the ordinary light on the word is {pooled:.1%} of the untold "
            f"light pooled over {CANVAS_SEEDS} seeds (bar {DIM_BAR:.0%})")
    if worst > DIM_BAR:
        reported.append(
            f"THE DIM BAR AT ITS WORST SEED: the ordinary light on the word "
            f"reads {worst:.1%} of the untold frame's at the worst of "
            f"{CANVAS_SEEDS} seeds, above the row's {DIM_BAR:.0%} letter "
            f"(pooled {pooled:.1%}, median "
            f"{float(np.median(ratios)):.1%}) — one frame of one seed "
            f"compares two shows whose last beat landed differently, the "
            f"quiet having withheld it on one of them")
    if least <= 0.0:
        failures.append(
            "the panel went DARK rather than dim on at least one seed — "
            "his verdict asks for dimmer, not clear")
    if max(launch_counts):
        failures.append(
            f"{max(launch_counts)} ordinary launches happened inside the "
            f"{FXM.WORD_SHAPE_HUSH_S:.2f} s quiet (bar: zero)")

    # ── W4.3: THE CONTRAST BAR ────────────────────────────────────────────
    print(f"\nTHE CONTRAST BAR (W4.3) — the shape's own OUTLINE BAND against "
          f"the rest of his real panel, graded by LUMINANCE rather than by a "
          f"\">= {LIT:.3f}\" share,\n  which is vacuous once anything is "
          f"trailing (the W1.4 Fish review's discipline, carried to every "
          f"wave-4 row). The shape alone, and over his live\n  show with the "
          f"SAME-SEED untold twin beside it. Bar: band/rest luminance ratio "
          f">= {CONTRAST_BAR:.1f}.")
    head3 = (f"{'shape':9s} {'energy':>6s} {'where':>10s} {'at':>9s} "
             f"{'band>=64':>9s} {'band>=128':>10s} {'ratio':>7s} "
             f"{'bar':>5s} {'twin ratio':>11s}")
    print(head3)
    print("-" * len(head3))
    loud_runs: dict[tuple[str, float], ShapeRun] = {}
    for shape_id in shapes:
        outline, _fill = cell_sets(word_shapes.get(shape_id), panel, size)
        for energy in list(energies) + [1.0]:
            key = (shape_id, energy)
            if key in quiet_runs:
                run = quiet_runs[key]
            else:
                run = run_shape(panel, shape_id, energy, size=size,
                                busy=False, settle_frames=10)
                loud_runs[key] = run
            mid = (run.word_frame + run.hold_end_frame) // 2
            for label, idx in (("word", run.word_frame), ("mid-hold", mid)):
                lo_s, hi_s, ratio = band_contrast(
                    run.frames[idx], panel, outline)
                ok = ratio >= CONTRAST_BAR
                print(f"{shape_id:9s} {energy:6.2f} {'alone':>10s} "
                      f"{label:>9s} {lo_s:8.1%} {hi_s:9.1%} {ratio:7.2f} "
                      f"{'ok' if ok else 'FAIL':>5s} {'-':>11s}")
                if not ok:
                    failures.append(
                        f"{shape_id} at Energy {energy} ({label}, the shape "
                        f"alone): the band is {ratio:.2f}x the rest of the "
                        f"panel (bar {CONTRAST_BAR:.1f})")

    print("\nNO WHITE, THE SHAPE ALONE — the highest share of its lit cells "
          "that are white-ish (bar: none at all). W4.3 RE-MEASURES THIS AT "
          "ENERGY 1.0\n  for all three shapes, because 150 sparks overlap "
          "deeper on the outline than W1.2's 100 did: if it rises, "
          "WORD_SHAPE_GRAD_SPAN and\n  WORD_SHAPE_LAUNCH_PITCH are the "
          "levers, and the trade is theirs — a narrower gradient slice is "
          "less of his colour set on the shape.")
    for (shape_id, energy), run in list(quiet_runs.items()) + \
            list(loud_runs.items()):
        worst = max(white_share(run.frames[i], panel)
                    for i in range(run.edge_frame,
                                   min(run.release_end_frame + 1,
                                       len(run.frames))))
        print(f"  {shape_id:9s} energy {energy:.2f}: {worst:.2%} "
              f"{'FAIL' if worst > 0.0 else 'ok'}")
        if worst > 0.0:
            failures.append(f"{shape_id} at Energy {energy}: {worst:.2%} of "
                            f"the shape's own lit cells are white")

    # ── THE SAME SHAPE OVER HIS LIVE SHOW ─────────────────────────────────
    room_e = args.room_energy
    # W4.3 also re-reads the live show at ENERGY 1.0 — 150 sparks overlap
    # deeper on the outline than W1.2's 100 did, and his verdict's own case
    # is the loud one
    room_energies = sorted({room_e, 1.0})
    print(f"\nOVER A LIVE SHOW (busy music, Energy "
          f"{', '.join(f'{e:g}' for e in room_energies)}) — the shape "
          f"beside the effect's own beat bursts. Two baselines over the SAME "
          f"frames: an UNTOLD\n  TWIN (the same show, no shape) and the "
          f"effect's own FIREWORK BURST FLARE on the same frame (six payoff "
          f"bursts — the\n  busiest thing it does today, and the volley this "
          f"burst is modelled on). 'No whiter than the effect's own busy "
          f"frames'\n  is measured against that flare; the twin says what "
          f"the room alone was doing.")
    light_rows: list = []
    head2 = (f"{'shape':9s} {'energy':>6s} {'coverage':>9s} {'ratio':>6s} "
             f"{'band':>6s} "
             f"{'twin':>6s} {'white':>7s} {'twin':>7s} {'flare':>7s} "
             f"{'jump':>6s} {'twin':>6s} {'p50 ms':>8s} {'twin':>7s}")
    print(head2)
    print("-" * len(head2))
    for shape_id, room_e in [(sh, e) for e in room_energies for sh in shapes]:
        run = run_shape(panel, shape_id, room_e, size=size)
        twin = run_shape(panel, shape_id, room_e, size=size, told=False)
        outline, fill = cell_sets(word_shapes.get(shape_id), panel, size)
        cov, ratio, _om, _fm = measure_frame(
            run.frames[run.word_frame], panel, outline, fill)
        lo, hi = run.edge_frame, min(run.release_end_frame + 1,
                                     len(run.frames))
        white = max(white_share(run.frames[i], panel) for i in range(lo, hi))
        white_twin = max(white_share(twin.frames[i], panel)
                         for i in range(lo, hi))
        flare = run_shape(panel, shape_id, room_e, size=size, told=False,
                          flare=True)
        white_flare = max(white_share(flare.frames[i], panel)
                          for i in range(lo, hi))
        jump = _worst_jump(run)
        jump_twin = _worst_jump(twin)
        # W4.3: the band's own contrast over the live show, and the SAME
        # SEED untold beside it — the room's bursts light the band too, so
        # the told/untold pair is the only honest read of it
        _lo_s, _hi_s, band = band_contrast(
            run.frames[run.word_frame], panel, outline)
        _tl, _th, band_twin = band_contrast(
            twin.frames[twin.word_frame], panel, outline)
        p50 = float(np.median(
            run.frame_ms[run.word_frame:run.hold_end_frame + 1]))
        p50_twin = float(np.median(
            twin.frame_ms[twin.word_frame:twin.hold_end_frame + 1]))
        print(f"{shape_id:9s} {room_e:6.2f} {cov:8.1%} {ratio:6.2f} "
              f"{band:6.2f} {band_twin:6.2f} {white:6.2%} "
              f"{white_twin:6.2%} {white_flare:6.2%} {jump:5.1%} "
              f"{jump_twin:5.1%} {p50:7.2f} {p50_twin:6.2f}")
        if white > max(white_flare, white_twin) + 1e-9:
            reported.append(
                f"{shape_id} over a live show at Energy {room_e:g}: "
                f"{white:.2%} of the lit cells "
                f"read white-ish at the worst frame, against the room "
                f"alone's {white_twin:.2%} and the effect's own Firework "
                f"Burst flare's {white_flare:.2%} over the same frames")
        if p50 - p50_twin > 1.0:
            failures.append(
                f"{shape_id} at Energy {room_e:g}: the shape holding "
                f"costs "
                f"{p50 - p50_twin:.2f} ms a frame (bar 1.0)")
        # W4.3: the "nothing jumps" bar, read on the panel's own MEAN
        # LIGHT over each of the shape's four stretches against the SAME
        # SEED untold, because the hush drives the lit count W1.2's own
        # ratio divides by to zero on purpose (light_jumps' docstring).
        wins = shape_windows(run, len(run.frames))
        told_j = light_jumps(run, panel, wins)
        twin_j = light_jumps(twin, panel, wins)
        # THE COMPARATOR is the effect's own ordinary maximum over the
        # whole SPAN, not each stretch's own — the hush MOVES when this
        # effect's busiest frames happen (the release's return lands on an
        # emptied panel instead of a full one), so a per-stretch comparison
        # would put a shifted show beside an unshifted one. Both are printed.
        twin_worst = max(twin_j.values())
        light_rows.append((f"{shape_id} {room_e:g}", told_j, twin_j,
                           twin_worst))
        for name in told_j:
            if told_j[name] > twin_worst + 1e-6:
                failures.append(
                    f"{shape_id} at Energy {room_e:g} over {name}: the "
                    f"panel's mean light moves {told_j[name]:.4f} in one "
                    f"frame, against this effect's own untold worst of "
                    f"{twin_worst:.4f} over the same span")
    print(f"\nNOTHING JUMPS (W4.3) — the largest ONE-FRAME change in the "
          f"panel's own MEAN LIGHT (0..1) over each of the shape's four "
          f"stretches,\n  beside the SAME SEED UNTOLD over the SAME frames. "
          f"W1.2's bar is the change in LIT CELLS as a share of the lit "
          f"count, and the hush\n  drives that denominator to ZERO on "
          f"purpose — the 'jump' column above is that number, which over a "
          f"hush measures the lit\n  threshold rather than a jump, so it is "
          f"printed and not asserted. A fade from a full panel to a dark one "
          f"has a steepest\n  frame whatever its length; what says it is "
          f"not a jump is that the steepest frame is no steeper than the "
          f"ones this effect\n  already renders.\n  BAR: at or under THIS "
          f"EFFECT'S OWN UNTOLD WORST OVER THE WHOLE SPAN ('own worst' "
          f"below) — not each stretch's own untold number, which is "
          f"printed\n  beside it but would compare a shifted show against "
          f"an unshifted one, the hush having MOVED when the busiest frames "
          f"happen.")
    head4 = (f"{'shape':13s} {'stretch':>18s} {'told':>8s} "
             f"{'untold here':>12s} {'own worst':>10s} {'bar':>5s}")
    print(head4)
    print("-" * len(head4))
    for shape_id, told_j, twin_j, twin_worst in light_rows:
        for name in told_j:
            ok = told_j[name] <= twin_worst + 1e-6
            print(f"{shape_id:13s} {name:>18s} {told_j[name]:8.4f} "
                  f"{twin_j[name]:12.4f} {twin_worst:10.4f} "
                  f"{'ok' if ok else 'FAIL':>5s}")

    print("\nwhite = the highest share of LIT real cells that are white-ish "
          "over the shape's own\n  frames (every channel >= "
          f"{WHITE_MIN}, within {WHITE_SPREAD} of each other). The shape "
          "alone lights\n  none at all (above); what shows here is additive "
          "mixing where one of the room's\n  own beat bursts crosses the "
          "standing shape — which is what the\n  effect already does to "
          "itself whenever two of its own fireworks share a cell inside "
          "the trail's\n  memory. IT IS REPORTED, NOT A BAR THIS SCRIPT "
          "CALLS PASSED: the block at the end has what was\n  measured "
          "about it, including the three composites that do NOT change "
          "it.\n"
          "band = the shape's own outline band's mean luminance over the "
          "rest of his real\n  panel's, told against the SAME SEED untold "
          "(the contrast bar above, read over a live\n  show; the room's "
          "own bursts light the band too, so the pair is the only honest "
          "read).\n"
          "jump = the largest frame-to-frame change in LIT CELLS over the "
          "form and over the\n  release, as a share of the lit count — "
          "W1.2's own form of the bar, PRINTED AND NOT\n  ASSERTED since "
          "W4.3, because the hush drives that denominator to zero on "
          "purpose;\n  the NOTHING JUMPS block below is the same bar read "
          "on the panel's own light.\n"
          "p50 = the median render ms a frame with the shape holding (bar: "
          "the twin + 1.0 ms).")

    if args.ascii:
        for (shape_id, energy), run in quiet_runs.items():
            outline, _fill = cell_sets(word_shapes.get(shape_id), panel, size)
            print(f"\n{shape_id} at Energy {energy} ON THE WORD "
                  f"(# lit outline, o lit elsewhere, - unlit outline, "
                  f". unlit real)")
            print(render_ascii(panel, run.frames[run.word_frame], outline))
        # W4.3: and the same frames GRADED BY LUMINANCE, at the word and at
        # mid-hold — the picture the contrast bar is read off
        for (shape_id, energy), run in list(quiet_runs.items()) + \
                list(loud_runs.items()):
            outline, _fill = cell_sets(word_shapes.get(shape_id), panel, size)
            mid = (run.word_frame + run.hold_end_frame) // 2
            for label, idx in (("ON THE WORD", run.word_frame),
                               ("AT MID-HOLD", mid)):
                print(f"\n{shape_id} at Energy {energy} {label}, GRADED BY "
                      f"LUMINANCE (band: # >= 128, + >= 64; elsewhere: "
                      f"* >= 128, : >= 64; - lit under 64, . dark)")
                print(render_graded(panel, run.frames[idx], outline))

    if reported:
        print("\nABOVE THE PLAN'S LETTER — reported, not moved. Each one "
              "is listed at the END of this block; what comes first is the "
              "standing\n  record of the OLDEST of them, so nobody "
              "re-chases it.\n"
              "\n  THE WHITE FRACTION OVER A LIVE SHOW (plan section 6's "
              "fifth bar: 'the white fraction during a shape is no higher "
              "than the\n  effect's own busy frames today'). The shape "
              "ALONE lights no white cell at all; this is where the room's "
              "own beat bursts cross the\n  standing shape. What was "
              "measured about it:\n"
              "    * not brightness — 1.63-2.01% at shaped-spark "
              "brightness 1.0, 0.8 and 0.65 alike;\n"
              "    * NOT the per-frame composite, which is the one that "
              "looks like the answer: summing, a per-channel\n      max "
              "and a per-cell winner-takes-all over two frames (the shaped "
              "sparks' own and the room's) all\n      give the heart the "
              "SAME 1.74%, and at most 0.23 points on the diamond. That "
              "two-pass version was\n      built, measured and NOT kept — "
              "it cost +0.2-0.4 ms p50 for that;\n"
              "    * the cause is `self.trail`, a channel-wise MAX over "
              "TIME: the shape's hue and a passing burst's\n      hue "
              "from a NEIGHBOURING frame, which no per-frame arithmetic "
              "reaches. Shortening the trail is no\n      lever either — "
              "`trail_decay` 0.27 -> 0.0 RAISES the share to 2.95-3.63%, "
              "the room's own lit cells\n      leaving the denominator "
              "faster than the washed-out ones leave the numerator.\n"
              "  The levers left are the Admiral's: accept it (the comet "
              "trail doing to a standing shape what it\n  already does "
              "wherever two of this effect's own fireworks share a cell), "
              "or change how it trails.\n"
              "  HIS RULING, 2026-11-17: option A, ship as built.\n"
              "  W4.3 RE-MEASURED IT with 150 sparks instead of 100, and "
              "THE HUSH CHANGED THE PICTURE rather than the sparks doing: "
              "the shape\n  alone still lights no white cell at any Energy, "
              "and over a live show the hush takes the room's own bursts "
              "away for the whole\n  form and hold, so most (shape, Energy) "
              "rows now sit AT OR BELOW the room's own number over the same "
              "frames. The untold\n  comparator itself rose (0.62% -> "
              "1.46%) because the 2.0 s form makes the measured window two "
              "and a half times longer and it\n  catches more of the room's "
              "own beats — an honest window change, stated rather than "
              "compared across windows.\n"
              "  W5.6 RE-MEASURED IT AGAIN, with 100 sparks and the DIM in "
              "place of the hush: the shape alone still lights no white "
              "cell at any\n  Energy — the two measured corrections that "
              "kept it there are WORD_SHAPE_FADE_IN_FRAC and "
              "WORD_SHAPE_LAUNCH_PITCH, see those two\n  constants — and "
              "over a live show the room is dimmed rather than withheld, so "
              "the told share sits at or below the room's own again.")
        print()
        for line in reported:
            print(f"  REPORTED: {line}")

    if failures:
        print()
        for line in failures:
            print(f"FAIL: {line}")
        print("\nFAIL")
        return 1
    print("\nPASS (with the number reported above)" if reported
          else "\nPASS")
    return 0


def _worst_jump(run: ShapeRun) -> float:
    """The largest frame-to-frame change in lit cells over the form and over
    the release, as a share of the lit count (plan section 6's third bar)."""
    worst = 0.0
    for a, b in ((run.edge_frame, run.word_frame),
                 (run.hold_end_frame, min(run.release_end_frame,
                                          len(run.lit) - 1))):
        for i in range(a, b):
            worst = max(worst, abs(run.lit[i + 1] - run.lit[i])
                        / max(run.lit[i], 1))
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
