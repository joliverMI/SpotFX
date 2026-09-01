"""THE NIGHT RUN'S POWER OWNERSHIP, and the two vendored WLED calls it is
the first caller of.

`fx/VENDOR.md` #30: `WLED.get_power_state` and `WLED.set_power_state` had no
caller anywhere in the fork and both were broken — one awaited a subscript
of a coroutine, the other form-encoded its body and built a double-slashed
URL. This file drives the REAL `fx.utils.WLED` against a REAL HTTP server
serving real WLED JSON, so it asserts the WIRE (a JSON body, no `//json`),
not a mock's opinion of it.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fx.utils import WLED
from spectra.services import night_power


class FakeWledServer:
    """A real HTTP endpoint speaking real WLED JSON, recording every request
    line and body exactly as it arrived."""

    def __init__(self, on: bool = True, bri: int = 255, live: bool = False):
        self.state = {"on": on, "bri": bri}
        self.info = {"brand": "WLED", "live": live, "lip": ""}
        self.requests: list[tuple[str, str, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):        # keep the test output clean
                pass

            def _send(self, body: dict):
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                outer.requests.append(("GET", self.path, {}))
                if self.path.endswith("/json/state"):
                    return self._send(outer.state)
                if self.path.endswith("/json/info"):
                    return self._send(outer.info)
                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode() or "{}")
                except Exception:
                    body = {"__unparsed__": raw.decode(errors="replace")}
                outer.requests.append(("POST", self.path, body))
                if isinstance(body, dict):
                    outer.state.update(
                        {k: v for k, v in body.items() if k in ("on", "bri")})
                return self._send(outer.state)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address = (f"127.0.0.1:{self._server.server_address[1]}")
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


class FakeDevice:
    def __init__(self, device_id: str, wled=None, kind: str = "wled"):
        self.id = device_id
        self.type = kind
        if wled is not None:
            self.wled = wled


# ── the vendored transport (fx/VENDOR.md #30) ──────────────────────────────

def test_get_power_state_reads_on_off_rather_than_raising():
    """Upstream did `await self.get_state()["on"]` — subscripting the
    COROUTINE, a TypeError on the first call ever made."""
    with FakeWledServer(on=False) as server:
        wled = WLED(server.address)
        assert asyncio.run(wled.get_power_state()) is False
        server.state["on"] = True
        assert asyncio.run(wled.get_power_state()) is True


def test_set_power_state_sends_a_json_body_to_a_singly_slashed_path():
    """Both of `set_brightness`' transport bugs (#27) were present here:
    `data=` form-encodes where WLED's JSON API needs JSON, and the leading
    slash builds `http://ip//json/state`."""
    with FakeWledServer(on=False) as server:
        asyncio.run(WLED(server.address).set_power_state(True))
    posts = [r for r in server.requests if r[0] == "POST"]
    assert posts, "the power write never reached the fixture"
    method, path, body = posts[-1]
    assert path == "/json/state", f"double-slashed path: {path!r}"
    assert body == {"on": True}, f"not a JSON body: {body!r}"
    assert server.state["on"] is True


# ── reading ────────────────────────────────────────────────────────────────

def test_a_non_wled_fixture_is_not_applicable_never_a_fabricated_on():
    """`fixture_brightness`' rule, one axis over: a made-up reading makes an
    unguarded fixture look guarded."""
    reading = asyncio.run(night_power.read_one(FakeDevice("hue-1", kind="hue")))
    assert reading.state == night_power.STATE_NOT_APPLICABLE
    assert reading.on is None
    assert reading.off is False
    assert "hue" in reading.reason


def test_a_fixture_that_will_not_answer_is_unreadable_not_off():
    class Deaf:
        async def get_power_state(self):
            raise OSError("no route to host")

    reading = asyncio.run(night_power.read_one(FakeDevice("wled-1", Deaf())))
    assert reading.state == night_power.STATE_UNREADABLE
    assert reading.on is None
    assert reading.off is False


# ── owning ─────────────────────────────────────────────────────────────────

def test_owned_turns_an_off_fixture_on_and_puts_the_switch_back():
    with FakeWledServer(on=False) as server:
        device = FakeDevice("strip", WLED(server.address))

        async def go():
            async with night_power.owned([device]) as result:
                assert server.state["on"] is True, \
                    "the fixture was not lit for the captures"
                return result

        result = asyncio.run(go())
    assert result.turned_on == ["strip"]
    assert result.restored == ["strip"]
    assert result.actions["strip"] == "turned_on"
    assert result.found["strip"] is False
    assert server.state["on"] is False, \
        "his switch was not put back — the run left a fixture on"
    assert not result.problems


def test_a_fixture_already_on_is_never_written_to_and_never_restored():
    with FakeWledServer(on=True) as server:
        device = FakeDevice("strip", WLED(server.address))

        async def go():
            async with night_power.owned([device]) as result:
                return result

        result = asyncio.run(go())
    assert result.actions["strip"] == "already_on"
    assert result.turned_on == []
    assert [r for r in server.requests if r[0] == "POST"] == [], \
        "a fixture already on was written to anyway"


def test_the_switch_goes_back_even_when_the_night_raises():
    with FakeWledServer(on=False) as server:
        device = FakeDevice("strip", WLED(server.address))

        async def go():
            async with night_power.owned([device]):
                raise RuntimeError("the queue blew up")

        with pytest.raises(RuntimeError):
            asyncio.run(go())
    assert server.state["on"] is False, \
        "a failed night left his fixture switched on"


def test_a_power_on_that_does_not_take_is_named_not_counted_as_lit():
    """A returning write call is never evidence (fx/VENDOR.md #29). The
    fixture accepts the POST and stays off; the run must SAY so rather than
    spend the night photographing an unlit strip."""
    class Stubborn:
        def __init__(self):
            self.writes = 0

        async def get_power_state(self):
            return False

        async def set_power_state(self, state):
            self.writes += 1          # accepted, and nothing happens

    helper = Stubborn()
    device = FakeDevice("strip", helper)

    async def go():
        async with night_power.owned([device]) as result:
            return result

    result = asyncio.run(go())
    assert helper.writes == 1
    assert result.actions["strip"] == "failed"
    assert result.turned_on == []
    assert any("could NOT be turned on" in p for p in result.problems)


def test_a_restore_that_fails_is_named_rather_than_swallowed():
    class OneWay:
        def __init__(self):
            self.on = False

        async def get_power_state(self):
            return self.on

        async def set_power_state(self, state):
            if not state:
                raise OSError("the fixture stopped answering")
            self.on = True

    device = FakeDevice("strip", OneWay())

    async def go():
        async with night_power.owned([device]) as result:
            return result

    result = asyncio.run(go())
    assert result.restored == []
    assert any("could NOT be switched back off" in p for p in result.problems)
