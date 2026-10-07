"""A FRIENDLY NAME HE SET ALWAYS WINS, ACROSS A RESTART.

The Admiral's report, verbatim: "i've noticed that the friendly names of
the devices keep reverting back to wled. i have changed crystal, tv
backlight, dining table, and porch rail and they keep switching back."

Root cause (fx/VENDOR.md #53): `WLEDDevice.async_initialize()` always
copied the fixture's OWN reported `name` (its firmware default, literally
"WLED" on every fixture he never locally renamed on the WLED side) onto
`self._config["name"]` unconditionally. That method runs on every host
start, re-activation, AND activation-report recheck — not just first
contact — so a rename made through the device console (correctly persisted
at the moment he made it) was silently reverted in the LIVE device
object's own memory the instant the stack came back up, which is exactly
what every live-reading surface (the Devices page, `GET
/spectra/api/house/targets`) reads from.

Same fixture/helper shapes as tests/test_device_identity.py, so this file
reads as a sibling of that one rather than inventing a second pattern.
"""
from __future__ import annotations

import asyncio

from fx.devices import wled as wled_module
from fx.devices.wled import WLEDDevice

PINNED = "203.0.113.120"


class FakeLedfx:
    thread_executor = None
    loop = None
    config = {"devices": [], "virtuals": []}
    virtuals: dict = {}


def _device(**config):
    base = {"name": "Crystal", "ip_address": PINNED, "pixel_count": 976,
            "sync_mode": "DDP", "refresh_rate": 60, "icon_name": "wled",
            "center_offset": 0, "timeout": 1, "create_segments": False}
    base.update(config)
    return WLEDDevice(FakeLedfx(), base)


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


def _patch_contact(monkeypatch, *, reported_name: str, mac: str = "68:25:dd:48:8b:80"):
    """One fixture, reachable at its pinned address, reporting its OWN
    `name` (the thing that used to clobber a user rename)."""
    import fx.devices as devices_module
    monkeypatch.setattr(devices_module, "resolve_destination",
                        _passthrough_resolver())
    monkeypatch.setattr(wled_module.WLED, "get_config", _fake_get_config(
        {PINNED: {"brand": "WLED", "mac": mac, "name": reported_name,
                  "vid": 2405180, "leds": {"count": 976, "rgbw": False}}}))

    async def no_sync_settings(self):
        self.sync_settings = {}
    monkeypatch.setattr(wled_module.WLED, "get_sync_settings", no_sync_settings)


def test_a_renamed_fixture_keeps_its_name_through_reinitialization(monkeypatch):
    """The exact bug: he renamed the fixture to "Crystal" (persisted via
    the device console's rename path, so this is the device's STORED
    config at the start of a restart) and the fixture itself still
    reports its own firmware name "WLED". Re-running async_initialize —
    what every host start, re-activation and activation-report recheck
    does — must leave his rename alone."""
    _patch_contact(monkeypatch, reported_name="WLED")
    device = _device(name="Crystal")

    asyncio.run(device.async_initialize())

    assert device._config["name"] == "Crystal"
    assert device.name == "Crystal"


def test_renaming_then_reinitializing_proves_the_revert_and_the_fix(monkeypatch):
    """The lifecycle the report described: rename, then a restart (a second
    async_initialize, as a real re-activation would be). Before the fix in
    fx/VENDOR.md #53 this assertion failed — the second call clobbered the
    first-contact name back to "WLED"."""
    _patch_contact(monkeypatch, reported_name="WLED")
    device = _device(name="WLED")  # first contact: no rename yet
    asyncio.run(device.async_initialize())
    assert device._config["name"] == "WLED"

    # He renames it (the device console's rename_device -> update_device,
    # which merges {"name": ...} into the device's own config, exactly as
    # Device.update_config does).
    device._config["name"] = "Crystal"

    # A restart / re-activation reconstructs nothing here (the device
    # object persists across a re-activation within one process, and a
    # genuine process restart re-validates this same persisted name from
    # disk before async_initialize ever runs) — so re-running
    # async_initialize must not touch the name at all.
    asyncio.run(device.async_initialize())

    assert device._config["name"] == "Crystal"
    assert device.name == "Crystal"


def test_a_device_with_no_stored_name_still_gets_the_reported_one(monkeypatch):
    """The other half of the rule: the fixture's own name may FILL IN a
    missing one. (In practice every device is created with a name — this
    proves the fallback still works for whatever reaches this path with
    none, rather than leaving the field empty forever.)"""
    _patch_contact(monkeypatch, reported_name="Dining Room Sconce")
    device = _device(name="")

    asyncio.run(device.async_initialize())

    assert device._config["name"] == "Dining Room Sconce"
    assert device.name == "Dining Room Sconce"
