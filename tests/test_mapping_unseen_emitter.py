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
"""
from __future__ import annotations

import asyncio

import numpy as np

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
        # The LIT step of whichever emitter is being measured decides what
        # the fake camera will see next: the far block paints nothing.
        if step == "lit":
            session.lit_value = 0.0 if UNSEEN in program.lit_virtual_ids else 0.5
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
