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

THE SERVER ASKS FOR THE CAMERA'S PER-RUN SETTINGS (2026-09-01) and this
client answers, in the same one-way shape as everything else here: a
`config` message names a wire frame size (320x180 for a map, 1920x1080 for
a commissioning read — `spectra/services/capture_settings.py` carries the
arithmetic) and, optionally, the four PINNED LEVERS: integration time,
gain, white balance temperature and focus. The client applies what it can,
RE-READS every control out of the device, and reports what came back. It
never decides to proceed anyway and never reports a setting it did not
read.

AND IT RE-ASSERTS THEM ON EVERY RECONNECT. The pinned regime is held here
(`_pinned`) and written to the driver again at each `hello`, so a dropped
socket comes back to a camera pinned the way this session pinned it rather
than to a memory of one. The camera's own `open()` covers the other half —
a reopen after a re-plug or a dead capture pipe — so between them
persistence is entirely software and a power cut costs nothing. Neither is
allowed to CLAIM the regime: both end in a read-back, and the server
refuses on that.

IT SAYS WHO AND WHAT IT IS, and that is what makes its ABSENCE readable.
`hello` carries the machine's name, the client's VERSION as its own field
(not only inside a user-agent string a server would have to regex), the
board it is running on, and `pose_name` — this camera's placement in his own
words, e.g. "the north shelf". SPECTRA keeps the last of these per machine
(`spectra/services/capture_health.py`), so a camera host that is switched
off is named rather than producing the same silence as one that was never
installed. **`pose_name` is a LABEL and never a measurement**: the pose id
is minted in `camera.open()`, and only `pose_fingerprint` can tell a moved
camera from a changed room.

AND IT NEVER UPSCALES. `camera.set_frame_size` clamps the wire size to what
the camera actually captures, so a request bigger than the camera comes
back as an honest downgrade; every frame carries `source_width`/
`source_height` so the server asserts the same thing independently rather
than trusting this promise.
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

from spectra.capture_client.camera import (LEVERS, BaseCamera, CameraLock,
                                           CameraUnavailable, GREY_MIME)

logger = logging.getLogger(__name__)

CLIENT_NAME = "spectra-capture-client"
#: 1.1 (2026-09-02): the wire gained `fresh_frames`, and this client's
#: transport gained the drain behind it. The number moves when what a
#: SERVER can rely on this client for moves — `capture_health` keeps the
#: last one per machine, so "which build is on the camera host" stays a
#: read rather than a guess. `fresh_frames` itself is still the signal
#: anything branches on; a version is for a human reading the record.
CLIENT_VERSION = "1.1"

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
    #: Older frames thrown away to keep the stream fresh, and frames
    #: discarded because a control had just moved. Read off the camera each
    #: cycle so the transport's real depth is a number a reader can see
    #: rather than a promise this client makes about itself.
    stale_dropped: int = 0
    regime_discards: int = 0
    #: How many times the pinned regime has been written to the driver
    #: again — once per reconnect that had something to re-assert. Reported
    #: so "it came back pinned" is a number a reader can see, not a promise.
    reasserts: int = 0
    session_id: str = ""
    pose_id: str = ""
    pose_token: str = ""
    last_refusal: str = ""
    camera_error: str = ""
    last_error: str = ""
    #: The wire size this client is currently sending — the map's own
    #: 320x180 until a run asks for something bigger, and never larger than
    #: what the camera actually captures.
    frame_size: list = field(default_factory=lambda: [320, 180])
    lock: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


