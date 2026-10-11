#!/usr/bin/env python3
"""Executable spec for fx/effects/sauron.py — the Eye of Sauron.

Every measurement is taken on the REAL render pipeline (fx.headless, audio
silenced, a fake clock) on his crystal's REAL 976-cell hex mask
(storage/device_profiles/crystal-mapper.json), reading the effect's own
output frame and the instruments it keeps (last_heat / last_flame /
last_slit / last_d) — never re-deriving the picture from the formulas.

What it proves (the approved plan's phase-1 list):
  1. the slit is black and CONTINUOUS on the hex lattice: every row it
     spans has a dark real cell at its centre line (a 1-px stroke would
     vanish on alternate rows) — and (1b, tune-up 1) it stays so while the
     eye MOVES: a gaze sweep at rest, under a full charge (the slit
     narrows) and at the narrowest Slit Width, every frame, with the floor
     switched off as the red control;
  2b. (tune-up 1) the perimeter ring resolves on the lattice as the eye
     moves (every angular bin round the iris holds a real cell on the
     ring's crest, every frame) and fades into the flames with no step;
  2. the rim is the hottest part of the fire: the brightest real cells sit
     on the slit's white-hot rim, far brighter than the flame tips;
  3. reach: bass lengthens the flames — measured as each angular bin's
     furthest lit flame cell over that cell's own gap to the crystal's
     edge; at full bass the longest licks come within 15% of the edge, at
     rest none do (at the shipped Flames 0.55 the MEAN reach is about half
     the gap even at full bass — Flames is the knob for more);
  4. a surge poke erupts the fire at once, self-resets the key, edges again
     on an identical later poke, and decays back to rest;
  5. a beat dilates the slit — width and height, about 1 : 0.3;
  6. the palette sort: identity on a set authored dark -> bright and on a
     solid colour; a rainbow set (Hype 1) resolves to the radial mapping,
     cold -> warm; Mid - Ice (authored bright -> dark) is reversed;
  7. angle mode colours by angle (hue varies around a ring of equal heat);
  7b. (tune-up 1) the radial mapping follows the eye's own shape (beside
     the slit and above its tip read the same colour although their
     distances from the centre differ) and is calmer than heat-mapping
     the same rainbow (neighbouring cells differ far less);
  8. no NaNs over 60 s of music, surges and a charge/lull/drop arc;
  9. the frame cost.

Run: .venv/bin/python scripts/check_sauron.py [--quick]
Exit status 0 = every check passed. tests/test_sauron.py runs it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fx import headless  # noqa: E402
from fx.effects import sauron as S  # noqa: E402

ROWS, COLS = 37, 72
DT = 1.0 / 60.0
FAILURES: list[str] = []

# His real colour sets' Matrix gradients (storage/color_sets.json, read
# 2026-10-10) — fixtures here so the proof needs no live storage.
SETS = {
    "Hype 1": "linear-gradient(90deg, rgb(255,0,0) 0%, rgb(255,120,0) 14%, rgb(255,200,0) 28%, rgb(0,255,0) 42%, rgb(0,199,140) 56%, rgb(0,0,255) 70%, rgb(128,0,128) 84%, rgb(255,0,178) 98%)",
    "Mid - Fire": "linear-gradient(90deg, rgb(255,0,0) 0%, rgb(255,143,0) 21%, rgb(255,143,0) 75%, rgb(255,0,0) 100%)",
    "Mid - Ice": "linear-gradient(90deg, rgb(0, 255, 255) 0%, rgb(0, 0, 255) 100%)",
    "Puerto Rico Red": "linear-gradient(90deg, rgb(255,255,255) 0%, rgb(255,255,255) 18%, rgb(255,0,0) 20%, rgb(255,0,0) 66%, rgb(255,255,255) 68%, rgb(255,255,255) 99%)",
    "Mid - Bright Purple": "linear-gradient(90deg, rgb(1,1,83) 0%, rgb(83,1,100) 43%, rgb(128,0,128) 65%, rgb(224,27,36) 100%)",
    "Mid - Blush": "linear-gradient(90deg, rgb(231,0,255) 0%, rgb(255,120,0) 58%, rgb(139,0,255) 100%)",
    "Orbit - Red": "linear-gradient(90deg, rgb(255,0,191) 0%, rgb(255,0,96) 25%, rgb(255,0,0) 50%, rgb(255,96,0) 75%, rgb(255,191,0) 100%)",
}


def check(cond, label):
    print(f"   {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        FAILURES.append(label)


def crystal_real_mask() -> np.ndarray:
    prof = json.loads((REPO / "storage" / "device_profiles"
                       / "crystal-mapper.json").read_text())
    mask, value = [], False
    for run in prof["mask_rle"]:
        mask.extend([value] * run)
        value = not value
    return np.array(mask, dtype=bool)


REAL = crystal_real_mask()
REAL2 = REAL.reshape(ROWS, COLS)


def outer_ring() -> np.ndarray:
    """The crystal's outermost real cells: the first and last real cell of
    every row, plus every real cell of the top and bottom real rows."""
    ring = np.zeros_like(REAL2)
    rows = [r for r in range(ROWS) if REAL2[r].any()]
    for r in rows:
        c = np.flatnonzero(REAL2[r])
        ring[r, c[0]] = ring[r, c[-1]] = True
    for r in (rows[0], rows[-1]):
        ring[r] = REAL2[r]
    return ring


class Rig:
    """One Sauron on a headless crystal under a fake clock."""

    _n = [0]

    def __init__(self, host, virtual, clock, effect, cm):
        self.host, self.virtual, self.clock = host, virtual, clock
        self.effect, self._cm = effect, cm

    @classmethod
    async def make(cls, config=None, seed=5):
        cls._n[0] += 1
        tag = f"sauron-check-{cls._n[0]}"
        td = tempfile.mkdtemp()
        host = await headless.start_headless_host(
            str(Path(td) / tag), pixel_count=ROWS * COLS, rows=ROWS,
            device_id=tag, real_mask=REAL)
        virtual = host.virtuals.get(tag)
        cm = headless.fake_clock()
        clock = cm.__enter__()
        eff = headless.attach_effect(host, virtual, "sauron",
                                     dict(config or {}))
        eff._rng = np.random.default_rng(seed)
        # the noise field is seeded from an unseeded generator at
        # construction; re-seed it so every measurement is repeatable
        eff.noise.seed = int(seed) * 7919 + 17
        return cls(host, virtual, clock, eff, cm)

    def step(self, frames=1, impulse=None, beat_every=None, hold_center=False):
        for i in range(frames):
            if impulse is not None:
                self.effect.impulse = float(impulse)
            if beat_every and i % beat_every == 0:
                self.effect._beat_pending = True
            if hold_center:
                self.effect.gaze = np.zeros(2, dtype=np.float32)
                self.effect._hold_left = 9.0
            self.clock.advance(DT)
            frame = self.virtual.assemble_frame()
            if frame is not None:
                self.virtual.flush(frame)

    def pixels(self) -> np.ndarray:
        return np.asarray(self.effect.matrix, dtype=np.float32).reshape(
            ROWS, COLS, 3)

    async def close(self):
        self._cm.__exit__(None, None, None)
        await self.host.shutdown()


def lum(px):
    return (0.2126 * px[..., 0] + 0.7152 * px[..., 1]
            + 0.0722 * px[..., 2]) / 255.0


# ── 1 · the slit is black and continuous on the lattice ──────────────────
async def section_slit(results):
    print("\n1 · the slit: black and continuous on the hex lattice")
    r = await Rig.make({"gradient": SETS["Mid - Fire"], "pupil_beat": 0.0})
    r.step(30, impulse=0.0, hold_center=True)
    e = r.effect
    px = lum(r.pixels())
    ex, ey = e.last_eye_px
    iris_r = e.iris_size
    w, h = e.slit_size(iris_r, 0.0, 0.0)
    h_px = h * e.s_min
    # the lens's half-width at a row's height, px. Where it is at least a
    # whole cell wide the slit must read as black on EVERY row (a 1-px
    # stroke would vanish on alternate rows of the lattice); its two tips,
    # narrower than a cell, are anti-aliased into the white-hot rim
    R = (w * w + h * h) / (2.0 * w)
    c = R - w

    def half_width_px(y):
        yy = (y - ey) / e.s_min
        return max(0.0, np.sqrt(max(R * R - yy * yy, 0.0)) - c) * e.s_min

    rows = [y for y in range(ROWS)
            if half_width_px(y) >= 1.0 and REAL2[y].any()]
    gaps = []
    for y in rows:
        cols = [x for x in range(COLS)
                if REAL2[y, x] and abs(x - ex) <= half_width_px(y) + 0.6]
        blackest = max((e.last_slit[y, x] for x in cols), default=0.0)
        if blackest < 0.9:
            gaps.append(y)
    results["slit_rows"] = len(rows)
    results["slit_gaps"] = gaps
    print(f"   slit spans {len(rows)} real rows (height {2 * h_px:.1f} px, "
          f"width {2 * w * e.s_min:.1f} px); rows with no dark real cell "
          f"(>= 90% black) at its centre line: {gaps}")
    check(len(rows) >= 10, "the slit is at least 10 rows tall")
    check(not gaps, "every row where the slit is a cell wide has a real "
          "cell at least 90% black (continuous on the lattice)")
    await r.close()


# ── 1b · continuous while the eye moves (tune-up 1) ──────────────────────
def _gaze_path(i, n):
    """A sweep over the gaze ring: round it 1.4 times at a breathing radius,
    a fractional step every frame (the slit lands on every lattice phase)."""
    a = i * 2 * np.pi * 1.4 / n + 0.3
    rad = 0.36 * (0.25 + 0.75 * abs(np.sin(i * 0.071)))
    return np.array([rad * np.cos(a), rad * np.sin(a)], dtype=np.float32)


def core_rows(e):
    """Real rows the slit's floor column covers this frame."""
    cx, cy, half = e.last_slit_core
    return [y for y in range(ROWS)
            if abs(y - cy) <= half - 0.5 and REAL2[y].any()], cx


