"""ANALYSED FLARES (2026-09-26) — the transitions that did not make the
density cut fire as flares (spectra/services/analysed_flares.py).

Proves: the spacing rules; an untriggered song fires a flare at each
unselected candidate through the REAL tick() crossing logic; the scope rule
(analysed / full-without-authored only — never "transitions", never an
authored song under "triggers_only" or "full"); and the engine choke point's
widened tier gate.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.models.trigger import FireSceneAction, SpectraTrigger
from spectra.services import analysed_flares, midsong_generator
from spectra.services.analysed_flares import (FLARE_MIN_SPACING_MS,
                                              SCENE_CUE_CLEARANCE_MS, FlareMoment,
                                              SongPlan)
from spectra.services.trigger_engine import TriggerEngine

URI = "spotify:track:analysed-flares"


def _cand(ms, intensity=0.5):
    return midsong_generator.CandidateMoment(ms, intensity, f"section:{ms}")


# ── the plan's spacing rules ─────────────────────────────────────────────


def test_plan_drops_flares_near_scene_cues_and_thins_close_flares(monkeypatch):
    kept = [_cand(10_000)]
    unselected = [
        _cand(10_000 + SCENE_CUE_CLEARANCE_MS - 1, 0.9),  # too close to a kept cue
        _cand(30_000, 0.4),
        _cand(30_000 + FLARE_MIN_SPACING_MS - 1, 0.8),     # beats its weaker neighbour
        _cand(50_000, 0.3),                                 # near a STORED scene cue
        _cand(70_000, 0.2),
    ]
    monkeypatch.setattr(midsong_generator, "plan_moments",
                        lambda uri: midsong_generator.MomentPlan(kept, unselected))
    stored = [SpectraTrigger(timestamp_ms=50_500, source="authored",
                             action=FireSceneAction(scene_id=None))]
    plan = analysed_flares.plan_for_song(URI, stored)
    assert [c.timestamp_ms for c in plan.scene_cues] == [10_000]
    assert [f.timestamp_ms for f in plan.flares] == [
        30_000 + FLARE_MIN_SPACING_MS - 1, 70_000]


def test_scope_rule():
    allowed = analysed_flares.analysed_flares_allowed
    assert allowed("analysed", False) and allowed("analysed", True)
    assert allowed("full", False)
    assert not allowed("full", True)
    assert not allowed("triggers_only", True)
    assert not allowed("transitions", False)


# ── the engine fires them ────────────────────────────────────────────────


def _engine(mode, stored, flares):
    fired: list[float] = []
    responses: list = []

    async def fire_flare(intensity):
        fired.append(intensity)

    async def fire_response(*a):
        responses.append(a)

    async def noop(*a, **k):
        return None

    te = TriggerEngine(
        list_triggers=lambda uri: list(stored),
        fire_scene=noop, fire_response=fire_response,
        fire_scene_update=noop, select_color_set=noop,
        select_scene=lambda i: None,
        scene_change_mode=lambda: mode,
        render_intensity=lambda x: x,
        sequencer_enabled=lambda: False,
        lead_ms=lambda t: 0, response_offset_ms=lambda a: 0,
        analysed_plan=lambda uri, st: SongPlan([], list(flares)),
        fire_analysed_flare=fire_flare,
    )
    return te, fired, responses


async def _play(te, positions):
    await te.on_track_state(URI)
    await te.plan_analysed_flares(URI)
    for p in positions:
        await te.tick(p)


FLARES = [FlareMoment(20_000, 0.3, "section:20000"),
          FlareMoment(40_000, 0.7, "section:40000")]
AUTHORED = [SpectraTrigger(timestamp_ms=90_000, source="authored",
                           action=FireSceneAction(scene_id="s1"))]


def test_untriggered_song_fires_a_flare_at_each_unselected_candidate():
    te, fired, responses = _engine("analysed", [], FLARES)
    asyncio.run(_play(te, [0, 19_900, 20_100, 39_900, 40_100, 60_000]))
    assert fired == [0.3, 0.7]
    assert responses == [], "an analysed flare never takes the authored path"


def test_fires_exactly_once_per_crossing():
    te, fired, _ = _engine("analysed", [], FLARES)
    asyncio.run(_play(te, [0, 20_100, 20_300, 20_500]))
    assert fired == [0.3]


@pytest.mark.parametrize("mode", ["triggers_only", "full"])
def test_untriggered_song_fires_under_the_fallback_modes(mode):
    te, fired, _ = _engine(mode, [], FLARES)
    asyncio.run(_play(te, [0, 20_100, 40_100]))
    assert fired == [0.3, 0.7]


@pytest.mark.parametrize("mode", ["triggers_only", "full"])
def test_authored_song_does_not_fire_analysed_flares(mode):
    te, fired, _ = _engine(mode, AUTHORED, FLARES)
    asyncio.run(_play(te, [0, 20_100, 40_100]))
    assert fired == []


def test_transitions_mode_never_fires_analysed_flares():
    te, fired, _ = _engine("transitions", [], FLARES)
    asyncio.run(_play(te, [0, 20_100, 40_100]))
    assert fired == []


def test_analysed_mode_fires_even_on_an_authored_song():
    te, fired, _ = _engine("analysed", AUTHORED, FLARES)
    asyncio.run(_play(te, [0, 20_100, 40_100]))
    assert fired == [0.3, 0.7]


def test_plan_for_a_stale_song_is_discarded():
    te, fired, _ = _engine("analysed", [], FLARES)

    async def run():
        await te.on_track_state(URI)
        await te.on_track_state("spotify:track:other")
        await te.plan_analysed_flares(URI)
        for p in [0, 20_100, 40_100]:
            await te.tick(p)
    asyncio.run(run())
    assert fired == []


def test_tick_plans_the_song_itself_in_the_background():
    te, fired, _ = _engine("analysed", [], FLARES)

    async def run():
        await te.on_track_state(URI)
        await te.tick(0)            # schedules the plan
        for _ in range(50):
            await asyncio.sleep(0.01)
            if te._flare_plan_uri == URI:
                break
        await te.tick(20_100)
    asyncio.run(run())
    assert fired == [0.3]


# ── the choke point's tier gate ──────────────────────────────────────────


@pytest.mark.parametrize("mode,analysed,expect", [
    ("analysed", True, None),
    ("analysed", False, "scene_change_mode"),
    ("full", True, None),
    ("triggers_only", True, None),
    ("transitions", True, "scene_change_mode"),
])
def test_response_gate_admits_analysed_only_for_analysed_flares(monkeypatch, mode, analysed, expect):
    from spectra.services import engine, room_controls
    monkeypatch.setattr(room_controls, "load_room_controls",
                        lambda: room_controls.RoomControlState(scene_change_mode=mode))
    assert engine._response_gate(True, analysed) == expect
