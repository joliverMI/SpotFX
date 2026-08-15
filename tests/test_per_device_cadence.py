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

        # The fast device shares the render loop's own rate (render_rate ==
        # FAST_FPS), so its gate threshold exactly matches the loop's own
        # tick period — near-exact parity, tight tolerance. (A loose
        # 0.5x-1.3x band here previously let a real ~2x regression pass
        # silently — confirmed live 2026-08-14: deploying an earlier gate
        # that used a naive 1.0/fps threshold instead of fps_to_sleep_
        # interval() near-halved throughput for EVERY device in the room,
        # including ones this fix should never touch.)
        assert FAST_FPS * 0.85 <= fast_count <= FAST_FPS * 1.15, fast_count

        # The slow device is the slower member of a MIXED virtual, so it can
        # only be serviced at the (faster) loop's own tick boundaries — its
        # gate threshold (fps_to_sleep_interval(30) ~= 0.033s) doesn't evenly
        # divide the loop's own tick period (fps_to_sleep_interval(62) ~=
        # 0.016s), so the achieved rate rounds UP to the next available
        # tick (~0.048s -> ~21fps), not its exact nominal 30. This is an
        # inherent, disclosed consequence of one shared render loop paced
        # to per-device delivery (see fx/VENDOR.md deviation 11) — never
        # faster than nominal, and bounded well clear of the ~2x-regression
        # range (which would land near 10-15) this test guards against.
        assert 15 <= slow_count <= 26, slow_count

        # Critically, the fast device was NOT dragged down to the slow
        # device's cadence: this is the regression the fix closes.
        assert fast_count > slow_count * 2, (slow_count, fast_count)

        assert slow_device.max_refresh_rate == SLOW_FPS
        assert fast_device.max_refresh_rate == FAST_FPS

    asyncio.run(main())


def test_homogeneous_single_device_virtual_is_unaffected(tmp_path):
    """Crystal's ACTUAL current room topology: Crystal-Mapper has no other
    real device, so render_rate == refresh_rate and this fix must be a
    complete no-op — near-exact parity with the configured rate. This is
    the tightest possible regression guard: the ~2x-regression bug found
    live 2026-08-14 degraded this homogeneous case too (it isn't specific
    to mixed virtuals), so a loose tolerance here would have hidden it."""
    import json
    import os

    from fx.consts import CONFIGURATION_VERSION

    device_id = "solo-30"

    async def main():
        config_dir = str(tmp_path / "homogeneous")
        os.makedirs(config_dir, exist_ok=True)
        config = {
            "configuration_version": CONFIGURATION_VERSION,
            "devices": [
                {
                    "id": device_id,
                    "type": "dummy",
                    "config": {
                        "name": device_id,
                        "pixel_count": 8,
                        "refresh_rate": SLOW_FPS,
                    },
                }
            ],
            "virtuals": [
                {
                    "id": device_id,
                    "is_device": device_id,
                    "auto_generated": False,
                    "config": {"name": device_id, "mapping": "span"},
                    "segments": [[device_id, 0, 7, False]],
                    "effect": {"type": "singleColor", "config": {"color": "#ffffff"}},
                }
            ],
        }
        with open(os.path.join(config_dir, "config.json"), "w") as f:
            json.dump(config, f)

        headless.silence_audio()
        host = FxHost(config_dir)
        host.audio = headless.SyntheticAudioSource()
        await host.start()

        virtual = host.virtuals.get(device_id)
        assert virtual.refresh_rate == SLOW_FPS
        assert virtual.render_rate == SLOW_FPS  # single device: min == max

        counts = {"n": 0}

        def on_update(event) -> None:
            if event.device_id == device_id:
                counts["n"] += 1

        remove = host.events.add_listener(on_update, Event.DEVICE_UPDATE)
        try:
            virtual.active = True
            await asyncio.sleep(1.0)
        finally:
            virtual.deactivate()
            remove()
            await host.shutdown()

        # Tight tolerance: this must land essentially at nominal, not at
        # roughly half of it.
        assert SLOW_FPS * 0.85 <= counts["n"] <= SLOW_FPS * 1.15, counts["n"]

    asyncio.run(main())
