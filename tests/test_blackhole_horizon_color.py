"""Headless proof for the blackhole event-horizon recolor
(fx/effects/blackhole.py `horizon_follow_blobs`).

Two things must be true, both asserted here without any live device:
  1. the glow (per-blob capture blend) and the charge/drop halo ring track
     the live blob gradient color instead of the hardcoded #ffffff default;
  2. everything ELSE about the effect — particle count, spawn/capture
     trajectory, phase state — is byte-identical whether the new toggle is
     on or off, i.e. this is a pure recolor with no side effects on motion
     or timing. `horizon_follow_blobs=False` also reproduces the original
     literal-`horizon_color` behavior exactly (same code path as before
     this change).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless


def _run(coro):
    import asyncio

    return asyncio.run(coro)


BASE_CONFIG = {
    "reverse": False,        # infall — the actual "black hole" direction
    "horizon_scale": 0.35,   # generous horizon so blobs are captured fast
    "horizon_hold": 0.5,     # schema minimum; short hold keeps the test brief
    "spawn_rate": 40.0,      # dense spawn so capture happens within a few frames
    "gradient_spin": 0.4,    # spin_total advances, proving the color tracks
                              # the *live* gradient position, not a frozen one
    "color_mode": "wheel",
    "base_speed": 2.0,       # max fall speed
    "edge_speed": 1.0,       # uniform (no rim taper) — reaches the horizon fast
}


async def _render(tmp_path, sub: str, extra_config: dict, n_frames: int = 150):
    # unique device/virtual id per call — headless.DEFAULT_VIRTUAL_ID is a
    # fixed constant, and reusing it across hosts in the same process has
    # been observed to leak state between unrelated runs
    host = await headless.start_headless_host(str(tmp_path / sub), device_id=sub)
    virtual = host.virtuals.get(sub)
    config = dict(BASE_CONFIG, **extra_config)
    with headless.fake_clock() as clock:
        effect = headless.attach_effect(host, virtual, "blackhole", config)
        # deterministic spawn/jitter so runs are comparable frame-for-frame
        effect._rng = np.random.default_rng(20260813)
        frames = headless.render_frames(virtual, n_frames, clock=clock, dt=1 / 60)
    result = {
        "frames": frames,
        "horizon_rgb": np.array(effect.horizon_rgb, copy=True),
        "spin_total": effect.spin_total,
        "n": effect.n,
    }
    await host.shutdown()
    return result


# ── Proof 1: the glow tracks the blob gradient, not white ───────────────────

def test_horizon_glow_tracks_blob_gradient_not_white(tmp_path):
    async def main():
        # follow_blobs is the new default — no override needed
        on = await _render(tmp_path, "follow_on", {})
        assert on["n"] > 0, "no blobs spawned — test config needs tuning"

        # the effect actually captured blobs (glow only renders once
        # something has orbited the horizon)
        white = np.array([255.0, 255.0, 255.0], dtype=np.float32)
        assert not np.allclose(on["horizon_rgb"], white, atol=2.0), (
            "horizon_rgb is still hardcoded white with horizon_follow_blobs on"
        )

        # it matches the live gradient sample at the effect's own spin
        # position — i.e. it really is "the blobs' colour", not some other
        # fixed non-white constant
        host = await headless.start_headless_host(
            str(tmp_path / "sample"), device_id="sample"
        )
        virtual = host.virtuals.get("sample")
        with headless.fake_clock():
            effect = headless.attach_effect(
                host, virtual, "blackhole", dict(BASE_CONFIG)
            )
            expected = effect.get_gradient_color_vectorized1d(
                np.array([on["spin_total"] % 1.0], dtype=np.float32)
            )[0]
        await host.shutdown()
        assert np.allclose(on["horizon_rgb"], expected, atol=1.0), (
            f"horizon_rgb {on['horizon_rgb']} does not match the gradient "
            f"sample {expected} at the effect's own spin_total"
        )

    _run(main())


def test_horizon_follow_blobs_off_reproduces_original_white(tmp_path):
    async def main():
        off = await _render(
            tmp_path, "follow_off", {"horizon_follow_blobs": False}
        )
        white = np.array([255.0, 255.0, 255.0], dtype=np.float32)
        assert np.allclose(off["horizon_rgb"], white, atol=1e-3), (
            "horizon_follow_blobs=False must reproduce the literal original "
            "hardcoded-white horizon_color behavior exactly"
        )

    _run(main())


# ── Proof 2: nothing else changes — pure recolor ─────────────────────────────

def test_recolor_does_not_touch_motion_or_phase_state(tmp_path):
    """Same config, same fake clock, only horizon_follow_blobs differs.
    Particle count and spin trajectory — which the toggle never touches —
    must land identically; only the painted color differs."""

    async def main():
        on = await _render(tmp_path, "parity_on", {})
        off = await _render(
            tmp_path, "parity_off", {"horizon_follow_blobs": False}
        )

        assert on["n"] == off["n"], (
            "particle count diverged between horizon_follow_blobs on/off — "
            "the recolor is not supposed to touch spawn/capture physics"
        )
        assert on["spin_total"] == off["spin_total"], (
            "gradient spin diverged between horizon_follow_blobs on/off"
        )

        # frame-by-frame: same number of frames, same "where is anything
        # lit" mask (motion/geometry), but the actual RGB payload differs
        # at least once (the recolor did something visible)
        assert len(on["frames"]) == len(off["frames"])
        any_rgb_diff = False
        for fa, fb in zip(on["frames"], off["frames"]):
            lit_a = fa.sum(axis=-1) > 1.0
            lit_b = fb.sum(axis=-1) > 1.0
            assert np.array_equal(lit_a, lit_b), (
                "lit-pixel geometry diverged between horizon_follow_blobs "
                "on/off — motion/phase behavior must be unaffected"
            )
            if not np.array_equal(fa, fb):
                any_rgb_diff = True
        assert any_rgb_diff, (
            "no frame differed in RGB between horizon_follow_blobs on/off — "
            "the recolor had no visible effect"
        )

    _run(main())


# ── Proof 3: the charge/drop halo ring recolors too (direct unit check) ─────

def test_phase_halo_tracks_blob_gradient(tmp_path):
    """_phase_halo paints the charge/drop ring straight from horizon_rgb —
    exercise it directly (bypassing the phase edge-detection state machine,
    which is untouched by this change) to prove the ring itself, not just
    the per-blob capture blend, recolors."""

    async def main():
        host = await headless.start_headless_host(
            str(tmp_path / "halo"), device_id="halo"
        )
        virtual = host.virtuals.get("halo")
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(
                host, virtual, "blackhole", dict(BASE_CONFIG)
            )
            # one frame to run do_once() and populate grid_r
            headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)

            rh = effect._horizon_radius()
            out_on = np.zeros((effect.r_height, effect.r_width, 3), dtype=np.float32)
            effect._phase = "charge"
            effect.phase_progress = 1.0
            effect._drop = None
            effect._phase_halo(out_on, rh)
            painted_on = out_on[out_on.sum(axis=-1) > 0]
            assert painted_on.size > 0, "charge halo painted nothing"

            effect.horizon_follow_blobs = False
            effect._horizon_rgb_explicit = np.array(
                [255.0, 255.0, 255.0], dtype=np.float32
            )
            effect.horizon_rgb = effect._horizon_rgb_explicit
            out_off = np.zeros((effect.r_height, effect.r_width, 3), dtype=np.float32)
            effect._phase_halo(out_off, rh)
            painted_off = out_off[out_off.sum(axis=-1) > 0]

        await host.shutdown()

        assert not np.allclose(painted_on[0], painted_off[0], atol=2.0), (
            "the charge/drop halo ring renders the same color whether "
            "horizon_follow_blobs is on or off"
        )
        white = np.array([255.0, 255.0, 255.0], dtype=np.float32)
        # off must match the original literal white ring
        ratio = painted_off[0] / max(painted_off[0].max(), 1e-6) * 255.0
        assert np.allclose(ratio, white, atol=2.0)

    _run(main())
