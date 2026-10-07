"""Measure the FISH WALL (fx/effects/fish.py, the WALL block) and the House
Fish SOLO BURST, on the real vendored render pipeline — fx.headless with his
crystal-mapper's REAL shape: 72x37 cells, the real ones on one dummy device
and the dark ones on a `gap-` device, segment for segment from
storage/device_profiles/crystal-mapper.json.

HIS WORDS, 2026-10-06: "the fish don't interact with the 'wall' naturally.
Have them 'anticipate' the wall and start turning away. Do this on both fish
scenes. In house fish scene, give individual ones an occasional burst of
speed." And 2026-10-07, on what the first build did: "The fish now get stuck
in the middle. I still want them to go right up to the edge of the wall, but
i want them to start turning so their bodies sides touch the walls, more
than their heads. That should improve how natural the motion looks. It's
okay for light to bleed off the fixture, I'm more interested in a natural
look."

Three fish are compared throughout: the OLD edge (`wall_lookahead = 0`, the
pond-edge pivot from before any of this), PR 361 (the first wall build,
loaded out of git at its pinned merge commit — the "stuck in the middle" he
saw) and the NEW glance. Every measurement is taken against the lit area
computed HERE (the row span of the device profile's real cells, as a
sub-pixel distance from an upsampled distance transform), never the effect's
own field, so the effect is not marking its own homework.

  0. THE WALL IS THE PANEL'S REAL SHAPE: what the effect reads off the
     virtual's own segments is the device profile's mask, and its lit
     silhouette holds every real cell.
  1. THE ESCAPE HATCH: at `wall_lookahead = 0` the effect reproduces the
     PINNED pre-wall fish bit for bit — kinematics through a whole swim /
     charge / lull / drop arc, on the crystal and on a plain rectangle.
  2. HIS SCENES, old / PR 361 / new, at their live params over three seeds:
       cover     share of the lit cells a fish's middle passed over (the
                 panel used, not the middle crowded)
       wall      share of fish-time its FLANK's light lies on the lit edge
                 (right up to the wall)
       alongside of the time it touches, the share with its heading within
                 20 degrees of the wall; pointing-in, the share more than 45
       tightest  share of fish-time turning at 90%+ of its tightest turn (a
                 pivot, not a sweep)
       off       share of fish-time its MIDDLE is past the lit edge
     PR 361 is the regression this replaces: asserted to have kept every
     fish off the wall and crowded in the middle, so the bar can see it.
  2b. A LOUD PASSAGE: his music fish at 3-6x cruise — no middle leaves the
     panel and the wake stays subtle against the fish.
  3. ONE FISH AT THE WALL, four approach angles: how far its nose still is
     from the wall when it starts to turn, how sharply the turn ever changes
     from one frame to the next, and whether its side reaches the wall —
     old edge vs new.
  4. THE SOLO BURST: at the House Fish scene's own settings, bursts land at
     about the configured rate, reach their top speed, and every one eases
     back to the fish's ordinary speed; at the effect's own default (rate 0)
     there are none.
  5. COST: the wall steer's own time per frame at his scenes' fish counts
     (reported, not asserted — it is this machine's number).

Read-only, offline, no live access.

    .venv/bin/python scripts/check_fish_wall.py
    .venv/bin/python scripts/check_fish_wall.py --gifs <dir>   # + evidence
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
from scipy.ndimage import distance_transform_edt, gaussian_filter

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fx import headless  # noqa: E402
from fx.effects import fish as FX  # noqa: E402
from scripts.add_house_fish_solo_burst import SOLO_BURST_PARAMS  # noqa: E402

DT = 1.0 / 60.0
ROWS, COLS = 37, 72

# THE PINNED PREDECESSORS, never moving refs (see scripts/check_fish_camera.py's
# BASELINE_REF for what a moving ref once did to a proof):
# the merge-base of the first wall build — master before the wall and the
# solo burst existed, what `wall_lookahead = 0` must still be bit for bit
WALL_BASELINE_REF = "a096a90bd40ad9eff350c9635c03b460b5aad2f7"
# the first wall build itself (PR 361), the "stuck in the middle" he saw
PR361_REF = "f8e61fd0b84646db641822ff13e22d5288326627"

# his live "House Fish" Matrix entry (storage/spectra/scenes.json, read
# 2026-10-07), its solo burst aside — SOLO_BURST_PARAMS adds it back where
# the scene's own behaviour is measured
HOUSE_FISH = {
    "particle_count": 5, "blob_size": 6, "base_speed": 0.16,
    "reactivity_scale": 0, "brightness_audio": 0, "size_audio": 0,
    "speed_jump": 0, "speed_jog": 0, "jiggle": 0.15, "spin": 0.28,
    "flap_rate": 0.2, "camera_follow": 0, "color_shift": 0,
    "tether_scatter": 0,
}
HOUSE_FISH_LIVE = dict(HOUSE_FISH, **SOLO_BURST_PARAMS)
# his live "Fish" Matrix entry, its bindings at their fallbacks (the same
# read): particle_count 3, blob_size 2.5, reverse off. Its pond is his own
# roam_scale 0.75 — a wall of its own, three quarters of the panel across
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



def load_pr361():
    """PR 361's fish.py, the first wall build, as its own effect — or None
    (a stated skip) when git cannot produce it."""
    return load_baseline_effect(name="fish_wall_pr361", ref=PR361_REF)


# ── the independent edge ────────────────────────────────────────────────
_UP, _PAD = 8, 16
_EDGE = {}


def _edge():
    """The lit area's edge as a SUB-PIXEL signed distance (px, + inside):
    every lit cell a solid square, the field from a distance transform at
    `_UP` times the resolution, plus a smoothed copy for the wall's normal.
    Computed from `lit_area` alone — nothing of the effect's."""
    if not _EDGE:
        lit = lit_area(crystal_real_mask())
        grid = np.zeros((ROWS + 2 * _PAD, COLS + 2 * _PAD), dtype=bool)
        grid[_PAD:-_PAD, _PAD:-_PAD] = lit
        big = np.kron(grid, np.ones((_UP, _UP), dtype=bool))
        sd = np.where(big, distance_transform_edt(big) - 0.5,
                      -(distance_transform_edt(~big) - 0.5)) / _UP
        gy, gx = np.gradient(gaussian_filter(sd, 2.0 * _UP))
        _EDGE.update(sd=sd.astype(np.float32), gx=gx, gy=gy)
    return _EDGE


