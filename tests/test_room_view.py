"""The Live view's Room map (spectra/services/room_view.py): one camera pose's
stored measurements turned into a glow per emitter and a placement per
fixture pixel — read-only on the room maps and the commissioning results,
writing only its own hand-placement store.

The room is the SHAPE of his (the layout test's config, plus the strips' own
device virtuals a copy-mapped carrier is measured through). Footprints are
synthetic blobs; nothing here touches a device or live storage.
"""
from __future__ import annotations

import base64
import copy
import json

import numpy as np
import pytest

from spectra import config as scfg
from spectra.models.room_map import (GRID_H, GRID_W, CaptureContext,
                                     EmitterFootprint, PixelRange, RoomMap)
from spectra.services import gray_code, preview_layout as pl
from spectra.services import room_view as rv
from tests.test_preview_layout import DRIVEN, ROOM

POSE = "pose-a"


def _room_config() -> dict:
    raw = copy.deepcopy(ROOM)
    for dev in ("sconce-kitchen-left", "sconce-kitchen-right"):
        raw["virtuals"].append({
            "id": dev, "active": False,
            "config": {"name": dev, "mapping": "span", "rows": 1},
            "segments": [[dev, 0, 87, False, 0]]})
    return raw


RAW = _room_config()


def _layout(raw=RAW) -> dict:
    return {"source": "stored",
            "virtuals": pl.build_layout(raw, DRIVEN, lambda v: v.get("active") is True)}


def _blob(cx: float, cy: float, peak: float = 0.1, spread: float = 0.02) -> list[float]:
    ys = (np.arange(GRID_H) + 0.5) / GRID_H
    xs = (np.arange(GRID_W) + 0.5) / GRID_W
    gx, gy = np.meshgrid(xs, ys)
    d2 = (gx - cx) ** 2 + ((gy - cy) * GRID_H / GRID_W) ** 2
    return [float(v) for v in (peak * np.exp(-d2 / (2 * spread ** 2))).reshape(-1)]


def _fp(emitter_id, carrier, grid, ranges=(), pose=POSE, unseen=False) -> EmitterFootprint:
    return EmitterFootprint(
        emitter_id=emitter_id, label=emitter_id, carrier_id=carrier,
        ranges=[PixelRange(virtual_id=v, start=a, end=b) for v, a, b in ranges],
        grid=grid, weight=float(sum(grid)) or 0.3, unseen=unseen,
        note="not seen from this pose" if unseen else "",
        capture=CaptureContext(pose_id=pose, exposure_locked=True, captured_at=100.0))


def _rooms() -> list[RoomMap]:
    return [
        RoomMap(id="living", name="Living Room", carrier_ids=["tv-mapper"], footprints=[
            _fp("tv-backlight:blk1", "tv-mapper", _blob(0.3, 0.6), [("tv-backlight", 10, 19)]),
            _fp("tv-backlight:blk0", "tv-mapper", [], [("tv-backlight", 0, 9)], unseen=True),
            _fp("sconce-left:blk1", "tv-mapper", _blob(0.7, 0.4, peak=0.4),
                [("sconce-kitchen-left", 30, 39)]),
        ]),
        RoomMap(id="crystal", name="Crystal", carrier_ids=["crystal-mapper"], footprints=[
            _fp("crystal-mapper", "", _blob(0.5, 0.25, peak=0.025, spread=0.03))]),
        RoomMap(id="dining", name="Dining", carrier_ids=["single-color-effect"], footprints=[
            _fp("single-color-effect", "", _blob(0.85, 0.8, peak=0.02))]),
        RoomMap(id="other", name="Other pose", carrier_ids=["crystal-mapper"], footprints=[
            _fp("crystal-mapper", "", _blob(0.1, 0.1), pose="pose-b")]),
    ]


def _view(**kw) -> dict:
    args = dict(raw=RAW, layout=_layout(), rooms=_rooms(), results=[], hand={})
    args.update(kw)
    return rv.build_view(args.pop("pose", POSE), **args)


def _pieces(view, virtual_id, device_id):
    return sorted((p for p in view["pieces"]
                   if (p["virtual_id"], p["device_id"]) == (virtual_id, device_id)),
                  key=lambda p: p["first"])


# ── poses ──────────────────────────────────────────────────────────────────

