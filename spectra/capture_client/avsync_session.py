"""THE A/V-SYNC SESSION — the same instrument, with the camera bolted to a
kiosk instead of held in a hand.

`spectra/services/av_sync_session.py` is the binding statement for what is
measured and for the SIGN of the answer; this module changes none of it. It
speaks the identical WebSocket protocol the browser page speaks
(`spectra/web/src/avsync/capture.ts`), producing the identical two number
streams from a v4l2 camera and an ALSA microphone, so the server correlates
a kiosk measurement with the code it already has and no branch anywhere
asks which client sent it.

    hello   capabilities + WHO IS MEASURING (`source: "kiosk"`, the client
            name/version, the machine, the pose label) — so a record in
            av_sync_measurements.json names the camera that took it rather
            than being indistinguishable from a phone run.
    pong    {seq, t_phone_ms} on `time.monotonic()`, the same clock the
            mapping client already answers pings on. The field keeps its
            wire name: it is the CLIENT's clock, and renaming it would be a
            protocol change for a cosmetic gain.
    audio   {t0_ms, hop_ms, v[]}  ~12 messages/s, 8 hops each
    video   {t_ms[], lum[], grid[][]}  batched like the page's

THE CLOCKS, and the honest limits of each — read this before trusting a
kiosk number, because a wrong-SIGN answer is the one outcome worse than no
answer at all:

  * ONE CLOCK for everything this client stamps: `time.monotonic()`. The
    server pairs it with its own over ping/pong and the residual cancels in
    the difference of the two lags (`av_sync_correlate`'s docstring has the
    algebra), so only the coarse pairing matters and ±RTT/2 is stated on the
    two individual lags.
  * VIDEO is stamped when the frame was READ, not when its photons landed.
    `camera.V4L2Camera.frame()` drains its transport first, so the frame is
    the newest one the pipe holds and no queue accumulates — but the sensor,
    USB and ffmpeg still sit between the light and the stamp. That makes the
    light look LATER than it was, which makes the lights read further
    BEHIND. This client therefore reports `capture_time_available: false`,
    exactly as a browser without `requestVideoFrameCallback.captureTime`
    does, and the server names the term and its direction
    (`SYSTEMATIC_NO_CAPTURE_TIME`, "lights_look_later"). It is a BOUND that
    has not been measured on this hardware, which is why the statement says
    "up to" and why two runs compared against each other are worth more than
    one absolute number.
  * AUDIO hops are stamped from a sample COUNT through the least-delayed
    read (`avsync_reduce.SampleClock`), so read jitter does not reach the
    envelope. The capture path's own latency does, in the other direction:
    the sound looks later, the audio lag reads larger, the lights read
    relatively EARLIER. `audio.latency_s` is sent as null rather than
    guessed, so the server names it (`SYSTEMATIC_MIC_UNKNOWN`,
    "lights_look_earlier") instead of subtracting a number nobody measured.
    The two terms therefore push in OPPOSITE directions and partly cancel —
    which is the structure the browser client has too, and the reason the
    statement's bound is a bound and not an error bar.

ONE CAMERA, ONE OPENER. This mode and the mapping session open the same
`/dev/video0`, and a camera is not shareable — so a machine already holding
a mapping session has to let go of it before this can measure. The refusal
is ffmpeg's own and it is loud (`CameraUnavailable`, exit 2); nothing here
tries to take a device off another process.

WHAT THIS CLIENT WILL NOT DO. It never asserts a measurement the server
refused: a run whose estimate comes back `ok: false` exits non-zero carrying
the server's own reason and statement. It never sends frames for the vision
frame-tap seam (that is a JPEG path this client has no encoder for, and a
`config` message asking for it is answered by not sending frames rather than
by sending something else). And it never starts a pattern — his lights, in
his room — when the server has already said it has no audio reference to
measure against: that would flash the room for a number that cannot exist.
"""
from __future__ import annotations

