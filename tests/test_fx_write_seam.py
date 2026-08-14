"""Regressions from the spectra-room-fault diagnosis (2026-08-14):

1. The stale-tween-PUT silent drop: fx/facade.py's ported "ignoring stale
   tween PUT" guard (447-461) silently swallows any combined type-switch+
   transition PUT, because neither fx_seam.py nor fx_executor.py ever used
   the two-phase switch-then-tween protocol that guard assumes. Both now
   check the target's currently-active effect type first and land a genuine
   switch as an instant PUT.
2. The colour-jump KeyError: 'current': fx/effects/__init__.py's
   start_param_transitions indexed prior["current"] unconditionally, but a
   gradient-kind prior stores current_curve instead — retargeting the same
   param key from a gradient to a colour/numeric value mid-tween raised
   KeyError, dropping the whole bridge event (scene_response.py._color_jump).

Offline/hermetic throughout: isolated tmp_path dummy host, no live
storage/network.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless, light_ownership as lo
from fx.host import FxHost

_ORIGINAL_OWNERSHIP_FILE = lo.OWNERSHIP_FILE


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _restore_ownership_file():
    yield
    lo.OWNERSHIP_FILE = _ORIGINAL_OWNERSHIP_FILE


async def _fresh_host(tmp_path, sub: str, *, effect_type: str = "singleColor",
                      config: dict | None = None):
    config_dir = str(tmp_path / sub)
    headless.write_headless_config(
        config_dir, initial_effect={"type": effect_type,
                                    "config": config or {"color": "#000080"}})
    headless.silence_audio()
    host = FxHost(config_dir)
    host.audio = headless.SyntheticAudioSource()
    await host.start()
    return host


def test_facade_executor_glide_lands_a_real_type_switch(tmp_path):
    """A glide asking for a DIFFERENT effect type with transition_ms>0 must
    actually switch the virtual, not silently no-op — the exact shape of
    every scene-driven engine re-baseline that was getting dropped."""
    from fx import facade
    from spectra.services.fx_executor import FacadeExecutor

    async def main():
        host = await _fresh_host(tmp_path, "executor")
        facade.set_host(host)
        virtual = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
        assert virtual.active_effect.type == "singleColor"
        try:
            await FacadeExecutor().glide(
                headless.DEFAULT_VIRTUAL_ID, "power",
                {"gradient": "#ff0000", "brightness": 0.8}, 400)
            assert virtual.active_effect.type == "power", \
                "type switch was silently dropped by the stale-tween-PUT guard"
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_fx_seam_apply_writes_lands_a_real_type_switch(tmp_path):
    """The manual-fire path (fx_seam.apply_writes, owner=spectra) must land
    a scene's effect-type switch even though scene_compiler.fire_scene
    always carries transition_ms>0 (scene.entry_ramp_ms or
    room.global_transition_ms) — the exact combination that stuck
    crystal-mapper on "blackhole" in production."""
    from fx import facade
    from spectra.services import fx_seam

    async def main():
        host = await _fresh_host(tmp_path, "seam")
        facade.set_host(host)
        virtual = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
        lo.OWNERSHIP_FILE = tmp_path / "ownership.json"
        lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
        try:
            await fx_seam.apply_writes(
                [{"virtual_id": headless.DEFAULT_VIRTUAL_ID, "effect_type": "power",
                  "config": {"gradient": "#00ff00", "brightness": 0.7}}],
                transition_ms=400)
            assert virtual.active_effect.type == "power", \
                "scene fire's type switch was silently dropped"
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_gradient_to_color_retarget_does_not_raise_keyerror(tmp_path):
    """A colour-jump retargeting the same param key from a gradient string
    to a plain colour before the gradient tween completes must not crash —
    this is scene_response._color_jump's exact shape, and the KeyError used
    to drop the whole bridge event (bridge.py's per-message try/except only
    logs and moves on, so the flare's colour change was simply lost)."""
    from fx import facade

    async def main():
        host = await _fresh_host(tmp_path, "keyerror",
                                  effect_type="power", config={"gradient": "#000080"})
        facade.set_host(host)
        vid = headless.DEFAULT_VIRTUAL_ID
        try:
            r1 = await facade.handle(
                "PUT", f"/api/virtuals/{vid}/effects",
                json={"type": "power",
                      "config": {"gradient": "linear-gradient(90deg, rgb(255,0,0) 0%, rgb(0,0,255) 100%)"},
                      "transition_ms": 5000, "transition_blend": "hue"})
            r1.raise_for_status()
            r2 = await facade.handle(  # retarget before the gradient tween finishes
                "PUT", f"/api/virtuals/{vid}/effects",
                json={"type": "power", "config": {"gradient": "#00ff00"},
                      "transition_ms": 500, "transition_blend": "hue"})
            r2.raise_for_status()  # used to raise KeyError: 'current' here
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())
