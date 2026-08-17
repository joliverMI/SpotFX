"""scripts/set_scene_colorset_preference.py — the migration that arms
SceneV2.preferred_color_set_mode="dark" on his four named scenes (Black
Hole V2, Black Hole V2 UI, Fireworks V2, Dancers V2).

The property under test that matters most: the write must be SURGICAL —
only the preferred_color_set_mode key changes, every other field on disk
stays byte-identical. An earlier draft of this script round-tripped scenes
through SceneV2.model_dump_json() and silently rewrote the legacy
flare-band shorthand into canonical flare_kinds storage on every scene it
touched — a far bigger change than "set one field" and exactly what "do
not modify his scenes beyond setting the preference" rules out. This file
locks that regression down."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "set_scene_colorset_preference.py"
_spec = importlib.util.spec_from_file_location("set_scene_colorset_preference", _SCRIPT_PATH)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


NAMES = ["Black Hole V2", "Black Hole V2 UI", "Fireworks V2", "Dancers V2"]


def _raw_scene(name: str, **extra) -> dict:
    # A legacy-shorthand flare band (param_patch/gain), same shape his real
    # scenes carry — the field the earlier draft silently rewrote.
    return {
        "name": name,
        "labels": [],
        "devices": [{"target_kind": "category", "target": "Matrix", "effect_type": "power", "params": {}}],
        "responses": {"flare": {"bands": [
            {"intensity_min": 0.0, "intensity_max": 1.0, "curve": "linear",
             "gain": 1.4, "param_patch": {"spawn_rate": 2.0}},
        ], "reroll_dice": True, "color_set_jump": True}},
        "accept_all_sets": True,
        "accepted_set_ids": [],
        **extra,
    }


def _write_store(path: Path, scenes: dict[str, dict]) -> None:
    store = {f"id-{i}": s for i, s in enumerate(scenes.values())}
    # keep ids stable/discoverable by name in tests
    store = {name.replace(" ", "-").lower(): {**s} for name, s in scenes.items()}
    path.write_text(json.dumps(store, indent=2))


@pytest.fixture()
def scenes_file(tmp_path) -> Path:
    path = tmp_path / "scenes.json"
    scenes = {name: _raw_scene(name) for name in NAMES}
    scenes["Orbits V2"] = _raw_scene("Orbits V2")   # an untouched scene, for the byte-identity check
    _write_store(path, scenes)
    return path


def _run(argv: list[str]) -> None:
    old_argv = sys.argv
    sys.argv = ["set_scene_colorset_preference.py", *argv]
    try:
        migration.main()
    finally:
        sys.argv = old_argv


def test_dry_run_writes_nothing(scenes_file, capsys):
    before = scenes_file.read_text()
    _run(["--scenes-file", str(scenes_file)])
    assert scenes_file.read_text() == before
    assert not (scenes_file.parent / "backups").exists()
    out = capsys.readouterr().out
    assert "DRY RUN" in out


def test_apply_patches_only_the_preference_key_on_named_scenes(scenes_file):
    before = json.loads(scenes_file.read_text())
    _run(["--scenes-file", str(scenes_file), "--apply"])
    after = json.loads(scenes_file.read_text())

    assert set(before) == set(after)
    for sid, raw in before.items():
        diffs = {k for k in set(raw) | set(after[sid]) if raw.get(k) != after[sid].get(k)}
        if raw["name"] in NAMES:
            assert diffs == {"preferred_color_set_mode"}, (raw["name"], diffs)
            assert after[sid]["preferred_color_set_mode"] == "dark"
        else:
            assert diffs == set(), (raw["name"], diffs)   # byte-identical, untouched scene


def test_apply_creates_a_backup_of_the_whole_store(scenes_file):
    before = scenes_file.read_text()
    _run(["--scenes-file", str(scenes_file), "--apply"])
    backups = list((scenes_file.parent / "backups").glob("scenes-preference-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text() == before


def test_apply_is_idempotent(scenes_file):
    _run(["--scenes-file", str(scenes_file), "--apply"])
    once = scenes_file.read_text()
    _run(["--scenes-file", str(scenes_file), "--apply"])
    assert scenes_file.read_text() == once
    # second apply found nothing to change -> no second backup
    backups = list((scenes_file.parent / "backups").glob("scenes-preference-*.json"))
    assert len(backups) == 1


def test_missing_scene_name_refuses_to_guess(tmp_path):
    path = tmp_path / "scenes.json"
    scenes = {n: _raw_scene(n) for n in NAMES if n != "Dancers V2"}
    _write_store(path, scenes)
    with pytest.raises(SystemExit, match="Dancers V2"):
        _run(["--scenes-file", str(path)])


def test_duplicate_scene_name_refuses_to_guess(tmp_path):
    path = tmp_path / "scenes.json"
    store = {}
    for i, name in enumerate(NAMES):
        store[f"id-{i}"] = _raw_scene(name)
    store["dupe"] = _raw_scene("Black Hole V2")
    path.write_text(json.dumps(store, indent=2))
    with pytest.raises(SystemExit, match="Black Hole V2"):
        _run(["--scenes-file", str(path)])
