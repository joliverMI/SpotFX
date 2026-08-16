"""Frame-level proof for the trigger engine — THE KEYSTONE's execution half:
a SpectraTrigger placed at a song moment fires its action, and the action's
effect actually lands on the real vendored render pipeline, at the moment
the engine's clock crosses the trigger's timestamp (never before).

Same harness discipline as test_spectra_engine.py: FacadeExecutor driving
fx.headless's dummy device, deterministic frame-stepping under a fake clock,
audio silenced. fire_scene's proof exercises the REAL resolve/compile/
re-baseline logic (scene_compiler.resolve_scene + compile_scene,
DriftConductor.on_scene_fire) — binding resolution included, so the fire
demonstrably used the TRIGGER's own intensity — landing writes through the
same FacadeExecutor.jump() every other S2 proof in this repo uses (the
owner-Fire HTTP/facade seam, fx_seam, is intentionally not exercised here:
its production PUT requires a virtual's active effect to already match —
see fx/facade.py's _effects_put — so pre-attaching via headless.attach_effect
and landing through the executor is the established, thread-safe pattern for
frame-stepped proofs; fx_seam routing itself is spec-covered, not frame-
rendered, in check_spectra.py).

No LedFX service, no HTTP, no audio hardware (fx.headless.silence_audio).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from random import Random

import numpy as np
import pytest

from fx import device_model, facade, headless

VID = headless.DEFAULT_VIRTUAL_ID


def _run(coro):
    return asyncio.run(coro)


def _categories_fixture(tmp_path) -> None:
    device_model.CATEGORIES_FILE = tmp_path / "device_categories.json"
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "c1": {"id": "c1", "name": "Headless", "parent_id": None,
               "virtuals": [VID], "effects": ["concentric"], "role": None}}))


async def _host(tmp_path, sub: str):
    host = await headless.start_headless_host(str(tmp_path / sub))
    facade.set_host(host)
    return host, host.virtuals.get(VID)


def _conductor_and_responder(clock, *, room=None, set_positions=None):
    """The S2 engine wiring, isolated per test — same shape as
    test_spectra_engine.py's _engine() helper."""
    from spectra.models.sequencer import SelectorEntry, SequencerConfig
    from spectra.services import color_journey as cj
    from spectra.services.color_sets import ColorSetCard
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import FacadeExecutor
    from spectra.services.scene_response import ResponseEngine

    room_box = [room or cj.RoomColorState()]
    positions = set_positions or {}
    cards = [ColorSetCard(id=sid, name=sid, entries=[]) for sid in positions]
    seq_config = SequencerConfig(color_set_entries={
        sid: SelectorEntry() for sid in positions})
    executor = FacadeExecutor(clock=lambda: clock.now)
    conductor = DriftConductor(
        executor=executor, clock=lambda: clock.now, leg_s=20.0,
        intensity=lambda: 1.0, drift_profiles=lambda: {}, curve_profiles=lambda: {},
        room_load=lambda: room_box[0],
        room_save=lambda st: room_box.__setitem__(0, st),
        set_position=lambda sid: positions.get(sid),
        set_cards=lambda: cards, sequencer_config=lambda: seq_config,
        rng=Random(3))
    responder = ResponseEngine(
        conductor=conductor, executor=executor, rng=Random(5),
        clock=lambda: clock.now, sequencer_config=lambda: seq_config,
        curve_profiles=lambda: {}, eligible_sets=lambda sc: dict(positions),
        room_load=lambda: room_box[0], room_save=lambda st: room_box.__setitem__(0, st))
    return executor, conductor, responder, room_box


async def _make_fire_scene(executor, conductor, scene):
    """The action-side proof of fire_scene: the REAL resolve → compile →
    re-baseline pipeline (binding resolution included), landed on the real
    device through the same executor every S2 write already uses."""
    from spectra.services import scene_compiler
    from spectra.services.binding_resolver import FireContext

    async def fire_scene(scene_id, color_set_id, intensity):
        ctx = FireContext(intensity, rng=Random(1))
        resolved = scene_compiler.resolve_scene(scene, ctx)
        writes = scene_compiler.compile_scene(resolved)
        conductor.on_scene_fire(scene, writes)
        for w in writes:
            await executor.jump(w["virtual_id"], w["effect_type"], w["config"])
    return fire_scene


