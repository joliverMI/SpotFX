"""THE HUE SCOPE (fx/hue_scope.py) and the release window — the 2026-10-05
02:31 incident, reproduced and closed.

What happened: a house-lighting proof take (his house asleep). Firstmate
released the room; River's restore switched every bulb off; then
  * the RELEASE FADE's "dim to 1%" write (on: true) went to EVERY bulb in
    both entertainment areas — his Loft Ceiling Uplight and three Ledge
    lights included, all of them off; and
  * the ROOM'S HUE HOLD (stored ambient, #ffe392) landed on all seventeen
    bulbs after the restore, because ambient.room_available() read only
    "stack up, no handover" — and a release keeps the stack up for seconds
    after it moves the record to "released".

The proofs, each red against tonight's code:
  1. put() writes ONE allow-listed light and refuses everything else: a
     bulb not on the list, a grouped_light, a room, a zone, the v1 "all
     lights" group. No allow-list file = nothing allowed.
  2. The room's Hue Hold writes, verifies and repairs only allow-listed
     bulbs — the loft and ledge bulbs in the same area are never touched.
  3. The release fade never writes a bulb outside the list, never sends
     on: true to a bulb that reads off, and lets go only of what is lit.
  4. A released record (and a handover in flight) refuses the Hue Hold:
     room_available() is False, a gate reconcile starts nothing, and a
     transition already in flight stops at its next bulb.
  5. No module writes a Hue light except through fx/hue_scope.put.
"""
from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from fx import hue_scope
from fx import light_ownership as lo

REPO = Path(__file__).resolve().parent.parent
ALLOWED = {"l-stand-1": "Standing Lamp 1", "l-corner": "Living Room Corner"}
LEFT_ALONE = {"l-loft": "Loft Ceiling Uplight", "l-ledge-l": "Ledge Left"}
ALL = {**ALLOWED, **LEFT_ALONE}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def real_scope(monkeypatch, tmp_path):
    """The REAL reader over a real file holding ALLOWED (conftest's
    permissive stand-in swapped back out)."""
    path = tmp_path / "hue_scope.json"
    path.write_text(json.dumps({"lights": ALLOWED}))
    monkeypatch.setattr(hue_scope, "SCOPE_FILE", path)
    monkeypatch.setattr(hue_scope, "load_allowed", hue_scope.read_allowed_file)
    return path


class Bridge:
    """A canned CLIP v2 bridge: one entertainment area holding ALL four
    bulbs, per-bulb on/off state, every PUT recorded."""

    def __init__(self, lit: set | None = None, unreadable: set | None = None):
        self.state = {rid: {"on": {"on": rid in (lit or set())},
                            "dimming": {"brightness": 1.0},
                            "color": {"xy": {"x": 0.3127, "y": 0.329}}}
                      for rid in ALL}
        self.unreadable = unreadable or set()
        self.puts: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/clip/v2/resource/entertainment":
            return httpx.Response(200, json={"data": [
                {"id": f"e-{rid}", "owner": {"rid": f"d-{rid}"}} for rid in ALL]})
        if path == "/clip/v2/resource/light":
            return httpx.Response(200, json={"data": [
                {"id": rid, "owner": {"rid": f"d-{rid}"}, "metadata": {"name": name}}
                for rid, name in ALL.items()]})
        if path.startswith("/clip/v2/resource/entertainment_configuration/"):
            return httpx.Response(200, json={"data": [{"channels": [
                {"members": [{"service": {"rtype": "entertainment", "rid": f"e-{rid}"}}]}
                for rid in ALL]}]})
        if path.startswith("/clip/v2/resource/light/"):
            rid = path.rsplit("/", 1)[-1]
            if request.method == "PUT":
                body = json.loads(request.content)
                self.puts.append((rid, body))
                self.state[rid].update({k: v for k, v in body.items()
                                        if k in ("on", "dimming", "color")})
                return httpx.Response(200, json={"data": []})
            if rid in self.unreadable:
                return httpx.Response(503)
            return httpx.Response(200, json={"data": [dict(self.state[rid], id=rid)]})
        raise AssertionError(f"unexpected bridge call {request.method} {path}")

    def client(self, cfg):
        return httpx.AsyncClient(base_url=f"https://{cfg['ip_address']}",
                                 transport=httpx.MockTransport(self.handler))

    def written(self) -> set:
        return {rid for rid, _ in self.puts}


