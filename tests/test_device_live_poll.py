"""device_gaps() polls each unconfirmed device until live or a shared
deadline, instead of snapshotting once — the race this closes: a real
take-back's WLEDs start receiving realtime SLOWLY and in VARYING ORDER
(first live flags measured 6.2-6.4s after activation, different subsets
first on different attempts), so a one-shot live-flag read raced the ramp
and nondeterministically named whichever devices hadn't come up YET.

Exercises LiveLights.device_gaps() directly against a minimal fake host
(fake virtuals + fake WLED devices) rather than a real FxHost/WLED socket —
the polling logic under test lives entirely in device_gaps() itself.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra.services.live_host import LiveLights


class _FakeVirtual:
    def __init__(self, segments):
        self._segments = segments


class _FakeWled:
    """live flips true after `rises_after` polls; `unreachable` raises on
    every read instead."""

    def __init__(self, rises_after=None, unreachable=False):
        self._rises_after = rises_after
        self._unreachable = unreachable
        self.calls = 0

    async def get_state(self):
        self.calls += 1
        if self._unreachable:
            raise ConnectionError("no route to device")
        live = self._rises_after is not None and self.calls >= self._rises_after
        return {"live": live}


class _FakeDevice:
    def __init__(self, wled):
        self.type = "wled"
        self.wled = wled


class _FakeHost:
    def __init__(self, virtuals, devices):
        self.virtuals = virtuals
        self.devices = devices


def _run(coro):
    return asyncio.run(coro)


def _live_lights(virtuals, devices, expected_active_ids):
    live = LiveLights()
    live.host = _FakeHost(virtuals, devices)
    live.expected_active_ids = expected_active_ids
    return live


def test_device_that_rises_within_deadline_verifies_clean():
    # Rises on the 3rd poll (~ poll_interval_s * 2 in) — well inside the
    # deadline, standing in for the measured 6-8s real-world ramp.
    wled = _FakeWled(rises_after=3)
    live = _live_lights(
        {"v1": _FakeVirtual([("dev-a", 0, 15, False)])},
        {"dev-a": _FakeDevice(wled)},
        {"v1"},
    )

    async def main():
        gaps = await live.device_gaps(deadline_s=1.0, poll_interval_s=0.05)
        assert gaps == {}
        assert wled.calls >= 3

    _run(main())


def test_device_still_dark_at_deadline_is_named():
    wled = _FakeWled(rises_after=None)  # never goes live
    live = _live_lights(
        {"v1": _FakeVirtual([("dev-a", 0, 15, False)])},
        {"dev-a": _FakeDevice(wled)},
        {"v1"},
    )

    async def main():
        gaps = await live.device_gaps(deadline_s=0.2, poll_interval_s=0.05)
        assert "dev-a" in gaps
        assert "live=false" in gaps["dev-a"]

    _run(main())


def test_unreachable_device_keeps_could_not_confirm_naming_at_deadline():
    wled = _FakeWled(unreachable=True)
    live = _live_lights(
        {"v1": _FakeVirtual([("dev-a", 0, 15, False)])},
        {"dev-a": _FakeDevice(wled)},
        {"v1"},
    )

    async def main():
        gaps = await live.device_gaps(
            timeout_s=0.05, deadline_s=0.2, poll_interval_s=0.05)
        assert "dev-a" in gaps
        assert "could not confirm live state" in gaps["dev-a"]

    _run(main())


def test_mixed_devices_only_names_the_one_still_dark():
    rising = _FakeWled(rises_after=2)
    stuck = _FakeWled(rises_after=None)
    live = _live_lights(
        {
            "v1": _FakeVirtual([("dev-a", 0, 15, False)]),
            "v2": _FakeVirtual([("dev-b", 0, 15, False)]),
        },
        {"dev-a": _FakeDevice(rising), "dev-b": _FakeDevice(stuck)},
        {"v1", "v2"},
    )

    async def main():
        gaps = await live.device_gaps(deadline_s=0.3, poll_interval_s=0.05)
        assert "dev-a" not in gaps
        assert "dev-b" in gaps

    _run(main())
