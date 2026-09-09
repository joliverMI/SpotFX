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


def test_songs_carry_title_and_artist_from_the_editor_profile():
    """The page labels every song from this ONE listing — never one
    /api/profiles/by-uri request per song."""
    from spectra import config as scfg
    _write_trigger(URI, 10000, "fire_scene")
    (scfg.PROFILES_DIR / "A - T.json").write_text(json.dumps({
        "spotify_uri": URI, "title": "Dopamine", "artist": "Purple Disco",
        "duration_ms": 1000, "verified": True, "ai_generated": False, "triggers": [],
    }), encoding="utf-8")
    _write_trigger("spotify:track:noprofile", 1000, "fire_scene")

    client = _client()
    rows = {s["uri"]: s for s in client.get("/api/testbed/songs").json()}
    assert (rows[URI]["title"], rows[URI]["artist"]) == ("Dopamine", "Purple Disco")
    assert rows[URI]["provenance"]["found"] is True
    assert (rows["spotify:track:noprofile"]["title"],
            rows["spotify:track:noprofile"]["artist"]) == (None, None)

    marks = client.get(f"/api/testbed/marks?uri={URI}").json()
    assert (marks["title"], marks["artist"]) == ("Dopamine", "Purple Disco")


def test_songs_listing_and_pin_run_off_the_event_loop(monkeypatch):
    """Both are synchronous file I/O over the corpus / a whole WAV; they
    must never run on the SPECTRA process's event loop, where they would
    stall the trigger engine, the bridge poll and every WS broadcast."""
    import asyncio
    from spectra import config as scfg
    from spectra.services import testbed_audio, testbed_engines, testbed_marks
    import numpy as np
    import soundfile as sf

    _seed_librosa(scfg)
    _write_trigger(URI, 10000, "fire_scene")
    stem = "Artist - Song"
    sf.write(str(scfg.AUDIO_SHAPES_DIR / f"{stem}.wav"),
             np.zeros(4000, dtype="float32"), 8000)

    on_loop = {}

    def _ran_on_loop() -> bool:
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    real_listing = testbed_marks.all_song_marks
    real_single = testbed_marks.marks_for_song
    real_reference = testbed_marks.reference_marks_for_song
    real_engine = testbed_engines.marks_for
    real_pin = testbed_audio.pin

    def _listing():
        on_loop["songs"] = _ran_on_loop()
        return real_listing()

    def _single(uri):
        on_loop["marks"] = _ran_on_loop()
        return real_single(uri)

    def _reference(uri):
        on_loop["compare"] = _ran_on_loop()
        return real_reference(uri)

    def _engine(engine, uri):
        on_loop.setdefault("engine_reads", []).append(_ran_on_loop())
        return real_engine(engine, uri)

    def _pin(uri):
        on_loop["pin"] = _ran_on_loop()
        return real_pin(uri)

    monkeypatch.setattr(testbed_marks, "all_song_marks", _listing)
    monkeypatch.setattr(testbed_marks, "marks_for_song", _single)
    monkeypatch.setattr(testbed_marks, "reference_marks_for_song", _reference)
    monkeypatch.setattr(testbed_engines, "marks_for", _engine)
    monkeypatch.setattr(testbed_audio, "pin", _pin)

    client = _client()
    assert client.get("/api/testbed/songs").status_code == 200
    assert client.get(f"/api/testbed/marks?uri={URI}").status_code == 200
    assert client.get(
        f"/api/testbed/compare?uri={URI}&engine=librosa&mark_kind=section_boundary",
    ).status_code == 200
    assert client.get(
        f"/api/testbed/engine-marks?uri={URI}&engine=librosa&mark_kind=beat",
    ).status_code == 200
    assert client.post(f"/api/testbed/audio/pin?uri={URI}").status_code == 200
    assert on_loop == {"songs": False, "marks": False, "compare": False,
                       "engine_reads": [False, False], "pin": False}


