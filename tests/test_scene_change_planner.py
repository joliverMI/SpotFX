"""THE SCENE-CHANGE PLANNER (2026-10-04, data/scene-change-ranking-plan/
report.md, the Admiral's "use all recommendations") — the strongest
analysed transitions become the real scene changes.

  1. Rank by SECTION-ENERGY CHANGE, not the one-beat bass jump.
  2. Two transitions placed on the same moment are one: the stronger keeps it.
  3. Strongest-first fill: a transition is a scene change when it fits the
     hold in BOTH directions around those already chosen and the song
     start; an optional scene-changes-per-minute ceiling, off by default.
     Everything else in the total-actions budget is a flare.
  4. Leftovers are ordinary (normal-intensity) analysed flares.
  5. A trigger-time scene pick never "changes" to the scene already showing.
  6. A planned scene change fires with a 1.5 s dwell tolerance.

Pure planner pieces are driven directly; the play-time half goes through
the real fire_scene_by_id and TriggerEngine with storage isolated.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fx import device_model
from spectra import config as scfg
from spectra.models.scene import SceneV2
from spectra.models.sequencer import CurvePoint
from spectra.models.trigger import FireSceneAction, SpectraTrigger
from spectra.services import dwell, midsong_generator as mg

URI = "spotify:track:planner"
STEM = "Planner Artist - Planner Song"
FLAT_10S = [[CurvePoint(x=0.0, y=10.0), CurvePoint(x=1.0, y=10.0)]]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra.services import analysis_reader
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    for name, file in (("AUDIO_SHAPES_DIR", "audio_shapes"),
                       ("TESTBED_ANALYSIS_DIR", "testbed"),
                       ("TRIGGERS_FILE", "triggers.json"),
                       ("ROOM_CONTROLS_FILE", "room_controls.json"),
                       ("SCENES_FILE", "scenes.json"),
                       ("SEQUENCER_FILE", "sequencer.json"),
                       ("COLOR_SETS_FILE", "color_sets.json"),
                       ("ROOM_COLOR_FILE", "room_color.json"),
                       ("INTENSITY_SCALE_MARKS_FILE", "marks.json")):
        monkeypatch.setattr(scfg, name, tmp_path / file)
    scfg.AUDIO_SHAPES_DIR.mkdir()
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({}))
    device_model.refresh()
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False
    analysis_reader._capture_offset_cache.clear()
    monkeypatch.setattr(mg, "_hold_curves_cache", None)
    monkeypatch.setattr(mg, "effective_intensity_scale_factor", lambda uri: 1.0)


def _moment(t_s, rank, intensity=0.5):
    return mg.CandidateMoment(int(t_s * 1000), intensity, f"section:{int(t_s * 1000)}",
                              strength=1.0 / rank, rank=rank)


def _fill(moments, ceiling=None, start_energy=0.5):
    by_strength = sorted(moments, key=lambda m: m.rank)
    chosen = mg._strongest_first_fill(by_strength, [{"energy_rms": start_energy}],
                                      1.0, ceiling, FLAT_10S)
    return sorted(int(m.timestamp_ms / 1000) for m in chosen)


# ── 1. the rank ────────────────────────────────────────────────────────────

def test_the_rank_is_the_section_energy_change():
    sections = [{"energy_rms": 0.2}, {"energy_rms": 0.9}, {"energy_rms": 0.6},
                {"energy_rms": 0.65}]
    assert mg.section_energy_change(sections) == pytest.approx([0.0, 0.7, 0.3, 0.05])


# ── 3. strongest-first fill ────────────────────────────────────────────────

def test_the_strongest_transition_is_always_the_scene_change():
    """Today's first-come-first-served gate gave the 20s moment the change
    and deferred the stronger one 5s later; the planner does the opposite."""
    assert _fill([_moment(20, rank=2), _moment(25, rank=1), _moment(40, rank=3)]) == [25, 40]


def test_a_scene_change_must_fit_the_hold_in_both_directions():
    """The 30s moment is clear of the 20s change behind it, but the 36s
    change already chosen sits inside ITS hold ahead of it."""
    assert _fill([_moment(36, rank=1), _moment(20, rank=2), _moment(30, rank=3)]) == [20, 36]


def test_nothing_changes_the_scene_inside_the_song_start_hold():
    assert _fill([_moment(8, rank=1), _moment(30, rank=2)]) == [30]


def test_the_ceiling_stops_the_fill():
    moments = [_moment(15 + 12 * i, rank=i + 1) for i in range(6)]
    assert len(_fill(moments)) == 6
    assert _fill(moments, ceiling=2) == [15, 27]


def test_a_quiet_moment_holds_the_room_longer_than_a_loud_one():
    curves = [dwell.DEFAULT_DWELL_CURVE]
    assert mg.planning_hold_s(0.0, 1.0, curves) > mg.planning_hold_s(1.0, 1.0, curves)
    assert mg.planning_hold_s(0.0, 1.0, curves) == pytest.approx(16.0 + mg.PLAN_HOLD_MARGIN_S)


def test_the_hold_is_the_longest_enabled_scenes_dwell(monkeypatch):
    from spectra.models.scene import CurveAttachment
    from spectra.services import scene_store
    scene_store.save(SceneV2(id="slow", name="slow", dwell_curve=CurveAttachment(
        inline_points=[{"x": 0.0, "y": 30.0}, {"x": 1.0, "y": 30.0}])))
    scene_store.save(SceneV2(id="off", name="off", disabled=True, dwell_curve=CurveAttachment(
        inline_points=[{"x": 0.0, "y": 90.0}, {"x": 1.0, "y": 90.0}])))
    curves = mg.planning_hold_curves()
    assert mg.planning_hold_s(0.5, 1.0, curves) == pytest.approx(30.0 + mg.PLAN_HOLD_MARGIN_S), \
        "the disabled scene's longer curve is not one the room can fire"


# ── the whole plan on a song ───────────────────────────────────────────────

def _write_song(sections, beats=None, tempo_bpm=None):
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.json").write_text(json.dumps({"spotify_uri": URI}))
    doc = {"spotify_uri": URI, "sections": sections}
    if beats is not None:
        doc["beats"] = beats
    if tempo_bpm is not None:
        doc["tempo_bpm"] = tempo_bpm
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.librosa.json").write_text(json.dumps(doc))


def _sections(pairs, end):
    """pairs: [(start_ms, energy)] after an opening section at 0."""
    marks = [(0, 0.5), *pairs]
    return [{"start_ms": a, "end_ms": (marks[i + 1][0] if i + 1 < len(marks) else end),
             "energy_rms": e} for i, (a, e) in enumerate(marks)]


def test_the_plan_splits_actions_into_scene_changes_and_flares_by_rank(monkeypatch):
    monkeypatch.setattr(mg, "resolve_transition_count", lambda uri, sections, rate: 4)
    # energy changes: 30s +0.4 (rank 1), 34s -0.3 (rank 3), 60s +0.35 (rank 2),
    # 90s -0.1 (rank 4), 100s +0.05 (rank 5, past the budget)
    _write_song(_sections([(30_000, 0.9), (34_000, 0.6), (60_000, 0.95),
                           (90_000, 0.85), (100_000, 0.9)], end=120_000))
    plan = mg.plan_moments(URI, snap_enabled=False, window_beats=1, sensitivity=1.5,
                           transitions_per_minute=1, scene_changes_per_minute=0,
                           hold_curves=FLAT_10S)
    assert [m.timestamp_ms for m in plan.kept] == [30_000, 60_000, 90_000]
    assert [m.timestamp_ms for m in plan.unselected] == [34_000], \
        "4s after a stronger change: an ordinary flare"
    assert [m.timestamp_ms for m in plan.dropped] == [100_000], "past the total-actions budget"
    assert {m.generator_key: m.rank for m in plan.kept} == {
        "section:30000": 1, "section:60000": 2, "section:90000": 4}
    assert plan.rank_of == 5


def test_two_transitions_placed_on_one_moment_are_one(monkeypatch):
    """With no edges and a coarse downbeat grid, 31.0s and 31.2s both snap to
    the 31s downbeat: the stronger keeps the moment, the other is dropped."""
    monkeypatch.setattr(mg, "resolve_transition_count", lambda uri, sections, rate: 99)
    beats = [{"ms": i * 500, "is_downbeat": i % 2 == 0, "rms_bass": 0.5} for i in range(300)]
    _write_song(_sections([(31_000, 0.6), (31_200, 0.95)], end=120_000),
                beats=beats, tempo_bpm=120.0)
    plan = mg.plan_moments(URI, snap_enabled=True, window_beats=1, sensitivity=1.5,
                           transitions_per_minute=1, scene_changes_per_minute=0,
                           hold_curves=FLAT_10S)
    actions = plan.kept + plan.unselected
    assert [m.generator_key for m in actions] == ["section:31200"], \
        "the 0.35 change outranks the 0.1 change on the shared moment"
    assert [m.generator_key for m in plan.dropped] == ["section:31000"]
    assert plan.rank_of == 1


def test_the_ceiling_setting_lowers_the_count_and_reaches_the_stamp(monkeypatch):
    from spectra.services import room_controls
    monkeypatch.setattr(mg, "resolve_transition_count", lambda uri, sections, rate: 99)
    _write_song(_sections([(20_000 + 15_000 * i, 0.2 + 0.1 * (i % 2)) for i in range(6)],
                          end=120_000))
    before = mg.generator_stamp(URI)
    room_controls.save_room_controls(room_controls.RoomControlState(
        scene_changes_per_minute=1.0, midsong_snap_to_beat=False))
    plan = mg.plan_moments(URI, hold_curves=FLAT_10S)
    assert len(plan.kept) == 2, "1/min x 2 minutes x factor 1.0"
    assert len(plan.unselected) == 4
    assert mg.generator_stamp(URI) != before, "a ceiling change marks the song stale"


def test_storage_keeps_only_the_scene_changes(monkeypatch):
    from spectra.services import trigger_store
    monkeypatch.setattr(mg, "resolve_transition_count", lambda uri, sections, rate: 99)
    _write_song(_sections([(30_000, 0.9), (34_000, 0.6), (60_000, 0.95)], end=120_000))
    mg.generate_for_song(URI)
    stored = sorted(t.timestamp_ms for t in trigger_store.list_for_song(URI))
    plan = mg.plan_moments(URI)
    assert stored == [m.timestamp_ms for m in plan.kept]
    assert 34_000 not in stored


# ── 4. leftovers are ordinary flares ───────────────────────────────────────

def test_leftover_actions_are_the_analysed_flares(monkeypatch):
    from spectra.services import analysed_flares
    monkeypatch.setattr(mg, "resolve_transition_count", lambda uri, sections, rate: 99)
    monkeypatch.setattr(mg, "planning_hold_curves", lambda: FLAT_10S)
    _write_song(_sections([(30_000, 0.9), (34_000, 0.6), (60_000, 0.95)], end=120_000))
    plan = analysed_flares.plan_for_song(URI, [])
    assert [m.timestamp_ms for m in plan.scene_cues] == [30_000, 60_000]
    assert [m.timestamp_ms for m in plan.flares] == [34_000]


def test_an_analysed_flare_fires_at_the_cues_own_render_intensity():
    """Not the deferral's doubled flare: the engine hands the flare path the
    cue's own intensity through the ordinary render scale."""
    from spectra.services.trigger_engine import TriggerEngine
    flares = []

    async def fire_flare(intensity):
        flares.append(intensity)

    async def run():
        eng = TriggerEngine(list_triggers=lambda u: [], fire_analysed_flare=fire_flare,
                            render_intensity=lambda raw: raw * 0.5,
                            scene_change_mode=lambda: "analysed")
        plan = type("P", (), {"flares": [type("F", (), {
            "timestamp_ms": 5_000, "intensity": 0.6, "generator_key": "section:5000",
            "snap_grid": None, "snap_moved_ms": None,
            "trigger_id": "analysed-flare:section:5000"})()], "scene_cues": []})()
        eng._analysed_plan = lambda uri, stored: plan
        await eng.on_track_state(URI)
        await eng.plan_analysed_flares(URI, [])
        await eng.tick(4_900)
        await eng.tick(5_100)

    asyncio.run(run())
    assert flares == [pytest.approx(0.3)]


