"""AMEND-IN-PART — the gate that decides whether a partly re-measured
carrier is honest, proven in BOTH directions.

The point of this step is that changing one fixture stops costing an
evening. The price of that cheapness is that a carrier can end up holding
footprints from two different nights, and a footprint is `lit - dark` in one
camera's own view and one camera's own brightness scale — so the whole
build stands or falls on one question: WHEN MAY THOSE TWO READINGS SIT SIDE
BY SIDE? `spectra/services/amendment.py` is the binding statement; this file
is its proof.

  IT MIXES AND SAYS SO when the pose MATCHED and the pinned regime is
  identical — and supersedes EXACTLY the emitters it re-measured, leaving
  the rest still credited to the run that took them.
  IT REFUSES BY NAME, spending nothing, when the pose cannot vouch for the
  camera, when the regime differs, when the kept footprints were not this
  calibration's to begin with, and when mixing would put two granularities
  on one carrier.
  FORCE NEVER REACHES THE MIXING GATE, unlike the pose gate on a full run.
  AN EDIT TO THE DECLARATION KEEPS THE PRIOR ONE and touches no measurement.
  THE NEVER-TAKES-HIS-ROOM BOUNDARY IS UNMOVED: a released room refuses and
  the refusal is an entry.

The run half drives the REAL chain — `capture_runs.run_map` through
`room_mapping.run_mapping` through the real footprint arithmetic — against
the synthetic camera `tests/test_pose_fingerprint.py` builds. Nothing here
touches a room, a light or a webcam.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.models.calibration import (KIND_AMENDMENT, KIND_DECLARATION,
                                        KIND_RUN, Calibration, PinnedCamera,
                                        declaration_snapshot)
from spectra.models.room_map import RoomMap
from spectra.services import (amendment, calibration_runs, calibration_store,
                              capture_runs, fx_seam, light_field,
                              mapping_refusals, mapping_session, room_mapping)
from spectra.services import pose_fingerprint as pf
from tests.test_pose_fingerprint import (AXIS, CARRIERS, SPREAD_ROOM, _Session,
                                         _deps)

#: The declaration these tests amend: one item per carrier, mapped in blocks
#: of ten pixels, so every carrier has TWO emitters and a partial re-take is
#: a real thing rather than a synonym for a whole one.
BLOCKS = {"north": ["north:blk0[0-9]", "north:blk1[10-19]"],
          "east": ["east:blk0[0-9]", "east:blk1[10-19]"]}


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(calibration_runs, "SESSION_WAIT_S", 0.0)


@pytest.fixture(autouse=True)
def _camera(monkeypatch):
    """A connected, locked, native camera looking at the unchanged room, for
    every test. A test that wants a MOVED camera or a CHANGED room re-wires
    with `_wire` — the point being that the ordinary case needs no setup and
    the interesting ones are visible."""
    _wire(monkeypatch, _Session(SPREAD_ROOM))


def _room():
    return light_field.put_room(
        RoomMap(name="Lounge", carrier_ids=list(CARRIERS), axis=AXIS))


def _wire(monkeypatch, session):
    monkeypatch.setattr(mapping_session, "current", session)
    monkeypatch.setattr(room_mapping, "production_deps",
                        lambda sess: _deps(session,
                                           save_room=light_field.put_room))
    return session


def _items(room):
    """One declared item per carrier, at block granularity."""
    return [{"kind": "map", "room_id": room.id, "granularity": "block",
             "block_pixels": 10, "carrier_ids": [c], "label": c}
            for c in ("north", "east")]


def _cal(room, *, items=None, camera=None, name="North shelf"):
    cal = Calibration(name=name, room_id=room.id,
                      camera=camera or PinnedCamera(),
                      items=items if items is not None else _items(room))
    cal.pose.placement = "the north shelf"
    return calibration_store.save(cal)


def _run(cal, **kw):
    return asyncio.run(calibration_runs.run_calibration(cal, **kw))


def _amend(cal, names, **kw):
    return asyncio.run(calibration_runs.run_amendment(cal, names, **kw))


def _origins(cal):
    return cal.emitter_origin()


# ── 1. a subset runs, and supersedes exactly what it measured ──────────────

def test_an_amendment_runs_only_what_it_names():
    """The whole point: one fixture without the evening. The item it did not
    name is never even started, so the room's dark time is spent on what he
    asked for."""
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)
    assert first.status == capture_runs.STATUS_OK
    assert sorted(first.emitters) == sorted(BLOCKS["north"] + BLOCKS["east"])

    cal, entry = _amend(cal, ["north"])
    assert entry.kind == KIND_AMENDMENT
    assert entry.status == capture_runs.STATUS_OK
    assert entry.amended == ["north"]
    assert [i.name for i in entry.items] == ["north"]
    assert sorted(entry.emitters) == sorted(BLOCKS["north"])


def test_supersession_is_per_emitter_and_the_rest_keep_their_own_run():
    """A carrier's untouched footprints stay, and the record still says
    which run each one came from. Provenance is a READ, so it is asked of
    the store rather than of the entry that wrote it."""
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)
    cal, entry = _amend(cal, ["north"])

    origin = _origins(cal)
    for emitter_id in BLOCKS["north"]:
        assert origin[emitter_id] == entry.id
        assert entry.superseded[emitter_id] == first.id
    for emitter_id in BLOCKS["east"]:
        assert origin[emitter_id] == first.id
        assert emitter_id not in entry.superseded

    prov = calibration_store.provenance(cal)
    states = {(r["emitter_id"], r["run_id"]): r["state"] for r in prov["emitters"]}
    assert states[(BLOCKS["north"][0], first.id)] == calibration_store.SUPERSEDED
    assert states[(BLOCKS["north"][0], entry.id)] == calibration_store.PRESENT
    assert states[(BLOCKS["east"][0], first.id)] == calibration_store.PRESENT


def test_the_room_map_keeps_the_untouched_footprints_unchanged():
    """Not just the record — the MAP. The amended emitters carry the new
    reading and the rest are byte-identical to what the first run left."""
    room = _room()
    cal = _cal(room)
    cal, _first = _run(cal)
    before = {f.emitter_id: f.model_dump()
              for f in light_field.get_room(room.id).footprints}

    _amend(cal, ["north"])
    after = {f.emitter_id: f.model_dump()
             for f in light_field.get_room(room.id).footprints}
    assert set(after) == set(before)
    for emitter_id in BLOCKS["east"]:
        assert after[emitter_id] == before[emitter_id]


# ── 2. mixing, allowed — and never silent ──────────────────────────────────

def test_a_matching_amendment_mixes_within_one_carrier_and_says_so(monkeypatch):
    """Re-measure ONE BLOCK of a carrier and keep its sibling. The pose
    matched and the regime is identical, so the two readings are in one
    scale — and the entry names the carrier that now holds two nights'
    work rather than leaving it to be discovered."""
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)

    cal, entry = _amend(cal, ["north"], overrides={
        "emitter_ids": [BLOCKS["north"][0]]})
    assert entry.status == capture_runs.STATUS_OK
    assert entry.emitters == [BLOCKS["north"][0]]
    assert entry.mixed_carriers == ["north"]
    assert any("more than one run" in n for n in entry.notes)

    origin = _origins(cal)
    assert origin[BLOCKS["north"][0]] == entry.id
    assert origin[BLOCKS["north"][1]] == first.id


def test_an_amendment_that_mixes_nothing_never_meets_the_gate(monkeypatch):
    """The common case, and the reason the gate is not a tax: re-taking a
    whole carrier leaves no second reading to be inconsistent with, so the
    pose does not have to vouch for anything. Proven with a pose that
    CANNOT vouch — the run still happens."""
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    cal = _cal(room)
    cal, _first = _run(cal)
    _wire(monkeypatch, _Session(SPREAD_ROOM.move_one("north", 0.2, 0.0)))

    cal, entry = _amend(cal, ["north"])
    assert entry.fingerprint["verdict"] != mapping_refusals.POSE_MATCH
    assert entry.status == capture_runs.STATUS_OK
    assert entry.mixed_carriers == []


# ── 3. mixing, refused — by name, having spent nothing ─────────────────────

def _partial(cal, **kw):
    return _amend(cal, ["north"],
                  overrides={"emitter_ids": [BLOCKS["north"][0]]}, **kw)


def test_a_pose_that_cannot_vouch_for_the_camera_refuses_the_mix(monkeypatch):
    """`cannot_tell` does not stop a FULL run — a rearranged room must not
    expire a calibration. It stops a MIX, because a full run replaces the
    whole carrier and only its claim against earlier runs is withheld, where
    a mixed carrier's inconsistency is inside its own footprints."""
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)
    _wire(monkeypatch, _Session(SPREAD_ROOM.move_one("north", 0.2, 0.0)))

    cal, entry = _partial(cal)
    assert entry.status == capture_runs.STATUS_REFUSED
    assert entry.refusal == "would_mix"
    assert "north" in entry.detail
    # THE GATE'S OWN WORKING IS ON THE RECORD, not only its answer: which
    # carrier would have mixed, and which emitters it was going to take.
    assert entry.mix["carriers"] == ["north"]
    assert entry.mix["kept"] == {"north": [BLOCKS["north"][1]]}
    # THE TWO WAYS OUT, named in the sentence — a refusal that only says no
    # turns a five-minute amendment back into the whole evening.
    assert "whole carrier" in entry.detail
    assert "re-anchor the pose" in entry.detail
    # NOTHING WAS RUN: the first run still owns every footprint.
    assert set(_origins(cal).values()) == {first.id}


