"""THE MAPPING SESSION — the phone's server half for a light-field capture
run: one live connection, greyscale frames, an exposure/white-balance gate
that REFUSES BY NAME, and no audio path at all.

WHY A SECOND SESSION TYPE RATHER THAN A MODE ON THE AV-SYNC ONE (his own
requirement: "never arms audio — no-audio is true by construction, not a
flag"): av_sync_session.Session opens an AudioReference in its own open()
and estimates against a microphone probe. A "mapping mode" on that class
would make no-audio a branch someone can get wrong. This class has no
AudioReference, no mic ingest, no estimator — there is no audio code here
to arm. The seams it DOES reuse are imported, never copied:
av_sync_session.FrameRing (the vision-stage hook, built naming this stage
as its consumer) and av_sync_session.ClockMap.

THE EXPOSURE GATE IS THE WHOLE INSTRUMENT'S HONESTY, and it is a hard
refusal, not a warning. A footprint is `lit - dark` in the camera's own
byte scale, and every footprint in a room is compared against every other
one. If the phone's auto-exposure re-scales between the dark reference and
the lit capture — or between two emitters — every one of those comparisons
is wrong by an unknown factor and NOTHING downstream can detect it: the
grids still look like plausible footprints. So:

  * a run cannot START unless the phone reported BOTH exposure and white
    balance actually locked (what the browser confirmed in getSettings(),
    never what the page asked for);
  * every frame carries the live lock state, and a lock LOST mid-run aborts
    the run by name (`refusal()` says which of the two, and what the mode
    changed to);
  * the refusal text names the phone and the capability, because "mapping
    failed" is useless and "this phone's camera will not lock exposure
    (exposureMode: continuous, capabilities: [continuous])" is actionable.

This is the AV instrument's own refusal-honesty pattern
(av_sync_session._refused / av_sync_correlate's MIN_PEAK_RATIO), applied to
the one systematic that would make a whole map lie.

THE WIRE, deliberately the same message shapes the av-sync phone page
already speaks (spectra/api/rooms.py is the router):
  phone -> server   hello / pong / frame / lock / stop
  server -> phone   welcome / hello_ack / ping / config / status / error
`frame` carries `data` (base64), `width`, `height`, `mime`,
`captured_at_ms` and `lock` — the same envelope av_sync_session._ingest_frame
reads, plus the lock state this stage requires.

PIXELS: `image/grey8` — raw single-byte luminance, width*height bytes, row
major. Not JPEG: a lossy codec's own quantisation lands in the difference
this instrument measures, and decoding one would put an image library in a
path that currently needs none. At 320x180 and 5 fps that is ~58 KB/frame,
~288 KB/s before base64 — the plan's own budget, on his LAN.

WHAT IS WRITTEN TO DISK BY THIS MODULE: nothing. Frames live in the bounded
in-memory ring and the derived grids in another; both are dropped when the
connection closes. The only persisted artefact of a mapping run is the
MAP (numbers), written by spectra/services/light_field.py.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import numpy as np

from spectra.services.av_sync_session import ClockMap, Frame, FrameRing
from spectra.services.light_field import FRAME_H, FRAME_W, downsample

logger = logging.getLogger(__name__)

PING_INTERVAL_S = 2.0
#: The tap's own rate. 5 fps over a 1.5 s capture is ~7 frames averaged —
#: enough to bury sensor noise, few enough that the whole run stays inside
#: the plan's 3-4 s per emitter.
FRAME_FPS = 5.0
#: Raw frames kept for the "check your aim" view only. The DERIVED grids are
#: what a capture averages, and they are kept separately below.
FRAME_RING_MAX = 4
#: Bounded grid history: 5 fps x this = ~24 s, comfortably more than the
#: longest single capture window and bounded regardless of run length.
GRID_RING = 120
#: FULL-RESOLUTION frames, kept ONLY while a caller asks for them
#: (`keep_full_frames`) and bounded the same way the grids are.
#:
#: WHY A SECOND RING AT ALL, and why it is off by default: the light-field
#: map is derived from the 64x36 grid, which is plenty for "where does this
#: fixture's light land". The COMMISSIONING test
#: (spectra/services/commissioning.py) asks a different question — WHICH of
#: 736 individual pixels is this? — and 2304 grid cells cannot resolve 736
#: pixels. So it turns this ring on for the length of its run and off
#: again. Nothing else in this codebase reads it.
#:
#: The cost is bounded and small: 320x180 bytes is ~58 KB, so the whole
#: ring is ~11 MB, in memory only, dropped on disconnect exactly like every
#: other ring here. Still never written to disk — the privacy statement
#: above is unchanged, and remains true.
FULL_RING = 200

GREY_MIME = "image/grey8"

PRIVACY_SUMMARY = {
    "raw_media_leaves_phone": False,
    "sent": "downsampled greyscale frames (320x180, ~5/s) while a mapping "
            "run is active — no audio stream is opened by this page at all",
    "written_to_disk": "storage/spectra/room_maps.json — the derived map "
                       "(per-emitter footprint grids, axis profiles, "
                       "weights, capture context). Never a frame, never an "
                       "image, never audio.",
    "retention": f"in-memory only while connected: <={FRAME_RING_MAX} raw "
                 f"frames and <={GRID_RING} derived grids, both dropped on "
                 f"disconnect",
    "network": "same-origin WebSocket to SPECTRA over whatever network you "
               "already reach it on; nothing is sent anywhere else",
}


@dataclass
class LockState:
    """What the BROWSER confirmed, not what the page asked for. `reported`
    is False until the phone has actually sent a lock report, so "never told
    us" and "told us it failed" are different refusals."""
    reported: bool = False
    exposure_locked: bool = False
    white_balance_locked: bool = False
    exposure_mode: str = ""
    white_balance_mode: str = ""
    exposure_capabilities: list[str] = field(default_factory=list)
    white_balance_capabilities: list[str] = field(default_factory=list)
    changed_at: float = 0.0

    @property
    def locked(self) -> bool:
        return self.reported and self.exposure_locked and self.white_balance_locked

    def as_dict(self) -> dict:
        return {"reported": self.reported,
                "exposure_locked": self.exposure_locked,
                "white_balance_locked": self.white_balance_locked,
                "exposure_mode": self.exposure_mode,
                "white_balance_mode": self.white_balance_mode,
                "exposure_capabilities": list(self.exposure_capabilities),
                "white_balance_capabilities": list(self.white_balance_capabilities),
                "locked": self.locked}


