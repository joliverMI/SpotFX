"""THE DROP SHOCKWAVE'S SWITCHES (2026-10-12) — the room's on/off, each
scene's on/off, and the room's minimum energy (the top bar's Energy).

The Admiral: "Shockwave should be a setting that can be toggled per scene,
as well as globally, as well as a global setting for minimum energy before
it is allowed to fire. As i understand it, it is an overlay, so it should
easily be able to be turned off ... Turn it off for fish to test it at
first and leave it on globally for drops over .7 energy." Firstmate's
ruling: the energy is the top bar's Energy (bridge.intensity()).

- the rule (phase_grammar.shock_allowed): room, then scene, then energy;
  an unknown energy is never gated;
- the settings: room on + 0.7 by default, scene on by default, all three
  Sonic-reachable;
- the drop arm (scene_response._drive_phase) tells every member the verdict
  as `drop_shock_on` and names it in the record — global off, below the
  floor, scene off, Fish off;
- skipped means skipped: the effect builds no painter, and on the real
  pipeline every member's told-off drop is byte-identical to its own drop
  with the Shockwave at zero (the effect's own drop unchanged);
- the Fish migration touches exactly one key.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from random import Random
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fx import device_model  # noqa: E402
from fx.effects import phase_grammar as pg  # noqa: E402
from spectra.models.scene import SceneV2  # noqa: E402
from spectra.services import room_controls as rc  # noqa: E402
from spectra.services import scene_response as sr  # noqa: E402

FISH_ID = "80811c53-56ad-552e-bdb5-12028448accc"


# ── the rule ───────────────────────────────────────────────────────────────

def test_the_rule_room_then_scene_then_energy():
    assert pg.shock_allowed(True, True, 0.8, 0.7) == (True, pg.SHOCK_ALLOWED)
    assert pg.shock_allowed(True, True, 0.7, 0.7) == (True, pg.SHOCK_ALLOWED)
    assert pg.shock_allowed(True, True, 0.69, 0.7) == (
        False, pg.SHOCK_BELOW_ENERGY)
    assert pg.shock_allowed(False, True, 1.0, 0.0) == (False, pg.SHOCK_ROOM_OFF)
    assert pg.shock_allowed(False, False, 0.1, 0.7) == (
        False, pg.SHOCK_ROOM_OFF)                      # the room wins
    assert pg.shock_allowed(True, False, 1.0, 0.0) == (
        False, pg.SHOCK_SCENE_OFF)
    # an energy that cannot be read is never gated (the drop floor's rule)
    assert pg.shock_allowed(True, True, None, 0.7) == (
        True, pg.SHOCK_ENERGY_UNKNOWN)
    # a floor of 0 lets every drop through
    assert pg.shock_allowed(True, True, 0.0, 0.0)[0] is True


def test_untold_reads_on():
    assert pg.shock_on({}) is True
    assert pg.shock_on({pg.SHOCK_ON_KEY: True}) is True
    assert pg.shock_on({pg.SHOCK_ON_KEY: False}) is False


# ── the settings ───────────────────────────────────────────────────────────

def test_the_room_settings_default_on_at_07_and_are_sonic_editable():
    from spectra.services import settings_console as sc
    room = rc.RoomControlState()
    assert room.drop_shock_enabled is True
    assert room.drop_shock_min_energy == pytest.approx(0.7)
    assert rc.field_bounds("drop_shock_min_energy") == (0.0, 1.0)
    assert sc.SETTINGS_REGISTRY["drop_shock_enabled"].kind == "bool"
    spec = sc.SETTINGS_REGISTRY["drop_shock_min_energy"]
    assert (spec.min, spec.max) == (0.0, 1.0)
    assert "top-bar" in spec.label.lower()


def test_the_scene_setting_defaults_on_and_is_sonic_editable():
    from spectra.services import scene_console as scc
    assert SceneV2(name="x").drop_shock_enabled is True
    # a scene stored before the field existed loads on
    assert SceneV2(**{"name": "old"}).drop_shock_enabled is True
    spec = scc.SCENE_SETTINGS_REGISTRY["drop_shock_enabled"]
    assert spec.kind == "bool"


def test_sonic_turns_a_scene_off_and_the_room_floor_up(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import scene_console as scc
    from spectra.services import scene_store
    from spectra.services import settings_console as sc
    for name in ("SCENES_FILE", "SCENE_AGENT_LOG_FILE", "SCENE_BACKUPS_FILE",
                 "SCENE_GENESIS_FILE", "SETTINGS_LOG_FILE",
                 "ROOM_CONTROLS_FILE"):
        monkeypatch.setattr(scfg, name, tmp_path / f"{name.lower()}.json")
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    scene = SceneV2(name="Orbits V2")
    scene_store.save(scene)
    asyncio.run(scc.apply_scene_setting(scene.id, "drop_shock_enabled",
                                        False))
    assert scene_store.get_by_id(scene.id).drop_shock_enabled is False
    asyncio.run(sc.apply_change("drop_shock_min_energy", 0.85))
    assert rc.load_room_controls().drop_shock_min_energy == pytest.approx(0.85)
    asyncio.run(sc.apply_change("drop_shock_enabled", False))
    assert rc.load_room_controls().drop_shock_enabled is False
    with pytest.raises(sc.SettingChangeError):
        asyncio.run(sc.apply_change("drop_shock_min_energy", 1.5))


# ── the drop arm ───────────────────────────────────────────────────────────

class _Exec:
    def __init__(self):
        self.jumps = []

    async def jump(self, vid, et, params):
        self.jumps.append((vid, dict(params)))

    async def glide(self, vid, et, params, ms):
        pass


def _responder(scene=None, energy=0.8, **room):
    ex = _Exec()
    effects = {vid: vid for vid in device_model.DROP_SHOCK_EFFECTS}
    effects |= {"fireworks": "fireworks", "squiggles": "squiggles"}
    conductor = SimpleNamespace(scene=scene, virtuals={
        vid: SimpleNamespace(effect_type=et) for vid, et in effects.items()})
    eng = sr.ResponseEngine(
        conductor=conductor, executor=ex, rng=Random(1),
        room_controls=lambda: rc.RoomControlState(**room),
        song_position=lambda: (None, None),
        room_energy=(energy if callable(energy) else (lambda: energy)))
    return eng, ex


def _drop(eng, ex):
    rec = asyncio.run(eng._drive_phase("drop", gap_ms=None, intensity=0.6))
    return rec, dict(ex.jumps)


def test_default_room_loud_drop_tells_every_member_on():
    eng, ex = _responder(energy=0.8)
    rec, told = _drop(eng, ex)
    for vid in device_model.DROP_SHOCK_EFFECTS:
        assert told[vid][pg.SHOCK_ON_KEY] is True
    # never told to a non-member (Fireworks keeps its own drop; the strips
    # and Squiggles have no crystal Shockwave)
    assert pg.SHOCK_ON_KEY not in told["fireworks"]
    assert pg.SHOCK_ON_KEY not in told["squiggles"]
    assert rec["drop_shock"] == {"on": True, "reason": pg.SHOCK_ALLOWED,
                                 "energy": 0.8, "min_energy": 0.7}


def test_global_off_tells_every_member_off():
    eng, ex = _responder(energy=1.0, drop_shock_enabled=False)
    rec, told = _drop(eng, ex)
    for vid in device_model.DROP_SHOCK_EFFECTS:
        assert told[vid][pg.SHOCK_ON_KEY] is False
    assert rec["drop_shock"]["reason"] == pg.SHOCK_ROOM_OFF


def test_a_drop_below_the_energy_floor_is_skipped():
    eng, ex = _responder(energy=0.5)
    rec, told = _drop(eng, ex)
    assert all(told[v][pg.SHOCK_ON_KEY] is False
               for v in device_model.DROP_SHOCK_EFFECTS)
    assert rec["drop_shock"]["reason"] == pg.SHOCK_BELOW_ENERGY
    # the room's own floor moves it
    eng, ex = _responder(energy=0.5, drop_shock_min_energy=0.4)
    assert _drop(eng, ex)[0]["drop_shock"]["on"] is True


def test_an_unreadable_energy_is_not_gated():
    eng, ex = _responder(energy=None)
    assert _drop(eng, ex)[0]["drop_shock"]["reason"] == pg.SHOCK_ENERGY_UNKNOWN

    def boom():
        raise RuntimeError("bridge down")
    eng, ex = _responder(energy=boom)
    rec, told = _drop(eng, ex)
    assert rec["drop_shock"]["on"] is True
    assert told["fish"][pg.SHOCK_ON_KEY] is True


def test_a_scene_switched_off_is_skipped_on_every_member():
    eng, ex = _responder(scene=SceneV2(name="Orbits V2",
                                       drop_shock_enabled=False), energy=1.0)
    rec, told = _drop(eng, ex)
    assert all(told[v][pg.SHOCK_ON_KEY] is False
               for v in device_model.DROP_SHOCK_EFFECTS)
    assert rec["drop_shock"]["reason"] == pg.SHOCK_SCENE_OFF


def test_the_drop_itself_is_still_driven_when_skipped():
    """Skipping the overlay changes ONE key on the arm: the phase edge, the
    progress and the drop's intensity are told exactly as before."""
    on_eng, on_ex = _responder(energy=1.0)
    off_eng, off_ex = _responder(energy=1.0, drop_shock_enabled=False)
    on_rec, on_told = _drop(on_eng, on_ex)
    off_rec, off_told = _drop(off_eng, off_ex)
    assert on_rec["targets"] == off_rec["targets"]
    for vid in on_told:
        a = {k: v for k, v in on_told[vid].items() if k != pg.SHOCK_ON_KEY}
        b = {k: v for k, v in off_told[vid].items() if k != pg.SHOCK_ON_KEY}
        assert a == b


