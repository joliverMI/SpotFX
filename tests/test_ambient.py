"""SPECTRA Ambient (services/ambient.py) — offline proof.

The proofs:
  1. Colour math: white maps near D65, and the light/fade payload shapes
     match what the Hue REST API expects.
  2. reconcile() no-ops (status "dark"/"no-hue-devices") without touching
     any device when SPECTRA doesn't own the live stack, or the room has
     no live Hue device — the room-control save must never fail just
     because there's nothing to drive.
  3. Enable freezes each Hue device BEFORE writing its REST state (a live
     stream frame must never win a race against the REST write); disable
     writes the brightness-only fade BEFORE unfreezing.
  4. One device failing (freeze or REST) never stops the others (best
     effort, same discipline as spectra/services/release.py).

No live Hue bridge, no LedFX, no live_host activation — a fake host/device
pair stands in for spectra.services.live_host.live.
"""
from __future__ import annotations

import asyncio

import pytest


def _run(coro):
    return asyncio.run(coro)


class FakeHueDevice:
    type = "hue"

    def __init__(self, ip: str, fail_freeze: bool = False, fail_rest_light: bool = False):
        self.config = {"ip_address": ip, "entertainment_id": f"ent-{ip}", "username": "u"}
        self.calls: list[tuple] = []
        self.frozen: bool | None = None
        self._fail_freeze = fail_freeze
        self._fail_rest_light = fail_rest_light

    async def set_frozen(self, frozen: bool) -> None:
        self.calls.append(("set_frozen", frozen))
        if self._fail_freeze:
            raise RuntimeError("bridge unreachable")
        self.frozen = frozen

    def _hue_request(self, method, endpoint, data=None, ssl=False):
        self.calls.append((method, endpoint, data))
        if endpoint == "/clip/v2/resource/entertainment":
            return {"data": [{"id": "esvc-1", "owner": {"rid": "dev-1"}}]}, {}
        if endpoint == "/clip/v2/resource/light":
            return {"data": [{"id": "light-1", "owner": {"rid": "dev-1"}}]}, {}
        if endpoint.startswith("/clip/v2/resource/entertainment_configuration/"):
            return {"data": [{"channels": [{"members": [
                {"service": {"rtype": "entertainment", "rid": "esvc-1"}}]}]}]}, {}
        if endpoint.startswith("/clip/v2/resource/light/"):
            if self._fail_rest_light:
                raise RuntimeError("light PUT failed")
            return {}, {}
        raise AssertionError(f"unexpected endpoint {endpoint}")


class FakeWledDevice:
    type = "wled"


class FakeHost:
    def __init__(self, devices: dict):
        self.devices = devices


@pytest.fixture(autouse=True)
def _clear_light_cache():
    from spectra.services import ambient
    ambient._light_cache.clear()
    yield
    ambient._light_cache.clear()


# ── colour math / payload shape ─────────────────────────────────────────────

def test_hex_to_xy_white_is_near_d65():
    from spectra.services.ambient import _hex_to_xy
    x, y = _hex_to_xy("#ffffff")
    assert x == pytest.approx(0.3227, abs=0.005)
    assert y == pytest.approx(0.3290, abs=0.005)


def test_hex_to_xy_bad_input_falls_back_to_white():
    from spectra.services.ambient import _hex_to_xy
    assert _hex_to_xy("not-a-colour") == (0.3127, 0.3290)


def test_light_payload_full_brightness_with_ramp():
    from spectra.services.ambient import _light_payload
    body = _light_payload("#ff0000", ramp_ms=1500)
    assert body["on"] == {"on": True}
    assert body["dimming"]["brightness"] == 100.0
    assert "xy" in body["color"]
    assert body["dynamics"] == {"duration": 1500}


def test_light_payload_no_ramp_omits_dynamics():
    from spectra.services.ambient import _light_payload
    body = _light_payload("#ffffff")
    assert "dynamics" not in body


def test_fade_dim_payload_clamps_and_has_no_colour_target():
    from spectra.services.ambient import _fade_dim_payload
    body = _fade_dim_payload(200, 1500)
    assert body["dimming"]["brightness"] == 100.0
    assert "color" not in body
    assert body["dynamics"] == {"duration": 1500}


# ── reconcile(): no live stack / no Hue devices ─────────────────────────────

def test_reconcile_dark_when_live_stack_not_active(monkeypatch):
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(live, "host", None)

    result = _run(ambient.reconcile(True, "#ff0000"))
    assert result == {"status": "dark"}


def test_reconcile_no_hue_devices(monkeypatch):
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(live, "host", FakeHost({"strip": FakeWledDevice()}))

    result = _run(ambient.reconcile(True, "#ff0000"))
    assert result == {"status": "no-hue-devices"}


# ── reconcile(): enable ─────────────────────────────────────────────────────

def test_reconcile_on_freezes_before_writing_rest(monkeypatch):
    from spectra.services import ambient
    from spectra.services.live_host import live
    dev = FakeHueDevice("10.0.0.1")
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    result = _run(ambient.reconcile(True, "#ff0000"))

    assert result["status"] == "on"
    assert result["devices"] == ["hue-lights"]
    assert result["lights_set"] == 1
    assert dev.frozen is True
    freeze_idx = dev.calls.index(("set_frozen", True))
    put_idx = next(i for i, c in enumerate(dev.calls)
                   if c[0] == "PUT" and c[1] == "/clip/v2/resource/light/light-1")
    assert freeze_idx < put_idx, "freeze must land before the REST write"
    _, _, body = dev.calls[put_idx]
    assert body["dimming"]["brightness"] == 100.0


def test_reconcile_on_holds_every_live_hue_device_wled_untouched(monkeypatch):
    from spectra.services import ambient
    from spectra.services.live_host import live
    a, b, w = FakeHueDevice("10.0.0.1"), FakeHueDevice("10.0.0.2"), FakeWledDevice()
    monkeypatch.setattr(live, "host", FakeHost({"a": a, "b": b, "strip": w}))

    result = _run(ambient.reconcile(True, "#00ff00"))

    assert result["devices"] == ["a", "b"]
    assert a.frozen is True and b.frozen is True


def test_reconcile_on_one_device_failing_does_not_stop_the_others(monkeypatch):
    from spectra.services import ambient
    from spectra.services.live_host import live
    bad = FakeHueDevice("10.0.0.1", fail_freeze=True)
    good = FakeHueDevice("10.0.0.2")
    monkeypatch.setattr(live, "host", FakeHost({"bad": bad, "good": good}))

    result = _run(ambient.reconcile(True, "#ffffff"))

    assert result["status"] == "on"
    assert result["devices"] == ["good"]
    assert good.frozen is True


# ── reconcile(): disable ─────────────────────────────────────────────────────

def test_reconcile_off_fades_before_unfreezing(monkeypatch):
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(ambient, "AMBIENT_TRANSITION_MS", 0)  # skip the real sleep
    dev = FakeHueDevice("10.0.0.1")
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    result = _run(ambient.reconcile(False, None))

    assert result == {"status": "off", "devices": ["hue-lights"]}
    assert dev.frozen is False
    put_idx = next(i for i, c in enumerate(dev.calls)
                   if c[0] == "PUT" and c[1] == "/clip/v2/resource/light/light-1")
    unfreeze_idx = dev.calls.index(("set_frozen", False))
    assert put_idx < unfreeze_idx, "the off-fade must land before unfreezing"
    _, _, body = dev.calls[put_idx]
    assert "color" not in body, "disable fades brightness only"
