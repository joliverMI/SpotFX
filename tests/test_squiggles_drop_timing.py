"""Headless proof for Squiggles' drop-burst timing (fx/effects/
squiggles.py).

History (so this isn't read as flip-flopping): his ORIGINAL report was
"the drop on squiggles is not timed correct... squiggles needs to explode
right on the trigger" — at the time, Black Hole's own progress-gated burst
was his confirmed-good reference, so PR fm/spectra-squiggles-drop-timing-
and-a-much-bigger-explosion made Squiggles mirror that end-anchored gate.
Black Hole was LATER tried and withdrawn as a drop-timing reference (data/
drops-still-fire-early-star-does-not-explode/ — "actually, i think black
hole might be too early, also"), and he settled a three-anchor rule
instead: drops/explosions anchor their START to the mark, not their end.
This module now proves THAT — the burst fires on the phase's first
rendered frame, unconditionally, matching orbits.py's own drop branch
(which never had the gate) and fx/effects/blackhole.py's own matching
fix. His other two asks from the original PR — burst count, and burst
speed/lingering — are untouched by any of this; still proven below.

Full before/after numbers (ramped + stalled-ramp variants) live in
scripts/check_squiggles_drop_timing.py, which this module imports and
reuses rather than re-deriving — see that script's own docstring for the
full history."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx.effects import squiggles

import scripts.check_squiggles_drop_timing as check


def _run(tmp_path, sub, **kwargs):
    return asyncio.run(check._run_variant(tmp_path, sub, **kwargs))


def test_burst_does_not_fire_synchronously_on_the_config_write(tmp_path):
    """Regression guard for the ORIGINAL, still-real defect: the burst
    must never fire as a side effect of writing config (before a single
    drop-phase frame has rendered) — it belongs inside the normal
    per-frame _phase_step cadence, real dt and real _phase_t bookkeeping
    included."""
    result = _run(tmp_path, "edge_check", ramp=True)
    assert not result["burst_before_first_frame"], (
        "the burst fired synchronously on the config write itself, before "
        "any frame rendered"
    )


def test_burst_lands_on_drop_entry_not_the_ramp_end(tmp_path):
    """The burst should land within one rendered frame of drop entry — his
    settled rule (drops anchor their START to the mark), proven here
    against the actual production code, not the end-anchored gate this
    same test used to require."""
    result = _run(tmp_path, "ramp_check", ramp=True, ramp_s=0.3)
    assert result["burst_delay_s"] < 2 * check.DT + 1e-9


def test_stalled_ramp_does_not_change_when_the_burst_fires(tmp_path):
    """A dropped/lost phase_progress ramp (stays at 0.0) used to matter —
    Blackhole's own DROP_FALLBACK_S wall-clock fallback existed exactly
    because the old end-anchored gate needed one. Now the burst never
    waits on phase_progress at all, so a stalled ramp can't delay it
    either: proven directly here, not merely inferred from the ramped
    case."""
    result = _run(tmp_path, "stall_check", ramp=False)
    assert result["burst_delay_s"] < 2 * check.DT + 1e-9


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
