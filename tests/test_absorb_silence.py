"""Absorb Music phase 2 — the silence, its proof, the Order 27 gate, yield
and resume, the restore and crash recovery (services/absorb_silence.py),
driven through the REAL runner (services/absorb.py) against a fake house:
a fake snapserver whose rooms the fake "Snap Volume Control" automation
moves when the fake Home Assistant's snap_volume changes — and which can
move `Effects Host` out from under the proof, drop a room in mid-window,
lose its own status, or play an announcement. Nothing here touches the
network, the house, Spotify or his storage (report §12 phase 2's
acceptance: "Silence and restore are proven against a fake snapserver that
can move Effects Host out from under the proof, and against one that drops
a client in mid-window").

The light stand-down is proven from the SHOW side in
tests/test_absorb_stand_down.py; here only the flag SpotFX publishes is
checked, and its ORDER against the volume.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import pytest

from api.ha_client import HouseAudioReading, HouseAudioWrite
from services import absorb, absorb_silence, absorb_store
from services.absorb_silence import SilenceDeps, SilentHouseGuard, judge, read_hard_block
from services.snapcast_status import SnapcastUnreadable, parse_status
from tests.absorb_world import DEVICE, SOURCE_ID, World, uri


def _go(coro):
    return asyncio.run(coro)


# ── the fake house ───────────────────────────────────────────────────────────

class FakeHouse:
    """Home Assistant's snap_volume and the rooms on snapserver, joined by
    the house's "Snap Volume Control" automation: a snap_volume write sets
    every CONNECTED client's percent, except the ones it skips."""

    def __init__(self) -> None:
        self.snap_volume = 34.0
        self.sleeping: Optional[bool] = False
        self.events: list[tuple] = []
        self.groups = {"g-eh": False, "g1": False, "g2": False, "g3": False,
                       "g4": False, "g5": False, "g6": False}
        self.clients = {
            "eh": dict(name="Effects Host", connected=True, percent=100, muted=False, group="g-eh"),
            "kit": dict(name="Kitchen", connected=True, percent=34, muted=False, group="g1"),
            "mc": dict(name="Media Center", connected=True, percent=34, muted=False, group="g2"),
            "bath": dict(name="Bathroom", connected=True, percent=34, muted=False, group="g3"),
            "din": dict(name="Dining Room", connected=True, percent=34, muted=False, group="g4"),
            # he muted the porch himself: it must STAY muted after a restore
            "porch": dict(name="Porch", connected=True, percent=34, muted=True, group="g5"),
            "bed": dict(name="Bedroom", connected=False, percent=30, muted=False, group="g6"),
        }
        self.group_stream = {g: "Spotify" for g in self.groups}
        self.streams = {"Spotify": "playing", "TTS": "idle", "Guest": "idle", "AirPlay": "idle"}
        self.automation_skips = {"eh"}
        self.ha_fail_reads = False
        self.ha_fail_writes = False
        self.ha_stuck = False            # HA accepts a write but the number never moves
        self.snap_fail_reads = False
        self.snap_fail_writes = False

    # Home Assistant
    def fan_out(self, v: float) -> None:
        for cid, c in self.clients.items():
            if cid in self.automation_skips or not c["connected"]:
                continue
            c["percent"] = int(round(v))

    # snapserver JSON, exactly as Server.GetStatus answers it
    def body(self) -> dict:
        groups = []
        for gid, muted in self.groups.items():
            clients = [{"id": cid, "connected": c["connected"], "host": {"name": cid},
                        "config": {"name": c["name"],
                                   "volume": {"percent": c["percent"], "muted": c["muted"]}}}
                       for cid, c in self.clients.items() if c["group"] == gid]
            groups.append({"id": gid, "muted": muted, "stream_id": self.group_stream[gid],
                           "clients": clients})
        return {"jsonrpc": "2.0", "id": 1, "result": {"server": {
            "groups": groups,
            "streams": [{"id": k, "status": v} for k, v in self.streams.items()]}}}

    def audible_rooms(self) -> list[str]:
        out = []
        for cid, c in self.clients.items():
            if cid == "eh" or not c["connected"]:
                continue
            if self.group_stream[c["group"]] == "TTS":
                continue
            if not (c["muted"] or self.groups[c["group"]] or c["percent"] == 0):
                out.append(c["name"])
        return out


