"""
The capture lane's EAR: reads the hidden player's PCM out of its own FIFO.

The hidden player's container runs River's parec governor (spotify-stack/
spotify/governor.py) pointed at `capture-audio/capturefifo`: raw s16le,
2 channels, 44.1 kHz, every chunk held at least the governor's floor (500 ms)
after parec read it, then written. Nothing else ever opens that FIFO, so
until this reader does the governor's writer blocks on its open and its
queue drains at the ceiling once a second — the expected idle state.

THE CLOCK. A song-time for every sample needs WHEN each sample arrived. The
reader keeps, per read, (arrival time, samples read so far); `origin()` is
the arrival time of sample 0 in the STEADY flow — a low percentile of
`t - end/rate` over reads after a warm-up, because the first reads after the
FIFO opens are the governor's held backlog arriving in one burst, and a late
read (this thread scheduled late) only ever makes a value larger, never
smaller. Sample n then arrived at `origin + n / rate`.

TWO WAYS A STREAM GOES WRONG, both measured here, never guessed:
  * samples MISSING (parec stalled, so the timeline after the stall is late
    by the stall): `drift_ms()` — the median lateness of the last reads
    against the first steady ones. A reader that was merely late catches up
    (the data waited in the pipe), so its later reads are on time again.
  * samples DROPPED by the governor's drain: its `seq` moves. That is the
    lane's to read (capture_lane.lane), from the governor's status file.

`open_fifo` opens O_NONBLOCK so a container that is down never hangs the
reader: with no writer a read returns EOF and the thread waits and tries
again. Memory: raw bytes for at most `max_seconds` (a 6-minute song is
~63 MB), refused past that so a stuck job can never grow without bound.
"""
from __future__ import annotations

import os
import select
import threading
import time
from typing import Callable, Optional

import numpy as np

RATE = 44100
CHANNELS = 2
FRAME_BYTES = 2 * CHANNELS          # s16le stereo
READ_BYTES = 4096                    # ~23 ms a read at 44.1 kHz stereo
WARMUP_S = 1.0                       # the governor's held backlog arrives in this window
ORIGIN_PERCENTILE = 10
DRIFT_READS = 50


def to_mono_float(raw: bytes) -> np.ndarray:
    """s16le stereo bytes -> mono float32 in [-1, 1) (the channel mean, as
    PulseAudio's own downmix to the mono capture stream does)."""
    usable = len(raw) // FRAME_BYTES * FRAME_BYTES
    if usable <= 0:
        return np.zeros(0, dtype=np.float32)
    pcm = np.frombuffer(memoryview(raw)[:usable], dtype="<i2").reshape(-1, CHANNELS)
    return (pcm.astype(np.float32).mean(axis=1) / 32768.0).astype(np.float32)


def origin_from(reads: list[tuple[float, int]], rate: int = RATE,
                warmup_s: float = WARMUP_S) -> Optional[float]:
    """The steady arrival time of sample 0 (see the module docstring), or
    None while there are not enough steady reads to say."""
    if not reads:
        return None
    t0 = reads[0][0]
    steady = [t - n / rate for t, n in reads if t - t0 >= warmup_s]
    if len(steady) < 5:
        return None
    return float(np.percentile(np.array(steady), ORIGIN_PERCENTILE))


def drift_from(reads: list[tuple[float, int]], rate: int = RATE,
               warmup_s: float = WARMUP_S, window: int = DRIFT_READS) -> Optional[float]:
    """How much later (ms) the last reads arrive than the first steady ones,
    each against the same origin: ~0 for an unbroken stream, the stall's
    length when parec stopped and the samples it would have made are
    missing. None until there are two windows of steady reads."""
    if not reads:
        return None
    t0 = reads[0][0]
    steady = [t - n / rate for t, n in reads if t - t0 >= warmup_s]
    if len(steady) < 2 * window:
        return None
    first = float(np.median(np.array(steady[:window])))
    last = float(np.median(np.array(steady[-window:])))
    return (last - first) * 1000.0


def open_fifo(path: str) -> int:
    return os.open(path, os.O_RDONLY | os.O_NONBLOCK)


class FifoReader:
    """One capture's worth of the FIFO, read on its own thread."""

    def __init__(self, path: str, *, rate: int = RATE, max_seconds: float = 900.0,
                 clock: Callable[[], float] = time.monotonic,
                 opener: Callable[[str], int] = open_fifo) -> None:
        self.path = path
        self.rate = rate
        self.max_bytes = int(max_seconds * rate) * FRAME_BYTES
        self._clock = clock
        self._opener = opener
        self._buf = bytearray()
        self._reads: list[tuple[float, int]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.error: Optional[str] = None
        self.overflowed = False
        self.started_at: Optional[float] = None

    # ── lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> None:
        self.started_at = self._clock()
        self._thread = threading.Thread(target=self._run, name="capture-lane-fifo", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        try:
            fd = self._opener(self.path)
        except OSError as exc:
            self.error = f"can't open {self.path}: {exc}"
            return
        try:
            while not self._stop.is_set():
                ready, _, _ = select.select([fd], [], [], 0.1)
                if not ready:
                    continue
                try:
                    data = os.read(fd, READ_BYTES)
                except BlockingIOError:
                    continue
                if not data:           # no writer yet (or it went away)
                    time.sleep(0.05)
                    continue
                now = self._clock()
                with self._lock:
                    if len(self._buf) + len(data) > self.max_bytes:
                        self.overflowed = True
                        return
                    self._buf.extend(data)
                    self._reads.append((now, len(self._buf) // FRAME_BYTES))
        except OSError as exc:
            self.error = f"reading {self.path} failed: {exc}"
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    # ── what was heard ──────────────────────────────────────────────────────

    @property
    def samples(self) -> int:
        with self._lock:
            return len(self._buf) // FRAME_BYTES

    @property
    def last_arrival(self) -> Optional[float]:
        with self._lock:
            return self._reads[-1][0] if self._reads else None

    def reads(self) -> list[tuple[float, int]]:
        with self._lock:
            return list(self._reads)

    def origin(self) -> Optional[float]:
        return origin_from(self.reads(), self.rate)

    def drift_ms(self) -> Optional[float]:
        return drift_from(self.reads(), self.rate)

    def mono(self, start: int = 0, end: Optional[int] = None) -> np.ndarray:
        """Samples [start, end) as mono float32."""
        with self._lock:
            n = len(self._buf) // FRAME_BYTES
            end = n if end is None else max(0, min(int(end), n))
            start = max(0, min(int(start), end))
            raw = bytes(self._buf[start * FRAME_BYTES:end * FRAME_BYTES])
        return to_mono_float(raw)
