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
