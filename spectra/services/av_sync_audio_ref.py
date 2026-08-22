"""AV-sync AUDIO REFERENCE — a lightweight tap on SPECTRA's own live audio
hub, kept as a bounded ring of (server monotonic seconds, log-energy dB).

WHY THIS IS THE REFERENCE (and not Spotify's position, not the stored WAV)
-------------------------------------------------------------------------
The instrument measures the room's audio/visual offset: light seen vs.
sound heard, for events the engine INTENDS to be simultaneous. The
engine's own clock is the audio passing the server's monitor — on his box
that monitor is `snapcast.monitor`, the local snapclient's null sink, i.e.
what the speakers are playing NOW (snapclients are mutually synced) —
and the same stream is what SPECTRA's live stack already captures for its
audio-reactive effects (`spectra/services/live_host.py`, one
`fx.audio_ingest.LiveDeviceSource` fanned out through one
`AudioIngestHub`). Tapping THAT hub gives the audio reference with the
server's own timestamps, on the same clock as the light writes, with
no second capture stream (AGENTS.md: duplicating the PipeWire capture is
a documented contention problem) and no dependence on the xcorr engine's
wandering `shape_offset_ms` (docs/SPECTRA_TIMING_CONVENTIONS.md,
failure 2) or on a stored WAV existing for the playing song.

What the tap does NOT see, stated so the confidence statement can name it:
  * the PortAudio/PipeWire input latency between a sample hitting the
    monitor and the hub callback stamping it `time.monotonic()` — the
    hub stamps at callback entry with no ADC-time correction
    (fx/audio_ingest.py LiveDeviceSource._callback). Typically 10-40 ms
    on this class of host; it shifts `audio_lag_ms` by that amount and
    cancels NOWHERE in the offset: the reference sound is stamped LATER
    than it was, the phone's measured audio lag reads SMALLER, and the
    lights therefore read relatively LATER (more "behind") by that much —
    the true value is further AHEAD. Named as a systematic term in the
    session's statement (direction "lights_look_later").
  * anything downstream of the monitor — the DAC, the speaker, the air
    between speaker and phone. Those are exactly what the phone measures.

Availability is honest: `available()` is False whenever SPECTRA is not
driving the room (`live.hub is None` — owner released/spot-effects, or
the stack is up with audio closed) and the session reports that reason
instead of a number. The hub API is pull-based (`Subscription.drain()`);
nothing drains for us, so `start()` owns a pump task draining every
PUMP_INTERVAL_S — a consumer that stops draining silently loses its oldest
blocks (counted + logged by the hub), which `stats()` surfaces.

Injectable seam: `AudioReference(hub_getter=...)` — tests hand it a fake
hub; production uses `live.hub` read FRESH on every start (the stack can
come and go across the process's life).
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from typing import Callable, Optional

import numpy as np

from spectra.services.av_sync_correlate import Series

logger = logging.getLogger(__name__)

PUMP_INTERVAL_S = 0.02
RING_SECONDS = 90.0              # how much reference history is kept
SUB_MAX_BLOCKS = 4096            # ~47 s of 512-sample blocks — far beyond any pump stall
HOP_SAMPLES = 512                # one log-energy frame per hub block (≈11.6 ms @ 44.1 k)
SILENCE_FLOOR_DB = -90.0


def _default_hub_getter():
    from spectra.services.live_host import live
    return live.hub


def log_energy_db(block: np.ndarray) -> float:
    """10·log10(mean square) with a silence floor — the one envelope
    definition shared by this tap and the phone (the phone computes the
    SAME quantity on its own mic blocks; av_sync_correlate.onset_flux is
    then applied to both sides identically)."""
    x = np.asarray(block, dtype=np.float64)
    if x.size == 0:
        return SILENCE_FLOOR_DB
    p = float(np.mean(x * x))
    if p <= 0.0:
        return SILENCE_FLOOR_DB
    return max(SILENCE_FLOOR_DB, 10.0 * math.log10(p))


class AudioReference:
    def __init__(self, *, hub_getter: Callable[[], object] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._hub_getter = hub_getter or _default_hub_getter
        self._clock = clock
        self._sub = None
        self._hub = None
        self._task: Optional[asyncio.Task] = None
        self._ring: deque[tuple[float, float]] = deque()
        self.frames_seen = 0
        self.last_frame_at: Optional[float] = None

    # ── availability ──────────────────────────────────────────────────────
    def hub(self):
        try:
            return self._hub_getter()
        except Exception:
            return None

    def available(self) -> bool:
        return self.hub() is not None

    def unavailable_reason(self) -> Optional[str]:
        if self.available():
            return None
        try:
            from fx import light_ownership
            owner = light_ownership.load().owner
        except Exception:
            owner = "unknown"
        return (f"no server audio reference: SPECTRA's live audio hub is not "
                f"open (light ownership = {owner!r}; the hub only runs while "
                f"SPECTRA owns and drives the room)")

    # ── lifecycle ─────────────────────────────────────────────────────────
    def start(self) -> bool:
        """Subscribe + start the pump. Returns False (and stays inert) when
        no hub is open — the session turns that into a stated reason."""
        if self._task is not None:
            return True
        hub = self.hub()
        if hub is None:
            return False
        self._hub = hub
        self._sub = hub.subscribe("av-sync-reference", max_blocks=SUB_MAX_BLOCKS)
        self._ring.clear()
        self._task = asyncio.create_task(self._pump(), name="spectra-av-sync-audio-ref")
        return True

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        sub, self._sub = self._sub, None
        if sub is not None and self._hub is not None:
            unsub = getattr(self._hub, "unsubscribe", None)
            if callable(unsub):
                try:
                    unsub(sub)
                except Exception:
                    logger.exception("av_sync audio ref: unsubscribe failed")
        self._hub = None

    @property
    def running(self) -> bool:
        return self._task is not None

    async def _pump(self) -> None:
        while True:
            try:
                self.ingest_blocks(self._sub.drain() if self._sub is not None else [])
            except Exception:
                logger.exception("av_sync audio ref: pump failed")
            await asyncio.sleep(PUMP_INTERVAL_S)

    # ── data ──────────────────────────────────────────────────────────────
    def ingest_blocks(self, blocks: list[tuple[float, np.ndarray]]) -> None:
        """Turn hub blocks into log-energy frames. A block's hub timestamp
        is taken at callback entry, i.e. (approximately) the END of the
        block's capture window — the frame is stamped at the block's
        centre so a ~12 ms block's energy sits where its samples actually
        were. Exposed (not private) so the executable spec/tests can feed
        synthetic blocks without a hub."""
        for ts, block in blocks:
            n = len(block)
            sr = getattr(self._hub, "sample_rate", 44100) or 44100
            centre = float(ts) - 0.5 * n / float(sr)
            self._ring.append((centre, log_energy_db(block)))
            self.frames_seen += 1
            self.last_frame_at = float(ts)
        self._trim()

    def _trim(self) -> None:
        if not self._ring:
            return
        cutoff = self._ring[-1][0] - RING_SECONDS
        while self._ring and self._ring[0][0] < cutoff:
            self._ring.popleft()

    def series(self, since_s: Optional[float] = None) -> Series:
        items = [(t, v) for (t, v) in self._ring if since_s is None or t >= since_s]
        if not items:
            return Series(np.zeros(0), np.zeros(0))
        t, v = zip(*items)
        return Series(np.asarray(t), np.asarray(v))

    def stats(self) -> dict:
        sub_stats = self._sub.stats() if self._sub is not None and hasattr(self._sub, "stats") else None
        return {
            "available": self.available(),
            "running": self.running,
            "frames_seen": self.frames_seen,
            "ring_frames": len(self._ring),
            "last_frame_age_s": (None if self.last_frame_at is None
                                 else round(self._clock() - self.last_frame_at, 2)),
            "subscription": sub_stats,
            "reason": self.unavailable_reason(),
        }
