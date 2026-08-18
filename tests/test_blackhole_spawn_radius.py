"""Headless proof for the Black Hole hex-spawn-at-edge fix
(fx/effects/blackhole.py HEX_SPAWN_VERTS/_hex_spawn_edge_radius, PR
fm/spectra-blackhole-spawn-at-edge).

Blackhole2d renders blind to which addressable cells are real light vs a
gap-mapped dummy device (see scripts/check_blackhole_hex_spawn.py for the
real-geometry evidence) — the effect only knows normalized (r, theta). The
infall-mode (`reverse=False`) spawn location went through two rounds: a
fixed (0.90, 1.05) rim (too far OUT, mostly dead corner gap), then a fixed
(0.70, 0.85) annulus tuned to maximize real-pixel hit rate (too far IN — his
2026-08-18 report: blobs spawn "several pixels" inside the visible edge
instead of arriving from it). Because the hex silhouette's distance from
center genuinely depends on direction, no single scalar can sit "at the
edge" in more than a few directions — the fix now computes the boundary per
spawn angle (`_hex_spawn_edge_radius`) and spawns just past it.

This is engine-level proof of three things: freshly spawned particles land
just past THEIR OWN spawn angle's true boundary (not a fixed band, and not
either of the two earlier fixed annuli), particles still travel a long
distance inward afterward (the fall to the horizon/center is unaffected —
this is not a uniform shrink/grow of the whole effect), and the closed-form
boundary formula matches what a plain polygon-intersection check would give
for the same angles (proof the support-function implementation is correct,
independent of scripts/check_blackhole_hex_spawn.py's own device-profile
comparison)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless
from fx.effects.blackhole import (
    HEX_SPAWN_VERTS,
    SPAWN_EDGE_MARGIN_MAX,
    SPAWN_EDGE_MARGIN_MIN,
    _hex_spawn_edge_radius,
)


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

# the two annuli this fix's history moved through — neither should reappear
OLD_RIM_MIN, OLD_RIM_MAX = 0.90, 1.05
HIT_RATE_ANNULUS_MIN, HIT_RATE_ANNULUS_MAX = 0.70, 0.85


def _naive_polygon_edge_radius(theta):
    """Independent, brute-force ray-vs-segment reference implementation
    (no support-function trick) — used only to cross-check
    _hex_spawn_edge_radius, not as a second copy of its logic."""
    ux, uy = math.cos(theta), math.sin(theta)
    best = math.inf
    n = len(HEX_SPAWN_VERTS)
    for i in range(n):
        x1, y1 = HEX_SPAWN_VERTS[i]
        x2, y2 = HEX_SPAWN_VERTS[(i + 1) % n]
        # ray: (t*ux, t*uy), t>=0. segment: p1 + s*(p2-p1), s in [0,1].
        ex, ey = x2 - x1, y2 - y1
        denom = ux * ey - uy * ex
        if abs(denom) < 1e-12:
            continue
        s = (ux * (0 - y1) - uy * (0 - x1)) / denom
        if not (0.0 <= s <= 1.0):
            continue
        if abs(ux) > abs(uy):
            t = (x1 + s * ex) / ux
        else:
            t = (y1 + s * ey) / uy
        if t > 1e-9:
            best = min(best, t)
    return best


def test_hex_spawn_edge_radius_matches_a_naive_reference_implementation():
    rng = np.random.default_rng(1)
    thetas = rng.uniform(0.0, 2 * np.pi, 200)
    formula = np.asarray(_hex_spawn_edge_radius(thetas))
    for theta, r in zip(thetas, formula):
        expected = _naive_polygon_edge_radius(float(theta))
        assert math.isclose(float(r), expected, abs_tol=1e-4), (
            f"theta={theta:.3f}: support-function gave {r:.4f}, "
            f"naive ray-cast gave {expected:.4f}"
        )


def test_hex_spawn_edge_radius_varies_with_direction():
    """The whole point of the fix: this is not a disguised scalar. Swept
    across all directions, the boundary distance at its loosest (a corner
    vertex) must be meaningfully farther than at its tightest (a flat edge's
    own midpoint-normal) — no single scalar radius can sit "at the edge" in
    both places at once."""
    theta = np.linspace(0.0, 2 * np.pi, 3600, endpoint=False)
    r = np.asarray(_hex_spawn_edge_radius(theta))
    r_min, r_max = float(r.min()), float(r.max())
    assert r_max > r_min * 1.2, (
        f"loosest boundary ({r_max:.3f}) should be well past the tightest "
        f"({r_min:.3f}) — a single scalar can't fit both"
    )
    # sanity-anchor against the measured vertices themselves: the loosest
    # point should be near a corner vertex's own radius, not some formula
    # artifact
    vertex_radii = [math.hypot(x, y) for x, y in HEX_SPAWN_VERTS]
    assert math.isclose(r_max, max(vertex_radii), rel_tol=0.02)


def test_fresh_spawns_land_just_past_their_own_directions_boundary(tmp_path):
    async def main():
        host = await headless.start_headless_host(
            str(tmp_path / "spawn"), device_id="spawn", pixel_count=72 * 37, rows=37,
        )
        virtual = host.virtuals.get("spawn")
        # spawn_rate=0 + a forced beat burst spawns an exact integer count
        # (beat_burst) deterministically, sidestepping the fractional
        # spawn_acc accumulator. Since it's the first frame ever, every live
        # particle is a fresh spawn with age exactly 0.
        config = dict(BASE_CONFIG, spawn_rate=0.0, beat_burst=12)
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(host, virtual, "blackhole", config)
            effect._rng = np.random.default_rng(20260818)
            effect._beat_pending = True
            headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)

            n = effect.n
            assert n >= 8, "too few blobs spawned on frame 1 — test config needs tuning"
            assert np.all(effect.p_age[:n] == 0.0)
            fresh_r = np.array(effect.p_r[:n], copy=True)
            fresh_theta = np.array(effect.p_theta[:n], copy=True)

        await host.shutdown()
        return fresh_r, fresh_theta

    fresh_r, fresh_theta = _run(main())

    edge_r = np.asarray(_hex_spawn_edge_radius(fresh_theta))

    # every spawn lands between its own direction's boundary + the min
    # margin and + the max margin — never inside the boundary, never past
    # the max margin
    assert np.all(fresh_r >= edge_r + SPAWN_EDGE_MARGIN_MIN - 1e-4)
    assert np.all(fresh_r <= edge_r + SPAWN_EDGE_MARGIN_MAX + 1e-4)

    # regression guard: not a disguised return to either earlier fixed
    # annulus. A direction-dependent spawn set spans a much wider range of r
    # than either historical fixed band did.
    assert fresh_r.max() - fresh_r.min() > (
        HIT_RATE_ANNULUS_MAX - HIT_RATE_ANNULUS_MIN
    ), "spawn radii show no per-direction spread — looks like a scalar again"

    # never inside the old too-far-in annulus's own floor, and confirm we've
    # actually moved past it for spawns whose local boundary sits at/above it
    outside_old_annulus = fresh_r[edge_r >= HIT_RATE_ANNULUS_MAX]
    if outside_old_annulus.size:
        assert np.all(outside_old_annulus > HIT_RATE_ANNULUS_MAX)


def test_blobs_still_fall_most_of_the_way_to_center_after_spawning(tmp_path):
    """The fix must not be a uniform shrink/grow: particles still travel a
    long distance inward from their spawn radius, same as before — proving
    radius_scale/the effect's overall panel-filling scale is untouched, only
    where blobs *start* changed."""

    async def main():
        host = await headless.start_headless_host(
            str(tmp_path / "fall"), device_id="fall", pixel_count=72 * 37, rows=37,
        )
        virtual = host.virtuals.get("fall")
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(host, virtual, "blackhole", BASE_CONFIG)
            effect._rng = np.random.default_rng(20260818)
            headless.render_frames(virtual, 90, clock=clock, dt=1 / 60)
            n = effect.n
            assert n > 0, "no blobs alive — test config needs tuning"
            min_r = float(effect.p_r[:n].min())

        await host.shutdown()
        return min_r

    min_r = _run(main())
    # well below the smallest possible spawn boundary — particles have
    # fallen most of the way in toward the horizon (horizon_scale=0.2)/
    # kill_radius, not just sitting near where they started
    assert min_r < HIT_RATE_ANNULUS_MIN - 0.3, (
        f"blobs only reached r={min_r:.3f} after 1.5s — the fall distance "
        "shrank along with the spawn radius"
    )
