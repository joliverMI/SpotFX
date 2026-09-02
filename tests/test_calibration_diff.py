"""THE DIFF THAT MAKES AMENDMENTS LEGIBLE — what changed between two of a
calibration's own lineage entries, computed from stored data.

The plan's claim is that "two calibrations with the same fingerprint and
settings are comparable across time — which is what makes drift DETECTABLE
instead of arguable". This file is that claim under test, and the three
things it must never do are as important as the one it must:

  IT READS THE LINEAGE, not the room map — which only ever holds the LATEST
  footprint, so a diff against it could compare the newest reading only with
  itself.
  IT NEVER TREATS ABSENCE AS A CHANGE. An entry with no recorded
  measurements reports UNMEASURED, and an emitter one side did not measure
  is named as that rather than as a fixture that vanished.
  IT NEVER CLAIMS A COMPARISON THE RECORD DOES NOT SUPPORT. Two entries
  taken under different pinned regimes still get their numbers; what is
  withheld is the CLAIM.
  IT NEVER TUNES ITS THRESHOLD: `NOISE_FRACTION` is
  `exposure_test.TIE_FRACTION`, this instrument's own measured wobble.

Most of it is driven against real runs through the real chain (the same
synthetic camera the amendment tests use), because a diff built only from
hand-written records would prove the arithmetic and not the plumbing.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.models.calibration import (Calibration, CalibrationRun,
                                        EmitterMeasurement, ItemOutcomeRecord,
                                        KIND_FINGERPRINT, PinnedCamera)
from spectra.models.room_map import RoomMap
from spectra.services import (calibration_diff, calibration_runs,
                              calibration_store, capture_runs, exposure_test,
                              light_field, mapping_session, room_mapping)
from spectra.services.calibration_diff import (APPEARED, CAME_INTO_VIEW,
                                               LOST_SIGHT, MOVED, SAME,
                                               VANISHED)
from tests.test_pose_fingerprint import (AXIS, CARRIERS, SPREAD_ROOM, _Session,
                                         _deps)


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(calibration_runs, "SESSION_WAIT_S", 0.0)


def _wire(monkeypatch, session):
    monkeypatch.setattr(mapping_session, "current", session)
    monkeypatch.setattr(room_mapping, "production_deps",
                        lambda sess: _deps(session,
                                           save_room=light_field.put_room))
    return session


@pytest.fixture(autouse=True)
def _camera(monkeypatch):
    _wire(monkeypatch, _Session(SPREAD_ROOM))


def _room():
    return light_field.put_room(
        RoomMap(name="Lounge", carrier_ids=list(CARRIERS), axis=AXIS))


def _cal(room, camera=None):
    cal = Calibration(name="North shelf", room_id=room.id,
                      camera=camera or PinnedCamera(),
                      items=[{"kind": "map", "room_id": room.id,
                              "granularity": "whole", "carrier_ids": [c],
                              "label": c} for c in ("north", "east")])
    cal.pose.placement = "the north shelf"
    return calibration_store.save(cal)


def _run(cal, **kw):
    return asyncio.run(calibration_runs.run_calibration(cal, **kw))


def _amend(cal, names, **kw):
    return asyncio.run(calibration_runs.run_amendment(cal, names, **kw))


def _by_id(got):
    return {d.emitter_id: d for d in got.deltas}


# ── 1. it reads what the runs recorded ─────────────────────────────────────

def test_a_run_records_what_each_emitter_measured():
    """Without this the diff has nothing to read: the room map keeps only
    the latest footprint, so the earlier number has to live on the entry."""
    room = _room()
    cal = _cal(room)
    cal, entry = _run(cal)
    rows = {m.emitter_id: m for i in entry.items for m in i.measurements}
    assert set(rows) == {"north", "east"}
    assert all(m.mapped and m.weight > 0.0 for m in rows.values())
    assert rows["north"].carrier_id == "north"


def test_an_unchanged_room_reads_as_unchanged():
    """The negative control, and the reason a threshold is needed at all:
    two runs of the same room are never bit-identical."""
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)
    cal, second = _run(cal)
    got = calibration_diff.diff(cal, first.id, second.id)
    assert got.comparable
    assert {d.state for d in got.deltas} == {SAME}
    assert "2 unchanged" in got.summary


def test_a_fixture_that_dimmed_reads_as_moved_past_the_noise(monkeypatch):
    """A real change, measured through the real chain: one fixture at half
    its light, the other untouched. THE UNTOUCHED ONE MUST STAY `same` —
    a diff that fired on everything would be as useless as one that fired
    on nothing."""
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)
    _wire(monkeypatch, _Session(SPREAD_ROOM.dim("north", 0.5)))
    cal, second = _run(cal, force=True)

    got = calibration_diff.diff(cal, first.id, second.id)
    rows = _by_id(got)
    assert rows["north"].state == MOVED
    assert rows["north"].ratio == pytest.approx(0.5, abs=0.05)
    assert "down" in rows["north"].note
    assert rows["east"].state == SAME


def test_the_noise_band_is_the_instruments_own_and_not_a_second_number():
    """PRE-REGISTERED, and derived: `exposure_test.TIE_FRACTION` is this
    codebase's measured answer to "how much do two readings of the same
    regime differ". A second number here would be a second idea of the same
    instrument's noise."""
    assert calibration_diff.NOISE_FRACTION == exposure_test.TIE_FRACTION


