"""The star x edges grid for the Admiral: star -0.7..+0.7 in 0.1 steps x edges
3,4,5,6 — one frozen still each on the real crystal layout (spin frozen,
same Melt frame and colours on every tile), ~240 px square, no labels.

Usage: .venv/bin/python scripts/render_star_improve_grid.py OUT_DIR
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))
sys.path.insert(0, os.path.join(HERE, ".."))

from star_harness import star_room, COLS, ROWS  # noqa: E402
from strip_phase_harness import run  # noqa: E402

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
PALETTE = "linear-gradient(90deg, #00ffff 0.00%,#0000ff 58.00%,#8b00ff 100.00%)"
FRAME = 24          # the same moment the tablet stills used (1.2 s in)
SIZE = 240


def crystal_real_mask():
    path = os.path.join(HERE, "..", "storage", "device_profiles", "crystal-mapper.json")
    mask, value = [], False
    for n in json.load(open(path))["mask_rle"]:
        mask.extend([value] * n)
        value = not value
    return np.array(mask, dtype=bool)


MASK = crystal_real_mask()
CELLS = [(int(k % COLS), int(k // COLS)) for k in np.flatnonzero(MASK)]


def draw(row):
    W = SIZE
    H = int(round(W * ROWS / COLS))
    im = Image.new("RGB", (SIZE, SIZE), (7, 6, 11))
    d = ImageDraw.Draw(im)
    cw, ch = W / COLS, H / ROWS
    rad = cw * 0.95
    y0 = (SIZE - H) / 2
    for i, (c, r) in enumerate(CELLS):
        x, y = (c + 0.5) * cw, y0 + (r + 0.5) * ch
        px = tuple(int(v) for v in row[i])
        if sum(px) < 10:
            d.ellipse([x - rad * .35, y - rad * .35, x + rad * .35, y + rad * .35], fill=(26, 26, 36))
        else:
            d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=px)
    return im


def tag(v):
    s = f"{abs(v) * 10:.0f}".rjust(2, "0")
    return "00" if abs(v) < 1e-9 else ("m" if v < 0 else "p") + s


async def main():
    measure = {"frame": FRAME, "palette": PALETTE, "tiles": {}}
    stars = [round(x / 10, 1) for x in range(-7, 8)]
    for edges in (3, 4, 5, 6):
        for sv in stars:
            np.random.seed(7)
            with tempfile.TemporaryDirectory() as tmp:
                async with star_room(tmp, radial={"star": sv, "edges": edges,
                                                   "spin": 0.0, "gradient": PALETTE},
                                     melt={"gradient": PALETTE, "speed": 0.2,
                                           "reactivity": 0.23, "blur": 0.0}) as room:
                    room.rev_s = 0.0          # spin frozen
                    room.step(FRAME + 1)
                    m = room.matrix().reshape(-1, 3)[MASK]
                    row = np.clip(m, 0, 255).astype(np.uint8)
                    name = f"e{edges}_s{tag(sv)}"
                    draw(row).save(os.path.join(OUT, name + ".png"), optimize=True)
                    mx = row.max(axis=1)
                    f = row.astype(float) / 255.0
                    lum = float((0.2126 * f[:, 0] + 0.7152 * f[:, 1] + 0.0722 * f[:, 2]).mean())
                    measure["tiles"][name] = {
                        "edges": edges, "star": sv,
                        "lit_cells": int((mx > 20).sum()),
                        "mean_brightness": round(float(mx.mean() / 255.0), 4),
                        "mean_luminance": round(lum, 4),
                    }
                    print(name, measure["tiles"][name]["lit_cells"],
                          measure["tiles"][name]["mean_brightness"])
    with open(os.path.join(OUT, "measure.json"), "w") as fh:
        json.dump(measure, fh, indent=1)


if __name__ == "__main__":
    run(main())
