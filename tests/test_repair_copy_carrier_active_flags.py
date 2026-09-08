"""scripts/repair_copy_carrier_active_flags.py — the one-time catch-up for
the config residue that evicts the copy-mapped carrier on load.

THE BAR IS THE LOADER, NOT THE SCRIPT'S OWN ARITHMETIC. Every residue shape
here is cold-loaded through the REAL `FxHost.start()` before the repair
(tv-mapper evicted — the failure the script exists for) and again after it
(tv-mapper driving), with dummies of the real pixel counts and the real
config ORDER (carrier first, device-virtuals after, so they evict it).
Both shapes the loader brings up are covered: a device-virtual stored
`active: true`, and one with a stored effect beside NO `active` key at all
— the shape the device layer creates every device-virtual in, and the one
the script's first cut missed.

The narrow rule's refusals are proven by leaving alone: a device-virtual
behind a SPAN carrier, one behind a copy carrier the loader would not bring
up (stored `active: false`, or no stored effect), and one that is already
held back. The written config is asserted SEMANTICALLY identical to the
original except the planned flips — parsed JSON, since the write is
save_config's canonical layout.
"""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest

from fx import device_model, headless
from fx.host import FxHost

_SCRIPT = (Path(__file__).resolve().parent.parent / "scripts"
           / "repair_copy_carrier_active_flags.py")
_spec = importlib.util.spec_from_file_location(
    "repair_copy_carrier_active_flags", _SCRIPT)
repair = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repair)

CARRIER = "tv-mapper"
DEVS = {"tv-backlight": 60,
        "sconce-kitchen-left": 30,
        "sconce-kitchen-right": 30}
LAMP = {"type": "singleColor",
        "config": {"color": "#000000", "brightness": 0.0,
                   "background_brightness": 0.0}}
RED = {"type": "singleColor",
       "config": {"color": "#ff0000", "brightness": 1.0,
                  "background_brightness": 0.0}}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(device_model, "CATEGORIES_FILE",
                        tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()


def _device(d: str, pix: int) -> dict:
    return {"id": d, "type": "dummy",
            "config": {"name": d, "pixel_count": pix}}


def _device_virtual(d: str, pix: int, **extra) -> dict:
    entry = {"id": d, "is_device": d, "auto_generated": False,
             "config": {"name": d, "mapping": "span", "rows": 1},
             "segments": [[d, 0, pix - 1, False]]}
    entry.update(extra)
    return entry


def _carrier(vid: str, devs: dict, mapping: str = "copy", **extra) -> dict:
    entry = {"id": vid, "is_device": False, "auto_generated": False,
             "config": {"name": vid, "mapping": mapping, "rows": 1},
             "segments": [[d, 0, pix - 1, False] for d, pix in devs.items()]}
    entry.update(extra)
    return entry


def _residue_config() -> dict:
    """His shape with BOTH residue shapes on the copy carrier's fixtures, plus
    one substitute already held back, and the narrow rule's controls."""
    from fx.consts import CONFIGURATION_VERSION
    controls = {"span-strip": 20, "down-strip": 20, "lampless-strip": 20}
    devices = [_device(d, p) for d, p in {**DEVS, **controls}.items()]
    virtuals = [
        _carrier(CARRIER, DEVS, active=True, effect=RED),
        # a SPAN carrier over its own fixture: not this bug
        _carrier("span-carrier", {"span-strip": 20}, mapping="span",
                 active=True, effect=RED),
        # a copy carrier the loader would NOT bring up (stored false)
        _carrier("down-carrier", {"down-strip": 20}, active=False,
                 effect=RED),
        # a copy carrier with nothing to restore (no stored effect)
        _carrier("lampless-carrier", {"lampless-strip": 20}, active=True),
        # residue shape 1: persisted active:true beside the black lamp
        _device_virtual("tv-backlight", 60, active=True, effect=LAMP),
        # residue shape 2: the lamp persisted, NO active key at all
        _device_virtual("sconce-kitchen-left", 30, effect=LAMP),
        # already held back: an explicit false — nothing to do
        _device_virtual("sconce-kitchen-right", 30, active=False,
                        effect=LAMP),
        # controls behind the three non-qualifying carriers, each in a
        # shape the loader WOULD bring up — and each must be left alone
        _device_virtual("span-strip", 20, active=True, effect=LAMP),
        _device_virtual("down-strip", 20, effect=LAMP),
        _device_virtual("lampless-strip", 20, active=True, effect=LAMP),
    ]
    return {"configuration_version": CONFIGURATION_VERSION,
            "devices": devices, "virtuals": virtuals}


def _write(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))


def _stored(path: Path) -> dict:
    cfg = json.loads(path.read_text())
    return {v["id"]: v for v in cfg["virtuals"]}


def _cold_load(config_dir: Path) -> dict[str, bool]:
    """Load the config through the real host: {virtual id: rendering}.
    Teardown is explicit — a virtual left rendering is a non-daemon thread
    that keeps the interpreter alive at exit."""
    async def go():
        headless.silence_audio()
        host = FxHost(str(config_dir))
        await host.start()
        host.audio = headless.SyntheticAudioSource()
        try:
            await asyncio.sleep(0.3)
            out = {}
            for virtual in host.virtuals.values():
                thread = getattr(virtual, "_thread", None)
                out[virtual.id] = bool(virtual.active and thread is not None
                                       and thread.is_alive())
            return out
        finally:
            await host.shutdown()
    return asyncio.run(go())


def _run(monkeypatch, path: Path, *flags: str) -> int:
    monkeypatch.setattr("sys.argv", [str(_SCRIPT), "--config", str(path),
                                     *flags])
    return repair.main()


