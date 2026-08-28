"""Measure the FISH lunge (fx/effects/fish.py, LUNGE_* constants).

His live diagnosis: the ripple correctly scales off real speed and flap, but
the beat speed boost decayed within tens of milliseconds, so big ripples rode
tiny travel. The lunge holds that boost near full for LUNGE_HOLD_S. This
prints the quantity that settles it — DISTANCE COVERED PER STRONG BEAT, in
body lengths — with the pre-lunge behaviour as the negative control, and the
quiet-swimming control that must not move at all.

Read-only, offline (fx.headless at his crystal-mapper's shape, audio
silenced). No live access.

    .venv/bin/python scripts/check_fish_lunge.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless  # noqa: E402
from fx.effects import fish as FX  # noqa: E402

DT = 1.0 / 60.0
ROWS, COLS = 37, 72

HIS = {
    "particle_count": 3, "radius_scale": 1.8, "horizon_scale": 0.19,
    "blob_size": 2.5, "x_offset": 0.5, "y_offset": 0.5, "spin": 0.37,
    "base_speed": 0.3, "jiggle": 0.5, "roam_scale": 0.75,
    "tether_scatter": 0.0, "reactivity_scale": 1.0, "speed_jump": 1.0,
    "speed_jog": 1.0, "brightness_audio": 0.5, "size_audio": 0.5,
    "color_shift": 1, "impulse_decay": 0.06, "reverse": False,
}


_RUN = [0]


async def _beat_travel(gain, window_s=1.0, beats=6, seed=5, quiet=False,
                       loud=False, hold=None):
    """Mean path length each fish covers in `window_s` after a strong beat,
    in BODY LENGTHS.

    `quiet=True` fires no beat at all (the calm control). `loud=True`
    additionally drives a simulated MUSIC envelope on top of the beat —
    headless audio is silenced, so with no drive a beat's spike caps at the
    0.4 floor `draw()` gives it; a real room's spike reaches 1.0, and that is
    the case worth reporting. `hold` overrides LUNGE_HOLD_S.
    """
    orig = FX.LUNGE_GAIN, FX.LUNGE_HOLD_S
    FX.LUNGE_GAIN = gain
    if hold is not None:
        FX.LUNGE_HOLD_S = hold
    # a UNIQUE device id per run: fx.effects.particle_handoff keeps a
    # module-level snapshot keyed by device, so reusing one name silently
    # hands the previous run's fish to the next and destroys determinism.
    _RUN[0] += 1
    dev = f"fish-lunge-{_RUN[0]}"
    try:
        with tempfile.TemporaryDirectory() as td:
            host = await headless.start_headless_host(
                str(Path(td) / dev), pixel_count=ROWS * COLS, rows=ROWS,
                device_id=dev,
            )
            virtual = host.virtuals.get(dev)
            with headless.fake_clock() as clock:
                eff = headless.attach_effect(host, virtual, "fish", dict(HIS))
                eff._rng = np.random.default_rng(seed)

                env = [0.0]

                def step():
                    if loud:
                        # a beat envelope on the same two signals draw()
                        # reads; spike = clip((impulse - slow) * 3, 0, 1)
                        eff.impulse = float(env[0])
                        eff.slow = 0.30 * float(env[0])
                        env[0] *= 0.5 ** (DT / 0.25)
                    clock.advance(DT)
                    f = virtual.assemble_frame()
                    if f is not None:
                        virtual.flush(f)

                for _ in range(180):
                    step()
                body = eff._body_len_px()
                travels = []
                for _ in range(beats):
                    if not quiet:
                        eff._beat_pending = True
                        env[0] = 1.0
                    n = eff.n
                    px = eff.p_x[:n].copy() * eff.sx
                    py = eff.p_y[:n].copy() * eff.sy
                    dist = np.zeros(n)
                    for _ in range(int(window_s / DT)):
                        step()
                        k = min(n, eff.n)
                        nx = eff.p_x[:k] * eff.sx
                        ny = eff.p_y[:k] * eff.sy
                        dist[:k] += np.hypot(nx - px[:k], ny - py[:k])
                        px[:k], py[:k] = nx, ny
                    travels.append(float(dist[:eff.n].mean()) / body)
                    for _ in range(int(1.2 / DT)):   # settle between beats
                        step()
                await host.shutdown()
        return float(np.mean(travels))
    finally:
        FX.LUNGE_GAIN, FX.LUNGE_HOLD_S = orig


def main():
    print("fish lunge — distance covered in the 1.0s after a strong beat, "
          "in body lengths\n(his state: jiggle 0.5, roam_scale 0.75, "
          f"speed_jump {HIS['speed_jump']}; hold {FX.LUNGE_HOLD_S}s, "
          f"release half-life {FX.LUNGE_FALL_S}s)\n")
    seeds = (5, 11, 23, 41)
    off = np.mean([asyncio.run(_beat_travel(0.0, seed=s)) for s in seeds])
    print(f"  lunge OFF (pre-lunge behaviour)   {off:5.2f} body lengths"
          "   <- NEGATIVE CONTROL")
    for gain in (0.5, 1.0, 1.5):
        got = np.mean([asyncio.run(_beat_travel(gain, seed=s)) for s in seeds])
        star = "  <- shipped" if abs(gain - FX.LUNGE_GAIN) < 1e-9 else ""
        print(f"  LUNGE_GAIN {gain:<4}                  {got:5.2f}"
              f"   ({100 * (got - off) / off:+.0f}%){star}")

    print("\n  with a real music envelope (spike reaches 1.0, "
          "as in his room):")
    l_off = np.mean([asyncio.run(_beat_travel(0.0, seed=s, loud=True))
                     for s in seeds])
    l_on = np.mean([asyncio.run(_beat_travel(FX.LUNGE_GAIN, seed=s,
                                             loud=True)) for s in seeds])
    print(f"    lunge OFF {l_off:5.2f} body lengths   <- NEGATIVE CONTROL")
    print(f"    lunge ON  {l_on:5.2f}   "
          f"({100 * (l_on - l_off) / l_off:+.0f}%)")

    print("\n  the HOLD is what does it (loud, LUNGE_GAIN "
          f"{FX.LUNGE_GAIN}):")
    for h in (0.0, 0.3, 0.6, 0.8):
        got = np.mean([asyncio.run(_beat_travel(FX.LUNGE_GAIN, seed=s,
                                                loud=True, hold=h))
                       for s in seeds])
        star = "  <- shipped" if abs(h - FX.LUNGE_HOLD_S) < 1e-9 else ""
        print(f"    hold {h:<4}s   {got:5.2f} body lengths"
              f"   ({100 * (got - l_off) / l_off:+.0f}%){star}")

    print("\n  quiet control (no beat fired, same seeds):")
    q_off = np.mean([asyncio.run(_beat_travel(0.0, seed=s, quiet=True))
                     for s in seeds])
    q_on = np.mean([asyncio.run(_beat_travel(FX.LUNGE_GAIN, seed=s,
                                             quiet=True)) for s in seeds])
    print(f"    lunge OFF {q_off:.6f}   lunge ON {q_on:.6f}   "
          f"delta {abs(q_on - q_off):.2e} body lengths")
    assert abs(q_on - q_off) < 1e-9, "quiet swimming must be untouched"
    print("\nPASS")


if __name__ == "__main__":
    main()
