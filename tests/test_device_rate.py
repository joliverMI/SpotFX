"""PER-DEVICE FRAME-RATE CAPS (fx/device_rate.py, fx/VENDOR.md #43).

A cap that round-trips a dict proves nothing about a fixture's packet rate.
This drives a REAL virtual's own render loop (`Virtual.thread_function`, on
a real FxHost with the vendored singleColor effect) and records the sleep
it chooses between frames — the one thing the cap changes — then counts the
frames that actually reach each device's transport over a fixed number of
loop passes. Capped vs uncapped, one virtual spanning two devices (his
tv-mapper fanning out to the TV backlight and both sconces).

  * No cap anywhere: the sleep is exactly what it was (1/refresh_rate less
    the frame's own run time) — the shipped state is byte-identical.
  * A cap on ONE of the virtual's devices slows the whole virtual (the
    sibling trade, stated in the module docstring).
  * A cap above the configured rate changes nothing (only ever lowers).
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

from fx import device_rate, headless
from fx.host import FxHost

D1, D2 = "rate-dev-a", "rate-dev-b"
VID = "rate-shared"
PIXELS = 8


def test_effective_rate_only_ever_lowers():
    device_rate.clear()
    assert device_rate.effective_rate(60, ["a"]) == 60
    device_rate.set_caps({"a": 10, "b": 0, "c": None})
    assert device_rate.caps() == {"a": 10.0}
    assert device_rate.effective_rate(60, ["a", "x"]) == 10.0
    assert device_rate.effective_rate(60, ["x"]) == 60
    assert device_rate.effective_rate(5, ["a"]) == 5, "a cap above the rate changes nothing"
    assert device_rate.effective_rate(False, ["a"]) is False
    device_rate.clear()
    assert not device_rate.active()


def _config(config_dir, refresh_rate=60):
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    devices = [{"id": d, "type": "dummy",
                "config": {"name": d, "pixel_count": PIXELS,
                           "refresh_rate": refresh_rate}} for d in (D1, D2)]
    virtuals = [{"id": VID, "is_device": False, "auto_generated": False,
                 "config": {"name": VID, "mapping": "span", "rows": 1},
                 "segments": [[D1, 0, PIXELS - 1, False],
                              [D2, 0, PIXELS - 1, False]]}]
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": devices, "virtuals": virtuals}, fh)


async def _drive(tmp_path, monkeypatch, *, caps, passes=6, tag="x"):  # noqa: ARG001
    """Run the virtual's real render loop for `passes` iterations, recording
    every sleep it asks for and every frame its devices flush."""
    import fx.virtuals as fxv
    config_dir = str(tmp_path / f"fx-{tag}")
    _config(config_dir)
    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    flushed = {D1: 0, D2: 0}
    for dev in host.devices.values():
        real = dev.flush

        def flush(data, _id=dev.id, _real=real):
            flushed[_id] = flushed.get(_id, 0) + 1
            return _real(data)
        dev.flush = flush
    sleeps: list[float] = []
    virtual = host.virtuals.get(VID)
    try:
        headless.attach_effect(host, virtual, "singleColor",
                               {"color": "#ff8000", "brightness": 1.0})
        device_rate.set_caps(caps)

        def fake_sleep(s):
            sleeps.append(s)
            if len(sleeps) >= passes:
                virtual._active = False
        # A LOCAL patch context: monkeypatch.undo() on the test's own
        # fixture would also revert conftest's autouse storage isolation.
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(fxv.time, "sleep", fake_sleep)
            virtual._active = True
            virtual.thread_function()
    finally:
        virtual._active = False
        device_rate.clear()
        await host.shutdown()
    return sleeps, flushed, virtual


def test_no_cap_sleeps_exactly_one_frame_of_the_configured_rate(tmp_path, monkeypatch):
    sleeps, flushed, virtual = asyncio.run(_drive(tmp_path, monkeypatch, caps={}, tag="idle"))
    rate = virtual.refresh_rate          # the dummy driver's own rate
    assert rate >= 30
    assert all(1 / rate - 0.01 < s <= 1 / rate for s in sleeps)
    assert flushed[D1] == flushed[D2] == len(sleeps)


def test_a_cap_on_one_device_slows_the_whole_virtual(tmp_path, monkeypatch):
    sleeps, flushed, _ = asyncio.run(_drive(tmp_path, monkeypatch, caps={D2: 10}, tag="cap"))
    assert all(1 / 10 - 0.02 < s <= 1 / 10 for s in sleeps), sleeps
    # one frame per pass reaches BOTH devices — the cap paces the loop
    assert flushed[D1] == flushed[D2] == len(sleeps)


def test_a_cap_above_the_rate_changes_nothing(tmp_path, monkeypatch):
    sleeps, _, virtual = asyncio.run(_drive(tmp_path, monkeypatch, caps={D1: 120}, tag="high"))
    rate = virtual.refresh_rate
    assert all(1 / rate - 0.01 < s <= 1 / rate for s in sleeps)


def test_frames_per_second_follow_the_cap(tmp_path, monkeypatch):
    """Sum the sleeps the loop chose over the same number of frames: the
    capped loop spends rate/10 times as long (e.g. 60 -> 10 fps) — i.e. ~1/6 the packets
    per second at the transport."""
    idle, _, virtual = asyncio.run(_drive(tmp_path, monkeypatch, caps={}, passes=12, tag="i2"))
    capped, _, _ = asyncio.run(_drive(tmp_path, monkeypatch, caps={D1: 10}, passes=12, tag="c2"))
    assert sum(capped) / sum(idle) == pytest.approx(virtual.refresh_rate / 10, rel=0.15)


# ═══ PARKING (fx/VENDOR.md #47, house lighting phase 3) ═════════════════════
#
# A virtual none of whose devices takes its frames renders at PARKED_FPS —
# decided LIVE on the render thread from the device objects themselves. The
# proofs drive the same real render loop as above; "an emitting device" is
# made by giving one dummy driver a non-dummy `type` for the test (the
# headless harness has no network transport to build a real WLED on).

class _Dev:
    def __init__(self, did, kind="wled", active=True, frozen=False):
        self.id = did
        self.type = kind
        self._active = active
        self.frozen = frozen

    def is_active(self):
        return self._active


def test_idle_reads_each_kind_of_device_that_takes_no_frames():
    from fx import device_output
    device_output.clear_withheld()
    assert device_rate.idle([_Dev("d", kind="dummy")])
    assert not device_rate.idle([_Dev("w")])
    assert device_rate.idle([_Dev("h", kind="hue", frozen=True)])
    assert not device_rate.idle([_Dev("h", kind="hue")])
    assert device_rate.idle([_Dev("w", active=False)])
    assert not device_rate.idle([]), "no devices is never parked"
    # one emitting sibling keeps the whole virtual at full rate
    assert not device_rate.idle([_Dev("d", kind="dummy"), _Dev("w")])
    device_output.set_withheld({"w": "lent"})
    try:
        assert device_rate.idle([_Dev("d", kind="dummy"), _Dev("w")])
        device_output.suspend(True)            # a capture holds the room
        assert not device_rate.idle([_Dev("w")]), \
            "withholding is not in force while suspended, so nor is parking"
    finally:
        device_output.suspend(False)
        device_output.clear_withheld()


def test_rate_for_parks_only_when_switched_on():
    device_rate.clear()
    dummy = [_Dev("d", kind="dummy")]
    assert device_rate.rate_for(62, dummy) == 62, "shipped state: untouched"
    device_rate.set_park_idle(True)
    try:
        assert device_rate.rate_for(62, dummy) == device_rate.PARKED_FPS
        assert device_rate.rate_for(62, [_Dev("w")]) == 62
        device_rate.set_caps({"w": 10})
        assert device_rate.rate_for(62, [_Dev("w")]) == 10
        assert device_rate.rate_for(1, dummy) == 1, "parking only ever lowers"
    finally:
        device_rate.clear()
    assert not device_rate.park_idle(), "clear() switches parking off too"


async def _drive_park(tmp_path, *, park, emitter=None, withheld=None,
                      passes=6, tag="p", during=None):
    """The real render loop of a virtual over two dummy devices. `emitter`
    names one of them to present as a non-dummy fixture; `during(n)` runs
    before the n-th sleep (to change the world mid-run)."""
    import fx.virtuals as fxv
    from fx import device_output
    from fx.devices.dummy import DummyDevice
    config_dir = str(tmp_path / f"fx-{tag}")
    _config(config_dir)
    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    flushed = {D1: 0, D2: 0}
    for dev in host.devices.values():
        real = dev.flush

        def flush(data, _id=dev.id, _real=real):
            flushed[_id] = flushed.get(_id, 0) + 1
            return _real(data)
        dev.flush = flush
    sleeps: list[float] = []
    virtual = host.virtuals.get(VID)
    try:
        headless.attach_effect(host, virtual, "singleColor",
                               {"color": "#ff8000", "brightness": 1.0})
        device_rate.set_park_idle(park)
        device_output.set_withheld(withheld or {})

        def fake_sleep(s):
            sleeps.append(s)
            if during is not None:
                during(len(sleeps))
            if len(sleeps) >= passes:
                virtual._active = False
        real_type = DummyDevice.type
        with pytest.MonkeyPatch.context() as mp:
            if emitter is not None:
                mp.setattr(DummyDevice, "type", property(
                    lambda self: "wled" if self.id == emitter else "dummy"))
            mp.setattr(fxv.time, "sleep", fake_sleep)
            virtual._active = True
            virtual.thread_function()
        assert DummyDevice.type is real_type
    finally:
        virtual._active = False
        device_rate.clear()
        device_output.clear_withheld()
        await host.shutdown()
    return sleeps, flushed, virtual


def test_a_virtual_that_lights_nothing_is_parked(tmp_path):
    """His radial-dummy: every device a dummy → PARKED_FPS while parking is
    on, and exactly the configured rate while it is off."""
    off, _, virtual = asyncio.run(_drive_park(tmp_path, park=False, tag="off"))
    rate = virtual.refresh_rate
    assert all(1 / rate - 0.01 < s <= 1 / rate for s in off)
    on, flushed, _ = asyncio.run(_drive_park(tmp_path, park=True, tag="on"))
    period = 1 / device_rate.PARKED_FPS
    assert all(period - 0.02 < s <= period for s in on), on
    # it still renders and flushes — the render-plane dead-man needs a frame
    # from every active virtual inside 2 s
    assert flushed[D1] == len(on)
    assert period < 2.0 - 1.0, "a parked virtual must flush well inside 2 s"


def test_one_emitting_sibling_keeps_the_full_rate(tmp_path):
    sleeps, _, virtual = asyncio.run(_drive_park(tmp_path, park=True,
                                                 emitter=D1, tag="emit"))
    rate = virtual.refresh_rate
    assert all(1 / rate - 0.01 < s <= 1 / rate for s in sleeps)


def test_withholding_the_only_emitter_parks_and_releasing_it_unparks_at_once(tmp_path):
    """Decided per frame from live state: the frame after the withhold is
    lifted runs at the full rate — no supervisor in between."""
    from fx import device_output

    def lift(n):
        if n == 3:
            device_output.set_withheld({})

    sleeps, _, virtual = asyncio.run(_drive_park(
        tmp_path, park=True, emitter=D1, withheld={D1: "lent"},
        passes=6, tag="lift", during=lift))
    rate = virtual.refresh_rate
    period = 1 / device_rate.PARKED_FPS
    assert all(period - 0.02 < s <= period for s in sleeps[:3]), sleeps
    assert all(1 / rate - 0.01 < s <= 1 / rate for s in sleeps[3:]), sleeps


def test_no_cap_takes_a_virtual_below_the_parked_rate():
    """The dead-man's 2 s margin holds for a cap too: a cap of 1 renders at
    PARKED_FPS, and sleeps 1/rate (below the vendored table's 10 fps floor,
    which used to turn every cap at or under 10 into ~11 fps)."""
    device_rate.clear()
    device_rate.set_caps({"w": 1})
    try:
        assert device_rate.rate_for(30, [_Dev("w")]) == device_rate.PARKED_FPS
        assert device_rate.rate_for(1.5, [_Dev("w")]) == 1.5, "a configured rate stands"
    finally:
        device_rate.clear()
    assert device_rate.sleep_interval(10) == pytest.approx(0.1)
    assert device_rate.sleep_interval(5) == pytest.approx(0.2)
    assert device_rate.sleep_interval(20) is None, "above the floor: the table"
