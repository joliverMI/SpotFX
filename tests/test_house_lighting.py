"""HOUSE LIGHTING — the resting layer (spectra/services/house.py).

The proofs, in the order the module docstring states its rules:

  1. The model refuses what cannot run (a held Hue look with no colour, a
     fixture target with no id); names and Home Assistant aliases are unique.
  2. WHO SET IT: HA's word maps through aliases; the same word again is a
     no-op; a person's pick holds until HA's word CHANGES; an unmapped word
     is recorded, never guessed; clearing holds against HA's heartbeat.
  3. INERT: with no mode, or with the room not SPECTRA's, nothing is written
     — no scene, no base level, no cap — and every hook answers None.
  4. RESTING: entering fires a scene from the pool through the house origin
     with the mode's glide, pushes per-fixture levels/off/caps, writes
     motion as a glide carried into the conductor; a scene already in the
     pool is KEPT; Force Scene/Colour outrank the mode; the flow clock.
  5. MUSIC: "show" hands in on playing and hands out after the debounce;
     an unknown read never moves it; "calm"/"ignore" defer at the choke
     points.
  6. COMPOSITION with the Light Show: base × show Level; letting go of a
     show hold or End show returns to the BASE, not an undimmed picture.
  7. STANDBY: a preview holds the room → no writes; afterwards the mode is
     re-asserted.

No live room: the conductor, the scene fire and the colour apply are fakes
behind house.deps; the gate is monkeypatched; scenes/colour sets live in a
temp store.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from spectra.models.house_mode import (ColorPick, FixtureHook, HouseMode, HouseTarget,
                                       HueLook, ScenePick)


def _run(coro):
    return asyncio.run(coro)


# ── fakes ──────────────────────────────────────────────────────────────────

class FakeExecutor:
    def __init__(self):
        self.glides: list = []
        self.jumps: list = []
        self.mode = "facade"

    async def glide(self, vid, effect_type, params, duration):
        self.glides.append((vid, effect_type, dict(params), duration))

    async def jump(self, vid, effect_type, params):
        self.jumps.append((vid, effect_type, dict(params)))


class FakeVState:
    def __init__(self, effect_type, baseline):
        self.effect_type = effect_type
        self.param_baseline = dict(baseline)


class FakeConductor:
    def __init__(self):
        self.scene = None
        self.virtuals: dict = {}
        self.executor = FakeExecutor()
        self.surges: list = []

    def on_surge(self, changes):
        self.surges.append(dict(changes))
        for (vid, p), v in changes.items():
            if vid in self.virtuals:
                self.virtuals[vid].param_baseline[p] = v

    def rebaseline(self, scene, virtuals):
        self.scene = scene
        self.virtuals = virtuals          # a NEW dict, like on_scene_fire


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Temp scenes + colour sets, a fake conductor/fire/apply behind
    house.deps, the gate open, resolve_target mapped to two fixtures."""
    from spectra import config as scfg
    from spectra.models.scene import SceneV2
    from spectra.services import house, scene_store, show_output

    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "ROOM_COLOR_FILE", tmp_path / "room_color.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    cards = {
        "calm-p": {"id": "calm-p", "name": "Calm - Purple", "kind": "set", "entries": []},
        "calm-g": {"id": "calm-g", "name": "Calm - Green", "kind": "set", "entries": []},
        "calm": {"id": "calm", "name": "Calm", "kind": "group",
                 "members": [{"color_set_id": "calm-p"}, {"color_set_id": "calm-g"}]},
        "eve": {"id": "eve", "name": "Calm - Evening", "kind": "set", "entries": []},
    }
    (tmp_path / "color_sets.json").write_text(json.dumps(cards))
    scenes = {}
    for name in ("Star", "Fish", "Noise"):
        s = SceneV2(name=name)
        scene_store.save(s)
        scenes[name] = s

    cond = FakeConductor()
    clock = Clock()
    fires: list = []
    applies: list = []
    hue_syncs: list = []
    state = {"playing": False, "active_set": None}

    async def fire_scene(scene_id, **kw):
        fires.append((scene_id, kw))
        scene = scene_store.get_by_id(scene_id)
        cond.rebaseline(scene, {
            "crystal": FakeVState("fish", {"base_speed": 0.3}),
            "strips": FakeVState("melt", {"speed": 0.4}),
        })
        if kw.get("color_set_id"):
            state["active_set"] = kw["color_set_id"]
        return {"dry_run": False}

    async def apply_set(card, glide_ms):
        applies.append((card.id, glide_ms))
        state["active_set"] = card.id
        return {"applied": card.id}

    async def sync_hue():
        hue_syncs.append(house.hue_directive())

    house.deps = house.Deps(
        playing=lambda: state["playing"], fire_scene=fire_scene,
        apply_set=apply_set, conductor=lambda: cond, sync_hue=sync_hue,
        active_set_id=lambda: state["active_set"], clock=clock)
    monkeypatch.setattr(house, "gate", lambda: (None, None))

    targets = {("everything", None): ["dev-crystal", "dev-tv", "dev-porch"],
               ("category", "Matrix"): ["dev-crystal"],
               ("category", "Singles"): ["dev-porch"],
               ("fixture", "dev-tv"): ["dev-tv"]}

    def resolve_target(t):
        key = (t.get("kind", "everything"), t.get("id"))
        devs = targets.get(key, [])
        return devs, ([] if devs else [f"no {key}"])
    monkeypatch.setattr(show_output, "resolve_target", resolve_target)
    monkeypatch.setattr(show_output, "device_label", lambda d: d)

    class W:
        pass
    w = W()
    w.house, w.cond, w.clock, w.fires, w.applies = house, cond, clock, fires, applies
    w.state, w.scenes, w.hue_syncs = state, scenes, hue_syncs
    return w