# ── proof 1: fire_scene lands the trigger's OWN intensity, exactly at crossing ──

def test_trigger_fires_scene_action_with_its_own_intensity_at_its_moment(tmp_path):
    from spectra.models.binding import ValueBinding
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.models.trigger import FireSceneAction, SpectraTrigger
    from spectra.services.trigger_engine import TriggerEngine

    _categories_fixture(tmp_path)
    # gradient_scale maps intensity 0..1 -> 0.5..2.0: a real binding, not a
    # static value, so a landed 1.25 can only come from intensity=0.5.
    scene = SceneV2(name="Triggered", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric",
        params={"gradient_scale": ValueBinding(
            signal="trigger_intensity", out_min=0.5, out_max=2.0)})])
    trig = SpectraTrigger(timestamp_ms=5000, action=FireSceneAction(
        scene_id=scene.id, intensity=0.5))

    async def main():
        host, virtual = await _host(tmp_path, "scene")
        try:
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(host, virtual, "concentric",
                                                {"gradient_scale": 1.0})
                from spectra.services.drift_conductor import DriftConductor
                from spectra.services.fx_executor import FacadeExecutor
                executor = FacadeExecutor(clock=lambda: clock.now)
                conductor = DriftConductor(executor=executor,
                                           clock=lambda: clock.now, leg_s=20.0)
                fire_scene = await _make_fire_scene(executor, conductor, scene)

                engine = TriggerEngine(list_triggers=lambda uri: [trig],
                                       fire_scene=fire_scene,
                                       render_intensity=lambda x: x)
                await engine.on_track_state("song:1")

                await engine.tick(4000)   # before the trigger's moment
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.0), \
                    "nothing fires before the trigger's timestamp is crossed"

                fired = await engine.tick(5000)   # crosses exactly at 5000
                assert len(fired) == 1 and fired[0].id == trig.id
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.25), \
                    "the fire used the TRIGGER's own intensity (0.5 -> 1.25), " \
                    "landed on the real dummy device on the crossing tick"

                again = await engine.tick(6000)   # already fired — no repeat
                assert again == []
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── proof 2: fire_response drives the real ResponseEngine at its moment ──────

def test_trigger_fires_response_action_on_the_real_pipeline(tmp_path):
    from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,
                                      SceneDeviceConfig, SceneV2)
    from spectra.models.trigger import FireResponseAction, SpectraTrigger
    from spectra.services.trigger_engine import TriggerEngine

    _categories_fixture(tmp_path)
    scene = SceneV2(name="Responding", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric",
        params={"gradient_scale": 1.0})],
        flare_kinds=[FlareKind(name="Patch", type="permanent",
                               params={"gradient_scale": 1.8})],
        responses={"drop": ResponseSpec(bands=[
            FlareBand(intensity_min=0.7, intensity_max=1.0,
                      kinds={"Patch": 1.0})])})
    trig = SpectraTrigger(timestamp_ms=2000,
                          action=FireResponseAction(event_class="drop", intensity=0.9))

    async def main():
        host, virtual = await _host(tmp_path, "response")
        try:
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(host, virtual, "concentric",
                                                {"gradient_scale": 1.0})
                executor, conductor, responder, _ = _conductor_and_responder(clock)
                writes = [{"virtual_id": VID, "effect_type": "concentric",
                          "config": {"gradient_scale": 1.0},
                          "entry_id": scene.devices[0].id, "color_mode": "set"}]
                conductor.on_scene_fire(scene, writes)

                engine = TriggerEngine(list_triggers=lambda uri: [trig],
                                       fire_response=responder.on_event,
                                       render_intensity=lambda x: x)
                await engine.on_track_state("song:2")

                await engine.tick(1000)
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.0), \
                    "the response hasn't fired before its trigger's moment"

                fired = await engine.tick(2000)
                assert len(fired) == 1
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.8), \
                    "fire_response reached the real response engine — the " \
                    "drop band's patch landed on the crossing tick, exactly " \
                    "as a bridge-classified drop would"
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── proof 2b: fire_scene_update (UPDATE) fires bypassing band gating ─────────

