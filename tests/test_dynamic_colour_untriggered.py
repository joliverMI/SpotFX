"""More dynamic colour on songs with no authored triggers (owner ask
2026-09-25, his picks 2, 3 and 4):

  2. a same-scene re-fire keeps colour custody — the journey's destination
     survives and the fire wears the palette the room is showing;
  3. every analysed (generated) cue on an untriggered song lands a colour
     moment through the existing Colour Jump, with an explicit precedence
     (deferral > force colour > gradient > rainbow > set jump);
  4. a room setting drives a 2D gradient on untriggered songs only.

Every injectable is passed explicitly; nothing reads or writes real storage.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra.models.gradient2d import GradientProfile
from spectra.models.scene import SceneDeviceConfig, SceneV2
from spectra.models.sequencer import SelectorEntry, SequencerConfig
from spectra.models.trigger import FireSceneAction, SpectraTrigger
from spectra.services import color_journey as cj
from spectra.services import scene_compiler
from spectra.services.color_sets import ColorSetCard, ColorSetEntry, SetScope
from spectra.services.drift_conductor import DriftConductor
from spectra.services.fx_executor import RecordingExecutor
from spectra.services.room_controls import RoomControlState
from spectra.services.scene_response import ResponseEngine
from spectra.services.trigger_engine import TriggerEngine


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fake_colour_store(monkeypatch):
    """A card's entries address virtuals by id only — no imported device
    categories exist in a test, so resolve scope straight off virtual_ids;
    force_color resolves its pin against these cards, never real storage."""
    from spectra.services import color_sets
    monkeypatch.setattr(scene_compiler, "_set_entry_by_virtual", lambda card: {
        vid: e for e in card.entries for vid in e.scope.virtual_ids})
    monkeypatch.setattr(color_sets, "get_by_id", lambda sid: CARDS.get(sid))


# Wheel positions: three chromatic sets and one rainbow (None).
POSITIONS = {"red": 0.0, "green": 120.0, "blue": 240.0, "rainbow": None}
COLOURS = {"red": "#ff0000", "green": "#00ff00", "blue": "#0000ff",
           "rainbow": "linear-gradient(90deg, #ff0000 0%, #0000ff 100%)"}
CARDS = {sid: ColorSetCard(id=sid, name=sid.title(), entries=[ColorSetEntry(
    scope=SetScope(virtual_ids=["v1"]), color_value=COLOURS[sid])])
    for sid in POSITIONS}


class Rig:
    def __init__(self, *, controls: RoomControlState | None = None,
                 untriggered: bool | None = True, deferral=None,
                 room: cj.RoomColorState | None = None):
        self.room = [room or cj.RoomColorState(
            wheel_position_deg=0.0, active_set_id="red")]
        self.controls = controls or RoomControlState()
        self.untriggered = untriggered
        self.profiles = {"n1": GradientProfile(
            id="n1", name="Normal", top="#ffff00", bottom="#0000ff",
            x_mode="loop"), "t1": GradientProfile(
            id="t1", name="Test", top="#001cff", bottom="#ff0000",
            x_mode="loop")}
        self.executor = RecordingExecutor(
            clock=lambda: 0.0, room_controls_load=lambda: self.controls)
        config = SequencerConfig(color_set_entries={
            sid: SelectorEntry() for sid in POSITIONS if sid != "rainbow"})
        self.conductor = DriftConductor(
            executor=self.executor, clock=lambda: 0.0, leg_s=20.0,
            intensity=lambda: 0.5, deferral=deferral or (lambda: None),
            drift_profiles=lambda: {}, curve_profiles=lambda: {},
            room_load=lambda: self.room[0],
            room_save=lambda st: self.room.__setitem__(0, st),
            set_position=lambda sid: POSITIONS.get(sid),
            set_cards=lambda: list(CARDS.values()),
            sequencer_config=lambda: config,
            gradient_profiles=lambda: self.profiles,
            room_controls=lambda: self.controls,
            song_untriggered=lambda: self.untriggered,
            rng=Random(3))
        self.responses = ResponseEngine(
            conductor=self.conductor, executor=self.executor, rng=Random(5),
            sequencer_config=lambda: config, curve_profiles=lambda: {},
            eligible_sets=lambda scene: {
                sid: pos for sid, pos in POSITIONS.items() if sid != "rainbow"},
            set_card=lambda sid: CARDS.get(sid),
            room_load=lambda: self.room[0],
            room_save=lambda st: self.room.__setitem__(0, st),
            room_controls=lambda: self.controls)

    def fire(self, scene: SceneV2, color_set_id: str | None = None,
             gradient: str = "#ff0000") -> list[dict]:
        """What scene_compiler.fire_scene does around the conductor on a
        live fire: the re-fire palette carry, then the re-baseline."""
        writes = [{"virtual_id": "v1", "effect_type": "concentric",
                   "config": {"gradient": gradient}, "color_mode": "set",
                   "entry_id": scene.devices[0].id}]
        writes = self.conductor.refire_palette(scene.id, color_set_id, writes)
        self.conductor.on_scene_fire(scene, writes, color_set_id)
        return writes


def _scene(name="S") -> SceneV2:
    return SceneV2(name=name, devices=[SceneDeviceConfig(
        target_kind="virtual", target="v1", effect_type="concentric")])


# ── 2. same-scene re-fire keeps colour custody ──────────────────────────────

def test_same_scene_refire_keeps_destination_and_progress():
    rig = Rig()
    scene = _scene()
    rig.fire(scene)
    _run(rig.conductor.tick())
    _run(rig.conductor.tick())
    before = rig.room[0]
    assert before.destination is not None
    assert before.wheel_position_deg not in (None, 0.0)
    shown = rig.conductor.virtuals["v1"].gradient
    assert shown != "#ff0000", "the journey has rotated the palette"

    writes = rig.fire(scene)   # the same scene again, the room's own set

    after = rig.room[0]
    assert after.destination == before.destination
    assert after.wheel_position_deg == before.wheel_position_deg
    assert rig.conductor._last_rebaseline["refire"] is True
    assert writes[0]["config"]["gradient"] == shown, \
        "the re-fire wears the rotated palette, never snaps back to the set"
    assert rig.conductor.virtuals["v1"].gradient == shown


def test_different_scene_fire_still_clears_the_destination():
    rig = Rig()
    rig.fire(_scene("A"))
    _run(rig.conductor.tick())
    assert rig.room[0].destination is not None
    writes = rig.fire(_scene("B"))
    assert rig.room[0].destination is None
    assert rig.conductor._last_rebaseline["refire"] is False
    assert writes[0]["config"]["gradient"] == "#ff0000"


def test_same_scene_on_a_different_set_is_a_real_change():
    rig = Rig()
    scene = _scene()
    rig.fire(scene)
    _run(rig.conductor.tick())
    writes = rig.fire(scene, color_set_id="blue", gradient="#0000ff")
    assert rig.room[0].destination is None
    assert rig.room[0].active_set_id == "blue"
    assert writes[0]["config"]["gradient"] == "#0000ff"


# ── 3. the analysed colour jump and its precedence ──────────────────────────

def test_analysed_cue_jumps_to_a_new_set_over_the_cue_crossfade():
    rig = Rig()
    rig.fire(_scene())
    record = _run(rig.responses.analysed_color_jump(0.6, 250))
    jump = record["color_jump"]
    assert record["result"] == "jumped"
    assert jump["picked_id"] in ("green", "blue"), "current set excluded"
    assert jump["ramp_ms"] == 250
    assert rig.room[0].active_set_id == jump["picked_id"]
    assert rig.room[0].destination is None, "a teleport clears the bearing"
    glide = rig.executor.writes[-1]
    assert (glide["kind"], glide["duration_ms"]) == ("glide", 250)
    assert glide["params"]["gradient"] == COLOURS[jump["picked_id"]]
    assert rig.conductor.virtuals["v1"].gradient == COLOURS[jump["picked_id"]]


def test_a_force_colour_pin_holds_the_analysed_jump():
    rig = Rig(controls=RoomControlState(force_color_enabled=True,
                                        force_color_target_id="blue"))
    rig.fire(_scene())
    n = len(rig.executor.writes)
    record = _run(rig.responses.analysed_color_jump(0.6, 250))
    assert record["held_for"] == "force_color"
    assert rig.room[0].active_set_id == "red"
    assert len(rig.executor.writes) == n


def test_an_active_gradient_replaces_the_set_jump_with_its_own_kick():
    rig = Rig(controls=RoomControlState(active_gradient_id="t1"))
    rig.fire(_scene())
    rig.room[0] = rig.room[0].model_copy(update={"gradient_x": 0.2})
    record = _run(rig.responses.analysed_color_jump(0.6, 250))
    assert record["held_for"] == "gradient_drift"
    kick = record["gradient"]
    assert kick["kick"] == "analysed_cue" and kick["gradient_id"] == "t1"
    assert rig.room[0].active_set_id == "red", "no set jump"
    assert rig.room[0].gradient_x > 0.2, "X jumped one leg-step"
    assert kick["target_y"] == rig.room[0].gradient_target_y == 0.5, \
        "Y target untouched — on_intensity_event already retargeted it"
    assert rig.executor.writes[-1]["duration_ms"] == 250


def test_force_colour_outranks_the_gradient_too():
    rig = Rig(controls=RoomControlState(active_gradient_id="t1",
                                        force_color_enabled=True,
                                        force_color_target_id="blue"))
    rig.fire(_scene())
    record = _run(rig.responses.analysed_color_jump(0.6, 250))
    assert record["held_for"] == "force_color"
    assert "gradient" not in record


def test_a_live_rainbow_palette_holds_the_analysed_jump():
    rig = Rig(room=cj.RoomColorState(wheel_position_deg=0.0,
                                     active_set_id="rainbow"))
    rig.fire(_scene())
    record = _run(rig.responses.analysed_color_jump(0.6, 250))
    assert record["held_for"] == "rainbow_palette"
    assert rig.room[0].active_set_id == "rainbow"


def test_a_conductor_deferral_holds_the_analysed_jump():
    rig = Rig(deferral=lambda: "preview")
    rig.fire(_scene())
    record = _run(rig.responses.analysed_color_jump(0.6, 250))
    assert record["held_for"] == "preview"
    assert rig.room[0].active_set_id == "red"


# ── 3. the trigger engine: every generated cue of an untriggered song ───────

# CloZee "Wonder" (spotify:track:2wjxo5RPZ4PHyx8aXnlX7l), his real stored
# generated cue list read off storage/spectra/triggers.json on 2026-09-25:
# (timestamp_ms, section energy).
WONDER_CUES = [(21559, 0.246), (27538, 0.268), (48878, 0.8), (56877, 0.896),
               (64876, 0.825), (70205, 0.794), (83557, 0.822), (90871, 0.844),
               (96212, 0.884), (101540, 0.331), (147539, 1.0), (155527, 0.981)]
WONDER = "spotify:track:2wjxo5RPZ4PHyx8aXnlX7l"


def _cue(ts: int, energy: float, source: str = "generated") -> SpectraTrigger:
    return SpectraTrigger(timestamp_ms=ts, source=source,
                          action=FireSceneAction(intensity=energy))


def _engine(triggers, fired, colours, *, scene_ids):
    picks = iter(scene_ids)

    async def fire_scene(scene_id, color_set_id, intensity):
        fired.append(scene_id)

    async def analysed_color(sel, render, scene_id):
        colours.append((sel, scene_id))

    return TriggerEngine(
        list_triggers=lambda uri: triggers,
        fire_scene=fire_scene, select_scene=lambda i: next(picks),
        scene_change_mode=lambda: "analysed",
        render_intensity=lambda raw: raw, sequencer_enabled=lambda: True,
        lead_ms=lambda trig: 0, analysed_color=analysed_color,
        rng=Random(1))


def _play(engine, uri, end_ms=160_000, step=200):
    async def go():
        await engine.on_track_state(uri)
        for pos in range(0, end_ms, step):
            await engine.tick(pos)
    _run(go())


def test_every_wonder_cue_carries_a_colour_moment_whatever_the_scene_did():
    triggers = [_cue(ts, e) for ts, e in WONDER_CUES]
    fired, colours = [], []
    # Real Wonder shape: changes, same-scene re-fires, and a kernel "stay".
    picks = ["fish", "fish", "fish", None, "fish", "orbits", "fish", "orbits",
             "squiggles", "squiggles", "star", "star"]
    engine = _engine(triggers, fired, colours, scene_ids=picks)
    _play(engine, WONDER)
    assert len(colours) == len(WONDER_CUES) == 12
    assert [sel for sel, _ in colours] == [e for _, e in WONDER_CUES], \
        "selected at each cue's own section energy"
    assert [sid for _, sid in colours] == picks
    assert None not in fired, "a 'stay' fires no scene but still jumps colour"


def test_an_authored_song_gets_no_analysed_colour_moments():
    triggers = [_cue(ts, e) for ts, e in WONDER_CUES]
    triggers.append(_cue(200_000, 0.5, source="authored"))
    fired, colours = [], []
    engine = TriggerEngine(
        list_triggers=lambda uri: triggers,
        fire_scene=lambda *a: asyncio.sleep(0),
        select_scene=lambda i: "fish", scene_change_mode=lambda: "full",
        render_intensity=lambda raw: raw, sequencer_enabled=lambda: True,
        lead_ms=lambda trig: 0,
        analysed_color=lambda *a: colours.append(a) or asyncio.sleep(0),
        rng=Random(1))
    _play(engine, WONDER)
    assert colours == []
    assert engine.song_untriggered() is False


def test_song_untriggered_reads_the_tick_cache():
    calls = []
    triggers = [_cue(1000, 0.5)]

    def list_triggers(uri):
        calls.append(uri)
        return triggers

    engine = TriggerEngine(list_triggers=list_triggers,
                           fire_scene=lambda *a: asyncio.sleep(0),
                           select_scene=lambda i: "s",
                           scene_change_mode=lambda: "analysed",
                           sequencer_enabled=lambda: True)
    assert engine.song_untriggered() is None, "no song known"
    _run(engine.on_track_state("u"))
    _run(engine.tick(0))
    n = len(calls)
    assert engine.song_untriggered() is True
    assert len(calls) == n, "reused tick()'s own read"


def test_analysed_jump_across_wonder_lands_distinct_sets():
    """End to end on the colour side: each of Wonder's 12 cues, in order,
    through the real ResponseEngine — never the set already showing."""
    rig = Rig()
    rig.fire(_scene())
    shown = [rig.room[0].active_set_id]
    for _ts, energy in WONDER_CUES:
        rec = _run(rig.responses.analysed_color_jump(energy, 250))
        assert rec["result"] == "jumped"
        shown.append(rig.room[0].active_set_id)
    assert all(a != b for a, b in zip(shown, shown[1:]))


# ── 4. the untriggered-song gradient ────────────────────────────────────────

def test_untriggered_gradient_off_by_default():
    rig = Rig()
    assert rig.conductor.effective_gradient_id() is None


def test_untriggered_gradient_defaults_to_normal_on_an_untriggered_song():
    rig = Rig(controls=RoomControlState(untriggered_gradient_enabled=True))
    assert rig.conductor.effective_gradient_id() == "n1"
    rig.fire(_scene())
    record = _run(rig.conductor.tick())
    assert record["gradient"]["gradient_name"] == "Normal"
    assert record["journey"]["held_for"] == "gradient_drift"


def test_untriggered_gradient_uses_the_chosen_id():
    rig = Rig(controls=RoomControlState(untriggered_gradient_enabled=True,
                                        untriggered_gradient_id="t1"))
    assert rig.conductor.effective_gradient_id() == "t1"


@pytest.mark.parametrize("untriggered", [False, None])
def test_an_authored_or_unknown_song_falls_back_to_active_gradient(untriggered):
    rig = Rig(controls=RoomControlState(untriggered_gradient_enabled=True),
              untriggered=untriggered)
    assert rig.conductor.effective_gradient_id() is None
    rig.controls = RoomControlState(untriggered_gradient_enabled=True,
                                    active_gradient_id="t1")
    assert rig.conductor.effective_gradient_id() == "t1"


def test_the_untriggered_gradient_y_still_follows_analysed_transitions():
    rig = Rig(controls=RoomControlState(untriggered_gradient_enabled=True))
    rig.fire(_scene())
    rig.conductor._intensity = lambda: 0.9
    rig.conductor.on_intensity_event()
    assert rig.room[0].gradient_target_y == 0.9
    record = _run(rig.conductor.tick())
    assert record["gradient"]["y"] > 0.5, "Y drifts toward the new target"


def test_the_drop_kick_follows_the_untriggered_gradient():
    rig = Rig(controls=RoomControlState(untriggered_gradient_enabled=True))
    rig.fire(_scene())
    rec = _run(rig.conductor.on_drop_event(1.0))
    assert rec["active"] is True and rec["kick"] == "drop"
    assert rec["gradient_id"] == "n1"


# ── production wiring ───────────────────────────────────────────────────────

def test_engine_wires_the_analysed_colour_hook_and_the_song_feed():
    from spectra.services import engine
    assert engine.trigger_engine._analysed_color is engine.fire_analysed_color_event
    engine.trigger_engine._uri = None
    assert engine.conductor._song_untriggered() is None


def test_fire_analysed_color_event_rides_the_scene_crossfade(monkeypatch):
    from spectra.services import engine, fire_history, scene_store
    from spectra.services import room_controls
    scene = _scene("Fish").model_copy(update={"entry_ramp_ms": 420})
    seen = {}

    async def jump(intensity, ramp_ms):
        seen.update(intensity=intensity, ramp_ms=ramp_ms)
        return {"color_jump": {"result": "jumped", "picked_id": "blue",
                               "set_name": "Blue"}}

    recorded = []
    monkeypatch.setattr(engine.responses, "analysed_color_jump", jump)
    monkeypatch.setattr(scene_store, "get_by_id",
                        lambda sid: scene if sid == scene.id else None)
    monkeypatch.setattr(room_controls, "load_room_controls",
                        lambda: RoomControlState())
    monkeypatch.setattr(fire_history, "record_fire",
                        lambda *a, **k: recorded.append(a))
    _run(engine.fire_analysed_color_event(0.7, 0.4, scene.id))
    assert seen == {"intensity": 0.7, "ramp_ms": 420}
    assert recorded[0][0] == "color_sets" and recorded[0][2]["via"] == "analysed_cue"