def row_gaps(e, rows, cx):
    """Rows (of `rows`) with no real cell at least 90% black near cx."""
    gaps = []
    for y in rows:
        cols = [x for x in range(COLS) if REAL2[y, x] and abs(x - cx) <= 4.5]
        if max((e.last_slit[y, x] for x in cols), default=0.0) < 0.9:
            gaps.append(y)
    return gaps


async def slit_sweep(config, charge, frames, plan=None):
    """Run the gaze sweep; return [(rows, cx)] per frame (the plan) and the
    per-frame gaps measured against `plan` (its own when None)."""
    r = await Rig.make(config)
    e = r.effect
    if charge:
        e.update_config({"phase": "charge", "phase_progress": 1.0})
    r.step(25, impulse=0.0)
    out_plan, gaps = [], []
    for i in range(frames):
        e.gaze = _gaze_path(i, frames)
        e._hold_left = 9.0
        r.step(1, impulse=0.0)
        rows, cx = plan[i] if plan is not None else core_rows(e)
        out_plan.append((rows, cx))
        gaps.append(row_gaps(e, rows, cx))
    await r.close()
    return out_plan, gaps


async def section_slit_moving(results, frames):
    print("\n1b · the slit stays one continuous dark column while the eye "
          "moves")
    cases = [("rest", {"gradient": SETS["Mid - Fire"], "pupil_beat": 0.0},
              False),
             ("full charge", {"gradient": SETS["Mid - Fire"],
                              "pupil_beat": 0.0}, True),
             ("narrowest Slit Width", {"gradient": SETS["Mid - Fire"],
                                       "pupil_beat": 0.0,
                                       "pupil_width": 0.03}, False)]
    out = {}
    for label, cfg, charge in cases:
        plan, gaps = await slit_sweep(cfg, charge, frames)
        bad = sum(1 for g in gaps if g)
        rows = [len(p[0]) for p in plan]
        # red control: the same sweep and the same rows, the floor off
        keep = S.SLIT_MIN_DARK_PX
        S.SLIT_MIN_DARK_PX = 0.0
        try:
            _p, off = await slit_sweep(cfg, charge, frames, plan=plan)
        finally:
            S.SLIT_MIN_DARK_PX = keep
        off_bad = sum(1 for g in off if g)
        out[label] = {"frames": frames, "frames_with_a_gap": bad,
                      "rows_min": min(rows), "rows_max": max(rows),
                      "floor_off_frames_with_a_gap": off_bad}
        print(f"   {label:21s}: column spans {min(rows)}-{max(rows)} real "
              f"rows; frames with a broken row {bad}/{frames} "
              f"(floor off: {off_bad}/{frames})")
        check(min(rows) >= 8, f"{label}: the column spans at least 8 rows "
              f"every frame")
        check(bad == 0, f"{label}: no row of the column loses its dark real "
              f"cell on any frame of the sweep")
        if label != "rest":
            check(off_bad > 0, f"{label}: red control — with the floor off "
                  f"the same sweep breaks")
    results["slit_moving"] = out


