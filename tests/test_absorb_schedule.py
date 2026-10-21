"""Absorb Music phase 3 — the schedule and the clean close (services/
absorb_schedule.py, and the window's end in services/absorb.py), driven
through the REAL runner and the REAL house guard against the fake house
(tests/test_absorb_silence.py's snapserver + Home Assistant + volume
automation) and a controllable clock in HOUSE time. Nothing here touches
the network, the house, Spotify or his storage.

Report §12 phase 3's acceptance, each its own test below:
  - a window that opens, runs, and closes with the volume back at its exact
    pre-window value;
  - a window killed mid-run whose next process restores before anything
    else;
  - a refusal recorded with its reason.
And the firstmate's own bar: nothing opens unless he configured a window —
the shipped config is proven to open nothing across a whole week.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.absorb import AbsorbConfig, AbsorbWindow
from routers import absorb_router
from services import absorb, absorb_schedule, absorb_silence, absorb_store
from tests.absorb_world import SOURCE_ID, World, uri
from tests.test_absorb_silence import FakeHouse, make_guard

TZ = ZoneInfo("America/New_York")
HIS_SONG = "spotify:track:hisownsong"


def _go(coro):
    return asyncio.run(coro)


def at(y: int, mo: int, d: int, h: int, mi: int, s: int = 0) -> float:
    """Epoch seconds of a wall-clock moment in HOUSE time."""
    return datetime(y, mo, d, h, mi, s, tzinfo=TZ).timestamp()


def ms(t: float) -> int:
    return int(t * 1000)


# 2026-10-19 is a Monday.
MON_2129 = at(2026, 10, 19, 21, 29)
MON_2130 = at(2026, 10, 19, 21, 30)
MON_2330 = at(2026, 10, 19, 23, 30)


# ── the world ────────────────────────────────────────────────────────────────

def _world(tmp_path, monkeypatch, house: FakeHouse, *, volume: float = 37.0,
           **patch) -> World:
    w = World(tmp_path, monkeypatch, warm_up=False)
    w.house = house
    house.snap_volume = volume
    house.fan_out(volume)
    w.guard = make_guard(w, house, tmp_path)
    w.gw.playlists[SOURCE_ID] = [uri(i) for i in range(1, 7)]
    real_pause = w.gw.pause

    def pause(device_id):
        house.events.append(("pause",))
        real_pause(device_id)

    w.gw.pause = pause
    if patch:
        absorb.apply_config_patch(patch)
    w.sched = absorb_schedule.Scheduler()
    w.clock[0] = MON_2129
    return w


EVENING = {"enabled": True,
           "windows": [{"days": ["mon"], "start": "21:30", "end": "23:30"}]}


@pytest.fixture
def house():
    return FakeHouse()


@pytest.fixture
def record_spy(monkeypatch, house):
    """Every run-record write, in the house's own event order."""
    real = absorb_store.write_run_file

    def spy(gen, data):
        run = data.get("run") or {}
        house.events.append(("record", run.get("state"), run.get("stage")))
        real(gen, data)

    monkeypatch.setattr(absorb_store, "write_run_file", spy)


def step(w: World, sched: Optional[absorb_schedule.Scheduler] = None) -> None:
    """One supervisor step — the runner, then the schedule — exactly as
    main.py's lifespan task runs it."""
    async def go():
        await absorb.supervise_once(w.runner, sched or w.sched)
        await w.runner.settle()
    _go(go())


def at_time(w: World, t: float, sched=None) -> None:
    w.clock[0] = t
    step(w, sched)


def outcomes(limit: int = 60) -> list[dict]:
    return [o.model_dump() for o in absorb_store.load_schedule().outcomes[:limit]]


def _quiet(w: World, minutes: float, step_s: float = 30) -> None:
    async def go():
        t = 0.0
        while t < minutes * 60:
            w.advance(step_s)
            t += step_s
            w.poll_ok = True
            w.playing(None)
            await w.poll()
    _go(go())


def _his_music(w: World) -> None:
    w.playing(HIS_SONG, progress_ms=1000)


