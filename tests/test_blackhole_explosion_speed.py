"""Headless proof for the Black Hole drop-explosion speed fix
(fx/effects/blackhole.py, PR fm/spectra-blackhole-explosion-twice-as-fast).

His ask, verbatim: "the timing is good on black hole, but the speed of the
explosion after the implosion needs to be 2 times faster." Scoped to just
the post-pinch outward burst (_phase_burst's blobs, tagged p_is_burst) —
not the implosion (the pinch, paced by phase_progress/DROP_FALLBACK_S) and
not the whole drop (the post-burst horizon ease-back, DROP_RESET_S).

Full numbers and methodology live in
scripts/check_blackhole_explosion_speed.py, which this module imports and
reuses rather than re-deriving — see its own docstring."""
from __future__ import annotations

import asyncio

import scripts.check_blackhole_explosion_speed as check
from fx.effects import blackhole


def _run(tmp_path, sub, **kwargs):
    return asyncio.run(check._run_speed_variant(tmp_path, sub, **kwargs))


def test_shipped_speed_multiplier_is_2x():
    assert blackhole.PHASE_BURST_SPEED_MULT == 2.0, "his own number, not an approximation"


def test_burst_still_lands_on_the_same_frame_regardless_of_speed(tmp_path):
    """Changing the explosion's speed must not shift when the drop lands
    on the trigger's timestamp — the burst still fires the instant the
    pinch completes, unrelated to how fast the burst blobs then fly."""
    orig = blackhole.PHASE_BURST_SPEED_MULT
    try:
        slow = _run(tmp_path, "a_1x", speed_mult=1.0)
    finally:
        blackhole.PHASE_BURST_SPEED_MULT = orig
    fast = _run(tmp_path, "b_shipped", speed_mult=blackhole.PHASE_BURST_SPEED_MULT)
    assert slow["burst_frame_s"] == fast["burst_frame_s"]


def test_shipped_explosion_reaches_the_same_extent_in_about_half_the_time(tmp_path):
    """Twice as fast, not twice as far: doubling velocity while halving the
    p_out flight duration should cover the same outward distance the old
    (1x) burst did, just in about half the wall-clock time — a bigger
    explosion (same time, more distance) is a different change and not
    what was asked."""
    orig = blackhole.PHASE_BURST_SPEED_MULT
    try:
        slow = _run(tmp_path, "c_1x", speed_mult=1.0)
    finally:
        blackhole.PHASE_BURST_SPEED_MULT = orig
    fast = _run(tmp_path, "d_shipped", speed_mult=blackhole.PHASE_BURST_SPEED_MULT)

    assert slow["settle_radius"] is not None and fast["settle_radius"] is not None
    radius_ratio = fast["settle_radius"] / slow["settle_radius"]
    assert 0.85 <= radius_ratio <= 1.15, (
        f"settle radius diverged too far: 1x={slow['settle_radius']:.4f} "
        f"shipped={fast['settle_radius']:.4f} (ratio {radius_ratio:.3f})"
    )
    time_ratio = fast["settle_frame_s"] / slow["settle_frame_s"]
    assert 0.4 <= time_ratio <= 0.6, (
        f"settle time did not halve: 1x={slow['settle_frame_s']:.3f}s "
        f"shipped={fast['settle_frame_s']:.3f}s (ratio {time_ratio:.3f})"
    )


def test_ambient_spawn_decoupling_survives_the_faster_burst(tmp_path):
    """PR #149 decoupled the ambient spawn's max_blobs check from the
    burst's own population so a bigger burst can't starve it — verify that
    decoupling still holds now that the burst is also faster (bigger +
    faster together stress the same logic)."""
    result = _run(tmp_path, "e_shipped_gap", speed_mult=blackhole.PHASE_BURST_SPEED_MULT)
    assert result["gap_s"] is not None, (
        "no ambient/beat blob spawned within 3s of the drop burst under the "
        "shipped (2x) speed — the post-explosion gap PR #149 fixed is back"
    )
    assert result["gap_s"] < 1.0
    assert result["spawns_after_burst_3s"] > 0
