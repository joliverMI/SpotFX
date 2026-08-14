"""THE OWNER'S PANIC HANDLE — offline proof. Same discipline as
test_handover.py: no live handover, no real device, no audio hardware
(silence_audio + fakes only).

The proofs:
  1. the state machine: release() sheds both worlds' write grants in one
     atomic step, is idempotent, and refuses only mid-handover.
  2. release_room() stops each device class on fakes:
       - spot-effects owns  → active LedFX virtuals deactivated via the API
                              (fake ledfx_client), inactive ones untouched,
                              one virtual's failure doesn't stop the rest.
       - spectra owns       → the real SpectraSide on the headless harness:
                              the live stack actually tears down (dummy
                              device deactivates, audio hub closes).
       - already released   → idempotent, no device-class cleanup re-run.
       - mid-handover        → refused, nothing touched.
  3. the WLED and Hue vendored drivers each get an EXPLICIT release call on
     deactivate() (not just "stop sending and let the device time out"):
     WLED via the JSON API's {"live": false}, Hue via the existing
     action:"stop" entertainment-session call.
  4. the way back is the SAME guarded handover: run_handover(SPECTRA, ...)
     from a released record skips the (vacuous) quiesce step, and an
     activation failure lands back at released with no from-side to
     "restore".
  5. both write seams refuse while released: fx_seam.apply_writes and the
     spot-effects ownership gate.
  6. the watchdogs treat a released room as healthy-dark, not dead (and
     correctly flag a live stack that ignored the release as the same
     split-brain tripwire).
  7. the liveness endpoint reports the released state honestly.
  8. the API route: not armed-gated, idempotent, 409 only mid-handover.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless, light_ownership as lo


def _run(coro):
    return asyncio.run(coro)


def _own_file(tmp_path) -> None:
    lo.OWNERSHIP_FILE = tmp_path / "ownership.json"


_ORIGINAL_OWNERSHIP_FILE = lo.OWNERSHIP_FILE


@pytest.fixture(autouse=True)
def _restore_ownership_file():
    """lo.OWNERSHIP_FILE is a module global; _own_file() repoints it per test
    but nothing else here restores it. Without this, whichever tmp_path this
    module last pointed it at (e.g. a HANDING_OVER record from a 409 test)
    leaks into every test file that runs afterward and doesn't call
    _own_file() itself — including ones outside this module entirely."""
    yield
    lo.OWNERSHIP_FILE = _ORIGINAL_OWNERSHIP_FILE


# ── 1. the state machine ──────────────────────────────────────────────────


def test_release_sheds_both_write_grants_atomically(tmp_path):
    _own_file(tmp_path)
    record = lo.release("spec: panic press")
    assert record.owner == lo.RELEASED
    assert not lo.writes_allowed(lo.SPOT_EFFECTS)
    assert not lo.writes_allowed(lo.SPECTRA)
    with pytest.raises(lo.OwnershipError):
        lo.mint_activation_grant(lo.SPECTRA)


def test_release_is_idempotent(tmp_path):
    _own_file(tmp_path)
    lo.release("first press")
    record = lo.release("second press")  # must not raise
    assert record.owner == lo.RELEASED
    assert any(e["event"] == "release_repeat" for e in record.history)


def test_release_refuses_mid_handover(tmp_path):
    _own_file(tmp_path)
    lo.begin_handover(lo.SPECTRA)
    with pytest.raises(lo.OwnershipError):
        lo.release("spec: cannot release mid-swap")
    assert lo.load().owner == lo.HANDING_OVER


def test_release_from_spectra_also_lands_released(tmp_path):
    _own_file(tmp_path)
    h = lo.begin_handover(lo.SPECTRA)
    lo.mark_quiesced(h.token)
    lo.commit(h.token)
    assert lo.load().owner == lo.SPECTRA
    record = lo.release("spec: panic while spectra owns")
    assert record.owner == lo.RELEASED


# ── 2a. release_room(): spot-effects → deactivate active LedFX virtuals ──────


def test_release_room_deactivates_only_active_ledfx_virtuals(tmp_path, monkeypatch):
    from spectra.services import release as release_svc

    _own_file(tmp_path)
    virtuals = {
        "v1": {"active": True},
        "v2": {"active": False},
        "v3": {"active": True},
    }
    set_calls = []

    async def fake_get_all_virtuals(force=False):
        assert force is True
        return {"virtuals": virtuals}

    async def fake_set_virtual_active(vid, active):
        set_calls.append((vid, active))
        return True

    from api import ledfx_client
    monkeypatch.setattr(ledfx_client, "get_all_virtuals", fake_get_all_virtuals)
    monkeypatch.setattr(ledfx_client, "set_virtual_active", fake_set_virtual_active)

    record = _run(release_svc.release_room("spec: spot-effects release"))
    assert record.owner == lo.RELEASED
    assert sorted(set_calls) == [("v1", False), ("v3", False)]


def test_release_room_ledfx_one_virtual_failure_does_not_stop_the_rest(tmp_path, monkeypatch):
    from spectra.services import release as release_svc

    _own_file(tmp_path)
    virtuals = {"v1": {"active": True}, "v2": {"active": True}}
    set_calls = []

    async def fake_get_all_virtuals(force=False):
        return {"virtuals": virtuals}

    async def flaky_set_virtual_active(vid, active):
        set_calls.append(vid)
        if vid == "v1":
            raise RuntimeError("simulated LedFX timeout")
        return True

    from api import ledfx_client
    monkeypatch.setattr(ledfx_client, "get_all_virtuals", fake_get_all_virtuals)
    monkeypatch.setattr(ledfx_client, "set_virtual_active", flaky_set_virtual_active)

    record = _run(release_svc.release_room("spec: one virtual fails"))
    # Released stands regardless — cleanup failure never re-opens the gate.
    assert record.owner == lo.RELEASED
    assert sorted(set_calls) == ["v1", "v2"]


# ── 2b. release_room(): spectra → the real live stack tears down ────────────


def test_release_room_deactivates_the_real_spectra_live_stack(tmp_path):
    from spectra.services import engine
    from spectra.services.handover import SpectraSide
    from spectra.services.live_host import live
    from spectra.services import release as release_svc

    _own_file(tmp_path)
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(str(config_dir))

    async def main():
        try:
            h = lo.begin_handover(lo.SPECTRA)
            lo.mark_quiesced(h.token)
            grant = lo.mint_activation_grant(lo.SPECTRA)
            side = SpectraSide(config_dir=str(config_dir), open_audio=False)
            await side.activate()
            lo.commit(h.token)
            assert live.active

            record = await release_svc.release_room("spec: spectra release")
            assert record.owner == lo.RELEASED
            # The device layer actually tore down — dummy device deactivated,
            # host gone, engine dark — not just the ownership record moving.
            assert not live.active
            assert engine.executor.mode == "recording"
        finally:
            engine.go_dark()
            from fx import facade
            facade.set_host(None)
            if live.active:
                await live.deactivate()

    _run(main())


def test_release_room_already_released_skips_device_cleanup(tmp_path, monkeypatch):
    from spectra.services import release as release_svc

    _own_file(tmp_path)
    lo.release("first press")

    called = []

    async def must_not_be_called(*a, **kw):
        called.append(True)
        raise AssertionError("device-class cleanup must not re-run when "
                             "already released")

    monkeypatch.setattr(release_svc, "_release_ledfx_virtuals", must_not_be_called)
    monkeypatch.setattr(release_svc, "_release_spectra_devices", must_not_be_called)

    record = _run(release_svc.release_room("second press"))
    assert record.owner == lo.RELEASED
    assert called == []


def test_release_room_refuses_mid_handover(tmp_path, monkeypatch):
    from spectra.services import release as release_svc

    _own_file(tmp_path)
    lo.begin_handover(lo.SPECTRA)

    called = []
    monkeypatch.setattr(release_svc, "_release_spectra_devices",
                        lambda: called.append(True))

    with pytest.raises(lo.OwnershipError):
        _run(release_svc.release_room("spec: refuse mid-handover"))
    assert lo.load().owner == lo.HANDING_OVER
    assert called == []


# ── 3. per-device-class explicit release ─────────────────────────────────────


def test_wled_release_realtime_posts_live_false(monkeypatch):
    """The protocol-level proof: WLED.release_realtime() sends the
    documented JSON API call, not a raw UDP timeout packet."""
    from fx import utils as fx_utils

    calls = []

    class FakeResponse:
        ok = True
        status_code = 200

        def json(self):
            return {}

    def fake_post(url, timeout=0.5, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(fx_utils.requests, "post", fake_post)

    wled = fx_utils.WLED("10.0.0.5")
    _run(wled.release_realtime())

    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == "http://10.0.0.5/json/state"
    assert kwargs["json"] == {"live": False}


def test_wled_device_deactivate_fires_the_explicit_release():
    """The wiring proof: WLEDDevice.deactivate() reaches
    WLED.release_realtime() — not just relies on the UDP timeout lapsing."""
    from fx.devices.wled import WLEDDevice

    calls = []

    class FakeWLED:
        async def release_realtime(self):
            calls.append("release_realtime")

    class FakeLedfx:
        def __init__(self, loop):
            self.loop = loop

    async def main():
        dev = WLEDDevice(FakeLedfx(asyncio.get_running_loop()),
                         {"name": "strip", "pixel_count": 1})
        dev.wled = FakeWLED()
        dev.deactivate()
        await asyncio.sleep(0.05)  # let the fire-and-forget task run

    _run(main())
    assert calls == ["release_realtime"]


def test_wled_device_deactivate_before_async_initialize_does_not_crash():
    """deactivate() can run before async_initialize() ever set self.wled
    (e.g. a handover abort mid-setup) — must not raise."""
    from fx.devices.wled import WLEDDevice

    class FakeLedfx:
        def __init__(self, loop):
            self.loop = loop

    async def main():
        dev = WLEDDevice(FakeLedfx(asyncio.get_running_loop()),
                         {"name": "strip", "pixel_count": 1})
        assert dev.wled is None
        dev.deactivate()  # must not raise
        await asyncio.sleep(0.01)

    _run(main())


def test_hue_device_deactivate_stops_the_entertainment_session():
    """The already-explicit Hue release (unchanged by this work, verified
    here on a fake bridge): deactivate() PUTs action:"stop", freeing the
    group for Home Assistant."""
    import concurrent.futures
    from fx.devices.hue import HueDevice

    calls = []

    class FakeLedfx:
        def __init__(self, loop):
            self.loop = loop
            self.thread_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    config = {
        "name": "hue-strip", "ip_address": "10.0.0.9", "group_name": "zone",
        "udp_port": 2100, "hue_application_id": "app-id",
        "clientkey": "00" * 16, "username": "user",
        "entertainment_id": "ent-1", "pixel_count": 1,
    }

    async def main():
        dev = HueDevice(FakeLedfx(asyncio.get_running_loop()), config)

        def fake_hue_request(method, endpoint, data=None, ssl=False):
            calls.append((method, endpoint, data, ssl))
            return {}, {}

        dev._hue_request = fake_hue_request
        dev.deactivate()
        await asyncio.sleep(0.05)

    _run(main())
    assert calls == [("PUT",
                      "/clip/v2/resource/entertainment_configuration/ent-1",
                      {"action": "stop"}, True)]


# ── 4. the way back: the normal guarded handover, from released ─────────────


def test_way_back_handover_from_released_skips_the_vacuous_quiesce(tmp_path):
    from spectra.services import engine
    from spectra.services.handover import SpectraSide, run_handover
    from spectra.services.live_host import live

    _own_file(tmp_path)
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(str(config_dir))
    lo.release("spec: start from released")

    class NeverCalledSide:
        name = lo.SPOT_EFFECTS

        async def readiness_problems(self):
            raise AssertionError("from_side must never be consulted coming "
                                 "from released")

        async def quiesce(self):
            raise AssertionError("nothing to quiesce coming from released")

        async def verify_quiesced(self):
            raise AssertionError

        async def activate(self):
            raise AssertionError("nothing to restore coming from released")

        async def verify_active(self):
            raise AssertionError

        async def deactivate(self):
            raise AssertionError

    sides = {lo.SPOT_EFFECTS: NeverCalledSide(),
            lo.SPECTRA: SpectraSide(config_dir=str(config_dir), open_audio=False)}

    async def main():
        try:
            record = await run_handover(lo.SPECTRA, sides, grace_s=0)
            assert record.owner == lo.SPECTRA
            assert live.active
        finally:
            engine.go_dark()
            from fx import facade
            facade.set_host(None)
            if live.active:
                await live.deactivate()

    _run(main())


def test_way_back_activation_failure_lands_back_at_released(tmp_path):
    from spectra.services.handover import HandoverFailed, run_handover

    _own_file(tmp_path)
    lo.release("spec: start from released")

    class FailingSpectraSide:
        name = lo.SPECTRA

        async def readiness_problems(self):
            return []

        async def activate(self):
            raise RuntimeError("simulated activation failure")

        async def verify_active(self):
            return False

        async def deactivate(self):
            pass

    sides = {lo.SPOT_EFFECTS: object(),  # never touched — proves from_released
            lo.SPECTRA: FailingSpectraSide()}

    async def main():
        with pytest.raises(HandoverFailed):
            await run_handover(lo.SPECTRA, sides, grace_s=0)

    _run(main())
    # No from-side to "restore" — released was already the safe landing.
    assert lo.load().owner == lo.RELEASED
    assert lo.load().handover is None


# ── 5. both write seams refuse while released ────────────────────────────────


def test_fx_seam_refuses_while_released(tmp_path):
    from spectra.services import fx_seam

    _own_file(tmp_path)
    lo.release("spec: seam must refuse")
    with pytest.raises(fx_seam.RoomReleased):
        _run(fx_seam.apply_writes([]))


def test_spot_effects_write_plane_sheds_while_released(tmp_path):
    from api import ledfx_client as lc

    _own_file(tmp_path)
    lo.release("spec: spot-effects gate must shed")
    resp = _run(lc._request("GET", "/api/info", label="release-spec"))
    assert resp is None
    assert lc.get_health()["light_ownership"] == lo.RELEASED


# ── 6. watchdogs: released is healthy-dark, not dead ─────────────────────────


def test_frame_watchdog_treats_released_and_dark_as_alive():
    from spectra.services.frame_watchdog import evaluate

    alive, reason = evaluate(lo.RELEASED, live_active=False, frames_fresh=False)
    assert alive and reason is None


def test_frame_watchdog_flags_a_live_stack_that_ignored_the_release():
    from spectra.services.frame_watchdog import evaluate

    alive, reason = evaluate(lo.RELEASED, live_active=True, frames_fresh=True)
    assert not alive
    assert "panic release did not take" in reason


def test_write_plane_watchdog_treats_released_as_surrendered_not_wedged():
    from services.write_plane_watchdog import evaluate

    alive, reasons = evaluate(
        {"light_ownership": lo.RELEASED, "last_completion_age_s": 9999,
         "counters": {}, "breaker_open": False},
        {"gate_reset": 0, "deadline": 0})
    assert alive and reasons == []


# ── 7. the liveness endpoint reports released honestly ───────────────────────


def test_liveness_reports_released_state_when_dark(tmp_path):
    from spectra.api.ownership import get_liveness

    _own_file(tmp_path)
    lo.release("spec: liveness released")

    async def main():
        resp = await get_liveness()
        body = json.loads(bytes(resp.body))
        assert resp.status_code == 200
        assert body["healthy"] and body["state"] == "released"
        assert body["owner"] == lo.RELEASED

    _run(main())


def test_liveness_reports_split_brain_if_live_stack_survives_release(tmp_path, monkeypatch):
    from spectra.api.ownership import get_liveness
    from spectra.services.live_host import live

    class FakeHost:
        virtuals: dict = {}
        devices: dict = {}

    _own_file(tmp_path)
    lo.release("spec: liveness split-brain")
    monkeypatch.setattr(live, "host", FakeHost())  # live.active becomes True

    async def main():
        resp = await get_liveness()
        body = json.loads(bytes(resp.body))
        assert resp.status_code == 503
        assert not body["healthy"] and body["state"] == "split-brain"

    _run(main())


# ── 8. the API route: not armed-gated, idempotent, 409 only mid-handover ─────


def test_release_api_not_armed_gated(tmp_path, monkeypatch):
    from spectra.api.ownership import post_release

    _own_file(tmp_path)
    monkeypatch.delenv("SPECTRA_HANDOVER_ARMED", raising=False)

    async def main():
        result = await post_release()
        assert result["result"] == "released"
        assert result["owner"] == lo.RELEASED

    _run(main())


def test_release_api_is_idempotent(tmp_path, monkeypatch):
    from spectra.api.ownership import post_release

    _own_file(tmp_path)
    monkeypatch.delenv("SPECTRA_HANDOVER_ARMED", raising=False)

    async def main():
        await post_release()
        result = await post_release()  # second press — must not error
        assert result["owner"] == lo.RELEASED

    _run(main())


def test_release_api_409_mid_handover(tmp_path):
    from fastapi import HTTPException
    from spectra.api.ownership import post_release

    _own_file(tmp_path)
    lo.begin_handover(lo.SPECTRA)

    async def main():
        with pytest.raises(HTTPException) as exc:
            await post_release()
        assert exc.value.status_code == 409
        assert lo.load().owner == lo.HANDING_OVER

    _run(main())


# ── offline guarantee ────────────────────────────────────────────────────────


def test_no_audio_hardware_was_touched():
    from fx.compat_sounddevice import _LazySounddevice

    assert _LazySounddevice._module is None
