"""HOUSE LIGHTING phase 4 — the code that his starting content needs.

  1. THE CUTOVER SWITCH (HouseSettings.enabled) ships OFF: with a mode set
     and the room SPECTRA's, nothing reaches a fixture — no scene, no base
     level, no Hue directive, no deferral — and the heartbeat says "idle".
     Switching it off while a mode rests hands the look back. The settings
     PUT applies a flip at once.
  2. THE HUE BULBS A MODE LEAVES ALONE (hue_excluded_lights) ride the
     directive as SKIP looks; the hold never writes them, the verifier never
     reports them, and an edit to the list changes what the gate compares.
  3. THE HOUSE JOURNEY travels the sets a mode NAMES even when they are
     opted out of the music pools (every Calm member is), and only those.
  4. THE BREATHING EFFECT is registered: its motion param, no background,
     the registered class (not the mixin) behind it, and a scene compile
     that writes the colour set's colour and no background.

The breath surviving a glide is tests/test_gradient_breathing.py; the
seeded content itself is tests/test_seed_house_lighting.py.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from spectra.models.house_mode import (FixtureHook, HouseLibrary, HouseMode, HouseSettings,
                                       HouseTarget, HueLook, ScenePick)


def _run(coro):
    return asyncio.run(coro)


def _settings(**kw):
    from spectra.services import house_store
    lib = house_store.load_library()
    house_store.put_settings(lib.settings.model_copy(update=kw))


# ── 1. the cutover switch ──────────────────────────────────────────────────

def test_a_fresh_library_ships_with_house_lighting_off():
    assert HouseSettings().enabled is False
    assert HouseLibrary().settings.enabled is False


@pytest.fixture
def open_room(monkeypatch):
    """The room SPECTRA's, nothing on standby — so only the switch decides."""
    from spectra.services import show_output
    monkeypatch.setattr(show_output, "ownership_refusal", lambda: None)
    monkeypatch.setattr(show_output, "standdown_reason", lambda: None)


@pytest.fixture
def fakes(monkeypatch):
    """A fake scene fire / colour apply / conductor behind house.deps that
    records every call — the proof that nothing was written."""
    from spectra.services import house, show_output
    calls = {"fires": [], "applies": [], "bases": [], "hue": 0}

    class Cond:
        scene = None
        virtuals: dict = {}

        class executor:
            @staticmethod
            async def glide(*a, **k):
                calls.setdefault("glides", []).append(a)

        def on_surge(self, changes):
            pass

    async def fire_scene(scene_id, **kw):
        calls["fires"].append(scene_id)
        return {"dry_run": False}

    async def apply_set(card, glide_ms):
        calls["applies"].append(card.id)
        return {}

    async def sync_hue():
        calls["hue"] += 1

    cond = Cond()
    house.deps.fire_scene = fire_scene
    house.deps.apply_set = apply_set
    house.deps.conductor = lambda: cond
    house.deps.sync_hue = sync_hue
    house.deps.playing = lambda: False
    house.deps.active_set_id = lambda: None
    monkeypatch.setattr(show_output, "set_base",
                        lambda levels, states, fade_s=0: calls["bases"].append((levels, states)))
    monkeypatch.setattr(show_output, "base_snapshot", lambda: {"levels": {}, "states": {}})
    monkeypatch.setattr(show_output, "resolve_target",
                        lambda t: (["crystal"], []))
    return calls


