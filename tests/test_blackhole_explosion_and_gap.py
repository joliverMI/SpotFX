"""Headless proof for the Black Hole drop-burst count + post-burst
ambient-spawn gap fix (fx/effects/blackhole.py, PR
fm/spectra-blackhole-explosion-and-gap).

His two asks fought under the pre-fix logic (scout report
data/charge-lull-drop-timing-blends-and-a-sus-7fm2/report.md §5.1):
PHASE_BURST_N=24 already bypassed max_blobs on the drop payoff, but the
ordinary ambient/beat spawn in `_spawn` was gated on TOTAL live population
(`max_blobs - self.n`) — so doubling the burst to satisfy his count ask
would have made his gap complaint *worse*, not better. The fix tags burst
particles (`p_is_burst`) and has `_spawn`'s cap check count only ambient
(non-burst) population.

Full before/after numbers (four variants: old-cap/burst=24, old-cap/
burst=48, fixed/burst=48, uncapped control) live in
scripts/check_blackhole_explosion_and_gap.py, which this module imports
and reuses rather than re-deriving — see its own docstring for the
driving methodology (real Effect.update_config charge->lull->drop calls
on a headless dummy host, instrumented `_spawn`/`_phase_burst` counts)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx.effects import blackhole
from fx.effects.blackhole import Blackhole2d

import scripts.check_blackhole_explosion_and_gap as check


def _run(tmp_path, sub, effect_cls, **kwargs):
    return asyncio.run(check._run_variant(tmp_path, sub, effect_cls, **kwargs))


def test_phase_burst_n_is_at_least_2x_his_original_24():
    assert blackhole.PHASE_BURST_N >= 2 * check.OLD_PHASE_BURST_N
    assert blackhole.PHASE_BURST_N == 48, "his own number, not an approximation"


def test_fixed_ambient_spawn_survives_the_doubled_burst(tmp_path):
    """The actual shipped code: burst=48 (his count ask), and the ambient
    trickle still lands shortly after — no starvation gap."""
    result = _run(tmp_path, "fixed", Blackhole2d)
    assert result["burst_count"] == 48
    assert result["gap_s"] is not None, (
        "no ambient/beat blob spawned within 3s of the drop burst — "
        "the post-explosion gap his second ask named is still present"
    )
    assert result["gap_s"] < 1.0, (
        f"post-burst gap {result['gap_s']:.3f}s is far longer than the "
        "natural spawn cadence — burst is still starving ambient spawn"
    )
    assert result["spawns_after_burst_3s"] > 0


def test_fixed_gap_matches_the_uncapped_control_not_the_starved_one(tmp_path):
    """The fix's gap should track the population-agnostic natural spawn
    cadence (control, max_blobs effectively uncapped), not be some smaller
    -but-still-present starvation artifact."""
    fixed = _run(tmp_path, "fixed2", Blackhole2d)
    control = _run(tmp_path, "control", Blackhole2d, max_blobs=1024)
    assert fixed["gap_s"] is not None and control["gap_s"] is not None
    assert abs(fixed["gap_s"] - control["gap_s"]) <= check.DT + 1e-9, (
        f"fixed gap {fixed['gap_s']:.3f}s diverges from the uncapped "
        f"control's natural cadence {control['gap_s']:.3f}s by more than "
        "one frame"
    )


def test_naively_doubling_the_burst_under_the_old_cap_makes_the_gap_worse(tmp_path):
    """Regression guard for the exact failure mode the scout report warned
    about: PHASE_BURST_N=48 with the OLD (population-gated, not
    ambient-only) cap formula must be at least as bad as the old
    burst=24 baseline — proving the two asks really did fight before this
    fix decoupled them."""
    orig = blackhole.PHASE_BURST_N
    try:
        blackhole.PHASE_BURST_N = check.OLD_PHASE_BURST_N
        baseline = _run(tmp_path, "old_baseline", check._OldCapBlackhole2d)
    finally:
        blackhole.PHASE_BURST_N = orig

    naive_double = _run(tmp_path, "naive_double", check._OldCapBlackhole2d)

    assert naive_double["burst_count"] == 2 * baseline["burst_count"]
    baseline_gap = baseline["gap_s"] if baseline["gap_s"] is not None else float("inf")
    naive_gap = naive_double["gap_s"] if naive_double["gap_s"] is not None else float("inf")
    assert naive_gap >= baseline_gap, (
        "doubling the burst under the old population-gated cap did not "
        "make the post-explosion gap the same or worse, contradicting the "
        "scout report's finding"
    )
