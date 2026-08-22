"""Fireworks drop rockets launch RADIALLY EQUIDISTANT around the centre
(owner ask, 2026-08-21: "radially equidistant around the center ... they
can have a little bit of wiggle so that they're not all perfectly radial
but generally close").

Pre-fix, `fireworks.py::_launch_rockets` drew each of the six rockets'
start angles independently (`rng.uniform(0, 2*pi, k)`), so they clumped.
Now `_rocket_start_angles(k)` is the ONE angular plan: even 2*pi/k
spacing, the whole ring randomly rotated per launch, each rocket nudged
by at most LULL_ROCKET_WIGGLE_FRAC of the step.

Proven by measurement, not by eye: across many seeded launches on the
real vendored effect (fx.headless, no audio), the gaps between sorted
start angles never deviate from the even step by more than the wiggle
bound — and the things he PRAISED (end_r, the +/-0.5 rad end-angle
jitter, six rockets) are pinned unchanged. The 1D strip's two rockets
launch from the fixed strip ends, already equidistant by construction —
asserted here so the strip and the crystal provably agree.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless
from fx.effects import fireworks, fireworks1d

VID = headless.DEFAULT_VIRTUAL_ID
SEEDS = range(200)


def _run(coro):
    return asyncio.run(coro)


def _launch_once(effect, seed):
    effect._rng = np.random.default_rng(seed)
    effect.n = 0
    effect._launch_rockets()
    path = effect._rocket_path
    k = int(effect.n)
    start_ang = np.arctan2(path["sy"], path["sx"])
    return k, start_ang, path


def _gap_excess(start_ang):
    """Max |gap - even step| over the k circular gaps of sorted angles."""
    k = len(start_ang)
    srt = np.sort(np.mod(start_ang, 2 * np.pi))
    gaps = np.diff(np.concatenate([srt, [srt[0] + 2 * np.pi]]))
    return float(np.max(np.abs(gaps - 2 * np.pi / k)))


def test_six_rockets_start_evenly_spaced_within_the_wiggle_bound(tmp_path):
    async def main():
        host = await headless.start_headless_host(str(tmp_path / "fw"))
        try:
            virtual = host.virtuals.get(VID)
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(
                    host, virtual, "fireworks", {"spawn_rate": 0.0})
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                step = 2 * np.pi / fireworks.LULL_ROCKETS
                wiggle = step * fireworks.LULL_ROCKET_WIGGLE_FRAC
                # float32 start coords -> atan2 round-trip slack
                eps = 1e-4
                worst = 0.0
                bases = []
                for seed in SEEDS:
                    k, ang, path = _launch_once(effect, seed)
                    assert k == fireworks.LULL_ROCKETS == 6
                    excess = _gap_excess(ang)
                    worst = max(worst, excess)
                    # two adjacent rockets can each move by `wiggle`, so a
                    # gap can stretch/shrink by at most 2*wiggle
                    assert excess <= 2 * wiggle + eps, (seed, excess)
                    bases.append(float(np.mod(ang[0], 2 * np.pi)))
                # the wiggle is real (not a perfectly rigid ring) ...
                assert worst > 0.25 * wiggle
                # ... and the ring rotates freely launch to launch
                assert np.ptp(bases) > np.pi
        finally:
            await host.shutdown()

    _run(main())


def test_wiggle_is_a_small_fraction_of_the_step_and_can_never_swap_order():
    # his "generally close": a sixth of the step (+/-10 degrees at six rockets)
    assert fireworks.LULL_ROCKET_WIGGLE_FRAC == 1.0 / 6.0
    deg = 360.0 / fireworks.LULL_ROCKETS * fireworks.LULL_ROCKET_WIGGLE_FRAC
    assert abs(deg - 10.0) < 1e-9
    # order swap needs a nudge of half a step; clumping reappears well
    # before that — keep the bound structurally far from it
    assert fireworks.LULL_ROCKET_WIGGLE_FRAC < 0.5
    assert fireworks.LULL_ROCKETS == 6


def test_praised_travel_distance_and_end_angle_jitter_are_untouched(tmp_path):
    async def main():
        host = await headless.start_headless_host(str(tmp_path / "fw2"))
        try:
            virtual = host.virtuals.get(VID)
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(
                    host, virtual, "fireworks", {"spawn_rate": 0.0})
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                start_r = float(getattr(effect, "r_max", 1.3)) - 0.05
                end_rs, end_jit = [], []
                for seed in SEEDS:
                    _, ang, path = _launch_once(effect, seed)
                    np.testing.assert_allclose(
                        np.hypot(path["sx"], path["sy"]), start_r, atol=1e-5)
                    end_r = np.hypot(path["ex"], path["ey"])
                    end_ang = np.arctan2(path["ey"], path["ex"])
                    jit = np.angle(np.exp(1j * (end_ang - (ang + np.pi))))
                    end_rs.extend(end_r.tolist())
                    end_jit.extend(jit.tolist())
                end_rs = np.array(end_rs)
                end_jit = np.array(end_jit)
                # end_r: his liked 0.36-0.76 past centre, and still random
                assert end_rs.min() >= 0.36 - 1e-5 and end_rs.max() <= 0.76 + 1e-5
                assert end_rs.max() - end_rs.min() > 0.3
                # end-angle jitter: still +/-0.5 rad around the far side
                assert np.abs(end_jit).max() <= 0.5 + 1e-4
                assert np.abs(end_jit).max() > 0.4
        finally:
            await host.shutdown()

    _run(main())


def test_strip_rockets_launch_from_the_two_fixed_ends(tmp_path):
    """fireworks1d has no clumping shape to fix: its two rockets always
    leave from the strip's own ends — equidistant by construction."""
    async def main():
        host = await headless.start_headless_host(str(tmp_path / "fw1d"))
        try:
            virtual = host.virtuals.get(VID)
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(
                    host, virtual, "fireworks1d", {"spawn_rate": 0.0})
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                for seed in SEEDS:
                    effect._rng = np.random.default_rng(seed)
                    effect.n = 0
                    effect._launch_rockets()
                    assert effect.n == fireworks1d.LULL_ROCKETS == 2
                    np.testing.assert_allclose(
                        effect._rocket_path["s"], [0.03, 0.97], atol=1e-6)
        finally:
            await host.shutdown()

    _run(main())
