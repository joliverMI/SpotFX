"""EVERY DROP ARRIVES IN A NEW COLOUR SET (predrop plan step 2 — the
Admiral, 2026-10-25: "frequently we don't get a color change on the drop. I
want it to change color cleanly so the drop comes in a new color set ... It
should be a big color change, but it can vary, just close to 180 degrees";
amended at approval, 2026-10-26: "if we have a pre-drop, fade the color
throught the predrop, not an instant change. drops without them should have
an instant change").

Three halves, the plan's own acceptance (report section 2.4):

  1. THE PICK, pure (spectra/services/drop_colour.py): over his own 46
     single-hue sets (tests/fixtures/drop_colour_his_sets.json — names and
     wheel positions from a read-only GET of his live colour sets), a pick
     is always 150-210 degrees away when the pool holds such a set, and the
     farthest one otherwise; rainbows count as big; nearest 180 likeliest.
  2. THE PRECEDENCE (ResponseEngine.drop_color_change), every injectable
     explicit: the setting, a room hold, Force Colour (a set pin holds, a
     group pin rolls), a 2D gradient, the incoming scene's pool, the
     instant jump vs the fade's glide, and one colour change per drop.
  3. FROM THE SHOW SIDE (tests/test_preview_holds_the_show.py's standard):
     the REAL trigger engine over a position feed through a song's drops,
     production defaults for every fire path (the drop's response goes
     through engine.fire_response_event, the colour change through
     engine.fire_drop_colour_event), every store isolated — measuring the
     engine's own output: the drop lands a set 150-210 degrees away in the
     drop's own tick, before its phase arm; a drop-led cut wears it, from
     the INCOMING scene's pool; his own drop trigger changes colour too; a
     preview, Force Colour, a house mode and a gradient each hold it and are
     named; the drop band's own colour jump skips; the fade across a
     pre-drop (dormant until drop_firing.PRE_DROPS_PLAY) starts on the
     pre-drop and lands on the drop, a late tick included. A red control
     reproduces the defect: unwired, a drop changes no colour.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from random import Random

import pytest

from spectra.services import drop_colour as dc

FIXTURE = json.loads((Path(__file__).parent / "fixtures" /
                      "drop_colour_his_sets.json").read_text(encoding="utf-8"))
HIS_SETS = FIXTURE["sets"]
HIS_SINGLES = [s for s in HIS_SETS if s["position_deg"] is not None]


def _run(coro):
    return asyncio.run(coro)


def _opt(s: dict, weight: float = 1.0) -> dc.Option:
    return dc.Option(set_id=s["name"], position_deg=s["position_deg"],
                     rainbow=s["rainbow"], weight=weight)


def _dist(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


# ═══ 1. the pick, pure ═══════════════════════════════════════════════════

def test_his_sets_are_the_plans_count():
    """The fixture is what the plan measured: 46 single hues, 5 rainbows,
    3 with no hue at all."""
    rainbows = [s for s in HIS_SETS if s["rainbow"]]
    hueless = [s for s in HIS_SETS if s["position_deg"] is None and not s["rainbow"]]
    assert (len(HIS_SINGLES), len(rainbows), len(hueless)) == (46, 5, 3)


def test_over_his_46_single_hue_sets_a_pick_is_always_in_the_band():
    """His own property: every one of his 46 single-hue sets has a set
    150-210 degrees away, and from each one every draw lands in that band,
    never on itself."""
    pool = [_opt(s) for s in HIS_SINGLES]
    for current in HIS_SINGLES:
        in_band = [s for s in HIS_SINGLES if s is not current
                   and _dist(current["position_deg"], s["position_deg"]) >= 150.0]
        assert len(in_band) >= 2, current["name"]
        for seed in range(12):
            pick = dc.pick(current["name"], current["position_deg"], pool,
                           rng=Random(seed))
            assert pick.rung == dc.RUNG_BAND and pick.in_band
            assert pick.set_id != current["name"]
            assert pick.distance_deg >= 150.0 - 1e-6, (current["name"], pick)


def test_with_nothing_in_the_band_it_takes_the_farthest_and_says_so():
    """From each of his single hues, with every set 150-210 away taken out
    of the pool, the pick is the farthest one left — named, never silent."""
    for current in HIS_SINGLES:
        here = current["position_deg"]
        rest = [s for s in HIS_SINGLES if s is not current
                and _dist(here, s["position_deg"]) < 150.0]
        if not rest:
            continue
        farthest = max(_dist(here, s["position_deg"]) for s in rest)
        pick = dc.pick(current["name"], here, [_opt(s) for s in rest],
                       rng=Random(3))
        assert pick.rung == dc.RUNG_WIDEST and not pick.in_band
        assert pick.distance_deg == pytest.approx(farthest)


def test_the_sets_nearest_180_are_likeliest():
    """Two sets, equal weight: one dead opposite, one on the band's edge.
    Closeness runs from EDGE_WEIGHT (0.25) to 1.0, so the opposite one is
    picked four times in five."""
    opts = [dc.Option("opposite", 180.0), dc.Option("edge", 150.0)]
    rng = Random(11)
    n = 4000
    opposite = sum(dc.pick("cur", 0.0, opts, rng=rng).set_id == "opposite"
                   for _ in range(n))
    assert 0.76 < opposite / n < 0.84


def test_it_varies_from_drop_to_drop():
    """His "it can vary": from one set, a run of drops lands several
    different sets of the band, not one."""
    here = 13.4                                 # "Mid - Fire"
    pool = [_opt(s) for s in HIS_SINGLES]
    rng = Random(2)
    seen = {dc.pick("Mid - Fire", here, pool, rng=rng).set_id for _ in range(60)}
    assert len(seen) >= 3


def test_rainbows_count_as_big_both_ways():
    singles = [dc.Option("near", 30.0)]
    rainbow = dc.Option("hype", None, rainbow=True)
    # single hue -> a rainbow is a big change (nothing single in the band)
    to = dc.pick("cur", 0.0, singles + [rainbow], rng=Random(1))
    assert (to.set_id, to.rung) == ("hype", dc.RUNG_TO_RAINBOW)
    # a rainbow showing -> every single hue is big; never another rainbow
    other_rainbow = dc.Option("bh rainbow", None, rainbow=True)
    for seed in range(20):
        frm = dc.pick("hype", None, [dc.Option("near", 30.0), other_rainbow],
                      rng=Random(seed), current_rainbow=True)
        assert (frm.set_id, frm.rung) == ("near", dc.RUNG_FROM_RAINBOW)
    # rainbow -> rainbow only when nothing else is allowed
    only = dc.pick("hype", None, [other_rainbow], rng=Random(1),
                   current_rainbow=True)
    assert (only.set_id, only.rung) == ("bh rainbow", dc.RUNG_RAINBOW_ONLY)


def test_a_set_with_no_hue_is_never_picked_and_an_empty_pool_keeps_the_colours():
    hueless = dc.Option("brightness", None, rainbow=False)
    assert dc.pick("cur", 0.0, [hueless], rng=Random(1)).rung == dc.RUNG_KEPT
    alone = dc.pick("cur", 0.0, [dc.Option("cur", 0.0)], rng=Random(1))
    assert (alone.set_id, alone.rung) == (None, dc.RUNG_KEPT)
    with_one = dc.pick("cur", 0.0, [hueless, dc.Option("cyan", 180.0)],
                       rng=Random(1))
    assert with_one.set_id == "cyan"


def test_his_selector_weight_counts_and_a_zero_weight_band_relaxes():
    opts = [dc.Option("weighted", 175.0, weight=1.0),
            dc.Option("zeroed", 180.0, weight=0.0)]
    for seed in range(30):
        p = dc.pick("cur", 0.0, opts, rng=Random(seed))
        assert p.set_id == "weighted" and not p.relaxed
    all_zero = [dc.Option("a", 175.0, weight=0.0), dc.Option("b", 180.0, weight=0.0)]
    p = dc.pick("cur", 0.0, all_zero, rng=Random(4))
    assert p.relaxed and p.in_band and p.set_id in ("a", "b")


def test_the_draw_does_not_depend_on_the_pool_order():
    pool = [_opt(s) for s in HIS_SINGLES]
    picks = {dc.pick("Mid - Fire", 13.4, list(order), rng=Random(9)).set_id
             for order in (pool, list(reversed(pool)), pool[7:] + pool[:7])}
    assert len(picks) == 1


def test_the_spread_narrows_the_band_and_is_clamped():
    opts = [dc.Option("170", 170.0), dc.Option("179", 179.0)]
    narrow = dc.pick("cur", 0.0, opts, spread_deg=5.0, rng=Random(1))
    assert narrow.set_id == "179"                  # 170 is outside 175-185
    assert dc.clamp_spread(0.0) == dc.MIN_SPREAD_DEG
    assert dc.clamp_spread(500.0) == dc.MAX_SPREAD_DEG


# ═══ 2. the precedence: ResponseEngine.drop_color_change ═════════════════

from spectra.models.gradient2d import GradientProfile  # noqa: E402
from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec,  # noqa: E402
                                  SceneDeviceConfig, SceneV2)
from spectra.models.sequencer import SelectorEntry, SequencerConfig  # noqa: E402
from spectra.services import color_journey as cj  # noqa: E402
from spectra.services import color_wheel  # noqa: E402
from spectra.services import scene_compiler  # noqa: E402
from spectra.services.color_sets import (ColorSetCard, ColorSetEntry,  # noqa: E402
                                         GroupMember, SetScope)
from spectra.services.drift_conductor import DriftConductor  # noqa: E402
from spectra.services.fx_executor import RecordingExecutor  # noqa: E402
from spectra.services.room_controls import RoomControlState  # noqa: E402
from spectra.services.scene_response import ResponseEngine  # noqa: E402

COLOURS = {"red": "#ff0000", "orange": "#ff5500", "green": "#00ff00",
           "cyan": "#00ffff", "blue": "#0000ff", "pink": "#ff002a",
           "rainbow": "linear-gradient(90deg, #ff0000 0%, #00ff00 50%, #0000ff 100%)"}
POSITIONS = {"red": 0.0, "orange": 20.0, "green": 120.0, "cyan": 180.0,
             "blue": 240.0, "pink": 350.1, "rainbow": None}


def _card(sid: str) -> ColorSetCard:
    return ColorSetCard(id=sid, name=sid.title(), is_rainbow=(sid == "rainbow"),
                        entries=[ColorSetEntry(scope=SetScope(virtual_ids=["v1"]),
                                               color_value=COLOURS[sid])])


CARDS = {sid: _card(sid) for sid in COLOURS}
CARDS["pool"] = ColorSetCard(id="pool", name="Pool", kind="group", members=[
    GroupMember(color_set_id="green"), GroupMember(color_set_id="blue")])
CONFIG = SequencerConfig(color_set_entries={
    sid: SelectorEntry() for sid in COLOURS})


@pytest.fixture
def card_store(monkeypatch, tmp_path):
    """A card's entries address virtuals by id (no device categories exist
    in a test); force colour and the groups resolve against these cards;
    the room controls a group's member filter reads are isolated."""
    from spectra import config as scfg
    from spectra.services import color_sets
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scene_compiler, "_set_entry_by_virtual", lambda card: {
        vid: e for e in card.entries for vid in e.scope.virtual_ids})
    monkeypatch.setattr(color_sets, "get_by_id", lambda sid: CARDS.get(sid))
    monkeypatch.setattr(color_sets, "list_all", lambda: list(CARDS.values()))
    from spectra.services import color_set_groups
    color_set_groups._cursor.clear()
    yield