import asyncio
import json
import logging
import platform
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import websockets

from spectra.capture_client.avsync_audio import ArecordSource, AudioUnavailable
from spectra.capture_client.avsync_reduce import GRID, FrameReducer
from spectra.capture_client.camera import BaseCamera, CameraUnavailable
from spectra.capture_client.session import CLIENT_NAME, CLIENT_VERSION

logger = logging.getLogger(__name__)

#: What this client calls itself in `hello`. The server keeps it on the
#: measurement record, which is what lets "the kiosk measured this" be a
#: read rather than an inference from a user-agent string.
SOURCE = "kiosk"

#: Video batching, mirrored from capture.ts so the server's rings fill at
#: the cadence they were tuned for.
VIDEO_BATCH = 4
VIDEO_FLUSH_S = 0.120

#: How long to wait for the server's clock map before giving up on a
#: measurement. Pings are every 2 s and the map wants a handful.
CLOCK_READY_TIMEOUT_S = 30.0
#: Streams have to be flowing before a pattern starts, or its first edges
#: land on empty rings.
WARMUP_S = 3.0
#: How long past the pattern's own duration to wait for `measure_done`
#: (the server takes a final settle read after the last edge).
MEASURE_GRACE_S = 30.0


def video_message(samples) -> dict:
    """The `video` message the server ingests, built in ONE place so the
    live loop and every proof of it cannot construct it differently.
    `samples` are `(t_ms, mean, grid)` on the client's own clock — the
    columnar shape `av_sync_session._ingest_video` reads."""
    return {"type": "video",
            "t_ms": [t for t, _m, _g in samples],
            "lum": [m for _t, m, _g in samples],
            "grid": [g for _t, _m, g in samples]}


@dataclass
class AvSyncState:
    connected: bool = False
    session_id: str = ""
    audio_batches: int = 0
    video_samples: int = 0
    pongs: int = 0
    camera_error: str = ""
    audio_error: str = ""
    last_error: str = ""
    last_estimate: dict = field(default_factory=dict)
    audio: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


class MeasurementFailed(Exception):
    """The run happened and produced no number — the server's own reason is
    carried, never replaced by one of ours."""

    def __init__(self, message: str, estimate: Optional[dict] = None) -> None:
        super().__init__(message)
        self.estimate = estimate or {}


