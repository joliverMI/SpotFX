"""Offline evidence for THE FIREWORKS MELDS (spectra/services/drop_switch.py's
THE FIREWORKS MELDS; drop-scene-variety plan phase 3, option C).

Renders, on his crystal-mapper's REAL cells (storage/device_profiles/
crystal-mapper.json's mask, through fx.headless — the real vendored render
pipeline, audio silenced, beats pulsed by hand), each switch as the trigger
clock lands it — a ONE-CALL HARD CUT (Virtual.set_effect(cut=True), fx/
VENDOR.md #63), the drop arm written straight after where the drop is the
moment:

  fireworks_meld_keepers.gif    Fish (his music Fish entry) above Orbits: a
                                charge, a 4 s lull TOLD `lull_keep = 3,
                                lull_next = "fireworks"`, then the cut to
                                Fireworks ON the drop with its drop arm —
                                each keeper explodes where it stands
  fireworks_meld_swallowed.gif  Fireworks' own charge / lull / drop, then
                                the cut to the Black Hole 1.0 s after the
                                drop (drop_switch_swallow_delay_s) — the
                                cloud joins the infall
  fireworks_meld_implode.gif    Fireworks' own drop, then the cut on "the
                                next big bass hit" (stood in by 1.5 s after
                                the drop) into Fish / Orbits / Squiggles,
                                one above the other — the falling fireworks
                                become their pieces; the fish's own flare
                                (its swim burst) fires with the cut, as the
                                incoming scene's flare does in the room

and prints the measured lit-cell counts around each cut. Nothing here
touches the live room or live storage (it reads the device profile,
read-only).

    .venv/bin/python scripts/render_fireworks_melds.py --out DIR
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
from fx.effects import lull_handoff as lh  # noqa: E402

DT = W.DT
EVERY = 3              # every 3rd frame -> a 20 fps GIF at real time
BEAT_EVERY = 26        # ~138 bpm, pulsed by hand (audio is silenced)
HIT_AFTER_S = 1.5      # the next big bass hit's stand-in
SWALLOW_AFTER_S = 1.0  # drop_switch_swallow_delay_s's default

FIREWORKS = {"spawn_rate": 0.0, "beat_burst": 1, "reverse": False}
ORBITS = {"gradient": "linear-gradient(90deg, #ff0040 0%, #ffb000 50%, "
                      "#00c0ff 100%)", "reverse": False}
SQUIGGLES = {"gradient": "linear-gradient(90deg, #00ff80 0%, #8000ff 100%)"}
BLACKHOLE = {"gradient": "linear-gradient(90deg, #ff00c0 0%, #4000ff 100%)",
             "reverse": False}


class Run:
    """One rig, its frames, and the lit-cell count every frame."""

    def __init__(self, r, title):
        self.r, self.title = r, title
        self.frames, self.lit, self.i = [], [], 0
        self.real = W.crystal_real_mask()

    def step(self, tag, n=1, beats=True):
        for _ in range(n):
            self.i += 1
            if beats and self.i % BEAT_EVERY == 0:
                self.r.effect._beat_pending = True
            self.r.step(1)
            px = np.asarray(self.r.effect.matrix, dtype=np.uint8).reshape(-1, 3)
            self.lit.append(int((px[self.real].max(axis=1) > 20).sum()))
            if self.i % EVERY == 0:
                self.frames.append((f"{self.title} - {tag}", px.copy()))

    def phase(self, phase, seconds, told=None, tag=None):
        eff = self.r.effect
        arm = {"phase": phase, "phase_progress": 0.0}
        arm.update(told or {})
        eff.update_config(arm)
        n = int(seconds / DT)
        ramp = max(1, int((0.9 if phase == "lull" else 1.0) * n))
        if phase == "drop":
            ramp = int(0.4 / DT)
        for i in range(1, n + 1):
            if i <= ramp:
                eff.update_config({"phase_progress": min(1.0, i / ramp)})
            self.step(f"{tag or phase} +{i * DT:3.1f}s")

    def cut(self, effect_type, config, seed=3):
        r = self.r
        new = r.host.effects.create(ledfx=r.host, type=effect_type,
                                    config=dict(config))
        r.virtual.set_effect(new, activate=False, cut=True)
        new._rng = np.random.default_rng(seed)
        r.effect = new
        return new


async def keepers(src, cfg, title):
    r = await W.rig("meldk", cfg, seed=5, effect_type=src)
    run = Run(r, title)
    run.step("swim", 150)
    run.phase("charge", 3.0)
    run.phase("lull", 4.0, told=lh.keys_for(3, "fireworks", 4.0))
    snap = r.effect._handoff_snapshot()
    kept = int(np.asarray(snap.get("keepers")).sum()) if snap.get("keepers") is not None else 0
    before = run.lit[-1]
    fw = run.cut("fireworks", FIREWORKS)
    fw.update_config({"phase": "drop", "phase_progress": 0.0})
    run.step("CUT on the drop -> Fireworks")
    on_cut = run.lit[-1]
    for i in range(1, int(3.0 / DT)):
        if i <= int(0.4 / DT):
            fw.update_config({"phase_progress": i / int(0.4 / DT)})
        run.step(f"Fireworks drop +{i * DT:3.1f}s")
    await W.close(r)
    return run, {"kept": kept, "lit_before": before, "lit_on_cut": on_cut,
                 "peak_after": max(run.lit[-int(3.0 / DT):])}


async def fireworks_then(effect_type, cfg, after_s, title, flare=False):
    r = await W.rig("meldo", FIREWORKS, seed=7, effect_type="fireworks")
    run = Run(r, title)
    run.step("Fireworks", 150)
    run.phase("charge", 2.5, tag="Fireworks charge")
    run.phase("lull", 2.5, tag="Fireworks lull")
    eff = r.effect
    eff.update_config({"phase": "drop", "phase_progress": 0.0})
    n = int(after_s / DT)
    for i in range(1, n + 1):
        if i <= int(0.4 / DT):
            eff.update_config({"phase_progress": i / int(0.4 / DT)})
        run.step(f"Fireworks' own drop +{i * DT:3.1f}s")
    before = run.lit[-1]
    new = run.cut(effect_type, cfg)
    if flare:
        new.update_config({"swim_burst": True})
    run.step(f"CUT -> {effect_type}")
    on_cut = run.lit[-1]
    for i in range(1, int(3.0 / DT)):
        if flare and i == int(0.3 / DT):
            new.update_config({"swim_burst": False})
        run.step(f"{effect_type} +{i * DT:3.1f}s after the cut")
    await W.close(r)
    return run, {"lit_before": before, "lit_on_cut": on_cut,
                 "adopted": getattr(new, "n", None) if effect_type != "squiggles"
                 else len(new.chains)}


def stack_gif(runs, path):
    real = W.crystal_real_mask().reshape(W.ROWS, W.COLS)
    lit = W.lit_area(W.crystal_real_mask())
    edges = W._outline(lit)
    k = min(len(run.frames) for run in runs)
    imgs = [W._stack([W.draw_crystal(run.frames[j][1], real, lit, edges,
                                     run.frames[j][0]) for run in runs])
            for j in range(k)]
    W.save_gif(imgs, path, EVERY)
    print(f"   wrote {path} ({len(imgs)} frames)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=True)

    print("\n1. INTO FIREWORKS — three keepers burst where they stand")
    runs = []
    for src, cfg, title in (("fish", W.MUSIC_FISH, "Fish -> Fireworks"),
                            ("orbits", ORBITS, "Orbits -> Fireworks")):
        run, n = asyncio.run(keepers(src, cfg, title))
        print(f"   {title}: {n['kept']} keepers flagged; lit cells "
              f"{n['lit_before']} -> {n['lit_on_cut']} on the cut frame, "
              f"peak {n['peak_after']}")
        runs.append(run)
    stack_gif(runs, out / "fireworks_meld_keepers.gif")

    print(f"\n2. SWALLOWED — the Black Hole {SWALLOW_AFTER_S:.1f}s after the drop")
    run, n = asyncio.run(fireworks_then("blackhole", BLACKHOLE, SWALLOW_AFTER_S,
                                        "Fireworks -> Black Hole"))
    print(f"   lit cells {n['lit_before']} -> {n['lit_on_cut']} on the cut "
          f"frame, {n['adopted']} pieces adopted into the infall")
    stack_gif([run], out / "fireworks_meld_swallowed.gif")

    print(f"\n3. IMPLODE ON THE NEXT HIT — {HIT_AFTER_S:.1f}s after the drop")
    runs = []
    for et, cfg, flare in (("fish", W.MUSIC_FISH, True),
                           ("orbits", ORBITS, False),
                           ("squiggles", SQUIGGLES, False)):
        run, n = asyncio.run(fireworks_then(et, cfg, HIT_AFTER_S,
                                            f"Fireworks -> {et}", flare=flare))
        print(f"   -> {et}: lit cells {n['lit_before']} -> {n['lit_on_cut']} "
              f"on the cut frame, {n['adopted']} pieces adopted")
        runs.append(run)
    stack_gif(runs, out / "fireworks_meld_implode.gif")
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
