"""Route-shape proofs for spectra/api/calibrations.py.

The calibration RECORD and the pose fingerprint are proven where they live
(tests/test_calibration_record.py, tests/test_pose_fingerprint.py). This
file is about the wire: what a caller can declare, what is refused at
declaration rather than at 3 am, what an edit does to the lineage, and the
one route that deliberately does not exist.
"""
from __future__ import annotations

import pytest

from spectra.services import calibration_store, pose_fingerprint


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


AXIS = {"kind": "vertical", "floor": {"x": 0.5, "y": 1.0},
        "ceiling": {"x": 0.5, "y": 0.0}}


def _room(client, carriers=("north", "east")):
    r = client.post("/api/rooms", json={"name": "Lounge",
                                        "carrier_ids": list(carriers),
                                        "axis": AXIS})
    assert r.status_code == 200, r.text
    return r.json()


def _create(client, room, **kw):
    body = {"name": "North shelf", "room_id": room["id"],
            "placement": "the north shelf",
            "items": [{"kind": "map", "room_id": room["id"],
                       "granularity": "whole"}]}
    body.update(kw)
    return client.post("/api/calibrations", json=body)


# ── 1. create / get / list ─────────────────────────────────────────────────

def test_a_calibration_round_trips_and_lists():
    with _client() as client:
        room = _room(client)
        made = _create(client, room)
        assert made.status_code == 200, made.text
        body = made.json()
        assert body["name"] == "North shelf"
        assert body["pose"]["placement"] == "the north shelf"
        assert body["ran"] is False
        assert body["pose_established"] is False
        got = client.get(f"/api/calibrations/{body['id']}").json()
        assert got["id"] == body["id"]
        listing = client.get("/api/calibrations").json()
        assert [c["id"] for c in listing["calibrations"]] == [body["id"]]
        # The pose fingerprint's own pre-registered tolerances are PUBLISHED,
        # so a page never hard-codes one and a reader can check the
        # judgement's arithmetic rather than believe it.
        assert listing["fingerprint"]["centroid_tolerance"] == \
            pose_fingerprint.CENTROID_TOLERANCE
        assert listing["fingerprint"]["min_discriminating"] == \
            pose_fingerprint.MIN_DISCRIMINATING


def test_a_missing_calibration_is_a_404():
    with _client() as client:
        assert client.get("/api/calibrations/nope").status_code == 404
        assert client.put("/api/calibrations/nope",
                          json={"name": "x"}).status_code == 404


def test_a_calibration_needs_a_room_that_exists():
    """A calibration is a pose IN a room; one pointing at nothing could
    never be run."""
    with _client() as client:
        r = client.post("/api/calibrations",
                        json={"name": "orphan", "room_id": "no-such-room"})
        assert r.status_code == 400
        assert "no room" in r.json()["detail"]


def test_a_calibration_needs_a_name():
    with _client() as client:
        room = _room(client)
        r = _create(client, room, name="  ")
        assert r.status_code == 400


# ── 2. ONE VALIDATOR, NEVER A SECOND ───────────────────────────────────────

@pytest.mark.parametrize("bad,says", [
    ([{"kind": "nope", "room_id": "r"}], "kind must be"),
    ([{"kind": "map"}], "room_id is required"),
    ([{"kind": "map", "room_id": "r", "granularty": "whole"}], "granularty"),
])
def test_a_declared_item_is_refused_at_declaration_by_the_queues_own_validator(
        bad, says):
    """`capture_queue.parse_items` is the ONE validator: a declaration with
    a typo in it fails HERE, with the item named, not at 3 am on the item
    nobody reads."""
    with _client() as client:
        room = _room(client)
        r = _create(client, room, items=bad)
        assert r.status_code == 400
        assert says in r.json()["detail"]
        assert calibration_store.load_all() == []


def test_a_bad_edit_is_refused_and_changes_nothing():
    with _client() as client:
        room = _room(client)
        cal = _create(client, room).json()
        r = client.put(f"/api/calibrations/{cal['id']}",
                       json={"items": [{"kind": "map"}]})
        assert r.status_code == 400
        after = client.get(f"/api/calibrations/{cal['id']}").json()
        assert after["items"] == cal["items"]
        assert after["runs"] == []


# ── 3. editing the declaration keeps lineage ───────────────────────────────

