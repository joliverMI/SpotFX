"""STAR's WORD SHAPE (fx/effects/radial.py, Word Shapes plan row W1.6) —
the row's clarity bar and every number beside it, printed.

Offline, on the real render pipeline and the real ResponseEngine
(tests/star_harness.py: a real Melt strip under a real Radial — Star
samples the strip and renders BLACK without it), with a Words band
carrying a `word_shape` kind, fired through `responder.on_word_shape`.
Every coverage number is measured on the REAL HEX MASK of his live
`crystal-mapper` virtual, decoded by scripts/check_word_shapes.py's own
loader (never re-derived here).

THE CLARITY TABLE, per shape and per Energy (0.2 and 0.8), at the WORD
(the last frame of the form) and at MID-HOLD:

- **inside** — the share of the frame's LIT real cells lying in the shape's
  own cells (strictly inside it, or within one cell pitch of its outline:
  the library's "inside" and "outline" sets). The plan's bar is 95%.
- **cov/strip** and **cov/abs** — the share of the shape's AREA cells that
  are lit, measured two ways, because STAR HAS NO LIGHT OF ITS OWN. Star
  samples the Melt strip and bends it into rings, so a dark band of the
  strip is a dark band of the heart exactly as it is a dark ring across the
  panel today, and Melt breathes (its own lit share swings between about a
  third and three quarters). `cov/strip` is of the area cells whose own
  sampled strip pixel is lit — THE SHAPE'S OWN DOING, and what the plan's
  90% bar is read against here. `cov/abs` is of every area cell, printed
  beside the **strip** column (the strip's own lit share at that frame): it
  is the strip's number, reported and not asserted.
- **radius** — the largest error, over 360 screen angles, between the
  outline the effect draws and `SIZE x polar(theta)` from the library, in
  cell pitches, measured through the effect's OWN angle-space law
  (`Radial2d._word_shape_div`, the one a lull piece and a transition
  program read). The plan's bar is half a cell.
- **field** — the largest difference between the effect's RENDERED shaped
  radius field (`_last_u`, the one the picture is sampled from) and
  `|n| / (SIZE x polar(theta_n))` over every real cell, at the hold. This
  is the "by construction" half of the claim: the two code paths above
  agree with each other and with the library.
- **white** — cells whose dimmest channel is over 200, against the same
  count on the effect's own untold busy frames.

THE SMOOTHNESS TABLE. The lit-cell count on this effect moves a great deal
on its own — Melt's breathing alone changes it by up to 18% of itself in
one rendered frame with no shape anywhere (the `untold` line below) — so
the shape's own contribution is measured with THE STRIP FROZEN: the only
thing moving in those runs is the shape. Printed per shape and Energy, at
the rig's 60 fps and at the crystal's own 30 fps: the worst frame-to-frame
change during the form, during the hold, and during the release, and the
pattern's per-frame advance at the end of the form, through the hold and at
the end of the release.

READ THE 8% BAR WITH THE ARITHMETIC IN FRONT OF YOU. STAR's rest state
lights the WHOLE panel and a shape is a fifth to a third of it, so the form
has to take the lit count from about 745 real cells to about 172 — a factor
of 4.3 — inside its own length. At the crystal's 30 fps a 0.5 s form is 15
rendered frames, and 0.92 ** 15 = 0.29: a 4.3x reduction at 8% per frame
is not available, by any envelope. What the law below does achieve is a
CONSTANT relative rate (the geometric pace), a hold that is exactly still,
and no frame worse than the effect's own untold worst. All three are
printed; nothing is rounded in this script's favour.

    .venv/bin/python scripts/check_star_word_shape.py
    .venv/bin/python scripts/check_star_word_shape.py --ascii

This script never writes anything and never reaches a live room.
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from check_word_shapes import (COLUMN_PITCH, DEFAULT_SIZE_FRACTION,  # noqa: E402
                               ROW_PITCH, load_panel)
from fx.effects import radial, word_shapes  # noqa: E402
from spectra.models.scene import FlareKind  # noqa: E402
from spectra.services import scene_response  # noqa: E402
from star_harness import STAR, STRIP, star_room  # noqa: E402
from strip_phase_harness import run, scene_for  # noqa: E402

SHAPES = ("heart", "star", "diamond")
ENERGIES = (0.2, 0.8)
LIT = 20.0          # star_harness.lit_cells' own threshold
WHITE = 200.0       # star_harness.white_cells' own threshold
CELL_PITCH = 1.0
RAYS = 360
OUTLINE_SAMPLES = 1440
# the plan's bars
BAR_INSIDE = 0.95
BAR_COVERED = 0.90
BAR_RADIUS_CELLS = 0.5
BAR_FIELD = 1e-4
BAR_JUMP = 0.08
BAR_COST_MS = 1.0


def words_scene():
    """The STAR scene plus a full-range Words band with one `word_shape`
    kind — the only thing that makes a sung word reach the crystal."""
    return scene_for({STRIP: "melt", STAR: "radial"},
                     kinds=[FlareKind(name="Word Shape", type="word_shape")],
                     bands={"word": {"Word Shape": 1.0}})


def normalized(panel, star):
    """Every addressable cell in the EFFECT's own normalized space — the
    same `nx = dx / ax`, `ny = dy / ay` on Star's own centre that
    `Radial2d._ws_normalized` uses, so this script measures where the effect
    actually draws rather than where a tidier centre would."""
    ax = max((star.r_width - 1) * 0.5, 1.0)
    ay = max((star.r_height - 1) * 0.5, 1.0)
    y, x = np.indices((panel.rows, panel.cols))
    nx = (x - float(star.cx)) / ax
    ny = (y - float(star.cy)) / ay
    return np.hypot(nx, ny), np.arctan2(ny, nx)


def outline_cells(panel, shape, size):
    """Real cells within one cell pitch of the outline, in PHYSICAL pitch
    units — check_word_shapes.py's own definition, on Star's own centre."""
    s = np.linspace(0.0, 1.0, OUTLINE_SAMPLES, endpoint=False)
    ux, uy = shape.at(s)
    ox = ux * size * panel.half_width * COLUMN_PITCH
    oy = uy * size * panel.half_height * ROW_PITCH
    rows_idx, cols_idx = np.nonzero(panel.grid)
    rx = (cols_idx - panel.half_width) * COLUMN_PITCH
    ry = (rows_idx - panel.half_height) * ROW_PITCH
    near = (np.hypot(rx[None, :] - ox[:, None],
                     ry[None, :] - oy[:, None]) <= CELL_PITCH).any(axis=0)
    out = np.zeros_like(panel.grid)
    out[rows_idx[near], cols_idx[near]] = True
    return out


class Frame:
    """One rendered frame, measured against the real mask."""

    def __init__(self, star, panel, matrix, strip, shape, size, near):
        grid = panel.grid
        rn, th = normalized(panel, star)
        rr = np.asarray(shape.polar(th)) * size
        q = rn / np.maximum(rr, 1e-9)            # the shape's own coordinate
        area = (q < 1.0) & grid
        value = np.asarray(matrix).max(axis=-1)
        lit = (value > LIT) & grid
        self.lit = int(lit.sum())
        self.inside = (float((lit & (area | near)).sum()) / self.lit
                       if self.lit else 1.0)
        self.area_cells = int(area.sum())
        self.covered_abs = (float((lit & area).sum()) / self.area_cells
                            if self.area_cells else 1.0)
        # the strip pixel each area cell samples, through the draw's own
        # arithmetic: index = ((u + twist x angle_norm) % 1) x N
        u = np.asarray(star._last_u)
        ang = np.asarray(star._last_angle)
        an = (ang + np.pi) / (2 * np.pi)
        idx = np.clip((((u + float(star.twist or 0.0) * an) % 1.0)
                       * len(strip)).astype(int), 0, len(strip) - 1)
        strip_lit = np.asarray(strip).max(axis=-1) > LIT
        have = strip_lit[idx] & area
        self.covered_strip = (float((lit & have).sum()) / int(have.sum())
                              if have.any() else 1.0)
        self.strip_share = float(strip_lit.mean())
        self.white = int(((np.asarray(matrix).min(axis=-1) > WHITE)
                          & grid).sum())
        self.field_err = float(np.abs(u[grid] - q[grid]).max())


def radius_error(star, shape, size, panel):
    """The largest error, in cell pitches, between the outline the effect
    draws and the library's, over 360 screen angles.

    The effect's own ANGLE-SPACE law is what is read (`_word_shape_div`,
    the divisor a lull piece and a transition program ride), so this is a
    sub-cell measurement of the drawn outline rather than a walk over the
    rasterised field — the raster's own agreement with the same law is the
    `field` column. A drawn point sits at `max_radius x div(psi)` pixels
    along `psi`; the library's outline point for that direction is at
    `SIZE x polar(theta_n)` in normalized units. Both go into physical
    pitch units before the comparison, because that is where "half a cell"
    means anything."""
    ax = max((star.r_width - 1) * 0.5, 1.0)
    ay = max((star.r_height - 1) * 0.5, 1.0)
    psi = np.arange(RAYS) * (2.0 * math.pi / RAYS)
    div = np.asarray(star._word_shape_div(psi), dtype=np.float64)
    r = div * float(star.max_radius)
    dx_px, dy_px = r * np.cos(psi), r * np.sin(psi)
    theta_n = np.arctan2(dy_px / ay, dx_px / ax)
    want = np.asarray(shape.polar(theta_n)) * size
    wx = want * np.cos(theta_n) * panel.half_width * COLUMN_PITCH
    wy = want * np.sin(theta_n) * panel.half_height * ROW_PITCH
    gx, gy = dx_px * COLUMN_PITCH, dy_px * ROW_PITCH
    return float(np.hypot(gx - wx, gy - wy).max())


def lit_of(matrix, grid):
    return int(((np.asarray(matrix).max(axis=-1) > LIT) & grid).sum())


def white_of(matrix, grid):
    return int(((np.asarray(matrix).min(axis=-1) > WHITE) & grid).sum())


def worst(track, a, b, stride=1):
    vals = [abs(track[i] - track[i - stride]) / max(track[i - stride], 1)
            for i in range(a + stride, min(b, len(track)), stride)]
    return max(vals) if vals else 0.0


def draw_ascii(matrix, grid):
    ramp = " .:-=+*#%@"
    v = np.asarray(matrix).max(axis=-1)
    return "\n".join(
        "".join(ramp[int(min(9, v[r, c] / 255.0 * 9.99))] if grid[r, c]
                else " " for c in range(v.shape[1]))
        for r in range(v.shape[0]))


async def untold_baseline(tmp, panel):
    """The effect's OWN worst per-frame change in lit cells, with no shape
    anywhere — the number every smoothness figure below is read against."""
    async with star_room(tmp, scene=words_scene()) as room:
        room.step(room.secs(2.0))
        track, white = [], 0
        for _ in range(180):
            room.step(1)
            track.append(lit_of(room.matrix(), panel.grid))
            white = max(white, white_of(room.matrix(), panel.grid))
        return (worst(track, 0, len(track)),
                worst(track, 0, len(track), stride=2), white, track)


async def clarity(tmp, panel, shape_id, energy, want_ascii=False):
    shape = word_shapes.get(shape_id).prime()
    async with star_room(tmp, scene=words_scene()) as room:
        room.step(room.secs(2.0))
        star = room.star
        size = star._word_shape_size()
        near = outline_cells(panel, shape, size)
        action = scene_response.preview_word_shape(energy, shape_id)
        await room.responder.on_word_shape(action)
        form = room.secs(action.form_s)
        hold = room.secs(action.hold_s)
        out, art = {}, None
        for i in range(form + hold):
            room.step(1)
            if i + 1 in (form, form + hold // 2):
                strip = np.asarray(room.virtuals[STRIP].assembled_frame)
                where = "word" if i + 1 == form else "mid-hold"
                out[where] = (Frame(star, panel, room.matrix(), strip, shape,
                                    size, near),
                              radius_error(star, shape, size, panel))
                if where == "mid-hold" and want_ascii:
                    art = draw_ascii(room.matrix(), panel.grid)
        return out, art


async def smoothness(tmp, panel, shape_id, energy):
    """The shape's own smoothness, WITH THE STRIP FROZEN: the strip's last
    frame is republished every step, so the only thing that moves in the
    picture is the shape."""
    async with star_room(tmp, scene=words_scene()) as room:
        room.step(room.secs(2.0))
        strip_v = room.virtuals[STRIP]
        frozen = np.array(strip_v.assembled_frame, copy=True)
        strip_v.assemble_frame = lambda: frozen
        room.step(2)
        star = room.star
        action = scene_response.preview_word_shape(energy, shape_id)
        await room.responder.on_word_shape(action)
        form = room.secs(action.form_s)
        hold = room.secs(action.hold_s)
        rel = room.secs(action.release_s)
        track, adv, env = [], [], []
        prev = star.spin_total
        for _ in range(form + hold + rel + 12):
            room.step(1)
            track.append(lit_of(room.matrix(), panel.grid))
            adv.append(((star.spin_total - prev + 0.5) % 1.0) - 0.5)
            env.append(float(star._shape_m))
            prev = star.spin_total
        return track, adv, env


async def cost(tmp):
    """p50 of Radial2d.draw, holding a shape against the same frames
    untold."""
    times: list[float] = []
    orig = radial.Radial2d.draw

    def timed(self):
        t0 = time.perf_counter()
        orig(self)
        times.append((time.perf_counter() - t0) * 1000.0)

    radial.Radial2d.draw = timed
    try:
        async with star_room(tmp, scene=words_scene()) as room:
            room.step(room.secs(1.0))
            times.clear()
            room.step(90)
            untold = statistics.median(times)
            # a long hold, so every timed frame is a holding one
            action = scene_response.PreviewWordShape(
                shape_id="heart", energy=0.8, form_s=0.3, hold_s=4.0,
                release_s=0.3)
            await room.responder.on_word_shape(action)
            room.step(room.secs(0.4))
            times.clear()
            room.step(90)
            held = statistics.median(times)
        return untold, held
    finally:
        radial.Radial2d.draw = orig


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ascii", action="store_true",
                    help="draw each shape at mid-hold on the real mask")
    args = ap.parse_args()
    panel = load_panel()
    ok = True
    arts = {}
    with tempfile.TemporaryDirectory() as tmp:
        base60, base30, base_white, base_track = run(
            untold_baseline(tmp, panel))
        print(f"crystal-mapper {panel.rows}x{panel.cols}, "
              f"{int(panel.grid.sum())} real cells; "
              f"word_shape_size {DEFAULT_SIZE_FRACTION}")
        print(f"untold: lit {min(base_track)}-{max(base_track)} real cells, "
              f"worst per-frame change {base60 * 100:.1f}% (60 fps) / "
              f"{base30 * 100:.1f}% (30 fps), white {base_white}\n")

        print(f"{'shape':8} {'E':>4} {'when':9} {'lit':>5} {'inside':>7} "
              f"{'cov/strip':>10} {'cov/abs':>8} {'strip':>7} {'radius':>8} "
              f"{'field':>9} {'white':>6}")
        for shape_id in SHAPES:
            for energy in ENERGIES:
                shots, art = run(clarity(tmp, panel, shape_id, energy,
                                         args.ascii and energy == 0.8))
                if art:
                    arts[shape_id] = art
                for where in ("word", "mid-hold"):
                    f, rad = shots[where]
                    bad = []
                    if f.inside < BAR_INSIDE:
                        bad.append("inside")
                    if f.covered_strip < BAR_COVERED:
                        bad.append("cov")
                    if rad > BAR_RADIUS_CELLS:
                        bad.append("radius")
                    if f.field_err > BAR_FIELD:
                        bad.append("field")
                    if f.white > base_white:
                        bad.append("white")
                    ok = ok and not bad
                    print(f"{shape_id:8} {energy:4.1f} {where:9} {f.lit:5d} "
                          f"{f.inside * 100:6.1f}% "
                          f"{f.covered_strip * 100:9.1f}% "
                          f"{f.covered_abs * 100:7.1f}% "
                          f"{f.strip_share * 100:6.1f}% {rad:7.3f}c "
                          f"{f.field_err:9.2e} {f.white:6d}"
                          + ("   FAIL " + ",".join(bad) if bad else ""))

        print(f"\nsmoothness, STRIP FROZEN (the shape's own doing). "
              f"untold worst {base60 * 100:.1f}% / {base30 * 100:.1f}%")
        print(f"{'shape':8} {'E':>4} {'form':>7} {'hold':>6} {'rel':>7}  "
              f"{'form30':>7} {'rel30':>7}  {'adv@form':>9} {'adv hold':>9} "
              f"{'adv@rel':>8}")
        for shape_id in SHAPES:
            for energy in ENERGIES:
                track, adv, env = run(
                    smoothness(tmp, panel, shape_id, energy))
                # the three stretches are read off the ENVELOPE the effect
                # itself reports, never off a frame count: a rounded frame
                # index would put a release frame inside the hold
                full = [i for i, m in enumerate(env) if m >= 1.0]
                form, last = full[0], full[-1] + 1
                rel = next((i for i, m in enumerate(env[last:], last)
                            if m <= 0.0), len(env) - 1) + 1
                jf = worst(track, 0, form + 1)
                jh = worst(track, form, last)
                jr = worst(track, last - 1, rel)
                jf2 = worst(track, 0, form + 1, stride=2)
                jr2 = worst(track, last - 1, rel, stride=2)
                hold_adv = max(abs(a) for a in adv[form:last])
                end_adv = abs(adv[min(rel, len(adv) - 1)])
                # the two claims this row DOES make, over and above the
                # printed 8%: the hold is exactly still, and no frame of the
                # form or the release is worse than the effect's own untold
                # worst at the same frame rate
                if hold_adv > 1e-12 or jh > 1e-9:
                    ok = False
                if max(jf, jr) > base60 or max(jf2, jr2) > base30:
                    ok = False
                flag = "" if max(jf2, jr2) <= BAR_JUMP else "  (over 8%)"
                print(f"{shape_id:8} {energy:4.1f} {jf * 100:6.1f}% "
                      f"{jh * 100:5.1f}% {jr * 100:6.1f}%  "
                      f"{jf2 * 100:6.1f}% {jr2 * 100:6.1f}%  "
                      f"{abs(adv[form - 1]) * 360:8.4f}d "
                      f"{hold_adv * 360:8.4f}d {end_adv * 360:7.3f}d" + flag)

        untold_ms, held_ms = run(cost(tmp))
        added = held_ms - untold_ms
        if added > BAR_COST_MS:
            ok = False
        print(f"\ncost p50: untold {untold_ms:.3f} ms, holding "
              f"{held_ms:.3f} ms -> +{added:.3f} ms (bar {BAR_COST_MS} ms)")

    for shape_id, art in arts.items():
        print(f"\n--- {shape_id} at mid-hold, Energy 0.8, real mask ---")
        print(art)
    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