@pytest.fixture
def a_mode(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.models.scene import SceneV2
    from spectra.services import house_store, scene_store
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    scene = SceneV2(name="House Star")
    scene_store.save(scene)
    mode = house_store.put_mode(HouseMode(
        name="Standard", ha_aliases=["Daytime"],
        scenes=[ScenePick(scene_id=scene.id)],
        fixtures=[FixtureHook(target=HouseTarget(kind="fixture", id="crystal"), level=6.0)],
        hue=[HueLook(area="*", kelvin=3521)]))
    return mode


def test_switched_off_a_set_mode_reaches_no_fixture(open_room, fakes, a_mode):
    from spectra.services import house
    _settings(enabled=False)
    out = _run(house.set_mode(ha_mode="Daytime", source="ha"))
    assert out["status"] == "applied", "HA's word is still recorded and mapped"
    assert out["lighting"]["mode"]["name"] == "Standard"
    assert out["lighting"]["enabled"] is False
    assert out["lighting"]["active"] is False
    assert house.gate() == ("off", house.SWITCHED_OFF)
    assert fakes["fires"] == [] and fakes["applies"] == []
    assert all(levels == {} and states == {} for levels, states in fakes["bases"])
    assert house.hue_directive() is None
    assert house.scene_deferral() is None and house.response_deferral() is None
    assert house.journey_override() is None
    assert house.layer_active() is False
    assert house.inactive_reason() == house.SWITCHED_OFF


def test_switched_on_the_same_mode_drives_the_room(open_room, fakes, a_mode):
    from spectra.services import house
    _settings(enabled=True)
    _run(house.set_mode(ha_mode="Daytime", source="ha"))
    assert fakes["fires"] == [a_mode.scenes[0].scene_id]
    assert any(levels == {"crystal": 0.06} for levels, _ in fakes["bases"])
    assert house.hue_directive() is not None
    assert house.layer_active() is True


def test_switching_off_while_resting_hands_the_look_back(open_room, fakes, a_mode, monkeypatch):
    from spectra.services import house, show_output
    _settings(enabled=True)
    _run(house.set_mode(ha_mode="Daytime", source="ha"))
    assert house.status_dict()["phase"] == "resting"
    monkeypatch.setattr(show_output, "base_snapshot",
                        lambda: {"levels": {"crystal": 0.06}, "states": {}})
    _settings(enabled=False)
    _run(house.tick())
    st = house.status_dict()
    assert st["phase"] == "inactive" and st["reason"] == house.SWITCHED_OFF
    assert fakes["bases"][-1] == ({}, {}), "the base levels are faded back"
    assert house.hue_directive() is None, "Hue goes back to the room toggle"


def test_the_heartbeat_reads_idle_while_switched_off(monkeypatch, a_mode):
    from fx import light_ownership
    from spectra.services import engine, house
    from spectra.services.live_host import live
    monkeypatch.setattr(light_ownership, "load",
                        lambda: type("R", (), {"owner": light_ownership.SPECTRA})())
    monkeypatch.setattr(live, "host", object())
    monkeypatch.setattr(engine.executor, "mode", "facade", raising=False)
    from spectra.services import house_store
    st = house_store.state()
    st.mode_id = a_mode.id
    _settings(enabled=False)
    hb = house.heartbeat()
    assert hb["state"] == "idle" and hb["lighting_ok"] is False
    assert hb["house_enabled"] is False


def test_the_settings_put_applies_a_flip_at_once(open_room, fakes, a_mode):
    from spectra.api import house as api
    from spectra.services import house
    _settings(enabled=False)
    _run(house.set_mode(ha_mode="Daytime", source="ha"))
    assert fakes["fires"] == []
    out = _run(api.put_settings({"enabled": True}))
    assert out["settings"]["enabled"] is True
    assert out["lighting"]["enabled"] is True and out["lighting"]["active"] is True
    assert fakes["fires"], "switching on applied the mode without waiting a tick"
    other = _run(api.put_settings({"owned_brightness": 200}))
    assert other["settings"]["enabled"] is True, "an unrelated edit keeps the switch"
    assert "lighting" not in other


# ── 2. the Hue bulbs a mode leaves alone ───────────────────────────────────

def test_the_directive_carries_one_skip_look_per_left_alone_bulb(open_room, fakes, a_mode):
    from spectra.services import ambient, house
    _settings(enabled=True, hue_excluded_lights=["Loft Ceiling Uplight", "ledge left"])
    _run(house.set_mode(ha_mode="Daytime", source="ha"))
    looks = house.hue_directive().looks
    assert ("*/Loft Ceiling Uplight", "skip", None, None, 0.0) in looks
    assert ambient.look_for("hue-lights", looks)[1] == "hold", "a skip never names an area"
    assert ambient.skipped_lights("hue-lights", looks) == {"loft ceiling uplight", "ledge left"}
    before = looks
    _settings(hue_excluded_lights=["Loft Ceiling Uplight"])
    assert house.hue_directive().looks != before, "an edit to the list re-lands the hold"


def test_names_are_deduplicated_ignoring_case():
    s = HouseSettings(hue_excluded_lights=["Ledge Left", " ledge left ", "", "Ledge Right"])
    assert s.hue_excluded_lights == ["Ledge Left", "Ledge Right"]


@pytest.fixture
def named_bridge(monkeypatch):
    from tests.test_ambient import _hue_handler, _install_bridge
    calls: list = []
    lights = [{"id": "l1", "owner": "d1", "name": "Standing Lamp 1"},
              {"id": "l2", "owner": "d2", "name": "Loft Ceiling Uplight"},
              {"id": "l3", "owner": "d3", "name": "Ledge Left"}]
    _install_bridge(monkeypatch, _hue_handler(calls, lights=lights))
    return calls


def test_the_hold_and_the_verifier_never_touch_a_left_alone_bulb(monkeypatch, named_bridge):
    from spectra.services import ambient
    from spectra.services.live_host import live
    from tests.test_ambient import FakeHost, FakeHueDevice
    dev = FakeHueDevice("10.0.0.1", named_bridge)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))
    looks = (("*", "hold", 284, None, 100.0),
             ("*/Loft Ceiling Uplight", "skip", None, None, 0.0),
             ("*/ledge left", "skip", None, None, 0.0))
    result = _run(ambient.reconcile_looks(looks, 0))
    assert result["status"] == "on" and result["lights_set"] == 1
    written = {c[2].rsplit("/", 1)[-1] for c in named_bridge
               if c[0] == "REST" and c[1] == "PUT"}
    assert written == {"l1"}, f"only the Spectra bulb is written, got {written}"
    report = _run(ambient.verify_looks(looks))
    assert report["lights_total"] == 1 and report["unlit"] == []
    off = (("*", "off", None, None, 100.0), ("*/Loft Ceiling Uplight", "skip", None, None, 0.0))
    named_bridge.clear()
    _run(ambient.reconcile_looks(off, 0))
    switched = {c[2].rsplit("/", 1)[-1] for c in named_bridge
                if c[0] == "REST" and c[1] == "PUT"}
    assert "l2" not in switched, "Night light never switches a left-alone bulb off either"