# ── 5. never "change" to the scene already showing ─────────────────────────

def test_the_trigger_time_pick_excludes_the_scene_showing(monkeypatch):
    from spectra.services import scene_store, selection_kernel, sequencer_store
    from spectra.services.trigger_engine import TriggerEngine
    scene_store.save(SceneV2(id="a", name="a"))
    seen = {}
    real = selection_kernel.select

    def spy(candidates, **kw):
        seen["current_id"] = kw.get("current_id")
        return real(candidates, **kw)

    monkeypatch.setattr(selection_kernel, "select", spy)
    monkeypatch.setattr(sequencer_store, "load_config", lambda: type(
        "C", (), {"entries": {}, "affinity": {}})())
    monkeypatch.setattr(sequencer_store, "load_curves", lambda: {})
    dwell.note_fired(scene_store.get_by_id("a"), 0.5)
    TriggerEngine()._default_select_scene(0.5)
    assert seen["current_id"] == "a"


def test_a_lookahead_pin_on_the_scene_now_showing_is_dropped():
    from spectra.services import scene_store
    from spectra.services.trigger_engine import TriggerEngine, _PinnedPick
    scene_store.save(SceneV2(id="a", name="a"))
    scene_store.save(SceneV2(id="b", name="b"))
    eng = TriggerEngine()
    pin = _PinnedPick(scene_id="b", lead_ms=100, force_scene=(False, None))
    assert eng._pin_still_valid(pin)
    dwell.note_fired(scene_store.get_by_id("b"), 0.5)
    assert not eng._pin_still_valid(pin), "firing the pinned scene again would change nothing"


