"""HIS TRIGGER EDITS REACH HIS SHOW — the invariants of the two-copy sync.

Proves the four standing decisions in spectra/services/profile_trigger_sync.py
hold as CODE, not as prose: authored material only, generated never crosses,
deletes are provenance-gated, negative timestamps are preserved and reported.
Plus the regression that matters most — a real profile save through the real
spot-effects endpoint lands in the real fired copy.
"""
from __future__ import annotations

import json
import uuid

import pytest

from spectra import config as scfg
from spectra.models.trigger import SpectraTrigger
from spectra.services import (legacy_trigger_migration as ltm,
                              profile_sync_ledger, profile_trigger_sync as sync,
                              trigger_store)

URI = "spotify:track:test-sync"
FLARE = "fixed-shape-flare"          # LEDGER: response bucket -> fire_response
SCENE = "37b62a98-3544-4157-a444-ac605b146039"   # "Intensity Scene" -> fire_scene
RETIRED = "164df939-217e-4081-a2d3-dc523cb5eca3"  # Dinner Party Scenes — scrapped
DROP_SCENE = "030ccfab-5f3f-4c8c-8556-80e366309153"  # intensity forced to MAX


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "PROFILE_SYNC_LEDGER_FILE",
                        tmp_path / "profile_sync_ledger.json")


def legacy(event_id=FLARE, ts=1000, intensity=0.5, enabled=True, tid=None) -> dict:
    return {"id": tid or str(uuid.uuid4()), "timestamp_ms": ts,
            "event_id": event_id, "labels": [], "enabled": enabled,
            "intensity": intensity}


def fired_row(t: SpectraTrigger) -> dict:
    return json.loads(t.model_dump_json())


def plan(profile, fired=(), known=None):
    return sync.plan_song(URI, list(profile), list(fired), dict(known or {}))


# ── 1. his edits actually cross ───────────────────────────────────────────────

def test_a_new_profile_trigger_lands_in_the_fired_copy():
    t = legacy(ts=42_000, intensity=0.9)
    p = plan([t])
    assert [x.id for x in p.upserts] == [t["id"]]
    assert p.upserts[0].timestamp_ms == 42_000
    assert p.upserts[0].action.kind == "fire_response"
    assert p.upserts[0].action.intensity == pytest.approx(0.9)
    assert p.upserts[0].source == "authored"


def test_an_edited_timestamp_or_intensity_overwrites_the_stale_fired_row():
    """Decision 1: the copy being saved wins. This is his actual bug — 128
    rows in his live corpus disagreed on exactly these two fields."""
    t = legacy(ts=1000, intensity=0.2)
    stale = fired_row(SpectraTrigger.model_validate(ltm.map_trigger(t)))
    edited = dict(t, timestamp_ms=5000, intensity=0.8)
    p = plan([edited], [stale])
    assert len(p.upserts) == 1 and p.deletes == []
    assert p.upserts[0].timestamp_ms == 5000
    assert p.upserts[0].action.intensity == pytest.approx(0.8)


def test_an_unchanged_trigger_is_not_rewritten():
    """A stored row predating a later-added model field must not read as a
    change — otherwise every save rewrites his whole 11k corpus."""
    t = legacy()
    row = fired_row(SpectraTrigger.model_validate(ltm.map_trigger(t)))
    row.pop("trigger_offset_ms", None)          # the pre-field shape on disk
    row["action"].pop("scene_pool", None)
    p = plan([t], [row])
    assert p.upserts == [] and p.deletes == [] and p.unchanged == 1


def test_a_spectra_only_field_survives_a_profile_save():
    """trigger_offset_ms is his SPECTRA-side drag; the legacy trigger cannot
    express it, so a profile save must carry it forward, not reset it."""
    t = legacy()
    stored = SpectraTrigger.model_validate(ltm.map_trigger(t)).model_copy(
        update={"trigger_offset_ms": -250, "timestamp_ms": 9})
    p = plan([t], [fired_row(stored)])
    assert len(p.upserts) == 1
    assert p.upserts[0].trigger_offset_ms == -250
    assert p.upserts[0].timestamp_ms == 1000        # the profile still won


