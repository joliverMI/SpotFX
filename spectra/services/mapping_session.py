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

TWO CLIENTS SPEAK THIS WIRE, and the gate cannot tell them apart on
purpose. The Rooms page on a phone is one (`spectra/web/src/rooms/
mappingCapture.ts`, confirming the lock out of `getSettings()`); the
UNATTENDED CAPTURE CLIENT is the other (`spectra/capture_client/`, a
process on a machine with a webcam, confirming the lock out of the V4L2
control it just read back). Both report what the DEVICE said and neither
gets to decide to proceed anyway — the gate reads two booleans and refuses,
and `lock.source` records whose read-back they came from without changing
how much they are trusted.

THE WIRE, deliberately the same message shapes the av-sync phone page
already speaks (spectra/api/rooms.py is the router):
  client -> server  hello / pong / frame / lock / stop
  server -> client  welcome / hello_ack / ping / config / status / error
`frame` carries `data` (base64), `width`, `height`, `mime`,
`captured_at_ms` and `lock` — the same envelope av_sync_session._ingest_frame
reads, plus the lock state this stage requires. `hello` may carry a
`pose_hint`, which a RECONNECTING client uses to say its camera never
closed and its exposure was never re-locked (see `_adopt_pose`), and a
`camera_error`, which is how a client with no camera at all still says so
out loud.

PIXELS: `image/grey8` — raw single-byte luminance, width*height bytes, row
major. Not JPEG, at ANY frame size: a lossy codec's own quantisation lands
in the difference this instrument measures, and decoding one would put an
image library in a path that currently needs none.

THE FRAME SIZE IS PER RUN, NOT ONE NUMBER (2026-09-01). `spectra/services/
capture_settings.py` is the binding statement — the ladder of declared
sizes, the arithmetic that chose them, and why a client must never upscale.
The short version:

  * A MAP still sends 320x180, ~58 KB/frame, ~288 KB/s before base64 — a
    footprint is a 64x36 grid and more pixels buy nothing. Night runs stay
    cheap.
  * A COMMISSIONING read asks for 1920x1080, because a gray-code decode
    needs ~2 camera pixels per composition index and his 736-pixel
    composition therefore needs ~1,472 of imaged strip, where the WHOLE
    perimeter of a 320x180 frame is 1,000. No pose could ever have worked;
    both field runs of 2026-09-01 decoded 0 of 736 for exactly that reason.
  * Every rung is 16:9 and an exact whole multiple of the 64x36 grid, so
    `light_field.downsample` stays a box mean at any of them and the STORED
    MAP GRID IS UNCHANGED.
  * A CLIENT NEVER UPSCALES. It sends the largest rung no bigger than both
    the request and its own camera image, and reports its source size on
    every frame; a frame that arrives larger than its source is NAMED
    (`mapping_refusals.upscaled_frame`) and never counted, because
    interpolated pixels would inflate `gray_code.resolution_report`'s count
    and make an unreadable target report that it is readable.

THE CAMERA'S FOUR PINNED LEVERS ride the same `config` message: integration
time, gain, white balance temperature and focus — all optional, all
defaulting to today's converge-then-freeze behaviour, all READ BACK from the
device and reported here like the lock is.
`capture_settings.CameraRequest` is what a run asks for; `LockState` is what
the camera said. They are never the same object, for the same reason
`lock_refusal` reads a read-back and not a constraint. Only the NATIVE
client can reach the last two; a browser session reports them as None, which
is what "not reported" has always meant here.

AND A DRIVER'S ANSWER IS STILL NOT THE LIGHT. Every read-back on this page
proves what the driver holds. Whether the SENSOR obeys it is a different
claim and needs a measurement — `spectra/services/lever_selftest.py` drives
a known emitter, commands two integration times a known factor apart, and
watches the measured light move. A native session runs it before any
calibration-grade run and its verdict rides on the session
(`lever_verdict`).

WHAT IS WRITTEN TO DISK BY THIS MODULE: one small row saying WHICH MACHINE
IS HOLDING THE CAMERA, and nothing else — no frame, no grid, no image, no
audio, ever. Frames live in the bounded in-memory ring and the derived grids
in another; both are dropped when the connection closes, and the persisted
artefact of a mapping run is still the MAP (numbers), written by
spectra/services/light_field.py.

The row (`capture_health.note_session`, written at hello and at close) is
the machine's name, its build, its declared placement, its camera's
description and its lock state — the same things `hello` already carries
over the wire, kept so that a camera host being GONE is a read rather than
the same silence as one that never existed. It gates nothing; see
`spectra/services/capture_health.py` for that boundary stated properly.
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

