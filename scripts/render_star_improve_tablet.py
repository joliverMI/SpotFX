"""Tablet stills + short GIFs for Q13 (the star wave range) from the crystal
sprites render_star_improve_crystal.py wrote: each frame drawn as the real
976-cell hex layout.

Usage: .venv/bin/python scripts/render_star_improve_tablet.py RENDER_DIR OUT_DIR
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

R, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
CELLS = json.load(open(os.path.join(R, "cells.json")))
COLS, ROWS = 72, 37
FPS = 20


def sprite(name):
    im = Image.open(os.path.join(R, f"star_{name}.png")).convert("RGB")
    return np.asarray(im)                       # F x 976 x 3


def font(sz):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def draw_frame(row, W=480):
    """One 976-cell row -> a hex-dot picture (W wide)."""
    H = int(round(W * ROWS / COLS))
    im = Image.new("RGB", (W, H), (7, 6, 11))
    d = ImageDraw.Draw(im)
    cw, ch = W / COLS, H / ROWS
    rad = cw * 0.95
    for i, (c, r) in enumerate(CELLS):
        x, y = (c + 0.5) * cw, (r + 0.5) * ch
        px = tuple(int(v) for v in row[i])
        if sum(px) < 10:
            d.ellipse([x - rad * .35, y - rad * .35, x + rad * .35, y + rad * .35], fill=(26, 26, 36))
        else:
            d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=px)
    return im


def still(option, title, items, frame=24):
    """items: [(sprite name, label)] -> one PNG, three panels side by side."""
    W = 480
    panels = [draw_frame(sprite(n)[frame], W) for n, _ in items]
    H = panels[0].height
    pad, top = 16, 64
    out = Image.new("RGB", (pad + len(panels) * (W + pad), top + H + 56), (10, 6, 18))
    d = ImageDraw.Draw(out)
    d.text((pad, 14), title, fill=(232, 121, 249), font=font(28))
    for k, (im, (_n, label)) in enumerate(zip(panels, items)):
        x = pad + k * (W + pad)
        out.paste(im, (x, top))
        d.text((x, top + H + 12), label, fill=(236, 231, 247), font=font(22))
    p = os.path.join(OUT, f"star_range_{option}.png")
    out.save(p, optimize=True)
    return p


def gif(option, title, name, start_s=3.0, secs=6.0, W=420, fps=10):
    spr = sprite(name)
    step = FPS // fps
    frames = []
    f0 = int(start_s * FPS)
    for f in range(f0, min(spr.shape[0], f0 + int(secs * FPS)), step):
        im = draw_frame(spr[f], W)
        canvas = Image.new("RGB", (W, im.height + 44), (10, 6, 18))
        canvas.paste(im, (0, 44))
        d = ImageDraw.Draw(canvas)
        d.text((10, 8), title, fill=(232, 121, 249), font=font(22))
        frames.append(canvas.quantize(colors=128, method=Image.Quantize.MEDIANCUT))
    p = os.path.join(OUT, f"star_sway_{option}.gif")
    frames[0].save(p, save_all=True, append_images=frames[1:], loop=0,
                   duration=int(1000 / fps), optimize=True)
    return p


paths = []
paths.append(still("A", "Option A — star 0.30 ↔ 0.70 (as typed)",
                   [("shape_03", "low end · star 0.30"), ("shape_05", "middle · star 0.50"),
                    ("shape_07", "high end · star 0.70")]))
paths.append(still("B", "Option B — star −0.20 ↔ +0.20 (±0.2 about flat)",
                   [("shape_m02", "low end · star −0.20 (corner points)"),
                    ("shape_00", "middle · star 0 — FLAT"), ("shape_02", "high end · star +0.20")]))
paths.append(still("C", "Option C — star 0.00 ↔ 0.40 (flat ↔ star), recommended",
                   [("shape_00", "low end · star 0 — FLAT"), ("shape_02", "middle · star 0.20"),
                    ("shape_04", "high end · star 0.40")]))
paths.append(gif("A", "A · 0.30 ↔ 0.70", "star_his"))
paths.append(gif("B", "B · −0.20 ↔ +0.20", "star_flat_sym"))
paths.append(gif("C", "C · 0.00 ↔ 0.40", "star_flat_up"))
for p in paths:
    print(p, os.path.getsize(p) // 1024, "KB")
