"""EVERY EXPECTED CONDITION ON THE MAPPING PATH IS A SENTENCE, NOT A 500.

The live failure this is written for (his first real run, 2026-08-31):
`POST /api/rooms/{id}/map` raised `fx_seam.RoomReleased` out of
`room_mapping.live_virtual_ids` and reached him as a bare 500 with a stack
trace — for a condition the system anticipates and the ownership bar fixes
in one press. The bar was already set one module over: `mapping_session`
refuses an unlockable camera BY NAME, saying which browser and which
capability.

What is proved here, condition by condition:

  * a released room, and a handover in flight, refuse with 409 and a
    sentence that says what to do — on the RUN route and on the PLAN route,
    with the same wording (one string, so they cannot drift);
  * an ownership loss MID-RUN ends the run as a stated partial that KEEPS
    what it measured, rather than a column of identical failures;
  * a hold refused by the 3-minute ceiling ends the run with the ceiling's
    own sentence, not the machine word "max_duration";
  * a fixture that dies mid-run is named and the run CARRIES ON;
  * a real bug still raises — no sentence is invented for one.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.models.room_map import AxisCalibration, Point, RoomMap
from spectra.services import fx_seam, mapping_refusals, room_mapping

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))
CARRIER = "tv-mapper"
CHAIN = {CARRIER: [{"id": "tv-backlight", "type": "wled"}]}


def _virtual():
    return {"active": True, "pixel_count": 20, "config": {"grouping": 1},
            "segments": [["tv-backlight", 0, 19, False]],
            "effect": {"type": "singleColor", "config": {}}}


class _Session:
    """The phone, reduced to what a run touches."""
    pose_id = "pose-1"
    run_abort = None

    class lock:
        exposure_locked = True
        white_balance_locked = True
        exposure_mode = "manual"
        white_balance_mode = "manual"

    def __init__(self):
        self._n = 0

    def refusal(self):
        return None

    async def gather(self, seconds, min_frames=1):
        """dark, then lit — alternating, so a footprint has real weight and
        an emitter reads as MAPPED when nothing refused it."""
        import numpy as np
        self._n += 1
        value = 0.0 if self._n % 2 else 0.5
        grid = np.full((36, 64), value, dtype=np.float64)
        return [grid, grid], [10, 10]


def _room(carriers=(CARRIER,)):
    return RoomMap(name="Living room", carrier_ids=list(carriers), axis=AXIS)


def _deps(*, get_virtuals=None, open_hold=None, close_hold=None):
    async def default_virtuals():
        return {CARRIER: _virtual()}

    async def default_open(program, intensity, *, step="fire",
                           heartbeat_timeout_s=0.0):
        return {"held": True}

    async def default_close():
        return None

    async def chains():
        return CHAIN

    async def sleep(_s):
        return None

    return room_mapping.RunDeps(
        session=_Session(), get_virtuals=get_virtuals or default_virtuals,
        carrier_devices=chains, open_hold=open_hold or default_open,
        close_hold=close_hold or default_close, sleep=sleep,
        spectra_owns=lambda: True)


def _run(room, deps, granularity="whole"):
    return asyncio.run(room_mapping.run_mapping(room, deps,
                                                granularity=granularity))


# ── 1. the condition that produced the 500 ─────────────────────────────────

@pytest.mark.parametrize("exc,word", [
    (fx_seam.RoomReleased("released"), "released"),
    (fx_seam.HandoverInProgress("handover"), "changing hands"),
])
def test_an_ownership_state_at_the_start_is_a_stated_refusal(exc, word):
    async def refuse():
        raise exc

    result = _run(_room(), _deps(get_virtuals=refuse))
    assert result.ok is False
    assert result.refusal == "ownership"
    assert word in result.reason
    # the sentence tells him what to do next, which is the whole point
    assert "Start mapping again" in result.reason
    assert result.emitters == []


def test_a_real_bug_still_raises_rather_than_being_given_a_sentence():
    async def boom():
        raise ValueError("a genuine bug")

    with pytest.raises(ValueError):
        _run(_room(), _deps(get_virtuals=boom))


# ── 2. the same wording, over the wire, on both routes ─────────────────────

def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _stored_room(client):
    return client.post("/api/rooms", json={
        "name": "Living room", "carrier_ids": [CARRIER],
        "axis": {"kind": "vertical", "floor": {"x": 0.5, "y": 1.0},
                 "ceiling": {"x": 0.5, "y": 0.0}}}).json()


def test_the_plan_route_refuses_a_released_room_by_name(monkeypatch):
    async def refuse():
        raise fx_seam.RoomReleased("released")

    monkeypatch.setattr(room_mapping, "production_deps",
                        lambda sess: _deps(get_virtuals=refuse))
    with _client() as client:
        room = _stored_room(client)
        r = client.get(f"/api/rooms/{room['id']}/plan")
        assert r.status_code == 409
        body = r.json()
        assert body["refusal"] == "ownership"
        assert body["detail"] == mapping_refusals.ownership_refusal(
            fx_seam.RoomReleased("x"))
        assert "ownership bar" in body["detail"]


def test_the_run_route_refuses_a_released_room_by_name_not_a_500(monkeypatch):
    """The exact shape of his live failure: a 500 with a stack trace becomes
    a 409 with an instruction."""
    from spectra.services import mapping_session

    async def refuse():
        raise fx_seam.RoomReleased("released")

    sess = _Session()
    sess.closed = False
    monkeypatch.setattr(mapping_session, "current", sess)
    monkeypatch.setattr(room_mapping, "production_deps",
                        lambda s: _deps(get_virtuals=refuse))
    with _client() as client:
        room = _stored_room(client)
        r = client.post(f"/api/rooms/{room['id']}/map")
        assert r.status_code == 200, "the run STATES it rather than erroring"
        body = r.json()
        assert body["ok"] is False and body["refusal"] == "ownership"
        assert "Home Assistant" in body["reason"]


def test_the_route_backstops_an_ownership_refusal_from_an_unwrapped_seam(
        monkeypatch):
    """run_mapping states these itself; if one ever reaches the route from a
    seam it does not wrap, the SENTENCE is still what he sees."""
    from spectra.services import mapping_session

    async def blow_up(*_a, **_kw):
        raise fx_seam.RoomReleased("released")

    sess = _Session()
    sess.closed = False
    monkeypatch.setattr(mapping_session, "current", sess)
    monkeypatch.setattr(room_mapping, "run_mapping", blow_up)
    monkeypatch.setattr(room_mapping, "production_deps", lambda s: _deps())
    with _client() as client:
        room = _stored_room(client)
        r = client.post(f"/api/rooms/{room['id']}/map")
        assert r.status_code == 409
        assert r.json()["refusal"] == "ownership"
        assert "ownership bar" in r.json()["detail"]


def test_a_genuine_bug_on_the_run_route_is_not_dressed_up_as_a_refusal(
        monkeypatch):
    from spectra.services import mapping_session

    async def blow_up(*_a, **_kw):
        raise ValueError("a genuine bug")

    sess = _Session()
    sess.closed = False
    monkeypatch.setattr(mapping_session, "current", sess)
    monkeypatch.setattr(room_mapping, "run_mapping", blow_up)
    monkeypatch.setattr(room_mapping, "production_deps", lambda s: _deps())
    with _client() as client:
        room = _stored_room(client)
        with pytest.raises(ValueError):
            client.post(f"/api/rooms/{room['id']}/map")


# ── 3. losing the room MID-run ─────────────────────────────────────────────

def test_a_mid_run_release_is_a_stated_partial_that_keeps_what_it_measured(
        monkeypatch, tmp_path):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "ROOM_MAPS_FILE", tmp_path / "maps.json")
    calls = {"n": 0}

    async def open_hold(program, intensity, *, step="fire",
                        heartbeat_timeout_s=0.0):
        calls["n"] += 1
        if calls["n"] > 2:          # the first emitter's dark+lit succeed
            raise fx_seam.RoomReleased("released mid-run")
        return {"held": True}

    closed = {"n": 0, "raised": 0}

    async def close_hold():
        closed["n"] += 1
        if calls["n"] > 2:
            # the revert write is refused too — this must not become a 500
            closed["raised"] += 1
            raise fx_seam.RoomReleased("released mid-run")

    async def two_virtuals():
        return {CARRIER: _virtual(), "hues": _virtual()}

    deps = _deps(get_virtuals=two_virtuals, open_hold=open_hold,
                 close_hold=close_hold)
    deps.carrier_devices = _deps().carrier_devices

    async def chains():
        return {CARRIER: CHAIN[CARRIER],
                "hues": [{"id": "hue-lights", "type": "hue"}]}

    deps.carrier_devices = chains
    room = _room((CARRIER, "hues"))
    result = _run(room, deps)

    assert result.refusal == "ownership"
    assert result.reason == mapping_refusals.MID_RUN_LOSS
    assert result.ok is False, "a run that stopped is never 'ok'"
    assert result.partial is True, "but what it measured is kept, and said"
    assert [e.mapped for e in result.emitters] == [True, False]
    assert room.mapped_carriers() == [CARRIER], "the footprint survives"
    assert closed["raised"] == 1, "the refused revert was swallowed, not raised"


def test_the_hold_ceiling_ends_the_run_with_its_own_sentence():
    async def at_the_ceiling(program, intensity, *, step="fire",
                             heartbeat_timeout_s=0.0):
        return {"held": False, "expired": True, "reason": "max_duration"}

    async def two_virtuals():
        return {CARRIER: _virtual(), "hues": _virtual()}

    async def chains():
        return {CARRIER: CHAIN[CARRIER],
                "hues": [{"id": "hue-lights", "type": "hue"}]}

    deps = _deps(get_virtuals=two_virtuals, open_hold=at_the_ceiling)
    deps.carrier_devices = chains
    result = _run(_room((CARRIER, "hues")), deps)

    assert result.refusal == "hold_ceiling"
    assert result.reason == mapping_refusals.HOLD_CEILING
    assert "three minutes" in result.reason
    assert "max_duration" not in result.reason
    assert len(result.emitters) == 1, (
        "the run stops rather than repeating one sentence per emitter")


def test_a_fixture_that_dies_mid_run_is_named_and_the_run_carries_on(tmp_path,
                                                                     monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "ROOM_MAPS_FILE", tmp_path / "maps.json")
    calls = {"n": 0}

    async def open_hold(program, intensity, *, step="fire",
                        heartbeat_timeout_s=0.0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("no route to host")
        return {"held": True}

    async def two_virtuals():
        return {CARRIER: _virtual(), "hues": _virtual()}

    async def chains():
        return {CARRIER: CHAIN[CARRIER],
                "hues": [{"id": "hue-lights", "type": "hue"}]}

    deps = _deps(get_virtuals=two_virtuals, open_hold=open_hold)
    deps.carrier_devices = chains
    result = _run(_room((CARRIER, "hues")), deps)

    assert len(result.emitters) == 2, "the neighbours were still measured"
    assert result.refusal == "", "one dead fixture does not end the run"
    dead = result.emitters[0]
    assert dead.mapped is False
    assert "could not be measured" in dead.reason
    assert "no route to host" in dead.reason
    assert result.emitters[1].mapped is True


# ── 4. the wordings are ONE string each ────────────────────────────────────

def test_every_refusal_sentence_says_what_to_do_next():
    from spectra.services import fx_seam as seam
    sentences = [
        mapping_refusals.ownership_refusal(seam.RoomReleased("x")),
        mapping_refusals.ownership_refusal(seam.HandoverInProgress("x")),
        mapping_refusals.MID_RUN_LOSS,
        mapping_refusals.HOLD_CEILING,
        mapping_refusals.hold_refusal("no writes"),
    ]
    for text in sentences:
        assert text and text[0].isupper() and text.endswith(".")
        assert "again" in text or "Check" in text
        # never an exception class or a machine word
        assert "Error" not in text and "_" not in text


def test_a_non_ownership_exception_is_not_claimed_as_one():
    assert mapping_refusals.ownership_refusal(ValueError("x")) is None
    assert mapping_refusals.ownership_refusal(OSError("x")) is None
