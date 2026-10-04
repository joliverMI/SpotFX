"""THE PROOF BAR FOR THE LIGHT SHOW's PER-DEVICE OUTPUT LAYER
(fx/device_output.py, `fx/VENDOR.md` deviation #41).

A target that round-trips through a dict proves nothing about a light. This
measures AT THE TRANSPORT — every frame each device's real `flush()` is
handed — on the real render pipeline (fx.headless, a real FxHost, the
vendored singleColor effect), the shape tests/test_device_timing_landing.py
established.

THE RIG IS HIS PROBLEM IN MINIATURE: ONE virtual spanning TWO dummy devices,
the way tv-mapper fans out to the TV backlight and both sconces. Nothing
upstream of the device can darken one of them alone; this layer must.

NEGATIVE CONTROLS: the idle layer is byte-identical to the layer not
existing, and `test_the_harness_fails_when_the_seam_is_bypassed` re-creates
the world without the seam and proves the instrument goes red on it.
"""
from __future__ import annotations

import asyncio
import json
import os

import numpy as np
import pytest

from fx import device_output, headless
from fx.host import FxHost

D1, D2 = "out-dev-a", "out-dev-b"
VID = "shared"
PIXELS = 8
FRAME_HZ = 60.0


def _config(config_dir):
    os.makedirs(config_dir, exist_ok=True)
    from fx.consts import CONFIGURATION_VERSION
    devices = [{"id": d, "type": "dummy",
                "config": {"name": d, "pixel_count": PIXELS}} for d in (D1, D2)]
    virtuals = [{"id": VID, "is_device": False, "auto_generated": False,
                 "config": {"name": VID, "mapping": "span", "rows": 1},
                 "segments": [[D1, 0, PIXELS - 1, False],
                              [D2, 0, PIXELS - 1, False]]}]
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": devices, "virtuals": virtuals}, fh)


class _Clock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now


class _Log:
    def __init__(self, host):
        self.frames: dict[str, list[np.ndarray]] = {D1: [], D2: []}
        for dev in host.devices.values():
            self._wrap(dev)

    def _wrap(self, dev):
        frames, real = self.frames, dev.flush

        def flush(data):
            frames.setdefault(dev.id, []).append(np.array(data, dtype=float, copy=True))
            return real(data)
        dev.flush = flush


async def _run(tmp_path, script, *, frames=120, color="#ff8000", tag="x"):
    """Render `frames` frames; `script(i, effect)` runs before frame i."""
    config_dir = str(tmp_path / f"fx-{tag}")
    _config(config_dir)
    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    clock = _Clock()
    device_output.set_clock(clock)
    log = _Log(host)
    try:
        with headless.fake_clock() as effect_clock:
            virtual = host.virtuals.get(VID)
            effect = headless.attach_effect(host, virtual, "singleColor",
                                            {"color": color, "brightness": 1.0})
            for i in range(frames):
                script(i, effect)
                effect_clock.advance(1.0 / FRAME_HZ)
                clock.now += 1.0 / FRAME_HZ
                assembled = virtual.assemble_frame()
                if assembled is not None:
                    virtual.flush(assembled)
    finally:
        await host.shutdown()
        device_output.clear_all()
        device_output.suspend(False)
        device_output.reset_clock()
    return log


def _run_sync(tmp_path, script, **kw):
    return asyncio.run(_run(tmp_path, script, **kw))


def _peak(frame):
    return float(np.asarray(frame).max())


# ── idle: nobody's room changes because this exists ───────────────────────

def test_idle_layer_returns_the_same_frame_object():
    frame = np.ones((4, 3)) * 7
    assert device_output.apply("anything", frame) is frame


def test_idle_layer_is_byte_identical_at_the_transport(tmp_path):
    idle = _run_sync(tmp_path, lambda i, e: None, tag="idle")
    real_apply = device_output.apply
    try:
        device_output.apply = lambda did, f: f          # the seam not existing
        absent = _run_sync(tmp_path, lambda i, e: None, tag="absent")
    finally:
        device_output.apply = real_apply
    for d in (D1, D2):
        assert len(idle.frames[d]) == len(absent.frames[d]) > 0
        for a, b in zip(idle.frames[d], absent.frames[d]):
            assert np.array_equal(a, b)


# ── one fixture of a shared virtual ───────────────────────────────────────

def test_dark_on_one_device_leaves_its_neighbour_lit(tmp_path):
    def script(i, _e):
        if i == 30:
            device_output.set_state(D1, "dark", fade_s=0.5)
    log = _run_sync(tmp_path, script, tag="dark")
    # lit before
    assert _peak(log.frames[D1][20]) > 200
    # mid-fade: partially down
    mid = _peak(log.frames[D1][30 + 15])
    assert 20 < mid < 240
    # after the fade: black
    assert _peak(log.frames[D1][30 + 31]) == 0.0
    assert _peak(log.frames[D1][-1]) == 0.0
    # the neighbour on the SAME virtual never moved
    assert all(_peak(f) > 200 for f in log.frames[D2])