# ── 2. generated triggers never cross, either way ─────────────────────────────

def test_generated_triggers_are_never_touched_and_never_written_back():
    gen = fired_row(SpectraTrigger(
        id="gen-1", timestamp_ms=7000, source="generated",
        generator_key="section:7000",
        action={"kind": "fire_scene", "intensity": 0.4}))
    t = legacy(ts=1000)
    p = plan([t], [gen])
    assert p.generated_untouched == 1
    assert "gen-1" not in [x.id for x in p.upserts]
    assert "gen-1" not in p.deletes
    assert "gen-1" not in p.protected      # not "protected" either — invisible
    rp = sync.plan_reverse(URI, [t], [gen], {})
    assert rp.edits == []


# ── 3. deletes are provenance-gated ───────────────────────────────────────────

def test_a_card_born_trigger_is_never_deleted_by_a_profile_save():
    """18 of his live authored triggers exist only in the fired copy. A
    profile save that has never seen them must leave every one alone."""
    card = fired_row(SpectraTrigger(id="card-1", timestamp_ms=3000,
                                    action={"kind": "fire_response",
                                            "event_class": "flare"}))
    p = plan([legacy()], [card])
    assert p.deletes == []
    assert p.protected == ["card-1"]


def test_a_profile_deletion_propagates_only_once_provenance_is_known():
    t = legacy(ts=1000)
    row = fired_row(SpectraTrigger.model_validate(ltm.map_trigger(t)))
    # First sync: the trigger is in both copies — provenance is established.
    first = plan([t], [row])
    assert first.provenance == {t["id"]: FLARE}
    # He deletes it in the editor and saves again.
    second = plan([], [row], known=first.provenance)
    assert second.deletes == [t["id"]]
    assert second.protected == []
    # Without that provenance the same shape is refused.
    blind = plan([], [row])
    assert blind.deletes == [] and blind.protected == [t["id"]]


def test_a_retired_event_takes_its_stale_fired_row_with_it():
    """Decision 4: a retired event must never keep firing. Only a
    provenance-known row is removed."""
    t = legacy(event_id=RETIRED, ts=5900)
    row = fired_row(SpectraTrigger(id=t["id"], timestamp_ms=5900,
                                   action={"kind": "fire_response",
                                           "event_class": "flare"}))
    p = plan([t], [row], known={t["id"]: FLARE})
    assert p.upserts == []
    assert p.deletes == [t["id"]]
    assert [s.reason for s in p.skipped] == [sync.SKIP_RETIRED]
    unknown = plan([t], [row])
    assert unknown.deletes == [] and unknown.skipped[0].reason == sync.SKIP_RETIRED


# ── 4. negative timestamps: preserved and reported, never clamped ─────────────

def test_a_negative_timestamp_is_reported_and_never_written_or_clamped():
    """5 of his real triggers carry a -50ms..-1950ms pre-roll that
    SpectraTrigger's `timestamp_ms >= 0` cannot express."""
    t = legacy(event_id=SCENE, ts=-1950)
    p = plan([t])
    assert p.upserts == []
    assert len(p.skipped) == 1
    s = p.skipped[0]
    assert s.reason == sync.SKIP_NEGATIVE_TIMESTAMP
    assert s.timestamp_ms == -1950          # reported as authored, not as 0
    assert t["timestamp_ms"] == -1950       # his profile dict is untouched


def test_an_unclassified_event_id_is_reported_never_guessed():
    p = plan([legacy(event_id="not-in-the-ledger")])
    assert p.upserts == []
    assert p.skipped[0].reason == sync.SKIP_UNCLASSIFIED


# ── 5. the batched write, and the ledger it maintains ─────────────────────────

