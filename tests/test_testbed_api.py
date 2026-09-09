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
    from spectra.services import testbed_audio, testbed_engines, testbed_marks, testbed_promote
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
    real_availability = testbed_engines.availability_for
    real_peaks = testbed_audio.load_peaks
    real_status = testbed_audio.status
    real_pin = testbed_audio.pin
    real_promote = testbed_promote.promote

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

    def _availability(uri, **kw):
        on_loop.setdefault("availability_reads", []).append(_ran_on_loop())
        return real_availability(uri, **kw)

    def _peaks(uri):
        on_loop["waveform"] = _ran_on_loop()
        return real_peaks(uri)

    def _status(uri, **kw):
        on_loop.setdefault("status_reads", []).append(_ran_on_loop())
        return real_status(uri, **kw)

    def _pin(uri):
        on_loop["pin"] = _ran_on_loop()
        return real_pin(uri)

    def _promote(**kw):
        on_loop["promote"] = _ran_on_loop()
        return real_promote(**kw)

    monkeypatch.setattr(testbed_marks, "all_song_marks", _listing)
    monkeypatch.setattr(testbed_marks, "marks_for_song", _single)
    monkeypatch.setattr(testbed_marks, "reference_marks_for_song", _reference)
    monkeypatch.setattr(testbed_engines, "marks_for", _engine)
    monkeypatch.setattr(testbed_engines, "availability_for", _availability)
    monkeypatch.setattr(testbed_audio, "load_peaks", _peaks)
    monkeypatch.setattr(testbed_audio, "status", _status)
    monkeypatch.setattr(testbed_audio, "pin", _pin)
    monkeypatch.setattr(testbed_promote, "promote", _promote)

    client = _client()
    assert client.get("/api/testbed/songs").status_code == 200
    assert client.get(f"/api/testbed/marks?uri={URI}").status_code == 200
    assert client.get(f"/api/testbed/waveform?uri={URI}").status_code == 200
    assert client.get(f"/api/testbed/engines?uri={URI}").status_code == 200
    assert client.get(f"/api/testbed/audio/status?uri={URI}").status_code == 200
    assert client.get(
        f"/api/testbed/compare?uri={URI}&engine=librosa&mark_kind=section_boundary",
    ).status_code == 200
    assert client.get(
        f"/api/testbed/engine-marks?uri={URI}&engine=librosa&mark_kind=beat",
    ).status_code == 200
    assert client.post(f"/api/testbed/audio/pin?uri={URI}").status_code == 200
    assert client.post("/api/testbed/promote", json={
        "uri": URI, "timestamp_ms": 30000,
        "action": {"kind": "fire_response", "event_class": "flare", "intensity": 0.5},
        "source_engine": "beat_this", "source_mark_kind": "downbeat", "confirmed": True,
    }).status_code == 200
    assert on_loop == {
        "songs": False, "marks": False, "waveform": False, "compare": False,
        "engine_reads": [False, False], "availability_reads": [False, False],
        "status_reads": [False, False], "pin": False, "promote": False,
    }


def test_compare_unavailable_payload_keeps_the_available_shape():
    """The "not computed" branch must describe itself the way the computed
    one does: `reference` is the set name, `reference_marks` the (empty)
    list — never a list under `reference`."""
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


def test_waveform_npz_fallback_carries_a_duration():
    """With no pinned WAV the page has only the coarse energy shape; it
    must still learn how long the song is, or the timeline ends at his
    last mark and every later engine mark piles up on the right edge."""
    from spectra import config as scfg
    import numpy as np
    stem = "Artist - Song"
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.json").write_text(
        json.dumps({"spotify_uri": URI}), encoding="utf-8")
    np.savez_compressed(
        scfg.AUDIO_SHAPES_DIR / f"{stem}.npz",
        timestamps_ms=np.array([0, 60000, 120000, 240000], dtype=np.int64),
        rms_total=np.array([0.1, 0.5, 0.2, 0.3], dtype=np.float32),
    )
    client = _client()
    resp = client.get(f"/api/testbed/waveform?uri={URI}").json()
    assert resp["source"] == "npz_rms_fallback"
    assert resp["duration_ms"] == 240000


