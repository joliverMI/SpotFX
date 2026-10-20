"""The capture-service side of Absorb Music (services/audio_shape_service.py
+ services/capture_watch.py), driven through the REAL service:

- the per-song force set forces exactly the songs in it, once each, and
  leaves the global recapture counter alone;
- a vouched head-start lets the first song after a non-capturing one keep its
  pre-roll (the boundary on_track_change computes only exists after a
  capture, so without the vouch a warm-up song would buy nothing);
- the mid-song detectors condemn on the very frame that dooms a capture and
  agree with what finalize would decide;
- every capture ends with exactly one CaptureOutcome;
- END TO END, the report's acceptance: a gap injected at 0:30 condemns the
  capture and the runner has already asked Spotify for the next song before
  the next frame is ingested.

No audio device, no ring buffer, no Spotify: the capture stream is an async
iterator of frames, the ring buffer is faked at its seam."""
from __future__ import annotations

import asyncio
import json
import time

import numpy as np
import pytest

from api.audio_capture import AudioFrame
from models.state import SpotifyTrackInfo
from services.capture_watch import (
    CaptureWatch, governor_moved, read_governor,
)

URI = "spotify:track:hooksong01"


def _go(coro):
    return asyncio.run(coro)


# ── capture_watch, pure ─────────────────────────────────────────────────────

def _watch(duration=200_000):
    return CaptureWatch(URI, duration, max_gap_ms=200, min_capture_pct=0.80)


def test_gap_fires_on_the_frame_after_it_and_only_once():
    w = _watch()
    assert w.on_frame(23, 0, 0) is None
    assert w.on_frame(46, 23, 0) is None
    hit = w.on_frame(30_500, 30_000, 0)
    assert hit is not None and hit.reason == "gap" and "500 ms gap" in hit.detail
    assert w.on_frame(31_000, 30_500, 0) is None          # one condemnation per capture


def test_a_gap_at_exactly_the_limit_is_not_a_gap():
    w = _watch()
    assert w.on_frame(23, 0, 0) is None
    assert w.on_frame(223, 23, 0) is None                  # finalize uses `>` too


def test_frames_past_the_song_end_are_not_judged():
    w = _watch(duration=10_000)
    assert w.on_frame(23, 0, 0) is None
    assert w.on_frame(12_000, 9_000, 0) is None            # trimmed at the boundary


def test_bad_timestamps_on_the_first_frame():
    w = _watch(duration=100_000)
    hit = w.on_frame(150_000, None, None)
    assert hit.reason == "bad_timestamps"


def test_coverage_that_can_no_longer_reach_the_bar():
    w = _watch(duration=100_000)
    hit = w.on_frame(30_000, None, None)                   # 72% at most
    assert hit.reason == "coverage"
    ok = _watch(duration=100_000)
    assert ok.on_frame(15_000, None, None) is None         # 87% still reachable


def test_coverage_judges_the_recorders_first_sample_not_the_live_one():
    w = _watch(duration=100_000)
    # pre-roll put the head at 0: the first LIVE frame at 30 s is fine
    assert w.on_frame(30_000, 29_977, 0) is None


def test_governor_reading_and_movement(tmp_path):
    p = tmp_path / "gov.json"
    assert read_governor(str(p)) is None
    p.write_text(json.dumps({"seq": 24, "dropped_total_ms": 14243, "x": 1}))
    a = read_governor(str(p))
    assert a == {"seq": 24, "dropped_total_ms": 14243}
    p.write_text("{not json")
    assert read_governor(str(p)) is None
    assert governor_moved(a, None) is None
    assert governor_moved(a, dict(a)) is None
    moved = governor_moved(a, {"seq": 25, "dropped_total_ms": 14843})
    assert "24→25" in moved and "600 ms" in moved


# ── the per-song force set and the vouched head-start ───────────────────────

def _track(uri=URI, progress_ms=4000):
    return SpotifyTrackInfo(spotify_uri=uri, title="T", artist="A", duration_ms=200_000,
                            progress_ms=progress_ms, is_playing=True,
                            fetched_at=time.monotonic(), device_name="Serenity")


