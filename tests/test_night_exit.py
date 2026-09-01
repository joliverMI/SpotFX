"""THE HONEST EXIT — proven RED when it would be lying.

THE STANDARD UNDER TEST: "the setting is not the light". A report that
reads a mode field, or trusts a 2xx, or believes a house scene was fired,
can say a room is dark while a fixture is plainly on — which is exactly the
morning of 2026-09-01, when he woke to lit fixtures no record described as
lit.

SO THE BAR HERE IS THE INVERSE OF A NORMAL TEST: the important case is the
one where the claim is FALSE. A fixture is forced LIT at its own firmware
while the run has ended, and the report must refuse to call the room dark
and must name that fixture. A proof that can only pass when things are fine
would be decoration.

WHAT IS REAL IN THIS FILE: a real `fx.headless` render host with a real
rendering virtual, real `fx.utils.WLED` transport code (unmodified
production), and a real HTTP endpoint serving real WLED JSON. The only
thing standing in for his room is the room.
"""
from __future__ import annotations

import asyncio
import contextlib
import os

from fx.headless import silence_audio, start_headless_host
from fx.utils import WLED
from spectra.services import night_exit
from tests.test_night_power import FakeWledServer


def _run(coro):
    """ONE event loop per test, and the host is started INSIDE it. A host
    started on a loop that is then closed leaves its own tasks orphaned and
    the next `asyncio.run` never returns — the reason every headless test in
    this repo is shaped this way (tests/test_param_watchdog.py)."""
    return asyncio.run(coro)


async def _room(tmp_path, *, kind: str = "dummy", server=None):
    """A real render host with one real rendering virtual. When `server` is
    given the device is handed a REAL `fx.utils.WLED` transport pointed at
    it, so the exit report reads that fixture back over the wire exactly the
    way it reads his."""
    silence_audio()
    config_dir = str(tmp_path / "fx")
    os.makedirs(config_dir, exist_ok=True)
    host = await start_headless_host(
        config_dir, pixel_count=16, rows=1, device_id="strip",
        initial_effect={"type": "singleColor",
                        "config": {"color": "#ffffff", "brightness": 1.0}})
    device = host.devices.get("strip")
    # The KIND lives on the listing entry (`_entries`), which is where
    # `device_console` reports it and where `night_exit` reads it; the
    # driver's own `type` is a read-only property. What goes onto the driver
    # is the REAL `fx.utils.WLED` transport, so the read-back under test is
    # production code all the way to the socket.
    host._night_test_kind = kind if server is None else "wled"
    if server is not None:
        device.wled = WLED(server.address)
    return host


@contextlib.asynccontextmanager
async def room(tmp_path, **kwargs):
    """A started host that is ALWAYS shut down. A headless host left running
    keeps non-daemon render threads alive and the test process never exits —
    it reads as a hang rather than a failure, and it cost a real cycle here
    (tests/test_fx_write_seam.py's own `finally: await host.shutdown()` is
    the pattern)."""
    host = await _room(tmp_path, **kwargs)
    try:
        yield host
    finally:
        await host.shutdown()


def _entries(host):
    """The device listing shape `device_console.list_devices` produces."""
    return [{"id": d.id, "type": getattr(host, "_night_test_kind", "dummy"),
             "config": {"name": d.id}, "virtuals": ["strip"]}
            for d in host.devices.values()]


async def _build(host, *, run_ids=(), shielded=None, read_hue=None):
    return await night_exit.build(
        device_entries=_entries(host),
        devices_by_id={d.id: d for d in host.devices.values()},
        run_device_ids=set(run_ids),
        shielded_devices=dict(shielded or {}),
        host=host if read_hue is not None else None,
        read_hue=read_hue)


# ── RED WHEN LYING ─────────────────────────────────────────────────────────

def test_a_fixture_forced_lit_fails_the_dark_claim_and_is_named(tmp_path):
    """The whole point. The run has ended; the fixture it drove reads ON at
    its own firmware. The report must not say dark, and must name it."""
    async def main():
        with FakeWledServer(on=True, bri=200, live=True) as server:
            async with room(tmp_path, server=server) as host:
                return await _build(host, run_ids={"strip"})

    report = _run(main())
    assert report.dark == [], \
        "a lit fixture was reported dark — the exit report lied"
    assert report.emitting == ["strip"]
    fixture = report.fixtures[0]
    assert fixture.verdict == night_exit.VERDICT_EMITTING
    assert fixture.attribution == night_exit.BY_RUN
    assert report.problems and "strip" in report.problems[0]
    assert "78%" in fixture.why          # 200/255
    assert "realtime stream" in fixture.why
    assert "still lit" in report.summary


def test_the_same_fixture_switched_off_reads_dark(tmp_path):
    """The negative control for the test above — the instrument has to be
    able to say dark, or its refusal above proves nothing."""
    async def main():
        with FakeWledServer(on=False) as server:
            async with room(tmp_path, server=server) as host:
                return await _build(host, run_ids={"strip"})

    report = _run(main())
    assert report.dark == ["strip"]
    assert report.emitting == []
    assert report.problems == []
    assert "switched off" in report.fixtures[0].why


def test_on_at_zero_brightness_is_dark_because_it_emits_nothing(tmp_path):
    async def main():
        with FakeWledServer(on=True, bri=0) as server:
            async with room(tmp_path, server=server) as host:
                return await _build(host, run_ids={"strip"})

    report = _run(main())
    assert report.dark == ["strip"]
    assert "emits nothing" in report.fixtures[0].why