def test_a_pose_is_one_pose_id_across_every_room_that_was_mapped_from_it():
    found = {p["pose_id"]: p for p in rv.poses(_rooms(), [])}
    assert set(found) == {POSE, "pose-b"}
    pose = found[POSE]
    assert [r["name"] for r in pose["rooms"]] == ["Living Room", "Crystal", "Dining"]
    assert (pose["mapped"], pose["unseen"]) == (4, 1)
    assert pose["label"] == "Living Room + Crystal + Dining"


def test_an_unknown_pose_has_no_view():
    assert _view(pose="nope") is None


def test_two_poses_are_never_drawn_together():
    ids = {e["id"] for e in _view()["emitters"]}
    assert ids == {"tv-backlight:blk1", "sconce-left:blk1", "crystal-mapper", "single-color-effect"}
    other = _view(pose="pose-b")
    assert [e["centre"] for e in other["emitters"]] == [pytest.approx([0.1, 0.1], abs=0.02)]


# ── every pixel has exactly one answer ─────────────────────────────────────

def test_every_fixture_pixel_is_in_exactly_one_piece():
    view = _view()
    for virtual in _layout()["virtuals"]:
        for fixture in virtual["fixtures"]:
            covered = np.zeros(fixture["count"], dtype=int)
            for piece in _pieces(view, virtual["id"], fixture["device_id"]):
                covered[piece["first"]:piece["first"] + piece["count"]] += 1
            assert (covered == 1).all(), (virtual["id"], fixture["device_id"])


def test_a_whole_carrier_footprint_places_the_whole_fixture_at_its_light():
    (piece,) = _pieces(_view(), "crystal-mapper", "crystal")
    assert (piece["first"], piece["count"], piece["source"]) == (0, 976, "footprint")
    assert piece["cluster"] is False
    assert (piece["at"]["x"], piece["at"]["y"]) == pytest.approx((0.5, 0.25), abs=0.02)
    # a whole fixture is never drawn too small to see its pixels
    assert piece["at"]["r"] >= rv.MIN_SHAPE_RADIUS


def test_a_range_measured_through_the_strips_own_virtual_lands_on_the_right_pixels():
    view = _view()
    tv = _pieces(view, "tv-mapper", "tv-backlight")
    assert [(p["first"], p["count"], p["source"]) for p in tv] == [
        (0, 10, "unseen"), (10, 10, "footprint"), (20, 540, "unmapped")]
    seen = tv[1]
    assert seen["cluster"] is True and seen["at"]["r"] <= rv.MAX_CLUSTER_RADIUS
    assert (seen["at"]["x"], seen["at"]["y"]) == pytest.approx((0.3, 0.6), abs=0.02)
    assert tv[0]["at"] is None and tv[0]["note"] == "not seen from this pose"
    # the sconce: device pixels 30-39, whatever order the mapper feeds them in
    left = [p for p in _pieces(view, "tv-mapper", "sconce-kitchen-left") if p["source"] == "footprint"]
    assert [(p["first"], p["count"]) for p in left] == [(30, 10)]


def test_bulbs_nobody_measured_are_one_piece_each():
    hue = _pieces(_view(), "hues", "hue-lights")
    assert len(hue) == 10 and all(p["count"] == 1 and p["source"] == "unmapped" for p in hue)
    assert hue[0]["label"] == "Hue Lights lamp 1"


def test_fixtures_measured_as_one_emitter_sit_side_by_side_at_its_centre():
    view = _view()
    (porch,) = _pieces(view, "single-color-effect", "porch-rail")
    (table,) = _pieces(view, "single-color-effect", "dining-table")
    assert porch["emitter"] == table["emitter"] is not None
    assert porch["at"]["y"] == table["at"]["y"]
    assert porch["at"]["x"] < 0.85 < table["at"]["x"]


def test_an_emitter_of_a_carrier_that_is_not_in_use_is_named_not_drawn():
    layout = _layout()
    layout["virtuals"] = [v for v in layout["virtuals"] if v["id"] != "crystal-mapper"]
    view = _view(layout=layout)
    assert "crystal-mapper" not in {e["id"] for e in view["emitters"]}
    assert any("not in use" in note for note in view["notes"])


# ── the glow ───────────────────────────────────────────────────────────────

def _glow(emitter) -> np.ndarray:
    return np.frombuffer(base64.b64decode(emitter["glow"]), dtype=np.uint8).reshape(GRID_H, GRID_W)


