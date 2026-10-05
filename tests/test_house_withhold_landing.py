"""WITHHELD — a lent or switched-off fixture gets NO frame at all
(fx/device_output.py's WITHHELD section, `fx/VENDOR.md` #44).

Measured AT THE TRANSPORT on the real render pipeline (fx.headless, a real
FxHost, the vendored singleColor effect), on his problem in miniature: ONE
virtual spanning TWO dummy devices, the way tv-mapper fans out to the TV
backlight and both kitchen sconces. Lending the TV strip to Hyperion must
stop its packets and leave the sconces' alone.

  1. a withheld device receives no flush and no update event; its sibling
     on the same virtual is untouched; letting go resumes it
  2. suspension (a preview / camera run / night run) streams it anyway
  3. the instrument goes RED with the seam bypassed
  4. the room's own health surfaces do not call a withheld fixture a
     fault: streaming_device_ids (the dark-fixture watch's precondition)
     and device_gaps (the activation gate) both leave it out
"""
from __future__ import annotations

import asyncio
import json
import os
import time

import numpy as np

from fx import device_output, headless
from fx.host import FxHost

D1, D2 = "tv-strip", "sconce"
VID = "tv-mapper"
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


async def _run(tmp_path, script, *, frames=60, tag="x"):
    config_dir = str(tmp_path / f"fx-{tag}")
    _config(config_dir)
    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    flushed: dict[str, list[int]] = {D1: [], D2: []}
    events: list[str] = []
    for dev in host.devices.values():
        real = dev.flush

        def flush(data, _d=dev.id, _real=real):
            flushed.setdefault(_d, []).append(len(flushed.get(_d, [])))
            return _real(data)
        dev.flush = flush
    from fx.events import Event
    host.events.add_listener(lambda e: events.append(e.device_id),
                             Event.DEVICE_UPDATE)
    per_frame: list[tuple[int, int]] = []
    try:
        with headless.fake_clock() as clock:
            virtual = host.virtuals.get(VID)
            headless.attach_effect(host, virtual, "singleColor",
                                   {"color": "#ff8000", "brightness": 1.0})
            for i in range(frames):
                script(i)
                before = (len(flushed[D1]), len(flushed[D2]))
                clock.advance(1.0 / FRAME_HZ)
                assembled = virtual.assemble_frame()
                if assembled is not None:
                    virtual.flush(assembled)
                per_frame.append((len(flushed[D1]) - before[0],
                                  len(flushed[D2]) - before[1]))
    finally:
        await host.shutdown()
        device_output.clear_withheld()
        device_output.suspend(False)
    return per_frame, events


def _run_sync(tmp_path, script, **kw):
    return asyncio.run(_run(tmp_path, script, **kw))


def test_a_withheld_fixture_gets_no_frame_and_its_sibling_is_untouched(tmp_path):
    def script(i):
        if i == 20:
            device_output.set_withheld({D1: "lent: TV Music is off"})
        if i == 40:
            device_output.set_withheld({})
    per_frame, events = _run_sync(tmp_path, script, tag="lend")
    before, during, after = per_frame[:20], per_frame[20:40], per_frame[40:]
    assert all(a == 1 and b == 1 for a, b in before)
    assert all(a == 0 for a, _ in during), "the lent strip still got frames"
    assert all(b == 1 for _, b in during), "lending the strip stopped the sconce"
    assert all(a == 1 and b == 1 for a, b in after), "the strip did not come back"
    # No DeviceUpdateEvent for the withheld device while it was withheld:
    # 20 + 20 frames of D1, 60 of D2.
    assert events.count(D1) == 40
    assert events.count(D2) == 60


def test_suspension_streams_a_withheld_fixture(tmp_path):
    def script(i):
        if i == 0:
            device_output.set_withheld({D1: "switched off"})
            device_output.suspend(True)
    per_frame, _ = _run_sync(tmp_path, script, frames=20, tag="susp")
    assert all(a == 1 for a, _ in per_frame), \
        "a capture must see every fixture it drives"


def test_the_harness_fails_when_the_seam_is_bypassed(tmp_path, monkeypatch):
    monkeypatch.setattr(device_output, "is_withheld", lambda d: False)

    def script(i):
        if i == 0:
            device_output.set_withheld({D1: "lent"})
    per_frame, _ = _run_sync(tmp_path, script, frames=10, tag="bypass")
    # With the seam bypassed the lent strip keeps receiving frames — the
    # same measurement the first test asserts zero on.
    assert all(a == 1 for a, _ in per_frame)


def test_idle_withheld_check_is_one_truthiness_check():
    device_output.clear_withheld()
    assert device_output.is_withheld("anything") is False
    device_output.set_withheld({"x": "off"})
    assert device_output.is_withheld("x") is True
    assert device_output.is_withheld("y") is False
    device_output.suspend(True)
    try:
        assert device_output.is_withheld("x") is False
    finally:
        device_output.suspend(False)
        device_output.clear_withheld()


