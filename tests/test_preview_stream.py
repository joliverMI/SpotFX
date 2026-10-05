"""The device preview's protocol-2 stream (spectra/services/preview_stream.py):
the wire format, real-cells-only frames, the ack window, the rate ladder,
subscription levels, and the hello that moves a viewer onto it.

Everything here is in-process against fake sockets. The end-to-end proof —
a real browser through an emulated link, against LedFX — is
scripts/preview_perf/run_preview_perf.py.
"""
from __future__ import annotations

import asyncio
import base64
import json

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spectra.api import device_preview as dp_api
from spectra.services import device_preview as dp
from spectra.services import preview_stream as ps


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list = []
        self.closed = False

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(ps.decode_message(data))

    async def close(self) -> None:
        self.closed = True

    def ticks(self) -> list[dict]:
        return [m for m in self.sent if "records" in m]

    def layouts(self) -> list[dict]:
        return [m for m in self.sent if m.get("type") == "device_preview_layout"]


def _rainbow(n: int, shift: int = 0) -> np.ndarray:
    base = (np.arange(n)[:, None] * np.array([3, 5, 7]) + shift) % 256
    return base.astype(float)


# ── wire format ────────────────────────────────────────────────────────────

def test_a_message_round_trips_through_the_documented_layout():
    data = ps.encode_message(7, 30, 112, 1234.5, [
        (0, ps.KIND_FULL, 9, 41, b"\x01\x02\x03\x04\x05\x06"),
        (1, ps.KIND_SUMMARY, 70000, 42, b"\xff\x00\x80"),
    ])
    assert len(data) == 20 + (12 + 6) + (12 + 3)
    assert data[0] == ps.MAGIC
    msg = ps.decode_message(data)
    assert (msg["seq"], msg["rate_fps"], msg["srtt_ms"], msg["sent_ms"]) == (7, 30, 112, 1234.5)
    first, second = msg["records"]
    assert (first["device"], first["kind"], first["age_ms"], first["frame_seq"]) == (0, 1, 9, 41)
    assert first["payload"] == b"\x01\x02\x03\x04\x05\x06"
    assert second["age_ms"] == 0xFFFF          # clamped, never wrapped
    assert second["payload"] == b"\xff\x00\x80"


# ── real cells only ────────────────────────────────────────────────────────

def test_the_crystal_sends_its_976_real_cells_and_says_where_they_are():
    index = ps.profile_cell_index("crystal-mapper", 2664, 37)
    assert index is not None and len(index) == 976
    hub = ps.PreviewStreamHub()
    hub._viewers["someone"] = object()        # publish only works for an audience
    pixels = _rainbow(2664)
    hub.publish("crystal-mapper", pixels, 37)
    frame = hub.latest()["crystal-mapper"]
    assert (frame.layout.rows, frame.layout.cols, frame.layout.cells) == (37, 72, 976)
    assert len(frame.full()) == 976 * 3
    assert frame.full() == pixels.astype(np.uint8)[index].tobytes()
    # The layout message carries one bit per cell of the rectangle.
    described = frame.layout.describe(0, "crystal-mapper")
    bits = np.unpackbits(np.frombuffer(base64.b64decode(described["mask"]), dtype=np.uint8))
    assert np.array_equal(np.flatnonzero(bits[:2664]), index)
    # The summary is the mean of the REAL cells, not of the dark rectangle.
    assert frame.summary() == bytes(
        int(round(float(c))) for c in pixels.astype(np.uint8)[index].mean(axis=0))


def test_a_profile_for_another_shape_is_ignored_not_guessed():
    assert ps.profile_cell_index("crystal-mapper", 2000, 37) is None
    assert ps.profile_cell_index("crystal-mapper", 2664, 36) is None
    assert ps.profile_cell_index("no-such-device", 17, 1) is None
    hub = ps.PreviewStreamHub()
    hub._viewers["someone"] = object()
    hub.publish("hues", _rainbow(17), 1)
    frame = hub.latest()["hues"]
    assert frame.layout.cell_index is None and len(frame.full()) == 17 * 3
    assert frame.layout.describe(0, "hues")["mask"] is None


