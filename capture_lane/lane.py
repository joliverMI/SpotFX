"""
The capture lane: ONE song at a time, played on the hidden player under
account B and turned into the same shape files a normal capture makes.

THE ORDER IS THE SAFETY (`Lane._run`):
  1. Who: account B is signed in, `GET /me` is that account, and it is NOT
     the main account (read fresh, read-only; a sign-in that was never
     checked and a main account that can't be read now is a refusal, not a
     guess). Playing as the main account would stop the house's music.
  2. Where: exactly one device named `device_name` ("Serenity Capture").
     Every play and pause names its id (capture_lane.spotify refuses
     without one).
  3. Not already learned: a complete shape for the song is never captured
     over (re-learning a head is a later phase's, with its realign).
  4. Audio flowing in the FIFO, steady, BEFORE anything plays.
  Only then the play, from 0:00. If any of 1-4 fails, nothing played.

WHILE IT PLAYS, every poll re-checks: still this song, still playing, still
on the hidden player, Spotify's progress keeping time with the clock (a
stalled player puts silence into the stream and slides everything after it),
and the governor's `seq` (a drain drops audio silently). Any of them ends the
job with its reason — and the lane PAUSES the hidden player on every way out
(the `finally`), so a failed job never leaves account B playing on.

THE SONG-TIME of each sample: `origin + n/rate` is when sample n arrived
(capture_lane.pcm); minus the governor's own reported hold (`offset_ms`,
read during the capture) and `extra_latency_ms` is when the player made it;
minus the song's start (the median of `poll time − progress` over every
poll) is where it sits in the song. The samples before 0:00 and after the
song's end are cut off, so the shape starts at its head like a pre-rolled
normal capture. The same `synthesize_frames_from_pcm` arithmetic as the
live capture turns the PCM into frames, the same `AudioShapeRecorder`
saves them, the same `detect_anchors` and the same WAV + librosa step
finish them (services/audio_shape_service.py). The sidecar says
`captured_by: "capture_lane"`.

WHAT IT DOESN'T DO, on purpose: anything with the MAIN account (the
recapture playlist, auto-generated triggers — SpotFX does those when it
reads the outcome), decide what to learn (SpotFX's), or run while nobody
asked (it acts only on `learn`). Its outcomes are a short memory
(`OUTCOMES_KEPT`), read by SpotFX through `status()`.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

RATE = 44100
AUDIO_WAIT_S = 6.0          # the FIFO has this long to start flowing steadily
START_TIMEOUT_S = 15.0      # playback has this long to start after the play
POLL_S = 2.0
STALL_TOLERANCE_MS = 1500   # Spotify's progress may wander this far from the clock
TAIL_S = 0.3                # beyond the measured delay, for the last chunk to land
OVERRUN_S = 60.0            # a job ends this long past the song's own length
OUTCOMES_KEPT = 20

STATES = ("idle", "preparing", "starting", "capturing", "finishing", "saving", "analysing")

SENTENCES = {
    "not_signed_in": "Account B isn't signed in.",
    "wrong_account": "The capture token isn't account B (or is the main account), so nothing was played.",
    "cannot_check_account": "Account B was never checked against the main account and the main "
                            "account can't be read now, so nothing was played.",
    "device_missing": "The hidden player isn't online.",
    "device_ambiguous": "More than one device has the hidden player's name.",
    "device_restricted": "Spotify won't let the hidden player be controlled.",
    "already_learned": "The song is already learned.",
    "no_audio": "No audio is coming from the hidden player's pipe.",
    "did_not_start": "The song didn't start on the hidden player.",
    "interrupted": "Something else took over the hidden player.",
    "stalled": "Spotify stalled while the song played.",
    "governor_drain": "Audio was dropped on the way to the lane.",
    "gap": "Part of the song's audio is missing.",
    "timeout": "The song ran far past its own length.",
    "too_short": "Too little of the song was heard.",
    "wav_librosa_failed": "The shape saved, but its analysis didn't finish.",
    "cancelled": "Stopped on request.",
    "error": "Something went wrong.",
}


class Busy(Exception):
    pass


@dataclass
class Job:
    uri: str
    title: str
    artist: str
    duration_ms: int
    genres: list[str] = field(default_factory=list)
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class Outcome:
    job_id: str
    uri: str
    status: str                 # "ok" | "failed" | "cancelled"
    reason: str = ""
    detail: str = ""
    played: bool = False        # did anything play on the hidden player?
    started_at_ms: int = 0
    ended_at_ms: int = 0
    covered_ms: int = 0
    head_ms: Optional[int] = None
    latency_ms: Optional[int] = None
    npz_file: str = ""


class JobFailed(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass
class LaneDeps:
    gateway: Any
    signed_in_user: Callable[[], Optional[dict]]
    main_user: Callable[[], Optional[str]]
    open_reader: Callable[[], Any]
    governor: Callable[[], Optional[dict]]
    shape_complete: Callable[[str], bool]
    make_recorder: Callable[[Job], Any]
    save_shape: Callable[[Any], Any]                  # blocking: recorder -> npz path
    detect_anchors: Callable[[Any, Any], list]        # blocking: (meta, npz path)
    write_sidecar: Callable[[Any, Any], None]         # blocking: (meta, npz path)
    wav_and_analyze: Callable[[Any, Any, int], Awaitable[bool]]
    device_name: str = "Serenity Capture"
    extra_latency_ms: int = 0
    max_gap_ms: int = 200
    min_capture_pct: float = 0.80
    anchors_enabled: bool = True
    clock: Callable[[], float] = time.monotonic
    wall_ms: Callable[[], int] = lambda: int(time.time() * 1000)
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    to_thread: Callable[..., Awaitable[Any]] = asyncio.to_thread


def production_deps() -> LaneDeps:
    from api import spotify_capture
    from capture_lane.pcm import FifoReader
    from capture_lane.spotify import CaptureGateway
    from config import settings
    from services import audio_analyzer
    from services import audio_shape_service as shapes

    def shape_complete(uri: str) -> bool:
        meta = audio_analyzer.load_audio_shape_meta(uri)
        return bool(meta and meta.capture_complete and not meta.capture_failed)

    def make_recorder(job: Job):
        return audio_analyzer.AudioShapeRecorder(job.uri, job.title, job.artist,
                                                 job.duration_ms, genres=job.genres)

    def write_sidecar(meta, npz_path) -> None:
        npz_path.with_suffix(".json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    return LaneDeps(
        gateway=CaptureGateway(),
        signed_in_user=spotify_capture.signed_in_user,
        main_user=spotify_capture._main_account_id,
        open_reader=lambda: FifoReader(settings.capture_lane_fifo),
        governor=lambda: read_lane_governor(settings.capture_lane_governor_path),
        shape_complete=shape_complete,
        make_recorder=make_recorder,
        save_shape=lambda rec: rec.save(),
        detect_anchors=shapes.detect_anchors,
        write_sidecar=write_sidecar,
        wav_and_analyze=shapes._save_wav_and_analyze,
        device_name=settings.capture_lane_device_name,
        extra_latency_ms=settings.capture_lane_extra_latency_ms,
        max_gap_ms=settings.audio_max_gap_ms,
        min_capture_pct=settings.audio_shape_min_capture_pct,
        anchors_enabled=bool(settings.anchor_enabled),
    )


def read_lane_governor(path: str) -> Optional[dict]:
    """`{seq, dropped_total_ms, offset_ms}` from the hidden player's governor
    status file, or None when it can't be read."""
    import json
    from pathlib import Path
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {"seq": int(data["seq"]),
                "dropped_total_ms": int(data.get("dropped_total_ms") or 0),
                "offset_ms": int(data["offset_ms"]) if data.get("offset_ms") is not None else None}
    except Exception:
        return None


