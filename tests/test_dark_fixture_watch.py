"""THE DARK FIXTURE WATCH — proven against the state every other signal
called healthy.

THE STANDARD UNDER TEST, and it is the inverse of a normal one: the
important case is the one where the OLD answer was FINE. On 2026-08-15 his
`tv-backlight` reported `on=false` while SPECTRA streamed to it at ~54 fps
— the liveness endpoint 200-healthy, `activation_gaps` empty,
`devices[].online` true, frames flowing — and he found it BY EYE. So the
first test here reproduces that exact state and asserts, one by one, that
every pre-existing signal still says fine over it, before asserting that
the new watch names it. A proof that only ever exercised the new code would
be decoration: it would not show that the blind spot was real, and it would
not notice if the fix stopped being needed.

WHAT IS REAL IN THIS FILE: a real `fx.headless` render host with a real
rendering virtual and its real render thread, the real frame-freshness tap
the liveness endpoint serves, the real `LiveLights.read_emission` /
`probe_device_live` / `activation_gaps`, the unmodified production
`fx.utils.WLED` transport, and a real HTTP endpoint serving real WLED JSON.
The only thing standing in for his room is the room.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx.headless import silence_audio, start_headless_host
from fx.utils import WLED
from spectra.services import dark_fixture_watch as dfw
from spectra.services.live_host import LiveLights

#: His real TV backlight: a 560-pixel strip, the Living Room's only capture
#: carrier and the fixture both reports are about.
TV_BACKLIGHT_PIXELS = 560
#: The shipped threshold, read off the module rather than typed here.
MIN_READS_TO_RIPEN = dfw.MIN_BAD_READS


# ── the fixture that can go bad ────────────────────────────────────────────

class StubWled:
    """A real HTTP endpoint speaking real WLED JSON, whose fixture can be
    taken dark or off the network OUT OF BAND — the proof bar's own words —
    while SPECTRA keeps streaming at it.

    Deliberately a superset of tests/test_night_power.py's FakeWledServer
    rather than a reuse of it: this one has to be able to STOP ANSWERING
    (`reachable = False`) and to answer too slowly (`hang_s`), which are the
    two shapes of "gone" a stream cannot see, and it records every request
    so the never-writes claim can be checked rather than asserted."""

    def __init__(self, *, on: bool = True, bri: int = 214,
                 live: bool = True):
        self.state = {"on": on, "bri": bri}
        self.info = {"brand": "WLED", "live": live, "lip": "127.0.0.1",
                     "fps": 54}
        self.reachable = True
        self.hang_s = 0.0
        self.drop_state = 0
        self.requests: list[tuple[str, str]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def _send(self, body: dict):
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                outer.requests.append(("GET", self.path))
                if outer.hang_s:
                    time.sleep(outer.hang_s)
                if not outer.reachable:
                    # A fixture that has fallen off the network: the socket
                    # is answered by nobody. Closing without a response is
                    # the closest a live server can get.
                    self.close_connection = True
                    return
                if self.path.endswith("/json/state"):
                    if outer.drop_state > 0:
                        outer.drop_state -= 1
                        self.close_connection = True
                        return
                    return self._send(outer.state)
                if self.path.endswith("/json/info"):
                    return self._send(outer.info)
                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length) if length else b""
                outer.requests.append(("POST", self.path))
                return self._send(outer.state)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address = f"127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)

    def go_dark(self) -> None:
        """Switched OFF at the fixture — his 2026-08-15 state. It keeps
        answering, and keeps reporting that our realtime stream is
        arriving; it simply shows nothing."""
        self.state["on"] = False

    def lose_state_replies(self, count: int) -> None:
        """Drop the next `count` json/state replies while json/info keeps
        answering — one lost request at a time, which is what a controller
        under a write burst actually does."""
        self.drop_state = count

    def leave_the_network(self) -> None:
        """His 2026-09-06 state: gone, while we keep streaming at it."""
        self.reachable = False

    def writes(self) -> list[tuple[str, str]]:
        return [r for r in self.requests if r[0] != "GET"]

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


@contextlib.asynccontextmanager
async def streaming_room(tmp_path, stub):
    """A REAL render host driving a REAL virtual at his strip's pixel count,
    with the production `fx.utils.WLED` transport pointed at `stub` — i.e.
    SPECTRA genuinely streaming to a fixture that can go bad underneath her.

    The host is ALWAYS shut down: a headless host left running keeps
    non-daemon render threads alive and the test process never exits, which
    reads as a hang rather than a failure (tests/test_night_exit.py's own
    note)."""
    silence_audio()
    config_dir = str(tmp_path / "fx")
    os.makedirs(config_dir, exist_ok=True)
    host = await start_headless_host(
        config_dir, pixel_count=TV_BACKLIGHT_PIXELS, rows=1,
        device_id="tv-backlight",
        initial_effect={"type": "singleColor",
                        "config": {"color": "#ffffff", "brightness": 1.0}})
    device = host.devices.get("tv-backlight")
    # `type` is a read-only property over `_type` (fx/utils.py BaseRegistry),
    # and the production probe scopes itself to WLED devices — so the rig
    # presents a genuine one, carrying the real transport.
    device._type = "wled"
    device.wled = WLED(stub.address)
    lights = LiveLights()
    lights.host = host
    lights.expected_active_ids = {"tv-backlight"}
    lights.freshness.attach(host)
    try:
        # The render thread has to have flushed at least one frame before
        # this room is "streaming" at all — that is the precondition the
        # whole detection rests on, so it is waited for, not assumed.
        assert await lights.wait_fresh(timeout_s=5.0), "the rig never rendered"
        yield host, lights
    finally:
        lights.freshness.detach()
        await host.shutdown()


class Clock:
    """Wall time that the test advances by whole sweeps, so a 60 s fault
    threshold costs no wall-clock seconds. Seeded from the real clock so
    every age the status surfaces compute stays sane."""

    def __init__(self):
        self.now = time.time()

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float = dfw.SWEEP_INTERVAL_S) -> None:
        self.now += seconds


def deps_for(lights: LiveLights, clock: Clock, *, gate=lambda: None) -> dfw.Deps:
    return dfw.Deps(
        streaming_device_ids=lights.streaming_device_ids,
        read_emission=lights.read_emission,
        describe_device=lambda did: (did, "192.168.40.236"),
        gate=gate,
        clock=clock,
    )


async def sweep_until_ripe(deps: dfw.Deps, clock: Clock, *, sweeps: int = 4):
    """Drive enough sweeps to cross FAULT_AFTER_S at the production
    cadence, so what is proven is the SHIPPED threshold and not a number
    the test invented."""
    for _ in range(sweeps):
        await dfw.sweep(deps)
        clock.tick()


def _run(coro):
    """One event loop per test, host started inside it — the shape every
    headless test in this repo uses (tests/test_param_watchdog.py)."""
    return asyncio.run(coro)


# ── 1. the judgement, pure ─────────────────────────────────────────────────

def _read(**kw):
    from spectra.services.live_host import EmissionRead
    base = dict(device_id="tv-backlight", checkable=True, reachable=True,
                live=True, on=True, brightness=214, state_read=True)
    base.update(kw)
    return EmissionRead(**base)


def test_a_lit_fixture_taking_the_stream_is_not_a_fault():
    assert dfw.judge(_read()) is None


def test_the_four_kinds_of_dark_are_told_apart():
    assert dfw.judge(_read(reachable=False, live=None, on=None,
                           brightness=None, state_read=False,
                           error="ConnectionError()")) == dfw.KIND_UNREACHABLE
    assert dfw.judge(_read(live=False)) == dfw.KIND_NOT_RECEIVING
    assert dfw.judge(_read(on=False)) == dfw.KIND_SWITCHED_OFF
    assert dfw.judge(_read(brightness=0)) == dfw.KIND_BLACKED_OUT


def test_what_could_not_be_checked_is_never_counted_as_lit():
    """"We did not look" and "it is lit" are different facts — the same
    distinction night_exit draws between DARK and UNKNOWN. A fixture we
    cannot ask must never be convicted, and must never be absolved.
    judge() is the ONE rule for what a read means, so "no opinion" is
    proven there and nowhere else."""
    from spectra.services.live_host import EmissionRead
    unknown = EmissionRead(device_id="hue-1", checkable=False)
    assert dfw.judge(unknown) is None
    # Reachable, but the state read did not land: on/bri unknown, so no
    # accusation — and no absolution either, see the sweep test below.
    partial = _read(on=None, brightness=None, state_read=False)
    assert dfw.judge(partial) is None
    assert dfw.judge(_read()) is None
    assert dfw.judge(_read(on=False)) == dfw.KIND_SWITCHED_OFF


# ── 2. HIS ROOM: the state every other signal called healthy ───────────────

def test_his_2026_08_15_state_every_old_signal_says_fine_and_the_watch_names_it(
        tmp_path):
    """THE FOUNDING DEFECT, reproduced whole: a fixture switched OFF at its
    own firmware while SPECTRA streams to it. The first half of this test IS
    the RED — it asserts that each pre-existing signal reports health over
    exactly this state, which is why he had to notice by eye."""
    with StubWled(on=True, bri=214, live=True) as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                device = host.devices.get("tv-backlight")
                stub.go_dark()          # out of band: the WLED app, an HA
                                        # automation, its own timer

                # ── every pre-existing signal, over the dark fixture ──
                assert lights.fresh(), \
                    "frame freshness proves OUR loop pushed a frame — and it does"
                assert lights.activation_gaps() == {}, \
                    "the config-declared virtual came up exactly as asked"
                assert device.is_online() is True, (
                    "devices[].online never clears for a UDP fixture — and "
                    "until this build the liveness payload did not even call "
                    "the method, so it reported True unconditionally")
                assert await lights.probe_device_live("tv-backlight") is None, \
                    ("the activation probe asks only `live`, which is TRUE of a "
                     "switched-off fixture receiving realtime data")

                # ── the fixture's own account of itself ──
                read = await lights.read_emission("tv-backlight")
                assert read.reachable and read.live is True
                assert read.on is False
                assert dfw.judge(read) == dfw.KIND_SWITCHED_OFF

                # ── the watch, at the shipped cadence and threshold ──
                clock = Clock()
                deps = deps_for(lights, clock)
                await dfw.sweep(deps)
                assert dfw.faults() == [], \
                    "one bad read must never accuse a working light"
                clock.tick()
                await sweep_until_ripe(deps, clock, sweeps=3)

                named = dfw.faults()
                assert len(named) == 1, dfw.summary()
                fault = named[0]
                assert fault.device_id == "tv-backlight"
                assert fault.kind == dfw.KIND_SWITCHED_OFF
                assert "switched OFF" in fault.why
                assert "192.168.40.236" in fault.why
                assert fault.dark_for_s >= dfw.FAULT_AFTER_S
                # and it is on the surfaces that lied
                assert dfw.liveness_summary()["fault_count"] == 1
                assert "tv-backlight" in dfw.status()["summary"]

        _run(scenario())


def test_his_2026_09_06_state_the_fixture_leaves_the_network_under_stream(
        tmp_path):
    """The second report: streamed to, and simply gone. The take-back named
    that one because it happened AT activation; nothing in this codebase
    could notice it happening mid-show."""
    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                deps = deps_for(lights, clock)
                await sweep_until_ripe(deps, clock)
                assert dfw.faults() == [], "a healthy fixture was accused"

                stub.leave_the_network()
                await sweep_until_ripe(deps, clock)

                named = dfw.faults()
                assert len(named) == 1, dfw.summary()
                assert named[0].kind == dfw.KIND_UNREACHABLE
                assert "not answering" in named[0].why
                assert f"within {dfw.HTTP_TIMEOUT_S:g}s" in named[0].why
                assert "dark" not in named[0].why, (
                    "no reply proves no reply; darkness is an inference the "
                    "read does not support")
                assert "no answer" in named[0].reason

        _run(scenario())


def test_a_fixture_refusing_the_stream_and_one_at_zero_brightness(tmp_path):
    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                deps = deps_for(lights, clock)
                stub.info["live"] = False
                await sweep_until_ripe(deps, clock)
                assert [f.kind for f in dfw.faults()] == [dfw.KIND_NOT_RECEIVING]

                stub.info["live"] = True
                stub.state["bri"] = 0
                await sweep_until_ripe(deps, clock)
                assert [f.kind for f in dfw.faults()] == [dfw.KIND_BLACKED_OUT]

        _run(scenario())


def test_a_lit_fixture_is_never_accused_however_long_the_show_runs(tmp_path):
    """The negative control. Without it, a watch that named everything
    would pass every test above."""
    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                deps = deps_for(lights, clock)
                for _ in range(12):     # six minutes of show at 30 s sweeps
                    await dfw.sweep(deps)
                    clock.tick()
                assert dfw.faults() == []
                assert dfw.status()["faults_total"] == 0
                assert dfw.summary() == "1 streamed fixture(s) confirmed lit"

        _run(scenario())


def test_a_fixture_that_comes_back_clears_its_own_fault(tmp_path):
    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                deps = deps_for(lights, clock)
                stub.go_dark()
                await sweep_until_ripe(deps, clock)
                assert len(dfw.faults()) == 1

                stub.state["on"] = True        # he switched it back on
                await dfw.sweep(deps)
                assert dfw.faults() == []
                assert dfw.status()["fault_count"] == 0
                assert dfw.liveness_summary()["fault_count"] == 0
                cleared = [e for e in dfw.status()["recent"]
                           if e["event"] == "cleared"]
                assert cleared and cleared[-1]["device_id"] == "tv-backlight"

        _run(scenario())


def test_a_lost_state_reply_neither_clears_nor_resets_a_dark_fixture(tmp_path):
    """AN UNKNOWN READING NEVER CLEARS A NAMED FAULT. His fixtures routinely
    lose a single request under a write burst — the very condition this
    watch exists for — so a switched-off fixture whose json/state reply is
    dropped on some sweeps (json/info still answering) must still ripen on
    the SHIPPED 60 s / 3-read threshold, and once named must survive a lost
    reply rather than flap. Only a read that positively says lit clears
    it."""
    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                deps = deps_for(lights, clock)
                stub.go_dark()

                # Every other json/state reply is lost on the way to
                # ripening: reads 1 and 3 land, reads 2 and 4 do not.
                await dfw.sweep(deps)                       # dark, read 1
                clock.tick()
                stub.lose_state_replies(1)
                seen = await dfw.sweep(deps)                # lost: no opinion
                assert seen["unchecked"] == ["tv-backlight"]
                assert seen["uncheckable"] == []
                assert "tv-backlight" in dfw.liveness_summary()["watching"]
                suspect = dfw._suspects["tv-backlight"]
                assert suspect.reads == 1, "an unknown read advanced the clock"
                # The SENTENCE, not just the fields: the standing suspicion
                # stays in it across the lost reply, and a fixture we CAN
                # ask is never described as one we cannot.
                line = dfw.summary()
                assert line.startswith("0 streamed fixture(s) confirmed lit"), line
                assert "not yet named (tv-backlight)" in line, line
                assert "unchecked this sweep (tv-backlight)" in line, line
                assert "not checkable" not in line, line
                assert dfw.liveness_summary()["summary"] == line
                clock.tick()
                await dfw.sweep(deps)                       # dark, read 2
                clock.tick()
                stub.lose_state_replies(1)
                await dfw.sweep(deps)                       # lost: no opinion
                assert dfw._suspects["tv-backlight"] is suspect, \
                    "an unknown read reset the suspicion"
                clock.tick()
                await dfw.sweep(deps)                       # dark, read 3
                named = dfw.faults()
                assert len(named) == 1, (
                    "a fixture dropping one request in two never ripened: "
                    + dfw.summary())
                assert named[0].kind == dfw.KIND_SWITCHED_OFF
                assert named[0].reads == MIN_READS_TO_RIPEN
                assert named[0].dark_for_s >= dfw.FAULT_AFTER_S

                # Named, and the next reply is lost: the fault STANDS.
                clock.tick()
                stub.lose_state_replies(1)
                seen = await dfw.sweep(deps)
                assert seen["unchecked"] == ["tv-backlight"]
                assert len(dfw.faults()) == 1, "a lost reply cleared a named fault"
                assert dfw.faults()[0] is named[0]
                assert dfw.liveness_summary()["fault_count"] == 1
                assert not [e for e in dfw.status()["recent"]
                            if e["event"] == "cleared"]
                line = dfw.summary()
                assert line.startswith(
                    "1 fixture(s) dark or not answering while streamed"), line
                assert "unchecked this sweep (tv-backlight)" in line, line
                assert "not checkable" not in line, line

                # A lost json/info in the same sweep is a different reading:
                # unreachable, and it CONTINUES the same clock.
                clock.tick()
                stub.leave_the_network()
                await dfw.sweep(deps)
                assert dfw.faults()[0] is named[0]
                assert dfw.faults()[0].kind == dfw.KIND_UNREACHABLE
                stub.reachable = True

                # Only a read that positively says lit clears it.
                clock.tick()
                stub.state["on"] = True
                await dfw.sweep(deps)
                assert dfw.faults() == []
                cleared = [e for e in dfw.status()["recent"]
                           if e["event"] == "cleared"]
                assert cleared and cleared[-1]["how"] == "it reads lit again"
                assert stub.writes() == []

        _run(scenario())


def test_the_summary_never_calls_a_dark_reading_fixture_confirmed_lit(
        tmp_path):
    """The ripening window — a fixture reading dark before FAULT_AFTER_S has
    elapsed — is exactly when the first shipped summary said "1 streamed
    fixture(s) confirmed lit" over a read that had just said on=false. A
    dark read is accounted for from its first sweep and never folded into
    the lit count; "confirmed lit" means a read that positively said so."""
    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                deps = deps_for(lights, clock)
                await dfw.sweep(deps)
                assert dfw.summary() == "1 streamed fixture(s) confirmed lit"

                clock.tick()
                stub.go_dark()
                seen = await dfw.sweep(deps)
                assert dfw.faults() == [] and seen["dark"] == ["tv-backlight"]
                assert seen["lit"] == 0 and seen["checked"] == 1
                pending = dfw.summary()
                assert "0 streamed fixture(s) confirmed lit" in pending
                assert "1 streamed fixture(s) confirmed lit" not in pending
                assert "reading dark" in pending and "not yet named" in pending
                assert "tv-backlight" in pending
                assert dfw.liveness_summary()["summary"] == pending
                assert dfw.liveness_summary()["watching"] == ["tv-backlight"]

                clock.tick()
                await sweep_until_ripe(deps, clock, sweeps=3)
                assert len(dfw.faults()) == 1
                assert "not yet named" not in dfw.summary()
                assert "confirmed lit" not in dfw.summary()

                stub.state["on"] = True
                await dfw.sweep(deps)
                assert dfw.summary() == "1 streamed fixture(s) confirmed lit"

        _run(scenario())


def test_the_declared_http_budget_is_the_one_that_decides_unreachable(
        tmp_path):
    """A fixture answering slower than the vendored transport's own 0.5 s
    default but inside HTTP_TIMEOUT_S is REACHABLE and reads lit — the
    budget this module declares is the one handed to the transport, not a
    number that only bounded the outer wait and never bound. The vendored
    default driven on the same fixture is the control: it is what used to
    decide, and it says unreachable, which is what a busy controller taking
    the stream looked like to the first shipped version."""
    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                stub.hang_s = 0.8
                assert 0.5 < stub.hang_s < dfw.HTTP_TIMEOUT_S

                read = await lights.read_emission(
                    "tv-backlight", dfw.READ_TIMEOUT_S,
                    http_timeout_s=dfw.HTTP_TIMEOUT_S)
                assert read.reachable and read.live is True and read.on is True
                assert dfw.judge(read) is None

                control = await lights.read_emission(
                    "tv-backlight", dfw.READ_TIMEOUT_S, read_state=False)
                assert control.reachable is False, (
                    "the vendored default did not time out on this fixture — "
                    "the control proves nothing")
                assert control.state_read is False and control.on is None

                clock = Clock()
                deps = deps_for(lights, clock)
                seen = await dfw.sweep(deps)
                assert seen["dark"] == [] and seen["lit"] == 1
                assert dfw._suspects == {} and dfw.faults() == []
                assert dfw.summary() == "1 streamed fixture(s) confirmed lit"

        _run(scenario())


def test_a_reader_crash_is_an_unknown_reading_and_leaves_a_named_fault_standing(
        tmp_path):
    """The reader itself raising is the most unknown reading there is: it
    must neither convict a light on our own error nor absolve one. A named
    fault survives it untouched, and only a read that positively says lit
    clears it afterwards."""
    from dataclasses import replace

    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                deps = deps_for(lights, clock)
                stub.go_dark()
                await sweep_until_ripe(deps, clock)
                named = dfw.faults()
                assert len(named) == 1

                async def broken(device_id, timeout_s, **kw):
                    raise RuntimeError("reader bug")

                seen = await dfw.sweep(replace(deps, read_emission=broken))
                assert seen["unchecked"] == ["tv-backlight"]
                assert seen["uncheckable"] == []
                assert seen["dark"] == [] and seen["lit"] == 0
                assert dfw.faults() and dfw.faults()[0] is named[0], \
                    "a reader crash cleared a named fault"
                assert not [e for e in dfw.status()["recent"]
                            if e["event"] == "cleared"]
                assert dfw.liveness_summary()["fault_count"] == 1
                line = dfw.summary()
                assert "unchecked this sweep (tv-backlight)" in line, line
                assert "not checkable" not in line, line

                clock.tick()
                stub.state["on"] = True
                await dfw.sweep(deps)
                assert dfw.faults() == []
                assert stub.writes() == []

        _run(scenario())


def test_only_a_device_that_cannot_be_asked_is_called_not_checkable(tmp_path):
    """"Not checkable" is a property of the DEVICE — not a WLED, or a driver
    with no client — never a transient miss on a fixture we can ask (the
    lost-reply and reader-crash proofs above say "unchecked this sweep" for
    those). When a fixture we were watching stops being askable at all, the
    claim is dropped, because we can no longer make it, and the sentence
    says so in exactly those words."""
    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                deps = deps_for(lights, clock)
                stub.go_dark()
                await sweep_until_ripe(deps, clock)
                assert len(dfw.faults()) == 1

                host.devices.get("tv-backlight").wled = None
                seen = await dfw.sweep(deps)
                assert seen["uncheckable"] == ["tv-backlight"]
                assert seen["unchecked"] == [] and seen["lit"] == 0
                assert dfw.faults() == [] and dfw._suspects == {}
                cleared = [e for e in dfw.status()["recent"]
                           if e["event"] == "cleared"]
                assert cleared and cleared[-1]["how"] == \
                    "it can no longer be checked"
                line = dfw.summary()
                assert line == ("0 streamed fixture(s) confirmed lit, "
                                "1 not checkable (tv-backlight)"), line
                assert dfw.liveness_summary()["uncheckable"] == ["tv-backlight"]
                assert dfw.liveness_summary()["unchecked"] == []
                assert stub.writes() == []

        _run(scenario())


def test_it_writes_nothing_to_the_fixture_ever(tmp_path):
    """DETECTION, NOT CURE — structurally, not by intent. Across a whole run
    including a raised fault, the fixture must have received GETs and
    nothing else: no power-on, no brightness change, no realtime release."""
    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                deps = deps_for(lights, clock)
                stub.go_dark()
                await sweep_until_ripe(deps, clock, sweeps=6)
                assert len(dfw.faults()) == 1
                assert stub.writes() == [], \
                    f"the watch wrote to his fixture: {stub.writes()}"

        _run(scenario())


def test_it_only_ever_speaks_about_a_fixture_it_is_streaming_to(tmp_path):
    """The precondition that makes a dark light a FAULT. A fixture nobody is
    writing to is allowed to be off, and a virtual that stopped flushing is
    activation_gaps' business — so when the frames stop, the claim is
    dropped rather than left standing."""
    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                deps = deps_for(lights, clock)
                stub.go_dark()
                await sweep_until_ripe(deps, clock)
                assert len(dfw.faults()) == 1
                assert lights.streaming_device_ids() == {"tv-backlight"}

                # SPECTRA stops driving the virtual: no frames, no claim.
                host.virtuals.get("tv-backlight").deactivate()
                assert lights.streaming_device_ids() == set()
                await dfw.sweep(deps)
                assert dfw.faults() == []

        _run(scenario())


def test_it_stands_down_and_drops_every_suspicion_when_the_room_is_held(
        tmp_path):
    """A capture run, a mapping pass and a room effect all hold the room
    through flare_preview_hold and deliberately move fixture power and
    brightness. Reporting a fault there would be an accusation about our own
    behaviour."""
    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                held = {"why": None}
                deps = deps_for(lights, clock, gate=lambda: held["why"])
                stub.go_dark()
                await sweep_until_ripe(deps, clock)
                assert len(dfw.faults()) == 1

                held["why"] = "flare preview hold active"
                await dfw.sweep(deps)
                assert dfw.faults() == []
                assert dfw.status()["last_sweep"]["gate"] == \
                    "flare preview hold active"
                assert "standing down" in dfw.summary()
                assert stub.writes() == []

        _run(scenario())


def test_a_dead_fixture_does_not_stall_the_event_loop(tmp_path):
    """The read is off the loop on purpose. `fx.utils.WLED`'s methods are
    `async def` wrappers around BLOCKING `requests` calls, so awaiting one
    parks the whole SPECTRA event loop — the loop that drives the bridge
    poll, the trigger tick and every WS broadcast. A sweep over a fixture
    that answers too slowly is exactly when that would bite, so it is
    measured here rather than reasoned about."""
    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                stub.hang_s = 0.6      # longer than WLED's own request budget
                ticks = 0

                async def heartbeat():
                    nonlocal ticks
                    while True:
                        await asyncio.sleep(0.01)
                        ticks += 1

                beat = asyncio.create_task(heartbeat())
                started = time.monotonic()
                await lights.read_emission("tv-backlight")
                elapsed = time.monotonic() - started
                beat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await beat

                assert elapsed >= 0.1, \
                    "the rig did not actually make the read wait"
                # An on-loop blocking read scores ~0 ticks; an off-loop one
                # keeps the loop free for the whole wait.
                assert ticks >= elapsed * 50, (
                    f"the event loop was starved: {ticks} ticks in "
                    f"{elapsed:.2f}s")

        _run(scenario())


def test_the_harness_goes_red_on_the_defect_it_was_written_for(
        tmp_path, monkeypatch):
    """A proof that cannot fail on the defect it was written for is
    decoration. Re-run his 2026-08-15 state with the PRE-FIX judgement — the
    live-flag-only rule `probe_device_live` still applies, the only
    device-level question this codebase asked before this module existed —
    and nothing is named, however long the fixture stays dark. That is the
    world he was living in."""
    def old_rule(read):
        """What we asked before: is realtime data arriving? Nothing else."""
        if read is None or not getattr(read, "checkable", False):
            return None
        if not read.reachable:
            return dfw.KIND_UNREACHABLE
        return dfw.KIND_NOT_RECEIVING if read.live is False else None

    monkeypatch.setattr(dfw, "judge", old_rule)
    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                deps = deps_for(lights, clock)
                stub.go_dark()
                await sweep_until_ripe(deps, clock, sweeps=8)
                assert dfw.faults() == [], (
                    "the pre-fix rule named a switched-off fixture — then "
                    "this harness is not proving what it claims to prove")
                assert dfw.liveness_summary()["fault_count"] == 0

        _run(scenario())


# ── 3. the surfaces that reported healthy ──────────────────────────────────

def test_the_liveness_endpoint_names_it_and_still_does_not_call_it_unhealthy(
        tmp_path, monkeypatch):
    """Both halves matter. NAMED, because that payload said nothing over his
    dark light. NEVER `healthy`, because the systemd dead-man and the
    fleet's checker read that field, and a restart cannot switch a fixture
    back on while it certainly would darken the ones that work — the owner's
    own 2026-08-21 trade, applied again."""
    from fx import light_ownership as lo
    from spectra.api import ownership as ownership_api
    from spectra.services.live_host import live as live_singleton

    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                deps = deps_for(lights, clock)
                stub.go_dark()
                await sweep_until_ripe(deps, clock)
                assert len(dfw.faults()) == 1

                monkeypatch.setattr(
                    lo, "load",
                    lambda: lo.OwnershipRecord(owner=lo.SPECTRA))
                monkeypatch.setattr(live_singleton, "host", host)
                monkeypatch.setattr(live_singleton, "freshness",
                                    lights.freshness)
                monkeypatch.setattr(live_singleton, "expected_active_ids",
                                    {"tv-backlight"})

                resp = await ownership_api.get_liveness()
                body = json.loads(bytes(resp.body))

                assert body["dark_fixtures"]["fault_count"] == 1
                named = body["dark_fixtures"]["faults"][0]
                assert named["device_id"] == "tv-backlight"
                assert named["kind"] == dfw.KIND_SWITCHED_OFF
                assert "switched OFF" in named["why"]
                # …and every one of the old signals on this very payload
                # still reads healthy over the same fixture, which is the
                # whole reason the new key had to exist.
                assert body["healthy"] is True and resp.status_code == 200
                assert body["activation_gaps"] == {}
                assert body["devices"]["tv-backlight"]["online"] is True
                assert body["virtuals"]["tv-backlight"]["fresh"] is True

        _run(scenario())


def test_the_ownership_payload_and_engine_status_both_carry_it(
        tmp_path, monkeypatch):
    from fx import light_ownership as lo
    from spectra.api import ownership as ownership_api
    from spectra.services import engine

    with StubWled() as stub:
        async def scenario():
            async with streaming_room(tmp_path, stub) as (host, lights):
                clock = Clock()
                deps = deps_for(lights, clock)
                stub.leave_the_network()
                await sweep_until_ripe(deps, clock)
                assert len(dfw.faults()) == 1

                monkeypatch.setattr(
                    lo, "load",
                    lambda: lo.OwnershipRecord(owner=lo.SPECTRA))
                record = await ownership_api.get_ownership()
                assert record["dark_fixtures"]["fault_count"] == 1
                assert "tv-backlight" in record["dark_fixtures"]["summary"]

                status = engine.status()
                assert status["dark_fixtures"]["fault_count"] == 1

        _run(scenario())


def test_the_production_gate_stands_down_while_spectra_is_not_driving(
        monkeypatch):
    """The shipped gate, not a test's own: with no live stack there is
    nothing to comment on, and every sweep is a cheap no-op."""
    from spectra.services.live_host import live as live_singleton

    monkeypatch.setattr(live_singleton, "host", None)
    assert dfw._production_gate() == "live stack down"
    assert _run(dfw.sweep(dfw.production_deps()))["gate"] == "live stack down"
    assert dfw.faults() == []
