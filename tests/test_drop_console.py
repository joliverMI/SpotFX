"""SONIC'S DROPS DOMAIN (spectra/services/drop_console.py): the playing
song's drop sequences named by number in song order, confirmed, dismissed
and moved through the same edits the Timeline makes. Synthetic sequences;
the store is isolated per test by conftest's _isolated_drop_sequences."""
from __future__ import annotations

import asyncio

import pytest

URI = "spotify:track:dropsonic1"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import drop_console
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(drop_console, "_current_uri", lambda: URI)


def _detected(drops):
    from spectra.services import drop_detector as dd
    from spectra.services import drop_sequences as ds

    def fn(entry):
        entry["detected"] = {
            "uri": URI, "detector_version": dd.DETECTOR_VERSION, "confident_score": 1.0,
            "suggested_score": 0.7, "tempo_bpm": 120.0, "beat_ms": 500.0,
            "captured_from_ms": 0, "captured_to_ms": 200_000, "duration_ms": 200_000,
            "stamp": "t", "excluded": [],
            "sequences": [{"key": dd.drop_key(d), "drop_ms": d, "lull_ms": lu, "charge_ms": ch,
                           "score": 1.2, "tier": t, "break_beats": 3.0, "step": 1.0,
                           "rise": 0.9, "path": "step", "loud_before": True, "capped": False,
                           "notes": []} for d, lu, ch, t in drops]}
    ds._mutate(URI, fn)


def _run(name, **kw):
    from spectra.services import settings_agent as sa
    return asyncio.run(sa._dispatch(name, kw))


def test_list_numbers_the_sequences_in_song_order():
    _detected([(90_000, 86_000, 80_000, "suggested"), (44_000, 40_000, 35_000, "confident")])
    out = _run("list_drop_sequences")
    assert out["status"] == "ok"
    assert [(s["number"], s["drop_s"], s["state"]) for s in out["sequences"]] == [
        (1, 44.0, "confident"), (2, 90.0, "suggested")]


def test_list_surfaces_whether_each_sequence_fires_right_now():
    """Build item D4's own named gap: the list showed state and times but
    never whether a sequence actually fires under the room's current
    scene-change tier — read via drop_firing.annotate, same verdict the
    Timeline shows."""
    _detected([(44_000, 40_000, 35_000, "confident"),
              (90_000, 86_000, 80_000, "confident")])
    out = _run("list_drop_sequences")
    for seq in out["sequences"]:
        assert "fires" in seq and isinstance(seq["fires"], bool)
        assert "fires_reason" in seq

    # a sequence standing down on his own triggers reads fires=False,
    # fires_reason="matches_yours" — the one verdict this test can assert
    # without depending on the room's own scene-change default.
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    trigger_store.upsert(URI, SpectraTrigger(
        timestamp_ms=44_050, action={"kind": "fire_response", "event_class": "drop"}))
    out = _run("list_drop_sequences")
    matched = next(s for s in out["sequences"] if s["drop_s"] == 44.0)
    assert matched["fires"] is False and matched["fires_reason"] == "matches_yours"


def test_confirm_all_dismiss_and_move_by_beats():
    from spectra.services import drop_sequences as ds
    _detected([(44_000, 40_000, 35_000, "confident"), (90_000, 86_000, 80_000, "suggested")])
    out = _run("confirm_drop_sequence", sequence="all")
    assert out["status"] == "applied" and "1 confident" in out["summary"]
    assert ds.stored(URI)["overrides"]["drop:44000"]["state"] == "confirmed"
    out = _run("move_drop_handle", sequence=2, handle="drop", by_beats=-1)
    assert out["status"] == "applied"
    assert ds.stored(URI)["overrides"]["drop:90000"]["drop_ms"] == 89_500
    out = _run("dismiss_drop_sequence", sequence=2)
    assert out["status"] == "applied"
    # a dismissed one leaves the numbering
    assert [s["drop_s"] for s in _run("list_drop_sequences")["sequences"]] == [44.0]


def test_a_number_that_names_nothing_is_rejected_with_the_list_never_guessed():
    from spectra.services import drop_sequences as ds
    _detected([(44_000, 40_000, 35_000, "confident")])
    out = _run("confirm_drop_sequence", sequence=3)
    assert out["status"] == "rejected" and len(out["sequences"]) == 1
    # the rejection's embedded list is built off the plain, un-annotated
    # view (never checked against drop_firing) — it must not fabricate a
    # fires/fires_reason verdict nothing actually computed
    assert "fires" not in out["sequences"][0]
    assert "fires_reason" not in out["sequences"][0]
    out = _run("move_drop_handle", sequence=1, handle="lull", by_beats=10)
    assert out["status"] == "rejected" and "before" in out["reason"]
    out = _run("move_drop_handle", sequence=1, handle="lull")
    assert out["status"] == "rejected"
    assert "overrides" not in ds.stored(URI)


