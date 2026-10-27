"""THE POND REST (fx/effects/fish.py `quiet_rest`, the POND REST block): his
ask — "at really low music levels, like when it's almost or completely
quiet, the fish should almost come to a rest, with very sporadic short
motions, like real fish in a pond" — and the plan he approved, "a quiet pond
rest with occasional darts", for the music Fish scene only, "'quiet' means
the music's own level".

The measured proof is scripts/check_fish_pond_rest.py (run here as a
subprocess, like every fish check script): `quiet_rest = 0` byte-identical
to the pinned pre-change module, the between-songs timeline of his real
audio, the darts, a drumless quiet passage, every moment it must stay out
of, an audio pause, and his library.

Pinned in-process below: the quiet detector's own rules, the startle,
switching it off, the darts' own generator, the registry, Sonic's reach,
and the scene script.
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

import check_fish_pond_rest as PR  # noqa: E402
from fx import device_model  # noqa: E402
from fx.effects import fish as FX  # noqa: E402
from spectra.models.scene import SceneV2  # noqa: E402

DT = 1.0 / 60.0
CALM, FULL = 0.66, 0.52


def test_the_measured_pond_rest_proof_passes():
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_fish_pond_rest.py")],
        cwd=REPO, capture_output=True, text=True, timeout=3000,
    )
    out = proc.stdout + proc.stderr
    if "cannot read" in out and "out of git" in out:
        pytest.skip(out.strip().splitlines()[-1])
    assert proc.returncode == 0, out[-4000:]
    assert "ALL POND REST CHECKS PASS" in proc.stdout, out[-4000:]
    assert proc.stdout.count("bit for bit") == 4, out[-4000:]


# ── the quiet detector ──────────────────────────────────────────────────
def _settle(volumes, state=None, calm=CALM, full=FULL):
    state = state or (volumes[0], volumes[0], 0.0)
    for v in volumes:
        state = FX.rest_step(state, v, DT, calm, full)
    return state


def test_quiet_is_a_smoothstep_between_the_two_levels():
    assert FX.rest_quiet(0.80, CALM, FULL) == 0.0
    assert FX.rest_quiet(CALM, CALM, FULL) == 0.0
    assert FX.rest_quiet(FULL, CALM, FULL) == 1.0
    assert FX.rest_quiet(0.10, CALM, FULL) == 1.0
    mid = FX.rest_quiet((CALM + FULL) / 2, CALM, FULL)
    assert abs(mid - 0.5) < 1e-9
    samples = [FX.rest_quiet(v, CALM, FULL) for v in np.linspace(0.8, 0.4, 41)]
    assert all(b >= a for a, b in zip(samples, samples[1:])), "monotonic"
    # levels set the wrong way round: a plain switch at the calm level
    assert FX.rest_quiet(CALM - 0.01, CALM, CALM + 0.1) == 1.0
    assert FX.rest_quiet(CALM + 0.01, CALM, CALM + 0.1) == 0.0


def test_the_rest_comes_in_slowly_and_goes_out_fast():
    quiet = _settle([0.80] * 60 + [0.30] * int(FX.REST_IN_S * 60))
    # entering is the slow average and then a REST_IN_S ease: about two
    # thirds of the way in one ease length after the music went quiet
    assert 0.3 < quiet[2] < 0.8, quiet
    rested = _settle([0.30] * 600, quiet)
    assert rested[2] > 0.99
    woke = _settle([0.80] * int(0.6 * 60), rested)
    assert woke[2] < 0.05, "the fast average wakes it within ~half a second"


def test_a_brief_quiet_dip_never_rests_it_but_a_brief_loud_one_wakes_it():
    playing = _settle([0.80] * 600)
    dip = _settle([0.80] * 120 + [0.20] * 18 + [0.80] * 120, playing)
    assert max(dip[2], 0.0) < 0.02, "0.3 s of quiet inside the music"
    rested = _settle([0.30] * 900)
    blip = _settle([0.85] * 18, rested)
    assert blip[2] < rested[2] * 0.6, "0.3 s of loud music starts to wake"


# ── the effect, in process ──────────────────────────────────────────────
def _run(coro):
    return asyncio.run(coro)


def test_a_strong_hit_cuts_the_rest_at_once():
    async def go():
        r = await PR.Crystal.open(PR.ON, seed=5)
        try:
            for _ in range(8 * 60):
                r.frame(PR.QUIET, 0.03)
            before = r.fish._rest_level
            r.frame(PR.LOUD, 0.95, beat=True)          # one real onset
            return before, r.fish._rest_level, r.lunged()
        finally:
            await r.close()
    before, after, lunged = _run(go())
    assert before > 0.9
    assert after < 0.05, "the startle cuts it in the same frame"
    assert lunged


def test_at_quiet_rest_zero_none_of_it_runs():
    async def go(extra):
        r = await PR.Crystal.open(extra, seed=5)
        calls = {"n": 0}
        own = r.fish._pond_rest_step

        def counted(*a, **k):
            calls["n"] += 1
            return own(*a, **k)
        r.fish._pond_rest_step = counted
        try:
            for _ in range(4 * 60):
                r.frame(PR.QUIET, 0.03)
            return calls["n"], r.audio.reads, r.fish._rest_level
        finally:
            await r.close()
    assert _run(go(PR.TAIL_ONLY)) == (0, 0, 0.0)
    calls, reads, level = _run(go(PR.ON))
    assert calls > 200 and reads > 200 and level > 0.5


def test_switching_it_off_mid_rest_forgets_the_rest_and_any_dart():
    async def go():
        r = await PR.Crystal.open(PR.ON, seed=5)
        eff = r.fish
        try:
            for _ in range(40 * 60):                   # until a dart flies
                r.frame(PR.QUIET, 0.03)
                if np.isfinite(eff.p_dhd[:eff.n]).any():
                    break
            flying = bool(np.isfinite(eff.p_dhd[:eff.n]).any())
            eff.update_config({"quiet_rest": 0.0})
            state = (eff._rest, eff._rest_level, eff._darting,
                     float(np.abs(eff.p_dart).max()),
                     bool(np.isfinite(eff.p_dhd).any()))
            for _ in range(4 * 60):
                r.frame(PR.QUIET, 0.03)
            return flying, state, r.speed()
        finally:
            await r.close()
    flying, (rest, level, darting, dart, heading), speed = _run(go())
    assert flying, "the run reached a dart in flight"
    assert rest is None and level == 0.0 and darting is None
    assert dart == 0.0 and not heading
    assert speed > 0.8, "back to ordinary swimming"


def test_the_darts_are_reproducible_from_the_effects_own_seed():
    async def go(seed):
        r = await PR.Crystal.open(PR.ON, seed=seed)
        starts = []
        try:
            for f in range(40 * 60):
                d0 = r.darts
                r.frame(PR.QUIET, 0.03)
                if r.darts > d0:
                    starts.append(f)
            return starts, r.fish._dart_rng is not r.fish._rng
        finally:
            await r.close()
    a, own_a = _run(go(5))
    b, _ = _run(go(5))
    c, _ = _run(go(7))
    assert a and a == b, "the same seed darts the same way"
    assert c != a, "another seed darts another way"
    assert own_a, "the darts never draw from the shared generator"


def test_a_swim_burst_at_rest_keeps_its_own_share():
    """The rest scales only the ordinary share of the target: a moment (the
    swim burst here) multiplies in before it and keeps its share whole.
    Resting the whole target instead (the old rule) loses the dash."""
    awake = _run(PR._burst(PR.TAIL_ONLY))
    rested = _run(PR._burst(PR.ON))
    old = _run(PR._burst(PR.ON, old=True))
    assert rested[0] > 0.9 and old[0] > 0.9, "both were at rest"
    assert rested[1] >= 0.5 * awake[1] and rested[2] >= 2.0, (rested, awake)
    assert old[1] < 0.2 * awake[1], old


# ── the defaults, the registry, Sonic ───────────────────────────────────
KEYS = ("quiet_rest", "rest_calm_level", "rest_full_level", "dart_every_s")


def test_the_settings_and_their_defaults():
    schema = FX.Fish2d.schema()({})
    assert schema["quiet_rest"] == 0.0, "off unless a scene turns it on"
    assert (schema["rest_calm_level"], schema["rest_full_level"],
            schema["dart_every_s"]) == (0.66, 0.52, 9.0)
    registry = json.loads((REPO / "config" / "effect_params.json").read_text())
    fish = registry["effects"]["fish"]
    for key in KEYS:
        meta = fish["params"][key]
        assert meta["default"] == schema[key] == fish["defaults"][key], key
        assert meta["help_topic"] == "fish-pond-rest", key
    assert fish["params"]["dart_every_s"]["min"] > FX.DART_MIN_S


def test_sonic_can_set_them_and_is_refused_out_of_range():
    from spectra.services import scene_console
    meta = device_model.effect_params("fish")
    assert scene_console._validate_param_value(
        "quiet_rest", meta["quiet_rest"], 1.0) == 1.0
    with pytest.raises(scene_console.SceneOpError):
        scene_console._validate_param_value(
            "quiet_rest", meta["quiet_rest"], 1.5)
    with pytest.raises(scene_console.SceneOpError):
        scene_console._validate_param_value(
            "dart_every_s", meta["dart_every_s"], 2.0)


# ── the scene script ────────────────────────────────────────────────────
def _store(tmp_path, fish_name="Fish", matrix_effect="fish"):
    import set_fish_pond_rest as mig
    matrix = {"target_kind": "category", "target": "Matrix",
              "effect_type": "fish",
              "params": {"particle_count": 3, "tail_drive": 1.0}}
    devices = [dict(matrix, effect_type=matrix_effect),
               {"target_kind": "category", "target": "Strips",
                "effect_type": "fireworks1d", "params": {}}]
    fish = json.loads(SceneV2(id=mig.entry.FISH_SCENE_ID, name=fish_name,
                              devices=devices).model_dump_json())
    house = json.loads(SceneV2(name="House Fish",
                               devices=[matrix]).model_dump_json())
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps({mig.entry.FISH_SCENE_ID: fish,
                                house["id"]: house}, indent=2))
    return mig, path, house["id"]


def _matrix(scene):
    return [d for d in scene["devices"] if d["target"] == "Matrix"][0]


def test_the_scene_script_turns_it_on_for_the_music_fish_only(tmp_path):
    mig, path, house_id = _store(tmp_path)
    fish_id = mig.entry.FISH_SCENE_ID
    before = json.loads(path.read_text())
    mig.main(["--scenes-file", str(path)])                 # dry run
    assert json.loads(path.read_text()) == before
    mig.main(["--scenes-file", str(path), "--apply"])
    after = json.loads(path.read_text())
    assert _matrix(after[fish_id])["params"] == dict(
        _matrix(before[fish_id])["params"], quiet_rest=1.0)
    # nothing else on the scene, its other entries, or House Fish moved
    strip = lambda s: {k: v for k, v in s.items() if k != "devices"}  # noqa: E731
    assert strip(after[fish_id]) == strip(before[fish_id])
    assert after[fish_id]["devices"][1] == before[fish_id]["devices"][1]
    assert after[house_id] == before[house_id]
    backups = list((tmp_path / "backups").glob("scenes-pond-rest-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == before
    entry = [d for d in SceneV2(**after[fish_id]).devices
             if d.target == "Matrix"]
    assert entry[0].params["quiet_rest"] == 1.0
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
