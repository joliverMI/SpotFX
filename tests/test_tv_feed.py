"""The TV feed (data/tv-display-plan/plan.html PR 1.2): the pure message
builders, the ping/pong clock's stall-resilience, the two per-connection
background loops, and the real `/spectra/api/tv/ws` route end to end over
FastAPI's TestClient. No pytest-asyncio plugin in this repo — async test
bodies run via `_go(coro)` (`asyncio.run`), the same convention
tests/test_absorb_runner.py and tests/test_night_self_take.py already use."""
from __future__ import annotations

import asyncio
import logging
import time

import pytest

from spectra.services import tv_feed


def _go(coro):
    return asyncio.run(coro)


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


# ── pure message builders ───────────────────────────────────────────────────

def test_director_layout_is_party_while_a_night_runs_else_attract():
    assert tv_feed.director_layout(True) == "party"
    assert tv_feed.director_layout(False) == "attract"
    assert tv_feed.director_layout(None) == "attract"


def test_resolve_layout_sleeps_past_the_10_minute_timeout_else_the_plain_split():
    assert tv_feed.resolve_layout(True, 0.0) == "party"
    assert tv_feed.resolve_layout(False, 0.0) == "attract"
    assert tv_feed.resolve_layout(False, tv_feed.SLEEP_TIMEOUT_S - 1) == "attract"
    assert tv_feed.resolve_layout(False, tv_feed.SLEEP_TIMEOUT_S) == "sleep"
    # sleep wins outright even if a night is somehow still marked running —
    # structurally impossible in production (a running night counts as
    # "active" every tick, resetting idle_s to 0), but the function itself
    # must not special-case it.
    assert tv_feed.resolve_layout(True, tv_feed.SLEEP_TIMEOUT_S) == "sleep"


def test_resolve_layout_falls_back_to_attract_once_a_running_boards_gone_stale():
    """Plan §2.2's second Attract trigger: 'a night runs but the screen has
    been unchanged a while' — independent of the idle/sleep clock (`idle_s`
    stays 0 the whole time a night is running, by construction)."""
    assert tv_feed.resolve_layout(True, 0.0, tv_feed.UNCHANGED_TIMEOUT_S - 1) == "party"
    assert tv_feed.resolve_layout(True, 0.0, tv_feed.UNCHANGED_TIMEOUT_S) == "attract"
    # it never fires while no night is running — that case is already
    # "attract" via director_layout, with nothing new to compose onto it.
    assert tv_feed.resolve_layout(False, 0.0, tv_feed.UNCHANGED_TIMEOUT_S) == "attract"
    assert tv_feed.resolve_layout(None, 0.0, tv_feed.UNCHANGED_TIMEOUT_S) == "attract"
    # sleep still wins outright over the unchanged-board fallback.
    assert tv_feed.resolve_layout(True, tv_feed.SLEEP_TIMEOUT_S, tv_feed.UNCHANGED_TIMEOUT_S) == "sleep"


def test_activity_tracker_resets_on_any_activity_and_accumulates_while_idle():
    tracker = tv_feed.ActivityTracker()
    assert tracker.idle_s(active=False, now_ms=0.0) == 0.0  # first call: never "already idle"
    assert tracker.idle_s(active=False, now_ms=5000.0) == 5.0
    assert tracker.idle_s(active=False, now_ms=600000.0) == 600.0
    # activity (a night running, or music playing) resets the clock
    assert tracker.idle_s(active=True, now_ms=600001.0) == 0.0
    assert tracker.idle_s(active=False, now_ms=603001.0) == 3.0


def test_config_message_carries_the_directors_pick_and_placeholders():
    msg = tv_feed.config_message({"screen_id": "lg"}, True, "build-42")
    assert msg == {"type": "config", "layout": "party", "look": None, "display_lead_ms": None,
                  "build_id": "build-42"}


def test_default_build_id_reads_the_real_manifest_or_is_honestly_none(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "TV_DIST", tmp_path / "no-such-tv-dist")
    assert tv_feed._default_build_id() is None

    built = tmp_path / "tv-dist"
    built.mkdir()
    (built / "build-id.txt").write_text("  1234567890  \n")
    monkeypatch.setattr(scfg, "TV_DIST", built)
    assert tv_feed._default_build_id() == "1234567890"


