#!/usr/bin/env python3
"""Read-only evidence script for the Squiggles drop-timing fix
(fx/effects/squiggles.py, PR
fm/spectra-squiggles-drop-timing-and-a-much-bigger-explosion).

His report, verbatim: "the drop on squiggles is not timed correct. The new
black hole timing is really good. Squiggles needs to explode right on the
trigger, and the explosion needs to be way bigger and last longer."

Black Hole's own drop payoff (`_phase_burst`) is gated on `phase_progress`
reaching ~1.0 (with a wall-clock fallback, `DROP_FALLBACK_S`, so a dropped
ramp can never lose the payoff) — his confirmed-good reference. Squiggles
used to call `_phase_burst()` the INSTANT `phase` edged to "drop", i.e. at
progress=0.0, before scene_response._drive_phase's 400ms ramp had played
any of the way through. Since the SAME drive mechanism
(`{"phase": <class>, "phase_progress": 0.0}` instant arm, then a glide of
phase_progress -> 1.0) feeds every phase-capable effect off the identical
trigger, this landed Squiggles' explosion up to a full ramp EARLY relative
to Black Hole on the same drop.

This script drives the real charge->lull->drop state machine through the
production code path (Effect.update_config, same call shape
scene_response.py's `_drive_phase` uses) on a headless dummy host, in two
variants:

  A. RAMPED — phase_progress glides 0->1 over 0.3s (mirrors
     scripts/check_blackhole_explosion_and_gap.py's own drop-ramp
     duration). Proves the burst fires at ~ramp-completion, not at t=0.
  B. STALLED — phase_progress never moves off 0.0 (a dropped/lost ramp).
     Proves the DROP_FALLBACK_S wall-clock fallback still lands the burst
     (the payoff can never be silently lost).

Every burst is measured directly off `_phase_burst`'s own chain count
(instrumented, not asserted) — the same engine the drop payoff actually
runs on, not a re-derivation. Speed is read directly off a burst chain's
own `speed_override`.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fx import headless  # noqa: E402
from fx.effects import squiggles  # noqa: E402

DT = 1.0 / 60.0

BASE_CONFIG = {
    "spawn_rate": 2.0,
    "beat_burst": 1,
    "max_blobs": 14,
    "base_speed": 38.0,
}


async def _run_variant(tmp_path: Path, sub: str, *, ramp: bool, ramp_s: float = 0.3):
    host = await headless.start_headless_host(str(tmp_path / sub), device_id=sub)
    virtual = host.virtuals.get(sub)

    burst_log: list[tuple[int, int]] = []
    frame_idx = [0]

    with headless.fake_clock() as clock:
        effect = headless.attach_effect(host, virtual, "squiggles", BASE_CONFIG)

        orig_burst = effect._phase_burst

        def logged_burst(_orig=orig_burst):
            before = len(effect.chains)
            _orig()
            added = len(effect.chains) - before
            burst_log.append((frame_idx[0], added))

        effect._phase_burst = logged_burst

        def step(n_frames: int):
            for _ in range(n_frames):
                clock.advance(DT)
                frame = virtual.assemble_frame()
                if frame is not None:
                    virtual.flush(frame)
                frame_idx[0] += 1

        # CHARGE: ramp phase_progress 0->1 over 1.2s
        effect.update_config({"phase": "charge", "phase_progress": 0.0})
        charge_frames = int(1.2 / DT)
        for i in range(1, charge_frames + 1):
            effect.update_config({"phase_progress": i / charge_frames})
            step(1)

        # LULL: hold for 1.0s
        effect.update_config({"phase": "lull", "phase_progress": 0.0})
        step(int(1.0 / DT))

        # DROP
        drop_start_frame = frame_idx[0]
        effect.update_config({"phase": "drop", "phase_progress": 0.0})
        immediate_burst = bool(burst_log)  # would a t=0 burst show up here?
        if ramp:
            drop_frames = int(ramp_s / DT)
            for i in range(1, drop_frames + 1):
                effect.update_config({"phase_progress": i / drop_frames})
                step(1)
        else:
            # a dropped/lost ramp: phase_progress never moves off 0.0
            step(int(1.5 / DT))

        burst_speed_override = None
        for c in effect.chains:
            if c.get("speed_override") is not None:
                burst_speed_override = c["speed_override"]
                break

    await host.shutdown()

    assert burst_log, f"{sub}: drop burst never fired"
    burst_frame, burst_count = burst_log[0]
    burst_delay_s = (burst_frame - drop_start_frame) * DT
    return {
        "immediate_burst_at_edge": immediate_burst,
        "burst_delay_s": burst_delay_s,
        "burst_count": burst_count,
        "burst_speed_override": burst_speed_override,
    }


def check(cond, msg):
    if not cond:
        print(f"FAIL: {msg}")
        raise SystemExit(1)
    print(f"OK: {msg}")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ramped = asyncio.run(_run_variant(tmp_path, "ramped", ramp=True))
        stalled = asyncio.run(_run_variant(tmp_path, "stalled", ramp=False))

    print("RAMPED (0.3s drop ramp):")
    print(f"  burst fired at edge (t=0)?  {ramped['immediate_burst_at_edge']}")
    print(f"  burst delay after drop entry: {ramped['burst_delay_s']:.3f}s")
    print(f"  burst count: {ramped['burst_count']}")
    print(f"  burst chain speed_override: {ramped['burst_speed_override']}")
    print()
    print("STALLED (phase_progress never moves — dropped ramp):")
    print(f"  burst delay after drop entry: {stalled['burst_delay_s']:.3f}s "
          f"(expect ~{squiggles.DROP_FALLBACK_S}s fallback)")
    print(f"  burst count: {stalled['burst_count']}")
    print()

    check(not ramped["immediate_burst_at_edge"],
          "burst must not fire the instant phase edges to drop")
    check(ramped["burst_delay_s"] > 0.2,
          "burst should land near the ramp's completion, not near t=0")
    check(abs(ramped["burst_delay_s"] - 0.3) < 2 * DT + 1e-9,
          "ramped burst should land within one frame of the ramp completing")
    check(ramped["burst_speed_override"] is not None,
          "burst chains must carry a fixed speed_override")
    check(abs(ramped["burst_speed_override"]
              - BASE_CONFIG["base_speed"] * squiggles.DROP_BURST_SPEED_MULT) < 1e-6,
          "burst speed_override should equal base_speed * DROP_BURST_SPEED_MULT")
    check(abs(stalled["burst_delay_s"] - squiggles.DROP_FALLBACK_S) < 2 * DT + 1e-9,
          "a stalled ramp should still land the burst via the wall-clock fallback")

    print("\nALL CHECKS PASSED")