class CaptureClient:
    """One camera, one session, held until stopped."""

    def __init__(self, ws_url: str, camera: BaseCamera, *,
                 host: str = "", fps: float = 5.0,
                 pose_name: str = "",
                 clock: Callable[[], float] = time.monotonic,
                 connect: Optional[Callable[[str], Any]] = None) -> None:
        self.ws_url = ws_url
        self.camera = camera
        self.host = host or platform.node()
        #: THIS CAMERA'S PLACEMENT IN HIS OWN WORDS, and it is a LABEL — see
        #: `spectra/capture_client/config.py` for why that word matters here.
        #: It travels in `hello` so a status surface can name WHICH camera is
        #: missing rather than saying "no session"; it is never evidence that
        #: the camera is where it says it is, which is what the pose
        #: fingerprint measures.
        self.pose_name = pose_name
        self.fps = fps
        self._clock = clock
        self._connect = connect or (lambda url: websockets.connect(url))
        self.state = ClientState()
        self._stop = asyncio.Event()
        self._ws = None
        self._last_lock_read = 0.0
        #: THE SESSION'S PINNED REGIME — the last thing the server asked
        #: this camera for, kept so it can be RE-ASSERTED on every
        #: reconnect. The camera keeps its own copy for a reopen
        #: (`camera._wanted`); this one covers the other half of the same
        #: rule, a socket that came back to a server that will not repeat
        #: itself. Both are in memory only: nothing about a pinned camera
        #: is written to disk, and re-asserting is what makes that free.
        self._pinned: dict = {name: None for name, *_ in LEVERS}

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
        self.state.frame_size = list(self.camera.frame_size)
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
                done, _pending = await asyncio.wait(
                    {pump, frames, stop}, return_when=asyncio.FIRST_COMPLETED)
                # A REASON THAT NEVER REACHES A HUMAN IS A SILENT FAILURE.
                # A frame pump that DIED takes the connection down with it,
                # and without this the client simply reconnects for ever
                # with an empty `last_error` — a loop nobody can explain.
                for task in done:
                    if task is stop or task.cancelled():
                        continue
                    exc = task.exception()
                    if exc is not None:
                        self.state.last_error = f"{type(exc).__name__}: {exc}"
                        logger.warning("capture client: the connection ended "
                                       "on %s", self.state.last_error,
                                       exc_info=exc)
            finally:
                for task in (pump, frames, stop):
                    task.cancel()
                self._ws = None
                self.state.connected = False

    async def _hello(self, ws) -> None:
        # RE-ASSERT THE PINNED REGIME BEFORE SAYING HELLO, so the lock this
        # connection opens with is a fresh read-back of the camera as this
        # session pinned it rather than a memory from before the drop. A
        # session that pinned nothing skips it entirely and an ordinary
        # reconnect costs exactly what it always did.
        if any(v is not None for v in self._pinned.values()):
            await self._reassert()
        await ws.send(json.dumps({
            "type": "hello",
            "user_agent": f"{CLIENT_NAME}/{CLIENT_VERSION} "
                          f"({platform.system()} {platform.machine()})",
            "client": CLIENT_NAME, "host": self.host,
            # THE VERSION AS A FIELD, not only inside the user-agent string.
            # A server that has to regex a UA to answer "which build is on
            # the camera machine" will one day answer wrongly; this is the
            # same fact stated where a reader can take it.
            "client_version": CLIENT_VERSION,
            "pose_name": self.pose_name,
            "platform": {"system": platform.system(),
                         "machine": platform.machine(),
                         "python": platform.python_version()},
            "camera": self.camera.describe(),
            # WHETHER THIS CLIENT'S FRAMES ARE FRESH — see
            # `camera.BaseCamera.fresh_frames`. A server measuring light
            # through this connection needs to know whether a frame stamped
            # after a light write can carry photons from before it; a build
            # that does not drain its transport simply does not send this,
            # and the server names that rather than producing a reading it
            # cannot account for.
            "fresh_frames": bool(getattr(self.camera, "fresh_frames", False)),
            "secure_context": True,
            "frame_size": {"width": self.camera.frame_size[0],
                           "height": self.camera.frame_size[1]},
            # A RECONNECT keeps its pose: the camera never closed, so the
            # byte scale either side of the drop is the same one. See the
            # module docstring, and `mapping_session._adopt_pose` for the
            # server's own account of why this is safe.
            "pose_hint": self.camera.pose_token or None,
            "lock": self.camera.lock.as_wire()}))

    async def _reassert(self) -> None:
        """Write the pinned levers to the driver again and read every
        control back. Never raises past the caller: a camera that has gone
        away is a `camera_error`, which is a condition the server already
        has a sentence for."""
        try:
            await self.camera.apply_lock(**self._pinned)
            self.state.reasserts += 1
        except CameraUnavailable as exc:
            self.state.camera_error = str(exc)
            self.camera.lock = CameraLock(camera_error=str(exc),
                                          source="camera:unavailable")
        except Exception as exc:                       # noqa: BLE001
            logger.exception("capture client: re-asserting the pinned "
                             "camera settings failed")
            self.state.last_error = f"{type(exc).__name__}: {exc}"
        self.state.lock = self.camera.lock.as_wire()
        self._last_lock_read = self._clock()

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
            elif kind == "config":
                await self._apply_config(ws, msg)
            elif kind == "error":
                self.state.last_error = str(msg.get("message") or "")

    async def _apply_config(self, ws, msg: dict) -> None:
        """THE SERVER ASKED THE CAMERA FOR SOMETHING. Apply what this camera
        can, re-read every control out of the device, and say what came
        back — including when what came back is not what was asked for.

        Never refuses and never raises past the connection: refusing is the
        server's job and its refusal names the camera and the control. A
        camera that cannot even reopen at the new size reports that as a
        camera error, which is the condition the server already has a
        sentence for."""
        size = msg.get("frame_size") or {}
        try:
            if size.get("width") and size.get("height"):
                got = await self.camera.set_frame_size(
                    (int(size["width"]), int(size["height"])))
                self.state.frame_size = list(got)
                if self.camera.pose_token != self.state.pose_token:
                    # The reopen re-locked the exposure, so this is a NEW
                    # pose. Saying so is the whole point: footprints either
                    # side of it are not comparable.
                    self.state.pose_token = self.camera.pose_token
                    self.state.camera_reopens += 1
            # EVERY LEVER THIS SESSION HAS EVER BEEN ASKED FOR, not just
            # the ones in this message: a config that names an integration
            # time must not silently un-pin the focus a previous one set.
            # A lever is un-pinned by naming it null, which is the only way
            # to say "let this one go" without saying it about all of them.
            for lever, *_ in LEVERS:
                if lever in msg:
                    value = msg.get(lever)
                    self._pinned[lever] = (None if value is None
                                           else int(value))
            await self.camera.apply_lock(**self._pinned)
        except CameraUnavailable as exc:
            self.state.camera_error = str(exc)
            self.camera.lock = CameraLock(camera_error=str(exc),
                                          source="camera:unavailable")
        except Exception as exc:                       # noqa: BLE001
            logger.exception("capture client: applying the camera config failed")
            self.state.last_error = f"{type(exc).__name__}: {exc}"
        self.state.lock = self.camera.lock.as_wire()
        self._last_lock_read = self._clock()
        await ws.send(json.dumps({"type": "lock", **self.camera.lock.as_wire()}))

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
            fw, fh = self.camera.frame_size
            cw, ch = self.camera.capture_size
            await ws.send(json.dumps({
                "type": "frame", "mime": GREY_MIME,
                "width": fw, "height": fh,
                # WHAT THE FRAME WAS DERIVED FROM. The server drops any
                # frame bigger than its own source rather than counting
                # interpolated pixels as resolution, so "never upscale" is
                # asserted on both sides instead of promised on one.
                "source_width": cw, "source_height": ch,
                "captured_at_ms": self._clock() * 1000.0,
                "data": base64.b64encode(data).decode("ascii"),
                "lock": self.camera.lock.as_wire()}))
            self.state.frames_sent += 1
            self.state.stale_dropped = getattr(self.camera, "stale_dropped", 0)
            self.state.regime_discards = getattr(
                self.camera, "regime_discards", 0)
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