def test_default_show_clock_calls_the_real_bridge_singleton_without_raising():
    """Exercises the real, unmonkeypatched `_default_show_clock()` — the
    production default `run_clock_loop` actually calls. Before the fix for
    the round-1 finding (it read `bridge.effective_position_ms()` off the
    `bridge` MODULE rather than the `engine.bridge` singleton instance),
    this raised `AttributeError` every single call."""
    show, position, playing = tv_feed._default_show_clock()
    assert isinstance(playing, bool)
    assert show is None or isinstance(show, int)
    assert position is None or isinstance(position, int)


def test_default_night_http_url_reads_env_override_and_falls_back(monkeypatch):
    """Exercises the real, unmonkeypatched `_default_night_http_url()`
    against the real `bridge.default_http_url()` it delegates to."""
    monkeypatch.delenv("SPECTRA_BRIDGE_HTTP_URL", raising=False)
    monkeypatch.delenv("SPOTFX_PORT", raising=False)
    assert tv_feed._default_night_http_url() == "http://127.0.0.1:8000"

    monkeypatch.setenv("SPOTFX_PORT", "9123")
    assert tv_feed._default_night_http_url() == "http://127.0.0.1:9123"

    monkeypatch.setenv("SPECTRA_BRIDGE_HTTP_URL", "http://example.test:1234/")
    assert tv_feed._default_night_http_url() == "http://example.test:1234"


def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _serve_jukebox_tv(board: dict, port: int):
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/api/jukebox/tv")
    def _board():
        return board

    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    return server, task


async def _stop_server(server, task):
    server.should_exit = True
    await task


def test_default_fetch_jukebox_reads_the_real_tv_endpoint():
    """Exercises the real, unmonkeypatched `_default_fetch_jukebox()`
    against a real HTTP server on loopback — the production default
    `run_jukebox_loop` actually calls."""
    async def scenario():
        port = free_port()
        board = {"running": True, "now": {"title": "Song"}, "next": []}
        server, task = await _serve_jukebox_tv(board, port)
        try:
            result = await tv_feed._default_fetch_jukebox(f"http://127.0.0.1:{port}")
            assert result == board
        finally:
            await _stop_server(server, task)

    _go(scenario())


def test_default_fetch_jukebox_returns_none_when_unreachable():
    async def scenario():
        port = free_port()  # nothing is listening on this port
        result = await tv_feed._default_fetch_jukebox(f"http://127.0.0.1:{port}")
        assert result is None

    _go(scenario())


def test_jukebox_message_names_unreachable_rather_than_repeating_stale_data():
    assert tv_feed.jukebox_message(None) == {"type": "jukebox", "running": None, "reachable": False}
    board = {"running": True, "now": {"title": "x"}}
    assert tv_feed.jukebox_message(board) == {"type": "jukebox", "reachable": True, **board}


# ── the ping/pong clock's stall resilience ──────────────────────────────────

async def _offset_survives_stall():
    """The NTP-style offset — ((server_recv - client_send) + (server_send
    - client_recv)) / 2 — must land near zero (same process, same clock,
    loopback) even though the server deliberately stalls for 300 ms
    between recording server_recv_ms and server_send_ms. This is the
    literal acceptance check: "clock offset within +/-10ms on loopback
    with an injected 300ms server stall"."""
    async def stall():
        await asyncio.sleep(0.3)

    deps = tv_feed.TvFeedDeps(before_pong_send=stall)
    t_client_send = time.time() * 1000.0
    pong = await tv_feed.handle_ping({"type": "ping", "t": t_client_send}, deps)
    t_client_recv = time.time() * 1000.0

    assert pong["server_send_ms"] - pong["server_recv_ms"] >= 300.0  # the stall really happened
    offset_ms = ((pong["server_recv_ms"] - t_client_send)
                + (pong["server_send_ms"] - t_client_recv)) / 2.0
    assert abs(offset_ms) < 10.0, f"offset {offset_ms}ms exceeds the 10ms bound"


def test_offset_formula_survives_a_300ms_server_stall():
    _go(_offset_survives_stall())