@pytest.fixture
def service(monkeypatch):
    import services.audio_shape_service as svc
    from models.state import state as app_state

    import api.pcm_ring_buffer as ring_mod
    # on_track_change's ring-buffer watchdog would open a real audio stream
    monkeypatch.setattr(ring_mod.pcm_ring_buffer, "ensure_alive", lambda: None)
    s = svc.AudioShapeService()
    starts = []

    async def fake_start(track, force_recapture=False, head_vouched=False):
        starts.append((track.spotify_uri, force_recapture, head_vouched))
        s._recording_uri = track.spotify_uri
        return True

    monkeypatch.setattr(s, "_start", fake_start)
    monkeypatch.setattr(app_state, "audio_analysis_enabled", True)
    monkeypatch.setattr(app_state, "on_target_device", True)
    monkeypatch.setattr(app_state, "recapture_active", False)
    monkeypatch.setattr(app_state, "recapture_remaining", 0)

    async def no_offset(track):
        return None

    from services import auto_offset_service
    monkeypatch.setattr(auto_offset_service.auto_offset_service, "on_track_change", no_offset)
    s.starts = starts
    return s


def test_a_uri_in_the_force_set_is_force_recaptured_once(service, monkeypatch):
    import services.audio_shape_service as svc
    from models.state import state as app_state
    monkeypatch.setattr(svc, "load_audio_shape_meta", lambda u: type(
        "M", (), {"capture_complete": True, "librosa_version": 3})())
    service.force_uris.add(URI)
    _go(service.on_track_change(_track()))
    assert service.starts == [(URI, True, False)]
    assert URI not in service.force_uris
    assert app_state.recapture_remaining == 0 and app_state.recapture_active is False


def test_a_complete_shape_not_in_the_force_set_is_left_alone(service, monkeypatch):
    import services.audio_shape_service as svc
    meta = type("M", (), {"capture_complete": True, "librosa_version": 3,
                          "npz_file": "x.npz", "title": "T"})()
    monkeypatch.setattr(svc, "load_audio_shape_meta", lambda u: meta)
    import services.librosa_service as ls
    monkeypatch.setattr(ls, "wav_path", lambda m: type("P", (), {"exists": lambda self: True})())
    monkeypatch.setattr(ls, "get_analysis_by_uri", lambda u: object())
    service.force_uris.add("spotify:track:other")
    _go(service.on_track_change(_track()))
    assert service.starts == []
    assert service.force_uris == {"spotify:track:other"}


def test_a_vouched_fresh_song_is_started_vouched_and_leaves_the_set(service, monkeypatch):
    import services.audio_shape_service as svc
    monkeypatch.setattr(svc, "load_audio_shape_meta", lambda u: None)
    service.preroll_uris.add(URI)
    _go(service.on_track_change(_track()))
    assert service.starts == [(URI, False, True)]
    assert URI not in service.preroll_uris


def test_an_unvouched_fresh_song_starts_as_before(service, monkeypatch):
    import services.audio_shape_service as svc
    monkeypatch.setattr(svc, "load_audio_shape_meta", lambda u: None)
    _go(service.on_track_change(_track()))
    assert service.starts == [(URI, False, False)]


def test_a_vouch_allows_the_pre_roll_splice_with_no_track_boundary(monkeypatch):
    """The other half of the vouch, at _start itself: no boundary was ever
    computed (nothing was being captured before), yet the ring buffer's
    audio is spliced, because the caller started this song at position 0."""
    import api.audio_capture as capture_mod
    import api.pcm_ring_buffer as ring_mod
    import services.audio_shape_service as svc

    class Stream:
        def __init__(self, song_start):
            self._pcm_chunks, self.pcm_start_ms = [], None
            self._song_start = song_start

        def set_pcm_start_ms(self, ms):
            self.pcm_start_ms = ms

        def start(self):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class Rec:
        def __init__(self, *a, **k):
            self.ingested, self._timestamps = [], []

        def ingest(self, f):
            self.ingested.append(f)

    asked = []
    monkeypatch.setattr(ring_mod.pcm_ring_buffer, "snapshot_since_with_start",
                        lambda want: (asked.append(want) or np.ones(4000, dtype=np.float32),
                                      time.monotonic()))
    frames = [object(), object()]
    monkeypatch.setattr(capture_mod, "synthesize_frames_from_pcm", lambda pcm, start: frames)
    monkeypatch.setattr(svc, "AudioCaptureStream", Stream)
    monkeypatch.setattr(svc, "AudioShapeRecorder", Rec)

    async def run(vouched):
        s = svc.AudioShapeService()
        assert s._pending_boundary_uri is None
        await s._start(_track(), force_recapture=False, head_vouched=vouched)
        await asyncio.sleep(0)
        return s

    s = _go(run(True))
    assert s._recorder.ingested == frames and asked
    asked.clear()
    s = _go(run(False))
    assert s._recorder.ingested == [] and asked == []


# ── the ingest loop's detectors, through the real service ───────────────────

