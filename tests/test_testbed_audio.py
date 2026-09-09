"""spectra/services/testbed_audio.py — pin/unpin retention, independent of
production's WAV cap (data/spotfx-music-analysis-plan/report.md, "Two
decisions" #1)."""
from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import analysis_reader
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path / "spectra")
    monkeypatch.setattr(scfg, "TESTBED_DIR", tmp_path / "spectra" / "testbed")
    monkeypatch.setattr(scfg, "TESTBED_AUDIO_DIR", tmp_path / "spectra" / "testbed" / "audio")
    monkeypatch.setattr(scfg, "TESTBED_PINNED_FILE",
                        tmp_path / "spectra" / "testbed" / "pinned_audio.json")
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True)
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False


URI = "spotify:track:testbedaudio1"


def _seed_source_wav(scfg, seconds=1.0, sample_rate=8000):
    stem = "Artist - Song"
    sidecar = {"spotify_uri": URI}
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.json").write_text(json.dumps(sidecar), encoding="utf-8")
    n = int(seconds * sample_rate)
    tone = 0.5 * np.sin(2 * np.pi * 220 * np.arange(n) / sample_rate).astype(np.float32)
    sf.write(str(scfg.AUDIO_SHAPES_DIR / f"{stem}.wav"), tone, sample_rate)
    return stem


def test_pin_refuses_when_no_source_wav_exists():
    from spectra.services import testbed_audio
    result = testbed_audio.pin("spotify:track:neverseen")
    assert result["status"] == "unknown_song"


def test_pin_copies_wav_and_computes_peaks_independent_of_source():
    from spectra import config as scfg
    from spectra.services import testbed_audio
    _seed_source_wav(scfg)

    result = testbed_audio.pin(URI)
    assert result["status"] == "pinned"
    assert result["peaks_computed"] is True
    assert testbed_audio.is_pinned(URI)
    assert testbed_audio.wav_copy_path(URI).exists()

    peaks = testbed_audio.load_peaks(URI)
    assert peaks is not None
    assert len(peaks["mins"]) > 0
    assert len(peaks["mins"]) == len(peaks["maxs"])
    assert peaks["duration_ms"] > 0

    st = testbed_audio.status(URI)
    assert st["pinned"] is True
    assert st["has_peaks"] is True


def test_unpin_removes_copy_and_peaks_but_never_touches_the_source():
    from spectra import config as scfg
    from spectra.services import testbed_audio
    _seed_source_wav(scfg)
    testbed_audio.pin(URI)

    source_wav = scfg.AUDIO_SHAPES_DIR / "Artist - Song.wav"
    source_bytes_before = source_wav.read_bytes()

    assert testbed_audio.unpin(URI) is True
    assert not testbed_audio.wav_copy_path(URI).exists()
    assert not testbed_audio.peaks_path(URI).exists()
    assert testbed_audio.is_pinned(URI) is False
    # Unpinning a second time is a clean no-op, not an error.
    assert testbed_audio.unpin(URI) is False

    assert source_wav.read_bytes() == source_bytes_before


def test_pin_survives_production_wav_deletion_afterward():
    """The whole point: production's LRU eviction of AUDIO_SHAPES_DIR must
    never reach the test bed's own copy."""
    from spectra import config as scfg
    from spectra.services import testbed_audio
    _seed_source_wav(scfg)
    testbed_audio.pin(URI)

    (scfg.AUDIO_SHAPES_DIR / "Artist - Song.wav").unlink()  # simulate eviction

    assert testbed_audio.wav_copy_path(URI).exists()
    assert testbed_audio.load_peaks(URI) is not None
    st = testbed_audio.status(URI)
    assert st["pinned"] is True
    assert st["has_source_wav"] is False  # honestly reports production lost it


def test_npz_shape_fallback_reads_production_rms_envelope():
    from spectra import config as scfg
    from spectra.services import testbed_audio
    stem = "Artist - Song"
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.json").write_text(
        json.dumps({"spotify_uri": URI}), encoding="utf-8")
    np.savez_compressed(
        scfg.AUDIO_SHAPES_DIR / f"{stem}.npz",
        timestamps_ms=np.array([0, 1000, 2000], dtype=np.int64),
        rms_total=np.array([0.1, 0.5, 0.2], dtype=np.float32),
    )
    shape = testbed_audio.load_npz_shape(URI)
    assert shape["timestamps_ms"] == [0, 1000, 2000]
    assert len(shape["rms_total"]) == 3


def test_npz_shape_fallback_none_when_nothing_captured():
    from spectra.services import testbed_audio
    assert testbed_audio.load_npz_shape("spotify:track:neverseen") is None