def test_the_glow_is_the_footprint_and_dimmer_lights_still_show_in_order():
    emitters = {e["id"]: e for e in _view()["emitters"]}
    sconce, crystal = _glow(emitters["sconce-left:blk1"]), _glow(emitters["crystal-mapper"])
    assert np.unravel_index(sconce.argmax(), sconce.shape) == pytest.approx((0.4 * GRID_H, 0.7 * GRID_W), abs=1.5)
    # 16x dimmer to the camera: shown at about a quarter, never brighter
    assert 0.15 * sconce.max() < crystal.max() < 0.4 * sconce.max()
    # the faint tail of a footprint is cut, not smeared over the frame
    assert (sconce == 0).mean() > 0.9


def test_the_glow_takes_its_colour_from_every_pixel_the_emitter_lit():
    emitters = {e["id"]: e for e in _view()["emitters"]}
    assert emitters["tv-backlight:blk1"]["pixels"] == [
        {"virtual_id": "tv-mapper", "device_id": "tv-backlight", "first": 10, "count": 10}]
    assert {(p["device_id"], p["count"]) for p in emitters["single-color-effect"]["pixels"]} == {
        ("porch-rail", 1), ("dining-table", 1)}


def test_the_core_of_a_light_ignores_a_stray_bright_cell():
    grid = np.asarray(_blob(0.25, 0.5, peak=0.2, spread=0.04)).reshape(GRID_H, GRID_W)
    grid[2, 60] = 0.19                       # one noisy cell, far away
    x, y, radius = rv.light_core(rv._soften(grid))
    assert (x, y) == pytest.approx((0.25, 0.5), abs=0.02)
    assert 0.01 < radius < 0.12


def test_the_backdrop_is_the_poses_measurements_added_up():
    view = _view()
    backdrop = np.frombuffer(base64.b64decode(view["backdrop"]), dtype=np.uint8).reshape(GRID_H, GRID_W)
    for cx, cy in ((0.3, 0.6), (0.7, 0.4), (0.5, 0.25), (0.85, 0.8)):
        assert backdrop[int(cy * GRID_H), int(cx * GRID_W)] > 3 * np.median(backdrop)


# ── per-pixel sources ──────────────────────────────────────────────────────

def _result(verdict: str, positions: dict, pose=POSE) -> dict:
    return {"mapper_id": "tv-mapper", "pose_id": pose, "at": 200.0, "targets": [{
        "composition": {"segments": [
            {"device_id": "sconce-kitchen-right", "start": 0, "end": 27, "device_start": 0},
            {"device_id": "sconce-kitchen-right", "start": 28, "end": 87, "device_start": 28}]},
        "decodes": [{"positions": positions}], "table": {"verdict": verdict}}]}


POSITIONS = {str(i): [0.6, 0.2 + i * 0.005] for i in range(88) if i != 40}


def test_a_judged_decode_places_each_pixel_where_the_camera_read_it():
    view = _view(results=[_result("pass", POSITIONS)])
    (piece,) = _pieces(view, "tv-mapper", "sconce-kitchen-right")
    assert (piece["source"], piece["first"], piece["count"]) == ("decode", 0, 88)
    xy = np.asarray(piece["xy"]).reshape(-1, 2)
    assert xy[10] == pytest.approx([0.6, 0.25])
    # the one pixel the camera did not read is drawn between its neighbours
    assert xy[40] == pytest.approx([0.6, 0.4])
    assert "87 of 88" in piece["note"]


@pytest.mark.parametrize("result", [
    _result("fail", POSITIONS),               # judged wrong: confidently misplaced
    _result("pass", {}),                      # stored before positions were kept
    _result("pass", POSITIONS, pose="pose-b"),  # another camera's picture
])
def test_a_decode_that_cannot_be_trusted_here_is_not_drawn(result):
    view = _view(results=[result])
    assert all(p["source"] != "decode" for p in view["pieces"])
    if result["pose_id"] == POSE:
        assert any("not drawn" in note for note in view["notes"])


