#!/usr/bin/env python3
"""THE STRIP PHASE LAYER, measured (fx/effects/strip_phase.py; strip phase
plan phase 1, revision 3).

Runs each strip phase member through a full cycle on the real render
pipeline (tests/strip_phase_harness.py: fx.headless, the production
ResponseEngine on the FacadeExecutor, a fake clock, deterministic audio) —
1.5 s normal, a 4 s charge, a 7 s lull (dark point 4 s in, 3 s of dark), a
drop at intensity 0.85 — once with the layer's stage switched off and once
with it, and prints (for Melt and Power the "off" run IS the effect as it
was before the layer; the Black Hole strip's own choreography changed when
it joined, so its true before/after is scripts/check_blackhole_strip_phase.py):

  normal / charge peak / charge end / dark seconds in the lull / drop peak
  (mean perceived luminance), and the worst frame's count of pixels whiter
  than the set during the charge and the first 1.5 s of the drop;

then the output stage's own cost per frame (off-phase, charge, drop).

Exit status 1 if any member with the layer fails his rule: a charge that
does not build, a lull without ~3 s of black, a drop below its charge, or
ANY charge/drop pixel whiter than the set. Offline only; touches nothing.

    .venv/bin/python scripts/check_strip_phase.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from fx import device_model  # noqa: E402
from fx.effects import strip_phase as sp  # noqa: E402
from strip_phase_harness import (FPS, PALETTE, STRIP_PX, Room, lum,  # noqa: E402
                                 palette_of, run, whiter_than_set)

CHARGE = (90, 330)
LULL = (330, 750)
DROP = (750, 990)


async def cycle(effect_type: str, layer: bool):
    cfg = {"gradient": PALETTE, "brightness": 0.8}
    if effect_type == "power":
        cfg["sparks_color"] = "#000000"   # the compiler's accent rule
    with tempfile.TemporaryDirectory() as tmp:
        async with Room(tmp, {"s": (effect_type, STRIP_PX, 1, cfg)},
                        layer=layer) as r:
            r.step(CHARGE[0])
            await r.phase("charge", gap_ms=4000)
            r.step(CHARGE[1] - CHARGE[0])
            await r.phase("lull", gap_ms=7000)
            r.step(LULL[1] - LULL[0])
            await r.phase("drop", intensity=0.85)
            r.step(DROP[1] - DROP[0])
            return r.frames["s"], palette_of(r.effects["s"])


def measure(frames, pal):
    L = [lum(f) for f in frames]
    dark = sum(1 for f in frames[LULL[0]:LULL[1]] if f.max() == 0.0) / FPS
    window = list(range(*CHARGE)) + list(range(DROP[0], DROP[0] + 90))
    white = max(whiter_than_set(frames[i], pal) for i in window)
    return {
        "normal": float(np.mean(L[:CHARGE[0]])),
        "charge_peak": max(L[CHARGE[0]:CHARGE[1]]),
        "charge_end": L[CHARGE[1] - 1],
        "dark_s": dark,
        "drop_peak": max(L[DROP[0]:DROP[0] + 90]),
        "white": white,
    }


def stage_cost():
    """The output stage alone on a 560-px frame, p50/p95 in microseconds."""
    @sp.Effect.no_registration
    class Probe(sp.StripPhase):
        pass

    eff = object.__new__(Probe)
    eff._config = dict(sp._schema()({}))
    eff._config["gradient"] = PALETTE
    eff.brightness = 0.8
    eff._sp_clock = 1.0
    eff._sp_drop_t = 0.1
    eff._sp_guard_key = None
    eff._sp_guard_allow = None
    pal = np.stack([np.linspace(255, 32, STRIP_PX), np.linspace(32, 64, STRIP_PX),
                    np.linspace(0, 255, STRIP_PX)], axis=1)
    eff._strip_phase_palette = lambda n: pal
    rng = np.random.default_rng(1)
    px = rng.uniform(0, 255, (STRIP_PX, 3))
    frames = {
        "off-phase": None,
        "charge": sp.StripFrame(gain=1.5, fill=0.25, guard=1.0, activity=2.5),
        "drop": sp.StripFrame(gain=1.8, wave=1.06, guard=1.0, activity=3.5),
        "lull + punch": sp.StripFrame(fade=0.6, punch_fill=0.05, activity=0.5),
    }
    out = {}
    for name, frame in frames.items():
        eff._sp_frame = frame
        ts = []
        for _ in range(400):
            t0 = time.perf_counter()
            eff._strip_phase_stage(px)
            ts.append((time.perf_counter() - t0) * 1e6)
        out[name] = (float(np.percentile(ts, 50)), float(np.percentile(ts, 95)))
    return out


def main() -> int:
    ok = True
    print("STRIP PHASE LAYER — members:", sorted(device_model.STRIP_PHASE_EFFECTS))
    print(f"{'effect':8} {'':6} {'normal':>7} {'ch.peak':>8} {'ch.end':>7} "
          f"{'dark s':>7} {'drop pk':>8} {'white px':>9}")
    for et in sorted(device_model.STRIP_PHASE_EFFECTS):
        for layer in (False, True):
            m = measure(*run(cycle(et, layer)))
            label = "layer" if layer else "off"
            print(f"{et:8} {label:6} {m['normal']:7.3f} {m['charge_peak']:8.3f} "
                  f"{m['charge_end']:7.3f} {m['dark_s']:7.2f} "
                  f"{m['drop_peak']:8.3f} {m['white']:9d}")
            if layer:
                problems = []
                if m["charge_peak"] <= m["normal"] * 1.2:
                    problems.append("charge does not build")
                if abs(m["dark_s"] - 3.0) > 0.05:
                    problems.append(f"lull dark {m['dark_s']:.2f}s, want 3.0s")
                if m["drop_peak"] < m["charge_peak"]:
                    problems.append("drop below its charge")
                if m["white"]:
                    problems.append("white above the set on a charge/drop")
                for p in problems:
                    ok = False
                    print(f"  FAIL {et}: {p}")
    print("\noutput stage cost, 560 px (p50 / p95 us):")
    for name, (p50, p95) in stage_cost().items():
        print(f"  {name:13} {p50:8.1f} / {p95:8.1f}")
    print("\nOK" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
