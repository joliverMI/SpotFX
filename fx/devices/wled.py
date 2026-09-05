import asyncio
import logging
import socket

import requests
import voluptuous as vol

from fx import device_identity
from fx.devices import NetworkedDevice
from fx.devices.ddp import DDPDevice
from fx.devices.e131 import E131Device
from fx.devices.udp import UDPRealtimeDevice
from fx.utils import WLED, wled_support_DDP

_LOGGER = logging.getLogger(__name__)

#: How long ONE identity probe (`json/info` at a candidate address) may take.
#: A sweep makes many of these, so it is deliberately the same short budget
#: `WLED._wled_request` already uses rather than a second, looser one.
IDENTITY_PROBE_TIMEOUT_S = 0.5


def read_info(address: str, timeout: float):
    """One `json/info` GET, returning the body or None. Never raises: for an
    identity probe "did not answer" and "answered something else" are the
    same non-answer, and the caller is sweeping addresses that mostly are
    not there. Blocking on purpose — every caller runs it in an executor,
    because `WLED._wled_request` is an `async def` that calls `requests`
    directly and would park the render loop for the whole timeout."""
    try:
        response = requests.get(f"http://{address}/json/info", timeout=timeout)
    except requests.exceptions.RequestException:
        return None
    if not response.ok:
        return None
    try:
        return response.json()
    except ValueError:
        return None


async def discover_peer_addresses(
        devices, executor=None,
        timeout: float = IDENTITY_PROBE_TIMEOUT_S):
    """Every address a REACHABLE WLED already knows about, from its own
    `json/nodes`. WLEDs discover each other over their sync protocol, so one
    fixture that still answers can name the one that moved — a handful of
    candidates to check instead of a subnet to sweep. Best-effort and never
    raising: a device that will not answer simply contributes nothing."""
    reachable = [d for d in devices
                 if getattr(d, "_destination", None)]
    if not reachable:
        return []
    loop = asyncio.get_running_loop()
    results = await asyncio.gather(*(
        loop.run_in_executor(executor, read_node_addresses,
                             d._destination, timeout)
        for d in reachable), return_exceptions=True)
    found: list[str] = []
    for result in results:
        if not isinstance(result, list):
            continue
        for address in result:
            if address not in found:
                found.append(address)
    return found


def read_node_addresses(address: str, timeout: float):
    """The IPs in one WLED's `json/nodes`, or []. Blocking; see
    `read_info` for why every caller uses an executor."""
    try:
        response = requests.get(f"http://{address}/json/nodes",
                                timeout=timeout)
    except requests.exceptions.RequestException:
        return []
    if not response.ok:
        return []
    try:
        body = response.json()
    except ValueError:
        return []
    nodes = body.get("nodes") if isinstance(body, dict) else None
    if not isinstance(nodes, list):
        return []
    return [n["ip"] for n in nodes
            if isinstance(n, dict) and isinstance(n.get("ip"), str) and n["ip"]]