def edge_distance(x, y):
    """Signed distance (px, + inside the lit area) at SCREEN points."""
    e = _edge()
    sd = e["sd"]
    u = (np.asarray(x, np.float32) + _PAD + 0.5) * _UP - 0.5
    v = (np.asarray(y, np.float32) + _PAD + 0.5) * _UP - 0.5
    u = np.clip(u, 0, sd.shape[1] - 1.001)
    v = np.clip(v, 0, sd.shape[0] - 1.001)
    i, j = u.astype(int), v.astype(int)
    fu, fv = u - i, v - j
    top = sd[j, i] * (1 - fu) + sd[j, i + 1] * fu
    bot = sd[j + 1, i] * (1 - fu) + sd[j + 1, i + 1] * fu
    return top * (1 - fv) + bot * fv


def edge_normal(x, y):
    """The wall's unit inward normal nearest SCREEN points."""
    e = _edge()
    shape = e["sd"].shape
    u = np.clip(((np.asarray(x, np.float32) + _PAD + 0.5) * _UP - 0.5)
                .astype(int), 0, shape[1] - 1)
    v = np.clip(((np.asarray(y, np.float32) + _PAD + 0.5) * _UP - 0.5)
                .astype(int), 0, shape[0] - 1)
    gx, gy = e["gx"][v, u], e["gy"][v, u]
    norm = np.maximum(np.hypot(gx, gy), 1e-9)
    return gx / norm, gy / norm


def body_reach(eff, x, y, hd):
    """(middle, nose light, flank light) distances to the lit edge, px, + =
    inside. The nose's light is its splat (SPINE_PROFILE[0] half-widths)
    round the nose point; the flank's is the widest part of the body (one
    half-width, SPINE_U 0.4) — so <= 0 means that part's light is lying on
    the last lit cells or past them."""
    hw = eff._half_width_px()
    half = hw * eff.body_aspect
    cx, cy = np.cos(hd), np.sin(hd)
    nose = edge_distance(x + cx * half, y + cy * half) - FX.SPINE_PROFILE[0] * hw
    flank = edge_distance(x + cx * 0.2 * half, y + cy * 0.2 * half) - hw
    return edge_distance(x, y), nose, flank


