"""scripts/migrate_singles_to_pulse.py — phase 4 of the single-led-power plan:
every Power Singles entry moves to Pulse with his tuning from the Pulse test
scene, his flare trigger timing included. Fixture scenes only; the script
never touches live storage from here."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import migrate_singles_to_pulse as mig
from spectra.models.scene import (EffectStep, FlareBand, FlareKind,
                                  ResponseSpec, SceneDeviceConfig, SceneV2)

SOURCE = mig.DEFAULT_SOURCE
HIS_FLASH_MS = -92
HIS_FLIP_MS = -355


def _bands(kinds_per_band: list[dict], lanes: list[dict] | None = None):
    edges = [(0.0, 0.35), (0.35, 0.7), (0.7, 1.0)]
    lanes = lanes or [{} for _ in kinds_per_band]
    return [FlareBand(intensity_min=lo, intensity_max=hi, kinds=k,
                      kind_lanes=ln)
            for (lo, hi), k, ln in zip(edges, kinds_per_band, lanes)]


BASE_KINDS = [FlareKind(name="Dice Re-roll", type="drift_jump", jump="dice"),
              FlareKind(name="Colour Jump", type="drift_jump",
                        jump="color_set")]


def _scene(name, singles_effect, *, singles_params=None, kinds=None,
           bands=None, singles_kind="category", singles_target="Singles",
           **extra_entry) -> dict:
    devices = [SceneDeviceConfig(target="Matrix", effect_type="orbits",
                                 params={"blob_size": 2.0})]
    if singles_effect is not None:
        devices.append(SceneDeviceConfig(
            target_kind=singles_kind, target=singles_target,
            effect_type=singles_effect, params=singles_params or {},
            **extra_entry))
    base = {"Dice Re-roll": 1.0, "Colour Jump": 1.0}
    scene = SceneV2(
        name=name, devices=devices,
        flare_kinds=kinds if kinds is not None else list(BASE_KINDS),
        responses={"flare": ResponseSpec(
            bands=bands or _bands([dict(base), dict(base), dict(base)]))})
    return scene.model_dump(mode="json")


def _source(flash_ms=HIS_FLASH_MS, flip_ms=HIS_FLIP_MS, attach_bands=3,
            extra_kinds=()) -> dict:
    kinds = list(BASE_KINDS) + [
        FlareKind(name="Pulse Flash", type="pulse_flash",
                  trigger_offset_ms=flash_ms),
        FlareKind(name="Pulse Colour Flip", type="pulse_flip",
                  trigger_offset_ms=flip_ms, min_intensity=0.4),
        *extra_kinds]
    per_band = []
    for i in range(3):
        k = {"Dice Re-roll": 1.0, "Colour Jump": 1.0}
        if i < attach_bands:
            k.update({"Pulse Flash": 1.0, "Pulse Colour Flip": 1.0})
        per_band.append(k)
    return _scene(SOURCE, "pulse", kinds=kinds, bands=_bands(per_band))


def _store(**scenes) -> dict:
    return {raw["id"]: raw for raw in scenes.values()}


def _by_name(store: dict, name: str) -> dict:
    return next(r for r in store.values() if r["name"] == name)


def _singles(raw: dict) -> dict:
    return next(d for d in raw["devices"] if d["target"] == "Singles")


def _kind(raw: dict, name: str) -> dict | None:
    return next((k for k in raw["flare_kinds"] if k["name"] == name), None)


@pytest.fixture
def store() -> dict:
    star_binding = {"bind": "signal", "signal": "trigger_intensity",
                    "mode": "steps", "fallback": 0.29,
                    "steps": [{"threshold": 0.0, "value": 0.29},
                              {"threshold": 0.7, "value": 0.85}]}
    return _store(
        source=_source(),
        power=_scene("Power Scene", "power",
                     singles_params={"bass_decay_rate": star_binding,
                                     "blur": 1, "flip": False},
                     brightness=0.8, background_brightness=0.23),
        laned=_scene("Laned Scene", "power",
                     singles_params={"blur": 1},
                     bands=_bands(
                         [{"Dice Re-roll": 1.0, "Colour Jump": 1.0}] * 3,
                         lanes=[{"Dice Re-roll": "Shape",
                                 "Colour Jump": "Shape"}] * 3)),
        house=_scene("House Scene", "gradient", singles_kind="virtual",
                     singles_target="single-color-effect"),
        nosingles=_scene("No Singles", None),
        steps=_scene("Stepped Scene", "power",
                     effect_steps=[EffectStep(threshold=0.7,
                                              effect_type="melt")]),
    )


def _write(tmp_path: Path, store: dict) -> Path:
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps(store, indent=2), encoding="utf-8")
    return path


def _quiet(*_a, **_k):
    pass


# ── the switch ─────────────────────────────────────────────────────────────

def test_power_singles_switch_to_pulse_with_his_params_and_flares(store):
    before = copy.deepcopy(store)
    tuning = mig.extract_tuning(store)
    mig.migrate(store, tuning)
    raw = _by_name(store, "Power Scene")
    old = _by_name(before, "Power Scene")
    dev = _singles(raw)
    assert dev["effect_type"] == "pulse"
    assert dev["params"] == {}          # the tuning scene's params, verbatim
    # The scene's own colour/brightness on that entry are untouched.
    for key in ("id", "color", "brightness", "background_brightness",
                "drift", "effect_steps", "target", "target_kind"):
        assert dev[key] == _singles(old)[key]
    assert raw["devices"][0] == old["devices"][0]     # Matrix untouched
    flash, flip = _kind(raw, "Pulse Flash"), _kind(raw, "Pulse Colour Flip")
    assert flash["trigger_offset_ms"] == HIS_FLASH_MS
    assert flip["trigger_offset_ms"] == HIS_FLIP_MS
    assert flip["min_intensity"] == 0.4
    src = _by_name(store, SOURCE)
    assert flash == _kind(src, "Pulse Flash")         # verbatim declaration
    for band in raw["responses"]["flare"]["bands"]:
        assert band["kinds"]["Pulse Flash"] == 1.0
        assert band["kinds"]["Pulse Colour Flip"] == 1.0
    SceneV2(**raw)


def test_new_kinds_join_no_lane_on_a_laned_scene(store):
    mig.migrate(store, mig.extract_tuning(store))
    for band in _by_name(store, "Laned Scene")["responses"]["flare"]["bands"]:
        assert "Pulse Flash" in band["kinds"]
        assert "Pulse Flash" not in band["kind_lanes"]
        assert band["kind_lanes"] == {"Dice Re-roll": "Shape",
                                      "Colour Jump": "Shape"}


def test_non_power_scenes_are_untouched(store):
    before = copy.deepcopy(store)
    plans = mig.migrate(store, mig.extract_tuning(store))
    for name in (SOURCE, "House Scene", "No Singles", "Stepped Scene"):
        assert _by_name(store, name) == _by_name(before, name), name
    names = {p.name: p for p in plans}
    assert set(names) == {"Power Scene", "Laned Scene", "Stepped Scene"}
    assert names["Stepped Scene"].skipped and "steps" in \
        names["Stepped Scene"].skipped


def test_his_retune_on_the_tuning_scene_is_what_travels(store):
    src = _by_name(store, SOURCE)
    _kind(src, "Pulse Flash")["trigger_offset_ms"] = -120
    _singles(src)["params"] = {"rest_level_calm": 0.3}
    mig.migrate(store, mig.extract_tuning(store))
    raw = _by_name(store, "Power Scene")
    assert _kind(raw, "Pulse Flash")["trigger_offset_ms"] == -120
    assert _singles(raw)["params"] == {"rest_level_calm": 0.3}


# ── his per-scene timing ───────────────────────────────────────────────────

def test_his_own_per_scene_timing_is_kept_and_seed_zero_is_retimed(store):
    own = _scene(
        "Own Timing", "power",
        kinds=list(BASE_KINDS) + [
            FlareKind(name="My Flash", type="pulse_flash",
                      trigger_offset_ms=-40),
            FlareKind(name="Pulse Colour Flip", type="pulse_flip",
                      min_intensity=0.5)],
        bands=_bands([{"Dice Re-roll": 1.0, "My Flash": 0.5}] * 3))
    store[own["id"]] = own
    before = copy.deepcopy(own)
    plans = {p.name: p for p in mig.migrate(store, mig.extract_tuning(store))}
    raw = _by_name(store, "Own Timing")
    assert _kind(raw, "My Flash")["trigger_offset_ms"] == -40   # his: kept
    assert _kind(raw, "Pulse Flash") is None        # matched by TYPE, not name
    flip = _kind(raw, "Pulse Colour Flip")
    assert flip["trigger_offset_ms"] == HIS_FLIP_MS            # seed 0 -> his
    assert flip["min_intensity"] == 0.5                         # untouched
    assert raw["responses"] == before["responses"]   # attachments untouched
    plan = plans["Own Timing"]
    assert plan.declared == []
    assert plan.retimed == [{"name": "Pulse Colour Flip",
                             "type": "pulse_flip", "from": 0,
                             "to": HIS_FLIP_MS}]
    assert any("'My Flash' kept at its own -40 ms" in n for n in plan.notes)
    table = mig.table(list(plans.values()))
    assert "Pulse Colour Flip: 0 ms → -355 ms" in table


def test_name_clash_with_another_type_skips_the_scene(store):
    clash = _scene("Clash", "power", kinds=list(BASE_KINDS) + [
        FlareKind(name="Pulse Flash", type="color_rotate")])
    store[clash["id"]] = clash
    before = copy.deepcopy(clash)
    plans = {p.name: p for p in mig.migrate(store, mig.extract_tuning(store))}
    assert plans["Clash"].skipped
    assert _by_name(store, "Clash") == before


def test_other_retimed_kinds_travel_by_name_and_type_only(store):
    src = _by_name(store, SOURCE)
    _kind(src, "Colour Jump")["trigger_offset_ms"] = -50
    plans = {p.name: p for p in mig.migrate(store, mig.extract_tuning(store))}
    assert _kind(_by_name(store, "Power Scene"),
                 "Colour Jump")["trigger_offset_ms"] == -50
    assert {"name": "Colour Jump", "type": "drift_jump", "from": 0,
            "to": -50} in plans["Power Scene"].retimed


def test_partial_attachment_on_the_tuning_scene_is_refused():
    store = _store(source=_source(attach_bands=2),
                   power=_scene("Power Scene", "power"))
    with pytest.raises(SystemExit, match="refusing to guess"):
        mig.extract_tuning(store)


# ── file runs: dry run, idempotence, revert ────────────────────────────────

def test_dry_run_writes_nothing(tmp_path, store):
    path = _write(tmp_path, store)
    blob = path.read_bytes()
    lines: list[str] = []
    result = mig.run_forward(path, SOURCE, apply=False, out=lines.append)
    assert path.read_bytes() == blob
    assert not (tmp_path / "backups").exists()
    assert not result["applied"]
    text = "\n".join(lines)
    assert "| Power Scene | power → pulse" in text
    assert "Pulse Flash (-92 ms)" in text
    assert "SKIPPED" in text      # the stepped scene, named


def test_apply_is_idempotent(tmp_path, store):
    path = _write(tmp_path, store)
    first = mig.run_forward(path, SOURCE, apply=True, out=_quiet)
    assert first["applied"] and first["backup"].exists()
    after_first = path.read_bytes()
    second = mig.run_forward(path, SOURCE, apply=True, out=_quiet)
    assert not second["applied"]
    assert all(p.skipped for p in second["plans"])   # only the stepped scene
    assert path.read_bytes() == after_first


def test_revert_restores_the_store_exactly(tmp_path, store):
    path = _write(tmp_path, store)
    original = json.loads(path.read_text())
    mig.run_forward(path, SOURCE, apply=True, out=_quiet)
    assert _singles(_by_name(json.loads(path.read_text()),
                             "Power Scene"))["effect_type"] == "pulse"
    dry = mig.run_revert(path, None, apply=False, out=_quiet)
    assert not dry["applied"]
    result = mig.run_revert(path, None, apply=True, out=_quiet)
    assert result["kept"] == []
    assert json.loads(path.read_text()) == original
    # Power's params come back verbatim, the ⚡ binding included.
    assert _singles(_by_name(json.loads(path.read_text()), "Power Scene")) \
        == _singles(_by_name(original, "Power Scene"))


def test_revert_leaves_his_later_edits_alone(tmp_path, store):
    path = _write(tmp_path, store)
    original = json.loads(path.read_text())
    mig.run_forward(path, SOURCE, apply=True, out=_quiet)
    data = json.loads(path.read_text())
    _kind(_by_name(data, "Power Scene"), "Pulse Flash")["trigger_offset_ms"] \
        = -10
    _singles(_by_name(data, "Laned Scene"))["params"] = {"flash_ms": 200}
    path.write_text(json.dumps(data, indent=2))
    result = mig.run_revert(path, None, apply=True, out=_quiet)
    out = json.loads(path.read_text())
    power = _by_name(out, "Power Scene")
    assert _singles(power)["effect_type"] == "power"
    assert _kind(power, "Pulse Flash")["trigger_offset_ms"] == -10
    assert all("Pulse Flash" in b["kinds"]
               for b in power["responses"]["flare"]["bands"])
    assert _kind(power, "Pulse Colour Flip") is None   # untouched: removed
    laned = _by_name(out, "Laned Scene")
    assert _singles(laned)["effect_type"] == "pulse"   # he retuned it: kept,
    assert _kind(laned, "Pulse Flash") is not None     # flares and all
    assert len(result["kept"]) == 2
    for name in ("House Scene", "No Singles", "Stepped Scene", SOURCE):
        assert _by_name(out, name) == _by_name(original, name)
