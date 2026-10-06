"""THE STREAM NEVER STARTS ON AN AREA HOLDING A BULB SPECTRA MAY NOT LIGHT
(2026-10-06).

THE INCIDENT (DJ, reading the bridge): house lighting was switched OFF at
17:35:29. After a deploy restart at 18:28:01 the Loft Ceiling Uplight and
the three Ledge bulbs — the four bulbs left to Home Assistant, NOT on
storage/spectra/hue_scope.json — turned on one by one from 18:28:07, with
the rest of the living-room group. They were off at 18:28:05.

THE CAUSE, from the journal and the code, and it is not Ambient: Ambient
had been switched off at 17:38:24 (room_controls.json, unchanged since)
and released at 17:38:45. Every Hue REST write already goes through
fx/hue_scope.put and could not have reached those bulbs. What ran was the
music show's entertainment stream: on start-up HueDevice asked the
"Music Group" bridge to START a session (`action: start`), and starting a
session switches on every bulb in the area — 18:28:07 is seventeen seconds
before the DTLS handshake completed (18:28:24), so before a single frame
could have been sent. The Music Group area's ten channels are six
allow-listed bulbs and those four.

MASKING CONDITION: while a house mode (or Ambient) holds Hue the area is
FROZEN and no session is ever started — PR 335 even kept the areas frozen
across a restart. With house lighting and Ambient both off nothing freezes
the area, so the restart started a session and lit them.

THE FIX (fx/hue_scope.stream_refusal, fx/devices/hue.py): HueDevice reads
its area's bulbs from the bridge immediately before every session start and
never sends `action: start` for an area that holds a bulb off the
allow-list. That does not depend on the house layer: it is the one door
every path that streams Hue goes through (a take, a restart's resume,
Ambient's or a house mode's release, a flush's reconnect).

The bridge here is a MODEL of the behaviour the timeline shows: a PUT
`action: start` switches every bulb in the area on. Each proof below has its
red control — the shipped driver, which starts the session anyway.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging

import pytest
from types import SimpleNamespace

from fx import hue_scope
from fx.devices import hue as hue_mod
from fx.devices.hue import HueDevice

# ── his real bulbs (storage/spectra/hue_scope.json, read from the bridges) ──

ALLOWED = {
    "81abef5d-2fac-4ec9-b805-173ca0f855d6": "Dining Hue NC",
    "4a266388-e1ab-4c5c-b2e8-c98c20c62c88": "Dining Hue NE",
    "b8e8f00c-fc8c-402a-8935-8b9396f9c8b0": "Dining Hue NW",
    "8c37c318-1e5d-4b8a-aaff-603a1f48cba5": "Dining Hue SC",
    "748798ec-1ec1-44b9-99ad-9e101cdc94a5": "Dining Hue SE",
    "8a1dada8-2ffb-4be4-b344-2bd792617f91": "Dining Hue SW",
    "46894b55-3923-4273-b67c-233d5da5c56d": "Kitchen Infuse",
    "9401f41b-8cd6-49dd-b237-69d531661c22": "Living Room Corner",
    "d1c4fb0e-272f-4493-b4ea-152b72e18dae": "Media Ceiling Uplight",
    "ede288be-9d2b-499f-8bbc-9ed946d31753": "Standing Lamp 1",
    "e068daa2-0ff4-4eed-9e7d-0ed5b33662a5": "Standing Lamp 2",
    "847cf0d1-9e97-413c-9174-ae0cb45ed184": "Standing Lamp Side",
    "4b689967-4290-4982-9b77-5ae1cb12ebdf": "Under Spiral",
}
EXCLUDED = {
    "f75d60db-e135-44f6-bd2e-f990eb337510": "Ledge Center",
    "bcbd6860-bc67-4652-885f-c4b2499e76e0": "Ledge Left",
    "f175b376-7907-4d5c-b942-5590403674a1": "Ledge Right",
    "f3425ad2-5776-4d18-a413-83cbe4922996": "Loft Ceiling Uplight",
}
EXCLUDED_NAMES = sorted(EXCLUDED.values())

#: the "Music Group" area on the living-room bridge — ten channels, one bulb
#: each (data/spectra-stuck-bulb-cause/report.md read it off the bridge)
MUSIC_GROUP = ["Loft Ceiling Uplight", "Media Ceiling Uplight",
               "Living Room Corner", "Under Spiral", "Standing Lamp 1",
               "Standing Lamp 2", "Standing Lamp Side", "Ledge Left",
               "Ledge Right", "Ledge Center"]
DINING_MUSIC = ["Dining Hue NC", "Dining Hue NE", "Dining Hue NW",
                "Dining Hue SC", "Dining Hue SE", "Dining Hue SW",
                "Kitchen Infuse"]
RID = {name: rid for rid, name in {**ALLOWED, **EXCLUDED}.items()}


@pytest.fixture
def his_scope(tmp_path, monkeypatch):
    """The REAL allow-list reader over a copy of his hue_scope.json (the
    conftest default is permissive — every bulb allowed)."""
    path = tmp_path / "hue_scope.json"
    path.write_text(json.dumps({"lights": ALLOWED, "excluded": EXCLUDED}))
    monkeypatch.setattr(hue_scope, "SCOPE_FILE", path)
    monkeypatch.setattr(hue_scope, "load_allowed", hue_scope.read_allowed_file)
    return path


# ── a model bridge ───────────────────────────────────────────────────────────

class ModelBridge:
    """One Hue bridge with one entertainment area. Bulb state is tracked;
    `action: start` switches EVERY bulb of the area on (what 18:28:07 shows),
    `action: stop` ends the session and leaves the bulbs as they are."""

    def __init__(self, ent_id: str, names: list[str]):
        self.ent_id = ent_id
        self.names = names
        self.state = {name: {"on": {"on": False},          # all off, as at 18:28:05
                             "dimming": {"brightness": 1.0},
                             "color": {"xy": {"x": 0.3127, "y": 0.3290}}}
                      for name in names}
        self.session = False
        self.actions: list[str] = []
        self.rest_writes: list[str] = []                   # bulb names PUT over REST

    @property
    def on(self) -> dict:
        return {n: bool(st["on"]["on"]) for n, st in self.state.items()}

    def config(self) -> dict:
        return {"id": self.ent_id, "id_v1": "/groups/200", "name": "Music Group",
                "channels": [
                    {"channel_id": i, "position": {"x": 0, "y": 0, "z": 0},
                     "members": [{"service": {"rtype": "entertainment",
                                              "rid": f"ent-{RID[n]}"}}]}
                    for i, n in enumerate(self.names)]}

    def request(self, method, endpoint, data=None, ssl=False):
        endpoint = "/" + endpoint.lstrip("/")
        if method == "GET" and endpoint == f"/clip/v2/resource/entertainment_configuration/{self.ent_id}":
            return {"data": [self.config()]}, {}
        if method == "GET" and endpoint == "/clip/v2/resource/entertainment":
            return {"data": [{"id": f"ent-{RID[n]}", "owner": {"rid": f"dev-{RID[n]}"}}
                             for n in self.names]}, {}
        if method == "GET" and endpoint == "/clip/v2/resource/light":
            return {"data": [{"id": RID[n], "owner": {"rid": f"dev-{RID[n]}"},
                              "metadata": {"name": n}} for n in self.names]}, {}
        if method == "PUT" and endpoint == f"/clip/v2/resource/entertainment_configuration/{self.ent_id}":
            action = (data or {}).get("action")
            self.actions.append(action)
            if action == "start":
                self.session = True
                for n in self.names:
                    self.state[n]["on"]["on"] = True
            elif action == "stop":
                self.session = False
            return {"data": [{"rid": self.ent_id}]}, {}
        raise AssertionError(f"unexpected hue request {method} {endpoint}")

    def httpx_handler(self, request):
        """The same bridge as seen by spectra.services.ambient (httpx)."""
        import httpx
        path = request.url.path
        name_of = {rid: n for n, rid in RID.items()}
        if path.startswith("/clip/v2/resource/light/"):
            rid = path.rsplit("/", 1)[-1]
            name = name_of[rid]
            if request.method == "PUT":
                self.rest_writes.append(name)
                body = json.loads(request.content)
                self.state[name].update({k: v for k, v in body.items()
                                         if k in ("on", "dimming", "color")})
                return httpx.Response(200, json={"data": []})
            return httpx.Response(200, json={"data": [dict(self.state[name], id=rid)]})
        payload, _ = self.request(request.method, path)
        return httpx.Response(200, json=payload)

    def starts(self) -> int:
        return self.actions.count("start")

    def lit(self) -> list[str]:
        return sorted(n for n, on in self.on.items() if on)


class _FakeDtls:
    """The DTLS context: wrap/connect/handshake succeed instantly, sends are
    recorded. Replacing the context (not a method) keeps the SHIPPED
    `_blocking_activate` runnable for the red controls."""

    def __init__(self):
        self.sent: list[bytes] = []

    def wrap_socket(self, sock, server_hostname):
        outer = self

        class Wrapped:
            _socket = sock

            def connect(self, addr):
                pass

            def do_handshake(self):
                pass

            def send(self, data):
                outer.sent.append(bytes(data))

            def close(self):
                sock.close()
        return Wrapped()


class _Ledfx:
    def __init__(self, loop):
        self.loop = loop
        self.thread_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def _device(loop, bridge: ModelBridge, did="hue-lights", name="Living Room Hues"):
    dev = HueDevice(_Ledfx(loop), {
        "name": name, "ip_address": "192.168.40.215", "group_name": "Music Group",
        "udp_port": 2100, "hue_application_id": "app-id", "clientkey": "00" * 16,
        "username": "user", "entertainment_id": bridge.ent_id,
        "pixel_count": len(bridge.names), "refresh_rate": 30,
    })
    dev._id = did
    dev._type = "hue"
    dev._hue_request = bridge.request
    dev._dtls_client_context = _FakeDtls()
    dev._destination = "192.168.40.215"
    return dev


def _run(coro):
    return asyncio.run(coro)


async def _close(dev):
    """Snapshot what the stream looked like, then tear the device down
    inside its own loop (its stop is dispatched there), so nothing fires
    after the loop has closed."""
    snap = SimpleNamespace(ready=dev._stream_ready, refusal=getattr(dev, "scope_refusal", None),
                           sent=list(dev._dtls_client_context.sent))
    await dev.async_deactivate()
    return snap


async def _settle(dev, seconds=0.3):
    """Let the fire-and-forget activation run to its end."""
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)


def _shipped_driver(monkeypatch):
    """The red control: the driver as shipped, which starts every session —
    the pre-fix _blocking_activate (no scope check), verbatim."""
    import socket

    def shipped(self):
        with HueDevice._activation_lock:
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
    monkeypatch.setattr(HueDevice, "_blocking_activate", shipped)


# ═══ 1. the judgement, on his real area ═══════════════════════════════════

def test_his_music_group_area_is_refused_by_name(his_scope):
    bridge = ModelBridge("music", MUSIC_GROUP)
    area = hue_scope.area_lights(bridge.config(),
                                 bridge.request("GET", "/clip/v2/resource/entertainment")[0]["data"],
                                 bridge.request("GET", "/clip/v2/resource/light")[0]["data"])
    assert sorted(name for _c, _r, name in area) == sorted(MUSIC_GROUP)
    reason = hue_scope.stream_refusal(area)
    assert reason is not None
    for name in EXCLUDED_NAMES:
        assert name in reason
    for name in set(MUSIC_GROUP) - set(EXCLUDED_NAMES):
        assert name not in reason, f"{name} is allow-listed and was named"


def test_his_dining_area_may_stream(his_scope):
    bridge = ModelBridge("dining", DINING_MUSIC)
    area = hue_scope.area_lights(bridge.config(),
                                 bridge.request("GET", "/clip/v2/resource/entertainment")[0]["data"],
                                 bridge.request("GET", "/clip/v2/resource/light")[0]["data"])
    assert hue_scope.stream_refusal(area) is None


def test_a_bulb_that_cannot_be_identified_is_refused_even_when_everything_is_allowed():
    """Fail closed: the permissive conftest scope allows every rid, but a
    channel whose bulb the bridge does not name is still not streamed."""
    cfg = {"channels": [{"channel_id": 0, "members": [
        {"service": {"rtype": "entertainment", "rid": "ent-unknown"}}]}]}
    area = hue_scope.area_lights(cfg, [], [])
    assert area == [(0, None, "channel 0 (bulb not identified)")]
    assert hue_scope.stream_refusal(area) is not None
    assert hue_scope.stream_refusal([]) is not None


def test_a_missing_scope_file_refuses_every_area(tmp_path, monkeypatch):
    monkeypatch.setattr(hue_scope, "SCOPE_FILE", tmp_path / "absent.json")
    monkeypatch.setattr(hue_scope, "load_allowed", hue_scope.read_allowed_file)
    bridge = ModelBridge("dining", DINING_MUSIC)
    area = hue_scope.area_lights(bridge.config(),
                                 bridge.request("GET", "/clip/v2/resource/entertainment")[0]["data"],
                                 bridge.request("GET", "/clip/v2/resource/light")[0]["data"])
    assert hue_scope.stream_refusal(area) is not None


# ═══ 2. the driver: the restart's activation, his real bulbs ════════════════

def test_a_restart_never_starts_a_session_on_the_music_group(his_scope, caplog):
    """The 18:28 restart, at the driver: the stack comes up, the Music Group
    device activates. No `action: start` reaches the bridge, so no bulb is
    switched on, and the refusal names the four bulbs at CRITICAL."""
    bridge = ModelBridge("music", MUSIC_GROUP)

    async def main():
        dev = _device(asyncio.get_running_loop(), bridge)
        with caplog.at_level(logging.CRITICAL, logger=hue_mod.__name__):
            dev.activate()
            await _settle(dev)
        return await _close(dev)

    dev = _run(main())
    assert bridge.starts() == 0, f"a session was started: {bridge.actions}"
    assert bridge.lit() == [], f"bulbs switched on: {bridge.lit()}"
    assert dev.ready is False and dev.refusal
    for name in EXCLUDED_NAMES:
        assert name in dev.refusal
    criticals = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(criticals) == 1 and "Ledge Center" in criticals[0].getMessage()


def test_red_control_the_shipped_driver_lights_all_four(his_scope):
    """The shipped driver on the same restart: the session starts and the
    bridge switches every bulb on — the four excluded ones with the rest."""
    bridge = ModelBridge("music", MUSIC_GROUP)
    mp = pytest.MonkeyPatch()
    try:
        _shipped_driver(mp)

        async def main():
            dev = _device(asyncio.get_running_loop(), bridge)
            dev.activate()
            await _settle(dev)
            await _close(dev)
        _run(main())
    finally:
        mp.undo()
    assert bridge.starts() == 1
    for name in EXCLUDED_NAMES:
        assert bridge.on[name] is True


def test_a_clean_area_still_streams(his_scope):
    """The fix is not "no Hue": the dining area holds only allow-listed
    bulbs, so its session starts and frames flow."""
    bridge = ModelBridge("dining", DINING_MUSIC)

    async def main():
        dev = _device(asyncio.get_running_loop(), bridge, did="dining-hues",
                      name="Dining Hues")
        dev.activate()
        await _settle(dev)
        dev.flush([[10, 20, 30]] * len(DINING_MUSIC))
        return await _close(dev)

    dev = _run(main())
    assert bridge.starts() == 1
    assert dev.ready is True and dev.refusal is None
    assert dev.sent, "no frame reached the stream"


def test_a_refused_area_sends_no_frame_and_rechecks_slowly(his_scope, monkeypatch):
    """Frames keep arriving from the render thread; none is sent, and the
    area is re-read at the slow cadence (so fixing it in the Hue app is
    picked up without a restart), never every five seconds."""
    bridge = ModelBridge("music", MUSIC_GROUP)
    reconnects = []

    async def main():
        dev = _device(asyncio.get_running_loop(), bridge)
        dev.activate()
        await _settle(dev)
        monkeypatch.setattr(HueDevice, "_trigger_reconnect",
                            lambda self: reconnects.append(1))
        clock = [dev._last_reconnect_attempt + HueDevice.RECONNECT_RETRY_INTERVAL + 1]
        monkeypatch.setattr(hue_mod.time, "monotonic", lambda: clock[0])
        dev.flush([[255, 255, 255]] * len(MUSIC_GROUP))
        clock[0] = dev._last_reconnect_attempt + HueDevice.SCOPE_RECHECK_INTERVAL + 1
        dev.flush([[255, 255, 255]] * len(MUSIC_GROUP))
        return await _close(dev)

    dev = _run(main())
    assert dev.sent == []
    assert reconnects == [1], "re-read on the five-second reconnect cadence"
    assert bridge.lit() == []


def test_fixing_the_area_in_the_hue_app_lets_the_rest_stream(his_scope):
    """Once the four bulbs are taken out of the area, the next re-check
    starts the session for the six that remain — and lights only them."""
    bridge = ModelBridge("music", MUSIC_GROUP)

    async def main():
        dev = _device(asyncio.get_running_loop(), bridge)
        dev.activate()
        await _settle(dev)
        assert dev.scope_refusal
        bridge.names = [n for n in MUSIC_GROUP if n not in EXCLUDED_NAMES]
        dev._trigger_reconnect()
        await _settle(dev)
        return await _close(dev)

    dev = _run(main())
    assert bridge.starts() == 1
    assert dev.ready is True and dev.refusal is None
    assert not any(bridge.on[n] for n in EXCLUDED_NAMES)


def test_an_unreadable_area_never_starts_a_session(his_scope):
    """A bridge that will not say what is in the area is not streamed."""
    bridge = ModelBridge("music", MUSIC_GROUP)
    real = bridge.request

    def flaky(method, endpoint, data=None, ssl=False):
        if method == "GET" and endpoint.endswith("/resource/light"):
            raise OSError("bridge timed out")
        return real(method, endpoint, data, ssl)
    bridge.request = flaky

    async def main():
        dev = _device(asyncio.get_running_loop(), bridge)
        dev.activate()
        await _settle(dev)
        return await _close(dev)

    dev = _run(main())
    assert bridge.starts() == 0 and bridge.lit() == []
    assert "could not" in dev.refusal


# ═══ 3. every way back to a stream goes through the same door ═══════════════

def test_ambient_or_a_house_mode_letting_go_never_starts_the_music_group(his_scope):
    """Ambient (or a house mode's Hue look) holds the area FROZEN; letting
    go calls set_frozen(False), which re-engages the stream — at 17:38:45
    on 2026-10-06 that is exactly what started the session. Refused."""
    bridge = ModelBridge("music", MUSIC_GROUP)

    async def main():
        dev = _device(asyncio.get_running_loop(), bridge)
        dev.activate()                       # comes up, refused
        await _settle(dev)
        await dev.set_frozen(True)           # Ambient ON: session stopped
        await dev.set_frozen(False)          # Ambient released
        await _settle(dev)
        return await _close(dev)

    dev = _run(main())
    assert bridge.starts() == 0
    assert bridge.lit() == []


# ═══ 4. the incident, at the service: house off, Ambient, restart ═══════════

@pytest.fixture
def incident(his_scope, monkeypatch):
    """His room at 17:35-18:28 on 2026-10-06: house lighting switched OFF,
    SPECTRA owns, the live host carries the REAL Hue driver for the Music
    Group area, every bulb of which is off on the bridge."""
    import httpx
    from fx import light_ownership as lo
    from spectra.models.house_mode import HouseLibrary, HouseSettings
    from spectra.services import ambient, house, house_store
    from spectra.services.live_host import live

    house_store.save_library(HouseLibrary(settings=HouseSettings(
        enabled=False, hue_excluded_lights=EXCLUDED_NAMES)))
    assert house.layer_active() is False
    bridge = ModelBridge("music", MUSIC_GROUP)

    def fake_bridge_client(cfg):
        return httpx.AsyncClient(base_url=f"https://{cfg['ip_address']}",
                                 transport=httpx.MockTransport(bridge.httpx_handler))
    monkeypatch.setattr(ambient, "_bridge_client", fake_bridge_client)
    for knob in ("AMBIENT_WRITE_STAGGER_MS", "AMBIENT_CONFIRM_SETTLE_MS",
                 "AMBIENT_RETRY_SPACING_MS", "AMBIENT_TRANSITION_MS",
                 "AMBIENT_CATCHUP_MS"):
        monkeypatch.setattr(ambient, knob, 0)
    ambient._light_cache.clear()
    monkeypatch.setattr(lo, "load", lambda: lo.OwnershipRecord(owner=lo.SPECTRA))
    monkeypatch.setattr(live, "scope", None)
    monkeypatch.setattr(live, "assembling", False, raising=False)
    yield SimpleNamespace(bridge=bridge, live=live, ambient=ambient)
    ambient._light_cache.clear()


def _install(incident, monkeypatch, dev):
    class Host:
        devices = {"hue-lights": dev}
    monkeypatch.setattr(incident.live, "host", Host())
    monkeypatch.setattr(type(incident.live), "active", property(lambda self: True))


def test_house_off_restart_then_ambient_never_lights_the_four(incident, monkeypatch):
    """House lighting off -> the restart's resume -> Ambient on -> Ambient
    off. Through all of it no session is started on the Music Group, and
    neither the stream nor a REST write ever switches on a bulb that was
    off — the four excluded ones above all, which are never even written."""
    from spectra.services import house_restart
    bridge = incident.bridge

    async def main():
        # the restart: house off, so nothing is re-installed or pre-frozen
        assert house_restart.prepare_for_resume()["installed"] is False
        dev = _device(asyncio.get_running_loop(), bridge)
        _install(incident, monkeypatch, dev)
        dev.activate()
        await _settle(dev)
        after_restart = bridge.lit()
        # Ambient on (the brief's reading of 18:28), then off (17:38's)
        on = await incident.ambient.reconcile(True, "#ffe392")
        await _settle(dev)
        off = await incident.ambient.reconcile(False, None)
        await _settle(dev)
        snap = await _close(dev)
        return after_restart, on, off, snap

    after_restart, on, off, snap = _run(main())
    assert after_restart == [], f"the restart switched on {after_restart}"
    assert on["status"] == "on" and on["lights_set"] == 6
    assert off["status"] == "off"
    assert bridge.starts() == 0, f"a session was started: {bridge.actions}"
    for name in EXCLUDED_NAMES:
        assert bridge.on[name] is False, f"{name} was switched on"
        assert name not in bridge.rest_writes, f"{name} was written over REST"
    assert snap.refusal and all(n in snap.refusal for n in EXCLUDED_NAMES)


def test_red_control_house_off_restart_with_the_shipped_driver(incident, monkeypatch):
    """The same restart on the shipped driver: the session starts and the
    four excluded bulbs come on with the rest — 18:28:07."""
    _shipped_driver(monkeypatch)
    bridge = incident.bridge

    async def main():
        dev = _device(asyncio.get_running_loop(), bridge)
        _install(incident, monkeypatch, dev)
        dev.activate()
        await _settle(dev)
        await _close(dev)

    _run(main())
    assert bridge.starts() == 1
    assert [n for n in EXCLUDED_NAMES if bridge.on[n]] == EXCLUDED_NAMES


# ═══ 5. it is said where he looks ══════════════════════════════════════════

def test_the_refusal_reaches_ownership_and_liveness(monkeypatch):
    from spectra.api import ownership
    from spectra.services.live_host import live

    class Refused:
        scope_refusal = "refused to start the Hue entertainment stream: Ledge Left"

    class Streaming:
        scope_refusal = None

    class Wled:
        pass

    class Registry:
        """The real fx Devices registry's shape: iterable + get(), NO .items()."""
        def __init__(self, d):
            self._d = d

        def __iter__(self):
            return iter(self._d)

        def get(self, key):
            return self._d.get(key)

    class Host:
        devices = Registry({"hue-lights": Refused(), "dining-hues": Streaming(),
                            "crystal": Wled()})
    monkeypatch.setattr(live, "host", Host())
    assert live.hue_stream_refusals() == {"hue-lights": Refused.scope_refusal}
    assert ownership._record_json()["hue_stream_refusals"] == {
        "hue-lights": Refused.scope_refusal}
    monkeypatch.setattr(live, "host", None)
    assert live.hue_stream_refusals() == {}