def test_an_edit_is_recorded_as_an_entry_and_never_touches_a_past_run():
    with _client() as client:
        room = _room(client)
        cal = _create(client, room).json()
        r = client.put(f"/api/calibrations/{cal['id']}", json={
            "name": "West shelf",
            "placement": "the west shelf",
            "camera": {"exposure_time": 400},
            "envelope": {"dark_required": True, "window": "night",
                         "note": "after the blinds close"},
            "items": [{"kind": "map", "room_id": room["id"],
                       "granularity": "blocks"},
                      {"kind": "commission", "room_id": room["id"],
                       "per_fixture": True}]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "West shelf"
        assert body["camera"]["exposure_time"] == 400
        assert len(body["items"]) == 2
        assert len(body["runs"]) == 1
        entry = body["runs"][0]
        assert entry["kind"] == "declaration"
        assert any("declared items: 1 -> 2" in n for n in entry["notes"])
        assert any("exposure time" in n for n in entry["notes"])
        # AN EDIT IS NOT A RUN.
        assert body["ran"] is False


def test_an_edit_that_changes_nothing_records_nothing():
    with _client() as client:
        room = _room(client)
        cal = _create(client, room).json()
        r = client.put(f"/api/calibrations/{cal['id']}",
                       json={"name": "North shelf"})
        assert r.json()["changed"] == []
        assert r.json()["runs"] == []


# ── 3b. THE TAG REGISTRY — storage only, and measured not nominal ──────────

def test_the_tag_registry_round_trips_and_defaults_to_empty():
    """Its arrival changed nothing: a calibration declared without tags has
    an empty registry, not a missing field."""
    with _client() as client:
        room = _room(client)
        plain = _create(client, room).json()
        assert plain["tags"] == []
        tagged = _create(client, room, name="With tags", tags=[
            {"tag_id": 7, "measured_side_mm": 97.4,
             "mount": "the left window frame"},
            {"tag_id": 12, "measured_side_mm": 149.2, "mount": "the door"}]).json()
        assert [t["tag_id"] for t in tagged["tags"]] == [7, 12]
        assert tagged["tags"][0]["measured_side_mm"] == 97.4
        assert tagged["tags"][0]["mount"] == "the left window frame"
        back = client.get(f"/api/calibrations/{tagged['id']}").json()
        assert back["tags"] == tagged["tags"]
        row = [c for c in client.get("/api/calibrations").json()["calibrations"]
               if c["id"] == tagged["id"]][0]
        assert row["tags"] == 2


def test_a_side_that_is_not_a_measurement_is_refused():
    """Zero and negative are not measurements. `TagRegistration` refuses
    them at the model, which is where an invariant the store must never hold
    belongs."""
    with _client() as client:
        room = _room(client)
        for bad in (0, -3.5):
            r = _create(client, room, tags=[{"tag_id": 1,
                                             "measured_side_mm": bad}])
            assert r.status_code == 422, (bad, r.text)
        assert calibration_store.load_all() == []


def test_one_physical_tag_cannot_be_registered_twice():
    """Two sizes for one tag is a contradiction, and the one that lost would
    silently scale every pose it anchored."""
    with _client() as client:
        room = _room(client)
        r = _create(client, room, tags=[
            {"tag_id": 7, "measured_side_mm": 97.4},
            {"tag_id": 7, "measured_side_mm": 100.0}])
        assert r.status_code == 400
        assert "registered twice" in r.json()["detail"]
        assert "silently scale" in r.json()["detail"]
        assert calibration_store.load_all() == []


def test_re_measuring_a_tag_is_recorded_in_the_lineage():
    """He measures after printing; if he measures again, the record says so
    — the size IS the fact this registry exists to hold."""
    with _client() as client:
        room = _room(client)
        cal = _create(client, room, tags=[
            {"tag_id": 7, "measured_side_mm": 100.0, "mount": "the shelf"}]).json()
        r = client.put(f"/api/calibrations/{cal['id']}", json={"tags": [
            {"tag_id": 7, "measured_side_mm": 97.4, "mount": "the shelf"},
            {"tag_id": 9, "measured_side_mm": 50.1, "mount": "the door"}]})
        assert r.status_code == 200, r.text
        entry = r.json()["runs"][-1]
        assert entry["kind"] == "declaration"
        note = " ".join(entry["notes"])
        assert "tag 7 re-measured 100 -> 97.4 mm" in note
        assert "tag 9 added at 50.1 mm on the door" in note


# ── 4. the routes that touch a light refuse honestly with no camera ────────

def test_a_run_with_no_camera_is_a_409_carrying_the_recorded_refusal(monkeypatch):
    """AN ANTICIPATED CONDITION, not a server fault — and the refusal IS an
    entry, which is why the whole record comes back with it."""
    from spectra.services import calibration_runs
    monkeypatch.setattr(calibration_runs, "SESSION_WAIT_S", 0.0)
    with _client() as client:
        room = _room(client)
        cal = _create(client, room).json()
        r = client.post(f"/api/calibrations/{cal['id']}/run", json={})
        assert r.status_code == 409
        body = r.json()
        assert body["entry"]["refusal"] == "session"
        assert body["entry"]["status"] == "refused"
        # RECORDED: "did it run?" is a read, never a silence.
        assert len(body["runs"]) == 1
        assert client.get(f"/api/calibrations/{cal['id']}").json()["runs"]


def test_taking_a_pose_with_no_camera_is_a_409_carrying_the_record(monkeypatch):
    from spectra.services import calibration_runs
    monkeypatch.setattr(calibration_runs, "SESSION_WAIT_S", 0.0)
    with _client() as client:
        room = _room(client)
        cal = _create(client, room).json()
        r = client.post(f"/api/calibrations/{cal['id']}/pose",
                        json={"placement": "the shelf by the window"})
        assert r.status_code == 409
        body = r.json()
        assert body["runs"][-1]["kind"] == "fingerprint"
        # HIS OWN NAME FOR THE PLACEMENT is kept even when the pose could
        # not be measured — it is a label he typed, not a measurement.
        assert body["pose"]["placement"] == "the shelf by the window"


# ── 5. the route that deliberately does not exist ──────────────────────────

def test_there_is_no_delete_route():
    """The lineage is append-only. A route that could drop a calibration
    would be a route that erases work that cost dark rooms to produce."""
    with _client() as client:
        room = _room(client)
        cal = _create(client, room).json()
        assert client.delete(f"/api/calibrations/{cal['id']}").status_code == 405
        assert calibration_store.load(cal["id"]) is not None