def _mode(world, name="Standard", **kw) -> HouseMode:
    from spectra.services import house_store
    base = dict(name=name, ha_aliases=["Daytime"] if name == "Standard" else [],
                scenes=[ScenePick(scene_id=world.scenes["Star"].id)],
                color_sets=[ColorPick(card_id="calm")])
    base.update(kw)
    return house_store.put_mode(HouseMode(**base))


# ═══ 1. model and store ═════════════════════════════════════════════════════

def test_a_held_hue_look_needs_a_colour_temperature_or_a_colour():
    with pytest.raises(ValueError):
        HueLook(area="*", look="hold")
    with pytest.raises(ValueError):
        HueLook(area="*", look="hold", kelvin=2700, color="#ff0000")
    assert HueLook(area="*", look="hold", kelvin=2000).mirek == 500
    assert HueLook(area="*", look="off").mirek is None


def test_a_fixture_target_needs_an_id():
    with pytest.raises(ValueError):
        HouseTarget(kind="fixture")
    assert HouseTarget(kind="everything").id is None


def test_names_and_ha_aliases_are_unique_ignoring_case(world):
    from spectra.services import house_store
    _mode(world, "Standard")
    with pytest.raises(house_store.ModeConflict):
        house_store.put_mode(HouseMode(name="standard"))
    with pytest.raises(house_store.ModeConflict):
        house_store.put_mode(HouseMode(name="Evening", ha_aliases=["daytime"]))
    # an alias equal to another mode's NAME is the same word too
    with pytest.raises(house_store.ModeConflict):
        house_store.put_mode(HouseMode(name="Other", ha_aliases=["Standard"]))


def test_ha_value_maps_through_alias_then_exact_name(world):
    from spectra.services import house_store
    std = _mode(world, "Standard")
    eve = _mode(world, "Evening")
    assert house_store.mode_for_ha("daytime").id == std.id
    assert house_store.mode_for_ha("Evening").id == eve.id
    assert house_store.mode_for_ha("Party") is None


# ═══ 2. who set it ══════════════════════════════════════════════════════════

def test_ha_word_applies_with_the_clock_glide_and_repeats_are_no_ops(world):
    from spectra.services import house_store
    std = _mode(world, "Standard", transitions={"clock_glide_s": 90, "button_glide_s": 5})
    res = _run(world.house.set_mode(ha_mode="Daytime", source="ha"))
    assert res["status"] == "applied"
    st = house_store.state()
    assert st.mode_id == std.id and st.manual is False and st.glide_s == 90
    res = _run(world.house.set_mode(ha_mode="Daytime", source="ha"))
    assert res["status"] == "unchanged"


def test_a_persons_pick_holds_until_ha_changes_its_word(world):
    from spectra.services import house_store
    std = _mode(world, "Standard")
    eve = _mode(world, "Evening")
    _run(world.house.set_mode(ha_mode="Daytime", source="ha"))
    res = _run(world.house.set_mode(mode="Evening", source="spectra"))
    assert res["status"] == "applied"
    assert house_store.state().manual is True
    assert house_store.state().glide_s == eve.transitions.button_glide_s
    # HA's 5-minute re-assert of the SAME word does not fight him
    res = _run(world.house.set_mode(ha_mode="Daytime", source="ha"))
    assert res["status"] == "held_manual"
    assert house_store.state().mode_id == eve.id
    # HA's word CHANGES: the clock wins again
    _mode(world, "Dim")
    res = _run(world.house.set_mode(ha_mode="Dim", source="ha"))
    assert res["status"] == "applied"
    assert house_store.state().manual is False
    del std


def test_an_unmapped_ha_word_is_recorded_never_guessed(world):
    from spectra.services import house_store
    std = _mode(world, "Standard")
    _run(world.house.set_mode(ha_mode="Daytime", source="ha"))
    res = _run(world.house.set_mode(ha_mode="Party", source="ha"))
    assert res["status"] == "unmapped"
    st = house_store.state()
    assert st.mode_id == std.id and st.ha_value == "Party"
    assert world.house.status_dict()["ha_mapped_mode"] is None


def test_an_unknown_mode_name_is_refused(world):
    res = _run(world.house.set_mode(mode="Nope", source="spectra"))
    assert res["status"] == "unknown_mode"


