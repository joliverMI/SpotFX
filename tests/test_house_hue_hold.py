"""HUE HOLD, PER AREA (house lighting): spectra/services/ambient.py's
`reconcile_looks`/`verify_looks` and the gate wiring in
ambient_music_gate.py.

  * A colour-temperature look is written as CLIP v2 `color_temperature.mirek`
    at the look's brightness, with the mode's glide as `dynamics.duration`,
    and confirmed by READING IT BACK — the same paced write/confirm engine
    the colour hold has always used.
  * An exact area beats "*"; "off" switches the bulbs off over the bridge.
  * An area with no look is released if it was held, and left alone if not.
  * The take scope still bounds which areas exist at all.
  * The periodic verifier REPORTS a bulb someone changed and never repairs
    it (house lighting yields until the next mode change).
  * The gate routes a house directive to reconcile_looks and leaves the
    room toggle's stored value alone; with no directive it is the toggle.

Offline: the mock bridge and fake devices from tests/test_ambient.py.
"""
from __future__ import annotations

import pytest

from spectra.services import ambient
from spectra.services.live_host import live
from tests.test_ambient import (FakeHost, FakeHueDevice, _clear_light_cache,  # noqa: F401
                                _fast_ambient_pacing, _hue_handler, _install_bridge, _run)


@pytest.fixture
def bridge(monkeypatch):
    calls: list = []
    _install_bridge(monkeypatch, _hue_handler(calls))
    return calls


def _puts(calls):
    return [c for c in calls if c[0] == "REST" and c[1] == "PUT"]


async def _state(dev, rid="l1"):
    async with ambient._bridge_client(dev.config) as client:
        return (await ambient._hue_get(client, f"/clip/v2/resource/light/{rid}"))["data"][0]


def test_a_colour_temperature_look_is_held_and_confirmed(monkeypatch, bridge):
    dev = FakeHueDevice("10.0.0.1", bridge)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))
    looks = (("*", "hold", 284, None, 100.0),)
    result = _run(ambient.reconcile_looks(looks, 90_000))
    assert result["status"] == "on" and result["lights_set"] == 1
    assert dev.frozen is True
    state = _run(_state(dev))
    assert state["color_temperature"]["mirek"] == 284
    assert state["dimming"]["brightness"] == 100.0


def test_the_glide_rides_on_dynamics_duration(monkeypatch):
    bodies = []
    calls: list = []
    inner = _hue_handler(calls)

    def handler(request):
        if request.method == "PUT":
            import json
            bodies.append(json.loads(request.content))
        return inner(request)
    _install_bridge(monkeypatch, handler)
    dev = FakeHueDevice("10.0.0.1", calls)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))
    _run(ambient.reconcile_looks((("*", "hold", 500, None, 60.0),), 90_000))
    assert bodies[0]["dynamics"] == {"duration": 90_000}
    assert bodies[0]["color_temperature"] == {"mirek": 500}
    _run(ambient.reconcile_looks((("*", "hold", 400, None, 60.0),), 90_000, snap=True))
    assert "dynamics" not in bodies[-1], "a snap drops the ramp"


@pytest.fixture
def two_bridges(monkeypatch):
    """One mock bridge per IP (the shared handler is keyed by path only, so
    two devices would otherwise share one bulb)."""
    calls: list = []
    handlers = {"10.0.0.1": _hue_handler(calls), "10.0.0.2": _hue_handler(calls)}
    _install_bridge(monkeypatch, lambda request: handlers[request.url.host](request))
    return calls


def test_an_exact_area_beats_every_area_and_off_switches_off(monkeypatch, two_bridges):
    bridge = two_bridges
    living = FakeHueDevice("10.0.0.1", bridge)
    dining = FakeHueDevice("10.0.0.2", bridge)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": living, "dining-hues": dining}))
    looks = (("*", "hold", 284, None, 100.0), ("dining-hues", "off", None, None, 100.0))
    result = _run(ambient.reconcile_looks(looks, 0))
    assert result["status"] == "on"
    assert _run(_state(living))["color_temperature"]["mirek"] == 284
    assert _run(_state(dining))["on"]["on"] is False
    assert living.frozen is True and dining.frozen is True


def test_an_area_with_no_look_is_released_only_if_it_was_held(monkeypatch, two_bridges):
    bridge = two_bridges
    living = FakeHueDevice("10.0.0.1", bridge)
    dining = FakeHueDevice("10.0.0.2", bridge)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": living, "dining-hues": dining}))
    _run(ambient.reconcile_looks((("hue-lights", "hold", 284, None, 100.0),), 0))
    assert dining.frozen is None, "never frozen, never touched"
    _run(ambient.reconcile_looks((("*", "hold", 284, None, 100.0),), 0))
    assert dining.frozen is True
    result = _run(ambient.reconcile_looks((("hue-lights", "hold", 284, None, 100.0),), 0))
    assert dining.frozen is False and result["released"] == ["dining-hues"]


