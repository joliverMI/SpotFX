"""The two new music-analysis test-bed tuning-loop lanes
(data/transition-alignment-plan/report.md section 4, ship task 2):
`generator` (stored/preview) and `edges` (bass_up/bass_down/gap_stop/
gap_resume) — service-layer lane payload shape, the window_beats/
sensitivity knobs, and the "generator:stored equals triggers.json
verbatim" acceptance bar."""
from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import analysis_reader, midsong_generator
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    monkeypatch.setattr(scfg, "TESTBED_ANALYSIS_DIR", tmp_path / "spectra" / "testbed" / "analysis")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    (tmp_path / "profiles").mkdir()
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True)
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False
    # Rate->count resolution patched to a plain identity — see
    # tests/test_testbed_reference_set.py's own fixture comment for why.
    monkeypatch.setattr(midsong_generator, "resolve_transition_count",
                        lambda uri, sections, rate: max(1, int(round(rate))))


URI = "spotify:track:testbedgenedge1"


def _seed_librosa(scfg, *, rms_bass_spike_at=None):
    stem = "Artist - GenEdgeSong"
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.json").write_text(
        json.dumps({"spotify_uri": URI}), encoding="utf-8")
    beats = [{"ms": i * 500.0, "rms_bass": 0.1, "is_downbeat": i % 4 == 0}
            for i in range(40)]
    if rms_bass_spike_at is not None:
        for i in range(rms_bass_spike_at, 40):
            beats[i]["rms_bass"] = 1.0
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.librosa.json").write_text(json.dumps({
        "spotify_uri": URI,
        "tempo_bpm": 120.0,
        "sections": [
            {"start_ms": 0, "end_ms": 10000, "label": "intro", "energy_rms": 0.2},
            {"start_ms": 10000, "end_ms": 20000, "label": "drop", "energy_rms": 0.9},
        ],
        "beats": beats,
    }), encoding="utf-8")


def _write_trigger(uri, timestamp_ms, *, source="generated", generator_key=None,
                   snap_grid=None, kind="fire_scene"):
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    trigger_store.upsert(uri, SpectraTrigger(
        timestamp_ms=timestamp_ms, source=source, generator_key=generator_key,
        snap_grid=snap_grid,
        action={"kind": kind, "scene_id": None, "intensity": 0.5, "color_set_id": None},
    ))


# ── generator engine ────────────────────────────────────────────────────

def test_generator_stored_equals_triggers_json_verbatim():
    """The ship task's own acceptance bar: generator:stored must show
    exactly what's currently in the fired trigger store for this song —
    no recomputation, timestamps unmodified — so it's where a generator
    frame defect becomes visible before it's fixed."""
    from spectra.services import testbed_engines
    _write_trigger(URI, 3692, source="generated", generator_key="section:0")
    _write_trigger(URI, 13692, source="generated", generator_key="section:10000")
    _write_trigger(URI, 999, source="authored")  # never shown as "stored"

    marks = testbed_engines.marks_for(testbed_engines.ENGINE_GENERATOR, URI)
    stored = sorted(m.time_ms for m in marks if m.kind == "stored")
    assert stored == [3692.0, 13692.0]  # exactly the generated rows, verbatim
    assert 999.0 not in stored


def test_generator_preview_runs_the_current_placement_rule_offline_with_no_write():
    """generator:preview is midsong_generator.candidate_moments run
    read-only — it must produce a real placement without ever touching the
    trigger store."""
    from spectra import config as scfg
    from spectra.services import testbed_engines, trigger_store
    _seed_librosa(scfg)

    marks = testbed_engines.marks_for(testbed_engines.ENGINE_GENERATOR, URI)
    preview = [m for m in marks if m.kind == "preview"]
    assert len(preview) == 1  # one interior section boundary (10000ms)
    assert preview[0].time_ms == 10000.0
    assert trigger_store.list_for_song(URI) == []  # nothing written


def test_generator_marks_none_when_nothing_stored_and_no_analysis():
    from spectra.services import testbed_engines
    assert testbed_engines.marks_for(
        testbed_engines.ENGINE_GENERATOR, "spotify:track:nothingatall") is None


