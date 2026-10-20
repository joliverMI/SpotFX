"""After a capture, the song leaves the recapture playlist and its
needs_recapture flag is cleared ONLY when the capture really succeeded — and
a forced recapture can commit with anchoring off
(services/audio_shape_service.py, report data/absorb-music-plan §7.1 / §14
items 2-4).

Three defects, all on the finalize path, all driven here through the real
`AudioShapeService._finalize_capture` (a real recorder saving a real npz,
a real WAV write, the real atomic-save backup/commit/rollback) against a temp
shapes directory:

- the playlist removal and the flag clear ran inside `_save_wav_and_analyze`
  whatever librosa returned, so a failed analysis — or a forced recapture
  that then ROLLED BACK — still took the song off the work playlist;
- that removal (Spotify HTTP, which pages his playlists) ran on the event
  loop;
- a forced recapture required >=1 anchor candidate even when the anchor pass
  is switched off (`settings.anchor_enabled`) and so never runs, which made
  every forced recapture roll back.

Stubbed: librosa's analysis (its outcome is the variable), the anchor
detector, the realign pass, Spotify (the playlist removal is a spy), and the
needs_recapture writer (a spy). No audio device, no network."""
from __future__ import annotations

import asyncio
import json
import threading
import time

import numpy as np
import pytest

URI = "spotify:track:song"
STEM = "Artist - Title"


class _FakeCapture:
    def __init__(self, pcm=None):
        self._pcm = pcm if pcm is not None else np.full(4410, 0.01, dtype=np.float32)

    def drain_pcm(self):
        return self._pcm


@pytest.fixture
def world(tmp_path, monkeypatch):
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
    monkeypatch.setattr(capture_alignment, "realign_after_recapture", lambda *a, **k: {})
    monkeypatch.setattr(capture_alignment, "invalidate_analyzed_cache", lambda uri: None)
    monkeypatch.setattr(app_state, "auto_generate_enabled", False)
    monkeypatch.setattr(config.settings, "anchor_enabled", False)

    w = type("World", (), {})()
    w.dir = d
    w.librosa_result = object()          # set to None for a failed analysis
    w.anchors = []
    w.removed, w.remove_threads, w.cleared = [], [], []

    async def fake_analyze(meta):
        return w.librosa_result

    def fake_remove(uri):
        w.removed.append(uri)
        w.remove_threads.append(threading.get_ident())
        return True

    def fake_clear(uri):
        w.cleared.append(uri)
        return True

    monkeypatch.setattr(ls, "analyze_async", fake_analyze)
    monkeypatch.setattr(recapture_playlist, "remove_track", fake_remove)
    monkeypatch.setattr(aa, "clear_needs_recapture", fake_clear)
    monkeypatch.setattr(anchor_detector, "detect_anchor_candidates",
                        lambda *a, **k: list(w.anchors))

    def recorder():
        rec = aa.AudioShapeRecorder(URI, "Title", "Artist", duration_ms=10_000)
        for t in range(0, 10_000, 50):
            rec.ingest(aa.AudioFrame(t, 0.2, 0.1, 0.1, 0.1))
        return rec

    def old_shape():
        """The intact original a forced recapture backs up."""
        (d / f"{STEM}.npz").write_bytes(b"OLD-NPZ")
        (d / f"{STEM}.json").write_text(json.dumps({"spotify_uri": URI, "needs_recapture": True}))
        (d / f"{STEM}.wav").write_bytes(b"OLD-WAV")
        (d / f"{STEM}.librosa.json").write_text("{}")

    def finalize(force, capture=None):
        service = svc.AudioShapeService()

        async def drive():
            await service._finalize_capture(capture or _FakeCapture(), recorder(), URI, force, None)
            # A first-time capture's WAV + librosa runs as a detached task.
            others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            await asyncio.gather(*others)

        asyncio.run(drive())
        return service

    w.recorder, w.old_shape, w.finalize = recorder, old_shape, finalize
    w.svc, w.settings = svc, config.settings
    return w


def _anchor():
    from services.anchor_detector import AnchorCandidate
    return AnchorCandidate(timestamp_ms=1000, band="rms_total", rise_magnitude=2.0,
                           uniqueness=0.5, template=[0.1, 0.2])


# ── first-time captures ─────────────────────────────────────────────────────

def test_first_capture_whose_librosa_fails_stays_on_the_recapture_playlist(world):
    """THE DEFECT: the removal and the flag clear used to run anyway."""
    world.librosa_result = None
    world.finalize(force=False)
    assert (world.dir / f"{STEM}.wav").exists()   # the WAV did land
    assert world.removed == []
    assert world.cleared == []