class FakeAudio:
    via = "fake"

    def __init__(self, house: FakeHouse, snapshot_path) -> None:
        self.h = house
        self.snapshot_path = snapshot_path

    async def read(self) -> HouseAudioReading:
        if self.h.ha_fail_reads:
            return HouseAudioReading(detail="Home Assistant unreachable (ConnectError)")
        return HouseAudioReading(volume=self.h.snap_volume, sleeping=self.h.sleeping)

    async def set_volume(self, volume: int) -> HouseAudioWrite:
        # the restore contract must be on disk BEFORE the first write
        self.h.events.append(("ha.set_volume", volume, self.snapshot_path.exists()))
        if self.h.ha_fail_writes:
            return HouseAudioWrite(False, "Home Assistant answered 500")
        if not self.h.ha_stuck:
            self.h.snap_volume = float(volume)
            self.h.fan_out(volume)
        return HouseAudioWrite(True, "")


class FakeSnap:
    def __init__(self, house: FakeHouse) -> None:
        self.h = house

    async def read_status(self):
        if self.h.snap_fail_reads:
            raise SnapcastUnreadable("snapserver unreachable (ConnectError)")
        return parse_status(json.loads(json.dumps(self.h.body())))

    async def set_client_volume(self, client_id: str, percent: int, muted: bool) -> None:
        self.h.events.append(("snap.set", client_id, percent, muted))
        if self.h.snap_fail_writes:
            raise SnapcastUnreadable("snapserver refused")
        c = self.h.clients[client_id]
        c["percent"], c["muted"] = int(percent), bool(muted)


def make_guard(w: World, house: FakeHouse, tmp_path, hard_block=lambda: None) -> SilentHouseGuard:
    path = absorb_silence.SNAPSHOT_FILE

    async def sleep(s):
        w.advance(s)

    async def playback():
        return w.gw.current_playback()

    async def pause():
        w.gw.pause("dev-serenity")

    async def announce():
        house.events.append(("announce", w.runner.run.lights_held if w.runner.run else None))

    guard = SilentHouseGuard(SilenceDeps(
        audio=FakeAudio(house, path), snap=FakeSnap(house), hard_block=hard_block,
        playback=playback, pause=pause, device_name=lambda: DEVICE,
        announce=announce, sleep=sleep, monotonic=lambda: w.clock[0],
        now_ms=lambda: int(w.clock[0] * 1000)))
    w.deps.guard = guard
    return guard


@pytest.fixture
def house():
    return FakeHouse()


@pytest.fixture
def world(tmp_path, monkeypatch, house):
    w = World(tmp_path, monkeypatch, warm_up=False)
    w.house = house
    w.guard = make_guard(w, house, tmp_path)
    w.gw.playlists[SOURCE_ID] = [uri(i) for i in range(1, 5)]
    return w


def _start(w: World) -> dict:
    return _go(w.runner.start())


def _h(w):
    return w.house


# ═══ 1. silence, and its proof ══════════════════════════════════════════════

def test_open_silences_the_rooms_and_leaves_the_capture_client_alone(world):
    result = _start(world)
    h = _h(world)
    assert result["status"] == "running", result
    assert h.snap_volume == 0
    assert h.audible_rooms() == []
    assert h.clients["eh"]["percent"] == 100 and h.clients["eh"]["muted"] is False
    # the restore contract was on disk before the first write
    first = next(e for e in h.events if e[0] == "ha.set_volume")
    assert first == ("ha.set_volume", 0, True)
    snap = absorb_silence.load_snapshot()
    assert snap["snap_volume"] == 34.0 and snap["capture"]["percent"] == 100
    assert world.run.pre_window["snap_volume"] == 34.0
    assert world.run.silent and world.run.lights_held
    assert absorb.brief(world.run)["lights_held"] is True
    # the music starts only after the silence is proven
    plays = [i for i, c in enumerate(world.gw.calls) if c[0] == "play"]
    assert plays and world.run.silence_checks[0]["ok"] is True
    assert world.fast_polls[-1] is True


