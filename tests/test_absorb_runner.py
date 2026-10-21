"""Absorb Music's runner (services/absorb.py), phase 1, driven against a fake
Spotify, a fake capture service and a fake shape disk (tests/absorb_world.py)
— the acceptance list of data/absorb-music-plan/report.md §12 phase 1:

  a queue classifies and orders correctly; a condemned capture skips ahead;
  a requeue lands after the next song; three attempts park; a committed but
  headless capture re-queues rather than counting as done; the ledger makes a
  re-run a no-op.

Plus the safety properties phase 1 owes before phase 2 exists: the shipped
guard refuses every window (nothing can play out loud), a refusal is a
recorded outcome, and someone else's music ends the window without a single
playback call."""
from __future__ import annotations

import asyncio

import pytest

from services import absorb, absorb_store
from tests.absorb_world import DEVICE, SOURCE_ID, World, uri


def _go(coro):
    return asyncio.run(coro)


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def _twenty(world: World) -> dict:
    """A 20-song playlist: 4 already captured, 8 with no shape, 8 complete
    but failing the bar with different missing heads."""
    songs = [uri(i) for i in range(20)]
    world.gw.playlists[SOURCE_ID] = list(songs)
    kinds = {}
    for i in (0, 5, 10, 15):
        world.disk.set(uri(i), "skip", head_ms=0)
        kinds[uri(i)] = "skip"
    for i in (1, 2, 6, 9, 11, 13, 17, 19):
        kinds[uri(i)] = "fresh"   # the disk's default: no shape
    heads = {3: 4000, 4: 60000, 7: 1500, 8: 20000, 12: 9000, 14: 2500, 16: 30000, 18: 1200}
    for i, h in heads.items():
        world.disk.set(uri(i), "recapture", ["headless"], head_ms=h)
        kinds[uri(i)] = "recapture"
    return kinds


# ── the shipped guard, and refusals ─────────────────────────────────────────

def test_the_shipped_guard_refuses_every_window_and_touches_nothing(tmp_path, monkeypatch):
    """Phase 1 alone must never play music out loud: until phase 2's silence
    exists, the production guard refuses before any Spotify call."""
    w = World(tmp_path, monkeypatch, guard=absorb.UnbuiltHouseGuard())
    _twenty(w)
    result = _go(w.runner.start())
    assert result["status"] == "refused"
    assert result["reason"] == "silence_unbuilt"
    assert w.gw.calls == []
    assert w.cap.force_uris == set() and w.cap.preroll_uris == set()
    stored = absorb_store.latest_run()
    assert stored.state == "refused" and stored.end_reason == "silence_unbuilt"


def test_production_deps_use_the_unbuilt_guard():
    assert isinstance(absorb.production_deps().guard, absorb.UnbuiltHouseGuard)


def test_config_ships_off():
    from models.absorb import AbsorbConfig
    cfg = AbsorbConfig()
    assert cfg.enabled is False and cfg.force_recapture is False
    assert cfg.head_max_ms == 1000 and cfg.max_attempts == 3


@pytest.mark.parametrize("setup, reason", [
    (lambda w: setattr(w, "anchors", False), "anchor_disabled"),
    (lambda w: setattr(w, "analysis", False), "analysis_disabled"),
    (lambda w: w.playing(uri(99)), "music_playing"),
    (lambda w: setattr(w, "spectra", ("night_run_active", "A night run has the room.")),
     "night_run_active"),
    (lambda w: setattr(w, "spectra", ("camera_run_active", "A camera run is in progress.")),
     "camera_run_active"),
    (lambda w: w.gw.devices.clear(), "device_unreachable"),
    (lambda w: w.gw.playlists.pop(SOURCE_ID), "playlist_unresolved"),
])
def test_each_gate_refuses_by_name_and_is_recorded(world, setup, reason):
    _twenty(world)
    setup(world)
    result = _go(world.runner.start())
    assert (result["status"], result["reason"]) == ("refused", reason)
    assert result["detail"]
    assert not world.gw.plays
    assert absorb_store.latest_run().end_reason == reason


def test_no_linked_playlist_is_refused(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, source_playlist_uri="")
    assert _go(w.runner.start())["reason"] == "no_playlist"


# ── classification, the skip pass, the order, the warm-up ───────────────────

