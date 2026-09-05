"""FINDING A DEVICE BY WHAT IT IS.

The defect, twice on 2026-09-04: a WLED pinned by `ip_address` took a new
DHCP lease, and **a relocated device is indistinguishable from a dead one**
— the probe called it dark, the take-back said "Failed to connect", and
both were honest statements about an address that no longer meant anything.

Three layers are proven here, deliberately separately:

  WIRE      `read_info` / `read_node_addresses` against a REAL
            HTTP server serving real WLED JSON on loopback. Never his
            network — the whole point of an identity fix is that it must be
            provable without the thing that broke.
  LADDER    `device_identity.locate`'s pinned -> mDNS -> peers -> sweep
            order, with I/O injected, including the case that matters most:
            a name that RESOLVES to the wrong host is refused, because the
            MAC is what is believed and never the name.
  DRIVER    `WLEDDevice` adopting a new address end to end, and — the
            byte-identity guarantee — doing nothing at all when the pin is
            still right or when no identity is stored.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fx import device_identity as ident
from fx.devices import wled as wled_module
from fx.devices.wled import WLEDDevice

LEFT_SCONCE_MAC = "e0:8c:fe:5c:3a:78"      # his own, from the backlog card
LEFT_SCONCE_BARE = "e08cfe5c3a78"
OTHER_MAC = "68:25:dd:48:8b:80"            # the crystal — a real non-match


# ── a real WLED, on loopback ───────────────────────────────────────────────

class FakeWled:
    """A real HTTP endpoint serving real WLED `json/info` / `json/nodes`.
    Same shape as tests/test_night_power.py's server, which is deliberate:
    the wire is asserted, not a mock's opinion of it."""

    def __init__(self, mac: str = LEFT_SCONCE_BARE, name: str = "Sconce",
                 nodes: list[str] | None = None):
        self.info = {"brand": "WLED", "ver": "0.15.4", "name": name,
                     "mac": ident.normalize_mac(mac),
                     "vid": 2405180, "live": False,
                     "leds": {"count": 88, "rgbw": False}}
        self.nodes = list(nodes or [])
        self.hits: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body):
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                outer.hits.append(self.path)
                if self.path.endswith("/json/info"):
                    return self._send(outer.info)
                if self.path.endswith("/json/nodes"):
                    return self._send(
                        {"nodes": [{"name": "peer", "ip": ip}
                                   for ip in outer.nodes]})
                self.send_response(404)
                self.end_headers()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address = f"127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


DEAD_ADDRESS = "127.0.0.1:1"      # nothing listens on port 1


# ── the pure arithmetic ────────────────────────────────────────────────────

def test_a_mac_is_normalized_from_every_spelling_a_human_or_device_uses():
    """The backlog card records his MACs colon-separated; WLED reports them
    bare. One identity, however it was written down."""
    for spelling in (LEFT_SCONCE_MAC, "E0-8C-FE-5C-3A-78", LEFT_SCONCE_BARE,
                     "E08CFE5C3A78", "e0 8c fe 5c 3a 78"):
        assert ident.normalize_mac(spelling) == LEFT_SCONCE_BARE


def test_a_thing_that_is_not_a_mac_never_becomes_one():
    for junk in (None, "", 12, "not-a-mac", "e08cfe5c3a", "e08cfe5c3a789",
                 "zzzzzzzzzzzz"):
        assert ident.normalize_mac(junk) is None


def test_the_mdns_name_is_derived_from_the_mac_not_stored_beside_it():
    """WLED's own default. Deriving it is what keeps one identity from
    becoming two that can disagree — and it matches his real config, which
    already pins two devices by exactly these names."""
    assert ident.mdns_name_for_mac(LEFT_SCONCE_MAC) == "wled-5c3a78.local"
    assert ident.mdns_name_for_mac("b0:cb:d8:8a:35:34") == "wled-8a3534.local"
    assert ident.mdns_name_for_mac("nonsense") is None