class Dev:
    type = "hue"

    def __init__(self):
        self.config = {"ip_address": "10.0.0.1", "entertainment_id": "ent-1",
                       "username": "u"}
        self.frozen = False
        self.ever_activated = True
        self.name = "Hue Lights"

    async def set_frozen(self, v):
        self.frozen = v

    def assemble_frame(self):
        return None


# ── 1. the single write point ──────────────────────────────────────────────

def test_put_writes_one_allow_listed_light_and_refuses_everything_else(real_scope):
    sent = []

    class Client:
        async def put(self, endpoint, json=None):
            sent.append(endpoint)
            return SimpleNamespace(status_code=200)
    _run(hue_scope.put(Client(), "/clip/v2/resource/light/l-stand-1", {"on": {"on": True}}))
    for endpoint in ("/clip/v2/resource/light/l-loft",            # Home Assistant's bulb
                     "/clip/v2/resource/grouped_light/g1",        # a group
                     "/clip/v2/resource/room/r1",
                     "/clip/v2/resource/zone/z1",
                     "/api/abc/groups/0/action",                  # v1 "all lights"
                     "/api/abc/lights/1/state",
                     "/clip/v2/resource/light/l-stand-1/../l-loft"):
        with pytest.raises(hue_scope.HueScopeRefused):
            _run(hue_scope.put(Client(), endpoint, {"on": {"on": True}}))
    assert sent == ["/clip/v2/resource/light/l-stand-1"], "nothing refused ever left"


