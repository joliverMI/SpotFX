"""scripts/seed_sauron_scene.py — the Sauron scene's copy of Eye V2.

WRITTEN, NOT RUN by the build (the tuning gate, docs/ADDING_EFFECTS.md).
These prove the copy against a fixture Eye V2 and a temp store: it differs
only where the script's docstring says, a dry run writes nothing, --apply
leaves every other scene byte-identical, a re-run upserts, and a source
already carrying the surge kind is refused.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── the scene copy script (written, never run by the build) ────────────────

def _eye_v2():
    from spectra.models.scene import (FlareBand, FlareKind, ParamTarget,
                                      ResponseSpec, SceneDeviceConfig, SceneV2)
    kinds = [FlareKind(name="Flare patch 0.7–1", type="permanent",
                       params={"flames": ParamTarget(mode="absolute",
                                                     value=1.0)}),
             FlareKind(name="Pulse Flash", type="pulse_flash",
                       trigger_offset_ms=-92)]
    return SceneV2(
        name="Eye V2", disabled=True, labels=["mid-group"],
        devices=[
            SceneDeviceConfig(target_kind="category", target="Matrix",
                              effect_type="eye",
                              params={"iris_size": 0.54, "pupil_size": 0.36,
                                      "gaze_radius": 0.5, "spin": 0.08,
                                      "spin_audio": 0, "flame_audio": 2,
                                      "x_offset": 0.5}),
            SceneDeviceConfig(target_kind="category", target="Strips",
                              effect_type="blackhole1d",
                              params={"swirl": 3.1}),
            SceneDeviceConfig(target_kind="category", target="Singles",
                              effect_type="pulse")],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0,
            kinds={k.name: 1.0 for k in kinds})])})


def _script():
    sys.path.insert(0, str(ROOT / "scripts"))
    import seed_sauron_scene as script
    return script


def test_the_copy_differs_only_where_the_docstring_says():
    script = _script()
    src = _eye_v2().model_dump(mode="json")
    new, dropped = script.build_sauron(src)
    assert sorted(dropped) == sorted(script.DROPPED_MATRIX_PARAMS)
    assert new["name"] == "Sauron" and new["disabled"] is True
    matrix = new["devices"][0]
    assert matrix["effect_type"] == "sauron"
    assert matrix["params"] == {"flame_audio": 2, "x_offset": 0.5}
    assert new["devices"][1]["params"] == src["devices"][1]["params"]
    assert new["devices"][1]["effect_type"] == "blackhole1d"
    assert new["flare_kinds"][:-1] == src["flare_kinds"]
    assert new["flare_kinds"][-1]["type"] == "sauron_surge"
    # appended, attached to no band
    for band in new["responses"]["flare"]["bands"]:
        assert script.SURGE_KIND_NAME not in band["kinds"]
    assert new["responses"] == src["responses"]
    diffs = script.difference_report(src, new)
    assert any(d.startswith("flare_kinds: +") for d in diffs)
    assert not any("EXISTING KINDS CHANGED" in d for d in diffs)
    # deterministic ids: a re-run upserts the same scene
    again, _ = script.build_sauron(src)
    assert again["id"] == new["id"]


def test_dry_run_writes_nothing_and_apply_leaves_every_other_scene_alone(
        tmp_path, capsys):
    from spectra.models.scene import SceneV2
    script = _script()
    eye = _eye_v2()
    other = SceneV2(name="Orbits V2")
    scenes = tmp_path / "scenes.json"
    scenes.write_text(json.dumps({s.id: s.model_dump(mode="json")
                                  for s in (eye, other)}, indent=2))
    seq = tmp_path / "sequencer.json"
    seq.write_text(json.dumps({"config": {"entries": {
        eye.id: {"curve_ref": None, "genre_mult": {}, "inline_points": []}}},
        "curves": {}}))
    before = scenes.read_text()
    assert script.main(["--scenes-file", str(scenes),
                        "--sequencer-file", str(seq)]) == 0
    assert scenes.read_text() == before
    assert "born DISABLED" in capsys.readouterr().out
    assert script.main(["--apply", "--scenes-file", str(scenes),
                        "--sequencer-file", str(seq)]) == 0
    store = json.loads(scenes.read_text())
    old = json.loads(before)
    for sid, raw in old.items():
        assert store[sid] == raw
    new = [r for r in store.values() if r["name"] == "Sauron"]
    assert len(new) == 1
    SceneV2(**new[0])
    entries = json.loads(seq.read_text())["config"]["entries"]
    assert new[0]["id"] in entries
    # re-running upserts, never a second copy
    assert script.main(["--apply", "--scenes-file", str(scenes),
                        "--sequencer-file", str(seq)]) == 0
    assert sum(1 for r in json.loads(scenes.read_text()).values()
               if r["name"] == "Sauron") == 1


def test_the_script_refuses_a_source_that_already_has_the_kind():
    script = _script()
    src = _eye_v2().model_dump(mode="json")
    src["flare_kinds"].append(script.surge_kind())
    with pytest.raises(SystemExit):
        script.build_sauron(src)