def test_the_proof_refuses_when_the_volume_control_reaches_the_capture_client(world):
    """The fake moves Effects Host out from under the proof: the volume is
    put back AT ONCE and the window refused by name."""
    h = _h(world)
    h.automation_skips = set()
    result = _start(world)
    assert result["status"] == "refused" and result["reason"] == "capture_client_reached"
    assert "reaches the capture client" in result["detail"]
    assert h.snap_volume == 34.0
    assert h.clients["eh"]["percent"] == 100 and h.clients["eh"]["muted"] is False
    assert absorb_silence.load_snapshot() is None
    assert not any(c[0] == "play" for c in world.gw.calls), "a song started on a refused window"


def test_a_room_the_volume_does_not_reach_is_muted_directly_and_given_back(world):
    h = _h(world)
    h.automation_skips = {"eh", "din"}          # the dining room stays at 34 %
    assert _start(world)["status"] == "running"
    assert h.clients["din"]["muted"] is True and h.audible_rooms() == []
    assert absorb_silence.load_snapshot()["muted"][0]["id"] == "din"
    _go(world.runner.stop())
    assert h.snap_volume == 34.0
    assert h.clients["din"]["muted"] is False and h.clients["din"]["percent"] == 34
    assert h.clients["porch"]["muted"] is True, "a room he muted himself was unmuted"
    assert absorb_silence.load_snapshot() is None


def test_home_assistant_unreachable_refuses_without_a_single_write(world):
    _h(world).ha_fail_reads = True
    result = _start(world)
    assert result["reason"] == "ha_unreachable"
    assert not [e for e in _h(world).events if e[0] in ("ha.set_volume", "snap.set")]
    assert absorb_silence.load_snapshot() is None


def test_a_volume_write_that_is_refused_never_opens_the_window(world):
    _h(world).ha_fail_writes = True
    result = _start(world)
    assert result["reason"] == "volume_unsettable"
    assert not any(c[0] == "play" for c in world.gw.calls)


def test_an_unreadable_snapserver_refuses_at_open(world):
    _h(world).snap_fail_reads = True
    result = _start(world)
    assert result["reason"] == "snapserver_unreadable"
    assert not [e for e in _h(world).events if e[0] == "ha.set_volume"]


def test_a_muted_capture_client_refuses(world):
    _h(world).clients["eh"]["muted"] = True
    assert _start(world)["reason"] == "capture_client_muted"


def test_a_guest_playing_to_the_house_refuses(world):
    _h(world).streams["Guest"] = "playing"
    assert _start(world)["reason"] == "foreign_stream"


# ═══ 2. the Order 27 exception ═════════════════════════════════════════════

def test_absorb_may_run_while_the_house_sleeps_and_records_it(world):
    _h(world).sleeping = True
    assert _start(world)["status"] == "running"
    assert world.run.sleeping_at_open is True


def test_an_unreadable_sleeping_flag_is_read_as_sleeping(world):
    _h(world).sleeping = None
    assert _start(world)["status"] == "running"
    assert world.run.sleeping_at_open is True


def test_with_the_exception_off_sleeping_refuses_and_stops(world):
    absorb.apply_config_patch({"run_while_sleeping": False})
    _h(world).sleeping = True
    assert _start(world)["reason"] == "sleeping"
    _h(world).sleeping = False
    assert _start(world)["status"] == "running"
    _h(world).sleeping = True
    world.advance(61)
    _go(world.runner.tick())
    assert world.run.state == "ended" and world.run.end_reason == "sleeping"
    assert _h(world).snap_volume == 34.0