def test_trigger_fires_scene_update_action_on_the_real_pipeline(tmp_path):
    """A fire_scene_update trigger reaches the real ResponseEngine.on_update
    at its moment — no response bands configured at all on this scene,
    proving update doesn't need them (unlike fire_response's proof 2
    above)."""
    from spectra.models.scene import (FlareKind, ParamTarget,
                                      SceneDeviceConfig, SceneV2)
    from spectra.models.trigger import FireSceneUpdateAction, SpectraTrigger
    from spectra.services.trigger_engine import TriggerEngine

    _categories_fixture(tmp_path)
    scene = SceneV2(name="Updating", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric",
        params={"gradient_scale": 1.0})],
        flare_kinds=[FlareKind(
            name="Big Shift", type="permanent",
            params={"gradient_scale": ParamTarget(mode="absolute", value=1.8)})],
        update_kind="Big Shift")
    trig = SpectraTrigger(timestamp_ms=2000,
                          action=FireSceneUpdateAction(intensity=1.0))

    async def main():
        host, virtual = await _host(tmp_path, "update")
        try:
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(host, virtual, "concentric",
                                                {"gradient_scale": 1.0})
                executor, conductor, responder, _ = _conductor_and_responder(clock)
                writes = [{"virtual_id": VID, "effect_type": "concentric",
                          "config": {"gradient_scale": 1.0},
                          "entry_id": scene.devices[0].id, "color_mode": "set"}]
                conductor.on_scene_fire(scene, writes)

                engine = TriggerEngine(list_triggers=lambda uri: [trig],
                                       fire_scene_update=responder.on_update,
                                       render_intensity=lambda x: x)
                await engine.on_track_state("song:update")

                await engine.tick(1000)
                headless.render_frames(virtual, 60, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.0), \
                    "update hasn't fired before its trigger's moment"

                fired = await engine.tick(2000)
                assert len(fired) == 1
                # the ramp-in, not an instant jump: not landed one frame later
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] < 1.8
                # but landed well past the ramp
                headless.render_frames(virtual, 300, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.8), \
                    "fire_scene_update reached the real response engine's " \
                    "on_update — no response band was configured at all"
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── proof 3: select_color_set drives the real room-colour apply at its moment ──

def test_trigger_fires_select_color_set_action_on_the_real_pipeline(tmp_path):
    from spectra.services.color_sets import ColorSetCard, ColorSetEntry, SetScope
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.models.trigger import SelectColorSetAction, SpectraTrigger
    from spectra.services.trigger_engine import TriggerEngine

    _categories_fixture(tmp_path)
    scene = SceneV2(name="Coloured", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric",
        params={"gradient_scale": 1.0})])
    card = ColorSetCard(id="warm", name="Warm", entries=[ColorSetEntry(
        scope=SetScope(virtual_ids=[VID]), color_kind="solid", color_value="#ff8800")])
    trig = SpectraTrigger(timestamp_ms=1500,
                          action=SelectColorSetAction(set_id=card.id))

    async def main():
        host, virtual = await _host(tmp_path, "color")
        try:
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(host, virtual, "concentric",
                                                {"gradient_scale": 1.0})
                executor, conductor, _, room_box = _conductor_and_responder(
                    clock, set_positions={card.id: 30.0})
                writes = [{"virtual_id": VID, "effect_type": "concentric",
                          "config": {"gradient_scale": 1.0},
                          "entry_id": scene.devices[0].id, "color_mode": "set"}]
                conductor.on_scene_fire(scene, writes)

                engine = TriggerEngine(
                    list_triggers=lambda uri: [trig],
                    select_color_set=lambda set_id: conductor.apply_set_directly(card))
                await engine.on_track_state("song:3")

                await engine.tick(1000)
                assert room_box[0].active_set_id is None, \
                    "the colour hasn't been selected before its trigger's moment"

                fired = await engine.tick(1500)
                assert len(fired) == 1
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert room_box[0].active_set_id == card.id
                assert effect._config.get("gradient") == "#ff8800", \
                    "select_color_set reached the real drift_conductor." \
                    "apply_set_directly — the room's set and the live " \
                    "device's colour both moved on the trigger's word"
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── proof 4a: the automatic song-transition fire lands on the real pipeline,
#    on a genuine song change, NOT on the first song ever seen ──────────────

