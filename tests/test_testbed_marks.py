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
    monkeypatch.setattr(scfg, "TESTBED_PROMOTIONS_FILE", tmp_path / "promotions.json")
    monkeypatch.setattr(scfg, "TESTBED_PROMOTED_IDS_FILE", tmp_path / "promoted_ids.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    (tmp_path / "profiles").mkdir()


URI = "spotify:track:testbedmarks1"


def _write_trigger(uri, timestamp_ms, kind, **action_extra):
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    action = {"kind": kind, **action_extra}
    trigger_store.upsert(uri, SpectraTrigger(timestamp_ms=timestamp_ms, action=action))


def _write_generated(uri, timestamp_ms, kind="fire_scene", **action_extra):
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    trigger_store.upsert(uri, SpectraTrigger(
        timestamp_ms=timestamp_ms, action={"kind": kind, **action_extra},
        source="generated", generator_key=f"section:{timestamp_ms}"))


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

    prov = testbed_marks.marks_for_song(URI).provenance
    assert prov.found is True
    assert prov.verified is True
    assert prov.ai_generated is False
    assert prov.editor_trigger_count == 2


def test_generated_triggers_are_never_reference_marks_but_are_counted():
    """midsong_generator seeds a fire_scene at every librosa section
    boundary — the librosa engine's own section_boundary times. If those
    counted as his marks, librosa would score itself; they are excluded
    from BOTH lists and reported as n_generated instead."""
    from spectra.services import testbed_marks
    _write_trigger(URI, 1000, "fire_scene")
    _write_trigger(URI, 3000, "fire_response", event_class="flare")
    _write_generated(URI, 20000)
    _write_generated(URI, 45000)
    _write_generated(URI, 46000, kind="fire_response", event_class="flare")

    marks = testbed_marks.marks_for_song(URI)
    assert [m.timestamp_ms for m in marks.transitions] == [1000]
    assert [m.timestamp_ms for m in marks.flares] == [3000]
    assert marks.n_generated == 3

    transitions, flares = testbed_marks.reference_marks_for_song(URI)
    assert [m.timestamp_ms for m in transitions] == [1000]
    assert [m.timestamp_ms for m in flares] == [3000]


def test_a_generated_only_song_stays_listed_with_nothing_to_compare_against():
    from spectra.services import testbed_marks
    generated_only = "spotify:track:generatedonly"
    _write_generated(generated_only, 20000)
    _write_generated(generated_only, 40000)
    _write_trigger(URI, 1000, "fire_scene")

    listing = testbed_marks.all_song_marks()
    assert set(listing) == {URI, generated_only}
    assert listing[generated_only].transitions == []
    assert listing[generated_only].flares == []
    assert listing[generated_only].n_generated == 2
    assert listing[URI].n_generated == 0


def _write_profile(scfg, uri, filename, **fields):
    profile = {"spotify_uri": uri, "title": "T", "artist": "A", "duration_ms": 1000,
               "verified": False, "ai_generated": False, "triggers": [], **fields}
    (scfg.PROFILES_DIR / filename).write_text(json.dumps(profile), encoding="utf-8")


def test_all_song_marks_agrees_with_per_song_reads_and_carries_title_artist():
    """Title/artist/provenance still agree between the listing and the
    per-song read for an old-authored-only song — only its reference
    marks (transitions/flares) deliberately diverge, since the listing (not
    marks_for_song) is the one that stops treating his old rows as "work
    to review" (all_song_marks()'s own docstring)."""
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
    assert list(listing) == sorted([URI, other])
    for uri, marks in listing.items():
        single = testbed_marks.marks_for_song(uri)
        assert marks.transitions == []
        assert marks.flares == []
        assert single.transitions != [] or single.flares != []
        assert marks.provenance == single.provenance
        assert (marks.title, marks.artist) == (single.title, single.artist)
        assert marks.n_generated == single.n_generated
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


def _push_from_the_testbed(uri, timestamp_ms, kind="fire_scene", **action_extra):
    """A mark that reached the corpus through push-to-real — the real
    write path, so the promotion log is the real one too."""
    from spectra.services import testbed_promote
    result = testbed_promote.promote(
        uri=uri, timestamp_ms=timestamp_ms,
        action={"kind": kind, **action_extra},
        source_engine="beat_this", source_mark_kind="downbeat", confirmed=True)
    return result["trigger_id"]


def test_a_pushed_mark_is_flagged_shown_and_left_out_of_the_scoring_set():
    """The circularity guard: a promoted mark sits at the suggesting
    engine's own exact time, so scoring against it grades that engine on
    its own suggestion. It stays visible (flagged), the number leaves it
    out."""
    from spectra.services import testbed_marks
    _write_trigger(URI, 1000, "fire_scene")
    pushed = _push_from_the_testbed(URI, 20000)

    marks = testbed_marks.marks_for_song(URI)
    by_id = {m.id: m for m in marks.transitions}
    assert set(by_id) == {pushed} | {m.id for m in marks.transitions if m.id != pushed}
    assert len(marks.transitions) == 2
    assert by_id[pushed].promoted is True
    assert [m.promoted for m in marks.transitions if m.id != pushed] == [False]
    assert marks.n_promoted == 1

    transitions, _flares = testbed_marks.reference_marks_for_song(URI)
    assert [m.timestamp_ms for m in transitions] == [1000]


def test_a_hand_placed_mark_is_never_flagged_promoted():
    """His own marks keep counting exactly as before — nothing on the
    trigger distinguishes them, so an over-broad rule would silently drop
    real ground truth."""
    from spectra.services import testbed_marks
    _write_trigger(URI, 1000, "fire_scene")
    _write_trigger(URI, 2000, "fire_response", event_class="flare")
    marks = testbed_marks.marks_for_song(URI)
    assert [m.promoted for m in marks.transitions] == [False]
    assert [m.promoted for m in marks.flares] == [False]
    assert marks.n_promoted == 0
    transitions, flares = testbed_marks.reference_marks_for_song(URI)
    assert len(transitions) == 1 and len(flares) == 1


def test_a_refused_promotion_never_marks_anything_as_promoted():
    """Only a LANDED promotion carries a trigger_id; a refusal must not
    make some unrelated authored row read as pushed."""
    import pytest as _pytest
    from spectra.services import testbed_marks, testbed_promote
    _write_trigger(URI, 1000, "fire_scene")
    with _pytest.raises(testbed_promote.PromotionNotConfirmed):
        testbed_promote.promote(
            uri=URI, timestamp_ms=1000, action={"kind": "fire_scene"},
            source_engine="librosa", source_mark_kind="section_boundary",
            confirmed=False)
    marks = testbed_marks.marks_for_song(URI)
    assert marks.n_promoted == 0
    assert [m.promoted for m in marks.transitions] == [False]


def test_the_listing_resolves_promotions_per_song():
    """A promoted mark is still an old authored-door row (testbed_promote's
    own docstring: it lands source=="authored"), so it gets the same
    treatment every other old row now gets in the LIST — no reference
    marks, nothing promoted to show — even though marks_for_song (the
    per-song page) keeps showing it flagged exactly as before."""
    from spectra.services import testbed_marks
    other = "spotify:track:testbedmarks2"
    _write_trigger(URI, 1000, "fire_scene")
    pushed = _push_from_the_testbed(URI, 5000)
    _write_trigger(other, 1000, "fire_scene")

    rows = testbed_marks.all_song_marks()
    assert rows[URI].n_promoted == 0
    assert rows[URI].transitions == []
    assert rows[other].n_promoted == 0
    assert rows[other].transitions == []

    single = testbed_marks.marks_for_song(URI)
    assert {m.id for m in single.transitions if m.promoted} == {pushed}
    assert single.n_promoted == 1


def _write_analyzed(scfg, track_id, training_profile_id, triggers):
    scfg.ANALYZED_TRIGGERS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "track_id": track_id,
        "training_profile_id": training_profile_id,
        "training_profile_hash": "deadbeef",
        "generated_at": "2026-11-10T00:00:00+00:00",
        "triggers": triggers,
    }
    (scfg.ANALYZED_TRIGGERS_DIR / f"{track_id}.json").write_text(
        json.dumps(data), encoding="utf-8")