def test_a_twenty_song_queue_is_classified_skipped_ordered_and_sent(world):
    kinds = _twenty(world)

    async def scenario():
        return await world.runner.start()

    result = _go(scenario())
    assert result["status"] == "running"
    run = world.run
    skips = [u for u, k in kinds.items() if k == "skip"]
    # the skip pass: filed, never played, Recently Captured tagged in the run
    assert run.counts.skipped == 4
    assert {e.uri for e in run.skipped} == set(skips)
    assert all(e.reason == "already_captured" for e in run.skipped)
    for u in skips:
        assert u not in world.gw.playlists[SOURCE_ID]
        assert u in world.gw.rc
    # fresh first (playlist order), then the re-captures worst head first
    fresh = [uri(i) for i in (1, 2, 6, 9, 11, 13, 17, 19)]
    rec = [uri(i) for i in (4, 16, 8, 12, 3, 14, 7, 18)]
    assert run.queue == fresh + rec
    # the warm-up is an already-captured song, played first and never forced
    assert run.warm_up_uri == uri(0)
    sent = world.last_play
    assert sent[0] == uri(0)
    assert sent[1:] == (fresh + rec)[:9]
    assert uri(0) not in world.cap.force_uris and uri(0) not in world.cap.preroll_uris
    # every fresh song in the window is vouched, no re-capture is in it yet
    assert world.cap.preroll_uris == set(fresh)
    assert world.cap.force_uris == {uri(4)}


@pytest.mark.parametrize("order, expected", [
    ("playlist", [1, 2, 3, 4, 6, 7]),
    ("worst_head_first", [1, 2, 6, 4, 3, 7]),   # fresh = whole song missing
    ("fresh_first", [1, 2, 6, 4, 3, 7]),
])
def test_queue_orders(tmp_path, monkeypatch, order, expected):
    w = World(tmp_path, monkeypatch, order=order, warm_up=False)
    w.gw.playlists[SOURCE_ID] = [uri(i) for i in (1, 2, 3, 4, 6, 7)]
    w.disk.set(uri(3), "recapture", ["headless"], head_ms=4000)
    w.disk.set(uri(4), "recapture", ["headless"], head_ms=60000)
    w.disk.set(uri(7), "recapture", ["no_librosa"], head_ms=0)
    _go(w.runner.start())
    assert w.run.queue == [uri(i) for i in expected]


def test_force_recapture_tag_disables_the_skip_pass(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, force_recapture=True, warm_up=False)
    w.gw.playlists[SOURCE_ID] = [uri(1), uri(2)]
    w.disk.set(uri(1), "skip", head_ms=0)
    _go(w.runner.start())
    assert w.run.counts.skipped == 0
    assert w.run.queue == [uri(2), uri(1)]
    assert uri(1) in w.cap.force_uris
    assert w.gw.rc == []


def test_everything_already_captured_ends_without_playing(world):
    world.gw.playlists[SOURCE_ID] = [uri(1), uri(2)]
    world.disk.set(uri(1), "skip", head_ms=0)
    world.disk.set(uri(2), "skip", head_ms=0)
    _go(world.runner.start())
    assert world.run.state == "ended" and world.run.end_reason == "nothing_to_capture"
    assert world.gw.plays == []
    assert world.gw.playlists[SOURCE_ID] == []


# ── playing, condemning, requeueing ─────────────────────────────────────────

def _start_plain(world: World, n: int = 4) -> list[str]:
    songs = [uri(i) for i in range(1, n + 1)]
    world.gw.playlists[SOURCE_ID] = list(songs)
    absorb_store.save_config(absorb_store.load_config().model_copy(update={"warm_up": False}))
    _go(world.runner.start())
    return songs


def test_a_condemned_capture_skips_ahead_and_requeues_after_the_next_song(world):
    a, b, c, d = _start_plain(world)

    async def scenario():
        await world.arrive(a)
        assert world.run.now_playing.uri == a
        await world.condemn(a, "gap")
        # skipped ahead at once: the next window starts with B, then A
        assert world.last_play[:3] == [b, a, c]
        assert world.run.queue[:3] == [b, a, c]
        await world.arrive(b)
        # A sits right after B — "requeues it after the next song"
        assert world.run.queue[:2] == [a, c]
        return world.run

    run = _go(scenario())
    assert run.counts.failed == 1 and run.counts.requeued == 1
    assert run.failed[-1].reason == "gap" and run.attempts[a] == 1


