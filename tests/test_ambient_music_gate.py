"""SPECTRA Ambient's mode precedence gate (services/ambient_music_gate.py)
— offline proof of the three-setting surface, in the Admiral's own words:

  "off"    never holds — the whole room performs.
  "always" Hue held lit at ambient_color UNCONDITIONALLY (his own request,
           2026-08-15: "Ambient mode should run even while the music is
           playing so that my Hue Lights are lit and bright but the other
           lights are still running the show") — mode 2, not the
           precedence bug.
  "auto"   the original music-precedence fix: holds only when playback is
           CONFIRMED not-playing, releases instantly when confirmed
           playing, carries an unresolved read forward. Proven live
           2026-08-15: with a real track playing, all 19 Hue bulbs had sat
           frozen at ambient cream under the pre-fix always-hold
           behaviour, following none of the music — "auto" is what fixes
           that specific case while "always" stays available as a
           deliberate choice.

The proofs:
  1. _desired_hold is the pure precedence rule, one branch per setting:
     "off" always releases; "always" always holds, playback irrelevant;
     "auto" holds only on a CONFIRMED not-playing read, an unknown (None)
     read never actively changes anything (fail-safe, module docstring).
  2. reconcile() drives the live hold through services.ambient — the SAME
     function a human toggling the room-bar control always called — so
     Ambient's release/ease-back fidelity (the thing the Admiral called
     "way better") is exercised by the real tested code path, not
     reimplemented here.
  3. "auto": music wins mid-hold — a quiet-room hold releases the instant
     playback is confirmed, and re-engages the instant it's confirmed
     quiet again. "always": a playback transition, either direction, never
     releases a hold — only switching the setting itself can.
  4. No redundant Hue writes on a repeated identical read; a colour change
     while holding still re-applies live; a failed reconcile is never
     recorded as held, so the next call retries rather than assuming
     success.
  5. status() reports the four honest live modes (off/holding/yielding/
     transitioning) alongside the chosen `setting`, both folded into
     GET /api/engine/status for the room bar.

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


# ── _desired_hold: the pure precedence rule, one branch per setting ────────

def test_desired_hold_auto_confirmed_reads_always_win():
    from spectra.services.ambient_music_gate import _desired_hold
    assert _desired_hold("auto", False, currently_held=False) is True
    assert _desired_hold("auto", False, currently_held=True) is True
    assert _desired_hold("auto", True, currently_held=False) is False
    assert _desired_hold("auto", True, currently_held=True) is False, \
        "a confirmed-playing read releases an already-held room"


def test_desired_hold_auto_unknown_never_actively_changes_anything():
    """A bridge blip (is_playing=None) must not release an already-held
    quiet room, and must not spuriously start holding one that was never
    confirmed quiet — it simply carries the current state forward."""
    from spectra.services.ambient_music_gate import _desired_hold
    assert _desired_hold("auto", None, currently_held=True) is True
    assert _desired_hold("auto", None, currently_held=False) is False


def test_desired_hold_off_always_wins():
    from spectra.services.ambient_music_gate import _desired_hold
    assert _desired_hold("off", False, currently_held=True) is False
    assert _desired_hold("off", None, currently_held=True) is False
    assert _desired_hold("off", True, currently_held=True) is False


def test_desired_hold_always_holds_unconditionally():
    """Mode 2, his own request: Hue held lit regardless of playback — not
    the precedence bug, a deliberate third setting."""
    from spectra.services.ambient_music_gate import _desired_hold
    assert _desired_hold("always", True, currently_held=False) is True, \
        "must hold even while music is confirmed playing"
    assert _desired_hold("always", False, currently_held=False) is True
    assert _desired_hold("always", None, currently_held=False) is True


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
    _save_controls(ambient_mode="auto", ambient_color="#f5da8c")

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
    _save_controls(ambient_mode="auto", ambient_color="#f5da8c")

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
    _save_controls(ambient_mode="auto", ambient_color="#f5da8c")

    result = _run(reconcile(None))

    assert result["status"] == "yielding"
    assert dev.frozen is None


def test_reconcile_unknown_playback_does_not_release_an_existing_hold(hue_room):
    """The flicker regression this design specifically avoids: once a
    quiet room is genuinely held, a bridge blip (is_playing=None) must
    NOT release it — only a CONFIRMED playing read may do that."""
    from spectra.services.ambient_music_gate import reconcile
    dev, calls = hue_room
    _save_controls(ambient_mode="auto", ambient_color="#f5da8c")

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
    _save_controls(ambient_mode="auto", ambient_color="#f5da8c")

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
    _save_controls(ambient_mode="auto", ambient_color="#f5da8c")

    _run(reconcile(True))     # playing — yields
    assert dev.frozen is None

    result = _run(reconcile(False))   # song ends
    assert result["status"] == "on"
    assert dev.frozen is True


def test_reconcile_disabled_never_holds_regardless_of_playback(hue_room):
    from spectra.services.ambient_music_gate import reconcile, status
    dev, calls = hue_room
    _save_controls(ambient_mode="off", ambient_color="#f5da8c")

    result = _run(reconcile(False))

    assert result["status"] == "off"
    assert dev.frozen is None
    assert status()["mode"] == "off"


def test_reconcile_is_a_no_op_when_desired_state_unchanged(hue_room):
    """A burst of bridge broadcasts carrying the same playback read must
    not re-fire redundant Hue writes."""
    from spectra.services.ambient_music_gate import reconcile
    dev, calls = hue_room
    _save_controls(ambient_mode="auto", ambient_color="#f5da8c")

    _run(reconcile(False))
    calls_after_first = len(calls)
    _run(reconcile(False))
    _run(reconcile(False))

    assert len(calls) == calls_after_first, "no additional REST calls on a repeated identical read"


def test_reconcile_reapplies_when_colour_changes_while_holding(hue_room):
    from spectra.services.ambient_music_gate import reconcile
    dev, calls = hue_room
    _save_controls(ambient_mode="auto", ambient_color="#f5da8c")
    _run(reconcile(False))
    calls_after_first = len(calls)

    _save_controls(ambient_mode="auto", ambient_color="#ff0000")
    result = _run(reconcile(False))

    assert result["status"] == "on"
    assert len(calls) > calls_after_first, "a colour change while holding must re-apply live"


def test_failed_reconcile_does_not_mark_held_and_retries_next_call(monkeypatch, hue_room):
    from spectra.services import ambient
    from spectra.services.ambient_music_gate import reconcile, status
    dev, calls = hue_room
    _save_controls(ambient_mode="auto", ambient_color="#f5da8c")

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


# ── "always": mode 2, his own requested setting ─────────────────────────────

def test_always_holds_even_while_music_is_confirmed_playing(hue_room):
    """The whole point of mode 2 — his own words: 'Ambient mode should run
    even while the music is playing so that my Hue Lights are lit and
    bright'. This must NOT be gated by is_playing at all."""
    from spectra.services.ambient_music_gate import reconcile, status
    dev, calls = hue_room
    _save_controls(ambient_mode="always", ambient_color="#f5da8c")

    result = _run(reconcile(True))   # music genuinely playing

    assert result["status"] == "on"
    assert dev.frozen is True
    assert status()["mode"] == "holding"
    assert status()["held"] is True


