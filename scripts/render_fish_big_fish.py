"""Offline evidence for THE BIG FISH flare (fx/effects/fish.py's BIG FISH
block — phase 1, the look only).

His word on the first build (PR 381): "the fish looks all wrong. it should
be the same as the other fish in the effect, just bigger, in the background,
and dimmer, with a dim but large ripple". So every view here is SIDE BY
SIDE: on the left the big fish as PR 381 drew it (the bespoke silhouette,
loaded out of git at PR381_REF as a second registered effect), on the right
the rework (an ordinary fish's own body, bigger, behind, dimmer, with its own
large dim wake) — the SAME seed, the SAME ordinary fish, the SAME moment.

Rendered on his crystal-mapper's REAL cells (storage/device_profiles/
crystal-mapper.json's mask, read-only, through fx.headless — the real
vendored render pipeline, audio silenced), with his music Fish scene's
Matrix entry (scripts/check_fish_wall.py::MUSIC_FISH, its bindings at their
fallbacks) wearing one colour set (GRADIENT below, centre #00c8ff):

  fish_big_fish_low.gif    one big fish fired at intensity 0.2 (120 deg,
                           the slow crossing)
  fish_big_fish_high.gif   one fired at intensity 0.8 (180 deg, fast)
  fish_big_fish_still.png  the middle of each crossing, PR 381 | rework,
                           low above high

and prints what each one measured (crossing time, the colour it wore, the
big fish's peak against the ordinary fish's peak, its wake's peak). Nothing
here touches the live room or live storage.

    .venv/bin/python scripts/render_fish_big_fish.py --out DIR
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

import check_fish_wall as W  # noqa: E402
from fx.effects import fish as FX  # noqa: E402

# the commit carrying PR 381's big fish exactly as it shipped (the rework's
# own merge-base) — pinned, never a moving branch name
PR381_REF = "34719fd452aa1a2758efa4648e039a054220f405"
DT = W.DT
EVERY = 3          # every 3rd frame -> a 20 fps GIF at real time
GRADIENT = ("linear-gradient(90deg, rgb(0, 64, 255) 0%, rgb(0, 200, 255) "
            "50%, rgb(128, 0, 255) 100%)")


async def crossing(effect_type, intensity, seconds, seed=3, **over):
    """Swim 3 s, fire one big fish, record `seconds`. Returns (frames,
    notes): frames are (label, pixels) pairs."""
    cfg = dict(W.MUSIC_FISH, gradient=GRADIENT, **over)
    r = await W.rig("bigfish", cfg, seed=seed, effect_type=effect_type)
    eff = r.effect
    frames = []
    r.step(180)
    eff.update_config({"big_fish": max(intensity, FX.BIG_FISH_POKE_FLOOR)})
    gone_at = None
    big_peak = 0.0
    wakes = []
    for i in range(1, int(seconds / DT) + 1):
        r.step(1)
        if i % EVERY == 0:
            frames.append((f"+{i * DT:4.1f}s",
                           np.asarray(eff.matrix, dtype=np.uint8)
                           .reshape(-1, 3).copy()))
        if gone_at is None and not eff._big:
            gone_at = i * DT
        bt = getattr(eff, "_big_trail", None)
        if bt is not None:
            big_peak = max(big_peak, float(bt.max())
                           * float(eff.big_fish_brightness))
        if eff.wake is not None:
            wakes.append(eff.wake.copy())
    fish = dict(eff.big_fish_last)
    centre = eff.get_gradient_color_vectorized1d(
        np.array([0.5], dtype=np.float32))[0]
    turned = FX.rotate_hue(centre, fish["turn"] * fish["degrees"])
    notes = {
        "intensity": intensity, "cross_s": fish["cross_s"],
        "gone_at_s": gone_at, "degrees": fish["degrees"],
        "turn": fish["turn"], "length": fish["length"],
        "ordinary_len": float(eff._body_len_px()),
        "centre": centre, "colour": turned,
        "big_peak": big_peak, "wakes": wakes,
    }
    await W.close(r)
    return frames, notes


def _hex(rgb):
    return "#" + "".join(f"{int(round(float(v))):02x}" for v in rgb)


def _side(images, gap=6):
    w = sum(im.width for im in images) + gap * (len(images) - 1)
    h = max(im.height for im in images)
    out = Image.new("RGB", (w, h), (0, 0, 0))
    x = 0
    for im in images:
        out.paste(im, (x, 0))
        x += im.width + gap
    return out


def _caption(img, text):
    out = Image.new("RGB", (img.width, img.height + 14), (0, 0, 0))
    out.paste(img, (0, 14))
    ImageDraw.Draw(out).text((4, 1), text, fill=(255, 220, 120))
    return out


def side_by_side(old, new, path, title):
    """PR 381 | rework, frame for frame."""
    real = W.crystal_real_mask().reshape(W.ROWS, W.COLS)
    lit = W.lit_area(W.crystal_real_mask())
    edges = W._outline(lit)
    k = min(len(old), len(new))
    imgs = []
    for j in range(k):
        a = W.draw_crystal(old[j][1], real, lit, edges,
                           f"PR 381 {old[j][0]}")
        b = W.draw_crystal(new[j][1], real, lit, edges,
                           f"rework {new[j][0]}")
        imgs.append(_caption(_side([a, b]), title))
    W.save_gif(imgs, path, EVERY)
    print(f"   wrote {path} ({len(imgs)} frames)")
    return imgs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    old_type = W.load_baseline_effect("fish_pr381_bigfish", ref=PR381_REF)
    if old_type is None:
        print("cannot load PR 381's fish.py from git — nothing to compare")
        return 1

    stills = []
    for label, intensity in (("low", 0.2), ("high", 0.8)):
        print(f"\n{label.upper()} — intensity {intensity}")
        seconds = FX.big_fish_cross_s(intensity, 7.0, 2.5) + 1.0
        old, n_old = asyncio.run(crossing(old_type, intensity, seconds))
        new, n = asyncio.run(crossing("fish", intensity, seconds))
        # the big fish's OWN wake: the same run with its ripple off, the
        # difference frame by frame (the ordinary fish swim identically)
        _f, n0 = asyncio.run(crossing("fish", intensity, seconds,
                                      big_fish_ripple=0.0))
        own = max(float((a - b).max()) for a, b in zip(n["wakes"],
                                                        n0["wakes"]))
        ordinary = max(float(b.max()) for b in n0["wakes"])
        area = max(int(np.count_nonzero((a - b).max(axis=2) > 1.0))
                   for a, b in zip(n["wakes"], n0["wakes"]))
        print(f"   crossing {n['cross_s']:.2f} s (gone at +{n['gone_at_s']:.2f}s,"
              f" PR 381 +{n_old['gone_at_s']:.2f}s), turned "
              f"{n['turn'] * n['degrees']:+.0f} deg -> {_hex(n['colour'])} "
              f"(centre {_hex(n['centre'])})")
        print(f"   body {n['length']:.1f} px long vs an ordinary fish "
              f"{n['ordinary_len']:.1f} px ({n['length'] / n['ordinary_len']:.1f}x)")
        print(f"   big fish peak level {n['big_peak']:.0f}/255 "
              f"(big_fish_brightness 0.6); its own wake peaks "
              f"{own:.0f}/255 over up to {area} px (the ordinary fish's "
              f"wakes peak {ordinary:.0f})")
        title = (f"big fish, intensity {intensity} "
                 f"({n['turn'] * n['degrees']:+.0f} deg, {n['cross_s']:.1f} s)")
        imgs = side_by_side(old, new, out / f"fish_big_fish_{label}.gif",
                            title)
        stills.append(imgs[len(imgs) // 2 - 3])
    W._stack(stills).save(out / "fish_big_fish_still.png")
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
