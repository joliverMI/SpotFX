#!/usr/bin/env python3
"""Read-only evidence script — per-effect VISIBLE ONSET of a drop, not the
write landing.

His report, verbatim: "I still think the timing on Orbitz and maybe all of
the drops is too early the explosion should start on the trigger you
should be able to test for that and make sure that that works." Firstmate's
own framing of the remaining gap (data/drops-still-fire-early-star-does-
not-explode/, 2026-08-20): "He is not watching the write. He is watching
the explosion... measure when the VISIBLE EXPLOSION BEGINS, against the
trigger mark, per effect. That is a different instrument from counting
fires."

trigger_engine._response_switch_lead_ms proves the WRITE for a drop lands
with ZERO lead on every one of his four real scenes (scripts/
check_triggers.py's own drop-anchor checks) — the phase=drop write is
never early. fx/effects/{blackhole,blackhole1d,squiggles}.py used to gate
their drop PAYOFF (the burst) on phase_progress reaching ~1.0 — anchoring
it to the RAMP'S END, up to 400ms after the write, not its start; that gate
is now removed (the burst fires unconditionally on the phase's first frame,
matching orbits.py's own drop branch, which never had the gate). This
script proves that fix landed, and separately measures radial.py's own
bloom reveal (STAR) — a continuous smoothstep curve, not a discrete burst
call, so it needs a different instrument: the fraction of the pattern
actually revealed (`_phase_warp`'s own returned `e`), read directly off the
production method, not re-derived.

"Visible" is defined as crossing VISIBLE_FRACTION (5%) of the effect's own
full payoff — a guaranteed burst (blackhole/orbits/squiggles) crosses it on
frame 0 by construction; radial's continuous reveal crosses it wherever the
smoothstep curve actually gets there, which this script measures rather
than assumes.

Every number is read off the real engine (a real Effect.update_config
charge->lull->drop sequence on a headless dummy host, the same call shape
scene_response.py's _drive_phase uses) via an instrumented hook on the
production method itself (_phase_burst / _spawn_drop_ejecta / _phase_warp)
— never a re-derivation of the choreography math.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fx import headless  # noqa: E402

DT = 1.0 / 60.0
VISIBLE_FRACTION = 0.05  # 5% of the payoff counts as "visibly begun"

# real drop ramp duration scene_response._drive_phase drives for every
# phase-capable effect (PHASE_RAMP_MS["drop"], spectra/services/
# scene_response.py) — the ramp this script replays.
DROP_RAMP_S = 0.4


async def _drive_charge_lull_drop(effect, step, *, charge_s=1.2, lull_s=1.0,
                                  drop_ramp_s=DROP_RAMP_S):
    """The production sequence (scene_response._drive_phase, replayed the
    same way scripts/check_squiggles_drop_timing.py and scripts/
    check_blackhole_explosion_and_gap.py already do): charge ramps, lull
    holds, drop arms at progress=0.0 then glides to 1.0. Returns the frame
    index at which "drop" was entered (frame 0 of the drop phase, i.e. the
    trigger mark under the zero-lead rule proven in
    scripts/check_triggers.py)."""
    effect.update_config({"phase": "charge", "phase_progress": 0.0})
    charge_frames = int(charge_s / DT)
    for i in range(1, charge_frames + 1):
        effect.update_config({"phase_progress": i / charge_frames})
        step(1)

    effect.update_config({"phase": "lull", "phase_progress": 0.0})
    step(int(lull_s / DT))

    drop_entry_frame = step.frame_idx[0]
    effect.update_config({"phase": "drop", "phase_progress": 0.0})
    drop_frames = int(drop_ramp_s / DT)
    for i in range(1, drop_frames + 1):
        effect.update_config({"phase_progress": i / drop_frames})
        step(1)
    step(int(0.5 / DT))  # let the post-burst settle play out too
    return drop_entry_frame


def _stepper(virtual, clock):
    frame_idx = [0]

    def step(n_frames: int):
        for _ in range(n_frames):
            clock.advance(DT)
            frame = virtual.assemble_frame()
            if frame is not None:
                virtual.flush(frame)
            frame_idx[0] += 1

    step.frame_idx = frame_idx
    return step


async def _burst_onset(tmp_path, sub, effect_type, config, burst_attr):
    """Blackhole/Orbits/Squiggles: the burst is a discrete, guaranteed
    event — onset is exactly the frame it fires, relative to drop entry.
    Hooks the real method (burst_attr) rather than inferring firing from
    population counts, so a genuine regression in WHEN it fires can't be
    masked by some other population change."""
    host = await headless.start_headless_host(str(tmp_path / sub), device_id=sub)
    virtual = host.virtuals.get(sub)
    fire_log = []
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(host, virtual, effect_type, config)
        step = _stepper(virtual, clock)
        orig = getattr(effect, burst_attr)

        def logged(*a, _orig=orig, **kw):
            fire_log.append(step.frame_idx[0])
            return _orig(*a, **kw)

        setattr(effect, burst_attr, logged)
        drop_entry_frame = await _drive_charge_lull_drop(effect, step)
    await host.shutdown()
    assert fire_log, f"{sub}: drop burst never fired"
    onset_s = (fire_log[0] - drop_entry_frame) * DT
    return {"onset_s": onset_s}


async def _radial_bloom_onset(tmp_path):
    """STAR/radial: no discrete burst — a continuous smoothstep reveal
    (_phase_warp's own `e`). Reads the REAL method's return value every
    frame (no re-derivation of the smoothstep math) and reports the first
    frame `e` crosses VISIBLE_FRACTION, relative to drop entry. A
    source_virtual isn't attached (this effect renders onto a hex Matrix
    panel via a paired 1D source in production) — draw() computes
    _phase_step/_phase_warp unconditionally before ever touching
    source_virtual, so the reveal curve itself is provably unaffected by
    skipping that pairing here; see fx/effects/radial.py's draw()."""
    host = await headless.start_headless_host(str(tmp_path / "radial-onset"),
                                               device_id="radial-onset")
    virtual = host.virtuals.get("radial-onset")
    e_log = []
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(host, virtual, "radial",
                                        {"edges": 6, "polygon": True})
        step = _stepper(virtual, clock)
        orig_warp = effect._phase_warp

        def logged_warp(_orig=orig_warp):
            result = _orig()
            if result is not None:
                _warp, e = result
                e_log.append((step.frame_idx[0], e))
            return result

        effect._phase_warp = logged_warp
        drop_entry_frame = await _drive_charge_lull_drop(effect, step)
    await host.shutdown()
    drop_log = [(f, e) for f, e in e_log if f >= drop_entry_frame]
    assert drop_log, "radial: _phase_warp never ran during the drop phase"
    peak = max(e for _, e in drop_log)
    crossing = next((f for f, e in drop_log if e >= VISIBLE_FRACTION), None)
    onset_s = (crossing - drop_entry_frame) * DT if crossing is not None else None
    return {"onset_s": onset_s, "peak_e": peak,
           "e_at_entry": drop_log[0][1], "e_at_ramp_end": drop_log[
               min(int(DROP_RAMP_S / DT), len(drop_log) - 1)][1]}


