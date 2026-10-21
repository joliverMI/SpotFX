"""ABSORB MUSIC'S LIGHT STAND-DOWN, PROVEN FROM THE SHOW SIDE
(data/absorb-music-plan/report.md §6.3 and §12 phase 2; his Q3: "nothing").

Held to tests/test_preview_holds_the_show.py's bar, which exists because a
hold once REPORTED itself set while his triggers kept firing underneath.
So nothing here reads Absorb's own report of itself. The hold arrives the
way it does in production — a SpotFX "state" message carrying
`absorb.lights_held` fed to the real bridge — and then the REAL trigger
engine is driven over a real position feed with a corpus of every action
kind, and the ENGINE'S OUTPUT is measured:

  * zero writes at fx_seam (the one seam a light byte leaves SPECTRA by)
    and zero writes on the response engine's executor;
  * zero response surges;
  * every refusal NAMED in fire_history's "deferred" bucket with
    reason "absorb", and the hold's start/end each a show-log line;
  * then the SAME sweep after SpotFX releases the lights fires for real —
    otherwise "nothing fired" would only prove the corpus was inert.

Plus a control that re-creates the un-gated world and proves this harness
goes red on it, and one test per extra choke point the sweep cannot reach
(the drift conductor's deferral, the house's hand-in, Light Show cues, a
Show Sequence's song count, the analysed colour moment, Ambient's read).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fx import device_model


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    for name, fn in (("SCENES_FILE", "scenes.json"),
                     ("SEQUENCER_FILE", "sequencer.json"),
                     ("DRIFT_PROFILES_FILE", "drift_profiles.json"),
                     ("ROOM_COLOR_FILE", "room_color.json"),
                     ("ROOM_CONTROLS_FILE", "room_controls.json"),
                     ("GRADIENT2D_FILE", "gradients2d.json"),
                     ("FIRE_HISTORY_FILE", "fire_history.json"),
                     ("SHOW_LOG_FILE", "show_log.json"),
                     ("COLOR_SETS_FILE", "color_sets.json"),
                     ("FLARE_PREVIEW_HOLD_FILE", "flare_preview_hold.json")):
        monkeypatch.setattr(scfg, name, tmp_path / fn)
    monkeypatch.setattr(device_model, "CATEGORIES_FILE",
                        tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()
    scfg.COLOR_SETS_FILE.write_text(json.dumps({"cs-blue": {
        "id": "cs-blue", "name": "Blue", "entries": [{
            "scope": {"virtual_ids": [VID]}, "color_kind": "solid",
            "color_value": "#0000ff"}]}}))


@pytest.fixture
def bridge(monkeypatch):
    """The production bridge singleton, with its track hook switched off so
    feeding it a state message changes only what this test is about."""
    from spectra.services import engine
    b = engine.bridge
    monkeypatch.setattr(b, "_on_track_uri", None)
    b._absorb, b._absorb_at, b._absorb_held_seen = None, None, False
    yield b
    b._absorb, b._absorb_at, b._absorb_held_seen = None, None, False


def _state(lights_held: bool, state: str = "running") -> dict:
    """SpotFX's websocket "state" message as services/websocket_manager.py
    shapes it, `absorb` being services/absorb.py's status_brief()."""
    return {"type": "state", "paused": False, "track": None,
            "absorb": {"state": state, "stage": "capturing", "run_id": "run1",
                       "lights_held": lights_held}}


async def _hold(bridge, held: bool) -> None:
    await bridge.handle_message(_state(held, "running" if held else "ended"))


VID = "v1"


class _SeamRecorder:
    def __init__(self) -> None:
        self.writes: list[dict] = []

    async def apply_writes(self, writes, *, transition_ms: int = 0, **_kw) -> None:
        for w in writes:
            self.writes.append({"virtual_id": w["virtual_id"]})

    async def get_virtuals(self) -> dict:
        effect = {"type": "radial", "config": {"spin": 0.1}}
        return {VID: {"effect": dict(effect, config=dict(effect["config"]))}}

    def reset(self) -> None:
        self.writes.clear()


@pytest.fixture
def seam(monkeypatch):
    from spectra.services import fx_seam
    rec = _SeamRecorder()
    monkeypatch.setattr(fx_seam, "apply_writes", rec.apply_writes)
    monkeypatch.setattr(fx_seam, "get_virtuals", rec.get_virtuals)
    return rec


