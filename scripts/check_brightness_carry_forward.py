#!/usr/bin/env python3
"""Read-only proof for the brightness-coverage carry-forward fix
(data/spectra-transition-brightness-flash/report.md, PR
fm/spectra-brightness-carry-forward).

Defect (report Part 2): 28 of his 50 real colour sets never author
`background_brightness` for `crystal-mapper` (27 never author `brightness`
either). On a genuine effect-type switch there — what most scene
transitions are — the fresh effect instance took LedFX's schema default
(1.0, full) instead of whatever was actually showing a moment before, a
real visible flash confirmed both offline (report 2c/2d) and live in his
room (report 2e).

Fix (both write seams — spectra/services/fx_seam.py's `_apply_via_facade`
and spectra/services/fx_executor.py's `FacadeExecutor._put`): on a detected
type switch, copy `background_brightness`/`brightness` from the virtual's
CURRENT live effect config into the outgoing write whenever the write
doesn't already set them. No prior effect (bootstrap) has nothing to
carry, so today's implicit default is untouched there.

This script drives the real, unmodified production functions
(`scene_compiler.resolve_scene`/`compile_scene`, `fx_seam.apply_writes`,
`fx_executor.FacadeExecutor`) against:
  - his real, read-only storage/color_sets.json + storage/spectra/
    scenes.json (SpotFX's own primary checkout, NEVER this worktree's copy
    — see AGENTS.md's "A worktree's own storage/spectra/*.json is
    gitignored and untracked" warning) to pick a genuinely representative
    (colour set, scene) pair, exactly the report's own method;
  - an in-process fx.headless dummy host (fx/facade.py, no HTTP, no real
    device) to prove what actually reaches the wire.

Never touches live storage or a live instance — GETs only, and only
against the throwaway headless host this script starts itself.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from random import Random

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fx import facade, headless, light_ownership as lo  # noqa: E402
from fx.host import FxHost  # noqa: E402
from spectra.models.scene import SceneV2  # noqa: E402
from spectra.services import fx_seam  # noqa: E402
from spectra.services.binding_resolver import FireContext  # noqa: E402
from spectra.services.color_sets import ColorSetCard  # noqa: E402
from spectra.services.fx_executor import FacadeExecutor  # noqa: E402
from spectra.services.scene_compiler import compile_scene, resolve_scene  # noqa: E402

REAL_COLOR_SETS = Path("/home/javi/SpotFX/storage/color_sets.json")
REAL_SCENES = Path("/home/javi/SpotFX/storage/spectra/scenes.json")
CRYSTAL = "crystal-mapper"

SCHEMA_DEFAULT_BRIGHTNESS = 1.0  # fx/effects/__init__.py CONFIG_SCHEMA


def _pick_real_write() -> dict:
    """Reproduces report Part 2c: a real crystal-uncovered set, fired onto
    a real crystal scene, compiled by the real (unmodified) compiler."""
    color_sets = json.loads(REAL_COLOR_SETS.read_text())
    card = ColorSetCard(**color_sets["15a767a0-13ae-451e-bca2-185aafca7e3e"])
    assert card.name == "Calm - Purple"

    scenes = json.loads(REAL_SCENES.read_text())
    scene = SceneV2(**scenes["e9b44a88-77b9-4eb9-ae2a-859d3ecd6dc1"])
    assert scene.name == "Black Hole V2"

    resolved = resolve_scene(scene, FireContext(0.5, rng=Random(20260820)))
    writes = compile_scene(resolved, card)
    write = next(w for w in writes if w["virtual_id"] == CRYSTAL)

    print(f"Real pair: colour set '{card.name}' fired onto scene "
          f"'{scene.name}' (effect '{write['effect_type']}')")
    print(f"Compiled write for {CRYSTAL}: {json.dumps(write['config'], indent=2)}")
    assert write["config"].get("background_color"), \
        "expected a genuinely visible authored background — not this pair"
    assert "background_brightness" not in write["config"], \
        "expected the defect precondition: no background_brightness authored"
    assert "brightness" not in write["config"], \
        "expected the defect precondition: no brightness authored"
    print("  -> confirmed: colour present, brightness fields absent "
          "(the exact defect precondition, report 2c)\n")
    return write


async def _fresh_host(config_dir: str) -> FxHost:
    headless.write_headless_config(
        config_dir, device_id=CRYSTAL, rows=8, pixel_count=64,
        initial_effect={"type": "radial",
                        "config": {"background_color": "#000000",
                                    "background_brightness": 0.05,
                                    "brightness": 0.42}})
    headless.silence_audio()
    host = FxHost(config_dir)
    host.audio = headless.SyntheticAudioSource()
    await host.start()
    return host


async def part1_scene_fire_seam(tmp_dir: str, write: dict) -> None:
    print("== Part 1: fx_seam.apply_writes — the scene-fire path ==")
    host = await _fresh_host(tmp_dir + "/seam")
    facade.set_host(host)
    virtual = host.virtuals.get(CRYSTAL)
    orig_ownership_file = lo.OWNERSHIP_FILE
    lo.OWNERSHIP_FILE = Path(tmp_dir) / "ownership.json"
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
    try:
        assert virtual.active_effect.type == "radial"
        print(f"BEFORE switch: radial  background_brightness="
              f"{virtual.active_effect.config['background_brightness']}  "
              f"brightness={virtual.active_effect.config['brightness']}")

        # The real, unmodified production write seam — nonzero transition_ms,
        # matching room_controls.scene_transition_ms()'s gentle/hard defaults
        # (300/200ms), what every real scene fire carries.
        await fx_seam.apply_writes([write], transition_ms=300)

        assert virtual.active_effect.type == write["effect_type"]
        cfg = virtual.active_effect.config
        print(f"AFTER switch:  {write['effect_type']}")
        print(f"  background_color      = {cfg['background_color']}")
        print(f"  background_brightness = {cfg['background_brightness']}")
        print(f"  brightness (foreground)= {cfg['brightness']}")

        assert cfg["background_color"] == write["config"]["background_color"], \
            "the genuinely authored colour must still land untouched"
        assert cfg["background_brightness"] == 0.05, (
            f"expected the CARRIED value 0.05, got {cfg['background_brightness']} "
            f"(schema default is {SCHEMA_DEFAULT_BRIGHTNESS} — a bare default "
            f"here means the fix regressed)")
        assert cfg["brightness"] == 0.42, (
            f"expected the CARRIED value 0.42, got {cfg['brightness']}")
        print("\n  -> CONFIRMED: background_brightness/brightness reaching the "
              "wire are the CARRIED values, not the schema default "
              f"{SCHEMA_DEFAULT_BRIGHTNESS}.\n")
    finally:
        facade.set_host(None)
        await host.shutdown()
        lo.OWNERSHIP_FILE = orig_ownership_file


async def part2_engine_executor(tmp_dir: str) -> None:
    print("== Part 2: fx_executor.FacadeExecutor — the engine glide/jump path ==")
    print("(report 2e: firstmate's live catch was very likely this copy)\n")
    host = await _fresh_host(tmp_dir + "/executor")
    facade.set_host(host)
    virtual = host.virtuals.get(CRYSTAL)
    try:
        assert virtual.active_effect.type == "radial"
        print(f"BEFORE glide: radial  background_brightness="
              f"{virtual.active_effect.config['background_brightness']}")

        # A drift leg/flare colour jump landing on a genuine type mismatch,
        # missing background_brightness/brightness — the same defect shape,
        # engine side.
        await FacadeExecutor().glide(
            CRYSTAL, "blackhole", {"gradient": "#00ff88"}, 400)

        assert virtual.active_effect.type == "blackhole"
        cfg = virtual.active_effect.config
        print(f"AFTER glide:  blackhole  background_brightness="
              f"{cfg['background_brightness']}  brightness={cfg['brightness']}")
        assert cfg["background_brightness"] == 0.05, (
            f"expected the CARRIED value 0.05, got {cfg['background_brightness']}")
        assert cfg["brightness"] == 0.42, (
            f"expected the CARRIED value 0.42, got {cfg['brightness']}")
        print("\n  -> CONFIRMED: the engine-side copy carries forward too.\n")
    finally:
        facade.set_host(None)
        await host.shutdown()


async def part3_bootstrap_has_nothing_to_carry() -> None:
    print("== Part 3: bootstrap (no prior effect) — untouched by design ==")
    # fx/facade.py's own PUT /effects handler 400s outright on a virtual
    # that has never had ANY active effect (fx/virtuals.py: _active_effect
    # defaults to None, and _effects_put refuses `not virtual.active_effect`)
    # — a genuinely-never-fired virtual cannot reach the type-switch branch
    # via the production PUT path at all, so there is no live-wire scenario
    # to drive here. Prove the fallback directly at the unit the fix adds it
    # at instead: current_effect=None (exactly what _current_effect returns
    # for an unknown/inactive virtual) must leave the write untouched.
    original = {"background_color": "#ff9940", "background_mode": "overwrite"}
    carried = fx_seam._carry_forward_brightness(original, None)
    print(f"_carry_forward_brightness(write, current_effect=None) = "
          f"{json.dumps(carried)}")
    assert carried == original, \
        "nothing to carry from None must leave the write byte-identical"
    assert "background_brightness" not in carried and "brightness" not in carried
    print("  -> CONFIRMED: with nothing to carry, the write is untouched — "
          f"the caller's own PUT still lands with LedFX's schema default "
          f"({SCHEMA_DEFAULT_BRIGHTNESS}), unchanged from before this fix.\n")


async def main() -> None:
    write = _pick_real_write()
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        await part1_scene_fire_seam(tmp_dir, write)
    with tempfile.TemporaryDirectory() as tmp_dir:
        await part2_engine_executor(tmp_dir)
    await part3_bootstrap_has_nothing_to_carry()
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