def _opened(w: World) -> list[str]:
    """Open at Monday 21:30 and capture the first song; the second is then
    playing, its capture running. Returns [first, second]."""
    at_time(w, MON_2130 + 5)
    assert w.run is not None and w.run.state == "running", (w.run and w.run.end_detail)
    a, b = w.run.queue[0], w.run.queue[1]

    async def go():
        await w.arrive(a)
        await w.finish(a)
        w.disk.set(a, "skip", head_ms=0)
        await w.arrive(b)
        await w.outcome(a, "ok")
    _go(go())
    assert w.run.counts.captured == 1 and w.run.now_playing.uri == b
    return [a, b]


# ═══ 1. house time ══════════════════════════════════════════════════════════

def test_an_evening_window_runs_monday_night_into_tuesday_in_house_time():
    windows = [AbsorbWindow(days=["mon"], start="21:30", end="00:30")]
    occ = absorb_schedule.open_occurrences(windows, ms(at(2026, 10, 19, 23, 0)))
    assert len(occ) == 1
    assert occ[0].start_ms == ms(MON_2130)
    assert occ[0].end_ms == ms(at(2026, 10, 20, 0, 30))
    assert occ[0].label == "Mon 21:30–00:30"
    # Tuesday 00:15 still belongs to MONDAY's window — days name the start
    assert absorb_schedule.open_occurrences(windows, ms(at(2026, 10, 20, 0, 15)))
    assert not absorb_schedule.open_occurrences(windows, ms(at(2026, 10, 20, 0, 30)))
    assert not absorb_schedule.open_occurrences(windows, ms(at(2026, 10, 20, 21, 45)))
    nxt = absorb_schedule.next_occurrence(windows, ms(at(2026, 10, 20, 1, 0)))
    assert nxt.start_ms == ms(at(2026, 10, 26, 21, 30))


def test_a_window_is_wall_clock_across_both_dst_changes():
    """Never a fixed number of seconds: the night the clocks fall back is an
    hour longer, the night they spring forward an hour shorter, and both
    still end at 05:30 on his wall."""
    sat = [AbsorbWindow(days=["sat"], start="23:00", end="05:30")]
    fall = absorb_schedule.open_occurrences(sat, ms(at(2026, 10, 31, 23, 30)))[0]
    assert fall.end_ms == ms(at(2026, 11, 1, 5, 30))
    assert fall.end_ms - fall.start_ms == int(7.5 * 3_600_000)
    spring = absorb_schedule.open_occurrences(sat, ms(at(2026, 3, 7, 23, 30)))[0]
    assert spring.end_ms == ms(at(2026, 3, 8, 5, 30))
    assert spring.end_ms - spring.start_ms == int(5.5 * 3_600_000)


def test_a_window_that_could_never_open_is_refused_by_name():
    with pytest.raises(ValueError, match="starts and ends at 21:30"):
        absorb.apply_config_patch(
            {"windows": [{"days": ["mon"], "start": "21:30", "end": "21:30"}]})
    with pytest.raises(ValueError, match="has no days"):
        absorb.apply_config_patch({"windows": [{"days": [], "start": "21:30", "end": "23:00"}]})
    assert absorb_store.load_config().windows == []
    assert absorb_schedule.open_occurrences(
        [AbsorbWindow(days=["mon"], start="21:30", end="21:30")], ms(MON_2130 + 60)) == []


# ═══ 2. nothing opens unless he configured it ══════════════════════════════

def test_absorb_ships_off_with_no_windows():
    cfg = AbsorbConfig()
    assert cfg.enabled is False and cfg.windows == []


@pytest.mark.parametrize("patch", [
    {},                                                                      # as shipped
    {"windows": [{"days": list(absorb_schedule.DAYS), "start": "00:00",
                  "end": "23:59"}]},                                        # a window, switched off
    {"enabled": True},                                                       # switched on, no window
], ids=["shipped", "window-but-off", "on-but-no-window"])
def test_a_whole_week_of_ticks_opens_nothing_unless_both_are_set(
        tmp_path, monkeypatch, house, patch):
    w = _world(tmp_path, monkeypatch, house, **patch)
    house.events.clear()
    t = at(2026, 10, 19, 0, 0)
    for _ in range(7 * 24 * 6):                    # every 10 minutes for a week
        at_time(w, t)
        t += 600
    assert w.runner.run is None
    assert w.gw.calls == [], "Spotify was touched with no window configured"
    assert house.events == [], "the house was touched with no window configured"
    assert absorb_store.load_schedule().outcomes == []
    assert absorb_store.latest_run() is None


