"""Per-item display-mode availability (owner ask, 2026-08-17,
spectra/services/mode_availability.py) — scenes, colour sets, and colour
groups each carry display_availability: "default" | "dark" | "light".

  item="light"   available while the room is light or default/hybrid,
                 skipped while the room is dark.
  item="dark"    available while the room is dark or default/hybrid,
                 skipped while the room is light.
  item="default" always available.

Proves the pure rule, then every automatic enforcement point: the scene
sequencer's own roll + colour-set roll, its central fire_scene_by_id gate
(scene- and colour-set-level, with Force Scene exempted), colour group
member picking, and trigger_engine's generated-trigger scene/select_color_set
paths. No live access: storage isolated the same way test_color_set_groups.py
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
from spectra.services import color_set_groups as csg
from spectra.services import color_sets
from spectra.services import mode_availability as ma
from spectra.services import scene_store
from spectra.services.color_sets import ColorSetCard, GroupMember
from spectra.services.room_controls import RoomControlState, save_room_controls


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
    csg._cursor.clear()
    csg._cursor_dir.clear()
    yield
    csg._cursor.clear()
    csg._cursor_dir.clear()


def _room_mode(mode: str) -> None:
    save_room_controls(RoomControlState(display_mode=mode))


def _write_cards(*cards: ColorSetCard) -> None:
    scfg.COLOR_SETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    scfg.COLOR_SETS_FILE.write_text(json.dumps(
        {c.id: json.loads(c.model_dump_json()) for c in cards}))


def _set(id_, **kw) -> ColorSetCard:
    return ColorSetCard(id=id_, name=id_, kind="set", **kw)


def _group(id_, member_ids, **kw) -> ColorSetCard:
    return ColorSetCard(id=id_, name=id_, kind="group",
                        members=[GroupMember(color_set_id=m) for m in member_ids], **kw)


def _scene(id_, **kw) -> SceneV2:
    return SceneV2(id=id_, name=id_, **kw)


# ── 1. the pure rule ────────────────────────────────────────────────────────

@pytest.mark.parametrize("item,room,expected", [
    ("default", "default", True),
    ("default", "dark", True),
    ("default", "light", True),
    ("light", "default", True),
    ("light", "light", True),
    ("light", "dark", False),
    ("dark", "default", True),
    ("dark", "dark", True),
    ("dark", "light", False),
])
def test_available_in_room_mode(item, room, expected):
    assert ma.available_in_room_mode(item, room) is expected


# ── 2. fire_scene_by_id — the central scene gate ────────────────────────────

def test_fire_scene_by_id_skips_light_only_scene_while_dark():
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("s1", display_availability="light"))
    _room_mode("dark")
    result = _run(fire_scene_by_id("s1"))
    assert result == {"skipped": "mode_availability", "scene_id": "s1", "scene_name": "s1"}


def test_fire_scene_by_id_fires_light_only_scene_while_light_or_hybrid():
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("s1", display_availability="light"))
    for mode in ("light", "default"):
        _room_mode(mode)
        result = _run(fire_scene_by_id("s1"))
        assert "skipped" not in result, mode


def test_fire_scene_by_id_skips_dark_only_scene_while_light():
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("s1", display_availability="dark"))
    _room_mode("light")
    result = _run(fire_scene_by_id("s1"))
    assert result["skipped"] == "mode_availability"


def test_force_scene_bypasses_mode_availability(monkeypatch):
    from spectra.services import scene_compiler
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("pinned", display_availability="light"))
    scene_store.save(_scene("requested", display_availability="default"))
    _room_mode("dark")
    save_room_controls(RoomControlState(display_mode="dark", force_scene_enabled=True,
                                        force_scene_scene_id="pinned"))

    fired_ids: list[str] = []

    async def fake_fire_scene(scene, **kw):
        fired_ids.append(scene.id)
        return {"dry_run": False, "intensity": kw.get("intensity", 0.5), "writes": []}

    monkeypatch.setattr(scene_compiler, "fire_scene", fake_fire_scene)
    result = _run(fire_scene_by_id("requested"))
    assert "skipped" not in result
    assert fired_ids == ["pinned"]


def test_fire_scene_by_id_falls_back_to_active_set_when_color_set_mode_gated():
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(_scene("s1"))
    _write_cards(_set("light-set", display_availability="light"))
    _room_mode("dark")
    result = _run(fire_scene_by_id("s1", color_set_id="light-set"))
    assert "skipped" not in result   # scene itself is default/always available


# ── 3. scene_sequencer's own roll: candidate pool is pre-filtered ──────────

def test_roll_never_picks_a_mode_unavailable_scene():
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("light-only", display_availability="light"))
    scene_store.save(_scene("always"))
    _room_mode("dark")

    fired: list[str] = []

    async def fake_fire(scene_id, color_set_id, intensity):
        fired.append(scene_id)

    seq = SceneSequencer(fire=fake_fire, intensity=lambda: 0.5,
                         deferral_fn=lambda: None, genre_bucket=lambda: None,
                         trigger_scene_id=lambda: None)
    from spectra.services import sequencer_store
    cfg = sequencer_store.load_config()
    from spectra.models.sequencer import SelectorEntry
    cfg.entries = {"light-only": SelectorEntry(), "always": SelectorEntry()}
    sequencer_store.save_config(cfg)

    for _ in range(20):
        _run(seq._roll(cfg, "test"))
    assert fired, "expected at least one fire across 20 rolls"
    assert set(fired) == {"always"}, fired


# ── 4. colour-set roll: eligible_sets excludes mode-gated sets ─────────────

def test_default_eligible_sets_excludes_mode_gated_sets():
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("s1"))
    _write_cards(_set("light-set", display_availability="light"),
                _set("always-set"))
    _room_mode("dark")
    seq = SceneSequencer()
    eligible = seq._default_eligible_sets("s1")
    assert "light-set" not in eligible
    assert "always-set" in eligible


# ── 5. colour group member picking ──────────────────────────────────────────

def test_group_member_pick_skips_mode_unavailable_members():
    _write_cards(
        _set("dark-member", display_availability="dark"),
        _set("always-member"),
        _group("g1", ["dark-member", "always-member"]))
    _room_mode("light")
    group = color_sets.get_by_id("g1")
    picks = {csg._pick_member(group) for _ in range(5)}
    assert picks == {"always-member"}


def test_group_becomes_unusable_when_every_member_is_mode_gated():
    _write_cards(
        _set("dark-member", display_availability="dark"),
        _group("g1", ["dark-member"]))
    _room_mode("light")
    group = color_sets.get_by_id("g1")
    assert csg._pick_member(group) is None
    assert csg.resolve_for_fire(group) is None


def test_group_card_itself_gated_before_member_substitution():
    _write_cards(
        _set("m1"),
        _group("g1", ["m1"], display_availability="light"))
    group = color_sets.get_by_id("g1")
    assert csg.resolve_for_fire_mode_gated(group, "dark") is None
    assert csg.resolve_for_fire_mode_gated(group, "light") is not None


# ── 6. trigger_engine parity ────────────────────────────────────────────────

def test_trigger_engine_select_scene_never_picks_mode_unavailable():
    from spectra.services.trigger_engine import TriggerEngine
    from spectra.models.sequencer import SelectorEntry
    scene_store.save(_scene("light-only", display_availability="light"))
    scene_store.save(_scene("always"))
    _room_mode("dark")
    from spectra.services import sequencer_store
    cfg = sequencer_store.load_config()
    cfg.entries = {"light-only": SelectorEntry(), "always": SelectorEntry()}
    sequencer_store.save_config(cfg)

    te = TriggerEngine()
    picks = {te._default_select_scene(0.5) for _ in range(20)}
    assert picks <= {"always", None}


def test_trigger_engine_select_color_set_skips_mode_unavailable(monkeypatch):
    from spectra.services.trigger_engine import TriggerEngine
    _write_cards(_set("dark-set", display_availability="dark"))
    _room_mode("light")

    applied = []

    class FakeConductor:
        async def apply_set_directly(self, card):
            applied.append(card.id)

    from spectra.services import engine as engine_mod
    monkeypatch.setattr(engine_mod, "conductor", FakeConductor())

    te = TriggerEngine()
    _run(te._default_select_color_set("dark-set"))
    assert applied == []


def test_trigger_engine_select_color_set_applies_available_set(monkeypatch):
    from spectra.services.trigger_engine import TriggerEngine
    _write_cards(_set("dark-set", display_availability="dark"))
    _room_mode("dark")

    applied = []

    class FakeConductor:
        async def apply_set_directly(self, card):
            applied.append(card.id)

    from spectra.services import engine as engine_mod
    monkeypatch.setattr(engine_mod, "conductor", FakeConductor())

    te = TriggerEngine()
    _run(te._default_select_color_set("dark-set"))
    assert applied == ["dark-set"]