def test_an_unchanged_frame_is_not_a_new_frame_and_nobody_watching_costs_nothing():
    hub = ps.PreviewStreamHub()
    hub.publish("hues", _rainbow(17), 1)
    assert hub.latest() == {}                  # no viewer: nothing kept
    hub._viewers["someone"] = object()
    hub.publish("hues", _rainbow(17), 1)
    seq = hub.latest()["hues"].seq
    hub.publish("hues", _rainbow(17), 1)
    assert hub.latest()["hues"].seq == seq
    hub.publish("hues", _rainbow(17, shift=9), 1)
    assert hub.latest()["hues"].seq == seq + 1


# ── the ticker, the levels and the ack window ──────────────────────────────

async def _feed(hub: ps.PreviewStreamHub, seconds: float, ids=("crystal-mapper", "hues")):
    """A 100 Hz source: every device changes on every frame."""
    shapes = {"crystal-mapper": (2664, 37), "hues": (17, 1)}
    end = asyncio.get_running_loop().time() + seconds
    shift = 0
    while asyncio.get_running_loop().time() < end:
        shift += 1
        for vid in ids:
            n, rows = shapes[vid]
            hub.publish(vid, _rainbow(n, shift), rows)
        await asyncio.sleep(0.01)


def test_a_full_viewer_gets_a_layout_then_30_ticks_a_second_of_real_cells():
    async def run():
        hub = ps.PreviewStreamHub()
        ws = FakeSocket()
        viewer = hub.connect(ws, level="full")

        async def acker():
            while True:
                for tick in ws.ticks():
                    viewer.ack(tick["seq"])
                await asyncio.sleep(0.005)

        ack_task = asyncio.create_task(acker())
        await _feed(hub, 1.0)
        ack_task.cancel()
        await hub.disconnect(ws)
        return ws, viewer

    ws, viewer = asyncio.run(run())
    assert ws.sent[0]["type"] == "device_preview_layout"      # before any frame
    table = {d["vis_id"]: d for d in ws.layouts()[-1]["devices"]}
    assert table["crystal-mapper"]["cells"] == 976 and table["hues"]["mask"] is None
    ticks = ws.ticks()
    # A steady clock against a faster source: about 30, not the "every third
    # frame" a minimum-interval test gives.
    assert 26 <= len(ticks) <= 32, len(ticks)
    crystal = table["crystal-mapper"]["index"]
    sizes = {len(r["payload"]) for t in ticks for r in t["records"] if r["device"] == crystal}
    assert sizes == {976 * 3}
    assert [t["seq"] for t in ticks] == list(range(1, len(ticks) + 1))
    assert viewer.ticks_blocked == 0


def test_a_summary_viewer_gets_three_bytes_a_device_and_a_level_change_resends():
    async def run():
        hub = ps.PreviewStreamHub()
        ws = FakeSocket()
        viewer = hub.connect(ws, level="summary")

        async def acker():
            while True:
                for tick in ws.ticks():
                    viewer.ack(tick["seq"])
                await asyncio.sleep(0.005)

        ack_task = asyncio.create_task(acker())
        await _feed(hub, 0.6)
        summary_ticks = list(ws.ticks())
        viewer.set_level("full")
        await asyncio.sleep(0.1)          # the source is now still
        after = ws.ticks()[len(summary_ticks):]
        ack_task.cancel()
        await hub.disconnect(ws)
        return summary_ticks, after

    summary_ticks, after = asyncio.run(run())
    records = [r for t in summary_ticks for r in t["records"]]
    assert records and all(r["kind"] == ps.KIND_SUMMARY and len(r["payload"]) == 3
                           for r in records)
    assert len(summary_ticks) <= ps.SUMMARY_MAX_FPS * 0.6 + 2
    # Going to "full" sends the current picture even though nothing moved.
    full = [r for t in after for r in t["records"]]
    assert {len(r["payload"]) for r in full} == {976 * 3, 17 * 3}


