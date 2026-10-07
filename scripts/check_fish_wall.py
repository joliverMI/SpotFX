"""Measure the FISH WALL (fx/effects/fish.py, the WALL block) and the House
Fish SOLO BURST, on the real vendored render pipeline — fx.headless with his
crystal-mapper's REAL shape: 72x37 cells, the real ones on one dummy device
and the dark ones on a `gap-` device, segment for segment from
storage/device_profiles/crystal-mapper.json.

HIS WORDS (2026-10-06): "the fish don't interact with the 'wall' naturally.
Have them 'anticipate' the wall and start turning away. Do this on both fish
scenes. In house fish scene, give individual ones an occasional burst of
speed."

  0. THE WALL IS THE PANEL'S REAL SHAPE: what the effect reads off the
     virtual's own segments is the device profile's mask, and its lit
     silhouette holds every real cell.
  1. THE ESCAPE HATCH: at `wall_lookahead = 0` (solo bursts off) the effect
     reproduces the PINNED pre-change fish bit for bit — kinematics, through
     a whole swim / charge / lull / drop arc, on the crystal and on a plain
     rectangle. Negative control: at the shipped defaults they differ.
  2. THE WALL HELD: his two real scenes' fish (House Fish and Fish, their
     live params) over several seeds — how far any swimming fish's nose or
     middle gets past the lit silhouette, and how much of all fish light
     lands where the panel cannot show it, before vs after. The silhouette
     here is NOT the effect's own: it is the row span of the real cells,
     computed in this file, so the effect is not marking its own homework.
     2b: the same under a sustained loud passage, plus how bright the wake
     gets against the fish (his "the trail is always subtle").
  3. ANTICIPATION: one fish swimming straight at the top wall — where its
     heading first starts to change (how far its nose still is from the
     wall), how hard the turn ever gets, and how big a single frame's change
     in curvature is, before vs after.
  4. THE SOLO BURST: at the House Fish scene's own settings, bursts land at
     about the configured rate, reach their top speed, and every one eases
     back to the fish's ordinary speed; at the effect's own default (rate 0)
     there are none.
  5. COST: the wall steer's own time per frame at his scenes' fish counts
     (reported, not asserted — it is this machine's number).

Read-only, offline, no live access.

    .venv/bin/python scripts/check_fish_wall.py
    .venv/bin/python scripts/check_fish_wall.py --gifs <dir>   # + GIFs
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fx import headless  # noqa: E402
from fx.effects import fish as FX  # noqa: E402
from scripts.add_house_fish_solo_burst import SOLO_BURST_PARAMS  # noqa: E402

DT = 1.0 / 60.0
ROWS, COLS = 37, 72

# THE PINNED PREDECESSOR: this change's own merge-base (master before the
# wall and the solo burst existed). Pinned, never a moving ref — see
# scripts/check_fish_camera.py's BASELINE_REF for what a moving ref did to
# that proof once.
WALL_BASELINE_REF = "a096a90bd40ad9eff350c9635c03b460b5aad2f7"

# his live "House Fish" Matrix entry, read from :8010 on 2026-10-06
HOUSE_FISH = {
    "particle_count": 5, "blob_size": 6, "base_speed": 0.16,
    "reactivity_scale": 0, "brightness_audio": 0, "size_audio": 0,
    "speed_jump": 0, "speed_jog": 0, "jiggle": 0.15, "spin": 0.28,
    "flap_rate": 0.2, "camera_follow": 0, "color_shift": 0,
    "tether_scatter": 0,
}
# his live "Fish" Matrix entry, its bindings at their fallbacks (the same
# day): particle_count 3, blob_size 2.5, reverse off
MUSIC_FISH = {
    "particle_count": 3, "horizon_scale": 0.3, "radius_scale": 1.8,
    "blob_size": 2.5, "x_offset": 0.5, "y_offset": 0.5, "spin": 0.37,
    "base_speed": 0.3, "jiggle": 0.5, "tether_scatter": 0,
    "reactivity_scale": 1, "speed_jump": 1, "speed_jog": 1,
    "brightness_audio": 0.5, "size_audio": 0.5, "color_shift": 1,
    "impulse_decay": 0.06, "flap_amount": 0.45, "school_variation": 0.08,
    "rush_chaos": 0.3, "roam_scale": 0.75, "reverse": False,
}
OLD = {"wall_lookahead": 0.0}

FAILURES: list[str] = []


def check(cond, label):
    print(f"   {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        FAILURES.append(label)


# ── the rig ─────────────────────────────────────────────────────────────
def crystal_real_mask():
    """His crystal-mapper's real cells, row-major, from the device profile."""
    prof = json.loads(
        (REPO / "storage" / "device_profiles" / "crystal-mapper.json")
        .read_text()
    )
    mask, value = [], False
    for run in prof["mask_rle"]:
        mask.extend([value] * run)
        value = not value
    return np.array(mask, dtype=bool)


