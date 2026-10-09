"""SHOW SEQUENCES (spectra/services/show_sequence.py) — the store, and the
runner's state machine driven through the REAL show_arms (arming, cue and
scene-change hooks, its _fire) with only the set executor faked at its seam
(show_actions.fire_set) and the gate held open. No live access."""
from __future__ import annotations

import asyncio

import pytest

from spectra.models.light_show import (ActionSet, SequenceItem, SequenceWait,
                                       ShowAction, ShowSequence, SongRef)
from spectra.services import (show_actions, show_arms, show_output,
                              show_sequence, show_store)

PLAYING = {"uri": "spotify:track:one"}


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
    monkeypatch.setattr(show_arms, "current_uri", lambda: PLAYING["uri"])
    monkeypatch.setattr(show_arms, "is_playing", lambda: True)
    PLAYING["uri"] = "spotify:track:one"
    ids = {}
    for name in ("A", "B", "C", "D"):
        ids[name] = show_store.put_set(ActionSet(
            name=name, actions=[ShowAction(kind="pause", params={"seconds": 1})])).id
    return {"fired": fired, "gate": gate, "ids": ids}


def S(world, name, arm="instant"):
    return SequenceItem(kind="set", set_id=world["ids"][name], arm=arm)


def W(**kw):
    return SequenceItem(kind="wait", wait=SequenceWait(**kw))


def seq(name, *items, loop=False):
    return show_store.put_sequence(ShowSequence(name=name, items=list(items), loop=loop))


async def settle(n=20):
    for _ in range(n):
        await asyncio.sleep(0)


def cur():
    return show_sequence.run()


def run_async(coro_fn):
    return asyncio.run(coro_fn())


# ── the store ──────────────────────────────────────────────────────────────

def test_store_round_trip_names_and_duplicate(world):
    a = seq("Evening", S(world, "A", "high"), W(kind="duration", seconds=30))
    seq("Late", S(world, "B"))
    assert [s.name for s in show_store.list_sequences()] == ["Evening", "Late"]
    with pytest.raises(show_store.SequenceNameTaken):
        show_store.put_sequence(ShowSequence(name="evening"))
    dup = show_store.duplicate_sequence(a.id)
    assert dup.name == "Evening copy"
    assert [s.name for s in show_store.list_sequences()] == ["Evening", "Evening copy", "Late"]
    assert [i.id for i in dup.items] != [i.id for i in a.items]
    assert [(i.kind, i.set_id, i.arm) for i in dup.items] == \
        [(i.kind, i.set_id, i.arm) for i in a.items]
    assert show_store.duplicate_sequence(a.id).name == "Evening copy 2"
    # independent: editing the copy leaves the original alone
    dup.items[0].arm = "low"
    show_store.put_sequence(dup)
    assert show_store.get_sequence(a.id).items[0].arm == "high"
    assert show_store.delete_sequence(dup.id)
    assert not show_store.delete_sequence(dup.id)


def test_problems_are_named(world):
    s = ShowSequence(name="x", items=[SequenceItem(kind="set"), W(kind="song_list"),
                                      W(kind="trigger_count", trigger="nope")])
    p = show_sequence.problems(s)
    assert any("no set chosen" in x for x in p)
    assert any("at least one song" in x for x in p)
    assert any("trigger Wait" in x for x in p)
    looped = ShowSequence(name="y", items=[S(world, "A")], loop=True)
    assert any("Loop needs" in x for x in show_sequence.problems(looped))
    with pytest.raises(show_sequence.SequenceError):
        show_store.put_sequence(s)
        show_sequence.start("x")


# ── order, never skipping ahead ────────────────────────────────────────────

