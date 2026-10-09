"""Offline evidence for THE OTHER FISH AVOID IT — fx/effects/fish.py's
BIG_AVOID block (the big fish flare, phase 2).

His approval of the look, then the ask: "Big fish looks right: build step
2 - the other fish steer around the big fish while it crosses."

Rendered on his crystal-mapper's REAL cells (storage/device_profiles/
crystal-mapper.json's mask, read-only, through fx.headless — the real
vendored render pipeline, audio silenced) with his music Fish scene's Matrix
entry (scripts/check_fish_wall.py::MUSIC_FISH), the ordinary fish solid red
so their light is told apart from the big fish's. Every crossing is run
TWICE from the same seed: BEFORE (`big_fish_avoid` 0 — the step-1 crossing
exactly, proven bit for bit in tests/test_fish_big_fish_avoid.py) and AFTER
(the shipped default). What is measured, per frame of each crossing, on his
real cells only (a pixel off the lit cells shows nothing):

  overlap   pixels where an ordinary fish's freshly drawn body is lit at
            BIG_FISH_OCCLUDE_AT or more (the level that hides the big fish —
            i.e. it visibly sits ON it) AND the big fish's own body is at
            least OVERLAP_BIG of its full level (a quarter: its lit body, not
            its faint fringe)
  middles   ordinary fish whose MIDDLE is on such a big-fish pixel — the
            fish visibly swimming through it, not brushing its edge; split
            into the panel's middle columns (MID_COLS, where there is room
            above and below the big fish) and its two pointed ends (where
            the big fish fills the whole lit height and there is not)
  outside   how far (px) any ordinary fish's middle gets past the lit
            panel's own edge — the wall rule: never further than BEFORE

    .venv/bin/python scripts/check_fish_big_fish_avoid.py
    .venv/bin/python scripts/check_fish_big_fish_avoid.py --gifs DIR

`--gifs` writes, side by side (before | after, the same seed, the same
moment): fish_big_fish_avoid_low.gif (intensity 0.2, the slow crossing),
fish_big_fish_avoid_high.gif (0.8) and fish_big_fish_avoid_still.png. Nothing
here touches the live room or live storage.
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
RED = "#ff0000"
OVERLAP_BIG = 0.25           # share of the big fish's full level = its body
MID_COLS = (20, 52)          # the panel's middle columns [lo, hi)
SEEDS = (0, 1, 2, 3, 4, 5)
EVERY = 3                    # GIF: every 3rd frame -> 20 fps at real time
GIF_GRADIENT = ("linear-gradient(90deg, rgb(255, 40, 0) 0%, rgb(255, 120, 0) "
                "50%, rgb(255, 0, 80) 100%)")

_FISH_CLS = FX.Fish2d


class _Bodies:
    """Captures the ordinary fish's freshly drawn body layer each frame:
    the first `_clip_body_layer` call of a draw is exactly that layer (before
    it is maxed into the persistent smear)."""

    def __init__(self):
        self.layer = None
        self._orig = None

    def __enter__(self):
        self._orig = _FISH_CLS._clip_body_layer
        spy = self

        def wrapped(eff, frame):
            out = spy._orig(eff, frame)
            if spy.layer is None:
                spy.layer = np.asarray(out).max(axis=2).copy()
            return out

        _FISH_CLS._clip_body_layer = wrapped
        return self

    def __exit__(self, *exc):
        _FISH_CLS._clip_body_layer = self._orig


def big_body(eff):
    """Every big fish's body, as drawn, at FULL level (0..255 white) — the
    renderer's own `_big_fish_bodies`, nothing re-derived."""
    frame = np.zeros((int(eff.r_height), int(eff.r_width), 3),
                     dtype=np.float32)
    for fish in eff._big:
        scale, flap_amp, _f, _s = eff._big_fish_motion(fish, 1.0)
        eff._big_fish_bodies(frame, fish, scale, 1.0, flap_amp,
                             np.array([255.0, 255.0, 255.0]), 1.0)
    return frame[..., 0]


async def crossing(intensity, seed, *, frames_out=False, gradient=RED,
                   **over):
    """Swim 3 s, fire one big fish, measure every frame until it is gone.
    Returns a dict of the measures (and the rendered frames with
    `frames_out`)."""
    cfg = dict(W.MUSIC_FISH, gradient=gradient, **over)
    if gradient == RED:
        # measuring: no wake, so every red pixel is an ordinary fish's body
        cfg["ripple_amount"] = 0.0
    real = W.crystal_real_mask().reshape(W.ROWS, W.COLS)
    r = await W.rig("avoid", cfg, seed=seed)
    eff = r.effect
    out = {"frames": 0, "overlap": [], "middles_mid": 0, "middles_end": 0,
           "outside": 0.0, "turn_over": 0.0, "shots": []}
    try:
        r.step(180)
        eff.update_config({"big_fish": max(intensity,
                                           FX.BIG_FISH_POKE_FLOOR)})
        prev = None
        with _Bodies() as bodies:
            for i in range(int(12.0 / DT)):
                bodies.layer = None
                r.step(1)
                if not eff._big:
                    if i > 5:
                        break
                    continue
                out["frames"] += 1
                big = big_body(eff) >= OVERLAP_BIG * 255.0
                lit = bodies.layer >= FX.BIG_FISH_OCCLUDE_AT
                out["overlap"].append(int(np.count_nonzero(big & lit & real)))
                n = eff.n
                sel = np.flatnonzero(eff.p_mode[:n] < 2)
                x, y = r.screen(sel)
                xi = np.round(x).astype(int)
                yi = np.round(y).astype(int)
                on = (xi >= 0) & (xi < W.COLS) & (yi >= 0) & (yi < W.ROWS)
                for a, b in zip(xi[on], yi[on]):
                    if real[b, a] and big[b, a]:
                        if MID_COLS[0] <= a < MID_COLS[1]:
                            out["middles_mid"] += 1
                        else:
                            out["middles_end"] += 1
                if sel.size:
                    d, _nx, _ny = FX._sample_field(eff._wall, x, y)
                    out["outside"] = max(out["outside"], float(-d.min()))
                # the turn-circle guarantee: no heading changed faster than
                # the fish's own speed over its turn radius allows
                state = (n, eff.p_mode[:n].copy(), eff.p_hd[:n].copy())
                if prev is not None and prev[0] == n and np.array_equal(
                        prev[1], state[1]):
                    turned = np.abs(FX._wrap_pi(state[2] - prev[2]))
                    allowed = eff.p_spd[:n] / eff.turn_radius_px * DT
                    swim = state[1] < 2
                    if swim.any():
                        out["turn_over"] = max(out["turn_over"], float(
                            (turned[swim] - allowed[swim]).max()))
                prev = state
                if frames_out and i % EVERY == 0:
                    out["shots"].append(
                        (f"+{i * DT:4.1f}s",
                         np.asarray(eff.matrix, dtype=np.uint8)
                         .reshape(-1, 3).copy()))
    finally:
        await W.close(r)
    return out


