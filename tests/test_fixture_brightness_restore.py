"""HIS LEVEL COMES BACK EVEN WHEN THE CONTROLLER IS BUSY BEING PHOTOGRAPHED.

THE LIVE FINDING (2026-09-06, the sconce commissioning). `tv-backlight`
(.236) was taken to full for the capture and never put back:

    "tv-backlight was turned up to full for the capture and could NOT be
     put back to 84% (ValueError) — set it on the fixture itself."

It sat at 255 instead of his 214 until the firstmate restored it by hand,
and nothing else does it for him: the release path hands back the STREAM,
not the firmware brightness, so a failed restore strands a fixture bright
indefinitely.

THE CAUSE, reproduced here against the REAL transport rather than argued:
`fx.utils.WLED._wled_request`'s blanket 0.5s default is the budget the
brightness write runs at, and the restore gets exactly ONE shot at it — at
the end of a run that has just spent ~35s pouring its own capture stream
into that controller. .236 is the fixture `dark_fixture_watch` exists for:
a controller that saturates under its own stream. A read timeout there
surfaces as `ValueError: Failed to connect`, which is precisely the
`(ValueError)` in his sentence. The RAISE succeeded because it happens
before the stream has been hammering; the restore lands after.

What is proved here:

  * a fixture at a NON-FULL level (his 214) is taken to full for the
    capture and comes back to EXACTLY 214, not to full and not to
    "somewhere near it", over a controller that refuses the first writes;
  * the restore is CONFIRMED BY READ-BACK, never by a 2xx — the §64 rule
    this codebase already applies to the Hue release path, arriving here
    one fixture-type over;
  * a controller that genuinely never takes the write is still NAMED
    loudly, with his own level in the sentence, because a lounge left
    bright must be said out loud;
  * "written but never confirmed" is a DIFFERENT sentence from "never
    written" — sending him to set a fixture by hand that probably did land
    is noise, and the two facts are not the same fact;
  * the whole thing is bounded: a dead controller cannot make a run's
    ending run away with the clock.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from spectra.services import fixture_brightness as fb


# ── a controller that is busy being streamed at ────────────────────────────

class _Saturated:
    """A WLED helper whose control writes are refused while the capture
    stream has it saturated — .236's own measured behaviour, reduced to the
    two calls this path makes.

    `refuse_writes` is how many writes fail before it answers again; the
    ValueError is the exact class the real transport raises when its read
    timeout lapses (`fx.utils.WLED._wled_request`)."""

    def __init__(self, value=214, refuse_writes=0, refuse_reads=0):
        self.value = int(value)
        self.writes: list[int] = []
        self.reads = 0
        self.refuse_writes = refuse_writes
        self.refuse_reads = refuse_reads

    async def get_brightness(self):
        self.reads += 1
        if self.refuse_reads > 0:
            self.refuse_reads -= 1
            raise ValueError("WLED 10.0.0.236: Failed to connect")
        return self.value

    async def set_brightness(self, value):
        if self.refuse_writes > 0:
            self.refuse_writes -= 1
            raise ValueError("WLED 10.0.0.236: Failed to connect")
        self.writes.append(int(value))
        self.value = int(value)


class _Device:
    def __init__(self, device_id="tv-backlight", type_="wled", helper=None):
        self.id = device_id
        self.type = type_
        self.wled = helper


def _run(helper, body=None):
    dev = _Device(helper=helper)

    async def go():
        readings = await fb.read_all([dev])
        async with fb.owned([dev], readings) as owned:
            if body is not None:
                body()
        return owned

    return asyncio.run(go())


# ── 1. the defect itself ───────────────────────────────────────────────────

def test_his_level_comes_back_over_a_controller_that_refuses_the_first_write():
    """The founding case. One refused write is all it took on the night: the
    restore had no second attempt to make."""
    helper = _Saturated(value=214, refuse_writes=1)
    # the raise happens while the controller is still idle; the refusal
    # lands on the restore, which is exactly the night's shape
    dev = _Device(helper=helper)

    async def go():
        readings = await fb.read_all([dev])
        async with fb.owned([dev], readings) as owned:
            assert helper.value == fb.FULL       # full for the capture
            helper.refuse_writes = 1             # the stream saturates it
        return owned

    owned = asyncio.run(go())

    assert helper.value == 214, (
        "his own 84% must come back — the fixture was left at "
        f"{helper.value}")
    assert owned.restored == ["tv-backlight"]
    assert owned.problems == []


def test_it_keeps_trying_a_controller_that_is_slow_to_come_back():
    helper = _Saturated(value=214)
    dev = _Device(helper=helper)

    async def go():
        readings = await fb.read_all([dev])
        async with fb.owned([dev], readings) as owned:
            helper.refuse_writes = 2
        return owned

    owned = asyncio.run(go())
    assert helper.value == 214
    assert owned.restored == ["tv-backlight"]


# ── 2. a 2xx is not proof — the read-back is ───────────────────────────────

def test_the_restore_is_confirmed_by_reading_the_fixture_back():
    """A controller that ACCEPTS the write and does not carry it is the
    silent half of this failure: nothing in a 2xx says the value landed.
    Modelled here as a fixture that swallows the restore write."""

    class _Swallows(_Saturated):
        async def set_brightness(self, value):
            self.writes.append(int(value))
            # takes the raise, silently drops anything else — a write that
            # returns clean and changes nothing
            if int(value) == fb.FULL:
                self.value = fb.FULL

    helper = _Swallows(value=214)
    owned = _run(helper)

    assert helper.value == fb.FULL               # it never did land
    assert owned.restored == []
    # ... and it is SAID, rather than reported as a clean restore
    assert owned.problems, "a restore that never landed must be named"
    assert "84%" in owned.problems[0]
    assert "tv-backlight" in owned.problems[0]


def test_a_restore_that_lands_is_never_reported_as_a_problem():
    helper = _Saturated(value=214)
    owned = _run(helper)
    assert helper.value == 214
    assert owned.restored == ["tv-backlight"]
    assert owned.problems == []
    assert owned.raised == ["tv-backlight (84% -> 100%)"]


# ── 3. a genuine failure stays loud, and stays honest ──────────────────────

def test_a_controller_that_never_answers_is_named_with_his_own_level():
    """Readable at plan time, taken to full, then off the network for good —
    the case where his lounge really is left bright and he has to be told."""
    helper = _Saturated(value=214)
    dev = _Device(helper=helper)

    async def go():
        readings = await fb.read_all([dev])          # readable at plan time
        async with fb.owned([dev], readings) as owned:
            assert helper.value == fb.FULL
            helper.refuse_writes = 99                # gone, and stays gone
            helper.refuse_reads = 99
        return owned

    owned = asyncio.run(go())

    assert helper.value == fb.FULL                   # genuinely left bright

    assert owned.restored == []
    assert owned.problems
    assert "could NOT be put back to 84%" in owned.problems[0]
    assert "set it on the fixture itself" in owned.problems[0]


def test_written_but_unconfirmed_is_not_the_same_sentence_as_never_written():
    """Sending him to a fixture by hand that probably DID land is noise, and
    "we could not check" has never been allowed to render as "it is broken"
    in this codebase."""
    helper = _Saturated(value=214)
    dev = _Device(helper=helper)

    async def go():
        readings = await fb.read_all([dev])
        async with fb.owned([dev], readings) as owned:
            helper.refuse_reads = 99      # writes fine, cannot be asked
        return owned

    owned = asyncio.run(go())

    assert helper.value == 214            # the write really did land
    assert owned.problems, "an unconfirmed restore must still be said"
    said = owned.problems[0]
    assert "could NOT be put back" not in said, (
        "a write that was accepted must not be reported as never written")
    assert "tv-backlight" in said and "84%" in said


# ── 4. the run's own note never contradicts its problems ───────────────────

def test_the_note_never_claims_a_restore_the_problems_deny():
    """Every caller appends `note` to its NOTES and `problems` beside it. A
    note reading "and put your own brightness back afterwards" next to a
    problem saying it could not be is the confident wrong answer this whole
    extension exists to stop."""
    helper = _Saturated(value=214)
    dev = _Device(helper=helper)

    async def go():
        readings = await fb.read_all([dev])
        async with fb.owned([dev], readings) as owned:
            helper.refuse_writes = 99
            helper.refuse_reads = 99
        return owned

    owned = asyncio.run(go())
    assert owned.problems
    assert "put your own brightness back afterwards" not in owned.note
    assert "see the problems" in owned.note
    # ... and the ordinary run still says the ordinary thing
    clean = _run(_Saturated(value=214))
    assert clean.note.endswith("put your own brightness back afterwards.")


# ── 5. bounded: a dead controller cannot run away with the clock ───────────

def test_a_dead_controller_cannot_run_the_ending_away_with_the_clock():
    """The budget must bind on ATTEMPTS, not merely on the waits between
    them — a controller that eats a full transport timeout on every call is
    the case that costs real seconds, and it is the case a dead .236
    presents. Driven on a fake clock so the bound is proved rather than
    approximately observed."""
    now = [0.0]
    slow_write_s = 3.0          # what a transport timeout actually costs

    class _Dead:
        async def get_brightness(self):
            now[0] += slow_write_s
            raise ValueError("WLED 10.0.0.236: Failed to connect")

        async def set_brightness(self, value):
            now[0] += slow_write_s
            raise ValueError("WLED 10.0.0.236: Failed to connect")

    helper = _Dead()
    slept: list[float] = []

    async def sleep(s):
        now[0] += s
        slept.append(s)

    async def go():
        return await fb._deliver(helper, 214, fb.RESTORE_BUDGET_S,
                                 sleep=sleep, clock=lambda: now[0])

    got = asyncio.run(go())

    assert got.outcome == "failed"
    assert got.attempts >= 1
    # the stated ceiling: the budget, plus at most one attempt's own
    # transport time (a request in flight cannot be abandoned)
    assert now[0] <= fb.RESTORE_BUDGET_S + 2 * slow_write_s, (
        f"a dead controller spent {now[0]:.1f}s against a declared "
        f"{fb.RESTORE_BUDGET_S:g}s budget")
    assert sum(slept) <= fb.RESTORE_BUDGET_S


def test_a_controller_answering_instantly_still_gets_every_attempt():
    """The budget is a ceiling on a SLOW failure, never a reason to give up
    early on a fixture that is merely refusing."""
    helper = _Saturated(value=214, refuse_writes=99)
    got = asyncio.run(fb._deliver(helper, 214, fb.RESTORE_BUDGET_S))
    assert got.attempts == fb.DELIVER_ATTEMPTS


# ── 6. the REAL transport, against a REAL saturating controller ────────────

class _WledHandler(BaseHTTPRequestHandler):
    """A WLED json API that stops answering promptly once its own capture
    stream has it saturated — the measured .236 signature."""

    state = {"bri": 214, "on": True}
    slow_until = 0.0
    slow_for_s = 1.2
    posts: list[dict] = []

    def log_message(self, *a):                       # noqa: A003
        pass

    def _reply(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _stall(self):
        if time.time() < _WledHandler.slow_until:
            time.sleep(_WledHandler.slow_for_s)

    def do_GET(self):                                # noqa: N802
        self._stall()
        self._reply(dict(_WledHandler.state))

    def do_POST(self):                               # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        self._stall()
        _WledHandler.posts.append(body)
        _WledHandler.state.update(
            {k: v for k, v in body.items() if k in ("bri", "on")})
        self._reply({"success": True})


def test_the_real_transport_puts_his_level_back_over_a_saturated_controller():
    """END TO END on the production path: the real `fx.utils.WLED`, real
    HTTP, and a controller that answers slower than the transport's own
    shipped default for the whole stretch the restore lands in. This is the
    run that reproduced his sentence byte for byte."""
    from fx.utils import WLED

    _WledHandler.state = {"bri": 214, "on": True}
    _WledHandler.slow_until = 0.0
    _WledHandler.posts = []

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _WledHandler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        helper = WLED(f"127.0.0.1:{port}")
        dev = _Device(helper=helper)

        async def go():
            readings = await fb.read_all([dev])
            assert readings[0].value == 214
            async with fb.owned([dev], readings) as owned:
                assert _WledHandler.state["bri"] == fb.FULL
                # the capture stream saturates it for the rest of the run
                _WledHandler.slow_until = time.time() + 6
            return owned

        owned = asyncio.run(go())
    finally:
        srv.shutdown()
        srv.server_close()

    assert _WledHandler.state["bri"] == 214, (
        "the operator's own 84% must be back on the fixture, not full — it "
        f"was left at {_WledHandler.state['bri']}")
    assert owned.restored == ["tv-backlight"]
    assert owned.problems == []
