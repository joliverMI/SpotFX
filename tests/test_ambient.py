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
  4. A non-2xx Hue REST response does NOT count as a successful write
     (raise_for_status — the exact gap legacy's own status_code < 400
     check covers), and reconcile() reports status "failed" rather than a
     false "on"/"off" when every device ends up untouched — never report
     success with nothing actually held.
  5. One device failing never stops the others (best effort, same
     discipline as spectra/services/release.py).

No live Hue bridge, no LedFX, no live_host activation — a fake host/device
pair plus httpx.MockTransport (httpx's own offline transport, no extra
dependency) stand in for spectra.services.live_host.live and the bridge.
Every fake device and the mock bridge log into ONE shared `calls` list per
test, so freeze-vs-REST ordering is directly provable, not inferred.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest


def _run(coro):
    return asyncio.run(coro)


def _hue_handler(calls: list, fail_light_put: bool = False):
    """A canned Hue CLIP v2 bridge, keyed only by path (MockTransport never
    touches the network, so every FakeHueDevice can share one handler
    regardless of its configured ip_address). Logs into the SAME `calls`
    list its FakeHueDevice(s) log set_frozen into, so ordering across the
    two is directly comparable."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(("REST", request.method, path))
        if path == "/clip/v2/resource/entertainment":
            return httpx.Response(200, json={"data": [{"id": "e1", "owner": {"rid": "d1"}}]})
        if path == "/clip/v2/resource/light":
            return httpx.Response(200, json={"data": [{"id": "l1", "owner": {"rid": "d1"}}]})
        if path.startswith("/clip/v2/resource/entertainment_configuration/"):
            return httpx.Response(200, json={"data": [{"channels": [{"members": [
                {"service": {"rtype": "entertainment", "rid": "e1"}}]}]}]})
        if path.startswith("/clip/v2/resource/light/"):
            if fail_light_put:
                return httpx.Response(400, json={"errors": [{"description": "bad xy"}]})
            return httpx.Response(200, json={"data": []})
        raise AssertionError(f"unexpected request {request.method} {path}")
    return handler


class FakeHueDevice:
    type = "hue"

    def __init__(self, ip: str, calls: list, fail_freeze: bool = False,
                live_frame=None):
        self.config = {"ip_address": ip, "entertainment_id": f"ent-{ip}", "username": "u"}
        self.calls = calls   # shared with the mock bridge handler
        self.frozen: bool | None = None
        self._fail_freeze = fail_freeze
        # None (the default) means "not yet activated" — assemble_frame()
        # raises AttributeError-shaped by simply not being callable in a
        # useful way; real devices instead return None, so model that.
        self._live_frame = live_frame

    async def set_frozen(self, frozen: bool) -> None:
        self.calls.append(("set_frozen", frozen))
        if self._fail_freeze:
            raise RuntimeError("bridge unreachable")
        self.frozen = frozen

    def assemble_frame(self):
        return self._live_frame


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


@pytest.fixture
def bridge(monkeypatch):
    """Route every spectra.services.ambient bridge call through a shared
    httpx.MockTransport instead of the network, logging (REST, method,
    path) into the returned list — pass the SAME list to FakeHueDevice(...)
    so set_frozen calls interleave with it for ordering proofs."""
    from spectra.services import ambient
    calls: list = []
    handler = _hue_handler(calls)

    def fake_bridge_client(cfg):
        return httpx.AsyncClient(
            base_url=f"https://{cfg['ip_address']}",
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(ambient, "_bridge_client", fake_bridge_client)
    return calls


@pytest.fixture
def failing_bridge(monkeypatch):
    """Swap in a bridge that 400s every light PUT (resolution GETs still
    succeed) — for the raise_for_status / all-devices-failed proofs."""
    from spectra.services import ambient
    calls: list = []
    handler = _hue_handler(calls, fail_light_put=True)

    def fake_bridge_client(cfg):
        return httpx.AsyncClient(
            base_url=f"https://{cfg['ip_address']}",
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(ambient, "_bridge_client", fake_bridge_client)
    return calls


def _first_index(calls, wanted):
    for i, c in enumerate(calls):
        if c == wanted:
            return i
    raise AssertionError(f"{wanted} not found in {calls}")


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

def test_reconcile_on_freezes_before_writing_rest(monkeypatch, bridge):
    from spectra.services import ambient
    from spectra.services.live_host import live
    dev = FakeHueDevice("10.0.0.1", bridge)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    result = _run(ambient.reconcile(True, "#ff0000"))

    assert result["status"] == "on"
    assert result["devices"] == ["hue-lights"]
    assert result["lights_set"] == 1
    assert dev.frozen is True
    freeze_at = _first_index(bridge, ("set_frozen", True))
    put_at = _first_index(bridge, ("REST", "PUT", "/clip/v2/resource/light/l1"))
    assert freeze_at < put_at, "freeze must land before the REST colour write"


def test_reconcile_on_holds_every_live_hue_device_wled_untouched(monkeypatch, bridge):
    from spectra.services import ambient
    from spectra.services.live_host import live
    a = FakeHueDevice("10.0.0.1", bridge)
    b = FakeHueDevice("10.0.0.2", bridge)
    w = FakeWledDevice()
    monkeypatch.setattr(live, "host", FakeHost({"a": a, "b": b, "strip": w}))

    result = _run(ambient.reconcile(True, "#00ff00"))

    assert result["devices"] == ["a", "b"]
    assert a.frozen is True and b.frozen is True


def test_reconcile_on_one_device_failing_does_not_stop_the_others(monkeypatch, bridge):
    from spectra.services import ambient
    from spectra.services.live_host import live
    bad = FakeHueDevice("10.0.0.1", bridge, fail_freeze=True)
    good = FakeHueDevice("10.0.0.2", bridge)
    monkeypatch.setattr(live, "host", FakeHost({"bad": bad, "good": good}))

    result = _run(ambient.reconcile(True, "#ffffff"))

    assert result["status"] == "on"
    assert result["devices"] == ["good"]
    assert good.frozen is True


def test_reconcile_on_reports_failed_when_every_device_fails(monkeypatch, bridge):
    from spectra.services import ambient
    from spectra.services.live_host import live
    bad = FakeHueDevice("10.0.0.1", bridge, fail_freeze=True)
    monkeypatch.setattr(live, "host", FakeHost({"bad": bad}))

    result = _run(ambient.reconcile(True, "#ffffff"))

    assert result == {"status": "failed", "devices": [], "lights_set": 0}


def test_reconcile_on_rejected_rest_write_does_not_count_as_set(monkeypatch, failing_bridge):
    """A Hue CLIP v2 4xx body is valid JSON but must not be treated as a
    successful light write — raise_for_status is the gate legacy's own
    status_code < 400 check made explicit."""
    from spectra.services import ambient
    from spectra.services.live_host import live
    dev = FakeHueDevice("10.0.0.1", failing_bridge)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    result = _run(ambient.reconcile(True, "#ff0000"))

    # The device itself froze fine (that's not gated on the bridge's REST
    # response), but the rejected light write must not be counted.
    assert result["status"] == "on"
    assert result["lights_set"] == 0
    put_calls = [c for c in failing_bridge
                if c[:2] == ("REST", "PUT") and c[2].startswith("/clip/v2/resource/light/")]
    assert len(put_calls) == 1, "the write was attempted, just not counted"


# ── reconcile(): disable ─────────────────────────────────────────────────────

def test_reconcile_off_fades_before_unfreezing(monkeypatch, bridge):
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(ambient, "AMBIENT_TRANSITION_MS", 0)  # skip the real sleep
    dev = FakeHueDevice("10.0.0.1", bridge)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    result = _run(ambient.reconcile(False, None))

    assert result == {"status": "off", "devices": ["hue-lights"]}
    assert dev.frozen is False
    fade_at = _first_index(bridge, ("REST", "PUT", "/clip/v2/resource/light/l1"))
    unfreeze_at = _first_index(bridge, ("set_frozen", False))
    assert fade_at < unfreeze_at, "the off-fade must land before unfreezing"


def test_reconcile_off_fade_body_has_no_colour_target(monkeypatch, bridge):
    from spectra.services import ambient
    from spectra.services.live_host import live
    captured = {}
    orig_fade = ambient._fade_dim_payload

    def spy(*args, **kwargs):
        body = orig_fade(*args, **kwargs)
        captured["body"] = body
        return body

    monkeypatch.setattr(ambient, "_fade_dim_payload", spy)
    monkeypatch.setattr(ambient, "AMBIENT_TRANSITION_MS", 0)
    dev = FakeHueDevice("10.0.0.1", bridge)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    _run(ambient.reconcile(False, None))

    assert "color" not in captured["body"]


def test_reconcile_off_reports_failed_when_every_device_fails_to_unfreeze(monkeypatch, bridge):
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(ambient, "AMBIENT_TRANSITION_MS", 0)
    bad = FakeHueDevice("10.0.0.1", bridge, fail_freeze=True)
    monkeypatch.setattr(live, "host", FakeHost({"bad": bad}))

    result = _run(ambient.reconcile(False, None))

    assert result == {"status": "failed", "devices": []}


# ── reconcile(): disable — catch-up ramp (the release-fidelity fix) ────────
#
# Legacy (services/ambient_mode.py) eases back into the real show over
# ambient_catchup_s AFTER the stream reconnects (a captured-effect-config
# tween); SPECTRA has no separate wake-scene config to tween from, so it
# eases the still-frozen bulb toward the live pixel buffer BEFORE
# reconnecting instead (module docstring) — same qualitative fix (a ramp,
# not a snap), reached through the only primitive available on this side.

def test_live_look_reads_mean_rgb_as_hex_and_brightness():
    from spectra.services.ambient import _live_look

    class Dev:
        def assemble_frame(self):
            return [(200.0, 0.0, 0.0), (100.0, 0.0, 0.0)]  # mean (150, 0, 0)

    color_hex, brightness_pct = _live_look(Dev())
    assert color_hex == "#960000"
    assert brightness_pct == round(150 / 255 * 100)


def test_live_look_none_when_frame_unavailable():
    from spectra.services.ambient import _live_look

    class DevNoFrame:
        def assemble_frame(self):
            return None

    class DevRaises:
        def assemble_frame(self):
            raise RuntimeError("not activated")

    assert _live_look(DevNoFrame()) is None
    assert _live_look(DevRaises()) is None


def test_reconcile_off_ramps_toward_the_live_look_before_unfreezing(monkeypatch, bridge):
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(ambient, "AMBIENT_TRANSITION_MS", 0)
    monkeypatch.setattr(ambient, "AMBIENT_CATCHUP_MS", 5)  # keep the test fast
    dev = FakeHueDevice("10.0.0.1", bridge, live_frame=[(0.0, 255.0, 0.0)])
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    result = _run(ambient.reconcile(False, None))

    assert result == {"status": "off", "devices": ["hue-lights"]}
    put_calls = [c for c in bridge
                if c[:2] == ("REST", "PUT") and c[2].startswith("/clip/v2/resource/light/")]
    assert len(put_calls) == 2, "phase-1 fade PUT, then the catch-up PUT"
    unfreeze_at = _first_index(bridge, ("set_frozen", False))
    assert unfreeze_at == len(bridge) - 1, "both REST phases must land before unfreezing"


def test_reconcile_off_catchup_payload_targets_the_live_colour(monkeypatch, bridge):
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(ambient, "AMBIENT_TRANSITION_MS", 0)
    monkeypatch.setattr(ambient, "AMBIENT_CATCHUP_MS", 5)
    captured = []
    orig_apply = ambient._apply_hue

    async def spy(dev, body):
        captured.append(body)
        return await orig_apply(dev, body)

    monkeypatch.setattr(ambient, "_apply_hue", spy)
    dev = FakeHueDevice("10.0.0.1", bridge, live_frame=[(0.0, 0.0, 255.0)])
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    _run(ambient.reconcile(False, None))

    fade_body, catchup_body = captured
    assert "color" not in fade_body  # phase 1 unchanged: brightness-only dim
    assert "xy" in catchup_body["color"]  # phase 2: ramps toward the live colour
    assert catchup_body["dynamics"] == {"duration": 5}


def test_reconcile_off_skips_catchup_when_no_live_frame_available(monkeypatch, bridge):
    """A device with nothing to read (e.g. not yet activated) just releases
    from the phase-1 fade, same as before this fix — no spurious write."""
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(ambient, "AMBIENT_TRANSITION_MS", 0)
    monkeypatch.setattr(ambient, "AMBIENT_CATCHUP_MS", 5)
    dev = FakeHueDevice("10.0.0.1", bridge)  # live_frame defaults to None
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    result = _run(ambient.reconcile(False, None))

    assert result == {"status": "off", "devices": ["hue-lights"]}
    put_calls = [c for c in bridge
                if c[:2] == ("REST", "PUT") and c[2].startswith("/clip/v2/resource/light/")]
    assert len(put_calls) == 1, "only the phase-1 fade PUT — no catch-up write"


def test_ambient_catchup_ms_matches_legacy_ambient_catchup_s_default():
    """config.py's settings.ambient_catchup_s default is 8.0 — the exact
    number this module's release ramp must match, not re-guess."""
    from spectra.services.ambient import AMBIENT_CATCHUP_MS
    assert AMBIENT_CATCHUP_MS == 8000