def test_clearing_holds_against_has_heartbeat(world):
    from spectra.services import house_store
    _mode(world, "Standard")
    _run(world.house.set_mode(ha_mode="Daytime", source="ha"))
    res = _run(world.house.set_mode(clear=True, source="spectra"))
    assert res["status"] == "cleared"
    assert house_store.state().mode_id is None
    assert _run(world.house.set_mode(ha_mode="Daytime", source="ha"))["status"] == "held_manual"
    assert house_store.state().mode_id is None


def test_the_mode_survives_a_restart(world):
    from spectra.services import house_store
    std = _mode(world, "Standard")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    house_store.reset_memory()
    assert house_store.state().mode_id == std.id


# ═══ 3. inert ═══════════════════════════════════════════════════════════════

def test_no_mode_set_writes_nothing_and_every_hook_is_none(world):
    from fx import device_rate
    from spectra.services import show_output
    _mode(world, "Standard", fixtures=[FixtureHook(level=10, fps=10)])
    _run(world.house.tick())
    assert world.fires == [] and world.applies == []
    assert show_output.base_snapshot() == {"levels": {}, "states": {}}
    assert device_rate.caps() == {}
    h = world.house
    assert (h.scene_deferral(), h.response_deferral(), h.journey_override(),
            h.hue_directive()) == (None, None, None, None)
    assert h.status_dict()["phase"] == "inactive"


def test_a_mode_set_while_the_room_is_not_ours_only_records(world, monkeypatch):
    from fx import device_rate
    from spectra.services import house_store, show_output
    monkeypatch.setattr(world.house, "gate",
                        lambda: ("refused", "the room is released"))
    std = _mode(world, "Standard", fixtures=[FixtureHook(level=10, fps=10)],
                hue=[HueLook(area="*", kelvin=3500)], music="ignore")
    res = _run(world.house.set_mode(ha_mode="Daytime", source="ha"))
    assert res["status"] == "applied"
    assert house_store.state().mode_id == std.id
    assert world.fires == [] and world.applies == []
    assert show_output.base_snapshot() == {"levels": {}, "states": {}}
    assert device_rate.caps() == {}
    h = world.house
    assert (h.scene_deferral(), h.response_deferral(), h.journey_override(),
            h.hue_directive()) == (None, None, None, None)
    status = h.status_dict()
    assert status["active"] is False and "released" in status["reason"]


def test_the_gate_reads_the_light_shows_own_ownership_and_standdown(monkeypatch):
    """house.gate() is show_output's two reasons, nothing of its own: the
    layer acts exactly when the Light Show may."""
    from spectra.services import house, show_output
    monkeypatch.setattr(show_output, "ownership_refusal", lambda: "the room is released")
    monkeypatch.setattr(show_output, "standdown_reason", lambda: None)
    assert house.gate() == ("refused", "the room is released")
    monkeypatch.setattr(show_output, "ownership_refusal", lambda: None)
    monkeypatch.setattr(show_output, "standdown_reason", lambda: "a preview is holding the room")
    assert house.gate() == ("standby", "a preview is holding the room")
    monkeypatch.setattr(show_output, "standdown_reason", lambda: None)
    assert house.gate() == (None, None)
    monkeypatch.setattr(show_output, "ownership_refusal", lambda: (
        "the room is released — SPECTRA is not driving the lights. "
        "The Light Show never takes the room; take it back first."))
    assert house.gate() == ("refused",
                            "the room is released — SPECTRA is not driving the lights")


# ═══ 4. resting ═════════════════════════════════════════════════════════════

def test_entering_fires_the_pool_scene_through_the_house_origin_with_the_glide(world):
    std = _mode(world, "Standard", flow={"intensity": 0.2},
                transitions={"clock_glide_s": 90})
    _run(world.house.set_mode(ha_mode="Daytime", source="ha"))
    assert len(world.fires) == 1
    scene_id, kw = world.fires[0]
    assert scene_id == world.scenes["Star"].id
    assert kw["origin"] == "house" and kw["transition_ms"] == 90_000
    assert kw["intensity"] == 0.2
    assert kw["color_set_id"] == "calm"            # the group goes to the fire
    assert kw["dwell_tolerance_s"] >= 3600
    status = world.house.status_dict()
    assert status["phase"] == "resting" and status["mode"]["id"] == std.id


def test_fixture_hooks_push_levels_off_and_caps_later_wins(world):
    from fx import device_rate
    from spectra.services import show_output
    _mode(world, "Standard", fixtures=[
        FixtureHook(target=HouseTarget(kind="everything"), level=40, fps=20),
        FixtureHook(target=HouseTarget(kind="category", id="Matrix"), level=6),
        FixtureHook(target=HouseTarget(kind="category", id="Singles"), fps=10),
        FixtureHook(target=HouseTarget(kind="fixture", id="dev-tv"), off=True),
    ])
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    base = show_output.base_snapshot()
    assert base["levels"] == {"dev-crystal": pytest.approx(0.06),
                              "dev-tv": pytest.approx(0.4),
                              "dev-porch": pytest.approx(0.4)}
    assert base["states"] == {"dev-tv": "dark"}
    assert device_rate.caps() == {"dev-crystal": 20.0, "dev-tv": 20.0, "dev-porch": 10.0}


