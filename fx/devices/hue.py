import asyncio
import logging
import re
import select
import socket
import threading
import time
from typing import Optional

import requests
import voluptuous as vol

# Try to import the optional package
try:
    import mbedtls.tls as tls

    MBEDTLS_AVAILABLE = True
except ImportError:
    MBEDTLS_AVAILABLE = False

from fx.devices import NetworkedDevice
from fx.utils import async_fire_and_forget

_LOGGER = logging.getLogger(__name__)


class HueDevice(NetworkedDevice):
    """
    Philips Hue device support (Entertainment Mode UDP streaming)
    """

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Required(
                "ip_address",
                description="Hostname or IP address of the Hue bridge",
            ): str,
            vol.Required(
                "group_name",
                description="Entertainment zone group name",
            ): str,
            vol.Optional("udp_port", description="port", default=2100): int,
        }
    )

    status: dict[int, tuple[int, int, int]]
    _sock: Optional[socket.socket] = None

    # DTLS handshake is bounded by both an attempt count and a wall-clock
    # deadline so a slow/unreachable bridge can't stall (re)activation forever.
    HANDSHAKE_TOTAL_TIMEOUT = 6.0     # seconds, total budget for the handshake
    HANDSHAKE_MAX_ATTEMPTS = 12       # max do_handshake() tries
    HANDSHAKE_SELECT_TIMEOUT = 0.5    # per-attempt wait for socket readiness

    # Stream activation (HTTPS "start" + DTLS handshake) is serialized across
    # ALL Hue bridges via this class-level lock. Two bridges handshaking at
    # once contend on the GIL/executor and one reliably blows its handshake
    # budget — whichever loses the race then stays dark. Serializing makes each
    # handshake run with the full machine to itself.
    _activation_lock = threading.Lock()

    # A failed activation (e.g. a lost race, or a bridge slow to open the DTLS
    # port after "start") is retried a few times before giving up, so a single
    # timed-out handshake self-heals instead of leaving the device dark.
    ACTIVATION_MAX_ATTEMPTS = 3
    ACTIVATION_RETRY_DELAY = 1.0      # seconds between activation attempts

    # If activation exhausts its retries (e.g. a flaky secondary bridge), the
    # stream stays down and flush() drops frames. Without this, nothing ever
    # retries — the device is dark until the virtual is manually re-activated.
    # So flush() re-arms a reconnect at most once per interval while down.
    RECONNECT_RETRY_INTERVAL = 5.0    # seconds between flush-driven reconnects

    # Every blocking REST call to the bridge runs in loop.run_in_executor on the
    # loop's DEFAULT ThreadPoolExecutor (set in core.py). A request with no
    # timeout blocks its worker forever when the bridge accepts the TCP connect
    # but stalls (flaky/overloaded bridge) — and a hung worker is never returned
    # to the shared pool. Enough of them and the loop's executor is exhausted, so
    # aiohttp's offloaded work (DNS, etc.) stalls and /api/info RTT climbs until
    # SpotFX's watchdog restarts LedFX. Bound every call so a stalled bridge
    # frees its worker instead. (connect, read) seconds.
    REST_TIMEOUT = (3.05, 5.0)

    def __init__(self, ledfx, config):
        super().__init__(ledfx, config)
        self._device_type = "Hue"
        # Stream (re)activation runs off the event loop (see activate()). These
        # guard against concurrent/blocking activation: _reconnecting ensures
        # only one activation is in flight (triggered from either the event loop
        # via set_effect or the virtual render thread via flush); _stream_ready
        # gates socket sends so flush() never touches a half-open socket.
        self._reconnect_lock = threading.Lock()
        self._reconnecting = False
        self._stream_ready = False
        self._last_reconnect_attempt = 0.0
        # When frozen (SpotFX Ambient Mode), the entertainment stream is stopped
        # so the bridge reverts to normal REST-controlled mode, and flush() drops
        # every frame so the bulbs hold whatever was last set via Hue REST. The
        # driving virtual stays ACTIVE and rendering — only this device's output
        # is muted. In-memory only: a LedFX restart clears it (SpotFX re-asserts).
        self._frozen = False
        if not MBEDTLS_AVAILABLE:
            raise Exception(
                "You need to install the python-mbedtls package for Hue to work."
            )

        if "hue_application_id" in self._config:
            # since this is present the init gets called because the device is already known
            self._dtls_client_context = tls.ClientContext(
                tls.DTLSConfiguration(
                    pre_shared_key=(
                        self._config["hue_application_id"],
                        bytes.fromhex(self._config["clientkey"]),
                    ),
                    ciphers=["TLS-PSK-WITH-AES-128-GCM-SHA256"],
                    validate_certificates=False,
                )
            )
        else:
            # The device gets setup for the first time.
            # We call these functions here so the device does only get added if they both succeed!
            # If we won't do that then the device would already be added and a second try wouldn't work
            # until "ledfx" is restartet.
            # But this can't be called if the device is already setup since it would block and the event loop
            # would throw an error. In this case this would get executed in the "async_initialize"
            self._hue_register()
            self._check_hue_bridge()

        self.status = {}

    def _hue_register(self):
        if (self._config.get("username") is None) and (
            self._config.get("clientkey") is None
        ):
            # We need to register this device as application at the Hue Bridge.
            request_data = {
                "devicetype": f"LedFx#{self._config['group_name']}",
                "generateclientkey": True,
            }
            response, _ = self._hue_request("POST", "api", request_data)
            if "success" in response[0]:
                # We successfully registerd
                clientdata = response[0]["success"]
                self.update_config(
                    {
                        "username": clientdata["username"],
                        "clientkey": clientdata["clientkey"],
                    }
                )
            else:
                # The Bridge Link Button needs to be pressed
                raise Exception(
                    "You need to press the Bridge Link Button and retry that again."
                )
        else:
            # We need to check if the credentials are still valid for this device.
            response, _ = self._hue_request(
                "GET", f"api/{self._config['username']}"
            )
            if "error" in response[0]:
                # Credentials are no longer valid - need Bridge Link Button to be pressed and LedFx to be restarted.
                # We delete the invalid credentials here - after a restart a fresh registration will be tried.
                self.update_config({"username": None, "clientkey": None})
                raise Exception(
                    "You need to press the Bridge Link Button and restart LedFx."
                )

    def _check_hue_bridge(self):
        response, _ = self._hue_request("GET", "api/config")
        if response["swversion"] < "1948086000":
            raise Exception(
                "Your Hue Bridge has an outdated Firmware installed. Update it using the Hue App."
            )

    def _hue_request(self, method, api_endpoint, data=None, ssl=False):
        url = f"{'https' if ssl else 'http'}://{self._config['ip_address']}/{api_endpoint}"

        headers = {"hue-application-key": self._config.get("username")}

        # SSL is somehow necessary for some Hue requests but we need to skip the verification since there are no valid certs
        response = getattr(requests, method.lower())(
            url, json=data, verify=not ssl, headers=headers,
            timeout=self.REST_TIMEOUT,
        )

        return response.json(), response.headers

    def _entertainment_groups(self):
        response, _ = self._hue_request(
            "GET", "/clip/v2/resource/entertainment_configuration", ssl=True
        )

        all_groups = response["data"]
        entertainmentZonesCount = len(all_groups)

        if entertainmentZonesCount == 0:
            raise Exception(
                "You did not setup any Entertainment zones. Do that in the Hue App."
            )

        return {group["id"]: group for group in all_groups}

    def _lights_from_entertainment_group(self, entertainment_id):
        response, _ = self._hue_request(
            "GET",
            f"/clip/v2/resource/entertainment_configuration/{entertainment_id}",
            ssl=True,
        )
        lights = dict()
        for channel in response["data"][0]["channels"]:
            lights.update(
                {
                    str(channel["channel_id"]): [
                        channel["position"]["x"],
                        channel["position"]["y"],
                        channel["position"]["z"],
                    ]
                }
            )

        if len(lights) > 20:
            raise Exception(
                f"{len(lights)} lights found. Only 20 are allowed."
            )

        return lights

    def _get_application_id(self):
        _, headers = self._hue_request("GET", "/auth/v1", ssl=True)
        return headers.get("hue-application-id")

    def activate(self):
        # Allocate the pixel buffer / set _active immediately so the render
        # pipeline has somewhere to write, but do the blocking stream setup
        # (HTTP start + DTLS handshake) OFF the event loop — activate() is
        # called on the asyncio loop via set_effect, so any blocking here would
        # freeze LedFX's web server. Actual socket sends are gated on
        # _stream_ready, which only flips true once the handshake succeeds.
        super().activate()
        self._trigger_reconnect()

    def _trigger_reconnect(self):
        """Schedule a single, guarded (re)activation of the entertainment
        stream. Safe to call from either the event loop (activate) or the
        virtual render thread (flush) — async_fire_and_forget hops to the loop
        thread-safely. Debounced via _reconnecting so a dropped stream can't
        spawn a storm of activations."""
        if self._frozen:
            return                          # ambient hold — never re-engage the stream
        with self._reconnect_lock:
            if self._reconnecting:
                return
            self._reconnecting = True
        self._cleanup_socket()
        async_fire_and_forget(
            self._async_activate_stream(), loop=self._ledfx.loop
        )

    async def _async_activate_stream(self):
        """Run the blocking stream setup in the thread executor so the event
        loop stays responsive, then mark the stream ready on success. A failed
        attempt is retried a few times so a single timed-out handshake (e.g. a
        lost race against another bridge) self-heals instead of going dark."""
        try:
            for attempt in range(1, self.ACTIVATION_MAX_ATTEMPTS + 1):
                if not self._active or self._frozen:
                    # Deactivated or frozen while (re)connecting — don't reopen.
                    self._cleanup_socket()
                    return
                try:
                    await self._ledfx.loop.run_in_executor(
                        self._ledfx.thread_executor, self._blocking_activate
                    )
                except Exception as e:
                    self._stream_ready = False
                    self._cleanup_socket()
                    if attempt < self.ACTIVATION_MAX_ATTEMPTS:
                        _LOGGER.debug(
                            "Hue %s: stream activation attempt %d/%d failed "
                            "(%s) — retrying",
                            self.name,
                            attempt,
                            self.ACTIVATION_MAX_ATTEMPTS,
                            e,
                        )
                        await asyncio.sleep(self.ACTIVATION_RETRY_DELAY)
                        continue
                    _LOGGER.warning(
                        "Hue %s: failed to (re)activate entertainment stream "
                        "after %d attempts: %s",
                        self.name,
                        self.ACTIVATION_MAX_ATTEMPTS,
                        e,
                    )
                    return
                if not self._active or self._frozen:
                    # Deactivated/frozen while the handshake was in flight — don't reopen.
                    self._cleanup_socket()
                    return
                self._stream_ready = True
                _LOGGER.info(
                    "Hue %s: entertainment stream activated", self.name
                )
                return
        finally:
            with self._reconnect_lock:
                self._reconnecting = False

    def _blocking_activate(self):
        """Blocking stream setup — runs in a worker thread, never the loop.

        Serialized across all Hue bridges via _activation_lock so concurrent
        bridge activations don't contend and starve each other's handshake."""
        with HueDevice._activation_lock:
            # Tell the bridge to start streaming for this entertainment zone.
            request_data = {"action": "start"}
            self._hue_request(
                "PUT",
                f"/clip/v2/resource/entertainment_configuration/{self._config['entertainment_id']}",
                request_data,
                ssl=True,
            )

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)
            wrapped = self._dtls_client_context.wrap_socket(
                sock, self._config["ip_address"]
            )
            wrapped.connect(
                (self._config["ip_address"], self._config["udp_port"])
            )
            self._do_handshake_with_timeout(wrapped)
            self._sock = wrapped

    def _do_handshake_with_timeout(self, wrapped):
        """Drive the DTLS handshake on a non-blocking socket, waiting on the
        raw fd via select() between attempts. Returns on the first success;
        raises if it can't complete within the attempt/time budget. Replaces
        the old sleep-and-retry loop that blocked for ~2s and never broke on
        success (logging spurious failures)."""
        raw = wrapped._socket          # underlying UDP socket (wrapper has no fileno)
        raw.setblocking(False)
        deadline = time.monotonic() + self.HANDSHAKE_TOTAL_TIMEOUT
        for _ in range(self.HANDSHAKE_MAX_ATTEMPTS):
            if time.monotonic() >= deadline:
                break
            try:
                wrapped.do_handshake()
                return                 # success — no extra iterations, no re-handshake
            except tls.WantReadError:
                select.select([raw], [], [], self.HANDSHAKE_SELECT_TIMEOUT)
            except tls.WantWriteError:
                select.select([], [raw], [], self.HANDSHAKE_SELECT_TIMEOUT)
            except BlockingIOError:    # inner raw recv/send would block ([Errno 11])
                select.select([raw], [], [], self.HANDSHAKE_SELECT_TIMEOUT)
        raise RuntimeError(
            "DTLS handshake to Hue bridge timed out — if this persists, "
            "power-cycle the bridge"
        )

    def _cleanup_socket(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def deactivate(self):
        # Idempotent: several code paths can each try to deactivate the same
        # device during one teardown (a virtual's check_and_deactivate_
        # devices, the vendored LEDFX_SHUTDOWN listener, FxHost's own
        # explicit pass) — only the first should dispatch the bridge stop.
        if self._teardown_dispatched:
            return
        # Stop sends first, cancel any reconnect intent, then tear down.
        self._stream_ready = False
        with self._reconnect_lock:
            self._reconnecting = False
        self._cleanup_socket()

        # Tell the bridge to stop streaming. Offloaded so deactivate (also
        # reachable on the event loop via set_effect) never blocks it — the
        # dispatched Task is remembered on the instance so a subsequent
        # async_deactivate() can await it instead of it being dropped by a
        # caller (FxHost.shutdown) that tears the thread executor down right
        # after deactivate() returns, with no intervening await (fx/VENDOR.md,
        # "Hue entertainment-stream stop dropped at teardown";
        # spectra-hue-bridge/report.md). The bridge, never told the stream
        # ended, then holds the entertainment session open until its own
        # idle timeout lapses — the next activation eats that as a DTLS
        # handshake timeout.
        self._dispatch_teardown_task(self._async_stop_stream())

        super().deactivate()

    async def _async_stop_stream(self):
        try:
            await self._ledfx.loop.run_in_executor(
                self._ledfx.thread_executor, self._blocking_stop
            )
        except Exception as e:
            _LOGGER.warning("Hue %s: failed to stop stream: %s", self.name, e)

    def _blocking_stop(self):
        request_data = {"action": "stop"}
        self._hue_request(
            "PUT",
            f"/clip/v2/resource/entertainment_configuration/{self._config['entertainment_id']}",
            request_data,
            ssl=True,
        )

    @property
    def frozen(self) -> bool:
        """Read-only view of the current freeze state (SpotFX-authored
        accessor, not a fork API — see fx/VENDOR.md deviation list). Lets a
        caller (spectra/services/ambient.py's group-scoped reconcile) tell
        an already-frozen device from one that was never touched, without
        reaching into the private _frozen attribute directly."""
        return self._frozen

    async def set_frozen(self, frozen: bool) -> None:
        """Freeze/unfreeze this device's output (SpotFX Ambient Mode).

        Frozen: stop the entertainment stream so the bridge reverts to normal
        REST-controlled mode, and have flush() drop all frames — the bulbs hold
        whatever was last set via Hue REST. The driving virtual stays active and
        rendering; only this device's output is muted. AWAITING the bridge
        action:stop is the ordering guarantee SpotFX relies on: once this returns
        the stream is down, so a REST write won't be overridden by a live frame.

        Unfrozen: re-engage the entertainment stream so reactivity resumes.

        Idempotent — a redundant freeze still re-asserts the stop (covers a stream
        that re-armed via flush between calls)."""
        self._frozen = frozen
        if frozen:
            self._stream_ready = False
            with self._reconnect_lock:
                self._reconnecting = False   # cancel any in-flight reconnect intent
            self._cleanup_socket()
            await self._async_stop_stream()
            _LOGGER.info(
                "Hue %s: frozen (stream stopped, holding REST state)", self.name
            )
        else:
            if self._active:
                self._trigger_reconnect()
            _LOGGER.info(
                "Hue %s: unfrozen (re-engaging entertainment stream)", self.name
            )

    def flush(self, data):
        # TODO: maybe use the position of the channel to make more sense of the effect

        # Frozen (Ambient Mode): SpotFX holds these bulbs static via REST. Drop
        # the frame and do NOT re-arm a reconnect — re-engaging would override REST.
        if self._frozen:
            return

        # Drop frames while the stream isn't up — cheap, no I/O. Re-arm a
        # reconnect at most once per RECONNECT_RETRY_INTERVAL so a device whose
        # activation exhausted its retries (e.g. a flaky secondary bridge)
        # recovers on its own instead of staying dark until manual re-activation.
        # _trigger_reconnect is debounced (_reconnecting), so this is cheap.
        if not self._stream_ready or self._sock is None:
            now = time.monotonic()
            if now - self._last_reconnect_attempt >= self.RECONNECT_RETRY_INTERVAL:
                self._last_reconnect_attempt = now
                self._trigger_reconnect()
            return

        pixels = [[int(r), int(g), int(b)] for r, g, b in data]
        send_data = bytearray(b"HueStream")
        send_data.append(2)  # Major version
        send_data.append(0)  # Minor version
        send_data.append(0)  # Sequence ID
        send_data.append(0)  # Reserved
        send_data.append(0)  # Reserved
        send_data.append(0)  # Color Mode (0=RGB, 1=XY)
        send_data.append(0)  # Reserved
        send_data.extend(self._config["entertainment_id"].encode("utf-8"))
        for i in range(len(pixels)):
            send_data.append(i)  # channel ID
            send_data.append(pixels[i][0])  # Red
            send_data.append(pixels[i][0])  # Red
            send_data.append(pixels[i][1])  # Green
            send_data.append(pixels[i][1])  # Green
            send_data.append(pixels[i][2])  # Blue
            send_data.append(pixels[i][2])  # Blue

        try:
            self._sock.send(send_data)
        except (BlockingIOError, tls.WantWriteError):
            pass                       # transient backpressure — drop this frame
        except Exception:
            # Stream dropped (e.g. bridge tore it down after idle). Mark it down
            # and kick off ONE non-blocking reconnect; subsequent frames are
            # dropped until it's back. No inline blocking activate, ever.
            self._stream_ready = False
            self._trigger_reconnect()

    async def async_initialize(self):
        await super().async_initialize()

        # see "self.__init__" why we do this.
        if "hue_application_id" in self._config:
            self._hue_register()
            self._check_hue_bridge()
            hue_application_id = self._config["hue_application_id"]
        else:
            hue_application_id = self._get_application_id()
            self._dtls_client_context = tls.ClientContext(
                tls.DTLSConfiguration(
                    pre_shared_key=(
                        hue_application_id,
                        bytes.fromhex(self._config["clientkey"]),
                    ),
                    ciphers=["TLS-PSK-WITH-AES-128-GCM-SHA256"],
                )
            )

        entertainment_groups = self._entertainment_groups()
        entertainment_id = next(
            id
            for id in entertainment_groups
            if entertainment_groups[id].get("name", "").lower()
            == self._config.get("group_name", "").lower()
        )
        entertainment_group = entertainment_groups[entertainment_id]
        group_id = re.findall(r"\d+", entertainment_group["id_v1"])[0]

        lights = self._lights_from_entertainment_group(entertainment_id)

        config = {
            "group_id": group_id,
            "entertainment_id": entertainment_id,
            "hue_application_id": hue_application_id,
            "pixel_count": len(lights),
            "pixel_lights": lights,  # currently not used but could be used to make better effects respecting the position
            "refresh_rate": 30,
        }

        self.update_config(config)