def test_a_changed_pinned_regime_refuses_the_mix():
    """The other half of the comparability rule, and it fails ON ITS OWN:
    the camera has not moved — the pose check says MATCH — and two pinned
    regimes are still two brightness scales.

    The lever changed here is GAIN rather than integration time, precisely
    so the pose half stays clean: this camera's light follows its commanded
    exposure (as an honest sensor must), so re-pinning that would move every
    anchor's weight at once and the pose would fail first, proving the wrong
    thing."""
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)

    cal.camera = PinnedCamera(gain=4)
    calibration_store.save(cal)
    cal, entry = _partial(cal)
    assert entry.fingerprint["verdict"] == mapping_refusals.POSE_MATCH
    assert entry.status == capture_runs.STATUS_REFUSED
    assert entry.refusal == "would_mix"
    assert "gain" in entry.detail
    assert set(_origins(cal).values()) == {first.id}


def test_footprints_this_calibration_never_produced_refuse_the_mix():
    """A carrier mapped from the Rooms page button carries no pose and no
    regime this record knows, so "the camera had not moved since" is not
    something anybody can say about it. Unknown provenance is the same
    answer as `cannot_tell`, and for the same reason."""
    room = _room()
    cal = _cal(room)
    # A REAL pose, so the pose half of the gate passes and the failure under
    # test is the provenance one on its own.
    cal, pose = asyncio.run(calibration_runs.establish_pose(cal))
    assert pose.status == capture_runs.STATUS_OK
    # The map exists; this calibration did not make it — the Rooms page
    # button, one seam over.
    asyncio.run(capture_runs.run_map(room.id, granularity="block",
                                     block_pixels=10))

    cal, entry = _partial(cal)
    assert entry.fingerprint["verdict"] == mapping_refusals.POSE_MATCH
    assert entry.status == capture_runs.STATUS_REFUSED
    assert entry.refusal == "would_mix"
    assert "was not measured by this calibration" in entry.detail


