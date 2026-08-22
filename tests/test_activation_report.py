"""spectra/services/activation_report.py — the unit proofs, on a minimal
fake host (the tests/test_device_live_poll.py shape): how a skipped device
is described (kind + the sentence he reads), how status()/liveness_summary()
gate on the stack being up, how recheck() marks recovery / keeps a still-
dark light honest / retries a never-resolved driver's own init, and that
the report can never outlive the stack. The real-pipeline proofs (real
FxHost + real WLED driver + real API route) are tests/test_take_back_
partial.py; the policy proofs on run_handover are there too.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra.services import activation_report as ar
from spectra.services.live_host import live


class _FakeVirtual:
    def __init__(self, segments):
        self._segments = segments


class _FakeWled:
    def __init__(self, live_after=None, unreachable=False):
        self.live_after = live_after
        self.unreachable = unreachable
        self.calls = 0

    async def get_info(self):
        self.calls += 1
        if self.unreachable:
            raise ValueError("WLED None: Failed to connect")
        return {"live": self.live_after is not None and self.calls >= self.live_after,
                "lip": "127.0.0.1", "fps": 41}


class _FakeDevice:
    def __init__(self, device_id, name, ip_address, *, destination,
                 wled=None, dtype="wled"):
        self.id = device_id
        self.type = dtype
        self._config = {"name": name, "ip_address": ip_address}
        self._destination = destination
        self.wled = wled
        self.init_calls = 0
        self.activate_calls = 0
        self._active = False
        self.init_resolves_to = None   # set to an address to "fix" the light

    async def async_initialize(self):
        self.init_calls += 1
        if self.init_resolves_to is not None:
            self._destination = self.init_resolves_to
            self.wled = _FakeWled(live_after=1)

    def activate(self):
        self.activate_calls += 1
        self._active = True

    def is_active(self):
        return self._active


class _FakeHost:
    def __init__(self, virtuals, devices):
        self.virtuals = virtuals
        self.devices = devices


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def fake_live(monkeypatch):
    """Install a fake host on the module-level `live` (the report reads
    live.host / live.expected_active_ids / live.expected_device_ids) and
    tear it down after."""
    def install(devices: dict, expected_virtuals: dict):
        live.host = _FakeHost(expected_virtuals, devices)
        live.expected_active_ids = set(expected_virtuals)
        return live
    yield install
    live.host = None
    live.expected_active_ids = set()


def _room(fake_live, dark: _FakeDevice):
    devices = {
        "porch-rail": _FakeDevice("porch-rail", "porch-rail", "porch", destination="porch", dtype="dummy"),
        "crystal": _FakeDevice("crystal", "crystal", "crystal", destination="crystal", dtype="dummy"),
        dark.id: dark,
    }
    return fake_live(devices, {
        "crystal-mapper": _FakeVirtual([("crystal", 0, 31, False)]),
        "single-color-effect": _FakeVirtual([("porch-rail", 0, 15, False),
                                             (dark.id, 0, 0, False)]),
    })


# ── describing a skipped device ─────────────────────────────────────────────

def test_unresolved_device_is_described_by_its_configured_address(fake_live):
    dark = _FakeDevice("dining-table", "Dining Table", "wled-8a3534.local",
                       destination=None, wled=_FakeWled(unreachable=True))
    _room(fake_live, dark)
    report = ar.record_from_live(
        ar.SOURCE_TAKE_BACK, {},
        {"dining-table": "could not confirm live state: "
                         "ValueError('WLED None: Failed to connect')"})
    assert report.partial and report.source == ar.SOURCE_TAKE_BACK
    assert report.expected_virtuals == 2 and report.up_virtuals == 2
    assert report.devices_total == 3
    entry = report.skipped["dining-table"]
    assert entry.name == "Dining Table"
    assert entry.kind == ar.KIND_UNRESOLVED
    assert entry.address == "wled-8a3534.local"
    assert entry.why == ("address 'wled-8a3534.local' did not resolve — the "
                         "light is not reachable on the network")
    assert "Dining Table" in report.summary() and "did not resolve" in report.summary()


def test_resolved_but_silent_device_is_unreachable_by_destination(fake_live):
    dark = _FakeDevice("sconce-kitchen-left", "Sconce, Kitchen, Left",
                       "192.168.40.110", destination="192.168.40.110",
                       wled=_FakeWled(unreachable=True))
    _room(fake_live, dark)
    report = ar.record_from_live(
        ar.SOURCE_TAKE_BACK, {},
        {"sconce-kitchen-left": "could not confirm live state: "
                                "ValueError('WLED 192.168.40.110: Failed to connect')"})
    entry = report.skipped["sconce-kitchen-left"]
    assert entry.kind == ar.KIND_UNREACHABLE
    assert "192.168.40.110" in entry.why and "no answer" in entry.why


def test_device_reporting_live_false_is_not_receiving(fake_live):
    dark = _FakeDevice("tv-backlight", "WLED", "192.168.40.236",
                       destination="192.168.40.236", wled=_FakeWled())
    _room(fake_live, dark)
    report = ar.record_from_live(
        ar.SOURCE_RESUME, {},
        {"tv-backlight": "device reports live=false — not receiving realtime data"})
    entry = report.skipped["tv-backlight"]
    assert entry.kind == ar.KIND_NOT_RECEIVING
    assert "not receiving SPECTRA's stream" in entry.why
    assert report.source == ar.SOURCE_RESUME


def test_virtual_gaps_are_carried_and_named(fake_live):
    _room(fake_live, _FakeDevice("d", "D", "d", destination="d"))
    report = ar.record_from_live(
        ar.SOURCE_RESUME,
        {"crystal-mapper": "not flushing frames (last_flush_age_s=None)"}, {})
    assert report.partial
    assert report.up_virtuals == 1 and report.expected_virtuals == 2
    assert "crystal-mapper" in report.summary()
    assert report.to_json()["virtual_gaps"] == {
        "crystal-mapper": "not flushing frames (last_flush_age_s=None)"}


def test_clean_activation_is_a_non_partial_report(fake_live):
    _room(fake_live, _FakeDevice("d", "D", "d", destination="d"))
    report = ar.record_from_live(ar.SOURCE_RESUME, {}, {})
    assert not report.partial
    assert report.summary() == "every expected light came up"
    assert ar.status()["partial"] is False
    assert ar.liveness_summary()["devices_still_dark"] == 0


# ── gating: the report never outlives the stack ─────────────────────────────

def test_status_is_none_while_the_stack_is_down():
    assert live.host is None
    assert ar.status() is None and ar.liveness_summary() is None
    assert ar.current() is None


def test_report_disappears_when_the_stack_goes_down_and_clear_empties_it(fake_live):
    dark = _FakeDevice("dining-table", "Dining Table", "x.invalid",
                       destination=None, wled=_FakeWled(unreachable=True))
    _room(fake_live, dark)
    ar.record_from_live(ar.SOURCE_TAKE_BACK, {}, {"dining-table": "could not confirm live state: x"})
    assert ar.status()["devices_still_dark"] == 1
    live.host = None
    assert ar.current() is None and ar.status() is None
    ar.clear()
    assert ar._report is None


# ── recheck: honesty after commit ───────────────────────────────────────────

def test_recheck_keeps_a_still_dark_light_honest_and_retries_its_driver(fake_live):
    dark = _FakeDevice("dining-table", "Dining Table", "x.invalid",
                       destination=None, wled=_FakeWled(unreachable=True))
    _room(fake_live, dark)
    report = ar.record_from_live(ar.SOURCE_TAKE_BACK, {}, {"dining-table": "could not confirm live state: ValueError('WLED None: Failed to connect')"})
    entry = report.skipped["dining-table"]
    first = entry.last_checked_wall

    async def main():
        await asyncio.sleep(0.01)
        out = await ar.recheck(probe_timeout_s=0.2)
        assert out is report
        assert entry.still_dark
        assert entry.last_checked_wall > first
        # A driver with no destination gets its own init retried, once per
        # recheck; it never resolved, so it is not activated.
        assert dark.init_calls == 1 and dark.activate_calls == 0
        assert entry.retries == 1
        assert ar.status()["skipped"][0]["last_checked_age_s"] < 5

    _run(main())


def test_recheck_marks_recovery_and_activates_a_fixed_unresolved_light(fake_live):
    dark = _FakeDevice("dining-table", "Dining Table", "x.invalid",
                       destination=None, wled=_FakeWled(unreachable=True))
    _room(fake_live, dark)
    report = ar.record_from_live(ar.SOURCE_TAKE_BACK, {}, {"dining-table": "could not confirm live state: ValueError('WLED None: Failed to connect')"})
    entry = report.skipped["dining-table"]

    async def main():
        dark.init_resolves_to = "192.168.40.99"   # the light was fixed
        await ar.recheck(probe_timeout_s=0.2)
        assert not entry.still_dark and entry.recovered_wall is not None
        assert dark.init_calls == 1 and dark.activate_calls == 1
        assert dark.is_active()
        assert report.still_dark == [] and report.recovered == [entry]
        js = ar.status()
        assert js["devices_still_dark"] == 0
        assert js["skipped"][0]["still_dark"] is False
        assert js["skipped"][0]["recovered_age_s"] is not None
        assert "came back later: Dining Table" in js["summary"]
        # A recovered light is never re-initialized or re-probed again.
        await ar.recheck(probe_timeout_s=0.2)
        assert dark.init_calls == 1 and dark.wled.calls == 1

    _run(main())


def test_recheck_on_a_resolved_device_only_reasks_and_recovers_on_live_true(fake_live):
    wled = _FakeWled(live_after=2)   # first probe live=false, second true
    dark = _FakeDevice("sconce", "Sconce", "192.168.40.110",
                       destination="192.168.40.110", wled=wled)
    _room(fake_live, dark)
    report = ar.record_from_live(ar.SOURCE_TAKE_BACK, {}, {"sconce": "device reports live=false — not receiving realtime data"})
    entry = report.skipped["sconce"]

    async def main():
        await ar.recheck(probe_timeout_s=0.2)
        assert entry.still_dark and dark.init_calls == 0 and entry.retries == 0
        await ar.recheck(probe_timeout_s=0.2)
        assert not entry.still_dark

    _run(main())


def test_recheck_refreshes_why_when_a_name_resolves_but_the_light_stays_silent(fake_live):
    dark = _FakeDevice("dining-table", "Dining Table", "wled-8a3534.local",
                       destination=None, wled=_FakeWled(unreachable=True))
    _room(fake_live, dark)
    report = ar.record_from_live(ar.SOURCE_TAKE_BACK, {}, {"dining-table": "could not confirm live state: ValueError('WLED None: Failed to connect')"})
    entry = report.skipped["dining-table"]
    assert entry.kind == ar.KIND_UNRESOLVED

    async def main():
        # The name now resolves (the re-init sets a destination) but the
        # light still does not answer: the report moves from "did not
        # resolve" to "no answer from <ip>" — never a stale sentence.
        async def init():
            dark.init_calls += 1
            dark._destination = "192.168.40.77"
            dark.wled = _FakeWled(unreachable=True)
        dark.async_initialize = init
        await ar.recheck(probe_timeout_s=0.2)
        assert entry.still_dark
        assert entry.kind == ar.KIND_UNREACHABLE
        assert "192.168.40.77" in entry.why

    _run(main())


def test_recheck_is_a_noop_without_a_report_or_with_nothing_dark(fake_live):
    async def main():
        assert await ar.recheck() is None
        _room(fake_live, _FakeDevice("d", "D", "d", destination="d"))
        report = ar.record_from_live(ar.SOURCE_RESUME, {}, {})
        assert await ar.recheck() is report

    _run(main())


def test_reset_clears_state_for_the_next_test(fake_live):
    _room(fake_live, _FakeDevice("d", "D", "d", destination="d"))
    ar.record_from_live(ar.SOURCE_RESUME, {}, {"d": "could not confirm live state: x"})
    ar.reset()
    assert ar._report is None
    assert ar.status() is None