def test_the_proof_is_rerun_every_minute_and_a_room_joining_unsilenced_is_muted(world):
    h = _h(world)
    assert _start(world)["status"] == "running"
    checks = len(world.run.silence_checks)
    # the bedroom comes back on the network at its own 30 %
    h.clients["bed"]["connected"] = True
    world.advance(30)
    _go(world.runner.tick())
    assert h.clients["bed"]["muted"] is False, "rechecked before the minute was up"
    world.advance(31)
    _go(world.runner.tick())
    assert h.clients["bed"]["muted"] is True and h.audible_rooms() == []
    assert world.run.state == "running"
    assert len(world.run.silence_checks) == checks + 1
    assert "joined un-silenced" in world.run.silence_checks[-1]["detail"]
    _go(world.runner.stop())
    # unmuted; its level is whatever the house's own volume control now gives it
    assert h.clients["bed"]["muted"] is False and h.clients["bed"]["percent"] == 34


def test_a_room_that_cannot_be_muted_stops_the_window(world):
    h = _h(world)
    assert _start(world)["status"] == "running"
    h.clients["bed"]["connected"] = True
    h.snap_fail_writes = True
    world.advance(61)
    _go(world.runner.tick())
    assert world.run.state == "ended" and world.run.end_reason == "not_silent"
    assert world.gw.pauses >= 1


def test_a_snapserver_that_stops_answering_stops_the_window(world):
    h = _h(world)
    assert _start(world)["status"] == "running"
    h.snap_fail_reads = True
    world.advance(61)
    _go(world.runner.tick())
    assert world.run.state == "ended" and world.run.end_reason == "snapserver_unreadable"
    assert world.gw.pauses >= 1, "a stopped window left absorb's song playing"
    # the volume comes back even though the rooms can't be read: loud, named
    assert h.snap_volume == 34.0
    assert world.run.restore_pending


def test_the_capture_client_moving_mid_window_stops_it(world):
    h = _h(world)
    assert _start(world)["status"] == "running"
    h.clients["eh"]["percent"] = 40
    world.advance(61)
    _go(world.runner.tick())
    assert world.run.end_reason == "capture_client_reached"
    assert h.clients["eh"]["percent"] == 100, "the capture client was not put back"


def test_an_announcement_is_left_alone(world):
    """River's TTS hooks unmute the rooms onto the TTS stream at the voice
    volume. Absorb must not suppress that — announcements may be urgent."""
    h = _h(world)
    assert _start(world)["status"] == "running"
    for cid in ("kit", "mc", "bath", "din"):
        h.group_stream[h.clients[cid]["group"]] = "TTS"
        h.clients[cid]["percent"] = 25
    h.streams["TTS"] = "playing"
    world.advance(61)
    _go(world.runner.tick())
    assert world.run.state == "running"
    assert not [e for e in h.events if e[0] == "snap.set"], "absorb muted an announcement"
    assert "announcement" in world.run.silence_checks[-1]["detail"]


def test_rivers_hard_block_refuses_and_stops(tmp_path, monkeypatch, house):
    block = tmp_path / ".audio-hard-block"
    w = World(tmp_path, monkeypatch, warm_up=False)
    w.house = house
    make_guard(w, house, tmp_path, hard_block=lambda: read_hard_block(str(block)))
    w.gw.playlists[SOURCE_ID] = [uri(1), uri(2)]
    block.write_text("Unconditional audio hard block. Remove only on explicit Admiral word.\n")
    assert _go(w.runner.start())["reason"] == "hard_block"
    assert not [e for e in house.events if e[0] == "ha.set_volume"]
    block.write_text("allow=coarse,absorb\n")
    assert _go(w.runner.start())["status"] == "running"
    block.write_text("blocked again\n")
    w.advance(61)
    _go(w.runner.tick())
    assert w.run.end_reason == "hard_block" and house.snap_volume == 34.0


def test_the_hard_block_reader_is_rivers_rule():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "block"
        assert read_hard_block(str(p)) is None
        p.write_text("anything\n")
        assert read_hard_block(str(p)) == "present"
        p.write_text("allow=absorb\nallow=coarse\n")      # the LAST allow= line wins
        assert read_hard_block(str(p)) == "present"
        p.write_text("allow=coarse, ABSORB\n")
        assert read_hard_block(str(p)) is None
        p.unlink()
        p.mkdir()                                          # unreadable: fail closed
        assert read_hard_block(str(p)) == "unreadable"


