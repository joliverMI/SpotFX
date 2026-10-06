"""The drop detector's read surfaces over the real app wiring
(FastAPI TestClient): GET /api/drop-sequences (read-through detection),
its summary, the analysed-plan's `drop_sequences` key, and the test bed's
Drops lane — engine marks in SONG time, the drops/lulls/charges reference
sets, and the four-song reference table. Synthetic songs only."""
from __future__ import annotations

import pytest

import drop_synth

URI = "spotify:track:dropapi1"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "TESTBED_DIR", tmp_path / "testbed")
    monkeypatch.setattr(scfg, "TESTBED_ANALYSIS_DIR", tmp_path / "testbed" / "analysis")
    monkeypatch.setattr(scfg, "TESTBED_PINNED_FILE", tmp_path / "testbed" / "pinned.json")
    monkeypatch.setattr(scfg, "TESTBED_PROMOTIONS_FILE", tmp_path / "testbed" / "promotions.json")
    monkeypatch.setattr(scfg, "TESTBED_PROMOTED_IDS_FILE", tmp_path / "testbed" / "promoted_ids.json")
    (tmp_path / "profiles").mkdir()
    drop_synth.reset_index()
    yield
    drop_synth.reset_index()


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _song(**kw):
    from spectra import config as scfg
    return drop_synth.one_drop_song(scfg.AUDIO_SHAPES_DIR, URI, **kw)


def _his(timestamp_ms, event_class):
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    trigger_store.upsert(URI, SpectraTrigger(
        timestamp_ms=timestamp_ms,
        action={"kind": "fire_response", "event_class": event_class}))


def test_get_detects_on_first_read_and_merges_his_triggers():
    _song()
    _his(44_100, "drop")
    body = _client().get(f"/api/drop-sequences?uri={URI}").json()
    assert body["status"] == "ok"
    assert body["detection"]["status"] == "detected"
    (seq,) = body["sequences"]
    assert seq["state"] == "matches_yours" and seq["tier"] == "confident"
    assert body["song"]["beat_ms"] == 500.0
    assert body["detector"]["confident_score"] == 1.0
    assert body["authored"][0]["drop"]["timestamp_ms"] == 44_100
    again = _client().get(f"/api/drop-sequences?uri={URI}").json()
    assert again["detection"]["status"] == "fresh"


def test_get_on_a_song_with_nothing_captured_is_unavailable_not_a_500():
    resp = _client().get("/api/drop-sequences?uri=spotify:track:none")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unavailable" and "no captured" in body["reason"]


def test_summary_reads_the_store_and_never_detects():
    client = _client()
    assert client.get("/api/drop-sequences/summary").json() == {"songs": []}
    _song()
    client.get(f"/api/drop-sequences?uri={URI}")
    (row,) = client.get("/api/drop-sequences/summary").json()["songs"]
    assert row["uri"] == URI and row["tiers"] == {"confident": 1}


def test_analysed_plan_carries_the_stored_drop_sequences_without_detecting():
    _song()
    client = _client()
    plan = client.get(f"/api/analysed-plan?uri={URI}").json()
    assert plan["drop_sequences"]["status"] == "not_detected"
    client.get(f"/api/drop-sequences?uri={URI}")
    plan = client.get(f"/api/analysed-plan?uri={URI}").json()
    assert [s["state"] for s in plan["drop_sequences"]["sequences"]] == ["confident"]


# ── the test bed's Drops lane ───────────────────────────────────────────

def test_drops_engine_marks_are_song_time_and_never_shifted_by_the_capture_offset():
    _song(offset_ms=5000)
    client = _client()
    drops = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=drops&mark_kind=drop").json()
    assert drops["available"]
    (mark,) = drops["estimate"]
    assert abs(mark["time_ms"] - 44_000) <= 30           # not 49 000
    assert mark["label"] == "confident"
    lulls = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=drops&mark_kind=lull").json()
    assert abs(lulls["estimate"][0]["time_ms"] - 40_000) <= 500


def test_drops_engine_takes_the_pages_two_thresholds():
    _song()
    client = _client()
    url = f"/api/testbed/engine-marks?uri={URI}&engine=drops&mark_kind=drop_confident"
    assert len(client.get(url).json()["estimate"]) == 1
    assert client.get(url + "&confident_score=1.9&suggested_score=0.7").json()["estimate"] == []
    suggested = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=drops&mark_kind=drop"
                           "&confident_score=1.9&suggested_score=0.7").json()["estimate"]
    assert [m["label"] for m in suggested] == ["suggested"]
    assert client.get(url + "&confident_score=9").status_code == 422


def test_compare_scores_the_drops_lane_against_his_drops_only():
    _song()
    _his(44_100, "drop")
    _his(30_000, "flare")
    body = _client().get(f"/api/testbed/compare?uri={URI}&engine=drops&mark_kind=drop"
                         "&reference=drops&tolerance_ms=500").json()
    assert [m["event_class"] for m in body["reference_marks"]] == ["drop"]
    assert body["metrics"]["n_matched"] == 1 and body["metrics"]["precision"] == 1.0


def test_song_listing_counts_his_drops_lulls_and_charges():
    _his(44_100, "drop")
    _his(40_000, "lull")
    _his(30_000, "flare")
    row = next(s for s in _client().get("/api/testbed/songs").json() if s["uri"] == URI)
    assert (row["n_drops"], row["n_lulls"], row["n_charges"], row["n_flares"]) == (1, 1, 0, 3)
    assert "drops" in row["engines"]


def test_drop_reference_set_reports_every_named_song_even_with_nothing_captured():
    body = _client().get("/api/testbed/drop-reference-set").json()
    assert [r["name"] for r in body["songs"]] == ["Contra", "Dopamine", "Pop Off", "100 Millones"]
    assert all(not r["available"] for r in body["songs"])
    assert body["confident_score"] == 1.0 and body["suggested_score"] == 0.7


def test_drop_reference_set_scores_a_captured_song(monkeypatch):
    from spectra.services import testbed_drop_reference
    monkeypatch.setattr(testbed_drop_reference, "DROP_REFERENCE_SONGS",
                        [("Synth", URI, True)])
    _song()
    _his(44_000, "drop")
    _his(40_100, "lull")
    _his(35_200, "charge")
    body = _client().get("/api/testbed/drop-reference-set").json()
    score = body["songs"][0]["score"]
    assert (score["his_drops"], score["found"], score["confident_found"]) == (1, 1, 1)
    assert score["lull_within_1_beat"] == 1 and score["charge_within_2_beats"] == 1
    assert body["edm_total"]["confident_extra"] == 0