# ═══ 3. a window that opens, runs, and closes ═══════════════════════════════

def test_a_scheduled_window_opens_runs_and_closes_with_the_volume_back_exactly(
        tmp_path, monkeypatch, house, record_spy):
    """Report §12 phase 3, acceptance 1, in the close order the report
    makes the semantics: stop the queue → pause playback → let the in-flight
    capture finalize → restore and read back → lift the stand-down → write
    the record."""
    w = _world(tmp_path, monkeypatch, house, overrun_grace_min=0, **EVENING)
    # Real Home Assistant writes suspend; the fake's don't. Yield here so a
    # record write already queued would land mid-restore, as it would live.
    audio = w.guard.d.audio
    real_set = audio.set_volume

    async def set_volume(volume):
        await asyncio.sleep(0)
        return await real_set(volume)

    audio.set_volume = set_volume
    at_time(w, MON_2129 + 30)
    assert w.runner.run is None, "opened before its time"
    a, b = _opened(w)
    run = w.run
    assert run.started_by == "schedule" and run.opened_ms
    assert run.window["end"] == ms(MON_2330) and run.window["label"] == "Mon 21:30–23:30"
    assert absorb.brief(run)["window"]["end"] == ms(MON_2330)
    assert house.snap_volume == 0 and house.audible_rooms() == []
    assert outcomes()[0]["outcome"] == "opened"

    house.events.clear()
    at_time(w, MON_2330)
    # paused, the capture of the song playing still finalizing: the house
    # stays silent and the lights held while it does
    assert ("pause",) in house.events
    assert run.stage == "closing" and run.state == "running"
    assert house.snap_volume == 0 and run.lights_held is True
    assert not any(e[0] == "ha.set_volume" for e in house.events)

    _go(w.outcome(b, "failed", "too_short"))
    assert run.state == "ended" and run.end_reason == "window_closed"
    assert house.snap_volume == 37.0, "the volume is not back at its pre-window value"
    assert house.clients["eh"]["percent"] == 100 and house.clients["eh"]["muted"] is False
    assert house.audible_rooms() != []
    assert run.lights_held is False and absorb.brief(run)["lights_held"] is False
    assert absorb_silence.load_snapshot() is None
    assert run.restore["ok"] is True
    # the abandoned song was absorb's choice, not a failed capture
    assert run.counts.failed == 0 and b not in run.attempts and run.counts.captured == 1

    kinds = [e for e in house.events if e[0] in ("pause", "ha.set_volume", "announce", "record")]
    pause_i = kinds.index(("pause",))
    restore_i = next(i for i, e in enumerate(kinds) if e[0] == "ha.set_volume")
    lift_i = kinds.index(("announce", False))
    ended_i = next(i for i, e in enumerate(kinds) if e[0] == "record" and e[1] == "ended")
    assert pause_i < restore_i < lift_i < ended_i, kinds
    assert kinds[restore_i][1] == 37
    assert absorb_store.latest_run().state == "ended"


def test_a_capture_that_never_reports_cannot_hold_the_house_silent(
        tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, overrun_grace_min=0, **EVENING)
    a, b = _opened(w)
    at_time(w, MON_2330)
    w.advance(absorb.CLOSE_FINALIZE_WAIT_S - 5)
    step(w)
    assert house.snap_volume == 0 and w.run.state == "running"
    w.advance(10)
    step(w)
    assert w.run.state == "ended" and house.snap_volume == 37.0
    assert any("recorded when it lands" in line for line in w.run.log)


