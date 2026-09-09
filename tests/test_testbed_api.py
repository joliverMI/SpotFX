"""Route-shape proofs for spectra/api/testbed.py over FastAPI's TestClient —
his marks, waveform, engine compare, audio pin, and the push-to-real gate
end to end through the real app wiring (not just the service layer)."""
from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import analysis_reader
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    monkeypatch.setattr(scfg, "TESTBED_DIR", tmp_path / "spectra" / "testbed")
    monkeypatch.setattr(scfg, "TESTBED_AUDIO_DIR", tmp_path / "spectra" / "testbed" / "audio")
    monkeypatch.setattr(scfg, "TESTBED_ANALYSIS_DIR", tmp_path / "spectra" / "testbed" / "analysis")
    monkeypatch.setattr(scfg, "TESTBED_PINNED_FILE", tmp_path / "spectra" / "testbed" / "pinned_audio.json")
    monkeypatch.setattr(scfg, "TESTBED_PROMOTIONS_FILE", tmp_path / "spectra" / "testbed" / "promotions.json")
    (tmp_path / "profiles").mkdir()
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True)
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False


URI = "spotify:track:testbedapi1"


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _write_trigger(uri, timestamp_ms, kind, **extra):
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    trigger_store.upsert(uri, SpectraTrigger(timestamp_ms=timestamp_ms,
                                             action={"kind": kind, **extra}))


def _seed_librosa(scfg):
    stem = "Artist - Song"
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.json").write_text(
        json.dumps({"spotify_uri": URI}), encoding="utf-8")
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.librosa.json").write_text(json.dumps({
        "spotify_uri": URI,
        "sections": [
            {"start_ms": 0, "end_ms": 10000, "label": "intro", "energy_rms": 0.2},
            {"start_ms": 10000, "end_ms": 30000, "label": "drop", "energy_rms": 0.9},
        ],
        "beats": [{"ms": 10050, "is_downbeat": True, "rms_total": 0.5}],
    }), encoding="utf-8")


def test_songs_and_marks_roundtrip():
    from spectra import config as scfg
    _write_trigger(URI, 10000, "fire_scene")
    _write_trigger(URI, 5000, "fire_response", event_class="flare")

    client = _client()
    songs = client.get("/api/testbed/songs").json()
    assert any(s["uri"] == URI for s in songs)
    row = next(s for s in songs if s["uri"] == URI)
    assert row["n_transitions"] == 1
    assert row["n_flares"] == 1

    marks = client.get(f"/api/testbed/marks?uri={URI}").json()
    assert [m["timestamp_ms"] for m in marks["transitions"]] == [10000]
    assert [m["timestamp_ms"] for m in marks["flares"]] == [5000]


def test_waveform_reports_none_when_nothing_captured():
    client = _client()
    resp = client.get(f"/api/testbed/waveform?uri={URI}").json()
    assert resp["source"] == "none"


def test_compare_reports_unavailable_when_no_analysis():
    client = _client()
    resp = client.get(
        f"/api/testbed/compare?uri={URI}&engine=librosa&mark_kind=section_boundary",
    ).json()
    assert resp["available"] is False
    assert resp["metrics"] is None


def test_compare_computes_metrics_against_librosa_baseline():
    from spectra import config as scfg
    _seed_librosa(scfg)
    _write_trigger(URI, 10000, "fire_scene")  # matches librosa's 10000ms boundary exactly

    client = _client()
    resp = client.get(
        f"/api/testbed/compare?uri={URI}&engine=librosa&mark_kind=section_boundary"
        "&reference=transitions&tolerance_ms=500",
    ).json()
    assert resp["available"] is True
    assert resp["metrics"]["n_matched"] == 1
    assert resp["metrics"]["f1"] == 1.0


def test_unknown_engine_is_a_404():
    client = _client()
    resp = client.get(f"/api/testbed/compare?uri={URI}&engine=nope&mark_kind=beat")
    assert resp.status_code == 404


def test_audio_pin_refuses_without_source_and_succeeds_once_captured():
    from spectra import config as scfg
    import numpy as np
    import soundfile as sf

    client = _client()
    resp = client.post(f"/api/testbed/audio/pin?uri={URI}")
    assert resp.status_code == 409

    stem = "Artist - Song"
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.json").write_text(
        json.dumps({"spotify_uri": URI}), encoding="utf-8")
    tone = np.zeros(4000, dtype="float32")
    sf.write(str(scfg.AUDIO_SHAPES_DIR / f"{stem}.wav"), tone, 8000)

    resp = client.post(f"/api/testbed/audio/pin?uri={URI}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pinned"

    status = client.get(f"/api/testbed/audio/status?uri={URI}").json()
    assert status["pinned"] is True

    resp = client.delete(f"/api/testbed/audio/pin?uri={URI}")
    assert resp.status_code == 200
    resp = client.delete(f"/api/testbed/audio/pin?uri={URI}")
    assert resp.status_code == 404


def test_promote_refuses_unconfirmed_over_http():
    client = _client()
    resp = client.post("/api/testbed/promote", json={
        "uri": URI, "timestamp_ms": 1000,
        "action": {"kind": "fire_response", "event_class": "flare", "intensity": 0.5},
        "source_engine": "beat_this", "source_mark_kind": "downbeat",
        "confirmed": False,
    })
    assert resp.status_code == 422

    from spectra.services import trigger_store
    assert trigger_store.list_for_song(URI) == []


def test_promote_missing_confirmed_field_is_422_not_a_default():
    client = _client()
    resp = client.post("/api/testbed/promote", json={
        "uri": URI, "timestamp_ms": 1000,
        "action": {"kind": "fire_response", "event_class": "flare", "intensity": 0.5},
        "source_engine": "beat_this", "source_mark_kind": "downbeat",
    })
    assert resp.status_code == 422


def test_promote_confirmed_lands_a_real_trigger_and_logs_it():
    client = _client()
    resp = client.post("/api/testbed/promote", json={
        "uri": URI, "timestamp_ms": 3000,
        "action": {"kind": "fire_response", "event_class": "flare", "intensity": 0.6},
        "source_engine": "beat_this", "source_mark_kind": "downbeat",
        "confirmed": True,
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "promoted"

    from spectra.services import trigger_store
    stored = trigger_store.list_for_song(URI)
    assert len(stored) == 1
    assert stored[0].timestamp_ms == 3000
    assert stored[0].source == "authored"

    log = client.get(f"/api/testbed/promotions?uri={URI}").json()
    assert len(log) == 1
    assert log[0]["status"] == "promoted"
