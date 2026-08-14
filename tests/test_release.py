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
from tests.conftest import FakeLedFX


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


# ── 2. release_room(): both worlds' cleanup, over the REAL seams ────────────
#
# Three defects fixed here (merge-scout two-writers report, 2026-08-13,
# judging PR #34 against that night's incident):
#   1. cleanup no longer branches on from_world — BOTH worlds run every time
#      a settled owner presses release, so a rogue writer the record didn't
#      know about (tonight: the record said spectra while systemd's
#      Wants=ledfx.service had resurrected the external LedFX behind its
#      back) still gets addressed.
#   2. the external-LedFX calls go through spectra/services/ledfx_release.py,
#      a direct client that never touches api.ledfx_client — so they are
#      never shed by its ownership gate. Proven below against the REAL gate
#      and a REAL fake-server HTTP round trip, not a monkeypatch of
#      get_all_virtuals/set_virtual_active themselves (which is what let the
#      old tests pass while production silently no-opped).
#   3. release_room() verifies by reading real state back afterward and
#      reports it in ReleaseResult.verified/.problems instead of just
#      claiming success.


def _ledfx_unit_stopped(monkeypatch) -> None:
    """Verification's cheap path: the external LedFX systemd unit reports
    not running, so _verify_released() never re-reads virtuals over HTTP."""
    from spectra.services import handover as handover_svc

    async def fake_systemctl(*args):
        return 0, "inactive"

    monkeypatch.setattr(handover_svc, "_systemctl", fake_systemctl)


def _ledfx_unit_running(monkeypatch) -> None:
    """Verification's HTTP path: the unit reports active, forcing
    _verify_released() to re-read virtuals over the direct client."""
    from spectra.services import handover as handover_svc

    async def fake_systemctl(*args):
        return 0, "active"

    monkeypatch.setattr(handover_svc, "_systemctl", fake_systemctl)


def test_release_room_deactivates_active_ledfx_virtuals_over_the_real_seam(tmp_path, monkeypatch):
    """A fake external LedFX answers REAL HTTP requests — proving
    release_room() actually reaches it (defect 2) and that verification
    confirms the deactivation for real (defect 3), not via a stubbed
    return value."""
    from spectra.services import release as release_svc

    _own_file(tmp_path)
    _ledfx_unit_running(monkeypatch)

    async def main():
        async with FakeLedFX(virtuals={
            "v1": {"active": True}, "v2": {"active": False}, "v3": {"active": True},
        }) as srv:
            monkeypatch.setenv("SPECTRA_LEDFX_URL", srv.base_url)
            result = await release_svc.release_room("spec: real seam release")
            assert result.record.owner == lo.RELEASED
            put_vids = sorted(p.rsplit("/", 1)[-1]
                              for m, p in srv.calls if m == "PUT")
            assert put_vids == ["v1", "v3"]
            assert srv.virtuals["v1"]["active"] is False
            assert srv.virtuals["v3"]["active"] is False
            assert result.verified, result.problems
            assert result.problems == []

    _run(main())


def test_release_room_ledfx_one_virtual_failure_does_not_stop_the_rest(tmp_path, monkeypatch):
    from spectra.services import release as release_svc

    _own_file(tmp_path)
    _ledfx_unit_running(monkeypatch)

    async def main():
        async with FakeLedFX(virtuals={"v1": {"active": True}, "v2": {"active": True}}) as srv:
            monkeypatch.setenv("SPECTRA_LEDFX_URL", srv.base_url)

            real_put = srv._route

            def flaky_route(method, path, body=b""):
                if method == "PUT" and path.endswith("/v1"):
                    raise ConnectionResetError("simulated LedFX timeout")
                return real_put(method, path, body)

            srv._route = flaky_route

            result = await release_svc.release_room("spec: one virtual fails")
            # Released stands regardless — cleanup failure never re-opens
            # the gate — but v1's failure to deactivate must surface as an
            # unverified problem, not a silent success.
            assert result.record.owner == lo.RELEASED
            assert srv.virtuals["v2"]["active"] is False
            assert result.verified is False
            assert any("v1" in p for p in result.problems)

    _run(main())