def test_compare_unavailable_payload_keeps_the_available_shape():
    """The "not computed" branch must describe itself the way the computed
    one does (types.ts's TestbedCompareResult): `reference` is the set name,
    `reference_marks` the (empty) list — never a list under `reference`."""
    client = _client()
    resp = client.get(
        f"/api/testbed/compare?uri={URI}&engine=librosa&mark_kind=section_boundary"
        "&reference=flares&tolerance_ms=250",
    ).json()
    assert resp["available"] is False
    assert resp["reference"] == "flares"
    assert resp["reference_marks"] == []
    assert resp["estimate"] == []
    assert resp["tolerance_ms"] == 250.0
    assert resp["metrics"] is None


def test_engine_marks_serves_one_engines_marks_without_touching_his_stores(monkeypatch):
    """The page's per-lane fetch. It must answer from the engine's own
    output alone: the trigger store and the profile directory are made to
    raise, and the route still answers — those reads are what /compare
    pays for a match this caller throws away."""
    from spectra import config as scfg
    from spectra.services import testbed_marks, trigger_store
    _seed_librosa(scfg)

    def _forbidden(*a, **kw):
        raise AssertionError("engine-marks touched a store it must not read")
    monkeypatch.setattr(trigger_store, "_load_raw", _forbidden)
    monkeypatch.setattr(testbed_marks, "_find_profile", _forbidden)

    client = _client()
    resp = client.get(
        f"/api/testbed/engine-marks?uri={URI}&engine=librosa&mark_kind=section_boundary",
    ).json()
    assert resp["available"] is True
    assert [m["time_ms"] for m in resp["estimate"]] == [10000.0]
    assert resp["estimate"][0]["label"] == "drop"
    assert set(resp) == {"uri", "engine", "mark_kind", "available", "estimate"}

    beats = client.get(
        f"/api/testbed/engine-marks?uri={URI}&engine=librosa&mark_kind=downbeat",
    ).json()
    assert [m["time_ms"] for m in beats["estimate"]] == [10050.0]

    missing = client.get(
        f"/api/testbed/engine-marks?uri=spotify:track:noanalysis&engine=librosa&mark_kind=beat",
    ).json()
    assert missing == {"uri": "spotify:track:noanalysis", "engine": "librosa",
                       "mark_kind": "beat", "available": False, "estimate": []}

    not_computed = client.get(
        f"/api/testbed/engine-marks?uri={URI}&engine=beat_this&mark_kind=downbeat",
    ).json()
    assert not_computed["available"] is False and not_computed["estimate"] == []

    assert client.get(
        f"/api/testbed/engine-marks?uri={URI}&engine=nope&mark_kind=beat",
    ).status_code == 404


def test_compare_never_scans_the_profile_directory(monkeypatch):
    """/compare needs the fired-copy marks to match against and nothing
    from the editor copy — provenance is /marks' caveat, not a metric."""
    from spectra import config as scfg
    from spectra.services import testbed_marks
    _seed_librosa(scfg)
    _write_trigger(URI, 10000, "fire_scene")
    _write_trigger(URI, 10020, "fire_response", event_class="flare")

    def _forbidden(*a, **kw):
        raise AssertionError("compare scanned the profile directory")
    monkeypatch.setattr(testbed_marks, "_find_profile", _forbidden)

    client = _client()
    transitions = client.get(
        f"/api/testbed/compare?uri={URI}&engine=librosa&mark_kind=section_boundary"
        "&reference=transitions&tolerance_ms=500",
    ).json()
    assert transitions["metrics"]["n_reference"] == 1
    assert transitions["metrics"]["n_matched"] == 1
    assert [r["timestamp_ms"] for r in transitions["reference_marks"]] == [10000]

    flares = client.get(
        f"/api/testbed/compare?uri={URI}&engine=librosa&mark_kind=section_boundary"
        "&reference=flares&tolerance_ms=500",
    ).json()
    assert [r["timestamp_ms"] for r in flares["reference_marks"]] == [10020]
    assert flares["metrics"]["n_matched"] == 1
