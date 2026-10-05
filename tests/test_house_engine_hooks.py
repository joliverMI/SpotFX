"""HOUSE LIGHTING's reach into the engine — each seam the resting layer
needs, proven where it lives, with the shipped (no-mode) behaviour as the
control:

  * the registry names ONE motion parameter per effect, numeric with a range
  * the colour journey walks only the mode's sets at the mode's pace, and a
    bearing chosen before the mode is dropped; with no override it is the
    journey it always was
  * apply_set_directly(glide_ms=...) GLIDES; without it, the old JUMP
  * scene_compiler.fire_scene(transition_ms=...) replaces the entry-ramp
    chain for that one fire; without it, the chain is unchanged
  * a calm/ignore mode defers the trigger engine's colour-set action and
    the analysed colour event
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


def _run(coro):
    return asyncio.run(coro)


# ── registry ───────────────────────────────────────────────────────────────

def test_each_effect_names_at_most_one_numeric_motion_param():
    from fx import device_model
    reg = device_model.registry()["effects"]
    tagged = {}
    for effect, entry in reg.items():
        motion = [p for p, meta in entry.get("params", {}).items() if meta.get("motion")]
        assert len(motion) <= 1, (effect, motion)
        for p in motion:
            meta = entry["params"][p]
            assert meta.get("type") == "numeric" and meta.get("min") is not None \
                and meta.get("max") is not None, (effect, p)
            tagged[effect] = p
    assert device_model.motion_param_for("fish") == "base_speed"
    assert device_model.motion_param_for("melt") == "speed"
    assert device_model.motion_param_for("radial") == "base_rotation"
    assert device_model.motion_param_for("power") is None
    assert len(tagged) >= 12


# ── the colour journey ─────────────────────────────────────────────────────

def _conductor(house_journey=None):
    from spectra.models.sequencer import SequencerConfig
    from spectra.services import color_journey
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor
    from spectra.services.room_controls import RoomControlState
    room = {"st": color_journey.RoomColorState(wheel_position_deg=0.0,
                                               active_set_id="a")}
    cards = [SimpleNamespace(id=x, name=x, kind="set", disabled=False,
                             scene_v2_opt_out=False) for x in "abcd"]
    positions = {"a": 0.0, "b": 60.0, "c": 120.0, "d": 240.0}
    cond = DriftConductor(
        executor=RecordingExecutor(room_controls_load=RoomControlState),
        room_load=lambda: room["st"],
        room_save=lambda st: room.__setitem__("st", st),
        set_position=positions.get, set_cards=lambda: cards,
        sequencer_config=SequencerConfig, curve_profiles=lambda: {},
        room_controls=RoomControlState, gradient_profiles=lambda: {},
        house_journey=house_journey)
    return cond, room


def test_the_journey_walks_only_the_modes_sets_at_its_pace():
    from spectra.services.house import JourneyOverride
    hj = JourneyOverride(set_ids=frozenset({"b", "c"}), deg_per_min=6.0, mode_name="Evening")
    cond, room = _conductor(lambda: hj)
    assert set(cond._destination_pool()) == {"b", "c"}
    rec = cond._journey_leg({}, 20000, [])
    assert rec["house_mode"] == "Evening" and rec["degrees_per_min"] == 6.0
    assert room["st"].destination.set_id in {"b", "c"}


def test_a_bearing_chosen_before_the_mode_is_dropped():
    from spectra.services import color_journey
    from spectra.services.house import JourneyOverride
    hj = JourneyOverride(set_ids=frozenset({"b"}), deg_per_min=6.0, mode_name="Evening")
    cond, room = _conductor(lambda: hj)
    room["st"] = room["st"].model_copy(update={"destination": color_journey.JourneyDestination(
        set_id="d", position_deg=240.0, pace_deg_per_min=30.0, from_deg=0.0)})
    cond._journey_leg({}, 20000, [])
    assert room["st"].destination.set_id == "b"


def test_an_empty_mode_pool_holds_the_walk():
    from spectra.services.house import JourneyOverride
    hj = JourneyOverride(set_ids=frozenset(), deg_per_min=6.0, mode_name="Night")
    cond, room = _conductor(lambda: hj)
    rec = cond._journey_leg({}, 20000, [])
    assert rec["paused"] is True and room["st"].destination is None


def test_control_no_override_is_the_journey_it_always_was():
    cond, room = _conductor()
    assert set(cond._destination_pool()) == {"a", "b", "c", "d"}
    rec = cond._journey_leg({}, 20000, [])
    assert "house_mode" not in rec and rec["degrees_per_min"] == 30.0


# ── glided colour apply ────────────────────────────────────────────────────

def test_apply_set_directly_glides_when_asked_and_jumps_otherwise(monkeypatch):
    from spectra.services import scene_compiler
    from spectra.services.drift_conductor import VirtualState
    cond, _room = _conductor()
    cond.virtuals = {"v": VirtualState("melt", "e1", "set", {"gradient": "#000000"})}
    entry = SimpleNamespace(color_value="#ff0000", bg_color=None, bg_mode=None,
                            brightness=None, background_brightness=None)
    monkeypatch.setattr(scene_compiler, "_set_entry_by_virtual", lambda card: {"v": entry})
    card = SimpleNamespace(id="a", name="A")
    _run(cond.apply_set_directly(card, glide_ms=5000))
    w = cond.executor.writes[-1]
    assert w["kind"] == "glide" and w["duration_ms"] == 5000
    _run(cond.apply_set_directly(card))
    assert cond.executor.writes[-1]["kind"] == "jump"


# ── fire_scene's glide override ────────────────────────────────────────────

def test_fire_scene_transition_ms_replaces_the_entry_ramp_chain(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.models.scene import SceneV2
    from spectra.services import engine, fx_seam, scene_compiler
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "rc.json")
    monkeypatch.setattr(scfg, "ROOM_COLOR_FILE", tmp_path / "room_color.json")
    seen = []

    async def fake_apply(writes, *, transition_ms=0):
        seen.append(transition_ms)
    monkeypatch.setattr(fx_seam, "apply_writes", fake_apply)
    monkeypatch.setattr(engine, "on_scene_fired", lambda *a, **k: None)
    scene = SceneV2(name="x")
    _run(scene_compiler.fire_scene(scene, dry_run=False, transition_ms=90_000))
    _run(scene_compiler.fire_scene(scene, dry_run=False))
    assert seen[0] == 90_000
    assert 0 < seen[1] < 1000, "no override: the intensity-scaled default ramp"


# ── calm/ignore defer the colour paths ─────────────────────────────────────

def test_a_holding_mode_defers_the_trigger_engines_colour_action(monkeypatch):
    from spectra.services import engine, force_color, house
    from spectra.services.trigger_engine import trigger_engine
    applied = []

    async def fake_apply(card, **kw):
        applied.append(card)
    monkeypatch.setattr(force_color, "pinned_card", lambda *a, **k: None)
    monkeypatch.setattr(engine.conductor, "apply_set_directly", fake_apply)
    monkeypatch.setattr(house, "scene_deferral", lambda: "house mode 'Night' keeps its look")
    _run(trigger_engine._default_select_color_set("anything"))
    assert applied == []


def test_a_holding_mode_defers_the_analysed_colour_event(monkeypatch):
    from spectra.services import engine, house
    monkeypatch.setattr(house, "scene_deferral", lambda: "house mode 'Night' keeps its look")
    res = _run(engine.fire_analysed_color_event(0.5, 0.5, None))
    assert res["skipped"] == "house_mode"