from spectra.services import capture_health, capture_settings
from spectra.services.av_sync_session import ClockMap, Frame, FrameRing
from spectra.services.light_field import FRAME_H, FRAME_W, downsample

logger = logging.getLogger(__name__)

#: THE MAP'S OWN FRAME, re-exported from `light_field` (where it is derived
#: from the stored grid) and asserted here to be the ladder's own bottom
#: rung. Two modules naming the same size is fine; two modules DISAGREEING
#: about it silently would put the wire and the downsample out of step.
assert (FRAME_W, FRAME_H) == capture_settings.MAP_PROFILE

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
#: THE RING IS BOUNDED IN BYTES, NOT FRAMES, since the commissioning read
#: moved to 1920x1080: 200 frames is ~11 MB at 320x180 and ~414 MB at
#: 1080p, and only one of those is a ring. `capture_settings.full_ring_len`
#: owns the budget, so the length follows the size that is actually
#: arriving (48 frames at 1080p — a capture window is a handful). In memory
#: only, dropped on disconnect exactly like every other ring here, still
#: never written to disk: the privacy statement above is unchanged.
#: The CEILING on that length. The ring is built at
#: `capture_settings.full_ring_len(*frame_size)` and rebuilt whenever
#: the size changes; this is the largest it can ever be.
FULL_RING = capture_settings.FULL_RING_MAX

GREY_MIME = "image/grey8"

PRIVACY_SUMMARY = {
    "raw_media_leaves_phone": False,
    "sent": "downsampled greyscale frames while a run is active, ~5/s and "
            "never compressed — 320x180 for a light-field map, and up to "
            "1920x1080 for the commissioning read, which has to tell "
            "individual LEDs apart. No audio stream is opened by this page "
            "at all",
    "written_to_disk": "storage/spectra/room_maps.json — the derived map "
                       "(per-emitter footprint grids, axis profiles, "
                       "weights, capture context) — and "
                       "storage/spectra/capture_health.json, one row per "
                       "camera MACHINE (its name, build, declared placement "
                       "and lock state, so a host that is gone can be named "
                       "rather than merely absent). Never a frame, never an "
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
    #: The client could not open a camera AT ALL — a different condition
    #: from "opened it and it will not lock", and one only the capture
    #: machine can know. Carried here so an unattended client that finds no
    #: camera still CONNECTS and says so, instead of dying quietly on a
    #: laptop nobody is looking at; the refusal then names the real reason
    #: rather than the generic "has not reported its lock state yet".
    camera_error: str = ""
    #: WHAT confirmed this lock, in the client's own words — "getSettings"
    #: for the browser page, "v4l2:auto_exposure" for the native client.
    #: Reported, never trusted differently: the gate reads the two booleans,
    #: and this says whose read-back they came from.
    source: str = ""
    #: THE TWO LEVERS, AS THE DEVICE REPORTED THEM BACK — never what was
    #: asked for. `exposure_time` is in 100-microsecond units on BOTH paths
    #: (V4L2 `exposure_time_absolute`, W3C `exposureTime`), so nothing
    #: converts it; `gain` is a device-specific scale passed through
    #: verbatim (V4L2 `gain`, the browser's `iso`). None means the client
    #: could not read it, which is a different thing from zero.
    #: See `spectra/services/capture_settings.py`.
    exposure_time: Optional[float] = None
    gain: Optional[float] = None
    #: THE OTHER TWO PINNED LEVERS (2026-09-01), same rule and same source:
    #: white balance TEMPERATURE in Kelvin and FOCUS on the device's own
    #: scale. Only the native client can pin these — the browser page has no
    #: way to reach them — so they are None on every browser session, which
    #: is exactly what "not reported" has always meant here.
    white_balance: Optional[float] = None
    focus: Optional[float] = None
    #: Whether this camera's own continuous autofocus reads OFF. None when
    #: it has no such control.
    focus_auto: Optional[bool] = None
    #: The device's own declared ranges, when it declares them — what a
    #: refusal quotes so "gain 800 was refused" says what the camera offers.
    exposure_time_range: Optional[list[float]] = None
    gain_range: Optional[list[float]] = None
    white_balance_range: Optional[list[float]] = None
    focus_range: Optional[list[float]] = None
    #: Controls a run ASKED FOR that this camera does not offer or did not
    #: take, in the client's own words. A run that asked for a manual lever
    #: and got this refuses BY NAME rather than measuring under whatever the
    #: camera decided instead.
    manual_refusals: list[str] = field(default_factory=list)
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
                "camera_error": self.camera_error, "source": self.source,
                "exposure_time": self.exposure_time, "gain": self.gain,
                "white_balance": self.white_balance, "focus": self.focus,
                "focus_auto": self.focus_auto,
                "exposure_time_range": (list(self.exposure_time_range)
                                        if self.exposure_time_range else None),
                "gain_range": (list(self.gain_range) if self.gain_range
                               else None),
                "white_balance_range": (list(self.white_balance_range)
                                        if self.white_balance_range else None),
                "focus_range": (list(self.focus_range) if self.focus_range
                                else None),
                "manual_refusals": list(self.manual_refusals),
                "locked": self.locked}


