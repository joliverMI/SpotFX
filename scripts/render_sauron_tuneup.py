#!/usr/bin/env python3
"""Before/after evidence for the first Sauron tune-up (the Admiral,
2026-10-11: rainbow sets too messy -> a radial mapping that follows the
eye's own shape; the slit's minimum width up a pixel; a thicker perimeter
ring that blends into the flames).

BEFORE is the effect as merged (PR #394), read out of git at BEFORE_REF and
registered beside the current module as a second effect (the fish proofs'
trick: an Effect registers under its module's last name segment). AFTER is
the working tree. Both run the SAME scripted song with the SAME seed, so the
eye looks at the same place on every frame of both columns, and the gaze
MOVES (big hits dart it; a charge narrows the slit near the end). Each frame
is drawn as his crystal shows it — the real cells as dots.

The config is his tuned Sauron scene's own values (storage/spectra/
scenes.json, scene 4874012c..., read 2026-10-11), with each signal binding
at its fallback: flames 0.35, flame_audio 2, drift_speed 0.5, snap_threshold
0.6, snap_hold 0.2, speed_audio 2.9, impulse_decay 0.06.

Writes (to --out, default docs/evidence/sauron-tuneup-1/):
  sauron_tuneup_compare.gif   rows = sets (Hype 1, Mid - Fire, Orbit - Red),
                              columns = before | after
  sauron_tuneup_moments.png   frozen moments, before | after, bigger cells

Run: .venv/bin/python scripts/render_sauron_tuneup.py [--out DIR]
Nothing live is touched.
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

import check_sauron as C  # noqa: E402
import render_sauron as R  # noqa: E402
from fx import headless  # noqa: E402

BEFORE_REF = "e1d92f7"          # the merged effect (PR #394)
BEFORE_NAME = "sauron_before"
DT = C.DT
EVERY = R.EVERY

HIS_SCENE = {"flames": 0.35, "flame_audio": 2.0, "drift_speed": 0.5,
             "snap_threshold": 0.6, "snap_hold": 0.2, "speed_audio": 2.9,
             "impulse_decay": 0.06, "x_offset": 0.5, "y_offset": 0.5}
SETS = ["Hype 1", "Mid - Fire", "Orbit - Red"]
CHARGE_AT = (5.2, 6.4)          # a charge builds here (the slit narrows)


def load_before() -> str | None:
    try:
        src = subprocess.run(
            ["git", "show", f"{BEFORE_REF}:fx/effects/sauron.py"],
            cwd=REPO, capture_output=True, text=True, check=True).stdout
    except Exception as exc:                       # noqa: BLE001
        print(f"  cannot read {BEFORE_REF}:fx/effects/sauron.py — {exc}")
        return None
    path = Path(tempfile.mkdtemp()) / f"{BEFORE_NAME}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(BEFORE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[BEFORE_NAME] = module
    spec.loader.exec_module(module)
    return BEFORE_NAME


async def run_tile(effect_type, config, seconds, seed=11):
    tag = f"tuneup-{effect_type}-{abs(hash(str(config))) % 10**8}"
    td = tempfile.mkdtemp()
    host = await headless.start_headless_host(
        str(Path(td) / tag), pixel_count=C.ROWS * C.COLS, rows=C.ROWS,
        device_id=tag, real_mask=C.REAL)
    virtual = host.virtuals.get(tag)
    cm = headless.fake_clock()
    clock = cm.__enter__()
    eff = headless.attach_effect(host, virtual, effect_type, dict(config))
    eff._rng = np.random.default_rng(seed)
    eff.noise.seed = int(seed) * 7919 + 17
    # the gaze's wander phase is drawn at construction, before the seed
    # above lands — pin it so both columns look at the same place
    eff._wander_seed = 1.3
    song = R.Song()
    frames = []
    for i in range(int(seconds / DT)):
        song.step(eff)
        t = song.t
        if CHARGE_AT[0] <= t < CHARGE_AT[1]:
            if eff._config.get("phase") != "charge":
                eff.update_config({"phase": "charge", "phase_progress": 0.0})
            eff.update_config({"phase_progress": min(
                1.0, (t - CHARGE_AT[0]) / (CHARGE_AT[1] - CHARGE_AT[0]))})
        clock.advance(DT)
        frame = virtual.assemble_frame()
        if frame is not None:
            virtual.flush(frame)
        if i % EVERY == 0:
            frames.append((t, np.asarray(eff.matrix, dtype=np.uint8).copy(),
                           tuple(round(v, 2) for v in eff.last_eye_px)))
    cm.__exit__(None, None, None)
    await host.shutdown()
    return frames


async def main_async(out: Path, seconds: float):
    headless.silence_audio()
    out.mkdir(parents=True, exist_ok=True)
    before = load_before()
    if before is None:
        return 1
    rows = []
    for name in SETS:
        cfg = dict(HIS_SCENE, gradient=C.SETS[name])
        rows.append((name, await run_tile(before, cfg, seconds),
                     await run_tile("sauron", cfg, seconds)))
    imgs = []
    for k in range(len(rows[0][1])):
        t = rows[0][1][k][0]
        tiles = []
        for name, b, a in rows:
            tiles.append(R.draw_crystal(b[k][1], f"BEFORE {name} {t:4.1f}s",
                                        R.GIF_CELL))
            tiles.append(R.draw_crystal(a[k][1], f"AFTER  {name}",
                                        R.GIF_CELL))
        imgs.append(R.grid(tiles, 2))
    R.save_gif(imgs, out / "sauron_tuneup_compare.gif")

    moments = [(1.2, "rest"), (1.78, "dart"), (3.3, "full bass"),
               (3.45, "surge"), (6.3, "charge (narrow slit)")]
    still = []
    for name, b, a in rows[:2]:
        for at, label in moments:
            fb = min(b, key=lambda fr: abs(fr[0] - at))
            fa = min(a, key=lambda fr: abs(fr[0] - at))
            still.append(R.grid([
                R.draw_crystal(fb[1], f"BEFORE {name} - {label}"),
                R.draw_crystal(fa[1], f"AFTER  {name} - {label}")], 2))
    R.grid(still, 2).save(out / "sauron_tuneup_moments.png")
    print(f"   wrote {out / 'sauron_tuneup_moments.png'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(REPO / "docs" / "evidence"
                                         / "sauron-tuneup-1"))
    ap.add_argument("--seconds", type=float, default=6.6)
    args = ap.parse_args()
    return asyncio.run(main_async(Path(args.out), args.seconds))


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
