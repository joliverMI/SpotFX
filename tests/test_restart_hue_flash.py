"""A RESTART UNDER A HOUSE MODE NEVER LIGHTS A HUE BULB (2026-10-06).

THE INCIDENT (River's house witness): every spectra.service restart lit 13
Hue bulbs for ~20 s — the dining Hues, the standing lamps, the media
ceiling uplight, the living-room corner, under-spiral — ON at stop+5 s, OFF
at stop+28 s, with no Home Assistant context, while Away held every one of
them off. Loft and ledge (outside fx/hue_scope's allow-list) stayed dark;
so did every WLED (withheld by house_restart).

THE CAUSE, from the journal (09:30, 07:55, 18:47 — identical each time):
not the stop and not the bridge. On START, resume_own_room() brings the
stack up with the record already saying SPECTRA owns and NO handover in
flight; `live.active` reads True from the moment the host is SET, ~16 s
before activation ends and the engine goes live. The bridge connected ~1.5
s in, its first state broadcast ran the Hue Hold gate, the house layer's
gate refused ("engine on paper") so `house.hue_directive()` was None, and
the gate fell through to the ROOM TOGGLE — stored `ambient_enabled: true`,
#ffe392 — and held all 13 allow-listed bulbs at it, at 100 % ("Ambient ON
... 13 light(s) confirmed"). Only once the engine went live did app.py's
reconcile land the mode's own "off" look ("Hue Hold (house) ... held").

Two independent fixes, each proven here with the shipped behaviour as its
red control:
  * ambient.room_available() refuses while the stack is still assembling
    (`live.assembling`), exactly as it refuses mid-handover.
  * the gate HOLDS BACK the room toggle while a set house mode will hold
    Hue once the layer may act (`house.pending_hue_directive()`), which also
    covers the window after assembly while the engine is still on paper.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from fx import light_ownership as lo
from spectra.models.house_mode import HouseMode, HueLook
from spectra.services import ambient, engine, house, house_store
from spectra.services import ambient_music_gate as gate
from spectra.services.live_host import live
from spectra.services.room_controls import RoomControlState
from tests.test_ambient import (FakeHost, FakeHueDevice, _clear_light_cache,  # noqa: F401
                                _fast_ambient_pacing, _hue_handler, _install_bridge, _run)

LIGHTS = [{"id": f"l{i}", "owner": f"d{i}", "name": f"Bulb {i}"} for i in range(3)]


@pytest.fixture
def room(monkeypatch):
    """His room at the restart: SPECTRA owns, Away is set and holds every
    Hue area off, the stored Hue Hold toggle is ON at #ffe392, every bulb is
    OFF on the bridge, and the engine is still on paper."""
    calls: list = []
    bodies: list = []
    inner = _hue_handler(calls, lights=LIGHTS)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT" and "/resource/light/" in request.url.path:
            bodies.append((request.url.path.rsplit("/", 1)[-1],
                           json.loads(request.content)))
        return inner(request)
    _install_bridge(monkeypatch, handler)

    dev = FakeHueDevice("10.0.0.1", calls)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))
    monkeypatch.setattr(live, "scope", None)
    monkeypatch.setattr(live, "assembling", False, raising=False)
    monkeypatch.setattr(lo, "load", lambda: lo.OwnershipRecord(owner=lo.SPECTRA))
    monkeypatch.setattr(engine, "executor", SimpleNamespace(mode="recording"))
    controls = RoomControlState(ambient_enabled=True, ambient_color="#ffe392")
    monkeypatch.setattr(gate, "load_room_controls", lambda: controls)

    away = house_store.put_mode(HouseMode(name="Away", music="ignore",
                                          hue=[HueLook(area="*", look="off")]))
    house_store.state().mode_id = away.id

    def lit():
        return sorted(rid for rid, body in bodies
                      if body.get("on", {}).get("on") is True)
    return SimpleNamespace(calls=calls, bodies=bodies, dev=dev, lit=lit)


def _engine_goes_live(monkeypatch):
    monkeypatch.setattr(engine, "executor", SimpleNamespace(mode="facade"))


# ═══ 1. the restart, in order ═══════════════════════════════════════════════

def test_a_restart_under_away_never_switches_a_bulb_on(monkeypatch, room):
    """The resume's three moments, in his journal's order: the stack is
    assembling when the first bridge broadcast lands; the stack is up but
    the engine still on paper; the engine is live and app.py reconciles.
    Not one write may carry on:true, and the mode's off look lands."""
    live.assembling = True
    result = _run(gate.reconcile(None))
    assert room.bodies == [], f"a Hue write landed mid-assembly: {room.bodies}"
    assert result["status"] in ("dark", "house-pending")

    live.assembling = False
    result = _run(gate.reconcile(None))
    assert room.bodies == [], "the room toggle landed while the engine was on paper"
    assert result["status"] == "house-pending" and result["house_mode"] == "Away"

    _engine_goes_live(monkeypatch)
    assert house.hue_directive() is not None
    _run(gate.reconcile(None))
    assert room.lit() == [], f"bulbs switched on: {room.lit()}"
    assert room.bodies, "the mode's off look never landed"
    assert all(body.get("on", {}).get("on") is False for _rid, body in room.bodies)


