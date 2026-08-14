"""Proof for spectra.services.legacy_trigger_migration — the real-data
mapper, now covering the full ruling on the Admiral's five-bucket rule
(RULING.md, data/spectra-trigger-migration-scoping/report.md):

  - response buckets (flare/charge/lull/drop): unaffected, 7,164 of 10,710.
  - scene-change bucket: ALL of it maps to fire_scene(scene_id=None) —
    Option B, built, not re-argued. "Drop scene" triggers (DROP_SCENE_IDS)
    get intensity forced to MAX.
  - update bucket (fixed-update-scene / fixed-reset-scene, one behaviour —
    reset IS update per his correction): maps to fire_scene_update, now
    that UPDATE is built (spectra.services.scene_response.ResponseEngine.
    on_update, spectra.models.trigger.FireSceneUpdateAction).
  - RETIRED: Dinner Party Scenes — scrapped at his word. Never mapped,
    never written, in any mode.

The hard invariant every write-path test here protects: `migrate(apply=True)`
must write mapped triggers and ONLY mapped triggers — retired, unclassified,
and invalid-timestamp triggers must never reach the live SPECTRA store, no
matter how they're mixed into the same source file.
"""
from __future__ import annotations

import json

import pytest

from spectra import config as scfg
from spectra.models.trigger import SpectraTrigger
from spectra.services import trigger_store
from spectra.services.legacy_trigger_migration import (
    DROP_SCENE_IDS,
    LEDGER,
    MAX_INTENSITY,
    RESPONSE_BUCKETS,
    RETIRED_IDS,
    SCENE_CHANGE_BUCKET,
    UPDATE_BUCKET,
    UPDATE_IDS,
    classify,
    map_scene_change,
    map_trigger,
    map_unambiguous,
    map_update,
    migrate,
)

INTENSITY_SCENE_ID = "37b62a98-3544-4157-a444-ac605b146039"
DROP_GROUP_ID = "030ccfab-5f3f-4c8c-8556-80e366309153"
DINNER_PARTY_SCENES_ID = "164df939-217e-4081-a2d3-dc523cb5eca3"


@pytest.fixture(autouse=True)
def _isolated_triggers_file(tmp_path, monkeypatch):
    # Nested under tmp_path so it never collides with a test's own
    # `tmp_path / "*.json"` legacy-profile glob (non-recursive).
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "_spectra_store" / "triggers.json")


def _legacy_trigger(event_id: str, *, timestamp_ms=1000, intensity=0.7,
                     trigger_id="t-1", enabled=True) -> dict:
    return {
        "id": trigger_id,
        "timestamp_ms": timestamp_ms,
        "event_id": event_id,
        "labels": [],
        "enabled": enabled,
        "intensity": intensity,
        "override_blend": False,
        "color_group_override": None,
        "display_mode": "default",
        "drop_scene_group_override": None,
    }


def _write_profile(path, uri: str, triggers: list[dict], setlist_triggers=None):
    path.write_text(json.dumps({
        "spotify_uri": uri,
        "title": "Test Song",
        "artist": "Test Artist",
        "artist_genre": [],
        "duration_ms": 200_000,
        "labels": [],
        "verified": False,
        "notes": "",
        "intensity_scale": None,
        "intensity_scale_source": None,
        "triggers": triggers,
        "setlist_triggers": setlist_triggers or {},
        "audio_shape_file": None,
        "ai_generated": False,
        "ai_training_profile_id": "",
        "ai_generated_date": "",
        "ai_model": "",
        "embedded_generated": False,
    }))


# ── ledger shape ─────────────────────────────────────────────────────────

def test_ledger_covers_the_full_real_corpus():
    """Pinned against the scout's live-corpus count: 28 ids in the base
    10,710-trigger corpus + 7 setlist-only ids. A ledger entry going
    missing is exactly the kind of silent regression this pin exists to
    catch."""
    assert len(LEDGER) == 35
    assert {e.bucket for e in LEDGER.values()} == {
        "flare", "charge", "drop", "lull", "scene change", "update"}


def test_ledger_status_matches_the_ruling():
    statuses = {e.event_id: e.status for e in LEDGER.values()}
    assert statuses["fixed-update-scene"] == "mapped"
    assert statuses["fixed-reset-scene"] == "mapped"
    assert statuses[DINNER_PARTY_SCENES_ID] == "retired"
    mapped = {eid for eid, s in statuses.items() if s == "mapped"}
    assert UPDATE_IDS <= mapped   # UPDATE is built — both ids are mapped now
    assert RETIRED_IDS.isdisjoint(mapped)
    assert INTENSITY_SCENE_ID in mapped
    assert DROP_GROUP_ID in mapped


