"""AV-sync SESSION — the phone audio/visual-offset instrument's server
half: one live phone connection, its two probe signals (mic envelope,
camera luminance), the two server references (audio hub tap, light
reference), a clock map between the two devices, the estimator that
turns them into A NUMBER WITH A STATED CONFIDENCE, and the vision-stage
frame seam. spectra/api/av_sync.py is the wire; av_sync_correlate.py is
the arithmetic; av_sync_audio_ref.py / av_sync_pattern.py are the two
references.

WHY (the whole point, from the brief): this project argued an audio delay
in the wrong direction against the owner's ears, read a wandering number
from the wrong engine as a measurement, and shipped a value settled by
his ears (docs/SPECTRA_TIMING_CONVENTIONS.md, failure cases 1-3). This
module exists so the answer comes from CAPTURE: his phone stands where he
stands, hears what he hears, sees what he sees.

WHAT IS MEASURED — one sign convention, stated once
---------------------------------------------------
  light_lag_ms = (phone sees a light edge)  − (server wrote it)
  audio_lag_ms = (phone hears a sound onset) − (server's audio hub heard it)
  av_offset_ms = light_lag_ms − audio_lag_ms
    > 0  the light arrived LATER than the sound it was meant to land with
         ("lights BEHIND / lag")
    < 0  the light arrived EARLIER ("lights AHEAD / lead")
The phone↔server clock offset is common to both lags and cancels in the
difference (av_sync_correlate.py's docstring has the algebra). It is a
measurement of his room from where the phone stood — not a setting, not
applied anywhere by this build (his authored offsets are his; the result
is presented for him to accept, never written into settings).

PRIVACY — where the audio and video GO, what is WRITTEN, how long it's KEPT
----------------------------------------------------------------------------
  * Raw audio and raw video NEVER leave the phone. The page reduces them
    ON THE PHONE to two low-rate number streams — a microphone log-energy
    envelope (~90 numbers/s) and a per-frame camera brightness (one mean +
    a 4×4 grid of means per frame, ~30-60/s) — and sends only those,
    over the same-origin WebSocket the rest of SPECTRA already uses
    (phone → the :8000 spot-effects reverse proxy → this :8010 process,
    all on whatever network he already reaches SPECTRA over; if that is
    his tailnet, the numbers cross the tailnet — the media never does).
  * The ONE exception is the frame tap (below), OFF by default, which
    sends small JPEG still frames to this process's MEMORY only.
  * Written to disk: exactly one file, config.AV_SYNC_MEASUREMENTS_FILE —
    finished measurement RECORDS (the numbers, the confidence statement,
    phone capability flags like "captureTime available", the user-agent
    string). Never audio, never video, never frames, never the raw
    number streams. Bounded to MEASUREMENTS_KEEP entries, oldest evicted.
    (config.AV_SYNC_PATTERN_FILE is the pattern driver's light snapshot —
    effect configs, no media.)
  * In memory: the probe rings hold RING_SECONDS of the number streams
    and are dropped when the connection closes; the frame ring holds at
    most FRAME_RING_MAX still frames and is cleared on close.
  * Nothing here ever sends a byte off the host to anywhere but the
    connected phone.

THE VISION-STAGE SEAM (prepared, NOT built — owner's line)
-----------------------------------------------------------
`FrameRing` is the hook a later ArUco/LED-mapping stage plugs into: when
the tap is enabled (POST /api/av-sync/frame-tap → pushed to the phone as a
`config` message), the phone sends still frames (JPEG bytes + its own
capture timestamp) at the requested rate; each lands here as a `Frame`
with `captured_at_phone_ms`, `captured_at_server_s` (via the session's
clock map, ±RTT/2 — the timestamp a later stage can trust, to that
stated precision), `received_at_server_s`, width/height. `subscribe(cb)`
delivers frames in-process; GET /api/av-sync/frame/latest serves the
newest for a human to check aim. NOTHING here decodes, inspects, or
recognises anything in a frame — that is his to build.

LIVE FEEDS (the stated next step) — the shape is already a stream: the
probe rings are sliding windows, the estimator re-runs every
ESTIMATE_INTERVAL_S over the most recent window, and the "show" light
reference (ShowReference: the engine's own jump/short-glide writes) needs
no pattern at all, so a camera left running measures continuously.
Tight numbers still come from the pattern (PatternReference); a fixed LAN
camera replacing the phone is a different WebSocket client speaking the
same messages — no rewrite.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import numpy as np

from spectra import config
from spectra.services import av_sync_correlate as corr
from spectra.services.av_sync_audio_ref import AudioReference
from spectra.services.av_sync_correlate import Series
from spectra.services.av_sync_pattern import PatternDriver, PatternRun

logger = logging.getLogger(__name__)

RING_SECONDS = 60.0
ESTIMATE_INTERVAL_S = 1.0
PING_INTERVAL_S = 2.0
CLOCK_SAMPLES = 12
SHOW_WINDOW_S = 15.0
AUDIO_MAX_LAG_S = 3.0          # snapcast-class audio paths can sit ~1 s behind the monitor
LIGHT_MAX_LAG_S = 1.5
FRAME_RING_MAX = 8
MEASUREMENTS_KEEP = 100
SHOW_EVENT_MAX_GLIDE_MS = 300  # an engine write counts as a visible "edge" candidate below this
FINAL_SETTLE_S = 1.5           # after the last pattern edge: let the phone's last batches arrive before the final read

# Systematic terms the arithmetic cannot see — bounds stated, not invented
# as a correction. Each entry: (name, bound_ms, direction, depends_on).
# direction: "lights_look_later" / "lights_look_earlier" / "either".
SYSTEMATICS_ALWAYS = [
    ("server audio-hub input latency (PipeWire/PortAudio callback stamps at "
     "callback entry, no ADC-time correction — the reference sound is stamped late, "
     "so the phone's audio lag reads SMALLER and the lights read relatively LATER)", 40,
     "lights_look_later", "this host's audio stack; constant between runs"),
    ("camera exposure integration (the edge is seen ~half an exposure late; bound = "
     "half a frame interval at the reported frame rate)", 17,
     "lights_look_later", "frame rate / exposure — shorter exposure, smaller"),
    ("light rise time (the edge is timed at its ~50% crossing — what the eye "
     "sees, but bulbs differ: Hue fades over ~100 ms, WLED snaps; bound = half a slow "
     "bulb's fade)", 50, "lights_look_later", "which fixtures are in frame"),
]
SYSTEMATIC_NO_CAPTURE_TIME = ("phone camera pipeline latency (no captureTime "
                              "from the browser — frames are timed when delivered, "
                              "not when captured)", 80, "lights_look_later",
                              "phone model + browser; constant for this phone")
SYSTEMATIC_CAPTURE_TIME = ("phone camera pipeline residual (captureTime used)", 15,
                           "lights_look_later", "phone model + browser")
SYSTEMATIC_MIC_UNKNOWN = ("phone microphone pipeline latency (browser did not "
                          "report input latency)", 40, "lights_look_earlier",
                          "phone model + browser; constant for this phone")
SYSTEMATIC_MIC_REPORTED = ("phone microphone pipeline residual (reported latency "
                           "subtracted)", 10, "lights_look_earlier",
                           "phone model + browser")


# ── clock map ──────────────────────────────────────────────────────────────

@dataclass
class ClockMap:
    """phone performance-clock ms ↔ server monotonic s, from server-driven
    ping/pong. `offset_s` = phone_s − server_s at the chosen (min-RTT)
    sample; ±rtt/2 is the stated precision of the INDIVIDUAL lags (it
    cancels in av_offset)."""
    samples: deque = field(default_factory=lambda: deque(maxlen=CLOCK_SAMPLES))
    offset_s: Optional[float] = None
    rtt_s: Optional[float] = None

    def add(self, t_server_sent: float, t_phone_ms: float, t_server_recv: float) -> None:
        rtt = max(0.0, t_server_recv - t_server_sent)
        mid = t_server_sent + 0.5 * rtt
        self.samples.append((rtt, t_phone_ms / 1000.0 - mid))
        best = min(self.samples, key=lambda s: s[0])
        self.rtt_s, self.offset_s = best

    @property
    def ready(self) -> bool:
        return self.offset_s is not None

    def to_server(self, t_phone_ms: float) -> float:
        if self.offset_s is None:
            raise RuntimeError("clock map not ready")
        return t_phone_ms / 1000.0 - self.offset_s

    def as_dict(self) -> dict:
        return {"ready": self.ready,
                "rtt_ms": None if self.rtt_s is None else round(self.rtt_s * 1000, 1),
                "phone_minus_server_ms": (None if self.offset_s is None
                                          else round(self.offset_s * 1000, 1)),
                "samples": len(self.samples)}


# ── light references ───────────────────────────────────────────────────────

class PatternReference:
    """The flash pattern's own edge log (server clock) as a ±1 square wave."""
    kind = "pattern"
    condition = "edges"              # ±1 pattern edges vs luminance edges (sharp peak)
    probe_transform = "raw"          # the correlator high-passes + differentiates it

    def __init__(self, run: PatternRun, clock: Callable[[], float]) -> None:
        self.run = run
        self._clock = clock

    def window(self) -> tuple[float, float]:
        t0 = self.run.started_at - 0.5
        t1 = self.run.finished_at if self.run.finished_at is not None else self._clock()
        return t0, t1

    def series(self, t0: float, t1: float) -> Series:
        edges = [(t, s) for (t, s) in self.run.edges if t0 - 1.0 <= t <= t1]
        until = min(t1, (self.run.finished_at or self._clock()))
        return corr.edges_to_series(edges, until_s=until)

    def describe(self) -> dict:
        return {"kind": self.kind, **self.run.as_dict()}


