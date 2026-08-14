"""SPECTRA room-control surface (spectra-kept-equivalents) — offline proof.

The proofs:
  1. apply_brightness scales brightness/background_brightness uniformly,
     is a no-op at multiplier 1.0, and never mutates its input.
  2. fx_executor (Recording + Facade) applies the room's brightness
     multiplier to every glide/jump write, uniformly — never the caller's
     own baseline bookkeeping (only the recorded/sent params change).
  3. scene_compiler.fire_scene scales only the LIVE bytes sent through
     fx_seam — the returned/baselined writes stay unscaled (dry-run/live
     preview parity) — and falls back to the room's global_transition_ms
     when a scene doesn't author its own entry_ramp_ms.

No LedFX I/O, no audio hardware.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from random import Random

import pytest


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "ROOM_COLOR_FILE", tmp_path / "room_color.json")


def test_apply_brightness_scales_uniformly_and_is_pure():
    from spectra.services import room_controls as rc

    params = {"brightness": 0.8, "background_brightness": 0.4, "speed": 1.0}
    scaled = rc.apply_brightness(params, 0.5)
    assert scaled == {"brightness": 0.4, "background_brightness": 0.2, "speed": 1.0}
    assert params == {"brightness": 0.8, "background_brightness": 0.4, "speed": 1.0}, \
        "apply_brightness must never mutate its input"

    same = rc.apply_brightness(params, 1.0)
    assert same is params, "multiplier 1.0 is a no-op — returns the same object"

    no_brightness = {"speed": 1.0}
    assert rc.apply_brightness(no_brightness, 0.5) is no_brightness, \
        "no brightness keys present — nothing to scale"

    clamped = rc.apply_brightness({"brightness": 0.9}, 2.0)
    assert clamped["brightness"] == 1.0, "scaled brightness clamps to [0, 1]"


def test_room_controls_store_round_trips(tmp_path):
    from spectra.services import room_controls as rc

    assert rc.load_room_controls() == rc.RoomControlState(), \
        "no file yet — defaults (multiplier 1.0, no room dimming)"
    state = rc.RoomControlState(brightness_multiplier=0.6, ambient_enabled=True,
                                ambient_color="#ff8800", global_transition_ms=1200)
    rc.save_room_controls(state)
    assert rc.load_room_controls() == state


def test_fx_executor_applies_room_brightness_multiplier():
    from spectra.services import room_controls as rc
    from spectra.services.fx_executor import RecordingExecutor

    executor = RecordingExecutor(
        room_controls_load=lambda: rc.RoomControlState(brightness_multiplier=0.5))

    async def main():
        await executor.jump("v1", "radial", {"brightness": 0.8, "spin": 3.0})
        await executor.glide("v1", "radial", {"background_brightness": 0.4}, 500)

    _run(main())
    jump, glide = executor.writes
    assert jump["params"] == {"brightness": 0.4, "spin": 3.0}, \
        "brightness scaled, unrelated params untouched"
    assert glide["params"] == {"background_brightness": 0.2}

    default_executor = RecordingExecutor()   # no override — reads the isolated empty store
    _run(default_executor.jump("v1", "radial", {"brightness": 0.8}))
    assert default_executor.writes[0]["params"] == {"brightness": 0.8}, \
        "no room_controls.json on disk — default multiplier 1.0, unchanged"


def test_scene_fire_scales_live_bytes_only_and_falls_back_to_global_transition(monkeypatch):
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services import room_controls as rc
    from spectra.services import scene_compiler

    rc.save_room_controls(rc.RoomControlState(
        brightness_multiplier=0.5, global_transition_ms=1500))

    scene = SceneV2(name="Dimmed", devices=[SceneDeviceConfig(
        target_kind="virtual", target="v1", effect_type="radial",
        params={}, brightness=0.8)])

    captured = {}

    async def fake_apply_writes(writes, *, transition_ms=0):
        captured["writes"] = writes
        captured["transition_ms"] = transition_ms

    def fake_on_scene_fired(scene, writes, set_id):
        captured["baselined_writes"] = writes

    monkeypatch.setattr(scene_compiler.fx_seam, "apply_writes", fake_apply_writes)
    monkeypatch.setattr("spectra.services.engine.on_scene_fired", fake_on_scene_fired)

    result = _run(scene_compiler.fire_scene(scene, dry_run=False))

    assert result["writes"][0]["config"]["brightness"] == 0.8, \
        "returned/preview writes stay UNSCALED — dry-run/live parity"
    assert captured["baselined_writes"][0]["config"]["brightness"] == 0.8, \
        "the engine baselines from the authored (unscaled) value"
    assert captured["writes"][0]["config"]["brightness"] == 0.4, \
        "only the bytes actually sent through fx_seam are room-scaled"
    assert captured["transition_ms"] == 1500, \
        "scene has no entry_ramp_ms of its own — falls back to global_transition_ms"

    scene.entry_ramp_ms = 300
    _run(scene_compiler.fire_scene(scene, dry_run=False))
    assert captured["transition_ms"] == 300, \
        "a scene's own entry_ramp_ms wins over the room's global default"