def test_a_sequence_on_his_own_triggers_is_not_edited_here():
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    _detected([(44_000, 40_000, 35_000, "confident")])
    trigger_store.upsert(URI, SpectraTrigger(
        timestamp_ms=44_050, action={"kind": "fire_response", "event_class": "drop"}))
    out = _run("confirm_drop_sequence", sequence=1)
    assert out["status"] == "rejected" and "triggers strip" in out["reason"]


def test_nothing_playing_and_no_uri_is_a_stated_rejection(monkeypatch):
    from spectra.services import drop_console
    monkeypatch.setattr(drop_console, "_current_uri", lambda: None)
    assert _run("list_drop_sequences")["status"] == "rejected"


# ═══ build item B — finishing the drop-edit set (2026-10-06 Sonic coverage
# audit): add, member on/off, revert, review, undo, redetect, summary ═══

def test_add_drop_sequence_with_explicit_lull_and_charge():
    from spectra.services import drop_sequences as ds

    out = _run("add_drop_sequence", drop_seconds=60.0, lull_seconds=55.0,
              charge_seconds=50.0)
    assert out["status"] == "applied"
    assert "60.0" in out["summary"]
    seqs = ds.view(URI)["sequences"]
    assert len(seqs) == 1
    assert seqs[0]["origin"] == "added"
    assert seqs[0]["drop_ms"] == 60_000
    assert seqs[0]["lull_ms"] == 55_000
    assert seqs[0]["charge_ms"] == 50_000


def test_add_drop_sequence_rejects_non_numeric_seconds():
    out = _run("add_drop_sequence", drop_seconds="soon")
    assert out["status"] == "rejected"


def test_set_drop_member_switches_an_existing_handle_off_then_back_on():
    from spectra.services import drop_sequences as ds
    _detected([(44_000, 40_000, 35_000, "confident")])

    out = _run("set_drop_member", sequence=1, handle="lull", on=False)
    assert out["status"] == "applied" and "off" in out["summary"]
    seqs = ds.view(URI)["sequences"]
    assert seqs[0]["lull_off"] is True
    assert seqs[0]["lull_ms"] is None
    # list_drop_sequences reports lull_off/charge_off (build item B5)
    listed = _run("list_drop_sequences")["sequences"][0]
    assert listed["lull_off"] is True and listed["charge_off"] is False

    out = _run("set_drop_member", sequence=1, handle="lull", on=True)
    assert out["status"] == "applied" and "added" in out["summary"]
    seqs = ds.view(URI)["sequences"]
    assert seqs[0]["lull_off"] is False
    assert seqs[0]["lull_ms"] == 40_000


def test_set_drop_member_refuses_to_switch_off_a_handle_already_off():
    _detected([(44_000, 40_000, 35_000, "confident")])
    _run("set_drop_member", sequence=1, handle="lull", on=False)
    out = _run("set_drop_member", sequence=1, handle="lull", on=False)
    assert out["status"] == "rejected"


def test_set_drop_member_refuses_to_switch_on_a_handle_already_present():
    _detected([(44_000, 40_000, 35_000, "confident")])
    out = _run("set_drop_member", sequence=1, handle="lull", on=True)
    assert out["status"] == "rejected" and "already has" in out["reason"]


def test_set_drop_member_adds_a_handle_that_was_never_there_via_placement(monkeypatch):
    from spectra.services import drop_sequences as ds

    monkeypatch.setattr(ds, "_place", lambda uri, entry, handle, drop_ms, lull_ms: drop_ms - 4_000)
    _run("add_drop_sequence", drop_seconds=60.0)
    seqs = ds.view(URI)["sequences"]
    assert seqs[0]["lull_ms"] is None

    out = _run("set_drop_member", sequence=1, handle="lull", on=True)
    assert out["status"] == "applied"
    seqs = ds.view(URI)["sequences"]
    assert seqs[0]["lull_ms"] == 56_000


def test_revert_drop_sequence_forgets_edits_to_a_detected_one():
    from spectra.services import drop_sequences as ds
    _detected([(44_000, 40_000, 35_000, "confident")])
    _run("move_drop_handle", sequence=1, handle="drop", by_beats=-1)
    assert "overrides" in ds.stored(URI) and ds.stored(URI)["overrides"]

    out = _run("revert_drop_sequence", sequence=1)
    assert out["status"] == "applied" and "back to detected" in out["summary"]
    assert not ds.stored(URI).get("overrides")