def test_a_failed_outcome_after_the_song_ended_requeues_after_the_song_now_playing(world):
    a, b, c, d = _start_plain(world)

    async def scenario():
        await world.arrive(a)
        await world.finish(a)
        world.cap.recording_uri = None
        await world.arrive(b)              # Spotify walked on to B by itself
        assert world.run.queue == [c, d]
        await world.outcome(a, "failed", "too_short")
        assert world.run.queue == [a, c, d]
        await world.finish(b)
        # Spotify would go to C (its own window); absorb wants A — it re-sends
        world.playing(c, progress_ms=800)
        await world.poll()
        assert world.last_play[0] == a
        await world.arrive(a)
        assert world.run.now_playing.uri == a and world.run.now_playing.attempt == 2

    _go(scenario())


def test_three_failed_attempts_park_the_song(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, warm_up=False)
    a, b = uri(1), uri(2)
    w.gw.playlists[SOURCE_ID] = [a, b]
    _go(w.runner.start())

    async def scenario():
        await w.arrive(a)
        await w.condemn(a, "gap")              # attempt 1 → after B
        assert w.run.queue[:2] == [b, a]
        await w.arrive(b)
        await w.condemn(b, "coverage")         # B fails too → after A
        assert w.run.queue[:2] == [a, b]
        await w.arrive(a)
        assert w.run.now_playing.attempt == 2
        await w.condemn(a, "gap")              # attempt 2
        await w.arrive(b)
        await w.condemn(b, "coverage")
        await w.arrive(a)
        assert w.run.now_playing.attempt == 3
        await w.condemn(a, "gap")              # attempt 3 → parked

    _go(scenario())
    run = w.run
    assert run.attempts[a] == 3
    assert [e.uri for e in run.parked] == [a]
    assert run.parked[0].reason == "gap"
    assert a not in run.queue and run.counts.parked == 1
    ledger = absorb_store.load_ledger()
    assert ledger.entries[a].parked and ledger.entries[a].lifetime_attempts == 3
    # a parked song is left in his playlist, named — never filed
    assert a in w.gw.playlists[SOURCE_ID] and a not in w.gw.rc


def test_a_committed_but_headless_capture_requeues_as_head_missed(world):
    a, b, c, d = _start_plain(world)

    async def scenario():
        await world.arrive(a)
        await world.finish(a)
        world.cap.recording_uri = None
        await world.arrive(b)
        # the capture COMMITTED, but the shape on disk starts 6 s in
        world.disk.set(a, "recapture", ["headless"], head_ms=6000)
        await world.outcome(a, "ok")

    _go(scenario())
    run = world.run
    assert run.counts.captured == 0
    assert run.counts.head_missed == 1 and run.counts.requeued == 1
    assert run.failed[-1].reason == "head_missed"
    assert run.queue[0] == a
    assert run.head_rate.attempted == 1 and run.head_rate.with_head == 0
    assert a in world.gw.playlists[SOURCE_ID] and a not in world.gw.rc


def test_head_missed_three_times_parks_as_head_unreachable(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, warm_up=False, max_attempts=1)
    w.gw.playlists[SOURCE_ID] = [uri(1), uri(2)]
    _go(w.runner.start())

    async def scenario():
        await w.arrive(uri(1))
        await w.finish(uri(1))
        w.cap.recording_uri = None
        await w.arrive(uri(2))
        w.disk.set(uri(1), "recapture", ["headless"], head_ms=6000)
        await w.outcome(uri(1), "ok")

    _go(scenario())
    assert w.run.parked[0].reason == "head_unreachable"


def test_a_committed_capture_with_its_head_is_filed(world):
    a, b, c, d = _start_plain(world)

    async def scenario():
        await world.arrive(a)
        await world.finish(a)
        world.cap.recording_uri = None
        await world.arrive(b)
        world.disk.set(a, "skip", head_ms=0)
        await world.outcome(a, "ok", realign={"status": "applied", "shift_ms": 420,
                                              "r": 0.91, "triggers": 7})

    _go(scenario())
    run = world.run
    assert run.counts.captured == 1 and run.captured[0].uri == a
    assert a not in world.gw.playlists[SOURCE_ID]
    assert world.gw.rc[0] == a
    assert run.head_rate.attempted == 1 and run.head_rate.with_head == 1
    assert run.realigned[0].triggers == 7 and run.realigned[0].shift_ms == 420
    f = absorb_store.load_ledger().entries[a].filing
    assert f.kind == "captured" and f.rc_added and f.source_removed and f.done_ms