def test_motion_glides_to_a_position_in_the_param_range_and_moves_the_baseline(world):
    _mode(world, "Standard", fixtures=[FixtureHook(motion=0.0)],
          transitions={"button_glide_s": 5})
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    glides = {(g[0], tuple(g[2])): g for g in world.cond.executor.glides}
    # fish base_speed registry range 0.05..2.0 -> motion 0 = 0.05
    fish = glides[("crystal", ("base_speed",))]
    assert fish[2]["base_speed"] == pytest.approx(0.05) and fish[3] == 5000
    melt = glides[("strips", ("speed",))]
    assert melt[2]["speed"] == pytest.approx(0.0)
    assert world.cond.virtuals["crystal"].param_baseline["base_speed"] == pytest.approx(0.05)


def test_a_scene_already_in_the_pool_is_kept_and_the_colour_glides(world):
    std = _mode(world, "Standard")
    _mode(world, "Evening", scenes=[ScenePick(scene_id=world.scenes["Star"].id)],
          color_sets=[ColorPick(card_id="eve")], transitions={"button_glide_s": 5})
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    assert len(world.fires) == 1
    _run(world.house.set_mode(mode="Evening", source="spectra"))
    assert len(world.fires) == 1, "same scene in both pools — a pure glide, no re-fire"
    assert world.applies == [("eve", 5000)]
    del std


def test_force_scene_outranks_the_mode(world):
    """Force Scene still waits for the mode's own scene to come due — that
    pin's behaviour is untouched by the Force Colour change below."""
    from spectra.services import room_controls
    st = room_controls.load_room_controls()
    room_controls.save_room_controls(st.model_copy(update={
        "force_scene_enabled": True, "force_scene_scene_id": world.scenes["Fish"].id}))
    _mode(world, "Standard")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    assert world.fires == []
    problems = " ".join(world.house.status_dict()["problems"])
    assert "Force Scene" in problems


def test_force_colour_no_longer_outranks_the_mode(world):
    """2026-10-05, the Admiral's ruling: house modes must ignore Force
    Colour and use their own colour sets. Pinned to a card the mode does
    NOT itself offer, so a leak would be unambiguous."""
    from spectra.services import room_controls
    st = room_controls.load_room_controls()
    room_controls.save_room_controls(st.model_copy(update={
        "force_color_enabled": True, "force_color_target_id": "calm-p"}))
    _mode(world, "Standard", color_sets=[ColorPick(card_id="eve")])
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    worn = [card_id for card_id, _glide in world.applies] or \
        [kw.get("color_set_id") for _sid, kw in world.fires]
    assert "eve" in worn, "the mode's own colour set reached the room"
    assert "calm-p" not in worn, "the pin never reached it"
    problems = " ".join(world.house.status_dict()["problems"])
    assert "Force Colour" not in problems


def test_the_flow_clock_draws_a_different_scene(world):
    _mode(world, "Standard", scenes=[ScenePick(scene_id=world.scenes["Star"].id),
                                     ScenePick(scene_id=world.scenes["Fish"].id)],
          flow={"scene_every_min": 45})
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    first = world.fires[-1][0]
    world.clock.now += 44 * 60
    _run(world.house.tick())
    assert len(world.fires) == 1
    world.clock.now += 2 * 60
    _run(world.house.tick())
    assert len(world.fires) == 2 and world.fires[-1][0] != first
    assert world.fires[-1][1]["origin"] == "house"


def test_a_resting_mode_defers_automatic_scene_picks(world):
    _mode(world, "Standard")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    assert "resting" in world.house.scene_deferral()
    assert world.house.response_deferral() is None


def test_journey_override_is_the_modes_sets_with_groups_expanded(world):
    _mode(world, "Standard", color_sets=[ColorPick(card_id="calm"), ColorPick(card_id="eve")],
          flow={"journey_deg_per_min": 12})
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    jo = world.house.journey_override()
    assert jo.set_ids == frozenset({"calm-p", "calm-g", "eve"})
    assert jo.deg_per_min == 12


def test_editing_the_live_mode_reapplies_it(world):
    from spectra.services import house_store, show_output
    std = _mode(world, "Standard", fixtures=[FixtureHook(level=40)])
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    house_store.put_mode(std.model_copy(update={"fixtures": [FixtureHook(level=20)]}))
    _run(world.house.tick())
    assert show_output.base_snapshot()["levels"]["dev-tv"] == pytest.approx(0.2)


def test_clearing_the_mode_takes_the_look_off_the_room(world):
    from fx import device_rate
    from spectra.services import show_output
    _mode(world, "Standard", fixtures=[FixtureHook(level=40, fps=10, motion=0.1)])
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    assert show_output.base_snapshot()["levels"]
    _run(world.house.set_mode(clear=True, source="spectra"))
    assert show_output.base_snapshot() == {"levels": {}, "states": {}}
    assert device_rate.caps() == {}
    # motion restored to what the scene authored
    last = {g[0]: g[2] for g in world.cond.executor.glides}
    assert last["crystal"]["base_speed"] == pytest.approx(0.3)
    assert world.house.status_dict()["phase"] == "inactive"


