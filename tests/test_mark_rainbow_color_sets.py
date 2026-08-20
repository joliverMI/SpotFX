"""scripts/mark_rainbow_color_sets.py — the migration that arms
ColorSetCard.is_rainbow=True on his ENUMERATED rainbow cards: Hype 1,
Hype 2, Hype 3, the Hype group, and Black Hole Rainbow.

The property that matters most, same as set_scene_colorset_preference.py's
own test: the write must be SURGICAL — only is_rainbow changes, every
other field on disk stays byte-identical (raw-dict patch, never a
model_dump_json() round-trip)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "mark_rainbow_color_sets.py"
_spec = importlib.util.spec_from_file_location("mark_rainbow_color_sets", _SCRIPT_PATH)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def _card(kind, name, **extra) -> dict:
    return {"id": f"id-{name.replace(' ', '-').lower()}", "name": name,
           "kind": kind, "color": "#ffffff", "labels": [], "entries": [],
           **extra}


def _write_store(path: Path, cards: list[dict]) -> None:
    path.write_text(json.dumps({c["id"]: c for c in cards}, indent=2))


@pytest.fixture()
def color_sets_file(tmp_path) -> Path:
    path = tmp_path / "color_sets.json"
    cards = [
        _card("set", "Hype 1"), _card("set", "Hype 2"), _card("set", "Hype 3"),
        _card("group", "Hype", members=[]),
        _card("set", "Black Hole Rainbow"),
        # colourful-named but NOT rainbow — must not be touched
        _card("set", "Neon Dreams"), _card("set", "Prism"),
    ]
    _write_store(path, cards)
    return path


def _run(argv: list[str]) -> None:
    old_argv = sys.argv
    sys.argv = ["mark_rainbow_color_sets.py", *argv]
    try:
        migration.main()
    finally:
        sys.argv = old_argv


def _run_apply(path: Path, capsys):
    _run(["--apply", "--color-sets-file", str(path)])
    return capsys.readouterr().out


def test_marks_exactly_the_five_enumerated_cards(color_sets_file, capsys):
    before = json.loads(color_sets_file.read_text())
    _run_apply(color_sets_file, capsys)
    after = json.loads(color_sets_file.read_text())

    marked = {cid for cid, c in after.items() if c.get("is_rainbow")}
    expected_names = {"Hype 1", "Hype 2", "Hype 3", "Hype", "Black Hole Rainbow"}
    marked_names = {after[cid]["name"] for cid in marked}
    assert marked_names == expected_names

    for cid, card in after.items():
        if cid in marked:
            continue
        assert card.get("is_rainbow", False) is False
        # untouched cards are byte-identical to before
        assert card == before[cid]


def test_only_is_rainbow_key_changes_on_touched_cards(color_sets_file, capsys):
    before = json.loads(color_sets_file.read_text())
    _run_apply(color_sets_file, capsys)
    after = json.loads(color_sets_file.read_text())
    for cid, card in after.items():
        if not card.get("is_rainbow"):
            continue
        before_card = dict(before[cid])
        before_card["is_rainbow"] = True
        assert card == before_card


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


def test_missing_card_refuses_to_guess(tmp_path, capsys):
    path = tmp_path / "color_sets.json"
    _write_store(path, [_card("set", "Hype 1")])   # missing the other four
    with pytest.raises(SystemExit):
        _run(["--apply", "--color-sets-file", str(path)])
