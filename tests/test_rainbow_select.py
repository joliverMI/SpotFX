"""Rainbow select (owner ask 2026-08-20, spectra/services/rainbow_select.py)
— a colour set/group carries is_rainbow (ENUMERATED, never inferred); above
RoomControlState.rainbow_select_limit only rainbow-marked cards are
eligible, at or below it only single (non-rainbow) cards are. Wired into
scene_sequencer._default_eligible_sets, the same automatic-selection choke
point mode_availability/color_set_preferred already reach."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model
from spectra import config as scfg
from spectra.models.scene import SceneV2
from spectra.services import color_sets
from spectra.services import rainbow_select as rs
from spectra.services import scene_store
from spectra.services.color_sets import ColorSetCard
from spectra.services.room_controls import RoomControlState, save_room_controls


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
    yield


def _write_cards(*cards: ColorSetCard) -> None:
    scfg.COLOR_SETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    scfg.COLOR_SETS_FILE.write_text(json.dumps(
        {c.id: json.loads(c.model_dump_json()) for c in cards}))


def _set(id_, **kw) -> ColorSetCard:
    return ColorSetCard(id=id_, name=id_, kind="set", **kw)


def _scene(id_, **kw) -> SceneV2:
    return SceneV2(id=id_, name=id_, **kw)


# ── the pure rule ────────────────────────────────────────────────────────────

def test_above_limit_only_rainbow_eligible():
    assert rs.eligible(True, 0.95, 0.9) is True
    assert rs.eligible(False, 0.95, 0.9) is False


def test_at_or_below_limit_only_single_eligible():
    assert rs.eligible(False, 0.9, 0.9) is True
    assert rs.eligible(True, 0.9, 0.9) is False
    assert rs.eligible(False, 0.1, 0.9) is True
    assert rs.eligible(True, 0.1, 0.9) is False


def test_partition_is_exclusive_never_both_never_neither():
    for intensity in (0.0, 0.3, 0.5, 0.89, 0.9, 0.91, 1.0):
        for limit in (0.0, 0.5, 0.9, 1.0):
            rainbow_ok = rs.eligible(True, intensity, limit)
            single_ok = rs.eligible(False, intensity, limit)
            assert rainbow_ok != single_ok


# ── wired into scene_sequencer._default_eligible_sets ───────────────────────

def test_eligible_sets_excludes_rainbow_above_limit_by_default_room_state():
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("s1"))
    _write_cards(_set("rainbow-set", is_rainbow=True), _set("single-set"))
    save_room_controls(RoomControlState())   # rainbow_select_limit default 0.9
    seq = SceneSequencer(intensity=lambda: 0.5)   # <= 0.9 -> single only
    eligible = seq._default_eligible_sets("s1")
    assert "single-set" in eligible
    assert "rainbow-set" not in eligible


def test_eligible_sets_includes_only_rainbow_above_limit():
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("s1"))
    _write_cards(_set("rainbow-set", is_rainbow=True), _set("single-set"))
    save_room_controls(RoomControlState(rainbow_select_limit=0.9))
    seq = SceneSequencer(intensity=lambda: 0.95)   # > 0.9 -> rainbow only
    eligible = seq._default_eligible_sets("s1")
    assert "rainbow-set" in eligible
    assert "single-set" not in eligible


def test_custom_rainbow_limit_is_honored():
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("s1"))
    _write_cards(_set("rainbow-set", is_rainbow=True), _set("single-set"))
    save_room_controls(RoomControlState(rainbow_select_limit=0.3))
    seq = SceneSequencer(intensity=lambda: 0.5)   # > 0.3 -> rainbow only
    eligible = seq._default_eligible_sets("s1")
    assert "rainbow-set" in eligible
    assert "single-set" not in eligible


def test_groups_never_become_candidates_here_regardless_of_is_rainbow():
    from spectra.services.scene_sequencer import SceneSequencer
    from spectra.services.color_sets import GroupMember
    scene_store.save(_scene("s1"))
    group = ColorSetCard(id="g1", name="g1", kind="group", is_rainbow=True,
                         members=[GroupMember(color_set_id="single-set")])
    _write_cards(_set("single-set"), group)
    save_room_controls(RoomControlState())
    seq = SceneSequencer(intensity=lambda: 0.95)
    eligible = seq._default_eligible_sets("s1")
    assert "g1" not in eligible   # groups are never selector candidates
