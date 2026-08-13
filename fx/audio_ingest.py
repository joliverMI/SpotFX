"""Shared audio ingest hub — SPECTRA Stage 2 (SpotFX-authored; report §3).

One 44.1 kHz capture stream fanned out to every audio consumer — the 30 s PCM
ring buffer, per-song shape capture, the xcorr sweep, and the vendored
melbank — so lights and analysis provably hear the same audio. Replaces (at a
later wiring stage, NOT in this file) the up-to-four independent
`sounddevice.InputStream`s that today compete for the same PipeWire monitor
and starved each other into software mutual-exclusion workarounds
(auto_offset_service stops xcorr while shape capture runs; report §2.2).

Architecture:

  source (one of)                    AudioIngestHub                consumers
  ─ LiveDeviceSource ──push()──▶  per-consumer bounded  ──drain()──▶ adapters
  ─ WavFileSource                 queues + drop counts             (api/audio_
  ─ test push() calls                                              ingest_adapters,
                                                                   HubMelbankSource)

- `push()` is safe from any thread (the live source pushes from the
  sounddevice callback thread). Each subscriber gets its own bounded deque;
  a full queue drops the OLDEST block (live audio wants freshest data) and
  the drop is counted and logged — never silent. The merge report documents
  real starvation incidents between competing streams; per-consumer drop
  accounting is what makes the next one diagnosable.
- Consumers drain explicitly (`Subscription.drain()`); nothing here spawns
  threads or tasks. The test bed pumps deterministically; live pumping is a
  later stage's wiring decision.
- `LiveDeviceSource.open()` is the ONLY place any code in this module can
  touch audio hardware, and it refuses to run without `allow_device=True` —
  a flag no test sets. `sounddevice` is imported inside `open()` so merely
  importing this module never initializes PortAudio.

`HubMelbankSource` adapts the vendored melbank/analysis pipeline to hub
frames with ZERO edits to vendored files: it subclasses AudioAnalysisSource
and overrides exactly the members whose base implementations enumerate audio
hardware (config schema validation, subscribe→activate, device open). Chunked
to `input_rate / sample_rate` samples (735 at 44.1 kHz / 60 fps), hub audio
enters `_audio_sample_callback` — the same entry, block-size convention, and
44.1 k→30 k resampler path a real device stream uses (report §3 Stage 2).
"""
from __future__ import annotations

import collections
import logging
import threading
import wave
from typing import Callable, Optional

import aubio
import numpy as np
import samplerate as _samplerate

from fx.effects.audio import AudioAnalysisSource
from fx.effects.melbank import FFT_SIZE, MIC_RATE

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 44100
DEFAULT_MAX_BLOCKS = 256  # at 512-sample blocks: ~3 s of headroom per consumer