class AvSyncKioskClient:
    """One camera, one microphone, one session — held until the requested
    measurements are done or something refuses."""

    def __init__(self, ws_url: str, camera: BaseCamera, audio: ArecordSource,
                 *, host: str = "", pose_name: str = "",
                 clock: Callable[[], float] = time.monotonic,
                 connect: Optional[Callable[[str], Any]] = None) -> None:
        self.ws_url = ws_url
        self.camera = camera
        self.audio = audio
        self.host = host or platform.node()
        self.pose_name = pose_name
        self._clock = clock
        self._connect = connect or (lambda url: websockets.connect(url))
        self.state = AvSyncState()
        self._ws = None
        self._reducer: Optional[FrameReducer] = None
        self._pending_video: list = []
        self._last_flush = 0.0
        self._server: asyncio.Queue = asyncio.Queue()
        self._fatal: Optional[BaseException] = None
        #: THREE COROUTINES SHARE ONE SOCKET — pongs, envelope batches and
        #: video samples all send from their own loop. Two of them mid-write
        #: on one WebSocket at the same time is undefined behaviour, and this
        #: codebase has already paid for that once (the device-preview
        #: relay's overlapping sends, `spectra/services/device_preview.py`).
        #: A lock costs nothing at ~40 small messages a second.
        self._send_lock: Optional[asyncio.Lock] = None

    # ── hello ─────────────────────────────────────────────────────────────
    def hello(self) -> dict:
        fw, fh = self.camera.frame_size
        fps = float(getattr(self.camera, "fps", 0.0) or 0.0)
        return {
            "type": "hello",
            # WHO IS MEASURING. `source` is the field a reader looks at;
            # the rest names the machine so a record months later still
            # says which camera stood where.
            "source": SOURCE,
            "client": CLIENT_NAME,
            "client_version": CLIENT_VERSION,
            "host": self.host,
            "pose_name": self.pose_name,
            "user_agent": f"{CLIENT_NAME}/{CLIENT_VERSION} ({SOURCE}; "
                          f"{platform.system()} {platform.machine()})",
            "origin": self.ws_url,
            # `secure_context` IS DELIBERATELY ABSENT. It is a browser fact
            # — whether the page's origin was allowed to open a camera and a
            # microphone at all — and there is no browser here: these two
            # devices are opened by the operating system's own permissions.
            # Sending True would answer a question nobody asked this
            # process, and the record would then carry a claim about a gate
            # that never applied. The server keeps only the keys a client
            # sends, so its absence is the honest answer, and `source` says
            # why it is missing.
            "audio": {
                "sample_rate": self.audio.rate_hz,
                "hop_ms": round(self.audio.hop_ms, 4),
                # NOT MEASURED, SO NOT SENT. The server subtracts this when
                # it is given; a guess here would silently move the answer.
                "latency_s": None,
                "worklet": False,
                "device": self.audio.device,
                "capture": self.audio.describe(),
            },
            "video": {
                "fps": fps or None,
                # See the module docstring: the stamp is the READ, so the
                # server must name the pipeline term rather than assume a
                # capture time it was never given.
                "capture_time_available": False,
                "width": fw, "height": fh,
                "rvfc": False,
                "facing": None,
                "grid": GRID,
                "camera": self.camera.describe(),
                "lock": self.camera.lock.as_wire(),
            },
        }

    # ── lifecycle ─────────────────────────────────────────────────────────
    async def start_devices(self) -> None:
        """Open BOTH, and refuse by name if either will not. Unlike the
        mapping client — which connects without a camera on purpose, so its
        refusal reaches a page — an A/V-sync run with one of its two signals
        missing can produce nothing at all, so it stops here."""
        try:
            await self.camera.open()
        except CameraUnavailable:
            raise
        except Exception as exc:                        # noqa: BLE001
            raise CameraUnavailable(f"{type(exc).__name__}: {exc}") from None
        self._reducer = FrameReducer(*self.camera.frame_size)
        await self.audio.open()
        self.state.audio = self.audio.describe()

    async def close_devices(self) -> None:
        try:
            await self.audio.close()
        finally:
            await self.camera.close()

    async def _send(self, ws, obj: dict) -> None:
        """Every outbound message goes through here — see `_send_lock`."""
        raw = json.dumps(obj)
        lock = self._send_lock
        if lock is None:                    # never under `_connected`, and
            lock = self._send_lock = asyncio.Lock()   # not an assert: -O
        async with lock:
            await ws.send(raw)

    async def _connected(self, body) -> Any:
        """One session: hello, the three loops, `body`, and a clean stop.

        Deliberately NOT reconnecting. The server destroys its session on
        disconnect — which reverts a pattern and drops both rings — so a
        measurement cannot span a drop, and a client that quietly rebuilt
        the session would produce a number from a fresh clock map with a
        gap in the middle of it. A drop ends the run and says so."""
        self._send_lock = asyncio.Lock()
        async with await self._connect(self.ws_url) as ws:
            self._ws = ws
            self.state.connected = True
            await self._send(ws, self.hello())
            tasks = [asyncio.create_task(self._pump(ws), name="avsync-pump"),
                     asyncio.create_task(self._audio_loop(ws), name="avsync-audio"),
                     asyncio.create_task(self._video_loop(ws), name="avsync-video")]
            try:
                return await body(ws)
            finally:
                for t in tasks:
                    t.cancel()
                for t in tasks:
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):   # noqa: BLE001
                        pass
                self.state.connected = False
                self._ws = None

    async def run_measurements(self, *, mode: str = "pattern",
                               duration_s: float = 12.0, runs: int = 1,
                               gap_s: float = 4.0,
                               warmup_s: float = WARMUP_S) -> list:
        """Connect, stream, and take `runs` measurements. Returns one
        record per run; raises `MeasurementFailed` on the first run the
        instrument refused, with the server's own words."""
        async def body(ws):
            await self._await_ready(warmup_s)
            out = []
            for i in range(max(1, int(runs))):
                if i:
                    await self._sleep_watching(gap_s)
                out.append(await self._one_measurement(ws, mode, duration_s))
            return out
        return await self._connected(body)

    async def hold(self, *, seconds: Optional[float] = None) -> AvSyncState:
        """Stream both signals and take no measurement — for watching them
        arrive (GET /api/av-sync/status) before committing his room to a
        flash. It does NOT apply `_await_ready`'s gates: refusing to hold
        because SPECTRA has no audio reference yet would refuse the one
        thing worth doing while waiting for it."""
        async def body(_ws):
            end = None if seconds is None else self._clock() + float(seconds)
            while end is None or self._clock() < end:
                await self._next(timeout=1.0 if end is None
                                 else min(1.0, end - self._clock()))
            return self.state
        return await self._connected(body)

    # ── the three loops ───────────────────────────────────────────────────
    async def _pump(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                continue
            kind = msg.get("type")
            if kind == "ping":
                await self._send(ws, {
                    "type": "pong", "seq": msg.get("seq"),
                    "t_phone_ms": self._clock() * 1000.0})
                self.state.pongs += 1
                continue
            if kind == "welcome" or kind == "hello_ack":
                self.state.session_id = str(msg.get("session_id")
                                            or self.state.session_id)
            elif kind == "estimate":
                self.state.last_estimate = msg
            elif kind == "error":
                self.state.last_error = str(msg.get("message") or "")
                logger.warning("av-sync server: %s", self.state.last_error)
            elif kind == "config":
                # The vision frame tap. This client has no JPEG encoder and
                # sends nothing; saying so in the log beats a server waiting
                # for frames that will never come.
                if (msg.get("frame_tap") or {}).get("enabled"):
                    logger.info("av-sync: the frame tap was switched on, but "
                                "the kiosk client sends no still frames")
            await self._server.put(msg)

    async def _audio_loop(self, ws) -> None:
        while True:
            try:
                batch = await self.audio.batch()
            except AudioUnavailable as exc:
                # A DEAD MICROPHONE ENDS THE RUN. Continuing would put an
                # empty envelope on the wire and let the correlator refuse
                # for a reason that points at the room instead of the mic.
                self.state.audio_error = str(exc)
                self._fatal = exc
                await self._server.put({"type": "_client_fatal",
                                        "message": str(exc)})
                return
            await self._send(ws, batch.as_message())
            self.state.audio_batches += 1

    async def _video_loop(self, ws) -> None:
        while True:
            data = await self.camera.frame()
            t_ms = self._clock() * 1000.0
            if data is None:
                # The capture pipe died. Unlike a map — where a reopen mints
                # a new pose and the run carries on — a reopen here re-locks
                # the exposure in the middle of a correlation, so the run
                # ends and says so.
                exc = CameraUnavailable(
                    f"the camera stopped producing frames mid-measurement "
                    f"({getattr(self.camera, 'device', 'camera')})")
                self.state.camera_error = str(exc)
                self._fatal = exc
                await self._server.put({"type": "_client_fatal",
                                        "message": str(exc)})
                return
            if self._reducer is None or (
                    self._reducer.width, self._reducer.height
            ) != tuple(self.camera.frame_size):
                self._reducer = FrameReducer(*self.camera.frame_size)
            try:
                mean, grid = self._reducer.reduce(data)
            except ValueError as exc:
                logger.debug("av-sync: skipping a frame: %s", exc)
                continue
            self._pending_video.append((t_ms, mean, grid))
            now = self._clock()
            if (len(self._pending_video) >= VIDEO_BATCH
                    or now - self._last_flush > VIDEO_FLUSH_S):
                self._last_flush = now
                out, self._pending_video = self._pending_video, []
                await self._send(ws, video_message(out))
                self.state.video_samples += len(out)

    # ── gates ─────────────────────────────────────────────────────────────
    async def _await_ready(self, warmup_s: float) -> None:
        """Wait for the server's clock map, and refuse BEFORE flashing his
        room if the server has already said it has no audio reference."""
        deadline = self._clock() + CLOCK_READY_TIMEOUT_S
        clock_ready = False
        while self._clock() < deadline:
            msg = await self._next(timeout=deadline - self._clock())
            if msg is None:
                break
            if msg.get("type") != "estimate":
                continue
            reason = msg.get("reason") or ""
            if reason == "no_audio_ref":
                raise MeasurementFailed(
                    msg.get("statement")
                    or "SPECTRA has no audio reference to measure against",
                    msg)
            if (msg.get("clock") or {}).get("ready"):
                clock_ready = True
                break
        if not clock_ready:
            raise MeasurementFailed(
                f"the server's clock map never became ready within "
                f"{CLOCK_READY_TIMEOUT_S:.0f}s ({self.state.pongs} pongs "
                f"answered) — the measurement needs it to put both clocks "
                f"on one axis", self.state.last_estimate)
        await self._sleep_watching(warmup_s)
        if not (self.state.audio_batches and self.state.video_samples):
            raise MeasurementFailed(
                f"after {warmup_s:.0f}s of warm-up the server had received "
                f"{self.state.audio_batches} audio batches and "
                f"{self.state.video_samples} video samples from this "
                f"machine — nothing to correlate", self.state.last_estimate)

    async def _one_measurement(self, ws, mode: str, duration_s: float) -> dict:
        await self._send(ws, {"type": "measure", "mode": mode,
                              "duration_s": duration_s})
        deadline = self._clock() + duration_s + MEASURE_GRACE_S
        started = False
        while self._clock() < deadline:
            msg = await self._next(timeout=deadline - self._clock())
            if msg is None:
                break
            kind = msg.get("type")
            if kind == "measure_started":
                started = True
            elif kind == "error":
                raise MeasurementFailed(
                    f"the server refused the measurement: "
                    f"{msg.get('message')}", self.state.last_estimate)
            elif kind == "measure_done":
                est = msg.get("estimate") or {}
                if not est.get("ok"):
                    raise MeasurementFailed(
                        est.get("statement")
                        or f"no number: {est.get('reason') or 'unknown'}",
                        est)
                return {"estimate": est, "measurement": msg.get("measurement"),
                        "aborted": bool(msg.get("aborted")),
                        "audio": self.audio.stats(),
                        "client": self.state.as_dict()}
        raise MeasurementFailed(
            f"the measurement never finished: no measure_done within "
            f"{duration_s + MEASURE_GRACE_S:.0f}s"
            + ("" if started else " (and the server never said it started)"),
            self.state.last_estimate)

    async def _next(self, *, timeout: float) -> Optional[dict]:
        """The next server message, or None on timeout. A client-side fatal
        (dead mic, dead camera) is raised here rather than queued past a
        caller that is waiting for the room."""
        if timeout <= 0:
            return None
        try:
            msg = await asyncio.wait_for(self._server.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        if msg.get("type") == "_client_fatal":
            raise self._fatal or MeasurementFailed(str(msg.get("message")))
        return msg

    async def _sleep_watching(self, seconds: float) -> None:
        """Sleep, but surface a client-side fatal the moment it happens
        rather than at the end of the wait."""
        end = self._clock() + max(0.0, seconds)
        while self._clock() < end:
            await self._next(timeout=min(0.25, end - self._clock()))
