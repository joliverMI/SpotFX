"""A RESTART MUST NOT LET THE SHOW OUT FROM UNDER A HUE HOLD (2026-10-07).

His report, verbatim: "dining hues are reacting even tho ambient is set for
them." The diagnosis (data/dining-hues-ambient-diag/report.md), from the
journal of the 10:18:22 deploy restart:

  10:18:28.654  Dining Hues: unfrozen        <- house_restart.after_resume
  10:18:29.031  Dining Hues: frozen          <- the Hue Hold, a moment later
  10:18:30.419  Dining Hues: entertainment stream activated

The bridge then streamed the show to the dining bulbs for ten minutes while
every Spectra surface said "held, 17 confirmed". Three things let it, and
each is held here, with its red control:

  1. after_resume read only what the hold had LANDED, so it unfroze both
     areas while the hold was still on its way.
  2. a freeze's `stop` did not wait for an activation already queued behind
     the class-wide activation lock — its `start` reached the bridge after.
  3. the "held" check read the light resource, which shows the held colour
     while the bulbs follow a stream; the entertainment configuration's own
     status is the instrument that tells the truth.

No network: the bridge is a model, the DTLS context a fake.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from fx import hue_freeze
from fx.devices.hue import HueDevice

ENT = "313a141a-ce30-43c9-89a7-fd3cc3b720a4"
APP_ID = "e05a3549-b159-4b79-9c12-bb3065efd376"


# ── 2. the driver: a freeze always wins ─────────────────────────────────────

class Bridge:
    """The entertainment-configuration half of a Hue bridge: every
    start/stop is recorded with its time; the session is whatever the LAST
    action left it."""

    def __init__(self):
        self.t0 = time.monotonic()
        self.actions: list[tuple[float, str]] = []
        self.session = False

    def request(self, method, endpoint, data=None, ssl=False):
        assert method == "PUT" and endpoint.endswith(ENT), (method, endpoint)
        action = (data or {}).get("action")
        self.actions.append((round(time.monotonic() - self.t0, 3), action))
        self.session = action == "start"
        return {"data": [{"rid": ENT}]}, {}

    def last(self) -> str:
        return self.actions[-1][1]


class _FakeDtls:
    def __init__(self, handshake_s: float = 0.0):
        self.sent: list[bytes] = []
        self.handshake_s = handshake_s

    def wrap_socket(self, sock, server_hostname):
        outer = self

        class Wrapped:
            _socket = sock

            def connect(self, addr):
                pass

            def do_handshake(self):
                time.sleep(outer.handshake_s)

            def send(self, data):
                outer.sent.append(bytes(data))

            def close(self):
                sock.close()
        return Wrapped()


class _Ledfx:
    def __init__(self, loop):
        self.loop = loop
        self.thread_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _device(loop, bridge: Bridge, *, scope_read_s=0.0, handshake_s=0.0):
    dev = HueDevice(_Ledfx(loop), {
        "name": "Dining Hues", "ip_address": "192.168.40.28",
        "group_name": "Dining Music", "udp_port": 2100,
        "hue_application_id": APP_ID, "clientkey": "00" * 16,
        "username": "user", "entertainment_id": ENT,
        "pixel_count": 7, "refresh_rate": 30,
    })
    dev._id = "dining-hues"
    dev._type = "hue"
    dev._hue_request = bridge.request
    dev._dtls_client_context = _FakeDtls(handshake_s)
    dev._destination = "192.168.40.28"

    def slow_scope_read():
        time.sleep(scope_read_s)          # the three bridge GETs, at bridge speed
        return None
    dev._area_scope_refusal = slow_scope_read
    return dev


async def _came_up_frozen_then(dev, freeze_after_s: float, settle_s: float = 1.2):
    """The restart's shape: the area comes up frozen, after_resume unfreezes
    it, and the Hue Hold freezes it again `freeze_after_s` later. Frames are
    rendered the whole time, as the virtual does."""
    dev._frozen = True
    dev.activate()                         # frozen: no session, no reconnect
    await dev.set_frozen(False)            # after_resume
    await asyncio.sleep(freeze_after_s)
    await dev.set_frozen(True)             # the Hue Hold
    frames_after_freeze = len(dev._dtls_client_context.sent)
    deadline = asyncio.get_running_loop().time() + settle_s
    while asyncio.get_running_loop().time() < deadline:
        dev.flush([(255, 0, 0)] * 7)
        await asyncio.sleep(0.02)
    sent_after = len(dev._dtls_client_context.sent) - frames_after_freeze
    await dev.async_deactivate()
    return sent_after


def _shipped_driver(monkeypatch):
    """The red control: the driver as shipped before the fix — the freeze's
    stop not ordered behind the activation lock, and an activation that
    starts the session whatever happened while it waited."""
    def shipped_activate(self):
        with HueDevice._activation_lock:
            refusal = self._area_scope_refusal()
            assert refusal is None
            self._hue_request(
                "PUT",
                f"/clip/v2/resource/entertainment_configuration/{self._config['entertainment_id']}",
                {"action": "start"}, ssl=True)
            self._sock = self._open_dtls()

    async def shipped_set_frozen(self, frozen):
        self._frozen = frozen
        if frozen:
            self._stream_ready = False
            with self._reconnect_lock:
                self._reconnecting = False
            self._cleanup_socket()
            await self._async_stop_stream()
        elif self._active:
            self._trigger_reconnect()
    monkeypatch.setattr(HueDevice, "_blocking_activate", shipped_activate)
    monkeypatch.setattr(HueDevice, "set_frozen", shipped_set_frozen)


def test_a_freeze_50ms_after_an_unfreeze_wins_over_the_queued_start():
    """The live race: the scope read before `start` is slow, the freeze
    lands 50 ms after the unfreeze. The bridge's last word is `stop`, the
    session is down, and not one frame is sent after the freeze."""
    bridge = Bridge()

    async def run():
        dev = _device(asyncio.get_running_loop(), bridge, scope_read_s=0.4)
        return await _came_up_frozen_then(dev, 0.05)
    sent_after = asyncio.run(run())
    starts = [a for _t, a in bridge.actions if a == "start"]
    assert starts == [], f"a start reached the bridge: {bridge.actions}"
    assert bridge.last() == "stop"
    assert bridge.session is False
    assert sent_after == 0


def test_red_control_the_shipped_driver_lets_the_start_land_after_the_stop(monkeypatch):
    _shipped_driver(monkeypatch)
    bridge = Bridge()

    async def run():
        dev = _device(asyncio.get_running_loop(), bridge, scope_read_s=0.4)
        dev._frozen = True
        dev.activate()
        await dev.set_frozen(False)
        await asyncio.sleep(0.05)
        await dev.set_frozen(True)
        await asyncio.sleep(0.8)
        # bypass the post-check's cleanup: what the BRIDGE was told is the point
        await dev.async_deactivate()
    asyncio.run(run())
    kinds = [a for _t, a in bridge.actions]
    # the freeze's stop, then the queued start — then only the teardown stop
    assert kinds[:2] == ["stop", "start"], bridge.actions


def test_a_freeze_during_the_handshake_stops_the_session_it_built():
    """The other interleaving: `start` has already gone out and the DTLS
    handshake is running when the freeze lands. The freeze's stop waits for
    the activation, which stops its own session first — `stop` is last."""
    bridge = Bridge()

    async def run():
        dev = _device(asyncio.get_running_loop(), bridge, handshake_s=0.4)
        return await _came_up_frozen_then(dev, 0.1)
    sent_after = asyncio.run(run())
    kinds = [a for _t, a in bridge.actions]
    assert kinds[0] == "start", bridge.actions
    assert "stop" in kinds[1:] and bridge.last() == "stop", bridge.actions
    assert bridge.session is False
    assert sent_after == 0


def test_an_unfreeze_that_lands_while_the_activation_stands_down_still_streams():
    """freeze -> unfreeze while the cancelled activation is still standing
    down: the unfreeze is not swallowed by the debounce."""
    bridge = Bridge()

    async def run():
        dev = _device(asyncio.get_running_loop(), bridge, scope_read_s=0.3)
        dev._frozen = True
        dev.activate()
        await dev.set_frozen(False)
        await asyncio.sleep(0.05)
        freeze = asyncio.ensure_future(dev.set_frozen(True))
        await asyncio.sleep(0.05)
        await dev.set_frozen(False)
        await freeze
        deadline = asyncio.get_running_loop().time() + 1.5
        while asyncio.get_running_loop().time() < deadline and not dev._stream_ready:
            await asyncio.sleep(0.02)
        ready = dev._stream_ready
        await dev.async_deactivate()
        return ready
    assert asyncio.run(run()) is True
    assert "start" in [a for _t, a in bridge.actions]


def test_an_ordinary_unfreeze_still_streams():
    bridge = Bridge()

    async def run():
        dev = _device(asyncio.get_running_loop(), bridge, scope_read_s=0.05)
        dev._frozen = True
        dev.activate()
        await dev.set_frozen(False)
        deadline = asyncio.get_running_loop().time() + 1.0
        while asyncio.get_running_loop().time() < deadline and not dev._stream_ready:
            await asyncio.sleep(0.02)
        dev.flush([(1, 2, 3)] * 7)
        out = (dev._stream_ready, len(dev._dtls_client_context.sent))
        await dev.async_deactivate()
        return out
    ready, sent = asyncio.run(run())
    assert ready is True and sent == 1
    assert [a for _t, a in bridge.actions][0] == "start"


# ── 1. after_resume keeps an area the hold is still landing on ──────────────

class _Hue:
    def __init__(self, did):
        self.id = did
        self.frozen = True
        self.calls: list[bool] = []

    async def set_frozen(self, on):
        self.calls.append(on)
        self.frozen = on


@pytest.fixture
def two_areas(monkeypatch):
    from spectra.services import ambient_music_gate as gate
    from spectra.services.live_host import live
    dining, living = _Hue("dining-hues"), _Hue("hue-lights")
    monkeypatch.setattr(live, "host", SimpleNamespace(
        devices={"dining-hues": dining, "hue-lights": living}))
    monkeypatch.setattr(gate, "_held", False)
    monkeypatch.setattr(gate, "_held_looks", None)
    monkeypatch.setattr(gate, "_held_resolved_groups", frozenset())
    monkeypatch.setattr(gate, "_house_directive", lambda: None)
    monkeypatch.setattr(gate, "_house_pending", lambda: None)
    hue_freeze.set_pending({"dining-hues", "hue-lights"})
    assert hue_freeze.consume("dining-hues") and hue_freeze.consume("hue-lights")
    return gate, dining, living


def _in_flight_on(gate, monkeypatch, target):
    tr = SimpleNamespace(target=target, in_flight=True, intent=bool(target[0]))
    monkeypatch.setattr(gate, "_transition", tr)
    return tr


def test_after_resume_during_an_in_flight_hold_leaves_both_areas_frozen(two_areas, monkeypatch):
    """10:18:28.65 exactly: the Hue Hold's ON transition is on its way (it
    lands at 10:18:44), nothing has LANDED yet. Neither area is unfrozen."""
    from spectra.services import house_restart
    gate, dining, living = two_areas
    _in_flight_on(gate, monkeypatch, (True, "#ffe392", frozenset(), None))
    monkeypatch.setattr(house_restart, "_watch_intended",
                        lambda ids, **kw: asyncio.sleep(0))
    out = asyncio.run(house_restart.after_resume())
    assert out == []
    assert dining.calls == [] and living.calls == []
    assert dining.frozen and living.frozen


def test_red_control_reading_only_what_landed_unfroze_them(two_areas, monkeypatch):
    from spectra.services import house_restart
    gate, dining, living = two_areas
    _in_flight_on(gate, monkeypatch, (True, "#ffe392", frozenset(), None))
    monkeypatch.setattr(house_restart, "_gate_intends_hold", lambda did: False)
    out = asyncio.run(house_restart.after_resume())
    assert out == ["dining-hues", "hue-lights"]


def test_the_stored_hue_hold_counts_before_any_transition_starts(two_areas, monkeypatch):
    """The startup reconcile returned without starting (the stack still
    assembling) and no broadcast has started one yet: the stored toggle
    says hold, so the areas stay frozen."""
    from spectra.services import house_restart
    from spectra.services import room_controls as rc
    gate, dining, living = two_areas
    monkeypatch.setattr(gate, "_transition", None)
    stored = rc.RoomControlState(ambient_enabled=True)
    monkeypatch.setattr(rc, "load_room_controls", lambda: stored)
    monkeypatch.setattr(house_restart, "_watch_intended",
                        lambda ids, **kw: asyncio.sleep(0))
    assert asyncio.run(house_restart.after_resume()) == []
    assert dining.frozen and living.frozen


def test_a_hold_scoped_to_one_area_lets_the_other_stream(two_areas, monkeypatch):
    from spectra.services import house_restart
    gate, dining, living = two_areas
    _in_flight_on(gate, monkeypatch, (True, "#ffe392", frozenset({"dining-hues"}), None))
    monkeypatch.setattr(house_restart, "_watch_intended",
                        lambda ids, **kw: asyncio.sleep(0))
    assert asyncio.run(house_restart.after_resume()) == ["hue-lights"]
    assert dining.calls == [] and living.calls == [False]


def test_an_in_flight_release_lets_them_stream(two_areas, monkeypatch):
    from spectra.services import house_restart
    gate, _dining, _living = two_areas
    _in_flight_on(gate, monkeypatch, (False, None, frozenset(), None))
    assert asyncio.run(house_restart.after_resume()) == ["dining-hues", "hue-lights"]


def test_the_watch_hands_a_landed_area_to_the_gate_and_unfreezes_a_hold_that_never_came(
        two_areas, monkeypatch):
    from spectra.services import house_restart
    gate, dining, living = two_areas
    tr = _in_flight_on(gate, monkeypatch, (True, "#ffe392", frozenset(), None))
    ticks = {"n": 0}

    async def fake_sleep(_s):
        ticks["n"] += 1
        if ticks["n"] == 2:
            # the hold lands on dining; living's intent goes away (he
            # scoped the hold to dining) — the transition is done
            tr.in_flight = False
            monkeypatch.setattr(gate, "_held", True)
            monkeypatch.setattr(gate, "_held_resolved_groups", frozenset({"dining-hues"}))
            from spectra.services import room_controls as rc
            monkeypatch.setattr(rc, "load_room_controls", lambda: rc.RoomControlState(
                ambient_enabled=True, ambient_hue_group_ids=["dining-hues"]))
    out = asyncio.run(house_restart._watch_intended(
        ["dining-hues", "hue-lights"], sleep=fake_sleep, wait_s=5.0))
    assert out == ["hue-lights"]
    assert dining.calls == [] and living.calls == [False]


def test_the_watch_times_out_with_the_intent_still_there_and_stays_frozen(
        two_areas, monkeypatch, caplog):
    """The hold never lands within the watch window (a stuck/erroring
    reconcile), but the gate still INTENDS to hold the area — that is the
    hold's own side, so the area is left frozen rather than unfrozen on a
    timeout, and the still-pending areas are named in a warning so the
    stuck reconcile is not silently invisible."""
    from spectra.services import house_restart
    gate, dining, living = two_areas
    _in_flight_on(gate, monkeypatch, (True, "#ffe392", frozenset(), None))

    async def fake_sleep(_s):
        return None

    with caplog.at_level("WARNING", logger="spectra.services.house_restart"):
        out = asyncio.run(house_restart._watch_intended(
            ["dining-hues", "hue-lights"], sleep=fake_sleep, wait_s=1.0))
    assert out == []
    assert dining.calls == [] and living.calls == []
    assert dining.frozen and living.frozen
    assert any("still frozen after" in r.getMessage() for r in caplog.records)
    assert any("dining-hues" in r.getMessage() and "hue-lights" in r.getMessage()
               for r in caplog.records)


# ── 3. "held" sees a live stream ────────────────────────────────────────────

NAMES = {"rid-nc": "Dining Hue NC", "rid-ne": "Dining Hue NE"}


def _hue_bridge_handler(*, status: str, streamer: str | None):
    held_xy = None

    def handler(request: httpx.Request):
        path = request.url.path
        if path == f"/clip/v2/resource/entertainment_configuration/{ENT}":
            body = {"id": ENT, "status": status}
            if streamer:
                body["active_streamer"] = {"rid": streamer, "rtype": "auth_v1"}
            return httpx.Response(200, json={"data": [body]})
        if path.startswith("/clip/v2/resource/light/"):
            # the light resource LIES during a stream: it reads the held colour
            from spectra.services import ambient
            x, y = ambient._hex_to_xy("#ffe392")
            return httpx.Response(200, json={"data": [{
                "on": {"on": True}, "dimming": {"brightness": 100.0},
                "color": {"xy": {"x": x, "y": y}}}]})
        raise AssertionError(f"unexpected {request.method} {path}")
    return handler


@pytest.fixture
def dining_live(monkeypatch):
    from spectra.services import ambient
    from spectra.services.live_host import live
    refrozen: list[bool] = []

    class Dev:
        type = "hue"
        config = {"ip_address": "192.168.40.28", "username": "u",
                  "entertainment_id": ENT, "hue_application_id": APP_ID}
        frozen = True

        async def set_frozen(self, on):
            refrozen.append(on)

    host = SimpleNamespace(devices={"dining-hues": Dev()})
    monkeypatch.setattr(live, "host", host)
    monkeypatch.setattr(type(live), "active", property(lambda self: True), raising=False)
    monkeypatch.setattr(live, "scope_device_ids", lambda: None, raising=False)

    async def named(client, cfg):
        return list(NAMES.items())
    monkeypatch.setattr(ambient, "_resolve_lights_named", named)

    def use(handler):
        monkeypatch.setattr(ambient, "_bridge_client", lambda cfg: httpx.AsyncClient(
            base_url="https://bridge", transport=httpx.MockTransport(handler)))
    return use, refrozen


def test_verify_held_reports_not_held_when_the_area_is_streaming(dining_live):
    from spectra.services import ambient
    use, _ = dining_live
    use(_hue_bridge_handler(status="active", streamer=APP_ID))
    out = asyncio.run(ambient.verify_held("#ffe392"))
    assert out["status"] == "verified"
    assert out["lights_lit"] == 0
    assert out["unlit"] == sorted(NAMES.values())
    assert out["streaming"] == ["dining-hues"]
    assert out["streaming_ours"] == ["dining-hues"]


def test_red_control_the_light_resource_alone_says_held(dining_live):
    """With the area NOT streaming the same light reads confirm every bulb —
    which is exactly what verify_held reported while it WAS streaming."""
    from spectra.services import ambient
    use, _ = dining_live
    use(_hue_bridge_handler(status="inactive", streamer=None))
    out = asyncio.run(ambient.verify_held("#ffe392"))
    assert out["lights_lit"] == 2 and out["unlit"] == []
    assert "streaming" not in out


def test_verify_looks_reports_a_streaming_house_hold_too(dining_live):
    from spectra.services import ambient
    use, _ = dining_live
    use(_hue_bridge_handler(status="active", streamer=APP_ID))
    looks = (("dining-hues", "hold", 370, None, 100.0),)
    out = asyncio.run(ambient.verify_looks(looks))
    assert out["lights_lit"] == 0 and out["streaming"] == ["dining-hues"]


def test_an_unreadable_entertainment_status_is_never_counted(dining_live):
    from spectra.services import ambient
    use, _ = dining_live

    def handler(request):
        if "entertainment_configuration" in request.url.path:
            return httpx.Response(503)
        return _hue_bridge_handler(status="inactive", streamer=None)(request)
    use(handler)
    out = asyncio.run(ambient.verify_held("#ffe392"))
    assert out["lights_lit"] == 2 and "streaming" not in out


def test_the_verifier_refreezes_our_own_stream_and_never_reports_held(dining_live, monkeypatch):
    from spectra.services import ambient
    from spectra.services import ambient_music_gate as gate
    use, refrozen = dining_live
    use(_hue_bridge_handler(status="active", streamer=APP_ID))
    monkeypatch.setattr(gate, "_held", True)
    monkeypatch.setattr(gate, "_held_looks", None)
    monkeypatch.setattr(gate, "_transition", None)

    async def no_repair(unlit, color):
        return {"repaired": [], "left_off": [], "unconfirmed": sorted(unlit)}
    monkeypatch.setattr(ambient, "repair_stragglers", no_repair)
    out = asyncio.run(gate.verify_now())
    assert refrozen == [True]
    assert out["refrozen"] == ["dining-hues"]
    assert gate._verified_ok is False
    assert gate.status()["verify"]["lights_lit"] == 0


def test_someone_elses_stream_is_reported_not_stopped(dining_live, monkeypatch):
    from spectra.services import ambient
    from spectra.services import ambient_music_gate as gate
    use, refrozen = dining_live
    use(_hue_bridge_handler(status="active", streamer="the-hue-app"))
    monkeypatch.setattr(gate, "_held", True)
    monkeypatch.setattr(gate, "_held_looks", None)
    monkeypatch.setattr(gate, "_transition", None)

    async def no_repair(unlit, color):
        return {"repaired": [], "left_off": [], "unconfirmed": sorted(unlit)}
    monkeypatch.setattr(ambient, "repair_stragglers", no_repair)
    out = asyncio.run(gate.verify_now())
    assert refrozen == []
    assert out["streaming"] == ["dining-hues"] and out["refrozen"] == []
    assert gate._verified_ok is False


def test_status_payload_is_json_serialisable(dining_live, monkeypatch):
    from spectra.services import ambient_music_gate as gate
    use, _ = dining_live
    use(_hue_bridge_handler(status="active", streamer=APP_ID))
    monkeypatch.setattr(gate, "_held", True)
    monkeypatch.setattr(gate, "_held_looks", None)
    monkeypatch.setattr(gate, "_transition", None)
    from spectra.services import ambient

    async def no_repair(unlit, color):
        return {"repaired": [], "left_off": [], "unconfirmed": sorted(unlit)}
    monkeypatch.setattr(ambient, "repair_stragglers", no_repair)
    json.dumps(asyncio.run(gate.verify_now()))
