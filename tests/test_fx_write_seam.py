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
3. The brightness-coverage flash (data/spectra-transition-brightness-flash/
   report.md): a genuine effect-type switch builds a fresh effect instance,
   which takes LedFX's schema default (1.0, full) for any base
   background_brightness/brightness field the write doesn't set — visible
   and real, since 28/50 (56%) of his real colour sets never author
   background_brightness for crystal-mapper. Both write seams now carry the
   previous effect's value forward on a type switch when the outgoing write
   doesn't set it.

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


def test_fx_seam_carries_forward_missing_brightness_on_type_switch(tmp_path):
    """A colour set that never authored background_brightness/brightness for
    this virtual (28/50 and 27/50 of his real sets, respectively) must not
    flash to LedFX's schema default (1.0) on a type switch — it must show
    whatever the room was actually displaying a moment before."""
    from fx import facade
    from spectra.services import fx_seam

    async def main():
        host = await _fresh_host(
            tmp_path, "seam-carry", effect_type="power",
            config={"gradient": "#000080", "background_color": "#000000",
                    "background_brightness": 0.05, "brightness": 0.42})
        facade.set_host(host)
        virtual = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
        lo.OWNERSHIP_FILE = tmp_path / "ownership.json"
        lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
        try:
            # Genuinely visible authored colour, no brightness fields — the
            # exact shape of an under-covered real colour set.
            await fx_seam.apply_writes(
                [{"virtual_id": headless.DEFAULT_VIRTUAL_ID,
                  "effect_type": "blackhole",
                  "config": {"background_color": "#ff9940",
                             "background_mode": "overwrite"}}],
                transition_ms=300)
            cfg = virtual.active_effect.config
            assert virtual.active_effect.type == "blackhole"
            assert cfg["background_color"] == "#ff9940"
            assert cfg["background_brightness"] == 0.05, \
                "expected the carried value, not the schema default 1.0"
            assert cfg["brightness"] == 0.42, \
                "expected the carried value, not the schema default 1.0"
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_fx_seam_does_not_override_an_authored_brightness(tmp_path):
    """A colour set entry that DOES author background_brightness/brightness
    must win outright — carry-forward only fills a gap, it never overrides
    an explicit value."""
    from fx import facade
    from spectra.services import fx_seam

    async def main():
        host = await _fresh_host(
            tmp_path, "seam-no-override", effect_type="power",
            config={"gradient": "#000080", "background_brightness": 0.05,
                    "brightness": 0.42})
        facade.set_host(host)
        virtual = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
        lo.OWNERSHIP_FILE = tmp_path / "ownership.json"
        lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
        try:
            await fx_seam.apply_writes(
                [{"virtual_id": headless.DEFAULT_VIRTUAL_ID,
                  "effect_type": "blackhole",
                  "config": {"background_color": "#ff9940",
                             "background_brightness": 0.9, "brightness": 0.8}}],
                transition_ms=300)
            cfg = virtual.active_effect.config
            assert cfg["background_brightness"] == 0.9
            assert cfg["brightness"] == 0.8
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_facade_executor_carries_forward_missing_brightness_on_type_switch(tmp_path):
    """The engine-side glide/jump path (drift legs, flare colour jumps) gets
    the identical carry-forward fix — firstmate's live catch (report 2e) was
    very likely this copy, not the scene-fire one."""
    from fx import facade
    from spectra.services.fx_executor import FacadeExecutor

    async def main():
        host = await _fresh_host(
            tmp_path, "executor-carry", effect_type="power",
            config={"gradient": "#000080", "background_color": "#000000",
                    "background_brightness": 0.05, "brightness": 0.42})
        facade.set_host(host)
        virtual = host.virtuals.get(headless.DEFAULT_VIRTUAL_ID)
        try:
            await FacadeExecutor().glide(
                headless.DEFAULT_VIRTUAL_ID, "blackhole",
                {"background_color": "#ff9940"}, 400)
            cfg = virtual.active_effect.config
            assert virtual.active_effect.type == "blackhole"
            assert cfg["background_brightness"] == 0.05
            assert cfg["brightness"] == 0.42
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


def test_carry_forward_with_no_prior_effect_is_a_no_op():
    """Bootstrap (no prior effect on this virtual, e.g. process start before
    any fire has ever touched it): nothing to carry, so the write must pass
    through byte-identical and LedFX's implicit schema default stays correct
    — proven at both write seams, which duplicate this helper independently."""
    from spectra.services import fx_executor, fx_seam

    original = {"background_color": "#ff9940", "background_mode": "overwrite"}
    assert fx_seam._carry_forward_brightness(dict(original), None) == original
    assert fx_executor._carry_forward_brightness(dict(original), None) == original


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