def test_a_literal_ip_is_not_a_hostname_and_a_local_name_is():
    assert ident.looks_like_hostname("wled-5c3a78.local")
    assert not ident.looks_like_hostname("192.168.40.112")
    assert not ident.looks_like_hostname("192.168.40.112:80")
    assert not ident.looks_like_hostname("")


def test_the_sweep_is_the_old_pins_own_slash_24_nearest_first():
    """A new lease usually lands close to the old one, so the common case is
    found in the first batch and the remaining ~250 reads never happen. His
    sconce moved .112 -> .110: third candidate."""
    candidates = ident.subnet_candidates("192.168.40.112")
    assert len(candidates) == 253                 # the /24 minus itself
    assert candidates[:4] == ["192.168.40.111", "192.168.40.113",
                              "192.168.40.110", "192.168.40.114"]
    assert candidates.index("192.168.40.110") == 2


def test_there_is_no_neighbourhood_to_sweep_for_a_name_or_an_ipv6():
    """Inventing one would be a scan, not a lookup."""
    assert ident.subnet_candidates("wled-5c3a78.local") == []
    assert ident.subnet_candidates("fe80::1") == []
    assert ident.subnet_candidates(None) == []


def test_a_mac_is_read_out_of_a_real_json_info_body_and_nothing_else():
    assert ident.mac_from_info({"brand": "WLED", "mac": LEFT_SCONCE_BARE}) \
        == LEFT_SCONCE_BARE
    for absent in ({}, {"brand": "WLED"}, {"mac": "?"}, None, "text", []):
        assert ident.mac_from_info(absent) is None


# ── the ladder ─────────────────────────────────────────────────────────────

def _world(macs: dict, names: dict | None = None):
    """An injected network: address -> mac, hostname -> address."""
    async def read_mac(address):
        return macs.get(address)

    async def resolve_host(hostname):
        return (names or {}).get(hostname)

    return read_mac, resolve_host


def _locate(mac, pinned, macs, names=None, **kw):
    read_mac, resolve_host = _world(macs, names)
    return asyncio.run(ident.locate(
        mac, pinned_address=pinned, read_mac=read_mac,
        resolve_host=resolve_host, **kw))


def test_a_healthy_pin_is_confirmed_and_nothing_moves():
    """The byte-identical path: one read, `via="pinned"`, `moved` False."""
    found = _locate(LEFT_SCONCE_MAC, "192.168.40.110",
                    {"192.168.40.110": LEFT_SCONCE_BARE})
    assert found is not None
    assert (found.address, found.via, found.moved) == \
        ("192.168.40.110", "pinned", False)


def test_his_own_failure_the_pin_is_dead_and_mdns_finds_it():
    """2026-09-04, reproduced: config says .112, nothing is there, the
    device is at .110, and `wled-5c3a78.local` is what says so."""
    found = _locate(
        LEFT_SCONCE_MAC, "192.168.40.112",
        macs={"192.168.40.110": LEFT_SCONCE_BARE},
        names={"wled-5c3a78.local": "192.168.40.110"})
    assert found is not None
    assert (found.address, found.via, found.moved) == \
        ("192.168.40.110", "mdns", True)


def test_a_name_that_resolves_to_the_wrong_host_is_refused():
    """avahi caches. A resolved name is a CANDIDATE, never an answer — this
    is the confident-wrong-answer the MAC check exists to end. Here the
    stale cache points at a neighbour, and the sweep goes on to find the
    real device."""
    found = _locate(
        LEFT_SCONCE_MAC, "192.168.40.112",
        macs={"192.168.40.99": ident.normalize_mac(OTHER_MAC),   # stale
              "192.168.40.113": LEFT_SCONCE_BARE},
        names={"wled-5c3a78.local": "192.168.40.99"})
    assert found is not None
    assert (found.address, found.via) == ("192.168.40.113", "sweep")


def test_a_reachable_sibling_can_name_the_one_that_moved():
    """Peers before a sweep: a handful of candidates instead of a subnet."""
    found = _locate(
        LEFT_SCONCE_MAC, "192.168.40.112",
        macs={"10.0.0.7": LEFT_SCONCE_BARE},          # off the pinned /24
        peer_addresses=["10.0.0.5", "10.0.0.7"])
    assert found is not None
    assert (found.address, found.via) == ("10.0.0.7", "peers")


