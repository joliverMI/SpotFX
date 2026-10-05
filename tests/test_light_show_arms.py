"""THE LIGHT SHOW, PHASE 2 — arms (spectra/services/show_arms.py) and the
High/Low Triggers (spectra/services/show_cues.py), driven through the real
executor, the real trigger engine's tick() and the real stores in a scratch
directory. No live access: the live host, the bridge and SpotFX's colour
API are faked at their seams (the `room` fixture from test_light_show).
"""
from __future__ import annotations

import asyncio
import time

import pytest

from spectra.models.light_show import ActionSet, ShowAction
from spectra.models.trigger import (FireResponseAction, FireSceneAction,
                                    SpectraTrigger)
from spectra.services import (midsong_generator, show_arms, show_cues,
                              show_store)
from spectra.services.trigger_engine import TriggerEngine
from tests.test_light_show import A, Registry, room  # noqa: F401  (fixture)

URI = "spotify:track:arms"


def _secs(*energies, step=30_000):
    return [{"start_ms": i * step, "end_ms": (i + 1) * step, "energy_rms": e}
            for i, e in enumerate(energies)]


def _cues(sections, **kw):
    kw.setdefault("placed", {})
    kw.setdefault("offset_ms", 0)
    kw.setdefault("drop_marks", [])
    kw.setdefault("overrides", {})
    return show_cues.cues_for_song(URI, sections=sections, **kw)


# ── 1. THE CUES ────────────────────────────────────────────────────────────

def test_the_shared_score_is_the_planners_magnitude():
    secs = _secs(0.2, 0.9, 0.4, 0.5)
    assert midsong_generator.section_energy_change(secs) == pytest.approx(
        [abs(v) for v in midsong_generator.section_energy_shift(secs)])
    assert midsong_generator.section_energy_shift(secs)[1] == pytest.approx(0.7)
    assert midsong_generator.section_energy_shift(secs)[2] == pytest.approx(-0.5)


def test_high_is_the_biggest_rise_low_the_biggest_fall():
    c = _cues(_secs(0.3, 0.5, 0.95, 0.4, 0.45, 0.2))
    assert c.high.timestamp_ms == 60_000 and c.high.source == "auto"
    assert c.high.shift == pytest.approx(0.45)
    assert c.low.timestamp_ms == 90_000
    assert c.low.shift == pytest.approx(-0.55)


def test_the_first_and_last_15_seconds_are_never_a_cue():
    # the biggest rise sits at 10 s (inside the intro), the biggest fall at
    # the song's last 10 s — both excluded
    secs = [{"start_ms": 0, "end_ms": 10_000, "energy_rms": 0.0},
            {"start_ms": 10_000, "end_ms": 40_000, "energy_rms": 1.0},
            {"start_ms": 40_000, "end_ms": 70_000, "energy_rms": 0.6},
            {"start_ms": 70_000, "end_ms": 100_000, "energy_rms": 0.8},
            {"start_ms": 100_000, "end_ms": 110_000, "energy_rms": 0.0}]
    c = _cues(secs)
    assert c.high.timestamp_ms == 70_000
    assert c.low.timestamp_ms == 40_000


def test_the_placed_time_and_the_frame_shift_are_used():
    secs = _secs(0.2, 0.9, 0.1, 0.1)
    c = _cues(secs, placed={"section:30000": 31_234}, offset_ms=500)
    assert c.high.timestamp_ms == 31_234          # the planner's placement
    assert c.low.timestamp_ms == 60_500           # raw + capture offset


def test_a_runner_up_within_ten_percent_is_close():
    c = _cues(_secs(0.1, 0.6, 0.15, 0.6, 0.1, 0.55, 0.55))
    assert c.high.runner_up_close is True
    assert c.high.alternates[0].close is True
    far = _cues(_secs(0.1, 0.9, 0.85, 0.95, 0.9))
    assert far.high.runner_up_close is False


def test_his_drop_mark_seeds_the_high():
    secs = _secs(0.1, 0.5, 0.45, 0.95, 0.5, 0.4)
    auto = _cues(secs)
    assert auto.high.timestamp_ms == 90_000
    seeded = _cues(secs, drop_marks=[31_000, 5_000])   # 5 s: inside the intro
    assert seeded.high.timestamp_ms == 31_000
    assert seeded.high.source == "drop_mark"
    assert seeded.high.auto_ms == 90_000               # the automatic still shown


