"""spectra/services/testbed_engines.py — the engine registry: librosa
derived live from .librosa.json, beat_this read from the offline
precompute cache. Never re-runs an engine in the request path (report
Part 3's own "What it does NOT do")."""
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


URI = "spotify:track:testbedengine1"


def _seed_librosa_json(scfg):
    stem = "Artist - Song"
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.json").write_text(
        json.dumps({"spotify_uri": URI}), encoding="utf-8")
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.librosa.json").write_text(json.dumps({
        "spotify_uri": URI,
        "sections": [
            {"start_ms": 0, "end_ms": 20000, "label": "intro", "energy_rms": 0.2},
            {"start_ms": 20000, "end_ms": 60000, "label": "drop", "energy_rms": 0.9},
        ],
        "beats": [
            {"ms": 500, "is_downbeat": True, "rms_total": 0.5},
            {"ms": 1000, "is_downbeat": False, "rms_total": 0.4},
        ],
    }), encoding="utf-8")


def test_librosa_marks_skip_opening_boundary_and_split_beat_vs_downbeat():
    from spectra import config as scfg
    from spectra.services import testbed_engines
    _seed_librosa_json(scfg)

    marks = testbed_engines.marks_for(testbed_engines.ENGINE_LIBROSA, URI)
    kinds = sorted((m.kind, m.time_ms) for m in marks)
    assert ("section_boundary", 20000.0) in kinds
    assert ("section_boundary", 0.0) not in kinds  # opening boundary excluded
    assert ("downbeat", 500.0) in kinds
    assert ("beat", 1000.0) in kinds


def test_librosa_marks_none_when_no_analysis_at_all():
    from spectra.services import testbed_engines
    assert testbed_engines.marks_for(testbed_engines.ENGINE_LIBROSA,
                                     "spotify:track:unknown") is None


def test_beat_this_marks_read_from_precompute_cache():
    from spectra.services import testbed_cache, testbed_engines
    testbed_cache.save(testbed_engines.ENGINE_BEAT_THIS, URI, "v1", [
        {"time_ms": 100.0, "kind": "beat", "label": None, "score": None},
        {"time_ms": 100.0, "kind": "downbeat", "label": None, "score": None},
    ])
    marks = testbed_engines.marks_for(testbed_engines.ENGINE_BEAT_THIS, URI)
    assert {(m.kind, m.time_ms) for m in marks} == {("beat", 100.0), ("downbeat", 100.0)}


def test_beat_this_marks_none_when_not_precomputed():
    from spectra.services import testbed_engines
    assert testbed_engines.marks_for(testbed_engines.ENGINE_BEAT_THIS, URI) is None


def test_availability_reports_both_engines_honestly():
    from spectra import config as scfg
    from spectra.services import testbed_engines
    _seed_librosa_json(scfg)
    avail = testbed_engines.availability_for(URI)
    assert avail["librosa"]["available"] is True
    assert avail["librosa"]["mark_count"] == 3  # 1 boundary + 2 beats
    assert avail["beat_this"]["available"] is False
    assert avail["beat_this"]["mark_count"] == 0