class Rig:
    def __init__(self, *, controls: RoomControlState | None = None,
                 deferral=None, room: cj.RoomColorState | None = None,
                 pool: set | None = None):
        self.room = [room or cj.RoomColorState(wheel_position_deg=0.0,
                                               active_set_id="red")]
        self.controls = controls or RoomControlState()
        self.pool_scenes: list = []
        self.executor = RecordingExecutor(
            clock=lambda: 0.0, room_controls_load=lambda: self.controls)
        self.conductor = DriftConductor(
            executor=self.executor, clock=lambda: 0.0, leg_s=20.0,
            intensity=lambda: 0.5, deferral=deferral or (lambda: None),
            drift_profiles=lambda: {}, curve_profiles=lambda: {},
            room_load=lambda: self.room[0],
            room_save=lambda st: self.room.__setitem__(0, st),
            set_position=lambda sid: POSITIONS.get(sid),
            set_cards=lambda: list(CARDS.values()),
            sequencer_config=lambda: CONFIG,
            gradient_profiles=lambda: {"g1": GradientProfile(
                id="g1", name="G", top="#ffff00", bottom="#0000ff",
                x_mode="loop")},
            room_controls=lambda: self.controls, rng=Random(3))
        allowed = (pool if pool is not None
                   else {s for s in POSITIONS if s != "rainbow"})

        def drop_pool(scene, intensity):
            self.pool_scenes.append(scene.name)
            accept = (allowed if scene.accept_all_sets
                      else set(scene.accepted_set_ids) & allowed)
            return {sid: color_wheel.wheel_position(CARDS[sid]) for sid in accept}

        self.responses = ResponseEngine(
            conductor=self.conductor, executor=self.executor, rng=Random(5),
            clock=lambda: 0.0,
            sequencer_config=lambda: CONFIG, curve_profiles=lambda: {},
            set_card=lambda sid: CARDS.get(sid),
            room_load=lambda: self.room[0],
            room_save=lambda st: self.room.__setitem__(0, st),
            room_controls=lambda: self.controls,
            drop_colour_pool=drop_pool,
            set_wheel=lambda sid: (color_wheel.wheel_position(CARDS[sid])
                                   if sid in CARDS else None),
            group_ids_by_set=lambda: {})

    def fire(self, scene: SceneV2) -> None:
        writes = [{"virtual_id": "v1", "effect_type": "orbits",
                   "config": {"gradient": COLOURS["red"]}, "color_mode": "set",
                   "entry_id": scene.devices[0].id}]
        self.conductor.on_scene_fire(scene, writes)


