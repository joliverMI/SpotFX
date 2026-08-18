"""Temporary scene disable (owner ask, 2026-08-18: "add an ability to
disable a scene temporarily", spectra/models/scene.py's SceneV2.disabled).

Reading: a manual, reversible toggle — not a timer/expiry. Proves:
  1. the field itself (default False, every existing scene loads unaffected)
  2. fire_scene_by_id's hard gate — skipped="disabled", checked BEFORE mode
     availability (the stronger, more explicit statement wins the reason)
  3. Force Scene still fires a disabled pinned scene (an explicit pin always
     wins) but the result — and reconcile_force_scene_if_changed's own
     result — NAME the override rather than silently applying it
  4. the sequencer's own roll never picks a disabled scene from its
     candidate pool
  5. trigger_engine's generated-trigger scene draw never picks one either
  6. a manual editor test-fire (POST /scenes/{id}/fire → scene_compiler.
     fire_scene directly) bypasses the gate entirely — same "explicit human
     action skips automatic gating" convention display_availability already
     established

No live access — storage isolated the same way test_mode_availability.py
does."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model
from spectra import config as scfg
from spectra.models.scene import SceneV2
from spectra.services import room_controls as rc
from spectra.services import scene_store


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    monkeypatch.setattr(scfg, "ROOM_COLOR_FILE", tmp_path / "room_color.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "FIRE_HISTORY_FILE", tmp_path / "fire_history.json")
    monkeypatch.setattr(scfg, "SHOW_LOG_FILE", tmp_path / "show_log.json")
    monkeypatch.setattr(scfg, "SEQUENCER_FILE", tmp_path / "sequencer.json")
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()


def _scene(id_, **kw) -> SceneV2:
    return SceneV2(id=id_, name=id_, **kw)


# ── 1. the field ─────────────────────────────────────────────────────────

def test_disabled_defaults_false_and_legacy_scenes_load_unaffected():
    s = SceneV2(name="Legacy")
    assert s.disabled is False
    # A scene stored before this field existed has no "disabled" key at all.
    loaded = SceneV2(**{"name": "Old", "id": "old"})
    assert loaded.disabled is False


# ── 2. fire_scene_by_id — the central scene gate ───────────────────────────

def test_fire_scene_by_id_skips_a_disabled_scene():
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("s1", disabled=True))
    result = _run(fire_scene_by_id("s1"))
    assert result == {"skipped": "disabled", "scene_id": "s1", "scene_name": "s1"}


def test_fire_scene_by_id_fires_a_reenabled_scene():
    from spectra.services.scene_sequencer import fire_scene_by_id
    from spectra.services import scene_compiler
    scene_store.save(_scene("s1", disabled=False))
    result = _run(fire_scene_by_id("s1"))
    assert "skipped" not in result


def test_disabled_wins_over_mode_availability_in_the_reported_reason(monkeypatch):
    """A scene that is BOTH disabled and mode-gated must report the
    stronger, more explicit reason — disabled, not mode_availability."""
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("s1", disabled=True, display_availability="light"))
    rc.save_room_controls(rc.RoomControlState(display_mode="dark"))
    result = _run(fire_scene_by_id("s1"))
    assert result["skipped"] == "disabled"


def test_force_scene_overrides_a_disabled_pinned_scene_and_says_so(monkeypatch):
    from spectra.services import scene_compiler
    from spectra.services.scene_sequencer import fire_scene_by_id

    scene_store.save(_scene("pinned", disabled=True))
    scene_store.save(_scene("requested"))
    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id="pinned"))

    fired_ids: list[str] = []

    async def fake_fire_scene(scene, **kw):
        fired_ids.append(scene.id)
        return {"dry_run": False, "intensity": kw.get("intensity", 0.5), "writes": []}

    monkeypatch.setattr(scene_compiler, "fire_scene", fake_fire_scene)
    result = _run(fire_scene_by_id("requested"))
    assert fired_ids == ["pinned"], "the pin wins — an explicit act in the moment"
    assert result.get("overrode_disabled") is True, \
        "the override must be NAMED, not silently applied"


def test_force_scene_does_not_flag_override_when_pinned_scene_is_enabled(monkeypatch):
    from spectra.services import scene_compiler
    from spectra.services.scene_sequencer import fire_scene_by_id

    scene_store.save(_scene("pinned", disabled=False))
    rc.save_room_controls(rc.RoomControlState(
        force_scene_enabled=True, force_scene_scene_id="pinned"))

    async def fake_fire_scene(scene, **kw):
        return {"dry_run": False, "intensity": 0.5, "writes": []}

    monkeypatch.setattr(scene_compiler, "fire_scene", fake_fire_scene)
    result = _run(fire_scene_by_id("requested-does-not-matter"))
    assert "overrode_disabled" not in result


# ── 3. the sequencer's own roll: candidate pool is pre-filtered ────────────

def test_roll_never_picks_a_disabled_scene():
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("off", disabled=True))
    scene_store.save(_scene("on"))

    fired: list[str] = []

    async def fake_fire(scene_id, color_set_id, intensity):
        fired.append(scene_id)

    seq = SceneSequencer(fire=fake_fire, intensity=lambda: 0.5,
                         deferral_fn=lambda: None, genre_bucket=lambda: None,
                         trigger_scene_id=lambda: None)
    from spectra.services import sequencer_store
    cfg = sequencer_store.load_config()
    from spectra.models.sequencer import SelectorEntry
    cfg.entries = {"off": SelectorEntry(), "on": SelectorEntry()}
    sequencer_store.save_config(cfg)

    for _ in range(20):
        _run(seq._roll(cfg, "test"))
    assert fired, "expected at least one fire across 20 rolls"
    assert set(fired) == {"on"}, fired


def test_default_scene_enabled_reflects_the_stored_field():
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("off", disabled=True))
    scene_store.save(_scene("on", disabled=False))
    seq = SceneSequencer()
    assert seq._default_scene_enabled("off") is False
    assert seq._default_scene_enabled("on") is True
    assert seq._default_scene_enabled("does-not-exist") is True, \
        "an unknown scene id is never the disable gate's business to veto"


# ── 4. trigger_engine's generated-trigger scene draw ────────────────────────

def test_trigger_engine_select_scene_never_draws_a_disabled_scene():
    from spectra.services.trigger_engine import TriggerEngine
    from spectra.services import sequencer_store
    from spectra.models.sequencer import SelectorEntry

    scene_store.save(_scene("off", disabled=True))
    scene_store.save(_scene("on"))
    cfg = sequencer_store.load_config()
    cfg.entries = {"off": SelectorEntry(), "on": SelectorEntry()}
    sequencer_store.save_config(cfg)

    engine = TriggerEngine()
    for _ in range(20):
        picked = engine._default_select_scene(0.5)
        assert picked != "off", "a disabled scene must never be drawn"


# ── 5. manual test-fire bypasses the gate (explicit human action) ──────────

def test_manual_editor_fire_bypasses_disabled(monkeypatch):
    """POST /scenes/{id}/fire calls scene_compiler.fire_scene directly,
    never fire_scene_by_id — same bypass display_availability already has."""
    from spectra.services import scene_compiler
    scene = _scene("s1", disabled=True)
    scene_store.save(scene)
    result = _run(scene_compiler.fire_scene(scene, intensity=0.5, dry_run=True))
    assert "skipped" not in result
