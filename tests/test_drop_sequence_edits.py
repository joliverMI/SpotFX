"""Drop-sequence EDITING (drop-detection plan, phase 4): the edit ops the
Timeline drives (spectra/services/drop_sequences.py `apply_edit`) and their
HTTP surface (spectra/api/drop_sequences.py). Each edit returns his edits
before and after it — the undo pair — and /restore puts one side back,
refusing when his edits changed since. Synthetic songs only; the store is
isolated per test by conftest's _isolated_drop_sequences."""
from __future__ import annotations

import pytest

import drop_synth

URI = "spotify:track:dropedit1"
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


def _set_detected(drops, *, tier="confident"):
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
                 "score": 1.2, "tier": t, "break_beats": 3.0, "step": 1.0,
                 "rise": 0.9, "path": "step", "loud_before": True, "capped": False,
                 "notes": []}
                for d, lu, ch, t in [(x[0], x[1], x[2], x[3] if len(x) > 3 else tier)
                                     for x in drops]],
            "excluded": [],
        }
    ds._mutate(URI, fn)


def _seqs():
    from spectra.services import drop_sequences as ds
    return ds.view(URI)["sequences"]


def _by_key(key):
    return next(s for s in _seqs() if s["key"] == key)


# ── one edit = his edits before and after ─────────────────────────────────

def test_every_edit_returns_his_edits_before_and_after_and_never_the_detection():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    res = ds.apply_edit(URI, "confirm", key="drop:44000")
    assert res.result == "drop:44000"
    assert res.before == {"overrides": {}, "added": []}
    assert res.after["overrides"]["drop:44000"]["state"] == "confirmed"
    assert "detected" not in res.after
    assert ds.edits(URI)["rev"] == ds.edits_rev(res.after)


def test_undo_and_redo_put_one_side_back_and_refuse_a_stale_undo():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    drag = ds.apply_edit(URI, "handles", key="drop:44000", handles={"drop": 44_250})
    assert _by_key("drop:44000")["drop_ms"] == 44_250
    # undo: back to before, only if his edits are still the "after" side
    ds.apply_edit(URI, "restore", edits=drag.before, expect=ds.edits_rev(drag.after))
    s = _by_key("drop:44000")
    assert s["drop_ms"] == 44_000 and s["state"] == "confident"
    assert "overrides" not in ds.stored(URI)
    # redo
    ds.apply_edit(URI, "restore", edits=drag.after, expect=ds.edits_rev(drag.before))
    assert _by_key("drop:44000")["drop_ms"] == 44_250
    # a stale undo (his edits moved on in another tab) writes nothing
    ds.apply_edit(URI, "confirm", key="drop:44000")
    with pytest.raises(ds.EditConflict):
        ds.apply_edit(URI, "restore", edits=drag.before, expect=ds.edits_rev(drag.after))
    assert _by_key("drop:44000")["state"] == "edited"


def test_a_redetection_between_edit_and_undo_does_not_block_the_undo():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    res = ds.apply_edit(URI, "dismiss", key="drop:44000")
    _set_detected([(44_100, 40_000, 35_000)])        # the analysis ran again
    ds.apply_edit(URI, "restore", edits=res.before, expect=ds.edits_rev(res.after))
    assert _by_key("drop:44100")["state"] == "confident"


# ── moving handles ────────────────────────────────────────────────────────

def test_a_whole_sequence_move_is_one_edit_and_order_is_checked_together():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    res = ds.apply_edit(URI, "handles", key="drop:44000",
                        handles={"charge": 35_500, "lull": 40_500, "drop": 44_500})
    s = _by_key("drop:44000")
    assert (s["charge_ms"], s["lull_ms"], s["drop_ms"]) == (35_500, 40_500, 44_500)
    assert s["state"] == "edited" and all(s["moved"].values())
    assert res.before == {"overrides": {}, "added": []}
    # moving the drop past where the lull is going would break the order if
    # applied one at a time — together it is fine
    ds.apply_edit(URI, "handles", key="drop:44000",
                  handles={"lull": 46_000, "drop": 47_000})
    with pytest.raises(ds.InvalidEdit):
        ds.apply_edit(URI, "handles", key="drop:44000", handles={"lull": 46_900})
    with pytest.raises(ds.InvalidEdit):
        ds.apply_edit(URI, "handles", key="drop:44000", handles={})