def test_runs_strictly_in_order(world):
    s = seq("Show", S(world, "A", "high"), S(world, "B"),
            W(kind="trigger_count", trigger="scene_change", count=2),
            S(world, "C", "low"))

    async def go():
        show_sequence.start(s.id)
        r = cur()
        assert r.index == 0 and r.arm_id
        arm = next(a for a in show_arms.active_arms() if a.id == r.arm_id)
        assert arm.on == "high" and arm.source.startswith("sequence:")
        assert "armed for the next High Trigger" in show_sequence.waiting_for(r)
        # a Low and a scene change while A waits on High: nothing moves
        await show_arms.on_cue("low", 1000, 0)
        show_arms.on_scene_change("x", "y")
        await settle()
        assert world["fired"] == [] and cur().index == 0
        # the High fires A, then B at once; the High did not count for the Wait
        await show_arms.on_cue("high", 2000, 0)
        await settle()
        assert world["fired"] == ["A", "B"]
        assert cur().index == 2 and cur().wait_count == 0
        assert show_sequence.waiting_for(cur()) == "waiting for 2 scene changes"
        show_arms.on_scene_change("y", "z")
        await settle()
        assert cur().wait_count == 1
        assert show_sequence.waiting_for(cur()) == "waiting for 1 more scene change"
        show_arms.on_scene_change("z", "z")          # a re-fire is no change
        show_arms.on_scene_change("z", "w")
        await settle()
        assert cur().index == 3
        await show_arms.on_cue("low", 3000, 0)
        await settle()
        assert world["fired"] == ["A", "B", "C"]
        assert cur().state == "finished"
        whats = [e["what"] for e in cur().log]
        assert whats[0] == "started" and whats[-1] == "finished"
    run_async(go)


def test_a_later_items_trigger_never_fires_it_early(world):
    s = seq("Show", S(world, "A", "high"), S(world, "B", "low"))

    async def go():
        show_sequence.start(s.id)
        await show_arms.on_cue("low", 1, 0)      # B is not armed yet
        await settle()
        assert world["fired"] == []
        assert not any(a.set_id == world["ids"]["B"] for a in show_arms.active_arms())
        await show_arms.on_cue("high", 2, 0)
        await settle()
        assert world["fired"] == ["A"] and cur().index == 1
        await show_arms.on_cue("low", 3, 0)
        await settle()
        assert world["fired"] == ["A", "B"]
    run_async(go)


def test_a_stood_down_trigger_is_not_counted_and_the_arm_waits(world):
    s = seq("Show", W(kind="trigger_count", trigger="high", count=1), S(world, "A", "high"))

    async def go():
        show_sequence.start(s.id)
        world["gate"]["reason"] = "SPECTRA does not hold the room"
        await show_arms.on_cue("high", 1, 0)
        await settle()
        assert cur().wait_count == 0
        world["gate"]["reason"] = None
        await show_arms.on_cue("high", 2, 0)
        await settle()
        assert cur().index == 1
        world["gate"]["reason"] = "a preview holds the room"
        await show_arms.on_cue("high", 3, 0)
        await settle()
        show_sequence.tick()
        assert world["fired"] == [] and "preview" in cur().waiting_reason
        world["gate"]["reason"] = None
        await show_arms.on_cue("high", 4, 0)
        await settle()
        assert world["fired"] == ["A"]
    run_async(go)


def test_an_instant_fire_refused_by_the_gate_retries_on_the_tick(world):
    s = seq("Show", S(world, "A"))
    world["gate"]["reason"] = "a camera run holds the room"

    async def go():
        show_sequence.start(s.id)
        await settle()
        assert world["fired"] == [] and cur().waiting_reason
        world["gate"]["reason"] = None
        show_sequence.tick()
        await settle()
        assert world["fired"] == ["A"] and cur().state == "finished"
    run_async(go)


# ── every Wait kind ────────────────────────────────────────────────────────