def test_an_outcome_from_an_earlier_abandoned_capture_is_not_read_as_the_current_one(world):
    a, b, c, d = _start_plain(world)

    async def scenario():
        await world.arrive(a)
        old_start = world.cap.started_at[a]
        await world.condemn(a, "gap")
        await world.arrive(b)
        await world.finish(b)
        world.cap.recording_uri = None
        await world.arrive(a)                     # A's second attempt
        # the FIRST capture's finalize lands only now
        await world.outcome(a, "failed", "gap", started_at=old_start)
        assert world.run.now_playing.uri == a
        assert world.run.attempts[a] == 1

    _go(scenario())


def test_no_capture_starting_condemns_the_song(world):
    a, b, c, d = _start_plain(world)

    async def scenario():
        await world.arrive(a, capture=False)
        world.advance(absorb.CAPTURE_START_GRACE_S)
        world.playing(a, progress_ms=40_000)
        await world.poll()

    _go(scenario())
    assert world.run.failed[-1].reason == "no_capture"
    assert world.last_play[:2] == [b, a]


def test_a_governor_drain_during_the_capture_condemns_and_distrusts(world):
    a, b, c, d = _start_plain(world)

    async def scenario():
        await world.arrive(a)
        world.governor_reading = {"seq": 25, "dropped_total_ms": 14843}
        world.advance(5)
        world.playing(a, progress_ms=20_000)
        await world.poll()

    _go(scenario())
    assert world.run.failed[-1].reason == "governor_drain"
    assert "600 ms" in world.run.failed[-1].detail
    assert a in world.runner.distrust


def test_the_force_set_carries_exactly_the_windows_recaptures(world):
    world.gw.playlists[SOURCE_ID] = [uri(1), uri(2), uri(3)]
    world.disk.set(uri(2), "recapture", ["headless"], head_ms=9000)
    absorb_store.save_config(absorb_store.load_config().model_copy(
        update={"warm_up": False, "order": "playlist"}))
    world.cap.force_uris.add("spotify:track:someone-elses")
    _go(world.runner.start())
    assert world.cap.force_uris == {uri(2), "spotify:track:someone-elses"}
    assert world.cap.preroll_uris == {uri(1), uri(3)}
    _go(world.runner.stop())
    # the runner empties only what it put there
    assert world.cap.force_uris == {"spotify:track:someone-elses"}
    assert world.cap.preroll_uris == set()


# ── his own music, his pause, his presses ───────────────────────────────────

def test_his_music_ends_the_window_without_a_single_playback_call(world):
    a, b, c, d = _start_plain(world)

    async def scenario():
        await world.arrive(a)
        before = len(world.gw.writes())
        world.playing("spotify:track:hisownsong", progress_ms=1000)
        await world.poll()
        return before

    before = _go(scenario())
    assert world.run.state == "ended" and world.run.end_reason == "foreign_playback"
    assert len(world.gw.writes()) == before            # no pause, no play
    assert world.cap.force_uris == set() and world.cap.preroll_uris == set()
    assert world.run.attempts.get(a, 0) == 0            # an interruption is not an attempt


def test_playback_moving_off_serenity_ends_the_window(world):
    a, *_ = _start_plain(world)

    async def scenario():
        await world.arrive(a)
        world.playing(a, progress_ms=9000, device="Javi's phone")
        await world.poll()

    _go(scenario())
    assert world.run.end_reason == "left_device"
    assert world.gw.pauses == 0


def test_his_pause_is_not_an_attempt_and_ends_the_window_after_the_grace(world):
    a, *_ = _start_plain(world)

    async def scenario():
        await world.arrive(a)
        world.playing(a, progress_ms=30_000, is_playing=False)
        await world.poll()
        # pausing stops the capture: a too_short outcome arrives
        await world.outcome(a, "failed", "too_short")
        assert world.run.state == "running"
        assert world.run.counts.failed == 0
        world.advance(absorb.PAUSE_GRACE_S + 1)
        await world.poll()

    _go(scenario())
    assert world.run.end_reason == "paused"
    assert world.run.counts.failed == 0 and world.gw.pauses == 0


def test_skip_song_moves_on_and_requeues_without_counting_an_attempt(world):
    a, b, c, d = _start_plain(world)

    async def scenario():
        await world.arrive(a)
        return await world.runner.skip_song()

    result = _go(scenario())
    assert result["status"] == "skipped"
    assert world.last_play[:2] == [b, a]
    assert world.run.attempts.get(a, 0) == 0 and world.run.counts.failed == 0


def test_stop_pauses_and_ends(world):
    _start_plain(world)
    result = _go(world.runner.stop())
    assert result["status"] == "ended"
    assert world.run.end_reason == "stopped" and world.gw.pauses == 1
    assert _go(world.runner.stop())["status"] == "not_running"


