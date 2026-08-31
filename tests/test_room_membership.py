"""THE TWO PER-MEMBER CONTROLS on the Rooms page, and the fact that they
are two different acts.

  REMOVE FROM ROOM   membership. The device leaves THIS room; the device
                     itself, its configuration and its place in every other
                     room are untouched. Never a device delete — there is
                     no device delete in this app.
  DESELECT           participation. The device stays in the room with
                     everything it has measured, and sits out: skipped by a
                     mapping run's emitter enumeration, and not offered to
                     a room effect. Re-selecting restores it with nothing
                     to re-measure.

The composition of the two selection layers is proven here too, because it
is the one place they could quietly disagree: the ROOM decides what is
offered, the per-effect chips choose among that, and a deselected member is
not driven even by an effect that names it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra.models.room_map import (GRID_H, GRID_W, AxisCalibration,
                                     EmitterFootprint, PixelRange, Point,
                                     RoomMap)
from spectra.services import light_field, room_effects
from spectra.services.light_field_fields import DimWave

DEVICE = "tv-mapper"
OTHER = "sconce-left"
VIRTUAL = "tv-mapper-v"
OTHER_VIRTUAL = "sconce-left-v"
PIXELS = 60
SEG = 20
AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))
AXIS_BODY = {"kind": "vertical", "floor": {"x": 0.5, "y": 1.0},
             "ceiling": {"x": 0.5, "y": 0.0}}


def _virtual(device_id=DEVICE, pixel_count=PIXELS, segments=None):
    return {"active": True, "pixel_count": pixel_count,
            "config": {"mapping": "span", "grouping": 1},
            "segments": segments if segments is not None else [
                [device_id, 0, SEG - 1, False],
                [device_id, SEG, 2 * SEG - 1, False],
                [device_id, 2 * SEG, pixel_count - 1, False]],
            "effect": {"type": "singleColor", "config": {}}}


def _fp(emitter_id: str, lo: float, hi: float, vids: list[str],
        device_id: str = "", ranges=None) -> EmitterFootprint:
    grid = np.zeros((GRID_H, GRID_W))
    y0 = int(round((1.0 - hi) * GRID_H))
    y1 = max(y0 + 1, int(round((1.0 - lo) * GRID_H)))
    grid[y0:y1, :] = 1.0
    return EmitterFootprint(emitter_id=emitter_id, virtual_ids=vids,
                            device_id=device_id, ranges=ranges or [],
                            grid=[float(v) for v in grid.reshape(-1)],
                            weight=float(grid.sum()))


def _room() -> RoomMap:
    room = RoomMap(name="Living room", device_ids=[DEVICE, OTHER], axis=AXIS)
    room.put_footprint(_fp(DEVICE, 0.0, 0.4, [VIRTUAL], DEVICE))
    room.put_footprint(_fp(OTHER, 0.6, 1.0, [OTHER_VIRTUAL], OTHER))
    return room


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


# ── 1. the model: two different acts, and a list that stays a subset ───────

def test_deselect_keeps_membership_and_everything_measured():
    room = _room()
    assert room.selected_device_ids() == [DEVICE, OTHER]
    assert room.set_selected(DEVICE, False) is True
    assert DEVICE in room.device_ids, "deselect must not touch membership"
    assert room.selected_device_ids() == [OTHER]
    assert room.is_selected(DEVICE) is False
    assert room.footprint(DEVICE) is not None, "a sitting-out fixture keeps its map"
    # re-select restores, with nothing to re-measure
    assert room.set_selected(DEVICE, True) is True
    assert room.selected_device_ids() == [DEVICE, OTHER]
    assert room.footprint(DEVICE) is not None
    # idempotent both ways
    assert room.set_selected(DEVICE, True) is False


def test_remove_edits_this_room_only_and_nothing_else():
    room = _room()
    room.set_selected(DEVICE, False)
    assert room.remove_device(DEVICE) is True
    assert room.device_ids == [OTHER]
    assert room.footprint(DEVICE) is None, (
        "a footprint measures what a device does in THIS room")
    assert room.footprint(OTHER) is not None, "the other member is untouched"
    # the deselect list never keeps a stale entry that would come back to
    # life the moment the device was re-added
    assert room.deselected_device_ids == []
    assert room.remove_device(DEVICE) is False


def test_a_non_member_is_never_recorded_as_deselected():
    room = _room()
    assert room.set_selected("not-in-this-room", False) is False
    assert room.deselected_device_ids == []


def test_the_field_is_additive_so_a_stored_room_means_what_it_did():
    """Nothing on disk carries this field. A room loaded without it must
    read as every member taking part."""
    room = RoomMap.model_validate({"id": "abc", "name": "Old",
                                   "device_ids": [DEVICE, OTHER]})
    assert room.deselected_device_ids == []
    assert room.selected_device_ids() == [DEVICE, OTHER]


# ── 2. a mapping run skips a deselected member's emitters entirely ─────────

def _deps(monkeypatch, room_mapping):
    async def get_virtuals():
        return {VIRTUAL: _virtual(),
                OTHER_VIRTUAL: _virtual(OTHER, pixel_count=1, segments=[])}

    async def virtuals_for_device(device_id):
        return {DEVICE: [VIRTUAL], OTHER: [OTHER_VIRTUAL]}.get(device_id, [])

    async def device_type(_device_id):
        return "wled"

    def fake_deps(session):
        return room_mapping.RunDeps(
            session=session, get_virtuals=get_virtuals,
            virtuals_for_device=virtuals_for_device, device_type=device_type)

    monkeypatch.setattr(room_mapping, "production_deps", fake_deps)
    monkeypatch.setattr(room_mapping, "spectra_owns_lights", lambda: True)
    return fake_deps


def test_a_deselected_member_is_not_enumerated_by_a_run(monkeypatch):
    """The property that matters at the light: a sitting-out fixture is not
    in the emitter list, so a run never lights it AND never overwrites what
    it already measured. Re-selecting brings it back with no re-map."""
    from spectra.services import room_mapping
    _deps(monkeypatch, room_mapping)
    with _client() as client:
        room = client.post("/api/rooms", json={
            "name": "Living room", "device_ids": [DEVICE, OTHER],
            "axis": AXIS_BODY}).json()
        rid = room["id"]
        full = client.get(f"/api/rooms/{rid}/plan?granularity=segment").json()
        assert {e["device_id"] for e in full["emitters"]} == {DEVICE, OTHER}
        before = full["count"]

        client.post(f"/api/rooms/{rid}/devices/{DEVICE}/selected",
                    json={"selected": False})
        narrowed = client.get(f"/api/rooms/{rid}/plan?granularity=segment").json()
        assert {e["device_id"] for e in narrowed["emitters"]} == {OTHER}
        assert narrowed["count"] < before
        assert DEVICE not in narrowed["per_device"]
        # the room still has it, and still says so
        listed = client.get("/api/rooms").json()["rooms"][0]
        assert DEVICE in listed["device_ids"]
        assert listed["deselected_device_ids"] == [DEVICE]
        assert listed["selected_device_ids"] == [OTHER]

        client.post(f"/api/rooms/{rid}/devices/{DEVICE}/selected",
                    json={"selected": True})
        restored = client.get(f"/api/rooms/{rid}/plan?granularity=segment").json()
        assert restored["count"] == before


def test_a_run_with_every_member_deselected_refuses_by_name(monkeypatch):
    """Never a silent nothing: a room whose members are all sitting out
    says so rather than reporting an empty success."""
    import asyncio

    from spectra.services import room_mapping
    fake_deps = _deps(monkeypatch, room_mapping)

    room = _room()
    room.set_selected(DEVICE, False)
    room.set_selected(OTHER, False)

    class _Sess:
        pose_id = "p"
        run_abort = None

        def refusal(self):
            return ""

    result = asyncio.run(room_mapping.run_mapping(room, fake_deps(_Sess())))
    assert result.ok is False
    assert "deselected" in result.reason


# ── 3. the effect pool, and how the two selection layers compose ───────────

def test_a_deselected_member_is_not_offered_to_a_room_effect():
    room = _room()
    spec = room_effects.RoomEffectSpec(room_id=room.id)
    assert {d.emitter_id for d in room_effects.resolve_driven(room, spec)} == {
        DEVICE, OTHER}
    room.set_selected(DEVICE, False)
    assert {d.emitter_id for d in room_effects.resolve_driven(room, spec)} == {
        OTHER}
    room.set_selected(DEVICE, True)
    assert {d.emitter_id for d in room_effects.resolve_driven(room, spec)} == {
        DEVICE, OTHER}


def test_room_level_deselect_wins_over_an_effects_own_chips():
    """The stated composition: the ROOM decides what is offered, the
    per-effect chips choose among it. An effect that names a sitting-out
    fixture does not get it — otherwise "sitting out" would mean one thing
    on the Rooms page and another inside a forgotten effect."""
    room = _room()
    spec = room_effects.RoomEffectSpec(room_id=room.id,
                                       device_ids=[DEVICE, OTHER])
    room.set_selected(DEVICE, False)
    driven = room_effects.resolve_driven(room, spec)
    assert {d.emitter_id for d in driven} == {OTHER}


def test_the_per_effect_chips_still_choose_among_what_the_room_offers():
    """The other half: room-level deselect must not have flattened the
    per-effect layer into a no-op."""
    room = _room()
    spec = room_effects.RoomEffectSpec(room_id=room.id, device_ids=[OTHER])
    assert {d.emitter_id for d in room_effects.resolve_driven(room, spec)} == {
        OTHER}


def test_starting_an_effect_on_an_all_deselected_room_says_why():
    import asyncio
    room = _room()
    room.set_selected(DEVICE, False)
    room.set_selected(OTHER, False)
    async def _noop(*_a, **_k):
        return {}

    deps = room_effects.RunnerDeps(apply_writes=_noop, get_virtuals=_noop,
                                   spectra_owns=lambda: True)
    out = asyncio.run(room_effects.start(
        room, room_effects.RoomEffectSpec(room_id=room.id), deps))
    assert out["running"] is False
    assert "deselected" in out["reason"]


def test_a_sub_device_member_sits_out_as_a_whole():
    """Participation is per DEVICE, so a strip mapped per segment sits out
    with every one of its ranges, never partly."""
    room = RoomMap(name="R", device_ids=[DEVICE, OTHER], axis=AXIS)
    for i in range(3):
        room.put_footprint(_fp(
            f"{DEVICE}:seg{i}[{i * SEG}-{(i + 1) * SEG - 1}]",
            i * 0.3, i * 0.3 + 0.3, [VIRTUAL], DEVICE,
            [PixelRange(virtual_id=VIRTUAL, start=i * SEG,
                        end=(i + 1) * SEG - 1)]))
    room.put_footprint(_fp(OTHER, 0.6, 1.0, [OTHER_VIRTUAL], OTHER))
    spec = room_effects.RoomEffectSpec(room_id=room.id)
    assert len(room_effects.resolve_driven(room, spec)) == 4
    room.set_selected(DEVICE, False)
    assert [d.emitter_id for d in room_effects.resolve_driven(room, spec)] == [
        OTHER]


# ── 4. the wire ───────────────────────────────────────────────────────────

def test_removing_a_member_over_the_wire_edits_this_room_only():
    with _client() as client:
        a = client.post("/api/rooms", json={
            "name": "Living room", "device_ids": [DEVICE, OTHER],
            "axis": AXIS_BODY}).json()
        b = client.post("/api/rooms", json={
            "name": "Kitchen", "device_ids": [DEVICE], "axis": AXIS_BODY}).json()
        stored = light_field.get_room(a["id"])
        stored.put_footprint(_fp(DEVICE, 0.0, 0.4, [VIRTUAL], DEVICE))
        stored.put_footprint(_fp(OTHER, 0.6, 1.0, [OTHER_VIRTUAL], OTHER))
        light_field.put_room(stored)

        out = client.delete(f"/api/rooms/{a['id']}/devices/{DEVICE}")
        assert out.status_code == 200
        room = out.json()["room"]
        assert room["device_ids"] == [OTHER]
        assert [f["emitter_id"] for f in room["footprints"]] == [OTHER]

        # the OTHER room's membership of the same device is untouched: this
        # is a room edit, never a device delete
        kitchen = light_field.get_room(b["id"])
        assert kitchen.device_ids == [DEVICE]

        assert client.delete(
            f"/api/rooms/{a['id']}/devices/{DEVICE}").status_code == 404
        assert client.delete(
            f"/api/rooms/nope/devices/{DEVICE}").status_code == 404


def test_an_ordinary_room_save_never_re_selects_a_sitting_out_member():
    """The page saves a room for a dozen unrelated reasons (a rename, an
    axis tap). None of them may quietly put a fixture he sat out back into
    every run."""
    with _client() as client:
        room = client.post("/api/rooms", json={
            "name": "Living room", "device_ids": [DEVICE, OTHER],
            "axis": AXIS_BODY}).json()
        client.post(f"/api/rooms/{room['id']}/devices/{DEVICE}/selected",
                    json={"selected": False})
        renamed = client.post("/api/rooms", json={
            "id": room["id"], "name": "The lounge",
            "device_ids": [DEVICE, OTHER]}).json()
        assert renamed["deselected_device_ids"] == [DEVICE]
        # and unpicking the device from the chips drops the stale entry
        unpicked = client.post("/api/rooms", json={
            "id": room["id"], "name": "The lounge", "device_ids": [OTHER]}).json()
        assert unpicked["deselected_device_ids"] == []


def test_selecting_a_device_that_is_not_in_the_room_is_a_404():
    with _client() as client:
        room = client.post("/api/rooms", json={
            "name": "Living room", "device_ids": [OTHER],
            "axis": AXIS_BODY}).json()
        assert client.post(
            f"/api/rooms/{room['id']}/devices/{DEVICE}/selected",
            json={"selected": False}).status_code == 404