def test_red_control_the_shipped_order_lights_every_bulb(monkeypatch, room):
    """The pre-fix world: nothing stops the toggle while the stack comes up
    — every allow-listed bulb is switched ON at the stored colour before the
    mode can say off. This is the ~20 s flash River's witness recorded."""
    monkeypatch.setattr(house, "pending_hue_directive", lambda: None, raising=False)
    live.assembling = False         # the flag did not exist
    _run(gate.reconcile(None))
    assert room.lit() == ["l0", "l1", "l2"]

    _engine_goes_live(monkeypatch)
    _run(gate.reconcile(None))
    assert room.bodies[-1][1]["on"]["on"] is False, "...and only then went off"


# ═══ 2. each guard on its own ═══════════════════════════════════════════════

def test_room_available_refuses_while_the_stack_assembles(monkeypatch):
    monkeypatch.setattr(live, "host", FakeHost({}))
    monkeypatch.setattr(lo, "load", lambda: lo.OwnershipRecord(owner=lo.SPECTRA))
    monkeypatch.setattr(live, "assembling", True)
    assert ambient.room_available() is False
    monkeypatch.setattr(live, "assembling", False, raising=False)
    assert ambient.room_available() is True


def test_the_assembling_guard_alone_holds_the_resume_window(monkeypatch, room):
    """With the house-pending guard removed, the assembling guard by itself
    still keeps the toggle off the bulbs for the whole activation."""
    monkeypatch.setattr(house, "pending_hue_directive", lambda: None, raising=False)
    live.assembling = True
    _run(gate.reconcile(None))
    assert room.bodies == []


def test_live_activate_sets_assembling_for_the_whole_start(monkeypatch):
    """The flag is raised before the host can read as active and cleared
    when activate() returns — and a failed start's deactivate() clears it."""
    from spectra.services import live_host
    seen = {}

    class Host:
        config = {}
        devices = {}
        virtuals = SimpleNamespace(blacked_out=[], held_back=[], values=lambda: [])

        def __init__(self, *_a, **_kw):
            pass

        async def start(self, **_kw):
            seen["active"] = live.active
            seen["assembling"] = live.assembling
            seen["available"] = ambient.room_available()

        async def shutdown(self, **_kw):
            pass

    monkeypatch.setattr(live_host, "FxHost", Host)
    monkeypatch.setattr(lo, "require_grant", lambda *a, **kw: None)
    monkeypatch.setattr(lo, "load", lambda: lo.OwnershipRecord(owner=lo.SPECTRA))
    monkeypatch.setattr(live.freshness, "attach", lambda host: None)
    monkeypatch.setattr(live_host, "_config_expected_active_ids", lambda cfg: set())
    monkeypatch.setattr(live_host, "_restrict_to_genuinely_driven", lambda ids: ids)
    try:
        _run(live.activate(object(), "unused", open_audio=False))
        assert seen == {"active": True, "assembling": True, "available": False}
        assert live.assembling is False
        assert ambient.room_available() is True
    finally:
        _run(live.deactivate())

    async def boom(self, **_kw):
        raise RuntimeError("host failed to start")
    monkeypatch.setattr(Host, "start", boom)
    with pytest.raises(RuntimeError):
        _run(live.activate(object(), "unused", open_audio=False))
    assert live.assembling is True
    _run(live.deactivate())          # the orchestrator's documented cleanup
    assert live.assembling is False and live.host is None


# ═══ 3. what the pending directive is, and what it is not ═══════════════════

def test_pending_only_while_spectra_owns_and_the_layer_is_refused(monkeypatch, room):
    assert house.hue_directive() is None
    pending = house.pending_hue_directive()
    assert pending is not None and pending.mode_name == "Away" and pending.holds_any

    _engine_goes_live(monkeypatch)
    assert house.pending_hue_directive() is None, "live: hue_directive answers"
    assert house.hue_directive() is not None

    monkeypatch.setattr(engine, "executor", SimpleNamespace(mode="recording"))
    monkeypatch.setattr(lo, "load", lambda: lo.OwnershipRecord(owner=lo.RELEASED))
    assert house.pending_hue_directive() is None, "a released room is not ours"


def test_no_mode_or_a_mode_without_hue_leaves_the_toggle_exactly_as_before(monkeypatch, room):
    """No mode: once the stack is up the stored toggle applies, unchanged —
    this build only holds it back FOR a mode that will drive Hue."""
    house_store.state().mode_id = None
    assert house.pending_hue_directive() is None
    _run(gate.reconcile(None))
    assert room.lit() == ["l0", "l1", "l2"]


def test_house_lighting_switched_off_never_defers(monkeypatch, room):
    from spectra.models.house_mode import HouseLibrary, HouseSettings
    house_store.save_library(HouseLibrary(settings=HouseSettings(enabled=False)))
    assert house.pending_hue_directive() is None


def test_status_names_the_pending_mode(monkeypatch, room):
    _run(gate.reconcile(None))
    st = gate.status()
    assert st["house"]["mode"] == "Away" and st["house"]["pending"] is True
    assert st["held"] is False