# ═══ 3. yield and resume ═══════════════════════════════════════════════════

def _his_music(w: World) -> None:
    w.playing("spotify:track:hisownsong", progress_ms=1000)


def test_his_music_gets_the_volume_back_first_then_the_lights(world):
    h = _h(world)
    assert _start(world)["status"] == "running"
    a = world.run.queue[0]

    async def scenario():
        await world.arrive(a)
        h.events.clear()
        writes_before = len(world.gw.writes())
        _his_music(world)
        await world.poll()
        return writes_before

    before = _go(scenario())
    assert world.run.state == "paused"
    assert h.snap_volume == 34.0
    kinds = [e[0] for e in h.events]
    assert kinds.index("ha.set_volume") < kinds.index("announce"), kinds
    assert ("announce", False) in h.events
    assert len(world.gw.writes()) == before, "absorb touched his playback"
    assert world.run.queue[0] == a, "the interrupted song went back at the front"
    assert world.run.yields[-1]["restore_ok"] is True
    assert world.fast_polls[-1] is False


def _yield(w: World, expect: str = "paused") -> None:
    a = w.run.queue[0]

    async def scenario():
        await w.arrive(a)
        _his_music(w)
        await w.poll()

    _go(scenario())
    assert w.run.state == expect


def _quiet_poll(w: World, minutes: float, *, ok: Optional[bool] = True, step_s: float = 30) -> None:
    async def scenario():
        t = 0.0
        while t < minutes * 60:
            w.advance(step_s)
            t += step_s
            w.poll_ok = ok
            w.playing(None)
            await w.poll()
    _go(scenario())


def test_twenty_minutes_of_confirmed_quiet_resumes_as_a_full_reopen(world):
    h = _h(world)
    assert _start(world)["status"] == "running"
    _yield(world)
    h.snap_volume = 52.0            # he turned it up while listening
    plays = len(world.gw.plays)
    _quiet_poll(world, 19)
    assert world.run.state == "paused"
    _quiet_poll(world, 1.5)
    assert world.run.state == "running" and world.run.resumes == 1
    assert h.snap_volume == 0 and h.audible_rooms() == []
    assert absorb_silence.load_snapshot()["snap_volume"] == 52.0, (
        "the resume did not remember the volume he last left")
    assert world.run.lights_held is True
    assert len(world.gw.plays) == plays + 1
    _go(world.runner.stop())
    assert h.snap_volume == 52.0


def test_an_unknown_read_holds_the_clock_and_music_resets_it(world):
    assert _start(world)["status"] == "running"
    _yield(world)
    _quiet_poll(world, 15)
    _quiet_poll(world, 60, ok=False)            # Spotify unreachable for an hour
    assert world.run.state == "paused", "an unknown read advanced the clock"
    _quiet_poll(world, 3)
    assert world.run.state == "paused"
    _quiet_poll(world, 3)                        # 15 + 6 confirmed minutes
    assert world.run.state == "running"

    _yield(world)
    _quiet_poll(world, 15)

    async def music():
        world.advance(30)
        world.poll_ok = True
        _his_music(world)
        await world.poll()
    _go(music())
    _quiet_poll(world, 15)
    assert world.run.state == "paused", "his music did not reset the quiet clock"


def test_three_resumes_then_the_window_ends_and_says_so(world):
    h = _h(world)
    assert _start(world)["status"] == "running"
    for n in range(3):
        _yield(world)
        _quiet_poll(world, 21)
        assert world.run.state == "running" and world.run.resumes == n + 1
    _yield(world, expect="ended")
    assert world.run.end_reason == "resume_cap"
    assert h.snap_volume == 34.0
    assert world.run.lights_held is False


def test_a_reproof_that_fails_on_resume_ends_the_window(world):
    h = _h(world)
    assert _start(world)["status"] == "running"
    _yield(world)
    h.automation_skips = set()                  # now it reaches the capture client
    _quiet_poll(world, 21)
    assert world.run.state == "ended" and world.run.end_reason == "capture_client_reached"
    assert h.snap_volume == 34.0 and h.clients["eh"]["percent"] == 100