def test_apply_plan_is_one_write_and_lands_exactly_the_plan():
    t1, t2 = legacy(ts=1000), legacy(ts=2000)
    trigger_store.upsert(URI, SpectraTrigger(
        id="card-1", timestamp_ms=9, action={"kind": "fire_response",
                                             "event_class": "flare"}))
    writes = []
    orig = trigger_store._save_raw
    trigger_store._save_raw = lambda d: (writes.append(1), orig(d))[1]
    try:
        summary = sync.apply_plan(plan([t1, t2], trigger_store._load_raw().get(URI, [])))
    finally:
        trigger_store._save_raw = orig
    assert writes == [1], "a whole song's sync must be ONE triggers.json write"
    ids = {t.id for t in trigger_store.list_for_song(URI)}
    assert ids == {t1["id"], t2["id"], "card-1"}
    assert summary["written"] == 2 and summary["deleted"] == 0
    assert profile_sync_ledger.for_song(profile_sync_ledger.load(), URI) == {
        t1["id"]: FLARE, t2["id"]: FLARE}


def test_a_full_round_trip_deletes_only_what_he_deleted():
    t1, t2 = legacy(ts=1000), legacy(ts=2000)
    card = SpectraTrigger(id="card-1", timestamp_ms=9,
                          action={"kind": "fire_response", "event_class": "flare"})
    trigger_store.upsert(URI, card)
    sync.apply_plan(plan([t1, t2], trigger_store._load_raw().get(URI, [])))
    known = profile_sync_ledger.for_song(profile_sync_ledger.load(), URI)
    sync.apply_plan(plan([t1], trigger_store._load_raw().get(URI, []), known=known))
    assert {t.id for t in trigger_store.list_for_song(URI)} == {t1["id"], "card-1"}


# ── 6. reverse: faithful fields only, never a lossy write ─────────────────────

def test_reverse_writes_only_the_three_faithful_fields_in_place():
    t = legacy(ts=1000, intensity=0.3)
    raw_profile = {"triggers": [dict(t, labels=["keep-me"], override_blend=True,
                                     color_group_override="grp-1")]}
    moved = fired_row(SpectraTrigger.model_validate(ltm.map_trigger(t)).model_copy(
        update={"timestamp_ms": 4321}))
    moved["action"]["intensity"] = 0.77
    rp = sync.plan_reverse(URI, raw_profile["triggers"], [moved], {t["id"]: FLARE})
    assert len(rp.edits) == 1
    assert set(rp.edits[0].changes) == {"timestamp_ms", "intensity"}
    assert sync.apply_reverse(rp, raw_profile) == 1
    out = raw_profile["triggers"][0]
    assert out["timestamp_ms"] == 4321 and out["intensity"] == pytest.approx(0.77)
    # every other legacy field byte-identical — no model round-trip
    assert out["labels"] == ["keep-me"] and out["override_blend"] is True
    assert out["color_group_override"] == "grp-1"


def test_reverse_never_writes_back_a_forced_max_intensity():
    """A drop-scene trigger's fired intensity is MAX by his own ruling, not
    his recorded number — writing it back would destroy what he authored."""
    t = legacy(event_id=DROP_SCENE, ts=1000, intensity=0.25)
    mapped = ltm.map_trigger(t)
    assert mapped["action"]["intensity"] == 1.0
    rp = sync.plan_reverse(URI, [t], [fired_row(SpectraTrigger.model_validate(mapped))],
                           {t["id"]: DROP_SCENE})
    assert rp.edits == []


def test_reverse_skips_a_card_born_trigger_and_a_changed_action_kind():
    card = fired_row(SpectraTrigger(id="card-1", timestamp_ms=3000,
                                    action={"kind": "select_color_set",
                                            "set_id": "s1"}))
    rp = sync.plan_reverse(URI, [], [card], {})
    assert rp.edits == [] and rp.skipped_unknown_origin == ["card-1"]

    t = legacy(ts=1000)      # profile says flare; the card now says scene
    changed = fired_row(SpectraTrigger(id=t["id"], timestamp_ms=1000,
                                       action={"kind": "fire_scene"}))
    rp2 = sync.plan_reverse(URI, [t], [changed], {t["id"]: FLARE})
    assert rp2.edits == [] and rp2.skipped_lossy == [t["id"]]