# ── 3. the house journey and opted-out sets ────────────────────────────────

def test_the_house_journey_travels_the_opted_out_sets_the_mode_names():
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.house import JourneyOverride

    class Card:
        def __init__(self, cid, opt_out=False, disabled=False, kind="set"):
            self.id, self.name, self.kind = cid, cid, kind
            self.scene_v2_opt_out, self.disabled = opt_out, disabled

    cards = [Card("calm-p", opt_out=True), Card("calm-g", opt_out=True),
             Card("other", opt_out=False), Card("off", opt_out=True, disabled=True)]
    override = {"value": None}
    c = DriftConductor(executor=None, set_cards=lambda: cards,
                       house_journey=lambda: override["value"])
    c._set_position = lambda sid: 100.0
    assert set(c._destination_pool()) == {"other"}, "room custody: the opt-out holds"
    override["value"] = JourneyOverride(set_ids=frozenset({"calm-p", "calm-g", "off"}),
                                        deg_per_min=15.0, mode_name="Standard")
    assert set(c._destination_pool()) == {"calm-p", "calm-g"}, \
        "a mode's own sets travel even opted out; a disabled one never"


# ── 4. the breathing effect ────────────────────────────────────────────────

def test_the_breathing_effect_is_registered_for_scenes():
    from fx import device_model
    assert device_model.motion_param_for("gradient") == "modulation_speed"
    assert device_model.bg_color_blocked("gradient") is True
    assert device_model.effect_dimension("gradient") == "1d"
    cls = device_model._effect_class("gradient")
    assert cls.__name__ == "TemporalGradientEffect", "the registered class, not the mixin"
    assert device_model.schema_default("gradient", "modulation_speed") == 0.5
    assert "gradient" in device_model.category_effect_options("Singles")


def test_a_breathing_scene_compiles_the_set_colour_and_no_background(monkeypatch):
    from fx import device_model
    from spectra.models.scene import SceneV2
    from spectra.services import color_sets, scene_compiler
    monkeypatch.setattr(device_model, "get_virtuals_for_category", lambda c: [])
    monkeypatch.setattr(device_model, "resolve_scope",
                        lambda v, c, r: ["single-color-effect"] if "Singles" in c else [])
    scene = SceneV2(name="House Star", devices=[{
        "target_kind": "virtual", "target": "single-color-effect", "effect_type": "gradient",
        "params": {"modulate": True, "modulation_effect": "sine", "modulation_speed": 0.8},
        "color": {"mode": "set"}}])
    card = color_sets.ColorSetCard(id="calm", name="Calm", kind="set", entries=[{
        "scope": {"virtual_ids": [], "categories": ["Singles"], "roles": []},
        "color_kind": "solid", "color_value": "#ffd37d", "bg_color": "#ffd37d",
        "bg_mode": "overwrite", "brightness": 1.0, "background_brightness": 0.64}])
    writes = scene_compiler.compile_scene(scene, card)
    cfg = next(w["config"] for w in writes if w["virtual_id"] == "single-color-effect")
    assert cfg["gradient"] == "#ffd37d"
    assert cfg["modulate"] is True
    assert "background_color" not in cfg, "no background: it would fill the exhale"