def test_duration_wait(world, monkeypatch):
    clock = {"t": 1_000_000}
    monkeypatch.setattr(show_sequence, "now_ms", lambda: clock["t"])
    s = seq("Show", W(kind="duration", seconds=90), S(world, "A"))

    async def go():
        show_sequence.start(s.id)
        assert show_sequence.waiting_for(cur()) == "waiting 1:30 more"
        clock["t"] += 89_000
        show_sequence.tick()
        assert cur().index == 0
        clock["t"] += 1_000
        show_sequence.tick()
        await settle()
        assert world["fired"] == ["A"]
    run_async(go)


def test_songs_wait_counts_song_starts_after_it_is_current(world):
    s = seq("Show", W(kind="songs", count=2), S(world, "A"))

    async def go():
        show_sequence.start(s.id)
        show_sequence.on_track_change("spotify:track:one")   # still the same song
        assert cur().wait_count == 0
        show_sequence.on_track_change("spotify:track:two")
        show_sequence.on_track_change("spotify:track:two")
        assert cur().wait_count == 1
        assert show_sequence.waiting_for(cur()) == "waiting for 1 more song to start"
        show_sequence.on_track_change("spotify:track:three")
        await settle()
        assert world["fired"] == ["A"]
    run_async(go)


def test_song_list_wait(world):
    songs = [SongRef(uri="spotify:track:x", title="Xanadu", artist="ELO"),
             SongRef(uri="spotify:track:y", title="Yellow")]
    s = seq("Show", W(kind="song_list", songs=songs), S(world, "A"))

    async def go():
        show_sequence.start(s.id)
        assert show_sequence.waiting_for(cur()) == \
            "waiting for one of: Xanadu — ELO, Yellow"
        show_sequence.on_track_change("spotify:track:other")
        assert cur().index == 0
        show_sequence.on_track_change("spotify:track:y")
        await settle()
        assert world["fired"] == ["A"]
        assert any("Yellow started" in e["detail"] for e in cur().log)
    run_async(go)


def test_song_list_wait_is_satisfied_by_a_listed_song_already_playing(world):
    PLAYING["uri"] = "spotify:track:x"
    s = seq("Show", S(world, "A"), W(kind="song_list",
                                     songs=[SongRef(uri="spotify:track:x")]),
            S(world, "B", "high"))

    async def go():
        show_sequence.start(s.id)
        await settle()
        assert world["fired"] == ["A"] and cur().index == 2
    run_async(go)


# ── the human override ─────────────────────────────────────────────────────

def test_pause_freezes_and_resume_rearms(world, monkeypatch):
    clock = {"t": 1_000_000}
    monkeypatch.setattr(show_sequence, "now_ms", lambda: clock["t"])
    s = seq("Show", S(world, "A", "high"), W(kind="duration", seconds=60),
            W(kind="trigger_count", trigger="low", count=1), S(world, "B"))

    async def go():
        show_sequence.start(s.id)
        show_sequence.pause()
        assert not show_arms.active_arms()                 # its arm is gone
        await show_arms.on_cue("high", 1, 0)
        await settle()
        assert world["fired"] == []
        show_sequence.resume()
        assert len(show_arms.active_arms()) == 1
        await show_arms.on_cue("high", 2, 0)
        await settle()
        assert cur().index == 1
        clock["t"] += 20_000
        show_sequence.pause()
        clock["t"] += 600_000                              # paused for 10 min
        show_sequence.tick()
        assert cur().index == 1 and cur().wait_remaining_ms == 40_000
        show_sequence.resume()
        clock["t"] += 39_000
        show_sequence.tick()
        assert cur().index == 1
        clock["t"] += 1_000
        show_sequence.tick()
        assert cur().index == 2
        show_sequence.pause()
        await show_arms.on_cue("low", 3, 0)                # ignored while paused
        assert cur().wait_count == 0
        show_sequence.resume()
        await show_arms.on_cue("low", 4, 0)
        await settle()
        assert world["fired"] == ["A", "B"]
    run_async(go)


