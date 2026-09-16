"""FISH NEVER FADE OUT — they disperse off the screen — and the swim-burst
flare (his words on the Admiral's card fish-effect-disperse-off-screen-
instead--wyxr; see scripts/check_fish_disperse.py's own docstring).

The measured proof is scripts/check_fish_disperse.py: the lull (swirl, leak,
off the panel before the third, never dimmer while on it) at his real 0.9 s /
2.5 s / 6.04 s gaps, the outgoing Add crossfade, an ordinary population trim,
the burst at the effect, and the flare on scene_response + flare_preview —
each change with a RED control against the pre-change module read out of
git. It runs as a SUBPROCESS: it repoints spectra.config's stores and
device_model.CATEGORIES_FILE, which must never leak into a shared pytest
interpreter (tests/test_light_field_checks.py's rule).
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def test_the_measured_dispersal_and_burst_proof_passes():
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_fish_disperse.py")],
        cwd=REPO, capture_output=True, text=True, timeout=1800,
    )
    tail = (proc.stdout + proc.stderr)[-4000:]
    assert proc.returncode == 0, tail
    assert "ALL CHECKS PASSED" in proc.stdout, tail
    # the red controls must have RUN, not been skipped
    assert "RED CONTROL" in proc.stdout and "SKIPPED" not in proc.stdout, tail


def _fish_store():
    kinds = [
        {"name": "Flare patch 0–0.35", "type": "permanent", "jump": None,
         "params": {"particle_count": {"mode": "absolute", "value": 2.0,
                                       "offset": None, "lo": None, "hi": None}},
         "gain": 1.0, "hold_ms": None, "trigger_offset_ms": 0, "enabled": True},
        {"name": "Reverse Momentarily (500ms)", "type": "momentary",
         "jump": None,
         "params": {"reverse": {"mode": "absolute", "value": 1.0,
                                "offset": None, "lo": None, "hi": None}},
         "gain": 1.0, "hold_ms": 500, "trigger_offset_ms": 0, "enabled": True},
        {"name": "Colour Jump", "type": "drift_jump", "jump": "color_set",
         "params": {}, "gain": 1.0, "hold_ms": None, "trigger_offset_ms": 0,
         "enabled": True},
    ]
    bands = [
        {"intensity_min": lo, "intensity_max": hi, "curve": "linear",
         "gain": 1.0, "param_patch": {},
         "kinds": {"Flare patch 0–0.35": 1.0, "Colour Jump": 1.0,
                   "Reverse Momentarily (500ms)": 1.0},
         "kind_lanes": {}}
        for lo, hi in ((0.0, 0.35), (0.35, 0.7), (0.7, 1.0))
    ]
    return {
        "fish-id": {"id": "fish-id", "name": "Fish", "labels": [],
                    "devices": [], "flare_kinds": kinds,
                    "responses": {"flare": {"bands": bands,
                                            "reroll_dice": False,
                                            "color_set_jump": False}}},
        "other": {"id": "other", "name": "STAR", "devices": []},
    }


def _run_script(scenes, *args):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "add_fish_swim_burst_flare.py"),
         "--scenes-file", str(scenes), *args],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )


def test_the_migration_pools_the_burst_with_the_momentary_shape_flares(tmp_path):
    scenes = tmp_path / "scenes.json"
    before = _fish_store()
    scenes.write_text(json.dumps(before, indent=2))

    dry = _run_script(scenes)
    assert dry.returncode == 0, dry.stderr
    assert json.loads(scenes.read_text()) == before, "dry run wrote"

    applied = _run_script(scenes, "--apply")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    after = json.loads(scenes.read_text())
    assert after["other"] == before["other"]
    fish = after["fish-id"]
    burst = [k for k in fish["flare_kinds"] if k["name"] == "Fish Swim Burst"]
    assert len(burst) == 1
    assert burst[0]["type"] == "momentary"
    assert burst[0]["hold_ms"] == 300 and burst[0]["trigger_offset_ms"] == -100
    assert set(burst[0]["params"]) == {"swim_burst"}
    for band in fish["responses"]["flare"]["bands"]:
        assert band["kinds"]["Fish Swim Burst"] == 1.0
        # "instead of other shape flares": pooled with the momentary shape
        # flare only — the permanent patch and the colour kind stay alongside
        assert band["kind_lanes"] == {
            "Fish Swim Burst": "Shape",
            "Reverse Momentarily (500ms)": "Shape",
        }

    again = _run_script(scenes, "--apply")
    assert again.returncode == 0
    assert json.loads(scenes.read_text()) == after, "not idempotent"

    reverted = _run_script(scenes, "--revert", "--apply")
    assert reverted.returncode == 0, reverted.stdout + reverted.stderr
    assert json.loads(scenes.read_text()) == before, "revert is not exact"


def test_the_migrated_store_parses_under_the_current_scene_model(tmp_path):
    from spectra.models.scene import SceneV2
    import scripts.add_fish_swim_burst_flare as mig

    raw = copy.deepcopy(_fish_store()["fish-id"])
    mig.forward(raw)
    scene = SceneV2(**raw)
    kind = next(k for k in scene.flare_kinds if k.name == mig.KIND_NAME)
    assert (kind.hold_ms, kind.trigger_offset_ms) == (300, -100)