async def _offset_formula_measures_a_real_stall():
    """A control proving the test above is measuring the real property,
    not a formula that happens to be insensitive to anything: the measured
    round-trip delay must actually grow with the stall length (proving the
    stall is real work being timed), while the OFFSET stays near zero
    either way — that is the property the formula is supposed to have."""
    async def stall_short():
        await asyncio.sleep(0.05)

    deps = tv_feed.TvFeedDeps(before_pong_send=stall_short)
    pong = await tv_feed.handle_ping({"type": "ping", "t": time.time() * 1000.0}, deps)
    delay_short = pong["server_send_ms"] - pong["server_recv_ms"]
    assert 40.0 <= delay_short < 300.0


def test_offset_formula_is_not_merely_insensitive_to_any_stall_length():
    _go(_offset_formula_measures_a_real_stall())


# ── the clock loop ───────────────────────────────────────────────────────────

async def _clock_loop_pushes_at_cadence():
    sent = []

    async def send(msg):
        sent.append(msg)
        if len(sent) >= 3:
            raise asyncio.CancelledError()

    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    deps = tv_feed.TvFeedDeps(
        show_clock=lambda: (12345, 12300, True),
        clock_push_s=0.25,
    )
    with pytest.raises(asyncio.CancelledError):
        await tv_feed.run_clock_loop(send, deps, fake_sleep)

    assert len(sent) == 3
    for msg in sent:
        assert msg["type"] == "clock"
        assert msg["show_clock_ms"] == 12345
        assert msg["is_playing"] is True
    assert sleeps == [0.25, 0.25]


def test_clock_loop_pushes_at_the_configured_cadence_then_stops_cleanly():
    _go(_clock_loop_pushes_at_cadence())


async def _clock_loop_dead_socket(exc):
    async def send(msg):
        raise exc

    deps = tv_feed.TvFeedDeps(show_clock=lambda: (None, None, False))
    await tv_feed.run_clock_loop(send, deps, asyncio.sleep)  # must not raise


@pytest.mark.parametrize("exc", [
    RuntimeError('Cannot call "send" once a close message has been sent.'),
    tv_feed.WebSocketDisconnect(code=1006),
])
def test_clock_loop_ends_quietly_when_the_socket_is_dead(exc, caplog):
    """A dead socket (Starlette's post-close RuntimeError, or the
    WebSocketDisconnect it raises for a mid-write OSError) is ROUTINE
    teardown on a wall-mounted kiosk — this must stay quiet, not log a
    warning on every ordinary disconnect."""
    with caplog.at_level(logging.WARNING, logger="spectra.services.tv_feed"):
        _go(_clock_loop_dead_socket(exc))
    assert caplog.records == []


async def _clock_loop_unexpected_error():
    async def send(msg):
        return None

    def broken_show_clock():
        raise AttributeError("module has no attribute 'effective_position_ms'")

    deps = tv_feed.TvFeedDeps(show_clock=broken_show_clock)
    await tv_feed.run_clock_loop(send, deps, asyncio.sleep)  # must not raise


def test_clock_loop_logs_a_warning_for_a_genuinely_unexpected_error(caplog):
    """Unlike the dead-socket case above, a bug in `deps.show_clock()`
    (the exact round-1 AttributeError class) must still surface loudly —
    this is the signal the round-2 logging fix exists to preserve."""
    with caplog.at_level(logging.WARNING, logger="spectra.services.tv_feed"):
        _go(_clock_loop_unexpected_error())
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.records[0].exc_info is not None


# ── the jukebox relay loop ───────────────────────────────────────────────────

async def _jukebox_loop_sends_only_on_change():
    boards = [{"running": True, "now": "a"}, {"running": True, "now": "a"}, {"running": True, "now": "b"}]
    calls = {"n": 0}

    async def fetch(url):
        i = min(calls["n"], len(boards) - 1)
        calls["n"] += 1
        return boards[i]

    sent = []
    stop_after = 3

    async def send(msg):
        sent.append(msg)

    async def fake_sleep(s):
        if calls["n"] >= stop_after:
            raise asyncio.CancelledError()

    deps = tv_feed.TvFeedDeps(fetch_jukebox=fetch, jukebox_poll_s=0.01,
                              show_clock=lambda: (None, None, False))
    with pytest.raises(asyncio.CancelledError):
        await tv_feed.run_jukebox_loop(send, deps, fake_sleep)

    jukebox_msgs = [m for m in sent if m["type"] == "jukebox"]
    layout_msgs = [m for m in sent if m["type"] == "layout"]
    # the BOARD changes on poll 1 (first ever, "a") and poll 3 ("b") —
    # poll 2 ("a" again) must NOT send a second jukebox message.
    assert len(jukebox_msgs) == 2
    assert jukebox_msgs[0]["now"] == "a"
    assert jukebox_msgs[1]["now"] == "b"
    # the LAYOUT never changes across all three polls (running=True
    # throughout -> "party" the whole time), so it's sent exactly ONCE —
    # layout is decoupled from the board's own change (PR 1.5's rework,
    # needed so sleep can be detected during a stretch with no board
    # change at all).
    assert layout_msgs == [{"type": "layout", "layout": "party"}]