def test_generator_marks_are_not_shifted_by_capture_offset():
    """The generator engine is the one exception to _estimate_for's
    capture-offset shift — its marks are already in the room's own
    operating frame. Verified at the API layer, where the shift is
    applied."""
    from spectra import config as scfg
    from spectra.services import testbed_audio, testbed_engines
    from spectra.api import testbed as testbed_api
    _seed_librosa(scfg)
    _write_trigger(URI, 5000, source="generated")
    monkeypatch_offset = 3692

    orig = testbed_audio.capture_offset_ms_or_zero
    try:
        testbed_audio.capture_offset_ms_or_zero = lambda uri: monkeypatch_offset
        gen_marks = testbed_api._estimate_for(
            testbed_engines.ENGINE_GENERATOR, URI, "stored")
        lib_marks = testbed_api._estimate_for(
            testbed_engines.ENGINE_LIBROSA, URI, "section_boundary")
    finally:
        testbed_audio.capture_offset_ms_or_zero = orig

    assert gen_marks[0].time_ms == 5000.0  # unshifted
    assert lib_marks[0].time_ms == 10000.0 + monkeypatch_offset  # shifted


# ── edges engine ─────────────────────────────────────────────────────────

def test_edges_engine_marks_come_from_rhythmic_edges_and_all_four_kinds_are_reachable():
    from spectra import config as scfg
    from spectra.services import testbed_engines
    _seed_librosa(scfg, rms_bass_spike_at=20)
    marks = testbed_engines.marks_for(testbed_engines.ENGINE_EDGES, URI)
    assert marks is not None
    kinds = {m.kind for m in marks}
    assert kinds <= set(testbed_engines.ENGINES[testbed_engines.ENGINE_EDGES]["kinds"])
    assert "bass_up" in kinds


def test_edges_engine_forwards_window_and_sensitivity_knobs():
    from spectra import config as scfg
    from spectra.services import testbed_engines
    _seed_librosa(scfg, rms_bass_spike_at=20)
    loose = testbed_engines.marks_for(testbed_engines.ENGINE_EDGES, URI, sensitivity=0.2)
    strict = testbed_engines.marks_for(testbed_engines.ENGINE_EDGES, URI, sensitivity=1.5)
    loose_up = [m for m in loose if m.kind == "bass_up"]
    strict_up = [m for m in strict if m.kind == "bass_up"]
    assert len(loose_up) >= len(strict_up)


def test_edges_engine_forwards_direction_knob():
    from spectra import config as scfg
    from spectra.services import testbed_engines
    _seed_librosa(scfg, rms_bass_spike_at=20)
    both = testbed_engines.marks_for(testbed_engines.ENGINE_EDGES, URI, direction="both")
    up = testbed_engines.marks_for(testbed_engines.ENGINE_EDGES, URI, direction="up")
    down = testbed_engines.marks_for(testbed_engines.ENGINE_EDGES, URI, direction="down")
    assert any(m.kind == "bass_up" for m in both)
    assert any(m.kind == "bass_up" for m in up)
    assert not any(m.kind == "bass_up" for m in down)


def test_edges_engine_none_when_no_beat_analysis():
    from spectra.services import testbed_engines
    assert testbed_engines.marks_for(
        testbed_engines.ENGINE_EDGES, "spotify:track:noanalysis") is None


# ── whole-corpus availability listing ──────────────────────────────────

def test_availability_listing_includes_all_four_engines():
    from spectra import config as scfg
    from spectra.services import analysis_reader, testbed_engines
    _seed_librosa(scfg, rms_bass_spike_at=20)
    avail = testbed_engines.availability_for(
        URI, stem_index=analysis_reader.stem_index(), count_marks=False)
    assert set(avail.keys()) == {"librosa", "beat_this", "generator", "edges"}
    assert avail["generator"]["available"] is True
    assert avail["edges"]["available"] is True
    assert avail["generator"]["mark_count"] is None  # fast path never counts


# ── /api/testbed/engine-marks and /compare — the query-param wiring ────

