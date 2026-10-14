"""GET /api/upcoming (spectra/api/upcoming.py) — proved from the SHOW SIDE,
the AGENTS.md standard: it must list exactly what the trigger engine's own
tick() actually fires, never a re-derived idea of what "should" fire.

Two modes proved against a real swept TriggerEngine.tick():
  - a song playing under "triggers_only" with his own authored triggers,
  - the planned-analysed-events path (his triggers absent).
And a drop sequence whose confidence never clears "confident" — a
SUGGESTED, unconfirmed member — proved excluded (`waits_for_confirm`),
never shown as upcoming.
"""
from __future__ import annotations

import asyncio

import pytest

import drop_synth

URI = "spotify:track:upcoming-api-1"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "AUDIO_SHAPES_DIR", tmp_path / "audio_shapes")
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", tmp_path / "triggers.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    (tmp_path / "profiles").mkdir()
    drop_synth.reset_index()
    yield
    drop_synth.reset_index()


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _mode(mode):
    from spectra.services import room_controls
    room_controls.save_room_controls(room_controls.RoomControlState(scene_change_mode=mode))


def test_upcoming_matches_exactly_what_tick_fires_under_his_own_triggers():
    """"triggers_only", his own stored authored triggers present — the
    engine's gate (_effective_mode_for_song/_trigger_allowed) means this
    song's analysed events never fire, and his triggers fire instead."""
    _mode("triggers_only")
    from spectra.models.trigger import (FireResponseAction, FireSceneAction,
                                        SpectraTrigger)
    from spectra.services import trigger_store
    from spectra.services.trigger_engine import TriggerEngine

    t_scene = SpectraTrigger(timestamp_ms=1000, source="authored",
                             action=FireSceneAction(scene_id="s1"))
    t_flare = SpectraTrigger(timestamp_ms=4000, source="authored",
                             action=FireResponseAction(event_class="flare", intensity=0.6))
    trigger_store.upsert(URI, t_scene)
    trigger_store.upsert(URI, t_flare)

    fired: list[tuple] = []

    async def fire_scene(scene_id, color_set_id, intensity):
        fired.append(("scene", None))

    async def fire_response(event_class, intensity, offset=None):
        fired.append(("flare", None))

    engine = TriggerEngine(fire_scene=fire_scene, fire_response=fire_response,
                           lead_ms=lambda t: 0, render_intensity=lambda x: x)

    async def sweep():
        await engine.on_track_state(URI)
        for ms in range(0, 5001, 50):
            await engine.tick(ms)
    asyncio.run(sweep())

    assert [k for k, _ in fired] == ["scene", "flare"], \
        "the real engine fired exactly one scene change then one flare"

    body = _client().get("/api/upcoming", params={"uri": URI}).json()
    assert body["has_authored"] is True
    kinds = [(e["ms"], e["kind"]) for e in body["events"]]
    assert kinds == [(1000, "scene"), (4000, "flare")], \
        "upcoming must list exactly the moments tick() actually fired"


def test_upcoming_labels_a_phase_trigger_by_its_event_class():
    """A fire_response trigger whose event_class is charge/lull/drop must
    come out of /api/upcoming as that phase kind — not the generic "flare"
    bucket _ACTION_KIND maps every other fire_response action to — so it
    draws with the gold/sky/magenta phase markers and the matching
    next-event icon. Only a genuine event_class=="flare" trigger stays
    "flare"."""
    _mode("full")
    from spectra.models.trigger import FireResponseAction, SpectraTrigger
    from spectra.services import trigger_store
    from spectra.services.trigger_engine import TriggerEngine

    t_charge = SpectraTrigger(timestamp_ms=2000, source="authored",
                              action=FireResponseAction(event_class="charge", intensity=0.5))
    t_flare = SpectraTrigger(timestamp_ms=6000, source="authored",
                             action=FireResponseAction(event_class="flare", intensity=0.5))
    trigger_store.upsert(URI, t_charge)
    trigger_store.upsert(URI, t_flare)

    fired: list[str] = []

    async def fire_scene(scene_id, color_set_id, intensity):
        pass

    async def fire_response(event_class, intensity, offset=None):
        fired.append(event_class)

    engine = TriggerEngine(fire_scene=fire_scene, fire_response=fire_response,
                           lead_ms=lambda t: 0, render_intensity=lambda x: x)

    async def sweep():
        await engine.on_track_state(URI)
        for ms in range(0, 7001, 50):
            await engine.tick(ms)
    asyncio.run(sweep())

    assert fired == ["charge", "flare"], \
        "the real engine fired exactly a charge then a flare"

    body = _client().get("/api/upcoming", params={"uri": URI}).json()
    kinds = [(e["ms"], e["kind"]) for e in body["events"]]
    assert kinds == [(2000, "charge"), (6000, "flare")], \
        "a charge-class fire_response trigger must be labeled 'charge', never the generic 'flare'"


