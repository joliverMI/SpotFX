"""spectra/services/testbed_marks.py — the reference-mark split (transition
vs flare) + provenance surfacing (report Part 3 "What it reads")."""
from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "PROFILES_DIR", tmp_path / "profiles")
    (tmp_path / "profiles").mkdir()


URI = "spotify:track:testbedmarks1"


def _write_trigger(uri, timestamp_ms, kind, **action_extra):
    from spectra import config as scfg
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    action = {"kind": kind, **action_extra}
    trigger_store.upsert(uri, SpectraTrigger(timestamp_ms=timestamp_ms, action=action))


def test_split_transitions_vs_flares():
    from spectra.services import testbed_marks
    _write_trigger(URI, 1000, "fire_scene")
    _write_trigger(URI, 2000, "fire_scene_update")
    _write_trigger(URI, 3000, "fire_response", event_class="flare")
    _write_trigger(URI, 4000, "select_color_set", set_id="whatever")

    marks = testbed_marks.marks_for_song(URI)
    assert sorted(m.timestamp_ms for m in marks.transitions) == [1000, 2000]
    assert sorted(m.timestamp_ms for m in marks.flares) == [3000, 4000]


def test_unknown_song_has_no_marks():
    from spectra.services import testbed_marks
    marks = testbed_marks.marks_for_song("spotify:track:nonexistent")
    assert marks.transitions == []
    assert marks.flares == []
    assert marks.provenance.found is False


def test_provenance_read_from_profile_by_uri():
    from spectra import config as scfg
    from spectra.services import testbed_marks
    profile = {
        "spotify_uri": URI, "title": "T", "artist": "A", "duration_ms": 1000,
        "verified": True, "ai_generated": False,
        "triggers": [{"timestamp_ms": 1, "event_id": "e1"},
                     {"timestamp_ms": 2, "event_id": "e2"}],
    }
    (scfg.PROFILES_DIR / "A - T.json").write_text(json.dumps(profile), encoding="utf-8")

    prov = testbed_marks.provenance_for(URI)
    assert prov.found is True
    assert prov.verified is True
    assert prov.ai_generated is False
    assert prov.editor_trigger_count == 2


def test_known_uris_only_lists_songs_with_stored_triggers():
    from spectra.services import testbed_marks
    _write_trigger(URI, 1000, "fire_scene")
    assert URI in testbed_marks.known_uris()
    assert "spotify:track:neverplaced" not in testbed_marks.known_uris()
