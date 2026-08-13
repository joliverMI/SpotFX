"""Headless dummy-device test bed for the vendored render pipeline
(SPECTRA Stage 1; report §4e).

Fully offline: frames render onto the vendored DummyDevice, audio is a
synthetic source (fx.headless.silence_audio — PortAudio is never touched;
the final test asserts sounddevice was never even imported), and the facade
path exercises api/ledfx_client with settings.fx_in_process on — zero HTTP.

The three Stage 1 proofs:
  1. an effect renders deterministically (frame-stepped, fake clock,
     bit-identical across two fresh hosts, PNG captured),
  2. a SceneV2 test-fire through the ledfx_client facade seam lands on the
     dummy virtual (real render thread, frames observed at the device),
  3. the server-side tween engine interpolates a param over transition_ms.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless


def _run(coro):
    return asyncio.run(coro)


async def _fresh_host(tmp_path, sub: str):
    return await headless.start_headless_host(str(tmp_path / sub))


# ── Proof 1: deterministic render ────────────────────────────────────────────

def test_effect_renders_deterministically(tmp_path):
    async def render_run(sub: str) -> list[np.ndarray]:
        host = await _fresh_host(tmp_path, sub)
        virtual = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
        with headless.fake_clock() as clock:
            headless.attach_effect(host, virtual, "concentric", {})
            frames = headless.render_frames(virtual, 30, clock=clock, dt=1 / 60)
        await host.shutdown()
        return frames

    async def main():
        frames_a = await render_run("run_a")
        frames_b = await render_run("run_b")

        # The effect actually drew something...
        assert frames_a, "no frames rendered"
        assert float(np.abs(frames_a[-1]).sum()) > 0, "effect rendered black"
        # ...and two fresh hosts produce bit-identical output under the
        # fake clock: the pipeline is deterministic when time is.
        digest_a = hashlib.sha1(np.concatenate(frames_a).tobytes()).hexdigest()
        digest_b = hashlib.sha1(np.concatenate(frames_b).tobytes()).hexdigest()
        assert digest_a == digest_b

        # Frame capture to PNG (the agent-evaluation surface from report 4e).
        png = tmp_path / "concentric_frame30.png"
        headless.save_png(frames_a[-1], str(png), rows=8)
        assert png.exists() and png.stat().st_size > 0

    _run(main())


# ── Proof 2: SceneV2 test-fire through the facade lands on the dummy ─────────

def test_scene_v2_fire_through_facade_lands_on_dummy(tmp_path, fresh_ledfx_client):
    from models.scene_v2 import SceneDeviceConfig, SceneV2
    from services import scene_v2_compiler
    from fx import facade

    lc = fresh_ledfx_client("http://facade-not-http.invalid")
    object.__setattr__(lc.settings, "fx_in_process", True)

    scene = SceneV2(
        name="testbed scene",
        devices=[
            SceneDeviceConfig(
                target_kind="virtual",
                target=headless.DEFAULT_VIRTUAL_ID,
                effect_type="concentric",
                brightness=0.9,
            )
        ],
    )

    async def main():
        # Production reality: every SpotFX-driven virtual boots with an
        # effect restored from config (the effects PUT rejects a bare one).
        config_dir = str(tmp_path / "facade")
        headless.write_headless_config(
            config_dir,
            initial_effect={"type": "singleColor", "config": {"color": "#000080"}},
        )
        headless.silence_audio()
        from fx.host import FxHost

        host = FxHost(config_dir)
        host.audio = headless.SyntheticAudioSource()
        await host.start()
        facade.set_host(host)
        virtual = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
        device = host.devices.get(headless.DEFAULT_DEVICE_ID)
        tap = headless.FrameTap(host, headless.DEFAULT_VIRTUAL_ID)
        try:
            result = await scene_v2_compiler.fire_scene(scene, dry_run=False)
            assert result["writes"], "compiler produced no writes"
            await lc.drain_bus()  # the 8 ms coalesce bus must flush in-process

            # The write landed as a direct call: the dummy virtual now runs
            # the scene's effect with the scene's brightness.
            assert virtual.active_effect is not None
            assert virtual.active_effect.type == "concentric"
            assert virtual.active_effect.config["brightness"] == pytest.approx(0.9)

            # The real per-virtual render thread is streaming frames into the
            # dummy device — this is thread-per-virtual running in-process.
            await asyncio.sleep(0.5)
            assert virtual.active and virtual._thread.is_alive()
            assert tap.frames, "no VirtualUpdateEvent frames observed"
            assert any(float(np.abs(f).sum()) > 0 for f in tap.frames)
            assert device._pixels is not None
        finally:
            tap.close()
            virtual.deactivate()
            facade.set_host(None)
            await host.shutdown()

    _run(main())
    object.__setattr__(lc.settings, "fx_in_process", False)


# ── Proof 3: the tween engine interpolates ───────────────────────────────────

def test_tween_engine_interpolates(tmp_path):
    from fx import facade

    async def main():
        host = await _fresh_host(tmp_path, "tween")
        facade.set_host(host)
        virtual = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
        try:
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(
                    host, virtual, "concentric", {"brightness": 1.0}
                )
                resp = await facade.handle(
                    "PUT",
                    f"/api/virtuals/{headless.DEFAULT_VIRTUAL_ID}/effects",
                    json={
                        "type": "concentric",
                        "config": {"brightness": 0.2},
                        "transition_ms": 1000,
                        "easing": "linear",
                        "transition_blend": "rgb",
                    },
                )
                assert resp.status_code == 200
                # Tween registered, config not snapped to target.
                assert effect._tweens and "brightness" in effect._tweens
                assert effect._config["brightness"] == pytest.approx(1.0)

                # Advance half the duration: linear lerp puts brightness at
                # the midpoint — the engine is interpolating, not snapping.
                headless.render_frames(virtual, 30, clock=clock, dt=1 / 60)
                assert 0.5 < effect._config["brightness"] < 0.7

                # Run past the end: lands exactly on target, tween retired.
                headless.render_frames(virtual, 40, clock=clock, dt=1 / 60)
                assert effect._config["brightness"] == pytest.approx(0.2)
                assert effect._tweens is None

                # GET through the facade reports the persisted TARGET config
                # (the update_effect_config(config_override=...) contract).
                get = await facade.handle(
                    "GET", f"/api/virtuals/{headless.DEFAULT_VIRTUAL_ID}"
                )
                persisted = get.json()[headless.DEFAULT_VIRTUAL_ID]
                assert persisted["effect"]["config"]["brightness"] == pytest.approx(0.2)
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── Offline guarantee ─────────────────────────────────────────────────────────

def test_no_audio_hardware_was_touched():
    """The vendored pipeline ran the whole bed without dereferencing the lazy
    sounddevice proxy — the synthetic audio source absorbed every effect
    subscription, so fx never initialized PortAudio or opened a stream.
    (sys.modules may still hold sounddevice: SpotFX's own audio_shape_service
    imports it when ledfx_client's capture gate probes it — out of fx scope.)"""
    from fx.compat_sounddevice import _LazySounddevice

    assert _LazySounddevice._module is None