def test_a_change_inside_the_noise_band_is_not_reported_as_drift():
    """Hand-built entries, because the synthetic camera cannot be nudged by
    5% on purpose — the arithmetic is what is under test here."""
    cal = _hand_built([("north", 100.0)], [("north", 104.0)])
    got = calibration_diff.diff(cal, cal.runs[0].id, cal.runs[1].id)
    assert _by_id(got)["north"].state == SAME
    cal = _hand_built([("north", 100.0)], [("north", 120.0)])
    assert _by_id(calibration_diff.diff(
        cal, cal.runs[0].id, cal.runs[1].id))["north"].state == MOVED


# ── 2. an amendment is exactly what the diff is for ────────────────────────

def test_an_amendment_shows_only_what_it_re_measured(monkeypatch):
    """The question a person asks after an amendment: did the thing I
    changed change? The fixture the amendment did not name is reported as
    NOT MEASURED THIS TIME, which is a different fact from a fixture that
    vanished — and the note says so."""
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)
    _wire(monkeypatch, _Session(SPREAD_ROOM.dim("north", 0.4)))
    cal, entry = _amend(cal, ["north"])

    got = calibration_diff.diff(cal, first.id, entry.id)
    rows = _by_id(got)
    assert rows["north"].state == MOVED
    assert rows["east"].state == VANISHED
    assert "measures only what it names" in rows["east"].note
    assert got.b_items == ["north"]


def test_the_default_pair_is_the_two_most_recent_measuring_entries():
    """What the route asks for when nothing is named — an amendment against
    whatever measured last before it. A pose entry sits between them here
    and must not be picked."""
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)
    cal, _pose = asyncio.run(calibration_runs.establish_pose(cal))
    cal, entry = _amend(cal, ["north"])
    runs = calibration_diff.measurable_runs(cal)
    assert [r.id for r in runs] == [first.id, entry.id]


# ── 3. absence is a read ───────────────────────────────────────────────────

def test_an_entry_with_no_recorded_measurements_reads_unmeasured():
    """A lineage entry written before measurements were recorded. Its
    emitters are UNMEASURED — never "nothing moved", which would read
    identically to a room that had not drifted."""
    cal = _hand_built([("north", 100.0)], [("north", 100.0)])
    cal.runs[0].items[0].measurements = []
    got = calibration_diff.diff(cal, cal.runs[0].id, cal.runs[1].id)
    assert _by_id(got)["north"].state == APPEARED
    assert "not measured by the earlier entry" in _by_id(got)["north"].note


def test_two_entries_with_nothing_in_common_say_so():
    cal = _hand_built([("north", 100.0)], [("east", 100.0)])
    got = calibration_diff.diff(cal, cal.runs[0].id, cal.runs[1].id)
    states = {d.emitter_id: d.state for d in got.deltas}
    assert states == {"north": VANISHED, "east": APPEARED}


