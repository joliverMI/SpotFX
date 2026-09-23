"""TWO OF THE FOUR FIXES FROM `data/kiosk-exposure-lever-no-response/
report.md`: a calibration must refuse while the show engine is animating
the room, and a calibration may name which emitter its lever self-test
measures rather than always inheriting the run's own first one.

Both drive the REAL calibration orchestration (`calibration_runs.
run_calibration`) against the synthetic camera `tests/test_pose_fingerprint.py`
builds — nothing here touches a room, a light or a webcam.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.models.calibration import Calibration, PinnedCamera
from spectra.models.room_map import RoomMap
from spectra.services import (calibration_runs, calibration_store,
                              capture_queue, capture_runs, lever_selftest,
                              light_field, mapping_refusals, room_mapping)
from tests.test_pose_fingerprint import AXIS, CARRIERS, SPREAD_ROOM, _Session, _deps


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(calibration_runs, "SESSION_WAIT_S", 0.0)


@pytest.fixture(autouse=True)
def _camera(monkeypatch):
    _wire(monkeypatch, _Session(SPREAD_ROOM))


def _wire(monkeypatch, session):
    from spectra.services import mapping_session
    monkeypatch.setattr(mapping_session, "current", session)
    monkeypatch.setattr(room_mapping, "production_deps",
                        lambda sess: _deps(session,
                                           save_room=light_field.put_room))
    return session


def _room():
    return light_field.put_room(
        RoomMap(name="Lounge", carrier_ids=list(CARRIERS), axis=AXIS))


def _cal(room, *, items=None, lever_scope=None, name="North shelf"):
    cal = Calibration(name=name, room_id=room.id, camera=PinnedCamera(),
                      items=items if items is not None else
                      [{"kind": "map", "room_id": room.id,
                        "granularity": "whole"}],
                      lever_scope=lever_scope or {})
    cal.pose.placement = "the north shelf"
    return calibration_store.save(cal)


def _run(cal, **kw):
    return asyncio.run(calibration_runs.run_calibration(cal, **kw))


# ── the engine-live refusal ─────────────────────────────────────────────

def test_a_calibration_refuses_while_the_engine_is_live(monkeypatch):
    """The 2026-09-23 finding, generalised: the drift conductor's own leg
    lit the crystal and 17 Hue bulbs in the middle of a self-test's dark/lit
    windows because the night's ORDINARY handover went live. Nothing here
    is measured or written."""
    from spectra.services import engine
    monkeypatch.setattr(engine, "status", lambda: {"dark": False})
    room = _room()
    cal = _cal(room)
    cal, entry = _run(cal)
    assert entry.status == capture_runs.STATUS_REFUSED
    assert entry.refusal == "engine_live"
    assert "engine is live" in entry.detail
    assert "quiet" in entry.detail.lower(), (
        "the refusal names the way out")
    assert entry.items == [], "nothing was measured"


def test_a_calibration_runs_normally_while_the_engine_is_dark(monkeypatch):
    from spectra.services import engine
    monkeypatch.setattr(engine, "status", lambda: {"dark": True})
    room = _room()
    cal = _cal(room)
    cal, entry = _run(cal)
    assert entry.status == capture_runs.STATUS_OK
    assert entry.refusal != "engine_live"


def test_a_status_call_that_cannot_answer_never_refuses_on_its_own_silence():
    """"We could not check" is not "we checked and it is live" — the same
    discipline every other verdict in this codebase stands on
    (`lever_selftest`'s own UNPROVABLE/UNPROVEN)."""
    assert calibration_runs._engine_live() is False   # noqa: SLF001


# ── the lever self-test scope, named per calibration ────────────────────

def test_with_no_lever_scope_the_self_test_drives_the_runs_own_first_emitter():
    """BYTE-IDENTICAL TO BEFORE THIS FIELD EXISTED — the whole-room default,
    unscoped, drives `plan.emitters[0]`."""
    room = _room()
    cal = _cal(room)
    cal, entry = _run(cal)
    assert entry.status == capture_runs.STATUS_OK
    assert entry.lever.get("emitter_id") == "north"


def test_a_named_lever_scope_overrides_it():
    """His kitchen kiosk sees the Living Room's own default emitter as a
    near-invisible smear — this is the setting that lets a calibration
    name a legible one instead, without changing what the run itself maps."""
    room = _room()
    cal = _cal(room, lever_scope={"carrier_ids": ["east"]})
    cal, entry = _run(cal)
    assert entry.status == capture_runs.STATUS_OK
    assert entry.lever.get("emitter_id") == "east"


def test_a_lever_scope_by_emitter_id_also_overrides_it():
    room = _room()
    cal = _cal(room, lever_scope={"emitter_ids": ["south"]})
    cal, entry = _run(cal)
    assert entry.status == capture_runs.STATUS_OK
    assert entry.lever.get("emitter_id") == "south"


def test_the_lever_scope_never_narrows_what_the_run_itself_maps():
    """The self-test's own emitter is a completely separate question from
    which emitters the map actually measures — a calibration naming "east"
    for the lever still maps the WHOLE declared room."""
    room = _room()
    cal = _cal(room, lever_scope={"carrier_ids": ["east"]})
    cal, entry = _run(cal)
    assert entry.status == capture_runs.STATUS_OK
    measured = set(entry.items[0].emitters)
    assert measured == set(CARRIERS), (
        "every carrier was still mapped, regardless of the lever scope")


# ── the pure helper, in isolation ────────────────────────────────────────

def test_lever_scope_helper_is_none_when_the_calibration_names_nothing():
    cal = Calibration(name="x", room_id="r")
    assert calibration_runs._lever_scope(cal) is None   # noqa: SLF001


def test_lever_scope_helper_builds_a_real_scope_from_the_field():
    cal = Calibration(name="x", room_id="r",
                      lever_scope={"emitter_ids": ["sconce-left"]})
    scope = calibration_runs._lever_scope(cal)           # noqa: SLF001
    assert isinstance(scope, lever_selftest.Scope)
    assert scope.emitter_ids == ("sconce-left",)
