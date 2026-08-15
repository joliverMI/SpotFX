"""Proof for the per-device cadence fix (fx/VENDOR.md deviation): a virtual
combining a deliberately slow device with a faster one must deliver each
device real network flushes at ITS OWN configured refresh_rate, not the
slowest member's — the bug named in
data/spectra-crystal-colour-lag/report.md (Virtual.refresh_rate used to be
both the render-loop clock AND the per-device flush ceiling; min() across a
virtual's devices meant one slow device forced every sibling in the SAME
virtual down to its cadence).

Headless/offline by construction (fx/headless.py): two DummyDevices, one
virtual, real per-virtual render thread (Live mode), real wall-clock pacing.
No network I/O, no live room access — see fx/headless.py's own docstring.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless
from fx.events import Event
from fx.host import FxHost

SLOW_ID = "slow-30"
FAST_ID = "fast-62"
VIRTUAL_ID = "mixed-cadence"
SLOW_FPS = 30
FAST_FPS = 62
SLOW_PIXELS = 8
FAST_PIXELS = 8


def _write_mixed_config(config_dir: str) -> None:
    import json
    import os

    from fx.consts import CONFIGURATION_VERSION

    os.makedirs(config_dir, exist_ok=True)
    config = {
        "configuration_version": CONFIGURATION_VERSION,
        "devices": [
            {
                "id": SLOW_ID,
                "type": "dummy",
                "config": {
                    "name": SLOW_ID,
                    "pixel_count": SLOW_PIXELS,
                    "refresh_rate": SLOW_FPS,
                },
            },
            {
                "id": FAST_ID,
                "type": "dummy",
                "config": {
                    "name": FAST_ID,
                    "pixel_count": FAST_PIXELS,
                    "refresh_rate": FAST_FPS,
                },
            },
        ],
        "virtuals": [
            {
                "id": VIRTUAL_ID,
                "is_device": False,
                "auto_generated": False,
                "config": {"name": VIRTUAL_ID, "mapping": "span"},
                "segments": [
                    [SLOW_ID, 0, SLOW_PIXELS - 1, False],
                    [FAST_ID, 0, FAST_PIXELS - 1, False],
                ],
                "effect": {"type": "singleColor", "config": {"color": "#ffffff"}},
            }
        ],
    }
    with open(os.path.join(config_dir, "config.json"), "w") as f:
        json.dump(config, f)


class _DeviceUpdateCounter:
    """Counts real DeviceUpdateEvent flushes per device_id — fired only when
    Device.update_pixels() actually calls self.flush(), i.e. after the
    per-device pacing gate clears (fx/devices/__init__.py)."""

    def __init__(self, host: FxHost):
        self.counts: dict[str, int] = {SLOW_ID: 0, FAST_ID: 0}

        def on_update(event) -> None:
            if event.device_id in self.counts:
                self.counts[event.device_id] += 1

        self._remove = host.events.add_listener(on_update, Event.DEVICE_UPDATE)

    def close(self) -> None:
        if callable(self._remove):
            self._remove()


def test_fast_device_not_capped_to_slow_siblings_rate(tmp_path):
    async def main():
        config_dir = str(tmp_path / "mixed")
        _write_mixed_config(config_dir)
        headless.silence_audio()
        host = FxHost(config_dir)
        host.audio = headless.SyntheticAudioSource()
        await host.start()

        virtual = host.virtuals.get(VIRTUAL_ID)
        slow_device = host.devices.get(SLOW_ID)
        fast_device = host.devices.get(FAST_ID)

        # The min()-across-devices ceiling is preserved as a distinct
        # property (still used by Device.refresh_rate/priority_virtual) —
        # only the render loop's own clock and per-device flush pacing
        # change.
        assert virtual.refresh_rate == SLOW_FPS
        assert virtual.render_rate == FAST_FPS

        counter = _DeviceUpdateCounter(host)
        try:
            virtual.active = True  # spawns the real per-virtual render thread
            assert virtual._thread.is_alive()
            await asyncio.sleep(1.0)
        finally:
            virtual.deactivate()
            counter.close()
            await host.shutdown()

        slow_count = counter.counts[SLOW_ID]
        fast_count = counter.counts[FAST_ID]

        # Each device flushed at roughly its OWN configured rate over the
        # ~1s window (generous tolerance for CI/scheduler jitter)...
        assert SLOW_FPS * 0.5 <= slow_count <= SLOW_FPS * 1.3, slow_count
        assert FAST_FPS * 0.5 <= fast_count <= FAST_FPS * 1.3, fast_count
        # ...and critically, the fast device was NOT dragged down to the
        # slow device's cadence: this is the regression this fix closes.
        assert fast_count > slow_count * 1.5, (slow_count, fast_count)

        assert slow_device.max_refresh_rate == SLOW_FPS
        assert fast_device.max_refresh_rate == FAST_FPS

    asyncio.run(main())