def test_always_holds_on_unknown_playback_too():
    """Unlike "auto", "always" never consults is_playing — an unresolved
    read must not delay the hold."""
    from spectra.services.ambient_music_gate import _desired_hold
    assert _desired_hold("always", None, currently_held=False) is True


def test_always_never_releases_when_playback_changes(hue_room):
    """Once held under "always", a playback transition (either direction)
    must not release it — only switching the setting itself can."""
    from spectra.services.ambient_music_gate import reconcile
    dev, calls = hue_room
    _save_controls(ambient_mode="always", ambient_color="#f5da8c")

    _run(reconcile(False))
    assert dev.frozen is True
    calls_after_hold = len(calls)

    result = _run(reconcile(True))   # music starts

    assert result["status"] == "on"
    assert dev.frozen is True
    assert len(calls) == calls_after_hold, "no release fired — 'always' ignores playback entirely"


def test_switching_from_always_to_off_releases_regardless_of_playback(hue_room):
    from spectra.services.ambient_music_gate import reconcile
    dev, calls = hue_room
    _save_controls(ambient_mode="always", ambient_color="#f5da8c")
    _run(reconcile(True))
    assert dev.frozen is True

    _save_controls(ambient_mode="off", ambient_color="#f5da8c")
    result = _run(reconcile(True))   # still playing — "off" must still release

    assert result["status"] == "off"
    assert dev.frozen is False


# ── status(): the visible modes the room bar reads ──────────────────────────

def test_status_off_when_ambient_disabled():
    from spectra.services.ambient_music_gate import status
    _save_controls(ambient_mode="off")
    assert status() == {"setting": "off", "mode": "off", "held": False}


def test_status_yielding_when_enabled_but_not_held():
    from spectra.services.ambient_music_gate import status
    _save_controls(ambient_mode="auto", ambient_color="#ffffff")
    st = status()
    assert st["setting"] == "auto"
    assert st["mode"] == "yielding"


def test_status_setting_reflects_always_while_holding(hue_room):
    from spectra.services.ambient_music_gate import reconcile, status
    _save_controls(ambient_mode="always", ambient_color="#f5da8c")
    _run(reconcile(True))
    st = status()
    assert st["setting"] == "always"
    assert st["mode"] == "holding"


def test_status_holding_after_a_successful_hold(hue_room):
    from spectra.services.ambient_music_gate import reconcile, status
    _save_controls(ambient_mode="auto", ambient_color="#f5da8c")
    _run(reconcile(False))
    assert status()["mode"] == "holding"


# ── status honesty: verify_now()'s periodic recheck (2026-08-15 overnight
#    defect — a claimed hold that goes stale must eventually report itself
#    honestly, not just replay the last write's outcome forever) ───────────

