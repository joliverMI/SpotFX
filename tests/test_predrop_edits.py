"""EDITING A PRE-DROP (predrop plan step 4; drop_sequences.py's PRE-DROPS
section is the binding statement): a drag, back to detected, switched off
and on, its kind switched, ＋ Pre-drop placed by the rules, its part toggle
and the double tick — on a detected drop, a drop he added, and one of his
own drops (stored in the drop store under "mine:<his drop trigger id>",
never his song profile); the snap rails it is dragged along; the routes;
Sonic's set_pre_drop / switch_pre_drop. Every edit answers the undo pair.
Whether a pre-drop plays is decided per scene by step 5's engine
(spectra/services/pre_drop_play.py), not by anything edited here.

Synthetic detections, plus his Eyes Cut Deeper shape (the step-3 fixture,
tests/fixtures/predrop/ecd) where the rules and the rails need real audio.
The store is isolated per test by conftest's _isolated_drop_sequences."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from spectra import config

URI = "spotify:track:predropedit1"
ECD = "spotify:track:3E8WZzcp6nscGt9YvBX9MW"
FIXTURES = Path(__file__).parent / "fixtures" / "predrop"
PRE = {"ms": 43_200, "kind": "spike", "lead_ms": 800, "score": 1.1, "tier": "confident"}
KEY = "drop:44000"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(config, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(config, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    _reset()
    yield
    _reset()


def _reset():
    from spectra.services import analysis_reader, drop_detector, drop_sequences
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False
    drop_detector.reset_memo()
    drop_sequences.reset()


def _set_detected(pre: dict | None = PRE, *, tier: str = "confident") -> None:
    from spectra.services import drop_detector as dd
    from spectra.services import drop_sequences as ds

    def fn(entry):
        seq = {"key": KEY, "drop_ms": 44_000, "lull_ms": 40_000, "charge_ms": 35_000,
               "score": 1.2, "tier": tier, "break_beats": 3.0, "step": 1.0, "rise": 0.9,
               "path": "step", "loud_before": True, "capped": False, "notes": []}
        if pre is not None:
            seq["pre_drop"] = dict(pre)
        entry["detected"] = {
            "uri": URI, "detector_version": dd.DETECTOR_VERSION, "confident_score": 1.0,
            "suggested_score": 0.7, "tempo_bpm": 120.0, "beat_ms": 500.0,
            "captured_from_ms": 0, "captured_to_ms": 200_000, "duration_ms": 200_000,
            "stamp": "test", "excluded": [], "sequences": [seq]}
    ds._mutate(URI, fn)


def _seq(uri: str = URI, key: str = KEY) -> dict:
    from spectra.services import drop_sequences as ds
    return next(s for s in ds.view(uri, triggers=[])["sequences"] if s["key"] == key)


def _edit(op: str, **kw):
    from spectra.services import drop_sequences as ds
    return ds.apply_edit(URI, op, key=KEY, **kw)


def _undo(res, uri: str = URI):
    from spectra.services import drop_sequences as ds
    ds.apply_edit(uri, "restore", edits=res.before, expect=ds.edits_rev(res.after))


# ── a detected drop's pre-drop ──────────────────────────────────────────────

def test_the_detectors_pre_drop_waits_for_his_tick():
    _set_detected()
    s = _seq()
    assert (s["pre_drop_ms"], s["pre_drop_kind"], s["pre_drop_auto"]) == (43_200, "spike", 43_200)
    assert (s["pre_drop_tier"], s["pre_drop_off"], s["moved"]["pre_drop"]) == (
        "confident", False, False)
    assert s["parts"]["pre_drop"] == "waiting"


def test_a_drag_moves_it_keeps_its_kind_and_one_undo_puts_it_back():
    from spectra.services import drop_sequences as ds
    _set_detected()
    res = _edit("handles", handles={"pre_drop": 43_000})
    assert res.before == {"overrides": {}, "added": []}
    s = _seq()
    assert (s["pre_drop_ms"], s["pre_drop_kind"], s["pre_drop_auto"]) == (43_000, "spike", 43_200)
    assert s["moved"]["pre_drop"] and s["state"] == "edited"
    assert s["pre_drop_tier"] is None and s["pre_drop_score"] is None   # his place now
    assert (s["charge_ms"], s["lull_ms"], s["drop_ms"]) == (35_000, 40_000, 44_000)
    _undo(res)
    assert _seq()["pre_drop_ms"] == 43_200 and "overrides" not in ds.stored(URI)


def test_back_to_detected_puts_the_detectors_place_and_confidence_back():
    _set_detected()
    _edit("handles", handles={"pre_drop": 43_000})
    _edit("handles", handles={"pre_drop": None})
    s = _seq()
    assert (s["pre_drop_ms"], s["pre_drop_tier"], s["moved"]["pre_drop"]) == (
        43_200, "confident", False)


@pytest.mark.parametrize("ms, words", [
    (40_500, "spike pre-drop sits 250-3000 ms before its drop"),   # 3500 ms before
    (43_900, "spike pre-drop sits 250-3000 ms before its drop"),   # only 100 ms before
    (44_100, "spike pre-drop sits 250-3000 ms before its drop"),   # after the drop
])
def test_a_drag_outside_its_kinds_lead_range_is_refused_and_writes_nothing(ms, words):
    from spectra.services import drop_sequences as ds
    _set_detected()
    with pytest.raises(ds.InvalidEdit, match=words):
        _edit("handles", handles={"pre_drop": ms})
    assert "overrides" not in ds.stored(URI)
    assert _seq()["pre_drop_ms"] == 43_200


def test_a_placed_pre_drop_holds_a_drop_move_back_by_the_order_rule():
    from spectra.services import drop_sequences as ds
    _set_detected()
    _edit("handles", handles={"pre_drop": 43_500})
    with pytest.raises(ds.InvalidEdit, match="at least 200 ms before its drop"):
        _edit("handles", handles={"drop": 43_600})
    assert _seq()["drop_ms"] == 44_000


def test_an_automatic_pre_drop_never_holds_a_drop_move_back():
    _set_detected()
    _edit("handles", handles={"drop": 43_100})        # now 100 ms after the detector's
    s = _seq()
    assert s["drop_ms"] == 43_100
    assert s["pre_drop_ms"] is None and s["pre_drop_auto"] == 43_200
    assert any("pre-drop left out" in n for n in s["notes"])


def test_a_whole_sequence_move_is_checked_against_where_the_pre_drop_is_going():
    _set_detected()
    _edit("handles", handles={"pre_drop": 43_700})    # 300 ms before the drop
    # everything 500 ms earlier: the new drop lands BEFORE where the pre-drop
    # was, but the pre-drop moves with it in the same edit
    _edit("handles", handles={"charge": 34_500, "lull": 39_500, "drop": 43_500,
                              "pre_drop": 43_200})
    s = _seq()
    assert (s["charge_ms"], s["lull_ms"], s["drop_ms"], s["pre_drop_ms"]) == (
        34_500, 39_500, 43_500, 43_200)


def test_switched_off_it_remembers_where_it_comes_back():
    _set_detected()
    res = _edit("member", handle="pre_drop", off=True)
    s = _seq()
    assert s["pre_drop_ms"] is None and s["pre_drop_off"]
    assert (s["pre_drop_was"], s["pre_drop_kind"], s["parts"]["pre_drop"]) == (
        43_200, "spike", "off")
    assert s["state"] == "edited"
    back_on = _edit("member", handle="pre_drop", off=False)
    s = _seq()
    assert (s["pre_drop_ms"], s["pre_drop_off"], s["pre_drop_was"]) == (43_200, False, None)
    _undo(back_on)
    assert _seq()["pre_drop_off"]
    _undo(res)
    assert not _seq()["pre_drop_off"]


def test_a_drop_with_no_pre_drop_refuses_its_edits_by_name():
    from spectra.services import drop_sequences as ds
    _set_detected(pre=None)
    assert _seq()["parts"]["pre_drop"] == "absent"
    with pytest.raises(ds.InvalidEdit, match="add one first"):
        _edit("handles", handles={"pre_drop": 43_000})
    with pytest.raises(ds.InvalidEdit, match="no pre-drop"):
        _edit("member", handle="pre_drop", off=True)
    with pytest.raises(ds.InvalidEdit, match="add one first"):
        _edit("pre_drop_kind", kind="intro")
    assert "overrides" not in ds.stored(URI)


def test_its_kind_switch_checks_the_kinds_lead_range():
    from spectra.services import drop_sequences as ds
    _set_detected()
    _edit("pre_drop_kind", kind="intro")               # 800 ms fits 350-4500
    s = _seq()
    assert (s["pre_drop_kind"], s["pre_drop_ms"]) == ("intro", 43_200)
    _edit("pre_drop_kind", kind="spike")               # back to the detector's: nothing kept
    assert "pre_drop_kind" not in ds.stored(URI)["overrides"][KEY]
    _edit("handles", handles={"pre_drop": 43_700})     # a spike 300 ms before
    with pytest.raises(ds.InvalidEdit, match="vocal intro pre-drop sits 350-4500 ms"):
        _edit("pre_drop_kind", kind="intro")
    assert _seq()["pre_drop_kind"] == "spike"


def test_its_part_toggle_approves_switches_off_and_back_on():
    _set_detected()
    _edit("parts", parts={"pre_drop": "on"})
    s = _seq()
    assert s["parts"]["pre_drop"] == "on"
    assert s["parts"]["drop"] == "waiting"          # approving one part approves only it
    _edit("parts", parts={"pre_drop": "off"})
    assert _seq()["parts"]["pre_drop"] == "off" and _seq()["pre_drop_ms"] is None
    _edit("parts", parts={"pre_drop": "on"})        # back on, and approved
    s = _seq()
    assert (s["parts"]["pre_drop"], s["pre_drop_ms"]) == ("on", 43_200)


def test_the_double_tick_and_confirm_approve_the_pre_drop_too():
    _set_detected()
    _edit("approve")
    assert set(_seq()["parts"].values()) == {"on"}
    _reset()
    _set_detected()
    _edit("confirm")
    assert _seq()["parts"]["pre_drop"] == "on"


def test_an_edited_approved_pre_drop_rides_its_lull_and_is_never_a_member():
    """Since the pre-drop engine (step 5): his dragged and approved pre-drop
    plays — it rides the sequence's LULL (FiringSequence.pre_drop_for, the
    candidate the trigger clock hands the lull arm) — and is never a member
    of its own: the sequence still fires charge, lull and drop."""
    from spectra.services import drop_firing, drop_sequences as ds
    _set_detected()
    _edit("handles", handles={"pre_drop": 43_000})
    _edit("approve")
    (seq,) = drop_firing.firing_sequences(ds.view(URI, triggers=[]))
    assert (seq.pre_drop_ms, seq.pre_drop_kind) == (43_000, "spike")
    assert seq.pre_drop_for("lull") == (43_000, "spike")
    assert [c for c, _ in seq.members()] == ["charge", "lull", "drop"]


# ── a drop he added ─────────────────────────────────────────────────────────

def test_an_added_drops_pre_drop_is_all_his_and_back_to_detected_removes_it():
    from spectra.services import drop_sequences as ds
    _set_detected(pre=None)
    added = ds.apply_edit(URI, "add", drop_ms=90_000, lull_ms=86_000, charge_ms=80_000,
                          fill=False).result
    with pytest.raises(ds.InvalidEdit, match="add one first"):
        ds.apply_edit(URI, "handles", key=added, handles={"pre_drop": 89_000})
    # ＋ Pre-drop on a song whose audio cannot be read says so, writing nothing
    with pytest.raises(ds.InvalidEdit, match="cannot be read"):
        ds.apply_edit(URI, "fill", key=added, handle="pre_drop")


# ── ＋ Pre-drop and the rails, on his real shape ────────────────────────────

@pytest.fixture()
def ecd(tmp_path):
    from spectra.services import drop_sequences as ds
    from spectra.services import room_controls
    shutil.copytree(FIXTURES / "ecd", config.AUDIO_SHAPES_DIR)
    _reset()
    room_controls.save_room_controls(room_controls.RoomControlState(drop_floor=0.1))
    assert ds.ensure_detected(ECD)["status"] == "detected"
    return ECD


def test_plus_pre_drop_places_one_where_the_rules_put_it(ecd):
    from spectra.services import drop_detector, drop_sequences as ds, predrop_detector
    key = ds.apply_edit(ecd, "add", drop_ms=120_000, fill=False).result
    res = ds.apply_edit(ecd, "fill", key=key, handle="pre_drop")
    want = predrop_detector.place(drop_detector.analyse(ecd).shape, 120_000)
    assert want is not None
    s = _seq(ecd, key)
    assert (s["pre_drop_ms"], s["pre_drop_kind"]) == want
    lo, hi = predrop_detector.lead_range(s["pre_drop_kind"])
    assert lo <= 120_000 - s["pre_drop_ms"] <= hi
    assert s["moved"]["pre_drop"] and s["parts"]["pre_drop"] == "on"
    with pytest.raises(ds.InvalidEdit, match="already has a pre-drop"):
        ds.apply_edit(ecd, "fill", key=key, handle="pre_drop")
    _undo(res, ecd)
    assert _seq(ecd, key)["pre_drop_ms"] is None
    # an added drop's "back to detected" removes the one he placed
    ds.apply_edit(ecd, "fill", key=key, handle="pre_drop")
    ds.apply_edit(ecd, "handles", key=key, handles={"pre_drop": None})
    assert _seq(ecd, key)["pre_drop_ms"] is None and _seq(ecd, key)["parts"]["pre_drop"] == "absent"


def test_the_rails_carry_every_hit_and_every_vocal_entry(ecd):
    from spectra.services import drop_detector, drop_sequences as ds, predrop_detector
    rails = ds.snap_rails(ecd)
    hits, entries = rails["hits"], rails["entries"]
    assert hits and all(len(h) == 2 and h[1] >= 0 for h in hits)
    assert [h[0] for h in hits] == sorted(h[0] for h in hits)
    # the spike the detector found before drop 1 is on the hits rail
    assert any(h[0] == 69_537 and h[1] > 0.5 for h in hits)
    assert (hits, entries) == tuple(map(list, predrop_detector.rails(
        drop_detector.analyse(ecd).shape)))


def test_a_song_without_audio_has_empty_rails():
    from spectra.services import drop_sequences as ds
    rails = ds.snap_rails(URI)
    assert rails["hits"] == [] and rails["entries"] == []


# ── one of his own drops ────────────────────────────────────────────────────

@pytest.fixture()
def his(ecd):
    from spectra.models.trigger import SpectraTrigger
    from spectra.services import drop_sequences as ds
    from spectra.services import trigger_store
    trigger_store.upsert(ecd, SpectraTrigger(
        timestamp_ms=70350, action={"kind": "fire_response", "event_class": "drop"}))
    (row,) = ds.view(ecd)["yours"]
    return row["key"], row["drop"]["id"]


def _his_pre(uri: str = ECD) -> dict:
    from spectra.services import drop_sequences as ds
    (row,) = ds.view_with_detection(uri)["yours"]
    return row["pre_drop"]


def _fired_bytes() -> bytes:
    return config.TRIGGERS_FILE.read_bytes()


def test_his_drops_pre_drop_edits_land_in_the_drop_store_never_his_triggers(his):
    from spectra.services import drop_panel, drop_sequences as ds
    key, drop_id = his
    before = _fired_bytes()
    pre = _his_pre()
    assert pre["kind"] == "spike" and pre["part"] == "waiting" and not pre["moved"]
    res = asyncio.run(drop_panel.move_handles(ECD, key, {"pre_drop": 69_800}))
    assert res.profile == []                                   # his profile untouched
    assert _fired_bytes() == before                            # and his fired copy
    assert set(res.after["overrides"]) >= {f"mine:{drop_id}"}
    pre = _his_pre()
    assert (pre["ms"], pre["lead_ms"], pre["moved"], pre["tier"]) == (69_800, 550, True, None)
    # back to the rules' place: nothing of his left in the store
    asyncio.run(drop_panel.move_handles(ECD, key, {"pre_drop": None}))
    assert f"mine:{drop_id}" not in (ds.stored(ECD).get("overrides") or {})
    assert not _his_pre()["moved"]


def test_his_drops_pre_drop_switches_off_on_and_its_kind(his):
    from spectra.services import drop_panel
    key, _id = his
    asyncio.run(drop_panel.pre_drop_member(ECD, key, True))
    pre = _his_pre()
    assert pre["off"] and pre["ms"] is None and pre["part"] == "off" and pre["was"]
    asyncio.run(drop_panel.pre_drop_member(ECD, key, False))
    assert not _his_pre()["off"]
    asyncio.run(drop_panel.pre_drop_kind(ECD, key, "intro"))
    assert _his_pre()["kind"] == "intro"


def test_the_double_tick_on_his_drop_approves_its_waiting_pre_drop(his):
    from spectra.services import drop_panel, drop_sequences as ds
    key, drop_id = his
    res = asyncio.run(drop_panel.approve(ECD, key))
    assert _his_pre()["part"] == "on"
    assert res.after["overrides"][f"mine:{drop_id}"]["parts"] == {"pre_drop": "on"}
    again = asyncio.run(drop_panel.approve(ECD, key))         # nothing left to approve
    assert again.before == again.after and "approved already" in again.said
    ds.apply_edit(ECD, "restore", edits=res.before, expect=ds.edits_rev(res.after))
    assert _his_pre()["part"] == "waiting"


def test_his_drops_pre_drop_part_toggle_asks_nothing_and_undoes(his):
    from spectra.services import drop_panel, drop_sequences as ds
    key, _id = his
    res = asyncio.run(drop_panel.set_parts(ECD, key, {"pre_drop": "off"}))
    assert _his_pre()["part"] == "off" and res.profile == []
    ds.apply_edit(ECD, "restore", edits=res.before, expect=ds.edits_rev(res.after))
    assert _his_pre()["part"] == "waiting"


# ── the routes ──────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())          # no lifespan: the routes alone


def test_the_routes_move_switch_and_reswitch_the_pre_drop(client):
    _set_detected()
    r = client.post("/api/drop-sequences/handles",
                    json={"uri": URI, "key": KEY, "handles": {"pre_drop": 43_100}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"before", "after", "view"} <= set(body)
    assert next(s for s in body["view"]["sequences"] if s["key"] == KEY)["pre_drop_ms"] == 43_100
    r = client.post("/api/drop-sequences/pre-drop-kind",
                    json={"uri": URI, "key": KEY, "kind": "intro"})
    assert r.status_code == 200, r.text
    assert _seq()["pre_drop_kind"] == "intro"
    r = client.post("/api/drop-sequences/member",
                    json={"uri": URI, "key": KEY, "handle": "pre_drop", "off": True})
    assert r.status_code == 200, r.text
    assert _seq()["pre_drop_off"]
    r = client.post("/api/drop-sequences/parts",
                    json={"uri": URI, "key": KEY, "parts": {"pre_drop": "on"}})
    assert r.status_code == 200, r.text
    assert (_seq()["pre_drop_ms"], _seq()["parts"]["pre_drop"]) == (43_100, "on")


def test_the_routes_refuse_a_bad_pre_drop_edit_by_name(client):
    from spectra.services import drop_sequences as ds
    _set_detected()
    r = client.post("/api/drop-sequences/handles",
                    json={"uri": URI, "key": KEY, "handles": {"pre_drop": 40_000}})
    assert r.status_code == 422 and "spike pre-drop sits" in r.text
    r = client.post("/api/drop-sequences/pre-drop-kind",
                    json={"uri": URI, "key": KEY, "kind": "shout"})
    assert r.status_code == 422
    r = client.post("/api/drop-sequences/fill",
                    json={"uri": URI, "key": KEY, "handle": "pre_drop"})
    assert r.status_code == 422 and "already has a pre-drop" in r.text
    assert "overrides" not in ds.stored(URI)


# ── Sonic ───────────────────────────────────────────────────────────────────

def _sonic(name: str, **kw) -> dict:
    from spectra.services import drop_console
    return asyncio.run(drop_console.OPERATIONS[name].handler(uri=URI, **kw))


def test_sonic_moves_switches_and_reswitches_the_pre_drop():
    _set_detected()
    out = _sonic("set_pre_drop", sequence=1, before_drop_ms=600)
    assert out["status"] == "applied", out
    assert "0.6 s before its drop" in out["summary"]
    assert _seq()["pre_drop_ms"] == 43_400
    out = _sonic("switch_pre_drop", kind="intro", sequence=1)
    assert out["status"] == "applied" and "vocal intro" in out["summary"]
    assert _sonic("set_pre_drop", sequence=1, place="off")["status"] == "applied"
    assert _seq()["pre_drop_off"]
    assert _sonic("set_pre_drop", sequence=1, place="on")["status"] == "applied"
    listed = _sonic("list_drop_sequences")
    (one,) = listed["sequences"]
    assert (one["pre_drop"]["at_s"], one["pre_drop"]["kind"]) == (43.4, "intro")
    assert one["pre_drop"]["placed_by_you"] and "tier" not in one["pre_drop"]
    # back to detected: the detector's place AND its kind
    assert _sonic("set_pre_drop", sequence=1, place="detected")["status"] == "applied"
    s = _seq()
    assert (s["pre_drop_ms"], s["pre_drop_kind"], s["moved"]["pre_drop"]) == (
        43_200, "spike", False)


def test_sonic_refuses_an_ambiguous_or_impossible_pre_drop_edit():
    _set_detected()
    out = _sonic("set_pre_drop", sequence=1, before_drop_ms=600, place="off")
    assert out["status"] == "rejected" and "exactly one" in out["reason"]
    out = _sonic("set_pre_drop", sequence=1, before_drop_ms=4000)      # a spike's max is 3000
    assert out["status"] == "rejected" and "spike pre-drop sits" in out["reason"]
    out = _sonic("switch_pre_drop", kind="shout", sequence=1)
    assert out["status"] == "rejected"
    assert _seq()["pre_drop_ms"] == 43_200


def test_sonic_switches_off_a_pre_drop_without_asking():
    _set_detected()
    out = _sonic("set_drop_part", part="pre_drop", on=False, sequence=1)
    assert out["status"] == "applied", out
    assert "pre-drop switched off" in out["summary"]
    assert _seq()["parts"]["pre_drop"] == "off"


def test_sonic_lists_and_edits_his_own_drops_pre_drop(his):
    from spectra.services import drop_console
    before = _fired_bytes()
    listed = asyncio.run(drop_console.OPERATIONS["list_drop_sequences"].handler(uri=ECD))
    (row,) = listed["yours"]
    assert row["pre_drop"]["kind"] == "spike" and row["pre_drop"]["part"] == "waiting"
    out = asyncio.run(drop_console.OPERATIONS["set_pre_drop"].handler(
        uri=ECD, your_drop_s=70.35, before_drop_ms=500))
    assert out["status"] == "applied", out
    assert "your drop at 70.35 s" in out["summary"]
    assert _his_pre()["ms"] == 69_850
    out = asyncio.run(drop_console.OPERATIONS["set_drop_part"].handler(
        uri=ECD, your_drop_s=70.35, part="pre_drop", on=False))
    assert out["status"] == "applied", out                 # no question asked
    assert _his_pre()["part"] == "off"
    assert _fired_bytes() == before
    undone = asyncio.run(drop_console.OPERATIONS["undo_drop_edit"].handler(uri=ECD))
    assert undone["status"] == "applied", undone
    assert _his_pre()["part"] != "off"


def test_the_routes_take_his_own_drops_key_for_the_pre_drop(his, client):
    key, drop_id = his
    before = _fired_bytes()
    r = client.post("/api/drop-sequences/handles",
                    json={"uri": ECD, "key": key, "handles": {"pre_drop": 69_700}})
    assert r.status_code == 200, r.text
    assert r.json()["profile"] == [] and _his_pre()["ms"] == 69_700
    r = client.post("/api/drop-sequences/approve", json={"uri": ECD, "key": key})
    assert r.status_code == 200, r.text
    assert _his_pre()["part"] == "on"
    r = client.post("/api/drop-sequences/pre-drop-kind",
                    json={"uri": ECD, "key": key, "kind": "intro"})
    assert r.status_code == 200, r.text
    assert _his_pre()["kind"] == "intro"
    assert _fired_bytes() == before