def test_a_bounded_sweep_finds_a_lease_that_moved_next_door():
    found = _locate(LEFT_SCONCE_MAC, "192.168.40.112",
                    macs={"192.168.40.110": LEFT_SCONCE_BARE})
    assert found is not None
    assert (found.address, found.via) == ("192.168.40.110", "sweep")


def test_not_found_is_none_and_never_an_exception():
    """"We could not find it" is not "it is dead", and an unreachable
    candidate is the normal case for a sweep, not an error."""
    async def explodes(address):
        raise OSError("network unreachable")

    async def resolve_boom(hostname):
        raise OSError("no resolver")

    found = asyncio.run(ident.locate(
        LEFT_SCONCE_MAC, pinned_address="192.168.40.112",
        read_mac=explodes, resolve_host=resolve_boom, sweep_limit=8))
    assert found is None


def test_no_identity_is_no_lookup():
    assert _locate("nonsense", "192.168.40.112",
                   {"192.168.40.112": LEFT_SCONCE_BARE}) is None


def test_a_pin_that_is_already_an_identity_handle_is_resolved_as_the_pin():
    """Two of his devices are pinned `wled-xxxxxx.local` already. Resolving
    that name IS the pinned check — it must not read as a move."""
    found = _locate(LEFT_SCONCE_MAC, "wled-5c3a78.local",
                    macs={"192.168.40.110": LEFT_SCONCE_BARE},
                    names={"wled-5c3a78.local": "192.168.40.110"})
    assert found is not None
    assert (found.address, found.via, found.moved) == \
        ("192.168.40.110", "pinned", False)


def test_the_sweep_can_be_refused_by_the_caller():
    """The rate-limited path (spectra/services/device_relocation.py) turns
    it off between cooldowns; the cheap rungs still run."""
    found = _locate(LEFT_SCONCE_MAC, "192.168.40.112",
                    macs={"192.168.40.110": LEFT_SCONCE_BARE}, sweep=False)
    assert found is None


# ── the wire ───────────────────────────────────────────────────────────────

def test_the_probe_reads_a_real_wled_json_info_off_a_real_socket():
    with FakeWled() as server:
        info = wled_module.read_info(server.address, 2.0)
    assert ident.mac_from_info(info) == LEFT_SCONCE_BARE
    assert server.hits == ["/json/info"]


def test_the_probe_answers_none_for_a_dead_address_rather_than_raising():
    """A sweep reads ~250 addresses that are not there. "Not there" has to
    be an answer, not an exception."""
    assert wled_module.read_info(DEAD_ADDRESS, 0.2) is None


def test_a_reachable_sibling_lists_its_peers_off_the_real_wire():
    with FakeWled(nodes=["192.168.40.110", "192.168.40.48"]) as server:
        addresses = wled_module.read_node_addresses(server.address, 2.0)
    assert addresses == ["192.168.40.110", "192.168.40.48"]
    assert wled_module.read_node_addresses(DEAD_ADDRESS, 0.2) == []


# ── the driver ─────────────────────────────────────────────────────────────

#: TEST-NET-3 (RFC 5737), mirroring his real 192.168.40.112 -> .110 move.
#: The driver tests patch the probe, but `WLED.get_config`/`get_sync_settings`
#: reach a real socket — so the addresses they are handed must be ones no
#: fixture of his could possibly answer at.
PINNED = "203.0.113.112"
ACTUAL = "203.0.113.110"


class FakeLedfx:
    thread_executor = None
    loop = None
    config = {"devices": [], "virtuals": []}
    virtuals: dict = {}


def _device(**config):
    base = {"name": "Sconce, Kitchen, Left", "ip_address": PINNED,
            "pixel_count": 88, "sync_mode": "DDP", "refresh_rate": 60,
            "icon_name": "wled", "center_offset": 0, "timeout": 1,
            "create_segments": False}
    base.update(config)
    return WLEDDevice(FakeLedfx(), base)


