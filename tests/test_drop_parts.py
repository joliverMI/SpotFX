"""THE HOME DROPS PANEL'S PARTS AND TESTING (2026-10-26, predrop plan step 1
— spectra/services/drop_sequences.py's PARTS, spectra/services/
drop_firing.py's PARTS and DROP TESTING).

  1. Every view sequence carries one state per part (on / waiting / off /
     absent), read the legacy way until a part edit moves it to PARTS MODE.
  2. The part edits: ANY EDIT APPROVES (2026-10-28) — approving or
     switching off one part approves every part not off, the drop with them
     unless it is the drop that went off; the double tick approves every part not off;
     switching the drop off keeps it listed but silent; Remove dismisses a
     detection and deletes an added drop; the Timeline's Confirm approves
     every part in parts mode.
  3. FROM THE SHOW SIDE (tests/test_preview_holds_the_show.py's standard):
     the real TriggerEngine swept over a position feed on 100 Millones'
     real detection — with Testing on a suggested drop plays, and an off
     part, a switched-off drop and a removed drop never do; with it off a
     suggestion waits; a drop that fires is told to `drop_played`.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from spectra import config as scfg
from spectra.models.trigger import FireResponseAction, SpectraTrigger
from spectra.services import drop_detector as dd
from spectra.services import drop_firing, drop_sequences as ds
from spectra.services.trigger_engine import TriggerEngine

URI = "spotify:track:dropparts1"
BEAT = 500.0

FIX = json.loads((Path(__file__).parent / "fixtures" /
                  "drop_sequences_four_songs.json").read_text(encoding="utf-8"))
MILLONES = next(u for u, s in FIX["songs"].items() if s["name"] == "100 Millones")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    ds.reset()
    yield
    ds.reset()


def _set_detected(drops):
    """drops: (drop_ms, lull_ms, charge_ms, tier)."""
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
                for d, lu, ch, t in drops],
            "excluded": [],
        }
    ds._mutate(URI, fn)


def _seq(key, uri=URI, triggers=None):
    return next(s for s in ds.view(uri, triggers=triggers or [])["sequences"] if s["key"] == key)


# ── 1. the view's part states ────────────────────────────────────────────

def test_a_plain_detection_waits_part_by_part_and_has_no_pre_drop():
    _set_detected([(44_000, 40_000, 35_000, "confident"), (90_000, 86_000, None, "suggested")])
    a = _seq("drop:44000")
    assert a["parts"] == {"charge": "waiting", "lull": "waiting", "pre_drop": "absent",
                          "drop": "waiting"}
    b = _seq("drop:90000")
    assert b["parts"]["charge"] == "absent" and b["parts"]["drop"] == "waiting"


def test_a_legacy_confirm_or_edit_reads_as_every_part_on():
    _set_detected([(44_000, 40_000, 35_000, "suggested"), (90_000, 86_000, 80_000, "suggested")])
    ds.apply_edit(URI, "confirm", key="drop:44000")
    ds.apply_edit(URI, "member", key="drop:90000", handle="lull", off=True)
    assert _seq("drop:44000")["parts"] == {"charge": "on", "lull": "on", "pre_drop": "absent",
                                           "drop": "on"}
    edited = _seq("drop:90000")
    assert edited["state"] == ds.STATE_EDITED
    assert edited["parts"] == {"charge": "on", "lull": "off", "pre_drop": "absent", "drop": "on"}


def test_an_added_drop_is_on_part_by_part():
    _set_detected([])
    key = ds.apply_edit(URI, "add", drop_ms=60_000, lull_ms=56_000, charge_ms=50_000,
                        fill=False).result
    assert _seq(key)["parts"] == {"charge": "on", "lull": "on", "pre_drop": "absent",
                                  "drop": "on"}


# ── 2. the part edits ────────────────────────────────────────────────────

def test_approving_the_drop_approves_the_whole_sequence():
    # ANY EDIT APPROVES: approving one part approves every part not off
    _set_detected([(44_000, 40_000, 35_000, "suggested")])
    res = ds.apply_edit(URI, "parts", key="drop:44000", parts={"drop": "on"})
    s = _seq("drop:44000")
    assert s["state"] == ds.STATE_CONFIRMED
    assert s["parts"] == {"charge": "on", "lull": "on", "pre_drop": "absent", "drop": "on"}
    ov = res.after["overrides"]["drop:44000"]
    assert ov["state"] == "confirmed"
    assert ov["parts"] == {"charge": "on", "lull": "on", "drop": "on"}
    assert res.before == {"overrides": {}, "added": []}


def test_approving_only_the_lull_approves_the_drop_so_it_plays():
    _set_detected([(44_000, 40_000, 35_000, "suggested")])
    ds.apply_edit(URI, "parts", key="drop:44000", parts={"lull": "on"})
    s = _seq("drop:44000")
    assert s["state"] == ds.STATE_CONFIRMED
    assert s["parts"] == {"charge": "on", "lull": "on", "pre_drop": "absent", "drop": "on"}
    v = ds.view(URI, triggers=[])
    by = {f.key: f for f in drop_firing.firing_sequences(v)}
    assert by["drop:44000"].members() == [("charge", 35_000), ("lull", 40_000),
                                          ("drop", 44_000)]


def test_switching_a_lull_off_approves_the_rest():
    _set_detected([(44_000, 40_000, 35_000, "suggested")])
    ds.apply_edit(URI, "parts", key="drop:44000", parts={"lull": "off"})
    s = _seq("drop:44000")
    # a disapproval is an edit too: every part not off is approved, the drop plays
    assert s["state"] == ds.STATE_EDITED
    assert s["parts"] == {"charge": "on", "lull": "off", "pre_drop": "absent", "drop": "on"}
    ds.apply_edit(URI, "parts", key="drop:44000", parts={"lull": "on"})
    assert _seq("drop:44000")["parts"]["lull"] == "on"


def test_switching_the_drop_off_approves_the_rest_and_plays_nothing():
    # Q6: the drop off counts as reviewed and plays nothing; it stays listed
    _set_detected([(44_000, 40_000, 35_000, "suggested")])
    ds.apply_edit(URI, "parts", key="drop:44000", parts={"drop": "off"})
    s = _seq("drop:44000")
    assert s["parts"] == {"charge": "on", "lull": "on", "pre_drop": "absent", "drop": "off"}
    v = ds.view(URI, triggers=[])
    assert drop_firing.firing_sequences(v, testing=True) == []
    a = next(x for x in drop_firing.annotate(v, "analysed", False, testing=True)["sequences"]
             if x["key"] == "drop:44000")
    assert a["fires"] is False and a["fires_reason"] == "switched_off"
    ds.apply_edit(URI, "parts", key="drop:44000", parts={"drop": "on"})
    assert _seq("drop:44000")["parts"] == {"charge": "on", "lull": "on", "pre_drop": "absent",
                                           "drop": "on"}


@pytest.mark.parametrize("op,kw", [
    ("handles", {"handles": {"lull": 41_000}}),
    ("handles", {"handles": {"lull": None}}),
    ("member", {"handle": "charge", "off": True}),
])
def test_every_other_edit_approves_the_sequence(op, kw):
    _set_detected([(44_000, 40_000, 35_000, "suggested")])
    ds.apply_edit(URI, op, key="drop:44000", **kw)
    s = _seq("drop:44000")
    assert s["state"] in (ds.STATE_CONFIRMED, ds.STATE_EDITED)
    assert s["parts"]["drop"] == "on"
    assert all(v in ("on", "off", "absent") for v in s["parts"].values())


def test_remove_back_to_detected_and_undo_do_not_approve():
    # Q7: Remove takes it away, Back to detected returns it to waiting
    _set_detected([(44_000, 40_000, 35_000, "suggested"), (90_000, 86_000, 80_000, "suggested")])
    ds.apply_edit(URI, "remove", key="drop:44000")
    ov = ds.stored(URI)["overrides"]["drop:44000"]
    assert ov["state"] == ds.STATE_DISMISSED and "parts" not in ov
    res = ds.apply_edit(URI, "handles", key="drop:90000", handles={"lull": 85_000})
    assert _seq("drop:90000")["parts"]["drop"] == "on"
    ds.apply_edit(URI, "revert", key="drop:90000")
    assert _seq("drop:90000")["state"] == "suggested"
    assert _seq("drop:90000")["parts"]["drop"] == "waiting"
    res = ds.apply_edit(URI, "handles", key="drop:90000", handles={"lull": 85_000})
    ds.apply_edit(URI, "restore", edits=res.before, expect=ds.edits_rev(res.after))
    assert _seq("drop:90000")["parts"]["drop"] == "waiting"


def test_the_double_tick_approves_every_part_that_is_not_off():
    _set_detected([(44_000, 40_000, 35_000, "suggested")])
    ds.apply_edit(URI, "parts", key="drop:44000", parts={"charge": "off"})
    ds.apply_edit(URI, "approve", key="drop:44000")
    s = _seq("drop:44000")
    assert s["parts"] == {"charge": "off", "lull": "on", "pre_drop": "absent", "drop": "on"}
    assert s["state"] == ds.STATE_EDITED          # approved, with a part switched off


def test_a_first_part_edit_on_a_legacy_confirm_keeps_it_approved():
    _set_detected([(44_000, 40_000, 35_000, "suggested")])
    ds.apply_edit(URI, "confirm", key="drop:44000")
    ds.apply_edit(URI, "parts", key="drop:44000", parts={"lull": "off"})
    s = _seq("drop:44000")
    assert s["parts"] == {"charge": "on", "lull": "off", "pre_drop": "absent", "drop": "on"}
    assert s["state"] == ds.STATE_EDITED


def test_switching_the_drop_off_keeps_it_listed_but_silent():
    _set_detected([(44_000, 40_000, 35_000, "confident")])
    ds.apply_edit(URI, "parts", key="drop:44000", parts={"drop": "off"})
    v = ds.view(URI, triggers=[])
    s = next(x for x in v["sequences"] if x["key"] == "drop:44000")
    assert s["state"] == "confident" and s["parts"]["drop"] == "off"
    annotated = drop_firing.annotate(v, "analysed", False, testing=True)
    a = next(x for x in annotated["sequences"] if x["key"] == "drop:44000")
    assert a["fires"] is False and a["fires_reason"] == "switched_off"
    assert drop_firing.firing_sequences(v, testing=True) == []
    # ...and back on: the drop part "on" confirms it
    ds.apply_edit(URI, "parts", key="drop:44000", parts={"drop": "on"})
    assert _seq("drop:44000")["state"] == ds.STATE_CONFIRMED


def test_the_timeline_confirm_in_parts_mode_approves_every_part():
    _set_detected([(44_000, 40_000, 35_000, "suggested")])
    ds.apply_edit(URI, "parts", key="drop:44000", parts={"drop": "off"})
    ds.apply_edit(URI, "confirm", key="drop:44000")
    assert _seq("drop:44000")["parts"] == {"charge": "on", "lull": "on", "pre_drop": "absent",
                                           "drop": "on"}


def test_remove_dismisses_a_detection_and_deletes_an_added_drop():
    _set_detected([(44_000, 40_000, 35_000, "confident")])
    ds.apply_edit(URI, "remove", key="drop:44000")
    assert _seq("drop:44000")["state"] == ds.STATE_DISMISSED
    key = ds.apply_edit(URI, "add", drop_ms=90_000, fill=False).result
    ds.apply_edit(URI, "remove", key=key)
    assert all(s["key"] != key for s in ds.view(URI, triggers=[])["sequences"])


def test_a_part_edit_is_refused_on_a_removed_drop_and_writes_nothing():
    _set_detected([(44_000, 40_000, 35_000, "confident")])
    ds.apply_edit(URI, "remove", key="drop:44000")
    rev = ds.edits(URI)["rev"]
    with pytest.raises(ds.InvalidEdit):
        ds.apply_edit(URI, "parts", key="drop:44000", parts={"drop": "on"})
    with pytest.raises(ds.InvalidEdit):
        ds.apply_edit(URI, "parts", key="drop:44000", parts={"pre_drop": "on"})
    assert ds.edits(URI)["rev"] == rev


def test_one_part_edit_is_one_undo_step():
    _set_detected([(44_000, 40_000, 35_000, "suggested")])
    res = ds.apply_edit(URI, "approve", key="drop:44000")
    ds.apply_edit(URI, "restore", edits=res.before, expect=ds.edits_rev(res.after))
    assert _seq("drop:44000")["parts"]["drop"] == "waiting"
    assert ds.edits(URI)["overrides"] == {}


# ── 2b. the firing gate, pure ────────────────────────────────────────────

def _half_approved(key):
    """An override left half-approved from before ANY EDIT APPROVES (the drop
    approved, the build still waiting) — the shape the one-time
    scripts/approve_half_edited_drops.py exists for; no edit makes it now."""
    def fn(entry):
        entry.setdefault("overrides", {})[key] = {
            "detected": None, "state": "confirmed", "parts": {"drop": "on"}}
    ds._mutate(URI, fn)


def test_only_the_parts_that_play_are_members():
    _set_detected([(44_000, 40_000, 35_000, "suggested"), (90_000, 86_000, 80_000, "confident")])
    _half_approved("drop:44000")
    def lull_off(entry):          # a lull off, the rest waiting (pre-rule)
        entry.setdefault("overrides", {})["drop:90000"] = {
            "detected": None, "lull_off": True, "parts": {}}
    ds._mutate(URI, lull_off)
    v = ds.view(URI, triggers=[])
    by = {s.key: s for s in drop_firing.firing_sequences(v)}
    # approved drop, waiting build on a SUGGESTED tier: only the drop
    assert by["drop:44000"].members() == [("drop", 44_000)]
    # a confident tier plays its waiting charge on its own; the lull is off
    assert by["drop:90000"].members() == [("charge", 80_000), ("drop", 90_000)]
    # Testing plays the waiting build too
    by_t = {s.key: s for s in drop_firing.firing_sequences(v, testing=True)}
    assert by_t["drop:44000"].members() == [("charge", 35_000), ("lull", 40_000),
                                            ("drop", 44_000)]


def test_testing_adds_suggestions_and_never_what_he_removed_or_switched_off():
    _set_detected([(44_000, 40_000, 35_000, "suggested"), (90_000, 86_000, 80_000, "suggested"),
                   (130_000, 126_000, 120_000, "suggested")])
    ds.apply_edit(URI, "remove", key="drop:90000")
    ds.apply_edit(URI, "parts", key="drop:130000", parts={"drop": "off"})
    v = ds.view(URI, triggers=[])
    assert drop_firing.firing_sequences(v) == []
    keys = [s.key for s in drop_firing.firing_sequences(v, testing=True)]
    assert keys == ["drop:44000"]
    annotated = drop_firing.annotate(v, "analysed", False, testing=True)
    a = next(x for x in annotated["sequences"] if x["key"] == "drop:44000")
    assert a["fires"] is True and a["fires_reason"] == "testing"
    assert a["playing"] == ["charge", "lull", "drop"]
    assert annotated["firing"]["testing"] is True
    # Testing lifts the approval, never the mode
    t_only = drop_firing.annotate(v, "transitions", False, testing=True)
    assert not any(s["fires"] for s in t_only["sequences"])


def test_testing_protects_what_it_fires_at_fire_time_only():
    _set_detected([(44_000, 40_000, 35_000, "suggested")])
    v = ds.view(URI, triggers=[])
    assert drop_firing.windows_from_view(v) == []
    assert [w.key for w in drop_firing.windows_from_view(v, testing=True)] == ["drop:44000"]
    # the planner's windows never move with Testing (no re-plan on a toggle)
    assert drop_firing.protected_windows(URI, triggers=[]) == []


# ── 3. FROM THE SHOW SIDE ────────────────────────────────────────────────

def _seed_millones():
    scfg.DROP_SEQUENCES_FILE.write_text(json.dumps(
        {MILLONES: {"detected": FIX["songs"][MILLONES]["detected"]}}), encoding="utf-8")
    ds.reset()


def _his_millones():
    return [SpectraTrigger(id=t["id"], timestamp_ms=t["timestamp_ms"],
                           trigger_offset_ms=t["trigger_offset_ms"], enabled=t["enabled"],
                           source="authored",
                           action=FireResponseAction(event_class=t["event_class"],
                                                     intensity=t["intensity"]))
            for t in FIX["songs"][MILLONES]["his_phase_triggers"]]


class _Rec:
    def __init__(self):
        self.seq: list[tuple] = []
        self.played: list[dict] = []
        self.position = 0

    async def fire_sequence(self, cls, intensity, gap):
        self.seq.append((self.position, cls))

    async def nothing(self, *a, **k):
        return None


async def _noop(_uri):
    return None


class _Plan:
    flares: list = []
    scene_cues: list = []


def _sweep(testing: bool, mode: str = "analysed") -> _Rec:
    rec = _Rec()
    his = _his_millones()
    eng = TriggerEngine(
        list_triggers=lambda uri: list(his),
        scene_change_mode=lambda: mode,
        drop_testing=lambda: testing,
        drop_played=lambda r: rec.played.append(r),
        fire_sequence=rec.fire_sequence, fire_response=rec.nothing,
        fire_scene=rec.nothing, fire_analysed_flare=rec.nothing,
        analysed_plan=lambda uri, stored: _Plan(),
        render_intensity=lambda x: x, lead_ms=lambda t: 0,
        response_offset_ms=lambda a: 0, drop_offset_ms=lambda: 0,
        sequencer_enabled=lambda: False, select_scene=lambda i: "S",
        transition_intensity=lambda: 0.5, auto_generate=_noop, auto_refresh=_noop)
    stop = int(FIX["songs"][MILLONES]["detected"]["duration_ms"])

    async def run():
        await eng.on_track_state(MILLONES)
        await eng.plan_analysed_flares(MILLONES)
        for pos in range(0, stop + 200, 200):
            rec.position = pos
            await eng.tick(pos)
    asyncio.run(run())
    return rec


def _drops(rec: _Rec) -> list[int]:
    return [p for p, cls in rec.seq if cls == "drop"]


def _near(fired: list[int], ms: int) -> bool:
    return any(abs(p - ms) <= 400 for p in fired)


def _members_near(rec: _Rec, cls: str, ms: int) -> bool:
    return any(c == cls and abs(p - ms) <= 400 for p, c in rec.seq)


def test_with_testing_off_a_suggestion_waits_and_a_confident_drop_plays():
    _seed_millones()
    rec = _sweep(testing=False)
    fired = _drops(rec)
    assert _near(fired, 87_070)                 # confident
    assert not _near(fired, 39_314)             # suggested: waits for him
    assert not _near(fired, 96_114)


def test_with_testing_on_a_suggested_drop_plays_its_whole_build():
    _seed_millones()
    rec = _sweep(testing=True)
    assert _near(_drops(rec), 39_314)
    assert _members_near(rec, "lull", 37_939) and _members_near(rec, "charge", 32_497)
    # the panel hears every drop that played, newest last
    keys = [r["key"] for r in rec.played]
    assert "drop:39314" in keys and "drop:87070" in keys
    assert rec.played[-1]["uri"] == MILLONES and rec.played[-1]["at_ms"] > 0


def test_with_testing_on_an_off_part_a_switched_off_drop_and_a_removed_drop_never_play():
    _seed_millones()
    ds.apply_edit(MILLONES, "parts", key="drop:87070", parts={"lull": "off"})   # an off part
    ds.apply_edit(MILLONES, "parts", key="drop:96114", parts={"drop": "off"})   # switched off
    ds.apply_edit(MILLONES, "remove", key="drop:116002")                        # removed
    rec = _sweep(testing=True)
    fired = _drops(rec)
    assert _near(fired, 87_070) and not _members_near(rec, "lull", 81_962)
    assert not _near(fired, 96_114)
    assert not _near(fired, 116_002)
    assert _near(fired, 39_314)                 # an untouched suggestion still plays
    played = {r["key"] for r in rec.played}
    assert "drop:96114" not in played and "drop:116002" not in played


def test_approving_one_drop_plays_it_without_testing():
    _seed_millones()
    rec = _sweep(testing=False)
    assert not _near(_drops(rec), 166_594)      # a suggestion waits
    ds.apply_edit(MILLONES, "parts", key="drop:166594", parts={"drop": "on"})
    rec = _sweep(testing=False)
    assert _near(_drops(rec), 166_594)
    # ANY EDIT APPROVES: its build was approved with it, so it plays too
    assert _members_near(rec, "lull", 161_485)


def test_approving_only_its_lull_plays_the_drop_without_testing():
    # the Admiral's own case: "approving just the lull plays nothing outside
    # Testing" — not any more
    _seed_millones()
    ds.apply_edit(MILLONES, "parts", key="drop:166594", parts={"lull": "on"})
    rec = _sweep(testing=False)
    assert _near(_drops(rec), 166_594)
    assert _members_near(rec, "lull", 161_485)
