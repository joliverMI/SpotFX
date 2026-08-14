"""Spec for the Hue entertainment-stream stop-at-teardown fix.

Root cause (spectra-hue-bridge/report.md, fx/VENDOR.md deviation 8):
HueDevice.deactivate() fires the bridge's `action: stop` PUT off the event
loop via async_fire_and_forget(), which only *schedules* the coroutine to
start on a later loop iteration. FxHost.shutdown() used to call plain
deactivate() and immediately shut its ThreadPoolExecutor down with no
intervening await, so the scheduled stop coroutine never got a chance to
even start before `run_in_executor` raised "cannot schedule new futures
after shutdown" — the bridge was never told the stream ended and held the
entertainment session open until its own idle timeout lapsed.

These tests prove:
  1. FxHost.shutdown() now delivers the stop before the executor is torn
     down, on a device whose plain deactivate() would have dropped it.
  2. The "cannot schedule new futures after shutdown" failure mode is
     structurally unreachable through FxHost.shutdown() — no warning is
     logged and the stop actually lands.
  3. HueDevice.async_deactivate() itself (independent of FxHost) awaits the
     bridge stop rather than dropping it under the same immediate-executor-
     shutdown conditions that reproduce the original bug on the old
     fire-and-forget deactivate().

No network I/O: HueDevice._blocking_stop is monkeypatched away from
requests(); DTLS/mbedtls objects are never constructed (no activate()
call), keeping this test offline per project convention.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx.devices.hue import HueDevice
from fx.host import FxHost


class _FakeLedfx:
    """Just enough of the FxHost surface HueDevice touches."""

    def __init__(self, loop, thread_executor):
        self.loop = loop
        self.thread_executor = thread_executor


def _make_hue_device(ledfx, stop_calls):
    config = {
        "name": "Dining Hues",
        "ip_address": "192.168.40.28",
        "group_name": "Dining",
        "entertainment_id": "test-ent-id",
        "hue_application_id": "test-app-id",
        "clientkey": "aa" * 16,
        "udp_port": 2100,
    }
    device = HueDevice.__new__(HueDevice)
    # Bypass HueDevice.__init__ (mbedtls DTLS context construction, bridge
    # registration probes) — this test only exercises deactivate/stop.
    device._ledfx = ledfx
    device._config = config
    device._device_type = "Hue"
    device._reconnect_lock = __import__("threading").Lock()
    device._reconnecting = False
    device._stream_ready = False
    device._last_reconnect_attempt = 0.0
    device._frozen = False
    device._sock = None
    device.status = {}
    device._active = True  # streaming, as it is whenever a real teardown deactivates it
    device._pixels = None
    device._id = "dining-hues"
    device._type = "hue"

    def _blocking_stop():
        stop_calls.append(True)

    device._blocking_stop = _blocking_stop
    return device


def test_async_deactivate_delivers_stop_before_immediate_executor_shutdown():
    """HueDevice.async_deactivate(), awaited, gets the stop PUT sent even
    when the caller shuts the executor down the instant it returns — the
    exact teardown shape that used to drop it via fire-and-forget."""
    stop_calls = []

    async def scenario():
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(thread_name_prefix="test-hue")
        ledfx = _FakeLedfx(loop, executor)
        device = _make_hue_device(ledfx, stop_calls)

        await device.async_deactivate()
        # Old bug shape: executor torn down immediately, no yield point.
        executor.shutdown(wait=False, cancel_futures=True)
        return stop_calls

    result = asyncio.run(scenario())
    assert result == [True], "bridge action:stop must be sent before the executor is shut down"


def test_plain_deactivate_still_fire_and_forgets_for_non_teardown_callers():
    """deactivate() (used by set_effect/flush-thread/check_and_deactivate_
    devices — contexts where the loop keeps running afterward) is
    unchanged: still schedules the stop via async_fire_and_forget rather
    than blocking the caller."""
    stop_calls = []

    async def scenario():
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(thread_name_prefix="test-hue")
        ledfx = _FakeLedfx(loop, executor)
        device = _make_hue_device(ledfx, stop_calls)

        device.deactivate()
        assert stop_calls == [], "deactivate() must not block on the stop call"
        # Give the loop a chance to run the scheduled callback — unlike
        # FxHost.shutdown()'s old bug, nothing tears the executor down here.
        await asyncio.sleep(0.05)
        executor.shutdown(wait=True)
        return stop_calls

    result = asyncio.run(scenario())
    assert result == [True]


def test_fxhost_shutdown_delivers_hue_stop_and_never_logs_schedule_failure(caplog):
    """End-to-end: a Hue-backed device registered on a real FxHost gets its
    stop delivered by host.shutdown(), and the "cannot schedule new futures
    after shutdown" failure is structurally unreachable — it would surface
    as a WARNING from HueDevice._async_stop_stream's except clause."""
    stop_calls = []

    async def scenario(config_dir):
        host = FxHost(config_dir)
        await host.start()

        device = _make_hue_device(host, stop_calls)
        host.devices._objects[device.id] = device

        with caplog.at_level(logging.WARNING):
            await host.shutdown()

        return stop_calls

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        from fx.headless import write_headless_config

        write_headless_config(tmp)
        result = asyncio.run(scenario(tmp))

    assert result == [True], "FxHost.shutdown() must deliver the Hue stop before tearing the executor down"
    assert "cannot schedule new futures after shutdown" not in caplog.text
    assert "failed to stop stream" not in caplog.text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
