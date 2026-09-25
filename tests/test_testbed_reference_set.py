"""spectra/services/testbed_reference_set.py + the /api/testbed/reference-set
route (data/transition-alignment-plan/report.md section 4/5 task 4) — the
plan's own four-song acceptance table, live on the test-bed page. Seeds the
SAME four hardcoded reference URIs (REFERENCE_SONGS) under isolated
storage, since the module intentionally does not parametrize which songs
it scores (matching scripts/check_transition_alignment.py's own reasoning
for keeping a private copy of that list)."""
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
    monkeypatch.setattr(scfg, "TESTBED_PROMOTIONS_FILE", tmp_path / "promotions.json")
    monkeypatch.setattr(scfg, "TESTBED_PROMOTED_IDS_FILE", tmp_path / "promoted_ids.json")
    (tmp_path / "profiles").mkdir()
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True)
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False
    # The old tests here were all written against a flat per-song COUNT
    # knob (transition_max_per_song); the rate replacing it
    # (transitions_per_minute, 2026-09-25) multiplies by duration and the
    # song's own intensity-scale factor — see
    # tests/test_midsong_generator.py for THAT arithmetic on its own.
    # Patching the rate->count resolution to a plain identity keeps this
    # file's density/knob-plumbing tests meaningful with a minimal rename
    # (transitions_per_minute=N behaves exactly like the old
    # transitions_per_minute=N did).
    monkeypatch.setattr(midsong_generator, "resolve_transition_count",
                        lambda uri, sections, rate: max(1, int(round(rate))))


def _seed_song(scfg, uri, stem, *, n_boundaries, tempo_bpm=120.0):
    """Same deterministic-strength density shape used throughout this
    build's other tuning-loop tests: the i-th of `n_boundaries` mid-song
    boundaries carries bass-energy step size i, so a lower transitions_per_minute/
    window_beats visibly moves which (and how many) candidates survive."""
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
        json.dumps({"spotify_uri": uri}), encoding="utf-8")
    (scfg.AUDIO_SHAPES_DIR / f"{stem}.librosa.json").write_text(json.dumps({
        "spotify_uri": uri, "tempo_bpm": tempo_bpm, "sections": sections, "beats": beats,
    }), encoding="utf-8")


def _write_authored_transition(uri, timestamp_ms):
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    trigger_store.upsert(uri, SpectraTrigger(
        timestamp_ms=timestamp_ms, source="authored",
        action={"kind": "fire_scene", "scene_id": None, "intensity": 0.5},
    ))


def test_compute_returns_one_row_per_reference_song_in_order():
    from spectra.services import testbed_reference_set
    rows = testbed_reference_set.compute(
        window_beats=8, sensitivity=0.5, direction="both", transitions_per_minute=None)
    assert [r.name for r in rows] == [name for name, _uri in testbed_reference_set.REFERENCE_SONGS]
    assert [r.uri for r in rows] == [uri for _name, uri in testbed_reference_set.REFERENCE_SONGS]


def test_a_song_with_no_analysis_reports_unavailable_not_a_crash():
    from spectra.services import testbed_reference_set
    rows = testbed_reference_set.compute(
        window_beats=8, sensitivity=0.5, direction="both", transitions_per_minute=None)
    for row in rows:
        assert row.available is False
        assert row.metrics is None
        assert row.tolerance_ms is None


def test_a_seeded_reference_song_scores_against_its_authored_transitions():
    from spectra import config as scfg
    from spectra.services import testbed_reference_set
    name, uri = testbed_reference_set.REFERENCE_SONGS[0]
    _seed_song(scfg, uri, "RefSong0", n_boundaries=10, tempo_bpm=120.0)
    _write_authored_transition(uri, 5000)  # lands exactly on boundary #5

    rows = testbed_reference_set.compute(
        window_beats=1, sensitivity=1.5, direction="both", transitions_per_minute=40)
    row = next(r for r in rows if r.uri == uri)
    assert row.available is True
    assert row.tolerance_ms == pytest.approx(500.0)  # one beat at 120bpm
    assert row.metrics["n_reference"] == 1
    assert row.metrics["n_matched"] == 1
    assert row.metrics["recall"] == pytest.approx(1.0)