def test_the_warm_up_song_is_played_first_and_never_counted(world):
    world.gw.playlists[SOURCE_ID] = [uri(0), uri(1), uri(2)]
    world.disk.set(uri(0), "skip", head_ms=0)
    _go(world.runner.start())

    async def scenario():
        await world.arrive(uri(0), capture=False)
        assert world.run.now_playing.mode == "warmup"
        world.advance(absorb.CAPTURE_START_GRACE_S + 5)
        world.playing(uri(0), progress_ms=60_000)
        await world.poll()                    # no capture for a warm-up is correct
        assert world.run.counts.failed == 0
        await world.finish(uri(0))
        await world.arrive(uri(1))            # Spotify walks into the first real song
        assert world.run.now_playing.uri == uri(1)
        assert world.run.now_playing.mode == "fresh"

    _go(scenario())
    assert len(world.gw.plays) == 1


# ── the queue running out ───────────────────────────────────────────────────

def test_the_window_ends_once_the_queue_is_done_and_every_outcome_landed(world):
    world.gw.playlists[SOURCE_ID] = [uri(1)]
    absorb_store.save_config(absorb_store.load_config().model_copy(update={"warm_up": False}))
    _go(world.runner.start())

    async def scenario():
        await world.arrive(uri(1))
        await world.finish(uri(1))
        world.cap.recording_uri = None
        world.playing(uri(1), progress_ms=200_000, is_playing=False)
        await world.poll()
        assert world.run.stage == "draining" and world.run.state == "running"
        assert world.gw.pauses == 1
        world.disk.set(uri(1), "skip", head_ms=0)
        await world.outcome(uri(1), "ok")

    _go(scenario())
    assert world.run.state == "ended" and world.run.end_reason == "queue_done"
    assert world.run.counts.captured == 1


def test_a_failure_while_draining_brings_the_song_back(world):
    world.gw.playlists[SOURCE_ID] = [uri(1)]
    absorb_store.save_config(absorb_store.load_config().model_copy(update={"warm_up": False}))
    _go(world.runner.start())

    async def scenario():
        await world.arrive(uri(1))
        await world.finish(uri(1))
        world.cap.recording_uri = None
        world.playing(uri(1), progress_ms=200_000, is_playing=False)
        await world.poll()
        await world.outcome(uri(1), "failed", "gap")
        await world.poll()

    _go(scenario())
    assert world.run.state == "running"
    assert world.last_play[0] == uri(1)


def test_send_window_drains_when_every_remaining_song_is_already_captured_by_send_time(
        tmp_path, monkeypatch):
    """A race, not the common empty-queue path: between the queue build and
    this particular send, EVERY song still in the window gets captured out
    of band (his own listening on another device). `_send_window` then has
    nothing left to send and must drain exactly as a genuinely empty queue
    would — never leave the run "running" with nothing driving it forward.
    `max_attempts=1` parks A outright (rather than requeuing it) so B is
    the only thing left in the queue for this send."""
    w = World(tmp_path, monkeypatch, warm_up=False, max_attempts=1)
    a, b = uri(1), uri(2)
    w.gw.playlists[SOURCE_ID] = [a, b]
    _go(w.runner.start())

    async def scenario():
        await w.arrive(a)
        # B passes the bar out of band before absorb ever gets to send it
        w.disk.set(b, "skip", head_ms=0)
        await w.condemn(a, "gap")

    _go(scenario())
    assert w.run.state == "ended" and w.run.end_reason == "queue_done"
    assert w.run.queue == [] and w.run.now_playing is None
    assert any(e.uri == b and e.reason == "captured_meanwhile" for e in w.run.skipped)
    assert w.run.parked[0].uri == a


# ── his playlist edits mid-run (D6) ─────────────────────────────────────────

def test_songs_he_adds_join_the_end_and_songs_he_removes_leave(world):
    a, b, c, d = _start_plain(world)
    world.disk.set(uri(9), "skip", head_ms=0)

    async def scenario():
        await world.arrive(a)
        pl = world.gw.playlists[SOURCE_ID]
        pl.remove(c)
        pl.extend([uri(7), uri(9)])
        world.gw._bump(SOURCE_ID)
        await world.finish(a)
        world.cap.recording_uri = None
        await world.arrive(b)

    _go(scenario())
    run = world.run
    assert c not in run.queue
    assert run.queue[-1] == uri(7)
    assert uri(9) not in run.queue and uri(9) in world.gw.rc   # already captured: filed
    assert any(e.uri == uri(9) for e in run.skipped)


