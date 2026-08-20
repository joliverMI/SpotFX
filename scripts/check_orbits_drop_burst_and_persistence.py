#!/usr/bin/env python3
"""Regression check for the Orbits drop-ejecta persistence retune
(fx/effects/orbits.py, PR fm/spectra-orbits-ejecta-three-seconds).

His ask, in full: "3 seconds" — up from the 1.4-1.6s the ballistic drop
ejecta previously cleared the panel in (see
data/spectra-orbits-blob-persistence/report.md + HIS-DECISION.md). The
burst COUNT (3x the configured population, DROP_EJECTA_X=2) is explicitly
NOT to be touched — it already matches his stated number and his real
pre-rebuild data. This script only measures ejecta lifetime and burst
count. Structural precedent:
scripts/check_blackhole_explosion_and_gap.py (PR #149).

Method: drive the real charge->lull->drop state machine (Effect.
update_config, the same call shape scene_response.py's `_drive_phase`
uses) on a headless 72x37 dummy virtual (his real crystal-mapper shape),
using his live scene's radius_scale=1.8 / horizon_scale=0.19
(data/spectra-orbits-blob-persistence/report.md). `_spawn_drop_ejecta` is
wrapped to tag each newly spawned ejecta particle's `p_grad_from` slot
with a unique sentinel (untouched by that function otherwise — it's left
NaN), so ejecta survival can be tracked frame-by-frame across
`_compact()` slot reshuffles without relying on any other machinery. The
"ejecta life" measured per burst is time from spawn until every tagged
particle in that burst has retired — the same "track until every one is
gone" method the original 1.4-1.6s figure used.

particle_count is tested across his real scene's intensity binding range
(imap(1, 8, 3), report.md) — count feeds the *number* of ejecta
(DROP_EJECTA_X * particle_count), and "time until the last one is gone"
is an order statistic over that count, so a higher particle_count
mechanically produces a longer worst-case straggler even at an unchanged
per-particle speed distribution. Every run is repeated over several RNG
seeds and averaged for this reason — a single run is noisy (order-stat
tail), the mean is not. The fallback particle_count=3 (his scene's actual
resting value, imap's own `fallback=3.0`) is weighted as the primary
target since it's what fires when no live intensity context is available;
the full 1-8 range is reported for honesty about the spread, not asserted
to individually equal 3.0s.
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
from fx.effects import orbits  # noqa: E402

DT = 1.0 / 60.0
SEEDS = [1, 2, 3, 4, 5, 6, 20260820]
TARGET_S = 3.0
TOLERANCE_S = 0.4  # applied to the fallback(3) mean and the overall mean

# His real crystal-mapper shape (72x37 = 2664 addressable cells).
ROWS = 37
COLS = 72

BASE_CONFIG = {
    "radius_scale": 1.8,      # his real Orbits V2 scene (report.md)
    "horizon_scale": 0.19,    # his real Orbits V2 scene (report.md)
    "blob_size": 2.5,         # midpoint of his 4->1 blob binding
    "phase": "none",
    "phase_progress": 0.0,
}


async def _run_once(tmp_path: Path, sub: str, particle_count: int, seed: int) -> dict:
    host = await headless.start_headless_host(
        str(tmp_path / sub), pixel_count=ROWS * COLS, rows=ROWS, device_id=sub
    )
    virtual = host.virtuals.get(sub)

    with headless.fake_clock() as clock:
        config = dict(BASE_CONFIG, particle_count=particle_count)
        effect = headless.attach_effect(host, virtual, "orbits", config)
        effect._rng = np.random.default_rng(seed)

        orig_spawn_ejecta = effect._spawn_drop_ejecta
        ejecta_spawned = [0]
        sentinel = -999.0

        def tagged_spawn_ejecta(count, _orig=orig_spawn_ejecta):
            before = effect.n
            _orig(count)
            added = effect.n - before
            if added > 0:
                effect.p_grad_from[before:effect.n] = sentinel
                ejecta_spawned[0] += added

        effect._spawn_drop_ejecta = tagged_spawn_ejecta

        def step(n_frames: int):
            for _ in range(n_frames):
                clock.advance(DT)
                frame = virtual.assemble_frame()
                if frame is not None:
                    virtual.flush(frame)

        # CHARGE: ramp phase_progress 0->1 over 1.2s (grows to CHARGE_PEAK_N)
        effect.update_config({"phase": "charge", "phase_progress": 0.0})
        charge_frames = int(1.2 / DT)
        for i in range(1, charge_frames + 1):
            effect.update_config({"phase_progress": i / charge_frames})
            step(1)

        # LULL: ramp phase_progress 0->1 over 1.0s (sheds to 1 blob)
        effect.update_config({"phase": "lull", "phase_progress": 0.0})
        lull_frames = int(1.0 / DT)
        for i in range(1, lull_frames + 1):
            effect.update_config({"phase_progress": i / lull_frames})
            step(1)

        # DROP: first frame at progress=0 triggers the burst.
        effect.update_config({"phase": "drop", "phase_progress": 0.0})
        step(1)

        alive = int(np.count_nonzero(effect.p_grad_from[: effect.n] == sentinel))
        assert alive == ejecta_spawned[0], (
            f"{sub}: tag mismatch immediately after burst "
            f"(spawned {ejecta_spawned[0]}, tagged-alive {alive})"
        )

        # Track ejecta survival until every tagged particle is retired, or
        # a generous timeout (should never trigger post-retune).
        max_frames = int(8.0 / DT)
        life_frames = None
        for f in range(1, max_frames + 1):
            step(1)
            alive = int(np.count_nonzero(effect.p_grad_from[: effect.n] == sentinel))
            if alive == 0:
                life_frames = f
                break

    await host.shutdown()

    life_s = life_frames * DT if life_frames is not None else None
    return {
        "burst_count": ejecta_spawned[0],
        "expected_burst_count": orbits.DROP_EJECTA_X * particle_count,
        "ejecta_life_s": life_s,
    }


def main() -> int:
    variants = [
        ("fallback(3)", 3),
        ("low(1)", 1),
        ("mid(5)", 5),
        ("high(8)", 8),
    ]

    print(f"DROP_EJECTA_SPEED={orbits.DROP_EJECTA_SPEED}  "
          f"DROP_SETTLE_S={orbits.DROP_SETTLE_S}\n")
    print(f"label            particle_count  burst_count  expected  "
          f"mean_life_s (n={len(SEEDS)} seeds)  min   max")

    ok = True
    variant_means = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for label, particle_count in variants:
            lives = []
            burst_ok = True
            for seed in SEEDS:
                r = asyncio.run(
                    _run_once(tmp_path, f"orbits_{label}_{seed}", particle_count, seed)
                )
                if r["burst_count"] != r["expected_burst_count"]:
                    print(f"\nFAIL: {label} seed={seed} burst count "
                          f"{r['burst_count']} != expected "
                          f"{r['expected_burst_count']} (3x population — "
                          f"DROP_EJECTA_X must stay untouched)")
                    ok = False
                    burst_ok = False
                if r["ejecta_life_s"] is None:
                    print(f"\nFAIL: {label} seed={seed} ejecta never fully "
                          f"retired within 8s")
                    ok = False
                else:
                    lives.append(r["ejecta_life_s"])

            arr = np.array(lives) if lives else np.array([np.nan])
            mean_life = float(arr.mean())
            variant_means[label] = mean_life
            print(f"{label:<16} {particle_count:<15} "
                  f"{'ok' if burst_ok else 'FAIL':<12} "
                  f"{'-':<9} {mean_life:<24.3f} {arr.min():<5.3f} {arr.max():.3f}")

    fallback_mean = variant_means["fallback(3)"]
    overall_mean = float(np.mean(list(variant_means.values())))
    print(f"\nfallback(3) mean life: {fallback_mean:.3f}s "
          f"(target {TARGET_S}s +/- {TOLERANCE_S}s)")
    print(f"overall mean-of-variant-means: {overall_mean:.3f}s "
          f"(target {TARGET_S}s +/- {TOLERANCE_S}s)")

    if abs(fallback_mean - TARGET_S) > TOLERANCE_S:
        print(f"\nFAIL: fallback(3) mean life {fallback_mean:.3f}s is more "
              f"than {TOLERANCE_S}s from the {TARGET_S}s target")
        ok = False
    if abs(overall_mean - TARGET_S) > TOLERANCE_S:
        print(f"\nFAIL: overall mean life {overall_mean:.3f}s is more than "
              f"{TOLERANCE_S}s from the {TARGET_S}s target")
        ok = False

    # Sanity: every variant must be a real improvement over the previous
    # 1.4-1.6s baseline, not just the target metrics above.
    for label, mean_life in variant_means.items():
        if mean_life < 2.0:
            print(f"\nFAIL: {label} mean life {mean_life:.3f}s is not a "
                  f"meaningful improvement over the 1.4-1.6s baseline")
            ok = False

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