def test_lowering_transitions_per_minute_can_only_reduce_or_hold_recall():
    """The acceptance shape from the report itself (Contra 73% -> 55% when
    Window moves 8 -> 2): tightening a knob narrows the candidate set, so
    recall against a fixed reference set never goes UP."""
    from spectra import config as scfg
    from spectra.services import testbed_reference_set
    name, uri = testbed_reference_set.REFERENCE_SONGS[1]
    _seed_song(scfg, uri, "RefSong1", n_boundaries=20, tempo_bpm=120.0)
    for i in range(1, 21):
        _write_authored_transition(uri, i * 1000)

    wide = testbed_reference_set.compute(
        window_beats=1, sensitivity=1.5, direction="both", transitions_per_minute=20)
    narrow = testbed_reference_set.compute(
        window_beats=1, sensitivity=1.5, direction="both", transitions_per_minute=6)
    wide_row = next(r for r in wide if r.uri == uri)
    narrow_row = next(r for r in narrow if r.uri == uri)
    assert narrow_row.metrics["recall"] <= wide_row.metrics["recall"]
    assert narrow_row.metrics["n_matched"] < wide_row.metrics["n_matched"]


def test_transitions_per_minute_omitted_falls_back_to_the_room_default():
    from spectra import config as scfg
    from spectra.services import room_controls, testbed_reference_set
    name, uri = testbed_reference_set.REFERENCE_SONGS[2]
    _seed_song(scfg, uri, "RefSong2", n_boundaries=20, tempo_bpm=120.0)
    for i in range(1, 21):
        _write_authored_transition(uri, i * 1000)
    room_controls.save_room_controls(room_controls.RoomControlState(
        midsong_snap_to_beat=False, transition_window_beats=1,
        transition_edge_sensitivity=1.5, transitions_per_minute=6))

    explicit = testbed_reference_set.compute(
        window_beats=1, sensitivity=1.5, direction="both", transitions_per_minute=6)
    omitted = testbed_reference_set.compute(
        window_beats=1, sensitivity=1.5, direction="both")
    explicit_row = next(r for r in explicit if r.uri == uri)
    omitted_row = next(r for r in omitted if r.uri == uri)
    assert omitted_row.metrics == explicit_row.metrics


def test_promoted_marks_are_excluded_from_scoring_here_too():
    """reference_marks_for_song already drops test-bed-promoted rows — this
    row must not grade the generator against its own pushed suggestion."""
    from spectra import config as scfg
    from spectra.services import testbed_promote, testbed_reference_set
    name, uri = testbed_reference_set.REFERENCE_SONGS[0]
    _seed_song(scfg, uri, "RefSong0Promoted", n_boundaries=10, tempo_bpm=120.0)
    testbed_promote.promote(
        uri=uri, timestamp_ms=5000,
        action={"kind": "fire_scene", "scene_id": None, "intensity": 0.5},
        source_engine="generator", source_mark_kind="preview", confirmed=True)

    rows = testbed_reference_set.compute(
        window_beats=1, sensitivity=1.5, direction="both", transitions_per_minute=40)
    row = next(r for r in rows if r.uri == uri)
    assert row.metrics["n_reference"] == 0


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def test_reference_set_route_returns_all_four_songs_and_the_knobs_used():
    client = _client()
    resp = client.get("/api/testbed/reference-set?window_beats=4&sensitivity=0.3&direction=up&transitions_per_minute=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["window_beats"] == 4
    assert body["sensitivity"] == pytest.approx(0.3)
    assert body["direction"] == "up"
    assert body["transitions_per_minute"] == 10
    assert len(body["songs"]) == 4
    assert {s["uri"] for s in body["songs"]} == {
        "spotify:track:1JxhrUWZjuI8AOjDJ1JpMN", "spotify:track:2zVg53xdC6RMpthWju6LRT",
        "spotify:track:7vFKcXQ39f74XNrZmXADIT", "spotify:track:0UvZcEfpzVyx47QsRbjyBz",
    }


def test_reference_set_route_rejects_out_of_bounds_knobs():
    client = _client()
    assert client.get("/api/testbed/reference-set?window_beats=999").status_code == 422
    assert client.get("/api/testbed/reference-set?sensitivity=99").status_code == 422
    assert client.get("/api/testbed/reference-set?direction=sideways").status_code == 422
    assert client.get("/api/testbed/reference-set?transitions_per_minute=0").status_code == 422
    assert client.get("/api/testbed/reference-set?transitions_per_minute=999").status_code == 422


def test_reference_set_route_defaults_transitions_per_minute_to_none_not_a_literal():
    """Omitting transitions_per_minute from the URL must mean 'use the
    room's own setting', matching testbed_engines.marks_for's own
    semantics — never a hardcoded literal that would silently disagree
    with a room default."""
    client = _client()
    resp = client.get("/api/testbed/reference-set")
    assert resp.status_code == 200
    assert resp.json()["transitions_per_minute"] is None