def _scene(name="Orbits", *, accept=None, colour_jump_on_drop=False) -> SceneV2:
    kinds = []
    responses = {}
    if colour_jump_on_drop:
        kinds = [FlareKind(name="Colour Jump", type="drift_jump", jump="color_set")]
        responses = {"drop": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds={"Colour Jump": 1.0})])}
    return SceneV2(name=name, devices=[SceneDeviceConfig(
        target_kind="virtual", target="v1", effect_type="orbits")],
        flare_kinds=kinds, responses=responses,
        accept_all_sets=accept is None, accepted_set_ids=list(accept or []))


def test_a_drop_lands_a_set_about_opposite_in_one_jump(card_store):
    rig = Rig()
    rig.fire(_scene())
    record = _run(rig.responses.drop_color_change(0.7))
    assert record["result"] == "jumped"
    assert record["color_jump"]["picked_id"] == "cyan"     # 180 from red
    assert (record["rung"], record["distance_deg"]) == (dc.RUNG_BAND, 180.0)
    write = rig.executor.writes[-1]
    assert (write["kind"], write["params"]["gradient"]) == ("jump", COLOURS["cyan"])
    room = rig.room[0]
    assert (room.active_set_id, room.wheel_position_deg, room.destination) == \
        ("cyan", 180.0, None), "the journey carries on from the new set"
    assert rig.conductor.virtuals["v1"].gradient == COLOURS["cyan"]


def test_a_fade_glides_over_the_time_it_is_given(card_store):
    rig = Rig()
    rig.fire(_scene())
    record = _run(rig.responses.drop_color_change(0.7, ramp_ms=800,
                                                  moment="pre_drop"))
    assert record["result"] == "jumped" and record["moment"] == "pre_drop"
    write = rig.executor.writes[-1]
    assert (write["kind"], write["duration_ms"]) == ("glide", 800)


def test_it_is_a_colour_change_not_a_flare(card_store):
    """A Light Show "flares off" target still changes colour."""
    rig = Rig()
    rig.fire(_scene())
    rig.responses._flare_blocked = lambda: frozenset({"v1"})
    record = _run(rig.responses.drop_color_change(0.7))
    assert record["color_jump"]["virtuals"] == 1


def test_the_room_setting_off_changes_nothing(card_store):
    rig = Rig(controls=RoomControlState(drop_colour_change=False))
    rig.fire(_scene())
    record = _run(rig.responses.drop_color_change(0.7))
    assert record["result"] == "off"
    assert rig.room[0].active_set_id == "red" and not rig.executor.writes


def test_a_room_hold_holds_it_and_names_it(card_store):
    rig = Rig(deferral=lambda: "preview")
    rig.fire(_scene())
    record = _run(rig.responses.drop_color_change(0.7))
    assert (record["result"], record["held_for"]) == ("held", "preview")
    assert rig.room[0].active_set_id == "red" and not rig.executor.writes


def test_force_colour_a_pinned_set_stays(card_store):
    rig = Rig(controls=RoomControlState(force_color_enabled=True,
                                        force_color_target_id="blue"))
    rig.fire(_scene())
    record = _run(rig.responses.drop_color_change(0.7))
    assert (record["result"], record["held_for"]) == ("held", "force_color")
    assert record["forced_color"] == "blue"
    assert not rig.executor.writes and rig.room[0].active_set_id == "red"