def test_an_emitter_the_camera_stopped_seeing_is_named_as_that():
    """`unseen` is a recorded READING — "we drove it and saw nothing" — so
    it gets its own word rather than reading as a weight that fell to zero."""
    cal = _hand_built([("north", 100.0)], [("north", 0.0, True)])
    assert _by_id(calibration_diff.diff(
        cal, cal.runs[0].id, cal.runs[1].id))["north"].state == LOST_SIGHT
    cal = _hand_built([("north", 0.0, True)], [("north", 100.0)])
    assert _by_id(calibration_diff.diff(
        cal, cal.runs[0].id, cal.runs[1].id))["north"].state == CAME_INTO_VIEW


# ── 4. it never claims a comparison the record does not support ────────────

def test_a_changed_pinned_regime_withholds_the_claim_and_keeps_the_numbers():
    """Two regimes are two scales. The numbers are still reported —
    withholding a measurement he asked for teaches him nothing — and the
    claim is not made."""
    cal = _hand_built([("north", 100.0)], [("north", 200.0)])
    cal.runs[1].camera = {"pinned": PinnedCamera(gain=4).model_dump()}
    got = calibration_diff.diff(cal, cal.runs[0].id, cal.runs[1].id)
    assert not got.comparable
    assert "gain" in got.comparable_note
    assert _by_id(got)["north"].after == 200.0
    assert got.comparable_note in got.summary


def test_an_entry_that_never_claimed_comparability_is_named():
    cal = _hand_built([("north", 100.0)], [("north", 100.0)])
    cal.runs[1].comparable = False
    cal.runs[1].comparable_note = "the camera has moved."
    got = calibration_diff.diff(cal, cal.runs[0].id, cal.runs[1].id)
    assert not got.comparable
    assert cal.runs[1].id in got.comparable_note


def test_a_pose_entry_is_not_a_side_of_a_comparison():
    """It took a pose and measured nothing, so there is nothing in it to
    compare. Refused by name rather than rendered as a page of nothing."""
    cal = _hand_built([("north", 100.0)], [("north", 100.0)])
    cal.runs.append(CalibrationRun(kind=KIND_FINGERPRINT, status="ok"))
    got = calibration_diff.diff(cal, cal.runs[0].id, cal.runs[2].id)
    assert "measured nothing" in got.refusal
    assert not got.deltas


def test_an_unknown_entry_is_refused_and_names_the_ones_there_are():
    cal = _hand_built([("north", 100.0)], [("north", 100.0)])
    got = calibration_diff.diff(cal, "nope", cal.runs[1].id)
    assert "no lineage entry nope" in got.refusal
    assert cal.runs[0].id in got.refusal


def test_a_refused_run_is_never_offered_as_a_side():
    """A refused run is a real lineage entry with no numbers in it."""
    cal = _hand_built([("north", 100.0)], [("north", 100.0)])
    cal.runs.append(CalibrationRun(kind="run", status="refused",
                                   detail="the room is released"))
    assert [r.id for r in calibration_diff.measurable_runs(cal)] == [
        cal.runs[0].id, cal.runs[1].id]


# ── helpers ────────────────────────────────────────────────────────────────

def _hand_built(before, after) -> Calibration:
    """Two comparable lineage entries carrying the given weights. Used only
    where the arithmetic is what is under test — everything about the
    plumbing is driven through the real chain above."""
    cal = Calibration(name="hand", room_id="room")
    for rows in (before, after):
        cal.append_run(CalibrationRun(
            kind="run", status="ok", comparable=True,
            camera={"pinned": PinnedCamera().model_dump()},
            items=[ItemOutcomeRecord(
                index=0, name="item 1", status="ok",
                emitters=[r[0] for r in rows],
                measurements=[EmitterMeasurement(
                    emitter_id=r[0], carrier_id=r[0], label=r[0],
                    weight=r[1], mapped=not (len(r) > 2 and r[2]),
                    unseen=bool(len(r) > 2 and r[2])) for r in rows])]))
    return cal
