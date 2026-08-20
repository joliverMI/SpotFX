#!/usr/bin/env python3
"""Read-only evidence script for Squiggles' drop-burst timing
(fx/effects/squiggles.py).

History, so the reversal below isn't read as a flip-flop: his ORIGINAL
report was "the drop on squiggles is not timed correct... squiggles needs
to explode right on the trigger" — at the time, Black Hole's own
progress-gated burst (fires when phase_progress reaches ~1.0) was his
confirmed-good reference, so PR fm/spectra-squiggles-drop-timing-and-a-
much-bigger-explosion made Squiggles mirror that same end-anchored gate.
Black Hole was LATER tried and withdrawn as a drop-timing reference (data/
drops-still-fire-early-star-does-not-explode/ — his words: "actually, i
think black hole might be too early, also"), and he settled a THREE-anchor
rule instead: momentary flares anchor their switch's END to the mark,
scene transitions anchor their MIDDLE, and drops/explosions anchor their
START — "an explosion begins on the trigger mark rather than before it".
Under that settled rule, the end-anchored gate this script used to prove
correct is now the defect: it fires up to a full ramp LATE relative to the
mark, not on it. fx/effects/blackhole.py's own drop branch was fixed the
same way, the same day, for the same reason — see its module comment.

This script drives the real charge->lull->drop state machine through the
production code path (Effect.update_config, same call shape
scene_response.py's `_drive_phase` uses) on a headless dummy host, in two
variants:

  A. RAMPED — phase_progress glides 0->1 over 0.3s (mirrors
     scripts/check_blackhole_explosion_and_gap.py's own drop-ramp
     duration).
  B. STALLED — phase_progress never moves off 0.0 (a dropped/lost ramp).

Both must land the burst on the phase's very first frame — proving the
burst no longer depends on phase_progress reaching anything, so a
stalled/lost ramp can't affect it either (not because of a wall-clock
fallback racing it, the way Black Hole's old gate needed one, but because
there is nothing left to wait for).

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
        # would the burst have fired SYNCHRONOUSLY on the config write
        # itself, before even one frame has rendered? Must always be
        # False — the burst belongs inside the normal per-frame
        # _phase_step cadence (real dt, real _phase_t bookkeeping), never
        # a side effect of writing config. Distinct from burst_delay_s
        # below, which measures how many RENDERED frames it takes — 0 is
        # the correct, desired value there (the first frame is a frame).
        burst_before_first_frame = bool(burst_log)
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
        "burst_before_first_frame": burst_before_first_frame,
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
    print(f"  burst fired before any frame rendered? {ramped['burst_before_first_frame']}")
    print(f"  burst delay after drop entry: {ramped['burst_delay_s']:.3f}s")
    print(f"  burst count: {ramped['burst_count']}")
    print(f"  burst chain speed_override: {ramped['burst_speed_override']}")
    print()
    print("STALLED (phase_progress never moves — dropped ramp):")
    print(f"  burst delay after drop entry: {stalled['burst_delay_s']:.3f}s "
          f"(expect ~0s — the burst no longer waits on phase_progress at all)")
    print(f"  burst count: {stalled['burst_count']}")
    print()

    check(not ramped["burst_before_first_frame"],
          "the burst must never fire synchronously on the config write "
          "itself — it belongs inside the normal per-frame _phase_step "
          "cadence, on the phase's first RENDERED frame")
    check(ramped["burst_delay_s"] < 2 * DT + 1e-9,
          "burst should land within one frame of drop entry — the "
          "explosion begins on the mark, it doesn't wait for a ramp")
    check(not stalled["burst_before_first_frame"],
          "same synchronous-fire guard, stalled-ramp variant")
    check(stalled["burst_delay_s"] < 2 * DT + 1e-9,
          "the stalled variant lands the burst on the same frame as the "
          "ramped one — there is no wall-clock fallback racing a ramp "
          "here any more, because nothing is being waited on")
    check(ramped["burst_speed_override"] is not None,
          "burst chains must carry a fixed speed_override")
    check(abs(ramped["burst_speed_override"]
              - BASE_CONFIG["base_speed"] * squiggles.DROP_BURST_SPEED_MULT) < 1e-6,
          "burst speed_override should equal base_speed * DROP_BURST_SPEED_MULT")

    print("\nALL CHECKS PASSED")
