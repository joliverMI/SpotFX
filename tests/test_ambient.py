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
import json

import httpx
import pytest


def _run(coro):
    return asyncio.run(coro)


def _hue_handler(calls: list, fail_light_put: bool = False, lights: list | None = None,
                 silent_drop_rids: set | None = None, silent_drop_attempts: int = 1):
    """A canned Hue CLIP v2 bridge, keyed only by path (MockTransport never
    touches the network, so every FakeHueDevice can share one handler
    regardless of its configured ip_address). Logs into the SAME `calls`
    list its FakeHueDevice(s) log set_frozen into, so ordering across the
    two is directly comparable.

    `lights` (default: one light "l1" on device "d1", named "l1" — matches
    the pre-confirmation test fixtures) drives entertainment/light/
    entertainment_configuration discovery for N lights on ONE device.
    Per-light STATE is tracked so GET reflects what the bulb actually holds
    — starting off/dim/D65-white, distinct from any test's target colour,
    so a light only reads back as confirmed once a PUT actually lands.
    `silent_drop_rids` models the live defect this module fixes: the bridge
    2xx's the PUT (`fail_light_put` is a different, honest 4xx rejection)
    but the physical bulb's state never updates — for `silent_drop_attempts`
    writes to that rid, then (if still below the count) starts landing, so
    a test can prove the retry path recovers a straggler, not just detect
    one."""
    lights = lights or [{"id": "l1", "owner": "d1", "name": None}]
    silent_drop_rids = silent_drop_rids or set()
    drop_counts: dict[str, int] = {}
    states: dict[str, dict] = {}

    def state(rid: str) -> dict:
        return states.setdefault(rid, {
            "on": {"on": False},
            "dimming": {"brightness": 1.0},
            "color": {"xy": {"x": 0.3127, "y": 0.3290}},
        })

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(("REST", request.method, path))
        if path == "/clip/v2/resource/entertainment":
            return httpx.Response(200, json={"data": [
                {"id": f"e{i}", "owner": {"rid": l["owner"]}} for i, l in enumerate(lights)]})
        if path == "/clip/v2/resource/light":
            return httpx.Response(200, json={"data": [
                {"id": l["id"], "owner": {"rid": l["owner"]},
                 **({"metadata": {"name": l["name"]}} if l.get("name") else {})}
                for l in lights]})
        if path.startswith("/clip/v2/resource/entertainment_configuration/"):
            return httpx.Response(200, json={"data": [{"channels": [
                {"members": [{"service": {"rtype": "entertainment", "rid": f"e{i}"}}]}
                for i in range(len(lights))]}]})
        if path.startswith("/clip/v2/resource/light/"):
            rid = path.rsplit("/", 1)[-1]
            if request.method == "PUT":
                if fail_light_put:
                    return httpx.Response(400, json={"errors": [{"description": "bad xy"}]})
                if rid in silent_drop_rids and drop_counts.get(rid, 0) < silent_drop_attempts:
                    drop_counts[rid] = drop_counts.get(rid, 0) + 1
                    return httpx.Response(200, json={"data": []})  # accepted, bulb ignores it
                body = json.loads(request.content)
                state(rid).update({k: v for k, v in body.items() if k in ("on", "dimming", "color")})
                return httpx.Response(200, json={"data": []})
            if request.method == "GET":
                return httpx.Response(200, json={"data": [dict(state(rid), id=rid)]})
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


@pytest.fixture(autouse=True)
def _fast_ambient_pacing(monkeypatch):
    """Zero every hold-confirmation pacing/settle knob by default so tests
    run fast; the dedicated pacing tests below override individual knobs to
    prove the spacing/staggering behaviour itself."""
    from spectra.services import ambient
    monkeypatch.setattr(ambient, "AMBIENT_TRANSITION_MS", 0)
    monkeypatch.setattr(ambient, "AMBIENT_CONFIRM_SETTLE_MS", 0)
    monkeypatch.setattr(ambient, "AMBIENT_WRITE_STAGGER_MS", 0)
    monkeypatch.setattr(ambient, "AMBIENT_RETRY_SPACING_MS", 0)