def test_upcoming_excludes_a_stood_down_member_of_a_firing_sequence():
    """A CONFIRMED drop sequence (his own) whose LULL member happens to
    land within reach of a separately authored, lone "lull" phase trigger
    stands that member down (drop_firing.resolved_stood_down) — his own
    trigger fires there instead, under a mode his own triggers fire in.
    /api/upcoming must not ALSO emit the sequence's own lull: that would
    list the same real fire twice (its own "else" branch already lists
    his lone trigger)."""
    _mode("full")
    from spectra.models.trigger import FireResponseAction, SpectraTrigger
    from spectra.services import drop_sequences, trigger_store
    from spectra import config as scfg

    drop_synth.one_drop_song(scfg.AUDIO_SHAPES_DIR, URI)

    view = drop_sequences.view_with_detection(URI)
    (seq,) = view["sequences"]
    key, lull_ms, drop_ms = seq["key"], seq["lull_ms"], seq["drop_ms"]
    beat_ms = view["song"]["beat_ms"]
    reach_ms = drop_sequences.MATCH_BEATS * beat_ms
    assert lull_ms is not None
    # far enough from the sequence's own drop that the whole sequence
    # still matches_his=False (its drop is untouched), close enough to
    # the sequence's own lull that THAT member alone stands down.
    assert drop_ms - lull_ms > reach_ms

    drop_sequences.confirm(URI, key)

    mark_ms = int(lull_ms + min(50.0, reach_ms / 2))
    t_lull = SpectraTrigger(timestamp_ms=mark_ms, source="authored",
                           action=FireResponseAction(event_class="lull", intensity=0.5))
    trigger_store.upsert(URI, t_lull)

    body = _client().get("/api/upcoming", params={"uri": URI}).json()
    lulls = [e for e in body["events"] if e["kind"] == "lull"]
    assert lulls == [{"ms": mark_ms, "kind": "lull", "rank": None, "rank_of": None,
                      "source": "authored"}], (
        "exactly one lull event — his own trigger — never a duplicate from "
        f"the sequence member it stood down; got {lulls}")
    assert any(e["kind"] == "drop" and e["ms"] == drop_ms for e in body["events"]), \
        "the sequence's own drop (never stood down) still fires"


def test_upcoming_excludes_a_suggested_unconfirmed_drop():
    """A drop whose own score never clears the confident threshold stays
    SUGGESTED (drop_sequences.STATE_SUGGESTED) — drop_firing.annotate
    marks it `fires=False, fires_reason="waits_for_confirm"`, and
    /api/upcoming must never list it."""
    _mode("analysed")
    from spectra.services import room_controls
    rc = room_controls.load_room_controls()
    # Push the confident bar out of reach so this drop lands SUGGESTED,
    # never CONFIRMED-by-default — the state drop_firing excludes.
    room_controls.save_room_controls(rc.model_copy(update={
        "scene_change_mode": "analysed",
        "drop_confident_score": 1.95, "drop_suggested_score": 0.3}))
    from spectra import config as scfg
    drop_synth.one_drop_song(scfg.AUDIO_SHAPES_DIR, URI)

    from spectra.services import drop_sequences
    # view_with_detection (the on-first-play read-through, same as
    # GET /api/drop-sequences uses): /api/upcoming's own drop_sequences
    # source reads the STORE, never detecting itself.
    view = drop_sequences.view_with_detection(URI)
    (seq,) = view["sequences"]
    assert seq["state"] == drop_sequences.STATE_SUGGESTED, \
        "fixture must land SUGGESTED for this test to prove the exclusion"

    body = _client().get("/api/upcoming", params={"uri": URI}).json()
    assert not any(e["kind"] in ("charge", "lull", "drop") for e in body["events"]), \
        "a SUGGESTED, unconfirmed drop must never be shown as upcoming"