def test_first_capture_that_fully_succeeds_leaves_the_playlist(world):
    world.finalize(force=False)
    assert world.removed == [URI]
    assert world.cleared == [URI]


def test_first_capture_whose_wav_write_fails_stays_on_the_playlist(world):
    world.finalize(force=False, capture=_FakeCapture(np.zeros((2, 2, 2), dtype=np.float32)))
    assert world.removed == []
    assert world.cleared == []


def test_save_wav_and_analyze_itself_never_does_the_bookkeeping(world):
    """The contract moved: the caller decides "really succeeded"."""
    rec = world.recorder()
    ok = asyncio.run(world.svc._save_wav_and_analyze(
        rec.meta, np.full(4410, 0.01, dtype=np.float32), 44100))
    assert ok is True
    assert world.removed == [] and world.cleared == []


# ── forced recaptures ───────────────────────────────────────────────────────

def test_forced_recapture_commits_with_anchoring_off(world):
    """THE DEFECT: with anchor_enabled off the anchor pass never runs, the
    candidate list is empty, and `>=1 anchor` rolled every one back."""
    world.old_shape()
    service = world.finalize(force=True)
    assert service._last_capture_status == "ok", service._last_capture_reason
    assert list(world.dir.glob("*.bak")) == []
    new_npz = np.load(world.dir / f"{STEM}.npz")       # the NEW shape, a real npz
    assert len(new_npz["timestamps_ms"]) == 200
    assert json.loads((world.dir / f"{STEM}.json").read_text())["capture_complete"] is True
    assert world.removed == [URI]
    assert world.cleared == [URI]


def test_forced_recapture_whose_librosa_fails_rolls_back_and_stays_on_the_playlist(world):
    """The removal used to run inside _save_wav_and_analyze, BEFORE the
    commit decision — so a rollback still dropped the song from the playlist."""
    world.old_shape()
    world.librosa_result = None
    service = world.finalize(force=True)
    assert (service._last_capture_status, service._last_capture_reason) == ("failed", "wav_librosa_failed")
    assert (world.dir / f"{STEM}.npz").read_bytes() == b"OLD-NPZ"
    assert (world.dir / f"{STEM}.wav").read_bytes() == b"OLD-WAV"
    assert json.loads((world.dir / f"{STEM}.json").read_text())["needs_recapture"] is True
    assert world.removed == []
    assert world.cleared == []


def test_forced_recapture_with_anchoring_on_still_needs_an_anchor(world, monkeypatch):
    """Unchanged when anchoring is on: no candidate, no commit."""
    monkeypatch.setattr(world.settings, "anchor_enabled", True)
    world.old_shape()
    world.anchors = []
    service = world.finalize(force=True)
    assert (service._last_capture_status, service._last_capture_reason) == ("failed", "anchor_zero")
    assert (world.dir / f"{STEM}.npz").read_bytes() == b"OLD-NPZ"
    assert world.removed == [] and world.cleared == []


def test_forced_recapture_with_anchoring_on_commits_with_an_anchor(world, monkeypatch):
    monkeypatch.setattr(world.settings, "anchor_enabled", True)
    world.old_shape()
    world.anchors = [_anchor()]
    service = world.finalize(force=True)
    assert service._last_capture_status == "ok"
    sidecar = json.loads((world.dir / f"{STEM}.json").read_text())
    assert [a["timestamp_ms"] for a in sidecar["anchor_candidates"]] == [1000]
    assert world.removed == [URI]


# ── the playlist removal is off the event loop ──────────────────────────────

def test_the_playlist_removal_does_not_block_the_event_loop(world, monkeypatch):
    from services import recapture_playlist

    def slow_remove(uri):
        world.remove_threads.append(threading.get_ident())
        time.sleep(0.4)            # a page-through-every-playlist Spotify round trip
        world.removed.append(uri)
        return True

    monkeypatch.setattr(recapture_playlist, "remove_track", slow_remove)

    async def drive():
        loop_thread = threading.get_ident()
        gaps: list[float] = []
        done = asyncio.Event()

        async def ticker():
            last = time.monotonic()
            while not done.is_set():
                await asyncio.sleep(0.01)
                now = time.monotonic()
                gaps.append(now - last)
                last = now

        tick = asyncio.create_task(ticker())
        await world.svc._after_successful_capture(URI)
        done.set()
        await tick
        return loop_thread, max(gaps)

    loop_thread, worst_gap = asyncio.run(drive())
    assert world.removed == [URI]
    assert world.remove_threads and world.remove_threads[0] != loop_thread
    assert worst_gap < 0.2, f"event loop stalled {worst_gap:.3f}s behind the removal"
