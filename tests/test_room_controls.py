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
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")


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
    state = rc.RoomControlState(brightness_multiplier=0.6, ambient_mode="always",
                                ambient_color="#ff8800", global_transition_ms=1200)
    rc.save_room_controls(state)
    assert rc.load_room_controls() == state


def test_ambient_enabled_migrates_to_ambient_mode(tmp_path, monkeypatch):
    """One-way migration from the pre-2026-08-15 ambient_enabled bool (§52's
    own field, never merged to master under that name) to the three-setting
    ambient_mode — True maps to "auto" (what True was built and proven to
    mean throughout §52's lifetime), False to "off"."""
    import json
    from spectra import config as scfg
    from spectra.services import room_controls as rc
    path = tmp_path / "room_controls.json"
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", path)

    path.write_text(json.dumps({"ambient_enabled": True, "ambient_color": "#f5da8c"}))
    assert rc.load_room_controls().ambient_mode == "auto"

    path.write_text(json.dumps({"ambient_enabled": False}))
    assert rc.load_room_controls().ambient_mode == "off"

    # A file already on the new field is never touched by the migration.
    path.write_text(json.dumps({"ambient_mode": "always"}))
    assert rc.load_room_controls().ambient_mode == "always"


def test_effective_ambient_color_defers_to_normal_until_dark_colour_authored():
    """His ruling: make the two colours the SAME for now — modeled here as
    ambient_color_dark defaulting to None (defer), not a frozen copy taken
    at some point in time, so they track each other by construction until
    he explicitly picks a different dark colour."""
    from spectra.services import room_controls as rc

    state = rc.RoomControlState(ambient_color="#f5da8c")
    assert rc.effective_ambient_color(state) == "#f5da8c", \
        "dark mode off — the normal/hybrid colour applies"

    dark_state = state.model_copy(update={"display_mode": "dark"})
    assert rc.effective_ambient_color(dark_state) == "#f5da8c", \
        "dark mode on but no dark colour authored yet — still the same value"

    dark_state.ambient_color = "#ff0000"
    assert rc.effective_ambient_color(dark_state) == "#ff0000", \
        "still deferring — tracks the normal colour even after it changes"

    authored = dark_state.model_copy(update={"ambient_color_dark": "#001133"})
    assert rc.effective_ambient_color(authored) == "#001133", \
        "a dark colour has been explicitly picked — it now wins while dark"
    assert rc.effective_ambient_color(authored.model_copy(update={"display_mode": "default"})) \
        == "#ff0000", "dark mode off again — back to the normal colour, dark colour untouched"


def test_ambient_color_dark_round_trips_and_validates_hex():
    from pydantic import ValidationError

    from spectra.services import room_controls as rc

    state = rc.RoomControlState(ambient_color="#f5da8c", ambient_color_dark="#112233")
    rc.save_room_controls(state)
    assert rc.load_room_controls() == state

    with pytest.raises(ValidationError):
        rc.RoomControlState(ambient_color_dark="not-a-colour")


def test_old_room_controls_file_without_dark_colour_loads_with_default_none(tmp_path, monkeypatch):
    """A file written before this field existed has no ambient_color_dark
    key at all — must load cleanly, deferring to the normal colour (no
    explicit migration needed, unlike the renamed ambient_enabled/
    midsong_triggers_enabled fields above)."""
    import json

    from spectra import config as scfg
    from spectra.services import room_controls as rc
    path = tmp_path / "room_controls.json"
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", path)

    path.write_text(json.dumps({"ambient_mode": "always", "ambient_color": "#f5da8c"}))
    loaded = rc.load_room_controls()
    assert loaded.ambient_color_dark is None
    assert rc.effective_ambient_color(loaded) == "#f5da8c"