def test_a_song_ending_inside_the_grace_is_finished_and_captured(tmp_path, monkeypatch, house):
    """D7: a song mid-capture at the window's end that will END within
    `overrun_grace_min` is finished, then the window closes; the next song
    Spotify moves on to is paused at once and never counted."""
    w = _world(tmp_path, monkeypatch, house, **EVENING)
    a, b = _opened(w)
    c = w.run.queue[0]
    house.events.clear()
    at_time(w, MON_2330)
    assert w.run.stage == "finishing" and ("pause",) not in house.events
    assert house.snap_volume == 0

    async def go():
        w.advance(180)
        await w.finish(b)
        w.disk.set(b, "skip", head_ms=0)
        w.playing(c, progress_ms=1000)          # Spotify carries on with the next one
        await w.poll()
    _go(go())
    assert ("pause",) in house.events and w.run.stage == "closing"
    assert c not in w.run.attempts and w.run.now_playing is None
    assert house.snap_volume == 0, "restored before the finished song's capture finalized"

    _go(w.outcome(b, "ok"))
    run = w.run
    assert run.state == "ended" and run.end_reason == "window_closed"
    assert run.counts.captured == 2 and b in [e.uri for e in run.captured]
    assert house.snap_volume == 37.0 and run.lights_held is False


def test_a_song_that_overruns_the_grace_is_abandoned(tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, overrun_grace_min=5, **EVENING)
    a, b = _opened(w)
    at_time(w, MON_2330)
    assert w.run.stage == "finishing"
    finish_in = (200_000 - w.runner.np_progress_ms) / 1000
    w.advance(finish_in + absorb.FINISH_SLACK_S + 1)        # the song never ends
    step(w)
    assert w.run.stage == "closing" and w.gw.pauses >= 1
    _go(w.outcome(b, "failed", "too_short"))
    assert w.run.state == "ended" and house.snap_volume == 37.0
    assert w.run.counts.failed == 0


def test_his_music_during_the_close_gets_the_volume_back_at_once(tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, overrun_grace_min=0, **EVENING)
    a, b = _opened(w)
    at_time(w, MON_2330)
    assert w.run.stage == "closing" and house.snap_volume == 0
    pauses = w.gw.pauses
    _his_music(w)
    _go(w.poll())
    assert house.snap_volume == 37.0, "he pressed play into a silent house and stayed there"
    assert w.run.state == "ended" and w.run.end_reason == "window_closed"
    assert w.gw.pauses == pauses, "absorb paused his music"


# ═══ 4. his music at the window's start ═════════════════════════════════════

def test_a_window_that_finds_him_listening_waits_and_never_touches_the_house(
        tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, **EVENING)
    house.events.clear()
    _his_music(w)
    at_time(w, MON_2130 + 5)
    run = w.run
    assert run.state == "paused" and run.stage == "waiting" and run.opened_ms == 0
    assert run.wait_reason == "music_playing"
    assert outcomes()[0]["outcome"] == "waiting"
    t = MON_2130 + 15
    while t < MON_2330:                            # his music never stops
        w.clock[0] = t
        _his_music(w)
        _go(w.poll())
        step(w)
        t += 300
    at_time(w, MON_2330)
    assert run.state == "ended" and run.end_reason == "window_closed"
    assert "never started" in run.end_detail
    evening = absorb_schedule.status(now_ms=ms(MON_2330 + 60))["outcomes"][0]
    assert evening["outcome"] == "waiting" and evening["run"]["end_reason"] == "window_closed"
    assert evening["run"]["opened_ms"] == 0
    assert w.gw.writes() == [], "absorb touched his playback"
    assert house.events == [], "the house was touched while he listened"


def test_it_opens_after_twenty_minutes_of_quiet_and_that_is_not_a_resume(
        tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, **EVENING)
    _his_music(w)
    at_time(w, MON_2130 + 5)
    assert w.run.stage == "waiting"
    _quiet(w, 19)
    assert w.run.state == "paused" and house.snap_volume == 37.0
    _quiet(w, 1.5)
    run = w.run
    assert run.state == "running" and run.opened_ms and run.resumes == 0
    assert run.wait_reason == ""
    assert house.snap_volume == 0 and house.audible_rooms() == []
    assert w.gw.plays and run.queue, "the queue was never built"
    # and the window still closes at its own time
    at_time(w, MON_2330)
    assert run.stage in ("closing", "finishing") or run.state == "ended"