class ShowReference:
    """The passive reference: the engine's own recent jump / short-glide
    writes (fx_executor.ExecutorWrite `at` stamps, server monotonic) as an
    impulse train, correlated against the luminance EDGE strength. Free —
    no pattern, the show keeps playing — but only as good as the show's
    own edges happen to be; the confidence gate says when that isn't good
    enough, and it often won't be (a 20 s drift glide has no edge)."""
    kind = "show"
    condition = "none"
    probe_transform = "edge"

    def __init__(self, writes_getter: Callable[[], list[dict]], clock: Callable[[], float]) -> None:
        self._writes = writes_getter
        self._clock = clock

    def window(self) -> tuple[float, float]:
        now = self._clock()
        return now - SHOW_WINDOW_S, now

    def event_times(self, t0: float, t1: float) -> list[float]:
        out = []
        for w in self._writes() or []:
            try:
                at = float(w.get("at"))
                dur = float(w.get("duration_ms") or 0)
            except (TypeError, ValueError):
                continue
            if t0 <= at <= t1 and (w.get("kind") == "jump" or dur <= SHOW_EVENT_MAX_GLIDE_MS):
                out.append(at)
        return out

    def series(self, t0: float, t1: float) -> Series:
        return corr.events_to_series(self.event_times(t0, t1), t0=t0, t1=t1)

    def describe(self) -> dict:
        t0, t1 = self.window()
        return {"kind": self.kind, "window_s": SHOW_WINDOW_S,
                "event_count": len(self.event_times(t0, t1))}