def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def test_engine_marks_route_accepts_and_uses_the_knobs():
    from spectra import config as scfg
    _seed_librosa(scfg, rms_bass_spike_at=20)
    client = _client()
    loose = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=edges"
                       f"&mark_kind=bass_up&sensitivity=0.2").json()
    strict = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=edges"
                        f"&mark_kind=bass_up&sensitivity=1.5").json()
    assert loose["available"] is True
    assert len(loose["estimate"]) >= len(strict["estimate"])


def test_engine_marks_route_rejects_out_of_bounds_knobs():
    client = _client()
    resp = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=edges"
                      f"&mark_kind=bass_up&window_beats=999")
    assert resp.status_code == 422
    resp2 = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=edges"
                       f"&mark_kind=bass_up&sensitivity=99")
    assert resp2.status_code == 422


def test_engine_marks_route_accepts_and_uses_direction():
    from spectra import config as scfg
    _seed_librosa(scfg, rms_bass_spike_at=20)
    client = _client()
    both = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=edges"
                      f"&mark_kind=bass_up&direction=both").json()
    down = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=edges"
                      f"&mark_kind=bass_up&direction=down").json()
    assert both["available"] is True
    assert len(both["estimate"]) > 0
    assert down["estimate"] == []


def test_engine_marks_route_rejects_invalid_direction():
    client = _client()
    resp = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=edges"
                      f"&mark_kind=bass_up&direction=sideways")
    assert resp.status_code == 422


def test_compare_route_forwards_the_knobs_too():
    from spectra import config as scfg
    _seed_librosa(scfg, rms_bass_spike_at=20)
    _write_trigger(URI, 10000, source="authored", kind="fire_scene")
    client = _client()
    resp = client.get(f"/api/testbed/compare?uri={URI}&engine=edges"
                      f"&mark_kind=bass_up&sensitivity=0.2&tolerance_ms=500")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["metrics"] is not None


def test_compare_route_forwards_direction_too():
    from spectra import config as scfg
    _seed_librosa(scfg, rms_bass_spike_at=20)
    _write_trigger(URI, 10000, source="authored", kind="fire_scene")
    client = _client()
    down = client.get(f"/api/testbed/compare?uri={URI}&engine=edges"
                      f"&mark_kind=bass_up&direction=down&tolerance_ms=500")
    assert down.status_code == 200
    body = down.json()
    assert body["available"] is True
    assert body["estimate"] == []
    assert body["metrics"]["n_matched"] == 0


def test_generator_lane_reachable_through_the_route_and_unshifted():
    from spectra import config as scfg
    _seed_librosa(scfg)
    _write_trigger(URI, 7777, source="generated")
    client = _client()
    resp = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=generator&mark_kind=stored")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["estimate"] == [{"time_ms": 7777.0, "label": "fire_scene", "score": None}]


# ── transitions_per_minute (the density RATE knob, 2026-09-25) ──

def _seed_density(scfg, n_boundaries=20, tempo_bpm=120.0):
    """`n_boundaries` mid-song section boundaries at 1000ms spacing, each
    carrying a distinct, isolated bass-energy step (i-th boundary's own
    strength == i) so transitions_per_minute's ranking is deterministic —
    the same shape tests/test_midsong_generator.py's own density tests
    use."""
    stem = "Artist - GenEdgeDensitySong"
    n_beats = n_boundaries * 2 + 2
    rms_bass = [0.0] * n_beats
    for i in range(1, n_boundaries + 1):
        rms_bass[i * 2] = float(i)
    beats = [{"ms": j * 500, "is_downbeat": False, "rms_bass": rms_bass[j]}
            for j in range(n_beats)]
    sections = [{"start_ms": 0, "end_ms": 1000, "label": "intro", "energy_rms": 0.1}]
    for i in range(1, n_boundaries + 1):
        sections.append({"start_ms": i * 1000, "end_ms": (i + 1) * 1000,
                         "label": "section", "energy_rms": 0.5})
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.json").write_text(
        json.dumps({"spotify_uri": URI}), encoding="utf-8")
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.librosa.json").write_text(json.dumps({
        "spotify_uri": URI, "tempo_bpm": tempo_bpm, "sections": sections, "beats": beats,
    }), encoding="utf-8")


