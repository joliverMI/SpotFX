"""ONE CONTINUOUS DARK HOLD FOR THE WHOLE CAPTURE SEQUENCE.

His words, watching a real twenty-two-emitter run: "it seems like it keeps
releasing the lights to the music frequently... just stay dark between
tests." He was watching the mechanism work exactly as designed — the capture
was A CHAIN OF SHORT PER-EMITTER HOLDS, which is how it stayed inside
`flare_preview_hold.MAX_HOLD_DURATION_S` — and the design was wrong twice:
his show flooded back through the fixtures between every capture, and every
dark reference after the first was taken moments after a restore, so the
show fading back out landed IN the dark frame and subtracted the next
emitter's own light away.

What is proved here:

  * THE SEAM SEES ONE SNAPSHOT AND ONE RESTORE FOR N EMITTERS, and the run
    never hands the room back between two captures. Written to go RED
    against the chain it replaced — `test_the_chain_this_replaced_would_fail
    _this_bar` re-creates the per-emitter release and shows the same
    assertions failing, because a proof bar that cannot fail on the defect
    it was written for is decoration.
  * RESTORABLE AT ANY INSTANT SURVIVES: his Stop mid-run, and a run that
    dies without ever closing, both land the room back — the first through
    the run's own one release, the second through the hold's independent
    deadline and sweep, unchanged and still bounded by
    HEARTBEAT_TIMEOUT_S + SWEEP_INTERVAL_S.
  * THE CEILING IS RUN-SCOPED: derived from the plan's own estimate with a
    stated margin, floored, hard-capped, computed at plan time and CARRIED
    ON THE PLAN RESPONSE beside the emitter count; a plan past the hard cap
    REFUSES by name with nothing written, and never quietly maps fewer
    emitters. MAX_HOLD_DURATION_S is untouched and still governs previews.
  * A run never normalises his granularity or block size to make itself fit
    — those are HIS decisions and the plan's job is to price them.
"""
from __future__ import annotations

import asyncio

import numpy as np

from spectra.models.room_map import (AxisCalibration, Point, RoomMap)
from spectra.services import (emitters as em, flare_preview_hold,
                              mapping_refusals, room_mapping)

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))
CARRIERS = ["lamp-a", "lamp-b", "lamp-c", "lamp-d"]


def _virtual(device):
    return {"active": True, "pixel_count": 20, "config": {"grouping": 1},
            "segments": [[device, 0, 19, False]],
            "effect": {"type": "singleColor", "config": {}}}


class _Session:
    pose_id = "pose-1"
    run_abort = None

    class lock:
        exposure_locked = True
        white_balance_locked = True
        exposure_mode = "manual"
        white_balance_mode = "manual"

    def __init__(self):
        self.dark_next = True

    def refusal(self):
        return None

    async def gather(self, seconds, min_frames=1):
        value = 0.0 if self.dark_next else 0.5
        self.dark_next = not self.dark_next
        grid = np.full((36, 64), value, dtype=np.float64)
        return [grid, grid], [10, 10]


class _HoldLog:
    """The hold seam as the run sees it, counting the two acts that the
    chain used to perform N times: taking a snapshot (the first open of a
    session) and giving the room back."""

    def __init__(self):
        self.opens: list[tuple[str, float | None]] = []
        self.snapshots = 0
        self.restores = 0
        #: the write order as it happened, for the "never mid-run" check
        self.order: list[str] = []
        self._held = False

    async def open_hold(self, program, intensity, *, step="fire",
                        heartbeat_timeout_s=0.0, max_duration_s=None):
        self.opens.append((step, max_duration_s))
        if not self._held:
            self._held = True
            self.snapshots += 1
        self.order.append(step)
        return {"held": True}

    async def close_hold(self):
        if self._held:
            self._held = False
            self.restores += 1
            self.order.append("restore")
        return None


def _deps(session, hold: _HoldLog, *, abort_after: int | None = None):
    async def virtuals():
        return {c: _virtual(f"{c}-fixture") for c in CARRIERS}

    async def chains():
        return {c: [{"id": f"{c}-fixture", "type": "wled"}] for c in CARRIERS}

    async def sleep(_s):
        return None

    real_open = hold.open_hold

    async def open_hold(program, intensity, **kw):
        out = await real_open(program, intensity, **kw)
        if abort_after is not None and hold.order.count("lit") >= abort_after:
            session.run_abort = "He pressed Stop."
        return out

    return room_mapping.RunDeps(
        session=session, get_virtuals=virtuals, carrier_devices=chains,
        open_hold=open_hold, close_hold=hold.close_hold, sleep=sleep,
        spectra_owns=lambda: True)


def _run(hold, *, abort_after=None, **kw):
    room = RoomMap(name="Living room", carrier_ids=list(CARRIERS), axis=AXIS)
    session = _Session()
    result = asyncio.run(room_mapping.run_mapping(
        room, _deps(session, hold, abort_after=abort_after),
        granularity="whole", **kw))
    return room, result


# ── 1. ONE snapshot, ONE restore, for N emitters ──────────────────────────