def test_jukebox_loop_sends_only_on_board_change_layout_only_on_layout_change():
    _go(_jukebox_loop_sends_only_on_change())


async def _jukebox_loop_names_unreachable():
    async def fetch(url):
        return None

    sent = []

    async def send(msg):
        sent.append(msg)

    async def fake_sleep(s):
        raise asyncio.CancelledError()

    deps = tv_feed.TvFeedDeps(fetch_jukebox=fetch)
    with pytest.raises(asyncio.CancelledError):
        await tv_feed.run_jukebox_loop(send, deps, fake_sleep)

    jukebox_msgs = [m for m in sent if m["type"] == "jukebox"]
    assert jukebox_msgs == [{"type": "jukebox", "running": None, "reachable": False}]


def test_jukebox_loop_names_unreachable_distinctly_from_board_off():
    _go(_jukebox_loop_names_unreachable())


async def _jukebox_loop_falls_asleep_after_the_timeout():
    """A real idle-time simulation (a fake clock advancing by whole
    minutes per poll, never real sleeping) proving the loop actually
    reaches "sleep" once ActivityTracker's own 10-minute timeout is
    crossed — not just that resolve_layout the pure function can return
    it in isolation."""
    async def fetch(url):
        return {"running": False}

    clock = {"t": 0.0}

    async def now_ms():
        return clock["t"]

    tracker = tv_feed.ActivityTracker()
    sent = []
    polls = {"n": 0}

    async def send(msg):
        sent.append(msg)

    async def fake_sleep(s):
        polls["n"] += 1
        clock["t"] += 120_000.0  # 2 simulated minutes per poll
        if polls["n"] >= 6:  # 6 * 2min = 12 simulated minutes, past the 10min timeout
            raise asyncio.CancelledError()

    deps = tv_feed.TvFeedDeps(fetch_jukebox=fetch, show_clock=lambda: (None, None, False),
                              now_ms=now_ms, idle_s=tracker.idle_s)
    with pytest.raises(asyncio.CancelledError):
        await tv_feed.run_jukebox_loop(send, deps, fake_sleep)

    layouts = [m["layout"] for m in sent if m["type"] == "layout"]
    assert layouts == ["attract", "sleep"]


def test_jukebox_loop_falls_asleep_after_the_idle_timeout():
    _go(_jukebox_loop_falls_asleep_after_the_timeout())


async def _jukebox_loop_falls_back_to_attract_when_a_running_boards_gone_stale():
    """A real staleness simulation (a fake clock, never real sleeping),
    the plan §2.2 trigger: a RUNNING night whose relayed board stays
    unchanged past UNCHANGED_TIMEOUT_S falls back to "attract" — distinct
    from, and never confused with, the idle/sleep clock above (`running`
    stays True throughout, so ActivityTracker's own idle_s is pinned at 0
    the whole time, never reaching SLEEP_TIMEOUT_S; a fresh, non-shared
    `ActivityTracker` is injected for the board clock so this test can't
    pollute — or be polluted by — the module's own process-wide
    singleton). Then, on the very next poll where the board actually
    changes, the layout returns to "party" immediately — proving the
    staleness clock resets on a real change rather than merely composing
    correctly in resolve_layout isolation."""
    board = {"running": True, "now": {"up": 1}}

    async def fetch(url):
        return dict(board)

    clock = {"t": 0.0}

    async def now_ms():
        return clock["t"]

    tracker = tv_feed.ActivityTracker()
    sent = []
    polls = {"n": 0}

    async def send(msg):
        sent.append(msg)

    async def fake_sleep(s):
        polls["n"] += 1
        clock["t"] += 60_000.0  # 1 simulated minute per poll
        if polls["n"] == 5:
            # the board changes partway through the stale stretch — its
            # effect is observed on the NEXT iteration's fetch, poll 6.
            board["now"] = {"up": 2}
        if polls["n"] >= 6:
            raise asyncio.CancelledError()

    deps = tv_feed.TvFeedDeps(fetch_jukebox=fetch, show_clock=lambda: (None, None, False),
                              now_ms=now_ms, board_unchanged_s=tracker.idle_s)
    with pytest.raises(asyncio.CancelledError):
        await tv_feed.run_jukebox_loop(send, deps, fake_sleep)

    layouts = [m["layout"] for m in sent if m["type"] == "layout"]
    # poll 1 (t=0s): first-ever fetch, counts as a change -> party.
    # polls 2-3 (t=60s, 120s): unchanged, still under the 180s timeout -> party.
    # poll 4 (t=180s): unchanged for exactly 180s -> attract.
    # poll 5 (t=240s): the board is still the OLD value here (the mutation
    #   happens after this iteration's fetch, inside fake_sleep) -> still attract.
    # poll 6 (t=300s): the board has now changed -> resets to party at once.
    assert layouts == ["party", "attract", "party"]