def _default_show_writes() -> list[dict]:
    from spectra.services import engine
    return list(engine.executor.writes)


# ── the frame seam ─────────────────────────────────────────────────────────

@dataclass
class Frame:
    captured_at_phone_ms: float
    captured_at_server_s: Optional[float]
    received_at_server_s: float
    width: int
    height: int
    mime: str
    data: bytes

    def meta(self) -> dict:
        return {"captured_at_phone_ms": self.captured_at_phone_ms,
                "captured_at_server_s": self.captured_at_server_s,
                "received_at_server_s": self.received_at_server_s,
                "width": self.width, "height": self.height, "mime": self.mime,
                "bytes": len(self.data)}


class FrameRing:
    """Bounded in-memory still-frame ring + in-process subscribers — THE
    vision-stage hook (module docstring). Never persisted, cleared on
    session close. Recognises nothing."""

    def __init__(self, maxlen: int = FRAME_RING_MAX) -> None:
        self._frames: deque[Frame] = deque(maxlen=maxlen)
        self._subs: list[Callable[[Frame], None]] = []
        self.enabled = False
        self.fps = 1.0
        self.width = 320
        self.received = 0

    def config(self) -> dict:
        return {"enabled": self.enabled, "fps": self.fps, "width": self.width}

    def configure(self, *, enabled: bool, fps: float = 1.0, width: int = 320) -> dict:
        self.enabled = bool(enabled)
        self.fps = float(min(max(0.2, fps), 10.0))
        self.width = int(min(max(64, width), 1280))
        if not self.enabled:
            self._frames.clear()
        return self.config()

    def push(self, frame: Frame) -> None:
        self._frames.append(frame)
        self.received += 1
        for cb in list(self._subs):
            try:
                cb(frame)
            except Exception:
                logger.exception("av_sync frame ring: subscriber failed")

    def latest(self) -> Optional[Frame]:
        return self._frames[-1] if self._frames else None

    def subscribe(self, cb: Callable[[Frame], None]) -> Callable[[], None]:
        self._subs.append(cb)

        def _unsub() -> None:
            try:
                self._subs.remove(cb)
            except ValueError:
                pass
        return _unsub

    def clear(self) -> None:
        self._frames.clear()

    def status(self) -> dict:
        latest = self.latest()
        return {**self.config(), "held": len(self._frames), "received": self.received,
                "latest": latest.meta() if latest else None,
                "subscribers": len(self._subs)}


# ── the estimate + its statement ───────────────────────────────────────────