def _patch_network(monkeypatch, macs, names=None, infos=None):
    """One injected world for the driver: which addresses answer, and what
    the resolver says. Patches the module-level blocking probe, so the
    driver's own executor plumbing still runs for real."""
    bodies = dict(infos or {})
    for address, mac in macs.items():
        bodies.setdefault(address, {"brand": "WLED", "mac": mac,
                                    "name": "Sconce", "vid": 2405180,
                                    "leds": {"count": 88, "rgbw": False}})

    monkeypatch.setattr(wled_module, "read_info",
                        lambda address, timeout: bodies.get(address))

    async def resolve(self, hostname):
        return (names or {}).get(hostname)

    monkeypatch.setattr(WLEDDevice, "_resolve_host", resolve)

    async def no_sync_settings(self):
        # A real fixture's json/cfg read; irrelevant here and the one call
        # in async_initialize that would otherwise touch a socket.
        self.sync_settings = {}

    monkeypatch.setattr(wled_module.WLED, "get_sync_settings",
                        no_sync_settings)


def test_a_device_with_no_stored_identity_reconciles_nothing(monkeypatch):
    """The backward-compatibility guarantee, stated as a test: his config
    carries no `hardware_id` today, so every path must be a no-op."""
    _patch_network(monkeypatch, {ACTUAL: LEFT_SCONCE_BARE},
                   names={"wled-5c3a78.local": ACTUAL})
    device = _device()
    assert device.hardware_id is None
    assert asyncio.run(device.reconcile_address()) is None
    assert device._config["ip_address"] == PINNED


def test_a_healthy_pinned_device_is_confirmed_and_left_exactly_alone(monkeypatch):
    _patch_network(monkeypatch, {PINNED: LEFT_SCONCE_BARE})
    device = _device(hardware_id=LEFT_SCONCE_MAC)
    before = dict(device._config)
    location = asyncio.run(device.reconcile_address())
    assert location is not None and location.moved is False
    assert device._config == before


def test_a_relocated_device_is_re_found_and_every_sender_follows(monkeypatch):
    """The acceptance criterion. Not just "we know where it is" — the JSON
    client, the resolved destination and the streaming subdevice all have to
    move, or frames keep going to the old address forever."""
    _patch_network(monkeypatch, {ACTUAL: LEFT_SCONCE_BARE},
                   names={"wled-5c3a78.local": ACTUAL})
    device = _device(hardware_id=LEFT_SCONCE_MAC)
    device._destination = PINNED
    device.wled = wled_module.WLED(PINNED)
    device.setup_subdevice()

    location = asyncio.run(device.reconcile_address())

    assert location is not None and location.moved and location.via == "mdns"
    assert device._config["ip_address"] == ACTUAL
    assert device._destination == ACTUAL
    assert device.wled.ip_address == ACTUAL
    assert device.subdevice._destination == ACTUAL
    assert device.subdevice._config["ip_address"] == ACTUAL


def test_initialization_relocates_instead_of_reporting_failed_to_connect(
        monkeypatch):
    """His take-back failure, end to end: the pin is dead, so today this
    raises `Failed to connect` and the light stays out. With an identity it
    comes up at the address the identity actually points to."""
    import fx.devices as devices_module
    monkeypatch.setattr(devices_module, "resolve_destination",
                        _passthrough_resolver())
    _patch_network(monkeypatch, {ACTUAL: LEFT_SCONCE_BARE},
                   names={"wled-5c3a78.local": ACTUAL})
    monkeypatch.setattr(wled_module.WLED, "get_config", _fake_get_config(
        {ACTUAL: {"brand": "WLED", "mac": LEFT_SCONCE_BARE,
                            "name": "Sconce", "vid": 2405180,
                            "leds": {"count": 88, "rgbw": False}}}))
    device = _device(hardware_id=LEFT_SCONCE_MAC)

    asyncio.run(device.async_initialize())

    assert device._config["ip_address"] == ACTUAL
    assert device._destination == ACTUAL
    assert device.wled.ip_address == ACTUAL


