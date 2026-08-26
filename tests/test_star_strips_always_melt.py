"""scripts/star_strips_always_melt.py — STAR's Strips always run melt
(his 2026-08-25 ruling: "always do melt").

The fixture reproduces his REAL STAR shape: three category entries, two of
which name `power` — the Strips entry's intensity STEP (the thing being
removed) and the Singles entry's outright base effect (which must not be
touched; the Singles category permits `power` only).

The properties under test, in order of what would hurt most if it broke:

  1. the write is SURGICAL — the only differing JSON path in the whole
     store is STAR.devices[<strips>].effect_steps; every other STAR entry
     and every other scene byte-identical (the script asserts this itself
     after writing; here it is proven independently from the outside);
  2. the OUTCOME — the patched scene resolves `melt` at every intensity
     through the real scene_compiler, not just "the bytes look right";
  3. the refusals — an unrecognised base effect or unexpected steps are
     refused rather than blindly emptied.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra.models.scene import SceneV2                       # noqa: E402
from spectra.services import scene_compiler                    # noqa: E402
from spectra.services.binding_resolver import FireContext      # noqa: E402

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "star_strips_always_melt.py"
_spec = importlib.util.spec_from_file_location("star_strips_always_melt", _SCRIPT)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

STAR_ID = migration.STAR_ID


def _color() -> dict:
    return {"mode": "set", "color_kind": None, "color_value": None,
            "bg_color": None, "bg_mode": None}


def _star_scene() -> dict:
    """His real STAR device shape (read off the live store 2026-08-25)."""
    return {
        "name": "STAR",
        "labels": [],
        "devices": [
            {"id": "93385d09-a352-4f16-9678-ce3760d93eac",
             "target_kind": "category", "target": "Matrix",
             "effect_type": "radial", "params": {"star": 0.4, "edges": 6},
             "effect_steps": [], "color": _color(), "drift": {}},
            {"id": "039e4e68-0337-4401-8ef1-10610abbfc1a",
             "target_kind": "category", "target": "Strips",
             "effect_type": "melt", "params": {},
             "effect_steps": [{"threshold": 0.7, "effect_type": "power",
                               "params": {"bass_decay_rate": 0.6,
                                          "blur": 1, "flip": False}}],
             "color": _color(), "drift": {}},
            {"id": "dc2da156-e5b7-45c0-9087-7944f204facc",
             "target_kind": "category", "target": "Singles",
             "effect_type": "power", "params": {},
             "effect_steps": [], "color": _color(), "drift": {}},
        ],
        "responses": {"flare": {"bands": [
            {"intensity_min": 0.0, "intensity_max": 1.0, "curve": "linear",
             "gain": 1.4, "param_patch": {"star": 0.0}},
        ], "reroll_dice": True, "color_set_jump": True}},
        "accept_all_sets": True,
        "accepted_set_ids": [],
    }


def _other_scene(name: str) -> dict:
    return {
        "name": name, "labels": [],
        "devices": [{"target_kind": "category", "target": "Strips",
                     "effect_type": "melt", "params": {},
                     "effect_steps": [{"threshold": 0.7,
                                       "effect_type": "power",
                                       "params": {"bass_decay_rate": 0.6}}]}],
        "responses": {"flare": {"bands": []}},
        "accept_all_sets": True, "accepted_set_ids": [],
    }


@pytest.fixture()
def scenes_file(tmp_path) -> Path:
    path = tmp_path / "scenes.json"
    # A DIFFERENT scene carrying the identical melt+power step shape: the
    # migration must reach STAR's entry and nothing that merely looks like it.
    store = {STAR_ID: _star_scene(), "other-scene-id": _other_scene("Hype Star")}
    path.write_text(json.dumps(store, indent=2))
    return path


def _run(argv: list[str]) -> None:
    old = sys.argv
    sys.argv = ["star_strips_always_melt.py", *argv]
    try:
        migration.main()
    finally:
        sys.argv = old


def _strips_effect(raw_scene: dict, intensity: float) -> str:
    scene = SceneV2(**json.loads(json.dumps(raw_scene)))
    res = scene_compiler.resolve_scene(scene, FireContext(intensity, rng=Random(6)))
    return next(d for d in res.devices if d.target == "Strips").effect_type


# ── 1. the dry-run plan ──────────────────────────────────────────────────
def test_dry_run_plans_the_removal_and_writes_nothing(scenes_file, capsys):
    before = scenes_file.read_text()
    _run(["--scenes-file", str(scenes_file)])
    assert scenes_file.read_text() == before
    assert not (scenes_file.parent / "backups").exists()
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "Strips: effect_steps [power @" in out
    assert "-> []" in out
    # the resolve proof and the named untouched siblings are in the plan
    assert "⚡0.50 -> melt" in out and "⚡0.95 -> melt" in out
    assert "untouched: Singles -> power" in out
    assert "untouched: Matrix -> radial" in out


def test_pre_migration_fixture_really_does_swap_to_power(scenes_file):
    """Guards the test itself: without the migration, a high fire IS power."""
    store = json.loads(scenes_file.read_text())
    assert _strips_effect(store[STAR_ID], 0.5) == "melt"
    assert _strips_effect(store[STAR_ID], 0.95) == "power"


# ── 2. the surgical write ────────────────────────────────────────────────
def test_apply_changes_exactly_one_json_path_in_the_whole_store(scenes_file):
    before = json.loads(scenes_file.read_text())
    _run(["--scenes-file", str(scenes_file), "--apply"])
    after = json.loads(scenes_file.read_text())

    diffs = migration._diff_paths(before, after)
    assert diffs == [(STAR_ID, "devices", 1, "effect_steps")], diffs
    assert after[STAR_ID]["devices"][1]["effect_steps"] == []

    # spelled out independently of the script's own diff helper
    assert json.dumps(before["other-scene-id"], sort_keys=True) == \
        json.dumps(after["other-scene-id"], sort_keys=True)
    for i in (0, 2):
        assert json.dumps(before[STAR_ID]["devices"][i], sort_keys=True) == \
            json.dumps(after[STAR_ID]["devices"][i], sort_keys=True)
    for key in set(before[STAR_ID]) | set(after[STAR_ID]):
        if key != "devices":
            assert before[STAR_ID].get(key) == after[STAR_ID].get(key), key


def test_apply_makes_every_intensity_resolve_melt(scenes_file):
    _run(["--scenes-file", str(scenes_file), "--apply"])
    star = json.loads(scenes_file.read_text())[STAR_ID]
    for inten in (0.0, 0.5, 0.69, 0.7, 0.95, 1.0):
        assert _strips_effect(star, inten) == "melt", inten
    # …and the Singles entry still fires power, untouched
    scene = SceneV2(**star)
    res = scene_compiler.resolve_scene(scene, FireContext(0.95, rng=Random(6)))
    singles = next(d for d in res.devices if d.target == "Singles")
    assert singles.effect_type == "power"


def test_apply_backs_up_the_whole_store_first(scenes_file):
    before = scenes_file.read_text()
    _run(["--scenes-file", str(scenes_file), "--apply"])
    backups = list((scenes_file.parent / "backups").glob("scenes-star-strips-melt-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text() == before


def test_apply_is_idempotent(scenes_file, capsys):
    _run(["--scenes-file", str(scenes_file), "--apply"])
    once = scenes_file.read_text()
    capsys.readouterr()
    _run(["--scenes-file", str(scenes_file), "--apply"])
    assert scenes_file.read_text() == once
    assert "nothing to do" in capsys.readouterr().out
    assert len(list((scenes_file.parent / "backups").glob("*.json"))) == 1


def test_revert_restores_the_step(scenes_file):
    _run(["--scenes-file", str(scenes_file), "--apply"])
    _run(["--scenes-file", str(scenes_file), "--apply", "--revert"])
    star = json.loads(scenes_file.read_text())[STAR_ID]
    steps = star["devices"][1]["effect_steps"]
    assert steps == [{"threshold": 0.7, "effect_type": "power",
                      "params": {"bass_decay_rate": 0.6}}]
    assert _strips_effect(star, 0.95) == "power"


# ── 3. the refusals ─────────────────────────────────────────────────────
def test_refuses_an_unrecognised_base_effect(scenes_file):
    store = json.loads(scenes_file.read_text())
    store[STAR_ID]["devices"][1]["effect_type"] = "power"
    store[STAR_ID]["devices"][1]["effect_steps"] = [
        {"threshold": 0.7, "effect_type": "melt", "params": {}}]
    scenes_file.write_text(json.dumps(store, indent=2))
    before = scenes_file.read_text()
    with pytest.raises(SystemExit):
        _run(["--scenes-file", str(scenes_file), "--apply"])
    assert scenes_file.read_text() == before


def test_refuses_unexpected_steps(scenes_file):
    store = json.loads(scenes_file.read_text())
    store[STAR_ID]["devices"][1]["effect_steps"] = [
        {"threshold": 0.4, "effect_type": "power", "params": {}}]
    scenes_file.write_text(json.dumps(store, indent=2))
    before = scenes_file.read_text()
    with pytest.raises(SystemExit):
        _run(["--scenes-file", str(scenes_file), "--apply"])
    assert scenes_file.read_text() == before


def test_refuses_when_drift_depends_on_a_step_only_param(scenes_file):
    store = json.loads(scenes_file.read_text())
    store[STAR_ID]["devices"][1]["drift"] = {
        "bass_decay_rate": {"ref": "slow-creep"}}
    scenes_file.write_text(json.dumps(store, indent=2))
    before = scenes_file.read_text()
    with pytest.raises(SystemExit):
        _run(["--scenes-file", str(scenes_file), "--apply"])
    assert scenes_file.read_text() == before


def test_refuses_when_star_is_absent(tmp_path):
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps({"other-scene-id": _other_scene("Hype Star")}, indent=2))
    with pytest.raises(SystemExit):
        _run(["--scenes-file", str(path), "--apply"])