def check(cond, msg):
    if not cond:
        print(f"FAIL: {msg}")
        raise SystemExit(1)
    print(f"OK: {msg}")


async def _main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        blackhole = await _burst_onset(
            tmp_path, "blackhole-onset", "blackhole",
            {"reverse": False, "horizon_scale": 0.25, "spawn_rate": 4.0,
             "beat_burst": 4, "max_blobs": 50}, "_phase_burst")
        orbits = await _burst_onset(
            tmp_path, "orbits-onset", "orbits",
            {"particle_count": 6}, "_spawn_drop_ejecta")
        squiggles = await _burst_onset(
            tmp_path, "squiggles-onset", "squiggles",
            {"spawn_rate": 2.0, "beat_burst": 1, "max_blobs": 14,
             "base_speed": 38.0}, "_phase_burst")
        radial = await _radial_bloom_onset(tmp_path)

    print(f"{'effect':<12} {'onset (visible change begins)':<32} {'notes'}")
    print(f"{'blackhole':<12} {blackhole['onset_s']*1000:>6.1f} ms after drop entry")
    print(f"{'orbits':<12} {orbits['onset_s']*1000:>6.1f} ms after drop entry")
    print(f"{'squiggles':<12} {squiggles['onset_s']*1000:>6.1f} ms after drop entry")
    if radial["onset_s"] is not None:
        print(f"{'radial/STAR':<12} {radial['onset_s']*1000:>6.1f} ms after drop entry"
              f"  (reveal e: {radial['e_at_entry']:.4f} at entry, "
              f"{radial['e_at_ramp_end']:.4f} at ramp end, peak {radial['peak_e']:.4f})")
    else:
        print(f"{'radial/STAR':<12} NEVER crosses {VISIBLE_FRACTION*100:.0f}% "
              f"reveal (peak e={radial['peak_e']:.4f})")
    print()

    check(blackhole["onset_s"] < 2 * DT + 1e-9,
          "Black Hole's burst lands within one frame of the drop's own "
          "entry — the payoff no longer waits for the pinch to complete")
    check(orbits["onset_s"] < 2 * DT + 1e-9,
          "Orbits' burst lands within one frame of drop entry — unchanged, "
          "this effect's own drop branch was never gated on progress")
    check(squiggles["onset_s"] < 2 * DT + 1e-9,
          "Squiggles' burst lands within one frame of drop entry — the "
          "PR fm/spectra-squiggles-drop-timing-and-a-much-bigger-explosion "
          "end-anchor gate that used to delay this to ~ramp-end is gone")
    if radial["onset_s"] is not None:
        print(f"NOTE: radial/STAR's own bloom crosses {VISIBLE_FRACTION*100:.0f}% "
              f"reveal at {radial['onset_s']*1000:.1f}ms — this is a "
              "CONTINUOUS reveal curve, not a discrete burst; whether that "
              "reads as \"begins on the mark\" to the eye is a live-room "
              "question this offline instrument can name a number for but "
              "can't answer by itself. Not asserted pass/fail here — see "
              "the script's own docstring and AGENTS.md's onset-"
              "investigation note for what's still open.")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(_main())
