"""scripts/fix_crystal_brightness_ceiling.py — the one-time correction for
the stored ceiling PR #356's pre-fix adoption bug wrote (house_fixtures.py's
"BRIGHTNESS IS NEVER ADOPTED"): `pre_take["crystal"]["bri"]` left at 255
after the night of the crystal-255 incident.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT = (Path(__file__).resolve().parent.parent / "scripts"
          / "fix_crystal_brightness_ceiling.py")
_spec = importlib.util.spec_from_file_location(
    "fix_crystal_brightness_ceiling", _SCRIPT)
fix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fix)


def _state_with(bri):
    return {
        "mode_id": None,
        "pre_take": {
            "crystal": {"on": True, "bri": bri, "ip": "192.168.40.48",
                       "at_ms": 1759678220656},
            "porch-rail": {"on": True, "bri": 255, "ip": "192.168.40.158",
                          "at_ms": 1759678220596},
        },
    }


def test_plan_finds_the_adopted_overshoot():
    change = fix.plan(_state_with(255))
    assert change == {"device": "crystal", "from": 255, "to": 34}


def test_plan_is_none_when_already_at_or_below_his_real_level():
    assert fix.plan(_state_with(34)) is None
    assert fix.plan(_state_with(10)) is None


def test_plan_is_none_with_no_crystal_entry():
    assert fix.plan({"pre_take": {"porch-rail": {"bri": 255}}}) is None
    assert fix.plan({}) is None


def test_apply_plan_touches_only_crystals_bri():
    raw = _state_with(255)
    change = fix.plan(raw)
    out = fix.apply_plan(raw, change)
    assert out["pre_take"]["crystal"]["bri"] == 34
    # everything else, including crystal's OTHER fields, is byte-identical
    assert out["pre_take"]["crystal"]["on"] is True
    assert out["pre_take"]["crystal"]["ip"] == "192.168.40.48"
    assert out["pre_take"]["porch-rail"] == raw["pre_take"]["porch-rail"]
    # the input is never mutated in place
    assert raw["pre_take"]["crystal"]["bri"] == 255


def test_end_to_end_dry_run_leaves_the_file_untouched(tmp_path, monkeypatch):
    path = tmp_path / "house_state.json"
    path.write_text(json.dumps(_state_with(255)), encoding="utf-8")

    class FakeConfig:
        HOUSE_STATE_FILE = path
    monkeypatch.setattr(fix, "_state_path", lambda: path)
    monkeypatch.setattr("sys.argv", ["fix_crystal_brightness_ceiling.py"])
    rc = fix.main()
    assert rc == 0
    assert json.loads(path.read_text())["pre_take"]["crystal"]["bri"] == 255


def test_end_to_end_apply_corrects_and_backs_up(tmp_path, monkeypatch):
    path = tmp_path / "house_state.json"
    path.write_text(json.dumps(_state_with(255)), encoding="utf-8")
    monkeypatch.setattr(fix, "_state_path", lambda: path)
    monkeypatch.setattr("sys.argv",
                        ["fix_crystal_brightness_ceiling.py", "--apply"])
    rc = fix.main()
    assert rc == 0
    corrected = json.loads(path.read_text())
    assert corrected["pre_take"]["crystal"]["bri"] == 34
    backups = list((tmp_path / "backups").glob("*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text())["pre_take"]["crystal"]["bri"] == 255


def test_end_to_end_apply_is_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "house_state.json"
    path.write_text(json.dumps(_state_with(34)), encoding="utf-8")
    monkeypatch.setattr(fix, "_state_path", lambda: path)
    monkeypatch.setattr("sys.argv",
                        ["fix_crystal_brightness_ceiling.py", "--apply"])
    rc = fix.main()
    assert rc == 0
    assert json.loads(path.read_text())["pre_take"]["crystal"]["bri"] == 34
    assert not (tmp_path / "backups").exists()
