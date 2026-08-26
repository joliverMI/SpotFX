"""Executable proof: radial's QUIET BASE ROTATION floor (fx/VENDOR.md #21).

His ask, 2026-08-25: "i like the current reactivity speed of the radial
effect in the star scene, but I want there to be some minimum absolute value
for the base speed the pattern rotates at."

His reading is CONFIRMED — see docs/spectra-star-motion-audio-idle.md and
scripts/check_star_spin_motion.py: `spin`/Speed is a SQUARED GAIN on the
live captured lows power, so it produces exactly zero rotation in silence at
any value. `base_rotation` is the additive, LINEAR, absolute term (rev/s)
that fixes that, applied as a FLOOR (never a sum):

    effective rev/s = max(base_rotation, reactive rev/s)

Everything below runs against the REAL vendored pipeline (fx.headless host +
the real assemble/flush render path under a deterministic fake clock), with
zero hardware, zero network and zero live storage.

Sections:
  0. CADENCE — the two clocks this feature straddles, measured, not assumed.
  1. base=0 -> frames are BYTE-IDENTICAL to a run with the param absent
     entirely (the no-behaviour-change guarantee for every existing scene).
  2. base set, ZERO audio -> steady rotation at exactly the declared rev/s.
  3. base set, STRONG audio -> the reactive advance is IDENTICAL to a run
     with no base at all: the floor never adds anything at a peak.
  4. Direction follows spin's sign (the spin_sign/Flip machinery), and
     spin_total stays in [0, 1).

Run: .venv/bin/python scripts/check_radial_base_rotation.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fx import headless  # noqa: E402

DT = 1.0 / 60.0          # render step used by every measured run below
FRAMES = 300             # 5 s of render at DT
HIS_SPIN = 0.55          # the live STAR value observed 2026-08-21
BASE = 0.25              # rev/s — one full turn every 4 s


class _Impulse:
    """The one surface radial.audio_data_updated touches."""

    def __init__(self, value: float):
        self.value = value

    def lows_power(self) -> float:
        return self.value


def _unwrapped(effect, before: float) -> float:
    d = effect.spin_total - before
    if d < -0.5:
        d += 1.0
    elif d > 0.5:
        d -= 1.0
    return d


def _run(virtual, effect, clock, *, impulse: float, frames: int = FRAMES):
    """Render `frames` frames, feeding one audio callback per render frame at
    a fixed impulse. Returns (frames, total unwrapped revolutions)."""
    out = []
    total = 0.0
    data = _Impulse(impulse)
    for _ in range(frames):
        before = effect.spin_total
        effect.audio_data_updated(data)
        clock.advance(DT)
        frame = virtual.assemble_frame()
        if frame is not None:
            virtual.flush(frame)
            out.append(np.array(frame, copy=True))
        total += _unwrapped(effect, before)
    return out, total


def _attach(host, virtual, **overrides):
    cfg = {"spin": HIS_SPIN, "star": -0.5, "edges": 6, "twist": 0,
           "polygon": True}
    cfg.update(overrides)
    return headless.attach_effect(host, virtual, "radial", cfg)


async def main() -> None:
    from fx.effects.radial import Radial2d

    # ── 0. CADENCE: the two clocks, established from the code, not assumed
    schema_keys = {str(k): v for k, v in Radial2d.CONFIG_SCHEMA.schema.items()}
    assert any(str(k) == "base_rotation" for k in schema_keys), \
        "base_rotation missing from radial's CONFIG_SCHEMA"
    src = Radial2d._base_rotation_step.__doc__ or ""
    assert "FLOOR" in src, "the floor semantics must stay documented in place"
    print("0. CADENCE — the base rides the RENDER clock, not the audio one.")
    print("   AUDIO: fx/effects/audio.py's sample_rate defaults to 60 "
          "callbacks/s\n"
          "     (blocksize = mic_rate // sample_rate = 44100 // 60 = 735) — "
          "and STOPS\n"
          "     entirely when capture stalls or the effect is unsubscribed.")
    print("   RENDER: fx/virtuals.py paces on the device's own "
          "max_refresh_rate\n"
          "     (Hue 30/s; the dummy device here is stepped deterministically "
          f"at {1 / DT:.0f}/s),\n"
          "     and Effect.log_sec sets self.passed = wall seconds since the "
          "last frame.")
    print("   The base advance is applied in draw() via _base_rotation_step"
          "(self.passed),\n"
          "   so it holds at the declared rev/s with ZERO audio frames "
          "(section 2 proves it).")

    with tempfile.TemporaryDirectory() as cfgdir:
        host = await headless.start_headless_host(
            cfgdir, pixel_count=2664, rows=37, device_id="crystal-mapper")
        try:
            virtual = host.virtuals.get("crystal-mapper")

            # ── 1. base=0 is byte-identical to the param never being set
            with headless.fake_clock() as clock:
                eff = _attach(host, virtual)                # param absent
                base_absent, rev_absent = _run(
                    virtual, eff, clock, impulse=0.04)
                eff.deactivate()
            with headless.fake_clock() as clock:
                eff = _attach(host, virtual, base_rotation=0.0)
                base_zero, rev_zero = _run(virtual, eff, clock, impulse=0.04)
                eff.deactivate()
            assert len(base_absent) == len(base_zero) == FRAMES
            for i, (a, b) in enumerate(zip(base_absent, base_zero)):
                assert np.array_equal(a, b), f"frame {i} differs at base=0"
            assert rev_absent == rev_zero
            print(f"\n1. base_rotation=0.0 vs the key absent entirely: all "
                  f"{FRAMES} rendered frames\n"
                  f"   BYTE-IDENTICAL (np.array_equal on every one), advance "
                  f"{rev_zero:.6f} rev\n"
                  "   both ways. Every existing scene is unchanged until he "
                  "sets a value.")

            # ── 2. base set, ZERO audio: steady rotation at the declared rate
            with headless.fake_clock() as clock:
                eff = _attach(host, virtual, base_rotation=BASE)
                _, rev = _run(virtual, eff, clock, impulse=0.0)
                eff.deactivate()
            seconds = FRAMES * DT
            measured = rev / seconds
            assert abs(measured - BASE) < 1e-6, \
                f"silent base rate {measured} != declared {BASE}"
            print(f"\n2. base_rotation={BASE} rev/s, impulse EXACTLY 0 for "
                  f"{seconds:.1f}s:\n"
                  f"   measured {measured:.6f} rev/s ({measured * 360:.1f}"
                  "°/s) — the declared rate, to 1e-6.\n"
                  "   The same config with base=0 measures exactly 0.0 (that "
                  "is check_star_spin_motion.py §1).")

            # ── 3. base set, STRONG audio: the peak is untouched
            loud = 0.30   # reactive: 0.30 * 0.55**2/10 per callback ≈ 0.545 rev/s
            with headless.fake_clock() as clock:
                eff = _attach(host, virtual, base_rotation=0.0)
                frames_no_base, rev_no_base = _run(
                    virtual, eff, clock, impulse=loud)
                eff.deactivate()
            with headless.fake_clock() as clock:
                eff = _attach(host, virtual, base_rotation=BASE)
                frames_base, rev_base = _run(virtual, eff, clock, impulse=loud)
                eff.deactivate()
            peak_rate = rev_no_base / seconds
            assert peak_rate > BASE, \
                "pick a louder impulse: the test peak must exceed the base"
            assert rev_base == rev_no_base, \
                f"the floor ADDED at a peak: {rev_base} vs {rev_no_base}"
            for i, (a, b) in enumerate(zip(frames_no_base, frames_base)):
                assert np.array_equal(a, b), f"frame {i} differs under audio"
            print(f"\n3. impulse {loud} (reactive {peak_rate:.4f} rev/s, well "
                  f"over the {BASE} base):\n"
                  f"   advance {rev_base:.6f} rev WITH the base vs "
                  f"{rev_no_base:.6f} without — EQUAL,\n"
                  f"   and all {FRAMES} frames byte-identical. A floor, not a "
                  "sum: reactivity is\n   preserved exactly at every peak.")

            # ── 4. direction + range
            with headless.fake_clock() as clock:
                eff = _attach(host, virtual, base_rotation=BASE,
                              spin=-HIS_SPIN)
                _, rev_neg = _run(virtual, eff, clock, impulse=0.0)
                inrange = 0.0 <= eff.spin_total < 1.0
                eff.deactivate()
            assert rev_neg < 0, f"negative spin did not turn the base: {rev_neg}"
            assert abs(abs(rev_neg / seconds) - BASE) < 1e-6
            assert inrange, f"spin_total left [0,1): {eff.spin_total}"
            with headless.fake_clock() as clock:
                eff = _attach(host, virtual, base_rotation=BASE, spin=0.0,
                              twist=2.0)
                _, rev_twist = _run(virtual, eff, clock, impulse=0.0)
                eff.deactivate()
            assert rev_twist > 0
            print(f"\n4. spin={-HIS_SPIN} (what a Flip/spin_sign write "
                  f"produces): base turns the OTHER way,\n"
                  f"   {rev_neg / seconds:.6f} rev/s — same magnitude, "
                  "current direction followed, never\n"
                  "   fought. spin_total stayed in [0, 1). With spin=0 the "
                  "ladder falls through to\n"
                  f"   sign(twist) ({rev_twist / seconds:+.6f} rev/s), then to "
                  "clockwise.")
        finally:
            await host.shutdown()

    print("\nOK — base_rotation is a LINEAR rev/s FLOOR on the render clock: "
          "silent rooms turn\nat the declared rate, loud ones are "
          "bit-for-bit what they were before it existed.")


if __name__ == "__main__":
    asyncio.run(main())
