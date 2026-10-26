"""THE TAIL DRIVE (fx/effects/fish.py `tail_drive`, the TAIL DRIVE block):
his ask — "a slow moving fish, or barely moving fish, would show it's tail
swimming and that motion would visually propel the fish ... so we still get
the good reactive movement, but also a more realistic swim" — and the plan
he approved, "tail-driven swimming with beats as strong as today".

The measured proof is scripts/check_fish_tail_drive.py (run here as a
subprocess, like every fish check script): `tail_drive = 0` byte-identical
to the pinned pre-change module, the steady and real-song speed, beats at
three levels, burst and glide, the swim burst, and the existing guards with
the tail drive on.

Pinned in-process below: the controller's own behaviour on the real
pipeline, the registry, Sonic's reach, and the scene script.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import check_fish_tail_drive as TD  # noqa: E402
from fx import device_model  # noqa: E402
from fx.effects import fish as FX  # noqa: E402
from spectra.models.scene import SceneV2  # noqa: E402

ON = {"tail_drive": 1.0}


def test_the_measured_tail_drive_proof_passes():
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_fish_tail_drive.py")],
        cwd=REPO, capture_output=True, text=True, timeout=3000,
    )
    out = proc.stdout + proc.stderr
    if "cannot read" in out and "out of git" in out:
        pytest.skip(out.strip().splitlines()[-1])
    assert proc.returncode == 0, out[-4000:]
    assert "ALL TAIL DRIVE CHECKS PASS" in proc.stdout, out[-4000:]
    assert proc.stdout.count("bit for bit") == 2, out[-4000:]


def _tank(*a, **k):
    return asyncio.run(TD.tank(*a, **k))


# ── the controller, on the real pipeline ────────────────────────────────
def test_at_cruise_the_tail_holds_cruise_at_its_own_size():
    """The calibration K * flap_rate^2 = drag: an effort of 1 strokes at the
    cruise size and rate and holds exactly cruise, whatever the drag."""
    for drag in (0.8, 1.6, 3.2):
        rec = _tank(0.0, dict(ON, glide_drag=drag), seconds=6.0,
                    effort=1.0)[120:]
        assert abs(rec[:, 2].mean() - 1.0) < 0.015, (drag, rec[:, 2].mean())
        assert abs(np.median(rec[:, 3]) - 1.0) < 0.03, drag
        assert (rec[:, 5] > 0.5).all(), "an effort of 1 never glides"


def test_below_glide_below_it_bursts_and_glides_and_never_at_zero():
    glides = _tank(0.0, ON, seconds=12.0, effort=0.4)[120:]
    assert np.mean(glides[:, 5] < 0.5) > 0.4, "it glides"
    straight = glides[glides[:, 5] < 0.5, 3]
    assert np.median(straight) < 0.2, "a gliding tail is near straight"
    steady = _tank(0.0, dict(ON, glide_below=0.0), seconds=12.0,
                   effort=0.4)[120:]
    assert (steady[:, 5] > 0.5).all(), "glide_below 0: it never glides"


def test_the_tail_moves_before_the_fish_does():
    """A beat: the drawn tail's activity (size x stroke rate) is up before
    the speed is, with the tail drive on."""
    rec = _tank(TD.LEVELS["normal"], ON, beats=(2.5,), seconds=4.0)
    b = int(2.5 * TD.FPS)
    activity = rec[:, 3] * rec[:, 4]
    lead = TD._half_rise(rec[:, 2], b) - TD._half_rise(activity, b)
    assert lead >= 0.06, lead


def test_at_tail_drive_zero_none_of_it_runs():
    """The escape hatch is structural: at 0 the tail drive's code is never
    entered, so nothing it would compute can reach the fish; at 1 it is."""
    calls = {"step": 0, "flap": 0}

    def count(name, own):
        def wrapped(*a, **k):
            calls[name] += 1
            return own(*a, **k)
        return wrapped

    import check_fish_wake_blend as WB

    def spy(eff):
        eff._tail_drive_step = count("step", eff._tail_drive_step)
        eff._tail_drive_flap = count("flap", eff._tail_drive_flap)
    asyncio.run(WB.run_arc("calm", "fish", {"tail_drive": 0.0},
                           on_attach=spy))
    assert calls == {"step": 0, "flap": 0}
    asyncio.run(WB.run_arc("calm", "fish", ON, on_attach=spy))
    assert calls["step"] > 1000 and calls["flap"] > 1000


# ── the defaults, the registry, Sonic ───────────────────────────────────
def test_the_settings_and_their_defaults():
    schema = FX.Fish2d.schema()({})
    assert schema["tail_drive"] == 0.0, "off unless a scene turns it on"
    assert schema["glide_drag"] == 1.6 and schema["glide_below"] == 0.75
    registry = json.loads((REPO / "config" / "effect_params.json").read_text())
    fish = registry["effects"]["fish"]
    for key in ("tail_drive", "glide_drag", "glide_below"):
        meta = fish["params"][key]
        assert meta["default"] == schema[key] == fish["defaults"][key], key
        assert meta["help_topic"] == "fish-tail-drive", key


def test_sonic_can_set_them_and_is_refused_out_of_range():
    from spectra.services import scene_console
    meta = device_model.effect_params("fish")
    assert scene_console._validate_param_value(
        "tail_drive", meta["tail_drive"], 1.0) == 1.0
    with pytest.raises(scene_console.SceneOpError):
        scene_console._validate_param_value(
            "tail_drive", meta["tail_drive"], 1.5)
    with pytest.raises(scene_console.SceneOpError):
        scene_console._validate_param_value(
            "glide_drag", meta["glide_drag"], 0.1)


# ── the scene script ────────────────────────────────────────────────────
def _store(tmp_path, fish_name="Fish", matrix_effect="fish"):
    import set_fish_tail_drive as mig
    matrix = {"target_kind": "category", "target": "Matrix",
              "effect_type": "fish", "params": {"particle_count": 3}}
    devices = [dict(matrix, effect_type=matrix_effect),
               {"target_kind": "category", "target": "Strips",
                "effect_type": "fireworks1d", "params": {}}]
    fish = json.loads(SceneV2(id=mig.FISH_SCENE_ID, name=fish_name,
                              devices=devices).model_dump_json())
    house = json.loads(SceneV2(name="House Fish",
                               devices=[matrix]).model_dump_json())
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps({mig.FISH_SCENE_ID: fish,
                                house["id"]: house}, indent=2))
    return mig, path, house["id"]


def _matrix(scene):
    return [d for d in scene["devices"] if d["target"] == "Matrix"][0]


def test_the_scene_script_turns_it_on_for_the_music_fish_only(tmp_path):
    mig, path, house_id = _store(tmp_path)
    before = json.loads(path.read_text())
    mig.main(["--scenes-file", str(path)])                 # dry run
    assert json.loads(path.read_text()) == before
    mig.main(["--scenes-file", str(path), "--apply"])
    after = json.loads(path.read_text())
    fish_before, fish_after = before[mig.FISH_SCENE_ID], after[mig.FISH_SCENE_ID]
    assert _matrix(fish_after)["params"] == dict(
        _matrix(fish_before)["params"], tail_drive=1.0)
    # nothing else on the scene, its other entries, or House Fish moved
    strip = lambda s: {k: v for k, v in s.items() if k != "devices"}  # noqa: E731
    assert strip(fish_after) == strip(fish_before)
    assert fish_after["devices"][1] == fish_before["devices"][1]
    assert after[house_id] == before[house_id]
    entry = [d for d in SceneV2(**fish_after).devices if d.target == "Matrix"]
    assert entry[0].params["tail_drive"] == 1.0
    mig.main(["--scenes-file", str(path), "--apply"])      # idempotent
    assert json.loads(path.read_text()) == after
    mig.main(["--scenes-file", str(path), "--apply", "--revert"])
    assert json.loads(path.read_text()) == before


@pytest.mark.parametrize("kw", [{"fish_name": "Not Fish"},
                                {"matrix_effect": "orbits"}])
def test_the_scene_script_refuses_to_guess(tmp_path, kw):
    mig, path, _ = _store(tmp_path, **kw)
    before = path.read_text()
    with pytest.raises(SystemExit):
        mig.main(["--scenes-file", str(path), "--apply"])
    assert path.read_text() == before