class Subscription:
    """One consumer's bounded view of the hub stream.

    Counters (all monotonically increasing, guarded by the subscription lock):
      offered_*   — everything the hub pushed at this consumer
      dropped_*   — blocks evicted because the queue was full (oldest-first)
      consumed_*  — blocks the consumer actually drained
    Conservation: offered == consumed + dropped + currently queued.
    """

    def __init__(self, hub: "AudioIngestHub", name: str, max_blocks: int):
        if max_blocks < 1:
            raise ValueError("max_blocks must be >= 1")
        self.hub = hub
        self.name = name
        self.max_blocks = max_blocks
        self._queue: collections.deque[tuple[float, np.ndarray]] = collections.deque()
        self._lock = threading.Lock()
        self.offered_blocks = 0
        self.offered_samples = 0
        self.dropped_blocks = 0
        self.dropped_samples = 0
        self.consumed_blocks = 0
        self.consumed_samples = 0

    def _offer(self, timestamp: float, block: np.ndarray) -> None:
        with self._lock:
            self.offered_blocks += 1
            self.offered_samples += len(block)
            if len(self._queue) >= self.max_blocks:
                _, evicted = self._queue.popleft()
                self.dropped_blocks += 1
                self.dropped_samples += len(evicted)
                if self.dropped_blocks == 1 or self.dropped_blocks % 100 == 0:
                    logger.warning(
                        "audio ingest: consumer %r queue full (max_blocks=%d) — "
                        "dropped oldest block (%d blocks / %d samples dropped so far)",
                        self.name, self.max_blocks,
                        self.dropped_blocks, self.dropped_samples,
                    )
            self._queue.append((timestamp, block))

    def pop(self) -> Optional[tuple[float, np.ndarray]]:
        """Oldest queued (timestamp, block), or None when empty."""
        with self._lock:
            if not self._queue:
                return None
            timestamp, block = self._queue.popleft()
            self.consumed_blocks += 1
            self.consumed_samples += len(block)
            return timestamp, block

    def drain(self) -> list[tuple[float, np.ndarray]]:
        """Everything currently queued, oldest first."""
        out = []
        while (item := self.pop()) is not None:
            out.append(item)
        return out

    def queued_blocks(self) -> int:
        with self._lock:
            return len(self._queue)

    def stats(self) -> dict:
        with self._lock:
            return {
                "max_blocks": self.max_blocks,
                "queued_blocks": len(self._queue),
                "offered_blocks": self.offered_blocks,
                "offered_samples": self.offered_samples,
                "dropped_blocks": self.dropped_blocks,
                "dropped_samples": self.dropped_samples,
                "consumed_blocks": self.consumed_blocks,
                "consumed_samples": self.consumed_samples,
            }


class AudioIngestHub:
    """Fan-out point between one capture source and every audio consumer."""

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._subscriptions: list[Subscription] = []
        self._lock = threading.Lock()
        self.pushed_blocks = 0
        self.pushed_samples = 0

    def subscribe(self, name: str, *, max_blocks: int = DEFAULT_MAX_BLOCKS) -> Subscription:
        sub = Subscription(self, name, max_blocks)
        with self._lock:
            self._subscriptions.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subscriptions:
                self._subscriptions.remove(sub)

    def push(self, block: np.ndarray, timestamp: float = 0.0) -> None:
        """Distribute one block of float32 mono samples to every subscriber.
        Callable from any thread; each subscriber gets the same array object
        (consumers must not mutate blocks in place)."""
        block = np.asarray(block, dtype=np.float32).reshape(-1)
        with self._lock:
            subs = list(self._subscriptions)
            self.pushed_blocks += 1
            self.pushed_samples += len(block)
        for sub in subs:
            sub._offer(timestamp, block)

    def stats(self) -> dict:
        with self._lock:
            subs = list(self._subscriptions)
            pushed = {
                "sample_rate": self.sample_rate,
                "pushed_blocks": self.pushed_blocks,
                "pushed_samples": self.pushed_samples,
            }
        return {**pushed, "consumers": {s.name: s.stats() for s in subs}}


# ── Sources ──────────────────────────────────────────────────────────────────

class WavFileSource:
    """Pushes a PCM WAV file through the hub — the offline test-bed source.

    16-bit PCM only (the format SpotFX's capture pipeline writes); stereo is
    downmixed by channel mean; samples scale to float32 in [-1, 1) via /32768.
    Unpaced: run() pushes the whole file as fast as the consumers' queues
    absorb it, stamping each block with its song-relative time.
    """

    def __init__(self, hub: AudioIngestHub, path: str, block_size: int = 512):
        self.hub = hub
        self.path = path
        self.block_size = block_size

    def run(self) -> int:
        """Push the entire file; returns total samples pushed."""
        pcm = self.load()
        for start in range(0, len(pcm), self.block_size):
            block = pcm[start : start + self.block_size]
            self.hub.push(block, timestamp=start / self.hub.sample_rate)
        return len(pcm)

    def load(self) -> np.ndarray:
        """Decode the file to the exact float32 mono array run() pushes."""
        with wave.open(self.path, "rb") as wav:
            if wav.getsampwidth() != 2:
                raise ValueError(
                    f"{self.path}: only 16-bit PCM WAV supported "
                    f"(got sampwidth={wav.getsampwidth()})"
                )
            if wav.getframerate() != self.hub.sample_rate:
                raise ValueError(
                    f"{self.path}: rate {wav.getframerate()} != hub rate "
                    f"{self.hub.sample_rate} — the hub does not resample"
                )
            raw = np.frombuffer(
                wav.readframes(wav.getnframes()), dtype=np.int16
            )
            channels = wav.getnchannels()
        pcm = raw.astype(np.float32) / 32768.0
        if channels > 1:
            pcm = pcm.reshape(-1, channels).mean(axis=1)
        return pcm