def _write_training_profile(scfg, profile_id, **event_ids):
    path = scfg.TRAINING_PROFILES_FILE
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    raw[profile_id] = {"id": profile_id, "name": "TP", **event_ids}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")


def test_an_analyzed_only_song_is_listed_and_scored_from_its_analyzed_triggers():
    """The 131-song gap: a song with NOTHING in trigger_store but a
    cached analyzed-trigger set (services/analyzed_trigger_store.py) must
    appear in the listing, split into transitions/flares by the same
    scene/flare role routers/ai_triggers_router.py applies at play time."""
    from spectra import config as scfg
    from spectra.services import testbed_marks
    track_id = "analyzedonly1"
    uri = f"spotify:track:{track_id}"
    _write_training_profile(scfg, "tp1", drop_event_id="drop", flare_event_id="spark")
    _write_analyzed(scfg, track_id, "tp1", [
        {"id": "a1", "timestamp_ms": 1000, "event_id": "drop", "labels": [], "intensity": None},
        {"id": "a2", "timestamp_ms": 2000, "event_id": "spark", "labels": [], "intensity": 0.5},
    ])

    listing = testbed_marks.all_song_marks()
    assert uri in listing
    assert [m.timestamp_ms for m in listing[uri].transitions] == [1000]
    assert [m.timestamp_ms for m in listing[uri].flares] == [2000]

    single = testbed_marks.marks_for_song(uri)
    assert single.transitions == listing[uri].transitions
    assert single.flares == listing[uri].flares

    transitions, flares = testbed_marks.reference_marks_for_song(uri)
    assert [m.timestamp_ms for m in transitions] == [1000]
    assert [m.timestamp_ms for m in flares] == [2000]


