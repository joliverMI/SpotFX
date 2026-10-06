"""The drop-sequence store (spectra/services/drop_sequences.py): detection
on first play and on a stale stamp, and the plan's "How edits are kept,
and what wins" table — each row a test. Synthetic songs only; the store
is isolated per test by conftest's _isolated_drop_sequences."""
from __future__ import annotations

import asyncio
import json

import pytest

import drop_synth

URI = "spotify:track:dropseq1"
BEAT = 500.0


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    drop_synth.reset_index()
    yield
    drop_synth.reset_index()


def _song(**kw):
    from spectra import config as scfg
    return drop_synth.one_drop_song(scfg.AUDIO_SHAPES_DIR, URI, **kw)


def _set_detected(drops: list[tuple[int, int | None, int | None]], *,
                  tier: str = "confident") -> None:
    """Store a detection directly — the merge is pure over the entry, so a
    re-detection that MOVED a drop is modelled by replacing this."""
    from spectra.services import drop_detector as dd
    from spectra.services import drop_sequences as ds

    def fn(entry):
        entry["detected"] = {
            "uri": URI, "detector_version": dd.DETECTOR_VERSION,
            "confident_score": 1.0, "suggested_score": 0.7,
            "tempo_bpm": 120.0, "beat_ms": BEAT, "captured_from_ms": 0,
            "captured_to_ms": 200_000, "duration_ms": 200_000, "stamp": "test",
            "sequences": [
                {"key": dd.drop_key(d), "drop_ms": d, "lull_ms": lu, "charge_ms": ch,
                 "score": 1.2, "tier": tier, "break_beats": 3.0, "step": 1.0,
                 "rise": 0.9, "path": "step", "loud_before": True, "capped": False,
                 "notes": []}
                for d, lu, ch in drops],
            "excluded": [],
        }
    ds._mutate(URI, fn)


def _view():
    from spectra.services import drop_sequences as ds
    return ds.view(URI)


def _only(view):
    seqs = [s for s in view["sequences"]]
    assert len(seqs) == 1, seqs
    return seqs[0]


def _his(timestamp_ms, kind, event_class=None, enabled=True):
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    action = ({"kind": "fire_response", "event_class": event_class}
              if kind == "fire_response" else {"kind": kind})
    trigger_store.upsert(URI, SpectraTrigger(timestamp_ms=timestamp_ms, action=action,
                                             enabled=enabled))


# ── detection on first play / stale stamp ─────────────────────────────────

def test_detects_once_then_holds_until_the_stamp_goes_stale():
    from spectra.services import drop_sequences as ds
    from spectra.services import room_controls
    _song()
    first = ds.ensure_detected(URI)
    assert first["status"] == "detected" and first["sequences"] == 1
    assert ds.ensure_detected(URI)["status"] == "fresh"
    stamp = ds.stored(URI)["detected"]["stamp"]
    # a threshold change is a settings change: stale, re-detected
    controls = room_controls.load_room_controls().model_copy(
        update={"drop_confident_score": 1.6})
    room_controls.save_room_controls(controls)
    again = ds.ensure_detected(URI)
    assert again["status"] == "detected" and again["stamp"] != stamp
    assert ds.stored(URI)["detected"]["sequences"][0]["tier"] == "suggested"


def test_a_reanalysis_of_the_song_is_stale_but_a_rewritten_identical_file_is_not():
    from spectra import config as scfg
    from spectra.services import drop_sequences as ds
    stem = _song()
    ds.ensure_detected(URI)
    path = scfg.AUDIO_SHAPES_DIR / f"{stem}.librosa.json"
    doc = json.loads(path.read_text())
    path.write_text(json.dumps(doc))                  # same content, new file time
    drop_synth.reset_index()
    assert ds.ensure_detected(URI)["status"] == "fresh"
    doc["analyzed_at"] = "2026-10-06T00:00:00"
    path.write_text(json.dumps(doc))
    drop_synth.reset_index()
    assert ds.ensure_detected(URI)["status"] == "detected"


def test_redetection_never_touches_his_edits():
    from spectra.services import drop_sequences as ds
    _song()
    ds.ensure_detected(URI)
    key = ds.stored(URI)["detected"]["sequences"][0]["key"]
    ds.confirm(URI, key)
    added = ds.add(URI, 70_000, fill=False)
    from spectra.services import room_controls
    room_controls.save_room_controls(room_controls.load_room_controls().model_copy(
        update={"drop_suggested_score": 0.5}))
    assert ds.ensure_detected(URI)["status"] == "detected"
    entry = ds.stored(URI)
    assert entry["overrides"][key]["state"] == "confirmed"
    assert entry["added"][0]["id"] == added


