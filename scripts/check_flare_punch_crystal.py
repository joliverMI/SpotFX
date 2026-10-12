"""A FLARE IN THE LULL'S DARK PUNCHES THROUGH on the crystal and the Singles
(the strip phase plan's phase 5) — measured, not asserted.

Offline, the real render pipeline (fx.headless, dummy devices, a fake clock)
driven by the PRODUCTION ResponseEngine on the FacadeExecutor — the same room
tests/test_flare_punch_crystal.py proves its claims on: a completed charge,
an 8 s lull whose dark point is 5 s in (the room's 3 s cap), and one real
flare (a momentary x1.4 gain held 600 ms) landing 6 s in — in the dark.

For the crystal's Black Hole (its real crystal cells), Squiggles and the Pulse
single it prints, as mean luminance (the brightest frame in each window): the
second before the charge (normal), the lull while still darkening, the dark
before the flare, the brightest frame in the 0.8 s after the flare, and how
long after the flare the dark is back — with the punch, with "Flare punch"
at 0, and under phase 1's strips-only SpotFX (the dark wins).

Reads and writes nothing of his: dummy devices in a temp dir.

    .venv/bin/python scripts/check_flare_punch_crystal.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fx import device_model  # noqa: E402
import test_flare_punch_crystal as T  # noqa: E402

FLARE_AT = 6.0
EFFECTS = (("Black Hole (crystal cells)", "bh", "bh_lum"),
           ("Squiggles", "sq", "sq_lum"),
           ("Pulse (Singles)", "pulse", "pulse_lum"))


def _lit(r, key):
    return r[key] > 0


def _summary(rows, normal, key, lum):
    norm = max(r[lum] for r in normal)
    darkening = max(r[lum] for r in T._window(rows, 2.0, 2.5))
    dark = max(r[lum] for r in T._window(rows, 5.2, FLARE_AT))
    peak = max(r[lum] for r in T._window(rows, FLARE_AT, FLARE_AT + 0.8))
    lit_after = [r["t"] for r in T._window(rows, FLARE_AT, 8.0)
                 if _lit(r, key)]
    back = (f"{max(lit_after) - FLARE_AT + T.DT:.2f} s"
            if lit_after else "never lit")
    return norm, darkening, dark, peak, back


def main():
    runs = {}
    with tempfile.TemporaryDirectory() as tmp:
        runs["punches"] = T._run_lull(Path(tmp) / "a", FLARE_AT)
        runs["Flare punch 0"] = T._run_lull(Path(tmp) / "b", FLARE_AT,
                                            strength=0.0)
        real = device_model.FLARE_PUNCH_EFFECTS
        device_model.FLARE_PUNCH_EFFECTS = device_model.STRIP_PHASE_EFFECTS
        try:
            runs["strips-only SpotFX"] = T._run_lull(Path(tmp) / "c",
                                                     FLARE_AT)
        finally:
            device_model.FLARE_PUNCH_EFFECTS = real

    print("A flare at 6.0 s into an 8 s lull (dark point 5.0 s); mean "
          "luminance, %")
    print(f"{'effect':28s} {'rule':20s} {'normal':>7s} {'darkening':>9s} "
          f"{'dark':>6s} {'flare':>7s}  dark again after the flare")
    ok = True
    for label, key, lum in EFFECTS:
        for rule, (rows, _fired, _vids, normal) in runs.items():
            norm, darkening, dark, peak, back = _summary(rows, normal, key,
                                                         lum)
            print(f"{label:28s} {rule:20s} {100 * norm:7.2f} "
                  f"{100 * darkening:9.2f} {100 * dark:6.2f} "
                  f"{100 * peak:7.2f}  {back}")
            if rule == "punches":
                ok &= dark == 0.0 and peak > 0.0 and back != "never lit"
            else:
                ok &= peak == 0.0
    print("\nattack 0.04 s + hold max(0.5, 0.6) s + release 0.8 s = 1.44 s")
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
