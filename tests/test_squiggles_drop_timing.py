"""Headless proof for the Squiggles drop-timing fix (fx/effects/squiggles.py,
PR fm/spectra-squiggles-drop-timing-and-a-much-bigger-explosion).

His report, verbatim: "the drop on squiggles is not timed correct. The new
black hole timing is really good. Squiggles needs to explode right on the
trigger, and the explosion needs to be way bigger and last longer."

Black Hole's own drop payoff waits for `phase_progress` to reach ~1.0
(with a wall-clock fallback) before bursting — his confirmed-good
reference. Squiggles used to burst the instant `phase` edged to "drop",
before scene_response._drive_phase's ramp had played any of the way
through — up to a full ramp EARLY relative to Black Hole on the identical
trigger. This fix gates the burst on phase_progress the same way, and
gives burst chains a fixed, slower travel speed so the explosion lingers
("last longer") instead of flashing past.

Full before/after numbers (ramped + stalled-ramp variants) live in
scripts/check_squiggles_drop_timing.py, which this module imports and
reuses rather than re-deriving."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx.effects import squiggles

import scripts.check_squiggles_drop_timing as check


def _run(tmp_path, sub, **kwargs):
    return asyncio.run(check._run_variant(tmp_path, sub, **kwargs))


def test_burst_does_not_fire_the_instant_phase_edges_to_drop(tmp_path):
    """Regression guard for the exact defect he reported: the old code
    called _phase_burst() synchronously inside _enter_phase, so it always
    showed up in the burst log before a single drop-phase frame had
    rendered."""
    result = _run(tmp_path, "edge_check", ramp=True)
    assert not result["immediate_burst_at_edge"], (
        "the burst fired at the instant phase edged to drop (progress=0.0) "
        "-- it must wait for the ramp, matching Blackhole's own gate"
    )


def test_burst_lands_at_ramp_completion_like_blackhole(tmp_path):
    """The burst should land within a frame of the drop ramp completing,
    not near t=0 -- proving the fix actually re-anchors to the ramp's end
    rather than just adding an arbitrary delay."""
    result = _run(tmp_path, "ramp_check", ramp=True, ramp_s=0.3)
    assert result["burst_delay_s"] > 0.2
    assert abs(result["burst_delay_s"] - 0.3) < 2 * check.DT + 1e-9


def test_stalled_ramp_still_lands_the_burst_via_wall_clock_fallback(tmp_path):
    """A dropped/lost phase_progress ramp (stays at 0.0) must not lose the
    payoff forever -- DROP_FALLBACK_S is the same safety net Blackhole
    uses for exactly this failure mode."""
    result = _run(tmp_path, "stall_check", ramp=False)
    assert abs(result["burst_delay_s"] - squiggles.DROP_FALLBACK_S) < 2 * check.DT + 1e-9


def test_burst_chains_carry_the_slower_linger_speed(tmp_path):
    """His ask "last longer": burst chains travel at DROP_BURST_SPEED_MULT
    of base_speed, a fixed override (not audio-scaled) so the fan lingers
    predictably instead of flashing past."""
    result = _run(tmp_path, "speed_check", ramp=True)
    expected = check.BASE_CONFIG["base_speed"] * squiggles.DROP_BURST_SPEED_MULT
    assert result["burst_speed_override"] is not None
    assert abs(result["burst_speed_override"] - expected) < 1e-6
    assert squiggles.DROP_BURST_SPEED_MULT < 1.0, (
        "the multiplier must actually slow the burst down, not speed it up"
    )