# ── idempotence: the ledger ─────────────────────────────────────────────────

def test_the_ledger_makes_a_re_run_a_no_op(world):
    world.gw.playlists[SOURCE_ID] = [uri(1), uri(2), uri(3)]
    for i in (1, 2, 3):
        world.disk.set(uri(i), "skip", head_ms=0)
    world.gw.fail_remove_from.add(SOURCE_ID)      # the first run's removal fails
    _go(world.runner.start())
    assert sorted(world.gw.rc) == [uri(1), uri(2), uri(3)]
    assert world.gw.playlists[SOURCE_ID] == [uri(1), uri(2), uri(3)]
    adds_before = sum(1 for c in world.gw.calls if c[0] == "add_tracks_top")

    # run two: only the missing step is retried — no second add to Recently Captured
    world.gw.fail_remove_from.clear()
    _go(world.runner.start())
    assert sum(1 for c in world.gw.calls if c[0] == "add_tracks_top") == adds_before
    assert world.gw.playlists[SOURCE_ID] == []
    assert sorted(world.gw.rc) == [uri(1), uri(2), uri(3)]

    # run three: nothing left to do, nothing written
    writes = len(world.gw.writes())
    _go(world.runner.start())
    assert len(world.gw.writes()) == writes
    assert world.run.end_reason == "nothing_to_capture"


def test_a_song_filed_twice_is_moved_to_the_top_never_duplicated(world):
    world.gw.playlists[SOURCE_ID] = [uri(1)]
    world.disk.set(uri(1), "skip", head_ms=0)
    _go(world.runner.start())
    world.gw.playlists["RECENTLYCAPTURED001"].append(uri(5))
    # he puts the song back into the work playlist later; it is filed again
    world.gw.playlists[SOURCE_ID] = [uri(1)]
    _go(world.runner.start())
    rc = world.gw.rc
    assert rc.count(uri(1)) == 1 and rc[0] == uri(1)


def test_recently_captured_is_trimmed_from_the_bottom(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, recently_captured_max=3, warm_up=False)
    w.gw.playlists[SOURCE_ID] = [uri(i) for i in range(6)]
    for i in range(6):
        w.disk.set(uri(i), "skip", head_ms=0)
    _go(w.runner.start())
    assert len(w.gw.rc) == 3


def test_skipped_songs_stay_out_of_recently_captured_when_he_says_so(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, recently_captured_includes_skipped=False)
    w.gw.playlists[SOURCE_ID] = [uri(1)]
    w.disk.set(uri(1), "skip", head_ms=0)
    _go(w.runner.start())
    assert w.gw.rc == [] and w.gw.playlists[SOURCE_ID] == []
    assert absorb_store.load_ledger().entries[uri(1)].filing.done_ms


def test_a_parked_song_is_left_out_until_he_retries_it(world):
    world.gw.playlists[SOURCE_ID] = [uri(1), uri(2)]
    ledger = absorb_store.load_ledger()
    from models.absorb import LedgerEntry
    ledger.entries[uri(1)] = LedgerEntry(uri=uri(1), parked=True, parked_reason="gap")
    absorb_store.save_ledger(ledger)
    absorb_store.save_config(absorb_store.load_config().model_copy(update={"warm_up": False}))
    _go(world.runner.start())
    assert world.run.queue == [uri(2)]
    _go(world.runner.stop())
    assert _go(absorb.unpark(uri(1))) is True
    assert _go(absorb.unpark(uri(1))) is False
    _go(world.runner.start())
    assert uri(1) in world.run.queue


# ── concurrent ledger writes (one in-memory ledger, persisted off the loop) ─