def test_a_guest_still_playing_holds_the_resume_rather_than_ending_the_window(world):
    h = _h(world)
    assert _start(world)["status"] == "running"
    _yield(world)
    h.streams["Guest"] = "playing"           # Spotify is quiet; a guest is not
    _quiet_poll(world, 21)
    assert world.run.state == "paused" and h.snap_volume == 34.0
    h.streams["Guest"] = "idle"
    _quiet_poll(world, 20.5)        # the clock restarted when the guest held it
    assert world.run.state == "running" and world.run.resumes == 1


def test_stop_while_yielded_never_pauses_his_music(world):
    assert _start(world)["status"] == "running"
    _yield(world)
    pauses = world.gw.pauses
    assert _go(world.runner.stop())["status"] == "ended"
    assert world.gw.pauses == pauses


def test_a_guest_stream_mid_window_yields(world):
    h = _h(world)
    assert _start(world)["status"] == "running"
    h.streams["Guest"] = "playing"
    world.advance(61)
    _go(world.runner.tick())
    assert world.run.state == "paused" and world.run.yields[-1]["code"] == "foreign_stream"
    assert h.snap_volume == 34.0


# ═══ 4. the close and the restore ══════════════════════════════════════════

def test_the_close_pauses_absorbs_song_before_the_volume_comes_back(world):
    h = _h(world)
    assert _start(world)["status"] == "running"
    a = world.run.queue[0]
    _go(world.arrive(a))
    h.events.clear()
    world.gw.calls.clear()
    _go(world.runner.stop())
    assert world.gw.pauses >= 1
    assert h.snap_volume == 34.0
    assert ("announce", False) in h.events
    assert absorb.brief(world.run)["lights_held"] is False
    assert world.run.restore["ok"] is True


def test_the_volume_is_never_restored_over_absorbs_own_song(world, caplog):
    """The pause doesn't take and Spotify keeps playing absorb's song: the
    house stays silent, loudly, and comes back once the song stops."""
    h = _h(world)
    assert _start(world)["status"] == "running"
    a = world.run.queue[0]
    _go(world.arrive(a))
    real_pause = world.gw.pause
    world.gw.pause = lambda device_id: world.gw.calls.append(("pause",))   # does nothing
    with caplog.at_level(logging.CRITICAL):
        _go(world.runner.stop())
    assert h.snap_volume == 0, "the volume came back over absorb's own song"
    assert world.run.restore_pending and world.run.lights_held is True
    assert any("NOT restored" in r.message for r in caplog.records)
    world.track = None              # his poller sees nothing; the silence is still absorb's
    assert _go(world.runner.start())["reason"] == "restore_pending"
    world.gw.pause = real_pause
    world.advance(absorb_silence.RETRY_PENDING_S + 1)
    _go(world.runner.tick())
    assert h.snap_volume == 34.0 and world.run.restore_pending == ""


def test_a_restore_that_does_not_read_back_is_loud_and_retried(world, caplog):
    h = _h(world)
    assert _start(world)["status"] == "running"
    h.ha_stuck = True
    with caplog.at_level(logging.CRITICAL):
        _go(world.runner.stop())
    assert world.run.restore["ok"] is False
    assert "reads 0" in world.run.restore_pending
    assert absorb_silence.load_snapshot()["stage"] == "restore_failed"
    assert any("NOT put back" in r.message for r in caplog.records)
    h.ha_stuck = False
    world.advance(absorb_silence.RETRY_PENDING_S + 1)
    _go(world.runner.tick())
    assert h.snap_volume == 34.0 and absorb_silence.load_snapshot() is None


# ═══ 5. crash recovery ═════════════════════════════════════════════════════

