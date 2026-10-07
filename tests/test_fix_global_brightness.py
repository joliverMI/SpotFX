"""scripts/fix_global_brightness.py — the one-time correction for the
`global_brightness` the go-day seeder copied verbatim from the old LedFX
world (pixel-brightness-chain report, §5/§9: 0.96 dims every fixture 4%
with no UI anywhere in SPECTRA to change it).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT = (Path(__file__).resolve().parent.parent / "scripts"
          / "fix_global_brightness.py")
_spec = importlib.util.spec_from_file_location("fix_global_brightness", _SCRIPT)
fix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fix)


def _config_with(global_brightness):
    return {
        "configuration_version": "1",
        "global_brightness": global_brightness,
        "devices": [{"id": "crystal", "type": "wled", "config": {}}],
        "virtuals": [{"id": "crystal", "config": {}}],
    }


def test_plan_finds_the_stale_value():
    change = fix.plan(_config_with(0.96))
    assert change == {"from": 0.96, "to": 1.0}


def test_plan_is_none_when_already_at_target():
    assert fix.plan(_config_with(1.0)) is None


def test_plan_is_none_with_no_key_at_all():
    raw = _config_with(0.96)
    del raw["global_brightness"]
    assert fix.plan(raw) is None


def test_apply_plan_touches_only_global_brightness():
    raw = _config_with(0.96)
    change = fix.plan(raw)
    out = fix.apply_plan(raw, change)
    assert out["global_brightness"] == 1.0
    # everything else is byte-identical
    assert out["devices"] == raw["devices"]
    assert out["virtuals"] == raw["virtuals"]
    # the input is never mutated in place
    assert raw["global_brightness"] == 0.96


def test_assert_only_global_brightness_changed_catches_a_wider_diff():
    raw = _config_with(0.96)
    bad = json.loads(json.dumps(raw))
    bad["global_brightness"] = 1.0
    bad["devices"] = []  # a second, unplanned change
    try:
        fix.assert_only_global_brightness_changed(raw, bad)
    except AssertionError:
        pass
    else:
        raise AssertionError("expected the wider diff to be refused")


def test_end_to_end_dry_run_leaves_the_file_untouched(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_config_with(0.96)), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["fix_global_brightness.py",
                                     "--config", str(path)])
    rc = fix.main()
    assert rc == 0
    assert json.loads(path.read_text())["global_brightness"] == 0.96


def test_end_to_end_apply_corrects_and_backs_up(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_config_with(0.96)), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["fix_global_brightness.py",
                                     "--config", str(path), "--apply"])
    rc = fix.main()
    assert rc == 0
    corrected = json.loads(path.read_text())
    assert corrected["global_brightness"] == 1.0
    backups = list((tmp_path / "backups").glob("*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text())["global_brightness"] == 0.96


def test_end_to_end_apply_is_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_config_with(1.0)), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["fix_global_brightness.py",
                                     "--config", str(path), "--apply"])
    rc = fix.main()
    assert rc == 0
    assert json.loads(path.read_text())["global_brightness"] == 1.0
    assert not (tmp_path / "backups").exists()