def test_update_ids_are_update_bucket():
    for eid in UPDATE_IDS:
        entry = classify(eid)
        assert entry is not None, eid
        assert entry.bucket == UPDATE_BUCKET


def test_drop_scene_ids_are_all_scene_change_bucket():
    for eid in DROP_SCENE_IDS:
        entry = classify(eid)
        assert entry is not None, eid
        assert entry.bucket == SCENE_CHANGE_BUCKET


def test_every_judgment_call_carries_a_recorded_reason():
    for entry in LEDGER.values():
        if entry.judgment:
            assert entry.reason, f"{entry.event_id} ({entry.name}) has no recorded reason"


# ── classify() ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("event_id,expected_class", [
    ("fixed-charge", "charge"),
    ("fixed-lull", "lull"),
    ("fixed-drop", "drop"),
    ("fixed-shape-flare", "flare"),
    ("fixed-combo-flare", "flare"),
    ("fixed-color-flare", "flare"),
])
def test_classify_exact_fixed_sentinels(event_id, expected_class):
    entry = classify(event_id)
    assert entry is not None
    assert entry.bucket == expected_class
    assert entry.judgment is False
    assert entry.status == "mapped"


def test_classify_unknown_event_id_returns_none_not_a_guess():
    assert classify("00000000-0000-0000-0000-000000000000") is None


# ── map_unambiguous(): response buckets ─────────────────────────────────

@pytest.mark.parametrize("event_id", [
    "fixed-charge", "fixed-lull", "fixed-drop",
    "fixed-shape-flare", "fixed-combo-flare", "fixed-color-flare",
])
def test_map_unambiguous_produces_a_valid_spectra_trigger(event_id):
    legacy = _legacy_trigger(event_id, intensity=0.42, trigger_id="abc-123", timestamp_ms=54321)
    out = map_unambiguous(legacy)
    assert out is not None
    validated = SpectraTrigger.model_validate(out)
    assert validated.id == "abc-123"
    assert validated.timestamp_ms == 54321
    assert validated.source == "authored"
    assert validated.generator_key is None
    assert validated.action.kind == "fire_response"
    assert validated.action.intensity == pytest.approx(0.42)
    assert validated.action.event_class == classify(event_id).bucket


def test_map_unambiguous_returns_none_for_scene_change():
    assert map_unambiguous(_legacy_trigger(INTENSITY_SCENE_ID)) is None


def test_map_unambiguous_returns_none_for_update():
    assert map_unambiguous(_legacy_trigger("fixed-update-scene")) is None


def test_every_response_bucket_ledger_entry_maps_and_validates():
    for entry in LEDGER.values():
        if entry.bucket not in RESPONSE_BUCKETS:
            continue
        out = map_unambiguous(_legacy_trigger(entry.event_id, trigger_id=f"trig-{entry.event_id}"))
        assert out is not None, entry.event_id
        SpectraTrigger.model_validate(out)


# ── map_scene_change(): Option B, the drop-scene MAX override, and the two carve-outs ──

def test_map_scene_change_is_option_b_scene_id_none():
    legacy = _legacy_trigger(INTENSITY_SCENE_ID, intensity=0.63, trigger_id="s-1", timestamp_ms=9999)
    out = map_scene_change(legacy)
    assert out is not None
    validated = SpectraTrigger.model_validate(out)
    assert validated.action.kind == "fire_scene"
    assert validated.action.scene_id is None
    assert validated.action.color_set_id is None
    assert validated.action.intensity == pytest.approx(0.63)
    assert validated.source == "authored"


@pytest.mark.parametrize("drop_scene_id", sorted(DROP_SCENE_IDS))
def test_map_scene_change_forces_max_intensity_for_drop_scenes(drop_scene_id):
    legacy = _legacy_trigger(drop_scene_id, intensity=0.1)  # recorded intensity deliberately low
    out = map_scene_change(legacy)
    assert out is not None
    validated = SpectraTrigger.model_validate(out)
    assert validated.action.intensity == MAX_INTENSITY


def test_map_scene_change_uses_recorded_intensity_for_non_drop_scenes():
    legacy = _legacy_trigger(INTENSITY_SCENE_ID, intensity=0.22)
    out = map_scene_change(legacy)
    assert SpectraTrigger.model_validate(out).action.intensity == pytest.approx(0.22)


def test_map_scene_change_returns_none_for_retired_dinner_party_scenes():
    assert classify(DINNER_PARTY_SCENES_ID).status == "retired"
    assert map_scene_change(_legacy_trigger(DINNER_PARTY_SCENES_ID)) is None


def test_map_scene_change_returns_none_for_update_bucket():
    assert map_scene_change(_legacy_trigger("fixed-update-scene")) is None


def test_map_scene_change_returns_none_for_response_bucket_id():
    assert map_scene_change(_legacy_trigger("fixed-charge")) is None


