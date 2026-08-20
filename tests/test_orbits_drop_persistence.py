"""Headless proof for the Orbits drop-ejecta persistence retune
(fx/effects/orbits.py, PR fm/spectra-orbits-ejecta-three-seconds).

His ask, verbatim: "3 seconds" — up from the 1.4-1.6s the ballistic drop
ejecta previously cleared the panel in (data/spectra-orbits-blob-
persistence/report.md + HIS-DECISION.md). The burst count (3x the
configured population) was explicitly not to be touched.

Full multi-seed measurements (four particle_count variants across his
scene's real 1-8 intensity binding range) live in
scripts/check_orbits_drop_burst_and_persistence.py, which this module
imports and reuses rather than re-deriving — see its own docstring for
the driving methodology (real Effect.update_config charge->lull->drop
calls on a headless dummy host, `_spawn_drop_ejecta` instrumented via a
p_grad_from sentinel tag)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx.effects import orbits

import scripts.check_orbits_drop_burst_and_persistence as check


def _run(tmp_path, sub, particle_count, seed):
    return asyncio.run(check._run_once(tmp_path, sub, particle_count, seed))


def test_ejecta_count_is_still_exactly_3x_population():
    """DROP_EJECTA_X (the 3x burst) was explicitly not to be touched by
    this retune — only speed/settle pacing."""
    assert orbits.DROP_EJECTA_X == 2, "3x total spawn = 1 kept + 2 ejecta per blob"


def test_fallback_particle_count_ejecta_life_lands_near_3s(tmp_path):
    """His scene's actual resting config (particle_count=3, imap's own
    fallback) is the primary target: mean ejecta life across seeds should
    land within 0.4s of his stated 3.0s."""
    results = [_run(tmp_path, f"fb_{seed}", 3, seed) for seed in check.SEEDS]
    for r in results:
        assert r["burst_count"] == r["expected_burst_count"] == 6
        assert r["ejecta_life_s"] is not None
    mean_life = float(np.mean([r["ejecta_life_s"] for r in results]))
    assert abs(mean_life - check.TARGET_S) <= check.TOLERANCE_S, (
        f"fallback(3) mean ejecta life {mean_life:.3f}s is more than "
        f"{check.TOLERANCE_S}s from the {check.TARGET_S}s target"
    )


def test_every_intensity_variant_clears_far_slower_than_the_old_baseline(tmp_path):
    """Across his scene's full 1-8 particle_count binding range, every
    variant's ejecta must meaningfully outlast the old ~1.4-1.6s baseline
    (order-statistic spread across particle counts is real and expected —
    see the check script's own docstring — but none should regress toward
    the old pace)."""
    for particle_count in (1, 3, 5, 8):
        lives = []
        for seed in check.SEEDS:
            r = _run(tmp_path, f"var_{particle_count}_{seed}", particle_count, seed)
            assert r["burst_count"] == r["expected_burst_count"]
            assert r["ejecta_life_s"] is not None
            lives.append(r["ejecta_life_s"])
        mean_life = float(np.mean(lives))
        assert mean_life >= 2.0, (
            f"particle_count={particle_count} mean ejecta life {mean_life:.3f}s "
            "is not a meaningful improvement over the 1.4-1.6s baseline"
        )
