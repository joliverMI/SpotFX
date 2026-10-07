"""scripts/repair_stale_wled_device_names.py — the one-time catch-up for
the four device names the pre-#53 bug in fx/devices/wled.py's
async_initialize() clobbered back to the firmware default "WLED" before
the fix landed.

Only the four named device ids are touched, and only when their stored
`config.name` is currently exactly the stale "WLED" — a device already
renamed to something else, or genuinely unnamed, is left alone. The
written config is asserted SEMANTICALLY identical to the original except
the planned renames.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parent.parent / "scripts"
           / "repair_stale_wled_device_names.py")
_spec = importlib.util.spec_from_file_location(
    "repair_stale_wled_device_names", _SCRIPT)
repair = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repair)


def _device(device_id: str, name: str, **extra_config) -> dict:
    cfg = {"name": name, "pixel_count": 30}
    cfg.update(extra_config)
    return {"id": device_id, "type": "wled", "config": cfg}


def _config() -> dict:
    """His real four plus controls: an already-renamed one, an unrelated
    device that genuinely ships named "WLED" (a device id not in his four),
    and a device with no name at all."""
    return {
        "configuration_version": 1,
        "devices": [
            _device("crystal", "WLED"),
            _device("tv-backlight", "WLED"),
            _device("dining-table", "Dining Table"),
            _device("porch-rail", "WLED"),
            _device("some-other-wled", "WLED"),
            {"id": "no-name-yet", "type": "wled", "config": {}},
        ],
        "virtuals": [{"id": "crystal", "is_device": "crystal"}],
    }


def _write(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))


def _run(monkeypatch, path: Path, *flags: str) -> int:
    monkeypatch.setattr("sys.argv", [str(_SCRIPT), "--config", str(path),
                                     *flags])
    return repair.main()


def test_only_the_four_named_devices_at_the_stale_name_are_found():
    stale = repair.find_stale(_config()["devices"])
    by_id = {s["id"]: s for s in stale}
    assert set(by_id) == {"crystal", "tv-backlight", "porch-rail"}
    assert by_id["crystal"]["target"] == "Crystal"
    assert by_id["tv-backlight"]["target"] == "TV Backlight"
    assert by_id["porch-rail"]["target"] == "Porch Rail"


def test_an_already_renamed_device_is_left_alone(tmp_path, monkeypatch,
                                                 capsys):
    config = _config()
    config["devices"] = [d for d in config["devices"]
                         if d["id"] in ("crystal", "dining-table")]
    path = tmp_path / "fx" / "config.json"
    _write(path, config)
    assert _run(monkeypatch, path, "--apply") == 0
    written = json.loads(path.read_text())
    names = {d["id"]: d["config"]["name"] for d in written["devices"]}
    assert names["crystal"] == "Crystal"
    assert names["dining-table"] == "Dining Table"


def test_the_fix_and_the_repair_together_make_a_rename_stick(tmp_path,
                                                              monkeypatch,
                                                              capsys):
    """Through the real write path: apply the repair, then run the real
    (fixed) async_initialize-style rule and confirm the now-correct name
    is left untouched — the scenario #53 alone cannot close."""
    path = tmp_path / "fx" / "config.json"
    _write(path, _config())
    original = json.loads(path.read_text())

    assert _run(monkeypatch, path, "--apply") == 0
    out = capsys.readouterr().out
    assert "wrote" in out
    assert "crystal" in out and "tv-backlight" in out and "porch-rail" in out

    written = json.loads(path.read_text())
    by_id = {d["id"]: d for d in written["devices"]}
    assert by_id["crystal"]["config"]["name"] == "Crystal"
    assert by_id["tv-backlight"]["config"]["name"] == "TV Backlight"
    assert by_id["porch-rail"]["config"]["name"] == "Porch Rail"
    assert by_id["dining-table"]["config"]["name"] == "Dining Table"
    assert by_id["some-other-wled"]["config"]["name"] == "WLED", (
        "a device outside his four named ones is never touched, even at "
        "the stale default")
    assert by_id["no-name-yet"]["config"].get("name") is None

    repair.assert_only_planned_name_changes(
        original, written,
        {"crystal": "Crystal", "tv-backlight": "TV Backlight",
         "porch-rail": "Porch Rail"})

    backups = list((tmp_path / "fx" / "backups").glob(
        "config-wled-names-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == original

    # The #53 rule itself: a reported firmware name only fills in a
    # currently-falsy stored name — the now-genuinely-set "Crystal" must
    # survive a simulated restart unconditionally.
    for device_id in ("crystal", "tv-backlight", "porch-rail", "dining-table"):
        stored_config = by_id[device_id]["config"]
        if not stored_config.get("name"):
            stored_config["name"] = "WLED"
    assert by_id["crystal"]["config"]["name"] == "Crystal"
    assert by_id["tv-backlight"]["config"]["name"] == "TV Backlight"
    assert by_id["porch-rail"]["config"]["name"] == "Porch Rail"


def test_dry_run_writes_nothing_and_names_the_three(tmp_path, monkeypatch,
                                                     capsys):
    path = tmp_path / "fx" / "config.json"
    _write(path, _config())
    raw = path.read_bytes()
    assert _run(monkeypatch, path) == 0
    assert path.read_bytes() == raw
    assert not (tmp_path / "fx" / "backups").exists()
    out = capsys.readouterr().out
    assert "dry-run: would set 3 device name(s)" in out
    assert "crystal" in out and "tv-backlight" in out and "porch-rail" in out
    assert "dining-table" not in out
    assert "some-other-wled" not in out


def test_the_repair_is_idempotent(tmp_path, monkeypatch, capsys):
    path = tmp_path / "fx" / "config.json"
    _write(path, _config())
    assert _run(monkeypatch, path, "--apply") == 0
    first = path.read_bytes()
    capsys.readouterr()
    assert _run(monkeypatch, path, "--apply") == 0
    assert "nothing to correct" in capsys.readouterr().out
    assert path.read_bytes() == first
    backups = list((tmp_path / "fx" / "backups").glob("*.json"))
    assert len(backups) == 1


def test_a_config_with_no_stale_names_is_left_alone(tmp_path, monkeypatch,
                                                     capsys):
    config = _config()
    for d in config["devices"]:
        if d["id"] in repair.FRIENDLY_NAMES:
            d["config"]["name"] = repair.FRIENDLY_NAMES[d["id"]]
    path = tmp_path / "fx" / "config.json"
    _write(path, config)
    raw = path.read_bytes()
    assert _run(monkeypatch, path, "--apply") == 0
    assert "nothing to correct" in capsys.readouterr().out
    assert path.read_bytes() == raw


def test_the_written_diff_guard_refuses_anything_but_the_plan():
    original = _config()
    planned = {"crystal": "Crystal", "tv-backlight": "TV Backlight",
              "porch-rail": "Porch Rail"}
    good = copy.deepcopy(original)
    for d in good["devices"]:
        if d["id"] in planned:
            d["config"]["name"] = planned[d["id"]]
    repair.assert_only_planned_name_changes(original, good, planned)

    stray = copy.deepcopy(good)
    next(d for d in stray["devices"]
         if d["id"] == "dining-table")["config"]["name"] = "Something Else"
    with pytest.raises(AssertionError, match="not planned"):
        repair.assert_only_planned_name_changes(original, stray, planned)

    touched = copy.deepcopy(good)
    next(d for d in touched["devices"]
         if d["id"] == "crystal")["config"]["pixel_count"] = 99
    with pytest.raises(AssertionError, match="other than `name`"):
        repair.assert_only_planned_name_changes(original, touched, planned)

    unlanded = copy.deepcopy(original)
    with pytest.raises(AssertionError, match="did not land"):
        repair.assert_only_planned_name_changes(original, unlanded, planned)


def test_a_missing_config_is_a_stated_exit(tmp_path, monkeypatch, capsys):
    assert _run(monkeypatch, tmp_path / "nope.json") == 2
    assert "pass --config PATH" in capsys.readouterr().out
