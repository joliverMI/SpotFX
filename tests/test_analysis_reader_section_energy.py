"""analysis_reader.section_energy_at's capture-offset shift (2026-09-23,
data/transition-alignment-plan/report.md §2.1's "related, smaller
consequence"): a section's own start_ms/end_ms sit in the CAPTURED-WAV's
frame, but a caller such as bridge.intensity() passes a song-relative
now_ms — this shifts the comparison by testbed_audio.capture_offset_ms so
both sides share one frame, the same fix midsong_generator.candidate_moments
applies to a generated cue's own placement."""
from __future__ import annotations

import json
import os

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import analysis_reader
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True)
    analysis_reader._shape_index = {}
    analysis_reader._index_built = False
    analysis_reader._capture_offset_cache.clear()


URI = "spotify:track:sectionenergy1"
STEM = "Artist - Song"


def _seed(scfg) -> None:
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.json").write_text(
        json.dumps({"spotify_uri": URI}), encoding="utf-8")
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.librosa.json").write_text(json.dumps({
        "spotify_uri": URI,
        "sections": [
            {"start_ms": 0, "end_ms": 2000, "energy_rms": 0.1},
            {"start_ms": 2000, "end_ms": 5000, "energy_rms": 0.9},
        ],
    }), encoding="utf-8")


def _seed_npz_offset(scfg, offset_ms: int) -> None:
    import numpy as np
    np.savez(scfg.AUDIO_SHAPES_DIR / f"{STEM}.npz",
              timestamps_ms=np.array([offset_ms, offset_ms + 100]),
              rms_total=np.array([0.1, 0.2]))


def test_no_offset_reads_sections_exactly_as_before():
    from spectra import config as scfg
    from spectra.services import analysis_reader
    _seed(scfg)
    assert analysis_reader.section_energy_at(URI, 500) == pytest.approx(0.1)
    assert analysis_reader.section_energy_at(URI, 2500) == pytest.approx(0.9)


def test_nonzero_offset_shifts_which_section_is_matched():
    """A song-relative now_ms of 2500 falls in the SECOND section's raw
    bounds (2000-5000), but once the sections are shifted 3000ms later
    (into song time), now_ms=2500 actually falls in the FIRST section's
    shifted bounds (3000-5000 is second; 0-2000 raw -> 3000-5000 shifted —
    wait, use a now_ms inside the first section's shifted window)."""
    from spectra import config as scfg
    from spectra.services import analysis_reader
    _seed(scfg)
    _seed_npz_offset(scfg, 3000)
    # Shifted sections: [3000, 5000) energy 0.1, [5000, 8000) energy 0.9.
    # now_ms=4000 sits in the FIRST section's shifted window — it would
    # have matched the (unshifted) SECOND section's raw [2000,5000) window
    # had the offset not been applied.
    assert analysis_reader.section_energy_at(URI, 4000) == pytest.approx(0.1)
    assert analysis_reader.section_energy_at(URI, 6000) == pytest.approx(0.9)


def test_offset_is_cached_per_uri_not_reread_every_call(monkeypatch):
    from spectra import config as scfg
    from spectra.services import analysis_reader, testbed_audio
    _seed(scfg)
    _seed_npz_offset(scfg, 1500)

    calls = {"n": 0}
    real = testbed_audio.capture_offset_ms_or_zero

    def _counting(uri):
        calls["n"] += 1
        return real(uri)
    monkeypatch.setattr(testbed_audio, "capture_offset_ms_or_zero", _counting)

    for _ in range(5):
        analysis_reader.section_energy_at(URI, 1000)
    assert calls["n"] == 1, (
        "the offset is read from the npz sidecar once per URI and cached — "
        "section_energy_at is on the hot per-tick path (bridge.intensity())"
        " and must not re-read a file on every call")


def test_missing_npz_treats_offset_as_zero_and_still_answers():
    from spectra import config as scfg
    from spectra.services import analysis_reader
    _seed(scfg)
    assert analysis_reader.section_energy_at(URI, 500) == pytest.approx(0.1)


def test_no_sections_returns_none_regardless_of_offset():
    from spectra.services import analysis_reader
    assert analysis_reader.section_energy_at("spotify:track:unknown", 500) is None


def test_a_live_recapture_with_a_new_offset_is_picked_up_without_a_restart():
    """_capture_offset_for used to cache the offset per URI forever (a
    plain dict keyed only on the URI) — a live recapture that rewrites the
    .npz sidecar with a different measured offset would keep reading the
    OLD offset for the rest of the process life. It now keys the cache
    entry on the .npz's own (mtime_ns, size) signature, so a recapture
    (a new mtime) invalidates the stale entry on its very next read."""
    from spectra import config as scfg
    from spectra.services import analysis_reader
    _seed(scfg)
    _seed_npz_offset(scfg, 1000)
    npz_path = scfg.AUDIO_SHAPES_DIR / f"{STEM}.npz"

    # Shifted sections at offset=1000: [1000,3000) energy 0.1, [3000,6000)
    # energy 0.9. Prime the cache at this offset.
    assert analysis_reader.section_energy_at(URI, 1500) == pytest.approx(0.1)
    assert analysis_reader.section_energy_at(URI, 4000) == pytest.approx(0.9)

    # Recapture: same song, a different measured capture offset. Force a
    # distinct mtime signature even if both writes landed within the same
    # filesystem-clock tick, so this test can't pass by timing luck.
    _seed_npz_offset(scfg, 4000)
    st = npz_path.stat()
    os.utime(npz_path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    # Shifted sections at the NEW offset=4000: [4000,6000) energy 0.1,
    # [6000,9000) energy 0.9 — 5000 fell in the OLD offset's [3000,6000)
    # window (energy 0.9), so this only passes if the cache actually
    # noticed the recapture rather than replaying the stale offset.
    assert analysis_reader.section_energy_at(URI, 5000) == pytest.approx(0.1)
    assert analysis_reader.section_energy_at(URI, 7000) == pytest.approx(0.9)