def test_a_song_with_nothing_captured_is_unavailable_and_nothing_is_stored():
    from spectra.services import drop_sequences as ds
    out = ds.ensure_detected("spotify:track:none")
    assert out["status"] == "unavailable" and "no captured" in out["reason"]
    assert ds.stored("spotify:track:none") == {}


def test_the_song_change_edge_detects_off_the_loop_once():
    from spectra.services import drop_sequences as ds
    _song()
    calls = []
    real = ds.ensure_detected

    def counting(uri, controls=None):
        calls.append(uri)
        return real(uri, controls)

    async def run():
        ds.ensure_detected = counting
        try:
            ds.on_song_played(URI)
            ds.on_song_played(URI)              # in flight: not scheduled twice
            for _ in range(200):
                if not ds._in_flight:
                    break
                await asyncio.sleep(0.02)
        finally:
            ds.ensure_detected = real
    asyncio.run(run())
    assert calls == [URI]
    assert ds.stored(URI)["detected"]["sequences"]


# ── the plan's "How edits are kept, and what wins" table ─────────────────

def test_nothing_saved_for_an_untouched_detection():
    _set_detected([(44_000, 40_000, 35_000)])
    s = _only(_view())
    assert s["state"] == "confident" and s["origin"] == "detected"
    assert s["auto"] == {"charge_ms": 35_000, "lull_ms": 40_000, "drop_ms": 44_000}
    from spectra.services import drop_sequences as ds
    assert "overrides" not in ds.stored(URI)


def test_confirm_survives_a_small_move_and_asks_when_it_moves_more_than_a_beat():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)], tier="suggested")
    key = ds.confirm(URI, "drop:44000")
    assert key == "drop:44000"
    s = _only(_view())
    assert s["state"] == "confirmed" and not s["needs_review"]
    _set_detected([(44_300, 40_000, 35_000)], tier="suggested")   # < 1 beat
    s = _only(_view())
    assert s["state"] == "confirmed" and s["key"] == "drop:44000" and not s["needs_review"]
    assert s["detected_key"] == "drop:44300"
    _set_detected([(44_800, 40_000, 35_000)], tier="suggested")   # 1-2 beats
    s = _only(_view())
    assert s["state"] == "confirmed" and s["needs_review"]
    assert any("keep yours" in n for n in s["notes"])


def test_a_confirmed_drop_the_analysis_loses_stays_his():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    ds.confirm(URI, "drop:44000")
    _set_detected([(60_000, 57_000, 52_000)])     # far away: the old one is gone
    seqs = _view()["sequences"]
    lost = next(s for s in seqs if s["key"] == "drop:44000")
    assert lost["state"] == "confirmed" and lost["detection_lost"] and lost["needs_review"]
    assert (lost["charge_ms"], lost["lull_ms"], lost["drop_ms"]) == (35_000, 40_000, 44_000)
    assert next(s for s in seqs if s["key"] == "drop:60000")["state"] == "confident"


def test_a_dragged_handle_wins_and_the_others_stay_automatic():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    ds.set_handle(URI, "drop:44000", "lull", 41_000)
    s = _only(_view())
    assert s["state"] == "edited"
    assert (s["charge_ms"], s["lull_ms"], s["drop_ms"]) == (35_000, 41_000, 44_000)
    assert s["moved"] == {"charge": False, "lull": True, "drop": False}
    _set_detected([(44_100, 39_000, 36_000)])      # re-analysis moves the automatic ones
    s = _only(_view())
    assert s["lull_ms"] == 41_000                  # his time always wins
    assert (s["charge_ms"], s["drop_ms"]) == (36_000, 44_100)
    assert s["auto"]["lull_ms"] == 39_000          # the dotted line's place
    ds.set_handle(URI, "drop:44000", "lull", None)  # back to automatic for that handle
    assert _only(_view())["lull_ms"] == 39_000


def test_an_automatic_handle_that_no_longer_fits_his_is_left_out_and_said_so():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    ds.set_handle(URI, "drop:44000", "lull", 41_000)
    _set_detected([(44_000, 40_000, 40_900)])      # the automatic charge now sits past his lull
    s = _only(_view())
    assert s["charge_ms"] is None
    assert any("automatic charge left out" in n for n in s["notes"])


def test_order_is_enforced_on_every_edit():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    with pytest.raises(ds.InvalidEdit):
        ds.set_handle(URI, "drop:44000", "lull", 43_900)     # < 200 ms before the drop
    with pytest.raises(ds.InvalidEdit):
        ds.set_handle(URI, "drop:44000", "charge", 41_000)   # after the lull
    with pytest.raises(ds.InvalidEdit):
        ds.set_handle(URI, "drop:44000", "bridge", 1)
    with pytest.raises(ds.SequenceNotFound):
        ds.confirm(URI, "drop:99000")
    assert "overrides" not in ds.stored(URI)                  # nothing half-written