def test_force_never_runs_past_the_mixing_gate(monkeypatch):
    """`force` wins over the pose gate on a full run — an explicit press
    costs a comparability claim the record then names. It must NOT win here,
    where it would cost a carrier whose own footprints disagree with each
    other and nothing downstream could tell."""
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)
    _wire(monkeypatch, _Session(SPREAD_ROOM.shift(0.25, 0.0)))

    cal, entry = _partial(cal, force=True)
    assert entry.fingerprint["verdict"] == mapping_refusals.POSE_CAMERA_MOVED
    assert entry.status == capture_runs.STATUS_REFUSED
    assert entry.refusal == "would_mix"
    assert set(_origins(cal).values()) == {first.id}


def test_whole_carrier_is_the_named_way_past_the_gate(monkeypatch):
    """The refusal points at this, so it has to work: widening the amendment
    to the whole carrier mixes nothing, so there is nothing to gate."""
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)
    _wire(monkeypatch, _Session(SPREAD_ROOM.move_one("north", 0.2, 0.0)))

    cal, refused = _partial(cal)
    assert refused.status == capture_runs.STATUS_REFUSED
    cal, entry = _amend(cal, ["north"],
                        overrides={"emitter_ids": [BLOCKS["north"][0]]},
                        whole_carrier=True)
    assert entry.status == capture_runs.STATUS_OK
    assert sorted(entry.emitters) == sorted(BLOCKS["north"])
    assert entry.mixed_carriers == []