# ── the room's health surfaces leave a withheld fixture out ───────────────

class _Dev:
    def __init__(self, did):
        self.id = did
        self.type = "wled"

    def is_active(self):
        return True


class _Virt:
    def __init__(self, vid, devices):
        self.id = vid
        self.active = True
        self._segments = [[d, 0, 7, False] for d in devices]


class _Host:
    def __init__(self):
        self.devices = {D1: _Dev(D1), D2: _Dev(D2)}
        self.virtuals = {VID: _Virt(VID, [D1, D2])}


def test_streaming_device_ids_leaves_a_withheld_fixture_out():
    from spectra.services.live_host import LiveLights
    lights = LiveLights()
    lights.host = _Host()
    lights.freshness.marks[VID] = time.monotonic()
    assert lights.streaming_device_ids() == {D1, D2}
    device_output.set_withheld({D1: "switched off"})
    try:
        assert lights.streaming_device_ids() == {D2}, \
            "the dark-fixture watch would name a switched-off fixture as a fault"
    finally:
        device_output.clear_withheld()
        lights.host = None


def test_device_gaps_does_not_probe_a_withheld_fixture():
    from spectra.services.live_host import LiveLights
    lights = LiveLights()
    lights.host = _Host()
    lights.expected_active_ids = {VID}
    asked: list = []

    async def probe(ids, timeout_s):
        asked.append(sorted(ids))
        return {d: "device reports live=false" for d in ids}
    lights.probe_devices = probe
    device_output.set_withheld({D1: "lent: TV Music is off"})
    try:
        gaps = asyncio.run(lights.device_gaps(deadline_s=0.0))
    finally:
        device_output.clear_withheld()
        lights.host = None
    assert asked == [[D2]]
    assert D1 not in gaps


# ── end to end: Home Assistant's report reaches the transport ──────────────

def test_tv_music_off_stops_the_strips_frames_end_to_end(tmp_path, monkeypatch):
    """PUT /house/tv-music {"on": false} → house_fixtures → the withheld set
    → Device.update_pixels: the TV strip's transport stops receiving frames
    while the sconce on the same virtual keeps going, and comes back on
    {"on": true}. Real FxHost and render pipeline; only the room gate and
    the WLED control transport are stand-ins (dummies have no control
    channel, which is also why nothing is posted to them)."""
    from spectra.models.house_mode import HouseMode, HouseSettings
    from spectra.services import house, house_fixtures, house_store, show_output

    async def scenario():
        config_dir = str(tmp_path / "fx-e2e")
        _config(config_dir)
        headless.silence_audio()
        host = FxHost(config_dir)
        await host.start()
        host.audio = headless.SyntheticAudioSource()
        counts = {D1: 0, D2: 0}
        for dev in host.devices.values():
            real = dev.flush

            def flush(data, _d=dev.id, _real=real):
                counts[_d] += 1
                return _real(data)
            dev.flush = flush
        monkeypatch.setattr(house, "gate", lambda: (None, None))
        monkeypatch.setattr(show_output, "ownership_refusal", lambda: None)
        monkeypatch.setattr(show_output, "_host", lambda: host)
        posts = []

        async def post(dev, payload):
            posts.append((dev.id, payload))
        house_fixtures.deps = house_fixtures.Deps(host=lambda: host, post=post)
        house_store.put_settings(HouseSettings(tv_strips=[D1]))
        mode = house_store.put_mode(HouseMode(name="Standard"))
        house_store.state().mode_id = mode.id

        def frames(n):
            before = dict(counts)
            for _ in range(n):
                clock.advance(1.0 / FRAME_HZ)
                v.flush(v.assemble_frame())
            return counts[D1] - before[D1], counts[D2] - before[D2]
        try:
            with headless.fake_clock() as clock:
                v = host.virtuals.get(VID)
                headless.attach_effect(host, v, "singleColor",
                                       {"color": "#ff8000", "brightness": 1.0})
                await house_fixtures.tick()
                assert frames(10) == (10, 10)
                house_fixtures.set_tv_music(False)
                await house_fixtures.tick()
                assert frames(10) == (0, 10), "the lent strip still got frames"
                house_fixtures.set_tv_music(True)
                await house_fixtures.tick()
                for _ in range(3):
                    await asyncio.sleep(0)
                await house_fixtures.tick()
                assert frames(10) == (10, 10), "the strip did not come back"
        finally:
            await host.shutdown()
            device_output.clear_withheld()
        return posts
    posts = asyncio.run(scenario())
    assert posts == [], "a dummy has no control channel — nothing is posted"