def test_jukebox_loop_falls_back_to_attract_when_a_running_boards_gone_stale_then_resets_on_change():
    _go(_jukebox_loop_falls_back_to_attract_when_a_running_boards_gone_stale())


async def _jukebox_loop_dead_socket(exc):
    async def fetch(url):
        return {"running": True}

    async def send(msg):
        raise exc

    deps = tv_feed.TvFeedDeps(fetch_jukebox=fetch)
    await tv_feed.run_jukebox_loop(send, deps, asyncio.sleep)  # must not raise


@pytest.mark.parametrize("exc", [
    RuntimeError('Cannot call "send" once a close message has been sent.'),
    tv_feed.WebSocketDisconnect(code=1006),
])
def test_jukebox_loop_ends_quietly_when_the_socket_is_dead(exc, caplog):
    with caplog.at_level(logging.WARNING, logger="spectra.services.tv_feed"):
        _go(_jukebox_loop_dead_socket(exc))
    assert caplog.records == []


async def _jukebox_loop_unexpected_error():
    def broken_http_url():
        raise AttributeError("module has no attribute 'default_http_url'")

    async def send(msg):
        return None

    deps = tv_feed.TvFeedDeps(http_url=broken_http_url)
    await tv_feed.run_jukebox_loop(send, deps, asyncio.sleep)  # must not raise


def test_jukebox_loop_logs_a_warning_for_a_genuinely_unexpected_error(caplog):
    with caplog.at_level(logging.WARNING, logger="spectra.services.tv_feed"):
        _go(_jukebox_loop_unexpected_error())
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.records[0].exc_info is not None


async def _vote_reaches_relay_within_bound():
    """Real time, the production poll cadence (JUKEBOX_POLL_S == 1.0):
    a change appearing between two polls is picked up by the very next
    one, so the worst case is one poll interval plus negligible send
    time — comfortably under the plan's own 1.5 s acceptance bound."""
    state = {"board": {"running": True, "now": {"up": 1}}}

    async def fetch(url):
        return dict(state["board"])

    sent = []

    async def send(msg):
        sent.append((time.monotonic(), msg))

    deps = tv_feed.TvFeedDeps(fetch_jukebox=fetch, jukebox_poll_s=tv_feed.JUKEBOX_POLL_S)
    task = asyncio.create_task(tv_feed.run_jukebox_loop(send, deps, asyncio.sleep))
    await asyncio.sleep(0.2)  # let the first (unconditional) send land

    changed_at = time.monotonic()
    state["board"] = {"running": True, "now": {"up": 2}}

    deadline = time.monotonic() + 1.5
    seen_at = None
    while time.monotonic() < deadline:
        for (t, msg) in sent:
            if msg.get("type") == "jukebox" and msg.get("now", {}).get("up") == 2:
                seen_at = t
                break
        if seen_at is not None:
            break
        await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert seen_at is not None, "the vote never reached the relay"
    assert seen_at - changed_at <= 1.5


def test_a_vote_reaches_the_relay_within_the_plans_1point5s_bound():
    _go(_vote_reaches_relay_within_bound())