def test_two_granularities_on_one_carrier_are_refused_at_the_plan(monkeypatch):
    """`RoomMap.drop_carrier_footprints`' own invariant, defended one level
    down by `room_mapping.scope_plan`: driving a whole-carrier footprint and
    a range of the same carrier would dim that fixture twice. The stored map
    here is WHOLE and the amendment asks for a block of it."""
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    cal = _cal(room, items=[{"kind": "map", "room_id": room.id,
                             "granularity": "whole", "carrier_ids": ["north"],
                             "label": "north"}])
    cal, first = _run(cal)
    assert first.emitters == ["north"]

    cal, entry = _amend(cal, ["north"], overrides={
        "granularity": "block", "block_pixels": 10,
        "emitter_ids": [BLOCKS["north"][0]]})
    assert entry.status == capture_runs.STATUS_REFUSED
    assert any("two different granularities" in i.detail for i in entry.items)
    assert light_field.get_room(room.id).footprint("north") is not None


def test_the_harness_goes_red_on_the_defect_it_was_written_for(monkeypatch):
    """A GATE THAT CANNOT BE SEEN TO FAIL IS DECORATION. With `judge_mix`
    stubbed out — the world as it would be with no gate at all — a partial
    amendment taken after the camera moved lands silently, and one carrier
    ends up holding two readings taken from two different places with
    nothing anywhere saying so. That is the failure every test above is
    written against."""
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)
    _wire(monkeypatch, _Session(SPREAD_ROOM.shift(0.25, 0.0)))
    monkeypatch.setattr(amendment, "judge_mix",
                        lambda *_a, **_kw: amendment.MixVerdict())

    cal, entry = _partial(cal, force=True)
    assert entry.status == capture_runs.STATUS_OK
    assert entry.mixed_carriers == ["north"]      # the RUN still names it
    origin = _origins(cal)
    assert origin[BLOCKS["north"][0]] == entry.id
    assert origin[BLOCKS["north"][1]] == first.id


# ── 4. naming, and what an amendment may change ────────────────────────────

def test_a_name_this_calibration_does_not_declare_is_refused_not_skipped():
    """An amendment that quietly measured three of the four things he named
    would report success while leaving the fourth at last month's reading."""
    room = _room()
    cal = _cal(room)
    cal, entry = _amend(cal, ["north", "the shelf lamp"])
    assert entry.status == capture_runs.STATUS_REFUSED
    assert entry.refusal == "amendment"
    assert "the shelf lamp" in entry.detail
    assert "north" in entry.detail and "east" in entry.detail


def test_an_amendment_naming_nothing_is_refused():
    room = _room()
    cal = _cal(room)
    _cal_, entry = _amend(cal, [])
    assert entry.status == capture_runs.STATUS_REFUSED
    assert "named nothing" in entry.detail


def test_an_amendment_may_not_change_what_the_calibration_declares():
    """Changing the room or the kind makes it a different declaration, which
    is an EDIT and its own lineage entry — not a one-run override."""
    room = _room()
    cal = _cal(room)
    _cal_, entry = _amend(cal, ["north"], overrides={"room_id": "elsewhere"})
    assert entry.status == capture_runs.STATUS_REFUSED
    assert "room_id" in entry.detail
    assert list(cal.items) == _items(room)