# ── 2 · the rim is hottest ───────────────────────────────────────────────
async def section_rim(results):
    print("\n2 · the slit's rim is the hottest part of the fire")
    for name in ("Mid - Fire", "Mid - Ice", "Hype 1"):
        r = await Rig.make({"gradient": SETS[name]})
        r.step(45, impulse=0.4, beat_every=30, hold_center=True)
        e = r.effect
        px = lum(r.pixels())
        d = e.last_d
        flame = e.last_flame
        slit = e.last_slit
        rim = REAL2 & (slit < 0.5) & (d < -0.2 * e.iris_size) & (px > 0)
        # the rim band: real cells right beside the slit
        ex, _ = e.last_eye_px
        w, _h = e.slit_size(e.iris_size, 0.0, 0.4)
        near = np.abs(np.arange(COLS)[None, :] - ex) <= w * e.s_min + 2.5
        rim &= near
        tips = REAL2 & (d > 0.12) & (flame > 0.04) & (flame < 0.30)
        rmean = float(px[rim].mean()) if rim.any() else 0.0
        tmean = float(px[tips].mean()) if tips.any() else 0.0
        ratio = rmean / max(tmean, 1e-6)
        results.setdefault("rim_tip", {})[name] = round(ratio, 2)
        print(f"   {name:12s}: rim {rmean:.3f}  tips {tmean:.3f}  "
              f"rim/tip {ratio:.1f}x")
        check(ratio > 2.0, f"{name}: the rim is over twice as bright as the "
              f"flame tips")
        await r.close()


