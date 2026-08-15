"""SPECTRA Ambient's music-precedence gate (services/ambient_music_gate.py)
— offline proof of the fix for the 2026-08-15 live defect: with Ambient
enabled and a real track playing, all 19 Hue bulbs sat frozen at ambient
cream, following none of the music, the active scene, or firing triggers.
Ambient did not merely compete with music — it silently swallowed the
whole song. His ruling: Ambient is the room's RESTING state — music wins
while it plays, and Ambient resumes on its own the instant it stops.

The proofs:
  1. _desired_hold is the pure precedence rule: enabled AND a CONFIRMED
     not-playing read holds; disabled, actively playing, or an unknown
     (None) read never does — fail-safe toward not holding (module
     docstring).
  2. reconcile() drives the live hold through services.ambient — the SAME
     function a human toggling the room-bar checkbox always called — so
     Ambient's release/ease-back fidelity (the thing the Admiral called
     "way better") is exercised by the real tested code path, not
     reimplemented here.
  3. Music wins mid-hold: a quiet-room hold releases the instant playback
     is confirmed, and Ambient re-engages the instant it's confirmed quiet
     again — the restore-on-its-own half of his ruling.
  4. No redundant Hue writes on a repeated identical read; a colour change
     while holding still re-applies live; a failed reconcile is never
     recorded as held, so the next call retries rather than assuming
     success.
  5. status() reports the four honest modes (off/holding/yielding/
     transitioning) GET /api/engine/status folds in for the room bar.

The Hue double (FakeHost/FakeHueDevice + httpx.MockTransport) mirrors
tests/test_ambient.py's own fixtures, trimmed to one light on one device —
this file proves the GATE's precedence/bookkeeping logic, not Ambient's
own REST mechanics (already proven there).
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")


@pytest.fixture(autouse=True)
def _clear_light_cache():
    from spectra.services import ambient
    ambient._light_cache.clear()
    yield
    ambient._light_cache.clear()


@pytest.fixture(autouse=True)
def _fast_ambient_pacing(monkeypatch):
    from spectra.services import ambient
    monkeypatch.setattr(ambient, "AMBIENT_TRANSITION_MS", 0)
    monkeypatch.setattr(ambient, "AMBIENT_CONFIRM_SETTLE_MS", 0)
    monkeypatch.setattr(ambient, "AMBIENT_WRITE_STAGGER_MS", 0)
    monkeypatch.setattr(ambient, "AMBIENT_RETRY_SPACING_MS", 0)


def _save_controls(**kwargs):
    from spectra.services import room_controls as rc
    state = rc.RoomControlState(**kwargs)
    rc.save_room_controls(state)
    return state


# ── _desired_hold: the pure precedence rule ─────────────────────────────────

def test_desired_hold_confirmed_reads_always_win():
    from spectra.services.ambient_music_gate import _desired_hold
    assert _desired_hold(True, False, currently_held=False) is True
    assert _desired_hold(True, False, currently_held=True) is True
    assert _desired_hold(True, True, currently_held=False) is False
    assert _desired_hold(True, True, currently_held=True) is False, \
        "a confirmed-playing read releases an already-held room"


def test_desired_hold_unknown_never_actively_changes_anything():
    """A bridge blip (is_playing=None) must not release an already-held
    quiet room, and must not spuriously start holding one that was never
    confirmed quiet — it simply carries the current state forward."""
    from spectra.services.ambient_music_gate import _desired_hold
    assert _desired_hold(True, None, currently_held=True) is True
    assert _desired_hold(True, None, currently_held=False) is False


def test_desired_hold_disabled_always_wins():
    from spectra.services.ambient_music_gate import _desired_hold
    assert _desired_hold(False, False, currently_held=True) is False
    assert _desired_hold(False, None, currently_held=True) is False


# ── reconcile(): drives services.ambient, the same path a human PUT uses ───

def _hue_handler(calls):
    """One light on one device — always accepts a write and reflects it
    back (trimmed from tests/test_ambient.py's own canned bridge)."""
    state = {
        "on": {"on": False},
        "dimming": {"brightness": 1.0},
        "color": {"xy": {"x": 0.3127, "y": 0.3290}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(("REST", request.method, path))
        if path == "/clip/v2/resource/entertainment":
            return httpx.Response(200, json={"data": [{"id": "e0", "owner": {"rid": "d1"}}]})
        if path == "/clip/v2/resource/light":
            return httpx.Response(200, json={"data": [{"id": "l1", "owner": {"rid": "d1"}}]})
        if path.startswith("/clip/v2/resource/entertainment_configuration/"):
            return httpx.Response(200, json={"data": [{"channels": [
                {"members": [{"service": {"rtype": "entertainment", "rid": "e0"}}]}]}]})
        if path == "/clip/v2/resource/light/l1":
            if request.method == "PUT":
                body = json.loads(request.content)
                state.update({k: v for k, v in body.items() if k in ("on", "dimming", "color")})
                return httpx.Response(200, json={"data": []})
            if request.method == "GET":
                return httpx.Response(200, json={"data": [dict(state, id="l1")]})
        raise AssertionError(f"unexpected request {request.method} {path}")
    return handler


class FakeHueDevice:
    type = "hue"

    def __init__(self, calls, live_frame=None):
        self.config = {"ip_address": "10.0.0.1", "entertainment_id": "ent-1", "username": "u"}
        self.calls = calls
        self.frozen = None
        self._live_frame = live_frame

    async def set_frozen(self, frozen):
        self.calls.append(("set_frozen", frozen))
        self.frozen = frozen

    def assemble_frame(self):
        return self._live_frame


class FakeHost:
    def __init__(self, devices):
        self.devices = devices


@pytest.fixture
def hue_room(monkeypatch):
    """One live Hue device wired to services.live_host.live, plus a mocked
    bridge — the shared fixture for every reconcile() proof below."""
    from spectra.services import ambient
    from spectra.services.live_host import live
    calls: list = []
    dev = FakeHueDevice(calls)
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))

    def fake_bridge_client(cfg):
        return httpx.AsyncClient(base_url=f"https://{cfg['ip_address']}",
                                 transport=httpx.MockTransport(_hue_handler(calls)))
    monkeypatch.setattr(ambient, "_bridge_client", fake_bridge_client)
    return dev, calls


def test_reconcile_holds_when_enabled_and_confirmed_not_playing(hue_room):
    from spectra.services.ambient_music_gate import reconcile, status
    dev, calls = hue_room
    _save_controls(ambient_enabled=True, ambient_color="#f5da8c")

    result = _run(reconcile(False))

    assert result["status"] == "on"
    assert dev.frozen is True
    assert status()["mode"] == "holding"
    assert status()["held"] is True


def test_reconcile_does_not_hold_while_music_is_playing(hue_room):
    """The exact live defect: Ambient must NOT freeze the room's Hue
    devices while a track is genuinely playing."""
    from spectra.services.ambient_music_gate import reconcile, status
    dev, calls = hue_room
    _save_controls(ambient_enabled=True, ambient_color="#f5da8c")

    result = _run(reconcile(True))

    assert result["status"] == "yielding"
    assert dev.frozen is None, "set_frozen must never be called — the device is left untouched"
    assert calls == [], "no Hue REST traffic at all while yielding"
    assert status()["mode"] == "yielding"
    assert status()["held"] is False


def test_reconcile_does_not_hold_on_first_unknown_playback(hue_room):
    """Bridge never connected yet (fresh room, nothing confirmed quiet) —
    an unknown read must not start a blind hold (the one asymmetric edge,
    module docstring)."""
    from spectra.services.ambient_music_gate import reconcile
    dev, calls = hue_room
    _save_controls(ambient_enabled=True, ambient_color="#f5da8c")

    result = _run(reconcile(None))

    assert result["status"] == "yielding"
    assert dev.frozen is None


def test_reconcile_unknown_playback_does_not_release_an_existing_hold(hue_room):
    """The flicker regression this design specifically avoids: once a
    quiet room is genuinely held, a bridge blip (is_playing=None) must
    NOT release it — only a CONFIRMED playing read may do that."""
    from spectra.services.ambient_music_gate import reconcile
    dev, calls = hue_room
    _save_controls(ambient_enabled=True, ambient_color="#f5da8c")

    _run(reconcile(False))
    assert dev.frozen is True
    calls_after_hold = len(calls)

    result = _run(reconcile(None))

    assert result["status"] == "on", "still held — unknown carries the existing state forward"
    assert dev.frozen is True
    assert len(calls) == calls_after_hold, "no release fired on a mere unknown read"


def test_reconcile_releases_when_music_starts_after_holding(hue_room):
    """Music wins mid-hold too: a quiet-room hold must release the instant
    playback is confirmed — through the SAME release/ease-back path (the
    thing that must survive 'unharmed')."""
    from spectra.services.ambient_music_gate import reconcile
    dev, calls = hue_room
    _save_controls(ambient_enabled=True, ambient_color="#f5da8c")

    held = _run(reconcile(False))
    assert held["status"] == "on"
    assert dev.frozen is True

    released = _run(reconcile(True))
    assert released["status"] == "off"
    assert dev.frozen is False, "set_frozen(False) — the room releases back to the live stream"
    assert ("set_frozen", False) in calls


def test_reconcile_resumes_ambient_when_music_stops(hue_room):
    """The restore half of his ruling: once music ends, Ambient comes back
    on its own — no manual re-toggle needed."""
    from spectra.services.ambient_music_gate import reconcile
    dev, calls = hue_room
    _save_controls(ambient_enabled=True, ambient_color="#f5da8c")

    _run(reconcile(True))     # playing — yields
    assert dev.frozen is None

    result = _run(reconcile(False))   # song ends
    assert result["status"] == "on"
    assert dev.frozen is True


def test_reconcile_disabled_never_holds_regardless_of_playback(hue_room):
    from spectra.services.ambient_music_gate import reconcile, status
    dev, calls = hue_room
    _save_controls(ambient_enabled=False, ambient_color="#f5da8c")

    result = _run(reconcile(False))

    assert result["status"] == "off"
    assert dev.frozen is None
    assert status()["mode"] == "off"


def test_reconcile_is_a_no_op_when_desired_state_unchanged(hue_room):
    """A burst of bridge broadcasts carrying the same playback read must
    not re-fire redundant Hue writes."""
    from spectra.services.ambient_music_gate import reconcile
    dev, calls = hue_room
    _save_controls(ambient_enabled=True, ambient_color="#f5da8c")

    _run(reconcile(False))
    calls_after_first = len(calls)
    _run(reconcile(False))
    _run(reconcile(False))

    assert len(calls) == calls_after_first, "no additional REST calls on a repeated identical read"


def test_reconcile_reapplies_when_colour_changes_while_holding(hue_room):
    from spectra.services.ambient_music_gate import reconcile
    dev, calls = hue_room
    _save_controls(ambient_enabled=True, ambient_color="#f5da8c")
    _run(reconcile(False))
    calls_after_first = len(calls)

    _save_controls(ambient_enabled=True, ambient_color="#ff0000")
    result = _run(reconcile(False))

    assert result["status"] == "on"
    assert len(calls) > calls_after_first, "a colour change while holding must re-apply live"


def test_failed_reconcile_does_not_mark_held_and_retries_next_call(monkeypatch, hue_room):
    from spectra.services import ambient
    from spectra.services.ambient_music_gate import reconcile, status
    dev, calls = hue_room
    _save_controls(ambient_enabled=True, ambient_color="#f5da8c")

    async def fail(*args, **kwargs):
        return {"status": "failed", "devices": [], "lights_set": 0}
    monkeypatch.setattr(ambient, "reconcile", fail)

    first = _run(reconcile(False))
    assert first["status"] == "failed"
    assert status()["held"] is False, "a failed reconcile must not be recorded as held"

    async def ok(enabled, color):
        return {"status": "on", "devices": ["hue-lights"], "lights_set": 1, "lights_total": 1}
    monkeypatch.setattr(ambient, "reconcile", ok)

    second = _run(reconcile(False))
    assert second["status"] == "on"
    assert status()["held"] is True, "the next call must retry, not assume the earlier one succeeded"


# ── status(): the visible modes the room bar reads ──────────────────────────

def test_status_off_when_ambient_disabled():
    from spectra.services.ambient_music_gate import status
    _save_controls(ambient_enabled=False)
    assert status()["mode"] == "off"


def test_status_yielding_when_enabled_but_not_held():
    from spectra.services.ambient_music_gate import status
    _save_controls(ambient_enabled=True, ambient_color="#ffffff")
    assert status()["mode"] == "yielding"


def test_status_holding_after_a_successful_hold(hue_room):
    from spectra.services.ambient_music_gate import reconcile, status
    _save_controls(ambient_enabled=True, ambient_color="#f5da8c")
    _run(reconcile(False))
    assert status()["mode"] == "holding"
