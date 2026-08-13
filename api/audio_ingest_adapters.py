"""Hub adapters for SpotFX's audio consumers — SPECTRA Stage 2 (report §3).

Bridges fx.audio_ingest.AudioIngestHub subscriptions onto the production
consumer classes WITHOUT those classes opening their own device streams:

  RingBufferFeed     → api.pcm_ring_buffer.PCMRingBuffer (the always-on 30 s
                       pre-roll ring; today opened unconditionally at boot)
  CaptureStreamFeed  → api.audio_capture.AudioCaptureStream — which is BOTH
                       remaining consumers: audio_shape_service's per-song
                       shape capture and auto_offset_service's xcorr sweep
                       each construct an AudioCaptureStream and iterate its
                       AudioFrames. One adapter covers both seams.

Each adapter feeds the consumer's existing sounddevice `_callback` — the
exact production math (band RMS, timestamping, queue put) runs unchanged;
only the audio's origin moves from a private InputStream to the shared hub.
The adapted consumer must NEVER have .start() called (that would open the
competing device stream the hub exists to eliminate).

NOT wired into main.py: production capture paths are untouched until a later
stage. These adapters prove themselves in the offline test bed
(tests/test_audio_ingest.py) only. Consumers pump explicitly via pump();
live pumping (thread or task) is a wiring-stage decision.
"""
from __future__ import annotations

from fx.audio_ingest import Subscription


class _HubCallbackTime:
    """Stands in for the PortAudio time_info struct. inputBufferAdcTime=0
    makes AudioCaptureStream._callback take its documented fallback branch
    (adc_delay=0, timestamp from time.monotonic())."""

    inputBufferAdcTime = 0.0
    currentTime = 0.0


class RingBufferFeed:
    """Pumps a hub subscription into a PCMRingBuffer via its _callback.
    Do not call ring.start(); ensure_alive() would reopen a device stream, so
    the wiring stage must also retire that watchdog for a hub-fed ring."""

    def __init__(self, subscription: Subscription, ring):
        self.subscription = subscription
        self.ring = ring

    def pump(self) -> int:
        """Deliver everything queued; returns samples delivered."""
        samples = 0
        for _timestamp, block in self.subscription.drain():
            self.ring._callback(block.reshape(-1, 1), len(block), None, None)
            samples += len(block)
        return samples


class CaptureStreamFeed:
    """Pumps a hub subscription into an AudioCaptureStream via its _callback
    (the shape-capture AND xcorr consumer seam). The capture must not be
    start()ed; stop() remains the caller's to invoke for the end-of-stream
    sentinel. _callback schedules its queue put onto the capture's event
    loop, so pump() must run while that loop is alive."""

    def __init__(self, subscription: Subscription, capture):
        self.subscription = subscription
        self.capture = capture

    def pump(self) -> int:
        """Deliver everything queued; returns samples delivered."""
        samples = 0
        for _timestamp, block in self.subscription.drain():
            self.capture._callback(
                block.reshape(-1, 1), len(block), _HubCallbackTime(), None
            )
            samples += len(block)
        return samples