def test_switching_the_schedule_off_while_it_waits_ends_it(tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, **EVENING)
    _his_music(w)
    at_time(w, MON_2130 + 5)
    absorb.apply_config_patch({"enabled": False})
    _quiet(w, 21)
    assert w.run.state == "ended" and w.run.end_reason == "schedule_off"
    assert house.snap_volume == 37.0 and not w.gw.plays


# ═══ 5. a refusal is a recorded outcome ═════════════════════════════════════

def test_a_refusal_is_recorded_with_its_reason_and_tried_again_next_time(
        tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, **EVENING)
    w.anchors = False
    at_time(w, MON_2130 + 5)
    run = absorb_store.latest_run()
    assert run.state == "refused" and run.end_reason == "anchor_disabled"
    assert run.started_by == "schedule" and "Anchor detection" in run.end_detail
    o = outcomes()
    assert len(o) == 1 and o[0]["outcome"] == "refused" and o[0]["reason"] == "anchor_disabled"
    assert "Anchor detection" in o[0]["detail"] and o[0]["run_id"] == run.id
    assert house.events == []
    joined = absorb_schedule.status(now_ms=ms(MON_2130 + 10))["outcomes"][0]["run"]
    assert joined["state"] == "refused" and joined["end_reason"] == "anchor_disabled"
    # final for tonight: the rest of the window doesn't retry it every tick
    for k in range(1, 20):
        at_time(w, MON_2130 + 5 + 300 * k)
    assert len(outcomes()) == 1 and absorb_store.latest_run().id == run.id
    # next Monday tries again
    w.anchors = True
    at_time(w, at(2026, 10, 26, 21, 30, 5))
    assert outcomes()[0]["outcome"] == "opened" and len(outcomes()) == 2
    assert w.run.state == "running"


def test_his_stop_is_never_undone_by_the_schedule(tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, **EVENING)
    at_time(w, MON_2130 + 5)
    run_id = w.run.id
    _go(w.runner.stop())
    for k in range(1, 10):
        at_time(w, MON_2130 + 5 + 120 * k)
    assert w.run.id == run_id and w.run.end_reason == "stopped"
    assert house.snap_volume == 37.0


def test_late_is_fine_too_late_is_not(tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, **EVENING)
    at_time(w, at(2026, 10, 19, 21, 50))           # SpotFX was down at 21:30
    assert w.run.state == "running"
    assert outcomes()[0]["detail"] == "opened 20 min after 21:30"
    _go(w.runner.stop())

    absorb.apply_config_patch({"windows": [{"days": ["tue"], "start": "21:30",
                                            "end": "22:00"}]})
    at_time(w, at(2026, 10, 20, 21, 45))           # 15 min left, under the 20 it needs
    assert outcomes()[0]["outcome"] == "too_late"
    assert w.run.end_reason == "stopped", "a window opened with too little of it left"


# ═══ 6. the end follows his windows ═════════════════════════════════════════

def test_an_edit_to_tonights_end_moves_the_close(tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, overrun_grace_min=0, **EVENING)
    at_time(w, MON_2130 + 5)
    absorb.apply_config_patch({"windows": [{"days": ["mon"], "start": "21:30",
                                            "end": "22:30"}]})
    at_time(w, at(2026, 10, 19, 22, 0))
    assert w.run.window["end"] == ms(at(2026, 10, 19, 22, 30))
    at_time(w, at(2026, 10, 19, 22, 30))
    assert w.run.state == "ended" and w.run.end_reason == "window_closed"
    assert house.snap_volume == 37.0


def test_an_overlapping_window_joins_the_open_one(tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, enabled=True, windows=[
        {"days": ["mon"], "start": "21:30", "end": "22:30"},
        {"days": ["mon"], "start": "22:00", "end": "23:30"}])
    at_time(w, MON_2130 + 5)
    run_id = w.run.id
    at_time(w, at(2026, 10, 19, 22, 0, 5))
    assert outcomes()[0]["outcome"] == "joined"
    assert w.run.id == run_id and w.run.window["end"] == ms(MON_2330)
    at_time(w, at(2026, 10, 19, 22, 30, 5))
    assert w.run.state == "running", "it closed at the first window's end"