def test_resolve_drop_review_keep_and_take():
    from spectra.services import drop_sequences as ds
    _detected([(44_000, 40_000, 35_000, "confident")])
    _run("confirm_drop_sequence", sequence=1)
    # re-detect under a shifted moment so the confirmed sequence needs review
    _detected([(44_900, 40_000, 35_000, "confident")])
    listed = _run("list_drop_sequences")["sequences"]
    assert any(s["needs_review"] for s in listed)
    n = next(s["number"] for s in listed if s["needs_review"])

    out = _run("resolve_drop_review", sequence=n, choice="keep")
    assert out["status"] == "applied" and "kept" in out["summary"]

    out = _run("resolve_drop_review", sequence=n, choice="bogus")
    assert out["status"] == "rejected"


def test_undo_drop_edit_puts_back_sonics_own_last_edit():
    from spectra.services import drop_sequences as ds
    _detected([(44_000, 40_000, 35_000, "confident")])
    _run("confirm_drop_sequence", sequence=1)
    assert ds.stored(URI)["overrides"]["drop:44000"]["state"] == "confirmed"

    out = _run("undo_drop_edit")
    assert out["status"] == "applied"
    assert not ds.stored(URI).get("overrides")


def test_undo_drop_edit_refuses_when_nothing_tracked():
    out = _run("undo_drop_edit")
    assert out["status"] == "rejected" and "nothing to undo" in out["reason"]


def test_undo_drop_edit_refuses_when_the_timeline_edited_since(monkeypatch):
    from spectra.services import drop_sequences as ds
    _detected([(44_000, 40_000, 35_000, "confident")])
    _run("confirm_drop_sequence", sequence=1)
    # a Timeline (non-Sonic) edit lands in between
    ds.apply_edit(URI, "dismiss", key="drop:44000")

    out = _run("undo_drop_edit")
    assert out["status"] == "rejected"


def test_redetect_drop_sequences_reruns_detection(monkeypatch):
    from spectra.services import drop_sequences as ds

    calls = []

    def fake_ensure(uri, force=False):
        calls.append((uri, force))
        return {"uri": uri, "status": "detected", "stamp": "x", "sequences": 2}

    monkeypatch.setattr(ds, "ensure_detected", fake_ensure)
    out = _run("redetect_drop_sequences")
    assert out["status"] == "applied"
    assert calls == [(URI, True)]
    assert "2 sequence" in out["summary"]


def test_redetect_drop_sequences_reports_unavailable_as_rejected(monkeypatch):
    from spectra.services import drop_sequences as ds

    monkeypatch.setattr(ds, "ensure_detected",
                        lambda uri, force=False: {"uri": uri, "status": "unavailable",
                                                  "reason": "no audio shape yet"})
    out = _run("redetect_drop_sequences")
    assert out["status"] == "rejected" and "no audio shape yet" in out["reason"]


def test_drop_detection_summary_counts_songs():
    _detected([(44_000, 40_000, 35_000, "confident")])
    out = _run("drop_detection_summary")
    assert out["status"] == "ok"
    assert len(out["songs"]) == 1
    assert out["songs"][0]["uri"] == URI
    assert "1 song" in out["summary"]


def test_every_apply_edit_op_has_a_sonic_operation_or_is_acknowledged():
    """Build item B8: every op name drop_sequences.apply_edit accepts must
    be reachable from a Sonic operation, or named here as a deliberate
    gap — never silently missing."""
    from spectra.services import drop_console as dc

    APPLY_EDIT_OPS = {"confirm", "dismiss", "revert", "handles", "member",
                      "review", "fill", "add", "confirm_all", "restore"}
    # restore is reached only through undo_drop_edit (never a raw
    # arbitrary-edits-dict pass-through — that stays the Timeline's own
    # undo/redo, which can replay any prior state; Sonic only ever
    # restores its OWN last tracked edit).
    ACKNOWLEDGED_INDIRECT = {"restore"}
    reachable_ops = {
        "confirm", "dismiss", "handles", "member", "review", "fill", "add",
        "confirm_all", "revert",
    }
    assert APPLY_EDIT_OPS - ACKNOWLEDGED_INDIRECT <= reachable_ops
    # and every Sonic drops write op actually exists
    for name in ("add_drop_sequence", "set_drop_member", "revert_drop_sequence",
                "resolve_drop_review", "undo_drop_edit", "redetect_drop_sequences"):
        assert name in dc.OPERATIONS


def test_drops_domain_appears_in_the_meta_domain_enum():
    """The audit's stale finding #3: 'drops' was missing from
    list_operations' own domain enum, so the model was told it wasn't a
    legal filter even though the handler always accepted it."""
    from spectra.services import settings_agent as sa

    assert "drops" in sa._DOMAIN_NAMES
    schema = sa.ALL_OPERATIONS["list_operations"].tool_schema()
    assert "drops" in schema["input_schema"]["properties"]["domain"]["enum"]