def _scene():
    from spectra.models.scene import (FlareBand, FlareKind, ParamTarget,
                                      ResponseSpec, SceneDeviceConfig, SceneV2)
    kind = FlareKind(name="spin-flare", type="momentary",
                     params={"spin": ParamTarget(mode="absolute", value=0.9)})
    scene = SceneV2(
        name="Absorb Hold Scene",
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual", target=VID,
                                   effect_type="radial", params={"spin": 0.2})],
        flare_kinds=[kind],
        responses={"flare": ResponseSpec(bands=[
            FlareBand(intensity_min=0.0, intensity_max=1.0,
                      kinds={"spin-flare": 1.0})])})
    from spectra.services import scene_store
    scene_store.save(scene)
    return scene


def _corpus(scene_id: str):
    """One trigger of EVERY action kind — the preview test's three plus a
    stored colour-set trigger, which is a separate choke point."""
    from spectra.models.trigger import (FireResponseAction, FireSceneAction,
                                        FireSceneUpdateAction,
                                        SelectColorSetAction, SpectraTrigger)
    return [
        SpectraTrigger(timestamp_ms=1000,
                       action=FireSceneAction(scene_id=scene_id, intensity=0.6)),
        SpectraTrigger(timestamp_ms=2000,
                       action=FireResponseAction(event_class="flare", intensity=0.6)),
        SpectraTrigger(timestamp_ms=3000,
                       action=FireSceneUpdateAction(intensity=0.6)),
        SpectraTrigger(timestamp_ms=3500,
                       action=SelectColorSetAction(set_id="cs-blue")),
        SpectraTrigger(timestamp_ms=4000,
                       action=FireSceneAction(scene_id=scene_id, intensity=0.9)),
    ]


def _engine(triggers):
    from spectra.services.trigger_engine import TriggerEngine
    return TriggerEngine(list_triggers=lambda uri: list(triggers),
                         scene_change_mode=lambda: "full",
                         sequencer_enabled=lambda: False)


def _install_scratch_responder(monkeypatch, scene):
    from random import Random
    from spectra.services import engine as engine_mod
    from spectra.services import flare_preview
    from spectra.services.fx_executor import RecordingExecutor
    clock = flare_preview._FakeClock()
    executor = RecordingExecutor(clock=clock)
    _cond, responder, _writes = flare_preview._scratch_engine(
        scene, 1.0, clock, executor)
    responder._rng = Random(7)
    monkeypatch.setattr(engine_mod, "responses", responder)
    monkeypatch.setattr(engine_mod, "conductor", responder.conductor)
    return responder, executor


def _absorb_deferrals() -> list[dict]:
    from spectra.services import fire_history
    return [e for e in fire_history.load_show_log()
            if e.get("bucket") == "deferred"
            and (e.get("detail") or {}).get("reason") == "absorb"]


def _absorb_lines() -> list[str]:
    from spectra.services import fire_history
    return [e.get("key") for e in fire_history.load_show_log()
            if e.get("bucket") == "absorb"]


async def _measure(engine, responder, executor, seam, uri: str) -> dict:
    before = len(_absorb_deferrals())
    seam.reset()
    executor.writes.clear()
    surges = len(responder.surges)
    await engine.on_track_state(uri)
    fired = 0
    for pos in range(0, 5001, 200):
        fired += len(await engine.tick(pos))
    await asyncio.sleep(0)
    return {"engine_fired": fired, "seam_writes": len(seam.writes),
            "executor_writes": len(executor.writes),
            "new_surges": len(responder.surges) - surges,
            "new_absorb_deferrals": len(_absorb_deferrals()) - before}


# ═══ 1. the window holds every trigger, and says so ════════════════════════