# ── 2b · the perimeter ring (tune-up 1) ──────────────────────────────────
async def section_ring(results, frames):
    print("\n2b · the perimeter ring holds on the lattice and fades into the "
          "flames")
    r = await Rig.make({"gradient": SETS["Mid - Fire"], "sky": 0.0})
    e = r.effect
    r.step(25, impulse=0.3)
    yy, xx = np.indices((ROWS, COLS))
    covered = total = 0
    prof = {}
    for i in range(frames):
        e.gaze = _gaze_path(i, frames)
        e._hold_left = 9.0
        r.step(1, impulse=0.3)
        ex, ey = e.last_eye_px
        b = ((np.arctan2(yy - ey, xx - ex) + np.pi) / (2 * np.pi)
             * N_BINS).astype(int) % N_BINS
        crest = REAL2 & (e.last_ring >= 0.8)
        for k in range(N_BINS):
            if (REAL2 & (b == k) & (e.last_d > -e.iris_size)).any():
                total += 1
                covered += bool((crest & (b == k)).any())
        # the radial heat profile just outside the iris, by whole pixels
        dpx = np.round(e.last_d * e.s_min).astype(int)
        for k in range(0, 8):
            m = REAL2 & (dpx == k) & (e.last_slit < 0.5)
            if m.any():
                prof.setdefault(k, []).append(float(e.last_heat[m].mean()))
    await r.close()
    cov = covered / max(total, 1)
    mean = [float(np.mean(prof[k])) for k in sorted(prof)]
    steps = [mean[k] - mean[k + 1] for k in range(len(mean) - 1)]
    results["ring"] = {"crest_coverage": round(cov, 4),
                       "profile": [round(v, 3) for v in mean],
                       "largest_step": round(max(steps), 3)}
    print(f"   angular bins holding a real cell on the ring's crest: "
          f"{cov:.1%} of {total} (bin, frame) pairs")
    print(f"   mean heat by pixel outside the iris: "
          f"{' '.join(f'{v:.2f}' for v in mean)} (largest step "
          f"{max(steps):.2f} per pixel)")
    check(cov >= 0.99, "the ring's crest lands on a real cell in every "
          "direction, every frame of a moving sweep")
    check(max(steps) <= 0.2, "the ring fades into the flames with no step "
          "(<= 0.2 heat per pixel)")


# ── 3 · reach ────────────────────────────────────────────────────────────
N_BINS = 24


