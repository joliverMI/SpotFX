"""FxHost — the in-process stand-in for LedFxCore (SpotFX-authored).

The vendored render pipeline (fx/virtuals.py, fx/devices/, fx/effects/) was
written against a `ledfx` core object. FxHost provides exactly the attributes
that code touches — config, config_dir, loop, thread_executor, events,
devices, effects, virtuals, scenes, colors, gradients, audio — and none of
the dropped subsystems (aiohttp server, zeroconf, integrations, tray,
sendspin). It runs on the caller's asyncio loop; it never creates one.

Wiring order mirrors LedFxCore.async_start (fork core.py:542-579) minus the
dropped subsystems. Contract:

    host = FxHost(config_dir)          # from a running event loop
    await host.start()                 # devices + virtuals from config
    ...
    await host.shutdown()              # deactivate virtuals + devices

config_dir is an fx-owned directory (never the live LedFX ~/.ledfx): the
vendored config.py reads/creates `config.json` there, and vendored handlers
persist through fx.config.save_config into it.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fx.color import (
    LEDFX_COLORS,
    LEDFX_GRADIENTS,
    parse_color,
    parse_gradient,
    validate_color,
    validate_gradient,
)
from fx.config import load_config, load_logger
from fx.devices import Devices
from fx.effects import Effects
from fx.events import Events, LedFxShutdownEvent
from fx.scenes import Scenes
from fx.utils import UserDefaultCollection
from fx.virtuals import Virtuals

logger = logging.getLogger(__name__)


# Device types whose activation touches no network or hardware. Everything
# else (hue/ddp/wled/e131) streams to the room and falls under the light
# ownership rule: never constructed without a live ActivationGrant.
SAFE_DEVICE_TYPES = frozenset({"dummy"})

# The driver modules vendored under fx/devices/. A config device of any other
# type is skipped by the registry at host start (warning, not error) — so for
# readiness checks a virtual is only usable if a device of one of THESE types
# backs it. Kept in lockstep with the fx/devices/ package contents; the
# fx-live seeder and the handover readiness gate both read this set.
#
# `udp` (fx/devices/udp.py, registered as "udp" by UDPRealtimeDevice) was
# missing here until 2026-08-28 while its driver was vendored, registered,
# and reachable — a WLED device with sync_mode="UDP" already runs on it as a
# subdevice. It is added now because the device edit/create page offers it
# (fx/device_schema.py reads this set), and offering a type the readiness
# gate would then refuse to count as usable is a trap. A udp-backed virtual
# now counts toward readiness exactly like a ddp-backed one, which is what
# the set's own "lockstep with the package contents" rule always said.
VENDORED_DEVICE_TYPES = frozenset({"dummy", "ddp", "udp", "wled", "e131", "hue"})


class FxHost:
    def __init__(self, config_dir: str, live_grant=None):
        load_logger()  # fx/config.py's own init hook: binds its module logger
        self._live_grant = live_grant
        self.config_dir = config_dir
        self.config = load_config(config_dir)
        self.loop = asyncio.get_running_loop()
        self.thread_executor = ThreadPoolExecutor(
            thread_name_prefix="fx-host"
        )
        self.events = Events(self)
        self.devices = Devices(self)
        self.effects = Effects(self)  # sets self.audio = None
        self.virtuals = Virtuals(self)
        # Virtuals is a singleton surviving across FxHost instances (tests
        # build several); reset rebinds it to this host and empties the
        # registry.
        self.virtuals.reset_for_core(self)
        self.scenes = Scenes(self)
        self.colors = UserDefaultCollection(
            self, "Colors", LEDFX_COLORS, "user_colors",
            validate_color, parse_color,
        )
        self.gradients = UserDefaultCollection(
            self, "Gradients", LEDFX_GRADIENTS, "user_gradients",
            validate_gradient, parse_gradient,
        )
        self._started = False

    async def start(self) -> None:
        """Instantiate devices and virtuals from the fx config file.

        Light ownership gate (SPECTRA S3), enforced in the construction path:
        a config with any non-dummy device is the live room, and starting it
        requires an ActivationGrant that is valid against the ownership
        record RIGHT NOW (fx/light_ownership.py). Headless/dummy configs are
        untouched — no grant, no record read."""
        live_types = sorted(
            {d.get("type") for d in self.config["devices"]} - SAFE_DEVICE_TYPES
        )
        if live_types:
            from fx import light_ownership
            light_ownership.require_grant(
                self._live_grant, light_ownership.SPECTRA,
                detail=f"device types {live_types}",
            )
        self.devices.create_from_config(self.config["devices"])
        await self.devices.async_initialize_devices()
        self.virtuals.create_from_config(self.config["virtuals"])
        self._started = True
        logger.info(
            "FxHost started: %d devices, %d virtuals (config_dir=%s)",
            len(list(self.devices.values())),
            len(list(self.virtuals.values())),
            self.config_dir,
        )

    async def shutdown(self) -> None:
        """Deactivate every virtual (joins render threads) and device.
        Does NOT cancel unrelated loop tasks — unlike LedFxCore.async_stop,
        which kills every task on the loop and can never run inside SpotFX.

        Devices are deactivated via async_deactivate_devices(), AWAITED,
        before the thread executor is shut down. Some drivers (Hue, WLED)
        fire an unawaited device-stop coroutine from their plain deactivate()
        for other (non-teardown) callers; here that coroutine would never
        even get scheduled before thread_executor.shutdown() ran out from
        under it (`RuntimeError: cannot schedule new futures after
        shutdown`), silently dropping the bridge/API stop call — see
        fx/VENDOR.md, "Hue entertainment-stream stop dropped at teardown".

        LedFxShutdownEvent fires LAST, after devices are already down, not
        first: Devices.__init__ registers its own listener for this event
        (vendored) that redundantly calls the plain, fire-and-forget
        deactivate_devices() again — firing the event before our own
        graceful pass raced it against async_deactivate_devices() (whichever
        ran first on the loop won, and either the graceful await got
        skipped as a no-op or its own fire-and-forget got dropped the same
        way). Devices are idempotent once deactivated (fx/VENDOR.md
        deviation 8), so a redundant listener-triggered deactivate() firing
        after this point is a safe no-op."""
        for virtual in list(self.virtuals.values()):
            try:
                virtual.deactivate()
            except Exception:
                logger.exception("FxHost: virtual %s deactivate failed", virtual.id)
        await self.devices.async_deactivate_devices()
        self.events.fire_event(LedFxShutdownEvent())
        self.thread_executor.shutdown(wait=False, cancel_futures=True)
        self._started = False

    # Vendored code probes these on the core object:

    def dev_enabled(self) -> bool:
        # False keeps RegistryLoader from starting watchdog file observers.
        return False

    def stop(self, exit_code: int = 0) -> None:
        """LedFxCore.stop kills the process's loop; inside SpotFX that must
        never happen. The only vendored caller is the audio layer's fatal
        sounddevice path — log it loudly and leave the app running."""
        logger.critical(
            "FxHost.stop(%s) called by vendored code — refusing to stop the "
            "SpotFX process; audio input is now unavailable", exit_code,
        )
