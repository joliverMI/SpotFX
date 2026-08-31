"""AN EMITTER THE CAMERA NEVER SAW IS A RECORD, NOT AN ABSENCE.

The live gap this is written for (his first real map, 2026-08-31): 22
emitters ran and 14 footprints were stored. The missing 8 — far-side TV
blocks and sconce spill outside the frame — produced ~zero lit-minus-dark
and simply did not appear in `room_maps.json`. The physics was right and the
record was silent: nothing in the store distinguished "never ran" from "ran,
and its light is not in this shot".

What is proved here:

  * an emitter whose capture lands under `light_field.UNSEEN_WEIGHT` is
    STORED — footprint-less, `unseen=True`, with a sentence naming the
    emitter and the pose;
  * the run result carries it as `unseen` and the summary counts it beside
    the mapped ones ("1 mapped, 1 unseen from this pose");
  * an unseen record is INERT to every reader that already gates on
    `mapped`: it never becomes a driven emitter, and its weight never enters
    a gain;
  * the room's API payload renders a MIXED room — mapped and unseen side by
    side — so the page can show both;
  * the wording is a FACT, not a warning: nothing in it reads as an error,
    because a second pose can see this emitter later.

AND THE WEIGHT-ZERO RETRY (his own design, folded into the same work). His
real map's zero blocks are SCATTERED — 2, 3, 5, 8, 11, with SEEN neighbours
either side — which is not what "outside the frame" looks like and is
exactly what the previous emitter's WLED fade contaminating the next dark
reference looks like. So a ~zero emitter gets ONE more capture later in the
same run with a 3x dark settle before it is recorded unseen, and the stored
note then says which of the two findings it is. Proved below: the retry
RECOVERS a contaminated emitter, it happens exactly once, it does not
duplicate a row in any count, and a genuinely invisible emitter still ends
unseen — with the retried wording.
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from spectra.models.room_map import (AxisCalibration, EmitterFootprint, Point,
                                     RoomMap)
from spectra.services import light_field, mapping_refusals, room_mapping

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))
SEEN = "seen-carrier"
UNSEEN = "unseen-carrier"


def _virtual(device):
    return {"active": True, "pixel_count": 20, "config": {"grouping": 1},
            "segments": [[device, 0, 19, False]],
            "effect": {"type": "singleColor", "config": {}}}


class _Session:
    """The phone. One carrier lights the frame; the other paints nothing —
    the far-side block whose light never reaches the camera."""
    pose_id = "pose-7"
    run_abort = None

    class lock:
        exposure_locked = True
        white_balance_locked = True
        exposure_mode = "manual"
        white_balance_mode = "manual"

    def __init__(self):
        self.lit_value = 0.0
        self.dark_next = True
        self.current = SEEN

    def refusal(self):
        return None

    async def gather(self, seconds, min_frames=1):
        value = 0.0 if self.dark_next else self.lit_value
        self.dark_next = not self.dark_next
        grid = np.full((36, 64), value, dtype=np.float64)
        return [grid, grid], [10, 10]


def _deps(session):
    async def virtuals():
        return {SEEN: _virtual("lamp"), UNSEEN: _virtual("far-block")}

    async def chains():
        return {SEEN: [{"id": "lamp", "type": "wled"}],
                UNSEEN: [{"id": "far-block", "type": "wled"}]}

    async def open_hold(program, intensity, *, step="fire",
                        heartbeat_timeout_s=0.0):
        # Both steps name whose turn it is — the DARK step matters too,
        # because a contaminated dark reference belongs to the emitter about
        # to be measured, not the one before it.
        session.current = (UNSEEN if UNSEEN in program.lit_virtual_ids
                           else SEEN)
        # the far block paints nothing the camera can see
        session.lit_value = 0.0 if session.current == UNSEEN else 0.5
        return {"held": True}

    async def close_hold():
        return None

    async def sleep(_s):
        return None

    return room_mapping.RunDeps(
        session=session, get_virtuals=virtuals, carrier_devices=chains,
        open_hold=open_hold, close_hold=close_hold, sleep=sleep,
        spectra_owns=lambda: True)


def _run():
    room = RoomMap(name="Living room", carrier_ids=[SEEN, UNSEEN], axis=AXIS)
    session = _Session()
    result = asyncio.run(room_mapping.run_mapping(room, _deps(session),
                                                  granularity="whole"))
    return room, result


# ── 1. the run: stored, named, counted ─────────────────────────────────────

def test_an_unseen_emitter_is_stored_with_its_reason_and_counted():
    room, result = _run()

    seen = next(e for e in result.emitters if e.emitter_id == SEEN)
    unseen = next(e for e in result.emitters if e.emitter_id == UNSEEN)
    assert seen.mapped is True and seen.unseen is False
    # NOT mapped, and NOT a plain failure either — its own third state.
    assert unseen.mapped is False and unseen.unseen is True
    assert "No light seen from this pose" in unseen.reason
    assert "pose-7" in unseen.reason

    # (a) the summary counts both — "1 mapped" alone would hide the other.
    assert result.mapped_count == 1
    assert result.unseen_count == 1
    assert result.summary == "1 mapped, 1 unseen from this pose"
    assert result.as_dict()["summary"] == result.summary
    assert result.as_dict()["unseen_count"] == 1
    assert result.as_dict()["emitters"][1]["unseen"] is True

    # (b) STORED — the whole point. Before this it was simply absent.
    fp = room.footprint(UNSEEN)
    assert fp is not None
    assert fp.unseen is True
    assert fp.grid == [] and fp.axis_profile == []
    assert fp.note == unseen.reason
    assert fp.capture.pose_id == "pose-7"
    assert room.unseen_ids() == [UNSEEN]
    # a run with one real footprint in it is still a good run
    assert result.ok is True


def test_an_unseen_record_is_inert_to_every_reader_that_gates_on_mapped():
    room, _ = _run()
    assert room.mapped_ids() == [SEEN]
    assert room.mapped_carriers() == [SEEN]
    # the carrier nothing was seen of is still reported as not mapped, which
    # is what the page's "0/2 mapped" count reads
    assert room.unmapped_ids() == [UNSEEN]

    from spectra.services import room_effects
    driven = room_effects.resolve_driven(room, room_effects.RoomEffectSpec(room_id=room.id))
    assert [d.emitter_id for d in driven] == [SEEN]
    # and it contributes nothing to a gain, rather than a fabricated 1.0
    assert light_field.thumbnail(room.footprint(UNSEEN)) == []


def test_a_room_nothing_was_visible_in_says_so_rather_than_reading_broken():
    room = RoomMap(name="Dark corner", carrier_ids=[UNSEEN], axis=AXIS)
    session = _Session()
    result = asyncio.run(room_mapping.run_mapping(room, _deps(session),
                                                  granularity="whole"))
    assert result.ok is False
    assert result.unseen_count == 1
    assert "visible from where the phone was standing" in result.reason
    # still stored: he can see WHICH pieces were tried
    assert room.unseen_ids() == [UNSEEN]


# ── 2. the threshold, and the wording ──────────────────────────────────────

def test_the_threshold_is_a_named_constant_far_under_a_real_footprint():
    # The constant's own scale: ONE fully-lit grid cell out of 2304. What it
    # has to separate is "nothing at all" from a fixture genuinely in shot,
    # and the gap is enormous — a modest patch of light lands two orders of
    # magnitude above it, so the number never has to be tuned finely.
    assert light_field.UNSEEN_WEIGHT == 1.0
    lit = np.zeros((36, 64))
    lit[10:16, 20:32] = 120.0          # a small, dim patch of real light
    real = light_field.footprint_grid(np.zeros((36, 64)), lit)
    assert real.sum() > 20 * light_field.UNSEEN_WEIGHT
    # and a capture that added nothing is on the other side of it
    nothing = light_field.footprint_grid(np.full((36, 64), 4.0),
                                         np.full((36, 64), 4.0))
    assert nothing.sum() < light_field.UNSEEN_WEIGHT


def test_the_sentence_is_a_fact_not_a_warning():
    note = mapping_refusals.unseen_note("tv-mapper:blk3[90-119]", "pose-7")
    assert "tv-mapper:blk3[90-119]" in note and "pose-7" in note
    for alarm in ("fail", "error", "wrong", "⚠", "problem", "broken"):
        assert alarm not in note.lower()
    # it says what to do, like every other sentence on this path
    assert "photograph the room from somewhere that can see it" in note


# ── 3. the room's API payload renders a MIXED room ─────────────────────────

def test_the_api_payload_carries_mapped_and_unseen_side_by_side():
    from spectra.api import rooms as rooms_api
    room, _ = _run()
    # a hand-built third piece nobody has run yet, so all three states are
    # distinguishable in one payload
    room.carrier_ids.append("never-run")
    view = rooms_api._room_view(room)

    by_id = {f["emitter_id"]: f for f in view["footprints"]}
    assert by_id[SEEN]["mapped"] is True and by_id[SEEN]["unseen"] is False
    assert by_id[UNSEEN]["mapped"] is False and by_id[UNSEEN]["unseen"] is True
    assert "No light seen from this pose" in by_id[UNSEEN]["note"]
    assert by_id[UNSEEN]["thumbnail"] == []
    assert view["unseen_ids"] == [UNSEEN]
    assert view["mapped_ids"] == [SEEN]
    # "never-run" has no footprint at all: the third state stays distinct
    assert "never-run" not in by_id
    assert set(view["unmapped_ids"]) == {UNSEEN, "never-run"}


def test_a_hand_written_footprint_defaults_to_seen_so_stored_maps_are_unchanged():
    fp = EmitterFootprint(emitter_id="x", grid=[0.0] * (64 * 36), weight=5.0)
    assert fp.unseen is False and fp.note == ""


# ── 4. the weight-zero retry ───────────────────────────────────────────────

class _ContaminatedSession(_Session):
    """The suspected real cause, reproduced: the FIRST capture of one
    emitter has a dark reference still lit by its neighbour's dying fade, so
    lit - dark clips to nothing. The second attempt, taken after a longer
    dark settle, sees the emitter perfectly well."""

    def __init__(self):
        super().__init__()
        self.long_dark = False

    async def gather(self, seconds, min_frames=1):
        if self.dark_next:
            self.dark_next = False
            # The neighbour's fade is still arriving, so this emitter's dark
            # reference comes out BRIGHTER than its own light and the
            # difference clips to nothing — unless the settle was long
            # enough for the fade to finish.
            contaminated = self.current == SEEN and not self.long_dark
            grid = np.full((36, 64), 0.9 if contaminated else 0.0,
                           dtype=np.float64)
            return [grid, grid], [10, 10]
        self.dark_next = True
        grid = np.full((36, 64), self.lit_value, dtype=np.float64)
        return [grid, grid], [10, 10]


def _contaminated_deps(session, sleeps):
    deps = _deps(session)

    async def sleep(s):
        sleeps.append(round(s, 3))
        # the extended dark settle is what clears the neighbour's fade
        session.long_dark = s >= room_mapping.DARK_SETTLE_S * 2
        return None

    return room_mapping.RunDeps(
        session=session, get_virtuals=deps.get_virtuals,
        carrier_devices=deps.carrier_devices, open_hold=deps.open_hold,
        close_hold=deps.close_hold, sleep=sleep, spectra_owns=lambda: True)


def test_a_contaminated_dark_reference_is_recovered_by_the_retry():
    room = RoomMap(name="Living room", carrier_ids=[SEEN, UNSEEN], axis=AXIS)
    sleeps: list[float] = []
    session = _ContaminatedSession()
    result = asyncio.run(room_mapping.run_mapping(
        room, _contaminated_deps(session, sleeps), granularity="whole"))

    seen = next(e for e in result.emitters if e.emitter_id == SEEN)
    # the lamp read as nothing first time — its dark reference was polluted
    # — and MAPPED on the second, slower look
    assert seen.mapped is True
    assert seen.retried is True
    assert result.recovered_count == 1
    assert "on a second, slower look" in result.summary

    # the retry actually used a LONGER dark settle, not just another go
    assert max(sleeps) == pytest.approx(
        room_mapping.DARK_SETTLE_S * room_mapping.RETRY_DARK_SETTLE_X)

    # ONE row for one emitter, however many times it was measured
    assert len(result.emitters) == 2
    assert [e.emitter_id for e in result.emitters] == [SEEN, UNSEEN]
    # and the store never keeps both readings
    assert len([f for f in room.footprints if f.emitter_id == SEEN]) == 1
    assert room.footprint(SEEN).unseen is False
    assert room.footprint(SEEN).retried is True

    # said, not silent: the run took longer than the plan's estimate
    assert any("looked at once more" in n for n in result.notes)


def test_the_retry_happens_exactly_once_and_the_finding_says_so():
    room, result = _run()
    unseen = next(e for e in result.emitters if e.emitter_id == UNSEEN)
    assert unseen.retried is True          # it was given its second look
    assert unseen.unseen is True           # and still saw nothing
    fp = room.footprint(UNSEEN)
    assert fp.retried is True
    # the retried wording is a DIFFERENT finding: one alternative
    # explanation has been ruled out by measurement, and it says so
    assert "retried with an extended settle" in fp.note
    assert "measured twice" in fp.note
    assert fp.note != mapping_refusals.unseen_note(UNSEEN, "pose-7")
    # never a loop — one row, and the run is not still trying
    assert len([e for e in result.emitters if e.emitter_id == UNSEEN]) == 1


def test_the_retried_sentence_is_still_a_fact_not_a_warning():
    note = mapping_refusals.unseen_note("tv-mapper:blk5[120-149]", "pose-7",
                                        retried=True)
    for alarm in ("fail", "error", "wrong", "⚠", "problem", "broken"):
        assert alarm not in note.lower()
    assert "three times as long" in note


# ── 5. per-run settles, bounded ────────────────────────────────────────────

def test_the_settles_are_per_run_and_bounded():
    c = room_mapping.clamp_settle
    assert c(None, room_mapping.DARK_SETTLE_S) == room_mapping.DARK_SETTLE_S
    assert c("nonsense", 0.7) == 0.7
    assert c(float("nan"), 0.7) == 0.7
    # bounded both ways rather than refusing a run over a stray number
    assert c(999.0, 0.7) == room_mapping.MAX_SETTLE_S
    assert c(0.0, 0.7) == room_mapping.MIN_SETTLE_S
    assert c(2.5, 0.7) == 2.5


def test_an_override_reaches_the_protocol_and_is_reported():
    room = RoomMap(name="Living room", carrier_ids=[SEEN], axis=AXIS)
    sleeps: list[float] = []
    session = _Session()
    result = asyncio.run(room_mapping.run_mapping(
        room, _contaminated_deps(session, sleeps), granularity="whole",
        dark_settle_s=2.0, lit_settle_s=99.0))
    assert result.dark_settle_s == 2.0
    assert result.lit_settle_s == room_mapping.MAX_SETTLE_S    # bounded
    assert sleeps == [2.0, room_mapping.MAX_SETTLE_S]
    assert result.as_dict()["dark_settle_s"] == 2.0


def test_omitting_the_override_runs_exactly_the_shipped_protocol():
    room = RoomMap(name="Living room", carrier_ids=[SEEN], axis=AXIS)
    sleeps: list[float] = []
    result = asyncio.run(room_mapping.run_mapping(
        room, _contaminated_deps(_Session(), sleeps), granularity="whole"))
    assert sleeps == [room_mapping.DARK_SETTLE_S, room_mapping.LIT_SETTLE_S]
    assert result.dark_settle_s == room_mapping.DARK_SETTLE_S
    assert result.lit_settle_s == room_mapping.LIT_SETTLE_S


# ── 6. the fixture's own firmware brightness, end to end through a run ─────

class _WledHelper:
    def __init__(self, value=26):
        self.value = value
        self.writes: list[int] = []

    async def get_brightness(self):
        return self.value

    async def set_brightness(self, value):
        self.writes.append(int(value))
        self.value = int(value)


class _WledDevice:
    def __init__(self, device_id, helper):
        self.id = device_id
        self.type = "wled"
        self.wled = helper


def _brightness_deps(session, helper):
    base = _deps(session)

    async def chains():
        return {SEEN: [{"id": "lamp", "type": "wled"}],
                UNSEEN: [{"id": "far-block", "type": "wled"}]}

    async def fixtures():
        return [_WledDevice("lamp", helper)]

    async def sleep(_s):
        return None

    return room_mapping.RunDeps(
        session=session, get_virtuals=base.get_virtuals,
        carrier_devices=chains, open_hold=base.open_hold,
        close_hold=base.close_hold, sleep=sleep, spectra_owns=lambda: True,
        fixture_devices=fixtures)


def test_a_turned_down_fixture_is_warned_about_BEFORE_the_room_goes_dark():
    """The whole point of reading it at plan time: a warning that arrives
    after a four-minute dark-room run has arrived too late to act on."""
    room = RoomMap(name="Living room", carrier_ids=[SEEN], axis=AXIS)
    session = _Session()
    deps = _brightness_deps(session, _WledHelper(26))     # his real 10%

    async def go():
        scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
        return await room_mapping.resolve_plan(room, deps, scope, "whole", 30)

    plan = asyncio.run(go())
    assert plan.warnings and "TURNED DOWN" in plan.warnings[0]
    assert "lamp at 10%" in plan.warnings[0]
    # and the reading itself rides the plan, so the page can show it
    assert plan.brightness[0]["percent"] == 10
    assert plan.brightness[0]["low"] is True
    assert plan.as_dict()["brightness"] == plan.brightness


def test_the_run_takes_the_fixture_to_full_and_puts_his_level_back():
    room = RoomMap(name="Living room", carrier_ids=[SEEN], axis=AXIS)
    helper = _WledHelper(26)
    result = asyncio.run(room_mapping.run_mapping(
        room, _brightness_deps(_Session(), helper), granularity="whole"))

    assert result.ok is True
    # full for the capture, HIS level back afterwards — the own-the-flag
    # pattern activate_for_capture already uses for the `active` flag
    assert helper.writes == [255, 26]
    assert helper.value == 26
    assert any("put your own brightness back" in n for n in result.notes)