def test_back_to_back_windows_are_one_silence(tmp_path, monkeypatch, house):
    """A window starting exactly as the open one ends carries it on: never
    a restore and a re-silence a second apart."""
    w = _world(tmp_path, monkeypatch, house, enabled=True, windows=[
        {"days": ["mon"], "start": "21:30", "end": "22:30"},
        {"days": ["mon"], "start": "22:30", "end": "23:30"}])
    at_time(w, MON_2130 + 5)
    run_id = w.run.id
    house.events.clear()
    for t in range(int(at(2026, 10, 19, 22, 29)), int(at(2026, 10, 19, 22, 31)), 10):
        at_time(w, t)
    assert w.run.id == run_id and w.run.state == "running"
    assert w.run.window["end"] == ms(MON_2330)
    assert not [e for e in house.events if e[0] == "ha.set_volume"], house.events
    assert outcomes()[0]["outcome"] == "joined"


def test_a_window_due_while_the_last_one_is_closing_opens_after_it(tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, overrun_grace_min=0, enabled=True, windows=[
        {"days": ["mon"], "start": "21:30", "end": "22:30"},
        {"days": ["mon"], "start": "22:31", "end": "23:30"}])
    a, b = _opened(w)
    at_time(w, at(2026, 10, 19, 22, 30))
    assert w.run.stage == "closing"
    first = w.run.id
    at_time(w, at(2026, 10, 19, 22, 31, 5))          # due, but the last one is closing
    assert w.run.id == first and not w.sched.fired(ms(at(2026, 10, 19, 22, 31)))
    assert outcomes()[0]["outcome"] == "opened" and len(outcomes()) == 1
    _go(w.outcome(b, "failed", "too_short"))
    assert w.run.state == "ended" and house.snap_volume == 37.0
    w.playing(b, progress_ms=60_000, is_playing=False)   # the poller has seen the pause
    at_time(w, at(2026, 10, 19, 22, 31, 20))
    assert w.run.id != first and w.run.state == "running"
    assert w.run.window["label"] == "Mon 22:31–23:30" and house.snap_volume == 0


def test_moving_tonights_end_into_the_past_closes_it_now(tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, overrun_grace_min=0, **EVENING)
    at_time(w, MON_2130 + 5)
    at_time(w, at(2026, 10, 19, 22, 40))
    absorb.apply_config_patch({"windows": [{"days": ["mon"], "start": "21:30",
                                            "end": "22:30"}]})
    at_time(w, at(2026, 10, 19, 22, 40, 15))
    at_time(w, at(2026, 10, 19, 22, 40, 20))
    assert w.run.state == "ended" and w.run.end_reason == "window_closed"
    assert house.snap_volume == 37.0


# ═══ 7. a window killed mid-run ═════════════════════════════════════════════

def _restart(w: World, tmp_path, monkeypatch, house) -> World:
    """The process dies: the run file says the window is open and (if it
    silenced the house) the snapshot is on disk. A new process, as main.py's
    lifespan builds it: recover, arm the schedule, then the supervisor."""
    absorb_store._runs_cache.update(path=None)
    recovered = absorb.recover_orphaned_run()
    w2 = World(tmp_path, monkeypatch, warm_up=False)
    w2.house = house
    w2.clock[0] = w.clock[0]
    w2.gw.now_playing = w.gw.now_playing
    w2.gw.playlists[SOURCE_ID] = list(w.gw.playlists[SOURCE_ID])
    make_guard(w2, house, tmp_path)
    w2.runner.install()
    w2.sched = absorb_schedule.Scheduler()
    w2.sched.arm(recovered, now_ms=ms(w2.clock[0]))
    return w2


