"""Offline evidence for THE SEARCHING LULL and THE DROP THAT FOLLOWS THE
MUSIC (fx/effects/fish.py's 2026-10-08 LULL block; fish-lull plan phase 4).

Renders, on his crystal-mapper's REAL cells (storage/device_profiles/
crystal-mapper.json's mask, through fx.headless — the real vendored render
pipeline, audio silenced), with his music Fish scene's Matrix entry
(scripts/check_fish_wall.py::MUSIC_FISH, its bindings at their fallbacks):

  fish_lull_before_after.gif  the pre-change fish (pinned, out of git) above
                              the new one: the end of a charge, a 6 s lull
                              driven the way SpotFX drives it, the drop
  fish_drop_intensity.gif     the new drop at fire intensity 0.30 / 0.75
                              (= the old drop exactly) / 1.00, one above the
                              other
  fish_lull_keep3.gif         a lull told `lull_keep = 3, lull_next =
                              "fireworks"` — the three spaced keepers a
                              Fireworks drop will adopt

and prints the measured numbers each one shows. Nothing here touches the
live room or live storage (it reads the device profile, read-only).

    .venv/bin/python scripts/render_fish_lull_searcher.py --out DIR
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import check_fish_wall as W  # noqa: E402
from fx.effects import lull_handoff as lh  # noqa: E402

PRE_CHANGE_REF = "17f263223b8334024aef5b99c4090b35c3e448cf"
DT = W.DT
EVERY = 3          # every 3rd frame -> a 20 fps GIF at real time


def load_pre_change(name="fish_prelull_gif"):
    if name in sys.modules:
        return name
    src = subprocess.run(
        ["git", "show", f"{PRE_CHANGE_REF}:fx/effects/fish.py"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


async def arc(effect_type, lull_s, lull_told, drop_told, drop_s=5.5,
              seed=3, label=""):
    """Swim, charge, a lull (ramp 90% of the gap, then hang) and a drop, as
    SpotFX drives them. Returns (frames, notes) — frames every EVERY-th
    from the last 1.5 s of the charge on, notes the measured moments."""
    r = await W.rig("lullgif", W.MUSIC_FISH, seed=seed,
                    effect_type=effect_type)
    eff = r.effect
    frames, notes = [], {"label": label}

    def grab(i, tag):
        if i % EVERY == 0:
            frames.append((tag, np.asarray(eff.matrix, dtype=np.uint8)
                           .reshape(-1, 3).copy()))

    r.step(180)
    eff.update_config({"phase": "charge", "phase_progress": 0.0})
    n = int(4.0 / DT)
    for i in range(1, n + 1):
        eff.update_config({"phase_progress": i / n})
        if i % 12 == 0:
            eff._beat_pending = True
        r.step(1)
        if i > n - int(1.5 / DT):
            grab(i, "charge")
    arm = {"phase": "lull", "phase_progress": 0.0}
    arm.update(lull_told or {})
    eff.update_config(arm)
    ramp = int(0.9 * lull_s / DT)
    lit_dark_from = None
    alone_at = None
    for i in range(1, int(lull_s / DT) + 1):
        if i <= ramp:
            eff.update_config({"phase_progress": i / ramp})
        r.step(1)
        grab(i, f"lull +{i * DT:4.1f}s")
        lit = float(np.asarray(eff.matrix).max())
        if lit <= 8 and lit_dark_from is None:
            lit_dark_from = i * DT
        if lit > 8:
            lit_dark_from = None
        x, y = r.screen()
        m = eff._body_len_px()
        on = int(np.count_nonzero((x >= -m) & (x <= W.COLS - 1 + m)
                                  & (y >= -m) & (y <= W.ROWS - 1 + m)))
        keep = (lull_told or {}).get(lh.KEEP_KEY, 1)
        if alone_at is None and on <= keep:
            alone_at = i * DT
    notes["lull_s"] = lull_s
    notes["dark_from_s"] = lit_dark_from
    notes["down_to_keep_at_s"] = alone_at
    arm = {"phase": "drop", "phase_progress": 0.0}
    arm.update(drop_told or {})
    eff.update_config(arm)
    settled = None
    peak = 0
    for i in range(1, int(drop_s / DT) + 1):
        if i <= int(0.4 / DT):
            eff.update_config({"phase_progress": i / int(0.4 / DT)})
        r.step(1)
        peak = max(peak, eff.n)
        if settled is None and eff._phase == "none":
            settled = i * DT
        grab(i, f"drop +{i * DT:4.1f}s")
    notes["drop_settled_s"] = settled
    notes["drop_peak_fish"] = peak
    await W.close(r)
    return frames, notes


def stack_gif(runs, path):
    real = W.crystal_real_mask().reshape(W.ROWS, W.COLS)
    lit = W.lit_area(W.crystal_real_mask())
    edges = W._outline(lit)
    k = min(len(f) for _, f in runs)
    imgs = []
    for j in range(k):
        rows = [W.draw_crystal(f[j][1], real, lit, edges,
                               f"{label} - {f[j][0]}") for label, f in runs]
        imgs.append(W._stack(rows))
    W.save_gif(imgs, path, EVERY)
    print(f"   wrote {path} ({len(imgs)} frames)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    pre = load_pre_change()

    print("\n1. BEFORE / AFTER — a 6 s lull, drop at intensity 0.75")
    a, na = asyncio.run(arc(pre, 6.0, None, None, label="before"))
    b, nb = asyncio.run(arc("fish", 6.0, lh.keys_for(1, "", 6.0),
                            lh.drop_keys_for(0.75), label="after"))
    for n in (na, nb):
        print(f"   {n['label']:6s}: down to the kept count at "
              f"+{n['down_to_keep_at_s']}s  nothing lit from "
              f"{n['dark_from_s']}  drop settled at +{n['drop_settled_s']}s "
              f"peak {n['drop_peak_fish']} fish")
    stack_gif([("BEFORE (pre-change)", a), ("AFTER: one fish searches", b)],
              out / "fish_lull_before_after.gif")

    print("\n2. THE DROP FOLLOWS THE MUSIC — intensity 0.30 / 0.75 / 1.00")
    runs = []
    for i in (0.3, 0.75, 1.0):
        f, n = asyncio.run(arc("fish", 2.5, lh.keys_for(1, "", 2.5),
                               lh.drop_keys_for(i), drop_s=6.0,
                               label=f"I={i}"))
        print(f"   intensity {i:.2f}: scale {lh.drop_scale(i):.2f}  drop "
              f"settled at +{n['drop_settled_s']}s  peak "
              f"{n['drop_peak_fish']} fish")
        runs.append((f"drop at intensity {i:.2f}", f))
    stack_gif(runs, out / "fish_drop_intensity.gif")

    print("\n3. KEEP 3 FOR A FIREWORKS DROP — a 6 s lull")
    f, n = asyncio.run(arc("fish", 6.0, lh.keys_for(3, "fireworks", 6.0),
                           lh.drop_keys_for(0.75), label="keep 3"))
    print(f"   down to three at +{n['down_to_keep_at_s']}s  nothing lit "
          f"from {n['dark_from_s']}")
    stack_gif([("lull_keep 3, lull_next fireworks", f)],
              out / "fish_lull_keep3.gif")
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
