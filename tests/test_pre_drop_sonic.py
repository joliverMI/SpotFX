"""SONIC'S REACH INTO THE PRE-DROP (predrop plan step 5): the six window
settings through set_scene_setting, and get_pre_drop_looks /
set_pre_drop_look on one entry — validated against what the entry's own
effect declares, refused with the allowed names otherwise, every write
backed up and logged like every scene edit. No live storage is touched.
"""
from __future__ import annotations

import asyncio

import pytest

from fx import device_model

LOOKS = {"looks": {"ring": {"label": "Infall ring", "kinds": ["spike", "intro"]},
                   "spin": {"label": "Spin-up", "kinds": ["intro"]}},
         "auto": {"spike": "ring", "intro": "ring"}}


@pytest.fixture
def scene(tmp_path, monkeypatch):
    from spectra import config as scfg
    for name, fn in (("SCENES_FILE", "scenes.json"),
                     ("SCENE_AGENT_LOG_FILE", "scene_agent_log.json"),
                     ("SCENE_BACKUPS_FILE", "scene_backups.json"),
                     ("SCENE_GENESIS_FILE", "scene_genesis.json")):
        monkeypatch.setattr(scfg, name, tmp_path / fn)
    real = device_model.pre_drop_looks
    monkeypatch.setattr(device_model, "pre_drop_looks",
                        lambda et: LOOKS if et == "blackhole" else real(et))
    from spectra.models.scene import SceneV2
    from spectra.services import scene_store
    s = SceneV2(name="Black Hole V2", devices=[
        {"target_kind": "category", "target": "Matrix", "effect_type": "blackhole"},
        # gradient declares no looks (Pulse has its own since step 6, and
        # power the strips' twinkle since step 9)
        {"target_kind": "category", "target": "Singles", "effect_type": "gradient"},
        {"target_kind": "category", "target": "Strips", "effect_type": "pulse"}])
    scene_store.save(s)
    return s


def _ops():
    from spectra.services import settings_agent
    return settings_agent.ALL_OPERATIONS


def _call(name, **kw):
    out = _ops()[name].handler(**kw)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


def test_the_operations_are_declared_and_discoverable():
    ops = _ops()
    assert ops["get_pre_drop_looks"].kind == "read"
    assert ops["set_pre_drop_look"].kind == "write"
    assert ops["set_pre_drop_look"].input_schema["properties"]["kind"]["enum"] == [
        "spike", "intro"]


def test_reading_an_entrys_looks(scene):
    got = _call("get_pre_drop_looks", scene="Black Hole V2", target="Matrix")
    assert got["chosen"] == {"spike": "auto", "intro": "auto"}
    assert got["plays"] == {"spike": "ring", "intro": "ring"}
    assert got["has_looks"] and set(got["declared"]) == {"ring", "spin"}
    assert got["windows"]["intro"] == {"enabled": True, "min_ms": 350, "max_ms": 4000}
    plain = _call("get_pre_drop_looks", scene="Black Hole V2", target="Singles")
    assert plain["has_looks"] is False and plain["plays"] == {"spike": None,
                                                              "intro": None}


def test_pulse_reads_back_its_own_declared_looks(scene):
    """Step 6's real registry block (config/effect_params.json): "auto"
    plays the burst for a spike and the dim swell for a vocal intro."""
    got = _call("get_pre_drop_looks", scene="Black Hole V2", target="Strips")
    assert got["has_looks"] and set(got["declared"]) == {"burst", "swell"}
    assert got["plays"] == {"spike": "burst", "intro": "swell"}


def test_setting_a_look_round_trips_and_is_backed_up(scene):
    from spectra.services import scene_store
    out = _call("set_pre_drop_look", scene="Black Hole V2", target="Matrix",
                kind="intro", look="spin")
    assert out["status"] == "applied" and out["backup_id"]
    assert "vocal intro" in out["summary"]
    entry = scene_store.get_by_id(scene.id).devices[0]
    assert entry.pre_drop_looks.intro == "spin"
    got = _call("get_pre_drop_looks", scene=scene.id, target="Matrix")
    assert got["plays"]["intro"] == "spin"
    out = _call("set_pre_drop_look", scene="Black Hole V2", target="Matrix",
                kind="intro", look="same")
    assert out["status"] == "applied"
    assert _call("get_pre_drop_looks", scene=scene.id,
                 target="Matrix")["plays"]["intro"] == "ring"


@pytest.mark.parametrize("kind,look", [
    ("spike", "spin"),          # spin suits the intro only
    ("spike", "same"),          # "same" is the intro's
    ("intro", "nope"),          # not declared
    ("clap", "auto"),           # not a kind
])
def test_a_look_the_effect_does_not_offer_is_refused(scene, kind, look):
    from spectra.services import scene_store
    out = _call("set_pre_drop_look", scene="Black Hole V2", target="Matrix",
                kind=kind, look=look)
    assert out["status"] == "rejected"
    assert scene_store.get_by_id(scene.id).devices[0].pre_drop_looks.spike == "auto"


def test_an_effect_with_no_looks_takes_only_auto_and_same(scene):
    out = _call("set_pre_drop_look", scene="Black Hole V2", target="Singles",
                kind="spike", look="ring")
    assert out["status"] == "rejected" and out["allowed_looks"] == ["auto"]
    assert _call("set_pre_drop_look", scene="Black Hole V2", target="Singles",
                 kind="intro", look="same")["status"] == "applied"


def test_the_window_settings_through_set_scene_setting(scene):
    from spectra.services import scene_store
    for key, value in (("pre_drop_spike_max_ms", 1500),
                       ("pre_drop_intro_enabled", False),
                       ("pre_drop_intro_min_ms", 600)):
        out = _call("set_scene_setting", scene_id=scene.id, key=key, value=value)
        assert out["status"] == "applied", out
    s = scene_store.get_by_id(scene.id)
    assert s.pre_drop_spike.max_ms == 1500
    assert (s.pre_drop_intro.enabled, s.pre_drop_intro.min_ms) == (False, 600)
    # out of bounds, and min >= max, are refused and change nothing
    for key, value in (("pre_drop_spike_max_ms", 3500),
                       ("pre_drop_spike_min_ms", 1500),
                       ("pre_drop_intro_max_ms", 300)):
        out = _call("set_scene_setting", scene_id=scene.id, key=key, value=value)
        assert out["status"] == "rejected", (key, value)
    assert scene_store.get_by_id(scene.id).pre_drop_spike.model_dump() == {
        "enabled": True, "min_ms": 350, "max_ms": 1500}