def _install_bridge(monkeypatch, handler):
    """Point spectra.services.ambient at `handler` via httpx.MockTransport."""
    from spectra.services import ambient

    def fake_bridge_client(cfg):
        return httpx.AsyncClient(
            base_url=f"https://{cfg['ip_address']}",
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(ambient, "_bridge_client", fake_bridge_client)


@pytest.fixture
def bridge(monkeypatch):
    """Route every spectra.services.ambient bridge call through a shared
    httpx.MockTransport instead of the network, logging (REST, method,
    path) into the returned list — pass the SAME list to FakeHueDevice(...)
    so set_frozen calls interleave with it for ordering proofs."""
    calls: list = []
    _install_bridge(monkeypatch, _hue_handler(calls))
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
    assert result["lights_total"] == 1
    assert dev.frozen is True
    freeze_at = _first_index(bridge, ("set_frozen", True))
    put_at = _first_index(bridge, ("REST", "PUT", "/clip/v2/resource/light/l1"))
    get_at = _first_index(bridge, ("REST", "GET", "/clip/v2/resource/light/l1"))
    assert freeze_at < put_at, "freeze must land before the REST colour write"
    assert put_at < get_at, "the hold must be READ BACK, not just written"


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
    status_code < 400 check made explicit. Every write is rejected, so this
    also proves the bounded-retry loop actually retries (not just detects)
    and still, correctly, never confirms it — reporting "partial" with the
    light named, not a false "on"."""
    from spectra.services import ambient
    from spectra.services.live_host import live
    dev = FakeHueDevice("10.0.0.1", failing_bridge)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    result = _run(ambient.reconcile(True, "#ff0000"))

    # The device itself froze fine (that's not gated on the bridge's REST
    # response), but the rejected light write must not be counted.
    assert result["status"] == "partial"
    assert result["lights_set"] == 0
    assert result["lights_total"] == 1
    assert result["unconfirmed"] == ["l1"]
    put_calls = [c for c in failing_bridge
                if c[:2] == ("REST", "PUT") and c[2].startswith("/clip/v2/resource/light/")]
    assert len(put_calls) == ambient.AMBIENT_HOLD_ATTEMPTS, \
        "every bounded retry attempted the write, none silently skipped"


# ── reconcile(): enable — read-back confirmation (the live defect fix) ─────
#
# The live incident: "Ambient ON: ['dining-hues', 'hue-lights'] held at
# #f5da8c, 17 light(s) set" — logged IDENTICALLY on a run where 3 lights
# (Kitchen Infuse, Dining Hue SE, Dining Hue SC) stayed on their old colour
# and a run where all 17 actually took it. The bridge 2xx'd every PUT both
# times — only a per-light READ BACK can tell the two runs apart, which is
# what these prove.

class _SleepSpy:
    """Forwards everything to the real asyncio module except sleep(), which
    it records instead of actually waiting — lets a test assert *how* a
    pacing delay was spaced without a real multi-second test."""
    def __init__(self, real):
        self._real = real
        self.calls: list[float] = []

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def sleep(self, seconds):
        self.calls.append(seconds)


@pytest.fixture
def sleep_spy(monkeypatch):
    from spectra.services import ambient
    spy = _SleepSpy(asyncio)
    monkeypatch.setattr(ambient, "asyncio", spy)
    return spy.calls


def test_reconcile_on_silently_dropped_write_is_never_reported_as_held(monkeypatch, caplog):
    """Contrive the exact live failure shape: the bridge accepts every PUT
    (2xx) for three lights, but the physical bulb never actually changes —
    modelling a light powered off at the wall, or one the zigbee mesh
    dropped under the burst. After the bounded retries are exhausted, they
    must come back UNCONFIRMED, by name, and the status must not read
    success."""
    from spectra.services import ambient
    from spectra.services.live_host import live
    lights = [
        {"id": "kl", "owner": "d-kl", "name": "Kitchen Infuse"},
        {"id": "se", "owner": "d-se", "name": "Dining Hue SE"},
        {"id": "sc", "owner": "d-sc", "name": "Dining Hue SC"},
        {"id": "lr", "owner": "d-lr", "name": "Living Room 1"},
    ]
    calls: list = []
    handler = _hue_handler(calls, lights=lights,
                           silent_drop_rids={"kl", "se", "sc"},
                           silent_drop_attempts=ambient.AMBIENT_HOLD_ATTEMPTS)
    _install_bridge(monkeypatch, handler)
    dev = FakeHueDevice("10.0.0.1", calls)
    monkeypatch.setattr(live, "host", FakeHost({"dining-hues": dev}))

    with caplog.at_level("ERROR"):
        result = _run(ambient.reconcile(True, "#f5da8c"))

    assert result["status"] == "partial"
    assert result["lights_set"] == 1
    assert result["lights_total"] == 4
    assert result["unconfirmed"] == ["Dining Hue SC", "Dining Hue SE", "Kitchen Infuse"], (
        "stragglers must be named by his own bulb names, not device/light ids")
    overclaim = [r for r in caplog.records if "4 light(s)" in r.getMessage()
                and "1/4" not in r.getMessage()]
    assert not overclaim, "must never log the old 'N light(s) set' overclaim shape"
    honest = [r for r in caplog.records if "1/4 light(s) confirmed" in r.getMessage()]
    assert honest, "the log line must state the confirmed/total split"


def test_reconcile_on_transient_straggler_recovers_via_spaced_retry(monkeypatch, sleep_spy):
    """A light that drops the FIRST write (transient — the module's own
    read-back-and-retry hypothesis) but takes the second must end up
    CONFIRMED, and the retry must be SPACED (asyncio.sleep called with the
    configured gap), never hammered back-to-back."""
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(ambient, "AMBIENT_RETRY_SPACING_MS", 777)
    lights = [{"id": "l1", "owner": "d1", "name": "Dining Hue SE"}]
    calls: list = []
    handler = _hue_handler(calls, lights=lights, silent_drop_rids={"l1"},
                           silent_drop_attempts=1)
    _install_bridge(monkeypatch, handler)
    dev = FakeHueDevice("10.0.0.1", calls)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    result = _run(ambient.reconcile(True, "#ff0000"))

    assert result["status"] == "on"
    assert result["lights_set"] == 1
    assert "unconfirmed" not in result
    put_calls = [c for c in calls
                if c[:2] == ("REST", "PUT") and c[2] == "/clip/v2/resource/light/l1"]
    assert len(put_calls) == 2, "one failed write, one spaced retry that landed"
    assert 0.777 in sleep_spy, "the retry must actually wait the configured spacing"


def test_reconcile_on_write_stagger_paces_multiple_lights(monkeypatch, sleep_spy):
    """Multiple lights in one hold pass must be paced (AMBIENT_WRITE_STAGGER_MS
    between successive PUTs), not fired back-to-back — the prevention half:
    pacing the burst from the start rather than only recovering after."""
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(ambient, "AMBIENT_WRITE_STAGGER_MS", 40)
    lights = [{"id": f"l{i}", "owner": f"d{i}", "name": f"Light {i}"} for i in range(3)]
    calls: list = []
    handler = _hue_handler(calls, lights=lights)
    _install_bridge(monkeypatch, handler)
    dev = FakeHueDevice("10.0.0.1", calls)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    result = _run(ambient.reconcile(True, "#00ffff"))

    assert result["status"] == "on"
    assert result["lights_set"] == 3
    assert sleep_spy.count(0.04) == 2, "one stagger gap between each of the 3 writes"


def test_reconcile_on_settle_waits_for_the_ramp_before_reading_back(monkeypatch, sleep_spy):
    """A bridge-side colour ramp (dynamics.duration) takes time to land —
    the first read-back must wait it out, not race it."""
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(ambient, "AMBIENT_TRANSITION_MS", 500)
    monkeypatch.setattr(ambient, "AMBIENT_CONFIRM_SETTLE_MS", 100)
    calls: list = []
    handler = _hue_handler(calls)
    _install_bridge(monkeypatch, handler)
    dev = FakeHueDevice("10.0.0.1", calls)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    result = _run(ambient.reconcile(True, "#ff0000"))

    assert result["status"] == "on"
    assert 0.6 in sleep_spy, "settle must be the ramp duration plus the confirm buffer"


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


# ── verify_held(): the status-honesty read-only recheck ────────────────────

def test_verify_held_dark_when_live_stack_not_active(monkeypatch):
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(live, "host", None)

    assert _run(ambient.verify_held("#ffffff")) == {"status": "dark"}


def test_verify_held_no_hue_devices(monkeypatch):
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(live, "host", FakeHost({"strip": FakeWledDevice()}))

    assert _run(ambient.verify_held("#ffffff")) == {"status": "no-hue-devices"}


def test_verify_held_reports_fully_lit_after_a_real_hold(monkeypatch, bridge):
    from spectra.services import ambient
    from spectra.services.live_host import live
    dev = FakeHueDevice("10.0.0.1", bridge)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    held = _run(ambient.reconcile(True, "#f5da8c"))
    assert held["status"] == "on"

    result = _run(ambient.verify_held("#f5da8c"))

    assert result == {"status": "verified", "lights_lit": 1, "lights_total": 1, "unlit": []}


def test_verify_held_reports_a_light_turned_off_out_of_band_without_writing(monkeypatch, bridge):
    """The exact live defect this function exists to catch: a bulb turned
    off by something other than this module (him, a Hue app, a physical
    switch) must be reported unlit by a read-only recheck — and the
    recheck itself must never write anything, i.e. never re-light a bulb
    he turned off."""
    from spectra.services import ambient
    from spectra.services.live_host import live
    dev = FakeHueDevice("10.0.0.1", bridge)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    held = _run(ambient.reconcile(True, "#f5da8c"))
    assert held["status"] == "on"

    async def _turn_off_out_of_band():
        async with ambient._bridge_client(dev.config) as client:
            await ambient._hue_put(client, "/clip/v2/resource/light/l1",
                                   {"on": {"on": False}})
    _run(_turn_off_out_of_band())
    calls_before_verify = len(bridge)

    result = _run(ambient.verify_held("#f5da8c"))

    assert result == {"status": "verified", "lights_lit": 0, "lights_total": 1,
                      "unlit": ["l1"]}
    assert all(c[1] != "PUT" for c in bridge[calls_before_verify:]), \
        "verify_held must only ever GET — never write"