# ── UNREADABLE IS A THIRD THING, NEVER DARK ────────────────────────────────

def test_a_fixture_that_will_not_answer_is_unknown_not_dark(tmp_path):
    async def main():
        async with room(tmp_path) as host:
            host._night_test_kind = "wled"
            host.devices.get("strip").wled = WLED("127.0.0.1:1")   # deaf
            return await _build(host, run_ids={"strip"})

    report = _run(main())
    assert report.unknown == ["strip"]
    assert report.dark == []
    assert "an unread fixture is not a dark one" in report.fixtures[0].why


def test_a_fixture_with_no_control_channel_is_unknown_not_dark(tmp_path):
    """dummy / e131 / ddp / udp have nothing to ask. Reporting them dark
    would be assuming, which is the failure this file exists for."""
    async def main():
        async with room(tmp_path) as host:
            return await _build(host, run_ids={"strip"})

    report = _run(main())
    assert report.unknown == ["strip"]
    assert report.dark == []
    assert "reported unknown rather than assumed dark" in report.fixtures[0].why


# ── THE THREE ATTRIBUTIONS ─────────────────────────────────────────────────

def test_a_shield_exempt_fixture_still_lit_is_named_by_design(tmp_path):
    """His Dark mode never clamps the shielded ones — those were the lit
    sets he woke to on 2026-09-01. Lit for a stated reason, and NOT one of
    this seam's problems, but never silently passed over."""
    async def main():
        with FakeWledServer(on=True, bri=255) as server:
            async with room(tmp_path, server=server) as host:
                return await _build(host, run_ids=set(),
                                    shielded={"strip": ["strip"]})

    report = _run(main())
    fixture = report.fixtures[0]
    assert fixture.verdict == night_exit.VERDICT_EMITTING
    assert fixture.attribution == night_exit.BY_DESIGN
    assert fixture.shielded_via == ["strip"]
    assert report.problems == [], \
        "a by-design lit fixture was reported as this seam's problem"
    assert "lit by design" in report.summary


def test_a_lit_fixture_outside_the_run_and_outside_the_shield_is_named(tmp_path):
    """The house's own Dark Music envelope is Home Assistant's act. The
    captain's order: the envelope is not a substitute for checking, so a
    fixture the envelope was supposed to have darkened is named too."""
    async def main():
        with FakeWledServer(on=True, bri=128) as server:
            async with room(tmp_path, server=server) as host:
                return await _build(host, run_ids=set(), shielded={})

    report = _run(main())
    fixture = report.fixtures[0]
    assert fixture.attribution == night_exit.OUTSIDE_RUN
    assert "Home Assistant's act" in fixture.why
    assert report.emitting == ["strip"]


def test_the_shield_exemption_beats_the_run_attribution(tmp_path):
    """A fixture that is both in the run AND shielded is by design: Dark
    mode was never going to clamp it, so its being lit is not evidence the
    run failed to let go."""
    async def main():
        with FakeWledServer(on=True, bri=255) as server:
            async with room(tmp_path, server=server) as host:
                return await _build(host, run_ids={"strip"},
                                    shielded={"strip": ["strip"]})

    report = _run(main())
    assert report.fixtures[0].attribution == night_exit.BY_DESIGN
    assert report.problems == []


# ── HUE, READ AT THE BULB ──────────────────────────────────────────────────

def _hue_reader(rows):
    async def read_hue(_host):
        return rows
    return read_hue


def test_a_hue_bridge_with_one_bulb_on_is_emitting_and_names_it(tmp_path):
    async def main():
        async with room(tmp_path, kind="hue") as host:
            return await _build(host, run_ids={"strip"}, read_hue=_hue_reader([
            {"device_id": "strip", "light_id": "a", "name": "Sofa",
             "on": False, "reason": ""},
            {"device_id": "strip", "light_id": "b", "name": "Corner",
             "on": True, "reason": ""}]))

    report = _run(main())
    assert report.emitting == ["strip"]
    assert "Corner" in report.fixtures[0].why


def test_a_hue_bulb_that_could_not_be_read_keeps_it_unknown(tmp_path):
    async def main():
        async with room(tmp_path, kind="hue") as host:
            return await _build(host, run_ids={"strip"}, read_hue=_hue_reader([
            {"device_id": "strip", "light_id": "a", "name": "Sofa",
             "on": False, "reason": ""},
            {"device_id": "strip", "light_id": "b", "name": "Corner",
             "on": None, "reason": "the bridge did not answer"}]))

    report = _run(main())
    assert report.unknown == ["strip"]
    assert report.dark == []
    assert "not confirmed dark" in report.fixtures[0].why


def test_all_bulbs_off_at_the_bridge_is_dark(tmp_path):
    async def main():
        async with room(tmp_path, kind="hue") as host:
            return await _build(host, run_ids={"strip"}, read_hue=_hue_reader([
            {"device_id": "strip", "light_id": "a", "name": "Sofa",
             "on": False, "reason": ""}]))

    report = _run(main())
    assert report.dark == ["strip"]
    assert "at the bridge itself" in report.fixtures[0].why


def test_the_report_says_it_was_verified_at_the_light(tmp_path):
    async def main():
        with FakeWledServer(on=False) as server:
            async with room(tmp_path, server=server) as host:
                return await _build(host)

    assert _run(main()).as_dict()["verified_at_the_light"] is True