def test_analyzed_drop_lull_charge_marks_carry_event_class_and_are_found_by_phase_marks():
    """An analyzed drop/lull/charge event_id (the song's own training
    profile names it) must be findable by phase_marks()'s event_class
    filter — the Drops lane's reference set — exactly like an authored
    fire_response carrying that event_class already is."""
    from spectra import config as scfg
    from spectra.services import testbed_marks
    track_id = "analyzedphases1"
    uri = f"spotify:track:{track_id}"
    _write_training_profile(scfg, "tp1", drop_event_id="drop", lull_event_id="lull",
                            charge_event_id="charge", flare_event_id="spark")
    _write_analyzed(scfg, track_id, "tp1", [
        {"id": "a1", "timestamp_ms": 1000, "event_id": "drop", "labels": [], "intensity": None},
        {"id": "a2", "timestamp_ms": 2000, "event_id": "lull", "labels": [], "intensity": None},
        {"id": "a3", "timestamp_ms": 3000, "event_id": "charge", "labels": [], "intensity": None},
        {"id": "a4", "timestamp_ms": 4000, "event_id": "spark", "labels": [], "intensity": 0.5},
    ])

    marks = testbed_marks.marks_for_song(uri)
    assert marks.phase_classes_available is True
    all_marks = marks.transitions + marks.flares
    assert [m.timestamp_ms for m in testbed_marks.phase_marks(all_marks, "drops")] == [1000]
    assert [m.timestamp_ms for m in testbed_marks.phase_marks(all_marks, "lulls")] == [2000]
    assert [m.timestamp_ms for m in testbed_marks.phase_marks(all_marks, "charges")] == [3000]
    assert testbed_marks.phase_marks(all_marks, "drops")[0].event_class == "drop"


def test_analyzed_song_with_missing_training_profile_has_phase_classes_unavailable():
    """A cache whose training_profile_id no longer resolves to a stored
    profile (deleted/renamed since the cache was written) cannot be
    classified into drop/lull/charge/flare at all — every mark falls back
    to a flare with no event_class, and the song is flagged as
    phase_classes_available=False rather than reading as a confident
    'no drops here'."""
    from spectra import config as scfg
    from spectra.services import testbed_marks
    track_id = "analyzedorphan1"
    uri = f"spotify:track:{track_id}"
    _write_analyzed(scfg, track_id, "nonexistent-profile", [
        {"id": "a1", "timestamp_ms": 1000, "event_id": "drop", "labels": [], "intensity": None},
    ])

    marks = testbed_marks.marks_for_song(uri)
    assert marks.phase_classes_available is False
    assert [m.timestamp_ms for m in marks.flares] == [1000]
    assert marks.flares[0].event_class is None


def test_analyzed_triggers_win_over_old_triggers_for_the_same_song():
    """A song carrying BOTH an old authored trigger and a cached analyzed
    set is listed from the analyzed set only — his old placement is no
    longer "work to review" once an analyzed alternative exists for the
    same song (the Admiral: old triggers "shouldn't be part of any future
    work")."""
    from spectra import config as scfg
    from spectra.services import testbed_marks
    track_id = "bothkinds1"
    uri = f"spotify:track:{track_id}"
    _write_trigger(uri, 9999, "fire_scene")
    _write_training_profile(scfg, "tp1", flare_event_id="spark")
    _write_analyzed(scfg, track_id, "tp1", [
        {"id": "a1", "timestamp_ms": 2000, "event_id": "spark", "labels": [], "intensity": None},
    ])

    listing = testbed_marks.all_song_marks()
    assert [m.timestamp_ms for m in listing[uri].flares] == [2000]
    assert listing[uri].transitions == []
    assert 9999 not in [m.timestamp_ms for m in listing[uri].flares + listing[uri].transitions]


def test_an_old_authored_only_song_has_no_work_to_review_in_the_listing():
    """No analyzed cache, only his old hand-placed triggers: the song stays
    listed (its audio/pin/engine status is still useful) but the listing
    itself shows no reference marks — the Admiral's old triggers are no
    longer "work" for the song LIST, even though the per-song page
    (marks_for_song) is left untouched."""
    from spectra.services import testbed_marks
    _write_trigger(URI, 1000, "fire_scene")
    _write_trigger(URI, 2000, "fire_response", event_class="flare")

    listing = testbed_marks.all_song_marks()
    assert URI in listing
    assert listing[URI].transitions == []
    assert listing[URI].flares == []

    single = testbed_marks.marks_for_song(URI)
    assert len(single.transitions) == 1
    assert len(single.flares) == 1
