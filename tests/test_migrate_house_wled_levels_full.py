"""D3a's one-time migration (scripts/migrate_house_wled_levels_full.py):
every WLED FIXTURE row's mode levels go to 100% — Hue rows, off rows and
category rows are left alone (the last one named) — and a second run finds
nothing to do. The plan is pure; the I/O is the live service's own routes."""
from __future__ import annotations

from scripts.migrate_house_wled_levels_full import plan_modes

WLEDS = {"crystal", "tv-backlight", "porch-rail"}


def _row(tid, kind="fixture", **kw):
    return {"target": {"kind": kind, "id": tid}, **kw}


def _modes():
    return [
        {"name": "Standard", "fixtures": [
            _row("crystal", level=6.0, motion=0.015, fps=20),
            _row("tv-backlight", level=40.0, music_level=80.0),
            _row("porch-rail", level=100.0),
            _row("hue-lights", level=30.0)]},
        {"name": "Night light", "fixtures": [
            _row("crystal", level=3.0),
            _row("tv-backlight", off=True, level=12.0)]},
        {"name": "Odd", "fixtures": [
            _row("Strips", kind="category", level=50.0)]},
        {"name": "Done", "fixtures": [_row("crystal", level=100.0)]},
    ]


def test_wled_fixture_rows_go_to_full_and_nothing_else_moves():
    to_write, changes, left = plan_modes(_modes(), WLEDS)
    by_name = {m["name"]: m for m in to_write}
    assert set(by_name) == {"Standard", "Night light"}
    std = by_name["Standard"]["fixtures"]
    assert std[0] == _row("crystal", level=100.0, motion=0.015, fps=20)
    assert std[1] == _row("tv-backlight", level=100.0, music_level=100.0)
    assert std[3] == _row("hue-lights", level=30.0), "Hue is not a WLED"
    night = by_name["Night light"]["fixtures"]
    assert night[0]["level"] == 100.0
    assert night[1] == _row("tv-backlight", off=True, level=12.0), "off stays off"
    assert {(c["mode"], c["fixture"], c["field"]) for c in changes} == {
        ("Standard", "crystal", "level"), ("Standard", "tv-backlight", "level"),
        ("Standard", "tv-backlight", "music_level"),
        ("Night light", "crystal", "level")}
    assert [r["mode"] for r in left] == ["Odd"]


def test_the_input_is_never_mutated_and_a_second_run_is_a_no_op():
    modes = _modes()
    before = repr(modes)
    to_write, _changes, _left = plan_modes(modes, WLEDS)
    assert repr(modes) == before
    merged = {m["name"]: m for m in modes}
    merged.update({m["name"]: m for m in to_write})
    again, changes, _ = plan_modes(list(merged.values()), WLEDS)
    assert again == [] and changes == []