def test_release_room_reports_unverified_when_a_device_lies(tmp_path, monkeypatch):
    """Verification-failure path, proven loud (defect 3): a PUT that
    reports success without actually flipping the device (the exact
    'command is not proof' failure mode handover.py's verify_quiesced
    guards against) must still be caught by the read-back."""
    from spectra.services import release as release_svc

    _own_file(tmp_path)
    _ledfx_unit_running(monkeypatch)

    async def main():
        async with FakeLedFX(virtuals={"v1": {"active": True}}) as srv:
            srv.mode = "lie"
            monkeypatch.setenv("SPECTRA_LEDFX_URL", srv.base_url)
            result = await release_svc.release_room("spec: stuck virtual")
            assert result.record.owner == lo.RELEASED   # still lands released
            assert result.verified is False
            assert any("v1" in p for p in result.problems)

    _run(main())


def test_ledfx_release_client_bypasses_the_spot_effects_gate(tmp_path, monkeypatch):
    """The real proof for defect 2: under the SAME released record,
    api.ledfx_client._request sheds every call (writes_allowed() is
    spot-effects-exclusive) while spectra.services.ledfx_release — the
    direct client release cleanup actually uses — reaches the real server,
    because it never passes through that gate at all. No monkeypatching of
    either module's request functions."""
    from api import ledfx_client as lc
    from spectra.services import ledfx_release

    _own_file(tmp_path)
    lo.release("spec: prove the gate split")

    async def main():
        async with FakeLedFX(virtuals={"v1": {"active": True}}) as srv:
            resp = await lc._request(
                "GET", "/api/virtuals", label="release-spec-gate")
            assert resp is None    # the spot-effects gate sheds it

            monkeypatch.setenv("SPECTRA_LEDFX_URL", srv.base_url)
            raw = await ledfx_release.get_all_virtuals()   # bypasses that gate
            assert raw["virtuals"]["v1"]["active"] is True
            assert "/api/virtuals" in srv.requests

    _run(main())


# ── 2b. release_room(): spectra → the real live stack tears down ────────────


def test_release_room_deactivates_the_real_spectra_live_stack(tmp_path, monkeypatch):
    from spectra.services import engine
    from spectra.services.handover import SpectraSide
    from spectra.services.live_host import live
    from spectra.services import release as release_svc

    _own_file(tmp_path)
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(str(config_dir))
    _ledfx_unit_stopped(monkeypatch)   # no rogue LedFX in this scenario

    async def main():
        try:
            h = lo.begin_handover(lo.SPECTRA)
            lo.mark_quiesced(h.token)
            grant = lo.mint_activation_grant(lo.SPECTRA)
            side = SpectraSide(config_dir=str(config_dir), open_audio=False)
            await side.activate()
            lo.commit(h.token)
            assert live.active

            result = await release_svc.release_room("spec: spectra release")
            assert result.record.owner == lo.RELEASED
            # The device layer actually tore down — dummy device deactivated,
            # host gone, engine dark — not just the ownership record moving.
            assert not live.active
            assert engine.executor.mode == "recording"
            assert result.verified, result.problems
        finally:
            engine.go_dark()
            from fx import facade
            facade.set_host(None)
            if live.active:
                await live.deactivate()

    _run(main())