def test_show_comes_back_in_step_with_what_is_rendering_now(tmp_path):
    """While dark the show moves on (brightness drops to 0.3); releasing to
    Show lands on what is rendering NOW — the show kept running underneath."""
    def script(i, effect):
        if i == 10:
            device_output.set_state(D1, "dark")
        if i == 40:
            effect.update_config({"brightness": 0.3})
        if i == 70:
            device_output.set_state(D1, "show", fade_s=0.0)
    log = _run_sync(tmp_path, script, tag="back")
    assert _peak(log.frames[D1][50]) == 0.0
    assert np.array_equal(log.frames[D1][-1], log.frames[D2][-1])
    assert _peak(log.frames[D2][-1]) < _peak(log.frames[D2][20])


def test_steady_holds_a_colour_and_is_scaled_by_the_room(tmp_path):
    device_output.set_scale_provider(lambda did: 0.5)
    try:
        def script(i, effect):
            if i == 5:
                device_output.set_state(D1, "steady", color=(0, 200, 0))
        log = _run_sync(tmp_path, script, tag="steady", color="#ff0000")
    finally:
        device_output.set_scale_provider(None)
    f = log.frames[D1][-1]
    assert np.allclose(f[:, 1], 100.0) and f[:, 0].max() == 0.0
    assert log.frames[D2][-1][:, 0].max() > 200      # neighbour shows the show


def test_freeze_holds_the_picture_while_the_show_changes(tmp_path):
    def script(i, effect):
        if i == 10:
            device_output.set_state(D1, "freeze")
        if i == 30:
            effect.update_config({"brightness": 0.2})
    log = _run_sync(tmp_path, script, tag="freeze", color="#ff0000")
    assert _peak(log.frames[D1][-1]) > 240          # held at the frozen picture
    assert _peak(log.frames[D2][-1]) < 80           # the show moved on


def test_level_multiplies_on_top_of_upstream_brightness(tmp_path):
    """Composes, never fights: an upstream brightness of 0.5 (the dimmer or a
    room-effect gain both land as an effect brightness) times a Level of 0.5
    is a quarter."""
    def script(i, effect):
        if i == 5:
            effect.update_config({"brightness": 0.5})
            device_output.set_level(D1, 0.5)
    log = _run_sync(tmp_path, script, tag="level", color="#ffffff")
    d1, d2 = _peak(log.frames[D1][-1]), _peak(log.frames[D2][-1])
    assert d2 > 0
    assert d1 == pytest.approx(d2 * 0.5, rel=0.02)


def test_level_above_one_brightens_and_clips(tmp_path):
    def script(i, effect):
        if i == 5:
            effect.update_config({"brightness": 0.4})
            device_output.set_level(D1, 2.0)
    log = _run_sync(tmp_path, script, tag="bright", color="#ffffff")
    assert _peak(log.frames[D1][-1]) == pytest.approx(2 * _peak(log.frames[D2][-1]), rel=0.02)
    assert _peak(log.frames[D1][-1]) <= 255.0


def test_flash_mixes_toward_white_then_decays(tmp_path):
    def script(i, _e):
        if i == 10:
            device_output.flash(D1, color=(255, 255, 255), amount=1.0,
                                attack_s=0.0, hold_s=0.1, decay_s=0.2)
    log = _run_sync(tmp_path, script, tag="flash", color="#ff0000")
    during = log.frames[D1][12]
    assert during[:, 2].max() > 240              # white in a red show
    assert log.frames[D1][-1][:, 2].max() < 5    # gone again


def test_suspended_layer_passes_through(tmp_path):
    def script(i, _e):
        if i == 5:
            device_output.set_state(D1, "dark")
        if i == 20:
            device_output.suspend(True)
    log = _run_sync(tmp_path, script, tag="susp")
    assert _peak(log.frames[D1][10]) == 0.0
    assert _peak(log.frames[D1][-1]) > 200


def test_the_layer_never_writes_in_place():
    device_output.set_level("x", 0.5)
    try:
        frame = np.full((4, 3), 100.0)
        for _ in range(5):
            out = device_output.apply("x", frame)
        assert np.all(frame == 100.0)
        assert np.allclose(out, 50.0)
    finally:
        device_output.clear_all()


def test_the_harness_fails_when_the_seam_is_bypassed(tmp_path):
    """The proof bar must be able to fail on the defect it was written for:
    with the seam removed, the dark device stays lit."""
    real_apply = device_output.apply
    try:
        device_output.apply = lambda did, f: f

        def script(i, _e):
            if i == 5:
                device_output.set_state(D1, "dark")
        log = _run_sync(tmp_path, script, tag="bypass")
    finally:
        device_output.apply = real_apply
    assert _peak(log.frames[D1][-1]) > 200