def test_moving_a_switched_off_member_switches_it_back_on():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    ds.apply_edit(URI, "member", key="drop:44000", handle="lull", off=True)
    assert _by_key("drop:44000")["lull_ms"] is None
    ds.apply_edit(URI, "handles", key="drop:44000", handles={"lull": 41_000})
    s = _by_key("drop:44000")
    assert s["lull_ms"] == 41_000 and not s["lull_off"]


def test_switching_a_member_back_on_restores_it_and_refuses_one_that_does_not_exist():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000), (90_000, None, 80_000)])
    ds.apply_edit(URI, "member", key="drop:44000", handle="charge", off=True)
    ds.apply_edit(URI, "member", key="drop:44000", handle="charge", off=False)
    s = _by_key("drop:44000")
    assert s["charge_ms"] == 35_000 and not s["charge_off"]
    with pytest.raises(ds.InvalidEdit):
        ds.apply_edit(URI, "member", key="drop:90000", handle="lull", off=False)


# ── his own added sequences ───────────────────────────────────────────────

def test_an_added_sequence_switches_members_off_and_on_keeping_their_times():
    from spectra.services import drop_sequences as ds
    key = ds.add(URI, 60_000, lull_ms=58_000, charge_ms=54_000, fill=False)
    ds.apply_edit(URI, "member", key=key, handle="lull", off=True)
    s = _by_key(key)
    assert s["lull_ms"] is None and s["lull_off"] and s["state"] == "added"
    assert s["auto"]["lull_ms"] == 58_000            # drawn where it was
    ds.apply_edit(URI, "member", key=key, handle="lull", off=False)
    s = _by_key(key)
    assert s["lull_ms"] == 58_000 and not s["lull_off"] and s["auto"] is None


def test_not_a_drop_on_an_added_sequence_removes_it_and_confirm_is_a_no_op():
    from spectra.services import drop_sequences as ds
    key = ds.add(URI, 60_000, fill=False)
    res = ds.apply_edit(URI, "confirm", key=key)
    assert res.before == res.after
    ds.apply_edit(URI, "dismiss", key=key)
    assert not any(s["key"] == key for s in _seqs())
    with pytest.raises(ds.SequenceNotFound):
        ds.apply_edit(URI, "dismiss", key=key)


def test_adding_a_drop_fills_the_lull_and_charge_by_the_rules():
    from spectra.services import drop_sequences as ds
    _song()
    res = ds.apply_edit(URI, "add", drop_ms=int(drop_synth.DROP_S * 1000))
    key = res.result
    s = _by_key(key)
    assert s["state"] == "added"
    assert abs(s["lull_ms"] - 40_000) <= BEAT and s["charge_ms"] < s["lull_ms"]
    assert res.after["added"][0]["id"] == key


def test_adding_a_drop_with_no_break_still_gets_a_charge_that_builds_to_it():
    from spectra.services import drop_sequences as ds
    _song()
    # 20 s in: steady bass, no break before it
    key = ds.add(URI, 20_000)
    rec = ds.stored(URI)["added"][0]
    assert rec["id"] == key and rec["lull_ms"] is None
    assert rec["charge_ms"] is not None and rec["charge_ms"] < 20_000 - 200


def test_a_lull_or_charge_can_be_added_to_a_bare_drop_by_the_rules():
    from spectra.services import drop_sequences as ds
    _song()
    key = ds.add(URI, int(drop_synth.DROP_S * 1000), fill=False)
    ds.apply_edit(URI, "fill", key=key, handle="lull")
    s = _by_key(key)
    assert abs(s["lull_ms"] - 40_000) <= BEAT
    ds.apply_edit(URI, "fill", key=key, handle="charge")
    s = _by_key(key)
    assert s["charge_ms"] is not None and s["charge_ms"] < s["lull_ms"]
    with pytest.raises(ds.InvalidEdit):
        ds.apply_edit(URI, "fill", key=key, handle="drop")