# ── map_update(): reset IS update, one behaviour ─────────────────────────

@pytest.mark.parametrize("update_id", sorted(UPDATE_IDS))
def test_map_update_produces_fire_scene_update(update_id):
    legacy = _legacy_trigger(update_id, intensity=0.81, trigger_id="u-1", timestamp_ms=4200)
    out = map_update(legacy)
    assert out is not None
    validated = SpectraTrigger.model_validate(out)
    assert validated.id == "u-1"
    assert validated.timestamp_ms == 4200
    assert validated.source == "authored"
    assert validated.action.kind == "fire_scene_update"
    assert validated.action.intensity == pytest.approx(0.81)


def test_map_update_returns_none_for_non_update_bucket():
    assert map_update(_legacy_trigger(INTENSITY_SCENE_ID)) is None
    assert map_update(_legacy_trigger("fixed-charge")) is None


def test_map_update_returns_none_for_retired_id():
    assert map_update(_legacy_trigger(DINNER_PARTY_SCENES_ID)) is None


# ── map_trigger(): the one dispatch entry point ─────────────────────────

def test_map_trigger_dispatches_all_three_shapes():
    assert map_trigger(_legacy_trigger("fixed-drop"))["action"]["kind"] == "fire_response"
    assert map_trigger(_legacy_trigger(INTENSITY_SCENE_ID))["action"]["kind"] == "fire_scene"
    assert map_trigger(_legacy_trigger("fixed-update-scene"))["action"]["kind"] == "fire_scene_update"
    assert map_trigger(_legacy_trigger("fixed-reset-scene"))["action"]["kind"] == "fire_scene_update"


def test_map_trigger_returns_none_for_retired():
    assert map_trigger(_legacy_trigger(DINNER_PARTY_SCENES_ID)) is None


def test_map_trigger_returns_none_for_unclassified_id():
    assert map_trigger(_legacy_trigger("some-future-event-not-in-the-ledger")) is None


# ── migrate(): the write-path invariants ────────────────────────────────

def test_migrate_dry_run_writes_nothing(tmp_path):
    profile = tmp_path / "song.json"
    _write_profile(profile, "spotify:track:abc", [
        _legacy_trigger("fixed-charge", trigger_id="c1"),
        _legacy_trigger(INTENSITY_SCENE_ID, trigger_id="s1"),
        _legacy_trigger("fixed-update-scene", trigger_id="u1"),
        _legacy_trigger(DINNER_PARTY_SCENES_ID, trigger_id="d1"),
    ])

    summary = migrate(str(tmp_path / "*.json"), apply=False)

    assert summary.mapped == 3       # c1 (response) + s1 (scene change) + u1 (update)
    assert summary.retired == 1      # d1
    assert summary.written == 0
    assert not scfg.TRIGGERS_FILE.exists()


def test_migrate_apply_writes_mapped_triggers_only(tmp_path):
    """The hard invariant: a source file mixing every category, migrated
    with --apply, must leave the live store holding EXACTLY the mapped
    (response + scene-change + update) triggers — nothing retired,
    unclassified, or with an invalid timestamp, no matter how it's mixed
    in with mapped ones in the same file. This is the whole-pass proof:
    his 236 update/reset triggers land in the SAME migration as everything
    else, not a later one."""
    profile = tmp_path / "mixed_song.json"
    _write_profile(profile, "spotify:track:mixed", [
        _legacy_trigger("fixed-charge", trigger_id="a"),
        _legacy_trigger("fixed-lull", trigger_id="b"),
        _legacy_trigger("fixed-drop", trigger_id="c"),
        _legacy_trigger("fixed-shape-flare", trigger_id="d"),
        _legacy_trigger(INTENSITY_SCENE_ID, trigger_id="scene-a", intensity=0.5),
        _legacy_trigger(DROP_GROUP_ID, trigger_id="scene-b", intensity=0.1),
        _legacy_trigger("fixed-update-scene", trigger_id="update-a", intensity=0.6),
        _legacy_trigger("fixed-reset-scene", trigger_id="update-b", intensity=0.4),
        _legacy_trigger(DINNER_PARTY_SCENES_ID, trigger_id="retired-a"),
        _legacy_trigger("totally-unknown-id", trigger_id="unk-a"),
        _legacy_trigger("fixed-charge", trigger_id="bad-ts", timestamp_ms=-500),
    ])

    summary = migrate(str(tmp_path / "*.json"), apply=True)

    assert summary.mapped == 8
    assert summary.written == 8
    assert summary.retired == 1
    assert summary.unclassified == 1
    assert summary.invalid_timestamp == 1
    assert summary.drop_scene_max_intensity == 1
    assert summary.by_class == {"flare": 1, "charge": 1, "lull": 1, "drop": 1,
                                "scene change": 2, "update": 2}

    written = trigger_store.list_for_song("spotify:track:mixed")
    written_ids = {t.id for t in written}
    assert written_ids == {"a", "b", "c", "d", "scene-a", "scene-b",
                           "update-a", "update-b"}
    for excluded in ("retired-a", "unk-a", "bad-ts"):
        assert excluded not in written_ids

    by_id = {t.id: t for t in written}
    assert by_id["scene-a"].action.kind == "fire_scene"
    assert by_id["scene-a"].action.scene_id is None
    assert by_id["scene-a"].action.intensity == pytest.approx(0.5)
    # drop scene: recorded intensity (0.1) overridden to MAX
    assert by_id["scene-b"].action.intensity == MAX_INTENSITY
    assert by_id["update-a"].action.kind == "fire_scene_update"
    assert by_id["update-a"].action.intensity == pytest.approx(0.6)
    assert by_id["update-b"].action.kind == "fire_scene_update"
    assert by_id["update-b"].action.intensity == pytest.approx(0.4)


