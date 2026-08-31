"""Route-shape proofs for spectra/api/room_effects.py and the room half of
spectra/api/rooms.py: the store round-trips, the kind gate refuses the three
UNBUILT field kinds by name rather than accepting a spec that could never
run, and a start against an unmapped room refuses honestly.

The capture and the wave themselves are proven end to end by the check
scripts (tests/test_light_field_checks.py); this file is about the wire."""
from __future__ import annotations

import pytest


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


AXIS = {"kind": "vertical", "floor": {"x": 0.5, "y": 1.0},
        "ceiling": {"x": 0.5, "y": 0.0}}


def _room(client, devices=("sconce-left",)):
    r = client.post("/api/rooms", json={"name": "Kitchen wall",
                                        "carrier_ids": list(devices),
                                        "axis": AXIS})
    assert r.status_code == 200, r.text
    return r.json()


# ── rooms ─────────────────────────────────────────────────────────────────

def test_a_room_round_trips_and_reports_what_is_not_mapped():
    with _client() as client:
        room = _room(client)
        assert room["unmapped_ids"] == ["sconce-left"]
        assert room["mapped_ids"] == []
        assert room["axis"]["floor"]["y"] == 1.0
        listing = client.get("/api/rooms").json()["rooms"]
        assert [r["id"] for r in listing] == [room["id"]]


def test_editing_a_room_keeps_its_footprints_but_a_removed_device_loses_its():
    """A measurement took a dark room to collect: renaming a room or adding
    a device must not silently discard one. Removing the device it belongs
    to is a different matter — it is no longer part of this room."""
    from spectra.models.room_map import GRID_H, GRID_W, EmitterFootprint
    from spectra.services import light_field
    with _client() as client:
        room = _room(client, devices=("a", "b"))
        stored = light_field.get_room(room["id"])
        grid = [1.0] * (GRID_W * GRID_H)
        for eid in ("a", "b"):
            stored.put_footprint(EmitterFootprint(emitter_id=eid, grid=grid,
                                                  weight=1.0))
        light_field.put_room(stored)

        renamed = client.post("/api/rooms", json={
            "id": room["id"], "name": "Kitchen wall 2",
            "carrier_ids": ["a", "b"], "axis": AXIS}).json()
        assert sorted(renamed["mapped_ids"]) == ["a", "b"]

        dropped = client.post("/api/rooms", json={
            "id": room["id"], "name": "Kitchen wall 2",
            "carrier_ids": ["a"], "axis": AXIS}).json()
        assert dropped["mapped_ids"] == ["a"]


def test_deleting_a_room_takes_its_map_with_it():
    with _client() as client:
        room = _room(client)
        assert client.delete(f"/api/rooms/{room['id']}").status_code == 200
        assert client.get("/api/rooms").json()["rooms"] == []
        assert client.delete(f"/api/rooms/{room['id']}").status_code == 404


def test_a_run_with_no_phone_is_refused_by_name():
    with _client() as client:
        room = _room(client)
        r = client.post(f"/api/rooms/{room['id']}/map")
        assert r.status_code == 409
        assert "no phone connected" in r.json()["detail"]


def test_the_frame_view_404s_with_no_session():
    with _client() as client:
        assert client.get("/api/rooms/map/frame/latest").status_code == 404
        status = client.get("/api/rooms/map/status").json()
        assert status["session"] is None
        assert status["protocol"]["lit_capture_s"] > 0


# ── room effects ──────────────────────────────────────────────────────────

def test_the_catalogue_says_which_kinds_are_built():
    with _client() as client:
        body = client.get("/api/room-effects").json()
        assert body["kinds"]["dim_wave"]["built"] is True
        assert [k for k, v in body["kinds"].items() if v["built"]] == ["dim_wave"]
        assert body["tick_hz"] >= 10.0


@pytest.mark.parametrize("kind", ["hue_rotation", "implode", "explode"])
def test_an_unbuilt_kind_is_refused_by_name_not_stored(kind):
    """The three kinds the INTERFACE serves but this slice does not build
    must not be authorable — a stored spec that could never run is a trap,
    and his instruction was to build the interface, not the UI."""
    with _client() as client:
        room = _room(client)
        r = client.post("/api/room-effects", json={"room_id": room["id"],
                                                   "kind": kind})
        assert r.status_code == 400
        assert "not built in this slice" in r.json()["detail"]
        assert client.get("/api/room-effects").json()["effects"] == []


def test_an_effect_round_trips_and_clamps_its_knobs():
    with _client() as client:
        room = _room(client)
        made = client.post("/api/room-effects", json={
            "room_id": room["id"], "name": "Kitchen wave", "kind": "dim_wave",
            "wavelength": 0.6, "speed": -0.4, "depth": 0.5,
            "carrier_ids": ["sconce-left"]}).json()
        assert made["id"] and made["speed"] == -0.4
        again = client.post("/api/room-effects", json={**made, "depth": 0.9}).json()
        assert again["id"] == made["id"] and again["depth"] == 0.9
        assert len(client.get("/api/room-effects").json()["effects"]) == 1
        assert client.delete(f"/api/room-effects/{made['id']}").status_code == 200
        assert client.get("/api/room-effects").json()["effects"] == []


def test_an_effect_for_a_room_that_does_not_exist_is_refused():
    with _client() as client:
        r = client.post("/api/room-effects", json={"room_id": "nope"})
        assert r.status_code == 404


def test_starting_an_effect_on_an_unmapped_room_refuses_and_names_the_devices():
    with _client() as client:
        room = _room(client)
        made = client.post("/api/room-effects", json={
            "room_id": room["id"], "carrier_ids": ["sconce-left"]}).json()
        r = client.post(f"/api/room-effects/{made['id']}/start")
        assert r.status_code == 409
        body = r.json()
        assert "map the room first" in body["reason"]
        assert body["unmapped"] == ["sconce-left"]


def test_status_reports_nothing_running_and_a_zeroed_cost():
    with _client() as client:
        body = client.get("/api/room-effects/status").json()
        assert body["running"] is False and body["gains"] == {}
        assert body["cost"]["samples"] == 0
        assert body["held_params"] == []


def test_stop_is_idempotent():
    with _client() as client:
        assert client.post("/api/room-effects/stop").json() == {
            "stopped": False, "deactivated": []}
