"""SHOW PLAYLISTS (spectra/services/show_playlists.py) — the store, and the
runner driven through the REAL show_arms (arming, cue / scene-change hooks,
its _fire, its tick) with only the set executor faked at its seam
(show_actions.fire_set) and the Light Show gate held open. The opening
scene-change proof drives the REAL bridge -> engine._on_track_uri -> a real
TriggerEngine's song-start transition. No live access."""
from __future__ import annotations

import asyncio

import pytest

from spectra.models.light_show import (ActionSet, PlaylistOnEnd, PlaylistOnStart,
                                       PlaylistStep, ShowAction, ShowPlaylist,
                                       SongEntry)
from spectra.services import (show_actions, show_arms, show_output,
                              show_playlists, show_store)

CTX = "spotify:playlist:forty"
OTHER = "spotify:playlist:liked"
ONE, TWO, THREE = "spotify:track:one", "spotify:track:two", "spotify:track:three"


@pytest.fixture
def world(monkeypatch):
    fired: list[str] = []

    async def fake_fire_set(set_id, *, source="button"):
        s = show_store.find_set(set_id)
        fired.append(s.name)
        return {"id": f"run-{len(fired)}", "state": "done"}
    monkeypatch.setattr(show_actions, "fire_set", fake_fire_set)
    gate = {"reason": None}
    monkeypatch.setattr(show_output, "refusal", lambda: gate["reason"])
    playing = {"uri": ONE, "context": CTX}
    monkeypatch.setattr(show_arms, "current_uri", lambda: playing["uri"])
    monkeypatch.setattr(show_arms, "is_playing", lambda: True)
    monkeypatch.setattr(show_playlists, "current_context", lambda: playing["context"])
    monkeypatch.setattr(show_playlists, "now_playing", lambda: ("", ""))
    ids = {}
    for name in ("Heavy Calm", "Easy Calm", "Show Mode", "Pause Show"):
        ids[name] = show_store.put_set(ActionSet(
            name=name, actions=[ShowAction(kind="pause", params={"seconds": 1})])).id
    return {"fired": fired, "gate": gate, "ids": ids, "playing": playing}


def step(world, name, on="high", **kw):
    return PlaylistStep(set_id=world["ids"][name], on=on, **kw)


def program(world, name="40! Lightshow", **kw):
    data = dict(name=name, contexts=[CTX], songs=[
        SongEntry(uri=ONE, title="One", steps=[step(world, "Heavy Calm", "low")]),
        SongEntry(uri=TWO, title="Two", steps=[step(world, "Show Mode", "high"),
                                               step(world, "Easy Calm", "scene_change")]),
    ])
    data.update(kw)
    return show_store.put_playlist(ShowPlaylist(**data))


async def settle(n=30):
    for _ in range(n):
        await asyncio.sleep(0)


def run_async(fn):
    return asyncio.run(fn())


def state(world, uri, ctx=CTX, pos=1000):
    world["playing"]["uri"] = uri
    world["playing"]["context"] = ctx
    show_playlists.on_state(uri, ctx, pos)


def arms_of_run():
    r = show_playlists.run()
    return [a for a in show_arms.active_arms() if a.source == f"playlist:{r.id}"]


# ── the store ──────────────────────────────────────────────────────────────

def test_store_names_and_one_context_one_program(world):
    a = program(world)
    with pytest.raises(show_store.PlaylistConflict, match="already exists"):
        show_store.put_playlist(ShowPlaylist(name="40! lightshow"))
    with pytest.raises(show_store.PlaylistConflict, match="only one program"):
        show_store.put_playlist(ShowPlaylist(name="Other", contexts=[CTX]))
    assert show_store.playlist_for_context(CTX).id == a.id
    dup = show_store.duplicate_playlist(a.id)
    assert dup.name == "40! Lightshow copy" and dup.contexts == []
    assert [p.name for p in show_store.list_playlists()] == ["40! Lightshow", "40! Lightshow copy"]
    assert dup.songs[0].id != a.songs[0].id
    assert dup.songs[0].steps[0].id != a.songs[0].steps[0].id
    assert dup.songs[0].steps[0].set_id == a.songs[0].steps[0].set_id
    assert show_store.delete_playlist(dup.id)
    assert not show_store.delete_playlist(dup.id)


