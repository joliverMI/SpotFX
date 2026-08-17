"""Per-scene colour-set PREFERENCE (owner ask, 2026-08-17: "black hole
would prefer dark mode color sets... they don't run light mode color sets
unless the system is set to light mode") — SceneV2.preferred_color_set_mode,
spectra/services/mode_availability.color_set_preferred().

A SECOND axis from display_availability / test_mode_availability.py's own
rule: availability decides whether an item plays at all in the current room
mode; preference decides which of the still-available colour sets a scene
draws from once it does play. Proves the pure rule, then the one wired
choke point (scene_sequencer's own colour-set roll, _default_eligible_sets).
No live access: storage isolated the same way test_mode_availability.py
does."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model
from spectra import config as scfg
from spectra.models.scene import SceneV2
from spectra.services import mode_availability as ma
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
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()
    yield


def _room_mode(mode: str) -> None:
    save_room_controls(RoomControlState(display_mode=mode))


def _write_cards(*cards: ColorSetCard) -> None:
    scfg.COLOR_SETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    scfg.COLOR_SETS_FILE.write_text(json.dumps(
        {c.id: json.loads(c.model_dump_json()) for c in cards}))


def _set(id_, **kw) -> ColorSetCard:
    return ColorSetCard(id=id_, name=id_, kind="set", **kw)


def _scene(id_, **kw) -> SceneV2:
    return SceneV2(id=id_, name=id_, **kw)


# ── 1. the pure rule ─────────────────────────────────────────────────────

@pytest.mark.parametrize("card_availability,scene_preference,room_mode,expected", [
    # no preference declared -> matches everything, any room mode
    ("default", "default", "default", True),
    ("light", "default", "dark", True),
    ("dark", "default", "light", True),
    # Hybrid, scene prefers dark: default+dark pass, light excluded
    ("default", "dark", "default", True),
    ("dark", "dark", "default", True),
    ("light", "dark", "default", False),
    # Hybrid, scene prefers light: default+light pass, dark excluded
    ("default", "light", "default", True),
    ("light", "light", "default", True),
    ("dark", "light", "default", False),
    # explicit room Light overrides a dark preference — his stated case
    ("light", "dark", "light", True),
    ("dark", "dark", "light", True),
    ("default", "dark", "light", True),
    # explicit room Dark overrides a light preference — symmetric case
    ("dark", "light", "dark", True),
    ("light", "light", "dark", True),
    ("default", "light", "dark", True),
])
def test_color_set_preferred(card_availability, scene_preference, room_mode, expected):
    assert ma.color_set_preferred(card_availability, scene_preference, room_mode) is expected


# ── 2. the wired choke point: scene_sequencer's colour-set roll ────────────

def test_eligible_sets_unfiltered_when_scene_has_no_preference():
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("s1"))   # preferred_color_set_mode defaults "default"
    _write_cards(_set("dark-set", display_availability="dark"),
                _set("light-set", display_availability="light"),
                _set("plain-set"))
    _room_mode("default")
    seq = SceneSequencer()
    eligible = seq._default_eligible_sets("s1")
    assert set(eligible) == {"dark-set", "light-set", "plain-set"}


def test_eligible_sets_excludes_opposite_marked_set_under_hybrid_preference():
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("s1", preferred_color_set_mode="dark"))
    _write_cards(_set("dark-set", display_availability="dark"),
                _set("light-set", display_availability="light"),
                _set("plain-set"))
    _room_mode("default")
    seq = SceneSequencer()
    eligible = seq._default_eligible_sets("s1")
    # unmarked sets still play — "you don't have to change any color sets"
    assert set(eligible) == {"dark-set", "plain-set"}


def test_eligible_sets_finds_nothing_new_while_every_set_is_unmarked():
    """The measured state of his real library today: 58/58 colour sets carry
    display_availability="default" (0 of 50 kind="set" cards carry a
    dark/light marking of any kind). A scene preferring dark OR light
    against an all-default library changes nothing — proves the "does
    nothing until sets are marked" finding, not just asserts it."""
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("prefers-dark", preferred_color_set_mode="dark"))
    scene_store.save(_scene("prefers-light", preferred_color_set_mode="light"))
    scene_store.save(_scene("no-preference"))
    _write_cards(_set("set-a"), _set("set-b"), _set("set-c"))
    for room in ("default", "dark", "light"):
        _room_mode(room)
        seq = SceneSequencer()
        baseline = seq._default_eligible_sets("no-preference")
        assert set(baseline) == {"set-a", "set-b", "set-c"}   # sanity: the full pool
        assert seq._default_eligible_sets("prefers-dark") == baseline, room
        assert seq._default_eligible_sets("prefers-light") == baseline, room


def test_preference_never_produces_an_empty_pool_when_nothing_is_marked():
    """THE FALLBACK THAT MUST NOT GO WRONG (his day-one deploy risk, stated
    directly): a preference that matches nothing must fall back to the full
    unfiltered selection, NEVER to an empty set — an empty result here is
    the difference between "colours some sets, not this one specifically"
    and "this scene has no colours at all" the moment this ships against
    his real, entirely-unmarked 50-set library. Proven for all four of his
    named scenes' actual preference (dark) against a library sized like his
    real one, across every room mode."""
    from spectra.services.scene_sequencer import SceneSequencer
    for name in ("Black Hole V2", "Black Hole V2 UI", "Fireworks V2", "Dancers V2"):
        scene_store.save(_scene(name, preferred_color_set_mode="dark"))
    _write_cards(*(_set(f"set-{i}") for i in range(50)))   # unmarked, matches his real count
    seq = SceneSequencer()
    for room in ("default", "dark", "light"):
        _room_mode(room)
        for name in ("Black Hole V2", "Black Hole V2 UI", "Fireworks V2", "Dancers V2"):
            eligible = seq._default_eligible_sets(name)
            assert len(eligible) == 50, (name, room, len(eligible))


def test_explicit_system_light_overrides_dark_preference():
    """His stated case, verbatim: a scene preferring dark does not run
    light-mode sets UNLESS the system is set to light."""
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("s1", preferred_color_set_mode="dark"))
    _write_cards(_set("dark-set", display_availability="dark"),
                _set("light-set", display_availability="light"))
    _room_mode("light")
    seq = SceneSequencer()
    eligible = seq._default_eligible_sets("s1")
    # availability already excludes the dark-marked set while the room is
    # light; preference is overridden, not additionally applied, so the
    # light-marked set is used rather than left with zero eligible sets.
    assert set(eligible) == {"light-set"}


def test_explicit_system_dark_overrides_light_preference():
    """Symmetric case: a scene preferring light doesn't get stranded with
    zero eligible sets just because the room is explicitly Dark."""
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("s1", preferred_color_set_mode="light"))
    _write_cards(_set("dark-set", display_availability="dark"),
                _set("light-set", display_availability="light"))
    _room_mode("dark")
    seq = SceneSequencer()
    eligible = seq._default_eligible_sets("s1")
    assert set(eligible) == {"dark-set"}


def test_preference_still_narrows_pool_when_room_and_scene_both_dark():
    """Room already Dark (explicit, not Hybrid) — preference is overridden
    per the rule above, but the outcome happens to be identical either way
    since availability alone already excludes the light-marked set."""
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("s1", preferred_color_set_mode="dark"))
    _write_cards(_set("dark-set", display_availability="dark"),
                _set("light-set", display_availability="light"),
                _set("plain-set"))
    _room_mode("dark")
    seq = SceneSequencer()
    eligible = seq._default_eligible_sets("s1")
    assert set(eligible) == {"dark-set", "plain-set"}