def test_transition_fire_lands_on_real_pipeline_on_song_change(tmp_path):
    """The settings model's floor tier ("transitions"): scene changes ON
    song transitions, driven directly by on_track_state (module docstring's
    _fire_transition section) rather than a stored trigger — proven here
    end to end through the real resolve/compile/land pipeline, same as a
    stored fire_scene trigger's own proof (test 1 above)."""
    from spectra.models.binding import ValueBinding
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.services.trigger_engine import TriggerEngine

    _categories_fixture(tmp_path)
    scene = SceneV2(name="OnTransition", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric",
        params={"gradient_scale": ValueBinding(
            signal="trigger_intensity", out_min=0.5, out_max=2.0)})])

    async def main():
        host, virtual = await _host(tmp_path, "transition")
        try:
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(host, virtual, "concentric",
                                                {"gradient_scale": 1.0})
                from spectra.services.drift_conductor import DriftConductor
                from spectra.services.fx_executor import FacadeExecutor
                executor = FacadeExecutor(clock=lambda: clock.now)
                conductor = DriftConductor(executor=executor,
                                           clock=lambda: clock.now, leg_s=20.0)
                fire_scene = await _make_fire_scene(executor, conductor, scene)

                engine = TriggerEngine(
                    list_triggers=lambda uri: [], fire_scene=fire_scene,
                    select_scene=lambda intensity: scene.id,
                    transition_intensity=lambda: 0.5,
                    render_intensity=lambda x: x)

                await engine.on_track_state("song:first")   # arms only
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.0), \
                    "the FIRST song ever seen only arms the transition " \
                    "clock — it isn't itself a transition, so nothing fires"

                await engine.on_track_state("song:second")  # a real transition
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.25), \
                    "a genuine song-to-song change fired the automatic " \
                    "transition scene change through the real resolve/" \
                    "compile/land pipeline, at the transition's own intensity"
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── proof 4b: scene_change_mode="transitions" still fires the automatic
#    transition change but skips a hand-authored trigger at the same moment ──

def test_scene_change_mode_transitions_skips_authored_trigger(tmp_path):
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.models.trigger import FireSceneAction, SpectraTrigger
    from spectra.services.trigger_engine import TriggerEngine

    _categories_fixture(tmp_path)
    scene = SceneV2(name="Authored", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric",
        params={"gradient_scale": 1.0})])
    trig = SpectraTrigger(timestamp_ms=1000, source="authored",
                          action=FireSceneAction(scene_id=scene.id))

    async def main():
        host, virtual = await _host(tmp_path, "mode-gate")
        try:
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(host, virtual, "concentric",
                                                {"gradient_scale": 9.0})
                from spectra.services.drift_conductor import DriftConductor
                from spectra.services.fx_executor import FacadeExecutor
                executor = FacadeExecutor(clock=lambda: clock.now)
                conductor = DriftConductor(executor=executor,
                                           clock=lambda: clock.now, leg_s=20.0)
                fire_scene = await _make_fire_scene(executor, conductor, scene)

                engine = TriggerEngine(
                    list_triggers=lambda uri: [trig], fire_scene=fire_scene,
                    scene_change_mode=lambda: "transitions")
                await engine.on_track_state("gate-song")

                fired = await engine.tick(1000)
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert fired == [] and effect._config["gradient_scale"] == pytest.approx(9.0), \
                    "scene_change_mode=transitions skips the hand-authored " \
                    "trigger's crossing — only the automatic transition " \
                    "fire (proof 4a) happens in this tier"
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())