# ── 6. the planned-cue tolerance ───────────────────────────────────────────

def _fake_compiler(monkeypatch, fired):
    from spectra.services import scene_compiler

    async def fake(scene, *, intensity=0.5, color_set=None, dry_run=True, rng=None):
        fired.append(scene.id)
        return {"dry_run": dry_run, "writes": []}
    monkeypatch.setattr(scene_compiler, "fire_scene", fake)


def _fake_update(monkeypatch, calls):
    from spectra.services import engine

    async def fake(intensity):
        calls.append(intensity)
        return {"result": "flare"}
    monkeypatch.setattr(engine, "fire_scene_update_event", fake)


def test_a_planned_change_fires_with_up_to_1_5s_of_hold_left(monkeypatch):
    import time as time_mod
    from spectra.services import scene_store
    from spectra.services.scene_sequencer import fire_scene_by_id
    scene_store.save(SceneV2(id="a", name="a"))
    scene_store.save(SceneV2(id="b", name="b"))
    fired, deferred = [], []
    _fake_compiler(monkeypatch, fired)
    _fake_update(monkeypatch, deferred)
    dwell.note_fired(scene_store.get_by_id("a"), 1.0, now_ms=1_000_000)   # 4s hold
    monkeypatch.setattr(time_mod, "time", lambda: 1_003_000 / 1000.0)     # 1s owed

    held = asyncio.run(fire_scene_by_id("b", intensity=0.5))
    assert held["skipped"] == "dwell" and fired == [], "no tolerance for an ordinary caller"
    landed = asyncio.run(fire_scene_by_id(
        "b", intensity=0.5, dwell_tolerance_s=dwell.PLANNED_CUE_TOLERANCE_S))
    assert fired == ["b"] and landed["dwell_tolerance_used_s"] == pytest.approx(1.0)

    dwell.note_fired(scene_store.get_by_id("a"), 1.0, now_ms=1_003_000)
    monkeypatch.setattr(time_mod, "time", lambda: 1_005_000 / 1000.0)     # 2s owed
    over = asyncio.run(fire_scene_by_id(
        "b", intensity=0.5, dwell_tolerance_s=dwell.PLANNED_CUE_TOLERANCE_S))
    assert over["skipped"] == "dwell", "beyond the tolerance it is still held"


def test_only_generated_cues_take_the_planned_path():
    from spectra.services.trigger_engine import TriggerEngine
    calls = []

    async def plain(scene_id, color_set_id, intensity):
        calls.append(("plain", scene_id))

    async def planned(scene_id, color_set_id, intensity):
        calls.append(("planned", scene_id))

    gen = SpectraTrigger(timestamp_ms=1_000, source="generated", generator_key="section:1000",
                         action=FireSceneAction(scene_id="s1"))
    mine = SpectraTrigger(timestamp_ms=2_000, action=FireSceneAction(scene_id="s2"))

    async def run():
        eng = TriggerEngine(list_triggers=lambda u: [gen, mine], fire_scene=plain,
                            fire_planned_scene=planned, scene_change_mode=lambda: "full",
                            lead_ms=lambda t: 0, analysed_plan=lambda u, s: type(
                                "P", (), {"flares": [], "scene_cues": []})())
        await eng.on_track_state(URI)
        await eng.tick(500)
        await eng.tick(2_500)

    asyncio.run(run())
    assert calls == [("planned", "s1"), ("plain", "s2")]
