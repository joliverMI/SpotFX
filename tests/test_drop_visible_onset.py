"""Headless proof — the drop-anchor fix (fx/effects/{blackhole,blackhole1d,
squiggles}.py) actually moves the VISIBLE onset, not just a write.

data/drops-still-fire-early-star-does-not-explode/: his settled rule is
that a drop/explosion anchors its START to the trigger mark. trigger_engine
proves the WRITE already lands with zero lead (scripts/check_triggers.py);
this module proves the separate, downstream question — when each effect's
own choreography makes the change actually VISIBLE — using the same
instrumented-hook methodology scripts/check_drop_visible_onset.py
documents in full. See that script's own docstring before extending this
file: it explains why a burst effect and radial's continuous reveal need
different instruments, and what's still open (radial's own onset number is
reported, not asserted pass/fail, on purpose)."""
from __future__ import annotations

import asyncio

import scripts.check_drop_visible_onset as check


def _run(coro):
    return asyncio.run(coro)


def test_blackhole_burst_lands_on_drop_entry_not_the_ramp_end(tmp_path):
    result = _run(check._burst_onset(
        tmp_path, "blackhole-onset", "blackhole",
        {"reverse": False, "horizon_scale": 0.25, "spawn_rate": 4.0,
         "beat_burst": 4, "max_blobs": 50}, "_phase_burst"))
    assert result["onset_s"] < 2 * check.DT + 1e-9, (
        "Black Hole's burst must fire within one frame of drop entry — "
        "the old progress-gated (~ramp-end) anchor must not come back"
    )


def test_orbits_burst_lands_on_drop_entry(tmp_path):
    """Orbits never had the end-anchored gate — this is a same-shape
    regression guard, not a fix proof."""
    result = _run(check._burst_onset(
        tmp_path, "orbits-onset", "orbits",
        {"particle_count": 6}, "_spawn_drop_ejecta"))
    assert result["onset_s"] < 2 * check.DT + 1e-9


def test_squiggles_burst_lands_on_drop_entry_not_the_ramp_end(tmp_path):
    result = _run(check._burst_onset(
        tmp_path, "squiggles-onset", "squiggles",
        {"spawn_rate": 2.0, "beat_burst": 1, "max_blobs": 14,
         "base_speed": 38.0}, "_phase_burst"))
    assert result["onset_s"] < 2 * check.DT + 1e-9, (
        "Squiggles' burst must fire within one frame of drop entry — the "
        "PR fm/spectra-squiggles-drop-timing-and-a-much-bigger-explosion "
        "end-anchor gate must not come back"
    )


def test_stalled_ramp_does_not_change_when_any_burst_effect_fires(tmp_path):
    """A dropped/lost phase_progress ramp used to matter (Blackhole's own
    DROP_FALLBACK_S wall-clock fallback existed exactly because the old
    gate needed one). Post-fix, none of the three burst effects wait on
    phase_progress at all, so a stalled ramp can't change their timing —
    proven directly, not inferred from the ramped case alone."""
    async def _stalled(sub, effect_type, config, burst_attr):
        from fx import headless
        host = await headless.start_headless_host(str(tmp_path / sub), device_id=sub)
        virtual = host.virtuals.get(sub)
        fire_log = []
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(host, virtual, effect_type, config)
            step = check._stepper(virtual, clock)
            orig = getattr(effect, burst_attr)

            def logged(*a, _orig=orig, **kw):
                fire_log.append(step.frame_idx[0])
                return _orig(*a, **kw)

            setattr(effect, burst_attr, logged)
            effect.update_config({"phase": "charge", "phase_progress": 0.0})
            step(int(1.2 / check.DT))
            effect.update_config({"phase": "lull", "phase_progress": 0.0})
            step(int(1.0 / check.DT))
            drop_entry_frame = step.frame_idx[0]
            # phase_progress NEVER moves off 0.0 — a stalled/lost ramp
            effect.update_config({"phase": "drop", "phase_progress": 0.0})
            step(int(1.0 / check.DT))
        await host.shutdown()
        assert fire_log, f"{sub}: drop burst never fired under a stalled ramp"
        return (fire_log[0] - drop_entry_frame) * check.DT

    blackhole_onset = _run(_stalled(
        "blackhole-stalled", "blackhole",
        {"reverse": False, "horizon_scale": 0.25, "spawn_rate": 4.0,
         "beat_burst": 4, "max_blobs": 50}, "_phase_burst"))
    squiggles_onset = _run(_stalled(
        "squiggles-stalled", "squiggles",
        {"spawn_rate": 2.0, "beat_burst": 1, "max_blobs": 14,
         "base_speed": 38.0}, "_phase_burst"))
    orbits_onset = _run(_stalled(
        "orbits-stalled", "orbits", {"particle_count": 6}, "_spawn_drop_ejecta"))

    for name, onset in (("blackhole", blackhole_onset),
                        ("squiggles", squiggles_onset),
                        ("orbits", orbits_onset)):
        assert onset < 2 * check.DT + 1e-9, (
            f"{name}: a stalled ramp must not delay the burst — it never "
            "depended on phase_progress reaching anything"
        )


def test_radial_bloom_reveal_reads_directly_off_the_production_method(tmp_path):
    """Not a pass/fail timing assertion (see the check script's own
    docstring on why) — this proves the INSTRUMENT itself is sound: the
    reveal starts near zero at drop entry, climbs monotonically-ish toward
    the ramp's end, and _phase_warp is the real production method (not a
    stand-in), so a future change to radial's own choreography is measured
    honestly here rather than silently missed."""
    result = _run(check._radial_bloom_onset(tmp_path))
    assert result["e_at_entry"] < 0.05, (
        "the reveal must start near zero at the exact moment drop is "
        "entered — a nonzero starting value would mean phase state leaked "
        "in from a prior phase"
    )
    assert result["peak_e"] > 0.9, (
        "the reveal must reach (near) full strength by the end of the "
        "drop's own ramp+settle window"
    )
