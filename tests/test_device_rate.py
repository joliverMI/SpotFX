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