# ── 2. his scenes ───────────────────────────────────────────────────────
async def scene_run(cfg, seed, seconds, effect_type="fish", warmup=2.0):
    """Per swimming-fish frame: middle, nose light and flank light to the
    lit edge, position, the sine of its heading INTO the nearest wall, and
    its curvature as a fraction of its own tightest turn."""
    r = await rig(f"scene{seed}", cfg, seed=seed, effect_type=effect_type)
    eff = r.effect
    rows = []
    prev = {}
    for i in range(int(seconds / DT)):
        r.step(1)
        sw = np.flatnonzero(eff.p_mode[:eff.n] == 0)
        x, y = r.screen(sw)
        hd = eff.p_hd[sw]
        here = {int(f): float(h) for f, h in zip(sw, hd)}
        if i * DT >= warmup and sw.size:
            mid, nose, flank = body_reach(eff, x, y, hd)
            nx, ny = edge_normal(x, y)
            into = -(np.cos(hd) * nx + np.sin(hd) * ny)
            for k, f in enumerate(sw):
                f = int(f)
                if f in prev:
                    turned = abs(float(FX._wrap_pi(hd[k] - prev[f])))
                    kap = turned / max(float(eff.p_spd[f]) * DT, 1e-6) \
                        * eff.turn_radius_px
                else:
                    kap = 0.0
                rows.append((mid[k], nose[k], flank[k], x[k], y[k], into[k],
                             kap))
        prev = here
    await close(r)
    return np.array(rows, dtype=np.float64).reshape(-1, 7)


def scene_metrics(rec):
    mid, nose, flank, x, y, into, kap = rec.T
    lit = lit_area(crystal_real_mask())
    rr, cc = np.nonzero(lit)
    seen = np.zeros(rr.size, dtype=bool)
    pts = np.stack([x, y], axis=1)
    for lo in range(0, len(pts), 2000):
        p = pts[lo: lo + 2000]
        d = np.hypot(cc[None, :] - p[:, :1], rr[None, :] - p[:, 1:])
        seen |= (d <= 1.5).any(axis=0)
    touch = (flank <= 0.0) | (nose <= 0.0)
    ang = np.degrees(np.arcsin(np.clip(into, -1.0, 1.0)))
    t = touch if touch.any() else np.ones_like(touch)
    return {
        "cover": 100.0 * seen.mean(),
        "wall": 100.0 * np.mean(flank <= 0.0),
        "alongside": 100.0 * np.mean(np.abs(ang[t]) < 20.0) if touch.any()
        else 0.0,
        "pointing": 100.0 * np.mean(ang[t] > 45.0) if touch.any() else 0.0,
        "tightest": 100.0 * np.mean(kap >= 0.9),
        "off": 100.0 * np.mean(mid < 0.0),
        "flank_first": 100.0 * np.mean(flank[t] < nose[t]) if touch.any()
        else 0.0,
    }


def measure_scene(cfg, effect_type, seeds, seconds):
    rec = np.concatenate([asyncio.run(scene_run(cfg, s, seconds, effect_type))
                          for s in seeds])
    return scene_metrics(rec)


def _row(name, m):
    return (f"   {name:9s} cover {m['cover']:5.1f}%  wall {m['wall']:5.1f}%  "
            f"alongside {m['alongside']:5.1f}%  pointing-in "
            f"{m['pointing']:4.1f}%  tightest {m['tightest']:5.1f}%  "
            f"off {m['off']:4.1f}%  (flank deeper than nose "
            f"{m['flank_first']:4.1f}% of contact)")