def test_charge_and_lull_arms_never_carry_the_verdict():
    for cls in ("charge", "lull"):
        eng, ex = _responder(energy=1.0)
        rec = asyncio.run(eng._drive_phase(cls, gap_ms=4_000, intensity=0.6))
        assert "drop_shock" not in rec
        assert all(pg.SHOCK_ON_KEY not in p for _, p in ex.jumps)


# ── the effect: skipped means no painter at all ────────────────────────────

def test_a_told_off_drop_builds_no_painter():
    from PIL import Image
    from fx.effects.twod import Twod
    eff = SimpleNamespace(_config={pg.SHOCK_ON_KEY: False}, _phase="drop",
                          _shock=None, _shock_pending=True,
                          _shock_fresh=False, passed=1 / 30,
                          r_width=72, r_height=37)
    eff.matrix = Image.new("RGB", (72, 37), (10, 20, 30))
    before = eff.matrix
    Twod._phase_grammar_post(eff)
    assert eff._shock is None
    assert eff.matrix is before            # the frame is the effect's own


@pytest.mark.parametrize("effect", sorted(device_model.DROP_SHOCK_EFFECTS))
def test_on_the_real_pipeline_a_skipped_drop_is_the_effects_own(
        effect, monkeypatch):
    """Told off on the drop arm, every member's frames are byte-identical to
    the same seed with its Shockwave at zero — its own drop, unchanged — and
    told on (the control) they are not. (Some members draw from an unseeded
    generator before the harness can seed them, so unseeded ones are pinned
    here; the comparison is then between three runs of one world.)"""
    import scripts.check_drop_shockwave as check
    real_rng = np.random.default_rng
    monkeypatch.setattr(np.random, "default_rng",
                        lambda seed=None: real_rng(11 if seed is None
                                                   else seed))
    off = asyncio.run(check.run_sequence(
        effect, shock=True, drop_arm={pg.SHOCK_ON_KEY: False}))
    zero = asyncio.run(check.run_sequence(effect, shock=False))
    on = asyncio.run(check.run_sequence(
        effect, shock=True, drop_arm={pg.SHOCK_ON_KEY: True}))
    d = off["drop_at"]
    assert len(off["frames"]) == len(zero["frames"])
    for a, b in zip(off["frames"], zero["frames"]):
        assert np.array_equal(a, b)
    assert any(not np.array_equal(a, b)
               for a, b in zip(on["frames"][d:], zero["frames"][d:]))