class _FrameStream:
    """An AudioCaptureStream stand-in: yields the frames, one per loop turn."""

    def __init__(self, timestamps, song_start=0.0):
        self.timestamps = list(timestamps)
        self._song_start = song_start
        self._pcm_chunks = []
        self.stopped = False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for t in self.timestamps:
            await asyncio.sleep(0)
            yield AudioFrame(t, 0.2, 0.1, 0.1, 0.1)

    def stop(self):
        self.stopped = True


def _armed(svc_mod, timestamps, duration=200_000):
    from services.audio_analyzer import AudioShapeRecorder
    s = svc_mod.AudioShapeService()
    s._recording_uri = URI
    s._recorder = AudioShapeRecorder(URI, "T", "A", duration)
    s._capture = _FrameStream(timestamps)
    s._watch = CaptureWatch(URI, duration, 200, 0.80)
    return s


def test_the_ingest_loop_condemns_on_the_gap_frame():
    import services.audio_shape_service as svc
    ts = list(range(0, 30_000, 23)) + list(range(30_500, 40_000, 23))
    gap_index = ts.index(30_500)
    s = _armed(svc, ts)
    seen = []
    s.condemn_listeners.append(lambda c: seen.append((c, len(s._recorder._timestamps))))
    _go(s._ingest_loop())
    assert len(seen) == 1
    c, ingested_before = seen[0]
    assert c.reason == "gap" and c.uri == URI
    assert ingested_before == gap_index          # judged before the doomed frame is kept
    # the capture itself keeps running — the detector only announces
    assert len(s._recorder._timestamps) == len(ts)


def test_a_clean_capture_is_never_condemned():
    import services.audio_shape_service as svc
    s = _armed(svc, range(0, 60_000, 23))
    seen = []
    s.condemn_listeners.append(seen.append)
    _go(s._ingest_loop())
    assert seen == []


def test_a_late_start_is_condemned_on_its_first_frame():
    import services.audio_shape_service as svc
    s = _armed(svc, range(100_000, 110_000, 23), duration=120_000)
    seen = []
    s.condemn_listeners.append(seen.append)
    _go(s._ingest_loop())
    assert [c.reason for c in seen] == ["coverage"]


def test_a_failing_listener_never_breaks_the_capture():
    import services.audio_shape_service as svc
    ts = list(range(0, 1_000, 23)) + [5_000, 5_023]
    s = _armed(svc, ts)

    def boom(c):
        raise RuntimeError("listener bug")

    s.condemn_listeners.append(boom)
    _go(s._ingest_loop())
    assert len(s._recorder._timestamps) == len(ts)


# ── one CaptureOutcome per capture ──────────────────────────────────────────

class _Drain:
    def __init__(self, pcm=None):
        self._pcm = pcm
        self._song_start = 0.0

    def drain_pcm(self):
        return self._pcm


@pytest.fixture
def finalize_world(tmp_path, monkeypatch):
    import config
    import services.audio_analyzer as aa
    import services.audio_shape_service as svc
    import services.librosa_service as ls
    from services import anchor_detector, capture_alignment, recapture_playlist
    from models.state import state as app_state

    d = tmp_path / "audio_shapes"
    d.mkdir()
    for mod in (config, aa, svc, ls):
        monkeypatch.setattr(mod, "AUDIO_SHAPES_DIR", d)
    monkeypatch.setattr(ls, "manage_wav_retention", lambda: None)
    monkeypatch.setattr(ls, "get_analysis", lambda meta: None)
    monkeypatch.setattr(capture_alignment, "invalidate_analyzed_cache", lambda uri: None)
    monkeypatch.setattr(app_state, "auto_generate_enabled", False)
    monkeypatch.setattr(config.settings, "anchor_enabled", False)
    monkeypatch.setattr(recapture_playlist, "remove_track", lambda u: True)
    monkeypatch.setattr(aa, "clear_needs_recapture", lambda u: True)
    monkeypatch.setattr(anchor_detector, "detect_anchor_candidates", lambda *a, **k: [])
    state = {"librosa": object(),
             "realign": {"status": "applied", "shift_ms": 300, "r": 0.9, "triggers": 2}}

    async def fake_analyze(meta):
        return state["librosa"]

    monkeypatch.setattr(ls, "analyze_async", fake_analyze)
    monkeypatch.setattr(capture_alignment, "realign_after_recapture",
                        lambda *a, **k: state["realign"])

    def recorder(ts):
        rec = aa.AudioShapeRecorder(URI, "Title", "Artist", duration_ms=10_000)
        for t in ts:
            rec.ingest(aa.AudioFrame(t, 0.2, 0.1, 0.1, 0.1))
        return rec

    def finalize(ts, force=False, pcm=np.full(4410, 0.01, dtype=np.float32)):
        s = svc.AudioShapeService()
        outcomes = []
        s.outcome_listeners.append(outcomes.append)

        async def drive():
            await s._finalize_capture(_Drain(pcm), recorder(ts), URI, force, None,
                                      capture_started_at=123.0)
            others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            await asyncio.gather(*others)

        asyncio.run(drive())
        return outcomes

    w = type("W", (), {})()
    w.finalize, w.state, w.dir = finalize, state, d
    return w