def test_reconcile_ambient_if_changed_fires_on_dark_colour_edit_while_dark(monkeypatch):
    """Editing ambient_color_dark while dark mode is already on must be
    treated the same as editing ambient_color normally — it changes what's
    actually held."""
    from spectra.services import room_controls as rc

    calls = []

    async def fake_reconcile_now():
        calls.append(True)
        return {"status": "on"}
    monkeypatch.setattr("spectra.services.ambient_music_gate.reconcile_now", fake_reconcile_now)

    previous = rc.RoomControlState(ambient_mode="always", display_mode="dark",
                                   ambient_color="#f5da8c", ambient_color_dark="#001133")
    new_state = previous.model_copy(update={"ambient_color_dark": "#220044"})
    result = _run(rc.reconcile_ambient_if_changed(previous, new_state))
    assert result == {"status": "on"}
    assert calls == [True]


def test_reconcile_ambient_if_changed_ignores_dark_colour_edit_while_not_dark(monkeypatch):
    """The inverse: editing the dark colour while dark mode is OFF changes
    nothing currently held — no reconcile should fire."""
    from spectra.services import room_controls as rc

    calls = []

    async def fake_reconcile_now():
        calls.append(True)
        return {"status": "on"}
    monkeypatch.setattr("spectra.services.ambient_music_gate.reconcile_now", fake_reconcile_now)

    previous = rc.RoomControlState(ambient_mode="always", display_mode="default",
                                   ambient_color="#f5da8c", ambient_color_dark="#001133")
    new_state = previous.model_copy(update={"ambient_color_dark": "#220044"})
    result = _run(rc.reconcile_ambient_if_changed(previous, new_state))
    assert result is None
    assert calls == []


def test_reconcile_ambient_if_changed_fires_when_dark_mode_toggles_while_holding():
    """Toggling dark mode itself, with distinct colours authored, changes
    the effective held colour — reconcile_ambient_if_changed must catch
    this even though ambient_mode/ambient_color themselves didn't move."""
    from spectra.services import room_controls as rc

    previous = rc.RoomControlState(ambient_mode="always", display_mode="default",
                                   ambient_color="#f5da8c", ambient_color_dark="#001133")
    new_state = previous.model_copy(update={"display_mode": "dark"})
    assert rc.effective_ambient_color(previous) != rc.effective_ambient_color(new_state)

    # Same field values, but the dark colour has never been authored (still
    # None) — toggling dark mode changes nothing effective, so this must
    # NOT fire, matching "make them the same for now."
    same_previous = rc.RoomControlState(ambient_mode="always", display_mode="default",
                                        ambient_color="#f5da8c")
    same_new = same_previous.model_copy(update={"display_mode": "dark"})
    assert rc.effective_ambient_color(same_previous) == rc.effective_ambient_color(same_new)


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


def test_force_scene_redirects_every_automatic_pick(monkeypatch):
    """The legacy Now Playing Force Scene control, ported to SPECTRA's one
    scene-fire choke point (scene_sequencer.fire_scene_by_id): while
    enabled, whatever scene id was about to fire is redirected to the
    pinned scene — the sequencer's own rolls and trigger_engine's fire_scene
    action both go through this same function, so one interception covers
    both."""
    from spectra.models.scene import SceneV2
    from spectra.services import room_controls as rc
    from spectra.services import scene_compiler, scene_store
    from spectra.services.scene_sequencer import fire_scene_by_id

    requested = SceneV2(name="Requested")
    held = SceneV2(name="Held")
    scene_store.save(requested)
    scene_store.save(held)

    fired_ids = []

    async def fake_fire_scene(scene, *, intensity=0.5, color_set=None,
                              dry_run=True, rng=None):
        fired_ids.append(scene.id)
        return {"dry_run": dry_run, "intensity": intensity, "writes": [],
                "resolved_bindings": {}, "dice_rolls": {}}

    monkeypatch.setattr(scene_compiler, "fire_scene", fake_fire_scene)

    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id=held.id))
    _run(fire_scene_by_id(requested.id, intensity=0.7))
    assert fired_ids[-1] == held.id, \
        "enabled: the pinned scene fires instead of the one requested"

    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id="does-not-exist"))
    _run(fire_scene_by_id(requested.id, intensity=0.7))
    assert fired_ids[-1] == requested.id, \
        "a pinned id pointing at a missing scene is treated as unset"

    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=False, force_scene_scene_id=held.id))
    _run(fire_scene_by_id(requested.id, intensity=0.7))
    assert fired_ids[-1] == requested.id, \
        "disabled: no redirect even with a scene still picked"
