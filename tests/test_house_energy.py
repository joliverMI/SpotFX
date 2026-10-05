"""HOUSE LIGHTING phase 3 — spectra/services/house_energy.py and the live
stack's audio pause (spectra/services/live_host.py). The proofs:

  1. THE GATE: parking and send-on-change are switched on only while a mode
     drives the room; off with no mode, off on standby, off when he turns
     them off in the library — and only pushed when they change.
  2. AUDIO PAUSE: two minutes of CONFIRMED quiet pause it; music resumes
     it at once; an unknown read neither pauses nor resumes and restarts
     the quiet clock; anyone else listening keeps it on (and resumes it);
     the layer going inactive resumes it; a stream that will not reopen is
     retried and named.
  3. LIVE STACK: pause_audio closes the capture stream and stops the pump
     but keeps the hub and its subscriptions; resume reopens, drops stale
     queued audio, restarts the pump; a failed reopen stays paused.
  4. STATUS: per-fixture frames sent/skipped come from the devices' own
     counters; the packet estimate is DDP's ceil(bytes/1440) per frame.

No audio hardware, no network: the capture source, the hub consumers and
the playback read are fakes.
"""
from __future__ import annotations

import asyncio

import pytest


def _run(coro):
    return asyncio.run(coro)


class FakeSource:
    def __init__(self, fail_open=False):
        self.opened = 0
        self.closed = 0
        self.fail_open = fail_open

    def open(self, *, allow_device=False):
        assert allow_device
        if self.fail_open:
            raise OSError("PortAudio: device unavailable")
        self.opened += 1

    def close(self):
        self.closed += 1


class FakeLive:
    """The surface house_energy uses on live_host.live."""

    def __init__(self):
        self.host = object()
        self.audio_source = FakeSource()
        self.audio_paused = False
        self.listeners: list = []
        self.calls: list = []
        self.resume_ok = True

    def audio_listeners(self):
        return list(self.listeners)

    async def pause_audio(self, reason):
        self.calls.append(("pause", reason))
        if self.audio_paused:
            return False
        self.audio_paused = True
        return True

    async def resume_audio(self, reason):
        self.calls.append(("resume", reason))
        if not self.audio_paused or not self.resume_ok:
            return False
        self.audio_paused = False
        return True

    def audio_status(self):
        return {"state": "paused" if self.audio_paused else "listening"}


@pytest.fixture
def energy(monkeypatch):
    from spectra.services import house, house_energy
    house_energy.reset()
    w = type("W", (), {})()
    w.active = [True]
    w.playing = [False]
    w.live = FakeLive()
    w.now = [1000.0]
    monkeypatch.setattr(house, "layer_active", lambda: w.active[0])
    monkeypatch.setattr(house, "inactive_reason", lambda: "no house mode is set")
    house.deps = house.Deps(playing=lambda: w.playing[0])
    monkeypatch.setattr(house_energy, "_live", lambda: w.live)
    monkeypatch.setattr(house_energy, "_sample_counters", lambda: None)
    monkeypatch.setattr(house_energy.time, "monotonic", lambda: w.now[0])
    w.he = house_energy
    yield w
    house_energy.reset()


# ═══ 1. the gate ═════════════════════════════════════════════════════════════

def test_parking_and_send_on_change_follow_the_layer(energy):
    from fx import device_output, device_rate
    _run(energy.he.tick())
    assert device_rate.park_idle() is True
    assert device_output.send_on_change_setting() == 1.0
    energy.active[0] = False                    # no mode / standby / released
    _run(energy.he.tick())
    assert device_rate.park_idle() is False
    assert device_output.send_on_change_setting() is None


def test_the_library_can_switch_each_off(energy):
    from fx import device_output, device_rate
    from spectra.models.house_mode import HouseEnergy, HouseSettings
    from spectra.services import house_store
    house_store.put_settings(HouseSettings(energy=HouseEnergy(
        park_idle=False, send_on_change=False)))
    _run(energy.he.tick())
    assert device_rate.park_idle() is False
    assert device_output.send_on_change_setting() is None
    house_store.put_settings(HouseSettings(energy=HouseEnergy(keepalive_s=0.5)))
    _run(energy.he.tick())
    assert device_output.send_on_change_setting() == 0.5


