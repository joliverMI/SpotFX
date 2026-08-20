"""In "light" mode, an authored black background must clear to the room's
own Light background (RoomControlState.display_light_bg_color) instead of
literal #000000 -- his ruling, "do option three" (docs/SPECTRA_SPEC.md,
PR fm/spectra-light-mode-clear-to-mode-bg). Light paints its forced
background ONCE and never re-asserts it; every later colour-set-driven
scene fire writes its own background over it, and 30 entries across 22 of
his real colour sets author literal #000000, which in overwrite mode clears
whatever Light just painted -- his report: effects "start with a background
color appropriately and then go dark."

room_controls.resolve_authored_bg_color is the one substitution rule
(display_mode=="light" and bg_color=="#000000" -> display_light_bg_color);
this file proves it is actually wired into EVERY write point that can land
a colour-set/scene-entry background on the wire, and that "default"
(hybrid)/"dark" are byte-identical to before this fix in every one of them:

  #1 scene_compiler._entry_config      (dev.color.bg_color, fixed entries)
  #2 scene_compiler._apply_set_colors  (entry.bg_color, the MAIN colour-set path)
  #3 scene_response.ResponseEngine._color_jump (the flare colour jump)
  #4 drift_conductor.DriftConductor.apply_color_set (manual/journey-arrival apply)
  #5 drift_conductor.DriftConductor._journey_leg     (the destination-journey
     rotation -- reads state.background_color, a DIFFERENT source than the
     other four's entry.bg_color/dev.color.bg_color, hence its own proof)

No live storage, no LedFX I/O, no network -- RecordingExecutor only.
"""
from __future__ import annotations

import asyncio
from random import Random

import pytest


def _run(coro):
    return asyncio.run(coro)


VID = "v1"


def _categories_fixture(tmp_path) -> None:
    """Any test that resolves a ColorSetEntry's scope (SetScope.virtual_ids/
    categories) through fx.device_model.resolve_scope needs VID to be a
    known "imported" virtual — resolve_scope intersects against the
    category registry and silently drops anything outside it."""
    import json

    from fx import device_model
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"], "role": None}}))


def test_resolve_authored_bg_color_is_the_one_substitution_rule():
    from spectra.services import room_controls as rc

    # Light + authored black -> substituted.
    assert rc.resolve_authored_bg_color("#000000", "light", "#7800be") == "#7800be"
    # Hybrid/dark + authored black -> unchanged (the load-bearing clear step
    # for colour bleed between scenes stays intact).
    assert rc.resolve_authored_bg_color("#000000", "default", "#7800be") == "#000000"
    assert rc.resolve_authored_bg_color("#000000", "dark", "#7800be") == "#000000"
    # Light + a REAL authored colour (not black) -> untouched in every mode.
    assert rc.resolve_authored_bg_color("#ff9940", "light", "#7800be") == "#ff9940"
    assert rc.resolve_authored_bg_color("#ff9940", "default", "#7800be") == "#ff9940"


# ── write points #1/#2: scene_compiler.compile_scene ─────────────────────────

def test_write_point_1_fixed_entry_background():
    from spectra.models.scene import (SceneColorAssignment, SceneDeviceConfig,
                                      SceneV2)
    from spectra.services.scene_compiler import compile_scene

    scene = SceneV2(name="Fixed", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric", params={},
        color=SceneColorAssignment(mode="fixed", color_value="#ff0000",
                                   bg_color="#000000", bg_mode="overwrite"))])

    light = compile_scene(scene, display_mode="light", light_bg_color="#7800be")
    assert light[0]["config"]["background_color"] == "#7800be"

    hybrid = compile_scene(scene)   # defaults: display_mode="default"
    assert hybrid[0]["config"]["background_color"] == "#000000"