def test_a_failure_resolved_mid_filing_keeps_both_the_filing_flags_and_the_attempt_increment(
        tmp_path, monkeypatch):
    """`_file_locked` loads the ledger, awaits several Spotify calls, then
    saves; `_resolve_failure` can load, mutate and save the SAME ledger
    while that filing is still in flight. Before the runner held ONE
    in-memory ledger for the whole run, whichever of the two saved LAST
    would silently discard the other's write (here: B's filing flags, or
    A's failure/attempt count) — a lost update, not a crash, so nothing
    but reading the file back afterward would ever catch it."""
    w = World(tmp_path, monkeypatch, warm_up=False)
    a, b = uri(1), uri(2)
    w.gw.playlists[SOURCE_ID] = [a, b]

    paused = asyncio.Event()
    resume = asyncio.Event()

    async def gating_to_thread(fn, *args):
        if getattr(fn, "__name__", "") == "find_or_create_playlist":
            paused.set()
            await resume.wait()
        return fn(*args)

    w.deps.to_thread = gating_to_thread

    spawned: list[asyncio.Task] = []
    real_spawn = w.runner._spawn

    def recording_spawn(coro):
        task = real_spawn(coro)
        if task is not None:
            spawned.append(task)
        return task

    monkeypatch.setattr(w.runner, "_spawn", recording_spawn)

    async def scenario():
        await w.runner.start()
        await w.arrive(a)
        # B's filing starts as a background task (the same shape a
        # committed capture's own `self._spawn(self._file(...))` takes) and
        # pauses mid-flight, right at its Spotify call.
        w.runner._spawn(w.runner._file([b], "skipped"))
        await paused.wait()
        stuck = next(t for t in spawned if not t.done())
        # while B's filing is still mid-Spotify-call, A's capture fails
        w.cap.condemn(a, "gap")
        while True:
            pending = [t for t in w.runner._tasks if t is not stuck and not t.done()]
            if not pending:
                break
            await asyncio.gather(*pending, return_exceptions=True)
        resume.set()
        await w.runner.settle()

    _go(scenario())

    ledger = absorb_store.load_ledger()
    assert ledger.entries[b].filing.rc_added and ledger.entries[b].filing.source_removed
    assert ledger.entries[b].filing.done_ms
    assert ledger.entries[a].lifetime_attempts == 1
    assert ledger.entries[a].last_failure == "gap"


def test_unpark_mid_run_survives_a_later_ledger_persist(world):
    """Retry (`unpark`) mid-run must mutate the SAME in-memory ledger this
    run holds — a direct disk edit would be invisible to a run that never
    reloads its ledger from disk, and the run's own very next ledger-
    mutating persist (here: a different song's failure) would silently
    revert it, since that persist writes the whole (stale) in-memory
    ledger back over whatever `unpark` wrote underneath it."""
    a, b = uri(1), uri(2)
    world.gw.playlists[SOURCE_ID] = [a, b]
    ledger = absorb_store.load_ledger()
    from models.absorb import LedgerEntry
    ledger.entries[b] = LedgerEntry(uri=b, parked=True, parked_reason="gap")
    absorb_store.save_ledger(ledger)
    absorb_store.save_config(absorb_store.load_config().model_copy(update={"warm_up": False}))
    _go(world.runner.start())
    assert world.run.queue == [a]      # B starts out parked, left out

    async def scenario():
        assert await world.runner.unpark(b) is True
        # a DIFFERENT song's failure now persists the (shared) ledger
        await world.arrive(a)
        await world.condemn(a, "gap")

    _go(scenario())

    on_disk = absorb_store.load_ledger()
    assert on_disk.entries[b].parked is False
    assert on_disk.entries[a].lifetime_attempts == 1


def test_unpark_mid_run_requeues_right_after_the_next_song_and_a_reconcile_never_duplicates_it(
        world):
    """A mid-run Retry must actually re-enter the active queue during THIS
    run, not wait on `_reconcile` (which can never see it: unparking never
    touches the Spotify playlist, and the URI is already known via
    `self.source_uris` regardless). It lands at the requeue position —
    right after the song at the head of the queue — and a later reconcile
    (triggered by an unrelated playlist edit) must never add it a second
    time nor drop it."""
    a, b, c = uri(1), uri(2), uri(3)
    world.gw.playlists[SOURCE_ID] = [a, b, c]
    ledger = absorb_store.load_ledger()
    from models.absorb import LedgerEntry
    ledger.entries[c] = LedgerEntry(uri=c, parked=True, parked_reason="gap")
    absorb_store.save_ledger(ledger)
    absorb_store.save_config(absorb_store.load_config().model_copy(update={"warm_up": False}))
    _go(world.runner.start())
    assert world.run.queue == [a, b]       # C starts out parked, left out

    async def scenario():
        await world.arrive(a)
        assert await world.runner.unpark(c) is True
        assert world.run.queue[:2] == [b, c]      # right after the head of the queue
        # an unrelated playlist edit now triggers a reconcile
        world.gw.playlists[SOURCE_ID].append(uri(9))
        world.gw._bump(SOURCE_ID)
        await world.finish(a)
        world.cap.recording_uri = None
        await world.arrive(b)

    _go(scenario())
    run = world.run
    assert run.queue.count(c) == 1 and c in run.queue


