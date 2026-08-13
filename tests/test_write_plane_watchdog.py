"""Write-plane watchdog (detection Option B) — predicate + sd_notify gating.

Extends the 2026-08-12 starvation harness: the same FakeLedFX/fresh-client
plumbing drives real _request traffic, and a real AF_UNIX datagram socket
stands in for systemd's $NOTIFY_SOCKET so the tests assert the actual pings,
not a mock. Covered:

  1. predicate alive under healthy flow, and the tick pings WATCHDOG=1;
  2. predicate wedged under simulated gate starvation, ping withheld,
     CRITICAL once per episode, recovery after the self-heal sticks;
  3. breaker-open (LedFX-side outage) stays ALIVE for the excusable signals
     (deadline advance, stale completions) but NOT for write-plane-internal
     ones (gate_reset advance, oldest_inflight past the hard deadline);
  4. ping cessation on alarm-task death — pings originate solely from the
     supervised task, so cancelling it stops them by construction;
  5. sd_notify is a silent no-op without $NOTIFY_SOCKET (dark-compatible).

All tests drive their own loop via asyncio.run(); no live access anywhere.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import socket

import pytest

from tests.conftest import FakeLedFX
from tests.test_ledfx_gate import _leak_all_slots


@pytest.fixture()
def wp():
    """Fresh services.write_plane_watchdog per test (episode latch, counter
    snapshot)."""
    import services.write_plane_watchdog as mod
    importlib.reload(mod)
    return mod


@pytest.fixture()
def notify_socket(tmp_path, monkeypatch):
    """A real AF_UNIX datagram socket exported as $NOTIFY_SOCKET; returns a
    drain() that collects every datagram received so far."""
    path = tmp_path / "notify.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(str(path))
    sock.setblocking(False)
    monkeypatch.setenv("NOTIFY_SOCKET", str(path))

    def drain() -> list[bytes]:
        out = []
        while True:
            try:
                out.append(sock.recv(4096))
            except BlockingIOError:
                return out

    yield drain
    sock.close()


# ── Pure predicate ────────────────────────────────────────────────────────────

def _health(**over) -> dict:
    base = {
        "breaker_open": False,
        "counters": {"deadline": 0, "gate_reset": 0},
        "oldest_inflight_s": 0.0,
        "request_deadline_s": 10.0,
        "last_completion_age_s": 4.0,
    }
    base.update(over)
    return base


def test_predicate_alive_on_healthy_snapshot(wp):
    alive, reasons = wp.evaluate(_health(), {"deadline": 0, "gate_reset": 0})
    assert alive and reasons == []
    # First tick (no baseline) and boot (no completion yet) are alive too.
    assert wp.evaluate(_health(last_completion_age_s=None), None)[0]


def test_predicate_wedged_on_each_signal(wp):
    prev = {"deadline": 0, "gate_reset": 0}
    assert not wp.evaluate(_health(counters={"deadline": 2, "gate_reset": 0}), prev)[0]
    assert not wp.evaluate(_health(counters={"deadline": 0, "gate_reset": 1}), prev)[0]
    assert not wp.evaluate(_health(oldest_inflight_s=11.0), prev)[0]
    assert not wp.evaluate(_health(last_completion_age_s=61.0), prev)[0]


def test_breaker_open_excuses_ledfx_outage_shapes_only(wp):
    """A legitimate LedFX outage (breaker open) must never stop the pings:
    deadline advances and stale completions are excused. Write-plane-internal
    signals still trip even with the breaker open."""
    prev = {"deadline": 0, "gate_reset": 0}
    assert wp.evaluate(_health(breaker_open=True,
                               counters={"deadline": 3, "gate_reset": 0},
                               last_completion_age_s=120.0), prev)[0]
    assert not wp.evaluate(_health(breaker_open=True,
                                   counters={"deadline": 0, "gate_reset": 1}), prev)[0]
    assert not wp.evaluate(_health(breaker_open=True, oldest_inflight_s=11.0), prev)[0]


# ── Tick against real gate traffic ────────────────────────────────────────────

def test_tick_pings_under_healthy_flow(wp, notify_socket, fresh_ledfx_client):
    async def run():
        async with FakeLedFX() as srv:
            lc = fresh_ledfx_client(srv.base_url)
            assert (await lc._request("GET", "/api/info", label="healthy")) is not None
            wp._tick()
            wp._tick()

    asyncio.run(run())
    pings = notify_socket()
    assert pings == [b"WATCHDOG=1", b"WATCHDOG=1"]


def test_tick_withholds_ping_under_starvation(wp, notify_socket, fresh_ledfx_client, caplog):
    """The outage shape: a starved gate advances the deadline + gate_reset
    counters → the tick withholds the ping and logs CRITICAL once; after the
    self-heal sticks (counters stop advancing, requests succeed) the next tick
    logs recovery and resumes pinging."""

    async def run():
        async with FakeLedFX() as srv:
            lc = fresh_ledfx_client(srv.base_url)
            lc._LEDFX_REQUEST_DEADLINE_S = 0.6
            wp._tick()                       # baseline counters, pings once
            _leak_all_slots(lc)
            assert await lc._request("GET", "/api/info", label="starved") is None
            with caplog.at_level(logging.CRITICAL, logger=wp.logger.name):
                wp._tick()                   # counters advanced → wedged
            assert any("WRITE PLANE WEDGED" in r.message for r in caplog.records)
            # Self-heal stuck: traffic flows again, counters quiesce.
            assert (await lc._request("GET", "/api/info", label="healed")) is not None
            wp._tick()                       # recovery + ping resumes

    asyncio.run(run())
    assert notify_socket() == [b"WATCHDOG=1", b"WATCHDOG=1"]  # none during the episode


def test_critical_logged_once_per_episode(wp, fresh_ledfx_client, caplog, monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)

    async def run():
        async with FakeLedFX() as srv:
            lc = fresh_ledfx_client(srv.base_url)
            lc._LEDFX_REQUEST_DEADLINE_S = 0.6
            wp._tick()
            _leak_all_slots(lc)
            assert await lc._request("GET", "/api/info", label="starved") is None
            lc._inflight_started[999] = ("stuck", 0.001)  # oldest_inflight breach persists
            with caplog.at_level(logging.WARNING, logger=wp.logger.name):
                wp._tick()
                wp._tick()

    asyncio.run(run())
    crits = [r for r in caplog.records if "WRITE PLANE WEDGED" in r.message]
    assert len(crits) == 1, "episode latch must suppress repeat CRITICALs"


# ── Supervised task wiring ────────────────────────────────────────────────────

def test_ping_cessation_when_alarm_task_dies(wp, notify_socket, fresh_ledfx_client):
    """Structural: WATCHDOG=1 is sent only from the supervised task's tick, so
    the task dying stops the pings by construction — nothing else can keep the
    watchdog fed. READY=1 is the Type=notify startup handshake."""

    async def run():
        async with FakeLedFX() as srv:
            fresh_ledfx_client(srv.base_url)
            wp.TICK_S = 0.05
            task = asyncio.create_task(wp.run_supervised())
            await asyncio.sleep(0.18)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            during = notify_socket()
            assert during[0] == b"READY=1"
            assert during.count(b"WATCHDOG=1") >= 2
            await asyncio.sleep(0.2)
            assert notify_socket() == [], "pings must stop when the task is dead"

    asyncio.run(run())


def test_supervisor_retries_after_tick_crash(wp, notify_socket, fresh_ledfx_client, monkeypatch):
    """A transiently-crashing tick misses its ping but the supervisor keeps
    the task alive; a later healthy tick pings again (systemd tolerates 2
    missed ticks via WatchdogSec=90)."""

    async def run():
        async with FakeLedFX() as srv:
            fresh_ledfx_client(srv.base_url)
            wp.TICK_S = 0.05
            real_tick, calls = wp._tick, []

            def flaky():
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("boom")
                real_tick()

            monkeypatch.setattr(wp, "_tick", flaky)
            task = asyncio.create_task(wp.run_supervised())
            await asyncio.sleep(0.18)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            assert len(calls) >= 3, "supervisor must keep ticking after a crash"

    asyncio.run(run())
    assert notify_socket().count(b"WATCHDOG=1") >= 1


def test_sd_notify_noop_without_socket(wp, monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert wp.sd_notify("WATCHDOG=1") is False   # dark-compatible: silent no-op