def song_start_from(poll_started: float, poll_ended: float, progress_ms: int) -> float:
    """The clock time the song's 0:00 played, from one poll."""
    return (poll_started + poll_ended) / 2.0 - progress_ms / 1000.0


def sample_window(origin: float, song_start: float, latency_s: float,
                  duration_ms: int, rate: int = RATE) -> tuple[int, int, int]:
    """(first sample, end sample, head_ms): the samples [first, end) that are
    the song's 0:00 to its end, and how far into the song the first kept
    sample sits (0 unless the reader started after the song did)."""
    n0 = round((song_start + latency_s - origin) * rate)
    n_end = n0 + round(duration_ms / 1000.0 * rate)
    head_ms = 0
    if n0 < 0:
        head_ms = round(-n0 / rate * 1000)
        n0 = 0
    return n0, max(n0, n_end), head_ms


class Lane:
    def __init__(self, deps: Optional[LaneDeps] = None) -> None:
        self._deps = deps
        self.state = "idle"
        self.job: Optional[Job] = None
        self.progress_ms: Optional[int] = None
        self.job_started_at_ms: Optional[int] = None
        self.outcomes: list[Outcome] = []
        self._task: Optional[asyncio.Task] = None
        self._cancel = False

    @property
    def deps(self) -> LaneDeps:
        if self._deps is None:
            self._deps = production_deps()
        return self._deps

    # ── the surface ─────────────────────────────────────────────────────────

    def learn(self, job: Job) -> Job:
        if self._task is not None and not self._task.done():
            raise Busy(self.job.uri if self.job else "")
        self.job = job
        self._cancel = False
        self.state = "preparing"
        self.progress_ms = None
        self.job_started_at_ms = self.deps.wall_ms()
        self._task = asyncio.create_task(self._run(job), name=f"capture-lane-{job.job_id}")
        return job

    def cancel(self, job_id: Optional[str] = None) -> bool:
        if self.job is None or self._task is None or self._task.done():
            return False
        if job_id and job_id != self.job.job_id:
            return False
        self._cancel = True
        return True

    async def wait(self) -> Optional[Outcome]:
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        return self.outcomes[-1] if self.outcomes else None

    def status(self) -> dict:
        job = asdict(self.job) if self.job and self.state != "idle" else None
        return {"state": self.state, "job": job, "progress_ms": self.progress_ms,
                "job_started_at_ms": self.job_started_at_ms if job else None,
                "outcomes": [asdict(o) for o in self.outcomes],
                "sentences": SENTENCES}

    # ── one job ─────────────────────────────────────────────────────────────

    async def _run(self, job: Job) -> None:
        d = self.deps
        out = Outcome(job.job_id, job.uri, "failed", started_at_ms=d.wall_ms())
        reader = None
        device_id: Optional[str] = None
        paused = False
        try:
            device_id = await self._preflight(job)
            self.state = "starting"
            reader = d.open_reader()
            reader.start()
            await self._wait_for_audio(reader)
            gov0 = d.governor()
            out.played = True       # from here on, anything may be playing
            starts = await self._start_playback(job, device_id)
            self.state = "capturing"
            offsets = await self._follow(job, device_id, starts, gov0)
            await d.to_thread(d.gateway.pause, device_id)
            paused = True
            self.state = "finishing"
            latency_s = ((statistics.median(offsets) if offsets else 0) + d.extra_latency_ms) / 1000.0
            out.latency_ms = round(latency_s * 1000)
            await d.sleep(latency_s + TAIL_S)
            reader.stop()
            self._check_stream(reader, gov0, d.governor())
            origin = reader.origin()
            if origin is None:
                raise JobFailed("no_audio", "the stream never steadied")
            song_start = statistics.median(starts)
            n0, n_end, head_ms = sample_window(origin, song_start, latency_s, job.duration_ms)
            out.head_ms = head_ms
            pcm = reader.mono(n0, n_end)
            self.state = "saving"
            meta, npz_path, covered = await self._save(job, pcm, head_ms)
            out.covered_ms = covered
            out.npz_file = meta.npz_file
            self.state = "analysing"
            if await d.wav_and_analyze(meta, pcm, RATE):
                out.status = "ok"
            else:
                out.reason = "wav_librosa_failed"
        except JobFailed as exc:
            out.status = "cancelled" if exc.reason == "cancelled" else "failed"
            out.reason, out.detail = exc.reason, exc.detail
        except Exception as exc:          # noqa: BLE001 — a lane never dies on one song
            logger.exception("Capture lane job %s failed", job.job_id)
            out.reason, out.detail = "error", str(exc)
        finally:
            if reader is not None:
                try:
                    reader.stop()
                except Exception:
                    pass
            if out.played and not paused and device_id:
                try:
                    await d.to_thread(d.gateway.pause, device_id)
                except Exception as exc:
                    logger.warning("Capture lane: couldn't pause the hidden player: %s", exc)
                    out.detail = (out.detail + "; " if out.detail else "") + f"pause failed: {exc}"
            out.ended_at_ms = d.wall_ms()
            self.outcomes.append(out)
            del self.outcomes[:-OUTCOMES_KEPT]
            self.state = "idle"
            self.progress_ms = None
            logger.info("Capture lane: %s %s (%s) %s", out.status, job.uri, out.reason or "-", out.detail)

    async def _preflight(self, job: Job) -> str:
        d = self.deps
        who = d.signed_in_user()
        if not who:
            raise JobFailed("not_signed_in")
        me = await d.to_thread(d.gateway.me)
        me_id = (me or {}).get("id")
        if not me_id or me_id != who.get("user_id"):
            raise JobFailed("wrong_account", "the token's account isn't the one that signed in")
        main = await d.to_thread(d.main_user)
        if main and main == me_id:
            raise JobFailed("wrong_account", "the token is the main account")
        if main is None and who.get("checked_not_main") is not True:
            raise JobFailed("cannot_check_account")
        if await d.to_thread(d.shape_complete, job.uri):
            raise JobFailed("already_learned")
        devices = await d.to_thread(d.gateway.devices)
        named = [x for x in devices if str(x.get("name", "")).lower() == d.device_name.lower()]
        if not named:
            raise JobFailed("device_missing")
        if len(named) > 1:
            raise JobFailed("device_ambiguous")
        dev = named[0]
        if dev.get("is_restricted"):
            raise JobFailed("device_restricted")
        if dev.get("volume_percent") is not None and int(dev["volume_percent"]) < 100:
            await d.to_thread(d.gateway.full_volume, dev["id"])
        return dev["id"]

    async def _wait_for_audio(self, reader) -> None:
        d = self.deps
        deadline = d.clock() + AUDIO_WAIT_S
        while reader.origin() is None:
            self._check_cancel()
            if getattr(reader, "error", None):
                raise JobFailed("no_audio", reader.error)
            if d.clock() > deadline:
                raise JobFailed("no_audio", "nothing arrived on the hidden player's pipe")
            await d.sleep(0.1)

    async def _poll(self) -> tuple[Optional[dict], float, float]:
        d = self.deps
        t0 = d.clock()
        pb = await d.to_thread(d.gateway.playback)
        return pb, t0, d.clock()

    async def _start_playback(self, job: Job, device_id: str) -> list[float]:
        d = self.deps
        await d.to_thread(d.gateway.play, device_id, job.uri)
        deadline = d.clock() + START_TIMEOUT_S
        while True:
            self._check_cancel()
            pb, t0, t1 = await self._poll()
            if (pb and pb.get("is_playing") and _uri_of(pb) == job.uri
                    and _device_of(pb) == device_id):
                self.progress_ms = int(pb.get("progress_ms") or 0)
                return [song_start_from(t0, t1, self.progress_ms)]
            if d.clock() > deadline:
                raise JobFailed("did_not_start")
            await d.sleep(0.5)

    async def _follow(self, job: Job, device_id: str, starts: list[float],
                      gov0: Optional[dict]) -> list[int]:
        """Follow the song to its end. Returns the governor's hold readings."""
        from services.capture_watch import governor_moved
        d = self.deps
        offsets: list[int] = []
        give_up = starts[0] + job.duration_ms / 1000.0 + OVERRUN_S
        while True:
            self._check_cancel()
            gov = d.governor()
            if gov and gov.get("offset_ms") is not None:
                offsets.append(int(gov["offset_ms"]))
            moved = governor_moved(gov0, gov)
            if moved:
                raise JobFailed("governor_drain", moved)
            expected_ms = (d.clock() - statistics.median(starts)) * 1000.0
            near_end = expected_ms >= job.duration_ms - POLL_S * 1000
            pb, t0, t1 = await self._poll()
            if not pb or _device_of(pb) != device_id:
                if near_end:
                    return offsets
                raise JobFailed("interrupted", "playback left the hidden player")
            if _uri_of(pb) != job.uri:
                if near_end:
                    return offsets
                raise JobFailed("interrupted", "another song started on the hidden player")
            if not pb.get("is_playing"):
                if near_end:
                    return offsets
                raise JobFailed("interrupted", "the hidden player was paused")
            progress = int(pb.get("progress_ms") or 0)
            self.progress_ms = progress
            est = song_start_from(t0, t1, progress)
            if abs(est - statistics.median(starts)) * 1000 > STALL_TOLERANCE_MS:
                raise JobFailed("stalled", f"progress {progress} ms is "
                                f"{abs(est - statistics.median(starts)) * 1000:.0f} ms off the clock")
            starts.append(est)
            remaining_s = (job.duration_ms - progress) / 1000.0
            if remaining_s <= POLL_S + 0.5:
                await d.sleep(max(0.0, remaining_s) + 0.2)
                self.progress_ms = job.duration_ms
                return offsets
            if d.clock() > give_up:
                raise JobFailed("timeout")
            await d.sleep(POLL_S)

    def _check_stream(self, reader, gov0, gov1) -> None:
        from services.capture_watch import governor_moved
        d = self.deps
        moved = governor_moved(gov0, gov1)
        if moved:
            raise JobFailed("governor_drain", moved)
        if getattr(reader, "overflowed", False):
            raise JobFailed("error", "the song ran past the reader's memory bound")
        if getattr(reader, "error", None):
            raise JobFailed("gap", reader.error)
        drift = reader.drift_ms()
        if drift is not None and abs(drift) > d.max_gap_ms:
            raise JobFailed("gap", f"the stream fell {drift:.0f} ms behind (limit {d.max_gap_ms} ms)")

    async def _save(self, job: Job, pcm, head_ms: int):
        from api.audio_capture import synthesize_frames_from_pcm
        d = self.deps
        frames = synthesize_frames_from_pcm(pcm, head_ms, sample_rate=RATE)
        if not frames:
            raise JobFailed("too_short", "no audio in the song's window")
        covered = frames[-1].timestamp_ms - frames[0].timestamp_ms
        if job.duration_ms > 0 and covered < job.duration_ms * d.min_capture_pct:
            raise JobFailed("too_short", f"heard {covered} ms of {job.duration_ms} ms")
        if await d.to_thread(d.shape_complete, job.uri):
            raise JobFailed("already_learned", "learned elsewhere while the lane listened")
        recorder = d.make_recorder(job)
        for f in frames:
            recorder.ingest(f)
        recorder.meta.captured_by = "capture_lane"
        npz_path = await d.to_thread(d.save_shape, recorder)
        meta = recorder.meta
        meta.capture_complete = True
        if d.anchors_enabled:
            try:
                anchors = await d.to_thread(d.detect_anchors, meta, npz_path)
                meta.anchor_candidates = [c.to_dict() for c in anchors]
            except Exception as exc:
                logger.warning("Capture lane: anchors failed for %s: %s", job.uri, exc)
                meta.anchor_candidates = []
        await d.to_thread(d.write_sidecar, meta, npz_path)
        return meta, npz_path, covered

    def _check_cancel(self) -> None:
        if self._cancel:
            raise JobFailed("cancelled")


def _uri_of(pb: dict) -> Optional[str]:
    return ((pb or {}).get("item") or {}).get("uri")


def _device_of(pb: dict) -> Optional[str]:
    return ((pb or {}).get("device") or {}).get("id")