def test_an_absorb_window_holds_every_trigger_and_names_it(monkeypatch, seam, bridge):
    scene = _scene()
    responder, executor = _install_scratch_responder(monkeypatch, scene)

    async def main():
        await _hold(bridge, True)
        assert bridge.absorb_holds_lights() is True

        held = await _measure(_engine(_corpus(scene.id)), responder, executor,
                              seam, "song:absorb-held")
        # The engine DID cross all five marks: the refusal is downstream, at
        # the production choke points — not a corpus that never triggered.
        assert held["engine_fired"] == 5, held
        assert held["seam_writes"] == 0, (
            f"a light byte left SPECTRA during an Absorb window: {seam.writes}")
        assert held["executor_writes"] == 0, "the response engine wrote during a window"
        assert held["new_surges"] == 0, "a flare fired on a song nobody hears"
        # every one of the five refusals is named — scene x2, response,
        # update, colour set
        assert held["new_absorb_deferrals"] == 5, _absorb_deferrals()
        keys = {e["key"] for e in _absorb_deferrals()}
        assert {scene.id, "response:flare", "update",
                "select_color_set:cs-blue"} <= keys, keys

        # SpotFX gives the house back: the SAME sweep fires for real
        await _hold(bridge, False)
        assert bridge.absorb_holds_lights() is False
        freed = await _measure(_engine(_corpus(scene.id)), responder, executor,
                               seam, "song:absorb-freed")
        assert freed["engine_fired"] == 5, freed
        assert freed["seam_writes"] > 0, "the released show wrote nothing — inert corpus?"
        assert freed["new_surges"] >= 1, "the released show fired no response"
        assert freed["executor_writes"] > 0, "the colour set never landed"
        assert freed["new_absorb_deferrals"] == 0
        # the hold's start and end are each one show-log line
        assert _absorb_lines() == ["held", "released"]

    asyncio.run(main())


# ═══ 2. the measurement goes red on the un-gated world ═════════════════════

def test_the_measurement_would_catch_a_choke_point_that_ignored_absorb(
        monkeypatch, seam, bridge):
    """The bridge says held, but the choke points never ask — the shape the
    preview hold's founding defect had. This harness must see writes."""
    from spectra.services import absorb_hold
    scene = _scene()
    responder, executor = _install_scratch_responder(monkeypatch, scene)

    async def main():
        await _hold(bridge, True)
        monkeypatch.setattr(absorb_hold, "active", lambda: False)
        held = await _measure(_engine(_corpus(scene.id)), responder, executor,
                              seam, "song:ungated")
        assert held["seam_writes"] > 0 and held["new_surges"] >= 1, (
            "the un-gated world wrote nothing — this harness would not catch "
            "the defect it exists for")

    asyncio.run(main())


# ═══ 3. it can never stick ═════════════════════════════════════════════════

def test_the_hold_survives_a_disconnect_but_never_goes_stale(monkeypatch, bridge):
    from spectra.services import bridge as bridge_mod
    now = [1000.0]
    monkeypatch.setattr(bridge, "_clock", lambda: now[0])

    async def main():
        await _hold(bridge, True)
        bridge.connected = False                     # SpotFX restarting
        now[0] += 30
        assert bridge.absorb_holds_lights() is True
        now[0] += bridge_mod.ABSORB_STALE_S
        assert bridge.absorb_holds_lights() is False, "a dead SpotFX held the show forever"

    asyncio.run(main())


def test_a_state_without_absorb_or_with_it_unheld_is_not_a_hold(bridge):
    async def main():
        await bridge.handle_message({"type": "state", "track": None})
        assert bridge.absorb_holds_lights() is False
        await bridge.handle_message({"type": "state", "track": None,
                                     "absorb": {"state": "running", "lights_held": False}})
        assert bridge.absorb_holds_lights() is False
        await bridge.handle_message({"type": "state", "track": None,
                                     "absorb": {"state": "idle"}})
        assert bridge.absorb_holds_lights() is False

    asyncio.run(main())


# ═══ 4. the choke points the sweep cannot reach ════════════════════════════

def test_drift_and_the_sequencer_defer_by_name(bridge):
    async def main():
        assert bridge.conductor_deferral() is None
        await _hold(bridge, True)
        assert bridge.conductor_deferral() == "absorb"
        assert bridge.sequencer_deferral() == "absorb"
        assert bridge.status()["absorb"]["lights_held"] is True

    asyncio.run(main())


def test_a_preview_still_outranks_absorb(bridge):
    from spectra.services import preview_pause

    async def main():
        await _hold(bridge, True)
        preview_pause.start(30.0)
        assert bridge.conductor_deferral() == "preview"
        preview_pause.clear()
        assert bridge.conductor_deferral() == "absorb"

    asyncio.run(main())


