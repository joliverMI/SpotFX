"""THE CALIBRATION RECORD — the artefact, the run, and the honesty rails.

The point of this step is that "what produced this map, from where, under
what settings, and may it be compared with last week's" stops being a matter
of memory. So the assertions here are about the RECORD as much as the run:

  * the lineage is APPEND-ONLY, and a REFUSED run is an entry in it;
  * provenance is a READ against the live room map — present, superseded,
    or MISSING, never an implied footprint that is not there;
  * ABSENCE IS A READ: a calibration that never ran says so;
  * the comparability claim is gated on the pose AND the pinned regime, and
    each half fails on its own;
  * the never-takes-his-room boundary is unmoved — a released room refuses
    and the refusal is recorded.

The run half drives the REAL chain: `capture_runs.run_map` through
`room_mapping.run_mapping` through the real footprint arithmetic, against
the synthetic camera `tests/test_pose_fingerprint.py` builds. Nothing here
touches a room, a light or a webcam.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import replace

import pytest

from spectra.models.calibration import (Calibration, CalibrationRun,
                                        PinnedCamera)
from spectra.models.room_map import RoomMap
from spectra.services import (calibration_runs, calibration_store,
                              capture_queue, capture_runs, fx_seam,
                              light_field, mapping_refusals, mapping_session,
                              room_mapping)
from spectra.services import pose_fingerprint as pf
from tests.test_pose_fingerprint import (AXIS, CARRIERS, SPREAD_ROOM, _Session,
                                         _deps)


# ── harness ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    """A calibration run WAITS for a present, locked camera — up to three
    minutes, because the real shape is "start it, then start the client".
    In here the camera is either there or deliberately not, so the wait is
    the one production behaviour these tests must not spend."""
    monkeypatch.setattr(calibration_runs, "SESSION_WAIT_S", 0.0)


def _room():
    return light_field.put_room(
        RoomMap(name="Lounge", carrier_ids=list(CARRIERS), axis=AXIS))


def _wire(monkeypatch, session):
    """Point the ONE SEAM at the synthetic camera. Everything above this —
    the lock gate, the lever self-test, the run lock, the hold ceiling —
    is the production code, unchanged."""
    monkeypatch.setattr(mapping_session, "current", session)
    # A REAL `save_room`, unlike the fingerprint tests: a calibration run's
    # whole point is that its footprints LAND in the room map, which is what
    # the provenance link is then resolved against.
    monkeypatch.setattr(room_mapping, "production_deps",
                        lambda sess: _deps(session,
                                           save_room=light_field.put_room))
    return session


def _cal(room, *, items=None, camera=None, name="North shelf"):
    cal = Calibration(name=name, room_id=room.id,
                      camera=camera or PinnedCamera(),
                      items=items if items is not None else [
                          {"kind": "map", "room_id": room.id,
                           "granularity": "whole", "label": "the whole room"}])
    cal.pose.placement = "the north shelf"
    return calibration_store.save(cal)


def _run(cal, **kw):
    return asyncio.run(calibration_runs.run_calibration(cal, **kw))


def _pose(cal, **kw):
    return asyncio.run(calibration_runs.establish_pose(cal, **kw))


# ── 1. the store ───────────────────────────────────────────────────────────

def test_a_calibration_is_one_file_per_id_and_round_trips():
    room = _room()
    cal = _cal(room)
    from spectra import config as scfg
    assert os.path.exists(os.path.join(str(scfg.CALIBRATIONS_DIR),
                                       f"{cal.id}.json"))
    back = calibration_store.load(cal.id)
    assert back is not None
    assert (back.name, back.room_id) == (cal.name, room.id)
    assert back.pose.placement == "the north shelf"
    assert [c.id for c in calibration_store.load_all()] == [cal.id]


def test_an_id_that_is_not_an_id_is_refused_rather_than_sanitised():
    """A calibration id is a filename. A silently different one would write
    a file nothing can find again."""
    assert calibration_store.load("../../etc/passwd") is None
    assert calibration_store.load("a/b") is None


def test_an_unreadable_calibration_does_not_take_the_listing_down():
    room = _room()
    good = _cal(room, name="good")
    from spectra import config as scfg
    with open(os.path.join(str(scfg.CALIBRATIONS_DIR), "broken.json"), "w") as fh:
        fh.write("{not json")
    assert [c.id for c in calibration_store.load_all()] == [good.id]


# ── 2. absence is a read ───────────────────────────────────────────────────

def test_a_calibration_that_never_ran_says_so():
    cal = _cal(_room())
    view = calibration_runs.view(cal)
    assert view["ran"] is False
    assert view["pose_established"] is False
    assert "never run" in view["state"]
    # NOT an empty result set that looks like a run finding nothing.
    assert view["provenance"]["counts"] == {"present": 0, "superseded": 0,
                                            "missing": 0, "unapplied": 0}
    assert "not produced a footprint yet" in view["provenance"]["note"]


# ── 3. the pose ────────────────────────────────────────────────────────────

def test_establishing_a_pose_drives_the_room_and_keeps_the_best_anchors(monkeypatch):
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    cal, entry = _pose(_cal(_room()))
    assert entry.status == capture_runs.STATUS_OK
    assert cal.pose.established
    assert cal.pose.discriminating is True
    assert set(r.emitter_id for r in cal.pose.references) <= set(CARRIERS)
    assert cal.pose.spread > pf.MIN_ANCHOR_SPREAD
    assert "Pose recorded at the north shelf" in entry.detail
    # THE LEVER SELF-TEST'S VERDICT RIDES ON THE ARTEFACT: "these numbers
    # were taken by a camera whose exposure control was measured".
    assert cal.lever.get("verdict") == mapping_refusals.LEVER_OK
    assert cal.lever.get("proven") is True
    # The camera's own identity is on the pose, so a different camera later
    # is a different pose by definition.
    assert cal.pose.camera["host"] == "capture-pi"


def test_establishing_a_pose_writes_no_footprint(monkeypatch):
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    cal, _ = _pose(_cal(room))
    assert light_field.get_room(room.id).footprints == []


def test_re_anchoring_replaces_the_pose_and_keeps_both_entries(monkeypatch):
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    cal, first = _pose(_cal(_room()))
    cal, second = _pose(cal, placement="the west shelf")
    assert cal.pose.taken_by_run == second.id
    assert cal.pose.placement == "the west shelf"
    # APPEND-ONLY: the entry that took the OLD pose is still there.
    assert [r.id for r in cal.runs] == [first.id, second.id]


# ── 4. the run, end to end ─────────────────────────────────────────────────

def test_a_run_measures_the_room_and_links_what_it_produced(monkeypatch):
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    cal, entry = _run(_cal(room))
    assert entry.status == capture_runs.STATUS_OK, entry.detail
    assert entry.kind == "run"
    assert cal.ran is True
    # It ran through the QUEUE, so it is visible on the ordinary run
    # surfaces too, not only in the lineage.
    assert entry.queue_run_id
    assert capture_queue.current.id == entry.queue_run_id
    # THE PROVENANCE LINK: the emitter ids it produced, resolvable against
    # the live room map.
    assert set(entry.emitters) == set(CARRIERS)
    stored = light_field.get_room(room.id)
    assert set(stored.mapped_ids()) == set(CARRIERS)
    prov = calibration_store.provenance(cal, room=stored)
    assert prov["counts"]["present"] == len(CARRIERS)
    assert prov["counts"]["missing"] == 0
    # The first run establishes the pose, and that is its own entry.
    kinds = [r.kind for r in cal.runs]
    assert kinds == ["fingerprint", "run"]
    assert entry.fingerprint["verdict"] == mapping_refusals.POSE_UNESTABLISHED


def test_a_re_run_records_what_it_superseded(monkeypatch):
    """Nothing disappears from the record without the record saying what
    replaced it. The per-emitter supersession MECHANICS are the next step;
    this is the ledger they will be written against."""
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    cal, first = _run(_cal(_room()))
    cal, second = _run(cal)
    assert second.status == capture_runs.STATUS_OK, second.detail
    assert set(second.superseded) == set(CARRIERS)
    assert set(second.superseded.values()) == {first.id}
    # The FIRST run's own entry is untouched and still names what it made.
    assert set(cal.run(first.id).emitters) == set(CARRIERS)
    prov = calibration_store.provenance(cal)
    states = {r["state"] for r in prov["emitters"]}
    assert states == {"present", "superseded"}
    assert "replaced by a later run" in prov["note"]


def test_each_items_witness_verdicts_ride_on_the_lineage_entry(monkeypatch):
    """WITNESS VERDICTS PER RUN. With no witness wired, every capture is
    UNCLAIMED — deliberately not folded into `clean`, because "we could not
    check" and "we checked and it was fine" are different facts and only one
    of them is evidence (`MappingResult.witness_counts`' own rule)."""
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    cal, entry = _run(_cal(_room()))
    assert len(entry.items) == 1
    counts = entry.items[0].witness
    assert counts["clean"] == 0
    assert counts["contaminated"] == 0
    assert counts["unclaimed"] == len(CARRIERS)


def test_the_envelope_it_needs_is_carried_on_the_artefact(monkeypatch):
    """DECLARED, not enforced here: the dark room is the hold's job and the
    house's own light is the witness's. What this makes possible is a run at
    the wrong hour being a readable mismatch rather than a map that is
    quietly worse than the one before it."""
    room = _room()
    cal = _cal(room)
    cal.envelope.window = "dark music"
    cal.envelope.note = "after the blinds close"
    calibration_store.save(cal)
    back = calibration_store.load(cal.id)
    assert back.envelope.dark_required is True
    assert back.envelope.window == "dark music"
    assert calibration_runs.view(back)["envelope"]["note"] == \
        "after the blinds close"


def test_a_second_run_under_the_same_pose_is_comparable(monkeypatch):
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    cal, _ = _run(_cal(_room()))
    cal, second = _run(cal)
    assert second.fingerprint["verdict"] == mapping_refusals.POSE_MATCH
    assert second.comparable is True
    assert "camera is where it was" in second.comparable_note


# ── 5. THE DISCRIMINATION, at the gate ─────────────────────────────────────

def test_a_moved_camera_refuses_the_re_run_by_name(monkeypatch):
    """The plan's own words: a moved camera is a NAMED REFUSAL rather than
    silently incomparable data."""
    sess = _wire(monkeypatch, _Session(SPREAD_ROOM))
    cal, _ = _run(_cal(_room()))
    sess.room = SPREAD_ROOM.shift(0.10, -0.06)
    cal, entry = _run(cal)
    assert entry.status == capture_runs.STATUS_REFUSED
    assert entry.refusal == "pose"
    assert "THE CAMERA HAS MOVED" in entry.detail
    assert entry.items == []            # nothing was measured
    assert entry.comparable is False
    # AND THE REFUSAL IS AN ENTRY: "did it run?" is a read, never a silence.
    assert cal.runs[-1].id == entry.id
    assert calibration_store.load(cal.id).runs[-1].detail == entry.detail


def test_a_changed_room_runs_and_says_it_is_not_comparable(monkeypatch):
    """THE CHAIR CASE, and the captain's binding requirement: "a calibration
    refusing because he moved a chair is a system that expires for reasons
    he cannot see"."""
    sess = _wire(monkeypatch, _Session(SPREAD_ROOM))
    cal, _ = _run(_cal(_room()))
    moved = [r.emitter_id for r in cal.pose.references][0]
    sess.room = SPREAD_ROOM.move_one(moved, 0.18, 0.10)
    cal, entry = _run(cal)
    assert entry.status == capture_runs.STATUS_OK, entry.detail
    assert entry.fingerprint["verdict"] == mapping_refusals.POSE_ROOM_CHANGED
    assert entry.comparable is False
    assert "THE ROOM HAS CHANGED" in entry.comparable_note
    assert set(entry.emitters) == set(CARRIERS)


def test_an_inconclusive_fingerprint_runs_too(monkeypatch):
    """`cannot_tell` deliberately does not refuse either: a thin-anchored
    pose would otherwise refuse for ever on any change at all."""
    sess = _wire(monkeypatch, _Session(SPREAD_ROOM))
    cal, _ = _run(_cal(_room()))
    sess.room = SPREAD_ROOM.dim_all(0.15)
    cal, entry = _run(cal)
    assert entry.fingerprint["verdict"] == mapping_refusals.POSE_CANNOT_TELL
    assert entry.status == capture_runs.STATUS_OK, entry.detail
    assert entry.comparable is False
    assert "CANNOT TELL" in entry.comparable_note


def test_an_explicit_press_runs_past_a_moved_camera_and_names_it(monkeypatch):
    """The Force Scene precedent. It must NEVER re-anchor the pose as a side
    effect — a silently re-anchored pose erases the thing that noticed."""
    sess = _wire(monkeypatch, _Session(SPREAD_ROOM))
    cal, _ = _run(_cal(_room()))
    was = [(r.emitter_id, r.x, r.y) for r in cal.pose.references]
    sess.room = SPREAD_ROOM.shift(0.10, -0.06)
    cal, entry = _run(cal, force=True)
    assert entry.status == capture_runs.STATUS_OK, entry.detail
    assert any("overrode_camera_moved" in n for n in entry.notes)
    assert entry.comparable is False
    assert [(r.emitter_id, r.x, r.y) for r in cal.pose.references] == was


# ── 6. the OTHER half of the comparability claim ───────────────────────────

def test_changing_the_pinned_regime_breaks_comparability_on_its_own(monkeypatch):
    """A footprint is `lit - dark` in a camera's own byte scale, so two
    regimes are two scales — the pose matching perfectly does not save
    them."""
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    cal, _ = _run(_cal(_room(), camera=PinnedCamera(exposure_time=200)))
    cal.camera = PinnedCamera(exposure_time=400)
    calibration_store.save(cal)
    cal, entry = _run(cal)
    assert entry.fingerprint["verdict"] == mapping_refusals.POSE_MATCH
    assert entry.comparable is False
    assert "different camera settings" in entry.comparable_note
    assert "exposure time: 200 -> 400" in entry.comparable_note


# ── 7. honesty rails ───────────────────────────────────────────────────────

def test_a_footprint_that_no_longer_exists_is_reported_not_implied(monkeypatch):
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    cal, _ = _run(_cal(room))
    stored = light_field.get_room(room.id)
    stored.drop_carrier_footprints("east")
    light_field.put_room(stored)
    prov = calibration_store.provenance(calibration_store.load(cal.id))
    gone = [r for r in prov["emitters"] if r["state"] == "missing"]
    assert [r["emitter_id"] for r in gone] == ["east"]
    assert "no longer in the room map at all" in prov["note"]


def test_a_calibration_whose_room_is_gone_reports_it_and_refuses(monkeypatch):
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    cal, _ = _run(_cal(room))
    light_field.delete_room(room.id)
    prov = calibration_store.provenance(calibration_store.load(cal.id))
    assert prov["room_present"] is False
    assert prov["counts"]["missing"] == len(CARRIERS)
    cal, entry = _run(calibration_store.load(cal.id))
    assert entry.status == capture_runs.STATUS_REFUSED
    assert entry.refusal == "no_room"
    assert "no longer stored" in entry.detail


def test_the_tag_registry_is_storage_only_and_nothing_reads_it():
    """STORAGE ONLY in this step, by design and provably: there is no
    tag-detection code anywhere in this build, so a registry with entries in
    it must change nothing about a pose, a run or a judgement. The vision
    step lands into a record that already holds his measured truth."""
    import pathlib
    from spectra.models.calibration import TagRegistration
    cal = _cal(_room())
    cal.tags = [TagRegistration(tag_id=7, measured_side_mm=97.4,
                                mount="the left window frame")]
    calibration_store.save(cal)
    back = calibration_store.load(cal.id)
    assert back.tag(7).measured_side_mm == 97.4
    assert back.tag(99) is None
    # NOTHING READS IT, asserted against the source rather than believed:
    # `pose_fingerprint` and `calibration_runs` are the two modules a tag
    # would have to reach to affect a measurement, and neither names the
    # registry at all. When the vision step arrives it will change this
    # test, which is the point — it should be a deliberate edit and not a
    # thing that quietly starts being true.
    for name in ("pose_fingerprint.py", "calibration_runs.py"):
        src = (pathlib.Path("spectra/services") / name).read_text()
        assert "TagRegistration" not in src, name
        assert ".tags" not in src, name
        assert "measured_side_mm" not in src, name


def test_the_lineage_has_no_way_to_drop_an_entry():
    """APPEND-ONLY is a property of the model, not a promise in a
    docstring: `append_run` is the only mutator and there is no
    counterpart."""
    cal = Calibration(name="x", room_id="r")
    assert [m for m in dir(cal) if "run" in m and m.startswith(("drop", "remove",
                                                               "delete"))] == []
    first = cal.append_run(CalibrationRun(kind="run", status="ok"))
    cal.append_run(CalibrationRun(kind="run", status="refused"))
    assert [r.id for r in cal.runs][0] == first.id
    assert len(cal.runs) == 2


def test_a_declaration_edit_is_recorded_in_the_lineage_and_is_not_a_run():
    cal = _cal(_room())
    calibration_runs.record_declaration_change(cal, ["declared items: 1 -> 2"])
    assert cal.runs[-1].kind == "declaration"
    assert cal.ran is False          # nothing was driven
    assert cal.last_run is None


# ── 8. THE BOUNDARY, unmoved ───────────────────────────────────────────────

def test_a_released_room_refuses_and_nothing_is_written(monkeypatch):
    """THE NEVER-TAKES-HIS-ROOM BOUNDARY. A calibration run asks for
    nothing, waits for no handover, and behaves no differently because
    nobody is awake."""
    sess = _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    cal = _cal(room)

    async def released():
        raise fx_seam.RoomReleased("the lights are released")

    monkeypatch.setattr(room_mapping, "production_deps",
                        lambda s: replace(_deps(sess), get_virtuals=released))
    cal, entry = _run(cal)
    assert entry.status == capture_runs.STATUS_REFUSED
    assert "released" in entry.detail
    assert light_field.get_room(room.id).footprints == []
    # RECORDED, not silent.
    assert calibration_store.load(cal.id).runs[-1].detail == entry.detail


def test_no_session_refuses_by_the_sessions_own_sentence(monkeypatch):
    monkeypatch.setattr(mapping_session, "current", None)
    cal = _cal(_room())
    cal, entry = _run(cal)
    assert entry.status == capture_runs.STATUS_REFUSED
    assert entry.refusal == "session"
    assert entry.items == []


def test_a_run_whose_pose_could_not_be_taken_claims_no_baseline(monkeypatch):
    """A pose that was TAKEN is the baseline of a comparable series; a pose
    that could not be taken is not, and claiming one would leave every later
    run comparing itself against nothing."""
    sess = _wire(monkeypatch, _Session(SPREAD_ROOM))
    room = _room()
    empty = light_field.put_room(RoomMap(name="Bare", carrier_ids=[], axis=AXIS))
    cal = _cal(empty, items=[{"kind": "map", "room_id": empty.id,
                              "granularity": "whole"}])
    cal, entry = _run(cal)
    assert cal.pose.established is False
    assert entry.comparable is False
    assert "No pose could be recorded" in entry.comparable_note


def test_a_calibration_with_nothing_declared_says_so(monkeypatch):
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    cal, entry = _run(_cal(_room(), items=[]))
    assert entry.refusal == "nothing_declared"
    assert "declares nothing to run yet" in entry.detail


def test_one_queue_at_a_time(monkeypatch):
    _wire(monkeypatch, _Session(SPREAD_ROOM))
    cal = _cal(_room())
    items = capture_queue.parse_items(cal.items)
    capture_queue.new_run(items, label="someone else")
    cal, entry = _run(cal)
    assert entry.refusal == "busy"
    assert "already running" in entry.detail
