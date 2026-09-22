"""spectra/services/beat_snap.py — Phase 2 of the music-analysis plan
(the Admiral's 2026-09-22 decision): grid choice (librosa vs beat_this's
half-time phrase grid), that a song's capture offset never leaks into this
module's own same-frame comparison, and the one-beat snap cap."""
from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import analysis_reader
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    monkeypatch.setattr(scfg, "TESTBED_ANALYSIS_DIR", tmp_path / "spectra" / "testbed" / "analysis")
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True)
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False


URI = "spotify:track:beatsnap1"
STEM = "Artist - Song"


def _seed_librosa(scfg, *, tempo_bpm, beats, sections=None):
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.json").write_text(
        json.dumps({"spotify_uri": URI}), encoding="utf-8")
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.librosa.json").write_text(json.dumps({
        "spotify_uri": URI,
        "tempo_bpm": tempo_bpm,
        "sections": sections or [],
        "beats": beats,
    }), encoding="utf-8")


def _seed_beat_this(scfg, marks):
    from spectra.services import testbed_cache, testbed_engines
    d = scfg.TESTBED_ANALYSIS_DIR / testbed_engines.ENGINE_BEAT_THIS
    d.mkdir(parents=True, exist_ok=True)
    testbed_cache.save(testbed_engines.ENGINE_BEAT_THIS, URI, "test-version", marks)


def _downbeats(times):
    """Every entry in `times` becomes a librosa downbeat at 500ms spacing
    starting at the first entry — a helper for building a regular grid."""
    return [{"ms": t, "is_downbeat": True, "rms_total": 0.5} for t in times]


def test_no_analysis_at_all_yields_no_grid():
    from spectra.services import beat_snap
    assert beat_snap.choose_grid(URI) is None
    result = beat_snap.snap(URI, 12_345)
    assert result.timestamp_ms == 12_345
    assert result.grid is None
    assert result.moved_ms is None


def test_librosa_is_the_fallback_with_no_beat_this_cache():
    from spectra import config as scfg
    from spectra.services import beat_snap
    _seed_librosa(scfg, tempo_bpm=120.0, beats=[
        {"ms": 0, "is_downbeat": True}, {"ms": 500, "is_downbeat": False},
        {"ms": 1000, "is_downbeat": True}, {"ms": 1500, "is_downbeat": False},
    ])
    grid = beat_snap.choose_grid(URI)
    assert grid == ("librosa", [0, 1000])


def test_beat_this_wins_when_its_tempo_reads_at_half_librosas():
    """The scout report's Q1 discriminator: beat_this's grid at ~0.5x
    librosa's tempo is a real phrase grid, not noise — Soy Peor's own
    shape."""
    from spectra import config as scfg
    from spectra.services import beat_snap
    _seed_librosa(scfg, tempo_bpm=117.45, beats=[
        {"ms": i * 511, "is_downbeat": (i % 4 == 0)} for i in range(20)
    ])
    # beat_this: 8-librosa-beat phrase, ~4120ms bar, full grid ~1020ms apart
    _seed_beat_this(scfg, [
        {"time_ms": i * 1020, "kind": "downbeat" if i % 4 == 0 else "beat",
         "label": None, "score": None}
        for i in range(10)
    ])
    grid = beat_snap.choose_grid(URI)
    assert grid is not None
    name, downbeats = grid
    assert name == "beat_this"
    assert downbeats == [0, 4080, 8160]


def test_beat_this_does_not_win_at_the_same_octave_as_librosa():
    """Contra/El Apagón's shape: beat_this reads the SAME tempo as
    librosa (ratio ~1.0) — no phrase-grid advantage, so librosa stays the
    grid."""
    from spectra import config as scfg
    from spectra.services import beat_snap
    _seed_librosa(scfg, tempo_bpm=126.0, beats=[
        {"ms": i * 476, "is_downbeat": (i % 4 == 0)} for i in range(20)
    ])
    _seed_beat_this(scfg, [
        {"time_ms": i * 480, "kind": "downbeat" if i % 4 == 0 else "beat",
         "label": None, "score": None}
        for i in range(20)
    ])
    grid = beat_snap.choose_grid(URI)
    assert grid is not None
    assert grid[0] == "librosa"