def test_problems_are_named(world):
    pl = ShowPlaylist(name="x", songs=[SongEntry(uri=ONE, steps=[PlaylistStep(on="high")]),
                                       SongEntry(uri=ONE),
                                       SongEntry(steps=[PlaylistStep(set_id="gone")])])
    p = show_playlists.problems(pl)
    assert any("no set chosen" in x for x in p)
    assert any("listed twice" in x for x in p)
    assert any("no song chosen" in x for x in p)
    assert any("no longer exists" in x for x in p)


# ── activation and each song ───────────────────────────────────────────────

def test_auto_follow_activates_on_its_playlist_and_arms_the_song(world):
    program(world)

    async def go():
        state(world, ONE)
        r = show_playlists.run()
        assert r is not None and r.state == "following" and r.via == "context"
        assert r.entry_source == "listed"
        [a] = arms_of_run()
        assert a.on == "low" and a.song_uri == ONE and a.expires_ms is None
        # the High does nothing (this song's step is on the Low)
        await show_arms.on_cue("high", 50_000, 0)
        await settle()
        assert world["fired"] == []
        await show_arms.on_cue("low", 90_000, 0)
        await settle()
        assert world["fired"] == ["Heavy Calm"]
        assert show_playlists.run().song_steps[0].status == "fired"
    run_async(go)


def test_a_song_change_misses_unfired_steps_and_arms_the_next(world):
    program(world)

    async def go():
        state(world, ONE)
        state(world, TWO)
        r = show_playlists.run()
        assert r.song_uri == TWO and r.songs_count == 2
        hist = {a.label: a for a in show_store.state().arms if a.status != "armed"}
        assert hist["Heavy Calm"].status == "missed"
        assert {a.on for a in arms_of_run()} == {"high", "scene_change"}
        assert r.songs_seen[0]["missed"] == 1 and r.songs_seen[0]["open"] is False
        # an unlisted song with no default arms nothing
        state(world, THREE)
        assert show_playlists.run().entry_source == "none" and arms_of_run() == []
    run_async(go)


def test_unlisted_song_uses_the_default_entry(world):
    program(world, default_song=SongEntry(steps=[step(world, "Pause Show", "scene_change")]))
    state(world, THREE)
    r = show_playlists.run()
    assert r.entry_source == "default"
    [a] = arms_of_run()
    assert a.label == "Pause Show" and a.on == "scene_change"


def test_unlisted_nothing_ignores_the_default(world):
    program(world, unlisted_song="nothing",
            default_song=SongEntry(steps=[step(world, "Pause Show", "scene_change")]))
    state(world, THREE)
    assert show_playlists.run().entry_source == "none" and arms_of_run() == []


def test_a_disabled_step_or_entry_does_nothing(world):
    program(world, songs=[SongEntry(uri=ONE, steps=[step(world, "Heavy Calm", enabled=False)]),
                          SongEntry(uri=TWO, enabled=False, steps=[step(world, "Show Mode")])])
    state(world, ONE)
    assert arms_of_run() == []
    state(world, TWO)
    assert show_playlists.run().entry_source == "off" and arms_of_run() == []


def test_follow_switch_off_and_auto_follow_off_never_activate(world):
    pl = program(world)
    show_playlists.set_follow(False)
    state(world, ONE)
    assert show_playlists.run() is None
    show_playlists.set_follow(True)
    show_store.put_playlist(pl.model_copy(update={"auto_follow": False}))
    state(world, TWO)
    assert show_playlists.run() is None


def test_leaving_the_playlist_ends_the_run_and_runs_on_end(world):
    program(world, on_end=PlaylistOnEnd(steps=[step(world, "Pause Show", "song_start")]))

    async def go():
        state(world, ONE)
        state(world, TWO, ctx=OTHER)
        await settle()
        r = show_playlists.run()
        assert r.state == "ended" and r.end_reason == "the music left the playlist"
        assert world["fired"] == ["Pause Show"]
        assert all(not a.source.startswith("playlist:") for a in show_arms.active_arms())
    run_async(go)


def test_pausing_the_music_is_not_leaving(world):
    program(world)
    state(world, ONE)
    show_playlists.on_state(None, None, None)       # nothing reported
    assert show_playlists.run().state == "following"
    state(world, ONE)
    assert show_playlists.run().songs_count == 1    # not a new song


