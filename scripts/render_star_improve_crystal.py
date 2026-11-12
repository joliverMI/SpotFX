"""STAR improve plan — the CRYSTAL clips (visuals i-iv), today beside proposals.

Rig: tests/star_harness.star_room — a real 280-px Melt strip (`radial-dummy`)
under a real Radial on the 72x37 Matrix virtual, fx.headless, fake clock. The
real 976 cells are cut out at capture (storage/device_profiles/
crystal-mapper.json's mask) into a sprite PNG: width 976, one row per 20-fps
frame. Every tile shares ONE scripted "song" (a lows-impulse profile with a
quiet intro, a groove and a loud section) and one seed, so the eye compares
the same moment.

Rotation is driven exactly as the live effect does it — rev/s = 4.8 x
lows_impulse x spin_cfg^2 (fx/effects/radial.py: ROTATION_SPEED_SCALE 0.8,
60 Hz audio callbacks, nonlinear_log(spin, 2)/10) — from the script's impulse,
so "today" tiles are the live law and "proposal" tiles are the law plus the
proposed change. The proposals are PURE DRIVE CHANGES in this rig (how
spin_total advances, what `star` and `edges` are per frame); the effect's own
render code is untouched.

Usage: .venv/bin/python scripts/render_star_improve_crystal.py OUT_DIR
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))
sys.path.insert(0, os.path.join(HERE, ".."))

from star_harness import star_room, COLS, ROWS, lit_cells  # noqa: E402
from strip_phase_harness import run, DT  # noqa: E402

FPS = 60
CAPTURE_FPS = 20
SPEED_SCALE = 0.8            # radial.ROTATION_SPEED_SCALE
CEIL_TODAY = 6.0 * SPEED_SCALE          # 4.8 rev/s at spin 1.0, impulse 1.0
CAP = 0.7 * CEIL_TODAY                  # 3.36 rev/s — "70% of what it is now"
PALETTE = "linear-gradient(90deg, #00ffff 0.00%,#0000ff 58.00%,#8b00ff 100.00%)"

SONG_S = 12.0


def impulse(t: float) -> float:
    """The scripted lows impulse (0..1): a quiet intro, a groove with hits,
    a loud section with bigger hits. Deterministic."""
    beat = (t * 2.0) % 1.0                   # 120 BPM
    hit = np.exp(-beat * 9.0)                # a decaying pulse each beat
    if t < 3.0:
        return 0.04 + 0.04 * hit
    if t < 8.0:
        return 0.22 + 0.55 * hit
    return 0.42 + 0.58 * hit


def energy(t: float) -> float:
    return 0.15 if t < 3.0 else (0.5 if t < 8.0 else 0.9)


def rev_s_today(spin_cfg: float, imp: float) -> float:
    return CEIL_TODAY * imp * spin_cfg * spin_cfg


def crystal_real_mask() -> np.ndarray:
    path = os.path.join(HERE, "..", "storage", "device_profiles",
                        "crystal-mapper.json")
    mask, value = [], False
    for n in json.load(open(path))["mask_rle"]:
        mask.extend([value] * n)
        value = not value
    return np.array(mask, dtype=bool)


MASK = crystal_real_mask()
assert MASK.size == COLS * ROWS and int(MASK.sum()) == 976


class Drive:
    """What one tile does per frame. rev_s(t, i) -> rev/s this frame;
    star(t) -> the `star` param (None = leave); edges_at(t) -> int or None
    (a change goes through the real update_config, so the shape morph runs)."""

    def __init__(self, name, label, rev_s, star=None, edges_at=None,
                 spin_cfg=0.7, star0=0.3, edges0=6):
        self.name, self.label = name, label
        self.rev_s, self.star_fn, self.edges_at = rev_s, star, edges_at
        self.spin_cfg, self.star0, self.edges0 = spin_cfg, star0, edges0


# ── (i) spin from entry ─────────────────────────────────────────────────────
UPDATE_AT = 4.0   # the "update" that today writes spin 0.55 absolute


def today_entry(t, i):
    # the 52% case: fire landed spin 0.0 -> nothing until the update
    if t < UPDATE_AT:
        return 0.0
    return rev_s_today(0.55, impulse(t))


def today_entry_spinning(t, i):
    # the 48% case: spin 0.7 from the fire, reactive only
    return rev_s_today(0.7, impulse(t))


def ease_in(t, tau=1.0):
    x = min(max(t / tau, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def prop_entry(t, i):
    # Q2: ease up to the song's current speed over ~1 s, from the first frame
    return ease_in(t) * rev_s_today(0.7, impulse(t))


def prop_entry_floor(t, i, floor=0.12):
    # the same, never below a quiet floor (base_rotation-style, rev/s)
    return ease_in(t) * max(floor, rev_s_today(0.7, impulse(t)))


# ── (ii) the speed cap ──────────────────────────────────────────────────────
def today_fast(t, i):
    return rev_s_today(0.94, impulse(t))     # intensity 0.9 -> spin 0.94


def prop_capped(t, i):
    return min(CAP, rev_s_today(0.94, impulse(t)))


# ── (iii) the amount of star flows ──────────────────────────────────────────
class StarWave:
    """A continuous wave between lo and hi; its speed follows energy
    (period slow -> fast), its depth is fixed by the pair. Phase integrates
    so a speed change never jumps the value."""

    def __init__(self, lo, hi, period_slow, period_fast, sign=1.0):
        self.lo, self.hi = lo, hi
        self.ps, self.pf = period_slow, period_fast
        self.sign = sign
        self.phase = 0.0
        self.last_t = 0.0

    def __call__(self, t):
        e = energy(t)
        period = self.ps + (self.pf - self.ps) * e
        self.phase += (t - self.last_t) / period
        self.last_t = t
        x = 0.5 - 0.5 * np.cos(2 * np.pi * self.phase)
        return self.sign * (self.lo + (self.hi - self.lo) * x)


def star_static(t):
    return 0.3


# ── (iv) flares change the edges ────────────────────────────────────────────
FLARES_AT = (3.0, 6.0, 9.0)
EDGE_SEQ = (6, 4, 5, 3)   # never the same twice in a row, holds between


def edges_prop(t):
    n = sum(1 for f in FLARES_AT if t >= f)
    return EDGE_SEQ[min(n, len(EDGE_SEQ) - 1)]


def edges_today(t):
    return 6


TILES = [
    # (i)
    Drive("entry_today_zero", "Today (52% of fires): spin lands 0 — still until the update at 4 s",
          today_entry, star=star_static),
    Drive("entry_today_spin", "Today (48% of fires): spin set, reactive only — parked in the quiet intro",
          today_entry_spinning, star=star_static),
    Drive("entry_prop", "Decided: eases up to the song's speed over 1 s from the first frame; no quiet floor — it may slow to a stop in quiet music",
          prop_entry, star=star_static),
    # (ii)
    Drive("cap_today", "Today: spin 0.94 (a loud fire) — peaks reach 4.8 rev/s x impulse",
          today_fast, star=star_static),
    Drive("cap_prop", "Decided: hard clamp at 3.36 rev/s (70%); below it, identical",
          prop_capped, star=star_static),
    # (iii)
    Drive("star_today", "Today: star fixed at 0.3 (or 0.5) for the whole run",
          prop_entry, star=star_static),
    Drive("star_his", "His pick: wave 0.30 ↔ 0.70, period 7 s quiet → 3 s loud",
          prop_entry, star=StarWave(0.30, 0.70, 7.0, 3.0)),
    Drive("star_flat_sym", "Symmetric about FLAT (0): wave −0.20 ↔ +0.20 — points pull out, then tuck in",
          prop_entry, star=StarWave(-0.20, 0.20, 7.0, 3.0)),
    Drive("star_flat_up", "Flat to pointed: wave 0.00 ↔ 0.40 — plain polygon ↔ clear star",
          prop_entry, star=StarWave(0.0, 0.40, 7.0, 3.0)),
    # (iv)
    Drive("edges_today", "Today: edges rolled once at the fire (6 here); flares at 3, 6, 9 s change nothing",
          prop_entry, star=star_static, edges_at=edges_today),
    Drive("edges_prop", "Decided: each upper-band flare morphs to a NEW count (6→4→5→3) over 0.6 s and holds",
          prop_entry, star=star_static, edges_at=edges_prop),
    # the star param itself, frozen shapes for the flat question
    Drive("shape_m05", "star = −0.5", prop_entry, star=lambda t: -0.5),
    Drive("shape_m02", "star = −0.2", prop_entry, star=lambda t: -0.2),
    Drive("shape_00", "star = 0 (flat polygon)", prop_entry, star=lambda t: 0.0),
    Drive("shape_02", "star = 0.2", prop_entry, star=lambda t: 0.2),
    Drive("shape_03", "star = 0.3 (his low)", prop_entry, star=lambda t: 0.3),
    Drive("shape_04", "star = 0.4", prop_entry, star=lambda t: 0.4),
    Drive("shape_05", "star = 0.5 (his high; he assumed flat)", prop_entry, star=lambda t: 0.5),
    Drive("shape_07", "star = 0.7", prop_entry, star=lambda t: 0.7),
]


async def render_tile(tile: Drive, out: str, measure: dict):
    with tempfile.TemporaryDirectory() as tmp:
        async with star_room(tmp, radial={"star": tile.star0, "edges": tile.edges0,
                                           "spin": tile.spin_cfg,
                                           "gradient": PALETTE},
                             melt={"gradient": PALETTE, "speed": 0.2,
                                   "reactivity": 0.23, "blur": 0.0}) as room:
            eff = room.star
            every = FPS // CAPTURE_FPS
            total = int(SONG_S * FPS)
            rows, revs, lit, stars, edges_tr = [], [], [], [], []
            cur_edges = tile.edges0
            for i in range(total):
                t = i * DT
                rs = float(tile.rev_s(t, i))
                room.rev_s = rs
                if tile.star_fn is not None:
                    sv = float(tile.star_fn(t))
                    with eff.lock:
                        eff._config["star"] = sv
                        eff.star = sv
                if tile.edges_at is not None:
                    want = int(tile.edges_at(t))
                    if want != cur_edges:
                        eff.update_config({"edges": want})
                        cur_edges = want
                room.step(1)
                m = room.matrix()                       # ROWS x COLS x 3
                if i % every == 0:
                    flat = m.reshape(-1, 3)[MASK]       # 976 x 3
                    rows.append(np.clip(flat, 0, 255).astype(np.uint8))
                    revs.append(round(rs, 3))
                    lit.append(int((flat.max(axis=1) > 20).sum()))
                    stars.append(round(float(eff.star), 3))
                    edges_tr.append(cur_edges)
            img = np.stack(rows)                        # F x 976 x 3
            from PIL import Image
            Image.fromarray(img, "RGB").save(
                os.path.join(out, f"star_{tile.name}.png"), optimize=True)
            # abruptness: largest frame-to-frame change of the lit count, and
            # the mean per-cell |delta| between captured frames
            d = np.abs(np.diff(img.astype(np.int16), axis=0)).mean(axis=(1, 2))
            measure[tile.name] = {
                "label": tile.label, "frames": int(img.shape[0]),
                "rev_s": revs, "lit": lit, "star": stars, "edges": edges_tr,
                "rev_s_max": max(revs), "rev_s_mean": round(float(np.mean(revs)), 3),
                "lit_min": int(min(lit)), "lit_max": int(max(lit)),
                "lit_jump_max": int(np.abs(np.diff(lit)).max()) if len(lit) > 1 else 0,
                "cell_delta_mean": round(float(d.mean()), 2),
                "cell_delta_max": round(float(d.max()), 2),
            }
            print(f"{tile.name:18s} rev/s max {max(revs):.2f} mean "
                  f"{np.mean(revs):.2f} | lit {min(lit)}..{max(lit)} "
                  f"jump {measure[tile.name]['lit_jump_max']} | Δcell mean "
                  f"{d.mean():.2f} max {d.max():.2f}")


async def main(out):
    os.makedirs(out, exist_ok=True)
    measure = {"song_s": SONG_S, "capture_fps": CAPTURE_FPS,
               "ceil_today_rev_s": CEIL_TODAY, "cap_rev_s": CAP,
               "update_at_s": UPDATE_AT, "flares_at_s": list(FLARES_AT),
               "impulse": [round(impulse(i / CAPTURE_FPS), 3)
                           for i in range(int(SONG_S * CAPTURE_FPS))],
               "tiles": {}}
    for tile in TILES:
        np.random.seed(7)
        await render_tile(tile, out, measure["tiles"])
    with open(os.path.join(out, "crystal_measure.json"), "w") as fh:
        json.dump(measure, fh)
    # the 976 real cells' (col, row) in sprite order, for the page's renderer
    idx = np.flatnonzero(MASK)
    with open(os.path.join(out, "cells.json"), "w") as fh:
        json.dump([[int(k % COLS), int(k // COLS)] for k in idx], fh)


if __name__ == "__main__":
    run(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/star-improve-crystal"))