def summarize(intensity, avoid, seeds=SEEDS, **over):
    runs = [asyncio.run(crossing(intensity, s, big_fish_avoid=avoid, **over))
            for s in seeds]
    ov = [v for run in runs for v in run["overlap"]]
    return {
        "frames": sum(run["frames"] for run in runs),
        "overlap_frames": sum(1 for v in ov if v > 0),
        "overlap_px": sum(ov),
        "overlap_max": max(ov) if ov else 0,
        "middles_mid": sum(run["middles_mid"] for run in runs),
        "middles_end": sum(run["middles_end"] for run in runs),
        "outside": max(run["outside"] for run in runs),
        "turn_over": max(run["turn_over"] for run in runs),
    }


def _row(label, m):
    print(f"   {label:7s} overlap {m['overlap_frames']:4d}/{m['frames']} "
          f"frames, {m['overlap_px']:5d} px total, max {m['overlap_max']:2d} "
          f"px | middles in it: {m['middles_mid']:3d} mid-panel, "
          f"{m['middles_end']:3d} at the points | furthest past the edge "
          f"{m['outside']:.1f} px | turn over its circle "
          f"{max(m['turn_over'], 0.0):.4f} rad")


def section_measure(seeds=SEEDS):
    print("THE OTHER FISH AVOID IT — his music Fish, his crystal, "
          f"seeds {list(seeds)}")
    for label, intensity in (("low", 0.2), ("high", 0.8)):
        print(f"\n {label.upper()} — intensity {intensity} "
              f"(crossing {FX.big_fish_cross_s(intensity, 7.0, 2.5):.1f} s)")
        before = summarize(intensity, 0.0, seeds)
        after = summarize(intensity, 1.0, seeds)
        _row("before", before)
        _row("after", after)


def _side(images, gap=6):
    from PIL import Image
    w = sum(im.width for im in images) + gap * (len(images) - 1)
    h = max(im.height for im in images)
    out = Image.new("RGB", (w, h), (0, 0, 0))
    x = 0
    for im in images:
        out.paste(im, (x, 0))
        x += im.width + gap
    return out


def _caption(img, text):
    from PIL import Image, ImageDraw
    out = Image.new("RGB", (img.width, img.height + 14), (0, 0, 0))
    out.paste(img, (0, 14))
    ImageDraw.Draw(out).text((4, 1), text, fill=(255, 220, 120))
    return out


def section_gifs(out_dir, seed=1):
    out_dir.mkdir(parents=True, exist_ok=True)
    real = W.crystal_real_mask().reshape(W.ROWS, W.COLS)
    lit = W.lit_area(W.crystal_real_mask())
    edges = W._outline(lit)
    stills = []
    for label, intensity in (("low", 0.2), ("high", 0.8)):
        runs = {}
        for name, avoid in (("before", 0.0), ("after", 1.0)):
            runs[name] = asyncio.run(crossing(
                intensity, seed, frames_out=True, gradient=GIF_GRADIENT,
                big_fish_avoid=avoid))
        a, b = runs["before"]["shots"], runs["after"]["shots"]
        k = min(len(a), len(b))
        imgs = []
        for j in range(k):
            left = W.draw_crystal(a[j][1], real, lit, edges,
                                  f"before {a[j][0]}")
            right = W.draw_crystal(b[j][1], real, lit, edges,
                                   f"avoiding {b[j][0]}")
            imgs.append(_caption(_side([left, right]),
                                 f"big fish, intensity {intensity}"))
        path = out_dir / f"fish_big_fish_avoid_{label}.gif"
        W.save_gif(imgs, path, EVERY)
        print(f"   wrote {path} ({len(imgs)} frames)")
        stills.append(imgs[k // 2])
    W._stack(stills).save(out_dir / "fish_big_fish_avoid_still.png")
    print(f"   wrote {out_dir / 'fish_big_fish_avoid_still.png'}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gifs", type=Path)
    args = parser.parse_args()
    if args.gifs:
        section_gifs(args.gifs)
    else:
        section_measure()
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
