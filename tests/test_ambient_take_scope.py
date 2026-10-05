"""AMBIENT STAYS INSIDE THE TAKE (2026-10-04).

THE INCIDENT: the Light Show's phase-1 room proof took the Living Room only
(a scoped take: the TV backlight and the two kitchen sconces). His stored
Ambient was on. Three seconds BEFORE the take even committed, a bridge
broadcast ran Ambient's reconcile (spectra/services/engine.py's
_on_track_uri), which saw a live stack (ambient.room_available read only
`live.active`) and held EVERY Hue device the host carried — seventeen bulbs
across dining, living, loft and bedroom, none of them in the take. River's
house witness showed every one switch on with no Home Assistant context.

Two causes, two proofs, each with the shipped behaviour as its red control:
  * Ambient's device set is the take's scope (live.scope_device_ids()).
  * Ambient does not act while a handover is in flight.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from fx import light_ownership as lo
from spectra.services import ambient
from spectra.services.live_host import live
from tests.test_ambient import FakeHueDevice, _run, bridge  # noqa: F401  (fixture)


class Host:
    def __init__(self, devices, virtuals):
        self.devices = devices
        self._v = virtuals
        self.virtuals = SimpleNamespace(get=self._v.get)


def _room(calls):
    kitchen = FakeHueDevice("10.0.0.1", calls)
    house = FakeHueDevice("10.0.0.2", calls)
    host = Host({"kitchen-hue": kitchen, "house-hues": house},
                {"kitchen-v": SimpleNamespace(_segments=[["kitchen-hue", 0, 0, False]]),
                 "house-v": SimpleNamespace(_segments=[["house-hues", 0, 0, False]])})
    return host, kitchen, house


def test_a_scoped_take_never_holds_hue_outside_its_scope(monkeypatch, bridge):
    host, kitchen, house = _room(bridge)
    monkeypatch.setattr(live, "host", host)
    monkeypatch.setattr(live, "scope", {"kitchen-v"})
    result = _run(ambient.reconcile(True, "#ffe392"))
    assert kitchen.frozen is True
    assert house.frozen is None, "Ambient held a Hue group the take never brought up"
    assert "house-hues" not in str(result)


def test_red_control_an_unscoped_take_still_holds_every_hue(monkeypatch, bridge):
    """The whole-room take is unchanged — and it is exactly what the scoped
    take used to do, which is why this is the incident's red control."""
    host, kitchen, house = _room(bridge)
    monkeypatch.setattr(live, "host", host)
    monkeypatch.setattr(live, "scope", None)
    _run(ambient.reconcile(True, "#ffe392"))
    assert kitchen.frozen is True and house.frozen is True


def test_scope_device_ids(monkeypatch):
    host, _k, _h = _room([])
    monkeypatch.setattr(live, "host", host)
    monkeypatch.setattr(live, "scope", None)
    assert live.scope_device_ids() is None
    monkeypatch.setattr(live, "scope", {"kitchen-v"})
    assert live.scope_device_ids() == {"kitchen-hue"}


def test_ambient_waits_out_a_handover_in_flight(monkeypatch):
    host, _k, _h = _room([])
    monkeypatch.setattr(live, "host", host)
    mid = lo.OwnershipRecord(owner=lo.RELEASED,
                             handover=SimpleNamespace(token="t"))
    monkeypatch.setattr(lo, "load", lambda: mid)
    assert ambient.room_available() is False
    monkeypatch.setattr(lo, "load", lambda: lo.OwnershipRecord(owner=lo.SPECTRA))
    assert ambient.room_available() is True


def test_dark_light_writes_only_the_takes_virtuals(monkeypatch):
    from fx import device_model
    from spectra.services import dark_light, fx_seam
    written = []

    async def get_virtuals():
        return {v: {"effect": {"type": "singleColor", "config": {}}}
                for v in ("kitchen-v", "house-v")}

    async def apply_writes(writes, transition_ms=0):
        written.extend(w["virtual_id"] for w in writes)
    monkeypatch.setattr(device_model, "get_all_virtual_ids", lambda: ["kitchen-v", "house-v"])
    monkeypatch.setattr(fx_seam, "get_virtuals", get_virtuals)
    monkeypatch.setattr(fx_seam, "apply_writes", apply_writes)
    monkeypatch.setattr(dark_light, "_shielded_set", lambda *a: set())
    monkeypatch.setattr(live, "scope", {"kitchen-v"})
    try:
        _run(dark_light._reconcile_impl("light", [], [], "#201830", 0.3))
    except Exception:
        pass
    assert "house-v" not in written
    assert "kitchen-v" in written