def test_force_colour_a_pinned_group_rolls_its_next_member(card_store):
    rig = Rig(controls=RoomControlState(force_color_enabled=True,
                                        force_color_target_id="pool"))
    rig.fire(_scene())
    first = _run(rig.responses.drop_color_change(0.7))
    second = _run(rig.responses.drop_color_change(0.7))
    assert first["result"] == second["result"] == "jumped"
    assert first["rung"] == "pinned_group"
    landed = [first["color_jump"]["picked_id"], second["color_jump"]["picked_id"]]
    assert landed == ["green", "blue"], "the pin's own rotation, member by member"


def test_a_2d_gradient_keeps_the_drop_for_its_own_kick(card_store):
    rig = Rig(controls=RoomControlState(active_gradient_id="g1"))
    rig.fire(_scene())
    record = _run(rig.responses.drop_color_change(0.7))
    assert (record["result"], record["held_for"]) == ("held", "gradient_drift")
    assert rig.room[0].active_set_id == "red" and not rig.executor.writes


def test_the_incoming_scenes_pool_decides(card_store):
    """When the drop switches the scene, the set comes from the scene that
    will show: the incoming one accepts only orange, so orange it is — even
    though the showing scene would have taken cyan."""
    rig = Rig()
    rig.fire(_scene())
    star = _scene("Star", accept=["orange"])
    record = _run(rig.responses.drop_color_change(0.7, pool_scene=star))
    assert record["color_jump"]["picked_id"] == "orange"
    assert rig.pool_scenes == ["Star"] and record["pool_scene"] == "Star"


def test_nothing_in_the_band_takes_the_farthest_and_no_set_keeps_the_colours(card_store):
    rig = Rig(pool={"red", "orange", "green"})
    rig.fire(_scene())
    widest = _run(rig.responses.drop_color_change(0.7))
    assert (widest["color_jump"]["picked_id"], widest["rung"]) == \
        ("green", dc.RUNG_WIDEST)
    alone = Rig(pool={"red"})
    alone.fire(_scene())
    kept = _run(alone.responses.drop_color_change(0.7))
    assert kept["result"] == "kept_current" and not alone.executor.writes


def test_from_a_rainbow_any_single_hue_is_big(card_store):
    rig = Rig(room=cj.RoomColorState(wheel_position_deg=0.0,
                                     active_set_id="rainbow"))
    rig.fire(_scene())
    record = _run(rig.responses.drop_color_change(0.7))
    assert record["result"] == "jumped" and record["from_rainbow"] is True
    assert record["rung"] == dc.RUNG_FROM_RAINBOW
    assert record["color_jump"]["picked_id"] != "rainbow"


def test_the_drop_band_skips_its_own_colour_jump_after_the_change(card_store):
    """One colour change per drop: a scene whose drop band carries a colour
    jump skips it once the drop colour change has landed — named — and runs
    it as before when no change preceded the drop."""
    rig = Rig()
    scene = _scene(colour_jump_on_drop=True)
    rig.fire(scene)
    _run(rig.responses.drop_color_change(0.7))
    after = _run(rig.responses.on_event("drop", 0.7))
    [kind] = after["kinds"]
    assert kind["skipped"] == "drop_colour_change" and after["drop_colour_done"]
    assert rig.room[0].active_set_id == "cyan", "the drop change stands"
    # the claim was taken: the next drop (no colour change before it) jumps
    again = _run(rig.responses.on_event("drop", 0.7))
    [kind] = again["kinds"]
    assert "skipped" not in kind and kind["result"] == "jumped"


def test_the_claim_lapses_when_its_drop_never_comes(card_store):
    now = [0.0]
    rig = Rig()
    rig.responses._clock = lambda: now[0]
    scene = _scene(colour_jump_on_drop=True)
    rig.fire(scene)
    _run(rig.responses.drop_color_change(0.7))
    now[0] = 5.0                    # the drop's response was gated; a later drop
    later = _run(rig.responses.on_event("drop", 0.7))
    [kind] = later["kinds"]
    assert "skipped" not in kind


def test_a_phase_only_drop_still_takes_the_claim(card_store):
    """A drop with no response band of its own (phase only) consumes its
    colour change's claim too, so it never carries over to a later drop."""
    rig = Rig()
    rig.fire(_scene())                         # no drop band at all
    _run(rig.responses.drop_color_change(0.7))
    first = _run(rig.responses.on_event("drop", 0.7))
    assert first["result"] == "phase_only" and first["drop_colour_done"]
    assert rig.responses._take_drop_colour_claim() is False


def test_a_staggered_drop_batch_carries_the_skip(card_store):
    """PER-FLARE TRIGGER MOMENT: a drop band's colour jump staggered to a
    later batch skips too."""
    rig = Rig()
    scene = _scene(colour_jump_on_drop=True)
    scene.flare_kinds.append(FlareKind(name="Early", type="drift_jump",
                                       jump="color_set", trigger_offset_ms=-100))
    scene.responses["drop"].bands[0].kinds["Early"] = 1.0
    rig.fire(scene)
    _run(rig.responses.drop_color_change(0.7))
    _run(rig.responses.on_event("drop", 0.7, anchor_relocated=True))
    [batch] = rig.responses.take_kind_batch_schedule()
    assert batch.drop_colour_done is True
    outcome = _run(rig.responses.run_kind_batch(batch))
    [kind] = outcome["kinds"]
    assert kind["skipped"] == "drop_colour_change"


# ═══ 3. from the show side: the real trigger engine through a song ═══════

from fx import device_model  # noqa: E402
from spectra.models.trigger import FireResponseAction, SpectraTrigger  # noqa: E402
from spectra.services import drop_detector as dd  # noqa: E402
from spectra.services import drop_firing  # noqa: E402
from spectra.services import drop_sequences as ds  # noqa: E402
from spectra.services import drop_switch  # noqa: E402
from spectra.services.trigger_engine import TriggerEngine  # noqa: E402

