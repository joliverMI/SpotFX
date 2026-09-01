"""THE UNATTENDED CAPTURE SESSION — the half that used to be a person
holding a phone.

WHAT IT REPLACES, step for step. A capture run needed someone to: open the
Rooms page on a device with a camera, grant the camera, wait for the
exposure lock to confirm, aim it at the room, keep the tab alive for the
whole run, and press Start. This client does all of that except AIMING —
which is a physical act and stays one — and holds the session for as long
as it is asked to, reconnecting through drops.

WHAT IT IS NOT ALLOWED TO REPLACE. The gate. It sends exactly what
`camera.read_lock()` read out of the device, on connect and on every frame,
and the server refuses on its own terms. There is no flag here that makes a
run happen anyway, and there is no code path that reports a lock the camera
did not confirm — see `camera.py`'s docstring, which is the binding
statement for that.

RECONNECTION, and the one thing about it that is not obvious. A dropped
WebSocket moves no camera and re-locks no exposure, so the client keeps its
open camera and RE-ASSERTS its pose (`pose_hint`) when it comes back: the
map either side of that drop is one measurement, and minting a fresh pose
id would label it as two. When the CAMERA has to be reopened — the capture
pipe died, the device came back — the pose token is minted again inside
`open()` and the queue will see and NAME the change
(`mapping_refusals.pose_changed_note`). The client never decides that a
pose survived; the placement of the token decides it.

A CLIENT WITH NO CAMERA STILL CONNECTS, deliberately. Dying quietly on a
laptop nobody is looking at is the failure mode this whole task exists to
remove: it connects, reports `camera_error`, and the run refuses with that
sentence on the page and in the queue's record instead of the generic "has
not reported its lock state yet".
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import platform
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import websockets

from spectra.capture_client.camera import (BaseCamera, CameraLock,
                                           CameraUnavailable, FRAME_H,
                                           FRAME_W, GREY_MIME)

logger = logging.getLogger(__name__)

CLIENT_NAME = "spectra-capture-client"
CLIENT_VERSION = "1.0"

#: Reconnect backoff. Short at first (a service restart is seconds) and
#: capped low: this client's whole job is to BE there when the queue looks,
#: and the queue's own session wait is measured in minutes.
RECONNECT_MIN_S = 0.5
RECONNECT_MAX_S = 5.0
#: How often the lock is re-read from the DEVICE rather than reused. Every
#: frame carries a lock state; re-reading a V4L2 control costs a subprocess,
#: so the read is paced and the frames in between carry the last read-back.
#: A camera that silently returns to auto is therefore caught within this,
#: which is well inside a single capture window's own settle.
LOCK_REREAD_S = 2.0


@dataclass
class ClientState:
    connected: bool = False
    connects: int = 0
    drops: int = 0
    frames_sent: int = 0
    camera_reopens: int = 0
    session_id: str = ""
    pose_id: str = ""
    pose_token: str = ""
    last_refusal: str = ""
    camera_error: str = ""
    last_error: str = ""
    lock: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


class CaptureClient:
    """One camera, one session, held until stopped."""

    def __init__(self, ws_url: str, camera: BaseCamera, *,
                 host: str = "", fps: float = 5.0,
                 clock: Callable[[], float] = time.monotonic,
                 connect: Optional[Callable[[str], Any]] = None) -> None:
        self.ws_url = ws_url
        self.camera = camera
        self.host = host or platform.node()
        self.fps = fps
        self._clock = clock
        self._connect = connect or (lambda url: websockets.connect(url))
        self.state = ClientState()
        self._stop = asyncio.Event()
        self._ws = None
        self._last_lock_read = 0.0

    # ── lifecycle ─────────────────────────────────────────────────────────
    async def start_camera(self) -> Optional[str]:
        """Open the camera and lock it. Returns the camera's own failure
        sentence, or None. NEVER raises for a missing camera: the client
        connects either way, because a refusal that reaches a surface is
        worth more than a process that exits."""
        try:
            await self.camera.open()
        except CameraUnavailable as exc:
            self.state.camera_error = str(exc)
            self.camera.lock = CameraLock(camera_error=str(exc),
                                          source="camera:unavailable")
            return str(exc)
        except Exception as exc:                       # noqa: BLE001
            # An unexpected failure opening a camera is still a camera that
            # is not there, from the room's point of view.
            logger.exception("capture client: opening the camera failed")
            self.state.camera_error = f"{type(exc).__name__}: {exc}"
            self.camera.lock = CameraLock(camera_error=self.state.camera_error,
                                          source="camera:unavailable")
            return self.state.camera_error
        self.state.camera_error = ""
        self.state.pose_token = self.camera.pose_token
        self.state.lock = self.camera.lock.as_wire()
        self._last_lock_read = self._clock()
        return None

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> ClientState:
        """Hold the session until stopped, reconnecting through drops."""
        backoff = RECONNECT_MIN_S
        while not self._stop.is_set():
            try:
                await self._one_connection()
                backoff = RECONNECT_MIN_S
            except asyncio.CancelledError:
                raise
            except Exception as exc:                   # noqa: BLE001
                self.state.last_error = f"{type(exc).__name__}: {exc}"
                logger.info("capture client: connection ended (%s)",
                            self.state.last_error)
            self.state.connected = False
            if self._stop.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(RECONNECT_MAX_S, backoff * 2)
        await self.camera.close()
        return self.state

    # ── one connection ────────────────────────────────────────────────────
    async def _one_connection(self) -> None:
        async with await self._connect(self.ws_url) as ws:
            self._ws = ws
            self.state.connected = True
            self.state.connects += 1
            if self.state.connects > 1:
                self.state.drops += 1
            await self._hello(ws)
            pump = asyncio.create_task(self._pump(ws))
            frames = asyncio.create_task(self._frames(ws))
            stop = asyncio.create_task(self._stop.wait())
            try:
                await asyncio.wait({pump, frames, stop},
                                   return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in (pump, frames, stop):
                    task.cancel()
                self._ws = None
                self.state.connected = False

    async def _hello(self, ws) -> None:
        await ws.send(json.dumps({
            "type": "hello",
            "user_agent": f"{CLIENT_NAME}/{CLIENT_VERSION} "
                          f"({platform.system()} {platform.machine()})",
            "client": CLIENT_NAME, "host": self.host,
            "camera": self.camera.describe(),
            "secure_context": True,
            # A RECONNECT keeps its pose: the camera never closed, so the
            # byte scale either side of the drop is the same one. See the
            # module docstring, and `mapping_session._adopt_pose` for the
            # server's own account of why this is safe.
            "pose_hint": self.camera.pose_token or None,
            "lock": self.camera.lock.as_wire()}))

    async def _pump(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                continue
            kind = msg.get("type")
            if kind == "ping":
                await ws.send(json.dumps({
                    "type": "pong", "seq": msg.get("seq"),
                    "t_phone_ms": self._clock() * 1000.0}))
            elif kind in ("hello_ack", "status"):
                self.state.session_id = str(msg.get("session_id")
                                            or self.state.session_id)
                self.state.pose_id = str(msg.get("pose_id")
                                         or self.state.pose_id)
                self.state.last_refusal = str(msg.get("refusal") or "")
            elif kind == "welcome":
                self.state.session_id = str(msg.get("session_id") or "")
                self.state.pose_id = str(msg.get("pose_id") or "")
            elif kind == "error":
                self.state.last_error = str(msg.get("message") or "")

    async def _frames(self, ws) -> None:
        period = 1.0 / max(0.5, self.fps)
        while not self._stop.is_set():
            started = self._clock()
            if self.state.camera_error:
                # Nothing to send. Keep the connection and keep saying why:
                # the run's refusal is the camera's own sentence.
                await ws.send(json.dumps({"type": "lock",
                                          **self.camera.lock.as_wire()}))
                await asyncio.sleep(2.0)
                continue
            data = await self.camera.frame()
            if data is None:
                # The capture pipe died. Reopening MINTS A NEW POSE, which
                # the queue will see and name — the camera's exposure has
                # been locked again and its scale starts over.
                await self._reopen_camera()
                continue
            if self._clock() - self._last_lock_read >= LOCK_REREAD_S:
                await self.camera.read_lock()
                self._last_lock_read = self._clock()
                self.state.lock = self.camera.lock.as_wire()
            await ws.send(json.dumps({
                "type": "frame", "mime": GREY_MIME,
                "width": FRAME_W, "height": FRAME_H,
                "captured_at_ms": self._clock() * 1000.0,
                "data": base64.b64encode(data).decode("ascii"),
                "lock": self.camera.lock.as_wire()}))
            self.state.frames_sent += 1
            spent = self._clock() - started
            if spent < period:
                await asyncio.sleep(period - spent)

    async def _reopen_camera(self) -> None:
        self.state.camera_reopens += 1
        try:
            await self.camera.close()
        except Exception:                              # noqa: BLE001
            logger.debug("capture client: closing a dead camera failed",
                         exc_info=True)
        problem = await self.start_camera()
        if problem:
            logger.warning("capture client: camera could not be reopened: %s",
                           problem)
        # The pose token changed with the reopen; the next hello carries it.
        # This connection keeps running so the server hears the new lock
        # state (or the camera error) immediately.
        if self._ws is not None:
            await self._ws.send(json.dumps({"type": "lock",
                                            **self.camera.lock.as_wire()}))