def test_a_later_segments_composition_index_is_resolved_by_its_own_device_start():
    """tv-mapper's real shape: tv-backlight occupies composition indices
    0-559, then sconce-kitchen-right lands at composition indices 560-647
    across two sub-segments whose OWN device numbering is 0-27 and 28-87.
    Those composition indices are not the device's own pixel numbers —
    only `device_start` tells them apart. Before the fix, the decode source
    read `start`/`end` as device pixel numbers directly, so these positions
    (keyed 560 and 647) never matched sconce-kitchen-right's real device
    pixels (0-87) and the decode was silently dropped for this fixture."""
    positions = {"560": [0.11, 0.22], "647": [0.33, 0.44]}
    result = {"mapper_id": "tv-mapper", "pose_id": POSE, "at": 200.0, "targets": [{
        "composition": {"segments": [
            {"device_id": "tv-backlight", "start": 0, "end": 559, "device_start": 0},
            {"device_id": "sconce-kitchen-right", "start": 560, "end": 587, "device_start": 0},
            {"device_id": "sconce-kitchen-right", "start": 588, "end": 647, "device_start": 28},
        ]},
        "decodes": [{"positions": positions}], "table": {"verdict": "pass"}}]}
    view = _view(results=[result])
    (piece,) = _pieces(view, "tv-mapper", "sconce-kitchen-right")
    assert (piece["source"], piece["first"], piece["count"]) == ("decode", 0, 88)
    xy = np.asarray(piece["xy"]).reshape(-1, 2)
    # device pixel 0 (composition index 560) and device pixel 87
    # (composition index 647) — never the composition index itself.
    assert xy[0] == pytest.approx([0.11, 0.22])
    assert xy[87] == pytest.approx([0.33, 0.44])


def test_a_composition_stored_before_device_start_was_recorded_is_not_drawn():
    """A segment with no `device_start` (or a negative one) predates this
    field — there is nothing to resolve its composition index into a real
    device pixel without guessing, so it is skipped exactly like any other
    unusable decode rather than placed by the composition index."""
    result = {"mapper_id": "tv-mapper", "pose_id": POSE, "at": 200.0, "targets": [{
        "composition": {"segments": [
            {"device_id": "sconce-kitchen-right", "start": 0, "end": 27},
            {"device_id": "sconce-kitchen-right", "start": 28, "end": 87}]},
        "decodes": [{"positions": POSITIONS}], "table": {"verdict": "pass"}}]}
    view = _view(results=[result])
    assert all(p["source"] != "decode" for p in view["pieces"])
    assert any("not drawn" in note for note in view["notes"])


def test_a_decode_keeps_where_it_saw_each_index():
    decode = gray_code.Decode(total=3, width=4, height=4, index_map=np.zeros(16, dtype=int),
                              positions={0: (0.1, 0.2), 2: (0.123456789, 0.5)},
                              support={0: gray_code.MIN_SUPPORT, 2: gray_code.MIN_SUPPORT, 1: 0})
    assert decode.as_dict()["positions"] == {"0": [0.1, 0.2], "2": [0.12346, 0.5]}


def test_another_position_source_plugs_in_without_changing_the_view():
    def wled_map(pose_id, fixtures):
        assert pose_id == POSE
        hue = next(f for f in fixtures if f["device_id"] == "dining-hues")
        return {(hue["virtual_id"], "dining-hues"): {
            "positions": {j: (0.1 + 0.1 * j, 0.9) for j in range(7)}, "note": "from a WLED map"}}

    view = _view(sources=[("wled-map", wled_map)])
    (piece,) = _pieces(view, "hues", "dining-hues")
    assert (piece["source"], piece["count"], piece["note"]) == ("wled-map", 7, "from a WLED map")
    assert piece["xy"][:2] == [0.1, 0.9]


def test_a_source_that_fails_is_named_and_the_rest_still_draws():
    def broken(pose_id, fixtures):
        raise RuntimeError("no file")

    view = _view(sources=[("river", broken)])
    assert any("river" in note for note in view["notes"])
    assert len(view["emitters"]) == 4


# ── his hand, and the one store this writes ────────────────────────────────

def test_hand_placements_merge_remove_and_survive_a_reload():
    a = rv.Placement(x=0.2, y=0.3, size=0.05)
    b = rv.Placement(x=0.9, y=0.1, size=0.03, angle=45)
    assert rv.put_placements(POSE, {"hues/hue-lights:0-0": a}) == {"hues/hue-lights:0-0": a.model_dump()}
    rv.put_placements(POSE, {"hues/hue-lights:1-1": b})
    rv.put_placements("pose-b", {"hues/hue-lights:0-0": b})
    assert set(rv.load_placements(POSE)) == {"hues/hue-lights:0-0", "hues/hue-lights:1-1"}
    rv.put_placements(POSE, {"hues/hue-lights:0-0": None})
    assert rv.load_placements(POSE) == {"hues/hue-lights:1-1": b.model_dump()}
    assert rv.load_placements("pose-b") == {"hues/hue-lights:0-0": b.model_dump()}


def test_the_view_carries_only_placements_for_pieces_it_has():
    hand = {"hues/hue-lights:0-0": {"x": 0.2, "y": 0.3, "size": 0.05, "angle": 0.0},
            "gone/device:0-9": {"x": 0.5, "y": 0.5, "size": 0.1, "angle": 0.0}}
    assert set(_view(hand=hand)["hand"]) == {"hues/hue-lights:0-0"}


