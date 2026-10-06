"""DROP SEQUENCES FIRE (drop-detection plan, phase 5 — spectra/services/
drop_firing.py is the binding statement).

  1. What fires under each scene-change mode, on the Admiral's four test
     songs (their real detections and his real phase triggers, captured
     from temp copies — tests/fixtures/drop_sequences_four_songs.json):
     confident detections where the analysed show plays, his (confirmed,
     edited, added) also under "My triggers only", never under
     "Transitions only"; suggestions and dismissals silent.
  2. Nothing double-fires against his own charge/lull/drop.
  3. Each member is the ordinary charge/lull/drop response, building to
     its own partner in the sequence.
  4. The protected window: no analysed scene change inside it, no analysed
     flare in a lull or on a drop; the planner keeps the drop moment out of
     its ranking.
  5. Fire history records each member; the views say what fires.

The trigger clock is the real TriggerEngine with its fire paths recorded;
the drop-sequence view is the real one, over the isolated store.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from spectra import config as scfg
from spectra.models.trigger import FireResponseAction, FireSceneAction, SpectraTrigger
from spectra.services import drop_firing, drop_sequences
from spectra.services.trigger_engine import TriggerEngine

FIX = json.loads((Path(__file__).parent / "fixtures" /
                  "drop_sequences_four_songs.json").read_text(encoding="utf-8"))
URI = {s["name"]: uri for uri, s in FIX["songs"].items()}
SONGS = list(URI)
MODES = ("transitions", "analysed", "triggers_only", "full")


def _seed(*uris: str) -> None:
    data = {u: {"detected": FIX["songs"][u]["detected"]} for u in uris}
    scfg.DROP_SEQUENCES_FILE.write_text(json.dumps(data), encoding="utf-8")
    drop_sequences.reset()


def _his(uri: str) -> list[SpectraTrigger]:
    return [SpectraTrigger(id=t["id"], timestamp_ms=t["timestamp_ms"],
                           trigger_offset_ms=t["trigger_offset_ms"],
                           enabled=t["enabled"], source="authored",
                           action=FireResponseAction(event_class=t["event_class"],
                                                     intensity=t["intensity"]))
            for t in FIX["songs"][uri]["his_phase_triggers"]]


def _beat(uri: str) -> float:
    return float(FIX["songs"][uri]["detected"]["beat_ms"])


def _duration(uri: str) -> int:
    return int(FIX["songs"][uri]["detected"]["duration_ms"])


class _Plan:
    def __init__(self, flares=(), scene_cues=()):
        self.flares = list(flares)
        self.scene_cues = list(scene_cues)


class _Rec:
    def __init__(self):
        self.seq: list[tuple] = []        # (position, class, intensity, gap)
        self.resp: list[tuple] = []       # his stored responses
        self.scenes: list[tuple] = []
        self.flares: list[tuple] = []
        self.position = 0

    async def fire_sequence(self, cls, intensity, gap):
        self.seq.append((self.position, cls, intensity, gap))

    async def fire_response(self, cls, intensity, gap=None):
        self.resp.append((self.position, cls, intensity, gap))

    async def fire_scene(self, scene_id, color_set_id, intensity):
        self.scenes.append((self.position, scene_id))

    async def fire_flare(self, intensity):
        self.flares.append((self.position, intensity))


def _engine(triggers, mode, rec, plan=None):
    return TriggerEngine(
        list_triggers=lambda uri: list(triggers),
        scene_change_mode=lambda: mode,
        fire_sequence=rec.fire_sequence, fire_response=rec.fire_response,
        fire_scene=rec.fire_scene, fire_analysed_flare=rec.fire_flare,
        analysed_plan=lambda uri, stored: plan or _Plan(),
        render_intensity=lambda x: x, lead_ms=lambda t: 0,
        response_offset_ms=lambda a: 0, sequencer_enabled=lambda: False,
        select_scene=lambda i: "S", transition_intensity=lambda: 0.5,
        auto_generate=_noop, auto_refresh=_noop)


async def _noop(_uri):
    return None


async def _sweep(engine, rec, uri, stop, step=200):
    await engine.on_track_state(uri)
    await engine.plan_analysed_flares(uri)
    for pos in range(0, stop + step, step):
        rec.position = pos
        await engine.tick(pos)


def _run(uri, triggers, mode, plan=None, stop=None) -> _Rec:
    rec = _Rec()
    eng = _engine(triggers, mode, rec, plan)
    asyncio.run(_sweep(eng, rec, uri, stop or _duration(uri)))
    return rec


def _fired_drops(rec: _Rec) -> list[int]:
    return [p for p, cls, *_ in rec.seq if cls == "drop"]


def _confident_drops(uri) -> list[int]:
    return [s["drop_ms"] for s in FIX["songs"][uri]["detected"]["sequences"]
            if s["tier"] == "confident"]


def _near(a: int, b: int, ms: float) -> bool:
    return abs(a - b) <= ms


# ═══ 1. what fires under each mode, on the four songs ═════════════════════

@pytest.mark.parametrize("song", SONGS)
@pytest.mark.parametrize("mode", MODES)
def test_with_his_triggers_only_what_the_rules_allow_fires(song, mode):
    uri = URI[song]
    _seed(uri)
    his = _his(uri)
    rec = _run(uri, his, mode)
    view = drop_sequences.view(uri, triggers=his)
    by_state = {s["drop_ms"]: s["state"] for s in view["sequences"]}
    for drop in _fired_drops(rec):
        state = next(st for d, st in by_state.items() if _near(drop, d, 200))
        assert state == "confident", (song, mode, drop, state)
    if mode == "analysed":
        expected = sorted(d for d, st in by_state.items() if st == "confident")
    else:
        # "full" / "triggers_only" on a song carrying his triggers: the
        # analysed show is off for it; nothing of his is confirmed yet.
        expected = []
    got = _fired_drops(rec)
    assert len(got) == len(expected), (song, mode, got, expected)
    for d, e in zip(got, expected):
        assert _near(d, e, 200)
    # his own triggers still fire wherever his triggers fire
    if mode in ("full", "triggers_only"):
        assert len(rec.resp) == len(his)
    else:
        assert rec.resp == []


@pytest.mark.parametrize("song", SONGS)
@pytest.mark.parametrize("mode", MODES)
def test_on_a_song_that_plays_the_analysed_show_confident_fire_and_suggestions_wait(song, mode):
    uri = URI[song]
    _seed(uri)
    rec = _run(uri, [], mode)          # no triggers of his: the analysed show plays
    got = _fired_drops(rec)
    if mode == "transitions":
        assert got == []
        return
    expected = sorted(_confident_drops(uri))
    assert len(got) == len(expected), (song, mode, got, expected)
    for d, e in zip(got, expected):
        assert _near(d, e, 200)
    suggested = [s["drop_ms"] for s in FIX["songs"][uri]["detected"]["sequences"]
                 if s["tier"] == "suggested"]
    for s in suggested:
        assert not any(_near(d, s, 200) for d in got), f"suggestion at {s} fired"


def test_the_four_songs_fire_something_somewhere():
    """A guard against an inert fixture: every song has a confident
    detection once his own triggers are out of the way."""
    for song in SONGS:
        assert _confident_drops(URI[song]), song


# ═══ 2. nothing double-fires against his own triggers ═════════════════════

@pytest.mark.parametrize("song", SONGS)
@pytest.mark.parametrize("mode", MODES)
def test_no_member_fires_on_top_of_his_own_trigger(song, mode):
    uri = URI[song]
    _seed(uri)
    # confirm every detection, so the his-tier gate is open too
    drop_sequences.apply_edit(uri, "confirm_all")
    for s in FIX["songs"][uri]["detected"]["sequences"]:
        try:
            drop_sequences.confirm(uri, s["key"])
        except drop_sequences.SequenceNotFound:
            pass
    his = _his(uri)
    rec = _run(uri, his, mode)
    reach = 2 * _beat(uri)
    for pos, cls, *_ in rec.seq:
        clash = [t for t in his if t.action.event_class == cls
                 and _near(pos, t.timestamp_ms, reach + 200)]
        assert not clash, (song, mode, cls, pos, [t.timestamp_ms for t in clash])


def test_confirming_a_suggestion_makes_it_his_under_my_triggers_only():
    uri = URI["Contra"]
    _seed(uri)
    his = _his(uri)
    assert _fired_drops(_run(uri, his, "triggers_only")) == []
    drop_sequences.confirm(uri, "drop:47612")
    rec = _run(uri, his, "triggers_only")
    assert [cls for _p, cls, *_ in rec.seq] == ["charge", "lull", "drop"]
    assert _near(_fired_drops(rec)[0], 47612, 200)
    # ...and still not under "Transitions only"
    assert _run(uri, his, "transitions").seq == []


def test_a_dismissed_detection_never_fires():
    uri = URI["100 Millones"]
    _seed(uri)
    before = _fired_drops(_run(uri, [], "analysed"))
    assert any(_near(d, 87070, 200) for d in before)
    drop_sequences.dismiss(uri, "drop:87070")
    after = _fired_drops(_run(uri, [], "analysed"))
    assert not any(_near(d, 87070, 200) for d in after)
    assert len(after) == len(before) - 1


def test_an_added_sequence_on_his_drop_stands_down_and_one_elsewhere_fires():
    uri = URI["Dopamine"]
    _seed(uri)
    his = _his(uri)
    drop_sequences.add(uri, 47900, lull_ms=41800, charge_ms=38000, fill=False)  # on his
    drop_sequences.add(uri, 130000, lull_ms=128000, charge_ms=124000, fill=False)
    rec = _run(uri, his, "triggers_only")
    assert [(cls) for _p, cls, *_ in rec.seq] == ["charge", "lull", "drop"]
    assert _near(_fired_drops(rec)[0], 130000, 200)


def test_a_member_on_his_own_lull_stands_down_alone():
    view = {"song": {"beat_ms": 500.0},
            "sequences": [{"key": "added:x", "origin": "added", "state": "added",
                           "drop_ms": 60000, "lull_ms": 58000, "charge_ms": 52000,
                           "step": None}],
            "authored": [], "authored_lone": [{"id": "his-lull", "kind": "lull",
                                               "timestamp_ms": 58300}]}
    (seq,) = drop_firing.firing_sequences(view)
    assert [c for c, _ms in seq.members()] == ["charge", "drop"]
    assert seq.stood_down == {"lull": "his-lull"}


def test_his_sequence_wins_over_a_detection_on_the_same_drop():
    view = {"song": {"beat_ms": 500.0},
            "sequences": [
                {"key": "drop:60000", "origin": "detected", "state": "confident",
                 "drop_ms": 60000, "lull_ms": 58000, "charge_ms": 52000, "step": 0.8},
                {"key": "added:y", "origin": "added", "state": "added",
                 "drop_ms": 60300, "lull_ms": None, "charge_ms": None, "step": None}],
            "authored": [], "authored_lone": []}
    (seq,) = drop_firing.firing_sequences(view)
    assert seq.key == "added:y"


# ═══ 3. each member is the ordinary response, building to its partner ═════

def test_members_build_to_their_own_partner():
    uri = URI["100 Millones"]
    _seed(uri)
    rec = _run(uri, [], "analysed")
    det = {s["drop_ms"]: s for s in FIX["songs"][uri]["detected"]["sequences"]}
    s = det[87070]
    fired = [(cls, gap, inten) for p, cls, inten, gap in rec.seq if s["charge_ms"] - 200 <= p <= 87300]
    assert [c for c, *_ in fired] == ["charge", "lull", "drop"]
    gaps = {c: g for c, g, _i in fired}
    assert gaps["charge"] == s["lull_ms"] - s["charge_ms"]
    assert gaps["lull"] == s["drop_ms"] - s["lull_ms"]
    assert gaps["drop"] is None
    intensities = {i for _c, _g, i in fired}
    assert intensities == {drop_firing.sequence_intensity(s["step"])}


def test_a_charge_with_no_lull_builds_to_its_drop():
    seq = drop_firing.FiringSequence(key="k", state="confident", origin="detected",
                                     his=False, drop_ms=10000, lull_ms=None,
                                     charge_ms=4000, intensity=0.8, beat_ms=500.0)
    assert seq.gap_ms("charge") == 6000
    assert seq.gap_ms("drop") is None


def test_the_intensity_follows_the_step_up():
    assert drop_firing.sequence_intensity(None) == drop_firing.DEFAULT_INTENSITY
    assert drop_firing.sequence_intensity(0.1) == drop_firing.INTENSITY_LOW
    assert drop_firing.sequence_intensity(2.0) == 1.0
    lo, hi = drop_firing.sequence_intensity(0.6), drop_firing.sequence_intensity(0.9)
    assert drop_firing.INTENSITY_LOW < lo < hi < 1.0


def test_the_default_fire_path_is_the_ordinary_response_choke_point(monkeypatch):
    from spectra.services import engine
    calls = []

    async def fake(event_class, intensity, gap_ms=None, via_trigger=False, analysed=False):
        calls.append((event_class, intensity, gap_ms, via_trigger, analysed))
    monkeypatch.setattr(engine, "fire_response_event", fake)
    eng = TriggerEngine(list_triggers=lambda uri: [])
    asyncio.run(eng._default_fire_sequence("lull", 0.7, 1500))
    assert calls == [("lull", 0.7, 1500, True, True)]


# ═══ 4. the protected window ═══════════════════════════════════════════════

def _gen_scene(at_ms, tid):
    return SpectraTrigger(id=tid, timestamp_ms=at_ms, source="generated",
                          generator_key=f"section:{at_ms}",
                          action=FireSceneAction(scene_id="S", intensity=0.5))


def _flare(at_ms):
    from spectra.services.analysed_flares import FlareMoment
    return FlareMoment(at_ms, 0.5, f"section:{at_ms}")


def test_the_window_holds_scene_changes_and_lull_flares_and_says_so():
    from spectra.services import fire_history
    uri = URI["100 Millones"]
    _seed(uri)
    s = next(x for x in FIX["songs"][uri]["detected"]["sequences"] if x["drop_ms"] == 87070)
    beat = _beat(uri)
    inside_charge = s["charge_ms"] + 1000
    in_tail = s["drop_ms"] + int(4 * beat)
    after = s["drop_ms"] + int(12 * beat)
    in_lull = s["lull_ms"] + 500
    at_drop = s["drop_ms"] + 100
    triggers = [_gen_scene(inside_charge, "g-in"), _gen_scene(in_tail, "g-tail"),
                _gen_scene(after, "g-after")]
    plan = _Plan(flares=[_flare(inside_charge + 600), _flare(in_lull), _flare(at_drop),
                         _flare(after + 3000)])
    rec = _run(uri, triggers, "analysed", plan, stop=after + 4000)
    scenes = [p for p, _s in rec.scenes if p > s["charge_ms"] - 400]
    assert len(scenes) == 1 and _near(scenes[0], after, 200), scenes
    flares = [p for p, _i in rec.flares if p > s["charge_ms"] - 400]
    assert len(flares) == 2, flares
    assert _near(flares[0], inside_charge + 600, 200) and _near(flares[1], after + 3000, 200)
    held = [e for e in fire_history.load_show_log()
            if e.get("bucket") == "deferred" and e.get("key") == "drop_window"]
    held_ids = sorted(e["detail"]["trigger_id"] for e in held)
    assert "g-in" in held_ids and "g-tail" in held_ids
    assert sum(1 for e in held if e["detail"]["what"] == "analysed flare") == 2
    # the sequence itself still fired
    assert any(_near(d, 87070, 200) for d in _fired_drops(rec))


def test_his_own_sequence_is_protected_too():
    """Plan section 2.3, Pop Off: generated scene cues stored inside two of
    his sequences. Under "Everything" they are held back now."""
    uri = URI["Pop Off"]
    _seed(uri)
    his = _his(uri)
    triggers = his + [_gen_scene(55389, "g-a"), _gen_scene(178303, "g-b"),
                      _gen_scene(140000, "g-free")]
    rec = _run(uri, triggers, "full")
    assert [p for p, _s in rec.scenes] == [140000]
    assert not _near(55389, 140000, 0)


def test_a_suggestion_protects_nothing():
    uri = URI["Contra"]
    _seed(uri)
    s = next(x for x in FIX["songs"][uri]["detected"]["sequences"] if x["drop_ms"] == 47612)
    rec = _run(uri, [_gen_scene(s["lull_ms"] + 300, "g")], "analysed", stop=60000)
    assert len(rec.scenes) == 1


def test_the_windows_cover_charge_to_two_bars_after_the_drop():
    view = {"song": {"beat_ms": 500.0},
            "sequences": [{"key": "drop:60000", "origin": "detected", "state": "confident",
                           "drop_ms": 60000, "lull_ms": 58000, "charge_ms": 52000}],
            "authored": [], "authored_lone": []}
    (w,) = drop_firing.windows_from_view(view)
    assert (w.start_ms, w.lull_ms, w.drop_ms, w.end_ms) == (52000, 58000, 60000, 64000)
    assert w.holds_scene_change(52000) and w.holds_scene_change(64000)
    assert not w.holds_scene_change(51999) and not w.holds_scene_change(64001)
    assert not w.silences_flare(55000)        # flares during the charge are fine
    assert w.silences_flare(58000) and w.silences_flare(59999)
    assert w.silences_flare(60900)            # on the drop (two beats)
    assert not w.silences_flare(61500)        # the tail allows flares


def test_the_fill_never_makes_a_scene_change_inside_a_window():
    from spectra.models.sequencer import CurvePoint
    from spectra.services import midsong_generator as mg
    w = drop_firing.Window("k", "sequence", 50000, 56000, 60000, 64000, 500.0)
    moments = [mg.CandidateMoment(t, 0.5, f"section:{t}", strength=1.0 / (i + 1),
                                  rank=i + 1)
               for i, t in enumerate((55000, 30000, 90000))]
    flat = [[CurvePoint(x=0.0, y=1.0), CurvePoint(x=1.0, y=1.0)]]
    chosen = mg._strongest_first_fill(moments, [{"energy_rms": 0.5}], 1.0, None, flat, (w,))
    assert sorted(m.timestamp_ms for m in chosen) == [30000, 90000]


def test_the_planner_takes_the_drop_moment_and_the_lull_out_of_the_ranking(monkeypatch):
    from spectra.models.sequencer import CurvePoint
    from spectra.services import analysis_reader, beat_snap, midsong_generator as mg, testbed_audio
    sections = [{"start_ms": s * 1000, "end_ms": (s + 10) * 1000, "energy_rms": e}
                for s, e in ((0, 0.2), (20, 0.9), (57, 0.1), (60, 1.0), (62, 0.5),
                             (90, 0.4), (120, 0.95))]
    monkeypatch.setattr(analysis_reader, "sections_for_uri", lambda uri: sections)
    monkeypatch.setattr(beat_snap, "resolve_song_placement", lambda *a, **k: None)
    monkeypatch.setattr(testbed_audio, "capture_offset_ms_or_zero", lambda uri: 0)
    monkeypatch.setattr(mg, "resolve_transition_count", lambda *a, **k: 100)
    monkeypatch.setattr(mg, "effective_intensity_scale_factor", lambda uri: 1.0)
    w = drop_firing.Window("k", "sequence", 50000, 56000, 60000, 64000, 500.0)
    flat = [[CurvePoint(x=0.0, y=1.0), CurvePoint(x=1.0, y=1.0)]]
    kw = dict(claimed=set(), hold_curves=flat, snap_enabled=False, window_beats=8,
              sensitivity=0.5, transitions_per_minute=8, scene_changes_per_minute=0)
    free = mg.plan_moments("u", protected=[], **kw)
    held = mg.plan_moments("u", protected=[w], **kw)
    acted = lambda p: sorted(m.timestamp_ms for m in p.kept + p.unselected)
    assert 60000 in [m.timestamp_ms for m in free.kept]
    assert 57000 in acted(free) and 60000 in acted(free)
    # the drop moment and the lull moment are no action at all now
    assert 60000 not in acted(held) and 57000 not in acted(held)
    assert {57000, 60000} <= {m.timestamp_ms for m in held.dropped}
    # 62 s sits in the tail: a flare, never a scene change
    assert 62000 not in [m.timestamp_ms for m in held.kept]
    assert 62000 in [m.timestamp_ms for m in held.unselected]


def test_an_edit_marks_the_songs_stored_cues_stale():
    from spectra.services import midsong_generator as mg
    uri = URI["100 Millones"]
    _seed(uri)
    before = mg.song_inputs(uri, claimed=set())["protected"]
    drop_sequences.dismiss(uri, "drop:87070")
    after = mg.song_inputs(uri, claimed=set())["protected"]
    assert before != after and len(after) == len(before) - 1
    assert mg.GENERATOR_VERSION == "3"


# ═══ 5. fire history and the views ═════════════════════════════════════════

def test_fire_history_records_each_member():
    from spectra.services import fire_history
    uri = URI["100 Millones"]
    _seed(uri)
    _run(uri, [], "analysed", stop=90000)
    entries = [e for e in fire_history.load_show_log()
               if e.get("bucket") == "triggers"
               and str(e.get("key", "")).startswith("drop_sequence:")
               and e["detail"].get("drop_sequence") == "drop:87070"]
    keys = [e["key"] for e in entries]
    assert keys == ["drop_sequence:charge", "drop_sequence:lull", "drop_sequence:drop"]
    d = entries[-1]["detail"]
    assert d["drop_sequence"] == "drop:87070" and d["member"] == "drop"
    assert d["state"] == "confident" and d["his"] is False
    assert d["members"] == ["charge", "lull", "drop"]


def test_the_annotated_view_says_what_fires_here():
    uri = URI["100 Millones"]
    _seed(uri)
    his = _his(uri)
    v = drop_sequences.view(uri, triggers=his)
    on = drop_firing.annotate(v, "analysed", True)
    off = drop_firing.annotate(v, "triggers_only", True)
    fires_on = {s["drop_ms"]: s["fires"] for s in on["sequences"]}
    assert fires_on[87070] is True and fires_on[59194] is False
    assert all(not s["fires"] for s in off["sequences"])
    reasons = {s["fires_reason"] for s in off["sequences"]}
    assert reasons <= {"analysed_show_off", "matches_yours", "waits_for_confirm"}
    assert off["firing"] == {"effective_mode": "triggers_only", "has_authored": True,
                             "analysed_applies": False, "his_applies": True}
    assert on["windows"] and on["windows"][0]["end_ms"] > on["windows"][0]["drop_ms"]


def test_a_sequence_of_his_never_counts_as_an_authored_trigger():
    """Confirming one drop must not silence the rest of a song's analysed
    show under "My triggers only" (the per-song fallback reads triggers
    only)."""
    uri = URI["100 Millones"]
    _seed(uri)
    drop_sequences.confirm(uri, "drop:87070")
    rec = _run(uri, [], "triggers_only")
    assert len(_fired_drops(rec)) == len(_confident_drops(uri))
