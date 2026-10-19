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

def _engine(stored=(), scene_change_mode="full"):
    fired_scenes: list = []
    cue_calls: list = []

    async def fire_scene(*a, **k):
        fired_scenes.append(("scene", time.monotonic()))

    async def fire_response(event_class, *a, **k):
        fired_scenes.append((f"response:{event_class}", time.monotonic()))

    async def noop(*a, **k):
        return None

    te = TriggerEngine(
        list_triggers=lambda uri: list(stored),
        fire_scene=fire_scene, fire_response=fire_response,
        fire_scene_update=noop, select_color_set=noop,
        select_scene=lambda i: "s1",
        scene_change_mode=lambda: scene_change_mode,
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


def test_status_carries_the_dwell_floor_as_an_honest_estimate(room):
    from spectra.services import dwell
    from spectra.models.scene import SceneV2
    dwell.reset()
    try:
        assert show_arms.status()["song"]["expected_scene_change_s"] is None
        scene = SceneV2(name="Dwell Test")
        dwell.note_fired(scene, intensity=0.5)
        body = show_arms.status()
        assert body["song"]["expected_scene_change_s"] is not None
        assert body["song"]["expected_scene_change_is_floor"] is True
    finally:
        dwell.reset()


# ── 5. THE PHASE TRIGGERS — "next drop / lull / charge" ────────────────────
# His ask, 2026-10-19: "add a button for next drop, lull, and charge".
# drop_firing.phase_moments is the pure rule (which moments a song has);
# show_arms carries them on the SAME cue_plan/on_cue path the High and Low
# already use, so these tests drive the real trigger clock end to end.

def _phase_view(**kw):
    """A drop-sequence view in the shape drop_sequences.view returns."""
    view = {"uri": URI, "song": {"beat_ms": 500.0}, "authored": [],
            "authored_lone": [], "sequences": []}
    view.update(kw)
    return view


def _seq(key, drop_ms, *, charge_ms=None, lull_ms=None, state="confident",
         tier="confident"):
    return {"key": key, "origin": "detected", "state": state, "tier": tier,
            "charge_ms": charge_ms, "lull_ms": lull_ms, "drop_ms": drop_ms,
            "step": 0.9, "moved": {}}


def _moments(view):
    from spectra.services import drop_firing
    return [(m.cls, m.ms, m.source) for m in drop_firing.phase_moments(view)]


class _PM:
    """A drop_firing.PhaseMoment stand-in (only .cls/.ms are read here)."""
    def __init__(self, cls, ms):
        self.cls, self.ms = cls, ms
        self.source, self.key = "sequence", "k"


def test_phase_moments_are_every_charge_lull_and_drop_the_timeline_draws():
    view = _phase_view(sequences=[
        _seq("s1", 30_000, charge_ms=20_000, lull_ms=28_000),
        _seq("s2", 60_000, charge_ms=50_000, state="suggested", tier="suggested"),
        _seq("s3", 90_000, state="added", tier=None),
    ])
    assert _moments(view) == [
        ("charge", 20_000, "sequence"), ("lull", 28_000, "sequence"),
        ("drop", 30_000, "sequence"), ("drop", 90_000, "sequence")]
    # a SUGGESTED detection waits for his confirm, so it is not a moment —
    # and neither is a dismissed one
    dismissed = _phase_view(sequences=[_seq("s4", 40_000, state="dismissed")])
    assert _moments(dismissed) == []


def test_his_own_phase_triggers_are_moments_and_win_a_collision():
    his = {"charge": {"id": "c1", "kind": "charge", "timestamp_ms": 118_000},
           "lull": None,
           "drop": {"id": "d1", "kind": "drop", "timestamp_ms": 120_000}}
    view = _phase_view(authored=[his],
                       authored_lone=[{"id": "l1", "kind": "lull",
                                       "timestamp_ms": 150_000}],
                       # a detection sitting ON his drop (within two beats)
                       sequences=[_seq("s9", 120_400)])
    assert _moments(view) == [
        ("charge", 118_000, "yours"), ("drop", 120_000, "yours"),
        ("lull", 150_000, "yours")]


def test_phase_moments_are_not_narrowed_by_the_rooms_mode():
    """Like a High Trigger, a phase cue is a moment in the MUSIC: it exists
    whatever the scene-change tier is. Drive the real engine's
    _drop_state -> phase_cue_moments chain under two different
    scene_change_mode values, fed the SAME drop-sequence view, and assert
    identical output. "transitions" is the meaningful contrast: under it
    neither a sequence member nor one of his own authored charge/lull/drop
    triggers fires at all (drop_firing.fires_here / _trigger_allowed), so a
    mode leaking into the phase path would visibly shrink or empty the
    list rather than merely changing something unobserved."""
    def view(uri, triggers):
        return _phase_view(sequences=[
            _seq("s1", 30_000, charge_ms=20_000, lull_ms=28_000)])

    async def moments_under(mode):
        te, _c, _f, _p = _engine(scene_change_mode=mode)
        te._drop_view = view
        te._drop_revision = lambda: ("rev",)
        te._show_cue_plan = lambda uri: []
        await te.on_track_state(URI)
        for p in (0, 1_000, 2_000):
            await te.tick(p)
        got = te.phase_cue_moments(URI)
        assert got is not None
        return [(m.cls, m.ms) for m in got]

    full = asyncio.run(moments_under("full"))
    transitions = asyncio.run(moments_under("transitions"))
    expected = [("charge", 20_000), ("lull", 28_000), ("drop", 30_000)]
    assert full == expected
    assert transitions == expected


def test_a_phase_arm_fires_even_when_his_own_authored_trigger_would_not(room):
    """The stronger, end-to-end consequence of mode-independence: a
    one-shot arm on "drop" still FIRES when the clock crosses a drop
    moment under scene_change_mode "analysed" — the same mode under which
    an authored (source="authored") FireResponseAction trigger of his own
    never reaches the room at all (_trigger_allowed: an authored trigger
    only fires under "full"/"triggers_only"). The moments come from the
    REAL _drop_view -> drop_firing.phase_moments chain, not a stubbed
    list, so the mode genuinely has a path to interfere if it leaked in."""
    his = {"charge": None, "lull": None,
           "drop": {"id": "d1", "kind": "drop", "timestamp_ms": 30_000}}

    def view(uri, triggers):
        return _phase_view(authored=[his])

    stored = [SpectraTrigger(id="d1", timestamp_ms=30_000, source="authored",
                             action=FireResponseAction(event_class="drop",
                                                       intensity=0.8))]
    s = _set()
    _play_uri(URI)
    arm = show_arms.arm(set_id=s.id, on="drop")
    te, _c, fired, _p = _engine(stored, scene_change_mode="analysed")
    te._drop_view = view
    te._drop_revision = lambda: ("rev",)
    te._show_cue_plan = show_arms.cue_plan
    te._show_cue = show_arms.on_cue

    orig_phase_moments = show_arms.phase_moments
    show_arms.phase_moments = te.phase_cue_moments
    try:
        async def go():
            await te.on_track_state(URI)
            for p in (0, 29_900, 30_100):
                await te.tick(p)
            await asyncio.sleep(0.05)
        asyncio.run(go())
    finally:
        show_arms.phase_moments = orig_phase_moments

    done = next(a for a in show_store.state().arms if a.id == arm.id)
    assert done.status == "fired"
    assert done.last_outcome["trigger"] == "drop"
    assert fired == [], "his own authored trigger never fires under analysed"


def test_the_engine_publishes_its_phase_moments_off_one_memo(room):
    """TriggerEngine.phase_cue_moments: None for a song it has not worked
    out, the list once it has — and the view is read through the same memo
    the windows ride (one read per revision, never one per tick)."""
    reads = []

    def view(uri, triggers):
        reads.append(uri)
        return _phase_view(sequences=[_seq("s1", 30_000, charge_ms=20_000)])
    te, _c, _f, _p = _engine()
    te._drop_view = view
    te._drop_revision = lambda: ("rev",)
    te._show_cue_plan = lambda uri: []
    assert te.phase_cue_moments(URI) is None            # nothing worked out yet
    assert te.phase_cue_moments(None) is None

    async def go():
        await te.on_track_state(URI)
        for p in (0, 1_000, 2_000):
            await te.tick(p)
    asyncio.run(go())
    got = te.phase_cue_moments(URI)
    assert [(m.cls, m.ms) for m in got] == [("charge", 20_000), ("drop", 30_000)]
    assert len(reads) == 1, "the view is read once per revision, not once per tick"
    assert te.phase_cue_moments("spotify:track:other") is None


def test_cue_plan_carries_the_phases_beside_the_high_and_low():
    show_arms.phase_moments = lambda uri: [
        _PM("charge", 20_000), _PM("drop", 30_000), _PM("drop", 90_000)]
    show_arms.cue_plan(URI)              # first look for this song: re-derives
    show_cues._cache[URI] = show_cues.SongCues(
        uri=URI, high=show_cues.Cue(level="high", timestamp_ms=60_000, source="auto"))
    plan = show_arms.cue_plan(URI)
    assert ("high", 60_000, 0) in plan
    assert [(c, ms) for c, ms, _l in plan if c in show_arms.PHASE_TRIGGERS] == [
        ("charge", 20_000), ("drop", 30_000), ("drop", 90_000)]
    # a song whose phases are not worked out yet simply contributes none
    show_arms.phase_moments = lambda uri: None
    assert [c for c, _m, _l in show_arms.cue_plan(URI)] == ["high"]


def test_an_arm_on_the_next_drop_fires_when_the_clock_crosses_it(room):
    s = _set()
    _play_uri(URI)
    show_arms.phase_moments = lambda uri: (
        [_PM("charge", 20_000), _PM("drop", 30_000), _PM("drop", 90_000)]
        if uri == URI else None)
    arm = show_arms.arm(set_id=s.id, on="drop")
    te, _c, _f, _p = _engine()
    te._show_cue_plan = show_arms.cue_plan
    te._show_cue = show_arms.on_cue

    async def go():
        await te.on_track_state(URI)
        for p in (0, 19_900, 20_100, 29_900, 30_100):
            await te.tick(p)
        await asyncio.sleep(0.05)
    asyncio.run(go())
    done = next(a for a in show_store.state().arms if a.id == arm.id)
    assert done.status == "fired"
    assert done.last_outcome["trigger"] == "drop"
    assert done.last_outcome["cue_ms"] == 30_000, "the FIRST drop, not a later one"
    assert "tv" in show_store.state().holds


def test_a_charge_arm_ignores_the_drop_and_an_arm_fires_once_per_crossing(room):
    """A song holds several of each: a one-shot arm takes the first of ITS
    OWN class and is done; a repeat arm fires on every one."""
    once = show_arms.arm(set_id=_set("Once").id, on="charge")
    every = show_arms.arm(set_id=_set("Every").id, on="drop", repeat=True)
    _play_uri(URI)
    show_arms.phase_moments = lambda uri: [
        _PM("drop", 30_000), _PM("charge", 50_000), _PM("drop", 90_000)]
    te, _c, _f, _p = _engine()
    te._show_cue_plan = show_arms.cue_plan
    te._show_cue = show_arms.on_cue

    async def go():
        await te.on_track_state(URI)
        for p in (0, 29_900, 30_100, 49_900, 50_100, 89_900, 90_100):
            await te.tick(p)
        await asyncio.sleep(0.05)
    asyncio.run(go())
    ended = next(a for a in show_store.state().arms if a.id == once.id)
    assert ended.status == "fired" and ended.last_outcome["cue_ms"] == 50_000
    live = next(a for a in show_arms.active_arms() if a.id == every.id)
    assert live.fire_count == 2, "the repeat arm fired on BOTH drops"


def test_disarming_a_phase_arm_cancels_it_and_it_never_fires(room):
    s = _set()
    _play_uri(URI)
    show_arms.phase_moments = lambda uri: [_PM("lull", 28_000)]
    arm = show_arms.arm(set_id=s.id, on="lull")
    assert show_arms.disarm(arm.id) is True
    assert show_arms.active_arms() == []
    te, _c, _f, _p = _engine()
    te._show_cue_plan = show_arms.cue_plan
    te._show_cue = show_arms.on_cue

    async def go():
        await te.on_track_state(URI)
        for p in (0, 27_900, 28_100):
            await te.tick(p)
        await asyncio.sleep(0.05)
    asyncio.run(go())
    ended = next(a for a in show_store.state().arms if a.id == arm.id)
    assert ended.status == "disarmed" and ended.fire_count == 0
    assert show_store.state().holds == {}


def test_a_song_with_no_drops_keeps_the_arm_and_says_so(room):
    s = _set()
    _play_uri(URI)
    show_arms.phase_moments = lambda uri: []          # worked out: it has none
    arm = show_arms.arm(set_id=s.id, on="drop")
    body = show_arms.status()
    assert body["song"]["phases"]["known"] is True
    assert body["song"]["phases"]["counts"]["drop"] == 0
    assert "no charge, lull or drop" in body["song"]["phases"]["reason"]
    row = next(a for a in body["armed"] if a["id"] == arm.id)
    assert row["due_ms"] is None                       # nothing to count down to
    te, _c, _f, _p = _engine()
    te._show_cue_plan = show_arms.cue_plan
    te._show_cue = show_arms.on_cue

    async def go():
        await te.on_track_state(URI)
        for p in (0, 30_000, 60_000, 90_000):
            await te.tick(p)
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert [a.id for a in show_arms.active_arms()] == [arm.id]   # still waiting
    assert show_store.state().holds == {}
    # and "not worked out yet" is a DIFFERENT answer from "it has none"
    show_arms.phase_moments = lambda uri: None
    unknown = show_arms.status()["song"]["phases"]
    assert unknown["known"] is False
    assert "not been worked out yet" in unknown["reason"]


def test_the_gate_never_consumes_a_phase_arm(room):
    s = _set()
    _play_uri(URI)
    show_arms.phase_moments = lambda uri: [_PM("drop", 30_000)]
    show_arms.arm(set_id=s.id, on="drop")
    room.gate["reason"] = "a preview is holding the room"
    te, _c, _f, _p = _engine()
    te._show_cue_plan = show_arms.cue_plan
    te._show_cue = show_arms.on_cue

    async def go():
        await te.on_track_state(URI)
        for p in (0, 29_900, 30_100):
            await te.tick(p)
        await asyncio.sleep(0.05)
    asyncio.run(go())
    waiting = show_arms.active_arms()
    assert len(waiting) == 1 and waiting[0].last_outcome["status"] == "waiting"
    assert show_store.state().holds == {}


def test_a_phase_arm_counts_down_to_the_next_one_ahead_of_the_playhead(room):
    s = _set()
    _play_uri(URI)
    show_arms.phase_moments = lambda uri: [_PM("drop", 30_000), _PM("drop", 90_000)]
    arm = show_arms.arm(set_id=s.id, on="drop")
    from spectra.services.trigger_engine import trigger_engine
    trigger_engine._uri, trigger_engine._last_position_ms = URI, 40_000
    try:
        body = show_arms.status()
        row = next(a for a in body["armed"] if a["id"] == arm.id)
        assert row["due_ms"] == 90_000, "the next drop AHEAD, not the one passed"
        assert body["song"]["phases"]["next"]["drop"] == 90_000
        assert body["song"]["phases"]["counts"]["drop"] == 2
    finally:
        trigger_engine._uri, trigger_engine._last_position_ms = None, None


def test_finish_on_the_mark_applies_to_a_phase_arm_too(room):
    """A phase sits at a known song-time moment exactly as a High does, so
    a set with a fade starts early by the same rule (show_arms.
    MARK_TRIGGERS) — only "scene_change", with no known time, never does."""
    s = _set("Fade", [A("device_state", target={"kind": "everything"},
                        state="dark", fade_ms=2500)])
    for on in show_arms.PHASE_TRIGGERS:
        assert show_arms.lead_ms(show_arms.arm(set_id=s.id, on=on)) == 2500
    assert show_arms.lead_ms(show_arms.arm(set_id=s.id, on="scene_change")) == 0
    off = show_arms.arm(set_id=_set("Fade2", s.actions).id, on="drop",
                        finish_on_mark=False)
    assert show_arms.lead_ms(off) == 0


def test_a_phase_arm_is_validated_and_reachable_by_sonic(room):
    from spectra.services import show_console
    s = _set("Quiet Hues")
    for on in show_arms.PHASE_TRIGGERS:
        assert show_arms.arm(set_id=s.id, on=on).on == on
    with pytest.raises(show_arms.ArmError):
        show_arms.arm(set_id=s.id, on="breakdown")
    assert set(show_arms.PHASE_TRIGGERS) <= set(show_console.TRIGGER_CHOICES)
    out = asyncio.run(show_console._op_arm_show_set("Quiet Hues", on="drop"))
    assert out["status"] == "applied"
    assert "next drop" in out["summary"]
