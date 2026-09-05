"""REMEMBERING WHERE A DEVICE WENT, AND ASKING IN THE RIGHT PLACE.

`fx/device_identity.py` finds a WLED by its MAC (proven in
tests/test_device_identity.py). This file is SPECTRA's half: the two things
that decide whether the fix survives the night.

  PERSISTENCE is the one that matters most, and it is not obvious. Learning
  a MAC on the live device object is enough to drive the fixture right now
  and useless after a restart — because a process coming up against a stale
  pin has nothing to contact and therefore nothing to learn an identity
  FROM. So a learned identity has to reach the config file, and it has to
  reach it without rewriting anything else.

  THE RECOVERY PLACEMENT is the other. `activation_report.recheck` only
  re-inits a device with NO destination — and a relocated device HAS one
  (a literal pinned IP "resolves" verbatim without contacting anything), so
  before this it was never re-inited and stayed dark forever. That is the
  2026-09-04 sconce; the test at the bottom goes red without the fix.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fx import device_identity as ident
from spectra.services import device_relocation as relocation

MAC = "e0:8c:fe:5c:3a:78"
BARE = "e08cfe5c3a78"
PINNED = "203.0.113.112"      # TEST-NET-3, mirroring his real .40.112
ACTUAL = "203.0.113.110"      # ...and his real .40.110


@pytest.fixture(autouse=True)
def _clean_cooldowns():
    relocation.reset()
    yield
    relocation.reset()


class FakeDevice:
    """Only what device_relocation actually touches — deliberately not a
    real WLEDDevice, so this file is about the SPECTRA policy and the driver
    is proven on its own terms next door."""

    type = "wled"

    def __init__(self, device_id, ip=PINNED, mac=BARE, found_at=None,
                 fail=False):
        self.id = device_id
        self._config = {"ip_address": ip, "name": device_id}
        if mac:
            self._config["hardware_id"] = mac
        self._destination = ip
        self._found_at = found_at
        self._fail = fail
        self.calls: list[dict] = []

    @property
    def hardware_id(self):
        return ident.normalize_mac(self._config.get("hardware_id"))

    async def reconcile_address(self, peer_addresses=(), sweep=True):
        self.calls.append({"peers": list(peer_addresses), "sweep": sweep})
        if self._fail:
            raise OSError("network unreachable")
        if self._found_at is None:
            return None
        moved = self._found_at != self._config["ip_address"]
        if moved:
            self._config["ip_address"] = self._found_at
            self._destination = self._found_at
        return ident.Location(address=self._found_at,
                              via="mdns" if moved else "pinned", mac=BARE)


class FakeHost:
    def __init__(self, tmp_path, devices, entries=None):
        self.devices = {d.id: d for d in devices}
        self.config_dir = str(tmp_path)
        self.config = {
            "devices": entries if entries is not None else [
                {"id": d.id, "type": "wled",
                 "config": {"ip_address": PINNED, "name": d.id}}
                for d in devices],
            "virtuals": [],
        }


def _stored(tmp_path):
    return json.loads((tmp_path / "config.json").read_text())


# ── persistence ────────────────────────────────────────────────────────────

def test_a_learned_identity_reaches_the_config_so_a_restart_can_use_it(
        tmp_path):
    """The whole point: a device that answered ONCE is re-findable forever,
    including on the restart where its address has already changed."""
    device = FakeDevice("sconce-kitchen-left")
    host = FakeHost(tmp_path, [device])
    host.config["devices"][0]["config"].pop("hardware_id", None)

    assert relocation.learn_from_live(host) == ["sconce-kitchen-left"]
    entry = _stored(tmp_path)["devices"][0]["config"]
    assert entry["hardware_id"] == BARE
    assert entry["ip_address"] == PINNED


def test_nothing_is_written_when_nothing_changed(tmp_path):
    """His config is not migrated on deploy and not rewritten on every
    activation — a save happens only when a device actually learned or
    actually moved."""
    device = FakeDevice("sconce-kitchen-left")
    host = FakeHost(tmp_path, [device])
    host.config["devices"][0]["config"]["hardware_id"] = BARE

    assert relocation.learn_from_live(host) == []
    assert not (tmp_path / "config.json").exists()


def test_only_the_device_that_changed_is_touched(tmp_path):
    """Every other entry — including a non-WLED and its untouched keys — is
    byte-identical afterwards."""
    moved = FakeDevice("sconce-kitchen-left", found_at=ACTUAL)
    still = FakeDevice("crystal", mac="68:25:dd:48:8b:80")
    host = FakeHost(tmp_path, [moved, still], entries=[
        {"id": "sconce-kitchen-left", "type": "wled",
         "config": {"ip_address": PINNED, "name": "left",
                    "hardware_id": BARE, "sync_mode": "DDP"}},
        {"id": "crystal", "type": "wled",
         "config": {"ip_address": "203.0.113.48", "name": "crystal",
                    "hardware_id": "6825dd488b80"}},
        {"id": "hue-lights", "type": "hue",
         "config": {"ip_address": "203.0.113.215", "name": "hue"}},
    ])
    before = json.loads(json.dumps(host.config))

    asyncio.run(relocation.reconcile(moved, host=host))

    after = _stored(tmp_path)
    assert after["devices"][0]["config"]["ip_address"] == ACTUAL
    assert after["devices"][0]["config"]["sync_mode"] == "DDP"
    for index in (1, 2):
        assert after["devices"][index] == before["devices"][index]


def test_a_device_the_config_does_not_carry_is_skipped_not_invented(tmp_path):
    device = FakeDevice("ghost")
    host = FakeHost(tmp_path, [device], entries=[])
    assert relocation.learn_from_live(host) == []


def test_persisting_with_no_host_is_a_no_op_rather_than_an_error():
    assert relocation.persist(None, FakeDevice("x")) == []
    assert relocation.learn_from_live(None) == []


# ── the search policy ──────────────────────────────────────────────────────

def test_a_device_with_no_identity_is_never_searched_for(tmp_path):
    device = FakeDevice("sconce-kitchen-left", mac=None, found_at=ACTUAL)
    host = FakeHost(tmp_path, [device])
    assert asyncio.run(relocation.reconcile(device, host=host)) is None
    assert device.calls == []


def test_a_healthy_pin_confirms_and_persists_nothing(tmp_path):
    device = FakeDevice("sconce-kitchen-left", found_at=PINNED)
    host = FakeHost(tmp_path, [device])
    host.config["devices"][0]["config"]["hardware_id"] = BARE

    location = asyncio.run(relocation.reconcile(device, host=host))

    assert location is not None and location.moved is False
    assert not (tmp_path / "config.json").exists()


def test_a_search_that_explodes_is_never_fatal(tmp_path):
    device = FakeDevice("sconce-kitchen-left", fail=True)
    host = FakeHost(tmp_path, [device])
    assert asyncio.run(relocation.reconcile(device, host=host)) is None


def test_the_subnet_sweep_is_rate_limited_but_the_cheap_rungs_are_not(
        tmp_path):
    """recheck runs every 30 s per dark device. mDNS is one lookup and runs
    every time; a /24 sweep is up to 254 probes and must not."""
    device = FakeDevice("sconce-kitchen-left")
    host = FakeHost(tmp_path, [device])

    for _ in range(4):
        asyncio.run(relocation.reconcile(device, host=host))

    assert [c["sweep"] for c in device.calls] == [True, False, False, False]

    relocation._last_sweep["sconce-kitchen-left"] -= \
        relocation.SWEEP_COOLDOWN_S + 1
    asyncio.run(relocation.reconcile(device, host=host))
    assert device.calls[-1]["sweep"] is True


def test_peers_come_from_the_rooms_other_wleds_never_the_device_itself(
        tmp_path, monkeypatch):
    device = FakeDevice("sconce-kitchen-left")
    sibling = FakeDevice("crystal", ip="203.0.113.48")
    host = FakeHost(tmp_path, [device, sibling])
    asked: list[list[str]] = []

    async def discover(devices, executor=None):
        asked.append([d.id for d in devices])
        return ["203.0.113.7"]

    monkeypatch.setattr("fx.devices.wled.discover_peer_addresses", discover)
    asyncio.run(relocation.reconcile(device, host=host))

    assert asked == [["crystal"]]
    assert device.calls[0]["peers"] == ["203.0.113.7"]


# ── the recovery placement (the defect's own shape) ────────────────────────

def test_the_dark_device_recheck_asks_the_identity_before_giving_up(
        monkeypatch):
    """A relocated device HAS a destination, so `recheck`'s pre-existing
    "only re-init a driver that never resolved" rule skipped it forever.
    Drive the real recheck and assert BOTH halves: the identity was asked,
    and the driver was re-initialized because it moved."""
    from spectra.services import activation_report as report_module

    device = FakeDevice("sconce-kitchen-left", found_at=ACTUAL)
    reinitialized: list[str] = []

    class Live:
        active = True
        expected_active_ids: set = set()
        host = type("H", (), {"devices": {"sconce-kitchen-left": device}})()

        def expected_device_ids(self):
            return {"sconce-kitchen-left"}

        async def probe_devices(self, ids, timeout):
            return {i: "device reports live=false" for i in ids}

    live = Live()
    monkeypatch.setitem(
        __import__("sys").modules, "spectra.services.live_host",
        type("M", (), {"live": live})())

    async def retry(target):
        reinitialized.append(target.id)
        return True

    monkeypatch.setattr(report_module, "_retry_driver_init", retry)
    monkeypatch.setattr(relocation, "persist", lambda *a, **k: [])

    report_module.record_from_live(
        report_module.SOURCE_TAKE_BACK, {},
        {"sconce-kitchen-left": "could not confirm live state"})
    try:
        asyncio.run(report_module.recheck())
    finally:
        report_module.clear()

    assert device.calls, "the recheck never asked the device's identity"
    assert reinitialized == ["sconce-kitchen-left"], (
        "a device that MOVED must be re-initialized — its sender was built "
        "against the old address")