def test_unpark_mid_run_requeues_even_while_the_condemned_attempt_still_awaits_its_outcome(
        tmp_path, monkeypatch):
    """A song parked through the live condemn path (a mid-song detector
    reaching `max_attempts`) still sits in `self.awaiting` — `_resolve_
    failure` never removes it; only the real outcome report (or the 300s
    sweep) does. Retrying it before that report ever arrives must still
    requeue it right away: a RESOLVED (condemned) attempt sitting in
    `self.awaiting` is not "still being captured"."""
    w = World(tmp_path, monkeypatch, warm_up=False, max_attempts=1)
    a, b = uri(1), uri(2)
    w.gw.playlists[SOURCE_ID] = [a, b]
    _go(w.runner.start())

    async def scenario():
        await w.arrive(a)
        await w.condemn(a, "gap")          # one attempt → parked at the cap
        assert a in (e.uri for e in w.run.parked)
        assert a in w.runner.awaiting      # its outcome report never arrived
        assert await w.runner.unpark(a) is True
        assert a in w.run.queue

    _go(scenario())


def test_run_file_write_drops_a_stale_generation_behind_a_newer_save(tmp_path, monkeypatch):
    """A synchronous `save_run` (`_refuse`/`recover_orphaned_run`'s own
    call shape) can land while an earlier-prepared, async off-loop write
    is still in flight. The earlier write must never clobber the later
    one just because its own `os.replace()` happens to run last."""
    monkeypatch.setattr(absorb_store, "RUN_FILE", tmp_path / "absorb_run.json")
    from models.absorb import AbsorbRun
    old_run = AbsorbRun(id="r1", state="running")
    gen_old, data_old = absorb_store.prepare_run_write(old_run)
    new_run = AbsorbRun(id="r1", state="ended", end_reason="stopped")
    absorb_store.save_run(new_run)                       # the newer save lands first
    absorb_store.write_run_file(gen_old, data_old)        # the stale write arrives last
    stored = absorb_store.latest_run()
    assert stored.state == "ended" and stored.end_reason == "stopped"


# ── recovery, config, brief ─────────────────────────────────────────────────

def test_a_run_left_open_by_a_dead_process_is_stamped_ended(world):
    _start_plain(world)
    assert absorb_store.latest_run().state == "running"
    assert absorb.recover_orphaned_run() == world.run.id
    stored = absorb_store.latest_run()
    assert stored.state == "ended" and stored.end_reason == "process_restarted"
    assert absorb.recover_orphaned_run() is None


def test_config_patch_is_partial_and_refuses_unknown_keys(world):
    cfg = absorb.apply_config_patch({"max_attempts": 5})
    assert cfg.max_attempts == 5 and cfg.source_playlist_uri.endswith(SOURCE_ID)
    with pytest.raises(ValueError):
        absorb.apply_config_patch({"max_atempts": 5})
    with pytest.raises(Exception):
        absorb.apply_config_patch({"max_attempts": 0})
    assert absorb_store.load_config().max_attempts == 5


def test_brief_is_small_and_flat(world):
    _start_plain(world)
    b = absorb.brief(world.run)
    assert b["state"] == "running" and b["queue_len"] == 4
    assert set(b["counts"]) == {"captured", "failed", "requeued", "skipped", "parked",
                                "head_missed"}
    assert absorb.brief(None) == {"state": "idle"}


def test_a_new_run_moves_the_last_one_into_the_compact_history(world):
    _start_plain(world)
    first = world.run.id
    _go(world.runner.stop())
    _go(world.runner.start())
    assert absorb_store.latest_run().id == world.run.id != first
    earlier = absorb_store.earlier_runs()
    assert earlier[0]["id"] == first and earlier[0]["end_reason"] == "stopped"
    assert "skipped" not in earlier[0] and "log" not in earlier[0]   # compact


def test_the_websocket_brief_never_reads_the_disk(world, monkeypatch):
    _start_plain(world)
    monkeypatch.setattr(absorb, "runner", world.runner)

    def boom():
        raise AssertionError("status_brief read the run file")

    monkeypatch.setattr(absorb_store, "latest_run", boom)
    assert absorb.status_brief()["state"] == "running"


def test_a_failure_inside_the_poll_hook_never_reaches_the_poller(world, monkeypatch):
    _start_plain(world)

    def boom():
        raise OSError("disk full")

    monkeypatch.setattr(world.runner, "_sweep_outcomes", boom)
    world.playing(uri(1))
    _go(world.runner.on_track_state(world.track))      # must not raise