def test_status_carries_verify_age_and_detail_right_after_a_hold(hue_room, monkeypatch):
    """A write's own read-back IS a fresh confirmation — status() must
    reflect it immediately, not wait for the next periodic tick."""
    from spectra.services import ambient_music_gate as gate
    _save_controls(ambient_mode="always", ambient_color="#f5da8c")
    clock = {"t": 100.0}
    monkeypatch.setattr(gate.time, "monotonic", lambda: clock["t"])

    result = _run(gate.reconcile(True))
    assert result["status"] == "on"

    st = gate.status()
    assert st["verified_age_s"] == 0.0
    assert st["verify"] == {"status": "verified", "lights_lit": 1,
                            "lights_total": 1, "unlit": []}

    clock["t"] += 42.0
    assert gate.status()["verified_age_s"] == 42.0, \
        "age must grow with real elapsed time, not reset on every status() call"


def test_repeated_identical_reconcile_does_not_refresh_verify_age(hue_room, monkeypatch):
    """_apply()'s own short-circuit (no redundant Hue writes on a repeated
    identical read) must not masquerade as a fresh confirmation either —
    the age should reflect the last REAL check, not the last call."""
    from spectra.services import ambient_music_gate as gate
    _save_controls(ambient_mode="always", ambient_color="#f5da8c")
    clock = {"t": 100.0}
    monkeypatch.setattr(gate.time, "monotonic", lambda: clock["t"])
    _run(gate.reconcile(True))

    clock["t"] += 10.0
    _run(gate.reconcile(True))   # identical desired -> short-circuits

    assert gate.status()["verified_age_s"] == 10.0


def test_verify_now_is_a_noop_when_nothing_is_currently_held():
    from spectra.services.ambient_music_gate import verify_now, status
    _save_controls(ambient_mode="off")

    result = _run(verify_now())

    assert result == {}
    assert status() == {"setting": "off", "mode": "off", "held": False}


def test_verify_now_skips_while_a_write_is_in_flight(hue_room):
    """The verifier must never race a real write — the write's own
    read-back is already fresher than anything a concurrent GET adds."""
    from spectra.services.ambient_music_gate import reconcile, verify_now, _get_apply_lock
    dev, calls = hue_room
    _save_controls(ambient_mode="always", ambient_color="#f5da8c")
    _run(reconcile(True))

    async def scenario():
        lock = _get_apply_lock()
        await lock.acquire()
        try:
            return await verify_now()
        finally:
            lock.release()

    assert _run(scenario()) == {}


def test_verify_now_downgrades_held_when_a_light_is_found_off(hue_room):
    """THE proof of the live defect: a bulb turned off out-of-band while
    Ambient believed it held must flip status()'s `held`/`mode` the next
    time the periodic verifier runs — via a read-only recheck, never a
    write of its own."""
    from spectra.services import ambient
    from spectra.services.ambient_music_gate import reconcile, verify_now, status
    dev, calls = hue_room
    _save_controls(ambient_mode="always", ambient_color="#f5da8c")

    held = _run(reconcile(True))
    assert held["status"] == "on"
    assert status()["held"] is True
    assert status()["mode"] == "holding"

    async def _turn_off_out_of_band():
        async with ambient._bridge_client(dev.config) as client:
            await ambient._hue_put(client, "/clip/v2/resource/light/l1",
                                   {"on": {"on": False}})
    _run(_turn_off_out_of_band())
    calls_before_verify = len(calls)

    result = _run(verify_now())

    assert result["status"] == "verified"
    assert result["unlit"] == ["l1"]
    st = status()
    assert st["held"] is False, "held must never stay true for a light that's off"
    assert st["mode"] == "partial"
    assert st["verify"]["unlit"] == ["l1"]
    assert all(c[1] != "PUT" for c in calls[calls_before_verify:]), \
        "the verifier itself must never write — only the out-of-band turn-off did"


def test_verify_now_downgrades_held_when_live_stack_no_longer_active(hue_room, monkeypatch):
    """SPECTRA can stop owning the live stack (handover, release) without
    Ambient's own bookkeeping ever hearing about it directly — the
    verifier must still stop claiming a hold that has nothing behind it."""
    from spectra.services.ambient_music_gate import reconcile, verify_now, status
    from spectra.services.live_host import live
    dev, calls = hue_room
    _save_controls(ambient_mode="always", ambient_color="#f5da8c")
    _run(reconcile(True))
    assert status()["held"] is True

    monkeypatch.setattr(live, "host", None)

    result = _run(verify_now())

    assert result == {"status": "dark"}
    st = status()
    assert st["held"] is False
    assert st["mode"] == "partial"


def test_write_time_dark_result_does_not_report_held(monkeypatch):
    """The same honesty gap, caught at write time rather than waiting for
    the periodic verifier: a reconcile that lands "dark" (SPECTRA doesn't
    own the live stack) must not report `held: true` just because the
    write's own intent bookkeeping records desired=True."""
    from spectra.services.ambient_music_gate import reconcile, status
    from spectra.services.live_host import live
    monkeypatch.setattr(live, "host", None)
    _save_controls(ambient_mode="always", ambient_color="#f5da8c")

    result = _run(reconcile(True))

    assert result == {"status": "dark"}
    st = status()
    assert st["held"] is False
    assert st["mode"] == "partial"