@dataclass
class Estimate:
    ok: bool
    av_offset_ms: Optional[float]
    sigma_ms: Optional[float]
    light: corr.LagEstimate
    audio: corr.LagEstimate
    light_region: str
    systematics: list[dict]
    systematic_bound_ms: float
    systematic_later_ms: float
    systematic_earlier_ms: float
    reason: str
    statement: str
    light_ref: dict
    clock: dict
    window_s: float

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "av_offset_ms": None if self.av_offset_ms is None else round(self.av_offset_ms, 1),
            "sigma_ms": None if self.sigma_ms is None else round(self.sigma_ms, 1),
            "light_lag": self.light.as_dict(),
            "audio_lag": self.audio.as_dict(),
            "light_region": self.light_region,
            "systematics": self.systematics,
            "systematic_bound_ms": round(self.systematic_bound_ms, 1),
            "systematic_later_ms": round(self.systematic_later_ms, 1),
            "systematic_earlier_ms": round(self.systematic_earlier_ms, 1),
            "reason": self.reason,
            "statement": self.statement,
            "light_ref": self.light_ref,
            "clock": self.clock,
            "window_s": round(self.window_s, 1),
        }


def _statement(av_offset_ms: Optional[float], sigma_ms: Optional[float],
               bound_ms: float, light: corr.LagEstimate, audio: corr.LagEstimate,
               reason: str, *, later_ms: float = 0.0, earlier_ms: float = 0.0) -> str:
    if av_offset_ms is None:
        why = {
            "audio": f"no usable sound match ({audio.reason or 'none'}: peak ratio "
                     f"{audio.peak_ratio:.1f}, need ≥ {corr.MIN_PEAK_RATIO:.0f})",
            "light": f"no usable light match ({light.reason or 'none'}: peak ratio "
                     f"{light.peak_ratio:.1f}, need ≥ {corr.MIN_PEAK_RATIO:.0f})",
            "clock": "phone/server clock not yet paired",
            "no_audio_ref": "no server audio reference (SPECTRA is not driving the room)",
            "no_data": "waiting for phone audio + video",
        }.get(reason, reason)
        return f"No measurement yet — {why}."
    direction = "BEHIND the sound (they change after you hear it)" if av_offset_ms > 0 \
        else "AHEAD of the sound (they change before you hear it)"
    mag = abs(av_offset_ms)
    stat = f"±{sigma_ms:.0f} ms statistical" if sigma_ms is not None else "statistical spread unknown"
    return (f"Lights are {mag:.0f} ms {direction}; {stat} from this capture. Systematic "
            f"terms this capture cannot see (phone camera/mic pipelines, exposure, bulb "
            f"rise, the server's audio input latency) could make the TRUE value up to "
            f"{later_ms:.0f} ms further AHEAD or {earlier_ms:.0f} ms further BEHIND than "
            f"reported — they are constant for this phone/room, so a CHANGE between two "
            f"runs is far tighter than either absolute number. A light that appears in "
            f"the camera frame is what was measured — aim at what you care about.")


# ── session ────────────────────────────────────────────────────────────────