def test_follow_songs_anywhere_starts_on_a_listed_song_elsewhere(world):
    program(world, follow_songs_anywhere=True)
    state(world, TWO, ctx=OTHER)
    r = show_playlists.run()
    assert r is not None and r.via == "song" and r.entry_source == "listed"
    # an unlisted song from elsewhere: leaves
    state(world, THREE, ctx=OTHER)
    assert show_playlists.run().state == "ended"


def test_on_start_starts_its_sequence_and_arms_its_steps(world):
    from spectra.models.light_show import SequenceItem, ShowSequence
    from spectra.services import show_sequence
    seq = show_store.put_sequence(ShowSequence(name="Spine", items=[
        SequenceItem(kind="set", set_id=world["ids"]["Easy Calm"], arm="high")]))
    program(world, on_start=PlaylistOnStart(sequence_id=seq.id,
                                            steps=[step(world, "Pause Show", "scene_change")]))
    state(world, ONE)
    assert show_sequence.run() is not None and show_sequence.run().name == "Spine"
    on_start = [a for a in arms_of_run() if a.song_uri is None]
    assert [a.label for a in on_start] == ["Pause Show"]
    # an on-start arm carries across songs (it is not song-scoped)
    state(world, TWO)
    assert [a.label for a in arms_of_run() if a.song_uri is None] == ["Pause Show"]


def test_a_running_sequence_keeps_the_room_unless_told_to_replace(world):
    from spectra.models.light_show import SequenceItem, ShowSequence
    from spectra.services import show_sequence
    mine = show_store.put_sequence(ShowSequence(name="Mine", items=[
        SequenceItem(kind="set", set_id=world["ids"]["Easy Calm"], arm="high")]))
    spine = show_store.put_sequence(ShowSequence(name="Spine", items=[
        SequenceItem(kind="set", set_id=world["ids"]["Show Mode"], arm="low")]))
    show_sequence.start(mine.id)
    program(world, on_start=PlaylistOnStart(sequence_id=spine.id))
    state(world, ONE)
    assert show_sequence.run().name == "Mine"
    assert any(e["what"] == "sequence_refused" for e in show_playlists.run().log)


def test_program_arms_and_hand_arms_never_replace_each_other(world):
    program(world)
    state(world, ONE)
    hand = show_arms.arm(set_id=world["ids"]["Heavy Calm"], on="low")
    assert len([a for a in show_arms.active_arms() if a.on == "low"]) == 2
    show_arms.arm(set_id=world["ids"]["Heavy Calm"], on="low")    # a re-tap replaces the HAND arm
    lows = [a for a in show_arms.active_arms() if a.on == "low"]
    assert len(lows) == 2 and hand.id not in {a.id for a in lows}
    assert any(a.source.startswith("playlist:") for a in lows)


def test_program_arms_do_not_expire_but_the_tick_misses_them_off_song(world):
    program(world)
    state(world, ONE)
    [a] = arms_of_run()
    assert a.expires_ms is None
    world["playing"]["uri"] = TWO              # the song moved on, the runner not yet told
    show_arms.tick()
    assert show_store.state().arms[-1].status in ("missed",) or \
        next(x for x in show_store.state().arms if x.id == a.id).status == "missed"


def test_stop_disarms_and_blocks_auto_follow_until_the_context_changes(world):
    program(world)
    state(world, ONE)
    show_playlists.stop()
    assert show_playlists.run().state == "stopped" and arms_of_run() == []
    state(world, TWO)                          # same playlist still playing
    assert show_playlists.run().state == "stopped"
    state(world, THREE, ctx=OTHER)             # he left it
    state(world, ONE)                          # and came back
    assert show_playlists.run().state == "following"


def test_manual_start_follows_whatever_plays_and_refuses_a_second(world):
    pl = program(world, contexts=[])

    async def go():
        world["playing"].update(uri=ONE, context=OTHER)
        show_playlists.start(pl.name)
        r = show_playlists.run()
        assert r.via == "manual" and r.entry_source == "listed"
        with pytest.raises(show_playlists.PlaylistError, match="already following"):
            show_playlists.start(pl.id)
        state(world, TWO, ctx="spotify:album:x")   # any context: still following
        assert show_playlists.run().state == "following"
    run_async(go)


def test_skip_song_disarms_this_songs_entry_only(world):
    program(world, on_start=PlaylistOnStart(steps=[step(world, "Pause Show", "scene_change")]))
    state(world, TWO)
    show_playlists.skip_song()
    labels = sorted(a.label for a in arms_of_run())
    assert labels == ["Pause Show"]
    assert {o.status for o in show_playlists.run().song_steps} == {"skipped"}