def test_the_seam_sees_one_snapshot_and_one_restore_for_n_emitters():
    hold = _HoldLog()
    _room, result = _run(hold)

    assert result.ok is True
    assert len(result.emitters) == len(CARRIERS) == 4
    # THE BAR. Under the chain this replaced these were both 4.
    assert hold.snapshots == 1, "the show is read once, before anything is written"
    assert hold.restores == 1, "the room comes back once, at the end"
    # and it comes back LAST — never between two captures
    assert hold.order == ["dark", "lit"] * 4 + ["restore"]
    assert hold.order.index("restore") == len(hold.order) - 1


def test_the_chain_this_replaced_would_fail_this_bar():
    """The red proof: re-create the per-emitter release and watch the same
    assertions fail. A bar that cannot fail on the defect it was written
    for proves nothing."""
    hold = _HoldLog()
    room = RoomMap(name="Living room", carrier_ids=list(CARRIERS), axis=AXIS)
    session = _Session()
    deps = _deps(session, hold)
    inner = deps.open_hold

    async def chained(program, intensity, **kw):
        # the OLD shape: every emitter's hold released before the next opens
        if kw.get("step") == "dark" and hold.order and hold.order[-1] == "lit":
            await hold.close_hold()
        return await inner(program, intensity, **kw)

    deps.open_hold = chained
    asyncio.run(room_mapping.run_mapping(room, deps, granularity="whole"))

    assert hold.snapshots == 4 and hold.restores == 4, \
        "the chain really did snapshot and restore once per emitter"
    assert hold.order != ["dark", "lit"] * 4 + ["restore"]
    # and the restore landed BEFORE the next emitter's dark reference —
    # which is the contamination the rework closes
    assert hold.order.index("restore") < len(hold.order) - 1


# ── 2. restorable at any instant, both ways ───────────────────────────────

def test_his_stop_mid_run_lands_the_room_once_and_keeps_what_it_measured():
    hold = _HoldLog()
    _room, result = _run(hold, abort_after=2)

    assert result.ok is False
    assert result.refusal == "aborted"
    assert result.partial is True, "what it managed is kept"
    assert 0 < result.mapped_count < len(CARRIERS)
    # STOPPING IS HIS ACT — and it still hands the room back exactly once
    assert hold.restores == 1
    assert hold.order[-1] == "restore"


def test_a_run_that_dies_without_closing_is_still_bounded_by_the_hold():
    """The abandon path is the HOLD's, not the run's, and is untouched:
    nothing has to run for a deadline to lapse, and the independent sweep
    reverts it. Proved against the real module with a real (tiny) window
    rather than by inspecting the run."""
    async def scenario():
        reverted = []

        class _Seam:
            @staticmethod
            async def get_virtuals():
                return {"v1": {"active": True, "effect": {
                    "type": "singleColor", "config": {"color": "#3050ff"}}}}

            @staticmethod
            async def apply_writes(writes, *, transition_ms=0):
                reverted.append([w["virtual_id"] for w in writes])

        from spectra.services import fx_seam
        orig = (fx_seam.get_virtuals, fx_seam.apply_writes)
        fx_seam.get_virtuals = _Seam.get_virtuals
        fx_seam.apply_writes = _Seam.apply_writes
        try:
            program = room_mapping.MappingProgram(["v1"], ["v1"])
            held = await flare_preview_hold.open_program_hold(
                program, 1.0, step="dark", heartbeat_timeout_s=0.05,
                max_duration_s=600.0)
            assert held["held"] is True
            assert flare_preview_hold.active() is True
            await asyncio.sleep(0.08)          # the heartbeat lapses
            # the SWEEP, not the run, is what lands it
            assert await flare_preview_hold.sweep_once() is True
            assert flare_preview_hold.active() is False
            # a lapse is not the ceiling: nothing is locked against reopening
            assert flare_preview_hold.locked_until_reopen() is False
        finally:
            fx_seam.get_virtuals, fx_seam.apply_writes = orig
            await flare_preview_hold.close_hold()
        assert reverted and reverted[-1] == ["v1"]

    asyncio.run(scenario())


# ── 3. the run-scoped ceiling ─────────────────────────────────────────────

def test_the_ceiling_is_the_estimate_plus_a_stated_margin_floored_and_capped():
    m = room_mapping.RUN_CEILING_MARGIN
    floor = room_mapping.RUN_CEILING_FLOOR_S
    cap = room_mapping.RUN_CEILING_HARD_CAP_S

    # small run: the floor governs, and it is never below a preview's own
    assert room_mapping.run_ceiling_s(8.0) == floor
    assert floor == flare_preview_hold.MAX_HOLD_DURATION_S
    # ordinary run: the margin governs
    mid = (floor / m) + 60.0
    assert room_mapping.run_ceiling_s(mid) == round(mid * m, 1)
    # huge run: the hard cap governs
    assert room_mapping.run_ceiling_s(100_000.0) == cap
    # junk never produces a junk ceiling
    for bad in (None, "later", float("nan"), -5.0):
        assert room_mapping.run_ceiling_s(bad) == floor