def test_the_loaders_rule_is_the_scripts_rule():
    assert repair.would_activate_on_load({"effect": LAMP, "active": True})
    assert repair.would_activate_on_load({"effect": LAMP})
    assert not repair.would_activate_on_load({"effect": LAMP,
                                              "active": False})
    assert not repair.would_activate_on_load({"active": True})
    assert not repair.would_activate_on_load({})


def test_both_residue_shapes_are_found_and_the_controls_are_not():
    residue = repair.find_residue(_residue_config()["virtuals"])
    by_id = {r["id"]: r for r in residue}
    assert set(by_id) == {"tv-backlight", "sconce-kitchen-left"}
    assert by_id["tv-backlight"]["stored_active"] is True
    assert by_id["sconce-kitchen-left"]["stored_active"] is None
    assert by_id["tv-backlight"]["carriers"] == [CARRIER]
    owned = repair.carrier_owned_devices(_residue_config()["virtuals"])
    assert set(owned) == set(DEVS), (
        "only the copy carrier the loader would bring up owns its devices")


def test_the_residue_strands_the_carrier_and_the_repair_frees_it(
        tmp_path, monkeypatch, capsys):
    """RED, then GREEN, through the real loader: before the repair both
    residue shapes evict tv-mapper; after `--apply` it drives and every
    substitute stays down."""
    config_dir = tmp_path / "fx"
    path = config_dir / "config.json"
    _write(path, _residue_config())
    original = json.loads(path.read_text())

    before = _cold_load(config_dir)
    assert before[CARRIER] is False, (
        "the residue must evict tv-mapper on load, or there is nothing to "
        "repair")
    assert before["tv-backlight"] and before["sconce-kitchen-left"]

    assert _run(monkeypatch, path, "--apply") == 0
    out = capsys.readouterr().out
    assert "written diff equals the planned diff" in out
    assert "no `active` key beside a stored effect" in out

    written = json.loads(path.read_text())
    stored = _stored(path)
    assert stored["tv-backlight"]["active"] is False
    assert stored["sconce-kitchen-left"]["active"] is False
    assert stored["sconce-kitchen-right"]["active"] is False
    for untouched in ("span-strip", "down-strip", "lampless-strip"):
        assert stored[untouched] == next(
            v for v in original["virtuals"] if v["id"] == untouched)
    assert stored[CARRIER] == next(
        v for v in original["virtuals"] if v["id"] == CARRIER)
    repair.assert_only_planned_active_flips(
        original, written, {"tv-backlight", "sconce-kitchen-left"})
    backups = list((config_dir / "backups").glob("config-carrier-active-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == original

    after = _cold_load(config_dir)
    assert after[CARRIER] is True, "after the repair tv-mapper must drive"
    for d in DEVS:
        assert after[d] is False
    assert after["span-strip"] and after["lampless-strip"]


def test_dry_run_writes_nothing_and_names_both_shapes(tmp_path, monkeypatch,
                                                      capsys):
    path = tmp_path / "fx" / "config.json"
    _write(path, _residue_config())
    raw = path.read_bytes()
    assert _run(monkeypatch, path) == 0
    assert path.read_bytes() == raw
    assert not (tmp_path / "fx" / "backups").exists()
    out = capsys.readouterr().out
    assert "dry-run: would set 2 device-virtual(s)" in out
    assert "tv-backlight" in out and "sconce-kitchen-left" in out
    assert "sconce-kitchen-right" not in out.split("residue:")[1]


def test_the_repair_is_idempotent(tmp_path, monkeypatch, capsys):
    path = tmp_path / "fx" / "config.json"
    _write(path, _residue_config())
    assert _run(monkeypatch, path, "--apply") == 0
    first = path.read_bytes()
    capsys.readouterr()
    assert _run(monkeypatch, path, "--apply") == 0
    assert "nothing to correct" in capsys.readouterr().out
    assert path.read_bytes() == first
    backups = list((tmp_path / "fx" / "backups").glob("*.json"))
    assert len(backups) == 1


def test_a_config_with_no_residue_is_left_alone(tmp_path, monkeypatch,
                                                capsys):
    config = _residue_config()
    for v in config["virtuals"]:
        if v.get("is_device") in DEVS:
            v["active"] = False
    path = tmp_path / "fx" / "config.json"
    _write(path, config)
    raw = path.read_bytes()
    assert _run(monkeypatch, path, "--apply") == 0
    assert "nothing to correct" in capsys.readouterr().out
    assert path.read_bytes() == raw


def test_the_written_diff_guard_refuses_anything_but_the_plan():
    original = _residue_config()
    planned = {"tv-backlight", "sconce-kitchen-left"}
    good = copy.deepcopy(original)
    for v in good["virtuals"]:
        if v["id"] in planned:
            v["active"] = False
    repair.assert_only_planned_active_flips(original, good, planned)

    stray = copy.deepcopy(good)
    next(v for v in stray["virtuals"] if v["id"] == "span-strip")["active"] = False
    with pytest.raises(AssertionError, match="not planned"):
        repair.assert_only_planned_active_flips(original, stray, planned)

    touched = copy.deepcopy(good)
    next(v for v in touched["virtuals"]
         if v["id"] == "tv-backlight")["effect"] = RED
    with pytest.raises(AssertionError, match="other than `active`"):
        repair.assert_only_planned_active_flips(original, touched, planned)

    unlanded = copy.deepcopy(original)
    with pytest.raises(AssertionError, match="did not land"):
        repair.assert_only_planned_active_flips(original, unlanded, planned)


def test_a_missing_config_is_a_stated_exit(tmp_path, monkeypatch, capsys):
    assert _run(monkeypatch, tmp_path / "nope.json") == 2
    assert "pass --config PATH" in capsys.readouterr().out