def test_a_window_killed_mid_run_is_restored_before_anything_else_and_not_reopened(
        tmp_path, monkeypatch, house):
    """Report §12 phase 3, acceptance 2."""
    w = _world(tmp_path, monkeypatch, house, **EVENING)
    a, b = _opened(w)
    assert house.snap_volume == 0
    old = w.run.id
    w.advance(60)
    w2 = _restart(w, tmp_path, monkeypatch, house)
    house.events.clear()
    step(w2)
    first = house.events[0] if house.events else None
    assert first is not None and first[0] in ("pause", "ha.set_volume"), house.events
    writes = [e for e in house.events if e[0] == "ha.set_volume"]
    assert writes[0][1] == 37, "the first volume write wasn't the restore"
    assert house.snap_volume == 37.0 and absorb_silence.load_snapshot() is None
    run = absorb_store.latest_run()
    assert run.id == old and run.end_reason == "process_restarted"
    assert w2.runner.run.lights_held is False
    o = outcomes()[0]
    assert o["outcome"] == "interrupted" and "press Start" in o["detail"]
    # the rest of the window: never reopened
    for k in range(1, 12):
        at_time(w2, w2.clock[0] + 300)
    assert not w2.gw.plays and absorb_store.latest_run().id == old
    assert not [e for e in house.events if e == ("ha.set_volume", 0, True)]


def test_the_next_window_waits_for_a_dead_processs_silence_to_be_restored(
        tmp_path, monkeypatch, house):
    """Back-to-back windows, and SpotFX dies in the first: when it comes
    back the second is already due. The first one's silence is put back
    BEFORE the second silences the house again — never a volume written
    over a restore that hadn't happened."""
    w = _world(tmp_path, monkeypatch, house, enabled=True, windows=[
        {"days": ["mon"], "start": "21:30", "end": "22:30"},
        {"days": ["mon"], "start": "22:30", "end": "23:59"}])
    _opened(w)
    w.clock[0] = at(2026, 10, 19, 22, 29)
    w2 = _restart(w, tmp_path, monkeypatch, house)
    house.events.clear()
    w2.clock[0] = at(2026, 10, 19, 22, 31)
    step(w2)
    vols = [e[1] for e in house.events if e[0] == "ha.set_volume"]
    assert vols[:2] == [37, 0], house.events
    assert w2.run.state == "running" and w2.run.window["label"] == "Mon 22:30–23:59"
    assert absorb_silence.load_snapshot()["snap_volume"] == 37.0, (
        "the new window remembered absorb's own silence as his volume")


def test_a_window_still_waiting_when_spotfx_restarted_is_tried_again(
        tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, **EVENING)
    _his_music(w)
    at_time(w, MON_2130 + 5)
    assert w.run.stage == "waiting"
    w.advance(600)
    w2 = _restart(w, tmp_path, monkeypatch, house)
    assert outcomes()[0]["outcome"] == "interrupted"
    w2.playing(None)                              # his music has stopped since
    w2.advance(30)
    step(w2)
    assert w2.run.started_by == "schedule" and w2.run.state == "running"
    assert house.snap_volume == 0


# ═══ 8. the route ═══════════════════════════════════════════════════════════

def test_the_schedule_route_says_what_comes_next_and_what_happened(
        tmp_path, monkeypatch, house):
    w = _world(tmp_path, monkeypatch, house, **EVENING)
    monkeypatch.setattr(absorb, "runner", w.runner)
    app = FastAPI()
    app.include_router(absorb_router.router)
    with TestClient(app) as c:
        body = c.get("/api/absorb/schedule").json()
        assert body["enabled"] is True and body["active"] is True
        assert body["house_tz"] == "America/New_York"
        assert body["windows"][0]["label"] == "Mon 21:30–23:30"
        assert body["outcomes"] == []
        bad = c.put("/api/absorb/config", json={
            "windows": [{"days": ["mon"], "start": "21:30", "end": "21:30"}]})
        assert bad.status_code == 422 and "starts and ends" in bad.json()["detail"]
    nxt = absorb_schedule.status(now_ms=ms(MON_2129))["next"]
    assert nxt["start_ms"] == ms(MON_2130) and nxt["in_s"] == 60