def test_a_viewer_that_stops_acknowledging_is_sent_no_more_than_its_window():
    async def run():
        hub = ps.PreviewStreamHub()
        ws = FakeSocket()
        viewer = hub.connect(ws, level="full")

        async def acker():
            while True:
                for tick in ws.ticks():
                    viewer.ack(tick["seq"])
                await asyncio.sleep(0.002)

        ack_task = asyncio.create_task(acker())
        await _feed(hub, 0.3)                     # a healthy local link
        ack_task.cancel()
        for tick in ws.ticks():
            viewer.ack(tick["seq"])
        healthy = len(ws.ticks())
        window = viewer.window()
        await _feed(hub, 0.6)                     # the viewer goes quiet
        stalled = len(ws.ticks())
        blocked = viewer.ticks_blocked
        newest_seq = hub.latest()["hues"].seq
        viewer.ack(ws.ticks()[-1]["seq"])         # one ack
        await asyncio.sleep(0.05)
        resumed = ws.ticks()[stalled:]
        await hub.disconnect(ws)
        return healthy, window, stalled, blocked, resumed, newest_seq

    healthy, window, stalled, blocked, resumed, newest_seq = asyncio.run(run())
    assert window == 1 + ps.EXTRA_IN_FLIGHT       # 2 beyond a ~0 ms round trip
    assert stalled - healthy == window            # 0.6 s of source, 3 frames sent
    assert blocked > 10                           # it kept WANTING to send
    # What goes out when the ack lands is the NEWEST picture, not a backlog.
    assert resumed and max(r["frame_seq"] for r in resumed[0]["records"]) == newest_seq


def test_the_window_is_two_frames_beyond_the_links_own_round_trip():
    hub = ps.PreviewStreamHub()
    viewer = ps.ViewerStream(FakeSocket(), hub, level="full")
    assert viewer.window() == 3 + 2                    # nothing measured yet
    viewer._note_rtt(100.0, 0.004)                     # a LAN
    assert viewer.window() == 1 + 2
    viewer._rtt_minima.clear()
    viewer._note_rtt(100.0, 0.100)                     # a relayed Tailscale link
    assert viewer.window() == 3 + 2
    viewer._rtt_minima.clear()
    viewer._note_rtt(100.0, 30.0)                      # nonsense never buys seconds
    assert viewer.window() == 18 + 2
    viewer.rate_idx = 3                                # at 10 fps
    assert viewer.window() == 6 + 2
    # The minimum is over a recent window, so one slow ack does not move it.
    viewer._rtt_minima.clear()
    viewer.rate_idx = 0
    viewer._note_rtt(100.0, 0.030)
    viewer._note_rtt(100.5, 0.400)
    assert viewer.min_rtt() == 0.030
    viewer._note_rtt(100.0 + ps.MIN_RTT_WINDOW_S + 2, 0.050)
    assert viewer.min_rtt() == 0.050


def test_held_ticks_step_the_rate_down_and_a_failed_step_up_waits_longer():
    now = {"t": 1000.0}
    hub = ps.PreviewStreamHub(clock=lambda: now["t"])
    viewer = ps.ViewerStream(FakeSocket(), hub, level="full", clock=lambda: now["t"])

    def second(sent: int, blocked: int) -> int:
        now["t"] += ps.RATE_EVAL_S
        viewer._sent_ticks, viewer._blocked_ticks = sent, blocked
        viewer._evaluate_rate(now["t"])
        return viewer.rate

    assert second(30, 0) == 30
    assert second(30, 1) == 30                  # one held tick is not congestion
    assert second(20, 10) == 20
    assert second(12, 8) == 15
    assert second(8, 6) == 10
    assert second(5, 5) == 10                   # the floor

    def quiet_seconds_until(rate: int) -> int:
        for n in range(1, 200):
            if second(viewer.rate, 0) == rate:
                return n
        raise AssertionError("never stepped up")

    first = quiet_seconds_until(15)               # quiet: back up one step
    assert 2 <= first <= ps.UP_HOLD_MIN_S
    # That step fails at once: down again, and the next try waits twice as long.
    assert second(8, 7) == 10
    assert quiet_seconds_until(15) == int(ps.UP_HOLD_MIN_S * 2)
    # It holds this time, so the longer wait is forgotten.
    for _ in range(int(ps.UP_HOLD_MIN_S * 2)):
        second(viewer.rate, 0)
    assert viewer._up_hold == {} and viewer.rate > 15


