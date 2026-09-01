"""THE CONTAMINATION RE-TAKE, on the real mapping run.

WHAT IS ACTUALLY BEING PROTECTED: a footprint is `lit - dark` in one
camera's own byte scale. A house light coming on between those two frames is
measured as the fixture's own light and nothing downstream can tell the
difference — the same class of failure the exposure lock and the
firmware-brightness guard each refuse, arriving by a door this instrument
could not see through until River's witness existed.

Driven through the REAL `room_mapping.run_mapping` with the same fake seams
`tests/test_mapping_one_dark_hold.py` uses, so the pass structure, the hold
accounting and the retry-in-place semantics under test are production's.
"""
from __future__ import annotations

import asyncio

import numpy as np

from spectra.models.room_map import AxisCalibration, Point, RoomMap
from spectra.services import room_mapping, witness

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))
CARRIERS = ["lamp-a", "lamp-b", "lamp-c"]


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


class _Wall:
    """A wall clock that advances one second per read, so every capture gets
    a real, ordered, non-overlapping window to be judged against."""

    def __init__(self):
        self.now = 1_700_000_000.0

    def __call__(self):
        self.now += 1.0
        return self.now


async def _open_hold(program, intensity, **kw):
    return {"held": True}


async def _close_hold():
    return None


def _deps(session, wall, *, witness_fn=None, sweep_fn=None):
    async def virtuals():
        return {c: _virtual(f"{c}-fixture") for c in CARRIERS}

    async def chains():
        return {c: [{"id": f"{c}-fixture", "type": "wled"}] for c in CARRIERS}

    async def sleep(_s):
        return None

    return room_mapping.RunDeps(
        session=session, get_virtuals=virtuals, carrier_devices=chains,
        open_hold=_open_hold, close_hold=_close_hold, sleep=sleep,
        spectra_owns=lambda: True, wall=wall,
        witness=witness_fn, witness_sweep=sweep_fn)


def _map(*, witness_fn=None, sweep_fn=None):
    room = RoomMap(name="Living room", carrier_ids=list(CARRIERS), axis=AXIS)
    wall = _Wall()
    result = asyncio.run(room_mapping.run_mapping(
        room, _deps(_Session(), wall, witness_fn=witness_fn,
                    sweep_fn=sweep_fn),
        granularity="whole"))
    return result


def _row(entity, at_ts):
    return witness.ChangeRow(entity_id=entity, at_ts=at_ts,
                             at=witness.iso(at_ts))


# ── NO WITNESS WIRED: byte-identical to before this existed ────────────────

def test_with_no_witness_wired_nothing_changes_and_nothing_claims_clean():
    """An unconfigured host runs exactly as it did before this feature.
    Every capture is recorded UNCLAIMED — which is not clean, and never
    renders as it."""
    result = _map()
    assert result.ok is True
    assert result.mapped_count == len(CARRIERS)
    assert result.witness_counts == {"clean": 0, "contaminated": 0,
                                     "unclaimed": len(CARRIERS)}
    assert all(e.witness == {} for e in result.emitters)
    # The window is recorded even with nobody to ask: a window nobody asked
    # about is still the window somebody may ask about later.
    assert all(e.ended_at > e.started_at > 0 for e in result.emitters)


# ── THE IMMEDIATE PER-WINDOW QUERY ─────────────────────────────────────────

def test_every_capture_is_asked_about_immediately_with_its_own_window():
    asked: list[tuple[float, float]] = []

    async def ask(start, end):
        asked.append((start, end))
        return witness.judge([], [], start, end).as_dict()

    result = _map(witness_fn=ask)
    assert len(asked) == len(CARRIERS)
    # Each window is that emitter's own, in order, and they do not overlap.
    windows = [(e.started_at, e.ended_at) for e in result.emitters]
    assert asked == windows
    assert all(a[1] <= b[0] for a, b in zip(windows, windows[1:]))
    assert result.witness_counts == {"clean": 3, "contaminated": 0,
                                     "unclaimed": 0}


def test_no_settle_is_added_for_the_witness():
    """River's binding instruction: the dark time stays flat. The query is a
    round trip that overlaps the next capture's own settle; it must never
    become a wait the room sits through."""
    slept: list[float] = []

    async def ask(start, end):
        return witness.judge([], [], start, end).as_dict()

    room = RoomMap(name="Living room", carrier_ids=list(CARRIERS), axis=AXIS)

    async def sleep(seconds):
        slept.append(seconds)

    deps = _deps(_Session(), _Wall(), witness_fn=ask)
    deps.sleep = sleep
    asyncio.run(room_mapping.run_mapping(room, deps, granularity="whole"))
    with_witness = sorted(slept)

    slept.clear()
    deps2 = _deps(_Session(), _Wall())
    deps2.sleep = sleep
    room2 = RoomMap(name="Living room", carrier_ids=list(CARRIERS), axis=AXIS)
    asyncio.run(room_mapping.run_mapping(room2, deps2, granularity="whole"))

    assert with_witness == sorted(slept), \
        "the witness added time to the dark room"