def test_show_looks_hold_nothing(monkeypatch, bridge):
    dev = FakeHueDevice("10.0.0.1", bridge)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))
    _run(ambient.reconcile_looks((("*", "hold", 284, None, 100.0),), 0))
    result = _run(ambient.reconcile_looks((("*", "show", None, None, 100.0),), 0))
    assert result["status"] == "off" and dev.frozen is False


def test_no_live_stack_touches_nothing(monkeypatch, bridge):
    monkeypatch.setattr(live, "host", None)
    assert _run(ambient.reconcile_looks((("*", "hold", 284, None, 100.0),), 0)) == {"status": "dark"}
    assert _puts(bridge) == []


def test_the_verifier_reports_a_changed_bulb_and_never_repairs_it(monkeypatch, bridge):
    from spectra.services import ambient_music_gate as gate
    dev = FakeHueDevice("10.0.0.1", bridge)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))
    looks = (("*", "hold", 284, None, 100.0),)
    _run(ambient.reconcile_looks(looks, 0))
    gate._held = True
    gate._held_looks = looks

    async def change_it():
        async with ambient._bridge_client(dev.config) as client:
            await ambient._hue_put(client, "/clip/v2/resource/light/l1",
                                   {"color_temperature": {"mirek": 153}})
    _run(change_it())
    puts_before = len(_puts(bridge))
    result = _run(gate.verify_now())
    assert result["unlit"] == ["l1"] and "yielded" in result["repair"]
    assert len(_puts(bridge)) == puts_before, "house lighting never fights a changed bulb"


def test_the_gate_routes_a_house_directive_to_per_area_looks(monkeypatch):
    from spectra.services import ambient_music_gate as gate, house
    seen = {}

    async def fake_looks(looks, ramp_ms, token=None, snap=False):
        seen["looks"], seen["ramp"] = looks, ramp_ms
        return {"status": "on", "devices": ["hue-lights"], "lights_set": 1, "lights_total": 1}

    async def fake_toggle(*a, **kw):
        seen["toggle"] = True
        return {"status": "off", "devices": []}
    monkeypatch.setattr(ambient, "reconcile_looks", fake_looks)
    monkeypatch.setattr(ambient, "reconcile", fake_toggle)
    monkeypatch.setattr(ambient, "room_available", lambda: True)
    directive = house.HueDirective(looks=(("*", "hold", 284, None, 100.0),),
                                   ramp_ms=90_000, mode_name="Standard")
    monkeypatch.setattr(house, "hue_directive", lambda: directive)
    result = _run(gate.reconcile(False))
    assert result["status"] == "on" and "toggle" not in seen
    assert seen == {"looks": directive.looks, "ramp": 90_000}
    status = gate.status()
    assert status["house"]["mode"] == "Standard" and status["intent"] == "on"
    # landed: the same directive again is a no-op
    seen.clear()
    _run(gate.reconcile(False))
    assert seen == {}
    # no directive any more: the room toggle (off) takes Hue back
    monkeypatch.setattr(house, "hue_directive", lambda: None)
    _run(gate.reconcile(False))
    assert seen.get("toggle") is True


def test_a_landed_hold_is_applied_again_after_a_release_and_take_back(monkeypatch):
    """A hold that landed, then the room released (the verifier reads it
    dark), then taken back: the gate must hold again — the stack that came
    back has nothing frozen. Applies to the toggle and to a house hold."""
    from spectra.services import ambient_music_gate as gate, house
    calls = []

    async def fake_looks(looks, ramp_ms, token=None, snap=False):
        calls.append(looks)
        return {"status": "on", "devices": ["hue-lights"], "lights_set": 1, "lights_total": 1}
    monkeypatch.setattr(ambient, "reconcile_looks", fake_looks)
    available = {"v": True}
    monkeypatch.setattr(ambient, "room_available", lambda: available["v"])
    directive = house.HueDirective(looks=(("*", "hold", 284, None, 100.0),),
                                   ramp_ms=0, mode_name="Standard")
    monkeypatch.setattr(house, "hue_directive", lambda: directive)
    _run(gate.reconcile(False))
    assert len(calls) == 1
    _run(gate.reconcile(False))
    assert len(calls) == 1, "landed: a repeat is a no-op"
    available["v"] = False          # released
    _run(gate.reconcile(False))
    available["v"] = True           # taken back
    _run(gate.reconcile(False))
    assert len(calls) == 2, "the take-back holds Hue again"
