"""Capture-trim fix (services/audio_shape_service.py): a song used to be
cut off at the BEGINNING (pre-roll from the ring buffer only ran for
force-recapture, silently dropping the head of every ordinary capture) and
at the END (a tail-wait that needed more than its own cap got skipped
ENTIRELY rather than clamped, so the wait-for-the-tail-to-arrive comment's
own stated purpose — "stopping immediately is what cut the end off
captures" — was defeated whenever the true wait exceeded 3s).

No live audio device, no live PCM ring buffer, no live Spotify poll — both
fixes are proven at the seam: the pure clamping arithmetic directly, and
_start()'s pre-roll branch with the ring buffer / capture stream / recorder
faked out (this module opens a real sounddevice.InputStream and the repo's
own rule is no live access from tests, ever)."""
from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from models.state import SpotifyTrackInfo
from services.audio_shape_service import AudioShapeService, _capped_wait_s


def _run(coro):
    return asyncio.run(coro)


# ── the shared clamping arithmetic ──────────────────────────────────────────

def test_capped_wait_returns_none_when_nothing_to_wait_for():
    assert _capped_wait_s(0.0, 3.0) is None
    assert _capped_wait_s(-5.0, 3.0) is None


def test_capped_wait_passes_through_when_under_the_cap():
    assert _capped_wait_s(1.2, 3.0) == 1.2


def test_capped_wait_clamps_instead_of_skipping_when_over_the_cap():
    """THE BUG: the old shape (`if 0 < wait_s <= cap: sleep(wait_s)`) would
    have this be an unconditional zero-wait (the tail never waited for at
    all) instead of a 3.0s wait."""
    assert _capped_wait_s(7.5, 3.0) == 3.0
    assert _capped_wait_s(3.0, 3.0) == 3.0  # boundary: exactly the cap still waits


# ── pre-roll on an ordinary (non-force) capture ─────────────────────────────

class _FakeCaptureStream:
    def __init__(self, song_start_monotonic):
        self.song_start = song_start_monotonic
        self._pcm_chunks = []
        self.pcm_start_ms = None
        self.started = False

    def set_pcm_start_ms(self, ms):
        self.pcm_start_ms = ms

    def start(self):
        self.started = True


class _FakeRecorder:
    def __init__(self, *a, **kw):
        self.ingested = []

    def ingest(self, frame):
        self.ingested.append(frame)


def _track(progress_ms=8000, duration_ms=200_000):
    now = time.monotonic()
    return SpotifyTrackInfo(
        spotify_uri="spotify:track:capturetrim1", title="T", artist="A",
        duration_ms=duration_ms, progress_ms=progress_ms, is_playing=True,
        fetched_at=now,
    )


def test_ordinary_capture_pre_rolls_from_the_ring_buffer(monkeypatch):
    """FIXED: pre-roll used to be force_recapture-only ("to preserve legacy
    behavior"), silently dropping every ordinary capture's head. It must
    now run for force_recapture=False too, whenever the ring buffer has
    something to offer."""
    import api.audio_capture as capture_mod
    import api.pcm_ring_buffer as ring_mod
    import services.audio_shape_service as svc_mod

    fake_pcm = np.ones(4000, dtype=np.float32)
    got_monotonic = time.monotonic()

    def fake_snapshot(want_monotonic):
        return fake_pcm, got_monotonic

    synthesized = [object(), object(), object()]

    def fake_synthesize(pcm, start_ms):
        assert pcm is fake_pcm
        return synthesized

    monkeypatch.setattr(ring_mod.pcm_ring_buffer, "snapshot_since_with_start", fake_snapshot)
    monkeypatch.setattr(capture_mod, "synthesize_frames_from_pcm", fake_synthesize)
    monkeypatch.setattr(svc_mod, "AudioCaptureStream", _FakeCaptureStream)
    monkeypatch.setattr(svc_mod, "AudioShapeRecorder", _FakeRecorder)

    service = AudioShapeService()
    track = _track()

    started = _run(service._start(track, force_recapture=False))

    assert started is True
    assert service._recorder.ingested == synthesized, (
        "pre-roll frames were never ingested on an ordinary (non-force) "
        "capture -- the head-truncation bug"
    )
    assert service._capture._pcm_chunks, "pre-roll PCM never seeded the WAV buffer"


def test_capture_with_no_ring_buffer_pcm_still_starts_cleanly(monkeypatch):
    """The 'nothing to pre-roll' path (empty ring buffer) must still
    degrade to an ordinary capture start, not an error."""
    import api.audio_capture as capture_mod
    import api.pcm_ring_buffer as ring_mod
    import services.audio_shape_service as svc_mod

    def fake_snapshot(want_monotonic):
        return np.array([], dtype=np.float32), time.monotonic()

    monkeypatch.setattr(ring_mod.pcm_ring_buffer, "snapshot_since_with_start", fake_snapshot)
    monkeypatch.setattr(capture_mod, "synthesize_frames_from_pcm", lambda *a, **kw: [])
    monkeypatch.setattr(svc_mod, "AudioCaptureStream", _FakeCaptureStream)
    monkeypatch.setattr(svc_mod, "AudioShapeRecorder", _FakeRecorder)

    service = AudioShapeService()
    started = _run(service._start(_track(), force_recapture=False))

    assert started is True
    assert service._recorder.ingested == []
    assert service._capture._pcm_chunks == []