FULL = range(0, 10_000, 50)


def test_outcome_too_short(finalize_world):
    [o] = finalize_world.finalize(range(0, 3_000, 50))
    assert (o.status, o.reason, o.capture_started_at) == ("failed", "too_short", 123.0)


def test_outcome_gap(finalize_world):
    [o] = finalize_world.finalize(list(range(0, 5_000, 50)) + list(range(6_000, 10_000, 50)))
    assert (o.status, o.reason) == ("failed", "gap")


def test_outcome_first_capture_waits_for_librosa(finalize_world):
    [o] = finalize_world.finalize(FULL)
    assert (o.status, o.reason, o.forced) == ("ok", "", False)


def test_outcome_first_capture_whose_librosa_fails(finalize_world):
    finalize_world.state["librosa"] = None
    [o] = finalize_world.finalize(FULL)
    assert (o.status, o.reason) == ("failed", "wav_librosa_failed")


def test_outcome_first_capture_with_no_pcm(finalize_world):
    [o] = finalize_world.finalize(FULL, pcm=None)
    assert o.status == "ok"


def test_outcome_forced_commit_carries_the_realign(finalize_world):
    [o] = finalize_world.finalize(FULL, force=True)
    assert (o.status, o.forced) == ("ok", True)
    assert o.realign["triggers"] == 2


def test_outcome_forced_rollback(finalize_world):
    finalize_world.state["librosa"] = None
    [o] = finalize_world.finalize(FULL, force=True)
    assert (o.status, o.reason, o.forced) == ("failed", "wav_librosa_failed", True)


def test_outcome_cancelled_by_stop_capture():
    import services.audio_shape_service as svc
    s = svc.AudioShapeService()
    s._recording_uri = URI
    s._capture_started_at = 77.0
    outcomes = []
    s.outcome_listeners.append(outcomes.append)
    _go(s.stop_capture())
    [o] = outcomes
    assert (o.status, o.reason, o.capture_started_at) == ("failed", "cancelled", 77.0)
    _go(s.stop_capture())                     # nothing recording: nothing published
    assert len(outcomes) == 1


# ── END TO END: a gap at 0:30 condemns and skips within one frame ───────────

def test_a_gap_at_thirty_seconds_skips_to_the_next_song_within_one_frame(tmp_path, monkeypatch):
    """The real capture service's ingest loop, the real detectors and the
    real runner, with only Spotify and the shape disk faked."""
    import services.audio_shape_service as svc
    from tests.absorb_world import SOURCE_ID, World, uri

    service = svc.AudioShapeService()
    w = World(tmp_path, monkeypatch, capture=service, warm_up=False)
    a, b, c = uri(1), uri(2), uri(3)
    w.gw.playlists[SOURCE_ID] = [a, b, c]
    asyncio.set_event_loop(asyncio.new_event_loop())
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(w.runner.start())
        assert service.preroll_uris == {a, b, c}

        async def scenario():
            w.playing(a, progress_ms=500)
            await w.poll()
            assert w.run.now_playing.uri == a
            # the capture service starts a's capture (what on_track_change does)
            ts = list(range(0, 30_000, 23)) + list(range(30_600, 60_000, 23))
            from services.audio_analyzer import AudioShapeRecorder
            service._recording_uri = a
            service._capture_started_at = w.clock[0]
            service._recorder = AudioShapeRecorder(a, "T", "A", 200_000)
            service._capture = _FrameStream(ts)
            service._watch = CaptureWatch(a, 200_000, 200, 0.80)
            gap_index = ts.index(30_600)

            plays_at = []
            real_play = w.gw.play

            def spy(device_id, uris):
                plays_at.append(len(service._recorder._timestamps))
                return real_play(device_id, uris)

            w.gw.play = spy
            await service._ingest_loop()
            await w.runner.settle()
            return gap_index, plays_at

        gap_index, plays_at = loop.run_until_complete(scenario())
    finally:
        loop.close()
        asyncio.set_event_loop(None)
    assert plays_at, "the runner never asked Spotify for the next song"
    # condemned on the gap frame; the skip landed before the frame after it
    assert plays_at[0] <= gap_index + 1
    assert w.last_play[:2] == [b, a]          # B now, A again right after it
    assert w.run.failed[-1].reason == "gap"