def lit_area(real):
    """The panel's lit area, judged INDEPENDENTLY of the effect: every cell
    between a row's first and last real cell. On the crystal that is the
    hexagon, its lattice holes and tip-row crenels included."""
    grid = real.reshape(ROWS, COLS)
    out = np.zeros_like(grid)
    for r in range(ROWS):
        c = np.flatnonzero(grid[r])
        if c.size:
            out[r, c[0]: c[-1] + 1] = True
    return out


class Rig:
    def __init__(self, host, virtual, clock, effect, cm):
        self.host, self.virtual, self.clock = host, virtual, clock
        self.effect, self._cm = effect, cm

    def step(self, frames=1):
        for _ in range(frames):
            self.clock.advance(DT)
            frame = self.virtual.assemble_frame()
            if frame is not None:
                self.virtual.flush(frame)

    def phase(self, phase, seconds, beats_every=None, watch=None):
        eff = self.effect
        eff.update_config({"phase": phase, "phase_progress": 0.0})
        frames = int(seconds / DT)
        for i in range(1, frames + 1):
            eff.update_config({"phase_progress": i / frames})
            if beats_every and i % beats_every == 0:
                eff._beat_pending = True
            self.step(1)
            if watch is not None:
                watch(eff)

    def screen(self, idx=None):
        eff = self.effect
        idx = np.arange(eff.n) if idx is None else idx
        x = eff.cx + eff.p_x[idx] * eff.sx - eff.cam_px
        y = eff.cy + eff.p_y[idx] * eff.sy - eff.cam_py
        return x, y


_RIGS = [0]


async def rig(tag, config, seed=5, crystal=True, effect_type="fish"):
    # every rig gets its OWN virtual id: the fish store a particle-handoff
    # snapshot under it when they shut down, and a later rig reusing the id
    # would adopt the previous run's shoal
    _RIGS[0] += 1
    tag = f"{tag}-{_RIGS[0]}"
    td = tempfile.mkdtemp()
    kwargs = {"real_mask": crystal_real_mask()} if crystal else {}
    host = await headless.start_headless_host(
        str(Path(td) / tag), pixel_count=ROWS * COLS, rows=ROWS,
        device_id=tag, **kwargs,
    )
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    eff = headless.attach_effect(host, virtual, effect_type, dict(config))
    eff._rng = np.random.default_rng(seed)
    return Rig(host, virtual, clock, eff, cm)


async def close(r):
    r._cm.__exit__(None, None, None)
    await r.host.shutdown()