def lick_reach(e) -> np.ndarray:
    """Per angular bin around the eye: the furthest LIT flame cell (flame
    heat > 0.05) as a fraction of that cell's own gap from the iris rim to
    the crystal's edge (1.0 = at the edge)."""
    ex, ey = e.last_eye_px
    yy, xx = np.indices((ROWS, COLS))
    q = e.last_d / e._edge_gap(ex, ey, e.iris_size)
    b = ((np.arctan2(yy - ey, xx - ex) + np.pi) / (2 * np.pi)
         * N_BINS).astype(int) % N_BINS
    lit = REAL2 & (e.last_flame > 0.05) & (e.last_d > 0)
    return np.array([q[lit & (b == k)].max() if (lit & (b == k)).any()
                     else 0.0 for k in range(N_BINS)])


async def section_reach(results):
    print("\n3 · reach: bass lengthens the flames toward the crystal's edge")
    out = {}
    for label, imp in (("rest", 0.0), ("half bass", 0.5), ("full bass", 1.0)):
        reach = []
        for seed in (1, 2, 3):
            r = await Rig.make({"gradient": SETS["Mid - Fire"], "sky": 0.0},
                               seed=seed)
            r.step(30, impulse=imp, hold_center=True)
            for _ in range(90):
                r.step(1, impulse=imp, hold_center=True)
                reach.append(lick_reach(r.effect))
            await r.close()
        reach = np.array(reach)
        out[label] = {"mean": round(float(reach.mean()), 3),
                      "frames_near_edge": round(float(
                          (reach.max(axis=1) >= 0.85).mean()), 3),
                      "longest": round(float(reach.max()), 3)}
    results["reach"] = out
    for label, m in out.items():
        print(f"   {label:9s}: mean lick reach {m['mean']:.2f} of the gap, "
              f"longest {m['longest']:.2f}, frames with a lick within 15% "
              f"of the edge {m['frames_near_edge']:.0%}")
    check(out["full bass"]["mean"] > 1.8 * out["rest"]["mean"],
          "full bass reaches over 1.8x as far as rest")
    check(out["half bass"]["mean"] > out["rest"]["mean"],
          "half bass reaches further than rest")
    check(out["full bass"]["longest"] >= 0.85
          and out["full bass"]["frames_near_edge"] > 0.2,
          "at full bass the longest licks come within 15% of the crystal's "
          "edge")
    check(out["rest"]["frames_near_edge"] == 0.0,
          "at rest no lick comes near the edge")


# ── 4 · the surge ────────────────────────────────────────────────────────
async def section_surge(results):
    print("\n4 · the surge poke erupts, self-resets and burns back")
    r = await Rig.make({"gradient": SETS["Mid - Fire"]})
    r.step(60, impulse=0.2, hold_center=True)
    e = r.effect

    def mass():
        return float(e.last_flame[REAL2].sum())

    r.step(1, impulse=0.2, hold_center=True)
    rest = mass()
    e.update_config({"surge": 1.0})
    r.step(1, impulse=0.2, hold_center=True)
    env0 = e._surge_env
    key0 = e._config["surge"]
    peak = mass()
    r.step(int(1.65 / DT), impulse=0.2, hold_center=True)
    late = mass()
    env_late = e._surge_env
    e.update_config({"surge": 1.0})
    r.step(1, impulse=0.2, hold_center=True)
    env_again = e._surge_env
    results["surge"] = {"rest": round(rest, 1), "peak": round(peak, 1),
                        "late": round(late, 1), "env0": round(env0, 3),
                        "env_after_3tau": round(env_late, 3)}
    print(f"   flame mass: rest {rest:.0f}, first frame of a full surge "
          f"{peak:.0f}, 3 time constants later {late:.0f}; envelope "
          f"{env0:.3f} -> {env_late:.3f}; key after the poke {key0}")
    check(peak > rest * 1.3, "the eruption lands on the first frame")
    check(env0 > 0.95, "the envelope rises to the poke's value at once")
    check(key0 == 0.0, "the surge key self-resets to 0")
    check(env_late < 0.06 and late < peak, "it burns back within ~3 "
          "time constants")
    check(env_again > 0.95, "an identical later poke edges again")
    stale = await Rig.make({"surge": 0.8})
    stale.step(5, impulse=0.0)
    check(stale.effect._surge_env == 0.0, "a stale persisted poke on a fresh "
          "instance never erupts")
    await stale.close()
    await r.close()