def test_beat_this_cache_present_but_no_downbeats_falls_back_to_librosa():
    from spectra import config as scfg
    from spectra.services import beat_snap
    _seed_librosa(scfg, tempo_bpm=120.0, beats=[
        {"ms": 0, "is_downbeat": True}, {"ms": 1000, "is_downbeat": True},
    ])
    # half-time tempo but every mark is a plain beat, no downbeat kind
    _seed_beat_this(scfg, [
        {"time_ms": i * 1000, "kind": "beat", "label": None, "score": None}
        for i in range(6)
    ])
    grid = beat_snap.choose_grid(URI)
    assert grid is not None
    assert grid[0] == "librosa"


def test_a_capture_offset_sidecar_never_shifts_the_grid_or_the_snap():
    """Section boundaries and downbeat times are both computed by the same
    librosa pass over the same captured WAV, so they already share one
    frame (the module docstring's ONE FRAME, NO SHIFT) — the WAV-time ->
    song-time shift testbed_audio.capture_offset_ms_or_zero provides for
    spectra/api/testbed.py::_estimate_for's CROSS-frame comparison must
    never leak into this module's own same-frame one. Proven by comparing
    the grid AND a real snap decision with and without a capture-offset
    npz sidecar present: identical either way."""
    from spectra import config as scfg
    from spectra.services import beat_snap, testbed_audio
    import numpy as np

    _seed_librosa(scfg, tempo_bpm=120.0, beats=[
        {"ms": 0, "is_downbeat": True}, {"ms": 1000, "is_downbeat": True},
    ])
    grid_no_offset = beat_snap.choose_grid(URI)
    snap_no_offset = beat_snap.snap(URI, 950)
    assert testbed_audio.capture_offset_ms_or_zero(URI) == 0

    npz_path = scfg.AUDIO_SHAPES_DIR / f"{STEM}.npz"
    np.savez(npz_path, timestamps_ms=np.array([3692, 3800, 3900]),
             rms_total=np.array([0.1, 0.2, 0.1]))
    assert testbed_audio.capture_offset_ms_or_zero(URI) == 3692

    grid_with_offset = beat_snap.choose_grid(URI)
    snap_with_offset = beat_snap.snap(URI, 950)

    assert grid_no_offset == grid_with_offset == ("librosa", [0, 1000])
    assert snap_no_offset == snap_with_offset
    assert snap_with_offset.timestamp_ms == 1000
    assert snap_with_offset.moved_ms == 50


def test_snap_lands_on_the_nearest_downbeat_within_one_beat():
    from spectra import config as scfg
    from spectra.services import beat_snap
    _seed_librosa(scfg, tempo_bpm=120.0, beats=[  # 500ms/beat
        {"ms": 0, "is_downbeat": True}, {"ms": 2000, "is_downbeat": True},
        {"ms": 4000, "is_downbeat": True},
    ])
    result = beat_snap.snap(URI, 2150)  # 150ms from the 2000 downbeat
    assert result.grid == "librosa"
    assert result.timestamp_ms == 2000
    assert result.moved_ms == -150


def test_snap_cap_leaves_a_far_moment_unsnapped():
    """A nearest downbeat farther than one beat length (60000/tempo_bpm)
    away is NOT snapped — the section's own time survives untouched."""
    from spectra import config as scfg
    from spectra.services import beat_snap
    _seed_librosa(scfg, tempo_bpm=120.0, beats=[  # 500ms/beat
        {"ms": 0, "is_downbeat": True}, {"ms": 2000, "is_downbeat": True},
    ])
    far_ms = 2000 + 600  # 600ms > one 500ms beat away from the nearest downbeat
    result = beat_snap.snap(URI, far_ms)
    assert result.timestamp_ms == far_ms
    assert result.grid is None
    assert result.moved_ms is None


def test_snap_cap_boundary_is_inclusive_of_exactly_one_beat():
    from spectra import config as scfg
    from spectra.services import beat_snap
    _seed_librosa(scfg, tempo_bpm=120.0, beats=[  # 500ms/beat
        {"ms": 0, "is_downbeat": True}, {"ms": 2000, "is_downbeat": True},
    ])
    result = beat_snap.snap(URI, 2000 + 500)  # exactly one beat away
    assert result.grid == "librosa"
    assert result.timestamp_ms == 2000
    assert result.moved_ms == -500
