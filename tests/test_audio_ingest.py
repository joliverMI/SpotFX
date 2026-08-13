"""SPECTRA Stage 2 test bed: the shared audio ingest hub, offline.

One WAV file through fx.audio_ingest.AudioIngestHub feeds the vendored
melbank pipeline and the production capture consumers simultaneously —
proving lights and analysis hear the same audio — with per-consumer drop
accounting asserted under a deliberately slow consumer.

Fully offline: the WAV is synthesized in tmp_path, no audio device is ever
opened (LiveDeviceSource.open() is asserted to refuse without its explicit
flag), and the final test asserts fx's lazy sounddevice proxy was never
dereferenced. SpotFX-side consumers (PCMRingBuffer, AudioCaptureStream) are
fed through api.audio_ingest_adapters without .start() ever being called, so
their sounddevice import stays unused too.
"""
from __future__ import annotations

import asyncio
import sys
import time
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless
from fx.audio_ingest import (
    AudioIngestHub,
    HubMelbankSource,
    LiveDeviceSource,
    WavFileSource,
)

SAMPLE_RATE = 44100
WAV_SECONDS = 2.0
WAV_SAMPLES = int(SAMPLE_RATE * WAV_SECONDS)  # 88200 = 120 × 735: no tail
BLOCK_SIZE = 512