def test_next_skips_previous_rearms_and_fire_now(world):
    s = seq("Show", S(world, "A", "high"), S(world, "B"), S(world, "C", "low"))

    async def go():
        show_sequence.start(s.id)
        show_sequence.next_item()                          # A skipped unfired
        await settle()
        assert world["fired"] == ["B"] and cur().index == 2
        show_sequence.previous_item()                      # back onto instant B
        await settle()
        assert cur().index == 1 and cur().awaiting_fire
        assert world["fired"] == ["B"]                     # no surprise re-fire
        assert not show_arms.active_arms()                 # C's arm went
        await show_sequence.fire_now()
        await settle()
        assert world["fired"] == ["B", "B"] and cur().index == 2
        await show_sequence.fire_now()                     # C fired by hand
        assert world["fired"] == ["B", "B", "C"] and cur().state == "finished"
        assert not show_arms.active_arms()
        with pytest.raises(show_sequence.SequenceError):
            show_sequence.next_item()
    run_async(go)


def test_previous_onto_an_armed_item_rearms_it(world):
    s = seq("Show", S(world, "A", "high"), W(kind="songs", count=1))

    async def go():
        show_sequence.start(s.id)
        await show_arms.on_cue("high", 1, 0)
        await settle()
        assert cur().index == 1
        show_sequence.previous_item()
        assert cur().index == 0
        arm = next(a for a in show_arms.active_arms() if a.id == cur().arm_id)
        assert arm.on == "high"
    run_async(go)


def test_one_at_a_time_and_stop(world):
    a = seq("One", S(world, "A", "high"))
    b = seq("Two", S(world, "B", "low"))

    async def go():
        show_sequence.start(a.id)
        with pytest.raises(show_sequence.SequenceError):
            show_sequence.start(b.id)
        show_sequence.start(b.id, replace=True)
        assert cur().name == "Two"
        assert [x.set_id for x in show_arms.active_arms()] == [world["ids"]["B"]]
        show_sequence.stop()
        assert cur().state == "stopped" and not show_arms.active_arms()
    run_async(go)


def test_loop_starts_again_from_the_top(world):
    s = seq("Show", S(world, "A", "high"), S(world, "B"), loop=True)

    async def go():
        show_sequence.start(s.id)
        await show_arms.on_cue("high", 1, 0)
        await settle()
        assert world["fired"] == ["A", "B"]
        assert cur().state == "running" and cur().index == 0 and cur().loops_done == 1
    run_async(go)


def test_release_pauses_the_sequence(world):
    s = seq("Show", S(world, "A", "high"))

    async def go():
        show_sequence.start(s.id)
        show_output.on_release()
        assert cur().state == "paused" and "released" in cur().paused_reason
        assert not show_arms.active_arms()
    run_async(go)


def test_a_hand_disarm_pauses_rather_than_hangs(world):
    s = seq("Show", S(world, "A", "high"))

    async def go():
        show_sequence.start(s.id)
        show_arms.disarm_all()
        show_sequence.tick()
        assert cur().state == "paused" and "disarmed" in cur().paused_reason
    run_async(go)


# ── the arm board's own rules ──────────────────────────────────────────────

def test_sequence_arm_and_hand_arm_never_replace_each_other(world):
    s = seq("Show", S(world, "A", "high"))

    async def go():
        show_sequence.start(s.id)
        show_arms.arm(set_id=world["ids"]["A"], on="high")
        assert len(show_arms.active_arms()) == 2
        show_arms.arm(set_id=world["ids"]["A"], on="high")   # the hand arm replaces itself
        assert len(show_arms.active_arms()) == 2
        seq_arm = next(a for a in show_arms.active_arms() if a.id == cur().arm_id)
        assert seq_arm.expires_ms is None
    run_async(go)


def test_a_sequence_arm_never_expires_on_its_own(world, monkeypatch):
    s = seq("Show", S(world, "A", "high"))

    async def go():
        show_sequence.start(s.id)
        monkeypatch.setattr(show_arms, "is_playing", lambda: False)
        monkeypatch.setattr(show_arms, "_last_music_mono", -10 ** 9)
        show_arms.tick()
        assert any(a.id == cur().arm_id for a in show_arms.active_arms())
    run_async(go)