def test_fire_step_fires_now_and_disarms_its_arm(world):
    program(world)

    async def go():
        state(world, ONE)
        sid = show_playlists.run().song_steps[0].step_id
        await show_playlists.fire_step(sid)
        assert world["fired"] == ["Heavy Calm"] and arms_of_run() == []
        assert show_playlists.run().song_steps[0].status == "fired"
    run_async(go)


def test_a_rewind_to_the_start_reapplies_the_entry(world):
    program(world)
    state(world, ONE, pos=120_000)
    state(world, ONE, pos=2_000)
    r = show_playlists.run()
    assert r.songs_count == 2
    assert len(arms_of_run()) == 1


def test_the_gate_holds_arms_waiting_and_refuses_song_start_fires(world):
    program(world, songs=[SongEntry(uri=ONE, steps=[step(world, "Heavy Calm", "song_start"),
                                                    step(world, "Show Mode", "high")])])
    world["gate"]["reason"] = "SPECTRA does not hold the room"

    async def go():
        state(world, ONE)
        show_playlists.after_track_state()
        await settle()
        r = show_playlists.run()
        ss = {o.on: o for o in r.song_steps}
        assert ss["song_start"].status == "refused"
        assert ss["high"].status == "armed" and "waiting" in ss["high"].detail
        assert world["fired"] == []
    run_async(go)


def test_a_room_release_pauses_and_resume_reapplies(world):
    program(world)

    async def go():
        state(world, ONE)
        show_output.on_release()
        r = show_playlists.run()
        assert r.state == "paused" and arms_of_run() == []
        state(world, TWO)                          # paused: nothing armed
        assert arms_of_run() == []
        show_playlists.resume()
        assert show_playlists.run().state == "following"
        assert {a.on for a in arms_of_run()} == {"high", "scene_change"}
    run_async(go)


def test_restart_resumes_without_counting_the_playing_song_again(world):
    program(world)
    state(world, ONE)
    show_store.reset_memory()                      # a new process reads the file
    show_playlists.reset()
    show_playlists.current_context = lambda: world["playing"]["context"]
    show_playlists.now_playing = lambda: ("", "")
    show_playlists.tick()
    r = show_playlists.run()
    assert r.state == "following" and any(e["what"] == "resumed" for e in r.log)
    state(world, ONE)
    assert show_playlists.run().songs_count == 1 and len(arms_of_run()) == 1


def test_idle_for_thirty_minutes_ends_the_run(world, monkeypatch):
    program(world)
    state(world, ONE)
    monkeypatch.setattr(show_arms, "is_playing", lambda: False)
    monkeypatch.setattr(show_playlists, "_last_music_mono",
                        show_playlists.time.monotonic() - show_playlists.IDLE_END_S - 1)
    show_playlists.tick()
    assert show_playlists.run().state == "ended"


def test_status_and_brief_name_the_song_and_up_next(world, monkeypatch):
    program(world)
    from spectra.services import engine
    monkeypatch.setattr(engine.bridge, "_next_track", {"uri": TWO, "title": "Two"})
    state(world, ONE)
    st = show_playlists.status()
    assert st["run"]["active"] and st["up_next"]["entry_source"] == "listed"
    assert "Show Mode" in st["up_next"]["summary"]
    b = show_actions.brief()
    assert b["active"] and b["playlist"]["name"] == "40! Lightshow"


# ── the opening scene change counts (his answer to the plan's Q2) ──────────

