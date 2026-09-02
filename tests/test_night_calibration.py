"""THE NIGHT SEAM — a calibration is what the night runs, and an unattended
amendment happens INSIDE the unchanged ownership boundary.

Step four of the calibration practice. What it makes true is the exact
sentence of his standing direction — "restart and edit the cals if needed
without my intervention" — AT NIGHT. So the things this file has to prove
are not new capabilities but OLD GUARANTEES SURVIVING A NEW CALLER:

  THE BOUNDARY IS UNMOVED. A start event on the calibration path declines
  by name when SPECTRA does not hold the room, exactly as a plain one does,
  and touches nothing on the way out.
  ONE RECORD SYSTEM. What the night measures lands in the calibration's own
  append-only lineage — the same entry a pressed run produces — and the
  night's record carries a LINK and a verdict, never a second copy.
  ONE VALIDATOR. A calibration declaration is validated the whole way down
  at DECLARATION time, while he is awake.
  THE HONESTY GATE APPLIES AT 2AM EXACTLY AS AT 2PM. An amendment whose
  mixing gate will not vouch REFUSES BY NAME, the night records the refusal
  as its outcome, and nothing is quietly widened into a full re-take.
  THE PLANNED END STILL BOUNDS IT, per item, on the calibration's own queue.
  A MORNING-CUT AMENDMENT APPLIES NOTHING (the Admiral's ruling) and the
  morning read says so in his nouns.

The run half drives the REAL chain — `night_run.start` through
`night_calibration` through `calibration_runs` through `capture_runs` and
`room_mapping` to the real footprint arithmetic — against the synthetic
camera `tests/test_pose_fingerprint.py` builds. Nothing here touches a room,
a light or a webcam: ownership is repointed per test, every store is
repointed by conftest, and the device layer is faked.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from fx import light_ownership as lo
from spectra.models.calibration import KIND_AMENDMENT, KIND_RUN, Calibration
from spectra.models.calibration import PinnedCamera
from spectra.models.room_map import RoomMap
from spectra.services import (calibration_runs, calibration_store,
                              capture_runs, light_field, mapping_refusals,
                              mapping_session, morning_read,
                              night_calibration, night_run, room_mapping)
from tests.test_pose_fingerprint import (AXIS, CARRIERS, SPREAD_ROOM, _Session,
                                         _deps)

_ORIGINAL_OWNERSHIP_FILE = lo.OWNERSHIP_FILE

EVENT = {"event": "sleep-window-start", "ts": "2026-09-01T01:00:00Z",
         "source": "home-assistant"}
MORNING = {"event": mapping_refusals.MORNING_ROUTINE,
           "ts": "2026-09-01T05:50:00Z", "source": "home-assistant"}

#: Two emitters per carrier, so a PARTIAL amendment is a real thing rather
#: than a synonym for a whole one.
BLOCKS = {"north": ["north:blk0[0-9]", "north:blk1[10-19]"],
          "east": ["east:blk0[0-9]", "east:blk1[10-19]"]}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _own_file(tmp_path):
    lo.OWNERSHIP_FILE = tmp_path / "ownership.json"
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
    yield
    lo.OWNERSHIP_FILE = _ORIGINAL_OWNERSHIP_FILE


def _owner(owner):
    lo._save(lo.OwnershipRecord(owner=owner))


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(calibration_runs, "SESSION_WAIT_S", 0.0)


@pytest.fixture(autouse=True)
def _quiet_room(monkeypatch):
    """The night's own device layer, faked: this file is about the seam, and
    `night_power`/`night_exit` have their own proofs in tests/test_night_*."""
    from spectra.services import flare_preview_hold

    async def listing():
        return []

    async def live_devices():
        return []

    async def close_hold():
        return {"reverted": True}

    monkeypatch.setattr(night_run, "_device_listing", listing)
    monkeypatch.setattr(night_run, "_live_devices", live_devices)
    monkeypatch.setattr(flare_preview_hold, "close_hold", close_hold)


def _camera(monkeypatch, session=None):
    session = session or _Session(SPREAD_ROOM)
    monkeypatch.setattr(mapping_session, "current", session)
    monkeypatch.setattr(room_mapping, "production_deps",
                        lambda sess: _deps(session,
                                           save_room=light_field.put_room))
    return session


def _room():
    return light_field.put_room(
        RoomMap(name="Lounge", carrier_ids=list(CARRIERS), axis=AXIS))


def _items(room):
    return [{"kind": "map", "room_id": room.id, "granularity": "block",
             "block_pixels": 10, "carrier_ids": [c], "label": c}
            for c in ("north", "east")]


def _cal(room, **kw):
    cal = Calibration(name="North shelf", room_id=room.id,
                      items=_items(room), **kw)
    cal.pose.placement = "the north shelf"
    return calibration_store.save(cal)


async def _night(trigger=None):
    run = await night_run.start(trigger or EVENT)
    if night_run._task is not None:
        await night_run._task
    return run


# ── 1. THE BOUNDARY, on the calibration path ───────────────────────────────

@pytest.mark.parametrize("owner", [lo.RELEASED, lo.SPOT_EFFECTS,
                                   lo.HANDING_OVER])
def test_a_calibration_night_declines_when_we_do_not_hold_the_room(
        monkeypatch, owner):
    """THE ONE THING THAT IS NOT NEGOTIABLE, re-asserted on the new caller.
    A calibration is a more valuable thing to run than a bare item list,
    which is exactly why the boundary has to be proven again rather than
    assumed to have carried over."""
    _camera(monkeypatch)
    cal = _cal(_room())
    night_run.save_declaration("nightly", calibration_id=cal.id)
    _owner(owner)

    run = _run(_night())
    assert run.state == night_run.STATE_DECLINED
    assert run.refusal == "not_owned"
    assert "never takes the room" in run.detail
    # Nothing reached the calibration: no lineage entry, no footprints.
    assert calibration_store.load(cal.id).runs == []
    assert light_field.get_room(cal.room_id).footprints == []


def test_a_declined_calibration_night_resolves_nothing_at_all(monkeypatch):
    """Read the ownership record FIRST. A declined night must not even have
    LOADED the calibration, let alone driven a light."""
    _camera(monkeypatch)
    cal = _cal(_room())
    night_run.save_declaration("nightly", calibration_id=cal.id)
    _owner(lo.RELEASED)

    def boom(*a, **kw):
        raise AssertionError("a declined night resolved the calibration")

    monkeypatch.setattr(night_calibration, "resolve", boom)
    assert _run(_night()).state == night_run.STATE_DECLINED


# ── 2. ONE VALIDATOR, AT DECLARATION TIME ──────────────────────────────────

def test_a_calibration_declaration_is_validated_while_he_is_awake(monkeypatch):
    _camera(monkeypatch)
    with pytest.raises(ValueError) as exc:
        night_run.save_declaration("nightly", calibration_id="no-such-thing")
    assert "no such calibration" in str(exc.value)
    assert night_run.load_declaration() is None


def test_an_amendment_naming_an_undeclared_item_is_refused_at_declaration(
        monkeypatch):
    """`amendment.resolve_subset`'s OWN sentence, reached through the same
    function the /amend route calls — not a second dialect that reads almost
    the same."""
    _camera(monkeypatch)
    cal = _cal(_room())
    with pytest.raises(ValueError) as exc:
        night_run.save_declaration("nightly", calibration_id=cal.id,
                                   amend={"items": ["the sofa"]})
    assert "declares nothing called" in str(exc.value)


def test_a_declaration_names_a_calibration_or_a_list_and_never_both(
        monkeypatch):
    _camera(monkeypatch)
    room = _room()
    cal = _cal(room)
    with pytest.raises(ValueError) as exc:
        night_run.save_declaration("nightly", _items(room),
                                   calibration_id=cal.id)
    assert "never both" in str(exc.value)


def test_a_plain_item_declaration_is_untouched_by_any_of_this(monkeypatch):
    """Every night declared before this existed still parses, still runs the
    plain path, and carries no calibration link."""
    _camera(monkeypatch)
    room = _room()
    stored = night_run.save_declaration("nightly", _items(room))
    assert "calibration_id" not in stored
    assert night_calibration.parse_target(stored).declared is False


# ── 3. ONE RECORD SYSTEM — the night lands in the lineage ──────────────────

def test_the_night_runs_the_calibration_and_lands_in_its_lineage(monkeypatch):
    """The whole point of the step: what the night measured is the SAME
    entry a pressed run produces, in the calibration's own append-only
    lineage, with its pose check, its supersession and its comparability
    claim — not a room map nobody can trace."""
    _camera(monkeypatch)
    cal = _cal(_room())
    night_run.save_declaration("tonight", calibration_id=cal.id)

    run = _run(_night())
    assert run.state == night_run.STATE_COMPLETE

    stored = calibration_store.load(cal.id)
    runs = [r for r in stored.runs if r.kind == KIND_RUN]
    assert len(runs) == 1, "the night did not land ONE entry in the lineage"
    entry = runs[0]
    assert entry.status == capture_runs.STATUS_OK
    assert sorted(entry.emitters) == sorted(BLOCKS["north"] + BLOCKS["east"])
    assert entry.applied is True
    # THE POSE WAS TAKEN AND CHECKED, unattended, exactly as it is by hand.
    assert stored.pose.established is True
    assert entry.comparable is True

    # THE NIGHT'S RECORD IS A LINK AND A VERDICT, never a copy.
    assert run.calibration["calibration_id"] == cal.id
    assert run.calibration["name"] == "North shelf"
    assert run.calibration["mode"] == night_calibration.MODE_RUN
    assert run.calibration["entry_id"] == entry.id
    assert run.calibration["applied"] is True
    # A LINK AND A VERDICT: no lineage, no declaration, no measurements.
    assert not ({"runs", "declared", "measurements", "lineage"}
                & set(run.calibration))
    assert night_run.load_nights()[-1]["calibration"]["entry_id"] == entry.id


def test_the_night_runs_an_amendment_and_supersedes_only_what_it_measured(
        monkeypatch):
    """Unattended amend-in-part: one fixture re-measured at 2am, the rest
    still credited to the run that took them."""
    _camera(monkeypatch)
    cal = _cal(_room())
    cal, first = _run(calibration_runs.run_calibration(cal))
    assert first.status == capture_runs.STATUS_OK

    night_run.save_declaration("just the north", calibration_id=cal.id,
                               amend={"items": ["north"]})
    run = _run(_night())
    assert run.state == night_run.STATE_COMPLETE

    stored = calibration_store.load(cal.id)
    entry = [r for r in stored.runs if r.kind == KIND_AMENDMENT][-1]
    assert entry.amended == ["north"]
    assert sorted(entry.emitters) == sorted(BLOCKS["north"])
    assert entry.applied is True
    origin = stored.emitter_origin()
    for emitter_id in BLOCKS["north"]:
        assert origin[emitter_id] == entry.id
    for emitter_id in BLOCKS["east"]:
        assert origin[emitter_id] == first.id


# ── 4. THE HONESTY GATE AT 2AM ─────────────────────────────────────────────

def test_a_night_amendment_that_would_mix_refuses_by_name_and_is_recorded(
        monkeypatch):
    """THE GATE IS THE SAME GATE. A subset re-take that would leave one
    carrier holding two readings taken under camera settings that are not
    comparable refuses, spends nothing, and the NIGHT records the refusal as
    its outcome — never a silent skip, and never a full re-take he did not
    declare."""
    _camera(monkeypatch)
    room = _room()
    cal = _cal(room)
    cal, first = _run(calibration_runs.run_calibration(cal))
    assert first.status == capture_runs.STATUS_OK
    before = {f.emitter_id: f.weight
              for f in light_field.get_room(room.id).footprints}

    # The regime moves: two scales, so the halves of one carrier could not
    # be read together.
    cal.camera = PinnedCamera(exposure_time=120)
    cal = calibration_store.save(cal)
    night_run.save_declaration(
        "half the north", calibration_id=cal.id,
        amend={"items": ["north"],
               "overrides": {"emitter_ids": [BLOCKS["north"][0]]}})

    run = _run(_night())
    assert run.state == night_run.STATE_REFUSED, \
        "a refused calibration read as an ordinary night"
    assert run.state in night_run.ENDED_STATES
    assert night_run.status_brief()["active"] is False
    assert "would leave" in run.detail and "not comparable" in run.detail

    stored = calibration_store.load(cal.id)
    entry = [r for r in stored.runs if r.kind == KIND_AMENDMENT][-1]
    assert entry.status == capture_runs.STATUS_REFUSED
    assert entry.refusal == "would_mix"
    # NOTHING RAN: the map is byte-for-byte what it was.
    assert {f.emitter_id: f.weight
            for f in light_field.get_room(room.id).footprints} == before
    # AND IT WAS NOT WIDENED into the full re-take he did not declare.
    assert stored.emitter_origin()[BLOCKS["east"][0]] == first.id


def test_a_refused_night_is_a_read_in_the_morning_not_a_silence(monkeypatch):
    """A REFUSAL IS DURABLE AND IT IS AN ACT LIST, not a silence
    indistinguishable from the seam being broken."""
    _camera(monkeypatch)
    room = _room()
    cal = _cal(room)
    cal, _first = _run(calibration_runs.run_calibration(cal))
    cal.camera = PinnedCamera(exposure_time=120)
    cal = calibration_store.save(cal)
    night_run.save_declaration(
        "half the north", calibration_id=cal.id,
        amend={"items": ["north"],
               "overrides": {"emitter_ids": [BLOCKS["north"][0]]}})

    run = _run(_night())
    assert run.state == night_run.STATE_REFUSED
    assert night_run.load_nights()[-1]["state"] == night_run.STATE_REFUSED
    read = morning_read.build()
    assert "refused" in read["ran"]
    assert read["waiting"], "a refused night left nothing waiting on him"


# ── 5. THE PLANNED END STILL BOUNDS THE CALIBRATION'S OWN QUEUE ────────────

def test_a_calibration_queue_that_will_not_fit_declines_before_the_dark(
        monkeypatch):
    """The bound is about the ITEMS, whoever declared them. A calibration is
    priced exactly as a plain list is, and refused the same way."""
    _camera(monkeypatch)
    cal = _cal(_room())
    night_run.save_declaration("nightly", calibration_id=cal.id)

    async def price(items, now=None):
        assert len(items) == 2, "the calibration's own items were not priced"
        return {"items": [{"name": i.name, "seconds": 4000.0} for i in items],
                "total_seconds": 8000.0, "window_seconds": 600.0,
                "planned_end": time.time() + 600,
                "planned_end_label": night_run.PLANNED_END_LABEL}

    monkeypatch.setattr(night_run, "price_items", price)
    run = _run(_night())
    assert run.state == night_run.STATE_DECLINED
    assert run.refusal == "will_not_fit"
    assert calibration_store.load(cal.id).runs == []


def test_the_per_item_guard_reaches_the_calibrations_own_queue(monkeypatch):
    """PER ITEM, not once at the top — and it has to reach through
    `calibration_runs` to `run_queue`, or a calibration night would be the
    one path with no morning bound."""
    _camera(monkeypatch)
    cal = _cal(_room())
    night_run.save_declaration("nightly", calibration_id=cal.id)

    async def price(items, now=None):
        return {"items": [{"name": i.name, "seconds": 30.0} for i in items],
                "total_seconds": 60.0, "window_seconds": 9999.0,
                "planned_end": time.time() + 9999,
                "planned_end_label": night_run.PLANNED_END_LABEL}

    monkeypatch.setattr(night_run, "price_items", price)
    # A window that has already closed by the time the first item starts.
    monkeypatch.setattr(night_run, "seconds_until_planned_end",
                        lambda now=None: 1.0)

    run = _run(_night())
    entry = calibration_store.load(cal.id).runs[-1]
    assert entry.status == capture_runs.STATUS_REFUSED
    assert "blinds open just after" in entry.detail
    assert light_field.get_room(cal.room_id).footprints == []


# ── 6. A MORNING-CUT AMENDMENT APPLIES NOTHING ─────────────────────────────

def _cut_after_first_footprint(monkeypatch, session, on_cut=None):
    """Stop the run part-way, the way his morning routine does.

    Tripped on the first footprint the run PERSISTS rather than on a frame
    count, and that precision is the point: the pose fingerprint pass drives
    the same camera and stores nothing (`capture_runs.run_pose_fingerprint`),
    so a frame-counting trip would abort the pose check instead of the
    amendment and prove something else entirely.

    `night_run.abort` sets exactly this attribute, and `room_mapping` checks
    it before every capture."""
    real_put = light_field.put_room
    real_gather = session.gather
    state: dict = {"footprints": 0, "cut": False}

    def put_room(room, path=None):
        got = real_put(room, path)
        state["footprints"] += 1
        return got

    async def gather(seconds, min_frames=1):
        # THE CUT LANDS ON THE NEXT CAPTURE AFTER THE FIRST FOOTPRINT — an
        # await, so an `abort()` scheduled here genuinely runs before the
        # run reads `run_abort`, which is what makes this deterministic
        # rather than dependent on where the event loop happens to yield.
        if state["footprints"] >= 1 and not state["cut"]:
            state["cut"] = True
            if on_cut is None:
                session.run_abort = mapping_refusals.night_ended_by_morning()
            else:
                await on_cut()
        return await real_gather(seconds, min_frames=min_frames)

    monkeypatch.setattr(light_field, "put_room", put_room)
    session.gather = gather
    return state


def test_a_night_amendment_cut_short_applies_nothing_and_says_so(monkeypatch):
    """THE ADMIRAL'S RULING. A partial that applied itself would leave his
    room holding neither the old calibration nor the new one but a mixture
    assembled by where the clock fell — and he could not know which parts of
    his room ran on which measurement.

    So: the readings are KEPT in the lineage, the room map is put back
    EXACTLY as it was, and the record says both."""
    _camera(monkeypatch)
    room = _room()
    cal = _cal(room)
    cal, first = _run(calibration_runs.run_calibration(cal))
    before = {f.emitter_id: (f.weight, f.grid)
              for f in light_field.get_room(room.id).footprints}
    assert len(before) == 4

    session = _camera(monkeypatch)
    _cut_after_first_footprint(monkeypatch, session)
    night_run.save_declaration("just the north", calibration_id=cal.id,
                               amend={"items": ["north"]})
    run = _run(_night())

    stored = calibration_store.load(cal.id)
    entry = [r for r in stored.runs if r.kind == KIND_AMENDMENT][-1]
    assert entry.status == capture_runs.STATUS_PARTIAL
    # KEPT: what it measured is in the lineage, where a diff reads it.
    assert entry.emitters, "a cut-short amendment recorded nothing it saw"
    measured = [m for i in entry.items for m in i.measurements]
    assert measured, "the readings it took were not kept"
    # APPLIED: nothing.
    assert entry.applied is False
    assert entry.superseded == {}
    assert "applied" in entry.unapplied_reason
    after = {f.emitter_id: (f.weight, f.grid)
             for f in light_field.get_room(room.id).footprints}
    assert after == before, "a cut-short amendment changed his room map"
    # And nothing credits it with a footprint it never applied.
    assert set(stored.emitter_origin().values()) == {first.id}
    assert run.calibration["applied"] is False


def test_the_ruling_is_proven_by_a_test_that_goes_red_without_it(monkeypatch):
    """A proof bar that cannot fail on the defect it was written for is
    decoration. With the rollback removed, the SAME night leaves his room
    holding one re-measured half of a carrier beside three older readings —
    the exact 'assembled by where the clock fell' state the ruling
    refuses."""
    _camera(monkeypatch)
    room = _room()
    cal = _cal(room)
    cal, first = _run(calibration_runs.run_calibration(cal))
    before = {f.emitter_id: f.weight
              for f in light_field.get_room(room.id).footprints}

    monkeypatch.setattr(calibration_runs, "_land_unapplied",
                        lambda *a, **kw: None)
    session = _camera(monkeypatch)
    _cut_after_first_footprint(monkeypatch, session)
    night_run.save_declaration("just the north", calibration_id=cal.id,
                               amend={"items": ["north"]})
    _run(_night())

    stored = calibration_store.load(cal.id)
    entry = [r for r in stored.runs if r.kind == KIND_AMENDMENT][-1]
    assert entry.applied is True, "the harness did not reach the old world"
    origin = stored.emitter_origin()
    mixed = {origin[e] for e in before}
    assert mixed == {first.id, entry.id}, \
        ("without the ruling the carrier holds two runs at once — which is "
         "what this test exists to show, and what the real one refuses")


def test_his_morning_ends_the_night_and_the_record_says_so_not_partial(
        monkeypatch):
    """The REAL abort path: Home Assistant pushes `morning-routine` while
    the amendment is in flight. The night is an ORDINARY ending, the
    amendment applied nothing, and the two facts are recorded separately —
    the run's own sentence must not overwrite the night's."""
    _camera(monkeypatch)
    room = _room()
    cal = _cal(room)
    cal, _first = _run(calibration_runs.run_calibration(cal))
    before = {f.emitter_id: f.weight
              for f in light_field.get_room(room.id).footprints}

    session = _camera(monkeypatch)
    cut = _cut_after_first_footprint(
        monkeypatch, session,
        on_cut=lambda: night_run.abort(MORNING, grace_s=0.0))
    night_run.save_declaration("just the north", calibration_id=cal.id,
                               amend={"items": ["north"]})
    run = _run(_night())
    assert cut["cut"] is True, "the morning event never reached the run"

    assert run.state == night_run.STATE_ENDED_BY_MORNING
    assert "ordinary ending" in run.detail
    assert night_run.status_brief()["ended_by_morning"] is True
    assert run.calibration["applied"] is False
    assert {f.emitter_id: f.weight
            for f in light_field.get_room(room.id).footprints} == before


# ── 7. THE MORNING READ ────────────────────────────────────────────────────

def test_the_morning_read_answers_all_four_questions(monkeypatch):
    """His bar: which calibration ran, what it measured, what changed
    against the previous one, and what waits on him — without asking anyone
    and without reading a log."""
    _camera(monkeypatch)
    cal = _cal(_room())
    cal, _first = _run(calibration_runs.run_calibration(cal))

    night_run.save_declaration("tonight", calibration_id=cal.id)
    _run(_night())

    read = morning_read.build()
    assert "North shelf" in read["ran"], "it did not name the calibration"
    assert "measured 4 fixture parts" in read["measured"]
    assert read["changed"]["available"] is True, \
        "it could not say what changed against the previous run"
    assert read["changed"]["comparable"] is True
    assert read["waiting"] == []
    assert "Nothing waits on you." in read["summary"]


def test_the_morning_read_names_the_unapplied_amendment_and_the_act(
        monkeypatch):
    """The one fact that must never be buried: a cut-short amendment
    measured a great deal and changed nothing, which looks — on every other
    count in the record — exactly like a successful one."""
    _camera(monkeypatch)
    cal = _cal(_room())
    cal, _first = _run(calibration_runs.run_calibration(cal))

    session = _camera(monkeypatch)
    _cut_after_first_footprint(monkeypatch, session)
    night_run.save_declaration("just the north", calibration_id=cal.id,
                               amend={"items": ["north"]})
    _run(_night())

    read = morning_read.build()
    assert "an amendment to 'North shelf'" in read["ran"]
    assert "APPLIED NONE" in read["measured"]
    assert any("Run the amendment" in w for w in read["waiting"])
    assert "still on the previous calibration" in " ".join(read["waiting"])


def test_the_morning_read_says_a_declined_night_declined_and_why(monkeypatch):
    """ABSENCE IS A READ. A night that never ran must not read like one that
    ran and found nothing."""
    _camera(monkeypatch)
    cal = _cal(_room())
    night_run.save_declaration("tonight", calibration_id=cal.id)
    _owner(lo.RELEASED)
    _run(_night())

    read = morning_read.build()
    assert "did not run" in read["ran"]
    assert "does not hold the lights" in read["ran"]
    assert any("ownership bar" in w for w in read["waiting"])
    assert read["changed"]["available"] is False


def test_the_morning_read_with_no_night_at_all_says_that(monkeypatch):
    assert "No night run has happened yet." in morning_read.build()["summary"]