# ── a restart ──────────────────────────────────────────────────────────────

def _restart():
    """A new process: the in-memory state and the runner's memory go; the
    files stay."""
    show_store.reset_memory()
    show_sequence.reset()


def test_restart_resumes_at_the_current_item(world, monkeypatch):
    clock = {"t": 1_000_000}
    monkeypatch.setattr(show_sequence, "now_ms", lambda: clock["t"])
    s = seq("Show", S(world, "A", "high"), W(kind="duration", seconds=60),
            W(kind="songs", count=1), S(world, "B", "low"))

    async def go():
        show_sequence.start(s.id)
        await show_arms.on_cue("high", 1, 0)
        await settle()
        assert cur().index == 1
        clock["t"] += 30_000
        _restart()
        show_sequence.tick()
        assert cur().index == 1 and cur().log[-1]["what"] == "resumed"
        clock["t"] += 30_000                                # the deadline held
        show_sequence.tick()
        assert cur().index == 2
        _restart()
        show_sequence.tick()
        # the playing song re-reported after the restart is not a new start
        show_sequence.on_track_change("spotify:track:one")
        assert cur().index == 2
        show_sequence.on_track_change("spotify:track:two")
        assert cur().index == 3
        armed = cur().arm_id
        _restart()
        show_sequence.tick()
        assert cur().arm_id == armed                       # the arm survived
        await show_arms.on_cue("low", 2, 0)
        await settle()
        assert world["fired"] == ["A", "B"] and cur().state == "finished"
    run_async(go)


def test_restart_rearms_an_arm_that_did_not_survive(world):
    s = seq("Show", S(world, "A", "high"))

    async def go():
        show_sequence.start(s.id)
        show_store.state().arms.clear()
        show_store.save_state()
        _restart()
        show_sequence.tick()
        assert cur().state == "running"
        assert any(a.id == cur().arm_id and a.on == "high" for a in show_arms.active_arms())
    run_async(go)


def test_restart_fires_an_instant_item_that_had_not_fired(world):
    s = seq("Show", W(kind="songs", count=1), S(world, "A"))

    async def go():
        show_sequence.start(s.id)
        r = cur()
        r.index = 1                 # crashed between entering and firing
        show_store.save_state()
        _restart()
        show_sequence.tick()
        await settle()
        assert world["fired"] == ["A"] and cur().state == "finished"
    run_async(go)


def test_every_step_is_in_the_show_log(world, monkeypatch):
    seen = []
    from spectra.services import fire_history
    monkeypatch.setattr(fire_history, "record_fire",
                        lambda bucket, key, detail=None: seen.append((bucket, key)))
    s = seq("Show", S(world, "A"))

    async def go():
        show_sequence.start(s.id)
        await settle()
    run_async(go)
    keys = [k for b, k in seen if b == "show"]
    assert {"sequence_started", "sequence_entered", "sequence_completed",
            "sequence_finished"} <= set(keys)


# ── the wire ───────────────────────────────────────────────────────────────