def test_filling_on_a_song_that_cannot_be_read_says_so():
    from spectra.services import drop_sequences as ds
    key = ds.add(URI, 60_000, fill=False)       # no audio shape for this song
    with pytest.raises(ds.InvalidEdit):
        ds.apply_edit(URI, "fill", key=key, handle="lull")


# ── "the analysis moved it": keep his, or take the new place ─────────────

def test_keep_pins_his_old_place_and_stops_asking():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    ds.confirm(URI, "drop:44000")
    _set_detected([(44_800, 40_600, 35_500)])
    assert _by_key("drop:44000")["needs_review"]
    ds.apply_edit(URI, "review", key="drop:44000", choice="keep")
    s = _by_key("drop:44000")
    assert not s["needs_review"]
    assert (s["charge_ms"], s["lull_ms"], s["drop_ms"]) == (35_000, 40_000, 44_000)
    assert s["state"] == "edited" and s["auto"]["drop_ms"] == 44_800


def test_take_moves_his_sequence_to_the_new_place_and_keeps_his_confirm():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    ds.confirm(URI, "drop:44000")
    ds.set_member_off(URI, "drop:44000", "charge", True)
    _set_detected([(44_800, 40_600, 35_500)])
    ds.apply_edit(URI, "review", key="drop:44000", choice="take")
    s = _by_key("drop:44000")
    assert not s["needs_review"]
    assert (s["lull_ms"], s["drop_ms"]) == (40_600, 44_800)
    assert s["charge_off"] and s["charge_ms"] is None          # his off stays
    ov = ds.stored(URI)["overrides"]["drop:44000"]
    assert ov["state"] == "confirmed"


def test_a_lost_detection_can_be_kept_or_let_go():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    ds.confirm(URI, "drop:44000")
    _set_detected([(90_000, 86_000, 80_000)])
    assert _by_key("drop:44000")["needs_review"]
    ds.apply_edit(URI, "review", key="drop:44000", choice="keep")
    s = _by_key("drop:44000")
    assert s["detection_lost"] and not s["needs_review"] and s["state"] == "confirmed"
    ds.apply_edit(URI, "review", key="drop:44000", choice="take")
    assert not any(s["key"] == "drop:44000" for s in _seqs())


def test_review_on_something_he_never_touched_is_not_found():
    from spectra.services import drop_sequences as ds
    _set_detected([(44_000, 40_000, 35_000)])
    with pytest.raises(ds.SequenceNotFound):
        ds.apply_edit(URI, "review", key="drop:44000", choice="keep")


# ── the review list's bulk tools ──────────────────────────────────────────

def test_confirm_all_confident_confirms_only_confident_detections_in_one_edit():
    from spectra.services import drop_sequences as ds
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import trigger_store
    _set_detected([(44_000, 40_000, 35_000, "confident"),
                   (90_000, 86_000, 80_000, "suggested"),
                   (130_000, 126_000, 120_000, "confident"),
                   (170_000, 166_000, 160_000, "confident")])
    trigger_store.upsert(URI, SpectraTrigger(           # his own drop: stands down
        timestamp_ms=170_050, action={"kind": "fire_response", "event_class": "drop"}))
    res = ds.apply_edit(URI, "confirm_all")
    assert sorted(res.result) == ["drop:130000", "drop:44000"]
    states = {s["key"]: s["state"] for s in _seqs()}
    assert states["drop:44000"] == states["drop:130000"] == "confirmed"
    assert states["drop:90000"] == "suggested" and states["drop:170000"] == "matches_yours"
    ds.apply_edit(URI, "restore", edits=res.before, expect=ds.edits_rev(res.after))
    assert {s["key"]: s["state"] for s in _seqs()}["drop:44000"] == "confident"


