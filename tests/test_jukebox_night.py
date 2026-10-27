"""The Jukebox's program engine at run time (services/jukebox/night.py),
driven over a fake Spotify player and a fake clock (tests/jukebox_world.py).

What is asserted is what the PLAYER played — the order songs actually
started — not what the engine believed: every other, every 3rd, two in a
row, manual slots, an empty slot that passes, the committed song that can't
move, a missed commit that re-syncs without a double send, the repair skip,
shuffle off, the run-out policies, and the house rules (sleeping, Absorb).
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from models.jukebox import ManualSlot
from services.jukebox import night as night_mod, store
from tests.jukebox_world import World, jb_uri, set_uri


def go(coro):
    return asyncio.run(coro)


def _night(w: World, adds: int = 0, seconds: int = 0, **start):
    async def run():
        r = await w.start(**start)
        for i in range(adds):
            await w.add(i)
        await w.run(seconds)
        return r
    return go(run())


def _sends(w: World) -> list[str]:
    return [w.titles[c[2][0]] for c in w.gw.calls if c[1] == "add_to_queue"]


# ── the slot patterns ───────────────────────────────────────────────────────

def test_every_other():
    w = World()
    r = _night(w, adds=4, seconds=8 * 110 + 60)
    assert r["status"] == "running"
    assert w.played()[:9] == ["S0", "J0", "S1", "J1", "S2", "J2", "S3", "J3", "S4"]
    assert _sends(w) == ["J0", "J1", "J2", "J3"]       # each sent once, never twice


def test_every_third():
    w = World(every=3)
    _night(w, adds=2, seconds=8 * 120 + 60)
    assert w.played()[:9] == ["S0", "S1", "S2", "J0", "S3", "S4", "S5", "J1", "S6"]


def test_two_in_a_row():
    w = World(run=2)
    _night(w, adds=4, seconds=7 * 120)
    assert w.played()[:7] == ["S0", "J0", "J1", "S1", "J2", "J3", "S2"]


def test_jukebox_first():
    w = World(mode="jukebox_first")
    _night(w, adds=3, seconds=6 * 120)
    assert w.played()[:6] == ["S0", "J0", "J1", "J2", "S1", "S2"]


def test_manual_slots():
    w = World(mode="manual", manual=[ManualSlot(after_uri=set_uri(1), count=2),
                                     ManualSlot(after_uri=set_uri(2), count=1)])
    _night(w, adds=4, seconds=8 * 120)
    assert w.played()[:7] == ["S0", "S1", "J0", "J1", "S2", "J2", "S3"]


def test_the_commit_lands_about_45_s_before_the_end_and_reads_back():
    w = World()
    _night(w, adds=1, seconds=90)
    send = next(c for c in w.gw.calls if c[1] == "add_to_queue")
    start = next(c for c in w.gw.calls if c[1] == "start_context")
    assert 74 <= send[0] - start[0] <= 76            # a 120 s song: 120 - 45 = 75 s in
    names = w.gw.names()
    assert names[names.index("add_to_queue") + 1] == "queue"
    entry = w.runner.night.line[0]
    assert (entry.state, entry.commit_check) == ("committed", "next")


# ── an empty slot passes ────────────────────────────────────────────────────

def test_an_empty_slot_passes_and_the_set_continues():
    w = World()
    _night(w, seconds=3 * 120 + 30)
    assert w.played()[:4] == ["S0", "S1", "S2", "S3"]
    assert "add_to_queue" not in w.gw.names()
    assert w.runner.night.cursor.owed == 0


def test_a_song_added_mid_set_plays_at_the_next_gap():
    w = World(every=2)

    async def run():
        await w.start()
        await w.run(130)              # S0 done, S1 playing
        await w.add(0)                # added before S1's commit window
        await w.run(3 * 120)
    go(run())
    assert w.played()[:4] == ["S0", "S1", "J0", "S2"]


def test_a_song_added_too_late_waits_for_the_following_gap():
    w = World(every=2)

    async def run():
        await w.start()
        await w.run(240 - 3)          # S1's last 3 s: too late for this gap
        w.player.lock_ms = 5_000      # the player has already picked S2
        await w.add(0)
        await w.run(5 * 120)
    go(run())
    played = w.played()
    assert played[:3] == ["S0", "S1", "S2"]
    assert played.count("J0") == 1
    assert _sends(w) == ["J0"]


def test_a_waiting_song_the_set_reaches_plays_as_a_set_song_and_leaves_the_line():
    w = World(every=3)

    async def run():
        await w.start()
        await w.runner.add(set_uri(1))          # someone asks for a song that is next in the set
        await w.add(0)
        await w.run(4 * 120 + 30)
    go(run())
    played = w.played()
    assert played[:5] == ["S0", "S1", "S2", "J0", "S3"]   # S1 counted for the rhythm; J0 fills the slot
    assert played.count("S1") == 1
    assert w.runner.night.line[0].state == "played"
    assert set_uri(1) not in [c[2][0] for c in w.gw.calls if c[1] == "add_to_queue"]


# ── the committed song can't move ───────────────────────────────────────────

def test_the_committed_song_cant_move_and_nothing_passes_it():
    w = World()

    async def run():
        await w.start()
        await w.add(0)
        await w.add(1)
        await w.run(80)               # J0 committed during S0's window
        n = w.runner.night
        j0, j1 = n.line[0], n.line[1]
        assert j0.state == "committed"
        refused = await w.runner.move(j0.id, 1)
        assert refused["reason"] == "committed_fixed"
        moved = await w.runner.move(j1.id, 0)         # to the front of the WAITING songs
        assert moved["status"] == "moved"
        await w.run(4 * 120)
    go(run())
    assert w.played()[:4] == ["S0", "J0", "S1", "J1"]


def test_moving_waiting_songs_reorders_what_is_sent_next():
    w = World()

    async def run():
        await w.start()
        for i in range(3):
            await w.add(i)
        await w.run(80)               # J0 committed
        j2 = w.runner.night.line[2]
        await w.runner.move(j2.id, 0)
        await w.run(5 * 120)
    go(run())
    assert w.played()[:6] == ["S0", "J0", "S1", "J2", "S2", "J1"]


# ── a missed commit re-syncs ────────────────────────────────────────────────

def test_a_stalled_engine_owes_the_slot_to_the_next_gap():
    w = World(every=3)

    async def run():
        await w.start()
        await w.add(0)
        await w.add(1)
        await w.run(3 * 120 - 50)               # into S2, before its window
        await w.run(60, engine=False)           # the engine stalls through S2's end
        await w.run(6 * 120)
    go(run())
    assert w.played()[:9] == ["S0", "S1", "S2", "S3", "J0", "S4", "S5", "J1", "S6"]
    assert _sends(w) == ["J0", "J1"]


def test_failed_sends_owe_the_slot():
    w = World()

    async def run():
        await w.start()
        await w.add(0)
        await w.add(1)
        w.gw.fail["add_to_queue"] = 3           # every attempt in S0's window fails
        await w.run(5 * 120)
    go(run())
    played = w.played()
    assert played[:2] == ["S0", "S1"]
    # S1's gap carries the owed slot: both songs play before S2
    assert played[2:5] == ["J0", "J1", "S2"]


def test_a_commit_after_the_player_picked_its_next_is_carried_never_resent():
    w = World()
    w.player.lock_ms = 50_000                    # S0's end: the next track was picked at T-50 s

    async def run():
        await w.start()
        for i in range(3):
            await w.add(i)
        await w.run(121)
        w.player.lock_ms = 0                     # a one-off: later songs are on time
        await w.run(6 * 120)
    go(run())
    played = w.played()
    # J0 was sent too late for S0's gap: it plays after S1, and S1's gap carries
    # the owed slot so J1 still gets its turn before S2
    assert played[:6] == ["S0", "S1", "J0", "J1", "S2", "J2"]
    assert _sends(w) == ["J0", "J1", "J2"]


def test_a_crossfade_longer_than_the_lead_slips_every_song_but_loses_none():
    w = World()
    w.player.lock_ms = 50_000                    # longer than the 45 s lead, all night

    async def run():
        await w.start()
        for i in range(3):
            await w.add(i)
        await w.run(8 * 120)
    go(run())
    played = w.played()
    assert [played.count(f"J{i}") for i in range(3)] == [1, 1, 1]
    assert _sends(w) == ["J0", "J1", "J2"]       # never sent twice


def test_a_read_back_that_misses_the_song_reads_again_before_resending():
    w = World()

    async def run():
        await w.start()
        await w.add(0)
        w.gw.hide_from_queue.add(jb_uri(0))     # the first read-back doesn't show it
        await w.run(76)
        assert w.runner.night.line[0].commit_check == "missing"
        w.gw.hide_from_queue.clear()             # ... the second one does
        await w.run(4)
        assert w.runner.night.line[0].commit_check == "next"
        await w.run(200)
    go(run())
    assert _sends(w) == ["J0"]
    assert w.played()[:3] == ["S0", "J0", "S1"]


def test_a_song_spotify_never_shows_goes_back_in_line_and_is_sent_again():
    w = World()

    async def run():
        await w.start()
        await w.add(0)
        w.gw.hide_from_queue.add(jb_uri(0))
        w.gw.fail["add_to_queue"] = 0
        orig = w.gw.add_to_queue

        def lost(uri):                           # Spotify accepts it and drops it
            w.gw._rec("add_to_queue", uri)
        w.gw.add_to_queue = lost
        await w.run(80)
        assert w.runner.night.line[0].state == "queued"
        w.gw.add_to_queue = orig
        w.gw.hide_from_queue.clear()
        await w.run(4 * 120)
    go(run())
    assert w.played().count("J0") == 1
    assert len(_sends(w)) == 2


# ── the repair path ─────────────────────────────────────────────────────────

def test_a_removed_committed_song_is_skipped_as_it_starts():
    w = World()

    async def run():
        await w.start()
        await w.add(0)
        await w.run(80)
        j0 = w.runner.night.line[0]
        r = await w.runner.remove(j0.id)
        assert r["status"] == "will_skip"
        await w.run(3 * 120)
    go(run())
    assert w.played()[:3] == ["S0", "J0", "S1"]   # J0 starts and is skipped at once
    assert "next_track" in w.gw.names()
    assert w.runner.night.played[1].kind == "skipped"


def test_a_removed_committed_song_is_replaced_behind_it():
    w = World()

    async def run():
        await w.start()
        await w.add(0)
        await w.add(1)
        await w.run(80)
        await w.runner.remove(w.runner.night.line[0].id)
        await w.run(4 * 120)
    go(run())
    assert w.played()[:4] == ["S0", "J0", "J1", "S1"]   # J0 skipped; J1 keeps the slot
    assert _sends(w) == ["J0", "J1"]


def test_removing_a_waiting_song_drops_it():
    w = World()

    async def run():
        await w.start()
        await w.add(0)
        await w.add(1)
        await w.runner.remove(w.runner.night.line[0].id)
        await w.run(3 * 120)
    go(run())
    assert w.played()[:3] == ["S0", "J1", "S1"]


# ── shuffle, repeat, and the set running out ────────────────────────────────

def test_start_turns_shuffle_off_and_sets_repeat_to_the_policy():
    w = World()
    _night(w)
    assert w.player.shuffle is False and w.player.repeat == "context"
    assert w.runner.night.warnings == []


def test_a_shuffle_that_wont_turn_off_is_a_warning():
    w = World()
    w.gw.shuffle_stuck = True
    _night(w, adds=1, seconds=200)
    assert any("Shuffle is on" in x for x in w.runner.night.warnings)
    assert w.runner.running                      # the slot rhythm still works


def test_run_out_again_plays_the_set_again():
    w = World(n_set=3)
    _night(w, seconds=4 * 120 + 30)
    assert w.played()[:5] == ["S0", "S1", "S2", "S0", "S1"]
    assert w.runner.night.cursor.loops == 1


def test_run_out_jukebox_only_plays_the_line_then_ends():
    w = World(n_set=2, run_out="jukebox_only")
    _night(w, adds=4, seconds=2 * 120 + 4 * 100 + 60)
    assert w.player.repeat == "off"
    assert w.played() == ["S0", "J0", "S1", "J1", "J2", "J3"]
    assert w.runner.night.state == "ended"
    assert w.runner.night.end_reason == "set_ran_out"


def test_run_out_end_ends_with_the_last_set_song():
    w = World(n_set=2, run_out="end")
    _night(w, adds=3, seconds=6 * 120)
    assert w.played() == ["S0", "J0", "S1"]
    assert _sends(w) == ["J0"]
    assert w.runner.night.state == "ended"


def test_an_autoplay_after_the_end_is_paused():
    w = World(n_set=1, run_out="end")

    async def run():
        await w.start()
        await w.run(119)
        w.player.context.append(set_uri(50))      # Spotify's autoplay picks a song
        w.player.durations[set_uri(50)] = 120_000
        w.player.repeat = "context"
        w.player.foreign_context = "spotify:station:autoplay"
        await w.run(5)
    go(run())
    assert w.runner.night.state == "ended" and "pause" in w.gw.names()


# ── following, the device, off the set ──────────────────────────────────────

def test_the_old_song_reported_before_the_start_took_is_ignored():
    w = World()

    async def run():
        w.player.start_context(5)                  # he was listening to the set at S5
        w.player.durations[set_uri(5)] = 10 ** 9
        real = w.gw.start_context
        w.gw.start_context = lambda *a: w.gw._rec("start_context", *a)   # Spotify is slow
        await w.start()
        await w.run(3)                             # the poll still says S5
        assert w.runner.night.cursor.started is False
        real("dev-serenity", "x", 0)               # ... then the set starts from S0
        await w.run(2)
    go(run())
    n = w.runner.night
    assert n.now.title == "S0" and n.cursor.set_pos == 0
    assert [p.title for p in n.played] == ["S0"]


def test_follow_mode_attaches_to_his_playback():
    w = World()

    async def run():
        w.player.start_context(4)                  # he started the set himself
        r = await w.start(play=False)
        assert r["status"] == "running"
        await w.add(0)
        await w.run(240)
    go(run())
    assert "start_context" not in w.gw.names()
    assert w.played()[:3] == ["S4", "J0", "S5"]
    assert w.runner.night.owns_playback is False


def test_nothing_is_sent_while_playback_is_on_another_device():
    w = World()

    async def run():
        await w.start()
        await w.add(0)
        w.on_device = False
        await w.run(100)
        assert any("not Serenity" in x for x in w.runner.night.warnings)
        assert "add_to_queue" not in w.gw.names()
        w.on_device = True
        await w.run(200)
    go(run())


def test_off_the_set_the_engine_waits():
    w = World()

    async def run():
        await w.start()
        await w.add(0)
        await w.run(20)
        w.player.foreign_context = "spotify:album:hisalbum"
        w.player.context = [jb_uri(9)] + w.player.context
        w.player.start_context(0)                  # he plays something else
        await w.run(90)
        assert "add_to_queue" not in w.gw.names()
        assert any("isn't in the set" in x for x in w.runner.night.warnings)
    go(run())


def test_a_reordered_playlist_is_picked_up():
    w = World()

    async def run():
        await w.start()
        await w.run(10)
        p = w.player
        p.context = [p.context[0], p.context[3], p.context[1], p.context[2]] + p.context[4:]
        w.gw.snapshot = "snap-2"
        await w.run(120)                         # S3 now plays second; re-read at its start
        n = w.runner.night
        assert n.snapshot_id == "snap-2"
        assert [s.title for s in n.set_items[:3]] == ["S0", "S3", "S1"]
        status = w.runner.status(4)
        assert [i["title"] for i in status["next"] if i["kind"] == "set"][:2] == ["S1", "S2"]
    go(run())


# ── house rules ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("asleep, reason", [(True, "sleeping"), (None, "sleeping_unreadable")])
def test_a_night_never_starts_while_the_house_sleeps(asleep, reason):
    w = World()
    w.asleep = asleep
    r = _night(w)
    assert (r["status"], r["reason"]) == ("refused", reason)
    assert "start_context" not in w.gw.names()
    assert store.load_nights().night.end_reason == reason


def test_a_night_ends_when_the_house_goes_to_sleep():
    w = World()

    async def run():
        await w.start()
        await w.run(30)
        w.asleep = True
        await w.run(61)
    go(run())
    n = w.runner.night
    assert (n.state, n.end_reason) == ("ended", "sleeping")
    assert "pause" in w.gw.names()               # the engine started the music, so it stops it


def test_one_unreadable_sleeping_reading_does_not_end_a_party():
    w = World()

    async def run():
        await w.start()
        w.asleep = None
        await w.run(61)
        assert w.runner.running
        w.asleep = False
        await w.run(61)
        assert w.runner.running
        w.asleep = None
        await w.run(122)
    go(run())
    assert w.runner.night.end_reason == "sleeping_unreadable"


def test_a_night_never_starts_while_absorb_has_a_window():
    w = World()
    w.absorb = True
    r = _night(w)
    assert r["reason"] == "absorb_window"


@pytest.mark.parametrize("setup, reason", [
    (lambda w: setattr(w.cfg, "playlist", ""), "no_playlist"),
    (lambda w: w.gw.devices.clear(), "device_unreachable"),
    (lambda w: setattr(w.cfg, "playlist", "spotify:playlist:someotherone12345"),
     "playlist_unresolved"),
    (lambda w: w.player.context.clear(), "playlist_empty"),
])
def test_each_gate_refuses_by_name_and_is_recorded(setup, reason):
    w = World()
    setup(w)
    r = _night(w)
    assert (r["status"], r["reason"]) == ("refused", reason) and r["detail"]
    assert "start_context" not in w.gw.names()


def test_a_second_start_is_refused():
    w = World()
    _night(w)
    assert go(w.start())["reason"] == "already_running"


def test_stop_leaves_the_music_playing_unless_asked():
    w = World()
    _night(w, seconds=10)
    r = go(w.runner.stop())
    assert r["status"] == "ended" and "pause" not in w.gw.names()


def test_a_stale_night_ends_itself():
    w = World()

    async def run():
        await w.start()
        w.clock.t += night_mod.MAX_NIGHT_S + 1
        await w.runner.step()
    go(run())
    assert w.runner.night.end_reason == "stale"


# ── a restart ───────────────────────────────────────────────────────────────

def test_a_restart_follows_the_night_again_and_resyncs_the_queue():
    w = World()

    async def run():
        await w.start()
        await w.add(0)
        await w.add(1)
        await w.run(80)                          # J0 committed and in Spotify's queue
    go(run())
    w2 = World()
    w2.player, w2.gw = w.player, w.gw
    w2.clock = w.clock
    w2.deps.gateway = w.gw
    w2.deps.clock = w.clock
    w2.deps.current_track = w2.track
    w2.deps.now_ms = lambda: int(w.clock.t * 1000)
    w2.titles = w.titles
    w2.runner = night_mod.JukeboxRunner(w2.deps)
    w2.runner.recover()
    assert w2.runner.running
    go(w2.run(3 * 120))
    assert w2.played()[:4] == ["S0", "J0", "S1", "J1"]
    assert _sends(w2) == ["J0", "J1"]            # J0 was not sent a second time


def test_a_restart_puts_a_lost_commit_back_in_line():
    w = World()

    async def run():
        await w.start()
        await w.add(0)
        await w.run(80)
    go(run())
    w.player.user_queue.clear()                  # Spotify dropped it while SpotFX was down
    runner = night_mod.JukeboxRunner(w.deps)
    runner.recover()
    w.runner = runner
    go(w.run(1))
    assert any("back in the line (after a restart)" in line for line in runner.night.log)
    go(w.run(3 * 120))
    assert w.played().count("J0") == 1
    assert _sends(w) == ["J0", "J0"]             # re-sent once, because Spotify had lost it


# ── reads ───────────────────────────────────────────────────────────────────

def test_status_lists_the_next_20_with_start_times():
    w = World()

    async def run():
        await w.start()
        for i in range(3):
            await w.add(i)
        await w.run(20)
    go(run())
    s = w.runner.status(20)
    assert s["running"] and s["now"]["title"] == "S0"
    assert len(s["next"]) == 20
    assert [i["title"] or "_" for i in s["next"][:7]] == ["J0", "S1", "J1", "S2", "J2", "S3", "_"]
    assert s["next"][0]["starts_in_ms"] == 100_000
    assert s["next"][1]["starts_in_ms"] == 200_000
    assert [e["title"] for e in s["line"]] == ["J0", "J1", "J2"]


def test_no_night_status_is_empty():
    s = night_mod.JukeboxRunner(World().deps).status()
    assert s["night"] is None and s["next"] == []


def test_the_night_file_is_written_atomically_and_reloads():
    w = World()
    _night(w, adds=1, seconds=80)
    nights = store.load_nights()
    assert nights.night.id == w.runner.night.id
    assert nights.night.line[0].state == "committed"


# ── every Spotify call is off the event loop ────────────────────────────────

def test_every_gateway_call_runs_on_a_worker_thread():
    w = World()
    seen: list[tuple[str, bool]] = []
    loop_thread: list[int] = []

    def wrap(name):
        inner = getattr(w.gw, name)

        def f(*a, **k):
            seen.append((name, threading.get_ident() == loop_thread[0]))
            return inner(*a, **k)
        return f

    for name in ("device_id", "resolve_playlist", "playlist_items", "start_context",
                 "set_shuffle", "set_repeat", "playback", "add_to_queue", "queue",
                 "playlist_snapshot", "track"):
        setattr(w.gw, name, wrap(name))
    w.deps.to_thread = night_mod._default_to_thread

    async def run():
        loop_thread.append(threading.get_ident())
        await w.start()
        await w.add(0)
        await w.run(130)
    go(run())
    assert seen and not any(on_loop for _, on_loop in seen)
    assert {n for n, _ in seen} >= {"add_to_queue", "queue", "start_context", "track"}


# ── the set-list editor's reads and the set move ───────────────────────────

def test_the_editor_preview_has_the_set_one_pass_and_the_manual_copy():
    w = World(n_set=4, every=2)
    p = go(w.runner.preview(w.cfg))
    assert p["status"] == "ok" and len(p["set"]) == 4
    assert [i["kind"] for i in p["lap_items"]] == ["set", "set", "open", "set", "set", "open"]
    assert [m["after_uri"] for m in p["manual_equivalent"]] == [set_uri(1), set_uri(3)]
    assert p["playhead"] is None
    before = w.gw.names().count("playlist_items")
    go(w.runner.preview(w.cfg))                       # an editor click: no Spotify read
    assert w.gw.names().count("playlist_items") == before
    go(w.runner.preview(w.cfg, refresh=True))
    assert w.gw.names().count("playlist_items") == before + 1


def test_moving_a_set_song_without_a_night_reorders_the_playlist():
    w = World(n_set=5)
    r = go(w.runner.move_set_song(4, 1))
    assert r["status"] == "moved"
    assert [w.titles[u] for u in w.player.context] == ["S0", "S4", "S1", "S2", "S3"]
    assert [x["title"] for x in r["set"]] == ["S0", "S4", "S1", "S2", "S3"]
    r = go(w.runner.move_set_song(1, 3))
    assert [w.titles[u] for u in w.player.context] == ["S0", "S1", "S2", "S4", "S3"]


def test_during_a_night_only_songs_two_or_more_ahead_move_and_the_new_order_plays():
    w = World(n_set=6)

    async def run():
        await w.start()
        await w.run(10)                                # S0 playing
        near = await w.runner.move_set_song(1, 4)      # the next song: refused
        assert near["reason"] == "too_close"
        assert "reorder" not in w.gw.names()
        ok = await w.runner.move_set_song(4, 2)        # two ahead: allowed
        assert ok["status"] == "moved"
        assert [s.title for s in w.runner.night.set_items[:4]] == ["S0", "S1", "S4", "S2"]
        await w.run(3 * 120)
    go(run())
    assert w.played()[:4] == ["S0", "S1", "S4", "S2"]


def test_a_stale_position_is_refused():
    w = World(n_set=3)
    assert go(w.runner.move_set_song(0, 7))["reason"] == "bad_position"