def test_migrate_apply_is_idempotent(tmp_path):
    profile = tmp_path / "song.json"
    _write_profile(profile, "spotify:track:idem", [
        _legacy_trigger("fixed-drop", trigger_id="d1", timestamp_ms=9000, intensity=0.9),
        _legacy_trigger(INTENSITY_SCENE_ID, trigger_id="s1", timestamp_ms=9500, intensity=0.4),
        _legacy_trigger("fixed-update-scene", trigger_id="u1", timestamp_ms=9700, intensity=0.5),
    ])

    migrate(str(tmp_path / "*.json"), apply=True)
    first_pass = json.loads(scfg.TRIGGERS_FILE.read_text())

    migrate(str(tmp_path / "*.json"), apply=True)
    second_pass = json.loads(scfg.TRIGGERS_FILE.read_text())

    assert first_pass == second_pass
    assert len(second_pass["spotify:track:idem"]) == 3


def test_migrate_never_mutates_the_legacy_source_file(tmp_path):
    profile = tmp_path / "song.json"
    _write_profile(profile, "spotify:track:readonly", [
        _legacy_trigger("fixed-charge", trigger_id="c1"),
        _legacy_trigger(INTENSITY_SCENE_ID, trigger_id="s1"),
        _legacy_trigger("fixed-update-scene", trigger_id="u1"),
    ])
    before = profile.read_text()

    migrate(str(tmp_path / "*.json"), apply=True)

    assert profile.read_text() == before


def test_migrate_counts_setlist_only_when_asked(tmp_path):
    profile = tmp_path / "song.json"
    _write_profile(profile, "spotify:track:sl", [
        _legacy_trigger("fixed-charge", trigger_id="base-1"),
    ], setlist_triggers={
        "setlist-1": [_legacy_trigger("fixed-lull", trigger_id="sl-1")],
    })

    base_only = migrate(str(tmp_path / "*.json"), apply=False, include_setlist=False)
    assert base_only.total == 1

    with_setlist = migrate(str(tmp_path / "*.json"), apply=False, include_setlist=True)
    assert with_setlist.total == 2


def test_migrate_flags_invalid_timestamp_without_crashing(tmp_path):
    profile = tmp_path / "song.json"
    _write_profile(profile, "spotify:track:preroll", [
        _legacy_trigger(INTENSITY_SCENE_ID, trigger_id="preroll-1", timestamp_ms=-1050, intensity=0.05),
        _legacy_trigger(INTENSITY_SCENE_ID, trigger_id="normal-1", timestamp_ms=500, intensity=0.05),
    ])

    summary = migrate(str(tmp_path / "*.json"), apply=True)

    assert summary.invalid_timestamp == 1
    assert summary.invalid_timestamp_examples[0]["id"] == "preroll-1"
    assert summary.mapped == 1
    written_ids = {t.id for t in trigger_store.list_for_song("spotify:track:preroll")}
    assert written_ids == {"normal-1"}


def test_migrate_real_corpus_lands_whole_in_one_pass():
    """The real 10,710-trigger corpus, dry-run, read-only: every trigger is
    either mapped or a deliberate exclusion (retired / invalid timestamp) —
    zero unclassified, zero blocked. This is the "lands whole in one pass"
    proof against the actual data, not a synthetic fixture."""
    import pathlib
    real_profiles = pathlib.Path("/home/javi/SpotFX/storage/profiles")
    if not real_profiles.is_dir():
        pytest.skip("live checkout not present in this environment")
    summary = migrate(str(real_profiles / "*.json"), apply=False)
    assert summary.total == 10710
    assert summary.unclassified == 0
    assert summary.retired == 5
    assert summary.invalid_timestamp == 5
    assert summary.mapped == 10700
    assert summary.by_class["update"] == 236