def test_no_allow_list_file_allows_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(hue_scope, "SCOPE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(hue_scope, "load_allowed", hue_scope.read_allowed_file)
    assert hue_scope.load_allowed() == {}
    with pytest.raises(hue_scope.HueScopeRefused):
        hue_scope.check("/clip/v2/resource/light/l-stand-1")
    assert hue_scope.allowed_pairs([("l-stand-1", "Standing Lamp 1")]) == []


# ── 2. the room's Hue Hold ─────────────────────────────────────────────────

@pytest.fixture
def ambient_room(monkeypatch, real_scope):
    from spectra.services import ambient
    from spectra.services.live_host import live
    bridge = Bridge()
    dev = Dev()
    monkeypatch.setattr(ambient, "_bridge_client", bridge.client)
    monkeypatch.setattr(live, "host", SimpleNamespace(devices={"hue-lights": dev}))
    monkeypatch.setattr(live, "scope", None, raising=False)
    monkeypatch.setattr(lo, "load", lambda: lo.OwnershipRecord(owner=lo.SPECTRA))
    for name in ("AMBIENT_WRITE_STAGGER_MS", "AMBIENT_CONFIRM_SETTLE_MS",
                 "AMBIENT_RETRY_SPACING_MS", "AMBIENT_TRANSITION_MS"):
        if hasattr(ambient, name):
            monkeypatch.setattr(ambient, name, 0)
    ambient._light_cache.clear()
    yield ambient, bridge, dev
    ambient._light_cache.clear()


def test_the_room_hue_hold_never_writes_the_loft_or_ledge_bulbs(ambient_room):
    ambient, bridge, _dev = ambient_room
    result = _run(ambient.reconcile(True, "#ffe392"))
    assert result["status"] == "on"
    assert bridge.written() == set(ALLOWED), bridge.written()
    assert not bridge.state["l-loft"]["on"]["on"] and not bridge.state["l-ledge-l"]["on"]["on"]


def test_the_house_look_hold_never_writes_them_either(ambient_room):
    ambient, bridge, _dev = ambient_room
    _run(ambient.reconcile_looks((("*", "hold", 284, None, 100.0),), 0))
    assert bridge.written() == set(ALLOWED)
    bridge.puts.clear()
    _run(ambient.reconcile_looks((("*", "off", None, None, 100.0),), 0))
    assert bridge.written() == set(ALLOWED), "an off look never switches HA's bulbs off"


def test_verify_and_repair_only_see_allow_listed_bulbs(ambient_room):
    ambient, bridge, _dev = ambient_room
    _run(ambient.reconcile(True, "#ffe392"))
    bridge.state["l-loft"]["on"]["on"] = True               # HA lit its own bulb
    report = _run(ambient.verify_held("#ffe392"))
    assert report["lights_total"] == len(ALLOWED)
    bridge.puts.clear()
    _run(ambient.repair_stragglers(list(ALL.values()), "#ffe392"))
    assert "l-loft" not in bridge.written() and "l-ledge-l" not in bridge.written()


# ── 3. the release fade ────────────────────────────────────────────────────

@pytest.fixture
def fade(monkeypatch, real_scope):
    from spectra.services import release_fade
    monkeypatch.setattr(release_fade, "RELEASE_FADE_MS", 0)
    monkeypatch.setattr(release_fade, "RELEASE_OFF_SETTLE_MS", 0)
    monkeypatch.setattr(release_fade, "RELEASE_OFF_RETRY_SPACING_MS", 0)
    release_fade._light_cache.clear()
    yield release_fade
    release_fade._light_cache.clear()


def test_the_release_fade_never_lights_a_dark_bulb_or_touches_ha_bulbs(fade, monkeypatch):
    # Tonight's state at release: Spectra's bulbs OFF (a Night light hold),
    # the loft and ledge bulbs OFF too.
    bridge = Bridge(lit=set())
    monkeypatch.setattr(fade, "_bridge_client", bridge.client)
    host = SimpleNamespace(devices={"hue-lights": Dev()})
    out = _run(fade.fade_and_release_hue(host))
    assert out["failed"] == []
    assert bridge.puts == [], f"nothing was lit, so nothing is written: {bridge.puts}"


def test_the_release_fade_lets_go_of_what_is_lit_and_only_that(fade, monkeypatch):
    bridge = Bridge(lit={"l-stand-1", "l-loft"})   # a held bulb, and HA's own lit loft
    monkeypatch.setattr(fade, "_bridge_client", bridge.client)
    _run(fade.fade_and_release_hue(SimpleNamespace(devices={"hue-lights": Dev()})))
    assert bridge.written() == {"l-stand-1"}, bridge.puts
    dims = [b for rid, b in bridge.puts if b.get("on") == {"on": True}]
    assert all(rid == "l-stand-1" for rid, b in bridge.puts if b.get("on") == {"on": True})
    assert dims, "the lit bulb is faded, then switched off"
    assert bridge.state["l-stand-1"]["on"]["on"] is False
    assert bridge.state["l-loft"]["on"]["on"] is True, "Home Assistant's loft light stays as it was"


def test_an_unreadable_bulb_gets_the_off_write_never_the_dim(fade, monkeypatch):
    bridge = Bridge(lit=set(), unreadable={"l-corner"})
    monkeypatch.setattr(fade, "_bridge_client", bridge.client)
    _run(fade.fade_and_release_hue(SimpleNamespace(devices={"hue-lights": Dev()})))
    assert ("l-corner", {"on": {"on": False}}) in bridge.puts
    assert not any(b.get("on") == {"on": True} for _rid, b in bridge.puts)


# ── 4. the release window ──────────────────────────────────────────────────

def test_room_available_refuses_a_released_record_while_the_stack_is_still_up(monkeypatch):
    from spectra.services import ambient
    from spectra.services.live_host import live
    monkeypatch.setattr(live, "host", SimpleNamespace(devices={}))
    monkeypatch.setattr(lo, "load", lambda: lo.OwnershipRecord(owner=lo.RELEASED))
    assert ambient.room_available() is False, "mid-release and after it"
    monkeypatch.setattr(lo, "load", lambda: lo.OwnershipRecord(owner=lo.SPECTRA))
    assert ambient.room_available() is True


def test_tonights_sequence_lands_no_hold_after_the_release(ambient_room, monkeypatch):
    """The house layer lets go mid-release → the gate falls back to the
    room's stored Hue Hold (ambient on) → before the fix it held every bulb.
    Now the released record refuses: no transition, no bridge write."""
    from spectra.services import ambient_music_gate as gate
    from spectra.services import room_controls
    ambient, bridge, _dev = ambient_room
    monkeypatch.setattr(lo, "load", lambda: lo.OwnershipRecord(owner=lo.RELEASED))
    monkeypatch.setattr(gate, "_house_directive", lambda: None)
    controls = room_controls.RoomControlState(ambient_enabled=True, ambient_color="#ffe392")
    monkeypatch.setattr(gate, "load_room_controls", lambda: controls)
    out = _run(gate.reconcile(None, wait=True))
    assert out.get("status") == "dark"
    assert bridge.puts == []


def test_a_hold_already_in_flight_stops_at_the_next_bulb_when_released(ambient_room, monkeypatch):
    ambient, bridge, _dev = ambient_room
    owner = {"now": lo.SPECTRA}
    monkeypatch.setattr(lo, "load", lambda: lo.OwnershipRecord(owner=owner["now"]))
    real_put = hue_scope.put

    async def put_then_release(client, endpoint, body):
        resp = await real_put(client, endpoint, body)
        owner["now"] = lo.RELEASED                  # the release lands mid-transition
        return resp
    monkeypatch.setattr(hue_scope, "put", put_then_release)
    with pytest.raises(ambient.AmbientCancelled):
        _run(ambient.reconcile(True, "#ffe392"))
    assert len(bridge.puts) == 1, f"one bulb, then it stopped: {bridge.puts}"


# ── 5. one write point, by construction ────────────────────────────────────

WRITERS = ["spectra/services/ambient.py", "spectra/services/release_fade.py",
           "services/ambient_mode.py"]


@pytest.mark.parametrize("rel", WRITERS)
def test_no_hue_writer_puts_except_through_the_scope(rel):
    tree = ast.parse((REPO / rel).read_text())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "put"):
            owner = node.func.value
            assert isinstance(owner, ast.Name) and owner.id == "hue_scope", (
                f"{rel}:{node.lineno} writes to a bridge without fx/hue_scope.put")


def test_nothing_in_the_tree_writes_a_hue_group_or_all_lights():
    for path in list((REPO / "spectra").rglob("*.py")) + list((REPO / "services").rglob("*.py")) \
            + list((REPO / "fx").rglob("*.py")):
        if path.name == "hue_scope.py":
            continue
        text = path.read_text()
        for needle in ("grouped_light", "/groups/0"):
            assert needle not in text, f"{path.relative_to(REPO)} names {needle!r}"


# ── the seed ───────────────────────────────────────────────────────────────

def test_the_seed_leaves_the_named_bulbs_to_home_assistant(monkeypatch, tmp_path):
    import scripts.seed_hue_scope as seed
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"devices": [{"id": "hue-lights", "type": "hue",
                                            "config": Dev().config}]}))
    monkeypatch.setattr(seed, "area_members", lambda c: list(ALL.items()))
    out = seed.build(cfg, ["Loft Ceiling Uplight", "ledge left"])
    assert out["lights"] == ALLOWED and out["excluded"] == LEFT_ALONE
    with pytest.raises(SystemExit):
        seed.build(cfg, ["Ledge Lefty"])                  # a typo must not allow a bulb