def lock_refusal(lock: LockState, phone: dict | None = None) -> Optional[str]:
    """The refusal text, or None when the camera is genuinely locked. One
    function so the run gate, the mid-run abort and the status surface all
    say the SAME sentence — a refusal a user reads in two different wordings
    reads as two different problems."""
    if not lock.reported:
        return ("the phone has not reported its camera lock state yet — "
                "start the camera on this page and wait for it to settle "
                "before mapping")
    ua = ((phone or {}).get("user_agent") or "").strip()
    who = f" ({ua})" if ua else ""
    missing = []
    if not lock.exposure_locked:
        caps = ", ".join(lock.exposure_capabilities) or "none reported"
        missing.append(f"EXPOSURE (mode is {lock.exposure_mode or 'unknown'}; "
                       f"this camera offers: {caps})")
    if not lock.white_balance_locked:
        caps = ", ".join(lock.white_balance_capabilities) or "none reported"
        missing.append(f"WHITE BALANCE (mode is {lock.white_balance_mode or 'unknown'}; "
                       f"this camera offers: {caps})")
    if not missing:
        return None
    return (f"this browser{who} will not lock " + " and ".join(missing) +
            ". A mapping run is refused: with auto-exposure live, every "
            "footprint is scaled by an unknown, silently changing factor and "
            "the whole map would lie. Try Chrome on this phone, or a camera "
            "app that exposes manual exposure.")


@dataclass
class TimedGrid:
    at_s: float                 # server clock (capture time when pairable)
    grid: np.ndarray
    raw_max: int


@dataclass
class TimedFrame:
    """One full-resolution greyscale frame with the server-clock time it was
    captured. Only kept while `keep_full_frames` is on — see FULL_RING."""
    at_s: float
    frame: np.ndarray           # uint8, height x width


