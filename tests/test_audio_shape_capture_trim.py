"""Capture-trim fix (services/audio_shape_service.py): a song used to be
cut off at the BEGINNING (pre-roll from the ring buffer only ran for
force-recapture, silently dropping the head of every ordinary capture) and
at the END (a tail-wait that needed more than its own cap got skipped
ENTIRELY rather than clamped, so the wait-for-the-tail-to-arrive comment's
own stated purpose — "stopping immediately is what cut the end off
captures" — was defeated whenever the true wait exceeded 3s).

The head fix is NARROW, and the two halves of that are both proven here: a
genuine TRACK CHANGE splices the ring buffer (the reported defect), a
MID-SONG start does not (the ring buffer between `song_start` and now is
the pause, not the song).

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


URI = "spotify:track:capturetrim1"


def _track(progress_ms=8000, duration_ms=200_000):
    now = time.monotonic()
    return SpotifyTrackInfo(
        spotify_uri=URI, title="T", artist="A",
        duration_ms=duration_ms, progress_ms=progress_ms, is_playing=True,
        fetched_at=now,
    )


def _fake_ring(monkeypatch, pcm, synthesized):
    """Fake the ring buffer / frame synthesis / capture stream / recorder at
    the seam, and report whether the ring buffer was ever asked."""
    import api.audio_capture as capture_mod
    import api.pcm_ring_buffer as ring_mod
    import services.audio_shape_service as svc_mod

    asked: list = []

    def fake_snapshot(want_monotonic):
        asked.append(want_monotonic)
        return pcm, time.monotonic()

    monkeypatch.setattr(ring_mod.pcm_ring_buffer, "snapshot_since_with_start", fake_snapshot)
    monkeypatch.setattr(capture_mod, "synthesize_frames_from_pcm",
                        lambda _pcm, _start: synthesized)
    monkeypatch.setattr(svc_mod, "AudioCaptureStream", _FakeCaptureStream)
    monkeypatch.setattr(svc_mod, "AudioShapeRecorder", _FakeRecorder)
    return asked


def _at_track_boundary(service, track):
    """What on_track_change leaves behind for a real URI flip into `track`:
    the acoustic boundary and the URI it belongs to."""
    service._pending_boundary_monotonic = time.monotonic() - track.progress_ms / 1000.0
    service._pending_boundary_uri = track.spotify_uri


def test_ordinary_track_change_pre_rolls_from_the_ring_buffer(monkeypatch):
    """FIXED: pre-roll used to be force_recapture-only ("to preserve legacy
    behavior"), silently dropping every ordinary capture's head. It must
    now run for force_recapture=False too on a genuine track change,
    whenever the ring buffer has something to offer."""
    synthesized = [object(), object(), object()]
    _fake_ring(monkeypatch, np.ones(4000, dtype=np.float32), synthesized)

    service = AudioShapeService()
    track = _track()
    _at_track_boundary(service, track)

    started = _run(service._start(track, force_recapture=False))

    assert started is True
    assert service._recorder.ingested == synthesized, (
        "pre-roll frames were never ingested on an ordinary (non-force) "
        "track change -- the head-truncation bug"
    )
    assert service._capture._pcm_chunks, "pre-roll PCM never seeded the WAV buffer"


def test_a_mid_song_start_never_splices_the_ring_buffer(monkeypatch):
    """THE OTHER HALF. `_start` also runs from on_track_change's tail for
    any playing song with no complete shape -- e.g. a resume after a pause
    whose too-short partial was discarded. There `song_start` is
    `now - progress` and the ring buffer between it and now holds the
    PAUSE, not the song, so splicing would stamp silence as this song's own
    head, feed it to librosa AND the WAV, and inflate the captured_ms the
    too-short guard reads."""
    synthesized = [object(), object(), object()]
    asked = _fake_ring(monkeypatch, np.ones(4000, dtype=np.float32), synthesized)

    service = AudioShapeService()
    # No pending boundary: nothing told us a URI flipped into this track.
    assert service._pending_boundary_uri is None

    started = _run(service._start(_track(progress_ms=300_000), force_recapture=False))

    assert started is True
    assert service._recorder.ingested == [], (
        "a mid-song start spliced ring-buffer audio it cannot know is this "
        "song's own -- silence stamped as the song's head"
    )
    assert service._capture._pcm_chunks == []
    assert service._capture.pcm_start_ms is None
    assert asked == [], "the ring buffer was snapshotted for a mid-song start"


def test_a_boundary_for_a_DIFFERENT_track_does_not_authorise_a_splice(monkeypatch):
    """The boundary is per-URI. One left behind by another song's
    transition says nothing about this one's contiguity."""
    _fake_ring(monkeypatch, np.ones(4000, dtype=np.float32), [object()])

    service = AudioShapeService()
    service._pending_boundary_monotonic = time.monotonic() - 8.0
    service._pending_boundary_uri = "spotify:track:someoneelse"

    started = _run(service._start(_track(), force_recapture=False))

    assert started is True
    assert service._recorder.ingested == []
    assert service._capture._pcm_chunks == []


def test_force_recapture_still_pre_rolls_without_a_boundary(monkeypatch):
    """Unchanged from before this whole fix: a force-recapture is a
    deliberate, operator-driven re-take and has always spliced."""
    synthesized = [object(), object()]
    _fake_ring(monkeypatch, np.ones(4000, dtype=np.float32), synthesized)

    service = AudioShapeService()
    assert service._pending_boundary_uri is None

    started = _run(service._start(_track(), force_recapture=True))

    assert started is True
    assert service._recorder.ingested == synthesized
    assert service._capture._pcm_chunks


def test_capture_with_no_ring_buffer_pcm_still_starts_cleanly(monkeypatch):
    """The 'nothing to pre-roll' path (empty ring buffer) must still
    degrade to an ordinary capture start, not an error."""
    _fake_ring(monkeypatch, np.array([], dtype=np.float32), [])

    service = AudioShapeService()
    track = _track()
    _at_track_boundary(service, track)
    started = _run(service._start(track, force_recapture=False))

    assert started is True
    assert service._recorder.ingested == []
    assert service._capture._pcm_chunks == []


# ── the tail-wait AT ITS REAL CALL SITE ─────────────────────────────────────
#
# The arithmetic tests above prove the shared helper. These drive the two
# places the capture actually waits, because that is where the reported
# defect lived: a needed wait longer than the cap was skipped ENTIRELY
# (zero sleep, tail never waited for) rather than clamped.

class _RecordedSleeps:
    def __init__(self, monkeypatch):
        import services.audio_shape_service as svc_mod
        self.slept: list = []

        async def fake_sleep(seconds):
            self.slept.append(seconds)

        monkeypatch.setattr(svc_mod.asyncio, "sleep", fake_sleep)


def _stoppable_service(monkeypatch):
    """A service positioned as if a capture were running, with finalize
    stubbed out — enough to reach _stop_and_save's tail-wait for real."""
    import services.audio_shape_service as svc_mod

    service = AudioShapeService()
    service._capture = _FakeCaptureStream(time.monotonic())
    service._capture.stop = lambda: None
    service._recorder = _FakeRecorder()
    service._recording_uri = URI

    async def no_finalize(*a, **kw):
        return None

    monkeypatch.setattr(svc_mod.AudioShapeService, "_finalize_capture", no_finalize)
    return service


def test_stop_and_save_tail_wait_clamps_instead_of_skipping(monkeypatch):
    """THE END-TRUNCATION BUG, at its own call site. A boundary far enough
    ahead that the required wait exceeds the cap used to fall outside the
    `0 < wait_s <= 3.0` window and be skipped completely — the capture
    stopped immediately and lost its tail. It must now sleep the cap."""
    sleeps = _RecordedSleeps(monkeypatch)
    service = _stoppable_service(monkeypatch)

    # Needed wait = boundary + latency + 0.3 - now, made comfortably > cap.
    boundary = time.monotonic() + 10.0
    _run(service._stop_and_save(boundary))

    assert sleeps.slept == [AudioShapeService._TAIL_WAIT_CAP_S], (
        "a tail-wait longer than the cap was skipped entirely instead of "
        f"clamped -- slept {sleeps.slept}"
    )


def test_stop_and_save_tail_wait_sleeps_the_exact_wait_when_under_the_cap(monkeypatch):
    """The ordinary case is unchanged: a short wait is slept in full."""
    from config import settings as _cfg

    sleeps = _RecordedSleeps(monkeypatch)
    service = _stoppable_service(monkeypatch)

    boundary = time.monotonic() + 0.5 - _cfg.audio_latency_ms / 1000.0 - 0.3
    _run(service._stop_and_save(boundary))

    assert len(sleeps.slept) == 1
    assert 0.0 < sleeps.slept[0] <= AudioShapeService._TAIL_WAIT_CAP_S
    assert sleeps.slept[0] == pytest.approx(0.5, abs=0.1)


def test_stop_and_save_does_not_wait_when_the_boundary_audio_already_arrived(monkeypatch):
    """A deadline already in the past is not a wait at all."""
    sleeps = _RecordedSleeps(monkeypatch)
    service = _stoppable_service(monkeypatch)

    _run(service._stop_and_save(time.monotonic() - 60.0))

    assert sleeps.slept == []


def test_on_track_change_boundary_wait_clamps_instead_of_skipping(monkeypatch):
    """The SECOND call site (on_track_change's wait for the previous
    track's tail to arrive) carried the identical all-or-nothing shape."""
    import services.audio_shape_service as svc_mod

    from models.state import state as app_state

    # Never let this test reach the real PCM ring buffer's watchdog (which
    # would open an audio device) -- the repo's rule is no live access.
    monkeypatch.setattr(app_state, "audio_analysis_enabled", False)

    sleeps = _RecordedSleeps(monkeypatch)
    service = _stoppable_service(monkeypatch)
    service._capture_started_at = time.monotonic() - 60.0

    # Stop the flow right after the wait so nothing downstream runs.
    class _Stop(Exception):
        pass

    async def boom(*a, **kw):
        raise _Stop()

    monkeypatch.setattr(svc_mod.AudioShapeService, "_stop_and_save", boom)

    # A track whose reported progress puts the arrival deadline far ahead.
    now = time.monotonic()
    nxt = SpotifyTrackInfo(
        spotify_uri="spotify:track:next", title="N", artist="A",
        duration_ms=200_000, progress_ms=0, is_playing=True,
        fetched_at=now + 10.0,
    )

    with pytest.raises(_Stop):
        _run(service.on_track_change(nxt))

    assert sleeps.slept == [AudioShapeService._TAIL_WAIT_CAP_S], (
        "the boundary-wait longer than the cap was skipped entirely "
        f"instead of clamped -- slept {sleeps.slept}"
    )