def _wire_engine(world, monkeypatch, events):
    """The REAL bridge -> engine._on_track_uri, with a REAL TriggerEngine
    whose song-start transition reports its scene change exactly the way
    engine.on_scene_fired does (show_arms.on_scene_change)."""
    from spectra.services import ambient_music_gate, drop_sequences, engine, pulse_feed
    from spectra.services import scene_sequencer as ss_mod
    from spectra.services.trigger_engine import TriggerEngine

    scene = {"id": "scene-A"}

    async def fire_scene(scene_id, color_set_id, intensity):
        events.append(("scene_change", scene_id))
        prev, scene["id"] = scene["id"], scene_id
        show_arms.on_scene_change(prev, scene_id)
        return {"fired": True}

    te = TriggerEngine(fire_scene=fire_scene, select_scene=lambda i: "scene-B",
                       scene_change_mode=lambda: "full",
                       sequencer_enabled=lambda: False,
                       transition_intensity=lambda: 0.5,
                       render_intensity=lambda i: i)
    monkeypatch.setattr(engine, "trigger_engine", te)
    # the global bridge is shared by every test: put its state back after
    for attr in ("_track", "_track_received_at", "_timing", "_next_track", "_context_name",
                 "_last_message_at", "paused", "dinner_party", "ambient", "last_scene_id",
                 "counts"):
        monkeypatch.setattr(engine.bridge, attr, getattr(engine.bridge, attr))
    monkeypatch.setattr(engine.bridge, "counts", dict(engine.bridge.counts))
    monkeypatch.setattr(engine, "_last_track_uri", None)
    te.maybe_auto_generate = lambda uri: None
    monkeypatch.setattr(ss_mod.scene_sequencer, "on_track_state", _anoop)
    monkeypatch.setattr(ambient_music_gate, "reconcile", _anoop)
    monkeypatch.setattr(drop_sequences, "on_song_played", lambda uri: None)
    monkeypatch.setattr(pulse_feed.feed, "prepare", _anoop)
    monkeypatch.setattr(show_arms, "current_uri", lambda: engine.bridge.track_uri())
    monkeypatch.setattr(show_playlists, "current_context", lambda: engine.bridge.context_uri())

    async def fake_fire_set(set_id, *, source="button"):
        s = show_store.find_set(set_id)
        events.append(("fired", s.name))
        world["fired"].append(s.name)
        return {"id": "r", "state": "done"}
    monkeypatch.setattr(show_actions, "fire_set", fake_fire_set)
    return engine


async def _anoop(*a, **k):
    return None


def _msg(uri, ctx=CTX, pos=0):
    return {"type": "state", "track": {"spotify_uri": uri, "progress_ms": pos,
                                       "is_playing": True, "context_uri": ctx,
                                       "context_type": "playlist", "title": uri},
            "context_name": "40! Lightshow", "next_track_uri": None}


def test_a_next_scene_change_step_fires_on_the_songs_opening_change(world, monkeypatch):
    events: list = []
    engine = _wire_engine(world, monkeypatch, events)
    program(world, songs=[SongEntry(uri=TWO, steps=[step(world, "Easy Calm", "scene_change"),
                                                    step(world, "Show Mode", "song_start")])])

    async def go():
        await engine.bridge.handle_message(_msg(ONE, ctx=OTHER))   # an earlier song
        await engine.bridge.handle_message(_msg(TWO))               # the playlist's song
        await settle(60)
        assert ("scene_change", "scene-B") in events
        # the scene-change step fired ON the opening transition ...
        assert "Easy Calm" in world["fired"]
        # ... and the song-start step fired only after that transition
        assert events.index(("fired", "Show Mode")) > events.index(("scene_change", "scene-B"))
        r = show_playlists.run()
        assert {o.on: o.status for o in r.song_steps} == {"scene_change": "fired",
                                                          "song_start": "fired"}
        assert engine.bridge.context_name() == "40! Lightshow"
    run_async(go)


def test_red_control_arms_made_after_the_transition_would_wait(world, monkeypatch):
    """The ordering is the whole point: an arm created AFTER the opening
    change (the plan's rejected recommendation) waits for the next one."""
    events: list = []
    engine = _wire_engine(world, monkeypatch, events)
    program(world, songs=[SongEntry(uri=TWO, steps=[step(world, "Easy Calm", "scene_change")])])
    real_on_state = show_playlists.on_state
    deferred: list = []
    monkeypatch.setattr(show_playlists, "on_state", lambda *a: deferred.append(a))

    async def go():
        await engine.bridge.handle_message(_msg(ONE, ctx=OTHER))
        await engine.bridge.handle_message(_msg(TWO))
        for a in deferred:                     # applied after the transition
            real_on_state(*a)
        await settle(60)
        assert ("scene_change", "scene-B") in events
        assert "Easy Calm" not in world["fired"]
        assert [o.status for o in show_playlists.run().song_steps] == ["armed"]
    run_async(go)


def test_stop_marks_the_songs_steps_disarmed_not_missed(world):
    program(world)
    state(world, TWO)
    show_playlists.stop()
    assert {o.status for o in show_playlists.run().song_steps} == {"disarmed"}


# ── the wire ───────────────────────────────────────────────────────────────

