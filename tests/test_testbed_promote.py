"""spectra/services/testbed_promote.py — the review-gated push-to-real.
Proves the structural claim in the definition of done: a suggestion cannot
reach storage/spectra/triggers.json without confirmed=True, and every
attempt (accepted or refused) is durably logged."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "TESTBED_PROMOTIONS_FILE", tmp_path / "promotions.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")


URI = "spotify:track:testbedpromote1"


def _fire_response_action():
    return {"kind": "fire_response", "event_class": "flare", "intensity": 0.7}


def test_unconfirmed_promotion_writes_nothing_and_raises():
    from spectra.services import testbed_promote, trigger_store
    with pytest.raises(testbed_promote.PromotionNotConfirmed):
        testbed_promote.promote(
            uri=URI, timestamp_ms=5000, action=_fire_response_action(),
            source_engine="beat_this", source_mark_kind="downbeat",
            confirmed=False,
        )
    assert trigger_store.list_for_song(URI) == []


def test_unconfirmed_attempt_is_still_logged_as_refused():
    from spectra.services import testbed_promote
    with pytest.raises(testbed_promote.PromotionNotConfirmed):
        testbed_promote.promote(
            uri=URI, timestamp_ms=5000, action=_fire_response_action(),
            source_engine="beat_this", source_mark_kind="downbeat",
            confirmed=False,
        )
    log = testbed_promote.log_for_song(URI)
    assert len(log) == 1
    assert log[0]["status"] == "refused"
    assert log[0]["reason"] == "not_confirmed"


def test_confirmed_promotion_lands_an_authored_fired_copy_trigger():
    from spectra.services import testbed_promote, trigger_store
    result = testbed_promote.promote(
        uri=URI, timestamp_ms=5000, action=_fire_response_action(),
        source_engine="beat_this", source_mark_kind="downbeat",
        confirmed=True,
    )
    assert result["status"] == "promoted"
    stored = trigger_store.list_for_song(URI)
    assert len(stored) == 1
    trig = stored[0]
    assert trig.id == result["trigger_id"]
    assert trig.timestamp_ms == 5000
    assert trig.source == "authored"          # never "generated"
    assert trig.generator_key is None         # front 3's rule stays clean
    assert trig.action.kind == "fire_response"


def test_confirmed_promotion_is_logged_with_full_provenance():
    from spectra.services import testbed_promote
    testbed_promote.promote(
        uri=URI, timestamp_ms=7000, action=_fire_response_action(),
        source_engine="beat_this", source_mark_kind="downbeat",
        confirmed=True,
    )
    log = testbed_promote.log_for_song(URI)
    assert len(log) == 1
    assert log[0]["status"] == "promoted"
    assert log[0]["source_engine"] == "beat_this"
    assert log[0]["source_mark_kind"] == "downbeat"
    assert "trigger_id" in log[0]


def test_invalid_reference_refuses_even_when_confirmed():
    """Same reference-integrity check the human-authoring POST applies
    (trigger_store.validate_action) -- confirmed=True is not a bypass."""
    from spectra.services import testbed_promote, trigger_store
    action = {"kind": "fire_scene", "scene_id": "does-not-exist"}
    with pytest.raises(trigger_store.InvalidTriggerAction):
        testbed_promote.promote(
            uri=URI, timestamp_ms=1000, action=action,
            source_engine="librosa", source_mark_kind="section_boundary",
            confirmed=True,
        )
    assert trigger_store.list_for_song(URI) == []
    log = testbed_promote.log_for_song(URI)
    assert log[-1]["status"] == "refused"


def test_promotion_offset_carries_through():
    from spectra.services import testbed_promote, trigger_store
    testbed_promote.promote(
        uri=URI, timestamp_ms=5000, action=_fire_response_action(),
        source_engine="beat_this", source_mark_kind="downbeat",
        confirmed=True, trigger_offset_ms=-150,
    )
    trig = trigger_store.list_for_song(URI)[0]
    assert trig.trigger_offset_ms == -150
