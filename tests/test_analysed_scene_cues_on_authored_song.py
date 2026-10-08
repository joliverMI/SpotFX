"""PLANNED SCENE CHANGES FIRE ON A SONG CARRYING HIS OWN TRIGGERS
(data/drop-scene-variety-plan/report.md option A, 2026-10-08).

A song with his own triggers is never auto-generated, so under "Transitions
+ analysed" (his triggers silenced) it held no stored analysed scene cue
and played its whole length on the scene picked at song start — FINA sat on
Fish through 13 drops while the markers drew 6 planned scene changes. The
trigger engine now fires the plan's KEPT cues itself (spectra/services/
analysed_flares.py, PLANNED SCENE CHANGES FIRE TOO).

Driven on FINA's real data, captured from a temp copy of the live stores
(tests/fixtures/fina_planned_scene_changes.json): his 71 authored triggers,
the drop-sequence store (detection + his 16 confirmations) and the plan the
real planner produced under his live room settings. The trigger clock is the
real TriggerEngine with its fire paths recorded; the drop-sequence view and
its protected windows are the real ones over the isolated store; the markers
are the real GET /api/analysed-plan body builder.

  1. "analysed": each of the 6 kept cues fires, through the planned-cue
     path, and is recorded in the show log; none of his triggers fire.
  2. "triggers_only" and "full" on his song: no planned cue fires (his own
     triggers govern there); "transitions": nothing analysed at all.
  3. A song holding stored generated cues fires those and never the plan —
     no double fire.
  4. The Timeline markers are exactly what fires, including a planned cue a
     drop sequence's protected window holds back (neither drawn nor fired,
     and the hold is recorded).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from spectra import config as scfg
from spectra.api import analysed_plan as plan_api
from spectra.models.trigger import FireSceneAction, SpectraTrigger
from spectra.services import (analysed_flares, drop_firing, drop_sequences,
                              fire_history, midsong_generator)
from spectra.services.trigger_engine import TriggerEngine

FIX = json.loads((Path(__file__).parent / "fixtures" /
                  "fina_planned_scene_changes.json").read_text(encoding="utf-8"))
URI = FIX["uri"]
HIS = [SpectraTrigger.model_validate(t) for t in FIX["triggers"]]
KEPT = [midsong_generator.CandidateMoment(**m) for m in FIX["plan"]["scene_cues"]]
FLARES = [analysed_flares.FlareMoment(**m) for m in FIX["plan"]["flares"]]
DURATION = int(FIX["drop_sequences_store"]["detected"]["duration_ms"])
STEP = 200


def _plan(scene_cues=None) -> analysed_flares.SongPlan:
    return analysed_flares.SongPlan(list(KEPT if scene_cues is None else scene_cues),
                                    list(FLARES), FIX["plan"]["rank_of"])


@pytest.fixture(autouse=True)
def _seed_drops():
    scfg.DROP_SEQUENCES_FILE.write_text(
        json.dumps({URI: FIX["drop_sequences_store"]}), encoding="utf-8")
    drop_sequences.reset()
    yield
    drop_sequences.reset()


class _Rec:
    def __init__(self):
        self.position = 0
        self.planned: list[int] = []      # positions a generated cue fired at
        self.authored: list[int] = []     # positions his fire_scene fired at
        self.responses: list[tuple] = []

    async def fire_scene(self, scene_id, color_set_id, intensity):
        self.authored.append(self.position)

    async def fire_planned_scene(self, scene_id, color_set_id, intensity):
        self.planned.append(self.position)

    async def fire_response(self, cls, intensity, gap=None):
        self.responses.append((self.position, cls))

    async def noop(self, *_a, **_k):
        return None


def _engine(triggers, mode, rec, plan) -> TriggerEngine:
    return TriggerEngine(
        list_triggers=lambda uri: list(triggers),
        scene_change_mode=lambda: mode,
        fire_scene=rec.fire_scene, fire_planned_scene=rec.fire_planned_scene,
        fire_response=rec.fire_response, fire_sequence=rec.noop,
        fire_analysed_flare=rec.noop, fire_scene_update=rec.noop,
        select_color_set=rec.noop,
        analysed_plan=lambda uri, stored: plan,
        render_intensity=lambda x: x, lead_ms=lambda t: 0,
        response_offset_ms=lambda a: 0, sequencer_enabled=lambda: False,
        select_scene=lambda i: "S", select_scene_from_pool=lambda p: "S",
        transition_intensity=lambda: 0.5,
        auto_generate=rec.noop, auto_refresh=rec.noop)


async def _sweep(engine, rec, stop=DURATION):
    await engine.on_track_state(URI)
    await engine.plan_analysed_flares(URI)
    for pos in range(0, stop + STEP, STEP):
        rec.position = pos
        await engine.tick(pos)


def _run(triggers, mode, plan=None) -> tuple[_Rec, TriggerEngine]:
    rec = _Rec()
    eng = _engine(triggers, mode, rec, plan or _plan())
    asyncio.run(_sweep(eng, rec))
    return rec, eng


def _crossed(fired: list[int], cue_ms: int) -> bool:
    """A cue at cue_ms fires on the first tick at or after it."""
    return any(cue_ms <= p < cue_ms + STEP for p in fired)


# ═══ 0. the fixture is the case the report measured ═══════════════════════

def test_the_fixture_is_fina_with_his_triggers_and_six_kept_cues():
    assert FIX["room"]["scene_change_mode"] == "analysed"
    assert any(t.source == "authored" for t in HIS)
    assert not analysed_flares.has_stored_scene_cues(HIS)
    assert [m.timestamp_ms for m in KEPT] == [42074, 100658, 116761,
                                              150070, 165860, 205972]


# ═══ 1. "analysed": the planned scene changes fire, and are logged ═══════

def test_analysed_fires_every_kept_cue_through_the_planned_path():
    rec, _eng = _run(HIS, "analysed")
    assert len(rec.planned) == len(KEPT), rec.planned
    for m in KEPT:
        assert _crossed(rec.planned, m.timestamp_ms), m
    # his own triggers stay silenced in this mode
    assert rec.authored == []
    assert rec.responses == []


def test_each_planned_fire_is_recorded_in_the_show_log():
    _run(HIS, "analysed")
    entries = [e for e in fire_history.load_show_log(uri=URI)
               if e.get("bucket") == "triggers"
               and (e.get("detail") or {}).get("planned_scene_cue")]
    assert len(entries) == len(KEPT)
    for e, m in zip(entries, KEPT):
        d = e["detail"]
        assert e["key"] == "generated:fire_scene"
        assert d["trigger_id"] == analysed_flares.SCENE_CUE_ID_PREFIX + m.generator_key
        assert d["source"] == "generated" and d["action_kind"] == "fire_scene"


# ═══ 2. the other modes leave his song alone ══════════════════════════════

def test_triggers_only_fires_none_of_the_plan_and_all_of_his_scenes():
    rec, _eng = _run(HIS, "triggers_only")
    assert rec.planned == []
    his_scenes = [t for t in HIS if t.enabled and t.action.kind == "fire_scene"]
    assert len(rec.authored) == len(his_scenes)


def test_full_on_his_song_fires_none_of_the_plan():
    """The analysed show (flares and planned cues alike) is off on a song
    carrying his triggers under "Everything" — his own triggers govern."""
    rec, _eng = _run(HIS, "full")
    assert rec.planned == []


def test_full_on_an_unauthored_song_fires_the_plan_until_cues_are_stored():
    rec, _eng = _run([], "full")
    assert len(rec.planned) == len(KEPT)


def test_transitions_fires_nothing_analysed():
    rec, _eng = _run(HIS, "transitions")
    assert rec.planned == [] and rec.authored == []


# ═══ 3. stored generated cues win — never both ════════════════════════════

def _clear_times(n: int) -> list[int]:
    """n moments outside every protected window and away from the kept cues."""
    windows = drop_firing.protected_windows(URI, HIS)
    out = []
    for ms in range(20000, DURATION, 1000):
        if any(w.holds_scene_change(ms) for w in windows):
            continue
        if any(abs(ms - m.timestamp_ms) < 5000 for m in KEPT):
            continue
        if out and ms - out[-1] < 20000:
            continue
        out.append(ms)
    assert len(out) >= n
    return out[:n]


def test_a_song_with_stored_generated_cues_fires_those_and_never_the_plan():
    times = _clear_times(2)
    stored = [SpectraTrigger(id=f"gen-{ms}", timestamp_ms=ms, source="generated",
                             generator_key=f"section:{ms}",
                             action=FireSceneAction(intensity=0.6))
              for ms in times]
    rec, eng = _run(HIS + stored, "analysed")
    assert len(rec.planned) == 2, rec.planned
    assert all(_crossed(rec.planned, ms) for ms in times)
    for m in KEPT:
        assert not _crossed(rec.planned, m.timestamp_ms), m
    logged = [e for e in fire_history.load_show_log(uri=URI)
              if (e.get("detail") or {}).get("planned_scene_cue")]
    assert logged == []


def test_a_disabled_stored_cue_does_not_count_as_stored():
    """has_stored_scene_cues reads ENABLED stored generated cues — the same
    test scene_change_moments falls back on, so markers and fires agree."""
    off = SpectraTrigger(id="gen-off", timestamp_ms=60000, source="generated",
                         enabled=False, action=FireSceneAction(intensity=0.6))
    rec, _eng = _run(HIS + [off], "analysed")
    assert len(rec.planned) == len(KEPT)


# ═══ 4. the markers are what fires ════════════════════════════════════════

def _markers(monkeypatch, eng, stored, mode, plan) -> list[int]:
    from spectra.services.room_controls import RoomControlState
    monkeypatch.setattr(plan_api, "trigger_engine", eng)
    monkeypatch.setattr(plan_api, "load_room_controls",
                        lambda: RoomControlState(scene_change_mode=mode))
    monkeypatch.setattr(analysed_flares, "plan_for_song", lambda uri, s=(): plan)
    body = plan_api._plan(URI, list(stored))
    return [e["timestamp_ms"] for e in body["scene_changes"]]


def _window_cue() -> midsong_generator.CandidateMoment:
    """A planned cue placed INSIDE one of FINA's protected windows — the
    planner never keeps one there, but a plan computed before an edit can."""
    windows = drop_firing.protected_windows(URI, HIS)
    assert windows
    w = windows[len(windows) // 2]
    return midsong_generator.CandidateMoment(
        timestamp_ms=w.drop_ms, intensity=0.8, generator_key="section:held",
        rank=1, rank_of=22)


@pytest.mark.parametrize("cached", [True, False], ids=["while-playing", "not-playing"])
def test_markers_equal_the_planned_fires_including_a_window_hold(monkeypatch, cached):
    held = _window_cue()
    plan = _plan(sorted([*KEPT, held], key=lambda m: m.timestamp_ms))
    rec = _Rec()
    eng = _engine(HIS, "analysed", rec, plan)
    asyncio.run(_sweep(eng, rec))
    fired_cues = [m.timestamp_ms for m in plan.scene_cues
                  if _crossed(rec.planned, m.timestamp_ms)]
    assert fired_cues == [m.timestamp_ms for m in KEPT]
    assert len(rec.planned) == len(KEPT)          # the held one did not fire
    holds = [e for e in fire_history.load_show_log(uri=URI)
             if e.get("bucket") == "deferred" and e.get("key") == "drop_window"]
    assert [h["detail"]["trigger_id"] for h in holds] == [
        analysed_flares.SCENE_CUE_ID_PREFIX + "section:held"]

    if not cached:
        eng = _engine(HIS, "analysed", _Rec(), plan)    # nothing cached
        assert eng.cached_scene_cues(URI) is None
    else:
        assert eng.cached_scene_cues(URI) is not None
    assert _markers(monkeypatch, eng, HIS, "analysed", plan) == fired_cues


def test_markers_are_empty_where_the_plan_does_not_fire(monkeypatch):
    rec = _Rec()
    eng = _engine(HIS, "triggers_only", rec, _plan())
    assert _markers(monkeypatch, eng, HIS, "triggers_only", _plan()) == []
    assert _markers(monkeypatch, eng, HIS, "full", _plan()) == []
