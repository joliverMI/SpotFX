"""Pre-release Hue fade (spectra/services/release_fade.py) — offline proof.

The proofs:
  1. Payload shapes: the dim step is brightness-only (no colour target — see
     module docstring on why release has no landing colour to fade toward),
     clamped to a minimum, ramped; the off step is a bare power-off.
  2. Freeze lands BEFORE any REST write (same race the live stream frame
     must never win, proven the same way spectra/services/ambient.py proves
     it for its own off-switch).
  3. The dim write lands BEFORE the off write, with exactly one shared sleep
     between them for the WHOLE batch — not one sleep per device — so N
     bridges fade together, not serially.
  4. Every live Hue device is covered, across different bridges (different
     ip_address) — WLED and dummy devices are left untouched (no REST calls
     for them at all).
  5. One device's freeze/REST failure never stops another's fade (best
     effort, same discipline as spectra/services/release.py and
     spectra/services/ambient.py).
  6. No Hue devices on the host is a clean no-op — no REST calls at all.

No live Hue bridge, no LedFX, no live_host activation — a fake host/device
pair plus httpx.MockTransport stand in for live_host.live.host and the
bridge, same technique as tests/test_ambient.py.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest


def _run(coro):
    return asyncio.run(coro)


def _hue_handler(calls: list, fail_light_put: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(("REST", request.method, path, _body(request)))
        if path == "/clip/v2/resource/entertainment":
            return httpx.Response(200, json={"data": [{"id": "e1", "owner": {"rid": "d1"}}]})
        if path == "/clip/v2/resource/light":
            return httpx.Response(200, json={"data": [{"id": "l1", "owner": {"rid": "d1"}}]})
        if path.startswith("/clip/v2/resource/entertainment_configuration/"):
            return httpx.Response(200, json={"data": [{"channels": [{"members": [
                {"service": {"rtype": "entertainment", "rid": "e1"}}]}]}]})
        if path.startswith("/clip/v2/resource/light/"):
            if fail_light_put:
                return httpx.Response(400, json={"errors": [{"description": "bad body"}]})
            return httpx.Response(200, json={"data": []})
        raise AssertionError(f"unexpected request {request.method} {path}")
    return handler


def _body(request: httpx.Request) -> dict:
    import json as _json
    try:
        return _json.loads(request.content or b"{}")
    except Exception:
        return {}


class FakeHueDevice:
    type = "hue"

    def __init__(self, ip: str, calls: list, fail_freeze: bool = False):
        self.config = {"ip_address": ip, "entertainment_id": f"ent-{ip}", "username": "u"}
        self.calls = calls
        self.frozen: bool | None = None
        self._fail_freeze = fail_freeze

    async def set_frozen(self, frozen: bool) -> None:
        self.calls.append(("set_frozen", frozen))
        if self._fail_freeze:
            raise RuntimeError("bridge unreachable")
        self.frozen = frozen


class FakeWledDevice:
    type = "wled"


class FakeHost:
    def __init__(self, devices: dict):
        self.devices = devices


@pytest.fixture(autouse=True)
def _clear_light_cache():
    from spectra.services import release_fade
    release_fade._light_cache.clear()
    yield
    release_fade._light_cache.clear()


@pytest.fixture
def bridge(monkeypatch):
    from spectra.services import release_fade
    calls: list = []
    handler = _hue_handler(calls)

    def fake_bridge_client(cfg):
        return httpx.AsyncClient(
            base_url=f"https://{cfg['ip_address']}",
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(release_fade, "_bridge_client", fake_bridge_client)
    return calls


@pytest.fixture
def failing_bridge(monkeypatch):
    from spectra.services import release_fade
    calls: list = []
    handler = _hue_handler(calls, fail_light_put=True)

    def fake_bridge_client(cfg):
        return httpx.AsyncClient(
            base_url=f"https://{cfg['ip_address']}",
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(release_fade, "_bridge_client", fake_bridge_client)
    return calls


def _first_index(calls, pred):
    for i, c in enumerate(calls):
        if pred(c):
            return i
    raise AssertionError(f"nothing matching in {calls}")


# ── payload shape ────────────────────────────────────────────────────────


def test_dim_payload_is_brightness_only_no_colour_target():
    from spectra.services.release_fade import _dim_payload
    body = _dim_payload(1500)
    assert body["on"] == {"on": True}
    assert body["dimming"]["brightness"] == 1.0
    assert "color" not in body
    assert body["dynamics"] == {"duration": 1500}


def test_off_payload_is_a_bare_power_off():
    from spectra.services.release_fade import _OFF_PAYLOAD
    assert _OFF_PAYLOAD == {"on": {"on": False}}


# ── ordering: freeze before REST, dim before off ────────────────────────


def test_fade_freezes_before_writing_rest(monkeypatch, bridge):
    from spectra.services import release_fade
    dev = FakeHueDevice("10.0.0.1", bridge)
    host = FakeHost({"hue-lights": dev})

    result = _run(release_fade.fade_and_release_hue(host))

    assert result == {"devices": ["hue-lights"], "failed": []}
    assert dev.frozen is True
    freeze_at = _first_index(bridge, lambda c: c == ("set_frozen", True))
    put_at = _first_index(bridge, lambda c: c[:2] == ("REST", "PUT"))
    assert freeze_at < put_at, "freeze must land before any REST write"


def test_fade_dims_then_powers_off_with_one_shared_sleep(monkeypatch, bridge):
    from spectra.services import release_fade
    monkeypatch.setattr(release_fade, "RELEASE_FADE_MS", 1500)
    sleeps: list = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(release_fade.asyncio, "sleep", fake_sleep)

    a = FakeHueDevice("10.0.0.1", bridge)
    b = FakeHueDevice("10.0.0.2", bridge)
    host = FakeHost({"a": a, "b": b})

    result = _run(release_fade.fade_and_release_hue(host))

    assert result == {"devices": ["a", "b"], "failed": []}
    assert sleeps == [1.5], "one shared sleep for the whole batch, not one per device"

    put_calls = [c for c in bridge if c[:2] == ("REST", "PUT")]
    dim_calls = [c for c in put_calls if c[3].get("dimming")]
    off_calls = [c for c in put_calls if c[3].get("on") == {"on": False}]
    assert len(dim_calls) == 2 and len(off_calls) == 2
    last_dim = max(i for i, c in enumerate(bridge) if c in dim_calls)
    first_off = min(i for i, c in enumerate(bridge) if c in off_calls)
    assert last_dim < first_off, "every dim must land before any off"


def test_fade_covers_every_hue_device_across_bridges_wled_untouched(monkeypatch, bridge):
    from spectra.services import release_fade
    monkeypatch.setattr(release_fade, "RELEASE_FADE_MS", 0)
    a = FakeHueDevice("10.0.0.1", bridge)
    b = FakeHueDevice("10.0.0.2", bridge)  # a second, distinct bridge
    w = FakeWledDevice()
    host = FakeHost({"a": a, "b": b, "strip": w})

    result = _run(release_fade.fade_and_release_hue(host))

    assert result["devices"] == ["a", "b"]
    assert a.frozen is True and b.frozen is True
    put_calls = [c for c in bridge if c[:2] == ("REST", "PUT")]
    assert len(put_calls) == 4  # dim + off per bridge — the wled device untouched


def test_fade_one_device_failing_does_not_stop_the_other(monkeypatch, bridge):
    from spectra.services import release_fade
    monkeypatch.setattr(release_fade, "RELEASE_FADE_MS", 0)
    broken = FakeHueDevice("10.0.0.1", bridge, fail_freeze=True)
    ok = FakeHueDevice("10.0.0.2", bridge)
    host = FakeHost({"broken": broken, "ok": ok})

    result = _run(release_fade.fade_and_release_hue(host))

    assert result["devices"] == ["ok"]
    assert result["failed"] == ["broken"]
    assert ok.frozen is True


def test_fade_no_hue_devices_is_a_clean_noop(bridge):
    from spectra.services import release_fade
    host = FakeHost({"strip": FakeWledDevice()})

    result = _run(release_fade.fade_and_release_hue(host))

    assert result == {"devices": [], "failed": []}
    assert bridge == []  # no REST calls at all


def test_fade_rejected_light_write_does_not_raise(monkeypatch, failing_bridge):
    """A non-2xx per-light response (raise_for_status, caught inside
    _apply_hue) must never propagate — best-effort, matching
    spectra/services/ambient.py's own per-light error handling."""
    from spectra.services import release_fade
    monkeypatch.setattr(release_fade, "RELEASE_FADE_MS", 0)
    dev = FakeHueDevice("10.0.0.1", failing_bridge)
    host = FakeHost({"hue-lights": dev})

    result = _run(release_fade.fade_and_release_hue(host))  # must not raise

    assert result["devices"] == ["hue-lights"]
    assert result["failed"] == []
