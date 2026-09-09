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
    assert shape["duration_ms"] == 2000


def test_npz_shape_fallback_none_when_nothing_captured():
    from spectra.services import testbed_audio
    assert testbed_audio.load_npz_shape("spotify:track:neverseen") is None


def test_a_failure_mid_copy_leaves_no_partial_wav_and_no_registry_entry(monkeypatch):
    """A crash or kill halfway through the WAV copy must not leave a
    truncated .wav at wav_copy_path() — scripts/testbed_precompute.py only
    checks that the path exists before feeding it to an engine."""
    import shutil
    from spectra import config as scfg
    from spectra.services import testbed_audio
    _seed_source_wav(scfg)
    source = scfg.AUDIO_SHAPES_DIR / "Artist - Song.wav"
    real_copyfile = shutil.copyfile

    def _dies_halfway(src, dst, *a, **kw):
        data = source.read_bytes()
        with open(dst, "wb") as fh:
            fh.write(data[: len(data) // 2])
        raise OSError("disk full")
    monkeypatch.setattr(shutil, "copyfile", _dies_halfway)

    with pytest.raises(OSError):
        testbed_audio.pin(URI)
    assert not testbed_audio.wav_copy_path(URI).exists()
    assert list(scfg.TESTBED_AUDIO_DIR.glob("*.tmp")) == []
    assert testbed_audio.is_pinned(URI) is False
    assert testbed_audio.status(URI)["pinned"] is False

    monkeypatch.setattr(shutil, "copyfile", real_copyfile)
    result = testbed_audio.pin(URI)
    assert result["status"] == "pinned"
    assert testbed_audio.wav_copy_path(URI).read_bytes() == source.read_bytes()
    assert list(scfg.TESTBED_AUDIO_DIR.glob("*.tmp")) == []


def test_concurrent_pins_of_two_songs_both_land_in_the_registry():
    """pin() runs off the event loop (spectra/api/testbed.py), so two
    presses can overlap; the registry's read-modify-write must not lose
    one of them."""
    import threading
    from spectra import config as scfg
    from spectra.services import testbed_audio
    other = "spotify:track:testbedaudio2"
    _seed_source_wav(scfg)
    (scfg.AUDIO_SHAPES_DIR / "Other - Song.json").write_text(
        json.dumps({"spotify_uri": other}), encoding="utf-8")
    sf.write(str(scfg.AUDIO_SHAPES_DIR / "Other - Song.wav"),
             np.zeros(8000, dtype=np.float32), 8000)

    barrier = threading.Barrier(2)
    results = {}

    def _pin(uri):
        barrier.wait()
        results[uri] = testbed_audio.pin(uri)

    threads = [threading.Thread(target=_pin, args=(u,)) for u in (URI, other)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert {r["status"] for r in results.values()} == {"pinned"}
    assert set(testbed_audio.list_pinned()) == {URI, other}


def test_a_malformed_registry_reads_as_empty_and_a_pin_still_lands():
    """pin() does a read-modify-write of pinned_audio.json AFTER the WAV
    copy has already landed, so a file that parses to something other than
    an object used to raise there — leaving a copied WAV nothing records
    as pinned."""
    from spectra import config as scfg
    from spectra.services import testbed_audio
    _seed_source_wav(scfg)
    scfg.TESTBED_PINNED_FILE.parent.mkdir(parents=True, exist_ok=True)
    scfg.TESTBED_PINNED_FILE.write_text(json.dumps(["not", "a", "registry"]),
                                        encoding="utf-8")

    assert testbed_audio.list_pinned() == {}
    assert testbed_audio.is_pinned(URI) is False
    assert testbed_audio.status(URI)["pinned"] is False

    assert testbed_audio.pin(URI)["status"] == "pinned"
    assert testbed_audio.is_pinned(URI) is True
    assert testbed_audio.status(URI)["pinned"] is True


def _seed_npz(scfg, stem, first_ms):
    """production's own `.npz` sidecar shape (services/audio_analyzer.py's
    save format) — the song-relative stamps a capture actually recorded."""
    np.savez(
        scfg.AUDIO_SHAPES_DIR / f"{stem}.npz",
        timestamps_ms=np.array([first_ms, first_ms + 500, first_ms + 1000]),
        rms_total=np.array([0.1, 0.2, 0.3]),
    )


def test_capture_offset_is_the_song_time_of_the_wavs_first_sample():
    """A capture starts MID-SONG, so a pinned WAV's sample 0 is not
    song-time 0. Drawing the waveform lane from the left edge without this
    puts a real transient earlier than the mark that names it, by the
    capture lag."""
    from spectra import config as scfg
    from spectra.services import testbed_audio
    stem = _seed_source_wav(scfg)
    _seed_npz(scfg, stem, 8123)

    assert testbed_audio.capture_offset_ms(URI) == 8123


def test_capture_offset_is_None_when_it_cannot_be_established():
    """UNKNOWN is its own answer — a caller must say so rather than assume
    0 and imply an alignment nothing measured."""
    from spectra import config as scfg
    from spectra.services import testbed_audio
    _seed_source_wav(scfg)          # a WAV, but no .npz beside it
    assert testbed_audio.capture_offset_ms(URI) is None
    assert testbed_audio.capture_offset_ms("spotify:track:nosuchsong") is None


def test_capture_offset_never_reads_the_unreliable_librosa_offset():
    """AGENTS.md records LibrosaAnalysis.librosa_offset_ms as noise
    (outliers into tens of thousands of seconds). A stored analysis
    claiming a wild offset must not move this answer."""
    from spectra import config as scfg
    from spectra.services import testbed_audio
    stem = _seed_source_wav(scfg)
    _seed_npz(scfg, stem, 4000)
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.librosa.json").write_text(
        json.dumps({"spotify_uri": URI, "librosa_offset_ms": 75_308_324,
                    "sections": [], "beats": []}), encoding="utf-8")

    assert testbed_audio.capture_offset_ms(URI) == 4000


def test_the_waveform_route_carries_the_offset_beside_the_peaks():
    """Resolved at READ time, so a pin taken before this existed carries it
    too — nothing has to be re-pinned."""
    from spectra import config as scfg
    from spectra.services import testbed_audio
    stem = _seed_source_wav(scfg)
    assert testbed_audio.pin(URI)["status"] == "pinned"
    _seed_npz(scfg, stem, 6500)

    peaks = testbed_audio.load_peaks(URI)
    assert peaks is not None and peaks["duration_ms"] > 0
    assert "capture_offset_ms" not in peaks      # not baked into the pin
    assert testbed_audio.capture_offset_ms(URI) == 6500