# ── 5. an ordinary take pre-freezes the Hue areas a mode will hold ──────────

def _hue_mode(**kw):
    from spectra.services import house_store
    mode = house_store.put_mode(HouseMode(name="Night light", ha_aliases=["Bedtime"], **kw))
    st = house_store.state()
    st.mode_id = mode.id
    house_store.save_state()
    return mode


def test_take_frozen_areas_names_exactly_what_the_mode_will_hold(tmp_path):
    from spectra.services import house
    _hue_mode(hue=[HueLook(area="hue-lights", look="off"),
                   HueLook(area="dining-hues", look="hold", kelvin=2000),
                   HueLook(area="other", look="show")], music="ignore")
    _settings(enabled=False)
    assert house.take_frozen_areas() == [], "switched off: nothing is named"
    _settings(enabled=True)
    assert house.take_frozen_areas() == ["dining-hues", "hue-lights"], "a show look streams"


def test_every_area_reads_the_hue_devices_from_the_stack_config(tmp_path):
    from spectra.services import house
    (tmp_path / "config.json").write_text(json.dumps({"devices": [
        {"id": "hue-lights", "type": "hue"}, {"id": "crystal", "type": "wled"},
        {"id": "dining-hues", "type": "hue"}]}))
    _hue_mode(hue=[HueLook(area="*", kelvin=3521)])
    assert house.take_frozen_areas(tmp_path) == ["dining-hues", "hue-lights"]


def test_music_whose_hue_follows_the_show_is_never_frozen_on_a_take():
    from spectra.services import house
    _hue_mode(hue=[HueLook(area="hue-lights", kelvin=3521)], music="show", music_hue="room")
    house.deps.playing = lambda: True
    assert house.take_frozen_areas() == []
    house.deps.playing = lambda: False
    assert house.take_frozen_areas() == ["hue-lights"]


def test_a_take_names_them_before_the_stack_comes_up(monkeypatch, tmp_path):
    from fx import facade, hue_freeze, light_ownership
    from spectra.services import engine, handover
    from spectra.services.live_host import live
    _hue_mode(hue=[HueLook(area="hue-lights", look="off")], music="ignore")
    hue_freeze.set_pending({"from-a-restart"})
    seen = {}

    async def activate(grant, config_dir, **kw):
        seen["pending"] = hue_freeze.pending()

    async def wait(**kw):
        return None
    monkeypatch.setattr(light_ownership, "mint_activation_grant", lambda w: "grant")
    monkeypatch.setattr(live, "activate", activate)
    monkeypatch.setattr(live, "wait_fully_active", wait)
    monkeypatch.setattr(facade, "set_host", lambda h: None)
    monkeypatch.setattr(engine, "go_live", lambda *a: None)
    _run(handover.SpectraSide(config_dir=str(tmp_path)).activate())
    assert seen["pending"] == {"hue-lights", "from-a-restart"}, "added to, never replacing"
    hue_freeze.clear()
    seen.clear()
    _run(handover.SpectraSide(config_dir=str(tmp_path), quiet=True).activate())
    assert seen["pending"] == set(), "a quiet take comes up black: no Hue named"


def test_after_take_waits_for_the_gate_then_unfreezes_what_it_does_not_hold(monkeypatch):
    from fx import hue_freeze
    from spectra.services import ambient_music_gate as gate
    from spectra.services import house_restart
    from spectra.services.live_host import live

    class Dev:
        def __init__(self):
            self.frozen = True

        async def set_frozen(self, v):
            self.frozen = v
    devs = {"hue-lights": Dev(), "dining-hues": Dev()}
    monkeypatch.setattr(live, "host", type("H", (), {"devices": devs})())
    hue_freeze.set_pending({"hue-lights", "dining-hues"})
    assert hue_freeze.consume("hue-lights") and hue_freeze.consume("dining-hues")
    in_flight = {"n": 3}

    def flying():
        in_flight["n"] -= 1
        return in_flight["n"] > 0
    monkeypatch.setattr(gate, "transition_in_flight", flying)
    monkeypatch.setattr(gate, "_held_looks", (("hue-lights", "hold", 284, None, 100.0),))

    async def no_sleep(_s):
        return None
    out = _run(house_restart.after_take(sleep=no_sleep))
    assert in_flight["n"] <= 0, "it waited for the gate's own transition"
    assert out == ["dining-hues"] and devs["hue-lights"].frozen is True
    assert devs["dining-hues"].frozen is False