def test_write_point_2_color_set_entry_background_the_main_path(tmp_path):
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services.color_sets import ColorSetCard, ColorSetEntry, SetScope
    from spectra.services.scene_compiler import compile_scene

    _categories_fixture(tmp_path)
    scene = SceneV2(name="Set-driven", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric", params={})])
    card = ColorSetCard(id="set-black", name="Black-authoring", entries=[
        ColorSetEntry(scope=SetScope(virtual_ids=[VID]), color_kind="solid",
                      color_value="#ff0000", bg_color="#000000",
                      bg_mode="overwrite")])

    light = compile_scene(scene, card, display_mode="light", light_bg_color="#7800be")
    assert light[0]["config"]["background_color"] == "#7800be"

    hybrid = compile_scene(scene, card)
    assert hybrid[0]["config"]["background_color"] == "#000000"

    dark = compile_scene(scene, card, display_mode="dark", light_bg_color="#7800be")
    assert dark[0]["config"]["background_color"] == "#000000"


@pytest.fixture()
def _isolated_room_controls(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")


def test_fire_scene_entry_point_threads_room_display_mode(
        _isolated_room_controls, tmp_path):
    """fire_scene is the real API entry point (not just compile_scene
    directly) -- proves the room_controls load this fix adds threads
    display_mode/display_light_bg_color through, dry-run (no fx_seam I/O)."""
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services import room_controls as rc
    from spectra.services import scene_compiler
    from spectra.services.color_sets import ColorSetCard, ColorSetEntry, SetScope

    _categories_fixture(tmp_path)
    scene = SceneV2(name="Set-driven", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric", params={})])
    card = ColorSetCard(id="set-black", name="Black-authoring", entries=[
        ColorSetEntry(scope=SetScope(virtual_ids=[VID]), color_kind="solid",
                      color_value="#ff0000", bg_color="#000000",
                      bg_mode="overwrite")])

    rc.save_room_controls(rc.RoomControlState(
        display_mode="light", display_light_bg_color="#7800be"))
    result = _run(scene_compiler.fire_scene(scene, color_set=card, dry_run=True))
    assert result["writes"][0]["config"]["background_color"] == "#7800be"

    rc.save_room_controls(rc.RoomControlState(display_mode="default"))
    result = _run(scene_compiler.fire_scene(scene, color_set=card, dry_run=True))
    assert result["writes"][0]["config"]["background_color"] == "#000000"


# ── write point #3: scene_response.ResponseEngine._color_jump ────────────────

def _black_card():
    from spectra.services.color_sets import ColorSetCard, ColorSetEntry, SetScope
    return ColorSetCard(id="set-black", name="Black-authoring", entries=[
        ColorSetEntry(scope=SetScope(virtual_ids=[VID]), color_kind="solid",
                      color_value="#ff0000", bg_color="#000000",
                      bg_mode="overwrite")])


def _flare_scene():
    from spectra.models.scene import FlareBand, ResponseSpec, SceneDeviceConfig, SceneV2
    return SceneV2(name="Flaring", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric", params={})],
        responses={"flare": ResponseSpec(
            bands=[FlareBand(intensity_min=0.0, intensity_max=1.0)],
            reroll_dice=False, color_set_jump=True)})


def _fire(conductor, scene, config):
    dev = scene.devices[0]
    conductor.on_scene_fire(scene, [{
        "virtual_id": VID, "effect_type": dev.effect_type,
        "config": dict(config), "entry_id": dev.id, "color_mode": "set"}])


@pytest.mark.parametrize("mode, expect", [("light", "#7800be"), ("default", "#000000")])
def test_write_point_3_flare_color_jump(mode, expect, tmp_path):
    from spectra.models.sequencer import SelectorEntry, SequencerConfig
    from spectra.services import color_journey as cj
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor
    from spectra.services.scene_response import ResponseEngine

    _categories_fixture(tmp_path)
    black_card = _black_card()
    scene = _flare_scene()
    seq_config = SequencerConfig(color_set_entries={"set-black": SelectorEntry()})
    executor = RecordingExecutor()
    conductor = DriftConductor(
        executor=executor, room_load=lambda: cj.RoomColorState(),
        room_save=lambda st: None, set_position=lambda sid: 10.0,
        set_cards=lambda: [black_card], sequencer_config=lambda: seq_config)
    _fire(conductor, scene, {"background_color": "#000000"})
    responder = ResponseEngine(
        conductor=conductor, executor=executor, rng=Random(7),
        sequencer_config=lambda: seq_config, curve_profiles=lambda: {},
        eligible_sets=lambda sc: {"set-black": 10.0},
        room_load=lambda: cj.RoomColorState(), room_save=lambda st: None,
        room_controls_load=lambda: rc.RoomControlState(
            display_mode=mode, display_light_bg_color="#7800be"))
    responder._set_card = lambda sid: black_card

    record = _run(responder.on_event("flare", 0.6))
    assert record["color_jump"]["result"] == "jumped", record

    writes = [w for w in executor.writes if "background_color" in w["params"]]
    assert writes, "expected a glide carrying background_color"
    assert writes[-1]["params"]["background_color"] == expect


# ── write point #4: drift_conductor.DriftConductor.apply_color_set ───────────

@pytest.mark.parametrize("mode, expect", [("light", "#7800be"), ("default", "#000000")])
def test_write_point_4_apply_color_set(mode, expect, tmp_path):
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services import color_journey as cj
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor

    _categories_fixture(tmp_path)
    black_card = _black_card()
    scene = SceneV2(name="Applied", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric", params={})])
    executor = RecordingExecutor()
    conductor = DriftConductor(
        executor=executor, room_load=lambda: cj.RoomColorState(),
        room_save=lambda st: None,
        room_controls_load=lambda: rc.RoomControlState(
            display_mode=mode, display_light_bg_color="#7800be"))
    _fire(conductor, scene, {"background_color": "#000000"})

    landed = _run(conductor.apply_color_set(black_card))
    assert landed == 1

    assert conductor.virtuals[VID].background_color == expect
    writes = [w for w in executor.writes if "background_color" in w["params"]]
    assert writes[-1]["params"]["background_color"] == expect


# ── write point #5: drift_conductor.DriftConductor._journey_leg ──────────────

@pytest.mark.parametrize("mode, expect", [("light", "#7800be"), ("default", "#000000")])
def test_write_point_5_journey_leg_rotation(mode, expect):
    """state.background_color is a DIFFERENT source than the other four
    write points' entry.bg_color -- it is whatever an earlier fire/apply
    left carried on the virtual. Seed it with a raw, unresolved #000000
    directly (bypassing every other write point) so this one's own
    resolve call is what's under test, not an inherited value."""
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services import color_journey as cj
    from spectra.services import room_controls as rc
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor

    scene = SceneV2(name="Journeying", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric", params={})])
    executor = RecordingExecutor()
    room_box = [cj.RoomColorState(wheel_position_deg=0.0, active_set_id="set-a")]
    positions = {"set-a": 0.0, "set-b": 90.0}
    cards = [type("Card", (), {"id": sid, "name": sid,
                               "scene_v2_opt_out": False})() for sid in positions]
    conductor = DriftConductor(
        executor=executor, leg_s=20.0,
        room_load=lambda: room_box[0],
        room_save=lambda st: room_box.__setitem__(0, st),
        set_position=lambda sid: positions.get(sid),
        set_cards=lambda: cards,
        room_controls_load=lambda: rc.RoomControlState(
            display_mode=mode, display_light_bg_color="#7800be"),
        rng=Random(11))
    _fire(conductor, scene, {"background_color": "#000000", "gradient": "#ff0000"})
    assert conductor.virtuals[VID].background_color == "#000000"   # raw, unresolved seed

    record = _run(conductor.tick())
    assert record is not None and record["journey"]["paused"] is False, record

    assert conductor.virtuals[VID].background_color == expect
    writes = [w for w in executor.writes
             if w["kind"] == "glide" and "background_color" in w["params"]]
    assert writes, "expected a journey-leg glide carrying background_color"
    assert writes[-1]["params"]["background_color"] == expect