def test_flags_are_pushed_only_when_they_change(energy, monkeypatch):
    from fx import device_rate
    pushes = []
    real = device_rate.set_park_idle
    monkeypatch.setattr(device_rate, "set_park_idle",
                        lambda on: (pushes.append(on), real(on)))
    for _ in range(3):
        _run(energy.he.tick())
    assert pushes == [True]


# ═══ 2. audio pause ══════════════════════════════════════════════════════════

def _tick_at(energy, t):
    energy.now[0] = t
    _run(energy.he.tick())


def test_two_minutes_of_confirmed_quiet_pause_the_audio(energy):
    _tick_at(energy, 1000.0)                    # quiet starts
    _tick_at(energy, 1119.0)
    assert energy.live.audio_paused is False
    _tick_at(energy, 1120.0)
    assert energy.live.audio_paused is True
    assert energy.live.calls[-1][0] == "pause"
    assert "no music for 120s" in energy.live.calls[-1][1]


def test_music_resumes_it_at_once(energy):
    _tick_at(energy, 1000.0)
    _tick_at(energy, 1200.0)
    assert energy.live.audio_paused
    energy.playing[0] = True
    _tick_at(energy, 1201.0)
    assert energy.live.audio_paused is False
    assert energy.live.calls[-1] == ("resume", "music is playing")


def test_an_unknown_read_neither_pauses_nor_resumes_and_restarts_the_clock(energy):
    _tick_at(energy, 1000.0)
    energy.playing[0] = None                    # the bridge is down
    _tick_at(energy, 1100.0)
    energy.playing[0] = False
    _tick_at(energy, 1130.0)                    # quiet again from here
    _tick_at(energy, 1200.0)
    assert energy.live.audio_paused is False, "only 70 s confirmed since"
    _tick_at(energy, 1250.0)
    assert energy.live.audio_paused is True
    energy.playing[0] = None
    _tick_at(energy, 1260.0)
    assert energy.live.audio_paused is True, "unknown never resumes on its own"


def test_anyone_else_listening_keeps_it_on_and_resumes_it(energy):
    energy.live.listeners = ["av-sync-reference"]
    _tick_at(energy, 1000.0)
    _tick_at(energy, 1500.0)
    assert energy.live.audio_paused is False
    energy.live.listeners = []
    _tick_at(energy, 1501.0)
    assert energy.live.audio_paused is True
    energy.live.listeners = ["av-sync-reference"]
    _tick_at(energy, 1502.0)
    assert energy.live.audio_paused is False
    assert "av-sync-reference is listening" in energy.live.calls[-1][1]


def test_the_layer_going_inactive_resumes_it(energy):
    _tick_at(energy, 1000.0)
    _tick_at(energy, 1200.0)
    assert energy.live.audio_paused
    energy.active[0] = False
    _tick_at(energy, 1201.0)
    assert energy.live.audio_paused is False


def test_with_no_mode_the_audio_is_never_paused(energy):
    energy.active[0] = False
    _tick_at(energy, 1000.0)
    _tick_at(energy, 5000.0)
    assert energy.live.audio_paused is False
    assert energy.live.calls == []


def test_zero_switches_pausing_off_and_resumes(energy):
    from spectra.models.house_mode import HouseEnergy, HouseSettings
    from spectra.services import house_store
    _tick_at(energy, 1000.0)
    _tick_at(energy, 1200.0)
    assert energy.live.audio_paused
    house_store.put_settings(HouseSettings(energy=HouseEnergy(audio_pause_after_s=0)))
    _tick_at(energy, 1201.0)
    assert energy.live.audio_paused is False


def test_a_failed_resume_is_retried_every_pass(energy):
    _tick_at(energy, 1000.0)
    _tick_at(energy, 1200.0)
    energy.live.resume_ok = False
    energy.playing[0] = True
    _tick_at(energy, 1201.0)
    _tick_at(energy, 1202.0)
    assert energy.live.audio_paused is True
    assert [c[0] for c in energy.live.calls[-2:]] == ["resume", "resume"]
    energy.live.resume_ok = True
    _tick_at(energy, 1203.0)
    assert energy.live.audio_paused is False


# ═══ 3. the live stack's own pause / resume ══════════════════════════════════

