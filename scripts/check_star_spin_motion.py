"""Executable proof: radial (STAR) rotation is AUDIO-DRIVEN, not a motor.

Investigation 2026-08-21 ("star is not moving at any speed"): the crystal was
painting at a healthy frame rate with a healthy ``spin`` config (0.55), and
still visibly did not rotate. This script proves why, against the REAL
vendored pipeline (fx.headless host + fx.audio_ingest.HubMelbankSource — the
identical wiring spectra/services/live_host.py installs), with zero hardware
and zero live storage.

The mechanism (fx/effects/radial.py):

    audio_data_updated:  spin_total += impulse * spin_cfg**2 / 10
    where impulse = lows_power() — live captured audio power in the
    beat+bass mel bins, NOT the bridge's librosa "intensity" (that number
    is precomputed from the song FILE and stays high even when the live
    capture's lows are quiet).

So at 60 audio callbacks/s:  rev/s = 6 * impulse * spin_cfg**2.
At his spin 0.55 that is 1.815 * impulse — and the lows impulse of a real
track idles near ~0.01 through bass-light passages, i.e. ~6 degrees/second:
parked, to the eye, while the effect keeps rendering every frame.

Sections:
  1. Silence           -> spin_total advance is EXACTLY zero at spin=0.55.
  2. Mid-only audio    -> loud 1 kHz content, no lows: still parked.
  3. Pumping bass      -> the same spin=0.55 visibly rotates.
  4. spin=0, bass thumping -> exactly zero (both factors are required).

Run: .venv/bin/python scripts/check_star_spin_motion.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fx import headless  # noqa: E402
from fx.audio_ingest import HubMelbankSource  # noqa: E402
from fx.effects import audio as fx_audio  # noqa: E402

RATE = 44100
CALLBACKS_PER_S = 60
HOP = RATE // CALLBACKS_PER_S  # 735 — the stock InputStream blocksize

# a 6-pointed star's symmetry repeats every 60°; treat anything under
# ~10°/s as "parked to the eye" and anything over ~30°/s as clearly moving
PARKED_REV_S = 10.0 / 360.0
VISIBLE_REV_S = 30.0 / 360.0

HIS_SPIN = 0.55  # the live value observed on crystal-mapper, 2026-08-21


def _tone(freq: float, seconds: float, amp: float) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _bass_pulses(seconds: float) -> np.ndarray:
    """Reggaeton-ish lows: a sustained sub under 55+110 Hz bursts, 200 ms
    long, three a second — comparable to the real-track capture this
    investigation measured (avg lows impulse ~0.07-0.13 in bass passages)."""
    n = int(seconds * RATE)
    t_all = np.arange(n) / RATE
    out = (0.15 * np.sin(2 * np.pi * 50 * t_all)).astype(np.float32)
    burst_len = int(0.2 * RATE)
    t = np.arange(burst_len) / RATE
    burst = (0.5 * np.sin(2 * np.pi * 55 * t)
             + 0.25 * np.sin(2 * np.pi * 110 * t)).astype(np.float32)
    burst *= np.hanning(burst_len).astype(np.float32)
    step = int(RATE / 3)
    for start in range(0, n - burst_len, step):
        out[start:start + burst_len] += burst
    return out


def _drive(melbank: HubMelbankSource, effect, audio: np.ndarray) -> float:
    """Feed audio through the real ingest path; return the unwrapped
    spin_total advance in revolutions."""
    total = 0.0
    last = effect.spin_total
    for i in range(0, len(audio) - HOP + 1, HOP):
        melbank.ingest(audio[i:i + HOP])
        d = effect.spin_total - last
        if d < -0.5:
            d += 1.0
        elif d > 0.5:
            d -= 1.0
        total += d
        last = effect.spin_total
    return total


async def main() -> None:
    with tempfile.TemporaryDirectory() as cfgdir:
        host = await headless.start_headless_host(
            cfgdir, pixel_count=2664, rows=37, device_id="crystal-mapper")
        prev_cls = fx_audio.AudioAnalysisSource
        fx_audio.AudioAnalysisSource = HubMelbankSource
        try:
            melbank = HubMelbankSource(host)
            host.audio = melbank
            virtual = host.virtuals.get("crystal-mapper")

            def attach(spin_cfg: float):
                return headless.attach_effect(host, virtual, "radial", {
                    "spin": spin_cfg, "star": -0.5, "edges": 6, "twist": 0,
                    "polygon": True,
                })

            seconds = 4.0

            # 1 — silence: the speed parameter alone moves nothing
            effect = attach(HIS_SPIN)
            adv = _drive(melbank, effect, np.zeros(int(seconds * RATE),
                                                   dtype=np.float32))
            assert adv == 0.0, f"silence advanced spin_total by {adv}"
            print(f"1. silence, spin={HIS_SPIN}: advance {adv:.5f} rev "
                  "— exactly zero. Spin is a gain, not a motor speed.")
            effect.deactivate()

            # 2 — loud mids, no lows: still parked
            effect = attach(HIS_SPIN)
            adv = _drive(melbank, effect, _tone(1000.0, seconds, 0.3))
            rate = abs(adv) / seconds
            assert rate < PARKED_REV_S, f"mid-only audio moved it: {rate} rev/s"
            print(f"2. loud 1kHz (no lows), spin={HIS_SPIN}: {rate:.4f} rev/s "
                  f"({rate * 360:.1f}°/s) — parked. The impulse is LOWS power "
                  "(beat+bass mel bins), other bands don't drive it.")
            effect.deactivate()

            # 3 — pumping bass: the same spin visibly rotates
            effect = attach(HIS_SPIN)
            adv = _drive(melbank, effect, _bass_pulses(seconds))
            rate = abs(adv) / seconds
            assert rate > VISIBLE_REV_S, f"bass failed to move it: {rate} rev/s"
            print(f"3. bass pulses, spin={HIS_SPIN}: {rate:.4f} rev/s "
                  f"({rate * 360:.1f}°/s) — clearly moving. Same config, "
                  "only the audio changed.")
            effect.deactivate()

            # 4 — spin=0 with thumping bass: both factors are required
            effect = attach(0.0)
            adv = _drive(melbank, effect, _bass_pulses(seconds))
            assert adv == 0.0, f"spin=0 advanced by {adv}"
            print("4. bass pulses, spin=0.0: advance exactly zero — "
                  "rev/s = 6 × lows_impulse × spin², both terms required.")
        finally:
            fx_audio.AudioAnalysisSource = prev_cls
            await host.shutdown()

    print("\nOK — radial rotation = 6 × lows_impulse × spin² rev/s; a healthy")
    print("spin with idle lows reads as 'not moving at any speed' by design.")


if __name__ == "__main__":
    asyncio.run(main())