URI = "spotify:track:dropcolour1"
BEAT = 500.0
DROPS = ((20_000, 16_000, 12_000), (52_000, 48_000, 44_000))  # (drop, lull, charge)
SHOW_ACCEPTS = ["red", "green", "cyan", "blue", "pink", "rainbow"]  # never orange
STAR_ACCEPTS = ["orange"]


@pytest.fixture
def show(tmp_path, monkeypatch):
    """Every store the drop path reads or writes, isolated; his colour
    sets, two scenes and the room as the show finds them."""
    from spectra import config as scfg
    for name, fn in (("SCENES_FILE", "scenes.json"),
                     ("SEQUENCER_FILE", "sequencer.json"),
                     ("ROOM_COLOR_FILE", "room_color.json"),
                     ("ROOM_CONTROLS_FILE", "room_controls.json"),
                     ("COLOR_SETS_FILE", "color_sets.json"),
                     ("GRADIENT2D_FILE", "gradients2d.json"),
                     ("DRIFT_PROFILES_FILE", "drift_profiles.json"),
                     ("TRIGGERS_FILE", "triggers.json")):
        monkeypatch.setattr(scfg, name, tmp_path / fn)
    monkeypatch.setattr(device_model, "CATEGORIES_FILE",
                        tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()
    monkeypatch.setattr(scene_compiler, "_set_entry_by_virtual", lambda card: {
        vid: e for e in card.entries for vid in e.scope.virtual_ids})
    scfg.COLOR_SETS_FILE.write_text(json.dumps(
        {sid: CARDS[sid].model_dump() for sid in COLOURS}))
    from spectra.services import scene_store
    orbits = _scene("Orbits", accept=SHOW_ACCEPTS).model_copy(
        update={"id": "orbits-scene"})
    star = _scene("Star", accept=STAR_ACCEPTS).model_copy(update={"id": "star-scene"})
    scene_store.save(orbits)
    scene_store.save(star)
    cj.save_room(cj.RoomColorState(wheel_position_deg=0.0, active_set_id="red"))
    ds.reset()
    yield {"orbits": orbits, "star": star}
    ds.reset()
    device_model.refresh()


def _with_drop_colour_jump(scenes):
    """Orbits as a scene whose drop band carries its own Colour Jump."""
    from spectra.services import scene_store
    orbits = _scene("Orbits", accept=SHOW_ACCEPTS,
                    colour_jump_on_drop=True).model_copy(update={"id": "orbits-scene"})
    scene_store.save(orbits)
    return {**scenes, "orbits": orbits}


def _controls(**kw):
    from spectra.services.room_controls import save_room_controls
    save_room_controls(RoomControlState(**kw))


def _detect(drops=DROPS, step=0.8):
    """His drop sequences, detected and confident. step 0.8 is a drop
    intensity of 0.8 (drop_firing.sequence_intensity) — under his rainbow
    limit, where the automatic pool is single-hue."""
    def fn(entry):
        entry["detected"] = {
            "uri": URI, "detector_version": dd.DETECTOR_VERSION,
            "confident_score": 1.0, "suggested_score": 0.7,
            "tempo_bpm": 120.0, "beat_ms": BEAT, "captured_from_ms": 0,
            "captured_to_ms": 200_000, "duration_ms": 200_000, "stamp": "test",
            "sequences": [
                {"key": dd.drop_key(d), "drop_ms": d, "lull_ms": lu,
                 "charge_ms": ch, "score": 1.2, "tier": dd.TIER_CONFIDENT,
                 "break_beats": 3.0, "step": step, "rise": 0.9, "path": "step",
                 "loud_before": True, "capped": False, "notes": []}
                for d, lu, ch in drops],
            "excluded": [],
        }
    ds._mutate(URI, fn)


class _Plan:
    flares: list = []
    scene_cues: list = []


async def _noop(*_a, **_k):
    return None


class Show:
    """The real trigger engine wired to the production choke points, over a
    scratch conductor/responder pair (RecordingExecutor) that the engine
    module's own fire_response_event / fire_drop_colour_event reach."""

    def __init__(self, monkeypatch, scenes, *, mode="analysed", triggers=(),
                 wired=True, drop_view=None):
        from spectra.services import engine as engine_mod
        self.now = [0.0]
        self.executor = RecordingExecutor(clock=lambda: self.now[0])
        self.conductor = DriftConductor(
            executor=self.executor, clock=lambda: self.now[0], rng=Random(0),
            drift_profiles=lambda: {}, curve_profiles=lambda: {},
            sequencer_config=lambda: CONFIG)
        self.responses = ResponseEngine(
            conductor=self.conductor, executor=self.executor,
            clock=lambda: self.now[0], rng=Random(5),
            sequencer_config=lambda: CONFIG, curve_profiles=lambda: {})
        monkeypatch.setattr(engine_mod, "responses", self.responses)
        monkeypatch.setattr(engine_mod, "conductor", self.conductor)
        self.scenes = scenes
        self.showing = scenes["orbits"]
        self.cue_told: list[int] = []        # positions the journey was told at
        self._seed(self.showing)
        self.cuts: list[tuple[str, str]] = []
        effects = {"orbits-scene": "orbits", "star-scene": "radial"}

        def showing():
            s = self.showing
            return drop_switch.Showing(
                scene=drop_switch.SceneInfo(s.id, s.name, effects[s.id]),
                stint=(s.id, 0), shown_s=5.0, dwell_s=8.0)

        async def cut(scene_id, intensity):
            # What scene_sequencer.fire_scene_by_id(scene_id, None, ...)
            # compiles with: the room's active set (scene_compiler.
            # room_active_set — real code over the isolated stores).
            worn = scene_compiler.room_active_set()
            self.cuts.append((scene_id, worn.id if worn else None))
            self.showing = scenes["star"]
            self._seed(self.showing)
            return {}

        self.engine = TriggerEngine(
            list_triggers=lambda uri: list(triggers),
            scene_change_mode=lambda: mode,
            drop_view=drop_view, drop_revision=lambda: 1,
            drop_testing=lambda: False,
            drop_colour=engine_mod.fire_drop_colour_event if wired else None,
            switch_showing=showing,
            switch_settings=lambda: drop_switch.SwitchSettings(),
            switch_blocker=lambda: None,
            switch_pick=lambda _i: (lambda _showing_id, _rng: drop_switch.SceneInfo(
                "star-scene", "Star", "radial")),
            fire_drop_switch=cut,
            colour_cue=lambda: self.cue_told.append(self.engine._last_position_ms),
            analysed_plan=lambda uri, stored: _Plan(),
            fire_analysed_flare=_noop, fire_scene=_noop,
            render_intensity=lambda x: x, lead_ms=lambda t: 0,
            response_offset_ms=lambda a: 0, drop_offset_ms=lambda: 0,
            sequencer_enabled=lambda: False, auto_generate=_noop,
            auto_refresh=_noop)

    def _seed(self, scene):
        worn = scene_compiler.room_active_set()
        writes = [{"virtual_id": "v1", "effect_type": scene.devices[0].effect_type,
                   "config": {"gradient": COLOURS[worn.id] if worn else COLOURS["red"]},
                   "color_mode": "set", "entry_id": scene.devices[0].id}]
        self.conductor.on_scene_fire(scene, writes)

    def sweep(self, stop=60_000, step=200, start=0, positions=None):
        async def run():
            await self.engine.on_track_state(URI)
            for pos in (positions if positions is not None
                        else range(start, stop + 1, step)):
                self.now[0] = pos / 1000.0
                await self.engine.tick(pos)
        asyncio.run(run())

    def colour_writes(self):
        return [w for w in self.executor.writes if "gradient" in w["params"]]

    def drop_entries(self):
        from spectra.services import fire_history
        return [e for e in fire_history.load_show_log()
                if e.get("bucket") == "triggers"
                and (e.get("detail") or {}).get("member") == "drop"
                or (e.get("bucket") == "triggers"
                    and (e.get("detail") or {}).get("action_kind") == "fire_response"
                    and "drop_colour" in (e.get("detail") or {}))]


def _room():
    return cj.load_room()


def test_red_control_unwired_a_drop_changes_no_colour(monkeypatch, show):
    """The defect he reported, reproduced: without the drop colour change a
    drop sequence plays in whatever colours were showing."""
    _controls(scene_change_mode="analysed")
    _detect()
    rig = Show(monkeypatch, show, wired=False)
    rig.sweep()
    assert _room().active_set_id == "red"
    assert not [w for w in rig.colour_writes() if w["kind"] == "jump"]


def test_every_drop_lands_a_set_about_opposite_in_its_own_tick(monkeypatch, show):
    _controls(scene_change_mode="analysed")
    _detect()
    rig = Show(monkeypatch, show)
    rig.sweep(stop=21_000)
    room = _room()
    assert room.active_set_id == "cyan"                  # 180 from red
    assert (room.wheel_position_deg, room.destination) == (180.0, None)
    [jump] = [w for w in rig.colour_writes() if w["kind"] == "jump"]
    assert jump["params"]["gradient"] == COLOURS["cyan"]
    assert jump["at"] == pytest.approx(20.0), "on the drop's own tick"
    # ...BEFORE the drop's own phase arm, which lands in the new colours
    arm = next(w for w in rig.executor.writes
               if w["params"].get("phase") == "drop")
    assert jump["seq"] < arm["seq"] and arm["at"] == jump["at"]
    [entry] = [e for e in rig.drop_entries()
               if e["detail"].get("drop_sequence") == dd.drop_key(20_000)]
    brief = entry["detail"]["drop_colour"]
    assert (brief["result"], brief["to_set_id"], brief["from_set_id"]) == \
        ("jumped", "cyan", "red")
    assert (brief["rung"], brief["distance_deg"]) == (dc.RUNG_BAND, 180.0)
    from spectra.services import fire_history
    counted = [e for e in fire_history.load_show_log()
               if e.get("bucket") == "color_sets"
               and (e.get("detail") or {}).get("via") == "drop_colour"]
    assert [e["key"] for e in counted] == ["cyan"]


def test_the_drop_band_colour_jump_skips_so_one_drop_is_one_change(monkeypatch, show):
    _controls(scene_change_mode="analysed")
    _detect(drops=DROPS[:1])
    rig = Show(monkeypatch, _with_drop_colour_jump(show))
    rig.sweep(stop=21_000)
    drops = [s for s in rig.responses.surges if s.get("class") == "drop"]
    [surge] = drops
    [kind] = surge["kinds"]
    assert kind["skipped"] == "drop_colour_change"
    assert len([w for w in rig.colour_writes() if w["kind"] == "jump"]) == 1


def test_a_drop_led_cut_wears_the_new_set_from_the_incoming_scenes_pool(monkeypatch, show):
    """The second drop repeats the first on a stale Orbits: the drop-led
    switch cuts to Star ON the drop. The colour change comes first, from
    Star's pool (orange — Orbits never accepts it), and the cut compiles
    in it."""
    _controls(scene_change_mode="analysed")
    _detect()
    rig = Show(monkeypatch, show)
    rig.sweep()
    assert rig.cuts == [("star-scene", "orange")]
    room = _room()
    assert room.active_set_id == "orange"
    assert rig.cue_told == [20_000, 52_000], \
        "the journey re-plans once per drop — the cut's own notice included"
    entry = next(e for e in rig.drop_entries()
                 if e["detail"].get("drop_sequence") == dd.drop_key(52_000))
    brief = entry["detail"]["drop_colour"]
    assert (brief["to_set_id"], brief["pool_scene"]) == ("orange", "Star")
    assert brief["distance_deg"] == pytest.approx(160.0)


def test_his_own_drop_trigger_changes_colour_too(monkeypatch, show):
    _controls(scene_change_mode="full")
    his = SpectraTrigger(id="his-drop", timestamp_ms=3000, source="authored",
                         action=FireResponseAction(event_class="drop", intensity=0.8))
    rig = Show(monkeypatch, show, mode="full", triggers=[his])
    rig.sweep(stop=4000)
    assert _room().active_set_id == "cyan"
    [entry] = [e for e in rig.drop_entries()
               if e["detail"].get("trigger_id") == "his-drop"]
    assert entry["detail"]["drop_colour"]["to_set_id"] == "cyan"


@pytest.mark.parametrize("hold, named", [
    ("force_colour", "force_color"),
    ("house_mode", "house_mode"),
    ("gradient", "gradient_drift"),
])
def test_a_hold_holds_the_change_and_names_it(monkeypatch, show, hold, named):
    if hold == "force_colour":
        _controls(scene_change_mode="analysed", force_color_enabled=True,
                  force_color_target_id="blue")
    elif hold == "gradient":
        from spectra.services import gradient2d_store
        gradient2d_store.save_all({"g1": GradientProfile(
            id="g1", name="G", top="#ffff00", bottom="#0000ff", x_mode="loop")})
        _controls(scene_change_mode="analysed", active_gradient_id="g1")
    else:
        _controls(scene_change_mode="analysed")
        from spectra.services import house
        monkeypatch.setattr(house, "scene_deferral",
                            lambda: "house mode 'Evening' keeps its look")
    _detect(drops=DROPS[:1])
    rig = Show(monkeypatch, show)
    rig.sweep(stop=21_000)
    assert _room().active_set_id == "red"
    [entry] = rig.drop_entries()
    brief = entry["detail"]["drop_colour"]
    assert (brief["result"], brief["held_for"]) == ("held", named)
    set_jumps = [w for w in rig.colour_writes() if w["kind"] == "jump"]
    assert not set_jumps, "no colour set landed while held"


def test_a_preview_holds_the_drop_and_its_colour(monkeypatch, show):
    from spectra.services import preview_pause
    _controls(scene_change_mode="analysed")
    _detect(drops=DROPS[:1])
    rig = Show(monkeypatch, show)
    preview_pause.start(120.0)
    try:
        rig.sweep(stop=21_000)
    finally:
        preview_pause.clear()
    assert _room().active_set_id == "red"
    assert not rig.executor.writes, "nothing at all reached the lights"
    [entry] = rig.drop_entries()
    assert entry["detail"]["drop_colour"]["held_for"] == "preview"


def test_the_room_setting_off_leaves_drops_as_they_were(monkeypatch, show):
    _controls(scene_change_mode="analysed", drop_colour_change=False)
    _detect(drops=DROPS[:1])
    rig = Show(monkeypatch, _with_drop_colour_jump(show))
    rig.sweep(stop=21_000)
    [surge] = [s for s in rig.responses.surges if s.get("class") == "drop"]
    [kind] = surge["kinds"]
    assert kind.get("result") == "jumped" and "skipped" not in kind, \
        "the scene's own drop colour jump plays as before"


def test_a_drop_over_the_rainbow_limit_lands_a_rainbow(monkeypatch, show):
    """His rainbow limit still decides (the plan's own "worth watching"): a
    drop louder than it (0.9) draws from the rainbow sets only, and a
    single hue -> rainbow counts as a big change."""
    _controls(scene_change_mode="analysed")
    _detect(drops=DROPS[:1], step=1.5)          # drop intensity 1.0
    rig = Show(monkeypatch, show)
    rig.sweep(stop=21_000)
    assert _room().active_set_id == "rainbow"
    [entry] = rig.drop_entries()
    assert entry["detail"]["drop_colour"]["rung"] == dc.RUNG_TO_RAINBOW


# ── the fade across a pre-drop: built, tested, dormant ──────────────────────

def _with_pre_drop(lead_ms=800):
    def view(uri, triggers):
        v = ds.view(uri, triggers=triggers)
        for s in v.get("sequences") or []:
            s["pre_drop_ms"] = int(s["drop_ms"]) - lead_ms
        return v
    return view


def test_pre_drops_do_not_play_yet(monkeypatch, show):
    """Until the pre-drop engine lands (drop_firing.PRE_DROPS_PLAY), a view
    carrying pre-drop times changes nothing: the change is instant, on the
    drop."""
    assert drop_firing.PRE_DROPS_PLAY is False
    _controls(scene_change_mode="analysed")
    _detect(drops=DROPS[:1])
    rig = Show(monkeypatch, show, drop_view=_with_pre_drop())
    rig.sweep(stop=21_000)
    colour = rig.colour_writes()
    assert [(w["kind"], w["at"]) for w in colour if w["kind"] == "jump"] == \
        [("jump", pytest.approx(20.0))]
    assert not [w for w in colour if w["kind"] == "glide"]


def test_with_a_pre_drop_the_change_fades_from_it_and_lands_on_the_drop(monkeypatch, show):
    monkeypatch.setattr(drop_firing, "PRE_DROPS_PLAY", True)
    _controls(scene_change_mode="analysed")
    _detect(drops=DROPS[:1])
    rig = Show(monkeypatch, _with_drop_colour_jump(show),
               drop_view=_with_pre_drop(800))
    rig.sweep(stop=21_000)
    colour = rig.colour_writes()
    [glide] = [w for w in colour if w["kind"] == "glide"]
    assert glide["at"] == pytest.approx(19.2), "starts ON the pre-drop"
    assert glide["duration_ms"] == 800, "lands on the drop"
    assert glide["params"]["gradient"] == COLOURS["cyan"]
    assert not [w for w in colour if w["kind"] == "jump"], \
        "the drop does not change again"
    [surge] = [s for s in rig.responses.surges if s.get("class") == "drop"]
    [kind] = surge["kinds"]
    assert kind["skipped"] == "drop_colour_change"
    [entry] = rig.drop_entries()
    assert entry["detail"]["drop_colour"]["result"] == "faded_at_pre_drop"
    from spectra.services import fire_history
    [pre] = [e for e in fire_history.load_show_log()
             if e.get("key") == "drop_sequence:pre_drop_colour"]
    assert pre["detail"]["drop_colour"]["to_set_id"] == "cyan"


def test_the_colour_journey_is_told_when_the_change_lands(monkeypatch, show):
    """The journey re-plans from the new set once it is on the lights: on
    the drop for an instant change, on the drop (not the pre-drop) for a
    fade."""
    _controls(scene_change_mode="analysed")
    _detect(drops=DROPS[:1])
    instant = Show(monkeypatch, show)
    instant.sweep(stop=21_000)
    assert instant.cue_told == [20_000]
    monkeypatch.setattr(drop_firing, "PRE_DROPS_PLAY", True)
    ds.reset()
    _detect(drops=DROPS[:1])
    cj.save_room(cj.RoomColorState(wheel_position_deg=0.0, active_set_id="red"))
    faded = Show(monkeypatch, show, drop_view=_with_pre_drop(800))
    faded.sweep(stop=21_000)
    assert faded.cue_told == [20_000]


def test_a_late_pre_drop_tick_still_lands_on_the_drop(monkeypatch, show):
    monkeypatch.setattr(drop_firing, "PRE_DROPS_PLAY", True)
    _controls(scene_change_mode="analysed")
    _detect(drops=DROPS[:1])
    rig = Show(monkeypatch, show, drop_view=_with_pre_drop(800))
    rig.sweep(positions=list(range(0, 19_001, 200)) + [19_300, 19_500, 19_700,
                                                       19_900, 20_100, 20_300])
    [glide] = [w for w in rig.colour_writes() if w["kind"] == "glide"]
    assert glide["at"] == pytest.approx(19.3)
    assert glide["duration_ms"] == 700, "the time left to the drop, not 800"


def test_a_held_fade_leaves_the_drop_its_own_try(monkeypatch, show):
    """A fade that did not land (a hold at the pre-drop) is not remembered:
    the drop tries again — and lands, once the hold is gone."""
    monkeypatch.setattr(drop_firing, "PRE_DROPS_PLAY", True)
    _controls(scene_change_mode="analysed")
    _detect(drops=DROPS[:1])
    from spectra.services import house
    held = {"on": True}
    monkeypatch.setattr(house, "scene_deferral",
                        lambda: "resting" if held["on"] else None)
    rig = Show(monkeypatch, show, drop_view=_with_pre_drop(800))

    async def run():
        await rig.engine.on_track_state(URI)
        for pos in range(0, 21_001, 200):
            rig.now[0] = pos / 1000.0
            if pos == 19_600:
                held["on"] = False
            await rig.engine.tick(pos)
    asyncio.run(run())
    colour = rig.colour_writes()
    assert not [w for w in colour if w["kind"] == "glide"]
    [jump] = [w for w in colour if w["kind"] == "jump"]
    assert jump["at"] == pytest.approx(20.0)
    assert _room().active_set_id == "cyan"


def test_a_rewind_forgets_the_fade(monkeypatch, show):
    monkeypatch.setattr(drop_firing, "PRE_DROPS_PLAY", True)
    _controls(scene_change_mode="analysed")
    _detect(drops=DROPS[:1])
    rig = Show(monkeypatch, show, drop_view=_with_pre_drop(800))
    rig.sweep(positions=list(range(0, 21_001, 200)) + [10_000]
              + list(range(10_200, 21_001, 200)))
    glides = [w for w in rig.colour_writes() if w["kind"] == "glide"]
    assert len(glides) == 2, "approached again, the pre-drop fades again"


# ═══ 4. the settings ══════════════════════════════════════════════════════

def test_the_room_settings_and_their_bounds():
    from pydantic import ValidationError
    rc = RoomControlState()
    assert (rc.drop_colour_change, rc.drop_colour_spread_deg) == (True, 30.0)
    for bad in (4.0, 91.0):
        with pytest.raises(ValidationError):
            RoomControlState(drop_colour_spread_deg=bad)


def test_sonic_can_set_both(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import settings_console as sc
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "SETTINGS_LOG_FILE", tmp_path / "settings_log.json")
    assert sc.SETTINGS_REGISTRY["drop_colour_change"].kind == "bool"
    spec = sc.SETTINGS_REGISTRY["drop_colour_spread_deg"]
    assert (spec.min, spec.max) == (5.0, 90.0)
    _run(sc.apply_change("drop_colour_spread_deg", 20))
    from spectra.services.room_controls import load_room_controls
    assert load_room_controls().drop_colour_spread_deg == 20.0
    with pytest.raises(sc.SettingChangeError):
        _run(sc.apply_change("drop_colour_spread_deg", 120))


# ═══ 5. the Review page names it ═════════════════════════════════════════

REPO = Path(__file__).resolve().parent.parent
_ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(not _ESBUILD.exists() or __import__("shutil").which("node") is None,
                    reason="frontend toolchain (node + esbuild) not installed")
def test_the_review_page_names_the_drop_colour_change():
    """scripts/check_drop_colour_review.mjs drives the real describeEvent()
    with the entries the server writes; this runs it on every full test
    run."""
    import subprocess
    result = subprocess.run(
        ["node", str(REPO / "scripts" / "check_drop_colour_review.mjs")],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "PASS" in result.stdout