# ═══ 5. music ═══════════════════════════════════════════════════════════════

def test_show_hands_in_on_playing_and_out_after_the_debounce(world):
    from fx import device_rate
    from spectra.services import show_output
    _mode(world, "Standard", fixtures=[FixtureHook(level=40, fps=10, motion=0.1)],
          transitions={"music_debounce_s": 60, "music_return_glide_s": 20})
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    assert len(world.fires) == 1
    world.state["playing"] = True
    _run(world.house.tick())
    assert world.house.status_dict()["phase"] == "music"
    assert show_output.base_snapshot() == {"levels": {}, "states": {}}
    assert device_rate.caps() == {}
    assert world.house.scene_deferral() is None       # the show owns the room
    assert world.house.journey_override() is None
    world.state["playing"] = False
    _run(world.house.tick())
    world.clock.now += 59
    _run(world.house.tick())
    assert world.house.status_dict()["phase"] == "music", "inside the debounce"
    world.clock.now += 2
    _run(world.house.tick())
    assert world.house.status_dict()["phase"] == "resting"
    assert len(world.fires) == 2 and world.fires[-1][1]["transition_ms"] == 20_000
    assert show_output.base_snapshot()["levels"]


def test_an_unknown_playback_read_never_hands_out(world):
    _mode(world, "Standard", transitions={"music_debounce_s": 1})
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    world.state["playing"] = True
    _run(world.house.tick())
    world.state["playing"] = None
    world.clock.now += 3600
    _run(world.house.tick())
    assert world.house.status_dict()["phase"] == "music"


def test_scene_deferral_is_live_so_music_owns_a_fire_before_the_next_tick(world):
    _mode(world, "Standard")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    world.state["playing"] = True                   # no tick yet
    assert world.house.scene_deferral() is None


def test_calm_keeps_the_scene_but_lets_flares_play(world):
    _mode(world, "Standard", music="calm")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    world.state["playing"] = True
    _run(world.house.tick())
    assert world.house.status_dict()["phase"] == "resting"
    assert "calm" in world.house.scene_deferral()
    assert world.house.response_deferral() is None


def test_ignore_silences_responses_at_the_engine_gate(world):
    from spectra.services import engine
    _mode(world, "Standard", music="ignore")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    world.state["playing"] = True
    assert engine._response_gate(via_trigger=True) == "house_mode"
    assert engine._update_gate() == "house_mode"


def test_fire_scene_by_id_defers_automatic_picks_but_passes_the_house_and_pins(world, monkeypatch):
    from spectra.services import fire_history, room_controls, scene_compiler, scene_sequencer
    _mode(world, "Standard")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    fired = []

    async def fake_fire(scene, **kw):
        fired.append((scene.id, kw))
        return {"dry_run": False}
    monkeypatch.setattr(scene_compiler, "fire_scene", fake_fire)
    fish = world.scenes["Fish"].id
    res = _run(scene_sequencer.fire_scene_by_id(fish))
    assert res["skipped"] == "house_mode" and fired == []
    assert fire_history.load_all()["deferred"].get(fish) is not None
    res = _run(scene_sequencer.fire_scene_by_id(fish, origin="house",
                                                transition_ms=1234,
                                                dwell_tolerance_s=99999))
    assert fired[-1] == (fish, {"intensity": 0.5, "color_set": None,
                                "dry_run": False, "transition_ms": 1234})
    st = room_controls.load_room_controls()
    room_controls.save_room_controls(st.model_copy(update={
        "force_scene_enabled": True, "force_scene_scene_id": fish}))
    res = _run(scene_sequencer.fire_scene_by_id(world.scenes["Noise"].id,
                                                dwell_tolerance_s=99999))
    assert res.get("skipped") is None, "a pin outranks the mode"


# ═══ 6. composition with the Light Show ═════════════════════════════════════

def test_base_times_show_level_and_end_show_returns_to_the_base():
    from fx import device_output
    from spectra.services import show_output
    show_output.set_base({"dev-a": 0.5}, {"dev-b": "dark"})
    assert device_output.target("dev-a").level == 0.5
    assert device_output.target("dev-b").state == "dark"
    show_output.add_level(["dev-a"], 0.5, until="released")
    assert device_output.target("dev-a").level == pytest.approx(0.25)
    show_output.set_state(["dev-b"], "steady", color=(255, 0, 0))
    assert device_output.target("dev-b").state == "steady"
    show_output.release_all(fade_ms=0)
    assert device_output.target("dev-a").level == pytest.approx(0.5)
    assert device_output.target("dev-b").state == "dark", \
        "End show returns to the mode's resting look, not an undimmed picture"
    show_output.set_base({}, {})
    assert device_output.target("dev-a").level == 1.0


