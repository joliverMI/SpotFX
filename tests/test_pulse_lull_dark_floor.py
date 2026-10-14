"""Pulse goes dark at the end of the lull before the drop — even under a
Light Show brightness FLOOR (the Admiral, 2026-10-13: "Make it so that the
pulse effect goes dark at the end of the lull before the drop like it used
to. it's not doing that anymore").

THE CAUSE, measured: none of the suspect timing changes (the breath-hold,
the flare punch, the drop timing offset) — every one of them still took
Pulse to black at the end of the lull. His Light Show had a Pulse
brightness FLOOR held on the Singles ("Singles" floor 0.3, "everything"
0.1, until released), and the floor clamped Pulse's level up in every phase,
so a lull faded to the floor and stayed there: 18/255 at 0.3, never black.
The fix (fx/effects/pulse.py, THE LULL'S DARK BEATS THE FLOOR): in a lull the
floor is scaled by the lull's own darkness — its fade, a flare's punch and
the breath-hold.

Driven on the REAL path: fx.headless render pipeline, the production
ResponseEngine on the FacadeExecutor (tests/strip_phase_harness.py), so each
phase arm carries exactly what _drive_phase writes — the lull's dark-point
keys, the breath-hold keys (the room's 0.4 s), and on a flare the punch
poke — with the lull's gap measured to the drop's SHIFTED moment (his room's
drop_timing_offset_ms, -100) and the drop fired there. The red control puts
the pre-fix floor back and the lull no longer reaches black.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fx import pulse_modulation as pm  # noqa: E402
from fx.effects import pulse as pulse_mod  # noqa: E402
from spectra.models.scene import FlareKind  # noqa: E402
from spectra.services import drop_timing  # noqa: E402
from strip_phase_harness import FPS, Room, run, scene_for  # noqa: E402

VID = "hues"
CFG = {"gradient": "#ff0000", "beat_ms": 500.0, "energy": 0.5}
DROP_OFFSET_MS = -100          # his room's setting the night he reported it
FLIP = FlareKind(name="Pulse Colour Flip", type="pulse_flip")


@pytest.fixture(autouse=True)
def _clean_modulation():
    pm.clear()
    pm.suspend(False)
    yield
    pm.clear()
    pm.suspend(False)


def _sequence(tmp_path, *, floor, lull_mark_ms, charge_ms=6100,
              flare_at_s=None, after_drop_s=1.0):
    """A charge, then a lull whose drop is marked `lull_mark_ms` later and
    fires DROP_OFFSET_MS off that mark; a Light Show floor on the Pulse
    single. Returns (lull frames, frames after the drop, lull record,
    the effect)."""
    lull_ms = drop_timing.build_gap_ms(0, lull_mark_ms, "drop", DROP_OFFSET_MS)

    async def main():
        scene = scene_for({VID: "pulse"}, [FLIP])
        async with Room(str(tmp_path), {VID: ("pulse", 1, 1, dict(CFG))},
                        scene=scene) as r:
            eff = r.effects[VID]
            if floor:
                pm.set_mod(VID, floor=floor)
            r.step(2 * FPS)
            await r.phase("charge", gap_ms=charge_ms)
            r.step(int(charge_ms / 1000 * FPS))
            rec = await r.phase("lull", gap_ms=lull_ms)
            n0 = len(r.frames[VID])
            frames = int(lull_ms / 1000 * FPS)
            if flare_at_s is None:
                r.step(frames)
            else:
                k = int(flare_at_s * FPS)
                r.step(k)
                await r.flare(0.9)
                r.step(frames - k)
            lull = [f.max() for f in r.frames[VID][n0:]]
            await r.phase("drop", intensity=0.7)
            n1 = len(r.frames[VID])
            r.step(int(after_drop_s * FPS))
            after = [f.max() for f in r.frames[VID][n1:]]
            return lull, after, rec, eff
    return run(main())


def _dark_window(rec, lull_frames):
    """Frame indices from the lull's dark point to the drop."""
    dark_s = rec["phase"]["lull_dark_s"]
    return range(int(np.ceil(dark_s * FPS)) + 1, lull_frames)