def test_lull_and_charge_can_be_switched_off():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    ds.set_member_off(URI, "drop:44000", "charge", True)
    s = _only(_view())
    assert s["state"] == "edited" and s["charge_ms"] is None and s["charge_off"]
    assert s["lull_ms"] == 40_000
    with pytest.raises(ds.InvalidEdit):
        ds.set_member_off(URI, "drop:44000", "drop", True)


def test_a_dismissal_blocks_a_redetection_within_two_beats_only():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    ds.dismiss(URI, "drop:44000")
    assert _only(_view())["state"] == "dismissed"
    _set_detected([(44_900, 40_000, 35_000)])      # within two beats: still not a drop
    assert _only(_view())["state"] == "dismissed"
    _set_detected([(46_500, 43_000, 38_000)])      # further: offered again
    seqs = _view()["sequences"]
    assert next(s for s in seqs if s["key"] == "drop:46500")["state"] == "confident"
    assert next(s for s in seqs if s["key"] == "drop:44000")["state"] == "dismissed"


def test_back_to_detected_forgets_every_edit():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    ds.set_handle(URI, "drop:44000", "drop", 44_200)
    assert ds.reset_to_detected(URI, "drop:44000")
    s = _only(_view())
    assert s["state"] == "confident" and s["drop_ms"] == 44_000
    assert not ds.reset_to_detected(URI, "drop:44000")


def test_an_added_sequence_is_his_whole_and_filled_from_the_song():
    from spectra.services import drop_sequences as ds
    _song()
    key = ds.add(URI, drop_synth.DROP_S * 1000)
    rec = ds.stored(URI)["added"][0]
    assert rec["id"] == key and key.startswith("added:")
    assert abs(rec["lull_ms"] - 40_000) <= BEAT and rec["charge_ms"] < rec["lull_ms"]
    ds.ensure_detected(URI)
    seqs = _view()["sequences"]
    added = next(s for s in seqs if s["key"] == key)
    assert added["state"] == "added" and added["origin"] == "added"
    ds.set_handle(URI, key, "charge", None)
    assert ds.stored(URI)["added"][0]["charge_ms"] is None
    with pytest.raises(ds.InvalidEdit):
        ds.add(URI, 50_000, lull_ms=49_900, fill=False)
    assert ds.remove_added(URI, key)
    assert "added" not in ds.stored(URI)


# ── his own triggers win ──────────────────────────────────────────────────

def test_a_detection_on_his_own_drop_stands_down_even_when_confirmed():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000), (90_000, 86_000, 80_000)])
    ds.confirm(URI, "drop:44000")
    _his(44_600, "fire_response", "drop")          # within two beats
    _his(90_200, "fire_response", "flare")         # a flare is not his drop
    seqs = {s["key"]: s for s in _view()["sequences"]}
    assert seqs["drop:44000"]["state"] == "matches_yours"
    assert [m["kind"] for m in seqs["drop:44000"]["matches"]] == ["drop"]
    assert seqs["drop:90000"]["state"] == "confident"
    assert [m["kind"] for m in seqs["drop:90000"]["his_marks_near"]] == ["flare"]


def test_a_disabled_trigger_of_his_does_not_stand_a_detection_down():
    _set_detected([(44_000, 40_000, 35_000)])
    _his(44_000, "fire_response", "drop", enabled=False)
    assert _only(_view())["state"] == "confident"


def test_his_own_sequences_are_grouped_for_the_timeline():
    _set_detected([])
    _his(30_000, "fire_response", "charge")
    _his(34_000, "fire_response", "lull")
    _his(35_000, "fire_response", "flare")
    _his(36_000, "fire_response", "drop")
    _his(80_000, "fire_response", "charge")        # a lone charge: his own effect
    v = _view()
    (g,) = v["authored"]
    assert (g["charge"]["timestamp_ms"], g["lull"]["timestamp_ms"],
            g["drop"]["timestamp_ms"]) == (30_000, 34_000, 36_000)
    assert [m["timestamp_ms"] for m in v["authored_lone"]] == [80_000]


def test_a_song_not_detected_yet_says_so_and_still_shows_his_added_ones():
    from spectra.services import drop_sequences as ds
    ds.add(URI, 50_000, fill=False)
    v = _view()
    assert v["status"] == "not_detected"
    assert [s["state"] for s in v["sequences"]] == ["added"]