def test_the_api_round_trip(world, monkeypatch):
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    client = TestClient(create_app())
    body = {"name": "40! Lightshow", "contexts": [CTX],
            "context_names": {CTX: "40! Lightshow"},
            "songs": [{"uri": ONE, "title": "One",
                       "steps": [{"set_id": world["ids"]["Heavy Calm"], "on": "low"}]}]}
    r = client.post("/api/light-show/playlists", json=body)
    assert r.status_code == 200, r.text
    pl = r.json()
    assert pl["songs"][0]["steps"][0]["title"] == "Heavy Calm — Low Trigger"
    assert pl["songs"][0]["summary"] == "Heavy Calm — Low Trigger" and pl["problems"] == []
    assert client.post("/api/light-show/playlists",
                       json={"name": "Other", "contexts": [CTX]}).status_code == 409
    lst = client.get("/api/light-show/playlists").json()
    assert lst["follow_enabled"] is True and len(lst["playlists"]) == 1
    assert client.put("/api/light-show/playlists/follow",
                      json={"enabled": False}).json() == {"follow_enabled": False}
    # start by NAME (the Home Assistant / Sonic shape), then the run
    st = client.post("/api/light-show/playlist-run/start", json={"name": "40! lightshow"})
    assert st.status_code == 200, st.text
    assert st.json()["run"]["name"] == "40! Lightshow" and st.json()["run"]["via"] == "manual"
    assert client.delete(f"/api/light-show/playlists/{pl['id']}").status_code == 409
    assert client.post("/api/light-show/playlist-run/start",
                       json={"name": "40! Lightshow"}).status_code == 409
    sid = st.json()["run"]["song_steps"][0]["step_id"]
    fs = client.post("/api/light-show/playlist-run/fire-step", json={"step_id": sid})
    assert fs.status_code == 200 and world["fired"] == ["Heavy Calm"]
    assert client.post("/api/light-show/playlist-run/skip-song").status_code == 200
    stop = client.post("/api/light-show/playlist-run/stop").json()
    assert stop["run"]["state"] == "stopped"
    assert client.post("/api/light-show/playlist-run/stop").status_code == 409
    dup = client.post(f"/api/light-show/playlists/{pl['id']}/duplicate").json()
    assert dup["name"] == "40! Lightshow copy" and dup["contexts"] == []
    assert client.delete(f"/api/light-show/playlists/{dup['id']}").status_code == 200
    assert client.post("/api/light-show/playlist-run/start", json={}).status_code == 400


def test_the_bridge_reads_context_and_up_next():
    from spectra.services.bridge import SpotEffectsBridge
    b = SpotEffectsBridge(ws_url="ws://x", http_url="http://x")
    assert b.context_uri() is None and b.next_track() is None

    async def go():
        await b.handle_message({"type": "state", "track": {
            "spotify_uri": ONE, "context_uri": CTX, "context_type": "playlist"},
            "next_track_uri": TWO, "next_track_title": "Artist — Two",
            "context_name": "40! Lightshow"})
    run_async(go)
    assert b.context_uri() == CTX and b.context_type() == "playlist"
    assert b.context_name() == "40! Lightshow"
    assert b.next_track() == {"uri": TWO, "title": "Artist — Two"}
    assert b.status()["track"]["context_name"] == "40! Lightshow"

    async def single():
        await b.handle_message({"type": "state", "track": {
            "spotify_uri": THREE, "context_uri": "", "context_type": ""}})
    run_async(single)
    assert b.context_uri() is None and b.context_name() is None and b.next_track() is None


def test_spotfx_context_routes_read_what_it_observed(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from models.state import state as sfx_state
    from routers import spotify as spotify_router
    from api import spotify_client
    monkeypatch.setattr(sfx_state, "observed_context_uris", {CTX: "40! Lightshow"})
    monkeypatch.setattr(spotify_client, "is_authenticated", lambda: False)
    app = FastAPI()
    app.include_router(spotify_router.router)
    c = TestClient(app)
    assert c.get("/api/spotify/context-name", params={"uri": CTX}).json() == \
        {"uri": CTX, "type": "playlist", "name": "40! Lightshow"}
    # unknown and not authenticated: "" — never a guess
    assert c.get("/api/spotify/context-name",
                 params={"uri": "spotify:album:zzz"}).json()["name"] == ""
    rec = c.get("/api/spotify/contexts").json()
    assert rec["recent"] == [{"context_uri": CTX, "type": "playlist", "name": "40! Lightshow"}]