def test_routes_round_trip(world, tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient

    from spectra import config as scfg
    from spectra.app import create_app
    from spectra.services import song_library
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    for i, (title, artist, uri) in enumerate([
            ("El Apagón", "Bad Bunny", "spotify:track:apagon"),
            ("Dopamine", "Purple Disco Machine", "spotify:track:dopa"),
            ("Old one", "", "ledfx:old:one")]):
        (profiles / f"p{i}.json").write_text(json.dumps(
            {"title": title, "artist": artist, "spotify_uri": uri}))
    monkeypatch.setattr(scfg, "PROFILES_DIR", profiles)
    song_library.reset()
    client = TestClient(create_app())

    r = client.post("/api/light-show/sequences", json={
        "name": "Party", "items": [
            {"kind": "set", "set_id": world["ids"]["A"], "arm": "high"},
            {"kind": "wait", "wait": {"kind": "duration", "seconds": 30}}]})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert r.json()["items"][0]["title"] == "A — next High Trigger"
    assert client.post("/api/light-show/sequences", json={"name": "party"}).status_code == 409
    dup = client.post(f"/api/light-show/sequences/{sid}/duplicate").json()
    assert dup["name"] == "Party copy"
    names = [s["name"] for s in client.get("/api/light-show/sequences").json()["sequences"]]
    assert names == ["Party", "Party copy"]

    st = client.post("/api/light-show/sequence-run/start", json={"sequence_id": sid}).json()
    assert st["run"]["state"] == "running"
    assert st["run"]["waiting_for"] == "armed for the next High Trigger"
    assert client.post("/api/light-show/sequence-run/start",
                       json={"sequence_id": dup["id"]}).status_code == 409
    assert client.delete(f"/api/light-show/sequences/{sid}").status_code == 409
    assert client.post("/api/light-show/sequence-run/next").json()["run"]["index"] == 1
    assert client.post("/api/light-show/sequence-run/pause").json()["run"]["state"] == "paused"
    assert client.post("/api/light-show/sequence-run/resume").json()["run"]["state"] == "running"
    assert client.post("/api/light-show/sequence-run/previous").json()["run"]["index"] == 0
    assert client.post("/api/light-show/sequence-run/stop").json()["run"]["state"] == "stopped"
    assert client.post("/api/light-show/sequence-run/stop").status_code == 409

    found = client.get("/api/light-show/songs", params={"q": "apagon"}).json()
    assert [s["uri"] for s in found["songs"]] == ["spotify:track:apagon"]
    every = client.get("/api/light-show/songs").json()["songs"]
    assert {s["uri"] for s in every} == {"spotify:track:apagon", "spotify:track:dopa"}
    assert client.get("/api/light-show/songs", params={"q": "purple disco"}).json()["songs"][0]["title"] == "Dopamine"


# ── Sonic ──────────────────────────────────────────────────────────────────

def test_sonic_reads_and_drives_a_sequence_by_name(world):
    from spectra.services import settings_agent, show_console
    for op in ("list_show_sequences", "show_sequence_status", "start_show_sequence",
               "stop_show_sequence", "pause_show_sequence", "resume_show_sequence",
               "next_show_sequence_step", "previous_show_sequence_step",
               "fire_show_sequence_step"):
        assert op in settings_agent.ALL_OPERATIONS
    seq("Friday Night", S(world, "A", "high"), W(kind="songs", count=2))

    async def go():
        ops = show_console.OPERATIONS
        assert ops["list_show_sequences"].handler()["sequences"][0]["items"] == [
            "A — next High Trigger", "Wait for 2 songs"]
        bad = ops["start_show_sequence"].handler(sequence_name="friday nite")
        assert bad["status"] == "rejected" and "Friday Night" in bad["close_matches"]
        ok = ops["start_show_sequence"].handler(sequence_name="friday night")
        assert ok["status"] == "applied" and ok["now"] == "armed for the next High Trigger"
        st = ops["show_sequence_status"].handler()["run"]
        assert st["current"] == "A — next High Trigger" and st["upcoming"] == ["Wait for 2 songs"]
        assert ops["next_show_sequence_step"].handler()["now"] == "waiting for 2 songs to start"
        assert ops["pause_show_sequence"].handler()["status"] == "applied"
        assert ops["resume_show_sequence"].handler()["status"] == "applied"
        assert ops["previous_show_sequence_step"].handler()["index"] == 0
        fired = await ops["fire_show_sequence_step"].handler()
        assert fired["status"] == "applied" and world["fired"] == ["A"]
        assert ops["stop_show_sequence"].handler()["status"] == "applied"
        assert ops["stop_show_sequence"].handler()["status"] == "rejected"
    run_async(go)
