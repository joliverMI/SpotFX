"""The device preview's STREAM (protocol 2) — 30 small binary frames a second
per viewer, paced by the viewer's own acknowledgements.

Why this exists (data/preview-perf-plan/report.md, 2026-10-05): the preview
delivered 7.7 frames a second against LedFX's 20.7 on the same link, and the
whole gap was one constant (`device_preview.RELAY_TARGET_FPS = 8`). Raising
that constant alone was measured unsafe — at 60 on a 1 Mbit link the screen
fell 2.3 s behind, because a newest-frame mailbox cannot help once frames
are inside TCP's buffers. This module is the four changes that make a higher
rate safe. `device_preview.py` still owns the SOURCE (ownership routing,
pause, favourites, demand); this module owns DELIVERY to a viewer that said
`hello` with `protocol: 2`. A viewer that never says hello keeps the old
JSON frames (`device_preview._PreviewFrameSender`), unchanged.

1. A STEADY CLOCK, NOT A MINIMUM INTERVAL. Each viewer has one ticker. On
   every tick it sends the NEWEST source frame of each device that has
   changed since this viewer last got it. There is no "has 1/fps passed
   since the last send" test: against a 60 Hz source that test rounds 30
   asked down to 20.7 delivered (it lets through every third frame).

2. BINARY, REAL CELLS ONLY. One WebSocket binary message per tick (layout
   below). A device with a stored profile mask (`storage/device_profiles/
   <id>.json` — the crystal is 976 real cells in a 72x37 rectangle) sends
   only its real cells, in row-major order. Which cells those are goes out
   ONCE, in a text `device_preview_layout` message, before the first frame
   that uses it.

3. FLOW CONTROL. The viewer acknowledges every tick's sequence number. The
   sender stops when too many ticks are unacknowledged and resumes on the
   next ack, so it can never push faster than the link delivers. The rate
   steps down 30 -> 20 -> 15 -> 10 when ticks keep getting held, and back up
   after a quiet spell (the wait doubles each time a step up fails).

   THE WINDOW IS "TWO FRAMES BEYOND THE LINK'S OWN ROUND TRIP", not a flat
   two. A flat limit of two caps the rate at 2 / round-trip: 22 fps on an
   80 ms relayed Tailscale link and 10 on a 200 ms one, whatever the
   bandwidth — which fails the plan's own gate (28 fps on the relay link).
   `ceil(min_rtt * rate)` frames are in flight on a perfectly healthy link;
   the two extra are the queue we tolerate. `MAX_WINDOW_S` bounds it
   absolutely, so a round trip measured wrongly high can never authorise
   seconds of backlog.

   A DEVICE THAT DID NOT CHANGE IS NOT SENT, AND ONE THAT SUDDENLY DID IS
   NOT MADE TO WAIT. A source frame identical to the last one is dropped at
   `publish` (a held Hue colour costs nothing). When a device that had been
   still for `STILL_S` changes, the hub nudges every viewer and that one
   device goes out at once, between ticks — at most one such early message
   per tick interval, and devices that are animating stay on the clock, so
   their spacing is untouched. A scene change on still fixtures shows up to
   one tick (33 ms) sooner.

4. SUBSCRIPTION LEVELS. `summary` (the collapsed top strip) gets three
   bytes per device — the mean colour of its real cells — at most
   `SUMMARY_MAX_FPS`, and only when the colour changed. `full` gets every
   cell. A viewer changes level with a `subscribe` message.

   SCOPE is the other half of a subscription: `favorites` (the top strip's
   own list) or `in_use` — every in-use virtual the Live view draws
   (preview_layout.py). The source reads the extra virtuals only while a
   viewer asks for them, and a `favorites` viewer is never sent them.

WIRE FORMAT, little-endian. Shaped so a WebGL renderer can upload a
record's payload as a colour buffer without copying or re-ordering, and so
the browser can report rate, round trip and frame age from the header alone.

  message header, 20 bytes
    u8   magic      0xD7
    u8   version    1
    u8   records    how many records follow
    u8   rate_fps   the sender's current rate
    u32  seq        tick sequence; the viewer acks this number
    f64  sent_ms    server wall clock at send (epoch ms)
    u16  srtt_ms    server's smoothed ack round trip (0 = not known yet)
    u16  reserved
  record header, 12 bytes, then the payload
    u8   device     index into this connection's layout table
    u8   kind       0 = summary (3 bytes), 1 = full (cells * 3 bytes)
    u16  age_ms     how long the frame waited on the server before sending
    u32  frame_seq  the device's own source frame counter
    u32  length     payload bytes
    payload         r,g,b per cell, row-major over the device's real cells

  viewer -> server (text JSON)
    {"type": "hello", "protocol": 2, "level": "summary" | "full",
     "scope": "favorites" | "in_use"}
    {"type": "subscribe", "level": ..., "scope": ...}
    {"type": "ack", "seq": n}
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import struct
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from spectra import config

logger = logging.getLogger(__name__)

PROTOCOL = 2
MAGIC = 0xD7
WIRE_VERSION = 1
HEADER = struct.Struct("<BBBBIdHH")
RECORD = struct.Struct("<BBHII")
KIND_SUMMARY = 0
KIND_FULL = 1
LEVELS = ("summary", "full")
SCOPES = ("favorites", "in_use")

STREAM_RATES = (30, 20, 15, 10)
SUMMARY_MAX_FPS = 15
# Unacknowledged ticks tolerated BEYOND what the link's round trip accounts
# for (module docstring, point 3).
EXTRA_IN_FLIGHT = 2
# Used until the first ack gives a real round trip.
ASSUMED_RTT_S = 0.1
# Absolute bound on the window, in seconds of frames at the current rate.
MAX_WINDOW_S = 0.6
MIN_RTT_WINDOW_S = 10.0
RATE_EVAL_S = 1.0
# Step down when at least this share of a second's ticks were held.
BLOCKED_SHARE_DOWN = 0.2
UP_HOLD_MIN_S = 4.0
UP_HOLD_MAX_S = 60.0
# An ack this old is treated as lost (a suspended tab): tracking restarts.
ACK_LOST_S = 5.0
SEND_TIMEOUT_S = 10.0
# A device unchanged for this long counts as still; its next change is sent
# early (module docstring, point 3).
STILL_S = 0.05


@dataclass
class DeviceLayout:
    """Where a device's cells sit. `cell_index` is None when every cell of
    the rows x cols rectangle is real."""
    rows: int
    cols: int
    cells: int
    cell_index: Optional[np.ndarray] = None

    def describe(self, index: int, vis_id: str) -> dict:
        mask = None
        if self.cell_index is not None:
            bits = np.zeros(self.rows * self.cols, dtype=np.uint8)
            bits[self.cell_index] = 1
            mask = base64.b64encode(np.packbits(bits).tobytes()).decode("ascii")
        return {"index": index, "vis_id": vis_id, "rows": self.rows,
                "cols": self.cols, "cells": self.cells, "mask": mask}


def profile_cell_index(vis_id: str, pixel_count: int, rows: int) -> Optional[np.ndarray]:
    """Buffer indices of a device's REAL cells from its stored profile, or
    None when there is no profile, it describes a different shape, or every
    cell is real. Never guessed: a profile that does not match the live
    pixel count is ignored, and the whole rectangle is sent."""
    path = config.REPO_ROOT / "storage" / "device_profiles" / f"{vis_id}.json"
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
        runs = np.asarray(profile["mask_rle"], dtype=np.int64)
        if (int(profile.get("pixel_count", 0)) != pixel_count
                or int(profile.get("rows", 0)) != rows
                or int(runs.sum()) != pixel_count):
            return None
        # mask_rle alternates run lengths starting with a run of False.
        values = (np.arange(len(runs)) % 2).astype(bool)
        index = np.flatnonzero(np.repeat(values, runs)).astype(np.uint32)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if len(index) == 0 or len(index) == pixel_count:
        return None
    return index


@dataclass
class SourceFrame:
    seq: int
    at: float
    rgb: np.ndarray                 # uint8, (pixel_count, 3)
    layout: DeviceLayout
    _full: Optional[bytes] = None
    _summary: Optional[bytes] = None

    def _cells(self) -> np.ndarray:
        idx = self.layout.cell_index
        return self.rgb if idx is None else self.rgb[idx]

    def full(self) -> bytes:
        if self._full is None:
            self._full = np.ascontiguousarray(self._cells()).tobytes()
        return self._full

    def summary(self) -> bytes:
        if self._summary is None:
            cells = self._cells()
            mean = cells.mean(axis=0) if len(cells) else np.zeros(3)
            self._summary = bytes(int(round(float(c))) for c in mean)
        return self._summary


def encode_message(seq: int, rate_fps: int, srtt_ms: int, sent_ms: float,
                   records: list[tuple[int, int, int, int, bytes]]) -> bytes:
    """`records` are (device_index, kind, age_ms, frame_seq, payload)."""
    parts = [HEADER.pack(MAGIC, WIRE_VERSION, len(records), rate_fps,
                         seq & 0xFFFFFFFF, sent_ms, min(srtt_ms, 0xFFFF), 0)]
    for device, kind, age_ms, frame_seq, payload in records:
        parts.append(RECORD.pack(device, kind, max(0, min(age_ms, 0xFFFF)),
                                 frame_seq & 0xFFFFFFFF, len(payload)))
        parts.append(payload)
    return b"".join(parts)


def decode_message(data: bytes) -> dict:
    """The inverse of encode_message — for tests and offline tools; the
    browser has its own (spectra/web/src/api/devicePreviewWs.ts)."""
    magic, version, count, rate, seq, sent_ms, srtt_ms, _ = HEADER.unpack_from(data, 0)
    if magic != MAGIC or version != WIRE_VERSION:
        raise ValueError("not a preview stream message")
    offset = HEADER.size
    records = []
    for _ in range(count):
        device, kind, age_ms, frame_seq, length = RECORD.unpack_from(data, offset)
        offset += RECORD.size
        records.append({"device": device, "kind": kind, "age_ms": age_ms,
                        "frame_seq": frame_seq,
                        "payload": data[offset:offset + length]})
        offset += length
    return {"seq": seq, "rate_fps": rate, "sent_ms": sent_ms,
            "srtt_ms": srtt_ms, "records": records}


class ViewerStream:
    """One viewer's ticker, window and rate. The only writer of frames to
    its socket."""

    def __init__(self, ws, hub: "PreviewStreamHub", level: str = "summary",
                 clock: Callable[[], float] = time.monotonic,
                 scope: str = "favorites") -> None:
        self.ws = ws
        self.hub = hub
        self.level = level if level in LEVELS else "summary"
        self.scope = scope if scope in SCOPES else "favorites"
        self._clock = clock
        self.rate_idx = 0
        self.seq = 0
        self._in_flight: dict[int, float] = {}
        self._ack_event = asyncio.Event()
        self._nudge = asyncio.Event()
        self._sudden: set[str] = set()
        self._last_early = 0.0
        self._task: Optional[asyncio.Task] = None
        self._table: list[str] = []
        self._layouts: dict[str, DeviceLayout] = {}
        self._sent_frame: dict[str, int] = {}
        self._sent_summary: dict[str, bytes] = {}
        self._rtt_minima: deque[tuple[float, float]] = deque()
        self.srtt: Optional[float] = None
        self._eval_at = clock() + RATE_EVAL_S
        self._sent_ticks = 0
        self._blocked_ticks = 0
        # How long to wait before trying each faster rate again, per target
        # rate: a failed 20 -> 30 must not be forgotten because 15 -> 20 held.
        self._up_hold: dict[int, float] = {}
        self._last_change = clock()
        self._last_up: Optional[tuple[float, int]] = None
        self._grace_until = 0.0
        self.ticks_sent = 0
        self.ticks_blocked = 0
        self.bytes_sent = 0

    # ── what the viewer tells us ────────────────────────────────────────

    def set_level(self, level: str) -> None:
        if level in LEVELS and level != self.level:
            self.level = level
            # Resend the current picture at the new level even if the source
            # has not moved since.
            self._sent_frame.clear()
            self._sent_summary.clear()

    def set_scope(self, scope: str) -> None:
        if scope in SCOPES and scope != self.scope:
            self.scope = scope
            self.reset_devices()

    def _in_scope(self, vis_id: str) -> bool:
        favorites = self.hub.favorites
        return self.scope == "in_use" or favorites is None or vis_id in favorites

    def ack(self, seq: int) -> None:
        now = self._clock()
        sent_at = self._in_flight.get(seq)
        for s in [s for s in self._in_flight if s <= seq]:
            del self._in_flight[s]
        if sent_at is not None:
            self._note_rtt(now, now - sent_at)
        self._ack_event.set()

    def nudge(self, vis_id: str) -> None:
        """A still device just changed: send it without waiting for the tick."""
        if not self._in_scope(vis_id):
            return
        self._sudden.add(vis_id)
        self._nudge.set()

    def reset_devices(self) -> None:
        """The favourite list changed: forget the layout table so the next
        tick sends a fresh one."""
        self._table = []
        self._layouts = {}
        self._sent_frame.clear()
        self._sent_summary.clear()

    # ── window and rate ─────────────────────────────────────────────────

    @property
    def rate(self) -> int:
        rate = STREAM_RATES[self.rate_idx]
        return min(rate, SUMMARY_MAX_FPS) if self.level == "summary" else rate

    def _note_rtt(self, now: float, rtt: float) -> None:
        self.srtt = rtt if self.srtt is None else 0.8 * self.srtt + 0.2 * rtt
        second = math.floor(now)
        if self._rtt_minima and self._rtt_minima[-1][0] == second:
            if rtt < self._rtt_minima[-1][1]:
                self._rtt_minima[-1] = (second, rtt)
        else:
            self._rtt_minima.append((second, rtt))
        while self._rtt_minima and self._rtt_minima[0][0] < second - MIN_RTT_WINDOW_S:
            self._rtt_minima.popleft()

    def min_rtt(self) -> Optional[float]:
        return min((r for _, r in self._rtt_minima), default=None)

    def window(self) -> int:
        base = self.min_rtt()
        if base is None:
            base = ASSUMED_RTT_S
        rate = self.rate
        natural = math.ceil(base * rate)
        return min(natural, math.ceil(MAX_WINDOW_S * rate)) + EXTRA_IN_FLIGHT

    def _blocked(self) -> bool:
        return len(self._in_flight) >= self.window()

    def _evaluate_rate(self, now: float) -> None:
        if now < self._eval_at:
            return
        sent, blocked = self._sent_ticks, self._blocked_ticks
        self._sent_ticks = self._blocked_ticks = 0
        self._eval_at = now + RATE_EVAL_S
        total = sent + blocked
        if self._last_up is not None and now - self._last_up[0] >= 2 * UP_HOLD_MIN_S:
            self._up_hold.pop(self._last_up[1], None)     # the step up held
            self._last_up = None
        if blocked >= 2 and blocked >= BLOCKED_SHARE_DOWN * total:
            if self.rate_idx < len(STREAM_RATES) - 1:
                if self._last_up is not None and self._last_up[1] == self.rate_idx:
                    # A step up that did not hold: wait twice as long before
                    # trying this rate again.
                    hold = self._up_hold.get(self.rate_idx, UP_HOLD_MIN_S)
                    self._up_hold[self.rate_idx] = min(hold * 2, UP_HOLD_MAX_S)
                self.rate_idx += 1
                self._last_change = now
                self._last_up = None
                # The queue built at the faster rate is still draining; do
                # not read its tail as a verdict on the slower one.
                self._grace_until = now + RATE_EVAL_S
            return
        if blocked == 0 and self.rate_idx > 0:
            target = self.rate_idx - 1
            if now - self._last_change >= self._up_hold.get(target, UP_HOLD_MIN_S):
                self._up_hold.pop(self.rate_idx, None)    # this rate held
                self.rate_idx = target
                self._last_change = now
                self._last_up = (now, target)

    # ── building a tick ─────────────────────────────────────────────────

    def _device_index(self, vis_id: str, layout: DeviceLayout) -> tuple[int, bool]:
        changed = False
        if vis_id not in self._layouts:
            self._table.append(vis_id)
            changed = True
        elif self._layouts[vis_id] is not layout:
            changed = True
        self._layouts[vis_id] = layout
        return self._table.index(vis_id), changed

    def _build(self, now: float, only: Optional[set] = None) -> tuple[Optional[dict], list]:
        layout_changed = False
        records = []
        for vis_id, frame in self.hub.latest().items():
            if only is not None and vis_id not in only:
                continue
            if not self._in_scope(vis_id):
                continue
            if self._sent_frame.get(vis_id) == frame.seq:
                continue
            index, changed = self._device_index(vis_id, frame.layout)
            layout_changed = layout_changed or changed
            self._sent_frame[vis_id] = frame.seq
            if self.level == "full":
                kind, payload = KIND_FULL, frame.full()
            else:
                kind, payload = KIND_SUMMARY, frame.summary()
                if self._sent_summary.get(vis_id) == payload and not changed:
                    continue
                self._sent_summary[vis_id] = payload
            age_ms = int((now - frame.at) * 1000)
            records.append((index, kind, age_ms, frame.seq, payload))
        layout = None
        if layout_changed:
            layout = {"type": "device_preview_layout", "devices": [
                self._layouts[v].describe(i, v) for i, v in enumerate(self._table)]}
        return layout, records

    async def _send_tick(self, now: float, only: Optional[set] = None) -> bool:
        layout, records = self._build(now, only)
        if layout is not None:
            await asyncio.wait_for(self.ws.send_text(json.dumps(layout)),
                                   timeout=SEND_TIMEOUT_S)
        if not records:
            return False
        self.seq += 1
        srtt_ms = int(self.srtt * 1000) if self.srtt is not None else 0
        data = encode_message(self.seq, self.rate, srtt_ms, time.time() * 1000.0,
                              records)
        self._in_flight[self.seq] = now
        await asyncio.wait_for(self.ws.send_bytes(data), timeout=SEND_TIMEOUT_S)
        self.bytes_sent += len(data)
        if only is None:
            self.ticks_sent += 1
            self._sent_ticks += 1
        return True

    async def _run(self) -> None:
        next_at = self._clock()
        try:
            while True:
                delay = next_at - self._clock()
                if delay > 0:
                    try:
                        await asyncio.wait_for(self._nudge.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        pass
                now = self._clock()
                interval = 1.0 / self.rate
                if self._nudge.is_set():
                    self._nudge.clear()
                    if (now < next_at and not self._blocked()
                            and now - self._last_early >= interval):
                        sudden, self._sudden = self._sudden, set()
                        self._last_early = now
                        await self._send_tick(now, only=sudden)
                    if now < next_at:
                        continue        # whatever was not sent early rides the tick
                self._sudden.clear()
                if self._blocked():
                    oldest = min(self._in_flight.values())
                    if now - oldest > ACK_LOST_S:
                        self._in_flight.clear()
                    else:
                        if now >= self._grace_until:
                            self._blocked_ticks += 1
                        self.ticks_blocked += 1
                        self._ack_event.clear()
                        try:
                            await asyncio.wait_for(self._ack_event.wait(),
                                                   timeout=interval)
                        except asyncio.TimeoutError:
                            pass
                        now = self._clock()
                        self._evaluate_rate(now)
                        # Send as soon as the ack that unblocks us arrives.
                        next_at = now
                        continue
                await self._send_tick(now)
                self._evaluate_rate(now)
                # A steady clock: the next tick is one interval after this
                # one was DUE, unless we are already late (never a burst).
                next_at = max(next_at + interval, now)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.info("preview_stream: closing a dead viewer connection")
            try:
                await self.ws.close()
            except Exception:
                pass

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    def stats(self) -> dict:
        min_rtt = self.min_rtt()
        return {"level": self.level, "scope": self.scope, "rate_fps": self.rate,
                "window": self.window(), "in_flight": len(self._in_flight),
                "srtt_ms": round(self.srtt * 1000, 1) if self.srtt is not None else None,
                "min_rtt_ms": round(min_rtt * 1000, 1) if min_rtt is not None else None,
                "ticks_sent": self.ticks_sent, "ticks_blocked": self.ticks_blocked,
                "bytes_sent": self.bytes_sent}


@dataclass
class PreviewStreamHub:
    """The newest frame of every favourite device, and the viewers reading
    them. `publish` is called for EVERY source frame; it only keeps the
    newest, and only does any work while a protocol-2 viewer is connected."""
    clock: Callable[[], float] = time.monotonic
    _latest: dict[str, SourceFrame] = field(default_factory=dict)
    _layouts: dict[tuple[str, int, int], DeviceLayout] = field(default_factory=dict)
    _viewers: dict[object, ViewerStream] = field(default_factory=dict)
    _seq: int = 0
    _changed_at: dict[str, float] = field(default_factory=dict)
    # The top strip's own list; None = no list known (every device is in
    # scope). A "favorites" viewer is sent only these.
    favorites: Optional[set] = None

    def _layout(self, vis_id: str, pixel_count: int, rows: int) -> DeviceLayout:
        key = (vis_id, pixel_count, rows)
        layout = self._layouts.get(key)
        if layout is None:
            rows = max(1, rows)
            cols = pixel_count // rows if rows else pixel_count
            index = profile_cell_index(vis_id, pixel_count, rows)
            layout = DeviceLayout(rows=rows, cols=cols, cell_index=index,
                                  cells=len(index) if index is not None else pixel_count)
            self._layouts[key] = layout
        return layout

    def publish(self, vis_id: str, pixels, rows: int) -> None:
        if not self._viewers:
            return
        rgb = np.clip(np.asarray(pixels), 0, 255).astype(np.uint8).reshape(-1, 3)
        previous = self._latest.get(vis_id)
        if previous is not None and np.array_equal(previous.rgb, rgb):
            return
        now = self.clock()
        was_still = now - self._changed_at.get(vis_id, now) >= STILL_S
        self._changed_at[vis_id] = now
        self._seq += 1
        self._latest[vis_id] = SourceFrame(
            seq=self._seq, at=now, rgb=rgb,
            layout=self._layout(vis_id, len(rgb), rows))
        if was_still:
            for viewer in self._viewers.values():
                viewer.nudge(vis_id)

    def latest(self) -> dict[str, SourceFrame]:
        return self._latest

    def reset(self) -> None:
        """Favourites changed or the source went away: drop what we hold so
        no viewer is shown a device that is no longer being read."""
        self._latest = {}
        self._changed_at = {}
        for viewer in self._viewers.values():
            viewer.reset_devices()

    def wants_in_use(self) -> bool:
        return any(v.scope == "in_use" for v in self._viewers.values())

    def connect(self, ws, level: str = "summary",
                scope: str = "favorites") -> ViewerStream:
        viewer = ViewerStream(ws, self, level=level, clock=self.clock, scope=scope)
        self._viewers[ws] = viewer
        viewer.start()
        return viewer

    async def disconnect(self, ws) -> None:
        viewer = self._viewers.pop(ws, None)
        if viewer is not None:
            await viewer.stop()
        if not self._viewers:
            self._latest = {}

    def viewer(self, ws) -> Optional[ViewerStream]:
        return self._viewers.get(ws)

    def client_count(self) -> int:
        return len(self._viewers)

    def stats(self) -> list[dict]:
        return [v.stats() for v in self._viewers.values()]
