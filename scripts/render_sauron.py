#!/usr/bin/env python3
"""Offline evidence for fx/effects/sauron.py: the BUILT effect, rendered on
the real pipeline (fx.headless, audio silenced, a fake clock) onto his
crystal's real 976 cells, side by side on several of his colour sets.

One scripted song drives every tile identically (same seed, so the eye
looks at the same place on every frame of every tile): 120 BPM, ordinary
hits, three big hits that dart the gaze, a bass swell that lengthens the
flames, and two sauron_surge pokes. Each frame is drawn as his crystal
shows it — the real cells as dots, nothing where there are no cells.

Writes (to --out, default docs/evidence/sauron/):
  sauron_sets.gif        the built effect on six of his sets
  sauron_hype1.gif       Hype 1 under each palette_sort choice
  sauron_moments.png     frozen moments: rest, a beat, full bass, a surge

Run: .venv/bin/python scripts/render_sauron.py [--out DIR] [--seconds S]
Nothing live is touched.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import check_sauron as C  # noqa: E402

ROWS, COLS, DT = C.ROWS, C.COLS, C.DT
CELL = 6                                     # the still's cell size
GIF_CELL = 4                                 # the GIFs' (keeps them small)
EVERY = 4                                    # 15 fps GIFs

SET_TILES = ["Mid - Fire", "Hype 1", "Mid - Ice", "Puerto Rico Red",
             "Mid - Bright Purple", "Mid - Blush"]
SORT_TILES = ["auto", "authored", "brightness", "warm", "angle"]


class Song:
    """120 BPM; ordinary hits 0.45, big hits 0.9 at 1.75/4.25/6.25 s (they
    dart the gaze), a bass swell 2.5-4.0 s, surges at 3.4 s and 5.8 s."""

    def __init__(self):
        self.t = 0.0
        self.next_beat = 0.25
        self.imp = 0.0
        self.big = [1.75, 4.25, 6.25]
        self.surges = [(3.4, 1.0), (5.8, 0.7)]

    def step(self, e):
        self.t += DT
        self.imp *= float(np.exp(-DT / 0.22))
        swell = 0.85 if 2.5 <= self.t < 4.0 else 0.0
        beat = False
        if self.t >= self.next_beat:
            self.next_beat += 0.5
            beat = True
            level = 0.45
            if any(abs(self.t - b) < 0.26 for b in self.big):
                level = 0.9
            self.imp = max(self.imp, level)
        e.impulse = max(self.imp, swell)
        if beat:
            e._beat_pending = True
        for s in list(self.surges):
            if self.t >= s[0]:
                e.update_config({"surge": float(s[1])})
                self.surges.remove(s)


def draw_crystal(pixels, label, cell=CELL):
    img = Image.new("RGB", (COLS * cell, ROWS * cell + 12), (6, 6, 10))
    d = ImageDraw.Draw(img)
    grid = pixels.reshape(ROWS, COLS, 3)
    for r in range(ROWS):
        for c in range(COLS):
            if not C.REAL2[r, c]:
                continue
            col = tuple(int(v) for v in grid[r, c])
            x0, y0 = c * cell, r * cell + 12
            if max(col) > 3:
                d.ellipse([x0, y0, x0 + cell - 1, y0 + cell - 1], fill=col)
            else:
                m = max(1, cell // 3)
                d.ellipse([x0 + m, y0 + m, x0 + cell - 1 - m,
                           y0 + cell - 1 - m], fill=(20, 20, 26))
    d.text((3, 0), label, fill=(225, 225, 225))
    return img


def grid(imgs, cols):
    w, h = imgs[0].size
    rows = (len(imgs) + cols - 1) // cols
    out = Image.new("RGB", (cols * w + (cols - 1) * 4,
                            rows * h + (rows - 1) * 4), (0, 0, 0))
    for i, im in enumerate(imgs):
        out.paste(im, ((i % cols) * (w + 4), (i // cols) * (h + 4)))
    return out


async def run_tile(config, seconds, seed=11):
    r = await C.Rig.make(config, seed=seed)
    song = Song()
    frames = []
    for i in range(int(seconds / DT)):
        song.step(r.effect)
        r.step(1)
        if i % EVERY == 0:
            frames.append((song.t, np.asarray(r.effect.matrix,
                                              dtype=np.uint8).copy()))
    await r.close()
    return frames


def save_gif(frames, path):
    frames = [f.quantize(colors=96, method=Image.Quantize.MEDIANCUT,
                         dither=Image.Dither.NONE)
              for f in frames]
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=int(round(1000 * DT * EVERY)), loop=0,
                   optimize=True)
    print(f"   wrote {path} ({len(frames)} frames, "
          f"{path.stat().st_size // 1024} KB)")


async def main_async(out: Path, seconds: float):
    C.headless.silence_audio()
    out.mkdir(parents=True, exist_ok=True)

    runs = [(name, await run_tile({"gradient": C.SETS[name]}, seconds))
            for name in SET_TILES]
    imgs = []
    for k in range(len(runs[0][1])):
        t = runs[0][1][k][0]
        imgs.append(grid([draw_crystal(f[k][1], f"{name}  {t:4.1f}s",
                                       GIF_CELL)
                          for name, f in runs], 3))
    save_gif(imgs, out / "sauron_sets.gif")

    moments = [(1.2, "rest"), (1.76, "a big hit (dart)"),
               (3.3, "full bass"), (3.45, "surge")]
    rows = []
    for name, f in runs[:3]:
        tiles = []
        for at, label in moments:
            best = min(f, key=lambda fr: abs(fr[0] - at))
            tiles.append(draw_crystal(best[1], f"{name} - {label}"))
        rows.append(grid(tiles, len(tiles)))
    grid(rows, 1).save(out / "sauron_moments.png")
    print(f"   wrote {out / 'sauron_moments.png'}")

    runs = [(how, await run_tile({"gradient": C.SETS["Hype 1"],
                                  "palette_sort": how}, seconds))
            for how in SORT_TILES]
    imgs = []
    for k in range(len(runs[0][1])):
        imgs.append(grid([draw_crystal(f[k][1], f"Hype 1 - {how}", GIF_CELL)
                          for how, f in runs], 3))
    save_gif(imgs, out / "sauron_hype1.gif")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(REPO / "docs" / "evidence" / "sauron"))
    ap.add_argument("--seconds", type=float, default=6.6)
    args = ap.parse_args()
    asyncio.run(main_async(Path(args.out), args.seconds))
    return 0


if __name__ == "__main__":
    status = 1
    try:
        status = main()
    except BaseException:                          # noqa: BLE001
        import traceback
        traceback.print_exc()
    finally:
        sys.stdout.flush()
        os._exit(status)
