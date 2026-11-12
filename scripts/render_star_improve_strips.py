"""STAR improve plan — the STRIP measurements and clips (facts 1e / visual v, vi).

Hosts, on the real render pipeline (tests/strip_phase_harness.Room: fx.headless
dummy devices, fake clock, the production ResponseEngine), one 560-px strip
per candidate — the tv-mapper's own length — all fed the SAME deterministic
audio and the SAME colour set, in dark mode (background black):

  today's Melt (the live tv-mapper config: speed 0.2, reactivity 0.23, blur 0,
  brightness 1.0), the other scenes' strip effects with their LIVE scene params
  (Black Hole V2's blackhole1d, Orbits V2's orbits1d at intensity 0.5,
  Fireworks V2's fireworks1d, Squiggles' orbits1d at brightness 0.35), and
  Melt "dark blob" proposals (a value gamma, and a value floor cut at two depths).

Measures per frame: lit fraction (max channel > 20/255) and mean perceived
luminance; writes measure.json and one sprite PNG per candidate (width 560,
one row per captured frame at 20 fps) for the explainer.

Usage: .venv/bin/python scripts/render_star_improve_strips.py OUT_DIR
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from strip_phase_harness import Room, run, lum  # noqa: E402

N = 560
SECONDS = 14.0
WARM = 2.0
CAPTURE_FPS = 20
PALETTE = ("linear-gradient(90deg, #00ffff 0.00%,#0000ff 58.00%,#8b00ff 100.00%)")  # Mid - Purple Blue Waves (Strips and Matrix)
PALETTE_NAME = "Mid - Purple Blue Waves"

MELT_LIVE = {"speed": 0.2, "reactivity": 0.23, "blur": 0.0, "brightness": 1.0,
             "background_brightness": 0.0, "gradient": PALETTE}
BH = {"swirl": 3.1, "radius_scale": 1, "blob_size": 0.5, "reverse": True,
      "x_offset": 0.5, "base_speed": 1, "accel": 5, "spawn_rate": 1,
      "beat_burst": 2, "spawn_audio": 1, "speed_audio": 2.3,
      "impulse_decay": 0.06, "max_blobs": 50, "edge_speed": 1,
      "approach_width": 0.16, "gradient": PALETTE, "background_brightness": 0.0}
ORB = {"particle_count": 4, "blob_size": 2.0, "x_offset": 0.5, "spin": 0.15,
       "base_speed": 0.5, "jiggle": 0.2, "tether_scatter": 0.1,
       "reactivity_scale": 0.5, "speed_jump": 1, "speed_jog": 0.3,
       "brightness_audio": 0.8, "size_audio": 0.5, "color_shift": 1,
       "impulse_decay": 0.06, "overlap_blend": 1, "bounce_chance": 0.2,
       "implode_fade": 0.5, "implode_reach": 0.4, "gradient": PALETTE,
       "background_brightness": 0.0}
FW = {"blob_size": 3.03, "reverse": False, "spawn_rate": 0.5, "beat_burst": 2,
      "spawn_audio": 2, "burst_speed": 0.5, "burst_life": 1.2,
      "speed_audio": 2.5, "brightness_audio": 2, "max_blobs": 6, "drag": 0.85,
      "impulse_decay": 0.06, "trail_decay": 0.24, "gradient": PALETTE,
      "background_brightness": 0.0}

# the candidates: id -> (effect_type, config, melt value post-process or None)
CANDS = {
    "melt_today": ("melt", MELT_LIVE, None),
    "blackhole1d": ("blackhole1d", BH, None),
    "orbits1d": ("orbits1d", ORB, None),
    "fireworks1d": ("fireworks1d", FW, None),
    "orbits1d_dim": ("orbits1d", {**ORB, "brightness": 0.35}, None),
    "melt_gamma2": ("melt", MELT_LIVE, ("gamma", 2.0)),
    "melt_gamma3": ("melt", MELT_LIVE, ("gamma", 3.0)),
    "melt_cut35": ("melt", MELT_LIVE, ("cut", 0.35)),
    "melt_cut50": ("melt", MELT_LIVE, ("cut", 0.50)),
    "melt_cut65": ("melt", MELT_LIVE, ("cut", 0.65)),
}

LABELS = {
    "melt_today": "Melt — today (STAR's strips, live values)",
    "blackhole1d": "Black Hole strip (Black Hole V2 / Eye V2 / Sauron)",
    "orbits1d": "Orbits strip (Orbits V2 / Dancers V2)",
    "fireworks1d": "Fireworks strip (Fireworks V2 / Fish)",
    "orbits1d_dim": "Orbits strip at brightness 0.35 (Squiggles / Pacman)",
    "melt_gamma2": "Melt — value² (darker valleys, same peaks)",
    "melt_gamma3": "Melt — value³",
    "melt_cut35": "Melt — dark floor 0.35 (true gaps)",
    "melt_cut50": "Melt — dark floor 0.50",
    "melt_cut65": "Melt — dark floor 0.65",
}


def _post(kind, k):
    def f(v):
        if kind == "gamma":
            return np.power(np.clip(v, 0, 1), k)
        if kind == "cut":
            return np.clip((v - k) / (1.0 - k), 0.0, 1.0)
        return v
    return f


def _patch_melt(eff, post):
    orig = eff.render_hsv

    def render_hsv():
        orig()
        eff.hsv_array[:, 2] = post(eff.hsv_array[:, 2])
    eff.render_hsv = render_hsv


async def main(out):
    os.makedirs(out, exist_ok=True)
    spec = {cid: (et, N, 1, dict(cfg)) for cid, (et, cfg, _p) in CANDS.items()}
    with tempfile.TemporaryDirectory() as tmp:
        async with Room(tmp, spec) as room:
            for cid, (_et, _cfg, post) in CANDS.items():
                if post is not None:
                    _patch_melt(room.effects[cid], _post(*post))
            total = int(SECONDS * 60)
            room.step(total)
            every = 60 // CAPTURE_FPS
            warm = int(WARM * 60)
            measure = {"palette": PALETTE_NAME, "seconds": SECONDS,
                       "warm_s": WARM, "capture_fps": CAPTURE_FPS,
                       "strip_px": N, "cands": {}}
            for cid in CANDS:
                frames = room.frames[cid]
                fr = np.stack(frames[warm:])          # (F, N, 3) 0..255
                mx = fr.max(axis=2)
                lit = (mx > 20.0).mean(axis=1)        # per frame lit fraction
                lums = np.array([lum(f) for f in fr])
                dark_gap = (mx <= 20.0).mean(axis=1)
                measure["cands"][cid] = {
                    "label": LABELS[cid],
                    "lit_frac_mean": round(float(lit.mean()), 4),
                    "lit_frac_min": round(float(lit.min()), 4),
                    "lit_frac_max": round(float(lit.max()), 4),
                    "lum_mean": round(float(lums.mean()), 4),
                    "lum_p95": round(float(np.percentile(lums, 95)), 4),
                    "peak_mean": round(float((mx.max(axis=1) / 255.0).mean()), 4),
                    "dark_gap_mean": round(float(dark_gap.mean()), 4),
                }
                cap = fr[::every]
                img = np.clip(cap, 0, 255).astype(np.uint8)   # (rows, 560, 3)
                _save_png(os.path.join(out, f"strip_{cid}.png"), img)
                measure["cands"][cid]["frames"] = int(img.shape[0])
            with open(os.path.join(out, "strips_measure.json"), "w") as fh:
                json.dump(measure, fh, indent=1)
            for cid, m in measure["cands"].items():
                print(f"{cid:14s} lit {m['lit_frac_mean']*100:5.1f}%  "
                      f"lum {m['lum_mean']:.3f}  peak {m['peak_mean']:.2f}  "
                      f"gap {m['dark_gap_mean']*100:5.1f}%")


def _save_png(path, img):
    from PIL import Image
    Image.fromarray(img, "RGB").save(path, optimize=True)


if __name__ == "__main__":
    run(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/star-improve-strips"))