def _number(value) -> Optional[float]:
    """A read-back number, or None. None and 0 are different answers here —
    "this camera would not tell us its exposure" is not "its exposure is
    zero" — so a junk value becomes None rather than a plausible float."""
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _pair(value) -> Optional[list[float]]:
    """A [min, max] the device declared, or None."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    lo, hi = _number(value[0]), _number(value[1])
    return None if lo is None or hi is None else [lo, hi]


def lock_refusal(lock: LockState, phone: dict | None = None) -> Optional[str]:
    """The refusal text, or None when the camera is genuinely locked. One
    function so the run gate, the mid-run abort and the status surface all
    say the SAME sentence — a refusal a user reads in two different wordings
    reads as two different problems.

    IT SPEAKS TO BOTH CLIENT KINDS. The phone's page and the unattended
    capture client hit exactly the same condition for exactly the same
    reason, so there is one sentence, and it names the remedy on each
    (`hello`'s `user_agent`/`host` say which machine is being talked to)."""
    ua = ((phone or {}).get("user_agent") or "").strip()
    if lock.camera_error:
        # A capture machine with NO camera is its own condition, and it is
        # the one an unattended client hits first. `mapping_refusals` owns
        # the wording, like every other expected condition on this path.
        from spectra.services import mapping_refusals
        return mapping_refusals.no_camera(
            lock.camera_error, ((phone or {}).get("host") or ua or ""))
    if not lock.reported:
        return ("the phone has not reported its camera lock state yet — "
                "start the camera on this page and wait for it to settle "
                "before mapping")
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
    return (f"this camera{who} will not lock " + " and ".join(missing) +
            ". A mapping run is refused: with auto-exposure live, every "
            "footprint is scaled by an unknown, silently changing factor and "
            "the whole map would lie. On a phone, try Chrome, or a camera app "
            "that exposes manual exposure; on a capture machine, check "
            "`v4l2-ctl --list-ctrls` for an auto_exposure control this camera "
            "actually has.")


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


class MappingSession(capture_settings.CameraNegotiation):
    """One phone connection for light-field capture. `send` is the coroutine
    the API layer hands in (ws.send_json).

    THE CAMERA'S PER-RUN SETTINGS — the wire frame size and the two manual
    levers — live in `capture_settings.CameraNegotiation`, which this
    inherits and every test double inherits too, so a gate is written once
    and exercised by the proofs rather than modelled by them. This class
    supplies the four things only a session knows: how to send, what time it
    is, when frames arrived, and what the lock read back."""

    def __init__(self, send: Callable[[dict], Awaitable[None]], *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.send = send
        self._clock = clock
        self.pose_id = uuid.uuid4().hex[:8]
        #: True when the CLIENT supplied this pose id on connect (a
        #: reconnect that kept the same open, still-locked camera) rather
        #: than the server minting a fresh one. See `_adopt_pose`.
        self.pose_asserted = False
        self.clockmap = ClockMap()
        self.hello: dict = {}
        self.lock = LockState()
        self.frames = FrameRing(maxlen=FRAME_RING_MAX)
        self.grids: deque[TimedGrid] = deque(maxlen=GRID_RING)
        #: OFF by default: only the commissioning run needs full-resolution
        #: frames, and only for the length of its own run (see FULL_RING).
        self.keep_full_frames = False
        self.full: deque[TimedFrame] = deque(
            maxlen=capture_settings.full_ring_len(*capture_settings.MAP_PROFILE))
        # The wire frame size and the two manual levers: state and every
        # decision on it come from CameraNegotiation, not from here.
        self.init_camera(capture_settings.MAP_PROFILE)
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
        #: THE LEVER SELF-TEST'S VERDICT for this connection
        #: (`spectra/services/lever_selftest.py`), or None until one has been
        #: earned. It lives on the SESSION and nowhere else, which is what
        #: makes it un-inheritable: a reconnect builds a new session
        #: (`open_session`) and starts with nothing, and the verdict's own
        #: fingerprint carries the pose id so a camera reopen inside one
        #: connection cannot reuse it either.
        self.lever_verdict: Any = None

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
                         "frame_size": {"width": self.frame_size[0],
                                        "height": self.frame_size[1]},
                         # The whole ladder, so a client knows which sizes
                         # it may be asked for and can pick its own rung
                         # honestly rather than guessing or upscaling.
                         "frame_sizes": [{"width": w, "height": h}
                                         for w, h in capture_settings.PROFILES],
                         "mime": GREY_MIME,
                         "privacy": PRIVACY_SUMMARY})
        self._loop_task = asyncio.create_task(
            self._loop(), name=f"spectra-room-map-{self.id}")

    async def close(self) -> None:
        if self.closed:
            return
        # RECORD THE DEPARTURE BEFORE THE RINGS GO. What is written here is
        # what makes a later absence answerable — see capture_health.py.
        _note_health(self, "closed")
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

    # ── the four hooks CameraNegotiation asks of a session ────────────────
    async def _send_camera_config(self, payload: dict) -> None:
        await self.send(payload)

    def _camera_clock(self) -> float:
        return self._clock()

    def _camera_frame_times(self) -> list:
        return [g.at_s for g in self.grids]

    def _camera_lock_view(self) -> dict:
        return self.lock.as_dict()

    def _camera_lock_stamp(self) -> float:
        # `_apply_lock` stamps this on every lock report the client sends —
        # its own `lock` message, and the one riding every frame — so it is
        # exactly "when did the camera last answer".
        return self.lock.changed_at

    def _on_frame_size_change(self, size: tuple) -> None:
        """The full-resolution ring is bounded in BYTES, so its LENGTH
        follows the frame size (see FULL_RING). Resizing DROPS what it held:
        frames of two shapes cannot be averaged into one stack, and keeping
        the old ones would only let a run pick up a straggler from before
        the switch."""
        self.full = deque(maxlen=capture_settings.full_ring_len(*size))

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
            # WHAT A CLIENT IS ALLOWED TO SAY ABOUT ITSELF. `client_version`,
            # `pose_name` and `platform` arrive with the unattended client
            # (spectra/capture_client/session.py) so a status surface can
            # name WHICH camera host is missing and WHAT BUILD it was
            # running — see capture_health.py. A key not on this list is
            # dropped, which is why adding one is a deliberate edit.
            self.hello = {k: msg.get(k) for k in
                          ("user_agent", "video", "secure_context", "origin",
                           "client", "client_version", "host", "pose_name",
                           "platform", "camera")
                          if k in msg}
            self._adopt_pose(msg.get("pose_hint"))
            if isinstance(msg.get("lock"), dict):
                self._apply_lock(msg["lock"])
            _note_health(self, "hello")
            await self.send({"type": "hello_ack", "session_id": self.id,
                             "pose_id": self.pose_id,
                             "pose_asserted": self.pose_asserted,
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

    def _adopt_pose(self, hint: Any) -> None:
        """A RECONNECTING CLIENT MAY ASSERT ITS POSE, and this is the whole
        reason the unattended client can survive a dropped WebSocket without
        quietly splitting a map in two.

        A pose is "this camera, where it is standing, at the exposure it
        locked". A footprint is `lit - dark` in that camera's own byte
        scale, so footprints are comparable within one pose and NOT across
        two. A WebSocket drop moves nothing and re-locks nothing: the camera
        stayed open and its scale is unchanged, so a new session id with a
        NEW pose id would be a lie in the more dangerous direction — it
        would label one measurement as two.

        WHAT MAKES THE ASSERTION HONEST IS ON THE CLIENT SIDE, structurally:
        the token is generated INSIDE the camera open (see
        `spectra/capture_client/camera.py`), so it cannot survive a reopen,
        and a reopen is exactly when the exposure is locked again. The
        server records that the pose was asserted rather than minted here
        (`pose_asserted`), so a reader can always tell which it was."""
        if not isinstance(hint, str):
            return
        token = "".join(ch for ch in hint.strip() if ch.isalnum() or ch in "-_")[:32]
        if not token:
            return
        self.pose_id = token
        self.pose_asserted = True

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
            camera_error=str(payload.get("camera_error") or ""),
            source=str(payload.get("source") or ""),
            exposure_time=_number(payload.get("exposure_time")),
            gain=_number(payload.get("gain")),
            white_balance=_number(payload.get("white_balance")),
            focus=_number(payload.get("focus")),
            focus_auto=(None if payload.get("focus_auto") is None
                        else bool(payload.get("focus_auto"))),
            exposure_time_range=_pair(payload.get("exposure_time_range")),
            gain_range=_pair(payload.get("gain_range")),
            white_balance_range=_pair(payload.get("white_balance_range")),
            focus_range=_pair(payload.get("focus_range")),
            manual_refusals=[str(x) for x in
                             (payload.get("manual_refusals") or [])],
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
        # THE CAMERA'S OWN IMAGE SIZE, which is what an upscale is measured
        # against. A client that does not send it leaves (0, 0) and the
        # negotiation simply cannot narrow the rung for it — it is never
        # read as "unlimited".
        rejected = self.note_frame(w, h, int(msg.get("source_width") or 0),
                                   int(msg.get("source_height") or 0))
        if rejected:
            self.last_error = rejected
            self.counts["rejected"] += 1
            return
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
        # The GRID is scale-free — a box mean of the same scene at any rung
        # of the ladder — so it is appended whatever size arrived, and the
        # aim view and the map keep working across a switch. The FULL ring
        # is not: frames of two shapes cannot be averaged into one stack.
        raw_max = int(np.frombuffer(data, dtype=np.uint8).max()) if data else 0
        self.grids.append(TimedGrid(at_s=t_server, grid=grid, raw_max=raw_max))
        if self.keep_full_frames:
            self.full.append(TimedFrame(
                at_s=t_server,
                frame=np.frombuffer(data, dtype=np.uint8).reshape(h, w).copy()))

    def _to_grid(self, data: bytes, w: int, h: int, mime: str) -> Optional[np.ndarray]:
        """grey8 bytes -> the stored 64x36 grid. Rejects anything that is
        not a DECLARED size rather than resampling a surprise: a frame of an
        undeclared shape means the client and the server disagree, and
        quietly stretching it would hide that.

        "Declared" is now the ladder (`capture_settings.PROFILES`) rather
        than one constant, since the commissioning read moved to 1080p.
        Every rung is an exact whole multiple of the 64x36 grid, so this
        stays a box mean with no interpolation to explain, and a grid taken
        from a 1080p frame is directly comparable with one taken from a
        320x180 frame of the same scene."""
        if mime != GREY_MIME:
            self.last_error = (f"frame mime {mime!r} is not {GREY_MIME!r} — "
                               "the mapping page sends raw greyscale bytes")
            return None
        if not capture_settings.is_profile(w, h):
            self.last_error = (
                f"frame is {w}x{h}, which is not one of the sizes this wire "
                f"declares (" +
                ", ".join(f"{a}x{b}" for a, b in capture_settings.PROFILES) +
                ")")
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
        # ONE SHAPE ONLY. A frame-size switch can leave a straggler of the
        # old size inside a window, and `np.stack` on two shapes raises
        # somewhere far from here; the newest arrival is the size the run
        # asked for, so that is the one kept.
        if picked:
            shape = picked[-1].frame.shape
            picked = [f for f in picked if f.frame.shape == shape]
        return picked

    def refusal(self) -> Optional[str]:
        return lock_refusal(self.lock, self.hello)

    def status(self) -> dict:
        latest = self.frames.latest()
        return {"session_id": self.id, "pose_id": self.pose_id,
                "pose_asserted": self.pose_asserted,
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
                "lever_verdict": (self.lever_verdict.as_dict()
                                  if hasattr(self.lever_verdict, "as_dict")
                                  else None),
                **self.camera_status(),
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
    live = current if current and not current.closed else None
    return {"session": live.status() if live else None,
            # THE CAMERA HOST ITSELF, present or absent, on the same surface
            # as the session — so "no session" is never the whole answer to
            # "where is my camera". `capture_health.py` is the record; this
            # only asks it. It gates nothing.
            "camera_host": capture_health.health(live),
            "privacy": PRIVACY_SUMMARY}


def _note_health(session: "MappingSession", event: str) -> None:
    """Write this session into the camera-host record. NEVER raises past
    here: a reporting surface that could take a session down would be worse
    than no reporting surface. `capture_health.note_session` already
    swallows a failed WRITE; this covers the rest."""
    try:
        capture_health.note_session(session, event=event)
    except Exception:                                  # noqa: BLE001
        logger.debug("mapping session: the camera-host record refused a "
                     "%s write", event, exc_info=True)