def test_absorb_playback_is_not_the_rooms_music_for_the_house(bridge):
    from spectra.services import house

    async def main():
        await bridge.handle_message({
            "type": "state",
            "track": {"spotify_uri": "spotify:track:x", "is_playing": True,
                      "device_name": "Serenity", "progress_ms": 5000},
            "absorb": {"state": "running", "lights_held": False}})
        assert house._default_playing() is True       # his music, allowed device
        bridge._absorb["lights_held"] = True
        assert house._default_playing() is False, (
            "a 'show' house mode would hand the room to a song nobody hears")

    asyncio.run(main())


def test_light_show_cues_do_not_fire_on_an_absorb_song(monkeypatch, bridge):
    from spectra.services import engine, show_arms
    calls = []

    async def on_cue(level, cue_ms, ahead_ms):
        calls.append(level)
        return ["fired"]

    monkeypatch.setattr(show_arms, "on_cue", on_cue)

    async def main():
        await _hold(bridge, True)
        assert await engine._show_cue("high", 1000, 0) == []
        await _hold(bridge, False)
        assert await engine._show_cue("high", 1000, 0) == ["fired"]
        assert calls == ["high"]

    asyncio.run(main())


def test_a_show_sequence_never_counts_an_absorb_song(monkeypatch, bridge):
    from spectra.services import engine, show_sequence, trigger_engine
    counted = []
    monkeypatch.setattr(show_sequence, "on_track_change", counted.append)

    async def nothing(*_a, **_k):
        return None

    for target, name in ((engine.responses, "release_phases"),
                         (engine.trigger_engine, "on_track_state")):
        monkeypatch.setattr(target, name, nothing)
    monkeypatch.setattr(engine.trigger_engine, "maybe_auto_generate", lambda uri: None)
    from spectra.services import drop_sequences, pulse_feed
    monkeypatch.setattr(drop_sequences, "on_song_played", lambda uri: None)

    async def prep(uri):
        return None

    monkeypatch.setattr(pulse_feed.feed, "prepare", prep)
    from spectra.services.scene_sequencer import scene_sequencer
    monkeypatch.setattr(scene_sequencer, "on_track_state", nothing)
    from spectra.services import ambient_music_gate
    monkeypatch.setattr(ambient_music_gate, "reconcile", nothing)
    monkeypatch.setattr(engine, "_last_track_uri", None)
    assert trigger_engine is not None

    async def main():
        await _hold(bridge, True)
        await engine._on_track_uri("spotify:track:absorb-song")
        await _hold(bridge, False)
        await engine._on_track_uri("spotify:track:his-song")
        await asyncio.sleep(0)
        assert counted == ["spotify:track:his-song"]

    asyncio.run(main())


def test_the_analysed_colour_moment_is_held_and_named(monkeypatch, bridge):
    from spectra.services import engine
    called = []

    async def jump(*a, **k):
        called.append(a)
        return {}

    monkeypatch.setattr(engine.responses, "analysed_color_jump", jump)

    async def main():
        await _hold(bridge, True)
        out = await engine.fire_analysed_color_event(0.6, 0.6, None)
        assert out == {"skipped": "absorb"}
        assert called == []
        assert any(e["key"] == "analysed_colour" for e in _absorb_deferrals())

    asyncio.run(main())


def test_ambient_reads_absorb_playback_as_unknown(bridge):
    from spectra.services import engine

    async def main():
        await bridge.handle_message({
            "type": "state",
            "track": {"spotify_uri": "spotify:track:x", "is_playing": True,
                      "device_name": "Serenity"},
            "absorb": {"state": "running", "lights_held": True}})
        assert engine._room_is_playing() is None, (
            "Ambient's on-music-pause rule would release a held room for a "
            "song nobody hears")
        bridge._absorb["lights_held"] = False
        assert engine._room_is_playing() is True

    asyncio.run(main())


def test_the_house_layers_own_fire_still_lands(monkeypatch, seam, bridge):
    """origin="house" is the house's own look, not the music's — a mode
    change at 23:00 is not Absorb's to hold."""
    from spectra.services import scene_sequencer
    scene = _scene()

    async def main():
        await _hold(bridge, True)
        auto = await scene_sequencer.fire_scene_by_id(scene.id, None, 0.5)
        assert auto.get("skipped") == "absorb"
        house = await scene_sequencer.fire_scene_by_id(scene.id, None, 0.5,
                                                       origin="house")
        assert house.get("skipped") != "absorb", house

    asyncio.run(main())