# ── proof 5: a GENERATED trigger's scene_id=None resolves through the real
#    selection kernel, then fires and lands exactly like a hand-picked one ──

def test_generated_trigger_resolves_scene_via_kernel_and_fires_at_its_moment(
    tmp_path, monkeypatch,
):
    """front 3 (decision-mid-song-model.md): a mid-song-generated trigger
    never bakes a scene_id — it names a moment, and spectra.services.
    trigger_engine's production _default_select_scene resolves WHICH scene
    through the SAME selection kernel the sequencer's own rolls use
    (spectra.services.selection_kernel + sequencer_store), at the trigger's
    own intensity. This proof exercises that real default (not an injected
    fake) end to end: real sequencer config on disk -> real kernel draw ->
    real resolve/compile/land on the dummy device, at the exact tick the
    engine's clock crosses the trigger's timestamp."""
    from spectra import config as scfg
    from spectra.models.binding import ValueBinding
    from spectra.models.scene import SceneDeviceConfig, SceneV2
    from spectra.models.sequencer import SelectorEntry, SequencerConfig
    from spectra.models.trigger import FireSceneAction, SpectraTrigger
    from spectra.services import scene_store, sequencer_store
    from spectra.services.trigger_engine import TriggerEngine

    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "SEQUENCER_FILE", tmp_path / "sequencer.json")

    _categories_fixture(tmp_path)
    # Same gradient_scale/trigger_intensity binding as proof 1 — a landed
    # value can only come from the trigger's own intensity flowing through
    # both the kernel draw AND the fire.
    scene = SceneV2(name="Kernel Picked", devices=[SceneDeviceConfig(
        target_kind="virtual", target=VID, effect_type="concentric",
        params={"gradient_scale": ValueBinding(
            signal="trigger_intensity", out_min=0.5, out_max=2.0)})])
    scene_store.save(scene)
    # The sole candidate: a flat curve, so the kernel's weighted draw has
    # exactly one positive-score option and must pick it deterministically.
    sequencer_store.save_config(SequencerConfig(entries={
        scene.id: SelectorEntry(inline_points=[{"x": 0.0, "y": 1.0}])}))

    trig = SpectraTrigger(timestamp_ms=3000,
                          action=FireSceneAction(scene_id=None, intensity=0.5),
                          source="generated", generator_key="section:3000")

    async def main():
        host, virtual = await _host(tmp_path, "kernelfire")
        try:
            with headless.fake_clock() as clock:
                effect = headless.attach_effect(host, virtual, "concentric",
                                                {"gradient_scale": 1.0})
                from spectra.services.drift_conductor import DriftConductor
                from spectra.services.fx_executor import FacadeExecutor
                executor = FacadeExecutor(clock=lambda: clock.now)
                conductor = DriftConductor(executor=executor,
                                           clock=lambda: clock.now, leg_s=20.0)
                fire_scene = await _make_fire_scene(executor, conductor, scene)

                # select_scene is left at its production default — this is
                # the real kernel, not an injected picker.
                engine = TriggerEngine(list_triggers=lambda uri: [trig],
                                       fire_scene=fire_scene,
                                       render_intensity=lambda x: x)
                await engine.on_track_state("song:kernel")

                await engine.tick(2000)
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.0), \
                    "nothing fires before the trigger's timestamp is crossed"

                fired = await engine.tick(3000)
                assert len(fired) == 1 and fired[0].id == trig.id
                headless.render_frames(virtual, 1, clock=clock, dt=1 / 60)
                assert effect._config["gradient_scale"] == pytest.approx(1.25), \
                    "the kernel-picked scene fired using the TRIGGER's own " \
                    "intensity (0.5 -> 1.25), landed on the real dummy " \
                    "device on the crossing tick — same as a baked scene_id"
        finally:
            facade.set_host(None)
            await host.shutdown()

    _run(main())
