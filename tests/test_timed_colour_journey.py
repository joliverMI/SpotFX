"""The trigger-timed colour journey (the Admiral, 2026-09-26: "Shouldn't
[the drift engine] have a destination based on when the next trigger is
going to hit"; and, asked whether it should replace the untriggered
gradient, "yes, replace").

Proves:
  1. trigger_engine.next_colour_cue — the next colour/scene cue the song
     will fire on the show clock (authored song → his next scene/colour
     trigger; untriggered → the next analysed scene change, the planned
     ones standing in before auto-generation), None on a stale clock or at
     the end of the song;
  2. the conductor ARRIVES ON THE CUE: the last leg glides over exactly the
     time left, so the wheel lands at the cue time; arrival makes the
     destination the room's set and holds until the cue passes;
  3. no known cue → today's distance-paced walk, unchanged;
  4. the pace bounds, and the analysed colour jump agreeing with the walk
     (arrived → no jump; not arrived → the jump lands the walk's set);
  5. an untriggered song no longer engages any gradient; a manual gradient
     and force colour hold the timed walk exactly as they held the old one;
  6. the status exposes the destination, cue time and pace.

Every injectable is explicit; nothing touches real storage.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra.models.trigger import (FireResponseAction, FireSceneAction,
                                    SelectColorSetAction, SpectraTrigger)
from spectra.services import color_journey as cj
from spectra.services.midsong_generator import CandidateMoment
from spectra.services.room_controls import RoomControlState
from spectra.services.trigger_engine import NextCue, TriggerEngine
from tests.test_dynamic_colour_untriggered import (  # noqa: F401 (fixture)
    COLOURS, POSITIONS, Rig, _fake_colour_store, _scene)


def _run(coro):
    return asyncio.run(coro)


def _cue(at_ms, pos_ms, *, key="c1", set_id=None, intensity=0.7,
         kind="fire_scene", source="generated") -> NextCue:
    return NextCue(uri="u", key=key, at_ms=at_ms, position_ms=pos_ms,
                   kind=kind, source=source, intensity=intensity,
                   set_id=set_id)


def _palette_glides(rig):
    return [w for w in rig.executor.writes
            if w["kind"] == "glide" and "gradient" in w["params"]]


# ── 1. the next-cue horizon ─────────────────────────────────────────────────

class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _engine(triggers, *, mode="triggers_only", clock=None):
    return TriggerEngine(
        list_triggers=lambda uri: triggers,
        fire_scene=lambda *a: asyncio.sleep(0),
        fire_response=lambda *a: asyncio.sleep(0),
        select_scene=lambda i: None,
        scene_change_mode=lambda: mode, render_intensity=lambda r: r,
        sequencer_enabled=lambda: True, lead_ms=lambda t: 0,
        clock=clock or Clock(), rng=Random(1))


def _at(engine, uri, pos):
    async def go():
        await engine.on_track_state(uri)
        await engine.tick(pos)
    _run(go())


def test_authored_song_next_cue_is_his_next_scene_or_colour_trigger():
    triggers = [
        SpectraTrigger(id="gen", timestamp_ms=15_000, source="generated",
                       action=FireSceneAction(intensity=0.4)),
        SpectraTrigger(id="flare", timestamp_ms=12_000, source="authored",
                       action=FireResponseAction(event_class="flare",
                                                 intensity=0.9)),
        SpectraTrigger(id="scene", timestamp_ms=30_000, source="authored",
                       trigger_offset_ms=-500,
                       action=FireSceneAction(intensity=0.8)),
        SpectraTrigger(id="colour", timestamp_ms=20_000, source="authored",
                       action=SelectColorSetAction(set_id="blue")),
        SpectraTrigger(id="past", timestamp_ms=5_000, source="authored",
                       action=FireSceneAction(intensity=0.1)),
    ]
    engine = _engine(triggers)
    _at(engine, "u", 10_000)
    cue = engine.next_colour_cue()
    assert (cue.key, cue.kind, cue.set_id, cue.at_ms, cue.position_ms) == \
        ("colour", "select_color_set", "blue", 20_000, 10_000), \
        "flares and the generated cue (silenced under triggers_only) never count"
    _at(engine, "u", 20_500)
    cue = engine.next_colour_cue()
    assert (cue.key, cue.at_ms, cue.intensity) == ("scene", 29_500, 0.8), \
        "the trigger's own offset relocates the cue, as tick() does"
    _at(engine, "u", 31_000)
    assert engine.next_colour_cue() is None, "end of song: nothing ahead"


def test_untriggered_song_next_cue_is_the_next_analysed_scene_change():
    triggers = [SpectraTrigger(id=f"g{ts}", timestamp_ms=ts, source="generated",
                               action=FireSceneAction(intensity=ts / 100_000))
                for ts in (8_000, 16_000, 24_000)]
    engine = _engine(triggers)          # triggers_only → falls back to analysed
    _at(engine, "u", 9_000)
    cue = engine.next_colour_cue()
    assert (cue.key, cue.at_ms, cue.source) == ("g16000", 16_000, "generated")


def test_planned_scene_cues_stand_in_before_auto_generation_lands():
    engine = _engine([], mode="analysed")
    _at(engine, "u", 1_000)
    engine._flare_plan_uri = "u"
    engine._scene_cue_plan = [CandidateMoment(12_000, 0.6, "section:12000")]
    cue = engine.next_colour_cue()
    assert (cue.key, cue.at_ms, cue.source) == \
        ("planned:section:12000", 12_000, "planned")


def test_transitions_mode_has_no_timed_cue():
    triggers = [SpectraTrigger(timestamp_ms=16_000, source="generated",
                               action=FireSceneAction(intensity=0.5))]
    engine = _engine(triggers, mode="transitions")
    _at(engine, "u", 1_000)
    assert engine.next_colour_cue() is None


def test_a_stale_show_clock_times_nothing():
    clock = Clock()
    triggers = [SpectraTrigger(timestamp_ms=16_000, source="generated",
                               action=FireSceneAction(intensity=0.5))]
    engine = _engine(triggers, clock=clock)
    _at(engine, "u", 1_000)
    assert engine.next_colour_cue() is not None
    clock.t += 10.0                       # paused / bridge down
    assert engine.next_colour_cue() is None


def test_a_fired_colour_cue_notifies_the_journey():
    notified = []
    triggers = [SpectraTrigger(timestamp_ms=1_000, source="authored",
                               action=FireSceneAction(scene_id="s")),
                SpectraTrigger(timestamp_ms=2_000, source="authored",
                               action=FireResponseAction(event_class="flare"))]
    engine = _engine(triggers)
    engine._colour_cue = lambda: notified.append(True)

    async def go():
        await engine.on_track_state("u")
        for pos in range(0, 3_000, 200):
            await engine.tick(pos)
    _run(go())
    assert notified == [True], "the scene cue notifies; the flare does not"


# ── 2. arriving on the cue ──────────────────────────────────────────────────

class ShowClock:
    """Show-clock position and wall clock advance together (1:1)."""
    def __init__(self, start_ms=10_000):
        self.pos_ms = start_ms

    def advance(self, seconds):
        self.pos_ms += int(round(seconds * 1000))


def _timed_rig(cue_at_ms, clock: ShowClock, **cue_kw):
    rig = Rig(room=cj.RoomColorState(wheel_position_deg=0.0,
                                     active_set_id="red"))
    rig.conductor._next_cue = lambda: (
        _cue(cue_at_ms, clock.pos_ms, **cue_kw)
        if clock.pos_ms < cue_at_ms else None)
    rig.fire(_scene())
    return rig


def test_the_wheel_arrives_on_the_cue_time():
    clock = ShowClock(start_ms=10_000)
    cue_at = 45_000                                  # 35 s ahead: two legs
    rig = _timed_rig(cue_at, clock)

    rec1 = _run(rig.conductor.tick())
    dest = rig.room[0].destination
    assert dest.cue_key == "c1" and dest.cue_at_ms == cue_at
    travel = abs(cj.signed_travel(0.0, dest.position_deg))
    assert dest.pace_deg_per_min == pytest.approx(travel / (35 / 60))
    assert rec1["journey"]["duration_ms"] == 20_000
    assert not rec1["journey"]["arrived"]
    clock.advance(20.0)

    leg2_start_ms = clock.pos_ms
    rec2 = _run(rig.conductor.tick())
    j = rec2["journey"]
    assert j["arrived"] is True
    assert j["duration_ms"] == 15_000, "the last leg glides over the time left"
    arrival_ms = leg2_start_ms + j["duration_ms"]
    assert abs(arrival_ms - cue_at) <= 1, \
        "the wheel lands on the cue (well inside one leg's tolerance)"
    assert rig.room[0].wheel_position_deg == pytest.approx(dest.position_deg)
    assert rig.room[0].active_set_id == dest.set_id, \
        "arrival makes the destination the room's set (the cue's fire wears it)"
    last = _palette_glides(rig)[-1]
    assert last["duration_ms"] == 15_000

    # Before the cue passes: hold on the destination, no reselect, no writes.
    clock.advance(10.0)
    n = len(list(rig.executor.writes))
    rec3 = _run(rig.conductor.tick())
    assert rig.room[0].destination.cue_key == "c1"
    assert rec3["journey"]["wheel_position_deg"] == pytest.approx(
        dest.position_deg, abs=0.01)
    assert not any("gradient" in w["params"]
                   for w in list(rig.executor.writes)[n:]), "held, nothing rotates"


def test_a_cue_inside_one_leg_arrives_in_that_leg():
    clock = ShowClock(start_ms=10_000)
    rig = _timed_rig(22_000, clock)          # 12 s: 120° needs 600°/min
    rec = _run(rig.conductor.tick())
    assert rec["journey"]["arrived"] is True
    assert rec["journey"]["duration_ms"] == 12_000


def test_a_cue_naming_a_set_walks_to_that_set():
    clock = ShowClock()
    rig = _timed_rig(40_000, clock, set_id="blue", kind="select_color_set",
                     source="authored")
    _run(rig.conductor.tick())
    dest = rig.room[0].destination
    assert (dest.set_id, dest.rung) == ("blue", "cue_set")
    assert dest.position_deg == POSITIONS["blue"]


def test_the_cue_step_picks_the_next_horizon_at_once():
    clock = ShowClock(start_ms=10_000)
    cues = {"now": _cue(20_000, 10_000, key="first")}
    rig = Rig(room=cj.RoomColorState(wheel_position_deg=0.0,
                                     active_set_id="red"))
    rig.conductor._next_cue = lambda: cues["now"]
    rig.fire(_scene())
    _run(rig.conductor.tick())
    first = rig.room[0].destination
    assert first.cue_key == "first"
    # The first cue fires; the next one is 8 s out.
    cues["now"] = _cue(28_500, 20_500, key="second")
    rec = _run(rig.conductor.cue_step())
    second = rig.room[0].destination
    assert second.cue_key == "second" and second.cue_at_ms == 28_500
    assert second.set_id != rig.room[0].active_set_id
    assert rec["duration_ms"] == 8_000, "a cue closer than a leg: arrive on it"


# ── 3. the fallback ─────────────────────────────────────────────────────────

def test_no_known_cue_is_todays_distance_paced_walk():
    rig = Rig()
    rig.fire(_scene())
    rec = _run(rig.conductor.tick())
    dest = rig.room[0].destination
    assert dest.cue_key is None and rec["journey"].get("cue") is None
    travel = abs(cj.signed_travel(0.0, dest.position_deg))
    assert dest.pace_deg_per_min == pytest.approx(
        cj.destination_pace(rig.room[0].journey.degrees_per_min, travel))
    assert rec["journey"]["duration_ms"] == 20_000


def test_a_timed_destination_whose_cue_has_passed_walks_on_distance_paced():
    clock = ShowClock(start_ms=10_000)
    rig = _timed_rig(50_000, clock)
    _run(rig.conductor.tick())
    assert rig.room[0].destination.cue_key == "c1"
    clock.advance(45.0)                  # past the cue, nothing further known
    _run(rig.conductor.tick())
    dest = rig.room[0].destination
    assert dest is not None and dest.cue_key is None


# ── 4. pace bounds and the analysed colour jump ─────────────────────────────

def test_timed_pace_bounds():
    assert cj.timed_pace(180.0, 1.0) == cj.TIMED_PACE_MAX_DEG_PER_MIN
    assert cj.timed_pace(1.0, 600.0) == cj.TIMED_PACE_MIN_DEG_PER_MIN
    assert cj.timed_pace(60.0, 60.0) == pytest.approx(60.0)


def test_a_too_near_cue_goes_part_way_and_the_jump_lands_the_walks_set():
    clock = ShowClock(start_ms=10_000)
    rig = _timed_rig(11_000, clock)          # 1 s to cover ~120-240°
    rec = _run(rig.conductor.tick())
    dest = rig.room[0].destination
    assert dest.pace_deg_per_min == cj.TIMED_PACE_MAX_DEG_PER_MIN
    assert rec["journey"]["arrived"] is False
    # The cue's scene fire (a different scene) clears the bearing …
    rig.fire(_scene("Next"))
    assert rig.room[0].destination is None
    # … and the analysed colour jump lands the set the walk was heading for.
    record = _run(rig.responses.analysed_color_jump(0.7, 250))
    assert record["color_jump"]["picked_id"] == dest.set_id
    assert record["color_jump"]["rung"] == "journey_destination"
    assert rig.room[0].active_set_id == dest.set_id
    assert rig.executor.writes[-1]["params"]["gradient"] == COLOURS[dest.set_id]


def test_an_arrived_walk_is_the_cues_colour_moment_no_second_jump():
    clock = ShowClock(start_ms=10_000)
    rig = _timed_rig(25_000, clock)
    _run(rig.conductor.tick())
    dest_set = rig.room[0].active_set_id
    assert rig.room[0].destination.cue_key == "c1"
    assert dest_set != "red", "arrived and committed"
    rig.fire(_scene("Next"))
    n = len(rig.executor.writes)
    record = _run(rig.responses.analysed_color_jump(0.7, 250))
    assert record["held_for"] == "journey_arrived"
    assert rig.room[0].active_set_id == dest_set
    assert len(rig.executor.writes) == n


def test_without_a_timed_walk_the_jump_draws_as_before():
    rig = Rig()
    rig.fire(_scene())
    record = _run(rig.responses.analysed_color_jump(0.6, 250))
    assert record["result"] == "jumped"
    assert record["color_jump"]["rung"] != "journey_destination"


# ── 5. the gradient is replaced; manual gradient and force colour hold ─────

def test_an_untriggered_song_is_driven_by_the_timed_walk_not_a_gradient():
    clock = ShowClock()
    rig = _timed_rig(40_000, clock, source="generated")
    rec = _run(rig.conductor.tick())
    assert rec["gradient"] == {"active": False}
    assert rec["journey"].get("held_for") is None
    assert rig.room[0].destination.cue_key == "c1"
    assert rig.conductor.status()["journey"]["held_for"] is None


def test_a_manual_gradient_still_holds_the_journey():
    clock = ShowClock()
    rig = _timed_rig(40_000, clock)
    rig.controls = RoomControlState(active_gradient_id="t1")
    rec = _run(rig.conductor.tick())
    assert rec["journey"]["held_for"] == "gradient_drift"
    assert rec["gradient"]["gradient_id"] == "t1"
    assert rig.room[0].destination is None
    assert _run(rig.conductor.cue_step()) is None
    assert rig.conductor.status()["journey"]["held_for"] == "gradient_drift"


def test_force_colour_still_holds_the_journey():
    clock = ShowClock()
    rig = _timed_rig(40_000, clock)
    rig.controls = RoomControlState(force_color_enabled=True,
                                    force_color_target_id="blue")
    rec = _run(rig.conductor.tick())
    assert rec["journey"]["held_for"] == "force_color"
    assert rig.room[0].destination is None
    assert _run(rig.conductor.cue_step()) is None
    record = _run(rig.responses.analysed_color_jump(0.6, 250))
    assert record["held_for"] == "force_color"


# ── 6. status ───────────────────────────────────────────────────────────────

def test_status_exposes_destination_cue_time_and_pace():
    clock = ShowClock(start_ms=10_000)
    rig = _timed_rig(70_000, clock)
    _run(rig.conductor.tick())
    d = rig.conductor.status()["journey"]["destination"]
    assert d["timed"] is True
    assert d["cue_at_ms"] == 70_000 and d["cue_kind"] == "fire_scene"
    assert d["cue_in_s"] == pytest.approx(60.0)
    assert d["pace_deg_per_min"] > 0 and d["set_name"]