# ── 5 · the beat dilates the slit ────────────────────────────────────────
async def section_beat(results):
    print("\n5 · a beat dilates the slit (width and height, about 1 : 0.3)")
    r = await Rig.make({"gradient": SETS["Mid - Fire"]})
    r.step(40, impulse=0.6, hold_center=True)
    e = r.effect
    before = float((e.last_slit[REAL2] > 0.5).sum())
    w0, h0 = e.slit_size(e.iris_size, 0.0, 0.6)
    e._beat_pending = True
    r.step(1, impulse=0.6, hold_center=True)
    after = float((e.last_slit[REAL2] > 0.5).sum())
    w1, h1 = e.slit_size(e.iris_size, e._pulse, 0.6)
    r.step(int(0.8 / DT), impulse=0.6, hold_center=True)
    settled = float((e.last_slit[REAL2] > 0.5).sum())
    dw, dh = w1 / w0 - 1.0, h1 / h0 - 1.0
    results["beat"] = {"cells_before": before, "cells_on_beat": after,
                       "cells_after": settled, "width_gain": round(dw, 3),
                       "height_gain": round(dh, 3)}
    print(f"   black real cells: before {before:.0f}, on the beat "
          f"{after:.0f}, 0.8 s later {settled:.0f}; width +{dw:.0%}, "
          f"height +{dh:.0%}")
    check(after > before * 1.2, "the beat opens the slit by over 20%")
    check(settled < after, "it eases back")
    check(abs(dh / max(dw, 1e-6) - S.SLIT_HEIGHT_BEAT)
          < 0.08 or w1 >= h1 * S.SLIT_MAX_ASPECT,
          "the height dilates by about 0.3 of the width's gain")
    await r.close()


# ── 6 · the palette sort ─────────────────────────────────────────────────
def _distinct_order(gradient):
    stops = S._stops(gradient) or []
    out = []
    for c, _p in stops:
        if not out or out[-1] != c:
            out.append(c)
    return out


def section_palette(results):
    print("\n6 · the palette sort")
    dark_bright = "linear-gradient(90deg, rgb(40,0,0) 0%, rgb(255,0,0) 50%, rgb(255,255,255) 100%)"
    sorted_db = S.palette_gradient(dark_bright, "auto")
    check(_distinct_order(sorted_db) == _distinct_order(dark_bright),
          "a set authored dark -> bright keeps its order under auto")
    check(S.palette_gradient("#ff4400", "auto") == "#ff4400",
          "a solid colour is untouched")
    hype = SETS["Hype 1"]
    check(S.resolve_palette_sort("auto", hype) == "radial",
          "Hype 1 (a rainbow set) resolves to the radial mapping")
    check(S.resolve_palette_sort("auto", SETS["Mid - Fire"]) == "brightness",
          "Mid - Fire resolves to brightness")
    ice = S.palette_gradient(SETS["Mid - Ice"], "auto")
    order = _distinct_order(ice)
    check(order[0] == (0, 0, 255) and order[-1] == (0, 255, 255),
          "Mid - Ice (authored bright -> dark) is reversed: blue tips, "
          "cyan rim")
    warm = _distinct_order(S.palette_gradient(hype, "auto"))
    check(S.warmth(warm[-1]) >= max(S.warmth(c) for c in warm) - 1e-9
          and S.warmth(warm[0]) <= min(S.warmth(c) for c in warm) + 1e-9,
          "Hype 1 under auto: coldest colour at the tips, warmest at the rim")
    check(_distinct_order(S.palette_gradient(hype, "radial")) == warm,
          "radial walks the set cold -> warm")
    check(S.palette_gradient(hype, "authored") == hype
          and S.palette_gradient(hype, "angle") == hype,
          "authored and angle leave the set as written")
    results["palette"] = {
        name: [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in _distinct_order(
            S.palette_gradient(g_, "auto"))]
        for name, g_ in SETS.items()}
    for name, cols in results["palette"].items():
        print(f"   {name:20s} auto -> {' '.join(cols)}")