class LiveDeviceSource:
    """The production capture source: one sounddevice.InputStream feeding the
    hub. PRESENT BUT NEVER OPENED IN TESTS — open() refuses to run unless the
    caller passes allow_device=True, and no test sets that flag. sounddevice
    is imported inside open() so importing this module never loads PortAudio.
    Wiring this into main.py is a later stage; nothing constructs it today.
    """

    def __init__(
        self,
        hub: AudioIngestHub,
        device: Optional[str] = None,
        block_size: int = 512,
    ):
        self.hub = hub
        self.device = device  # None = system default
        self.block_size = block_size
        self._stream = None
        self.callback_status_count = 0

    def open(self, *, allow_device: bool = False) -> None:
        if not allow_device:
            raise RuntimeError(
                "LiveDeviceSource.open() touches audio hardware; pass "
                "allow_device=True explicitly (never from tests)"
            )
        import sounddevice as sd  # deliberate: the module's only hardware path
        import time

        def _callback(indata, frames, cb_time, status):
            if status:
                self.callback_status_count += 1
                logger.warning("audio ingest: device callback status %s", status)
            self.hub.push(indata[:, 0].copy(), timestamp=time.monotonic())

        self._stream = sd.InputStream(
            samplerate=self.hub.sample_rate,
            blocksize=self.block_size,
            channels=1,
            dtype="float32",
            device=self.device,
            callback=_callback,
        )
        self._stream.start()
        logger.info(
            "audio ingest: live device source opened (device=%s, rate=%d)",
            self.device or "default", self.hub.sample_rate,
        )

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def is_open(self) -> bool:
        return self._stream is not None


# ── Vendored melbank path fed from the hub ───────────────────────────────────