def test_a_pose_cannot_be_filled_without_bound(monkeypatch):
    monkeypatch.setattr(rv, "MAX_PLACEMENTS_PER_POSE", 2)
    place = rv.Placement(x=0.5, y=0.5, size=0.1)
    rv.put_placements(POSE, {"a": place, "b": place})
    with pytest.raises(ValueError):
        rv.put_placements(POSE, {"c": place})
    assert set(rv.load_placements(POSE)) == {"a", "b"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """The real routes over the stored-data seams: a room map file, a
    commissioning file, the fx config and the layout."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from spectra.api import room_view as api
    from spectra.services import device_console, light_field

    monkeypatch.setattr(scfg, "COMMISSIONING_FILE", tmp_path / "commissioning.json")
    scfg.COMMISSIONING_FILE.write_text(json.dumps({"results": [_result("fail", POSITIONS)]}))
    light_field.save_rooms(_rooms())
    monkeypatch.setattr(device_console, "_read_stored_config", lambda: copy.deepcopy(RAW))
    monkeypatch.setattr(pl, "current_layout", _layout)
    app = FastAPI()
    app.include_router(api.router, prefix="/spectra")
    return TestClient(app)


def test_the_routes_serve_poses_and_a_view_and_refuse_an_unknown_pose(client):
    poses = client.get("/spectra/api/room-view/poses").json()["poses"]
    assert {p["pose_id"] for p in poses} == {POSE, "pose-b"}
    view = client.get("/spectra/api/room-view", params={"pose": POSE}).json()
    assert len(view["emitters"]) == 4 and view["grid"] == {"w": GRID_W, "h": GRID_H}
    assert client.get("/spectra/api/room-view", params={"pose": "nope"}).status_code == 404


def test_a_placement_is_saved_read_back_and_removed_through_the_route(client):
    key = "hues/hue-lights:3-3"
    url = f"/spectra/api/room-view/placements/{POSE}"
    saved = client.put(url, json={"placements": {key: {"x": 0.4, "y": 0.6, "size": 0.03}}})
    assert saved.status_code == 200 and saved.json()["placements"][key]["angle"] == 0.0
    assert client.get("/spectra/api/room-view", params={"pose": POSE}).json()["hand"][key]["x"] == 0.4
    assert client.put(url, json={"placements": {key: None}}).json()["placements"] == {}


@pytest.mark.parametrize("body", [
    {"placements": {"k": {"x": 1.4, "y": 0.5, "size": 0.1}}},      # outside the picture
    {"placements": {"k": {"x": 0.5, "y": 0.5, "size": 0}}},        # no size
    {"placements": {"k" * 300: {"x": 0.5, "y": 0.5, "size": 0.1}}},
])
def test_a_bad_placement_is_refused_and_nothing_is_stored(client, body):
    assert client.put(f"/spectra/api/room-view/placements/{POSE}", json=body).status_code == 422
    assert rv.load_placements(POSE) == {}


def test_a_placement_for_a_pose_nothing_was_mapped_from_is_refused(client):
    body = {"placements": {"k": {"x": 0.5, "y": 0.5, "size": 0.1}}}
    assert client.put("/spectra/api/room-view/placements/nope", json=body).status_code == 404
    assert not scfg.ROOM_VIEW_FILE.exists()


def test_reading_and_placing_never_write_the_maps_or_the_commissioning_results(client):
    before = (scfg.ROOM_MAPS_FILE.read_bytes(), scfg.COMMISSIONING_FILE.read_bytes())
    stamps = (scfg.ROOM_MAPS_FILE.stat().st_mtime_ns, scfg.COMMISSIONING_FILE.stat().st_mtime_ns)
    client.get("/spectra/api/room-view/poses")
    client.get("/spectra/api/room-view", params={"pose": POSE})
    client.put(f"/spectra/api/room-view/placements/{POSE}",
               json={"placements": {"hues/hue-lights:0-0": {"x": 0.1, "y": 0.1, "size": 0.03}}})
    assert (scfg.ROOM_MAPS_FILE.read_bytes(), scfg.COMMISSIONING_FILE.read_bytes()) == before
    assert (scfg.ROOM_MAPS_FILE.stat().st_mtime_ns,
            scfg.COMMISSIONING_FILE.stat().st_mtime_ns) == stamps
    assert scfg.ROOM_VIEW_FILE.exists()
