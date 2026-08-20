"""Before/after evidence for the device-preview transport fix
(data/preview-frame-rate-is-still-bad-over-rem-dhvp/, his report: "the
frame rate on the preview is still terrible. Remember, I'm always on a
remote computer, but LEDFx previews were really good").

WHAT WAS TRIED BEFORE AND WHY IT DIDN'T HOLD (the "still" in his report):
PR #115 (fm/spectra-preview-smoothness, docs/SPECTRA_SPEC.md §43) already
investigated "choppy preview" once. It measured SOURCE (~62fps, fine),
TRANSPORT (relay achieves ~7.66fps against its own 8fps target, fine), and
RENDER (DOM-per-pixel reconciliation cost, the real bottleneck it fixed
with a canvas repaint) — and concluded payload size "was never actually
load-bearing," based on timing `JSON.parse` + `decodePixels()` of a full
crystal-mapper frame at <1ms. That is a LOCAL CPU measurement. It never
asked how long the same bytes take to arrive over a bandwidth-constrained
link — which is exactly his stated, permanent condition ("I'm always on a
remote computer"). This script closes that gap: it measures actual
wall-clock delivery time over a real (throttled loopback) TCP socket, not
CPU decode time, for the OLD encoding (reproduced below, byte-for-byte,
for comparison — it no longer exists in the shipped code) against the NEW
one (`spectra.services.device_preview._facade_frame_payload`, base64,
matching LedFX's own default `transmission_mode="compressed"`).

WHAT THIS DOES NOT PROVE: this is a throttled-loopback simulation of a
constrained link (rate-limited real socket I/O, not just arithmetic), NOT
a test against his actual remote connection — his room/browser were never
touched, per this task's own hard limits. Bandwidth figures below are
chosen to be representative of a constrained remote/VPN link, not measured
from his real one. Report this measurement as what it is: a remote-
EQUIVALENT proxy, not a field result.

Run: .venv/bin/python scripts/check_device_preview_remote_transport.py
No live storage, no LedFX, no audio; a loopback TCP server/client pair on
an ephemeral port is the only I/O.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from spectra.services.device_preview import _facade_frame_payload


class _FakeVirtual:
    def __init__(self, rows: int) -> None:
        self.rows = rows


class _FakeHost:
    def __init__(self, rows: int) -> None:
        self.virtuals = {"dev": _FakeVirtual(rows)}


def _old_encoding_payload(vis_id: str, pixels: np.ndarray, rows: int) -> dict:
    """Byte-for-byte reproduction of the encoding `_facade_frame_payload`
    used before this fix (channel-planar JSON lists) — kept here only as
    the "before" side of the comparison; the shipped module no longer
    contains this code path."""
    pixel_count = int(pixels.shape[0])
    cols = pixel_count // rows if rows else pixel_count
    channels = np.clip(pixels, 0, 255).astype(np.uint8).T.tolist()
    return {
        "type": "device_preview_frame",
        "vis_id": vis_id,
        "pixels": channels,
        "shape": [rows, cols],
        "is_device": False,
    }


def _synthetic_pixels(pixel_count: int) -> np.ndarray:
    rng = np.random.default_rng(12345)
    return rng.integers(0, 256, size=(pixel_count, 3)).astype(np.float64)


DEVICES = [
    ("crystal-mapper (his real Matrix favourite)", 2664, 37),
    ("hues strip", 17, 1),
    ("hue-lights strip", 10, 1),
    ("dining-hues strip", 7, 1),
]


def measure_bytes():
    print("=== Bytes per frame (exact, from the real serialization code) ===")
    rows_out = []
    for name, pixel_count, rows in DEVICES:
        pixels = _synthetic_pixels(pixel_count)
        host = _FakeHost(rows)
        old = json.dumps(_old_encoding_payload("dev", pixels, rows))
        new = json.dumps(_facade_frame_payload("dev", pixels, host))
        old_bytes, new_bytes = len(old.encode()), len(new.encode())
        ratio = old_bytes / new_bytes
        print(f"{name:38s} old={old_bytes:7d}B  new={new_bytes:7d}B  "
              f"({ratio:.2f}x smaller)")
        rows_out.append((name, pixel_count, old_bytes, new_bytes))
    return rows_out


async def _throttled_server(host_ip: str, port: int, bytes_per_sec: float,
                            payload: bytes, n_frames: int, latency_s: float):
    """A loopback TCP server that sends `n_frames` copies of `payload`,
    length-prefixed, paced to `bytes_per_sec` — a real rate-limited socket
    write, not an arithmetic estimate. `latency_s` is an artificial delay
    applied once per frame (simulating one-way network latency on a real
    remote link, which a pure bandwidth cap alone doesn't model)."""
    async def handle(reader, writer):
        chunk_size = max(1024, int(bytes_per_sec * 0.02))  # ~20ms worth per write
        for _ in range(n_frames):
            await asyncio.sleep(latency_s)
            writer.write(len(payload).to_bytes(4, "big"))
            sent = 0
            while sent < len(payload):
                chunk = payload[sent:sent + chunk_size]
                writer.write(chunk)
                await writer.drain()
                sent += len(chunk)
                await asyncio.sleep(len(chunk) / bytes_per_sec)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, host_ip, port)
    async with server:
        await server.serve_forever()