def _write_test_wav(path: Path) -> np.ndarray:
    """220 Hz + 3 kHz tone mix, 16-bit mono. Returns the float32 array a
    WavFileSource will reproduce exactly (int16/32768 both directions)."""
    t = np.arange(WAV_SAMPLES) / SAMPLE_RATE
    signal = 0.5 * np.sin(2 * np.pi * 220 * t) + 0.2 * np.sin(2 * np.pi * 3000 * t)
    int_pcm = (signal * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(int_pcm.tobytes())
    return int_pcm.astype(np.float32) / 32768.0


def _run(coro):
    return asyncio.run(coro)


# ── The Stage 2 proof: one stream, two consumers, identical audio ────────────

def test_wav_feeds_melbank_and_capture_identically(tmp_path):
    from api.audio_capture import AudioCaptureStream
    from api.audio_ingest_adapters import CaptureStreamFeed

    wav_path = tmp_path / "tone.wav"
    expected_pcm = _write_test_wav(wav_path)

    async def main():
        host = await headless.start_headless_host(str(tmp_path / "fx"))
        try:
            hub = AudioIngestHub(SAMPLE_RATE)
            mel_sub = hub.subscribe("melbank")
            cap_sub = hub.subscribe("capture")

            melbank_source = HubMelbankSource(host)
            accepted_frames: list[int] = []
            melbank_source.subscribe(lambda: accepted_frames.append(1))

            capture = AudioCaptureStream(song_start_monotonic=time.monotonic())
            capture_feed = CaptureStreamFeed(cap_sub, capture)
            frames = []

            async def collect():
                async for frame in capture:
                    frames.append(frame)

            collector = asyncio.create_task(collect())

            pushed = WavFileSource(hub, str(wav_path), BLOCK_SIZE).run()
            assert pushed == WAV_SAMPLES

            # Pump the melbank consumer, keeping the blocks it saw.
            melbank_seen: list[np.ndarray] = []
            for _ts, block in mel_sub.drain():
                melbank_seen.append(block)
                melbank_source.ingest(block)
            capture_feed.pump()
            await asyncio.sleep(0.05)
            capture.stop()
            await collector
        finally:
            await host.shutdown()

        # Both consumers were offered, and consumed, every sample — none
        # dropped, none duplicated: lights and analysis heard the same audio.
        mel_stats, cap_stats = mel_sub.stats(), cap_sub.stats()
        for stats in (mel_stats, cap_stats):
            assert stats["offered_samples"] == WAV_SAMPLES
            assert stats["consumed_samples"] == WAV_SAMPLES
            assert stats["dropped_blocks"] == 0

        # Content identity on both sides, not just counts.
        assert np.array_equal(np.concatenate(melbank_seen), expected_pcm)
        captured_pcm = capture.drain_pcm()
        assert np.array_equal(captured_pcm, expected_pcm)

        # The vendored melbank pipeline produced frames from hub audio:
        # 120 hop-size chunks entered _audio_sample_callback; all but at most
        # the resampler's priming frames were analyzed (subscribed callbacks
        # fire only for accepted frames).
        assert melbank_source.frames_ingested == 120
        assert len(accepted_frames) >= 110
        assert any(
            float(np.max(bank)) > 0 for bank in melbank_source.melbanks.melbanks
        )

        # The capture consumer produced the production AudioFrame stream:
        # one frame per hub block, monotonic timestamps, energy present.
        assert len(frames) == -(-WAV_SAMPLES // BLOCK_SIZE)  # ceil = 173
        assert capture._dropped_frames == 0
        timestamps = [f.timestamp_ms for f in frames]
        assert timestamps == sorted(timestamps)
        assert max(f.rms_total for f in frames) > 0.1

    _run(main())


# ── Drop accounting: a slow consumer's losses are visible, not silent ────────

def test_slow_consumer_drop_accounting():
    hub = AudioIngestHub(SAMPLE_RATE)
    fast = hub.subscribe("fast", max_blocks=1000)
    slow = hub.subscribe("slow", max_blocks=8)

    n_blocks = 100
    for i in range(n_blocks):
        hub.push(np.full(BLOCK_SIZE, float(i), dtype=np.float32))
        fast.drain()  # the healthy consumer keeps up; the slow one never reads

    assert fast.stats()["dropped_blocks"] == 0
    assert fast.stats()["consumed_samples"] == n_blocks * BLOCK_SIZE

    slow_stats = slow.stats()
    assert slow_stats["offered_blocks"] == n_blocks
    assert slow_stats["dropped_blocks"] == n_blocks - 8
    assert slow_stats["dropped_samples"] == (n_blocks - 8) * BLOCK_SIZE
    assert slow_stats["queued_blocks"] == 8

    # Drop-oldest: what survives is the freshest audio.
    survivors = slow.drain()
    assert [int(block[0]) for _ts, block in survivors] == list(range(92, 100))

    # Sample conservation after final drain: offered == consumed + dropped.
    slow_stats = slow.stats()
    assert (
        slow_stats["offered_samples"]
        == slow_stats["consumed_samples"] + slow_stats["dropped_samples"]
    )

    # The hub-level stats() surface exposes every consumer's drops.
    assert hub.stats()["consumers"]["slow"]["dropped_blocks"] == n_blocks - 8


# ── SpotFX ring-buffer consumer through its adapter ──────────────────────────

def test_ring_buffer_adapter(tmp_path):
    from api.audio_ingest_adapters import RingBufferFeed
    from api.pcm_ring_buffer import PCMRingBuffer

    wav_path = tmp_path / "tone.wav"
    expected_pcm = _write_test_wav(wav_path)

    hub = AudioIngestHub(SAMPLE_RATE)
    ring = PCMRingBuffer()  # never .start()ed — the hub is its stream now
    feed = RingBufferFeed(hub.subscribe("ring"), ring)

    WavFileSource(hub, str(wav_path), BLOCK_SIZE).run()
    assert feed.pump() == WAV_SAMPLES

    assert not ring.is_running()  # no device stream was ever opened
    assert ring.stats()["samples"] == WAV_SAMPLES
    held = np.concatenate([chunk for _ts, chunk in ring._chunks])
    assert np.array_equal(held, expected_pcm)

    # snapshot_since() is deliberately NOT asserted here: it maps sample
    # positions from wall-clock arrival stamps, and a burst pump compresses
    # every stamp into microseconds, collapsing its time-window math. A live
    # pump arrives paced and keeps those stamps meaningful; content identity
    # (above) is the property the hub owns.


# ── The live source exists but cannot open hardware without the flag ─────────

def test_live_device_source_refuses_without_flag():
    hub = AudioIngestHub(SAMPLE_RATE)
    source = LiveDeviceSource(hub)
    with pytest.raises(RuntimeError, match="allow_device"):
        source.open()
    assert not source.is_open()
    source.close()  # no-op on a never-opened source


def test_wav_source_rejects_rate_mismatch(tmp_path):
    path = tmp_path / "wrong_rate.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(np.zeros(100, dtype=np.int16).tobytes())
    with pytest.raises(ValueError, match="does not resample"):
        WavFileSource(AudioIngestHub(SAMPLE_RATE), str(path)).run()


# ── Offline guarantee ────────────────────────────────────────────────────────

def test_fx_lazy_sounddevice_never_dereferenced():
    """The whole hub + melbank path ran without fx touching PortAudio:
    HubMelbankSource bypasses every device-enumerating base member, so the
    Stage 1 lazy proxy is still unloaded. (SpotFX's own api modules import
    sounddevice at module scope — that import initializes no stream and is
    outside fx; the adapters never call .start() on their consumers.)"""
    from fx.compat_sounddevice import _LazySounddevice

    assert _LazySounddevice._module is None