def test_generated_only_song_is_listed_with_no_reference_marks():
    """A song seeded only by midsong_generator stays in the picker, but
    its reference lists are empty and the generated rows are counted —
    never served as if he had placed them."""
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    generated_only = "spotify:track:generatedonly"
    for ts in (20000, 40000):
        trigger_store.upsert(generated_only, SpectraTrigger(
            timestamp_ms=ts, action={"kind": "fire_scene"},
            source="generated", generator_key=f"section:{ts}"))
    _write_trigger(URI, 10000, "fire_scene")

    client = _client()
    rows = {s["uri"]: s for s in client.get("/api/testbed/songs").json()}
    assert rows[generated_only]["n_transitions"] == 0
    assert rows[generated_only]["n_flares"] == 0
    assert rows[generated_only]["n_generated"] == 2
    assert rows[URI]["n_transitions"] == 1
    assert rows[URI]["n_generated"] == 0

    marks = client.get(f"/api/testbed/marks?uri={generated_only}").json()
    assert marks["transitions"] == [] and marks["flares"] == []
    assert marks["n_generated"] == 2

    compare = client.get(
        f"/api/testbed/compare?uri={generated_only}&engine=librosa&mark_kind=section_boundary",
    ).json()
    assert compare["reference_marks"] == []


def test_promote_refuses_a_second_push_at_the_same_moment_with_409():
    client = _client()
    body = {
        "uri": URI, "timestamp_ms": 3000,
        "action": {"kind": "fire_response", "event_class": "flare", "intensity": 0.6},
        "source_engine": "beat_this", "source_mark_kind": "downbeat",
        "confirmed": True,
    }
    assert client.post("/api/testbed/promote", json=body).status_code == 200
    resp = client.post("/api/testbed/promote", json=body)
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]

    from spectra.services import trigger_store
    assert len(trigger_store.list_for_song(URI)) == 1
    log = client.get(f"/api/testbed/promotions?uri={URI}").json()
    assert [e["status"] for e in log] == ["promoted", "refused"]
    assert log[-1]["reason"] == "duplicate"


def test_songs_listing_never_parses_a_librosa_analysis(monkeypatch):
    """The listing reads each engine's availability BIT and nothing else;
    the parse is what /engines and /engine-marks are for. Against his real
    corpus that difference is 965 files and 417MB per request, re-fetched
    on every pin, unpin and promotion."""
    from spectra import config as scfg
    from spectra.services import analysis_reader
    _seed_librosa(scfg)
    _write_trigger(URI, 10000, "fire_scene")

    def _forbidden(*a, **kw):
        raise AssertionError("the songs listing parsed a .librosa.json")
    monkeypatch.setattr(analysis_reader, "librosa_analysis_for_stem", _forbidden)

    client = _client()
    rows = {s["uri"]: s for s in client.get("/api/testbed/songs").json()}
    assert rows[URI]["engines"]["librosa"]["available"] is True
    assert rows[URI]["engines"]["librosa"]["mark_count"] is None
    assert rows[URI]["engines"]["librosa"]["kinds"] == [
        "section_boundary", "beat", "downbeat"]


def test_a_pushed_mark_is_shown_flagged_and_kept_out_of_compare(monkeypatch):
    """Push-to-real lands a mark at the engine's own exact time, so
    scoring against it would grade that engine on its own suggestion.
    /marks still shows it (flagged); /compare must not count it."""
    from spectra import config as scfg
    _seed_librosa(scfg)
    _write_trigger(URI, 25000, "fire_scene")
    client = _client()

    pushed = client.post("/api/testbed/promote", json={
        "uri": URI, "timestamp_ms": 10000,
        "action": {"kind": "fire_scene", "intensity": 0.5},
        "source_engine": "librosa", "source_mark_kind": "section_boundary",
        "confirmed": True,
    })
    assert pushed.status_code == 200
    pushed_id = pushed.json()["trigger_id"]

    marks = client.get(f"/api/testbed/marks?uri={URI}").json()
    assert marks["n_promoted"] == 1
    by_id = {m["id"]: m for m in marks["transitions"]}
    assert by_id[pushed_id]["promoted"] is True
    assert [m["promoted"] for m in marks["transitions"] if m["id"] != pushed_id] == [False]

    rows = {s["uri"]: s for s in client.get("/api/testbed/songs").json()}
    assert rows[URI]["n_promoted"] == 1
    assert rows[URI]["n_transitions"] == 2

    # librosa's only interior section boundary is at 10000 — exactly where
    # the pushed mark sits. Counting it would report a perfect match.
    compare = client.get(
        f"/api/testbed/compare?uri={URI}&engine=librosa&mark_kind=section_boundary"
        "&reference=transitions&tolerance_ms=500",
    ).json()
    assert [r["timestamp_ms"] for r in compare["reference_marks"]] == [25000]
    assert compare["metrics"]["n_reference"] == 1
    assert compare["metrics"]["n_matched"] == 0
