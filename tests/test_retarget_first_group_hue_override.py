"""scripts/retarget_first_group_hue_override.py — the migration that
retargets "First Group"'s Hue-category colour-set override onto the live
`hues` virtual (pixel-brightness-chain report, §6/§9).

Same discipline as test_mark_rainbow_color_sets.py: the write must be
SURGICAL — only the one entry's `scope` changes, every other field on
disk (including the entry's own brightness/background_brightness values
and every OTHER group) stays byte-identical.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_SCRIPT_PATH = (Path(__file__).resolve().parent.parent / "scripts"
               / "retarget_first_group_hue_override.py")
_spec = importlib.util.spec_from_file_location(
    "retarget_first_group_hue_override", _SCRIPT_PATH)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def _first_group_card(**overrides) -> dict:
    card = {
        "id": "id-first-group",
        "name": "First Group",
        "kind": "group",
        "color": "#ffffff",
        "labels": [],
        "members": [{"color_set_id": "id-mid-purple", "weight": 1.0}],
        "entries": [
            {
                "scope": {"virtual_ids": [], "categories": ["Hue"], "roles": []},
                "brightness": 0.72,
                "background_brightness": 0.5,
            },
            {
                "scope": {"virtual_ids": [], "categories": ["Strips", "Matrix"],
                          "roles": []},
                "bg_mode": "overwrite",
                "background_brightness": 0.05,
            },
        ],
    }
    card.update(overrides)
    return card


def _other_group_card() -> dict:
    return {
        "id": "id-lines",
        "name": "Lines",
        "kind": "group",
        "color": "#ffffff",
        "labels": [],
        "members": [],
        "entries": [
            {
                "scope": {"virtual_ids": ["hues"], "categories": [], "roles": []},
                "brightness": 0.3,
                "background_brightness": 0.3,
            },
        ],
    }


def _write_store(path: Path, cards: list[dict]) -> None:
    path.write_text(json.dumps({c["id"]: c for c in cards}, indent=2))


@pytest.fixture()
def color_sets_file(tmp_path) -> Path:
    path = tmp_path / "color_sets.json"
    _write_store(path, [_first_group_card(), _other_group_card()])
    return path


def _run(argv: list[str]) -> None:
    old_argv = sys.argv
    sys.argv = ["retarget_first_group_hue_override.py", *argv]
    try:
        migration.main()
    finally:
        sys.argv = old_argv


def _run_apply(path: Path, capsys):
    _run(["--apply", "--color-sets-file", str(path)])
    return capsys.readouterr().out


def test_retargets_only_the_hue_scoped_entry(color_sets_file, capsys):
    before = json.loads(color_sets_file.read_text())
    _run_apply(color_sets_file, capsys)
    after = json.loads(color_sets_file.read_text())

    patched_entry = after["id-first-group"]["entries"][0]
    assert patched_entry["scope"]["categories"] == []
    assert patched_entry["scope"]["virtual_ids"] == ["hues"]
    # values untouched
    assert patched_entry["brightness"] == 0.72
    assert patched_entry["background_brightness"] == 0.5

    # the OTHER entry on the same card is byte-identical
    assert after["id-first-group"]["entries"][1] == before["id-first-group"]["entries"][1]
    # the card's non-entries fields are byte-identical
    for key in ("id", "name", "kind", "color", "labels", "members"):
        assert after["id-first-group"][key] == before["id-first-group"][key]
    # the OTHER group is completely untouched
    assert after["id-lines"] == before["id-lines"]


def test_idempotent_second_run_reports_nothing_to_do(color_sets_file, capsys):
    _run_apply(color_sets_file, capsys)
    after_first = json.loads(color_sets_file.read_text())
    _run_apply(color_sets_file, capsys)
    after_second = json.loads(color_sets_file.read_text())
    assert after_first == after_second


def test_dry_run_writes_nothing(color_sets_file, capsys):
    before = color_sets_file.read_text()
    _run(["--color-sets-file", str(color_sets_file)])
    assert color_sets_file.read_text() == before


def test_missing_group_refuses_to_guess(tmp_path, capsys):
    path = tmp_path / "color_sets.json"
    _write_store(path, [_other_group_card()])
    with pytest.raises(SystemExit):
        _run(["--apply", "--color-sets-file", str(path)])


def test_ambiguous_group_name_refuses_to_guess(tmp_path, capsys):
    path = tmp_path / "color_sets.json"
    dup = _first_group_card(id="id-first-group-dup")
    _write_store(path, [_first_group_card(), dup])
    with pytest.raises(SystemExit):
        _run(["--apply", "--color-sets-file", str(path)])


def test_no_hue_scoped_entry_refuses_to_guess(tmp_path, capsys):
    path = tmp_path / "color_sets.json"
    card = _first_group_card()
    card["entries"] = [card["entries"][1]]   # drop the Hue-scoped entry
    _write_store(path, [card])
    with pytest.raises(SystemExit):
        _run(["--apply", "--color-sets-file", str(path)])


def test_drifted_values_refuse_to_guess(tmp_path, capsys):
    path = tmp_path / "color_sets.json"
    card = _first_group_card()
    card["entries"][0]["brightness"] = 0.9  # someone already changed it
    _write_store(path, [card])
    with pytest.raises(SystemExit):
        _run(["--apply", "--color-sets-file", str(path)])