def section_scenes(seeds=(0, 1, 2), seconds=30.0):
    print("\n2. HIS SCENES — old edge / PR 361 / new, live params, "
          f"{len(seeds)} seeds x {seconds:.0f}s")
    pr = load_pr361()
    out = {}
    for name, cfg in (("House Fish", HOUSE_FISH_LIVE), ("Fish", MUSIC_FISH)):
        print(f"  {name}")
        got = {}
        for label, extra, et in (("old edge", OLD, "fish"),
                                 ("PR 361", {}, pr),
                                 ("new", {}, "fish")):
            if et is None:
                continue
            got[label] = measure_scene(dict(cfg, **extra), et, seeds, seconds)
            print(_row(label, got[label]))
        out[name] = got
    h = out["House Fish"]
    new, old = h["new"], h["old edge"]
    if "PR 361" in h:
        p = h["PR 361"]
        check(p["wall"] < 1.0 and p["cover"] < 35.0,
              f"control — PR 361 kept every House Fish off the wall "
              f"({p['wall']:.1f}%) and crowded in the middle ({p['cover']:.1f}"
              "% of the panel): the regression the bar must see")
        check(new["cover"] >= 2.0 * p["cover"],
              "House Fish: uses the panel — at least twice the cover PR 361 "
              "had")
    check(new["cover"] >= old["cover"] - 8.0,
          "House Fish: about as much of the panel as before any wall")
    check(new["wall"] >= 40.0,
          "House Fish: right up to the wall — its flank's light lies on the "
          "edge 40%+ of the time")
    check(new["alongside"] >= 70.0 and new["pointing"] <= 6.0,
          "House Fish: touching the wall, its body lies along it (heading "
          "within 20 degrees) 70%+ of the time and points into it (>45) "
          "rarely")
    check(new["tightest"] <= old["tightest"] / 3.0,
          "House Fish: sweeps, not pivots — a third or less of the old "
          "edge's time at its tightest turn")
    check(new["off"] <= 0.5,
          "House Fish: no middle leaves the panel")
    f = out["Fish"]
    if "PR 361" in f:
        check(f["new"]["cover"] >= f["PR 361"]["cover"] + 10.0,
              "Fish: more of its pond used than PR 361")
    check(f["new"]["tightest"] <= f["old edge"]["tightest"],
          "Fish: no more pivoting than the old edge")
    check(f["new"]["off"] <= 0.1, "Fish: no middle leaves the panel")
    # what his music fish would do in a pond the size of the panel (his own
    # roam_scale is 0.75): reported only
    what_if = measure_scene(dict(MUSIC_FISH, roam_scale=0.95), "fish",
                            seeds, seconds)
    print("  Fish with a pond the size of the panel (roam_scale 0.95; his "
          "is 0.75) — reported, not asserted:")
    print(_row("new", what_if))
    return out


# ── 2b. a loud passage ──────────────────────────────────────────────────
async def loud_run(cfg, seed, impulse, seconds=10.0):
    """(worst px a swimming fish's MIDDLE gets past the lit edge, median
    wake-to-fish brightness) under a sustained loud passage."""
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
        if sw.size:
            x, y = r.screen(sw)
            worst = max(worst, float(-edge_distance(x, y).min()))
    await close(r)
    return worst, float(np.median(ratio))


def section_loud():
    print("\n2b. A LOUD PASSAGE — his music fish driven to 3-6x cruise")
    for impulse in (0.3, 0.9):
        res = [asyncio.run(loud_run(MUSIC_FISH, s, impulse)) for s in (1, 2)]
        worst = max(w for w, _ in res)
        ratio = float(np.mean([q for _, q in res]))
        print(f"   impulse {impulse}: middle at worst {worst:5.2f}px past the "
              f"lit edge (negative = inside); wake/fish brightness "
              f"{ratio:.2f}")
        check(worst <= 0.0 and ratio < 0.6,
              f"impulse {impulse}: no middle leaves the panel and the wake "
              "stays subtle (< 0.6 of the fish)")


# ── 3. one fish at the wall ─────────────────────────────────────────────
APPROACHES = ((-40.0, 16.0, 28.0), (-60.0, 22.0, 30.0), (-90.0, 34.0, 30.0),
              (-120.0, 46.0, 30.0))


def _fresh(eff):
    """A placed fish carries none of the turn it was making where it was."""
    for name in ("p_wsg", "p_wurg", "p_wcmd", "p_wauth", "p_jog", "p_ro"):
        getattr(eff, name)[0] = 0.0
    for name in ("p_wr",):
        getattr(eff, name)[0] = 0.0
    eff.p_wph[0] = np.nan