class MappingSession:
    """One phone connection for light-field capture. `send` is the coroutine
    the API layer hands in (ws.send_json)."""

    def __init__(self, send: Callable[[dict], Awaitable[None]], *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.send = send
        self._clock = clock
        self.pose_id = uuid.uuid4().hex[:8]
        self.clockmap = ClockMap()
        self.hello: dict = {}
        self.lock = LockState()
        self.frames = FrameRing(maxlen=FRAME_RING_MAX)
        self.grids: deque[TimedGrid] = deque(maxlen=GRID_RING)
        #: OFF by default: only the commissioning run needs full-resolution
        #: frames, and only for the length of its own run (see FULL_RING).
        self.keep_full_frames = False
        self.full: deque[TimedFrame] = deque(maxlen=FULL_RING)
        self.closed = False
        self.counts = {"frames": 0, "pongs": 0, "rejected": 0}
        self.last_error: Optional[str] = None
        self._pings: dict[int, float] = {}
        self._ping_seq = 0
        self._loop_task: Optional[asyncio.Task] = None
        #: set while a run is in flight, so the run can be aborted from here
        #: the instant a lock is lost rather than at the next capture.
        self.run_abort: Optional[str] = None
        self.run_label: Optional[str] = None

    # ── lifecycle ─────────────────────────────────────────────────────────
    async def open(self) -> None:
        # The frame tap IS the instrument here, not an optional extra: turn
        # it on as part of opening rather than waiting for a separate switch
        # the way av-sync's does (there it is off by default because that
        # instrument does not need pixels at all).
        self.frames.configure(enabled=True, fps=FRAME_FPS, width=FRAME_W)
        await self.send({"type": "welcome", "session_id": self.id,
                         "pose_id": self.pose_id,
                         "frame_tap": self.frames.config(),
                         "frame_size": {"width": FRAME_W, "height": FRAME_H},
                         "mime": GREY_MIME,
                         "privacy": PRIVACY_SUMMARY})
        self._loop_task = asyncio.create_task(
            self._loop(), name=f"spectra-room-map-{self.id}")

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        task, self._loop_task = self._loop_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.frames.clear()
        self.grids.clear()
        self.full.clear()

    async def _loop(self) -> None:
        last_ping = 0.0
        while True:
            try:
                now = self._clock()
                if now - last_ping >= PING_INTERVAL_S or not self.clockmap.ready:
                    last_ping = now
                    await self._ping()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("mapping session %s: loop iteration failed", self.id)
            await asyncio.sleep(0.2)

    async def _ping(self) -> None:
        self._ping_seq += 1
        seq = self._ping_seq
        self._pings[seq] = self._clock()
        for k in [k for k, t in self._pings.items() if self._clock() - t > 10.0]:
            self._pings.pop(k, None)
        await self.send({"type": "ping", "seq": seq})

    # ── inbound ───────────────────────────────────────────────────────────
    async def handle(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "hello":
            self.hello = {k: msg.get(k) for k in
                          ("user_agent", "video", "secure_context", "origin")
                          if k in msg}
            if isinstance(msg.get("lock"), dict):
                self._apply_lock(msg["lock"])
            await self.send({"type": "hello_ack", "session_id": self.id,
                             "pose_id": self.pose_id,
                             "lock": self.lock.as_dict(),
                             "refusal": lock_refusal(self.lock, self.hello)})
        elif kind == "pong":
            seq = msg.get("seq")
            t_phone = msg.get("t_phone_ms")
            sent = self._pings.pop(seq, None)
            if sent is not None and isinstance(t_phone, (int, float)):
                self.clockmap.add(sent, float(t_phone), self._clock())
                self.counts["pongs"] += 1
        elif kind == "lock":
            self._apply_lock(msg)
            await self.send({"type": "status", "lock": self.lock.as_dict(),
                             "refusal": lock_refusal(self.lock, self.hello)})
        elif kind == "frame":
            self._ingest_frame(msg)
        elif kind == "stop":
            self.run_abort = "the phone stopped the run"
        else:
            await self.send({"type": "error",
                             "message": f"unknown message type {kind!r}"})

    def _apply_lock(self, payload: dict) -> None:
        prev = self.lock.locked
        self.lock = LockState(
            reported=True,
            exposure_locked=bool(payload.get("exposure_locked")),
            white_balance_locked=bool(payload.get("white_balance_locked")),
            exposure_mode=str(payload.get("exposure_mode") or ""),
            white_balance_mode=str(payload.get("white_balance_mode") or ""),
            exposure_capabilities=[str(x) for x in (payload.get("exposure_capabilities") or [])],
            white_balance_capabilities=[
                str(x) for x in (payload.get("white_balance_capabilities") or [])],
            changed_at=self._clock())
        if prev and not self.lock.locked and self.run_abort is None:
            # A lock LOST mid-run is the failure this instrument exists to
            # catch: abort by name rather than finish a run whose later
            # footprints are on a different scale than its earlier ones.
            self.run_abort = ("the camera lock was lost mid-run — " +
                              (lock_refusal(self.lock, self.hello) or "unknown"))

    def _ingest_frame(self, msg: dict) -> None:
        if not self.frames.enabled:
            return
        try:
            data = base64.b64decode(msg["data"])
            t_phone = float(msg["captured_at_ms"])
            w = int(msg.get("width") or 0)
            h = int(msg.get("height") or 0)
            mime = str(msg.get("mime") or GREY_MIME)
        except (KeyError, TypeError, ValueError):
            self.counts["rejected"] += 1
            return
        if isinstance(msg.get("lock"), dict):
            self._apply_lock(msg["lock"])
        recv = self._clock()
        t_server = (self.clockmap.to_server(t_phone)
                    if self.clockmap.ready else recv)
        self.frames.push(Frame(captured_at_phone_ms=t_phone,
                               captured_at_server_s=t_server if self.clockmap.ready else None,
                               received_at_server_s=recv, width=w, height=h,
                               mime=mime, data=data))
        self.counts["frames"] += 1
        grid = self._to_grid(data, w, h, mime)
        if grid is None:
            self.counts["rejected"] += 1
            return
        raw_max = int(np.frombuffer(data, dtype=np.uint8).max()) if data else 0
        self.grids.append(TimedGrid(at_s=t_server, grid=grid, raw_max=raw_max))
        if self.keep_full_frames:
            self.full.append(TimedFrame(
                at_s=t_server,
                frame=np.frombuffer(data, dtype=np.uint8).reshape(h, w).copy()))

    def _to_grid(self, data: bytes, w: int, h: int, mime: str) -> Optional[np.ndarray]:
        """grey8 bytes -> the stored 64x36 grid. Rejects anything that is
        not the declared size rather than resampling a surprise: a frame of
        the wrong shape means the page and the server disagree, and quietly
        stretching it would hide that."""
        if mime != GREY_MIME:
            self.last_error = (f"frame mime {mime!r} is not {GREY_MIME!r} — "
                               "the mapping page sends raw greyscale bytes")
            return None
        if w <= 0 or h <= 0 or len(data) != w * h:
            self.last_error = (f"frame is {len(data)} bytes for a declared "
                               f"{w}x{h} greyscale image")
            return None
        try:
            arr = np.frombuffer(data, dtype=np.uint8).reshape(h, w)
            return downsample(arr)
        except ValueError as exc:
            self.last_error = str(exc)
            return None

    # ── what a run consumes ───────────────────────────────────────────────
    async def gather(self, seconds: float, *, min_frames: int = 1
                     ) -> tuple[list[np.ndarray], list[int]]:
        """Average-ready grids captured over the NEXT `seconds`. Returns
        (grids, raw_maxima) — the raw maxima ride along so the caller can
        report saturation without keeping frames.

        Windowed by arrival, not by a frame's own capture stamp: the window
        boundaries here are settle/capture phases of a light write, which
        are hundreds of ms wide, so RTT-scale timing precision buys nothing
        and depending on a paired clock would make a capture fail for a
        reason unrelated to light."""
        start = self._clock()
        await asyncio.sleep(max(0.0, seconds))
        end = self._clock()
        picked = [g for g in list(self.grids) if start <= g.at_s <= end]
        if len(picked) < min_frames:
            # Fall back to whatever arrived at all in this window's span,
            # then say so by returning fewer than asked — the caller decides
            # whether that is enough, never this function silently.
            picked = [g for g in list(self.grids) if g.at_s >= start]
        return [g.grid for g in picked], [g.raw_max for g in picked]

    async def gather_full(self, seconds: float, *, min_frames: int = 1
                          ) -> list["TimedFrame"]:
        """Full-resolution frames captured over the NEXT `seconds`, with
        their server-clock times — the commissioning run's own consumer
        (`gather` above is the map's, and is unchanged).

        Same arrival-windowed rule and same fall-back as `gather`: a caller
        that asked for more than arrived gets fewer and decides for itself,
        rather than this function silently pretending."""
        if not self.keep_full_frames:
            raise RuntimeError(
                "full-resolution frames are not being kept — set "
                "keep_full_frames before a run that needs them")
        start = self._clock()
        await asyncio.sleep(max(0.0, seconds))
        end = self._clock()
        picked = [f for f in list(self.full) if start <= f.at_s <= end]
        if len(picked) < min_frames:
            picked = [f for f in list(self.full) if f.at_s >= start]
        return picked

    def refusal(self) -> Optional[str]:
        return lock_refusal(self.lock, self.hello)

    def status(self) -> dict:
        latest = self.frames.latest()
        return {"session_id": self.id, "pose_id": self.pose_id,
                "closed": self.closed,
                "clock": self.clockmap.as_dict(),
                "counts": dict(self.counts),
                "lock": self.lock.as_dict(),
                "refusal": self.refusal(),
                "frame_tap": self.frames.config(),
                "frames_held": len(self.frames._frames),  # noqa: SLF001 (status only)
                "grids_held": len(self.grids),
                "full_frames_held": len(self.full),
                "keep_full_frames": self.keep_full_frames,
                "latest_frame": latest.meta() if latest else None,
                "last_error": self.last_error,
                "phone": self.hello,
                "audio": "never opened by this session type"}


# ── process-wide registry (one live session at a time) ────────────────────

current: Optional[MappingSession] = None


async def open_session(send: Callable[[dict], Awaitable[None]], **kw: Any) -> MappingSession:
    """One phone at a time — a second connection takes over and the first
    one's rings are dropped, matching av_sync_session.open_session. A room
    has one Admiral."""
    global current
    if current is not None and not current.closed:
        await current.close()
    sess = MappingSession(send, **kw)
    current = sess
    await sess.open()
    return sess


async def close_session(sess: MappingSession) -> None:
    global current
    await sess.close()
    if current is sess:
        current = None


def status() -> dict:
    return {"session": current.status() if current and not current.closed else None,
            "privacy": PRIVACY_SUMMARY}
