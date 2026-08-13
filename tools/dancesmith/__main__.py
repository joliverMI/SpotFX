"""dancesmith CLI — preview and validate Dancer-effect dances headless.

    python3 -m tools.dancesmith validate
    python3 -m tools.dancesmith list
    python3 -m tools.dancesmith preview --dance tai_chi [--move cloud_hands]
        [--png build/dances/tai_chi.png] [--ascii] [--partner]

Rendering mimics the live effect (bone sampling + soft splat through the
crystal-mapper mask) so what you see here is what the matrix shows.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from tools.dancesmith import import_moves
from tools.gifsmith.device_profiles import load_profile, profile_mask

dm = import_moves()

STROKE_R = 1.5   # matches the effect's blob_size 2.0 * 0.75
LIT = 32


def _mask_grid(virtual_id: str) -> np.ndarray:
    profile = load_profile(virtual_id)
    return np.array(profile_mask(profile), dtype=bool)


def render_pose(vec, mask, tilt=0.0, mirror=False, fig_scale=0.82):
    """One pose → (rows, cols) float frame, effect-style sampling."""
    rows, cols = mask.shape
    if mirror:
        vec = dm.mirror_vec(vec)
    h = rows * fig_scale
    ground = rows - 2.0
    hip_y = ground - dm.LEG_REACH * h
    cx = cols / 2.0
    joints = dm.joint_xy(vec, h)
    if abs(tilt) > 0.01:
        r = math.radians(tilt if not mirror else -tilt)
        c, s = math.cos(r), math.sin(r)
        px, py = 0.0, dm.LEG_REACH * h
        x = joints[:, 0] - px
        y = joints[:, 1] - py
        joints[:, 0] = px + x * c - y * s
        joints[:, 1] = py + x * s + y * c
    joints[:, 0] += cx
    joints[:, 1] += hip_y
    frame = np.zeros((rows, cols), np.float32)
    span = np.arange(-3, 4)
    kdx, kdy = np.meshgrid(span, span)
    kd = np.sqrt(kdx**2 + kdy**2).ravel()
    keep = kd <= STROKE_R
    kdx, kdy = kdx.ravel()[keep], kdy.ravel()[keep]
    kw = 1.0 - kd[keep] / (STROKE_R + 0.5)

    def splat(xs, ys, radius_keep=None):
        xi = np.round(np.atleast_1d(xs)).astype(int)
        yi = np.round(np.atleast_1d(ys)).astype(int)
        for x, y in zip(xi, yi):
            for ddx, ddy, w in zip(kdx, kdy, kw):
                px_, py_ = x + ddx, y + ddy
                if 0 <= px_ < cols and 0 <= py_ < rows:
                    frame[py_, px_] = max(frame[py_, px_], w)

    for a, b in dm.BONES:
        ax, ay = joints[a]
        bx, by = joints[b]
        n = max(int(math.hypot(bx - ax, by - ay) / 0.6), 1) + 1
        t = np.linspace(0, 1, n)
        splat(ax + (bx - ax) * t, ay + (by - ay) * t)
    splat(joints[dm.J_HEAD, 0], joints[dm.J_HEAD, 1])  # head
    return frame


def ascii_frame(frame, mask):
    rows, cols = mask.shape
    lines = []
    for r in range(rows):
        line = []
        for c in range(cols):
            if not mask[r, c]:
                line.append(" ")
            elif frame[r, c] * 255 >= LIT:
                line.append("#")
            else:
                line.append(".")
        lines.append("".join(line))
    return "\n".join(lines)


def coverage(frame, mask):
    return int(np.count_nonzero((frame * 255 >= LIT) & mask))


def move_frames(dance, move, partner=False, tweens=1):
    """Key poses (+ optional midpoints) for one move; partner=True renders
    the second dancer's poses instead."""
    keys = move["pkeys"] if partner else move["keys"]
    if partner and dance["partner"] == "sync":
        keys = move["keys"]
    out = []
    k = len(keys)
    for i in range(k):
        out.append((keys[i], float(move["tilt"][i]), f"k{i}"))
        if tweens:
            j = (i + 1) % k
            mid = (keys[i] + keys[j]) / 2.0
            mid_t = (float(move["tilt"][i]) + float(move["tilt"][j])) / 2.0
            out.append((mid, mid_t, f"k{i}.5"))
    return out


def contact_sheet(frames_by_move, mask, path, scale=6):
    rows, cols = mask.shape
    n_rows = len(frames_by_move)
    n_cols = max(len(f) for _, f in frames_by_move)
    pad = 14
    img = Image.new(
        "RGB",
        (n_cols * (cols * scale // 2 + pad) + pad,
         n_rows * (rows * scale // 2 + pad + 12) + pad),
        (12, 12, 16),
    )
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    y = pad
    for name, frames in frames_by_move:
        x = pad
        draw.text((x, y - 11), name, fill=(200, 200, 210))
        for frame, label in frames:
            for r in range(rows):
                for c in range(cols):
                    if not mask[r, c]:
                        continue
                    v = frame[r, c]
                    px = x + c * scale // 2
                    py = y + r * scale // 2
                    color = (
                        (int(80 + 175 * v), int(40 + 200 * v), 60)
                        if v * 255 >= LIT
                        else (28, 28, 34)
                    )
                    draw.ellipse(
                        [px, py, px + max(scale // 2 - 1, 1),
                         py + max(scale // 2 - 1, 1)],
                        fill=color,
                    )
            x += cols * scale // 2 + pad
        y += rows * scale // 2 + pad + 12
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def main():
    ap = argparse.ArgumentParser(prog="dancesmith")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    sub.add_parser("list")
    pv = sub.add_parser("preview")
    pv.add_argument("--dance", required=True)
    pv.add_argument("--move")
    pv.add_argument("--png")
    pv.add_argument("--ascii", action="store_true")
    pv.add_argument("--partner", action="store_true")
    pv.add_argument("--virtual", default="crystal-mapper")
    args = ap.parse_args()

    if args.cmd == "validate":
        probs = dm.validate()
        for p in probs:
            print("PROBLEM:", p)
        print("OK" if not probs else f"{len(probs)} problem(s)")
        sys.exit(1 if probs else 0)

    dances = dm.compile_dances()
    if args.cmd == "list":
        for name, d in dances.items():
            moves = ", ".join(m["name"] for m in d["moves"])
            print(f"{name:10s} [{d['partner']:8s} x{d['tempo']} "
                  f"{d['energy']:4s}] {moves}")
        return

    dance = dances[args.dance]
    mask = _mask_grid(args.virtual)
    moves = dance["moves"]
    if args.move:
        moves = [m for m in moves if m["name"] == args.move]
        if not moves:
            sys.exit(f"no move '{args.move}' in {args.dance}")
    rows_out = []
    low_cov = []
    for m in moves:
        frames = []
        for vec, tilt, label in move_frames(dance, m, partner=args.partner):
            fr = render_pose(vec, mask, tilt=tilt)
            cov = coverage(fr, mask)
            if cov < 20:
                low_cov.append(f"{m['name']}/{label}: {cov} lit cells")
            frames.append((fr, label))
            if args.ascii:
                print(f"--- {m['name']} {label} (lit {cov})")
                print(ascii_frame(fr, mask))
        rows_out.append((m["name"], frames))
    if args.png:
        out = contact_sheet(rows_out, mask, Path(args.png))
        print("wrote", out)
    for warning in low_cov:
        print("LOW COVERAGE:", warning)


if __name__ == "__main__":
    main()
