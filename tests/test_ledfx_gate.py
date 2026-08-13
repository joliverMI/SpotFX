"""Regression tests for the 2026-08-12 write-plane starvation outage.

Failure shape reproduced offline: all _LEDFX_MAX_INFLIGHT semaphore slots
leaked (holders that never release — live, requests whose timeout delivery was
lost during a LedFX stall + cancellation storm). Under the old code every
subsequent ledfx_client._request() — including ambient-mode Hue group
discovery — parked forever in sem.acquire(): no result, no failure, breaker
closed, UI "No Hue groups found". These tests assert the fixed invariants:

  1. a _request against a starved gate returns (None) within the deadline
     instead of hanging;
  2. slot-wait starvation triggers a gate reset, after which requests succeed;
  3. a request wedged in its HTTP phase past the deadline frees its slot
     (the slot-leak class itself);
  4. ambient group discovery — the user-visible victim — completes bounded
     and self-heals to the recorded live groups;
  5. discovery still resolves both groups on the happy path;
  6. resolve_groups serves stale cached groups during a discovery outage
     instead of stripping the picker empty.

All tests drive their own loop via asyncio.run(); no live access anywhere.
"""
from __future__ import annotations

import asyncio
import time

from tests.conftest import FakeLedFX


def _leak_all_slots(lc):
    """Simulate the outage: every gate slot held by something that will never
    release it."""
    sem = lc._get_sem()
    for _ in range(lc._LEDFX_MAX_INFLIGHT):
        assert sem._value > 0
        sem._value -= 1  # equivalent to an acquire() whose owner vanished
    assert sem._value == 0


def test_request_bounded_when_gate_starved(fresh_ledfx_client):
    async def run():
        async with FakeLedFX() as srv:
            lc = fresh_ledfx_client(srv.base_url)
            lc._LEDFX_REQUEST_DEADLINE_S = 0.6
            _leak_all_slots(lc)
            t0 = time.monotonic()
            # Old code: parks in sem.acquire() forever -> wait_for trips.
            resp = await asyncio.wait_for(
                lc._request("GET", "/api/info", label="starved"), timeout=5
            )
            dt = time.monotonic() - t0
            assert resp is None
            assert dt < 3, f"request took {dt:.1f}s — deadline did not bound it"
            assert lc._event_counters["deadline"] == 1
            # Starvation was recognized as such, not as a slow request.
            assert lc._event_counters["gate_reset"] == 1

    asyncio.run(run())


def test_gate_reset_restores_service(fresh_ledfx_client):
    async def run():
        async with FakeLedFX() as srv:
            lc = fresh_ledfx_client(srv.base_url)
            lc._LEDFX_REQUEST_DEADLINE_S = 0.6
            _leak_all_slots(lc)
            assert await lc._request("GET", "/api/info", label="starved") is None
            # The reset rebuilt the gate: the very next request must succeed.
            resp = await asyncio.wait_for(
                lc._request("GET", "/api/info", label="after-reset"), timeout=5
            )
            assert resp is not None and resp.status_code == 200
            # Full capacity restored and returned after use.
            assert lc._get_sem()._value == lc._LEDFX_MAX_INFLIGHT

    asyncio.run(run())


def test_wedged_http_attempt_frees_its_slot(fresh_ledfx_client):
    """The leak class itself: a request stuck in its HTTP phase beyond every
    inner timeout must be forced out by the outer deadline WITH its slot
    released — under the old code each such request leaked one slot for the
    process lifetime (24 of them = the outage)."""

    async def run():
        async with FakeLedFX() as srv:
            lc = fresh_ledfx_client(srv.base_url)
            lc._LEDFX_REQUEST_DEADLINE_S = 0.8
            # Neutralize httpx's own phase timeouts so the fake stall models a
            # request the HTTP stack never times out (the live wedge).
            import httpx
            lc._client = httpx.AsyncClient(base_url=srv.base_url, timeout=None)
            srv.mode = "stall"
            resp = await asyncio.wait_for(
                lc._request("GET", "/api/info", label="wedged"), timeout=5
            )
            assert resp is None
            assert lc._get_sem()._value == lc._LEDFX_MAX_INFLIGHT, "slot leaked"
            # This was a request-phase expiry, not gate starvation:
            assert lc._event_counters["gate_reset"] == 0
            assert lc._event_counters["deadline"] == 1

    asyncio.run(run())


def test_ambient_discovery_bounded_and_self_heals_when_starved(ambient_env, fresh_ledfx_client):
    """THE incident regression: ambient Hue-group discovery against a starved
    gate. Old behavior: resolve_groups() never returns (picker falls back to
    'No Hue groups found'). Fixed behavior: bounded, gate self-heals mid-call,
    and the recorded live groups come back."""
    am = ambient_env

    async def run():
        async with FakeLedFX() as srv:
            lc = fresh_ledfx_client(srv.base_url)
            lc._LEDFX_REQUEST_DEADLINE_S = 0.8
            _leak_all_slots(lc)
            t0 = time.monotonic()
            groups = await asyncio.wait_for(am.resolve_groups(force=True), timeout=10)
            dt = time.monotonic() - t0
            assert dt < 8, f"discovery took {dt:.1f}s"
            assert groups == {"hue-lights": "Hue Lights", "dining-hues": "Dining Hues"}
            assert lc._event_counters["gate_reset"] == 1

    asyncio.run(run())


def test_ambient_discovery_happy_path(ambient_env, fresh_ledfx_client):
    am = ambient_env

    async def run():
        async with FakeLedFX() as srv:
            lc = fresh_ledfx_client(srv.base_url)
            groups = await asyncio.wait_for(am.resolve_groups(force=True), timeout=10)
            assert groups == {"hue-lights": "Hue Lights", "dining-hues": "Dining Hues"}
            # Discovery read the LedFX API, not anything live.
            assert "/api/virtuals" in srv.requests
            assert lc._event_counters["deadline"] == 0

    asyncio.run(run())


def test_resolve_groups_serves_stale_cache_during_outage(ambient_env, fresh_ledfx_client):
    am = ambient_env

    async def run():
        async with FakeLedFX() as srv:
            fresh_ledfx_client(srv.base_url)
            first = await am.resolve_groups(force=True)
            assert first  # cache seeded

            async def nothing():
                return {}

            orig = am._resolve_hue_cfgs
            am._resolve_hue_cfgs = nothing
            try:
                again = await am.resolve_groups(force=True)
            finally:
                am._resolve_hue_cfgs = orig
            assert again == first, "stale cache should mask a transient outage"

    asyncio.run(run())
