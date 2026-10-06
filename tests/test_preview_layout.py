"""The Live view's layout (spectra/services/preview_layout.py) and the stream
scope that feeds it (preview_stream.py, SCOPE): every in-use fixture in its
real shape, each pixel tied to the stream cell that colours it.

The config below is the SHAPE of his room (segment lists read 2026-10-05),
as plain dicts — nothing here builds a device or touches storage.
"""
from __future__ import annotations

import asyncio

import numpy as np

from spectra.services import device_preview as dp
from spectra.services import preview_layout as pl
from spectra.services import preview_stream as ps


def _device(device_id, kind, name, count):
    return {"id": device_id, "type": kind, "config": {"name": name, "pixel_count": count}}


def _crystal_segments():
    index = ps.profile_cell_index("crystal-mapper", 2664, 37)
    real = set(int(i) for i in index)
    segments, device_pixel = [], 0
    for pixel in range(2664):
        if pixel in real:
            segments.append(["crystal", device_pixel, device_pixel, False, 0])
            device_pixel += 1
        else:
            segments.append(["gap-crystal-mapper", pixel, pixel, False, 0])
    return segments


ROOM = {
    "devices": [
        _device("crystal", "wled", "WLED", 976),
        _device("gap-crystal-mapper", "dummy", "gap-crystal-mapper", 4096),
        _device("tv-backlight", "wled", "WLED", 560),
        _device("sconce-kitchen-left", "wled", "Sconce, Kitchen, Left", 88),
        _device("sconce-kitchen-right", "wled", "Sconce, Kitchen, Right", 88),
        _device("hue-lights", "hue", "Hue Lights", 10),
        _device("dining-hues", "hue", "Dining Hues", 7),
        _device("porch-rail", "wled", "WLED", 1),
        _device("dining-table", "wled", "WLED", 1),
        _device("radial-dummy", "dummy", "Radial Dummy", 280),
    ],
    "virtuals": [
        {"id": "crystal-mapper", "active": True,
         "config": {"name": "Crystal-Mapper", "mapping": "span", "rows": 37},
         "segments": _crystal_segments()},
        {"id": "tv-mapper", "active": True,
         "config": {"name": "Strip Effect", "mapping": "copy", "rows": 1},
         "segments": [["tv-backlight", 0, 559, False, 0],
                      ["sconce-kitchen-right", 0, 27, False, 0],
                      ["sconce-kitchen-right", 28, 87, False, 0],
                      ["sconce-kitchen-left", 0, 27, False, -2],
                      ["sconce-kitchen-left", 28, 87, True, 0]]},
        {"id": "hues", "active": True,
         "config": {"name": "Hues", "mapping": "copy", "rows": 1},
         "segments": ([["hue-lights", i, i, False, 0] for i in range(10)]
                      + [["dining-hues", i, i, False, 0] for i in range(7)])},
        {"id": "single-color-effect", "active": True,
         "config": {"name": "Single Color Effect", "mapping": "copy", "rows": 1},
         "segments": [["porch-rail", 0, 0, False, 0], ["dining-table", 0, 0, False, 0]]},
        {"id": "radial-dummy", "active": True,
         "config": {"name": "Radial Dummy", "mapping": "span", "rows": 1},
         "segments": [["radial-dummy", 0, 279, False, 0]]},
        {"id": "hue-lights", "active": False,
         "config": {"name": "Hue Lights", "mapping": "copy", "rows": 1},
         "segments": [["hue-lights", 0, 9, False, 0]]},
        {"id": "tv-backlight", "active": False,
         "config": {"name": "TV Backlight", "mapping": "span", "rows": 1},
         "segments": [["tv-backlight", 0, 559, False, 0]]},
    ],
}
DRIVEN = {"crystal-mapper", "tv-mapper", "hues", "single-color-effect",
          "radial-dummy", "hue-lights"}


def _layout():
    virtuals = pl.build_layout(ROOM, DRIVEN, lambda v: v.get("active") is True)
    return {v["id"]: v for v in virtuals}


def _fixtures(virtual):
    return {f["device_id"]: f for f in virtual["fixtures"]}


def test_only_active_driven_virtuals_that_reach_a_light_are_drawn():
    # radial-dummy is driven and active and lights nothing; hue-lights is
    # driven and inactive (hues carries its bulbs); tv-backlight is neither.
    assert set(_layout()) == {"crystal-mapper", "tv-mapper", "hues", "single-color-effect"}


def test_the_crystal_is_one_hex_matrix_of_its_976_real_cells():
    crystal = _layout()["crystal-mapper"]
    assert (crystal["rows"], crystal["cols"], crystal["cells"]) == (37, 72, 976)
    assert crystal["hex_lattice"] is True
    (fixture,) = crystal["fixtures"]
    assert (fixture["device_id"], fixture["kind"], fixture["count"]) == ("crystal", "matrix", 976)
    # stream cell i IS real cell i, in row-major order: no table needed
    assert fixture["src"] is None
    index = ps.profile_cell_index("crystal-mapper", 2664, 37)
    assert fixture["grid"] == [int(i) for i in index]


def test_a_copy_virtual_draws_each_fixture_from_the_one_effect():
    tv = _layout()["tv-mapper"]
    assert (tv["cells"], tv["mapping"]) == (560, "copy")
    fixtures = _fixtures(tv)
    assert fixtures["tv-backlight"]["kind"] == "frame"
    assert fixtures["tv-backlight"]["count"] == 560
    assert fixtures["tv-backlight"]["src"] is None
    right = fixtures["sconce-kitchen-right"]
    assert (right["kind"], right["orient"], right["count"]) == ("strip", "v", 88)
    # each segment is the WHOLE effect, squeezed onto its own length
    assert right["src"][0] == 0 and right["src"][27] == 559
    assert right["src"][28] == 0 and right["src"][87] == 559
    left = fixtures["sconce-kitchen-left"]["src"]
    expected = np.roll(np.rint(np.linspace(0, 559, 28)).astype(int), -2)
    assert left[:28] == [int(i) for i in expected]
    assert left[28] == 559 and left[87] == 0          # an inverted segment


