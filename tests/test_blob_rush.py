"""The BLOB RUSH flare (his ask, 2026-08-24): "a new effect that runs as a
shape flare that randomly chooses between the momentary reverse and this
one... it just generates 12 blobs all at once spread out fairly evenly.
Override any max blob counts for this generation if that's easy".

Fast, deterministic coverage of the mechanism itself, on the real vendored
Blackhole effect (fx.headless, audio silenced). The end-to-end proof
against HIS real Black Hole V2 scene — the lane pick, the real
ResponseEngine fire, the population already at his own max_blobs=50 — is
scripts/check_blob_rush.py."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model, headless
from fx.effects import blackhole as bh

DT = 1.0 / 60.0
CFG = {
    "horizon_scale": 0.2, "blob_size": 1.75, "swirl": 0.0, "reverse": False,
    "base_speed": 2.0, "accel": 5.0, "spawn_rate": 0.0, "beat_burst": 0,
    "max_blobs": 20, "edge_speed": 0.2, "horizon_hold": 2.8,
}


async def _rush(tmp_path, sub, *, config=None, prefill=0, count=12, frames=2):
    host = await headless.start_headless_host(
        str(tmp_path / sub), device_id=sub, pixel_count=72 * 37, rows=37)
    virtual = host.virtuals.get(sub)
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(host, virtual, "blackhole",
                                        dict(CFG, **(config or {})))

        def step(n):
            for _ in range(n):
                clock.advance(DT)
                frame = virtual.assemble_frame()
                if frame is not None:
                    virtual.flush(frame)

        step(1)
        if prefill:
            effect._spawn(prefill, 0)
        before_n = effect.n
        before_r = effect.p_r[: effect.n].copy()
        before_cap = effect.p_cap[: effect.n].copy()
        effect.update_config({"blob_rush": count})
        step(frames)
        fresh = np.flatnonzero(effect.p_nocap[: effect.n])
        out = {
            "before_n": before_n, "n": effect.n,
            "fresh": len(fresh),
            "theta": effect.p_theta[fresh].copy(),
            "r": effect.p_r[fresh].copy(),
            "key": effect._config["blob_rush"],
            "kept_r": effect.p_r[: len(before_r)].copy(),
            "before_r": before_r, "before_cap": before_cap,
            "kept_cap": effect.p_cap[: len(before_cap)].copy(),
            "horizon": effect._horizon_radius(),
        }
    await host.shutdown()
    return out


def test_twelve_blobs_land_past_the_density_cap(tmp_path):
    """max_blobs=20, already full: the rush still lands all 12 (his
    "Override any max blob counts for this generation")."""
    res = asyncio.run(_rush(tmp_path, "cap", prefill=40))
    assert res["before_n"] == 20, "the ordinary spawn is capped at max_blobs"
    assert res["fresh"] == 12
    assert res["n"] == res["before_n"] + 12


def test_the_rush_is_evenly_spread(tmp_path):
    """Even 2*pi/12 spacing, the whole ring randomly rotated, each blob
    nudged by at most BLOB_RUSH_WIGGLE_FRAC of one step — so no two ever
    swap order (fireworks' own equidistant-rocket shape)."""
    res = asyncio.run(_rush(tmp_path, "even"))
    theta = np.sort(res["theta"] % (2 * np.pi))
    gaps = np.diff(np.concatenate([theta, [theta[0] + 2 * np.pi]]))
    step = 2 * np.pi / 12
    assert np.all(np.abs(gaps - step) <= 2 * bh.BLOB_RUSH_WIGGLE_FRAC * step + 1e-6)
    assert len(np.unique(np.round(theta, 4))) == 12


def test_infall_rush_arrives_from_the_hex_boundary(tmp_path):
    """In infall the rush arrives where an ordinary blob does: just past
    the true per-direction crystal-mapper hex boundary, never a scalar
    annulus (.claude/skills/crystal-hex-grid/SKILL.md)."""
    res = asyncio.run(_rush(tmp_path, "hex", frames=1))
    edge = bh._hex_spawn_edge_radius(res["theta"].astype(np.float32))
    assert np.all(res["r"] > edge - 0.05)
    assert np.all(res["r"] <= edge + bh.SPAWN_EDGE_MARGIN_MAX + 1e-6)
    # direction-dependent by construction: a scalar radius could not match
    assert float(edge.max() - edge.min()) > 0.15


def test_reverse_rush_leaves_from_the_horizon_ring(tmp_path):
    """While the effect is reversed the rush erupts from the event horizon
    instead — the mode's own spawn location, not a second rule."""
    res = asyncio.run(_rush(tmp_path, "rev", config={"reverse": True},
                            frames=1))
    assert res["fresh"] == 12
    assert np.all(res["r"] >= res["horizon"] - 1e-3)
    assert np.all(res["r"] <= res["horizon"] + 0.12)


def test_the_rush_disturbs_nothing_already_on_screen(tmp_path):
    """His second option — "or remove the ones in the event horizon" — was
    deliberately NOT taken: the ring keeps its orbiters, and every live
    blob keeps its own position."""
    res = asyncio.run(_rush(tmp_path, "quiet", prefill=12, frames=1))
    assert len(res["kept_r"]) == res["before_n"]
    assert np.all(res["kept_cap"] == res["before_cap"])
    assert np.all(np.abs(res["kept_r"] - res["before_r"]) < 0.05)


def test_the_key_self_resets_and_a_second_rush_edges(tmp_path):
    """Same discipline as the phase keys and fireworks' burst_rockets: the
    effect self-resets the key to 0 after firing, so an identical later
    write edges again."""
    async def run():
        host = await headless.start_headless_host(
            str(tmp_path / "edge"), device_id="edge",
            pixel_count=72 * 37, rows=37)
        virtual = host.virtuals.get("edge")
        counts = []
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(host, virtual, "blackhole", dict(CFG))

            def step(n):
                for _ in range(n):
                    clock.advance(DT)
                    frame = virtual.assemble_frame()
                    if frame is not None:
                        virtual.flush(frame)

            step(1)
            for _ in range(3):
                effect.update_config({"blob_rush": 12})
                step(1)
                counts.append(int(np.count_nonzero(
                    effect.p_nocap[: effect.n])))
                assert effect._config["blob_rush"] == 0
        await host.shutdown()
        return counts

    assert asyncio.run(run()) == [12, 24, 36]


def test_a_stale_persisted_count_never_rushes_on_a_fresh_instance(tmp_path):
    """The creation baseline: an effect built from a config that still
    carries a count must not fire it — the same rule the phase key has."""
    async def run():
        host = await headless.start_headless_host(
            str(tmp_path / "stale"), device_id="stale",
            pixel_count=72 * 37, rows=37)
        virtual = host.virtuals.get("stale")
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(
                host, virtual, "blackhole", dict(CFG, blob_rush=12))
            for _ in range(4):
                clock.advance(DT)
                frame = virtual.assemble_frame()
                if frame is not None:
                    virtual.flush(frame)
            fired = int(np.count_nonzero(effect.p_nocap[: effect.n]))
            key = effect._config["blob_rush"]
        await host.shutdown()
        return fired, key

    fired, key = asyncio.run(run())
    assert fired == 0
    assert key == 0, "the stale key is still cleared, so a later write edges"


def test_blob_rush_is_gated_to_black_hole_and_unregistered():
    """Structural, like the phase keys and burst_rockets: the key rides the
    dedicated flare write only — never an editor surface or a band patch."""
    assert device_model.BLOB_RUSH_EFFECTS == frozenset({"blackhole"})
    assert "blob_rush" not in device_model.effect_params("blackhole")
    assert "blob_rush" in bh.Blackhole2d.CONFIG_SCHEMA.schema