def test_letting_go_of_one_show_hold_returns_to_the_base_state():
    from fx import device_output
    from spectra.services import show_output
    show_output.set_base({}, {"dev-b": "dark"})
    show_output.set_state(["dev-b"], "steady", color=(0, 0, 255))
    show_output.set_state(["dev-b"], "show")
    assert device_output.target("dev-b").state == "dark"
    show_output.set_state(["dev-b"], "steady", color=(0, 0, 255))
    show_output.release_device("dev-b", fade_ms=0)
    assert device_output.target("dev-b").state == "dark"


def test_a_room_release_drops_the_base():
    from fx import device_output
    from spectra.services import show_output
    show_output.set_base({"dev-a": 0.3}, {})
    show_output.on_release()
    assert show_output.base_snapshot() == {"levels": {}, "states": {}}
    assert device_output.target("dev-a") is None


# ═══ 7. standby ═════════════════════════════════════════════════════════════

def test_standby_writes_nothing_and_resumes_afterwards(world, monkeypatch):
    from fx import device_rate
    _mode(world, "Standard", fixtures=[FixtureHook(fps=10, motion=0.2)])
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    glides = len(world.cond.executor.glides)
    assert device_rate.caps()
    monkeypatch.setattr(world.house, "gate", lambda: ("standby", "a preview is holding the room"))
    _run(world.house.tick())
    assert world.house.status_dict()["phase"] == "standby"
    assert device_rate.caps() == {}
    assert len(world.cond.executor.glides) == glides and len(world.fires) == 1
    monkeypatch.setattr(world.house, "gate", lambda: (None, None))
    _run(world.house.tick())
    assert world.house.status_dict()["phase"] == "resting"
    assert len(world.fires) == 1, "the scene is still the mode's — kept"
    assert device_rate.caps() == {"dev-crystal": 10.0, "dev-tv": 10.0, "dev-porch": 10.0}


# ═══ 8. Hue directive ═══════════════════════════════════════════════════════

def test_hue_directive_follows_the_mode_and_its_music_hue(world):
    _mode(world, "Standard", hue=[HueLook(area="*", kelvin=3521),
                                  HueLook(area="dining-hues", kelvin=2005, brightness=80)],
          music_hue="join", transitions={"button_glide_s": 5})
    assert world.house.hue_directive() is None, "no mode set yet"
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    d = world.house.hue_directive()
    assert d.holds_any and d.ramp_ms == 5000
    assert ("dining-hues", "hold", 499, None, 80.0) in d.looks
    world.state["playing"] = True
    d = world.house.hue_directive()
    assert d.looks == (("*", "show", None, None, 100.0),) and not d.holds_any
    assert world.hue_syncs, "the gate was asked to re-read"


def test_a_mode_with_no_hue_looks_leaves_hue_to_the_hue_hold_toggle(world):
    _mode(world, "Standard")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    assert world.house.hue_directive() is None


def test_music_hue_room_hands_hue_back_to_the_toggle_during_music(world):
    _mode(world, "Standard", hue=[HueLook(area="*", kelvin=3000)], music_hue="room")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    world.state["playing"] = True
    assert world.house.hue_directive() is None


# ═══ 9. phase 2: music_level — the music show's brightness ══════════════════

def test_hand_in_pushes_the_music_levels_and_hand_out_the_resting_ones(world):
    """Spectra owns each WLED's master brightness in phase 2, so the music
    brightness Home Assistant's scripts used to write lives in music_level."""
    from spectra.services import show_output
    _mode(world, "Standard",
          fixtures=[FixtureHook(target=HouseTarget(kind="category", id="Matrix"),
                                level=6, music_level=40),
                    FixtureHook(target=HouseTarget(kind="fixture", id="dev-tv"),
                                level=30)],
          transitions={"music_debounce_s": 0, "music_return_glide_s": 1})
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    assert show_output.base_snapshot()["levels"] == {"dev-crystal": 0.06,
                                                    "dev-tv": 0.30}
    world.state["playing"] = True
    _run(world.house.tick())
    # music: the crystal at its music level, the TV strip at the picture's own
    assert show_output.base_snapshot()["levels"] == {"dev-crystal": 0.40}
    world.state["playing"] = False
    _run(world.house.tick())
    _run(world.house.tick())
    assert world.house.status_dict()["phase"] == "resting"
    assert show_output.base_snapshot()["levels"] == {"dev-crystal": 0.06,
                                                    "dev-tv": 0.30}


def test_a_mode_change_during_music_moves_the_music_levels(world):
    from spectra.services import show_output
    matrix = HouseTarget(kind="category", id="Matrix")
    _mode(world, "Standard", fixtures=[FixtureHook(target=matrix, music_level=80)])
    _mode(world, "Evening", ha_aliases=["Evening"],
          fixtures=[FixtureHook(target=matrix, music_level=30)])
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    world.state["playing"] = True
    _run(world.house.tick())
    assert show_output.base_snapshot()["levels"] == {"dev-crystal": 0.80}
    _run(world.house.set_mode(ha_mode="Evening", source="ha"))
    assert world.house.status_dict()["phase"] == "music"
    assert show_output.base_snapshot()["levels"] == {"dev-crystal": 0.30}