def test_without_an_identity_the_same_start_still_fails_the_same_way(
        monkeypatch):
    """The change must not turn a genuinely-off fixture into a different
    message. No identity: the original error, verbatim."""
    import fx.devices as devices_module
    monkeypatch.setattr(devices_module, "resolve_destination",
                        _passthrough_resolver())
    _patch_network(monkeypatch, {})
    monkeypatch.setattr(wled_module.WLED, "get_config", _fake_get_config({}))
    device = _device()
    with pytest.raises(ValueError, match="Failed to connect"):
        asyncio.run(device.async_initialize())


def test_an_identity_is_learned_on_first_contact_and_never_invented(
        monkeypatch):
    """Lazy by design: nothing rewrites his config; the field arrives the
    first time the fixture is actually reached."""
    import fx.devices as devices_module
    monkeypatch.setattr(devices_module, "resolve_destination",
                        _passthrough_resolver())
    _patch_network(monkeypatch, {})
    monkeypatch.setattr(wled_module.WLED, "get_config", _fake_get_config(
        {PINNED: {"brand": "WLED", "mac": LEFT_SCONCE_BARE,
                            "name": "Sconce", "vid": 2405180,
                            "leds": {"count": 88, "rgbw": False}}}))
    device = _device()
    asyncio.run(device.async_initialize())
    assert device._config["hardware_id"] == LEFT_SCONCE_BARE

    # a body with no mac never produces a fabricated identity
    other = _device()
    assert other.learn_identity({"brand": "WLED"}) is None
    assert other.hardware_id is None

    # and an identity already stored is never overwritten
    pinned = _device(hardware_id=OTHER_MAC)
    assert pinned.learn_identity({"mac": LEFT_SCONCE_BARE}) is None
    assert pinned.hardware_id == ident.normalize_mac(OTHER_MAC)


def _passthrough_resolver():
    async def resolve_destination(loop, executor, destination):
        return destination
    return resolve_destination


def _fake_get_config(bodies):
    async def get_config(self):
        body = bodies.get(self.ip_address)
        if body is None:
            raise ValueError(f"WLED {self.ip_address}: Failed to connect")
        return body
    return get_config


def test_peer_discovery_asks_only_devices_that_have_a_destination(monkeypatch):
    """Best-effort and never raising: an unreachable sibling contributes
    nothing rather than failing the search."""
    seen: list[str] = []

    def nodes(address, timeout):
        seen.append(address)
        return {"a": ["10.0.0.7"], "b": []}.get(address, [])

    monkeypatch.setattr(wled_module, "read_node_addresses", nodes)

    class Sibling:
        def __init__(self, destination):
            self._destination = destination

    found = asyncio.run(wled_module.discover_peer_addresses(
        [Sibling("a"), Sibling("b"), Sibling(None)]))
    assert found == ["10.0.0.7"]
    assert sorted(seen) == ["a", "b"]


def test_activation_uses_the_cheap_rungs_only(monkeypatch):
    """Activation contacts EVERY device. A whole network that is down must
    not cost a full /24 sweep per device before the room comes up — mDNS is
    one lookup, and the sweep belongs on the rate-limited 30 s recheck."""
    import fx.devices as devices_module
    monkeypatch.setattr(devices_module, "resolve_destination",
                        _passthrough_resolver())
    _patch_network(monkeypatch, {})
    monkeypatch.setattr(wled_module.WLED, "get_config", _fake_get_config({}))
    device = _device(hardware_id=LEFT_SCONCE_MAC)
    asked: list[bool] = []
    real = WLEDDevice.reconcile_address

    async def record(self, peer_addresses=(), sweep=True):
        asked.append(sweep)
        return await real(self, peer_addresses=peer_addresses, sweep=sweep)

    monkeypatch.setattr(WLEDDevice, "reconcile_address", record)
    with pytest.raises(ValueError):
        asyncio.run(device.async_initialize())
    assert asked == [False], "activation must not sweep a /24 per device"