# ── 7 · angle mode ───────────────────────────────────────────────────────
async def section_angle(results):
    print("\n7 · angle mode colours by angle around the eye")
    r = await Rig.make({"gradient": SETS["Hype 1"], "palette_sort": "angle"})
    r.step(30, impulse=0.3, hold_center=True)
    e = r.effect
    px = r.pixels()
    ex, ey = e.last_eye_px
    yy, xx = np.indices((ROWS, COLS))
    rr = np.hypot(xx - ex, yy - ey) / e.s_min
    band = REAL2 & (np.abs(rr - 0.8 * e.iris_size) < 0.08) & (lum(px) > 0.05)
    cols = px[band] / np.maximum(px[band].max(axis=1, keepdims=True), 1)
    spread = float(np.std(cols, axis=0).mean())
    results["angle_spread"] = round(spread, 3)
    print(f"   colour spread round a ring of the iris: {spread:.3f}")
    check(band.sum() > 10 and spread > 0.2, "the iris ring wears many "
          "colours by angle")
    await r.close()


# ── 7b · the radial mapping (tune-up 1) ──────────────────────────────────
def colour_islands(px, region, palette):
    """How BROKEN UP the colour is: label every real cell of `region` with
    its nearest colour of the set (on chroma), then count the connected
    patches of one colour over the lattice's own neighbours (two columns
    along a row, one diagonally to the next row) — patches per lit cell.
    A speckle of colours scores high; calm bands score low."""
    col = px / np.maximum(px.max(axis=2, keepdims=True), 1.0)
    pal = np.array(palette, dtype=np.float32)
    pal = pal / np.maximum(pal.max(axis=1, keepdims=True), 1.0)
    lab = np.argmin(((col[..., None, :] - pal) ** 2).sum(axis=3), axis=2)
    parent = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    cells = list(zip(*np.nonzero(region)))
    for c in cells:
        parent[c] = c
    for y, x in cells:
        for dy, dx in ((0, 2), (1, 1), (1, -1)):
            n = (y + dy, x + dx)
            if n in parent and lab[n] == lab[y, x]:
                parent[find(n)] = find((y, x))
    roots = {find(c) for c in cells}
    return len(roots) / max(len(cells), 1)


async def section_radial(results):
    print("\n7b · the radial mapping: follows the eye's shape, calmer than "
          "heat")
    busy = {}
    for how in ("radial", "warm"):
        vals = []
        for seed in (1, 2):
            r = await Rig.make({"gradient": SETS["Hype 1"],
                                "palette_sort": how}, seed=seed)
            r.step(40, impulse=0.4, beat_every=30, hold_center=True)
            e = r.effect
            px = r.pixels()
            region = REAL2 & (lum(px) > 0.08) & (e.last_slit < 0.5)
            vals.append(colour_islands(
                px, region, _distinct_order(SETS["Hype 1"])))
            if how == "radial":
                check(e.mapping() == "radial", "radial is what is sampled")
                ex, ey = e.last_eye_px
                w, h = e.slit_size(e.iris_size, e._pulse, 0.4)
                # one ring of EQUAL distance from the eye, inside the iris:
                # a circular mapping reads one colour all round it; this
                # one reads hotter toward the slit's tips (the slit is
                # near) than out beside its flanks
                yy, xx = np.indices((ROWS, COLS))
                rr = np.hypot(xx - ex, yy - ey) / (e.iris_size * e.s_min)
                aa = np.abs(np.arctan2(yy - ey, xx - ex))
                vert = np.abs(aa - np.pi / 2) < np.radians(25)
                horz = (aa < np.radians(25)) | (aa > np.radians(155))
                ring_m = REAL2 & (np.abs(rr - 0.9) < 0.07) & (
                    e.last_slit < 0.5)
                rc = e.last_radial
                results.setdefault("radial_shape", []).append(
                    {"toward_tips": round(float(rc[ring_m & vert].mean()), 3),
                     "beside_flanks": round(float(
                         rc[ring_m & horz].mean()), 3)})
            await r.close()
        busy[how] = float(np.mean(vals))
    shape = {k: float(np.mean([s_[k] for s_ in results["radial_shape"]]))
             for k in ("toward_tips", "beside_flanks")}
    print(f"   on one ring of equal distance (0.9 of the iris): colour "
          f"coordinate toward the slit's tips {shape['toward_tips']:.2f}, "
          f"beside its flanks {shape['beside_flanks']:.2f}")
    print(f"   colour patches per lit cell on Hype 1: radial "
          f"{busy['radial']:.3f}, heat-mapped (the old auto) "
          f"{busy['warm']:.3f}")
    results["radial_busy"] = {k: round(v, 3) for k, v in busy.items()}
    check(shape["toward_tips"] - shape["beside_flanks"] > 0.03,
          "the bands follow the slit, not a circle (equal distance, "
          "hotter toward the tips)")
    check(busy["radial"] < 0.6 * busy["warm"], "the radial mapping breaks "
          "the colour into far fewer patches than heat-mapping the same "
          "rainbow")