def test_the_preview_ceiling_is_untouched_and_a_run_declares_its_own():
    assert flare_preview_hold.MAX_HOLD_DURATION_S == 180.0
    hold = _HoldLog()
    _room, result = _run(hold)
    asked = {d for _step, d in hold.opens}
    assert asked == {result.hold_ceiling_s}, \
        "every open of the run's hold asks for the run's own ceiling"
    assert result.hold_ceiling_s > 0


def test_a_run_past_the_hard_cap_refuses_at_plan_time_with_nothing_written():
    sentence = room_mapping.too_long_refusal(10_000.0)
    assert sentence and "Nothing was written" in sentence
    # THE SHAPE OF THE ANSWER: it names the cost and hands the choice back.
    # It must never propose (or perform) a coarser granularity on his
    # behalf — a surprising value is his decision, not an error.
    assert "map them in a second pass" in sentence

    room = RoomMap(name="Living room", carrier_ids=list(CARRIERS), axis=AXIS)
    session = _Session()
    hold = _HoldLog()
    deps = _deps(session, hold)
    orig_cap = room_mapping.RUN_CEILING_HARD_CAP_S
    try:
        room_mapping.RUN_CEILING_HARD_CAP_S = 1.0
        result = asyncio.run(room_mapping.run_mapping(room, deps,
                                                      granularity="whole"))
    finally:
        room_mapping.RUN_CEILING_HARD_CAP_S = orig_cap

    assert result.ok is False
    assert result.refusal == "too_long"
    assert "Nothing was written" in result.reason
    # NOTHING WRITTEN, and NO TRUNCATION: it did not map "as many as fit".
    assert hold.snapshots == 0 and hold.restores == 0 and hold.opens == []
    assert result.emitters == []
    # and his own choices are exactly as he made them — never normalised
    # or reset to make the run fit.
    assert result.granularity == "whole"
    assert result.block_pixels == em.DEFAULT_BLOCK_PIXELS


def test_the_plan_carries_the_ceiling_beside_the_emitter_count():
    plan = em.Plan(granularity="whole", block_pixels=30,
                   emitters=[em.Emitter(emitter_id=c, carrier_id=c, label=c,
                                        virtual_ids=[c])
                             for c in CARRIERS])
    body = plan.as_dict()
    assert body["count"] == 4
    assert body["estimated_seconds"] == plan.seconds
    assert body["hold_ceiling_seconds"] == room_mapping.run_ceiling_s(
        plan.seconds)
    assert body["too_long"] == ""
    # the check-before-the-cost surface says BOTH: how many, and how long
    # it may hold the room to do it
    assert body["hold_ceiling_seconds"] >= body["estimated_seconds"]


# ── 4. the estimate stopped charging for a restore that no longer happens ──

def test_the_estimate_charges_one_hold_for_the_run_not_one_per_emitter():
    one = room_mapping.run_estimate_s(1, 0.7, 0.5, 0.7, 1.5)
    two = room_mapping.run_estimate_s(2, 0.7, 0.5, 0.7, 1.5)
    per_emitter = round(two - one, 1)
    assert per_emitter == round(0.7 + 0.5 + 0.7 + 1.5 + em.STEP_OVERHEAD_S, 1)
    # the snapshot+revert is charged ONCE, not per emitter
    assert round(one - per_emitter, 1) == em.HOLD_OVERHEAD_S


# ── 5. the four waits are all real, bounded inputs ────────────────────────

def test_all_four_protocol_waits_are_per_run_and_bounded():
    hold = _HoldLog()
    _room, result = _run(hold, dark_settle_s=0.2, lit_settle_s=0.3,
                         dark_capture_s=0.3, lit_capture_s=0.6)
    assert (result.dark_settle_s, result.lit_settle_s) == (0.2, 0.3)
    assert (result.dark_capture_s, result.lit_capture_s) == (0.3, 0.6)

    # bounded, and junk falls back to the shipped protocol rather than
    # refusing a run or holding the room dark for a minute
    hold = _HoldLog()
    _room, result = _run(hold, dark_capture_s=0.0, lit_capture_s="fast")
    assert result.dark_capture_s == room_mapping.MIN_CAPTURE_S
    assert result.lit_capture_s == room_mapping.LIT_CAPTURE_S
    assert result.ok is True


def test_the_capture_window_is_the_frame_count_and_is_passed_through():
    """At the phone's fixed ~5 fps, `lit_capture_s` IS how many frames the
    average is built from — one knob, not two. Proved by watching what the
    session is actually asked for."""
    asked: list[float] = []

    class _Watching(_Session):
        async def gather(self, seconds, min_frames=1):
            asked.append(seconds)
            return await super().gather(seconds, min_frames=min_frames)

    room = RoomMap(name="Living room", carrier_ids=list(CARRIERS), axis=AXIS)
    hold = _HoldLog()
    session = _Watching()
    asyncio.run(room_mapping.run_mapping(
        room, _deps(session, hold), granularity="whole",
        dark_capture_s=0.4, lit_capture_s=0.9))

    assert asked == [0.4, 0.9] * 4, \
        "every capture window is the run's own, not the module constant"
