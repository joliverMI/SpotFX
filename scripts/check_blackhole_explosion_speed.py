#!/usr/bin/env python3
"""Read-only evidence script for the Black Hole drop-explosion speed fix
(fx/effects/blackhole.py, PR fm/spectra-blackhole-explosion-twice-as-fast).

His ask, verbatim: "the timing is good on black hole, but the speed of the
explosion after the implosion needs to be 2 times faster." Narrow scope: the
outward burst only (_phase_burst's blobs, tagged p_is_burst), not the
implosion (the pinch) and not the whole drop (the post-burst horizon
ease-back stays DROP_RESET_S).

This script drives the real charge->lull->drop state machine through the
production code path on a headless dummy host (same harness as
scripts/check_blackhole_explosion_and_gap.py) and proves three things
directly off the running effect, not by inspection:

  1. LANDING POINT UNCHANGED — the drop burst fires on the exact same frame
     regardless of PHASE_BURST_SPEED_MULT. Changing the explosion's speed
     must not shift when the drop lands on the trigger's timestamp.
  2. SAME REACH, HALF THE TIME — the burst-tagged particles' mean radius at
     MULT=2's outward-flight settle time (when the last p_out expires)
     matches MULT=1's settle radius, and MULT=2's settle time is
     ~half of MULT=1's. This is the "twice as fast, not twice as far"
     property: doubling velocity without halving duration would make the
     explosion bigger, not faster — this proves the paired change avoids
     that.
  3. AMBIENT-SPAWN DECOUPLING (PR #149) STILL HOLDS UNDER THE FASTER PATH —
     the post-burst ambient/beat spawn gap (his other, already-shipped ask)
     is unaffected by the speed change: still tracks the uncapped control's
     natural cadence, not starved.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fx import headless  # noqa: E402
from fx.effects import blackhole  # noqa: E402
from fx.effects.blackhole import Blackhole2d  # noqa: E402

import scripts.check_blackhole_explosion_and_gap as gapcheck  # noqa: E402

DT = 1.0 / 60.0


async def _run_speed_variant(tmp_path: Path, sub: str, *, speed_mult: float,
                              max_blobs: int = 50):
    host = await headless.start_headless_host(str(tmp_path / sub), device_id=sub)
    virtual = host.virtuals.get(sub)

    burst_log: list[int] = []
    spawn_log: list[tuple[int, int]] = []
    # per-frame (frame_idx, mean radius of burst-tagged particles still in
    # flight) sampled every frame after ignition
    radius_series: list[tuple[int, float]] = []
    settle_frame = [None]
    settle_radius = [None]
    frame_idx = [0]

    with headless.fake_clock() as clock:
        config = dict(gapcheck.BASE_CONFIG, max_blobs=max_blobs)
        effect = gapcheck._attach_custom_effect(host, virtual, Blackhole2d, config)
        effect._rng = np.random.default_rng(20260820)

        orig_spawn = effect._spawn

        def logged_spawn(count, beat_count, _orig=orig_spawn, **kw):
            # AMBIENT spawns only: since 2026-08-24 the charge/lull also
            # force blobs into being through this same function with
            # ignore_cap=True (fx/effects/blackhole.py's _phase_spawn_rate),
            # and this measurement is about the music-driven population the
            # cap governs — counting the forced ones would silently change
            # what this script reports.
            before = effect.n
            _orig(count, beat_count, **kw)
            added = effect.n - before
            if added > 0 and not kw.get("ignore_cap"):
                spawn_log.append((frame_idx[0], added))

        effect._spawn = logged_spawn

        orig_burst = effect._phase_burst

        def logged_burst(_orig=orig_burst):
            before = effect.n
            _orig()
            burst_log.append(frame_idx[0])

        effect._phase_burst = logged_burst

        beat_interval_frames = int(0.4 / DT)

        def step(n_frames: int):
            for _ in range(n_frames):
                if frame_idx[0] % beat_interval_frames == 0:
                    effect._beat_pending = True
                clock.advance(DT)
                frame = virtual.assemble_frame()
                if frame is not None:
                    virtual.flush(frame)
                if burst_log:
                    n = effect.n
                    burst_mask = effect.p_is_burst[:n]
                    flying = burst_mask & (effect.p_out[:n] > 0.0)
                    if flying.any():
                        radius_series.append(
                            (frame_idx[0], float(effect.p_r[:n][flying].mean()))
                        )
                    elif burst_mask.any() and settle_frame[0] is None:
                        settle_frame[0] = frame_idx[0]
                        settle_radius[0] = float(effect.p_r[:n][burst_mask].mean())
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

        # DROP: ramp phase_progress 0->1 over 0.3s -> triggers the burst.
        # Apply the speed multiplier for this variant right as the drop
        # arms so charge/lull pacing (unrelated to this feature) is
        # identical across variants.
        blackhole.PHASE_BURST_SPEED_MULT = speed_mult
        effect.update_config({"phase": "drop", "phase_progress": 0.0})
        drop_frames = int(0.3 / DT)
        for i in range(1, drop_frames + 1):
            effect.update_config({"phase_progress": i / drop_frames})
            step(1)

        # POST: measure ambient/beat spawn continuation for 3s
        step(int(3.0 / DT))

        n_at_end = effect.n

    await host.shutdown()

    assert burst_log, f"{sub}: drop burst never fired"
    burst_frame = burst_log[0]
    after = [t for t, _ in spawn_log if t > burst_frame]
    gap_s = (after[0] - burst_frame) * DT if after else None
    return {
        "burst_frame_s": burst_frame * DT,
        "settle_frame_s": (
            (settle_frame[0] - burst_frame) * DT
            if settle_frame[0] is not None else None
        ),
        "settle_radius": settle_radius[0],
        "gap_s": gap_s,
        "spawns_after_burst_3s": len(after),
        "n_at_end": n_at_end,
    }


def main() -> int:
    orig_mult = blackhole.PHASE_BURST_SPEED_MULT
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        try:
            slow = asyncio.run(
                _run_speed_variant(tmp_path, "a_1x", speed_mult=1.0)
            )
            fast = asyncio.run(
                _run_speed_variant(tmp_path, "b_2x_shipped", speed_mult=2.0)
            )
        finally:
            blackhole.PHASE_BURST_SPEED_MULT = orig_mult

    print("Variant     burst_t   settle_t_after_burst   settle_radius   post-burst gap   spawns/3s")
    print(f"1x (was)    {slow['burst_frame_s']:.3f}s   "
          f"{slow['settle_frame_s']:.3f}s               "
          f"{slow['settle_radius']:.4f}         "
          f"{slow['gap_s']:.3f}s          {slow['spawns_after_burst_3s']}")
    print(f"2x (shipped) {fast['burst_frame_s']:.3f}s   "
          f"{fast['settle_frame_s']:.3f}s               "
          f"{fast['settle_radius']:.4f}         "
          f"{fast['gap_s']:.3f}s          {fast['spawns_after_burst_3s']}")

    ok = True

    # 1. Landing point: the burst fires on the exact same frame either way.
    if abs(slow["burst_frame_s"] - fast["burst_frame_s"]) > 1e-9:
        print(f"\nFAIL: burst landing point moved: {slow['burst_frame_s']:.3f}s "
              f"(1x) vs {fast['burst_frame_s']:.3f}s (2x)")
        ok = False

    # 2. Same reach, half the time: settle radius should match within a
    #    small tolerance (the physics isn't perfectly r-independent of wall
    #    time — audio impulse/wind terms vary — so allow 15%), and the
    #    settle time should roughly halve.
    if slow["settle_radius"] is None or fast["settle_radius"] is None:
        print("\nFAIL: burst never settled (p_out never expired) within the window")
        ok = False
    else:
        radius_ratio = fast["settle_radius"] / slow["settle_radius"]
        if not (0.85 <= radius_ratio <= 1.15):
            print(f"\nFAIL: settle radius diverged: 1x={slow['settle_radius']:.4f} "
                  f"2x={fast['settle_radius']:.4f} (ratio {radius_ratio:.3f}, "
                  "expected ~1.0 — same reach)")
            ok = False
        time_ratio = fast["settle_frame_s"] / slow["settle_frame_s"]
        if not (0.4 <= time_ratio <= 0.6):
            print(f"\nFAIL: settle time did not halve: 1x={slow['settle_frame_s']:.3f}s "
                  f"2x={fast['settle_frame_s']:.3f}s (ratio {time_ratio:.3f}, expected ~0.5)")
            ok = False

    # 3. PR #149's ambient-spawn decoupling still holds under the faster path.
    if fast["gap_s"] is None:
        print("\nFAIL: 2x variant never spawns an ambient/beat blob within 3s of the burst")
        ok = False
    elif fast["gap_s"] > 1.0:
        print(f"\nFAIL: 2x variant post-burst gap {fast['gap_s']:.3f}s regressed "
              "past the natural spawn cadence — the faster burst is starving "
              "ambient spawn")
        ok = False

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