# ── the real route, end to end ───────────────────────────────────────────────

@pytest.fixture
def fast_deps(monkeypatch):
    board = {"running": True, "now": {"title": "Dancing Queen", "up": 3, "down": 0},
             "board": {"songs": []}, "settings": {"board_on_tv": True}}

    async def fetch(url):
        return dict(board)

    deps = tv_feed.TvFeedDeps(fetch_jukebox=fetch, clock_push_s=0.05, jukebox_poll_s=0.05,
                              show_clock=lambda: (5000, 4950, True), build_id=lambda: None)
    monkeypatch.setattr(tv_feed, "production_deps", lambda: deps)
    return board


class _FakeTvWebSocket:
    """Minimal stand-in for Starlette's `WebSocket`, driving the real
    `tv_ws()` dispatch loop directly (not through TestClient, which has no
    way to force a `send_json` to raise mid-round-trip). `_send_exc` fires
    on the reply to the ping specifically, simulating a TV connection
    ending while a ping round-trip is in flight."""

    def __init__(self, send_exc):
        self._send_exc = send_exc
        self._recv_calls = 0

    async def accept(self):
        pass

    async def receive_json(self):
        self._recv_calls += 1
        if self._recv_calls == 1:
            return {"kind": "tv"}
        if self._recv_calls == 2:
            return {"type": "ping", "t": 0.0}
        await asyncio.sleep(999)

    async def send_json(self, msg):
        if msg.get("type") == "pong":
            raise self._send_exc

    async def close(self):
        pass


async def _dispatch_loop_dead_socket(exc, fast_deps_obj):
    from spectra.api import tv_feed as tv_feed_api

    ws = _FakeTvWebSocket(exc)
    await tv_feed_api.tv_ws(ws)  # must not raise


@pytest.mark.parametrize("exc", [
    RuntimeError('Cannot call "send" once a close message has been sent.'),
    tv_feed.WebSocketDisconnect(code=1006),
])
def test_dispatch_loop_ends_quietly_when_the_socket_is_dead(exc, caplog, fast_deps):
    """The router's own ping-dispatch loop (`tv_ws()` in
    spectra/api/tv_feed.py) must stay as quiet about a dead socket as the
    two background loops already are (see the same-shaped tests above for
    `run_clock_loop`/`run_jukebox_loop`) — a TV connection ending mid-ping
    (a deploy restart, an ordinary reconnect race) is routine teardown,
    not a bug to log at WARNING."""
    with caplog.at_level(logging.WARNING, logger="spectra.api.tv_feed"):
        _go(_dispatch_loop_dead_socket(exc, fast_deps))
    assert caplog.records == []


def test_dispatch_loop_logs_a_warning_for_a_genuinely_unexpected_error(caplog, fast_deps):
    """Unlike the dead-socket case above, a genuinely unexpected error from
    the dispatch loop must still surface loudly."""
    from spectra.api import tv_feed as tv_feed_api

    class _BrokenWebSocket(_FakeTvWebSocket):
        async def receive_json(self):
            self._recv_calls += 1
            if self._recv_calls == 1:
                return {"kind": "tv"}
            raise AttributeError("boom")

    with caplog.at_level(logging.WARNING, logger="spectra.api.tv_feed"):
        _go(tv_feed_api.tv_ws(_BrokenWebSocket(RuntimeError("unused"))))
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.records[0].exc_info is not None


def test_route_hello_config_ping_pong_clock_jukebox_end_to_end(fast_deps):
    client = _client()
    with client.websocket_connect("/api/tv/ws") as ws:
        ws.send_json({"type": "hello", "screen_id": "lg-c4", "webgl2": True, "build_id": "123"})
        config = ws.receive_json()
        assert config == {"type": "config", "layout": "party", "look": None, "display_lead_ms": None,
                          "build_id": None}

        ws.send_json({"type": "ping", "t": time.time() * 1000.0})

        seen_types = set()
        pong = None
        for _ in range(30):
            msg = ws.receive_json()
            seen_types.add(msg["type"])
            if msg["type"] == "pong":
                pong = msg
            if {"pong", "clock", "jukebox"} <= seen_types:
                break
        assert pong is not None
        assert pong["server_recv_ms"] <= pong["server_send_ms"]
        assert "clock" in seen_types
        assert "jukebox" in seen_types
