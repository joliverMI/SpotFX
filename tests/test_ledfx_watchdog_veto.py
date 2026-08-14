"""LedFX-restart watchdog: the resurrect-trap veto and the dead-probe-only
trigger (report gate e4iii, two-writers incident 2026-08-13).

Two proofs:
  1. _ledfx_restart_veto_reason() names a veto for every non-spot-effects
     owner (handing-over, spectra, released) and is None only when
     spot-effects outright owns — consulted first-class at both the tick
     accumulation site and immediately before spawning systemctl.
  2. _ledfx_watchdog_tick() only ever counts toward a restart on a DEAD
     probe; sustained high RTT with an answering probe is logged as
     sluggish but never trips the counter or calls the restart.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import light_ownership as lo


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def client(tmp_path, fresh_ledfx_client, monkeypatch):
    lc = fresh_ledfx_client("http://127.0.0.1:1/")
    monkeypatch.setattr(lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")
    return lc


def test_veto_reason_names_each_non_owner_state(client):
    assert client._ledfx_restart_veto_reason() is None  # default: spot-effects

    handover = lo.begin_handover(lo.SPECTRA)
    assert "handover" in client._ledfx_restart_veto_reason()

    lo.mark_quiesced(handover.token)
    lo.commit(handover.token)
    assert "SPECTRA" in client._ledfx_restart_veto_reason()

    rec = lo.load()
    rec.owner = lo.SPOT_EFFECTS
    lo._save(rec)
    lo.release("test")
    assert "released" in client._ledfx_restart_veto_reason()


def test_restart_refuses_when_vetoed(client, caplog, monkeypatch):
    caplog.set_level("CRITICAL", logger="api.ledfx_client")
    lo.begin_handover(lo.SPECTRA)

    async def guard(*a, **k):
        raise AssertionError("systemctl must not be spawned while vetoed")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", guard)
    _run(client._restart_ledfx_service())
    assert any("REFUSING ledfx restart" in r.message
               for r in caplog.records if r.levelname == "CRITICAL")


def test_watchdog_tick_ignores_sluggish_answering_probe(client, monkeypatch):
    """The 2026-08-13 near-miss: rtt=838ms, probe_failed=False must never
    trip the counter or call the restart."""
    restarted = []

    async def fake_restart():
        restarted.append(1)

    monkeypatch.setattr(client, "_restart_ledfx_service", fake_restart)
    client._probe_failed = False
    client.state.ledfx_rtt_ms = 838.0

    for _ in range(client._LEDFX_WATCHDOG_TRIPS + 2):
        _run(client._ledfx_watchdog_tick())

    assert restarted == []
    assert client._watchdog_degraded_count == 0


def test_watchdog_tick_trips_only_on_dead_probe(client, monkeypatch):
    restarted = []

    async def fake_restart():
        restarted.append(1)

    monkeypatch.setattr(client, "_restart_ledfx_service", fake_restart)
    client._probe_failed = True
    client.state.ledfx_rtt_ms = 5.0  # RTT itself is fine; the probe is dead

    for _ in range(client._LEDFX_WATCHDOG_TRIPS - 1):
        _run(client._ledfx_watchdog_tick())
    assert restarted == []  # not yet at the trip threshold

    _run(client._ledfx_watchdog_tick())
    assert restarted == [1]


def test_watchdog_tick_vetoed_during_handover_even_with_dead_probe(client, monkeypatch):
    lo.begin_handover(lo.SPECTRA)
    restarted = []

    async def fake_restart():
        restarted.append(1)

    monkeypatch.setattr(client, "_restart_ledfx_service", fake_restart)
    client._probe_failed = True
    client.state.ledfx_rtt_ms = 5.0

    for _ in range(client._LEDFX_WATCHDOG_TRIPS + 2):
        _run(client._ledfx_watchdog_tick())

    assert restarted == []
    assert client._watchdog_degraded_count == 0
