"""Headless proof for the Black Hole hex-spawn fix
(fx/effects/blackhole.py SPAWN_ANNULUS_MIN/MAX, PR fm/spectra-blackhole-hex-spawn).

Blackhole2d renders blind to which addressable cells are real light vs a
gap-mapped dummy device (see scripts/check_blackhole_hex_spawn.py for the
real-geometry evidence) — the effect only knows normalized (r, theta). The
infall-mode (`reverse=False`) spawn annulus used to be a fixed (0.90, 1.05):
right at/past the panel's own rectangular edge, which is almost entirely gap
on a hex-lattice matrix virtual like his real `crystal-mapper`. Pulling it in
to SPAWN_ANNULUS_MIN..MAX keeps every fresh spawn inside the region a
hex-lattice virtual actually lights, without touching radius_scale/sx/sy (the
effect's overall panel-filling scale) — so this is engine-level proof of two
things: freshly spawned particles land in the new band (not the old one),
and particles still travel a long distance inward afterward (the fall to the
horizon/center is unaffected, i.e. this is not a uniform shrink of the whole
effect)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless
from fx.effects.blackhole import SPAWN_ANNULUS_MAX, SPAWN_ANNULUS_MIN


def _run(coro):
    import asyncio

    return asyncio.run(coro)


BASE_CONFIG = {
    "reverse": False,       # infall — the mode his real Black Hole V2 scene
                             # uses on Matrix/crystal-mapper
    "horizon_scale": 0.2,   # matches his real scene's horizon_scale
    "spawn_rate": 40.0,     # dense spawn so every frame yields fresh blobs
    "beat_burst": 0,
    "base_speed": 2.0,
    "edge_speed": 0.2,
    "accel": 5.0,
}


def test_fresh_spawns_land_in_the_new_annulus_not_the_old_rim_band(tmp_path):
    async def main():
        host = await headless.start_headless_host(
            str(tmp_path / "spawn"), device_id="spawn", pixel_count=72 * 37, rows=37,
        )
        virtual = host.virtuals.get("spawn")
        # spawn_rate=0 + a forced beat burst spawns an exact integer count
        # (beat_burst) deterministically, sidestepping the fractional
        # spawn_acc accumulator (an `int(spawn_acc)` floating-point edge at
        # exactly the frame boundary can silently defer a spawn by a frame —
        # not what this test is about). Since it's the first frame ever,
        # every live particle is a fresh spawn with age exactly 0 — no
        # ambiguity about which particles to sample.
        config = dict(BASE_CONFIG, spawn_rate=0.0, beat_burst=12)
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(host, virtual, "blackhole", config)
            effect._rng = np.random.default_rng(20260817)
            effect._beat_pending = True
            headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)

            n = effect.n
            assert n >= 5, "too few blobs spawned on frame 1 — test config needs tuning"
            assert np.all(effect.p_age[:n] == 0.0)
            fresh_r = np.array(effect.p_r[:n], copy=True)

        await host.shutdown()
        return fresh_r

    fresh_r = _run(main())

    # the module's own constants are what a live scene actually gets —
    # exercise them, not a re-typed copy
    assert np.all(fresh_r >= SPAWN_ANNULUS_MIN - 1e-6)
    assert np.all(fresh_r <= SPAWN_ANNULUS_MAX + 1e-6)

    # disjoint from the old (0.90, 1.05) rim band this replaced — a
    # regression guard against silently reverting to the corner-heavy spawn
    OLD_ANNULUS_MIN = 0.90
    assert SPAWN_ANNULUS_MAX < OLD_ANNULUS_MIN, (
        "new spawn annulus overlaps the old rim band — the fix regressed"
    )
    assert np.all(fresh_r < OLD_ANNULUS_MIN)


def test_blobs_still_fall_most_of_the_way_to_center_after_spawning(tmp_path):
    """The fix must not be a uniform shrink: particles still travel a long
    distance inward from their (now smaller) spawn radius, same as before —
    proving radius_scale/the effect's overall panel-filling scale is
    untouched, only where blobs *start* changed."""

    async def main():
        host = await headless.start_headless_host(
            str(tmp_path / "fall"), device_id="fall", pixel_count=72 * 37, rows=37,
        )
        virtual = host.virtuals.get("fall")
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(host, virtual, "blackhole", BASE_CONFIG)
            effect._rng = np.random.default_rng(20260817)
            headless.render_frames(virtual, 90, clock=clock, dt=1 / 60)
            n = effect.n
            assert n > 0, "no blobs alive — test config needs tuning"
            min_r = float(effect.p_r[:n].min())

        await host.shutdown()
        return min_r

    min_r = _run(main())
    # well below the new spawn band — particles have fallen most of the way
    # from ~0.7-0.85 in toward the horizon (horizon_scale=0.2)/kill_radius
    assert min_r < SPAWN_ANNULUS_MIN - 0.3, (
        f"blobs only reached r={min_r:.3f} after 1.5s — the fall distance "
        "shrank along with the spawn radius"
    )