def test_live_pause_closes_the_stream_keeps_the_hub_and_resume_drops_stale_audio():
    import numpy as np

    from fx.audio_ingest import AudioIngestHub
    from spectra.services.live_host import MELBANK_SUBSCRIPTION, LiveLights

    class FakeMelbank:
        def __init__(self):
            self.blocks = []

        def ingest(self, block):
            self.blocks.append(block)

    async def main():
        live = LiveLights()
        live.hub = AudioIngestHub()
        live._melbank_sub = live.hub.subscribe(MELBANK_SUBSCRIPTION)
        live.melbank = FakeMelbank()
        live.audio_source = FakeSource()
        live._pump_task = asyncio.create_task(live._pump_audio())
        live.hub.push(np.ones(64, dtype=np.float32))
        await asyncio.sleep(0.05)
        assert len(live.melbank.blocks) == 1
        assert live.audio_listeners() == []
        other = live.hub.subscribe("av-sync-reference")
        assert live.audio_listeners() == ["av-sync-reference"]
        live.hub.unsubscribe(other)

        assert await live.pause_audio("test quiet") is True
        assert await live.pause_audio("again") is False
        assert live.audio_source.closed == 1 and live._pump_task is None
        assert live.hub is not None and live._melbank_sub is not None
        assert live.audio_status()["state"] == "paused"
        # something queued while paused must not be analysed as now
        live.hub.push(np.ones(64, dtype=np.float32))
        await asyncio.sleep(0.05)
        assert len(live.melbank.blocks) == 1

        assert await live.resume_audio("music") is True
        assert live.audio_source.opened == 1 and live._pump_task is not None
        await asyncio.sleep(0.05)
        assert len(live.melbank.blocks) == 1, "the stale block was dropped"
        live.hub.push(np.ones(64, dtype=np.float32))
        await asyncio.sleep(0.05)
        assert len(live.melbank.blocks) == 2
        assert live.audio_status()["state"] == "listening"
        live._pump_task.cancel()

    _run(main())


def test_live_resume_that_cannot_reopen_stays_paused_and_says_why():
    from fx.audio_ingest import AudioIngestHub
    from spectra.services.live_host import MELBANK_SUBSCRIPTION, LiveLights

    async def main():
        live = LiveLights()
        live.hub = AudioIngestHub()
        live._melbank_sub = live.hub.subscribe(MELBANK_SUBSCRIPTION)
        live.audio_source = FakeSource(fail_open=True)
        assert await live.pause_audio("quiet") is True
        assert await live.resume_audio("music") is False
        assert live.audio_paused is True
        assert "device unavailable" in live.audio_status()["resume_error"]

    _run(main())


# ═══ 4. status ═══════════════════════════════════════════════════════════════

def test_fixture_rates_come_from_the_devices_own_counters(monkeypatch):
    from spectra.services import house_energy
    house_energy.reset()

    class Dev:
        def __init__(self, did, kind, pixels):
            self.id, self.type, self.pixel_count = did, kind, pixels
            self._frames_sent = 0
            self._frames_skipped = 0

    class Host:
        def __init__(self):
            self.devices = {"crystal": Dev("crystal", "wled", 976),
                            "porch-rail": Dev("porch-rail", "wled", 1),
                            "hue-lights": Dev("hue-lights", "hue", 10),
                            "gap-x": Dev("gap-x", "dummy", 4096)}

    class Live:
        host = Host()

    t = [0.0]
    monkeypatch.setattr(house_energy, "_live", lambda: Live)
    monkeypatch.setattr(house_energy.time, "monotonic", lambda: t[0])
    house_energy._sample_counters()
    t[0] = 10.0
    Live.host.devices["crystal"]._frames_sent = 200          # 20 fps
    Live.host.devices["crystal"]._frames_skipped = 0
    Live.host.devices["porch-rail"]._frames_sent = 20        # 2 fps sent
    Live.host.devices["porch-rail"]._frames_skipped = 80     # 8 skipped
    Live.host.devices["hue-lights"]._frames_sent = 0
    house_energy._sample_counters()
    rates = house_energy.fixture_rates()
    assert "gap-x" not in rates
    assert rates["crystal"] == {"sent_fps": 20.0, "skipped_fps": 0.0,
                                "packets_per_s": 60.0}       # 2928 B = 3 packets
    assert rates["porch-rail"] == {"sent_fps": 2.0, "skipped_fps": 8.0,
                                   "packets_per_s": 2.0}
    assert rates["hue-lights"]["packets_per_s"] == 0.0
    house_energy.reset()