async def approach(cfg, heading, x0, y0, seconds=5.0):
    """One House-Fish-sized fish placed at (x0, y0) heading `heading`
    degrees (screen, y down: negative is up) toward the top wall. Its wander
    SWING and home pull are switched off for this run only (module
    constants, restored), so only the wall can turn it. Returns (the nose
    point's distance to the lit edge when its heading first changes, the
    largest one-frame change in curvature, the peak curvature, whether its
    flank's light ever reached the edge)."""
    lone = dict(cfg, particle_count=1, jiggle=0.0, spin=0.0,
                horizon_scale=0.0, speed_jump=0.0, speed_jog=0.0,
                reactivity_scale=0.0, min_drift_speed=1.0,
                stroke_speed_cap=0.0, avoid_strength=0.0)
    names = ("WANDER_SWING", "WANDER_SWING_JIGGLE", "HOME_W")
    saved = {k: getattr(FX, k) for k in names}
    for k in names:
        setattr(FX, k, 0.0)
    try:
        r = await rig("approach", lone, seed=1)
        eff = r.effect
        r.step(1)
        eff.p_x[0] = (x0 - eff.cx) / eff.sx
        eff.p_y[0] = (y0 - eff.cy) / eff.sy
        eff.p_hd[0] = np.deg2rad(heading)
        eff.p_trail_x[0, 0] = np.nan
        eff.p_spd[0] = eff.cruise_px
        _fresh(eff)
        half = eff._half_width_px() * eff.body_aspect
        prev = float(eff.p_hd[0])
        onset = None
        peak = jump = last = 0.0
        touched = False
        for _ in range(int(seconds / DT)):
            r.step(1)
            x, y = r.screen(np.array([0]))
            hd = float(eff.p_hd[0])
            kap = abs(float(FX._wrap_pi(hd - prev))) / max(
                float(eff.p_spd[0]) * DT, 1e-6) * eff.turn_radius_px
            prev = hd
            if onset is None and kap > 0.02:
                onset = float(edge_distance(x + np.cos(hd) * half,
                                            y + np.sin(hd) * half)[0])
            jump = max(jump, abs(kap - last))
            last = kap
            peak = max(peak, kap)
            _, _, flank = body_reach(eff, x, y, np.array([hd]))
            touched = touched or bool(flank[0] <= 0.0)
        await close(r)
    finally:
        for k, v in saved.items():
            setattr(FX, k, v)
    return (onset if onset is not None else float("nan")), jump, peak, touched


def section_approach():
    print("\n3. ONE FISH AT THE WALL — House Fish's size and speed, four "
          "approaches to the top wall")
    for heading, x0, y0 in APPROACHES:
        res = {}
        for label, extra in (("old edge", OLD), ("new", {})):
            res[label] = asyncio.run(approach(dict(HOUSE_FISH, **extra),
                                              heading, x0, y0))
            onset, jump, peak, touched = res[label]
            print(f"   {heading:6.0f} deg {label:8s}: starts turning with its "
                  f"nose {onset:5.1f}px from the wall; biggest one-frame "
                  f"change in curvature {jump:4.2f}; peak {peak:4.2f}; side "
                  f"reaches the wall: {'yes' if touched else 'no'}")
        o, n = res["old edge"], res["new"]
        into = abs(heading) if abs(heading) <= 90 else 180 - abs(heading)
        if into >= 60:
            check(n[0] > o[0] + 1.0,
                  f"{heading:.0f} deg ({into:.0f} into the wall): anticipated "
                  "— the turn starts further out than the old edge's")
        else:
            # a shallow approach is meant to straighten up late, at the wall
            check(n[0] >= o[0] - 0.5,
                  f"{heading:.0f} deg ({into:.0f} into the wall): the turn "
                  "starts no later than the old edge's")
        check(n[1] < 0.3 and n[1] < o[1] / 2.0,
              f"{heading:.0f} deg: the turn never jolts (one-frame change "
              f"{n[1]:.2f} against the old edge's {o[1]:.2f})")
        check(n[3], f"{heading:.0f} deg: its side reaches the wall")


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




