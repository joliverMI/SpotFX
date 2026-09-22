"""spectra/services/analysis_reader.tempo_bpm_for_uri — the music-analysis
test bed's per-lane tolerance default reads this to size a beat/downbeat
lane's tolerance below half a beat (data/music-analysis-octave-scout/
report.md, "Work that should ship" #2)."""
from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import analysis_reader
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True)
    analysis_reader._shape_index = {}
    analysis_reader._index_built = False


URI = "spotify:track:tempotest1"


def _seed(scfg, tempo_bpm):
    stem = "Artist - Song"
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.json").write_text(
        json.dumps({"spotify_uri": URI}), encoding="utf-8")
    doc = {"spotify_uri": URI, "sections": [], "beats": []}
    if tempo_bpm is not None:
        doc["tempo_bpm"] = tempo_bpm
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.librosa.json").write_text(
        json.dumps(doc), encoding="utf-8")


def test_reads_tempo_bpm_off_the_librosa_analysis():
    from spectra import config as scfg
    from spectra.services import analysis_reader
    _seed(scfg, 117.45)
    assert analysis_reader.tempo_bpm_for_uri(URI) == 117.45


def test_none_without_any_analysis():
    from spectra.services import analysis_reader
    assert analysis_reader.tempo_bpm_for_uri("spotify:track:unknown") is None


def test_none_when_the_field_is_missing():
    from spectra import config as scfg
    from spectra.services import analysis_reader
    _seed(scfg, None)
    assert analysis_reader.tempo_bpm_for_uri(URI) is None


def test_none_when_the_field_is_zero_or_negative():
    from spectra import config as scfg
    from spectra.services import analysis_reader
    _seed(scfg, -5.0)
    assert analysis_reader.tempo_bpm_for_uri(URI) is None
