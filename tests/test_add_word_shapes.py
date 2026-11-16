"""scripts/add_word_shapes.py — the Word Shapes scene-data script (W2.5).

The script DJ runs at W3 to turn Word Shapes on: one "Word Shape" flare
kind plus a full-range Words band on each of the plan's six scenes. Never
run against live storage from here — every test builds its own fixture
store in tmp_path, shaped like the six scenes' real entries (Matrix/Strips/
Singles device entries with each scene's own live effect types, three flare
bands with kinds and a pooled lane, a colour journey, labels), and asserts
what the script does to that file byte for byte.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Each scene's live effect entries (Matrix / Strips / Singles), per the six
# scene skills under .claude/skills/.
SIX = {
    "Black Hole V2": ("blackhole", "blackhole1d", "power"),
    "STAR": ("radial", "melt", "power"),
    "Orbits V2": ("orbits", "orbits1d", "power"),
    "Fish": ("fish", "fireworks1d", "power"),
    "Sauron": ("sauron", "blackhole1d", "power"),
    "Fireworks V2": ("fireworks", "fireworks1d", "power"),
}


def _script():
    sys.path.insert(0, str(ROOT / "scripts"))
    import add_word_shapes as script
    return script


def _scene(name: str, effects: tuple[str, str, str]):
    """One fixture scene with the shape a real stored scene has."""
    from spectra.models.scene import (FlareBand, FlareKind, ParamTarget,
                                      ResponseSpec, SceneColorJourney,
                                      SceneDeviceConfig, SceneV2)
    matrix, strips, singles = effects
    kinds = [
        FlareKind(name="Colour Jump", type="drift_jump", jump="color_set"),
        FlareKind(name="Reverse Momentarily (500ms)", type="momentary",
                  params={"reverse": ParamTarget(mode="absolute", value=1.0)},
                  hold_ms=500),
        FlareKind(name="Brighten", type="momentary", gain=1.4, hold_ms=250),
    ]
    lanes = {"Reverse Momentarily (500ms)": "Shape", "Brighten": "Shape"}
    bands = [FlareBand(intensity_min=lo, intensity_max=hi,
                       kinds={k.name: 1.0 for k in kinds}, kind_lanes=lanes)
             for lo, hi in ((0.0, 0.35), (0.35, 0.7), (0.7, 1.0))]
    charge = [FlareBand(kinds={"Brighten": 1.0})]
    return SceneV2(
        name=name,
        labels=["test"],
        devices=[
            SceneDeviceConfig(target_kind="category", target="Matrix",
                              effect_type=matrix),
            SceneDeviceConfig(target_kind="category", target="Strips",
                              effect_type=strips),
            SceneDeviceConfig(target_kind="category", target="Singles",
                              effect_type=singles),
        ],
        flare_kinds=kinds,
        color_journey=SceneColorJourney(mode="inherit", pace_factor=1.0),
        responses={"flare": ResponseSpec(bands=bands),
                   "charge": ResponseSpec(bands=charge)},
    )


def _store(tmp_path, scenes, *, extra=()):
    """A fixture scenes.json holding `scenes` plus any `extra` scenes."""
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps(
        {s.id: s.model_dump(mode="json") for s in (*scenes, *extra)},
        indent=2), encoding="utf-8")
    return path


def _six(tmp_path, *, skip=(), extra=()):
    scenes = [_scene(n, e) for n, e in SIX.items() if n not in skip]
    return scenes, _store(tmp_path, scenes, extra=extra)


# ---------------------------------------------------------------- the shapes

def test_the_literals_are_exactly_what_the_models_serialize():
    """The script writes literals; they must BE the canonical serialized
    shape, so a model field added later fails here rather than writing a
    half-canonical scene into his store."""
    from spectra.models.scene import FlareBand, FlareKind, ResponseSpec
    script = _script()
    assert script.KIND == FlareKind(
        name="Word Shape", type="word_shape").model_dump(mode="json")
    assert script.WORD_SECTION == ResponseSpec(bands=[FlareBand(
        intensity_min=0.0, intensity_max=1.0,
        kinds={"Word Shape": 1.0})]).model_dump(mode="json")


def test_dry_run_changes_nothing(tmp_path):
    script = _script()
    _scenes, path = _six(tmp_path)
    original = path.read_text(encoding="utf-8")
    assert script.main(["--scenes-file", str(path)]) == 0
    assert path.read_text(encoding="utf-8") == original


def test_apply_changes_exactly_the_two_keys_on_all_six(tmp_path):
    from spectra.models.scene import SceneV2
    from spectra.services.scene_store import scene_warnings
    script = _script()
    scenes, path = _six(tmp_path)
    original = json.loads(path.read_text(encoding="utf-8"))
    assert script.main(["--scenes-file", str(path), "--apply"]) == 0
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert set(stored) == set(original)
    for scene in scenes:
        raw = stored[scene.id]
        was = original[scene.id]
        # exactly one new flare kind, exactly the spec's shape
        new = [k for k in raw["flare_kinds"] if k not in was["flare_kinds"]]
        assert new == [script.KIND], scene.name
        assert len(raw["flare_kinds"]) == len(was["flare_kinds"]) + 1
        # exactly one new response class, the full-range Words band
        assert set(raw["responses"]) - set(was["responses"]) == {"word"}
        assert raw["responses"]["word"] == script.WORD_SECTION
        # and NOTHING else differs
        assert script._normalize(raw) == script._normalize(was), scene.name
        # the patched scene loads, with no warning of its own
        loaded = SceneV2.model_validate(raw)
        assert scene_warnings(loaded) == [], scene.name
        band = loaded.responses["word"].bands[0]
        assert (band.intensity_min, band.intensity_max) == (0.0, 1.0)
        assert band.kinds == {"Word Shape": 1.0}
        assert band.kind_lanes == {}
        kind = next(k for k in loaded.flare_kinds if k.name == "Word Shape")
        assert kind.type == "word_shape"
        assert kind.enabled is True
        assert kind.min_intensity is None
        assert kind.trigger_offset_ms == 0


def test_every_song_the_whole_energy_range_draws(tmp_path):
    """His Q6 A is "every song": the engine's own plan-time question must
    say yes across the whole Energy axis, not just the middle."""
    from spectra.models.scene import SceneV2
    from spectra.services.scene_response import words_band_draws
    script = _script()
    scenes, path = _six(tmp_path)
    script.main(["--scenes-file", str(path), "--apply"])
    stored = json.loads(path.read_text(encoding="utf-8"))
    for scene in scenes:
        loaded = SceneV2.model_validate(stored[scene.id])
        for energy in (0.0, 0.01, 0.2, 0.5, 0.75, 0.99, 1.0):
            assert words_band_draws(loaded, energy), (scene.name, energy)


def test_other_scenes_are_untouched(tmp_path):
    script = _script()
    other = _scene("Pacman V2", ("pacman", "orbits1d", "power"))
    scenes, path = _six(tmp_path, extra=[other])
    original = json.loads(path.read_text(encoding="utf-8"))
    assert script.main(["--scenes-file", str(path), "--apply"]) == 0
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored[other.id] == original[other.id]


def test_revert_returns_a_byte_identical_file(tmp_path):
    script = _script()
    _scenes, path = _six(tmp_path)
    original = path.read_text(encoding="utf-8")
    assert script.main(["--scenes-file", str(path), "--apply"]) == 0
    assert path.read_text(encoding="utf-8") != original
    assert script.main(["--scenes-file", str(path), "--apply", "--revert"]) == 0
    assert path.read_text(encoding="utf-8") == original


def test_both_directions_are_idempotent(tmp_path):
    script = _script()
    _scenes, path = _six(tmp_path)
    original = path.read_text(encoding="utf-8")
    script.main(["--scenes-file", str(path), "--apply"])
    applied = path.read_text(encoding="utf-8")
    assert script.main(["--scenes-file", str(path), "--apply"]) == 0
    assert path.read_text(encoding="utf-8") == applied
    script.main(["--scenes-file", str(path), "--apply", "--revert"])
    assert script.main(["--scenes-file", str(path), "--apply", "--revert"]) == 0
    assert path.read_text(encoding="utf-8") == original


def test_a_missing_sauron_is_reported_and_skipped_never_invented(
        tmp_path, capsys):
    """Sauron's seed is still gated on his own tuning session."""
    from spectra.models.scene import SceneV2
    script = _script()
    scenes, path = _six(tmp_path, skip=("Sauron",))
    assert script.main(["--scenes-file", str(path), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "Sauron: NOT IN THIS STORE" in out
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert len(stored) == 5
    assert all(raw.get("name") != "Sauron" for raw in stored.values())
    for scene in scenes:
        assert "word" in SceneV2.model_validate(stored[scene.id]).responses


# ------------------------------------------------------------- the refusals

def test_it_refuses_an_ambiguous_name(tmp_path):
    script = _script()
    twin = _scene("Fish", SIX["Fish"])
    _scenes, path = _six(tmp_path, extra=[twin])
    original = path.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="refusing to guess which one"):
        script.main(["--scenes-file", str(path), "--apply"])
    assert path.read_text(encoding="utf-8") == original


def test_it_refuses_a_word_shape_name_of_another_type(tmp_path):
    from spectra.models.scene import FlareKind
    script = _script()
    scenes = [_scene(n, e) for n, e in SIX.items()]
    scenes[2].flare_kinds.append(
        FlareKind(name="Word Shape", type="momentary", gain=1.5))
    path = _store(tmp_path, scenes)
    original = path.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        script.main(["--scenes-file", str(path), "--apply"])
    assert path.read_text(encoding="utf-8") == original


def test_it_refuses_a_words_section_that_differs(tmp_path):
    """Detaching the kind from the band is one of plan §7's undo paths — a
    re-run must not quietly undo his undo."""
    from spectra.models.scene import FlareBand, ResponseSpec
    script = _script()
    scenes = [_scene(n, e) for n, e in SIX.items()]
    scenes[0].responses["word"] = ResponseSpec(bands=[FlareBand(
        intensity_min=0.0, intensity_max=1.0, kinds={"Colour Jump": 1.0})])
    path = _store(tmp_path, scenes)
    original = path.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        script.main(["--scenes-file", str(path), "--apply"])
    assert path.read_text(encoding="utf-8") == original


def test_a_kind_switched_off_by_his_power_button_is_left_alone(tmp_path):
    """Plan §7's first undo path. A re-run must never re-enable it."""
    from spectra.models.scene import SceneV2
    script = _script()
    scenes, path = _six(tmp_path)
    script.main(["--scenes-file", str(path), "--apply"])
    stored = json.loads(path.read_text(encoding="utf-8"))
    sid = scenes[1].id
    for kind in stored[sid]["flare_kinds"]:
        if kind["name"] == "Word Shape":
            kind["enabled"] = False
    path.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    off = path.read_text(encoding="utf-8")
    assert script.main(["--scenes-file", str(path), "--apply"]) == 0
    assert path.read_text(encoding="utf-8") == off
    loaded = SceneV2.model_validate(json.loads(off)[sid])
    kind = next(k for k in loaded.flare_kinds if k.name == "Word Shape")
    assert kind.enabled is False


def test_revert_refuses_a_kind_he_has_edited(tmp_path):
    script = _script()
    scenes, path = _six(tmp_path)
    script.main(["--scenes-file", str(path), "--apply"])
    stored = json.loads(path.read_text(encoding="utf-8"))
    for kind in stored[scenes[3].id]["flare_kinds"]:
        if kind["name"] == "Word Shape":
            kind["min_intensity"] = 0.3
    path.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    edited = path.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="refusing to remove it"):
        script.main(["--scenes-file", str(path), "--apply", "--revert"])
    assert path.read_text(encoding="utf-8") == edited


def test_revert_refuses_a_words_section_he_has_edited(tmp_path):
    script = _script()
    scenes, path = _six(tmp_path)
    script.main(["--scenes-file", str(path), "--apply"])
    stored = json.loads(path.read_text(encoding="utf-8"))
    band = stored[scenes[4].id]["responses"]["word"]["bands"][0]
    band["intensity_min"] = 0.4
    path.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    edited = path.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="refusing to remove it"):
        script.main(["--scenes-file", str(path), "--apply", "--revert"])
    assert path.read_text(encoding="utf-8") == edited


def test_a_missing_store_is_refused(tmp_path):
    script = _script()
    with pytest.raises(SystemExit, match="nothing to do"):
        script.main(["--scenes-file", str(tmp_path / "nope.json"), "--apply"])


def test_apply_backs_the_store_up_first(tmp_path):
    script = _script()
    _scenes, path = _six(tmp_path)
    original = path.read_text(encoding="utf-8")
    assert script.main(["--scenes-file", str(path), "--apply"]) == 0
    backups = sorted((tmp_path / "backups").glob("scenes-word-shapes-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original
