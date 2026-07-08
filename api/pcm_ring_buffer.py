"""
SpotFX — Always-on PCM ring buffer.

Runs a single dedicated `sounddevice.InputStream` continuously from app startup
and keeps the last N seconds of float32 mono PCM in a bounded ring buffer.
Consumers (notably audio_shape_service force-recapture) can request the PCM
slice from a given monotonic timestamp through `now`, letting them backfill
song-start audio that played before the capture worker realized a song change.

Memory: at 44.1kHz mono float32, 30s = 5.3 MB. Trivial. The buffer is sized
to settings.pcm_ring_buffer_seconds (default 30).

Architecture:
- Singleton via module-level `pcm_ring_buffer` instance.
- `start()` opens the input stream and registers a callback that appends each
  audio chunk to the ring (a deque of (monotonic_ts, pcm) tuples).
- The callback is called from sounddevice's audio thread — operations on the
  deque must be thread-safe. CPython's `collections.deque.append`/`popleft`
  are atomic.
- `snapshot_since(t)` and `latest_n_seconds(s)` walk the deque to assemble
  the requested PCM slice. These run on the asyncio thread; they don't need
  locking because deque iteration during concurrent appends is safe (we may
  miss the very-newest chunk, which is fine).
- Additive — does NOT replace the per-purpose AudioCaptureStream instances
  used by audio_shape_service or auto_offset_service xcorr. Multiple
  PulseAudio consumers from the same input source are supported.
"""
from __future__ import annotations

import collections
import logging
import time
from typing import Optional

import numpy as np
import sounddevice as sd

from config import settings

logger = logging.getLogger(__name__)


class PCMRingBuffer:
    """Continuously-running PCM ring buffer. See module docstring."""

    def __init__(self) -> None:
        self._stream: Optional[sd.InputStream] = None
        self._chunks: collections.deque[tuple[float, np.ndarray]] = collections.deque()
        self._sample_rate: int = settings.audio_sample_rate
        self._buffer_seconds: int = getattr(settings, "pcm_ring_buffer_seconds", 30)
        self._max_samples: int = self._sample_rate * self._buffer_seconds
        self._sample_count: int = 0
        self._started_at: float = 0.0

    def start(self) -> None:
        """Open the input stream and begin filling the ring. Idempotent."""
        if self._stream is not None:
            return
        device = None if settings.audio_input_device == "default" else settings.audio_input_device
        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                blocksize=settings.audio_chunk_size,
                channels=1,
                dtype="float32",
                device=device,
                callback=self._callback,
            )
            self._stream.start()
            self._started_at = time.monotonic()
            logger.info(
                "PCM ring buffer started (%ds @ %dHz, max %d samples, device=%s)",
                self._buffer_seconds, self._sample_rate, self._max_samples,
                device or "default",
            )
        except Exception as exc:
            logger.error("PCM ring buffer failed to start: %s", exc)
            self._stream = None

    def stop(self) -> None:
        """Close the input stream. Idempotent."""
        if self._stream is None:
            return
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
        self._stream = None
        self._chunks.clear()
        self._sample_count = 0
        logger.info("PCM ring buffer stopped")

    def _callback(self, indata: np.ndarray, frames: int, cb_time, status) -> None:
        """sounddevice audio thread — must be thread-safe and fast."""
        if status:
            logger.debug("PCM ring buffer callback status: %s", status)
        # Stamp with the time the chunk was received. Coarse — adequate for
        # song-start backfill where we're aligning to ±100ms.
        ts = time.monotonic()
        pcm = indata[:, 0].astype(np.float32).copy()
        self._chunks.append((ts, pcm))
        self._sample_count += len(pcm)
        # Trim from the front while we exceed the budget. deque.popleft is
        # atomic in CPython.
        while self._sample_count > self._max_samples and self._chunks:
            _, oldest = self._chunks.popleft()
            self._sample_count -= len(oldest)

    def snapshot_since(self, monotonic_ts: float) -> np.ndarray:
        """Return concatenated float32 mono PCM from `monotonic_ts` through now."""
        return self.snapshot_since_with_start(monotonic_ts)[0]

    def snapshot_since_with_start(self, monotonic_ts: float) -> tuple[np.ndarray, float]:
        """Return (pcm, effective_start_monotonic) from `monotonic_ts` through now.

        effective_start_monotonic is where the returned PCM actually begins:
        equal to the request when the buffer covers it, or the oldest held
        chunk's start when the request predates the buffer (pre-roll
        truncated — callers must label the PCM from the EFFECTIVE start, not
        the requested one, or every sample gets stamped too early).
        """
        if not self._chunks:
            return np.zeros(0, dtype=np.float32), monotonic_ts
        # Snapshot the deque to a list so concurrent appends/popleft don't
        # disturb iteration (chunks added mid-iteration would be missed —
        # acceptable, they're newer than `now` anyway).
        snap = list(self._chunks)
        oldest_ts = snap[0][0]
        if monotonic_ts < oldest_ts:
            # Requested window starts before the oldest chunk we hold.
            # Return what we have from the start, but log a warning so the
            # caller knows the pre-roll is incomplete.
            logger.warning(
                "PCM ring buffer: requested ts=%.3f older than oldest chunk %.3f (%.1fs gap) — pre-roll truncated",
                monotonic_ts, oldest_ts, oldest_ts - monotonic_ts,
            )
            monotonic_ts = oldest_ts
        # Find the first chunk whose timestamp covers `monotonic_ts`. Each
        # chunk's timestamp is when it was RECEIVED — we keep chunks that
        # ended at or after `monotonic_ts`.
        out_chunks: list[np.ndarray] = []
        for ts, pcm in snap:
            chunk_duration = len(pcm) / self._sample_rate
            chunk_start = ts - chunk_duration
            if chunk_start >= monotonic_ts:
                # Whole chunk is inside the requested window
                out_chunks.append(pcm)
            elif ts > monotonic_ts:
                # Partial chunk — slice from the offset into this chunk that
                # corresponds to monotonic_ts
                offset_s = monotonic_ts - chunk_start
                offset_samples = max(0, int(offset_s * self._sample_rate))
                if offset_samples < len(pcm):
                    out_chunks.append(pcm[offset_samples:])
        if not out_chunks:
            return np.zeros(0, dtype=np.float32), monotonic_ts
        return np.concatenate(out_chunks), monotonic_ts

    def latest_n_seconds(self, seconds: float) -> np.ndarray:
        """Convenience: return the last `seconds` of PCM (or what's available)."""
        return self.snapshot_since(time.monotonic() - seconds)

    def is_running(self) -> bool:
        return self._stream is not None

    def stats(self) -> dict:
        """Diagnostic snapshot: depth, sample count, age of oldest sample."""
        if not self._chunks:
            return {
                "running": self.is_running(),
                "chunks": 0,
                "samples": 0,
                "seconds": 0.0,
                "started_at": self._started_at,
            }
        oldest_ts = self._chunks[0][0]
        return {
            "running": self.is_running(),
            "chunks": len(self._chunks),
            "samples": self._sample_count,
            "seconds": self._sample_count / self._sample_rate,
            "oldest_age_s": time.monotonic() - oldest_ts,
            "started_at": self._started_at,
        }


# Singleton — import this from anywhere that needs pre-roll PCM.
pcm_ring_buffer = PCMRingBuffer()
