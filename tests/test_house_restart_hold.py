"""HOUSE LIGHTING phase 2 — A SPECTRA RESTART KEEPS THE LAST PICTURE
(spectra/services/house_restart.py; fx/VENDOR.md #45, #46). One test group
per blink the module ends:

  1. THE WLEDs LET GO — a planned stop with a mode driving the room does
     not send {"live": false}; every other teardown still does.
  2. THE FIRST FRAMES WERE AT FULL — the snapshot re-installed before the
     stack comes up puts the mode's level on the VERY FIRST frame, measured
     at the transport on the real render pipeline (red without it).
  3. THE HUE BULBS STREAMED THE SHOW — a held area comes up frozen (no
     entertainment session); one nothing holds after the restart is
     unfrozen again.
  4. ONLY WHEN IT WILL APPLY — no mode, not the owner, another mode's or a
     stale snapshot: nothing is installed; no mode: no file is written.
  5. THE ORDER in the real lifespan: install before resume, decide the hold
     before the engine goes on paper.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
from types import SimpleNamespace

import numpy as np
import pytest

from fx import device_output, device_rate, headless, hue_freeze, light_ownership
from fx.host import FxHost
from spectra.models.house_mode import HouseMode, now_ms

D1, D2 = "crystal", "sconce"
VID = "room"
PIXELS = 8


# ── 1. the WLEDs do not let go on a planned stop ───────────────────────────

def _bare_wled():
    from fx.devices.wled import WLEDDevice
    dev = WLEDDevice.__new__(WLEDDevice)
    dev._teardown_dispatched = False
    dev._active = True
    dev._pixels = None
    dev.subdevice = None
    dev.wled = object()
    dispatched = []
    dev._dispatch_teardown_task = lambda coro: (dispatched.append(coro), coro.close())
    return dev, dispatched


def test_a_wled_lets_go_on_an_ordinary_teardown():
    dev, dispatched = _bare_wled()
    dev.deactivate()
    assert len(dispatched) == 1, "the release must still go out by default"


def test_a_wled_holding_its_last_frame_is_not_told_to_let_go():
    dev, dispatched = _bare_wled()
    dev._hold_last_frame = True
    dev.deactivate()
    assert dispatched == []


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


def test_shutdown_holding_marks_every_device_and_the_default_marks_none(tmp_path):
    async def run(hold):
        cfg = str(tmp_path / f"fx-{hold}")
        _config(cfg)
        headless.silence_audio()
        host = FxHost(cfg)
        await host.start()
        devices = list(host.devices.values())
        if hold:
            await host.shutdown(release_realtime=False)
        else:
            await host.shutdown()
        return [d._hold_last_frame for d in devices]
    assert asyncio.run(run(True)) == [True, True]
    assert asyncio.run(run(False)) == [False, False]


def test_live_deactivate_passes_the_hold_down():
    from spectra.services.live_host import LiveLights
    seen = []

    class Host:
        async def shutdown(self, release_realtime=True):
            seen.append(release_realtime)
    lights = LiveLights()
    lights.host = Host()
    asyncio.run(lights.deactivate(hold_last_frame=True))
    lights.host = Host()
    asyncio.run(lights.deactivate())
    assert seen == [False, True]


# ── 2. the first frame already carries the mode ────────────────────────────

@pytest.fixture
def owned_mode(monkeypatch):
    from spectra.services import house_store
    monkeypatch.setattr(light_ownership, "load",
                        lambda: SimpleNamespace(owner=light_ownership.SPECTRA))
    mode = house_store.put_mode(HouseMode(name="Night light"))
    st = house_store.state()
    st.mode_id = mode.id
    house_store.save_state()
    return mode


def _write_snapshot(mode_id, **kw):
    from spectra import config as scfg
    snap = {"mode_id": mode_id, "levels": {}, "states": {}, "caps": {},
            "withheld": {}, "hue_frozen": [], "at_ms": now_ms()}
    snap.update(kw)
    with open(scfg.HOUSE_RESTART_FILE, "w") as fh:
        json.dump(snap, fh)


async def _first_frames(tmp_path, prepare):
    cfg = str(tmp_path / f"fx-{prepare}")
    _config(cfg)
    if prepare:
        from spectra.services import house_restart
        res = house_restart.prepare_for_resume()
        assert res["installed"], res
    headless.silence_audio()
    host = FxHost(cfg)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    first: dict = {}
    for dev in host.devices.values():
        real = dev.flush

        def flush(data, _d=dev.id, _real=real):
            first.setdefault(_d, np.array(data, dtype=float, copy=True))
            return _real(data)
        dev.flush = flush
    try:
        with headless.fake_clock() as clock:
            v = host.virtuals.get(VID)
            headless.attach_effect(host, v, "singleColor",
                                   {"color": "#ffffff", "brightness": 1.0})
            clock.advance(1 / 60)
            v.flush(v.assemble_frame())
    finally:
        await host.shutdown()
        device_output.clear_all()
        device_output.clear_withheld()
    return first


def test_the_first_frame_after_a_restart_is_already_at_the_modes_level(
        tmp_path, owned_mode):
    _write_snapshot(owned_mode.id, levels={D1: 0.03})
    first = asyncio.run(_first_frames(tmp_path, prepare=True))
    assert float(first[D1].max()) <= 255 * 0.03 + 1e-6, \
        "the crystal flashed full on the restart"
    assert float(first[D2].max()) == pytest.approx(255.0)


def test_red_without_the_snapshot_the_first_frame_is_full(tmp_path, owned_mode):
    first = asyncio.run(_first_frames(tmp_path, prepare=False))
    assert float(first[D1].max()) == pytest.approx(255.0)


def test_withheld_caps_and_hue_are_installed_too(owned_mode):
    from spectra.services import house_restart
    _write_snapshot(owned_mode.id, caps={D1: 15}, withheld={"tv": "lent: x"},
                    hue_frozen=["hue-lights"], states={D2: "dark"})
    res = house_restart.prepare_for_resume()
    assert res["installed"] and res["off"] == 1
    assert device_rate.caps() == {D1: 15.0}
    assert device_output.withheld() == {"tv": "lent: x"}
    assert hue_freeze.pending() == {"hue-lights"}
    assert device_output.target(D2).state == "dark"


def test_a_modes_switched_off_wleds_are_installed_ready(owned_mode):
    """Phase 3: the fixtures the mode had switched OFF (no stream) come back
    already off — house.mode_off_devices() names them before the layer's
    first pass, so the fixtures half never switches them on in between."""
    from spectra.services import house, house_restart
    _write_snapshot(owned_mode.id, withheld={"porch-rail": "switched off"},
                    mode_off=["porch-rail"], states={"porch-rail": "dark"})
    assert house_restart.prepare_for_resume()["installed"]
    assert house.mode_off_devices() == {"porch-rail": "Night light"}
    assert house_restart.snapshot()["mode_off"] == ["porch-rail"]


# ── 4. only when it will apply ─────────────────────────────────────────────

def test_nothing_is_installed_without_a_mode(monkeypatch):
    from spectra.services import house_restart
    monkeypatch.setattr(light_ownership, "load",
                        lambda: SimpleNamespace(owner=light_ownership.SPECTRA))
    _write_snapshot("whatever", levels={D1: 0.1})
    assert house_restart.prepare_for_resume()["installed"] is False
    assert device_output.snapshot() == {}


def test_nothing_is_installed_when_spectra_does_not_own(owned_mode, monkeypatch):
    from spectra.services import house_restart
    monkeypatch.setattr(light_ownership, "load",
                        lambda: SimpleNamespace(owner=light_ownership.RELEASED))
    _write_snapshot(owned_mode.id, levels={D1: 0.1})
    assert house_restart.prepare_for_resume()["installed"] is False


def test_another_modes_or_a_stale_snapshot_is_ignored(owned_mode):
    from spectra.services import house_restart
    _write_snapshot("another-mode", levels={D1: 0.1})
    assert house_restart.prepare_for_resume()["why"] == "the snapshot is of another mode"
    _write_snapshot(owned_mode.id, levels={D1: 0.1},
                    at_ms=now_ms() - house_restart.MAX_AGE_MS - 1)
    assert house_restart.prepare_for_resume()["why"] == "the snapshot is stale"


def test_no_mode_writes_no_file_and_a_mode_writes_on_change(monkeypatch):
    from spectra import config as scfg
    from spectra.services import house_restart, house_store, show_output
    from spectra.services.live_host import live
    monkeypatch.setattr(live, "host", SimpleNamespace(devices={}))
    assert house_restart.maybe_persist() is False
    assert not os.path.exists(scfg.HOUSE_RESTART_FILE)
    mode = house_store.put_mode(HouseMode(name="Standard"))
    house_store.state().mode_id = mode.id
    show_output.set_base({D1: 0.06}, {})
    assert house_restart.maybe_persist() is True
    assert house_restart.maybe_persist() is False, "unchanged: no rewrite"
    saved = json.load(open(scfg.HOUSE_RESTART_FILE))
    assert saved["levels"] == {D1: 0.06} and saved["mode_id"] == mode.id


def test_the_hold_follows_whether_a_mode_drives_the_room(monkeypatch):
    from spectra.services import house, house_restart
    monkeypatch.setattr(house, "layer_active", lambda: True)
    assert house_restart.hold_on_shutdown() is True
    monkeypatch.setattr(house, "layer_active", lambda: False)
    assert house_restart.hold_on_shutdown() is False


# ── 3. Hue comes up frozen, and is unfrozen if nothing holds it ────────────

def test_a_named_hue_area_comes_up_frozen_once(monkeypatch):
    from fx.devices import NetworkedDevice
    from fx.devices.hue import HueDevice
    monkeypatch.setattr(NetworkedDevice, "activate", lambda self: None)
    reconnects = []
    monkeypatch.setattr(HueDevice, "_trigger_reconnect",
                        lambda self: reconnects.append(self._frozen))
    dev = HueDevice.__new__(HueDevice)
    dev._frozen = False
    dev._id = "hue-lights"
    dev._config = {"name": "Hue Lights"}
    hue_freeze.set_pending({"hue-lights"})
    dev.activate()
    assert dev._frozen is True and reconnects == [True]
    assert hue_freeze.take_consumed() == {"hue-lights"}
    dev2 = HueDevice.__new__(HueDevice)
    dev2._frozen = False
    dev2._id = "hue-lights"
    dev2._config = {"name": "Hue Lights"}
    dev2.activate()
    assert dev2._frozen is False, "one-shot: a later activation streams"


def test_after_resume_unfreezes_an_area_nothing_holds(monkeypatch):
    from spectra.services import ambient_music_gate as gate
    from spectra.services import house_restart
    from spectra.services.live_host import live

    class Hue:
        def __init__(self, did):
            self.id = did
            self.frozen = True
            self.calls = []

        async def set_frozen(self, on):
            self.calls.append(on)
            self.frozen = on
    held, loose = Hue("dining-hues"), Hue("hue-lights")
    monkeypatch.setattr(live, "host", SimpleNamespace(
        devices={"dining-hues": held, "hue-lights": loose}))
    monkeypatch.setattr(gate, "_held_looks",
                        (("dining-hues", "hold", 500, None, 100.0),
                         ("hue-lights", "show", None, None, 100.0)))
    hue_freeze.set_pending({"dining-hues", "hue-lights"})
    assert hue_freeze.consume("dining-hues") and hue_freeze.consume("hue-lights")
    out = asyncio.run(house_restart.after_resume())
    assert out == ["hue-lights"]
    assert held.calls == [] and loose.calls == [False]
    assert hue_freeze.pending() == set()


# ── 5. the order in the real lifespan ──────────────────────────────────────

def test_the_lifespan_installs_before_resume_and_decides_before_go_dark():
    from spectra import app
    src = inspect.getsource(app._standalone_lifespan)
    assert src.index("house_restart.prepare_for_resume()") \
        < src.index("handover.resume_own_room()")
    assert src.index("ambient_music_gate.reconcile_now()") \
        < src.index("house_restart.after_resume()")
    tail = src[src.index("yield"):]
    assert tail.index("hold_on_shutdown()") < tail.index("engine.go_dark()")
    assert "live.deactivate(hold_last_frame=hold)" in tail