# ── 8 · no NaNs over a minute of everything ──────────────────────────────
async def section_soak(results, seconds):
    print(f"\n8 · {seconds:.0f} s of music, surges and a charge/lull/drop "
          f"arc — no NaNs")
    rng = np.random.default_rng(3)
    r = await Rig.make({"gradient": SETS["Hype 1"]})
    e = r.effect
    bad = 0
    n = int(seconds / DT)
    arc = {int(n * 0.3): "charge", int(n * 0.45): "lull",
           int(n * 0.55): "drop"}
    for i in range(n):
        if i in arc:
            e.update_config({"phase": arc[i], "phase_progress": 0.0})
        if e._phase in ("charge", "lull"):
            e.update_config({"phase_progress": min(1.0, e.phase_progress
                                                   + DT / 3.0)})
        if rng.random() < 0.01:
            e.update_config({"surge": float(rng.uniform(0.0, 1.0))})
        if rng.random() < 0.002:
            e.update_config({"palette_sort": str(rng.choice(S.PALETTE_SORTS))})
        r.step(1, impulse=float(rng.uniform(0, 1)),
               beat_every=None)
        if i % 30 == 0:
            e._beat_pending = True
        if (not np.isfinite(e.last_heat).all()
                or not np.isfinite(e.gaze).all()):
            bad += 1
    results["soak_bad_frames"] = bad
    check(bad == 0, f"no NaN/inf in the heat or the gaze over {n} frames")
    await r.close()


# ── 9 · cost ─────────────────────────────────────────────────────────────
async def section_cost(results):
    print("\n9 · frame cost (this machine's CPU, whole effect at 72x37)")
    r = await Rig.make({"gradient": SETS["Mid - Fire"]})
    times = []
    for i in range(420):
        if i % 30 == 0:
            r.effect._beat_pending = True
        t0 = time.perf_counter()
        r.step(1, impulse=0.6)
        times.append((time.perf_counter() - t0) * 1e3)
    t = np.array(times[60:])
    results["frame_ms"] = {"p50": round(float(np.percentile(t, 50)), 2),
                           "p95": round(float(np.percentile(t, 95)), 2),
                           "max": round(float(t.max()), 2)}
    print(f"   p50 {results['frame_ms']['p50']} ms, p95 "
          f"{results['frame_ms']['p95']} ms, max {results['frame_ms']['max']}"
          f" ms (a 60 fps frame has 16.7 ms)")
    check(results["frame_ms"]["p95"] < 12.0, "p95 well inside a 60 fps frame")
    await r.close()


async def main_async(args):
    headless.silence_audio()
    results: dict = {}
    await section_slit(results)
    await section_slit_moving(results, 60 if args.quick else 160)
    await section_rim(results)
    await section_ring(results, 60 if args.quick else 160)
    await section_reach(results)
    await section_surge(results)
    await section_beat(results)
    section_palette(results)
    await section_angle(results)
    await section_radial(results)
    await section_soak(results, 15.0 if args.quick else 60.0)
    await section_cost(results)
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2,
                                              default=str))
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true",
                    help="a 15 s soak instead of 60 s")
    ap.add_argument("--json", help="write the measurements here")
    args = ap.parse_args()
    asyncio.run(main_async(args))
    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    status = 1
    try:
        status = main()
    except BaseException:                          # noqa: BLE001
        import traceback
        traceback.print_exc()
    finally:
        # fx's TemporalEffect threads are never joined by the frame-stepped
        # harness, so a plain return would leave the interpreter alive
        # (AGENTS.md: a check script that renders through fx.headless must
        # os._exit()).
        sys.stdout.flush()
        os._exit(status)