def _crash(w: World, tmp_path, monkeypatch, house) -> World:
    """The process dies mid-window: the run file says running and the
    silence snapshot is on disk. A new process: recover, then a new runner
    whose guard loads that snapshot."""
    absorb_store._runs_cache.update(path=None)
    assert absorb.recover_orphaned_run() == w.run.id
    w2 = World(tmp_path, monkeypatch, warm_up=False)
    w2.house = house
    w2.gw.now_playing = w.gw.now_playing
    make_guard(w2, house, tmp_path)
    w2.runner.run = absorb_store.latest_run()
    return w2


def test_a_crash_mid_window_is_restored_on_the_first_tick(world, tmp_path, monkeypatch):
    h = _h(world)
    assert _start(world)["status"] == "running"
    _go(world.arrive(world.run.queue[0]))
    assert h.snap_volume == 0
    w2 = _crash(world, tmp_path, monkeypatch, h)
    assert w2.run.state == "ended" and w2.run.end_reason == "process_restarted"
    assert w2.run.lights_held is True, "the show was handed a silent song before the restore"
    _go(w2.runner.tick())
    assert w2.gw.pauses == 1, "absorb's song was left playing over the restored volume"
    assert h.snap_volume == 34.0 and absorb_silence.load_snapshot() is None
    assert w2.run.lights_held is False and absorb.brief(w2.run)["lights_held"] is False


def test_a_crash_while_his_music_plays_restores_without_pausing_it(world, tmp_path, monkeypatch):
    h = _h(world)
    assert _start(world)["status"] == "running"
    w2 = _crash(world, tmp_path, monkeypatch, h)
    w2.gw.now_playing = {"uri": "spotify:track:hisownsong", "is_playing": True,
                         "device_name": DEVICE}
    _go(w2.runner.tick())
    assert w2.gw.pauses == 0
    assert h.snap_volume == 34.0


def test_a_crash_with_spotify_unreadable_stays_silent_until_it_can_tell(
        world, tmp_path, monkeypatch):
    h = _h(world)
    assert _start(world)["status"] == "running"
    _go(world.arrive(world.run.queue[0]))
    w2 = _crash(world, tmp_path, monkeypatch, h)
    w2.gw.playback_unknown = True
    _go(w2.runner.tick())
    assert h.snap_volume == 0, "restored the volume over a song that may be absorb's"
    assert w2.run.lights_held is True
    w2.gw.playback_unknown = False
    w2.advance(absorb_silence.RETRY_PENDING_S + 1)
    _go(w2.runner.tick())
    assert h.snap_volume == 34.0


def test_no_snapshot_means_nothing_is_touched_at_startup(world):
    _go(world.runner.tick())
    assert _h(world).events == []


# ═══ 6. the pieces ═════════════════════════════════════════════════════════

def test_judge_is_the_whole_rule():
    h = FakeHouse()
    st = parse_status(h.body())
    pre = judge(st, "Effects Host", None, "TTS")
    assert pre.code == "" and not pre.ok      # the rooms are audible before the write
    assert {c.name for c in pre.audible} == {"Kitchen", "Media Center", "Bathroom",
                                             "Dining Room"}
    cap = {"percent": 100, "muted": False, "group_muted": False}
    h.fan_out(0)
    assert judge(parse_status(h.body()), "Effects Host", cap, "TTS").ok
    h.groups["g-eh"] = True
    assert judge(parse_status(h.body()), "Effects Host", cap, "TTS").code == \
        "capture_client_reached"
    h.groups["g-eh"] = False
    h.clients["eh"]["connected"] = False
    assert judge(parse_status(h.body()), "Effects Host", cap, "TTS").code == \
        "capture_client_missing"


def test_a_malformed_snapserver_answer_is_never_a_proof():
    for body in (None, [], {"error": {"code": -1}}, {"result": {}},
                 {"result": {"server": {"groups": [{"clients": [{"id": "x"}]}]}}}):
        with pytest.raises(SnapcastUnreadable):
            parse_status(body)


def test_the_snapshot_file_unreadable_is_held_not_ignored(tmp_path):
    p = tmp_path / "absorb_silence.json"
    p.write_text("{not json")
    assert absorb_silence.load_snapshot(p) == {"unreadable": True}