def test_bulbs_and_single_pixels():
    hues = _fixtures(_layout()["hues"])
    assert {k: (f["kind"], f["count"]) for k, f in hues.items()} == {
        "hue-lights": ("bulbs", 10), "dining-hues": ("bulbs", 7)}
    # one effect pixel lights every bulb
    assert hues["hue-lights"]["src"] == [0] * 10
    singles = _fixtures(_layout()["single-color-effect"])
    assert {f["kind"] for f in singles.values()} == {"dot"}


def test_no_ground_truth_means_no_restriction():
    assert len(pl.build_layout(ROOM, set(), lambda v: v.get("active") is True)) == 4


class _Socket:
    def __init__(self):
        self.messages = []

    async def send_text(self, text):
        pass

    async def send_bytes(self, data):
        self.messages.append(ps.decode_message(data))

    async def close(self):
        pass


def test_a_favorites_viewer_is_never_sent_the_extra_virtuals():
    async def run():
        hub = ps.PreviewStreamHub()
        hub.favorites = {"fav"}
        strip, live = _Socket(), _Socket()
        hub.connect(strip, level="full")
        hub.connect(live, level="full", scope="in_use")
        assert hub.wants_in_use()
        for step in range(3):
            hub.publish("fav", np.full((4, 3), step), 1)
            hub.publish("extra", np.full((4, 3), step + 9), 1)
            await asyncio.sleep(0.05)
        await hub.disconnect(live)
        assert not hub.wants_in_use()
        await hub.disconnect(strip)
        payloads = lambda sock: {bytes(r["payload"][:1]) for m in sock.messages  # noqa: E731
                                 for r in m["records"]}
        assert payloads(strip) <= {b"\x00", b"\x01", b"\x02"} and payloads(strip)
        assert payloads(live) & {b"\x09", b"\x0a", b"\x0b"}
    asyncio.run(run())


def test_the_relay_reads_extra_virtuals_only_while_asked():
    relay = dp.DevicePreviewRelay(favorite_ids=["a"], has_viewers=lambda: True)
    assert relay._wanted() == ["a"]
    relay.set_extra(["a", "b"])
    assert relay._wanted() == ["a", "b"]
    relay.set_extra([])
    assert relay._wanted() == ["a"]
    # nothing favourite, but the Live view is open: still worth an upstream
    empty = dp.DevicePreviewRelay(favorite_ids=[], has_viewers=lambda: True)
    assert not empty._wants_upstream()
    empty.set_extra(["b"])
    assert empty._wants_upstream()


def test_fixtures_sharing_a_name_are_labelled_by_their_device():
    names = {f["device_id"]: f["name"] for v in _layout().values() for f in v["fixtures"]}
    assert names["tv-backlight"] == "Tv backlight" and names["porch-rail"] == "Porch rail"
    assert names["hue-lights"] == "Hue Lights"        # already unique: kept


def test_the_layout_route_answers_from_the_stored_config(tmp_path, monkeypatch):
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from fx import device_model
    from spectra import config as scfg
    from spectra.api import device_preview as dp_api

    monkeypatch.setattr(scfg, "FX_LIVE_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", tmp_path / "none.json")
    (tmp_path / "config.json").write_text(json.dumps(ROOM))
    app = FastAPI()
    app.include_router(dp_api.router)
    body = TestClient(app).get("/api/device-preview/layout").json()
    assert body["source"] == "stored"
    assert [v["id"] for v in body["virtuals"]] == [
        "crystal-mapper", "tv-mapper", "hues", "single-color-effect"]
    assert all("favorite" in v for v in body["virtuals"])


def test_the_live_views_hello_widens_the_source_and_leaving_narrows_it(monkeypatch):
    import json
    import time

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from spectra.api import device_preview as dp_api

    monkeypatch.setattr(pl, "in_use_virtual_ids", lambda: ["crystal-mapper", "tv-mapper"])
    monkeypatch.setattr(dp.relay, "_favorite_ids", ["crystal-mapper"])
    monkeypatch.setattr(dp.relay, "_extra_ids", [])

    def wait(condition):
        for _ in range(300):
            if condition():
                return True
            time.sleep(0.01)
        return False

    app = FastAPI()
    app.include_router(dp_api.router)
    client = TestClient(app)
    with client.websocket_connect("/api/device-preview/ws") as ws:
        ws.receive_json()
        ws.send_text(json.dumps({"type": "hello", "protocol": 2, "level": "full",
                                 "scope": "in_use"}))
        assert wait(lambda: dp.relay._wanted() == ["crystal-mapper", "tv-mapper"])
        assert dp.stream_hub.stats()[0]["scope"] == "in_use"
        # the Live view closes; the strip on the same socket stays
        ws.send_text(json.dumps({"type": "subscribe", "level": "summary",
                                 "scope": "favorites"}))
        assert wait(lambda: dp.relay._wanted() == ["crystal-mapper"])
        ws.send_text(json.dumps({"type": "subscribe", "level": "full", "scope": "in_use"}))
        assert wait(lambda: dp.relay._wanted() == ["crystal-mapper", "tv-mapper"])
    assert wait(lambda: dp.relay._wanted() == ["crystal-mapper"])     # the viewer left