# ── the evidence ────────────────────────────────────────────────────────
CELL = 8
VARIANTS = (("OLD EDGE (before any wall)", OLD), ("PR 361 (stuck in the middle)",
                                                 {}), ("NEW GLANCE", {}))


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
    outline faint, and any light that lands past the panel's edge (where
    there are no cells to show it — he has said that is fine) as a faint
    square."""
    img = Image.new("RGB", (COLS * CELL, ROWS * CELL + 14), (6, 6, 10))
    d = ImageDraw.Draw(img)
    for r, c, dr, dc in edges:
        x0, y0 = c * CELL, r * CELL + 14
        if dc:
            x = x0 + (CELL if dc > 0 else 0)
            d.line([(x, y0), (x, y0 + CELL)], fill=(60, 60, 84))
        else:
            y = y0 + (CELL if dr > 0 else 0)
            d.line([(x0, y), (x0 + CELL, y)], fill=(60, 60, 84))
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
                dim = tuple(int(v * 0.35) for v in col)
                d.rectangle([x0 + 2, y0 + 2, x0 + CELL - 2, y0 + CELL - 2],
                            outline=dim)
    d.text((4, 1), label, fill=(225, 225, 225))
    return img


async def _frames(cfg, seconds, seed, effect_type, every, setup=None):
    r = await rig("gif", cfg, seed=seed, effect_type=effect_type)
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


def save_gif(frames, path, every):
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=int(round(1000 * DT * every)), loop=0,
                   optimize=True)


def _stack(rows):
    w = max(im.width for im in rows)
    h = sum(im.height for im in rows) + 4 * (len(rows) - 1)
    out = Image.new("RGB", (w, h), (0, 0, 0))
    y = 0
    for im in rows:
        out.paste(im, (0, y))
        y += im.height + 4
    return out


def comparison_gif(cfg, seconds, seed, path, title, every=3, setup=None,
                   still=False):
    """Old edge / PR 361 / new, one above the other, the same seed and the
    same frames — the real light on his crystal's real cells."""
    real = crystal_real_mask().reshape(ROWS, COLS)
    lit = lit_area(crystal_real_mask())
    edges = _outline(lit)
    pr = load_pr361()
    names = ("WANDER_SWING", "WANDER_SWING_JIGGLE", "HOME_W")
    saved = {k: getattr(FX, k) for k in names}
    runs = []
    try:
        if still:
            for k in names:
                setattr(FX, k, 0.0)
        for label, extra in VARIANTS:
            et = pr if label.startswith("PR 361") else "fish"
            if et is None:
                continue
            runs.append((label, asyncio.run(_frames(
                dict(cfg, **extra), seconds, seed, et, every, setup))))
    finally:
        for k, v in saved.items():
            setattr(FX, k, v)
    imgs = []
    for k in range(min(len(f) for _, f in runs)):
        rows = [draw_crystal(f[k], real, lit, edges,
                             f"{label} - {title}") for label, f in runs]
        imgs.append(_stack(rows))
    save_gif(imgs, path, every)
    print(f"   wrote {path} ({len(imgs)} frames)")


async def _tracks(cfg, seconds, seed, effect_type):
    r = await rig("tracks", cfg, seed=seed, effect_type=effect_type)
    eff = r.effect
    out = []
    for i in range(int(seconds / DT)):
        r.step(1)
        sw = np.flatnonzero(eff.p_mode[:eff.n] == 0)
        x, y = r.screen(sw)
        out.append((i, sw.copy(), x.copy(), y.copy(), eff.p_hd[sw].copy(),
                    eff._half_width_px() * eff.body_aspect))
    await close(r)
    return out


TRACK_COLORS = ((80, 200, 255), (255, 170, 60), (120, 255, 120),
                (255, 110, 200), (200, 160, 255), (255, 255, 120),
                (120, 255, 230), (255, 140, 140))


