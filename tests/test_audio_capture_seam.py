"""Pre-roll/live seam fix (services/audio_shape_service.py, recommendation 1
of data/dream-on-capture-loop/report.md).

THE BUG: when a capture starts at a real track boundary, `_start()` splices
in synthesized pre-roll frames from the always-on PCM ring buffer, then
opens a BRAND NEW `AudioCaptureStream`. Any audio that played between the
end of that pre-roll snapshot and the new stream's own first delivered
callback was silently lost — a hole measured at 160-370ms in production,
comfortably over the 200ms gap-discard limit, and present on essentially
every track-boundary capture library-wide (roughly half the discards on a
typical day, per the report).

THE FIX: `AudioShapeService._seal_preroll_seam` runs once, on the very
first frame the new live stream delivers, and re-snapshots the (still
continuously running) ring buffer from exactly where the pre-roll splice
left off through exactly where the live stream's own first sample begins,
synthesizing the hole as ordinary frames the same way pre-roll itself is
synthesized.

No live audio device, no live PCM ring buffer — the ring buffer's
`snapshot_since_with_start` is faked at the seam, matching this repo's own
"no live access from tests, ever" rule. `synthesize_frames_from_pcm` is the
REAL function, so the frame timestamps here are the real math, not a stub."""
from __future__ import annotations

import time

import numpy as np
import pytest

from config import settings
from api.audio_capture import AudioFrame
from services.audio_shape_service import AudioShapeService


class _FakeCaptureForSeam:
    """Only what _seal_preroll_seam touches: _song_start and _pcm_chunks."""

    def __init__(self, song_start_monotonic: float):
        self._song_start = song_start_monotonic
        self._pcm_chunks: list = []


class _FakeRecorderForSeam:
    def __init__(self):
        self.ingested: list = []

    def ingest(self, frame):
        self.ingested.append(frame)


def test_seam_backfill_collapses_the_hole_to_about_one_chunk(monkeypatch):
    """THE BUG, reproduced at the seam: without this fix, nothing at all
    fills the gap between the pre-roll's own end and the live stream's
    first sample, so the gap there is exactly however long the new
    InputStream took to start (160-370ms in production, well over the
    200ms discard limit). With the fix, the gap collapses to at most a
    couple of chunk-widths (~23ms here) — a >10x reduction, and nowhere
    near the discard limit."""
    import api.pcm_ring_buffer as ring_mod

    sr = settings.audio_sample_rate
    chunk_size = settings.audio_chunk_size
    chunk_dur_ms = (chunk_size / sr) * 1000.0
    latency_ms = settings.audio_latency_ms

    song_start = time.monotonic() - 20.0

    # Where the pre-roll splice (already tested elsewhere) left off.
    preroll_end_monotonic = song_start + latency_ms / 1000.0 + 5.0
    preroll_end_song_ms = (preroll_end_monotonic - song_start) * 1000.0 - latency_ms

    # A real-world-sized hole (report's own range: 160-370ms).
    GAP_S = 0.29
    live_start_monotonic = preroll_end_monotonic + GAP_S
    live_frame = AudioFrame(
        timestamp_ms=int((live_start_monotonic - song_start) * 1000 - latency_ms),
        rms_total=0.1, rms_low=0.1, rms_mid=0.1, rms_high=0.1,
    )

    # The always-on ring buffer kept recording through the whole hole and
    # then some — the seam-close trims it to exactly what's needed.
    seam_pcm = np.zeros(int((GAP_S + 0.1) * sr), dtype=np.float32)

    def fake_snapshot(monotonic_ts):
        assert monotonic_ts == pytest.approx(preroll_end_monotonic, abs=1e-6)
        return seam_pcm, preroll_end_monotonic

    monkeypatch.setattr(ring_mod.pcm_ring_buffer, "snapshot_since_with_start", fake_snapshot)

    service = AudioShapeService()
    service._preroll_end_monotonic = preroll_end_monotonic
    service._preroll_pcm_chunk_count = 1
    service._capture = _FakeCaptureForSeam(song_start)
    service._capture._pcm_chunks = [np.zeros(10, dtype=np.float32)]  # stand-in pre-roll chunk
    service._recording_uri = "spotify:track:seamtest"
    service._recorder = _FakeRecorderForSeam()

    service._seal_preroll_seam(live_frame)

    seam_frames = service._recorder.ingested
    assert seam_frames, "the seam produced no frames -- the hole was never backfilled"

    timeline = [preroll_end_song_ms] + [f.timestamp_ms for f in seam_frames] + [live_frame.timestamp_ms]
    gaps = [b - a for a, b in zip(timeline, timeline[1:])]
    max_gap = max(gaps)

    # The whole point: collapse a 160-370ms hole down to about a chunk's
    # width, not zero -- chunk-boundary quantization can leave up to
    # roughly one chunk uncovered on either side of the backfill. Generous
    # 2-chunk bound so this isn't fragile to floor-division rounding, while
    # still being a >10x tightening of the real defect.
    assert max_gap <= 2 * chunk_dur_ms + 1, (
        f"gap of {max_gap:.1f}ms survived the seam close (chunk={chunk_dur_ms:.1f}ms) "
        "-- the pre-roll/live hole was not actually closed"
    )
    # And, the property that actually matters: nowhere near the discard limit.
    assert max_gap < settings.audio_max_gap_ms / 4

    # The seam's raw PCM lands in the WAV buffer right after the pre-roll
    # chunk (index 1) -- never at index 0, which would put it ahead of the
    # pre-roll itself.
    assert len(service._capture._pcm_chunks) == 2
    expected_samples = int((live_start_monotonic - preroll_end_monotonic) * sr)
    assert len(service._capture._pcm_chunks[1]) == expected_samples

    # One-shot: consumed regardless of outcome, so a second frame on the
    # same stream can never re-trigger it.
    assert service._preroll_end_monotonic is None


