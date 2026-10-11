#!/usr/bin/env python3
"""THE BLACK HOLE STRIP ON THE STRIP PHASE LAYER, measured (fx/effects/
blackhole1d.py; strip phase plan phase 2, revision 3).

The Admiral, 2026-10-11: charge/lull/drop on the strips should "increase in
brightness and activity during charge, dim and relax into black for most
lulls, and big explosion of brightness and activity on the [drop]" — and,
binding, "i don't want to raise the white in the charge, or on the drop".
His call 1: the Black Hole strip's charge is a TINTED PALETTE GLOW (no white
flood). His call 3: every lull is black at the room's dark point.

Runs his real Black Hole V2 strip entry (live scenes.json, read once and
copied in below) through one cycle on the real render pipeline (fx.headless,
a fake clock, deterministic audio fed to the effect's own audio callback,
numpy seeded) — 2.5 s normal, a 4 s charge, a 7 s lull (told the room's
dark point: 4 s in, 3 s of dark), a drop at intensity 0.85 — written the way
spectra scene_response._drive_phase writes it (the arm, then the progress
ramp over 90% of the gap). Twice: the module as it was BEFORE this phase
(pinned at BEFORE_REF, loaded beside the current one as a second registered
effect) and as it is now. Prints, per run:

  brightness (mean perceived luminance): normal / charge peak / charge end /
    dark seconds in the lull / the drop's first frame / drop peak;
  white: the worst frame's count of pixels whiter than the set during the
    charge, and during the drop's first 1.5 s (measured with code that
    shares nothing with the layer — tests/strip_phase_harness.py);
  live blobs: normal / charge peak / charge end / drop peak.

Asserts the new run follows his rule AND that the old run shows each defect
this phase retires (so every measure here can fail): a white flood on the
charge; a drop that starts from black; a lull dark spell that does not match
the room cap. Offline only; touches no storage, no network, no live process.

    .venv/bin/python scripts/check_blackhole_strip_phase.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from fx import headless  # noqa: E402
from fx.effects import blackhole1d as bh1  # noqa: E402
from fx.effects import lull_dark, strip_phase as sp  # noqa: E402
from strip_phase_harness import (PALETTE, _AudioFrame, lum,  # noqa: E402
                                 palette_of, whiter_than_set)

# The last commit before the Black Hole strip joined the layer (strip phase
# plan phase 1 merged; blackhole1d still drew its own phases).
BEFORE_REF = "7ba9934e72cd06c00775ffd7c5d6fda945e31ec5"

FPS = 60
DT = 1.0 / FPS
PX = 560
NORMAL_S, CHARGE_S, LULL_S, DROP_S = 2.5, 4.0, 7.0, 4.0
MAX_DARK_S = 3.0
DROP_INTENSITY = 0.85
DROP_RAMP_S = 0.4
WHITE_DROP_S = 1.5

# his live Black Hole V2 strip entry (storage/spectra/scenes.json, read-only)
HIS_STRIP = {
    "swirl": 3.1, "radius_scale": 1, "blob_size": 0.5, "reverse": True,
    "x_offset": 0.5, "base_speed": 1, "accel": 5, "spawn_rate": 1,
    "beat_burst": 2, "spawn_audio": 1, "speed_audio": 2.3,
    "impulse_decay": 0.06, "max_blobs": 50, "edge_speed": 1,
    "approach_width": 0.16,
}


def load_before(name: str = "blackhole1d_before"):
    """BEFORE_REF's blackhole1d.py as a SECOND registered effect (an Effect
    registers under its module's last name segment). None — a stated skip,
    never a silent pass — when git cannot produce the ref."""
    try:
        src = subprocess.run(
            ["git", "show", f"{BEFORE_REF}:fx/effects/blackhole1d.py"],
            cwd=REPO, capture_output=True, text=True, check=True).stdout
    except Exception as exc:                                  # noqa: BLE001
        print(f"  (skipped the before run: cannot read {BEFORE_REF} — {exc})")
        return None
    if name in sys.modules:
        return name
    path = Path(tempfile.mkdtemp()) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return name


async def cycle(tmp: str, effect_type: str, *, flare_at_s=None):
    """One normal/charge/lull/drop cycle. Returns frames, the palette and
    the live blob count per frame."""
    np.random.seed(7)
    host = await headless.start_headless_host(
        str(Path(tmp) / effect_type), device_id="strip", pixel_count=PX)
    virtual = host.virtuals.get("strip")
    frames, blobs = [], []
    i = [0]
    with headless.fake_clock() as clock:
        eff = headless.attach_effect(host, virtual, effect_type,
                                     dict(HIS_STRIP, gradient=PALETTE))
        eff._rng = np.random.default_rng(11)

        def step(n=1):
            for _ in range(n):
                clock.advance(DT)
                i[0] += 1
                with eff.lock:
                    eff.audio_data_updated(_AudioFrame(i[0]))
                f = virtual.assemble_frame()
                if f is not None:
                    virtual.flush(f)
                    frames.append(np.array(f, dtype=np.float64, copy=True))
                    blobs.append(int(eff.n))

        def ramp(seconds, ramp_s):
            n = int(round(seconds * FPS))
            n_ramp = max(1, int(round(ramp_s * FPS)))
            for k in range(1, n + 1):
                if k <= n_ramp:
                    eff.update_config({"phase_progress": k / n_ramp})
                step()

        step(int(NORMAL_S * FPS))
        eff.update_config({"phase": "charge", "phase_progress": 0.0,
                           sp.STRENGTH_KEY: 1.0})
        ramp(CHARGE_S, 0.9 * CHARGE_S)
        eff.update_config({"phase": "lull", "phase_progress": 0.0,
                           sp.STRENGTH_KEY: 1.0,
                           **lull_dark.keys_for(LULL_S, 0.9 * LULL_S,
                                                MAX_DARK_S)})
        ramp(LULL_S, 0.9 * LULL_S)
        eff.update_config({"phase": "drop", "phase_progress": 0.0,
                           sp.STRENGTH_KEY: 1.0,
                           "drop_intensity": DROP_INTENSITY})
        ramp(DROP_S, DROP_RAMP_S)
        pal = palette_of(eff, PX)
    await host.shutdown()
    return frames, pal, blobs


def windows():
    c0 = int(NORMAL_S * FPS)
    l0 = c0 + int(CHARGE_S * FPS)
    d0 = l0 + int(LULL_S * FPS)
    return c0, l0, d0, d0 + int(DROP_S * FPS)


def measure(frames, pal, blobs):
    c0, l0, d0, end = windows()
    L = [lum(f) for f in frames]
    lull = frames[l0:d0]
    dark = [k for k, f in enumerate(lull) if f.max() == 0.0]
    wd = int(WHITE_DROP_S * FPS)
    return {
        "normal": float(np.mean(L[:c0])),
        "charge_peak": max(L[c0:l0]),
        "charge_end": L[l0 - 1],
        "dark_s": len(dark) / FPS,
        "dark_from": dark[0] if dark else None,
        "dark_solid": bool(dark) and dark == list(range(dark[0], len(lull))),
        "drop_first": L[d0],
        "drop_peak": max(L[d0:d0 + wd]),
        "drop_peak_at": int(np.argmax(L[d0:d0 + wd])),
        "white_charge": max(whiter_than_set(frames[k], pal)
                            for k in range(c0, l0, 4)),
        "white_drop": max(whiter_than_set(frames[k], pal)
                          for k in range(d0, d0 + wd, 2)),
        "n_normal": int(np.mean(blobs[:c0])),
        "n_charge_peak": max(blobs[c0:l0]),
        "n_charge_end": blobs[l0 - 1],
        "n_drop_peak": max(blobs[d0:d0 + wd]),
    }


_failures: list[str] = []


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _failures.append(msg)


def main() -> int:
    runs, frames = {}, {}
    with tempfile.TemporaryDirectory() as tmp:
        before = load_before()
        if before:
            out = asyncio.run(cycle(tmp, before))
            frames["before"] = out[0]
            runs["before"] = measure(*out)
        out = asyncio.run(cycle(tmp, "blackhole1d"))
        frames["now"] = out[0]
        runs["now"] = measure(*out)

    cols = ("normal", "charge_peak", "charge_end", "dark_s", "drop_first",
            "drop_peak")
    print("BLACK HOLE STRIP — brightness (mean perceived luminance)")
    print(f"{'':7}" + "".join(f"{c:>12}" for c in cols))
    for name, m in runs.items():
        print(f"{name:7}" + "".join(f"{m[c]:12.3f}" for c in cols))
    print("\nwhiter than the set (worst frame, pixels) / live blobs")
    cols2 = ("white_charge", "white_drop", "n_normal", "n_charge_peak",
             "n_charge_end", "n_drop_peak")
    print(f"{'':7}" + "".join(f"{c:>14}" for c in cols2))
    for name, m in runs.items():
        print(f"{name:7}" + "".join(f"{m[c]:14d}" for c in cols2))

    now = runs["now"]
    print("\nnow — his rule")
    check(now["charge_peak"] > 2.0 * now["normal"],
          f"the charge builds ({now['normal']:.3f} -> peak "
          f"{now['charge_peak']:.3f}) in the set's colours")
    check(now["white_charge"] == 0,
          "no charge frame is whiter than the set (the white flood is gone)")
    want_from = int(round((LULL_S - MAX_DARK_S) * FPS)) - 1
    check(now["dark_solid"] and now["dark_from"] == want_from,
          f"the lull is black from the room's dark point ({MAX_DARK_S:.0f} s "
          f"before the drop, frame {now['dark_from']} of the lull) to the drop, "
          "no phosphor dot")
    check(abs(now["dark_s"] - MAX_DARK_S) <= 2.0 / FPS,
          f"…for the room's cap ({now['dark_s']:.2f} s)")
    check(now["drop_first"] > 0.2 * now["drop_peak"],
          f"the drop is lit on its very first frame ({now['drop_first']:.3f}, "
          f"peak {now['drop_peak']:.3f}) — no fade up from black")
    front = int(np.ceil(sp.DROP_FRONT_S * FPS))
    check(now["drop_peak_at"] <= front,
          f"…and peaks as the shockwave reaches the strip's ends (frame "
          f"{now['drop_peak_at']}, the front lands at frame {front})")
    check(now["drop_peak"] > now["charge_peak"],
          f"the drop out-shines the charge ({now['drop_peak']:.3f} > "
          f"{now['charge_peak']:.3f})")
    check(now["white_drop"] == 0,
          "no drop frame is whiter than the set")
    check(now["n_charge_peak"] > 2 * now["n_normal"],
          f"more going on: {now['n_normal']} blobs normally, "
          f"{now['n_charge_peak']} at the charge's peak")

    if "before" in runs:
        b = runs["before"]
        print("\nbefore — the defects this phase retires (each measure can fail)")
        check(b["white_charge"] > 0,
              f"the old charge flooded the strip whiter than the set "
              f"({b['white_charge']} px)")
        check(b["drop_first"] < 0.1 * b["drop_peak"] + 1e-9,
              f"the old drop started from black ({b['drop_first']:.3f} of "
              f"peak {b['drop_peak']:.3f})")
        check(b["charge_peak"] > b["drop_peak"],
              f"…and its build out-shone its payoff ({b['charge_peak']:.3f} "
              f"vs {b['drop_peak']:.3f})")
        check(not (b["dark_solid"] and b["dark_from"] == want_from),
              "the old lull did not go dark at the room's dark point")
        c0 = windows()[0]
        check(all(np.array_equal(x, y) for x, y in
                  zip(frames["before"][:c0], frames["now"][:c0])),
              f"off-phase the strip is byte-identical to before (all {c0} "
              "normal frames, same seed) — joining the layer changes nothing "
              "outside a phase")
        check(now["n_charge_peak"] > b["n_charge_peak"]
              and now["n_drop_peak"] > b["n_drop_peak"],
              f"more blobs now: charge peak {b['n_charge_peak']} -> "
              f"{now['n_charge_peak']}, drop peak {b['n_drop_peak']} -> "
              f"{now['n_drop_peak']}")

    print(f"\nconstants: charge formation up to {bh1.CHARGE_SPAWN_RATE_MAX:.0f}/s, "
          f"drop burst {bh1.PHASE_BURST_N}..{bh1.PHASE_BURST_N_MAX} by "
          f"intensity (now {bh1.Blackhole1d.__name__} at {DROP_INTENSITY}: "
          f"{int(round(bh1.PHASE_BURST_N + (bh1.PHASE_BURST_N_MAX - bh1.PHASE_BURST_N) * DROP_INTENSITY))}), "
          f"punch ring burst {bh1.PUNCH_BURST_N}")
    print("\n" + ("ALL CHECKS PASSED" if not _failures
                  else f"{len(_failures)} FAILED: " + "; ".join(_failures)))
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
