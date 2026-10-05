"""SEND ON CHANGE (fx/device_output.py, fx/VENDOR.md #48) — counted where a
frame actually leaves: the device driver's own `flush`, called by a REAL
virtual's render loop on a real FxHost (the shape of tests/test_device_
rate.py and tests/test_house_withhold_landing.py).

  * OFF (the shipped state): every rendered frame reaches the transport.
  * ON, a picture that is not moving: the first frame goes out, identical
    ones are skipped until the keep-alive is due, then one copy goes out.
  * ON, a picture that changes: every changed frame goes out at once.
  * Never for a Hue area; never while the layer is suspended (a capture).
  * A frame after a withhold always goes out, however recently the same
    bytes were sent — the fixture was not shown them in between.
  * RED CONTROL: with the comparison removed from `_emit_frame` the
    static-picture run sends every frame (the harness can see the defect).
"""
from __future__ import annotations

import asyncio
import json
import os

import numpy as np
import pytest

from fx import device_output, headless
from fx.host import FxHost

D1 = "soc-dev"
VID = "soc-virtual"
PIXELS = 8


def _config(config_dir):
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    devices = [{"id": D1, "type": "dummy",
                "config": {"name": D1, "pixel_count": PIXELS, "refresh_rate": 60}}]
    virtuals = [{"id": VID, "is_device": False, "auto_generated": False,
                 "config": {"name": VID, "mapping": "span", "rows": 1},
                 "segments": [[D1, 0, PIXELS - 1, False]]}]
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": devices, "virtuals": virtuals}, fh)


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


async def _drive(tmp_path, *, keepalive, passes=12, frame_dt=0.05,
                 changing=False, tag="x", kind=None, during=None,
                 suspended=False, patch_emit=None):
    """Run the real render loop for `passes` frames, advancing a fake clock
    `frame_dt` per frame; returns how many frames reached the transport and
    the device (for its counters)."""
    import fx.virtuals as fxv
    from fx.devices.dummy import DummyDevice
    config_dir = str(tmp_path / f"fx-{tag}")
    _config(config_dir)
    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    dev = host.devices.get(D1)
    sent: list = []
    real = dev.flush

    def flush(data):
        sent.append(np.array(data, copy=True))
        return real(data)
    dev.flush = flush
    virtual = host.virtuals.get(VID)
    clock = FakeClock()
    device_output.set_clock(clock)
    n = {"i": 0}
    try:
        headless.attach_effect(host, virtual, "singleColor",
                               {"color": "#ff8000", "brightness": 1.0})
        device_output.set_send_on_change(keepalive)
        device_output.suspend(suspended)

        def fake_sleep(_s):
            n["i"] += 1
            clock.t += frame_dt
            if changing:
                # a different brightness every frame: a moving picture
                virtual._config["max_brightness"] = 0.3 + 0.05 * (n["i"] % 12)
            if during is not None:
                during(n["i"])
            if n["i"] >= passes:
                virtual._active = False
        with pytest.MonkeyPatch.context() as mp:
            if kind is not None:
                mp.setattr(DummyDevice, "type", property(lambda self: kind))
            if patch_emit is not None:
                mp.setattr(DummyDevice, "_emit_frame", patch_emit)
            mp.setattr(fxv.time, "sleep", fake_sleep)
            virtual._active = True
            virtual.thread_function()
    finally:
        virtual._active = False
        device_output.set_send_on_change(None)
        device_output.suspend(False)
        device_output.clear_withheld()
        device_output.reset_clock()
        await host.shutdown()
    return sent, dev


def test_off_sends_every_frame(tmp_path):
    sent, dev = asyncio.run(_drive(tmp_path, keepalive=None, tag="off"))
    assert len(sent) == 12
    assert dev._frames_skipped == 0 and dev._frames_sent == 12


def test_a_still_picture_is_sent_once_then_only_as_keep_alive(tmp_path):
    # 12 frames 50 ms apart = 0.55 s of rendering with a 0.2 s keep-alive:
    # the first frame, then one keep-alive every 0.2 s
    sent, dev = asyncio.run(_drive(tmp_path, keepalive=0.2, tag="still"))
    assert 2 <= len(sent) <= 4, len(sent)
    assert dev._frames_skipped == 12 - len(sent)
    assert all(np.array_equal(sent[0], f) for f in sent), "only copies went out"


def test_a_moving_picture_is_sent_every_frame(tmp_path):
    sent, dev = asyncio.run(_drive(tmp_path, keepalive=1.0, changing=True,
                                   tag="moving"))
    assert len(sent) == 12, "every changed frame goes out at once"
    assert dev._frames_skipped == 0


def test_a_hue_area_is_always_sent(tmp_path):
    sent, _ = asyncio.run(_drive(tmp_path, keepalive=1.0, kind="hue", tag="hue"))
    assert len(sent) == 12


def test_never_while_suspended_for_a_capture(tmp_path):
    sent, _ = asyncio.run(_drive(tmp_path, keepalive=1.0, suspended=True,
                                 tag="susp"))
    assert len(sent) == 12


def test_the_first_frame_after_a_withhold_always_goes_out(tmp_path):
    """Withheld at frame 2, released at frame 4 — well inside the 1 s
    keep-alive and with the identical picture. The fixture was not shown
    those frames (it may have left realtime), so the first one back goes
    out at once."""
    def during(i):
        if i == 2:
            device_output.set_withheld({D1: "lent"})
        if i == 4:
            device_output.set_withheld({})
    sent, _ = asyncio.run(_drive(tmp_path, keepalive=1.0, passes=8,
                                 during=during, tag="wh"))
    # frame 1 (first), nothing while withheld, frame after release
    assert len(sent) == 2, len(sent)


def test_red_control_without_the_comparison_every_frame_goes_out(tmp_path):
    """The harness can see the defect it guards: a plain emit (the pre-#48
    body) sends every frame of the still picture."""
    from fx.devices import DeviceUpdateEvent

    def plain_emit(self, frame):
        self.flush(frame)
        self._ledfx.events.fire_event(DeviceUpdateEvent(self.id, frame))
    sent, _ = asyncio.run(_drive(tmp_path, keepalive=0.2, tag="red",
                                 patch_emit=plain_emit))
    assert len(sent) == 12


def test_the_keep_alive_is_clamped_inside_the_sconces_timeout():
    assert device_output.set_send_on_change(30) == device_output.KEEPALIVE_MAX_S
    assert device_output.KEEPALIVE_MAX_S < 2.5, \
        "his sconces leave realtime after 2.5 s without a packet"
    assert device_output.set_send_on_change(0.0) == device_output.KEEPALIVE_MIN_S
    assert device_output.set_send_on_change(None) is None
    assert device_output.send_on_change_s() is None