def test_generator_preview_forwards_transitions_per_minute_knob():
    from spectra import config as scfg
    from spectra.services import testbed_engines
    _seed_density(scfg, n_boundaries=20)
    uncapped = testbed_engines.marks_for(
        testbed_engines.ENGINE_GENERATOR, URI, window_beats=1, sensitivity=1.5,
        direction="both", transitions_per_minute=20)
    capped = testbed_engines.marks_for(
        testbed_engines.ENGINE_GENERATOR, URI, window_beats=1, sensitivity=1.5,
        direction="both", transitions_per_minute=5)
    uncapped_preview = [m for m in uncapped if m.kind == "preview"]
    capped_preview = [m for m in capped if m.kind == "preview"]
    assert len(uncapped_preview) == 20
    assert len(capped_preview) == 5


def test_generator_preview_omits_transitions_per_minute_falls_back_to_room_default():
    from spectra import config as scfg
    from spectra.services import room_controls, testbed_engines
    _seed_density(scfg, n_boundaries=20)
    room_controls.save_room_controls(room_controls.RoomControlState(
        midsong_snap_to_beat=False, transition_window_beats=1,
        transition_edge_sensitivity=1.5, transitions_per_minute=6))
    marks = testbed_engines.marks_for(
        testbed_engines.ENGINE_GENERATOR, URI, window_beats=1, sensitivity=1.5,
        direction="both")  # transitions_per_minute omitted entirely
    preview = [m for m in marks if m.kind == "preview"]
    assert len(preview) == 6, "an omitted transitions_per_minute reads the live room setting"


def test_edges_engine_ignores_transitions_per_minute():
    """The density cap is a generator-only concept — edges just detects
    edges, it never ranks or trims candidates."""
    from spectra import config as scfg
    from spectra.services import testbed_engines
    _seed_density(scfg, n_boundaries=20)
    with_cap = testbed_engines.marks_for(
        testbed_engines.ENGINE_EDGES, URI, window_beats=1, sensitivity=0.2,
        direction="both", transitions_per_minute=1)
    without_cap = testbed_engines.marks_for(
        testbed_engines.ENGINE_EDGES, URI, window_beats=1, sensitivity=0.2, direction="both")
    assert with_cap == without_cap


def test_engine_marks_route_accepts_and_uses_transitions_per_minute():
    from spectra import config as scfg
    _seed_density(scfg, n_boundaries=20)
    client = _client()
    uncapped = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=generator"
                          f"&mark_kind=preview&window_beats=1&sensitivity=1.5&transitions_per_minute=20").json()
    capped = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=generator"
                        f"&mark_kind=preview&window_beats=1&sensitivity=1.5&transitions_per_minute=6").json()
    assert len(uncapped["estimate"]) == 20
    assert len(capped["estimate"]) == 6


def test_engine_marks_route_rejects_out_of_bounds_transitions_per_minute():
    """Bounds read live off RoomControlState.transitions_per_minute's own
    Field(ge=1, le=30) — spectra/api/testbed.py's _RATE_GE/_LE."""
    client = _client()
    resp = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=generator"
                      f"&mark_kind=preview&transitions_per_minute=999")
    assert resp.status_code == 422
    resp2 = client.get(f"/api/testbed/engine-marks?uri={URI}&engine=generator"
                       f"&mark_kind=preview&transitions_per_minute=0")
    assert resp2.status_code == 422


def test_compare_route_forwards_transitions_per_minute_too():
    from spectra import config as scfg
    _seed_density(scfg, n_boundaries=20)
    _write_trigger(URI, 1000, source="authored", kind="fire_scene")
    client = _client()
    resp = client.get(f"/api/testbed/compare?uri={URI}&engine=generator&mark_kind=preview"
                      f"&window_beats=1&sensitivity=1.5&transitions_per_minute=6&tolerance_ms=500")
    assert resp.status_code == 200
    assert len(resp.json()["estimate"]) == 6