# ── DISCARD AND RE-TAKE ────────────────────────────────────────────────────

def test_a_contaminated_capture_is_discarded_and_taken_again():
    """The first capture of `lamp-a` happens while a house light changes;
    it is re-taken, and the re-take REPLACES it in place (an emitter
    measured twice is still one emitter)."""
    seen: list[float] = []

    async def ask(start, end):
        seen.append(start)
        # Only the FIRST window is contaminated. Its re-take, later in wall
        # time, comes back clean.
        rows = [_row("light.hallway", start + 0.5)] if len(seen) == 1 else []
        return witness.judge(rows, [], start, end).as_dict()

    result = _map(witness_fn=ask)

    # 3 emitters + 1 re-take = 4 captures asked about.
    assert len(seen) == len(CARRIERS) + 1
    assert len(result.emitters) == len(CARRIERS), \
        "the re-take was appended instead of replacing its first result"
    retaken = [e for e in result.emitters if e.retried]
    assert len(retaken) == 1
    assert retaken[0].witness["status"] == witness.VERDICT_CLEAN
    assert result.witness_counts["contaminated"] == 0
    assert any("changed light" in n for n in result.notes)


def test_the_settled_sweep_catches_a_late_row_and_re_takes_that_capture():
    """A row that arrives after the immediate query still indicts the
    capture it overlaps, and that capture is taken again."""
    asked: list[tuple[float, float]] = []
    sweeps: list[tuple[float, float]] = []

    async def ask(start, end):
        asked.append((start, end))
        return witness.judge([], [], start, end).as_dict()

    async def sweep(start, end):
        sweeps.append((start, end))
        if len(sweeps) > 1:
            return [], set()
        # A row landing inside the SECOND capture's window, reported late.
        mid = asked[1][0] + 0.5
        return [_row("light.hallway", mid)], set()

    result = _map(witness_fn=ask, sweep_fn=sweep)

    assert len(sweeps) == 1, "the settled sweep is ONE query over the span"
    # Over the whole span of the captures taken SO FAR — asked[3] is the
    # re-take, which happens after the sweep by construction.
    assert sweeps[0][0] == asked[0][0]
    assert sweeps[0][1] >= asked[len(CARRIERS) - 1][1]
    retaken = [e for e in result.emitters if e.retried]
    assert len(retaken) == 1
    assert retaken[0].emitter_id == result.emitters[1].emitter_id


def test_the_re_take_never_loops():
    """ONE re-take, never a loop — the unseen retry's own rule. A second
    contamination is an answer about the evening (somebody is up), not a
    reason to keep his room dark until it stops."""
    asked = []

    async def ask(start, end):
        asked.append(start)
        # EVERY window is contaminated, forever.
        return witness.judge([_row("light.hallway", start + 0.5)], [],
                             start, end).as_dict()

    result = _map(witness_fn=ask)
    assert len(asked) == len(CARRIERS) * 2, \
        "the contamination re-take ran more than once"
    assert result.witness_counts["contaminated"] == len(CARRIERS)
    assert "still reading as taken while the house changed light" in \
        result.summary


# ── UNAVAILABLE MARKS, NEVER DISCARDS, NEVER KILLS ─────────────────────────

def test_an_unavailable_witness_keeps_every_capture_and_claims_nothing():
    """River's instruction, and it is the right way round: a witness outage
    is a fact about the witness, not about the room."""
    async def ask(start, end):
        return witness.unavailable(RuntimeError("no route"),
                                   start, end).as_dict()

    result = _map(witness_fn=ask)
    assert result.ok is True
    assert result.mapped_count == len(CARRIERS)
    assert not any(e.retried for e in result.emitters), \
        "an unavailable witness triggered a re-take"
    assert result.witness_counts == {"clean": 0, "contaminated": 0,
                                     "unclaimed": len(CARRIERS)}
    assert all(e.witness["status"] == witness.VERDICT_UNAVAILABLE
               for e in result.emitters)


def test_a_witness_that_raises_never_ends_a_run():
    async def ask(start, end):
        raise RuntimeError("the client blew up")

    result = _map(witness_fn=ask)
    assert result.ok is True
    assert result.mapped_count == len(CARRIERS)
    assert result.witness_counts["unclaimed"] == len(CARRIERS)


def test_the_result_carries_the_counts_for_the_exit_report():
    async def ask(start, end):
        return witness.judge([], [], start, end).as_dict()

    body = _map(witness_fn=ask).as_dict()
    assert body["witness"] == {"clean": 3, "contaminated": 0, "unclaimed": 0}
