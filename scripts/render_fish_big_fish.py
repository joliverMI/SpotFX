"""Offline evidence for THE BIG FISH flare (fx/effects/fish.py's BIG FISH
block, 2026-10-08 — phase 1, the look only).

Renders, on his crystal-mapper's REAL cells (storage/device_profiles/
crystal-mapper.json's mask, through fx.headless — the real vendored render
pipeline, audio silenced), with his music Fish scene's Matrix entry
(scripts/check_fish_wall.py::MUSIC_FISH, its bindings at their fallbacks)
wearing one colour set (GRADIENT below, centre #00c8ff):

  fish_big_fish_speed.gif   one big fish fired at intensity 0.1 / 0.5 /
                            1.0, one above the other — the same colour
                            (all at or past 0.5 is 180°; 0.1 is 120°), the
                            speed following the intensity
  fish_big_fish_colour.gif  intensity 0.2 / 0.35 / 0.5 with the crossing
                            time held at 4 s for all three, so the only
                            difference is the colour: 120° / 150° / 180°
  fish_big_fish_still.png   the middle of each colour crossing, side by side

and prints the measured numbers each one shows (crossing time, the colour
it wore, its brightness against the turned colour). Nothing here touches
the live room or live storage (it reads the device profile, read-only).

    .venv/bin/python scripts/render_fish_big_fish.py --out DIR
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import check_fish_wall as W  # noqa: E402
from fx.effects import fish as FX  # noqa: E402

DT = W.DT
EVERY = 3          # every 3rd frame -> a 20 fps GIF at real time
GRADIENT = ("linear-gradient(90deg, rgb(0, 64, 255) 0%, rgb(0, 200, 255) "
            "50%, rgb(128, 0, 255) 100%)")


async def crossing(intensity, seconds, seed=3, **over):
    """Swim 3 s, fire one big fish, record `seconds`. Returns (frames,
    notes)."""
    cfg = dict(W.MUSIC_FISH, gradient=GRADIENT, **over)
    r = await W.rig("bigfish", cfg, seed=seed)
    eff = r.effect
    frames = []
    r.step(180)
    eff.update_config({"big_fish": max(intensity, FX.BIG_FISH_POKE_FLOOR)})
    gone_at = None
    for i in range(1, int(seconds / DT) + 1):
        r.step(1)
        if i % EVERY == 0:
            frames.append((f"+{i * DT:4.1f}s", np.asarray(eff.matrix, dtype=np.uint8)
                           .reshape(-1, 3).copy()))
        if gone_at is None and not eff._big:
            gone_at = i * DT
    fish = dict(eff.big_fish_last)
    centre = eff.get_gradient_color_vectorized1d(
        np.array([0.5], dtype=np.float32))[0]
    turned = FX.rotate_hue(centre, fish["turn"] * fish["degrees"])
    notes = {
        "intensity": intensity, "cross_s": fish["cross_s"],
        "gone_at_s": gone_at, "degrees": fish["degrees"],
        "turn": fish["turn"], "travel": fish["travel"],
        "centre": centre, "colour": turned * eff.big_fish_brightness,
    }
    await W.close(r)
    return frames, notes


def _hex(rgb):
    return "#" + "".join(f"{int(round(float(v))):02x}" for v in rgb)


def stack_gif(runs, path):
    real = W.crystal_real_mask().reshape(W.ROWS, W.COLS)
    lit = W.lit_area(W.crystal_real_mask())
    edges = W._outline(lit)
    k = min(len(f) for _, f in runs)
    imgs = []
    for j in range(k):
        rows = [W.draw_crystal(f[j][1], real, lit, edges,
                               f"{label} {f[j][0]}") for label, f in runs]
        imgs.append(W._stack(rows))
    W.save_gif(imgs, path, EVERY)
    print(f"   wrote {path} ({len(imgs)} frames)")
    return imgs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    print("\n1. SPEED FOLLOWS INTENSITY — 0.1 / 0.5 / 1.0 (defaults: 7 s "
          "quiet, 2.5 s loud)")
    runs = []
    for i in (0.1, 0.5, 1.0):
        f, n = asyncio.run(crossing(i, 7.5))
        print(f"   intensity {i:.2f}: crossing {n['cross_s']:.2f} s "
              f"(measured gone at +{n['gone_at_s']}s), turned "
              f"{n['turn'] * n['degrees']:+.0f} deg, colour "
              f"{_hex(n['colour'])} (centre {_hex(n['centre'])})")
        runs.append((f"I={i:.1f} {n['cross_s']:.1f}s", f))
    stack_gif(runs, out / "fish_big_fish_speed.gif")

    print("\n2. COLOUR — 0.2 / 0.35 / 0.5, crossing held at 4 s")
    runs = []
    stills = []
    for i in (0.2, 0.35, 0.5):
        f, n = asyncio.run(crossing(i, 4.5, big_fish_cross_slow_s=4.0,
                                    big_fish_cross_fast_s=4.0))
        print(f"   intensity {i:.2f}: {n['turn'] * n['degrees']:+.0f} deg "
              f"-> {_hex(n['colour'])} at 60% (centre "
              f"{_hex(n['centre'])})")
        runs.append((f"I={i:.2f} {n['turn'] * n['degrees']:+.0f}deg", f))
    imgs = stack_gif(runs, out / "fish_big_fish_colour.gif")
    imgs[len(imgs) // 2].save(out / "fish_big_fish_still.png")
    print(f"   wrote {out / 'fish_big_fish_still.png'}")
    return 0


if __name__ == "__main__":
    status = 1
    try:
        status = main()
    except BaseException:                          # noqa: BLE001
        import traceback
        traceback.print_exc()
    finally:
        # fx.headless leaves non-daemon effect threads behind (AGENTS.md)
        sys.stdout.flush()
        os._exit(status)