def test_seam_is_a_no_op_when_there_was_no_preroll(monkeypatch):
    """A mid-song start (no track boundary) never pre-rolls, so there is no
    seam to close -- _seal_preroll_seam must be an inert no-op, never a
    ring-buffer call or a fabricated frame."""
    import api.pcm_ring_buffer as ring_mod

    def fail_snapshot(monotonic_ts):
        raise AssertionError("ring buffer consulted with no pre-roll to seam-close")

    monkeypatch.setattr(ring_mod.pcm_ring_buffer, "snapshot_since_with_start", fail_snapshot)

    service = AudioShapeService()
    assert service._preroll_end_monotonic is None
    service._capture = _FakeCaptureForSeam(time.monotonic() - 5.0)
    service._recorder = _FakeRecorderForSeam()

    live_frame = AudioFrame(timestamp_ms=0, rms_total=0.0, rms_low=0.0, rms_mid=0.0, rms_high=0.0)
    service._seal_preroll_seam(live_frame)

    assert service._recorder.ingested == []
    assert service._capture._pcm_chunks == []


def test_seam_skips_cleanly_when_live_frame_arrived_before_the_preroll_end(monkeypatch):
    """A live frame that (somehow) lands at or before the pre-roll's own
    end means there's no hole -- must not go negative or fabricate frames."""
    import api.pcm_ring_buffer as ring_mod

    def fail_snapshot(monotonic_ts):
        raise AssertionError("ring buffer consulted for a non-existent (<=0) gap")

    monkeypatch.setattr(ring_mod.pcm_ring_buffer, "snapshot_since_with_start", fail_snapshot)

    song_start = time.monotonic() - 20.0
    latency_ms = settings.audio_latency_ms
    preroll_end_monotonic = song_start + latency_ms / 1000.0 + 5.0

    service = AudioShapeService()
    service._preroll_end_monotonic = preroll_end_monotonic
    service._capture = _FakeCaptureForSeam(song_start)
    service._recorder = _FakeRecorderForSeam()

    # timestamp_ms corresponding to exactly preroll_end_monotonic itself.
    live_frame = AudioFrame(
        timestamp_ms=int((preroll_end_monotonic - song_start) * 1000 - latency_ms),
        rms_total=0.0, rms_low=0.0, rms_mid=0.0, rms_high=0.0,
    )

    service._seal_preroll_seam(live_frame)

    assert service._recorder.ingested == []
    assert service._preroll_end_monotonic is None