class WLEDDevice(NetworkedDevice):
    """
    Dedicated WLED device support
    This class fetches its config (px count, etc) from the WLED device
    at launch, and lets the user choose a sync mode to use.

    SPOT-FX DEVIATION (fx/VENDOR.md #33): a WLED may also be pinned by its
    HARDWARE IDENTITY (`hardware_id`, its MAC), so a device that took a new
    DHCP lease is RE-FOUND rather than reported dead. See
    `fx/device_identity.py` for the whole mechanism and why the MAC is the
    identity. Absent a stored `hardware_id` every path here behaves exactly
    as it did before the field existed.
    """

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "sync_mode",
                description="Streaming protocol to WLED device. Recommended: DDP for 0.13 or later. Use UDP for older versions.",
                default="DDP",
            ): vol.In(["DDP", "UDP", "E131"]),
            vol.Optional(
                "timeout",
                description="Time between LedFx effect off and WLED effect activate",
                default=1,
            ): vol.All(int, vol.Range(0, 255)),
            vol.Optional(
                "create_segments",
                description="Import WLED segments into LedFx",
                default=False,
            ): bool,
            vol.Optional(
                "icon_name",
                description="Icon for the device*",
                default="wled",
            ): str,
            vol.Optional(
                "hardware_id",
                description=(
                    "The device's MAC — its identity, so it can be re-found "
                    "after its IP address changes. Learned automatically on "
                    "first contact; leave blank to pin by address only."
                ),
                default="",
            ): str,
        }
    )

    SYNC_MODES = {
        "UDP": UDPRealtimeDevice,
        "DDP": DDPDevice,
        "E131": E131Device,
    }

    def __init__(self, ledfx, config):
        super().__init__(ledfx, config)
        self.subdevice = None
        self.wled = None

        # moved DEVICE_CONFIGS class var to device_configs instance var as it is manipulated in seperate instances
        # see https://github.com/LedFx/LedFx/pull/237
        self.device_configs = {
            "UDP": {
                "name": None,
                "ip_address": None,
                "pixel_count": None,
                "port": 21324,
                "udp_packet_type": "DNRGB",
                "timeout": 1,
                "minimise_traffic": True,
            },
            "DDP": {
                "name": None,
                "port": 4048,
                "ip_address": None,
                "pixel_count": None,
                "destination_id": 1,
            },
            "E131": {
                "name": None,
                "ip_address": None,
                "pixel_count": None,
                "universe": 1,
                "universe_size": 510,
                "channel_offset": 0,
                "packet_priority": 100,
            },
        }

    def config_updated(self, config):
        if not isinstance(
            self.subdevice, self.SYNC_MODES[self._config["sync_mode"]]
        ):
            self.setup_subdevice()

    def setup_subdevice(self):
        if self.subdevice is not None:
            self.subdevice.deactivate()

        device = self.SYNC_MODES[self._config["sync_mode"]]
        config = self.device_configs[self._config["sync_mode"]]
        config["name"] = self._config["name"]
        config["ip_address"] = self._config["ip_address"]
        config["pixel_count"] = self._config["pixel_count"]
        config["refresh_rate"] = self._config["refresh_rate"]

        self.subdevice = device(self._ledfx, config)
        self.subdevice._destination = self._destination

    def activate(self):
        if self.subdevice is None:
            self.setup_subdevice()
        self.subdevice.activate()
        super().activate()

    def deactivate(self):
        # Idempotent — see HueDevice.deactivate()'s comment: several code
        # paths can each try to deactivate the same device during one
        # teardown; only the first should dispatch the release.
        if self._teardown_dispatched:
            return
        if self.subdevice is not None:
            self.subdevice.deactivate()
        if self.wled is not None:
            # Explicit release (panic-release path), not just "stop sending
            # and let the device's own timeout lapse" — see WLED.
            # release_realtime. Fire-and-forget like the Hue driver's stream
            # stop: deactivate() must never block on device I/O — the
            # dispatched Task is remembered on the instance so a subsequent
            # async_deactivate() can await it (see Device._dispatch_
            # teardown_task / HueDevice.deactivate() for why).
            self._dispatch_teardown_task(self._async_release_realtime())
        super().deactivate()

    async def _async_release_realtime(self):
        try:
            await self.wled.release_realtime()
        except Exception as e:
            _LOGGER.warning(
                "WLED %s: failed to release realtime mode: %s", self.name, e
            )

    async def resolve_address(self, success_callback=None):
        await super().resolve_address(success_callback)
        if self.subdevice is not None:
            self.subdevice._destination = self._destination

    def flush(self, data):
        self.subdevice.flush(data)

    async def add_postamble(self):
        _LOGGER.debug("Doing post creation things for WLED...")
        if (
            self.config["create_segments"]
            or self._ledfx.config["create_segments"]
        ):
            segments = await self.wled.get_segments()
            isMatrix = segments[0].get("stopY", 0) > 0
            if len(segments) > 1 or isMatrix:
                for seg in segments:
                    if seg["stop"] - seg["start"] > 0:
                        name = seg.get("n", f'Seg-{seg["id"]}')
                        rows = seg.get("stopY", 1)
                        if not rows > 1:
                            self.sub_v(
                                name,
                                None,
                                [[seg["start"], rows * (seg["stop"] - 1)]],
                                rows,
                            )

    # ── identity (fx/VENDOR.md #33) ─────────────────────────────────────

    @property
    def hardware_id(self):
        """This device's stored identity (a normalized MAC), or None. None
        means "pinned by address only" — every identity path is then a
        no-op and this driver is byte-identical to the fork's."""
        return device_identity.normalize_mac(self._config.get("hardware_id"))

    def learn_identity(self, wled_info):
        """Stamp the MAC off a `json/info` we just received, if we do not
        already have one. LAZY BY DESIGN: nothing rewrites his config to add
        this field — it arrives on the device object the first time the
        fixture is actually contacted, and rides out to disk on the next
        ordinary save, the same way `name`/`pixel_count`/`rgbw_led` already
        do a few lines below. Returns the MAC when this call learned it,
        else None."""
        if self.hardware_id is not None:
            return None
        mac = device_identity.mac_from_info(wled_info)
        if mac is None:
            return None
        self._config["hardware_id"] = mac
        _LOGGER.info("WLED %s: learned hardware id %s", self.name, mac)
        return mac

    def _executor(self):
        return getattr(self._ledfx, "thread_executor", None)

    async def _read_mac(self, address):
        """The MAC at `address`, or None — one `json/info` in an executor.
        `device_identity.locate`'s confirmation step."""
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(
            self._executor(), read_info, address,
            IDENTITY_PROBE_TIMEOUT_S)
        return device_identity.mac_from_info(info)

    async def _resolve_host(self, hostname):
        """A hostname to an address, or None. Deliberately NOT
        `fx.utils.resolve_destination`: that one raises for a name that does
        not resolve, and here a name that does not resolve is an ordinary
        "not this way", not an error to report."""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                self._executor(), socket.gethostbyname, hostname.rstrip("."))
        except (socket.gaierror, OSError, UnicodeError):
            return None

    def adopt_address(self, address):
        """Point every part of this driver at `address` — the device config,
        the resolved destination, the JSON client and the streaming
        subdevice — so a relocated fixture is DRIVEN, not merely re-found.
        The subdevice's own `_destination` is what its flush writes to, so
        missing it would leave frames going to the old address forever."""
        previous = self._config.get("ip_address")
        self._config["ip_address"] = address
        self._destination = address
        self._online = True
        if self.wled is not None:
            self.wled.ip_address = address
        for mode_config in self.device_configs.values():
            mode_config["ip_address"] = address
        if self.subdevice is not None:
            self.subdevice._destination = address
            if isinstance(getattr(self.subdevice, "_config", None), dict):
                self.subdevice._config["ip_address"] = address
        _LOGGER.warning(
            "WLED %s: relocated from %s to %s (matched hardware id %s)",
            self.name, previous, address, self.hardware_id)

    async def reconcile_address(self, peer_addresses=(), sweep=True):
        """Find this device by its identity and adopt wherever it actually
        is. Returns the `Location` (whose `.moved` is False when the pin was
        right all along) or None — None being "no identity stored" or "could
        not find it", never "it is dead". Safe to call on a healthy device:
        the pinned address is checked first and confirming it changes
        nothing."""
        mac = self.hardware_id
        if mac is None:
            return None
        location = await device_identity.locate(
            mac,
            pinned_address=self._config.get("ip_address"),
            read_mac=self._read_mac,
            resolve_host=self._resolve_host,
            peer_addresses=tuple(peer_addresses),
            sweep=sweep,
        )
        if location is not None and location.moved:
            self.adopt_address(location.address)
        return location

    async def _contact(self):
        """The device's own config, contacting it at the pinned address and
        — only if that fails and only if we know what this device IS —
        again at wherever its identity says it now lives. When there is no
        identity to fall back on, the original error is re-raised verbatim:
        this must not turn a real "device is off" into a different
        message."""
        self.wled = WLED(self._destination)
        try:
            if self._destination is None:
                raise ValueError(
                    f"WLED {self.name}: address did not resolve")
            return await self.wled.get_config()
        except Exception as first:
            if self.hardware_id is None:
                raise
            _LOGGER.info(
                "WLED %s: %s at %s — looking for it by hardware id",
                self.name, first, self._config.get("ip_address"))
            location = await self.reconcile_address()
            if location is None or not location.moved:
                raise first
            self.wled = WLED(self._destination)
            return await self.wled.get_config()

    async def async_initialize(self):
        await super().async_initialize()
        # if not self._destination:
        #     self.setup_subdevice()
        #     return
        wled_config = await self._contact()
        self.learn_identity(wled_config)

        led_info = wled_config["leds"]
        wled_name = wled_config["name"]
        wled_count = led_info["count"]
        wled_rgbmode = led_info["rgbw"]
        wled_build = wled_config["vid"]

        wled_config = {
            "name": wled_name,
            "pixel_count": wled_count,
            "rgbw_led": wled_rgbmode,
        }

        self._config.update(wled_config)
        self.setup_subdevice()

        # Currently *assuming* that this PR gets released in 0.13
        # https://github.com/Aircoookie/WLED/pull/1944
        if wled_support_DDP(wled_build):
            _LOGGER.info(
                "WLED Build Supports Sync Setting API: %s", wled_build
            )
            await self.wled.get_sync_settings()
        # self.wled.enable_realtime_gamma()
        # self.wled.set_inactivity_timeout(self._config["timeout"])
        # self.wled.first_universe()
        # self.wled.first_dmx_address()
        # self.wled.multirgb_dmx_mode()

        # await self.wled.flush_sync_settings()