class HubMelbankSource(AudioAnalysisSource):
    """The vendored melbank/aubio analysis pipeline, fed by hub blocks instead
    of its own device stream. No vendored files are modified: this subclass
    overrides exactly the base members whose implementations enumerate or open
    audio hardware, and replicates only their non-device work.

    ingest() re-chunks arbitrary hub blocks to `input_rate // sample_rate`
    samples (735 at 44.1 kHz / 60 fps) — the identical blocksize convention
    AudioInputSource.open_audio_stream configures on a real InputStream — and
    hands each chunk to the unmodified `_audio_sample_callback`, which runs
    the stock 44.1 k→30 k resampler, phase vocoder, melbanks, pitch/onset/
    tempo, and subscriber callbacks. Effects therefore cannot tell this source
    from a live device.

    `ledfx` is an FxHost (config + events + dev_enabled are what the analysis
    layer reads). Single-threaded contract: call ingest() from one place.
    """

    _NON_DEVICE_AUDIO_DEFAULTS = {
        "sample_rate": 60,
        "mic_rate": DEFAULT_SAMPLE_RATE,
        "fft_size": FFT_SIZE,
        "min_volume": 0.2,
        "audio_device": None,
        "audio_device_name": "",
        "delay_ms": 0,
    }

    def __init__(self, ledfx, config: Optional[dict] = None,
                 input_rate: int = DEFAULT_SAMPLE_RATE):
        self._input_rate = input_rate
        super().__init__(ledfx, config or {})
        self._hop_in = input_rate // self._config["sample_rate"]
        self._pending = np.zeros(0, dtype=np.float32)
        self.frames_ingested = 0
        self._init_dsp()

    # -- base members replaced because they enumerate/open hardware ----------

    def update_config(self, config):
        # AudioInputSource.update_config validates through AUDIO_CONFIG_SCHEMA,
        # whose property getter and device_index_validator both enumerate
        # PortAudio devices. Merge over the non-device defaults instead.
        if hasattr(self, "_config") and isinstance(self._config, dict):
            config = {**self._config, **config}
        self._config = {
            **self._NON_DEVICE_AUDIO_DEFAULTS,
            **config,
            "mic_rate": self._input_rate,
        }
        # AudioAnalysisSource.update_config re-runs analysis setup on config
        # change; during __init__ the base calls initialise_analysis itself.
        if hasattr(self, "melbanks"):
            self.initialise_analysis()
        if hasattr(self, "resampler"):
            self._init_dsp()  # fft_size/sample_rate changes rebuild DSP state

    def subscribe(self, callback: Callable) -> None:
        # Base subscribe auto-activates the class-level device stream.
        self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable) -> None:
        # Base unsubscribe arms a deactivation timer on the shared stream.
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def activate(self):
        raise RuntimeError("HubMelbankSource is hub-fed; it never opens a device")

    def deactivate(self):
        pass

    def check_and_deactivate(self):
        # Fired via threading.Timer by the base shutdown listener; the base
        # implementation inspects shared class stream state. Nothing to do.
        pass

    # -- DSP state a device activation would have built ----------------------

    def _init_dsp(self) -> None:
        # Mirrors the analysis-state block of AudioInputSource._activate_inner
        # (pre-emphasis, buffers, phase vocoder, resampler) minus every device
        # concern. delay_ms is intentionally unsupported: it exists to sync
        # LedFX output with laggy speakers and belongs to output wiring.
        self.pre_emphasis = aubio.digital_filter(3)
        coeffs_type = self._ledfx.config.get("melbanks", {}).get(
            "coeffs_type", "matt_mel"
        )
        if coeffs_type == "matt_mel":
            self.pre_emphasis.set_biquad(0.8268, -1.6536, 0.8268, -1.6536, 0.6536)
        elif coeffs_type == "scott_mel":
            self.pre_emphasis.set_biquad(1.3662, -1.9256, 0.5621, -1.9256, 0.9283)
        else:
            self.pre_emphasis.set_biquad(0.85870, -1.71740, 0.85870, -1.71605, 0.71874)

        hop = MIC_RATE // self._config["sample_rate"]
        self._raw_audio_sample = np.zeros(hop, dtype=np.float32)
        self._phase_vocoder = aubio.pvoc(self._config["fft_size"], hop)
        self._frequency_domain_null = aubio.cvec(self._config["fft_size"])
        self._frequency_domain = self._frequency_domain_null
        self.delay_queue = None
        self.resampler = _samplerate.Resampler("sinc_fastest", channels=1)

    # -- the hub feed --------------------------------------------------------

    def ingest(self, block: np.ndarray) -> int:
        """Feed one hub block; returns how many input-rate chunks it handed to
        `_audio_sample_callback`. (A chunk the stock resampler judges malformed
        — typically the priming frame — is discarded downstream with a debug
        log; the accepted-frame signal is a subscribed callback firing.)
        Partial chunks are carried over to the next call, so consecutive
        ingests lose no samples regardless of hub block size."""
        block = np.asarray(block, dtype=np.float32).reshape(-1)
        self._pending = (
            np.concatenate([self._pending, block]) if self._pending.size else block
        )
        frames = 0
        while self._pending.size >= self._hop_in:
            chunk = np.ascontiguousarray(self._pending[: self._hop_in])
            self._pending = self._pending[self._hop_in :]
            self._audio_sample_callback(chunk, len(chunk), None, None)
            frames += 1
        self.frames_ingested += frames
        return frames