# ═══ 10. phase 2: the media centre selects the TV mode ══════════════════════

def test_a_playing_source_selects_the_tv_mode_and_stopping_returns(world):
    from spectra.services import house_store
    std = _mode(world, "Standard")
    tv = _mode(world, "TV", ha_aliases=["TV"], music="ignore",
               transitions={"button_glide_s": 2})
    paused = _mode(world, "TV paused", ha_aliases=["TV paused"])
    _run(world.house.set_mode(ha_mode="Daytime", source="ha"))
    res = _run(world.house.set_media(source="roku", state="playing"))
    assert res["status"] == "applied"
    assert world.house.current_mode().id == tv.id
    st = house_store.state()
    assert st.mode_id == std.id, "the clock's pick stays underneath"
    assert st.glide_s == 2, "a media change glides like a press"
    lighting = world.house.status_dict()
    assert lighting["mode"]["name"] == "TV"
    assert lighting["clock_mode"]["name"] == "Standard"
    assert lighting["media"]["active"] and lighting["media"]["source"] == "roku"
    res = _run(world.house.set_media(source="roku", state="paused"))
    assert world.house.current_mode().id == paused.id
    res = _run(world.house.set_media(source="roku", state="stopped"))
    assert res["status"] == "applied"
    assert world.house.current_mode().id == std.id


def test_a_clock_change_during_a_film_shows_after_it(world):
    from spectra.services import house_store
    _mode(world, "Standard")
    eve = _mode(world, "Evening", ha_aliases=["Evening"])
    tv = _mode(world, "TV", ha_aliases=["TV"])
    _run(world.house.set_mode(ha_mode="Daytime", source="ha"))
    _run(world.house.set_media(source="bluray", state="playing"))
    res = _run(world.house.set_mode(ha_mode="Evening", source="ha"))
    assert res["status"] == "applied"
    assert house_store.state().mode_id == eve.id
    assert world.house.current_mode().id == tv.id, "the film keeps the room"
    _run(world.house.set_media(source="bluray", state="stopped"))
    assert world.house.current_mode().id == eve.id


def test_a_source_specific_mode_wins_over_the_plain_one(world):
    _mode(world, "Standard")
    _mode(world, "TV", ha_aliases=["TV"])
    game = _mode(world, "Gaming", ha_aliases=["TV (switch)"])
    _run(world.house.set_mode(ha_mode="Daytime", source="ha"))
    _run(world.house.set_media(source="Switch", state="playing"))
    assert world.house.current_mode().id == game.id


def test_a_media_word_no_mode_answers_to_changes_nothing_but_is_recorded(world):
    from spectra.services import house_store
    std = _mode(world, "Standard")
    _run(world.house.set_mode(ha_mode="Daytime", source="ha"))
    res = _run(world.house.set_media(source="roku", state="playing"))
    assert res["status"] == "recorded" and "no house mode answers" in res["note"]
    assert world.house.current_mode().id == std.id
    assert house_store.state().media_state == "playing"


def test_media_never_switches_the_house_on_by_itself(world):
    _mode(world, "TV", ha_aliases=["TV"])
    res = _run(world.house.set_media(source="roku", state="playing"))
    assert res["status"] == "recorded"
    assert world.house.current_mode() is None, \
        "no clock mode set: the house is off and a film does not turn it on"


def test_an_invalid_media_state_is_refused(world):
    res = _run(world.house.set_media(source="roku", state="rewinding"))
    assert res["status"] == "invalid"


def test_repeating_a_media_report_is_a_no_op(world):
    _mode(world, "Standard")
    _mode(world, "TV", ha_aliases=["TV"])
    _run(world.house.set_mode(ha_mode="Daytime", source="ha"))
    _run(world.house.set_media(source="roku", state="playing"))
    res = _run(world.house.set_media(source="roku", state="playing"))
    assert res["status"] == "unchanged"


# ═══ 11. phase 3: energy — resting caps and "off means no stream" ═══════════

class _TypedDev:
    def __init__(self, did, kind):
        self.id, self.type = did, kind


class _TypedHost:
    def __init__(self):
        self.devices = {"dev-crystal": _TypedDev("dev-crystal", "wled"),
                        "dev-tv": _TypedDev("dev-tv", "wled"),
                        "dev-porch": _TypedDev("dev-porch", "wled"),
                        "dev-hue": _TypedDev("dev-hue", "hue")}


def test_a_calm_mode_gets_the_librarys_resting_caps_without_asking(world):
    """settings.energy.resting_fps (Matrix 20, Strips 20, Singles 10) under
    every mode — no fixture setting needed."""
    from fx import device_rate
    _mode(world, "Standard")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    assert device_rate.caps() == {"dev-crystal": 20.0, "dev-porch": 10.0}