# ── the Fish migration ─────────────────────────────────────────────────────

def _store(tmp_path, fish_name="Fish"):
    fish = json.loads(SceneV2(id=FISH_ID, name=fish_name).model_dump_json())
    fish["legacy_untouched"] = {"keep": [1, 2]}
    other = json.loads(SceneV2(name="Orbits V2").model_dump_json())
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps({FISH_ID: fish, other["id"]: other}, indent=2))
    return path, other["id"]


def test_the_fish_migration_turns_exactly_one_key_off(tmp_path):
    import scripts.set_fish_drop_shock_off as mig
    path, other_id = _store(tmp_path)
    before = json.loads(path.read_text())
    mig.main(["--scenes-file", str(path)])                 # dry run
    assert json.loads(path.read_text()) == before
    mig.main(["--scenes-file", str(path), "--apply"])
    after = json.loads(path.read_text())
    assert after[FISH_ID]["drop_shock_enabled"] is False
    assert {k: v for k, v in after[FISH_ID].items()
            if k != "drop_shock_enabled"} == {
        k: v for k, v in before[FISH_ID].items() if k != "drop_shock_enabled"}
    assert after[other_id] == before[other_id]
    assert SceneV2(**after[FISH_ID]).drop_shock_enabled is False
    mig.main(["--scenes-file", str(path), "--apply"])      # idempotent
    assert json.loads(path.read_text()) == after
    mig.main(["--scenes-file", str(path), "--apply", "--on"])   # revert
    assert json.loads(path.read_text())[FISH_ID]["drop_shock_enabled"] is True


def test_the_fish_migration_refuses_to_guess(tmp_path):
    import scripts.set_fish_drop_shock_off as mig
    path, _ = _store(tmp_path, fish_name="Not Fish")
    with pytest.raises(SystemExit):
        mig.main(["--scenes-file", str(path), "--apply"])


def test_fish_off_reaches_the_fish_drop():
    """The migrated Fish scene, showing, skips the Shockwave on a loud drop
    while the room stays on at 0.7."""
    fish = SceneV2(id=FISH_ID, name="Fish", drop_shock_enabled=False)
    eng, ex = _responder(scene=fish, energy=0.95)
    rec, told = _drop(eng, ex)
    assert told["fish"][pg.SHOCK_ON_KEY] is False
    assert rec["drop_shock"]["reason"] == pg.SHOCK_SCENE_OFF