def test_an_override_applies_to_the_run_and_never_to_the_declaration(monkeypatch):
    """A granularity change is the plan's own example of an amendment. It
    changes what this run measures and leaves the declaration alone."""
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    cal = _cal(room, items=[{"kind": "map", "room_id": room.id,
                             "granularity": "whole", "carrier_ids": ["north"],
                             "label": "north"}])
    cal, _first = _run(cal)
    cal, entry = _amend(cal, ["north"], overrides={"granularity": "block",
                                                   "block_pixels": 10})
    assert entry.status == capture_runs.STATUS_OK
    assert sorted(entry.emitters) == sorted(BLOCKS["north"])
    assert entry.declared[0]["granularity"] == "block"
    assert cal.items[0]["granularity"] == "whole"


# ── 5. the lineage, and the declaration that is never rewritten ────────────

def test_editing_the_declaration_keeps_the_previous_one_whole():
    """"Append-only, never rewritten" has to be true of the DECLARATION and
    not only of the run list: the change sentences say what moved and could
    never rebuild what was there."""
    room = _room()
    cal = _cal(room)
    previous = declaration_snapshot(cal)
    calibration_runs.record_declaration_change(
        cal, ["declared items: 2 -> 1"], previous=previous)
    cal.items = [cal.items[0]]
    calibration_store.save(cal)

    back = calibration_store.load(cal.id)
    edits = [r for r in back.runs if r.kind == KIND_DECLARATION]
    assert len(edits) == 1
    assert edits[0].previous_declaration["items"] == previous["items"]
    assert len(back.items) == 1


def test_a_declaration_edit_touches_no_measurement(monkeypatch):
    """It drives nothing, supersedes nothing, and does not count as a run."""
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)
    before = {f.emitter_id: f.model_dump()
              for f in light_field.get_room(room.id).footprints}

    calibration_runs.record_declaration_change(
        cal, ["name: 'a' -> 'b'"], previous=declaration_snapshot(cal))
    calibration_store.save(cal)
    after = {f.emitter_id: f.model_dump()
             for f in light_field.get_room(room.id).footprints}
    assert after == before
    assert cal.last_run.id == first.id
    assert set(_origins(cal).values()) == {first.id}


def test_an_amendment_counts_as_a_run_everywhere_a_reader_asks():
    """An amendment produces footprints exactly as a run does. A reader
    still testing `kind == "run"` would report his newest measurement as
    belonging to nobody — which is why `RUN_KINDS` is a constant."""
    room = _room()
    cal = _cal(room)
    cal, first = _run(cal)
    cal, entry = _amend(cal, ["north"])
    assert cal.ran
    assert cal.last_run.id == entry.id
    assert cal.last_full_run.id == first.id
    summary = cal.as_summary()
    assert (summary["runs"], summary["amendments"]) == (1, 1)


# ── 6. the boundary, unmoved ───────────────────────────────────────────────

def test_a_released_room_refuses_an_amendment_and_the_refusal_is_an_entry(
        monkeypatch):
    """NEVER TAKES HIS ROOM. An amendment is an ordinary capture run through
    the one seam, so it refuses on the same sentence a button press does —
    and the refusal is recorded, because "did it run last night" must be a
    read."""
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    cal = _cal(room)
    cal, _first = _run(cal)

    def _released(*_a, **_kw):
        raise fx_seam.RoomReleased("the room is released")

    monkeypatch.setattr(room_mapping, "live_virtual_ids", _released)
    cal, entry = _amend(cal, ["north"])
    assert entry.kind == KIND_AMENDMENT
    assert entry.status == capture_runs.STATUS_REFUSED
    assert calibration_store.load(cal.id).runs[-1].id == entry.id


def test_amendable_says_no_before_anything_has_ever_been_measured():
    """ABSENCE IS A READ: there is no subset worth re-taking of a
    calibration that has never measured anything."""
    room = _room()
    cal = _cal(room)
    assert not amendment.amendable(cal)
    cal, _first = _run(cal)
    assert amendment.amendable(cal)
    assert calibration_runs.view(cal)["item_names"] == ["north", "east"]