def test_redetect_runs_again_even_on_a_fresh_stamp_and_keeps_his_edits():
    from spectra.services import drop_sequences as ds
    _song()
    assert ds.ensure_detected(URI)["status"] == "detected"
    key = ds.view(URI)["sequences"][0]["key"]
    ds.confirm(URI, key)
    assert ds.ensure_detected(URI)["status"] == "fresh"
    assert ds.ensure_detected(URI, force=True)["status"] == "detected"
    assert ds.view(URI)["sequences"][0]["state"] == "confirmed"


# ── HTTP ──────────────────────────────────────────────────────────────────

def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def test_http_edits_answer_the_view_and_the_undo_pair():
    _set_detected([(44_000, 40_000, 35_000)])
    c = _client()
    r = c.post("/api/drop-sequences/handles",
               json={"uri": URI, "key": "drop:44000", "handles": {"drop": 44_300}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"] == "drop:44000"
    (seq,) = body["view"]["sequences"]
    assert seq["drop_ms"] == 44_300 and seq["state"] == "edited"
    assert body["before"] == {"overrides": {}, "added": []}
    assert body["rev_after"] != body["rev_before"]
    assert c.get(f"/api/drop-sequences/edits?uri={URI}").json()["rev"] == body["rev_after"]
    # undo
    u = c.post("/api/drop-sequences/restore",
               json={"uri": URI, "edits": body["before"], "expect": body["rev_after"]})
    assert u.status_code == 200
    assert u.json()["view"]["sequences"][0]["drop_ms"] == 44_000
    # the same undo again is stale now
    again = c.post("/api/drop-sequences/restore",
                   json={"uri": URI, "edits": body["before"], "expect": body["rev_after"]})
    assert again.status_code == 409


def test_http_handles_null_means_back_to_automatic():
    _set_detected([(44_000, 40_000, 35_000)])
    c = _client()
    c.post("/api/drop-sequences/handles",
           json={"uri": URI, "key": "drop:44000", "handles": {"lull": 41_000}})
    r = c.post("/api/drop-sequences/handles",
               json={"uri": URI, "key": "drop:44000", "handles": {"lull": None}})
    assert r.json()["view"]["sequences"][0]["lull_ms"] == 40_000


def test_http_errors_are_named_not_500s():
    _set_detected([(44_000, 40_000, 35_000)])
    c = _client()
    assert c.post("/api/drop-sequences/confirm",
                  json={"uri": URI, "key": "drop:99000"}).status_code == 404
    bad = c.post("/api/drop-sequences/handles",
                 json={"uri": URI, "key": "drop:44000", "handles": {"lull": 43_950}})
    assert bad.status_code == 422 and "before" in bad.json()["detail"]
    assert c.post("/api/drop-sequences/member",
                  json={"uri": URI, "key": "drop:44000", "handle": "drop", "off": True}
                  ).status_code == 422
    assert c.post("/api/drop-sequences/review",
                  json={"uri": URI, "key": "drop:44000", "choice": "maybe"}).status_code == 422


def test_http_add_confirm_all_dismiss_revert_and_redetect():
    _song()
    c = _client()
    first = c.get(f"/api/drop-sequences?uri={URI}").json()
    (det,) = first["sequences"]
    added = c.post("/api/drop-sequences/add", json={"uri": URI, "drop_ms": 120_000}).json()
    assert added["result"].startswith("added:")
    assert any(s["key"] == added["result"] for s in added["view"]["sequences"])
    allc = c.post("/api/drop-sequences/confirm-all", json={"uri": URI}).json()
    assert allc["result"] == [det["key"]]
    dis = c.post("/api/drop-sequences/dismiss", json={"uri": URI, "key": det["key"]}).json()
    assert next(s for s in dis["view"]["sequences"] if s["key"] == det["key"])["state"] == "dismissed"
    rev = c.post("/api/drop-sequences/revert", json={"uri": URI, "key": det["key"]}).json()
    assert rev["result"] is True
    red = c.post("/api/drop-sequences/redetect", json={"uri": URI}).json()
    assert red["detection"]["status"] == "detected"
    assert any(s["key"] == added["result"] for s in red["sequences"])