def track_plot(cfg, seconds, seed, path, title, every=30):
    """Each fish's middle as a line over the run, on the panel's outline,
    with its body drawn every `every` frames — old edge / PR 361 / new."""
    sc = 10
    lit = lit_area(crystal_real_mask())
    edges = _outline(lit)
    pr = load_pr361()
    panels = []
    for label, extra in VARIANTS:
        et = pr if label.startswith("PR 361") else "fish"
        if et is None:
            continue
        frames = asyncio.run(_tracks(dict(cfg, **extra), seconds, seed, et))
        img = Image.new("RGB", (COLS * sc, ROWS * sc + 18), (8, 8, 12))
        d = ImageDraw.Draw(img)
        for r, c, dr, dc in edges:
            x0, y0 = c * sc, r * sc + 18
            if dc:
                x = x0 + (sc if dc > 0 else 0)
                d.line([(x, y0), (x, y0 + sc)], fill=(90, 90, 120), width=2)
            else:
                y = y0 + (sc if dr > 0 else 0)
                d.line([(x0, y), (x0 + sc, y)], fill=(90, 90, 120), width=2)

        def at(px, py):
            return ((px + 0.5) * sc, (py + 0.5) * sc + 18)

        last = {}
        for i, sw, x, y, hd, half in frames:
            if i * DT < 1.0:
                continue
            for k, f in enumerate(sw):
                col = TRACK_COLORS[int(f) % len(TRACK_COLORS)]
                p = at(x[k], y[k])
                if f in last:
                    d.line([last[f], p], fill=tuple(int(v * 0.45) for v in col),
                           width=2)
                last[f] = p
                if i % every == 0:
                    nx, ny = x[k] + np.cos(hd[k]) * half, y[k] + np.sin(hd[k]) * half
                    tx, ty = x[k] - np.cos(hd[k]) * half, y[k] - np.sin(hd[k]) * half
                    d.line([at(tx, ty), at(nx, ny)], fill=col, width=3)
                    q = at(nx, ny)
                    d.ellipse([q[0] - 3, q[1] - 3, q[0] + 3, q[1] + 3],
                              outline=col)
        d.text((6, 3), f"{label} - {title} - {seconds:.0f}s of tracks (a "
               "line per fish; its body every half second, nose circled)",
               fill=(230, 230, 230))
        panels.append(img)
    _stack(panels).save(path)
    print(f"   wrote {path}")


def write_evidence(outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    comparison_gif(HOUSE_FISH_LIVE, 12.0, 4, outdir / "fish_wall_house.gif",
                   "House Fish")
    comparison_gif(MUSIC_FISH, 12.0, 3, outdir / "fish_wall_music.gif",
                   "Fish (music scene, his pond 0.75)")
    track_plot(HOUSE_FISH_LIVE, 20.0, 1, outdir / "fish_wall_tracks_house.png",
               "House Fish")
    track_plot(MUSIC_FISH, 20.0, 1, outdir / "fish_wall_tracks_music.png",
               "Fish")

    def aim(eff):
        eff.p_x[0] = (22.0 - eff.cx) / eff.sx
        eff.p_y[0] = (30.0 - eff.cy) / eff.sy
        eff.p_hd[0] = np.deg2rad(-60.0)
        eff.p_trail_x[0, 0] = np.nan
        eff.p_spd[0] = eff.cruise_px
        for buf in (eff.trail, eff.wake):
            if buf is not None:
                buf[...] = 0.0

    lone = dict(HOUSE_FISH, particle_count=1, jiggle=0.0, spin=0.0,
                horizon_scale=0.0, speed_jump=0.0, speed_jog=0.0,
                reactivity_scale=0.0, min_drift_speed=1.0,
                stroke_speed_cap=0.0, avoid_strength=0.0)
    comparison_gif(lone, 6.0, 1, outdir / "fish_wall_approach.gif",
                   "one House Fish swims up at the top wall", every=2,
                   setup=aim, still=True)
    cfg = dict(HOUSE_FISH, **dict(SOLO_BURST_PARAMS, solo_burst_rate=20.0))
    real = crystal_real_mask().reshape(ROWS, COLS)
    lit = lit_area(crystal_real_mask())
    frames = asyncio.run(_frames(cfg, 12.0, 5, "fish", 3))
    imgs = [draw_crystal(f, real, lit, _outline(lit),
                         "House Fish solo bursts (rate raised to 20/min to "
                         "show several)") for f in frames]
    save_gif(imgs, outdir / "fish_solo_burst.gif", 3)
    print(f"   wrote {outdir / 'fish_solo_burst.gif'} ({len(imgs)} frames)")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--gifs", type=Path, default=None,
                        help="also write the before/after evidence (GIFs and "
                        "track plots) into this dir")
    args = parser.parse_args()
    headless.silence_audio()
    section_shape()
    section_escape_hatch()
    section_scenes()
    section_loud()
    section_approach()
    section_burst()
    section_cost()
    if args.gifs:
        print("\nEVIDENCE")
        write_evidence(args.gifs)
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