def test_a_still_device_that_changes_is_sent_before_the_next_tick():
    async def run():
        hub = ps.PreviewStreamHub()
        ws = FakeSocket()
        viewer = hub.connect(ws, level="full")
        loop = asyncio.get_running_loop()
        hub.publish("hues", np.zeros((17, 3)), 1)
        await asyncio.sleep(0.2)                       # hues is now still
        for tick in ws.ticks():
            viewer.ack(tick["seq"])
        before = len(ws.ticks())
        delays = []
        for value in (255, 0, 255):
            await asyncio.sleep(0.12)
            for tick in ws.ticks():
                viewer.ack(tick["seq"])
            hub.publish("hues", np.full((17, 3), value), 1)
            sent_at, n = loop.time(), len(ws.ticks())
            while len(ws.ticks()) == n and loop.time() - sent_at < 0.2:
                await asyncio.sleep(0.001)
            delays.append(loop.time() - sent_at)
        await hub.disconnect(ws)
        return delays, ws.ticks()[before:]

    delays, ticks = asyncio.run(run())
    # A tick is 33 ms apart; on the clock alone the average wait would be ~17.
    assert max(delays) < 0.012, delays
    assert [r["payload"][0] for t in ticks for r in t["records"]] == [255, 0, 255]


# ── the relay feeds both formats ───────────────────────────────────────────

def test_the_relay_hands_every_source_frame_to_the_stream_and_skips_unread_json():
    got, legacy = [], []

    async def on_frame(payload):
        legacy.append(payload)

    async def run(wants_legacy: bool):
        relay = dp.DevicePreviewRelay(
            favorite_ids=["alpha"], on_frame=on_frame,
            on_source_frame=lambda vid, px, rows: got.append((vid, np.asarray(px).copy(), rows)),
            wants_legacy=lambda: wants_legacy)
        raw = bytes(range(12))
        for _ in range(3):
            await relay._handle_frame({
                "event_type": "visualisation_update", "vis_id": "alpha",
                "pixels": base64.b64encode(raw).decode(), "shape": [2, 2]})
        return relay

    relay = asyncio.run(run(False))
    assert len(got) == 3 and legacy == []            # unthrottled; no JSON built
    vid, pixels, rows = got[0]
    assert (vid, rows, pixels.shape) == ("alpha", 2, (4, 3))
    assert pixels.tobytes() == bytes(range(12))
    assert relay.frames_received == 3
    got.clear()
    asyncio.run(run(True))
    assert len(got) == 3 and len(legacy) == 1        # the old format keeps its 8 fps
    # LedFX's "uncompressed" shape too: three per-channel lists.
    assert dp._decode_ledfx_pixels([[1, 4], [2, 5], [3, 6]]).tolist() == [[1, 2, 3], [4, 5, 6]]
    assert dp._decode_ledfx_pixels(None) is None


# ── the hello ──────────────────────────────────────────────────────────────

def test_hello_moves_a_viewer_onto_the_stream_and_silence_keeps_the_old_format():
    app = FastAPI()
    app.include_router(dp_api.router)
    client = TestClient(app)
    assert dp.stream_hub.client_count() == 0 and dp.frame_hub.client_count() == 0
    with client.websocket_connect("/api/device-preview/ws") as ws:
        assert ws.receive_json()["type"] == "device_preview_status"
        assert (dp.frame_hub.client_count(), dp.stream_hub.client_count()) == (1, 0)
        ws.send_text("not json")                       # ignored, never fatal
        ws.send_text(json.dumps({"type": "ack", "seq": 3}))   # before hello: ignored
        ws.send_text(json.dumps({"type": "hello", "protocol": 2, "level": "full"}))
        ws.send_text(json.dumps({"type": "subscribe", "level": "summary"}))
        ws.send_text(json.dumps({"type": "subscribe", "level": "nonsense"}))
        # A status round trip proves the server has read everything above.
        client.get("/api/device-preview/status")
        for _ in range(200):
            if dp.stream_hub.client_count() == 1 and dp.stream_hub.stats()[0]["level"] == "summary":
                break
            import time
            time.sleep(0.01)
        assert (dp.frame_hub.client_count(), dp.stream_hub.client_count()) == (0, 1)
        assert dp.stream_hub.stats()[0]["level"] == "summary"
        assert dp.preview_ws_manager.client_count() == 1     # still gets status pushes
    assert dp.stream_hub.client_count() == 0 and dp.frame_hub.client_count() == 0
    assert dp.relay.status()["stream_fps"] == 30
