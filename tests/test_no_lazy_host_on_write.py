"""A WRITE NEVER STARTS A HOST (2026-10-06 — the deploy restart that came
back with 0 of 5 virtuals up; spectra/services/fx_seam.py's module
docstring is the binding statement).

While a resume was still assembling the live stack, a trigger crossing on
the playing song sent a scene write through fx_seam; fx.facade.handle found
no host installed and STARTED ONE of its own on the default config dir (0
devices), and the real stack then loaded every virtual against an empty
device registry. These tests fire a trigger mid start-up through the real
TriggerEngine and the real fx_seam, with FxHost replaced by a recorder so a
host being started is observable, and prove:

  1. nothing starts a host, the fire is refused and logged, the clock runs on;
  2. the same fire lands once the stack is up (the control);
  3. with the guard removed the harness goes RED — the defect reproduces;
  4. the engine's own FacadeExecutor and the device console hold the line too.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from fx import facade
from fx import light_ownership as lo
from spectra.models.trigger import FireSceneAction, SpectraTrigger
from spectra.services import fx_seam
from spectra.services.live_host import live
from spectra.services.trigger_engine import TriggerEngine

WRITE = {"virtual_id": "v1", "effect_type": "singleColor",
         "config": {"color": "#ff0000"}}


class _HostSpy:
    """Stands in for fx.facade.FxHost: records every host the facade starts."""
    started: list[str] = []

    def __init__(self, config_dir):
        self.config_dir = config_dir

    async def start(self):
        _HostSpy.started.append(self.config_dir)


@pytest.fixture(autouse=True)
def _spectra_owns_and_no_host(tmp_path, monkeypatch):
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")
    lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
    monkeypatch.setattr(facade, "FxHost", _HostSpy)
    _HostSpy.started = []
    facade.set_host(None)
    monkeypatch.setattr(live, "assembling", True, raising=False)
    monkeypatch.setattr(fx_seam, "_not_ready_logged", False)
    yield
    facade.set_host(None)


def _engine(fired_ok: list):
    async def fire_scene(scene_id, color_set_id, intensity):
        await fx_seam.apply_writes([WRITE])
        fired_ok.append(scene_id)

    return TriggerEngine(
        list_triggers=lambda uri: [SpectraTrigger(
            id="mid-start", timestamp_ms=1000, source="authored",
            action=FireSceneAction(scene_id="S", intensity=0.6))],
        scene_change_mode=lambda: "full", fire_scene=fire_scene,
        lead_ms=lambda t: 0, sequencer_enabled=lambda: False,
        render_intensity=lambda x: x,
        drop_view=lambda uri, trs: {"sequences": [], "authored": []})


async def _cross(eng):
    await eng.on_track_state("song:mid-start")
    for pos in (800, 1000, 1200):
        await eng.tick(pos)


def test_a_trigger_mid_start_up_starts_no_host_and_is_refused(caplog):
    fired: list = []
    eng = _engine(fired)
    with caplog.at_level(logging.WARNING):
        asyncio.run(_cross(eng))
    assert _HostSpy.started == [], "a write started a host of its own"
    assert facade._host is None
    assert fired == []
    assert eng.last_fire == {"id": "mid-start", "kind": "fire_scene", "ok": False}
    warnings = [r for r in caplog.records
                if "still starting" in r.getMessage() and r.name.endswith("fx_seam")]
    assert len(warnings) == 1, "logged once, not per write"


def test_every_seam_primitive_refuses_while_starting():
    async def go():
        for call in (fx_seam.apply_writes([WRITE]), fx_seam.get_virtuals(),
                     fx_seam.set_virtual_config("v1", {"dark_lock": True}),
                     fx_seam.set_virtual_active("v1", True),
                     fx_seam.set_virtual_effect("v1", "singleColor", {})):
            with pytest.raises(fx_seam.HostNotReady):
                await call
    asyncio.run(go())
    assert _HostSpy.started == []
    # every caller that already handles a handover handles this the same way
    assert issubclass(fx_seam.HostNotReady, fx_seam.HandoverInProgress)


def test_the_same_fire_lands_once_the_stack_is_up(monkeypatch):
    seen = []

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {}

    async def fake_handle(method, path, *, json=None, **_kw):
        seen.append((method, path))
        return _Resp()

    monkeypatch.setattr(facade, "handle", fake_handle)
    facade.set_host(object())
    monkeypatch.setattr(live, "assembling", False, raising=False)
    fired: list = []
    asyncio.run(_cross(_engine(fired)))
    assert fired == ["S"]
    assert ("PUT", "/api/virtuals/v1/effects") in seen
    assert _HostSpy.started == []


def test_without_the_guard_the_defect_reproduces(monkeypatch):
    """The red control: the pre-fix seam (no readiness check) lets the same
    mid-start-up fire reach the facade, which starts a host of its own on
    the default config dir — the empty host of the 14:50 restart."""
    monkeypatch.setattr(fx_seam, "facade_host_ready", lambda: True)
    asyncio.run(_cross(_engine([])))
    assert len(_HostSpy.started) == 1


def test_the_engine_executor_writes_nothing_while_starting(monkeypatch):
    from spectra.services.fx_executor import FacadeExecutor
    called = []

    async def fake_handle(*a, **k):
        called.append(a)
        raise AssertionError("the executor reached the facade mid start-up")

    monkeypatch.setattr(facade, "handle", fake_handle)
    ex = FacadeExecutor(clock=lambda: 0.0)
    asyncio.run(ex.glide("v1", "radial", {"spin": 0.4}, 500))
    asyncio.run(ex.jump("v1", "radial", {"spin": 0.1}))
    assert called == [] and _HostSpy.started == []
    assert len(ex.writes) == 2, "the engine still models the writes"


def test_the_device_console_refuses_a_live_edit_while_starting(monkeypatch):
    from spectra.services import device_console
    monkeypatch.setattr(device_console, "_live_host", lambda: object())

    async def fake_handle(*a, **k):
        raise AssertionError("the device console reached the facade mid start-up")

    monkeypatch.setattr(facade, "handle", fake_handle)
    with pytest.raises(device_console.DeviceOpError, match="still starting"):
        asyncio.run(device_console.update_device("dev-1", {"pixel_count": 64}))
    assert _HostSpy.started == []