def load_baseline_effect(name="fish_wall_baseline", ref=None):
    """The pinned predecessor's fish.py, registered as a SECOND effect (an
    Effect registers under its module's last name segment). None — a STATED
    skip — when git cannot produce the ref."""
    ref = ref or WALL_BASELINE_REF
    try:
        src = subprocess.run(
            ["git", "show", f"{ref}:fx/effects/fish.py"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout
    except Exception as exc:                       # noqa: BLE001
        print(f"  (skipped: cannot read {ref}:fx/effects/fish.py — {exc})")
        return None
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


ARC = [
    ("swim", 5.0, None),
    ("charge", 4.0, 12),
    ("lull", 3.0, None),
    ("drop", 4.0, None),
    ("swim", 3.0, None),
]


async def kinematics(tag, cfg, seed, effect_type, crystal, script=ARC):
    r = await rig(tag, cfg, seed=seed, crystal=crystal, effect_type=effect_type)
    eff = r.effect
    seq = []

    def grab(_e=None):
        n = eff.n
        seq.append((eff.p_x[:n].copy(), eff.p_y[:n].copy(),
                    eff.p_hd[:n].copy(), eff.p_spd[:n].copy()))

    for kind, arg, beats in script:
        if kind == "swim":
            for _ in range(int(arg / DT)):
                r.step(1)
                grab()
        else:
            r.phase(kind, arg, beats_every=beats, watch=grab)
    await close(r)
    return seq


def same_kinematics(a, b):
    if len(a) != len(b):
        return False
    for fa, fb in zip(a, b):
        for xa, xb in zip(fa, fb):
            if xa.shape != xb.shape or not np.array_equal(xa, xb):
                return False
    return True


async def wall_run(cfg, seed, seconds, lit, warmup=1.0):
    """(worst nose/middle distance past the lit area in px — 0 if never —,
    share of all fish light landing outside it). Swimming fish only (an
    arriving or departing fish crosses the edge on purpose)."""
    r = await rig(f"wall{seed}", cfg, seed=seed)
    eff = r.effect
    rr, cc = np.nonzero(lit)
    worst = 0.0
    out_light = total = 0.0
    for i in range(int(seconds / DT)):
        r.step(1)
        light = np.asarray(eff.matrix, dtype=np.float32).sum(axis=2)
        total += float(light.sum())
        out_light += float(light[~lit].sum())
        if i * DT < warmup:
            continue
        sw = np.flatnonzero(eff.p_mode[:eff.n] == 0)
        if not sw.size:
            continue
        x, y = r.screen(sw)
        half = eff._half_width_px() * eff.body_aspect
        nx = x + np.cos(eff.p_hd[sw]) * half
        ny = y + np.sin(eff.p_hd[sw]) * half
        for px, py in zip(np.r_[x, nx], np.r_[y, ny]):
            ci, ri = int(round(px)), int(round(py))
            if 0 <= ci < COLS and 0 <= ri < ROWS and lit[ri, ci]:
                continue
            worst = max(worst, float(np.min(np.hypot(cc - px, rr - py))) - 0.5)
    await close(r)
    return worst, out_light / max(total, 1e-9)


def _fresh(eff):
    """A placed fish carries none of the turn it was making where it was."""
    for name in ("p_wsg", "p_wurg", "p_wcmd", "p_wauth", "p_jog", "p_ro"):
        getattr(eff, name)[0] = 0.0


async def approach(cfg, seconds=3.0):
    """One fish, placed at the middle-left of the panel heading up and to
    the right at the top wall. Returns per-frame (nose distance to the top
    of the lit area, heading, curvature as a fraction of its tightest
    turn). Its wander SWING and its home pull are switched off for this run
    only (module constants, restored) — wander then points exactly along
    its own heading — so the only thing that can turn it is the edge:
    before, the old pond-edge steer; after, the wall."""
    lone = dict(cfg, particle_count=1, jiggle=0.0, spin=0.0,
                horizon_scale=0.0, speed_jump=0.0, speed_jog=0.0,
                reactivity_scale=0.0, min_drift_speed=1.0,
                stroke_speed_cap=0.0, avoid_strength=0.0)
    names = ("WANDER_SWING", "WANDER_SWING_JIGGLE", "HOME_W")
    saved = {k: getattr(FX, k) for k in names}
    for k in names:
        setattr(FX, k, 0.0)
    try:
        return await _approach(lone, seconds)
    finally:
        for k, v in saved.items():
            setattr(FX, k, v)


async def _approach(lone, seconds):
    r = await rig("approach", lone, seed=1)
    eff = r.effect
    r.step(1)
    eff.p_x[0] = (24.0 - eff.cx) / eff.sx
    eff.p_y[0] = (24.0 - eff.cy) / eff.sy
    eff.p_hd[0] = np.deg2rad(-50.0)
    eff.p_trail_x[0, 0] = np.nan
    eff.p_spd[0] = eff.cruise_px
    _fresh(eff)
    rows = []
    prev = float(eff.p_hd[0])
    half = eff._half_width_px() * eff.body_aspect
    radius = eff.turn_radius_px
    for _ in range(int(seconds / DT)):
        r.step(1)
        if eff.n == 0:
            break
        x, y = r.screen(np.array([0]))
        hd = float(eff.p_hd[0])
        nose_y = float(y[0]) + np.sin(hd) * half
        turned = float(FX._wrap_pi(hd - prev))
        kappa = abs(turned) / max(float(eff.p_spd[0]) * DT, 1e-6) * radius
        rows.append((nose_y + 0.5, hd, kappa))
        prev = hd
    await close(r)
    return rows


# ── 0. the shape ────────────────────────────────────────────────────────
def section_shape():
    print("\n0. THE WALL IS THE PANEL'S REAL SHAPE")

    async def go():
        real = crystal_real_mask().reshape(ROWS, COLS)
        r = await rig("shape", HOUSE_FISH)
        r.step(1)                       # the panel is known after a frame
        read = FX._real_cell_mask(r.effect)
        sil = FX._silhouette(read)
        await close(r)
        p = await rig("plain", HOUSE_FISH, crystal=False)
        p.step(1)
        plain = FX._real_cell_mask(p.effect)
        await close(p)
        return real, read, sil, plain

    real, read, sil, plain = asyncio.run(go())
    check(np.array_equal(read, real),
          f"read off the virtual's segments == the device profile's mask "
          f"({int(read.sum())} real cells of {read.size})")
    check(bool(sil[real].all()), "the lit silhouette holds every real cell")
    check(np.array_equal(sil, lit_area(crystal_real_mask())),
          "... and is exactly the row span of the real cells (the hexagon)")
    check(bool(plain.all()), "a virtual with no gap devices is the whole "
          "rectangle")


# ── 1. the escape hatch ─────────────────────────────────────────────────
def section_escape_hatch():
    print(f"\n1. ESCAPE HATCH — wall_lookahead=0 vs the pinned merge-base "
          f"{WALL_BASELINE_REF[:12]}")
    base = load_baseline_effect()
    if base is None:
        return
    for crystal in (True, False):
        where = "crystal" if crystal else "plain"
        for cfg_name, cfg in (("House Fish", HOUSE_FISH),
                              ("Fish", MUSIC_FISH)):
            for seed in (3, 11):
                a = asyncio.run(kinematics(f"b{seed}", cfg, seed, base,
                                           crystal))
                b = asyncio.run(kinematics(f"n{seed}", dict(cfg, **OLD), seed,
                                           "fish", crystal))
                check(same_kinematics(a, b),
                      f"{where:7s} {cfg_name:10s} seed {seed:>2}: "
                      f"{len(a)} frames identical through swim/charge/lull/"
                      "drop")
    a = asyncio.run(kinematics("bd", HOUSE_FISH, 3, base, True))
    b = asyncio.run(kinematics("nd", HOUSE_FISH, 3, "fish", True))
    check(not same_kinematics(a, b),
          "control: at the shipped defaults the kinematics differ (the wall "
          "is not inert)")


# ── 2. the wall held ────────────────────────────────────────────────────
def section_wall(seeds=(0, 1, 2, 3), seconds=30.0):
    print("\n2. THE WALL HELD — swimming fish's nose/middle past the lit "
          "area, and fish light the panel cannot show")
    lit = lit_area(crystal_real_mask())
    for name, cfg in (("House Fish", HOUSE_FISH), ("Fish", MUSIC_FISH)):
        for label, extra in (("before", OLD), ("after", {})):
            res = [asyncio.run(wall_run(dict(cfg, **extra), s, seconds, lit))
                   for s in seeds]
            worst = max(w for w, _ in res)
            share = float(np.mean([o for _, o in res]))
            print(f"   {name:10s} {label:6s}: worst {worst:5.2f}px past the "
                  f"wall, {100 * share:5.2f}% of fish light outside it")
            if label == "after":
                check(worst <= 0.0,
                      f"{name}: no swimming fish's nose or middle ever "
                      "leaves the lit area")


# ── 2b. a loud passage ──────────────────────────────────────────────────
async def loud_run(cfg, seed, impulse, seconds=10.0):
    """(worst px a swimming fish's nose or middle gets past the lit area,
    median wake-to-fish brightness) under a sustained loud passage."""
    lit = lit_area(crystal_real_mask())
    rr, cc = np.nonzero(lit)
    r = await rig("loud", cfg, seed=seed)
    eff = r.effect
    r.step(240)
    worst, ratio = 0.0, []
    for _ in range(int(seconds / DT)):
        eff.impulse = impulse
        eff.slow = 0.25 * impulse
        r.step(1)
        ratio.append(eff.wake.max() / max(float(eff.trail.max()), 1.0))
        sw = np.flatnonzero(eff.p_mode[:eff.n] == 0)
        x, y = r.screen(sw)
        half = eff._half_width_px() * eff.body_aspect
        for px, py in zip(np.r_[x, x + np.cos(eff.p_hd[sw]) * half],
                          np.r_[y, y + np.sin(eff.p_hd[sw]) * half]):
            ci, ri = int(round(px)), int(round(py))
            if 0 <= ci < COLS and 0 <= ri < ROWS and lit[ri, ci]:
                continue
            worst = max(worst, float(np.min(np.hypot(cc - px, rr - py))) - 0.5)
    await close(r)
    return worst, float(np.median(ratio))


def section_loud():
    print("\n2b. A LOUD PASSAGE — his music fish driven to 3-6x cruise")
    for impulse in (0.3, 0.9):
        for label, extra in (("before", OLD), ("after", {})):
            res = [asyncio.run(loud_run(dict(MUSIC_FISH, **extra), s, impulse))
                   for s in (1, 2)]
            worst = max(w for w, _ in res)
            ratio = float(np.mean([q for _, q in res]))
            print(f"   impulse {impulse} {label:6s}: worst {worst:5.2f}px past "
                  f"the wall; wake/fish brightness {ratio:.2f}")
            if label == "after":
                check(worst <= 0.0 and ratio < 0.6,
                      f"impulse {impulse}: every fish stays on the panel and "
                      "the wake stays subtle (< 0.6 of the fish)")


# ── 3. anticipation ─────────────────────────────────────────────────────
def onset_and_shape(rows):
    """(nose distance to the wall when the heading first turns, the peak
    curvature, the largest one-frame jump in curvature, the nearest the
    nose ever gets) — curvature as a fraction of the tightest turn."""
    kap = np.array([k for _, _, k in rows])
    gap = np.array([g for g, _, _ in rows])
    turning = np.flatnonzero(kap > 0.02)
    onset = float(gap[turning[0]]) if turning.size else float("nan")
    jump = float(np.max(np.abs(np.diff(kap)))) if kap.size > 1 else 0.0
    return onset, float(kap.max()), jump, float(gap.min())


def section_approach():
    print("\n3. ANTICIPATION — one fish swimming at the top wall "
          "(House Fish's size and speed)")
    out = {}
    for label, extra in (("before", OLD), ("after", {})):
        rows = asyncio.run(approach(dict(HOUSE_FISH, **extra)))
        onset, peak, jump, nearest = onset_and_shape(rows)
        out[label] = (onset, peak, jump, nearest)
        print(f"   {label:6s}: starts turning with its nose {onset:5.1f}px "
              f"from the wall; peak curvature {peak:4.2f} of its tightest "
              f"turn; biggest one-frame change {jump:4.2f}; nose comes "
              f"within {nearest:5.1f}px")
    b, a = out["before"], out["after"]
    check(a[0] > b[0] + 2.0, "after: the turn starts well before the wall "
          "(earlier than before)")
    check(a[2] < b[2], "after: the turn eases in — no one-frame snap as "
          "large as before's")
    check(a[3] >= 0.0, "after: the nose never reaches the wall")


# ── 4. the solo burst ───────────────────────────────────────────────────
async def burst_run(cfg, seconds, seed=2):
    r = await rig("burst", cfg, seed=seed)
    eff = r.effect
    r.step(1)                       # the panel is known after a frame
    cruise = eff.cruise_px
    starts = []
    peak = 0.0
    prev_t = eff.p_sb_t[: eff.n].copy()
    for i in range(int(seconds / DT)):
        r.step(1)
        n = eff.n
        now = eff.p_sb_t[:n]
        began = (now > 0) & (np.pad(prev_t, (0, max(n - prev_t.size, 0)))[:n]
                             <= 0)
        starts.extend([i * DT] * int(began.sum()))
        if eff.p_sb[:n].any():
            peak = max(peak, float((eff.p_spd[:n][eff.p_sb[:n] > 0.9]
                                    / cruise).max(initial=0.0)))
        prev_t = now.copy()
    # after the last burst has had time to ease out: everyone is back
    settle_frames = int((cfg.get("solo_burst_time", 0.8) + 3.0) / DT)
    eff.update_config({"solo_burst_rate": 0.0})
    r.step(settle_frames)
    back = float(np.abs(eff.p_spd[: eff.n] / cruise).max())
    left = float(eff.p_sb[: eff.n].max())
    count = eff.solo_bursts
    await close(r)
    return count, starts, peak, back, left


def section_burst(minutes=6.0):
    print("\n4. THE SOLO BURST — House Fish's own settings "
          f"{SOLO_BURST_PARAMS}")
    cfg = dict(HOUSE_FISH, **SOLO_BURST_PARAMS)
    count, starts, peak, back, left = asyncio.run(
        burst_run(cfg, minutes * 60.0)
    )
    want = SOLO_BURST_PARAMS["solo_burst_rate"] * minutes
    sd = np.sqrt(want)
    print(f"   {count} bursts in {minutes:.0f} min (expected {want:.0f}, "
          f"Poisson sd {sd:.1f}); top speed seen {peak:.2f}x cruise; once "
          f"they stop, the fastest fish is at {back:.2f}x cruise, envelope "
          f"{left:.3f}")
    check(abs(count - want) <= 3.0 * sd, "about the configured rate")
    check(peak >= 0.85 * SOLO_BURST_PARAMS["solo_burst_speed"],
          "a burst really reaches its top speed")
    check(left == 0.0 and back <= 1.4,
          "every burst eases back to the ordinary speed (the thrust pulse "
          "peaks at 1.25x)")
    gaps = np.diff(starts)
    if gaps.size:
        print(f"   gaps between bursts: min {gaps.min():.1f}s, median "
              f"{np.median(gaps):.1f}s, max {gaps.max():.1f}s (irregular)")
    c0, _, _, _, _ = asyncio.run(burst_run(dict(HOUSE_FISH), 60.0))
    check(c0 == 0, "the effect's own default (rate 0): no solo bursts at "
          "all — the music Fish scene is untouched")


# ── 5. cost ─────────────────────────────────────────────────────────────
def section_cost():
    print("\n5. COST — the wall steer's own time per frame (this machine)")

    async def go(cfg):
        r = await rig("cost", cfg, seed=0)
        eff = r.effect
        orig = FX.Fish2d._wall_steer
        took = []

        def timed(self, *a):
            t0 = time.perf_counter()
            out = orig(self, *a)
            took.append(time.perf_counter() - t0)
            return out

        FX.Fish2d._wall_steer = timed
        try:
            r.step(600)
        finally:
            FX.Fish2d._wall_steer = orig
        await close(r)
        return np.percentile(took, 50) * 1e3, np.percentile(took, 95) * 1e3

    for name, cfg in (("House Fish (5)", HOUSE_FISH),
                      ("Fish (3)", MUSIC_FISH),
                      ("Fish at 16", dict(MUSIC_FISH, particle_count=16))):
        p50, p95 = asyncio.run(go(cfg))
        print(f"   {name:15s} p50 {p50:.2f} ms  p95 {p95:.2f} ms")


# ── the GIFs ────────────────────────────────────────────────────────────
CELL = 8


def _outline(lit):
    edges = []
    for r in range(ROWS):
        for c in range(COLS):
            if not lit[r, c]:
                continue
            for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                rr, cc = r + dr, c + dc
                if not (0 <= rr < ROWS and 0 <= cc < COLS) or not lit[rr, cc]:
                    edges.append((r, c, dr, dc))
    return edges


def draw_crystal(pixels, real, lit, edges, label):
    """One frame as his crystal shows it: the real cells as dots, the lit
    outline faint, and any light the panel CANNOT show (outside the lit
    area) marked in red."""
    img = Image.new("RGB", (COLS * CELL, ROWS * CELL + 14), (6, 6, 10))
    d = ImageDraw.Draw(img)
    for r, c, dr, dc in edges:
        x0, y0 = c * CELL, r * CELL + 14
        if dc:
            x = x0 + (CELL if dc > 0 else 0)
            d.line([(x, y0), (x, y0 + CELL)], fill=(50, 50, 70))
        else:
            y = y0 + (CELL if dr > 0 else 0)
            d.line([(x0, y), (x0 + CELL, y)], fill=(50, 50, 70))
    grid = pixels.reshape(ROWS, COLS, 3)
    for r in range(ROWS):
        for c in range(COLS):
            col = tuple(int(v) for v in grid[r, c])
            x0, y0 = c * CELL, r * CELL + 14
            if real[r, c]:
                if max(col) > 3:
                    d.ellipse([x0 + 1, y0 + 1, x0 + CELL - 1, y0 + CELL - 1],
                              fill=col)
                else:
                    d.ellipse([x0 + 3, y0 + 3, x0 + CELL - 3, y0 + CELL - 3],
                              fill=(20, 20, 26))
            elif not lit[r, c] and max(col) > 10:
                d.rectangle([x0 + 2, y0 + 2, x0 + CELL - 2, y0 + CELL - 2],
                            outline=(200, 40, 40))
    d.text((4, 1), label, fill=(225, 225, 225))
    return img


async def frames_for(cfg, seconds, seed, setup=None, every=2, still=False):
    """still=True holds the wander swing and the home pull at zero for the
    run (module constants, restored), the approach measurement's own
    setup, so BEFORE and AFTER swim the identical straight line until the
    edge turns them."""
    if not still:
        return await _frames_for(cfg, seconds, seed, setup, every)
    names = ("WANDER_SWING", "WANDER_SWING_JIGGLE", "HOME_W")
    saved = {k: getattr(FX, k) for k in names}
    for k in names:
        setattr(FX, k, 0.0)
    try:
        return await _frames_for(cfg, seconds, seed, setup, every)
    finally:
        for k, v in saved.items():
            setattr(FX, k, v)


async def _frames_for(cfg, seconds, seed, setup, every):
    r = await rig("gif", cfg, seed=seed)
    eff = r.effect
    out = []
    r.step(1)
    if setup is not None:
        setup(eff)
    for i in range(int(seconds / DT)):
        r.step(1)
        if i % every == 0:
            out.append(np.asarray(eff.matrix, dtype=np.uint8).reshape(-1, 3)
                       .copy())
    await close(r)
    return out


def save_gif(frames, path, every=2):
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=int(1000 * DT * every), loop=0, optimize=True)


def write_gifs(outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    real = crystal_real_mask().reshape(ROWS, COLS)
    lit = lit_area(crystal_real_mask())
    edges = _outline(lit)

    def side_by_side(cfg, seconds, seed, name, setup=None, note="",
                     every=2, still=False):
        before = asyncio.run(frames_for(dict(cfg, **OLD), seconds, seed,
                                        setup=setup, every=every,
                                        still=still))
        after = asyncio.run(frames_for(cfg, seconds, seed, setup=setup,
                                       every=every, still=still))
        imgs = []
        for fb, fa in zip(before, after):
            a = draw_crystal(fb, real, lit, edges, f"BEFORE {note}")
            b = draw_crystal(fa, real, lit, edges, f"AFTER {note}")
            both = Image.new("RGB", (a.width, a.height * 2 + 4), (0, 0, 0))
            both.paste(a, (0, 0))
            both.paste(b, (0, a.height + 4))
            imgs.append(both)
        save_gif(imgs, outdir / name, every=every)
        print(f"   wrote {outdir / name} ({len(imgs)} frames)")

    def aim(eff):
        # middle of the panel, heading up and to the right: the whole body
        # starts inside the lit area, so any red later is the edge's doing
        eff.p_x[0] = (30.0 - eff.cx) / eff.sx
        eff.p_y[0] = (24.0 - eff.cy) / eff.sy
        eff.p_hd[0] = np.deg2rad(-55.0)
        eff.p_trail_x[0, 0] = np.nan
        eff.p_spd[0] = eff.cruise_px
        _fresh(eff)
        # and the smear of where it spawned a frame ago is not this run's
        for buf in (eff.trail, eff.wake):
            if buf is not None:
                buf[...] = 0.0

    lone = dict(HOUSE_FISH, particle_count=1, jiggle=0.0, spin=0.0,
                horizon_scale=0.0, speed_jump=0.0, speed_jog=0.0,
                reactivity_scale=0.0, min_drift_speed=1.0,
                stroke_speed_cap=0.0, avoid_strength=0.0)
    side_by_side(lone, 4.0, 1, "fish_wall_approach.gif", setup=aim,
                 still=True, note="one House Fish swims at the wall")
    side_by_side(HOUSE_FISH, 10.0, 4, "fish_wall_house.gif", every=3,
                 note="House Fish (red = light the panel can't show)")
    side_by_side(MUSIC_FISH, 10.0, 3, "fish_wall_music.gif", every=3,
                 note="Fish (music scene)")

    cfg = dict(HOUSE_FISH, **dict(SOLO_BURST_PARAMS, solo_burst_rate=20.0))
    frames = asyncio.run(frames_for(cfg, 12.0, 5, every=3))
    imgs = [draw_crystal(f, real, lit, edges,
                         "House Fish solo bursts (rate raised to 20/min to "
                         "show several)") for f in frames]
    save_gif(imgs, outdir / "fish_solo_burst.gif", every=3)
    print(f"   wrote {outdir / 'fish_solo_burst.gif'} ({len(imgs)} frames)")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--gifs", type=Path, default=None,
                        help="also write before/after GIFs into this dir")
    args = parser.parse_args()
    headless.silence_audio()
    section_shape()
    section_escape_hatch()
    section_wall()
    section_loud()
    section_approach()
    section_burst()
    section_cost()
    if args.gifs:
        print("\nGIFs")
        write_gifs(args.gifs)
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
        # fx.headless leaves non-daemon effect threads behind; a plain
        # return would hang the interpreter (AGENTS.md)
        sys.stdout.flush()
        os._exit(status)