def test_of_several_drops_the_one_nearest_the_biggest_rise_wins():
    secs = _secs(0.1, 0.5, 0.45, 0.95, 0.5, 0.4)
    c = _cues(secs, drop_marks=[31_000, 91_500])
    assert c.high.timestamp_ms == 91_500


def test_his_move_always_wins_and_one_tap_reverts():
    secs = _secs(0.1, 0.5, 0.45, 0.95, 0.5, 0.4)
    show_cues.set_override(URI, "high", 77_700)
    c = _cues(secs, drop_marks=[31_000], overrides=None)
    assert c.high.timestamp_ms == 77_700 and c.high.source == "moved"
    assert c.high.auto_ms == 90_000
    assert show_cues.clear_override(URI, "high") is True
    c = _cues(secs, drop_marks=[31_000], overrides=None)
    assert c.high.source == "drop_mark"
    assert show_cues.clear_override(URI, "high") is False


def test_moving_a_cue_never_writes_the_trigger_store(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import trigger_store
    path = tmp_path / "triggers.json"
    path.write_text('{"x": []}')
    monkeypatch.setattr(scfg, "TRIGGERS_FILE", path, raising=False)
    before = path.read_bytes()
    show_cues.set_override(URI, "low", 50_000)
    assert path.read_bytes() == before
    assert trigger_store is not None


def test_the_cache_never_blocks_and_fills_in_a_thread(monkeypatch):
    calls = []
    monkeypatch.setattr(show_cues, "cues_for_song",
                        lambda uri: calls.append(uri) or show_cues.SongCues(uri=uri))

    async def go():
        assert show_cues.cached(URI) is None
        for _ in range(50):
            await asyncio.sleep(0.01)
            if show_cues.cached(URI) is not None:
                break
        return show_cues.cached(URI)
    assert asyncio.run(go()).uri == URI
    assert calls == [URI]


# ── 2. ARMING ──────────────────────────────────────────────────────────────

def _set(name="Blackout", actions=None):
    return show_store.put_set(ActionSet(name=name, actions=actions or [
        A("device_state", target={"kind": "category", "id": "Strips"},
          state="dark", fade_ms=0)]))


def _play_uri(uri):
    show_arms.current_uri = lambda: uri


def test_arming_the_same_set_on_the_same_trigger_replaces(room):
    s = _set()
    a1 = show_arms.arm(set_id=s.id, on="high")
    a2 = show_arms.arm(set_id=s.id, on="high", repeat=True)
    other = show_arms.arm(set_id=s.id, on="low")
    live = show_arms.active_arms()
    assert [a.id for a in live] == [a2.id, other.id]
    old = next(a for a in show_store.state().arms if a.id == a1.id)
    assert old.status == "disarmed" and "replaced" in old.end_reason


def test_arms_are_validated_and_by_name(room):
    s = _set("Reveal Crystal")
    assert show_arms.arm(set_id="reveal crystal", on="low").set_id == s.id
    with pytest.raises(show_arms.ArmError):
        show_arms.arm(set_id="nope", on="low")
    with pytest.raises(show_arms.ArmError):
        show_arms.arm(set_id=s.id, on="sometime")
    with pytest.raises(show_arms.ArmError):
        show_arms.arm(action=ShowAction(kind="level", params={"level": 999,
                      "target": {"kind": "everything"}}), on="low")


def test_next_scene_change_is_a_real_change_to_a_different_scene(room):
    s = _set()
    show_arms.arm(set_id=s.id, on="scene_change")

    async def go():
        assert show_arms.on_scene_change("a", "a") == []     # a re-fire
        assert show_arms.on_scene_change("a", None) == []
        ids = show_arms.on_scene_change("a", "b")
        await asyncio.sleep(0.05)
        return ids
    ids = asyncio.run(go())
    assert len(ids) == 1
    arm = next(a for a in show_store.state().arms if a.id == ids[0])
    assert arm.status == "fired" and arm.fire_count == 1
    assert "tv" in show_store.state().holds


def test_a_scene_change_the_show_caused_never_counts(room, monkeypatch):
    from spectra.services import show_actions
    s = _set()
    show_arms.arm(set_id=s.id, on="scene_change")
    monkeypatch.setattr(show_actions, "_executing", 1)
    assert show_arms.on_scene_change("a", "b") == []
    assert len(show_arms.active_arms()) == 1


def test_repeat_stays_armed_and_counts(room):
    s = _set()
    a = show_arms.arm(set_id=s.id, on="scene_change", repeat=True)

    async def go():
        show_arms.on_scene_change("a", "b")
        await asyncio.sleep(0.05)
        show_arms.on_scene_change("b", "c")
        await asyncio.sleep(0.05)
    asyncio.run(go())
    live = show_arms.active_arms()
    assert [x.id for x in live] == [a.id] and live[0].fire_count == 2


def test_the_gate_never_consumes_an_arm(room):
    s = _set()
    show_arms.arm(set_id=s.id, on="scene_change")
    room.gate["reason"] = "a preview is holding the room"

    async def go():
        ids = show_arms.on_scene_change("a", "b")
        await asyncio.sleep(0.02)
        return ids
    assert asyncio.run(go()) == []
    arm = show_arms.active_arms()[0]
    assert arm.last_outcome["status"] == "waiting"
    assert "preview" in arm.last_outcome["reason"]
    assert show_store.state().holds == {}


def test_this_song_only_is_missed_when_the_song_changes(room):
    s = _set()
    _play_uri("song-a")
    a = show_arms.arm(set_id=s.id, on="high", this_song_only=True)
    carry = show_arms.arm(set_id=_set("Carry").id, on="high")
    assert a.song_uri == "song-a" and carry.song_uri is None
    _play_uri("song-b")
    show_arms.tick()
    ended = next(x for x in show_store.state().arms if x.id == a.id)
    assert ended.status == "missed"
    assert [x.id for x in show_arms.active_arms()] == [carry.id]


def test_this_song_only_needs_a_song(room):
    _play_uri(None)
    with pytest.raises(show_arms.ArmError):
        show_arms.arm(set_id=_set().id, on="low", this_song_only=True)


def test_expiry_on_release_after_12h_and_after_30_min_without_music(room, monkeypatch):
    from spectra.services import show_output
    s1, s2, s3 = _set("One"), _set("Two"), _set("Three")
    show_arms.arm(set_id=s1.id, on="high")
    show_output.on_release()
    assert show_arms.active_arms() == []
    assert show_store.state().arms[0].end_reason == "the room was released"

    a = show_arms.arm(set_id=s2.id, on="high")
    a.expires_ms = 1
    show_arms.tick()
    assert "12 hours" in next(x for x in show_store.state().arms if x.id == a.id).end_reason

    b = show_arms.arm(set_id=s3.id, on="low")
    show_arms.is_playing = lambda: False
    monkeypatch.setattr(show_arms, "_last_music_mono",
                        time.monotonic() - show_arms.ARM_IDLE_EXPIRY_S - 1)
    show_arms.tick()
    assert "without music" in next(x for x in show_store.state().arms if x.id == b.id).end_reason


def test_music_playing_keeps_an_arm_alive(room, monkeypatch):
    show_arms.arm(set_id=_set().id, on="high")
    show_arms.is_playing = lambda: True
    monkeypatch.setattr(show_arms, "_last_music_mono", 0.0)
    show_arms.tick()
    assert len(show_arms.active_arms()) == 1


def test_arms_survive_a_restart(room):
    a = show_arms.arm(set_id=_set().id, on="low", repeat=True)
    show_store.reset_memory()                      # a fresh process reads the file
    live = show_arms.active_arms()
    assert [x.id for x in live] == [a.id] and live[0].repeat is True


def test_finish_on_the_mark_lead(room):
    s = _set("Fade", [A("level", target={"kind": "everything"}, level=20,
                        fade_in_ms=3000, until="released"),
                      A("device_state", target={"kind": "everything"},
                        state="dark", fade_ms=1500),
                      A("pause", seconds=1),
                      A("device_state", target={"kind": "everything"},
                        state="dark", fade_ms=9000)])
    hi = show_arms.arm(set_id=s.id, on="high")
    sc = show_arms.arm(set_id=s.id, on="scene_change")
    off = show_arms.arm(set_id=_set("Fade2", s.actions).id, on="low",
                        finish_on_mark=False)
    assert show_arms.lead_ms(hi) == 3000           # steps after a pause do not count
    assert show_arms.lead_ms(sc) == 0              # a scene change has no known time
    assert show_arms.lead_ms(off) == 0


# ── 3. THE TRIGGER CLOCK ───────────────────────────────────────────────────

def _engine(stored=()):
    fired_scenes: list = []
    cue_calls: list = []

    async def fire_scene(*a, **k):
        fired_scenes.append(("scene", time.monotonic()))

    async def noop(*a, **k):
        return None

    te = TriggerEngine(
        list_triggers=lambda uri: list(stored),
        fire_scene=fire_scene, fire_response=noop,
        fire_scene_update=noop, select_color_set=noop,
        select_scene=lambda i: "s1",
        scene_change_mode=lambda: "full",
        render_intensity=lambda x: x,
        sequencer_enabled=lambda: False,
        lead_ms=lambda t: 0, response_offset_ms=lambda a: 0,
        analysed_plan=lambda uri, st: None,
    )
    plan = {"cues": [("high", 60_000, 0), ("low", 120_000, 2_000)]}
    te._show_cue_plan = lambda uri: list(plan["cues"])

    async def on_cue(level, cue_ms, ahead_ms):
        cue_calls.append((level, cue_ms, ahead_ms))
        fired_scenes.append((f"cue:{level}", time.monotonic()))
    te._show_cue = on_cue
    return te, cue_calls, fired_scenes, plan


async def _play(te, positions):
    await te.on_track_state(URI)
    for p in positions:
        await te.tick(p)


def test_a_cue_crosses_exactly_once_and_rearms_on_a_rewind():
    te, calls, _f, _p = _engine()
    asyncio.run(_play(te, [0, 59_900, 60_100, 60_300, 70_000]))
    assert [c[0] for c in calls] == ["high"]
    asyncio.run(_play(te, [10_000, 59_900, 60_100]))   # rewound
    assert [c[0] for c in calls] == ["high", "high"]


def test_a_finish_on_the_mark_lead_fires_the_cue_early():
    te, calls, _f, _p = _engine()
    asyncio.run(_play(te, [0, 59_900, 60_100, 117_900, 118_100, 120_100]))
    assert calls[1] == ("low", 120_000, 1_900)


def test_a_seek_over_a_cue_skips_it_rather_than_firing_late():
    te, calls, _f, _p = _engine()
    asyncio.run(_play(te, [0, 70_000, 70_200]))
    assert calls == []


def test_cues_run_before_the_stored_trigger_on_the_same_moment():
    stored = [SpectraTrigger(timestamp_ms=60_000, source="authored",
                             action=FireSceneAction(scene_id="s1"))]
    te, _c, fired, _p = _engine(stored)
    asyncio.run(_play(te, [0, 59_900, 60_100]))
    assert [x[0] for x in fired] == ["cue:high", "scene"]


def test_the_default_hooks_are_inert():
    async def noop(*a, **k):
        return None
    te = TriggerEngine(
        list_triggers=lambda uri: [SpectraTrigger(
            timestamp_ms=1_000, source="authored",
            action=FireResponseAction(event_class="flare", intensity=0.5))],
        fire_scene=noop, fire_response=noop, fire_scene_update=noop,
        select_color_set=noop, select_scene=lambda i: None,
        scene_change_mode=lambda: "full", render_intensity=lambda x: x,
        sequencer_enabled=lambda: False, lead_ms=lambda t: 0,
        response_offset_ms=lambda a: 0, analysed_plan=lambda uri, st: None)
    fired = asyncio.run(_play_ret(te, [0, 2_000]))
    assert len(fired) == 1


async def _play_ret(te, positions):
    await te.on_track_state(URI)
    out = []
    for p in positions:
        out += await te.tick(p)
    return out


# ── 4. AN ARM ON HIGH, END TO END ──────────────────────────────────────────

def test_an_arm_on_high_fires_when_the_clock_crosses_it(room):
    s = _set()
    _play_uri(URI)
    show_cues._cache[URI] = show_cues.SongCues(
        uri=URI, high=show_cues.Cue(level="high", timestamp_ms=60_000, source="auto"))
    arm = show_arms.arm(set_id=s.id, on="high")
    te, _c, _f, _p = _engine()
    te._show_cue_plan = show_arms.cue_plan
    te._show_cue = show_arms.on_cue

    async def go():
        await te.on_track_state(URI)
        te._show_cue_plan(URI)                      # first look: re-derive
        show_cues._cache[URI] = show_cues.SongCues(
            uri=URI, high=show_cues.Cue(level="high", timestamp_ms=60_000, source="auto"))
        for p in (0, 59_900, 60_100):
            await te.tick(p)
        await asyncio.sleep(0.05)
    asyncio.run(go())
    done = next(a for a in show_store.state().arms if a.id == arm.id)
    assert done.status == "fired"
    assert done.last_outcome["trigger"] == "high"
    assert "tv" in show_store.state().holds


def test_a_room_effect_is_armed_and_triggered_like_any_action(room, monkeypatch):
    """His order: the Light Show must ARM and TRIGGER room effects. A future
    room effect kind ('stub_pulse' — not a kind room_effects knows today)
    armed on High starts through room_effects' one entry point when the
    trigger clock crosses the cue — no Light Show change for a new kind."""
    from spectra.services import show_actions
    from tests.test_light_show import StubRunner, _stub_spec
    stub = StubRunner([_stub_spec()])
    monkeypatch.setattr(show_actions, "room_effect_runner", stub)
    s = _set("Pulse on the drop", [A("room_effect", effect="Pulse",
                                     params={"depth": 0.8}, duration_s=0.2)])
    _play_uri(URI)
    arm = show_arms.arm(set_id=s.id, on="high")
    te, _c, _f, _p = _engine()
    te._show_cue_plan = show_arms.cue_plan
    te._show_cue = show_arms.on_cue

    async def go():
        await te.on_track_state(URI)
        te._show_cue_plan(URI)                      # first look: re-derive
        show_cues._cache[URI] = show_cues.SongCues(
            uri=URI, high=show_cues.Cue(level="high", timestamp_ms=60_000, source="auto"))
        for p in (0, 59_900, 60_100):
            await te.tick(p)
        await asyncio.sleep(0.5)
    asyncio.run(go())
    assert stub.started and stub.started[0].kind == "stub_pulse"
    assert stub.started[0].depth == 0.8
    assert stub.stopped == 1
    done = next(a for a in show_store.state().arms if a.id == arm.id)
    assert done.status == "fired"


def test_the_show_log_records_light_show_events(tmp_path, monkeypatch):
    """Phase 1 wrote to a `show` bucket that did not exist: every record
    raised KeyError (seen live 2026-10-04), so the Review page could never
    answer "why did the crystal go dark"."""
    from spectra.services import fire_history
    fire_history.record_fire("show", "arm_fired", {"set": "Blackout"})
    counts = fire_history._load_counts()
    assert counts["show"]["arm_fired"]


# ── 5. THE WIRE ────────────────────────────────────────────────────────────

def test_the_arm_and_cue_routes(room):
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    c = TestClient(create_app())
    s = _set("Wire")
    r = c.post("/api/light-show/arms", json={"set_id": s.id, "on": "low"})
    assert r.status_code == 200 and r.json()["on"] == "low"
    assert c.post("/api/light-show/arms", json={"set_id": "nope"}).status_code == 400
    body = c.get("/api/light-show/arms").json()
    assert [a["label"] for a in body["armed"]] == ["Wire"]
    assert c.delete(f"/api/light-show/arms/{r.json()['id']}").status_code == 200
    assert c.delete("/api/light-show/arms/nope").status_code == 404
    show_arms.arm(set_id=s.id, on="high")
    assert len(c.post("/api/light-show/arms/disarm-all").json()["disarmed"]) == 1

    assert c.put("/api/light-show/cues", json={"uri": URI, "level": "high",
                                               "timestamp_ms": 61_000}).status_code == 200
    assert show_cues.overrides_for(URI)["high"]["timestamp_ms"] == 61_000
    assert c.put("/api/light-show/cues", json={"uri": URI, "level": "middle",
                                               "timestamp_ms": 1}).status_code == 400
    assert c.delete("/api/light-show/cues", params={"uri": URI, "level": "high"}).json()["reverted"] is True
    assert c.get("/api/light-show/status").json()["brief"]["armed"] == 0


def test_an_arm_made_while_released_waits_instead_of_expiring(room, monkeypatch):
    from fx import light_ownership as lo
    monkeypatch.setattr(lo, "load", lambda: lo.OwnershipRecord(owner=lo.RELEASED))
    room.gate["reason"] = "the room is released"
    show_arms.arm(set_id=_set().id, on="high")
    show_arms.is_playing = lambda: True
    show_arms.tick()
    assert len(show_arms.active_arms()) == 1