def test_release_room_addresses_rogue_ledfx_while_record_says_spectra(tmp_path, monkeypatch):
    """THE EXACT SHAPE OF THE 2026-08-13 INCIDENT (defect 1's proof): the
    record says spectra owns while systemd's Wants=ledfx.service resurrected
    the external LedFX behind the record's back — a second, rogue writer the
    record doesn't know about. Before this fix, release_room() branched on
    from_world == SPECTRA and never called _release_ledfx_virtuals at all,
    leaving the rogue LedFX painting the room alone after the press. Now
    both worlds are addressed and verified every time."""
    from spectra.services.handover import SpectraSide
    from spectra.services.live_host import live
    from spectra.services import release as release_svc

    _own_file(tmp_path)
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(str(config_dir))
    _ledfx_unit_running(monkeypatch)   # the rogue LedFX process IS running

    async def main():
        async with FakeLedFX(virtuals={"rogue-v1": {"active": True}}) as srv:
            monkeypatch.setenv("SPECTRA_LEDFX_URL", srv.base_url)
            try:
                h = lo.begin_handover(lo.SPECTRA)
                lo.mark_quiesced(h.token)
                grant = lo.mint_activation_grant(lo.SPECTRA)
                side = SpectraSide(config_dir=str(config_dir), open_audio=False)
                await side.activate()
                lo.commit(h.token)
                assert lo.load().owner == lo.SPECTRA
                assert live.active

                result = await release_svc.release_room(
                    "spec: panic while record says spectra, LedFX rogue")

                assert result.record.owner == lo.RELEASED
                assert not live.active   # the recorded (legitimate) writer torn down
                put_paths = [p for m, p in srv.calls if m == "PUT"]
                assert any(p.endswith("rogue-v1") for p in put_paths), (
                    "the rogue external LedFX must be addressed even though "
                    "the record said spectra owned, not spot-effects")
                assert srv.virtuals["rogue-v1"]["active"] is False
                assert result.verified, result.problems
            finally:
                from spectra.services import engine
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
    _ledfx_unit_stopped(monkeypatch)   # verification's cheap path, no network

    called = []

    async def must_not_be_called(*a, **kw):
        called.append(True)
        raise AssertionError("device-class cleanup must not re-run when "
                             "already released")

    monkeypatch.setattr(release_svc, "_release_ledfx_virtuals", must_not_be_called)
    monkeypatch.setattr(release_svc, "_release_spectra_devices", must_not_be_called)

    result = _run(release_svc.release_room("second press"))
    assert result.record.owner == lo.RELEASED
    assert called == []
    assert result.verified


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
    _ledfx_unit_stopped(monkeypatch)

    async def main():
        result = await post_release()
        assert result["result"] == "released"
        assert result["owner"] == lo.RELEASED

    _run(main())


def test_release_api_is_idempotent(tmp_path, monkeypatch):
    from spectra.api.ownership import post_release

    _own_file(tmp_path)
    monkeypatch.delenv("SPECTRA_HANDOVER_ARMED", raising=False)
    _ledfx_unit_stopped(monkeypatch)

    async def main():
        await post_release()
        result = await post_release()  # second press — must not error
        assert result["owner"] == lo.RELEASED

    _run(main())


def test_release_api_reports_unverified_loudly(tmp_path, monkeypatch):
    """The API surface for defect 3: when verification can't confirm reality
    matches, the route must not report a clean "released". result flips to
    "released-unverified" at HTTP 207, carrying the specific problems so the
    UI can warn ("these lights may still be lit") instead of going quiet."""
    from spectra.api.ownership import post_release

    _own_file(tmp_path)
    monkeypatch.delenv("SPECTRA_HANDOVER_ARMED", raising=False)
    _ledfx_unit_running(monkeypatch)
    # Nothing listens here — the external LedFX is "running" per systemctl
    # but unreachable over HTTP, exactly like a wedged or half-dead service.
    monkeypatch.setenv("SPECTRA_LEDFX_URL", "http://127.0.0.1:1")

    async def main():
        response = await post_release()
        assert response.status_code == 207
        body = json.loads(bytes(response.body))
        assert body["result"] == "released-unverified"
        assert body["owner"] == lo.RELEASED
        assert body["problems"]

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
