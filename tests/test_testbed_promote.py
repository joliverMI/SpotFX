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


def _promote(timestamp_ms, action=None, **kw):
    from spectra.services import testbed_promote
    return testbed_promote.promote(
        uri=URI, timestamp_ms=timestamp_ms, action=action or _fire_response_action(),
        source_engine="beat_this", source_mark_kind="downbeat", confirmed=True, **kw,
    )


def test_confirming_the_same_suggestion_twice_lands_one_trigger_and_refuses_by_name():
    """The dialog closes on success and the mark is still there to click:
    a second confirm must never stack a second trigger on the same tick."""
    from spectra.services import testbed_promote, trigger_store
    first = _promote(5000)
    with pytest.raises(testbed_promote.PromotionDuplicate) as excinfo:
        _promote(5000)
    assert "already exists" in str(excinfo.value)
    assert first["trigger_id"] in str(excinfo.value)

    stored = trigger_store.list_for_song(URI)
    assert [t.id for t in stored] == [first["trigger_id"]]

    log = testbed_promote.log_for_song(URI)
    assert [e["status"] for e in log] == ["promoted", "refused"]
    assert log[-1]["reason"] == "duplicate"
    assert log[-1]["existing_trigger_id"] == first["trigger_id"]
    assert "already exists" in log[-1]["detail"]


def test_duplicate_window_is_a_few_hundred_ms_not_exact_equality():
    from spectra.services import testbed_promote, trigger_store
    _promote(5000)
    with pytest.raises(testbed_promote.PromotionDuplicate):
        _promote(5000 + testbed_promote.DUPLICATE_WINDOW_MS)
    _promote(5000 + testbed_promote.DUPLICATE_WINDOW_MS + 1)
    assert sorted(t.timestamp_ms for t in trigger_store.list_for_song(URI)) == \
        [5000, 5000 + testbed_promote.DUPLICATE_WINDOW_MS + 1]


def test_a_different_action_kind_at_the_same_moment_is_not_a_duplicate():
    from spectra.services import trigger_store
    _promote(5000)
    _promote(5000, action={"kind": "fire_scene_update", "intensity": 0.4})
    kinds = sorted(t.action.kind for t in trigger_store.list_for_song(URI))
    assert kinds == ["fire_response", "fire_scene_update"]


def test_a_generated_trigger_at_the_same_moment_does_not_block_a_promotion():
    """Only AUTHORED triggers guard the moment — a machine-generated row
    is exactly what a promotion may be there to replace with his own."""
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    trigger_store.upsert(URI, SpectraTrigger(
        timestamp_ms=5000, action={"kind": "fire_response", "event_class": "flare"},
        source="generated", generator_key="section:5000"))
    result = _promote(5000)
    assert result["status"] == "promoted"
    sources = sorted(t.source for t in trigger_store.list_for_song(URI))
    assert sources == ["authored", "generated"]


def _meet_at_every_read(monkeypatch, parties=2, timeout_s=0.3):
    """Slow every triggers.json read so that two writers which are NOT
    serialised meet inside their read-modify-write window (both read, then
    both write). A writer that IS serialised arrives at the read alone,
    waits out the barrier once, and every later read passes straight
    through — so the same fixture reproduces the race unlocked and stays
    cheap locked."""
    import threading
    from spectra.services import trigger_store
    gate = threading.Barrier(parties)
    real_load = trigger_store._load_raw

    def slow_load():
        data = real_load()
        try:
            gate.wait(timeout=timeout_s)
        except threading.BrokenBarrierError:
            pass
        return data
    monkeypatch.setattr(trigger_store, "_load_raw", slow_load)


def test_two_concurrent_confirms_of_one_moment_land_exactly_one_trigger(monkeypatch):
    """Two tabs, one double-tap: both confirms are in flight on worker
    threads at once. The duplicate check and the write are one critical
    section, so exactly one lands and the other is refused by name — never
    two authored triggers on the same tick, and never a lost write."""
    import threading
    from spectra.services import testbed_promote, trigger_store
    _meet_at_every_read(monkeypatch)

    outcomes: list = []

    def confirm():
        try:
            outcomes.append(_promote(5000))
        except testbed_promote.PromotionDuplicate as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=confirm) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=10)
    assert not any(th.is_alive() for th in threads)

    promoted = [o for o in outcomes if isinstance(o, dict)]
    refused = [o for o in outcomes if isinstance(o, testbed_promote.PromotionDuplicate)]
    assert len(promoted) == 1 and len(refused) == 1
    stored = trigger_store.list_for_song(URI)
    assert [t.id for t in stored] == [promoted[0]["trigger_id"]]
    assert promoted[0]["trigger_id"] in str(refused[0])

    statuses = sorted(e["status"] for e in testbed_promote.log_for_song(URI))
    assert statuses == ["promoted", "refused"]


def test_a_malformed_log_never_turns_a_landed_write_into_a_500():
    """_record appends AFTER trigger_store.upsert has landed the trigger.
    A promotions.json that parses to something other than a list used to
    raise there: the write stood, the audit trail had no entry for it, and
    his retry was then refused as a duplicate."""
    import json
    from spectra import config as scfg
    from spectra.services import testbed_promote, trigger_store
    scfg.TESTBED_PROMOTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    scfg.TESTBED_PROMOTIONS_FILE.write_text(json.dumps({"oops": True}),
                                            encoding="utf-8")

    result = testbed_promote.promote(
        uri=URI, timestamp_ms=5000, action=_fire_response_action(),
        source_engine="beat_this", source_mark_kind="downbeat", confirmed=True)

    assert result["status"] == "promoted"
    assert [t.id for t in trigger_store.list_for_song(URI)] == [result["trigger_id"]]
    log = testbed_promote.log_for_song(URI)
    assert [e["status"] for e in log] == ["promoted"]
    assert log[0]["trigger_id"] == result["trigger_id"]



def test_promoted_ids_name_only_landed_pushes():
    """The audit log is the ONLY provenance a promoted trigger has (its
    source/generator_key are deliberately indistinguishable from a
    hand-placed one), so these two lookups are what testbed_marks uses to
    keep a pushed mark out of the scoring set."""
    import pytest as _pytest
    from spectra.services import testbed_promote
    landed = testbed_promote.promote(
        uri=URI, timestamp_ms=5000, action=_fire_response_action(),
        source_engine="beat_this", source_mark_kind="downbeat", confirmed=True)
    with _pytest.raises(testbed_promote.PromotionNotConfirmed):
        testbed_promote.promote(
            uri=URI, timestamp_ms=9000, action=_fire_response_action(),
            source_engine="beat_this", source_mark_kind="downbeat", confirmed=False)

    assert testbed_promote.promoted_trigger_ids(URI) == {landed["trigger_id"]}
    assert testbed_promote.promoted_trigger_ids("spotify:track:other") == set()
    assert testbed_promote.promoted_ids_by_uri() == {URI: {landed["trigger_id"]}}


def test_a_promoted_trigger_carries_no_generator_key():
    """generator_key is midsong_generator's own matching key; a
    "testbed:..." value there would put a non-generated row into the space
    a generated one is identified by. Provenance lives in the log."""
    from spectra.services import testbed_promote, trigger_store
    testbed_promote.promote(
        uri=URI, timestamp_ms=5000, action=_fire_response_action(),
        source_engine="beat_this", source_mark_kind="downbeat", confirmed=True)
    stored = trigger_store.list_for_song(URI)[0]
    assert stored.source == "authored"
    assert stored.generator_key is None