@pytest.mark.parametrize("lull_mark_ms", [11262, 1772, 467])
@pytest.mark.parametrize("floor", [0.3, 0.1])
def test_a_floored_pulse_still_goes_black_from_the_dark_point_to_the_drop(
        tmp_path, floor, lull_mark_ms):
    """His live lulls (11.2 s, 1.8 s and the shortest, under half a second)
    under his Light Show floors: black from the lull's dark point to the
    drop, the breath-hold included; the floor still holds before the lull
    and after the drop."""
    lull, after, rec, eff = _sequence(tmp_path, floor=floor,
                                      lull_mark_ms=lull_mark_ms)
    assert rec["phase"]["targets"] == [VID]
    assert rec["phase"]["lull_breath_s"] > 0.0          # the breath was told
    window = _dark_window(rec, len(lull))
    assert len(window) > 0
    assert max(lull[i] for i in window) == 0.0
    assert lull[-1] == 0.0                               # black on the drop
    # the floor is not abolished: the lull starts at (at least) the floor
    # and the light after the drop never dips below it
    g = eff._config["gamma"]
    assert lull[0] >= 255.0 * floor ** g * 0.95
    assert min(after) >= 255.0 * floor ** g - 1e-6


def test_the_unfloored_lull_is_unchanged(tmp_path):
    """No Light Show modulation: the lull lands black exactly as before."""
    lull, _after, rec, _eff = _sequence(tmp_path, floor=0.0,
                                        lull_mark_ms=11262)
    assert max(lull[i] for i in _dark_window(rec, len(lull))) == 0.0


def test_red_control_the_pre_fix_floor_holds_the_lull_lit(tmp_path,
                                                          monkeypatch):
    """Put the pre-fix rule back (the floor applies in full in every phase):
    the floored lull never reaches black — the defect he reported."""
    monkeypatch.setattr(pulse_mod.PulseAudioEffect, "_floor_gain",
                        lambda self: 1.0)
    lull, _after, rec, eff = _sequence(tmp_path, floor=0.3,
                                       lull_mark_ms=11262)
    g = eff._config["gamma"]
    window = _dark_window(rec, len(lull))
    assert min(lull[i] for i in window) >= 255.0 * 0.3 ** g - 1e-6
    assert lull[-1] > 0.0


def test_a_flare_in_the_dark_still_punches_through_then_the_dark_returns(
        tmp_path):
    """A flare landing in the lull's dark (11.2 s lull, dark from ~8.2 s)
    punches the floored single back up — the punch is unchanged — then the
    lull takes it back to black before the drop."""
    lull, _after, rec, _eff = _sequence(tmp_path, floor=0.3,
                                        lull_mark_ms=11262, flare_at_s=8.6)
    k = int(8.6 * FPS)
    assert max(lull[k:k + int(0.4 * FPS)]) > 0.0         # the flare shows
    assert lull[-1] == 0.0                                # dark by the drop
    # the breath-hold's window is true black
    breath_s = rec["phase"]["lull_breath_s"]
    n = len(lull)
    assert max(lull[n - int(breath_s * FPS) + 1:]) == 0.0


def test_a_lull_ending_without_a_drop_eases_the_floor_back(tmp_path):
    """A floored lull released without its drop (the effect's orphan
    watchdog): the floor comes back with the light's own exit blend, never
    as a jump from black."""
    async def main():
        async with Room(str(tmp_path), {VID: ("pulse", 1, 1, dict(CFG))}) as r:
            eff = r.effects[VID]
            pm.set_mod(VID, floor=0.3)
            r.step(2 * FPS)
            await r.phase("lull", gap_ms=4000)
            r.step(4 * FPS)
            assert r.frames[VID][-1].max() == 0.0
            # the lull is released without a drop
            eff._leave_phase_without_drop()
            eff._phase = "none"
            eff._self_reset_phase()
            n0 = len(r.frames[VID])
            r.step(int(1.5 * FPS))
            levels = [f.max() for f in r.frames[VID][n0:]]
            g = eff._config["gamma"]
            full = 255.0 * 0.3 ** g
            assert levels[0] < 0.2 * full                 # no jump
            assert levels[-1] >= full - 1e-6              # the floor is back
            steps = np.diff(levels)
            assert steps.max() < 0.2 * full
    run(main())