class Session:
    """One phone connection. `send` is the coroutine that writes a JSON
    message back to that phone (the API layer hands in ws.send_json)."""

    def __init__(self, send: Callable[[dict], Awaitable[None]], *,
                 audio_ref: AudioReference | None = None,
                 pattern: PatternDriver | None = None,
                 show_writes: Callable[[], list[dict]] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 measurements_file: Optional[os.PathLike] = None) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.send = send
        self._clock = clock
        self.audio_ref = audio_ref or AudioReference(clock=clock)
        self.pattern = pattern
        self._show_writes = show_writes or _default_show_writes
        self._measurements_file = measurements_file
        self.clockmap = ClockMap()
        self.hello: dict = {}
        self.mode: Optional[str] = None           # "pattern" | "show"
        self.light_ref: PatternReference | ShowReference | None = None
        self.frames = FrameRing()
        self.audio_probe: deque[tuple[float, float]] = deque()       # (t_server, dB)
        self.video_probe: deque[tuple[float, float, list[float]]] = deque()  # (t_server, lum, grid)
        self.last_estimate: Optional[Estimate] = None
        self.measurements: list[dict] = []
        self.opened_at = clock()
        self.closed = False
        self._pings: dict[int, float] = {}
        self._ping_seq = 0
        self._loop_task: Optional[asyncio.Task] = None
        self._final_task: Optional[asyncio.Task] = None
        self._audio_ref_started = False
        self.counts = {"audio": 0, "video": 0, "frames": 0, "pongs": 0}

    # ── lifecycle ─────────────────────────────────────────────────────────
    async def open(self) -> None:
        self._audio_ref_started = self.audio_ref.start()
        await self.send({"type": "welcome", "session_id": self.id,
                         "audio_ref": self.audio_ref.stats(),
                         "frame_tap": self.frames.config(),
                         "privacy": PRIVACY_SUMMARY})
        self._loop_task = asyncio.create_task(self._loop(), name=f"spectra-av-sync-{self.id}")

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for attr in ("_loop_task", "_final_task"):
            task = getattr(self, attr, None)
            setattr(self, attr, None)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self.mode == "show" and self.last_estimate and self.last_estimate.ok:
            self._record(self.last_estimate, final=False)
        if self.pattern is not None and self.pattern.active:
            await self.pattern.stop()
        await self.audio_ref.stop()
        self.frames.clear()
        self.audio_probe.clear()
        self.video_probe.clear()

    async def _loop(self) -> None:
        last_ping = 0.0
        last_est = 0.0
        while True:
            now = self._clock()
            try:
                if now - last_ping >= PING_INTERVAL_S or not self.clockmap.ready:
                    last_ping = now
                    await self._ping()
                if now - last_est >= ESTIMATE_INTERVAL_S:
                    last_est = now
                    est = self.estimate()
                    self.last_estimate = est
                    await self.send({"type": "estimate", **est.as_dict()})
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("av_sync session %s: loop iteration failed", self.id)
            await asyncio.sleep(0.1)

    async def _ping(self) -> None:
        self._ping_seq += 1
        seq = self._ping_seq
        self._pings[seq] = self._clock()
        # prune stale pings (lost pongs)
        for k in [k for k, t in self._pings.items() if self._clock() - t > 10.0]:
            self._pings.pop(k, None)
        await self.send({"type": "ping", "seq": seq})

    # ── inbound messages ──────────────────────────────────────────────────
    async def handle(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "hello":
            self.hello = {k: msg.get(k) for k in ("user_agent", "audio", "video", "secure_context",
                                                  "origin") if k in msg}
            await self.send({"type": "hello_ack", "session_id": self.id})
        elif kind == "pong":
            seq = msg.get("seq")
            t_phone = msg.get("t_phone_ms")
            sent = self._pings.pop(seq, None)
            if sent is not None and isinstance(t_phone, (int, float)):
                self.clockmap.add(sent, float(t_phone), self._clock())
                self.counts["pongs"] += 1
        elif kind == "audio":
            self._ingest_audio(msg)
        elif kind == "video":
            self._ingest_video(msg)
        elif kind == "frame":
            self._ingest_frame(msg)
        elif kind == "measure":
            await self.start_measure(mode=str(msg.get("mode") or "pattern"),
                                    duration_s=float(msg.get("duration_s") or 0) or None)
        elif kind == "stop":
            await self.stop_measure()
        else:
            await self.send({"type": "error", "message": f"unknown message type {kind!r}"})

    def _ingest_audio(self, msg: dict) -> None:
        if not self.clockmap.ready:
            return
        try:
            t0 = float(msg["t0_ms"])
            hop = float(msg["hop_ms"])
            vals = [float(x) for x in msg["v"]]
        except (KeyError, TypeError, ValueError):
            return
        latency_s = self._phone_audio_latency_s()
        for i, v in enumerate(vals):
            t_server = self.clockmap.to_server(t0 + i * hop) - latency_s
            self.audio_probe.append((t_server, v))
        self.counts["audio"] += len(vals)
        self._trim(self.audio_probe)

    def _ingest_video(self, msg: dict) -> None:
        if not self.clockmap.ready:
            return
        try:
            ts = [float(x) for x in msg["t_ms"]]
            lum = [float(x) for x in msg["lum"]]
            grids = msg.get("grid") or [None] * len(ts)
        except (KeyError, TypeError, ValueError):
            return
        for t, l, g in zip(ts, lum, grids):
            grid = [float(x) for x in g] if isinstance(g, list) else []
            self.video_probe.append((self.clockmap.to_server(t), l, grid))
        self.counts["video"] += len(ts)
        self._trim(self.video_probe)

    def _ingest_frame(self, msg: dict) -> None:
        if not self.frames.enabled:
            return
        try:
            data = base64.b64decode(msg["data"])
            t_phone = float(msg["captured_at_ms"])
            w = int(msg.get("width") or 0)
            h = int(msg.get("height") or 0)
        except (KeyError, TypeError, ValueError):
            return
        t_server = self.clockmap.to_server(t_phone) if self.clockmap.ready else None
        self.frames.push(Frame(captured_at_phone_ms=t_phone, captured_at_server_s=t_server,
                               received_at_server_s=self._clock(), width=w, height=h,
                               mime=str(msg.get("mime") or "image/jpeg"), data=data))
        self.counts["frames"] += 1

    def _trim(self, ring: deque) -> None:
        if not ring:
            return
        cutoff = ring[-1][0] - RING_SECONDS
        while ring and ring[0][0] < cutoff:
            ring.popleft()

    def _phone_audio_latency_s(self) -> float:
        lat = ((self.hello.get("audio") or {}).get("latency_s"))
        return float(lat) if isinstance(lat, (int, float)) and 0 <= lat < 1.0 else 0.0

    # ── measuring ─────────────────────────────────────────────────────────
    async def start_measure(self, *, mode: str = "pattern", duration_s: float | None = None) -> None:
        if mode not in ("pattern", "show"):
            await self.send({"type": "error", "message": f"unknown mode {mode!r}"})
            return
        if not self._audio_ref_started:
            self._audio_ref_started = self.audio_ref.start()
        if mode == "pattern":
            if self.pattern is None:
                await self.send({"type": "error", "message": "no pattern driver"})
                return
            try:
                run = await self.pattern.start(
                    duration_s=duration_s or 12.0, on_done=self._pattern_done)
            except Exception as exc:
                await self.send({"type": "error", "message": f"pattern refused: {exc}"})
                return
            self.light_ref = PatternReference(run, self._clock)
            self.mode = "pattern"
            await self.send({"type": "measure_started", "mode": mode, **run.as_dict()})
        else:
            self.light_ref = ShowReference(self._show_writes, self._clock)
            self.mode = "show"
            await self.send({"type": "measure_started", "mode": mode,
                             "window_s": SHOW_WINDOW_S})

    def _pattern_done(self, run: PatternRun) -> None:
        # The final, full-window read is taken FINAL_SETTLE_S after the last
        # edge: the phone batches its streams (~100 ms), the light itself
        # lags the write, and the last luminance response has to cross the
        # network before it can be counted — reading at the instant the
        # driver finishes would silently drop the tail of the capture.
        self._final_task = asyncio.get_event_loop().create_task(
            self._finalize_pattern(run), name=f"spectra-av-sync-final-{self.id}")

    async def _finalize_pattern(self, run: PatternRun) -> None:
        try:
            await asyncio.sleep(FINAL_SETTLE_S)
        except asyncio.CancelledError:
            return
        est = self.estimate()
        self.last_estimate = est
        record = self._record(est, final=True)
        self.mode = None
        try:
            await self.send({"type": "measure_done", "mode": "pattern", "aborted": run.aborted,
                             "estimate": est.as_dict(), "measurement": record})
        except Exception:
            logger.exception("av_sync session %s: measure_done send failed", self.id)

    async def stop_measure(self) -> None:
        if self.mode == "pattern" and self.pattern is not None and self.pattern.active:
            await self.pattern.stop()          # _pattern_done fires via on_done
        elif self.mode == "show":
            est = self.estimate()
            self.last_estimate = est
            record = self._record(est, final=True) if est.ok else None
            self.mode = None
            await self.send({"type": "measure_done", "mode": "show", "aborted": False,
                             "estimate": est.as_dict(), "measurement": record})

    # ── the estimator ─────────────────────────────────────────────────────
    def estimate(self) -> Estimate:
        clock = self.clockmap.as_dict()
        light_ref_desc = self.light_ref.describe() if self.light_ref else {"kind": None}
        empty = corr.LagEstimate(False, None, None, 0.0, 1.0, 0.0, 0, 0, reason="empty")
        if not self.clockmap.ready:
            return self._refused("clock", empty, empty, light_ref_desc, clock, 0.0)
        if not self.audio_ref.available():
            return self._refused("no_audio_ref", empty, empty, light_ref_desc, clock, 0.0)
        if self.light_ref is None or not self.audio_probe or not self.video_probe:
            return self._refused("no_data", empty, empty, light_ref_desc, clock, 0.0)
        t0, t1 = self.light_ref.window()
        window_s = max(0.0, t1 - t0)
        # audio: server hub envelope (ref) vs phone envelope (probe), onset flux both sides
        a_ref = self.audio_ref.series(since_s=t0 - AUDIO_MAX_LAG_S - 1.0)
        a_probe = self._audio_series(t0 - 1.0, t1 + AUDIO_MAX_LAG_S + 1.0)
        audio = corr.estimate_lag(a_ref, a_probe, max_lag_s=AUDIO_MAX_LAG_S, condition="onset")
        # light: reference vs the best-responding luminance region
        l_ref = self.light_ref.series(t0, t1)
        light, region = self._best_light_lag(l_ref, t0 - 1.0, t1 + LIGHT_MAX_LAG_S + 1.0)
        systematics, bound = self._systematics()
        if not audio.ok:
            return self._refused("audio", light, audio, light_ref_desc, clock, window_s,
                                 region=region, systematics=systematics, bound=bound)
        if not light.ok:
            return self._refused("light", light, audio, light_ref_desc, clock, window_s,
                                 region=region, systematics=systematics, bound=bound)
        av = (light.lag_s - audio.lag_s) * 1000.0
        sig = None
        if light.sigma_s is not None and audio.sigma_s is not None:
            sig = float(np.hypot(light.sigma_s, audio.sigma_s) * 1000.0)
        later, earlier = self._directional(systematics)
        # the TRUE value = reported − (later terms) + (earlier terms); later
        # terms make the lights LOOK later than they are, so the truth is
        # further AHEAD by up to `later`, further BEHIND by up to `earlier`
        return Estimate(True, av, sig, light, audio, region, systematics, bound, later, earlier, "",
                        _statement(av, sig, bound, light, audio, "", later_ms=later,
                                   earlier_ms=earlier),
                        light_ref_desc, clock, window_s)

    def _refused(self, reason: str, light, audio, light_ref_desc, clock, window_s, *,
                 region: str = "", systematics: list | None = None, bound: float = 0.0) -> Estimate:
        systematics = systematics if systematics is not None else self._systematics()[0]
        bound = bound or self._systematics()[1]
        later, earlier = self._directional(systematics)
        return Estimate(False, None, None, light, audio, region, systematics, bound, later, earlier,
                        reason, _statement(None, None, bound, light, audio, reason),
                        light_ref_desc, clock, window_s)

    def _audio_series(self, t0: float, t1: float) -> Series:
        items = [(t, v) for (t, v) in self.audio_probe if t0 <= t <= t1]
        if not items:
            return Series(np.zeros(0), np.zeros(0))
        t, v = zip(*items)
        return Series(np.asarray(t), np.asarray(v))

    def _video_series(self, t0: float, t1: float, region: int | None) -> Series:
        items = []
        for (t, l, g) in self.video_probe:
            if t0 <= t <= t1:
                if region is None:
                    items.append((t, l))
                elif g and region < len(g):
                    items.append((t, g[region]))
        if not items:
            return Series(np.zeros(0), np.zeros(0))
        t, v = zip(*items)
        return Series(np.asarray(t), np.asarray(v))

    def _best_light_lag(self, l_ref: Series, t0: float, t1: float) -> tuple[corr.LagEstimate, str]:
        """Correlate the reference against the whole-frame mean AND each of
        the phone's grid regions; keep the strongest detection. The lights
        rarely fill the frame — a region that IS a light beats a mean
        diluted by the wall around it."""
        candidates: list[tuple[corr.LagEstimate, str]] = []
        mean_series = self._video_series(t0, t1, None)
        grid_n = 0
        for (_, _, g) in self.video_probe:
            if g:
                grid_n = len(g)
                break
        probes = [(mean_series, "mean")] + [
            (self._video_series(t0, t1, i), f"region{i}") for i in range(grid_n)]
        cond = self.light_ref.condition if self.light_ref else "highpass"
        transform = self.light_ref.probe_transform if self.light_ref else "raw"
        for probe, name in probes:
            if probe.empty:
                continue
            if transform == "edge":
                probe = Series(probe.t, _edge_strength(probe.v))
            est = corr.estimate_lag(l_ref, probe, max_lag_s=LIGHT_MAX_LAG_S, condition=cond)
            candidates.append((est, name))
        if not candidates:
            return corr.LagEstimate(False, None, None, 0.0, 1.0, 0.0, l_ref.t.size, 0,
                                    reason="empty"), ""
        ok = [c for c in candidates if c[0].ok]
        pool = ok or candidates
        best = max(pool, key=lambda c: c[0].peak_ratio)
        return best

    def _systematics(self) -> tuple[list[dict], float]:
        video = self.hello.get("video") or {}
        audio = self.hello.get("audio") or {}
        terms = list(SYSTEMATICS_ALWAYS)
        fps = video.get("fps")
        if isinstance(fps, (int, float)) and fps > 0:
            # replace the fixed 30 fps exposure bound with this capture's own
            name, _, d, dep = terms[1]
            terms[1] = (name, round(500.0 / float(fps), 1), d, dep)
        terms.append(SYSTEMATIC_CAPTURE_TIME if video.get("capture_time_available")
                     else SYSTEMATIC_NO_CAPTURE_TIME)
        terms.append(SYSTEMATIC_MIC_REPORTED if isinstance(audio.get("latency_s"), (int, float))
                     else SYSTEMATIC_MIC_UNKNOWN)
        out = [{"term": n, "bound_ms": b, "direction": d, "depends_on": dep}
               for (n, b, d, dep) in terms]
        return out, float(sum(t["bound_ms"] for t in out))

    def _directional(self, systematics: list[dict]) -> tuple[float, float]:
        """(later_ms, earlier_ms): how far the named systematics could push
        the TRUE value behind (more positive) or ahead (more negative) of
        the reported one. A term tagged "either" counts on both sides."""
        later = sum(t["bound_ms"] for t in systematics if t["direction"] in ("lights_look_later", "either"))
        earlier = sum(t["bound_ms"] for t in systematics if t["direction"] in ("lights_look_earlier", "either"))
        return float(later), float(earlier)

    # ── the record (the only thing persisted) ─────────────────────────────
    def _record(self, est: Estimate, *, final: bool) -> dict:
        record = {
            "id": uuid.uuid4().hex[:12],
            "session_id": self.id,
            "at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "mode": self.mode,
            "final": final,
            "ok": est.ok,
            "av_offset_ms": est.as_dict()["av_offset_ms"],
            "sigma_ms": est.as_dict()["sigma_ms"],
            "systematic_bound_ms": round(est.systematic_bound_ms, 1),
            "light_lag_ms": est.light.as_dict()["lag_ms"],
            "audio_lag_ms": est.audio.as_dict()["lag_ms"],
            "light_region": est.light_region,
            "light_ref": est.light_ref,
            "clock": est.clock,
            "statement": est.statement,
            "reason": est.reason,
            "phone": self.hello,
            "counts": dict(self.counts),
        }
        self.measurements.append(record)
        try:
            append_measurement(record, path=self._measurements_file)
        except Exception:
            logger.exception("av_sync: could not persist measurement record")
        return record

    def status(self) -> dict:
        return {
            "session_id": self.id, "mode": self.mode, "closed": self.closed,
            "clock": self.clockmap.as_dict(), "counts": dict(self.counts),
            "audio_ref": self.audio_ref.stats(),
            "light_ref": self.light_ref.describe() if self.light_ref else None,
            "frame_tap": self.frames.status(),
            "last_estimate": self.last_estimate.as_dict() if self.last_estimate else None,
            "phone": self.hello,
        }


def _edge_strength(x: np.ndarray) -> np.ndarray:
    """|first difference| of luminance, box-smoothed — both an ON and an
    OFF edge count as an edge for the passive show reference."""
    x = np.asarray(x, dtype=float)
    if x.size < 2:
        return np.zeros_like(x)
    d = np.abs(np.diff(x, prepend=x[0]))
    return corr._box_smooth(d, 3)


# ── the measurements file ──────────────────────────────────────────────────

def _measurements_path(path: Optional[os.PathLike] = None):
    return config.AV_SYNC_MEASUREMENTS_FILE if path is None else path


def load_measurements(path: Optional[os.PathLike] = None) -> list[dict]:
    p = _measurements_path(path)
    try:
        if not os.path.exists(p):
            return []
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return list(data.get("measurements") or [])
    except Exception:
        logger.exception("av_sync: unreadable measurements file %s", p)
        return []


def append_measurement(record: dict, path: Optional[os.PathLike] = None) -> None:
    p = _measurements_path(path)
    items = load_measurements(p)
    items.append(record)
    items = items[-MEASUREMENTS_KEEP:]
    os.makedirs(os.path.dirname(str(p)) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(str(p)) or ".", prefix="av_sync", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"measurements": items}, fh, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


PRIVACY_SUMMARY = {
    "raw_media_leaves_phone": False,
    "sent": "microphone log-energy envelope (~90 numbers/s) + per-frame camera brightness "
            "(one mean + a 4x4 grid per frame); JPEG still frames ONLY while the frame tap "
            "is enabled (default off), kept in server memory only",
    "written_to_disk": "storage/spectra/av_sync_measurements.json — finished measurement "
                       "records (numbers + statement + phone capability flags); never audio, "
                       "video, frames or the raw number streams",
    "retention": f"last {MEASUREMENTS_KEEP} records; in-memory streams dropped on disconnect; "
                 f"frame ring (≤{FRAME_RING_MAX}) cleared on disconnect",
    "network": "same-origin WebSocket to SPECTRA over whatever network you already reach it "
               "on; nothing is sent anywhere else",
}


# ── process-wide registry (one live session at a time) ────────────────────

current: Optional[Session] = None


async def open_session(send: Callable[[dict], Awaitable[None]], **kw: Any) -> Session:
    """Open a session, closing any previous one (a room has one Admiral —
    a second phone connecting takes over, and the first one's lights/
    pattern are reverted by its close)."""
    global current
    if current is not None and not current.closed:
        await current.close()
    from spectra.services.av_sync_pattern import driver as pattern_driver
    kw.setdefault("pattern", pattern_driver)
    sess = Session(send, **kw)
    current = sess
    await sess.open()
    return sess


async def close_session(sess: Session) -> None:
    global current
    await sess.close()
    if current is sess:
        current = None


def status() -> dict:
    return {"session": current.status() if current and not current.closed else None,
            "privacy": PRIVACY_SUMMARY}
