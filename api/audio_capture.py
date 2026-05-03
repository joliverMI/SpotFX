"""
SpotFX — Audio capture and real-time feature extraction.

Cross-platform:
  - Windows desktop: captures from default loopback / virtual cable
  - Raspberry Pi 5: captures from snapclient audio source (configured via
    settings.audio_input_device — set to the correct ALSA/PulseAudio device name)

Produces a stream of AudioFrame objects consumed by:
  - AudioShapeRecorder  (stores to .npz)
  - AudioAnalyzer       (detects music marks in real-time)
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

from config import settings

logger = logging.getLogger(__name__)

LOW_FREQ_CUTOFF = 250    # Hz — below this = "bass"
HIGH_FREQ_CUTOFF = 4000  # Hz — above this = "highs"


@dataclass
class AudioFrame:
    timestamp_ms: int          # ms since song start (adjusted for audio latency)
    rms_total: float
    rms_low: float
    rms_mid: float
    rms_high: float


def _compute_band_rms(pcm: np.ndarray, sample_rate: int,
                       low_hz: float, high_hz: float) -> float:
    """Bandpass filter a chunk and compute RMS."""
    from scipy.signal import butter, sosfilt
    nyq = sample_rate / 2
    low = max(low_hz / nyq, 1e-6)
    high = min(high_hz / nyq, 1 - 1e-6)
    sos = butter(4, [low, high], btype="band", output="sos")
    filtered = sosfilt(sos, pcm)
    return float(np.sqrt(np.mean(filtered ** 2)))


class AudioCaptureStream:
    """
    Opens an audio input stream and pushes AudioFrame objects into an asyncio queue.
    Also buffers raw PCM chunks so the caller can write a WAV file after capture.

    Usage:
        stream = AudioCaptureStream(song_start_monotonic)
        async for frame in stream:
            ...
        pcm = stream.drain_pcm()   # concatenated float32 mono array
    """

    def __init__(self, song_start_monotonic: float):
        self._song_start = song_start_monotonic
        # Queue size: at 50ms/frame, 200 = 10s of buffer. Observed in production
        # that a 200-frame buffer overflows during normal trigger-fire bursts
        # (3+ concurrent plan fires + WebSocket reconnects + librosa subprocess
        # IPC), creating capture gaps that get the shape discarded. 1000 frames
        # = 50s lets the consumer absorb several-second event-loop blips without
        # dropping audio data. Memory cost: ~1000 × ~80 bytes/AudioFrame = 80KB.
        self._queue: asyncio.Queue[AudioFrame | None] = asyncio.Queue(maxsize=1000)
        self._stream: sd.InputStream | None = None
        self._loop = asyncio.get_event_loop()
        # Raw PCM buffer for WAV/librosa — list.append is GIL-atomic in CPython
        self._pcm_chunks: list[np.ndarray] = []
        # Diagnostic counter for queue-full drops (correlated with gap discards).
        self._dropped_frames: int = 0

    def _callback(self, indata: np.ndarray, frames: int,
                  cb_time, status) -> None:
        """Called by sounddevice in a separate thread — must be thread-safe."""
        if status:
            # Elevate to WARNING so we can correlate device-level overflows /
            # underruns with downstream gap discards. PortAudio sets this
            # whenever the input buffer overruns (we missed reading samples
            # in time), which is exactly the signal we want.
            logger.warning("Audio callback status: %s", status)

        pcm = indata[:, 0].astype(np.float32)  # mono
        self._pcm_chunks.append(pcm.copy())
        # Use cb_time.inputBufferAdcTime for accurate capture timestamp.
        # This is when the first sample arrived at the ADC, which is earlier than
        # callback invocation by the driver's input buffer latency (~chunk duration).
        # Falls back to time.monotonic() if the backend doesn't supply it (value is 0).
        if cb_time.inputBufferAdcTime > 0:
            adc_delay_s = cb_time.currentTime - cb_time.inputBufferAdcTime
        else:
            adc_delay_s = 0.0
        now_ms = int((time.monotonic() - adc_delay_s - self._song_start) * 1000)
        # Adjust for audio latency offset
        adjusted_ms = now_ms - settings.audio_latency_ms

        rms_total = float(np.sqrt(np.mean(pcm ** 2)))
        # Frequency decomposition — normalize FFT by chunk length so values
        # are amplitude-compatible with rms_total (Parseval-consistent scaling)
        sr = settings.audio_sample_rate
        n = len(pcm)
        freqs = np.fft.rfftfreq(n, d=1 / sr)
        fft_mag = np.abs(np.fft.rfft(pcm)) / n  # amplitude-normalised
        low_mask  = freqs < LOW_FREQ_CUTOFF
        mid_mask  = (freqs >= LOW_FREQ_CUTOFF) & (freqs <= HIGH_FREQ_CUTOFF)
        high_mask = freqs > HIGH_FREQ_CUTOFF
        rms_low  = float(np.sqrt(np.mean(fft_mag[low_mask]  ** 2))) if low_mask.any()  else 0.0
        rms_mid  = float(np.sqrt(np.mean(fft_mag[mid_mask]  ** 2))) if mid_mask.any()  else 0.0
        rms_high = float(np.sqrt(np.mean(fft_mag[high_mask] ** 2))) if high_mask.any() else 0.0

        frame = AudioFrame(adjusted_ms, rms_total, rms_low, rms_mid, rms_high)
        # Non-blocking put from the audio thread.
        # QueueFull must be caught inside the scheduled callback (where it's raised),
        # not here — call_soon_threadsafe runs put_nowait in the event loop thread.
        def _put(f=frame, _self=self):
            try:
                _self._queue.put_nowait(f)
            except asyncio.QueueFull:
                # Diagnostic: log queue-full drops so we can correlate them
                # with the downstream gap discards. Throttled to once per 50
                # drops to avoid flooding the journal.
                _self._dropped_frames += 1
                if _self._dropped_frames % 50 == 1:
                    logger.warning(
                        "AudioCaptureStream: queue full, dropped frame (total dropped this stream=%d)",
                        _self._dropped_frames,
                    )
        self._loop.call_soon_threadsafe(_put)

    def start(self) -> None:
        device = None if settings.audio_input_device == "default" else settings.audio_input_device
        self._stream = sd.InputStream(
            samplerate=settings.audio_sample_rate,
            blocksize=settings.audio_chunk_size,
            channels=1,
            dtype="float32",
            device=device,
            callback=self._callback,
        )
        self._stream.start()
        logger.info("Audio capture started (device=%s).", settings.audio_input_device)

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
        # Drain any backlog then send sentinel so __anext__ sees StopAsyncIteration
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._queue.put_nowait(None)  # sentinel
        logger.info("Audio capture stopped.")

    def drain_pcm(self) -> np.ndarray:
        """Return all buffered PCM as a single float32 array and clear the buffer."""
        if not self._pcm_chunks:
            return np.array([], dtype=np.float32)
        pcm = np.concatenate(self._pcm_chunks)
        self._pcm_chunks.clear()
        return pcm

    def __aiter__(self):
        return self

    async def __anext__(self) -> AudioFrame:
        frame = await self._queue.get()
        if frame is None:
            raise StopAsyncIteration
        return frame