async def _client_measure(host_ip: str, port: int, n_frames: int) -> float:
    reader, writer = await asyncio.open_connection(host_ip, port)
    t0 = time.monotonic()
    received = 0
    while received < n_frames:
        len_bytes = await reader.readexactly(4)
        length = int.from_bytes(len_bytes, "big")
        await reader.readexactly(length)
        received += 1
    elapsed = time.monotonic() - t0
    writer.close()
    return elapsed


async def _run_throttled_trial(payload: bytes, bytes_per_sec: float,
                               n_frames: int, latency_s: float) -> float:
    port = 0
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()

    srv_task = asyncio.create_task(
        _throttled_server("127.0.0.1", port, bytes_per_sec, payload, n_frames, latency_s))
    await asyncio.sleep(0.05)
    try:
        elapsed = await asyncio.wait_for(
            _client_measure("127.0.0.1", port, n_frames), timeout=60.0)
    finally:
        srv_task.cancel()
        try:
            await srv_task
        except (asyncio.CancelledError, Exception):
            pass
    return elapsed


def measure_remote_equivalent():
    print()
    print("=== Remote-equivalent delivery (real throttled-loopback socket) ===")
    print("Simulated link: bandwidth cap + a fixed per-frame latency, chosen to be")
    print("representative of a constrained remote/VPN connection — NOT his real")
    print("link, which this task never touched.")
    name, pixel_count, rows = DEVICES[0]  # crystal-mapper — the worst case
    pixels = _synthetic_pixels(pixel_count)
    host = _FakeHost(rows)
    old_payload = json.dumps(_old_encoding_payload("dev", pixels, rows)).encode()
    new_payload = json.dumps(_facade_frame_payload("dev", pixels, host)).encode()

    target_fps = 8.0  # RELAY_TARGET_FPS
    n_frames = 24  # 3 seconds' worth at the relay's own target rate

    for label, bw_mbps, latency_ms in [
        ("modest remote link (2 Mbps, 60ms latency)", 2.0, 60),
        ("poor remote link (768 kbps, 120ms latency)", 0.768, 120),
    ]:
        bytes_per_sec = bw_mbps * 1_000_000 / 8
        latency_s = latency_ms / 1000.0
        old_elapsed = asyncio.run(_run_throttled_trial(old_payload, bytes_per_sec, n_frames, latency_s))
        new_elapsed = asyncio.run(_run_throttled_trial(new_payload, bytes_per_sec, n_frames, latency_s))
        old_fps = n_frames / old_elapsed
        new_fps = n_frames / new_elapsed
        print(f"\n{label}, device={name}:")
        print(f"  old encoding: {n_frames} frames in {old_elapsed:.2f}s -> {old_fps:.2f} fps "
              f"(target {target_fps:.0f} fps)")
        print(f"  new encoding: {n_frames} frames in {new_elapsed:.2f}s -> {new_fps:.2f} fps "
              f"(target {target_fps:.0f} fps)")


if __name__ == "__main__":
    measure_bytes()
    measure_remote_equivalent()
    print("\nDone. See docstring for what this does and does not prove.")