def test_a_modes_own_fps_wins_over_the_resting_default(world):
    from fx import device_rate
    _mode(world, "Night light", fixtures=[
        FixtureHook(target=HouseTarget(kind="category", id="Matrix"), fps=15)])
    _run(world.house.set_mode(mode="Night light", source="spectra"))
    assert device_rate.caps() == {"dev-crystal": 15.0, "dev-porch": 10.0}


def test_resting_caps_are_lifted_when_the_music_show_takes_the_room(world):
    from fx import device_rate
    _mode(world, "Standard")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    assert device_rate.caps()
    world.state["playing"] = True
    _run(world.house.tick())
    assert device_rate.caps() == {}


def test_an_emptied_resting_table_lands_at_once(world):
    from fx import device_rate
    from spectra.models.house_mode import HouseEnergy, HouseSettings
    from spectra.services import house_store
    _mode(world, "Standard")
    _run(world.house.set_mode(mode="Standard", source="spectra"))
    house_store.put_settings(HouseSettings(energy=HouseEnergy(resting_fps={})))
    _run(world.house.reapply())
    assert device_rate.caps() == {}


def test_off_on_a_wled_switches_it_off_only_after_the_fade(world, monkeypatch):
    """The mode's dark state fades over the glide; mode_off_devices() names
    the WLED only once that fade (+ OFF_AFTER_FADE_S) is done. A Hue area's
    off stays a dark state — its off is the mode's Hue look."""
    from spectra.services import show_output
    monkeypatch.setattr(show_output, "_host", lambda: _TypedHost())
    _mode(world, "Night light", fixtures=[
        FixtureHook(target=HouseTarget(kind="fixture", id="dev-tv"), off=True),
        FixtureHook(target=HouseTarget(kind="fixture", id="dev-hue"), off=True)],
        transitions={"button_glide_s": 5})
    # make dev-hue resolvable in the world's fake resolver
    real = show_output.resolve_target
    monkeypatch.setattr(show_output, "resolve_target", lambda t: (
        (["dev-hue"], []) if t.get("id") == "dev-hue" else real(t)))
    _run(world.house.set_mode(mode="Night light", source="spectra"))
    assert show_output.base_snapshot()["states"] == {"dev-tv": "dark", "dev-hue": "dark"}
    assert world.house.mode_off_devices() == {}, "still fading to black"
    world.clock.now += 5.0
    assert world.house.mode_off_devices() == {}
    world.clock.now += world.house.OFF_AFTER_FADE_S + 0.01
    assert world.house.mode_off_devices() == {"dev-tv": "Night light"}
    st = world.house.status_dict()
    assert "dev-tv" in st["fixtures"]["switching_off"]


def test_a_fixture_already_dark_is_switched_off_at_once(world, monkeypatch):
    """Night light -> Away (both have the strip off), or a restart that
    re-installed the dark base: no second fade before the switch-off."""
    from spectra.services import show_output
    monkeypatch.setattr(show_output, "_host", lambda: _TypedHost())
    off = [FixtureHook(target=HouseTarget(kind="fixture", id="dev-tv"), off=True)]
    _mode(world, "Night light", fixtures=off, transitions={"button_glide_s": 30})
    _mode(world, "Away", fixtures=off, transitions={"button_glide_s": 30})
    _run(world.house.set_mode(mode="Night light", source="spectra"))
    world.clock.now += 31
    assert world.house.mode_off_devices() == {"dev-tv": "Night light"}
    _run(world.house.set_mode(mode="Away", source="spectra"))
    assert world.house.mode_off_devices() == {"dev-tv": "Away"}


def test_the_music_show_powers_every_fixture_back(world, monkeypatch):
    from spectra.services import show_output
    monkeypatch.setattr(show_output, "_host", lambda: _TypedHost())
    _mode(world, "Evening", fixtures=[
        FixtureHook(target=HouseTarget(kind="fixture", id="dev-tv"), off=True)],
        transitions={"button_glide_s": 0})
    _run(world.house.set_mode(mode="Evening", source="spectra"))
    world.clock.now += 1
    assert world.house.mode_off_devices() == {"dev-tv": "Evening"}
    world.state["playing"] = True
    _run(world.house.tick())
    assert world.house.mode_off_devices() == {}



def test_status_labels_are_unique_when_fixtures_share_a_name(monkeypatch):
    """Four of his WLEDs are all named "WLED": keyed by bare name, three of
    them vanished from every status dict during the 2026-10-05 re-measure."""
    from types import SimpleNamespace

    from spectra.services import house, show_output
    names = {"crystal": "WLED", "porch-rail": "WLED", "radial-dummy": "Radial Dummy",
             "x": "x"}
    monkeypatch.setattr(show_output, "_host",
                        lambda: SimpleNamespace(devices=dict.fromkeys(names)))
    monkeypatch.setattr(show_output, "device_label", lambda d: names[d])
    labels = house.fixture_labels()
    assert labels == {"crystal": "WLED (crystal)", "porch-rail": "WLED (porch-rail)",
                      "radial-dummy": "Radial Dummy", "x": "x"}
    assert house.show_output_label("nope", labels) == "nope"
