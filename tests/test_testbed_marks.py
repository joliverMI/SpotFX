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


def _write_profile(scfg, uri, filename, **fields):
    profile = {"spotify_uri": uri, "title": "T", "artist": "A", "duration_ms": 1000,
               "verified": False, "ai_generated": False, "triggers": [], **fields}
    (scfg.PROFILES_DIR / filename).write_text(json.dumps(profile), encoding="utf-8")


def test_all_song_marks_agrees_with_per_song_reads_and_carries_title_artist():
    from spectra import config as scfg
    from spectra.services import testbed_marks
    other = "spotify:track:testbedmarks2"
    _write_trigger(URI, 1000, "fire_scene")
    _write_trigger(URI, 3000, "fire_response", event_class="flare")
    _write_trigger(other, 500, "fire_scene_update")
    _write_profile(scfg, URI, "A - T.json", title="Dopamine", artist="Purple Disco",
                   verified=True, ai_generated=True,
                   triggers=[{"timestamp_ms": 1, "event_id": "e1"}])

    listing = testbed_marks.all_song_marks()
    assert list(listing) == testbed_marks.known_uris() == sorted([URI, other])
    for uri, marks in listing.items():
        single = testbed_marks.marks_for_song(uri)
        assert marks.transitions == single.transitions
        assert marks.flares == single.flares
        assert marks.provenance == single.provenance
        assert (marks.title, marks.artist) == (single.title, single.artist)
    assert (listing[URI].title, listing[URI].artist) == ("Dopamine", "Purple Disco")
    assert listing[URI].provenance.ai_generated is True
    assert listing[URI].provenance.editor_trigger_count == 1
    assert (listing[other].title, listing[other].artist) == (None, None)
    assert listing[other].provenance.found is False


def test_all_song_marks_reads_the_trigger_store_once_and_never_scans_profiles_per_song(monkeypatch):
    """The whole point of the listing shape: N stored songs cost ONE
    triggers.json parse and ONE profile-directory pass, not N of each."""
    from spectra import config as scfg
    from spectra.services import testbed_marks, trigger_store
    uris = [f"spotify:track:bulk{i}" for i in range(5)]
    for i, uri in enumerate(uris):
        _write_trigger(uri, 1000 * (i + 1), "fire_scene")
        _write_profile(scfg, uri, f"bulk{i}.json", title=f"Song {i}")

    loads = []
    real_load = trigger_store._load_raw
    monkeypatch.setattr(trigger_store, "_load_raw",
                        lambda: loads.append(1) or real_load())

    def _per_song_scan(uri):
        raise AssertionError(f"per-song profile scan for {uri}")
    monkeypatch.setattr(testbed_marks, "_find_profile", _per_song_scan)

    listing = testbed_marks.all_song_marks()
    assert len(loads) == 1
    assert [m.title for m in listing.values()] == [f"Song {i}" for i in range(5)]
