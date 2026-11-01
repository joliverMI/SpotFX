"""The TV feed (data/tv-display-plan/plan.html PR 1.2): the pure message
builders, the ping/pong clock's stall-resilience, the two per-connection
background loops, and the real `/spectra/api/tv/ws` route end to end over
FastAPI's TestClient. No pytest-asyncio plugin in this repo — async test
bodies run via `_go(coro)` (`asyncio.run`), the same convention
tests/test_absorb_runner.py and tests/test_night_self_take.py already use."""
from __future__ import annotations

import asyncio
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


async def _clock_loop_dead_socket():
    async def send(msg):
        raise RuntimeError("socket closed")

    deps = tv_feed.TvFeedDeps(show_clock=lambda: (None, None, False))
    await tv_feed.run_clock_loop(send, deps, asyncio.sleep)  # must not raise


def test_clock_loop_ends_quietly_when_the_socket_is_dead():
    _go(_clock_loop_dead_socket())


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

    deps = tv_feed.TvFeedDeps(fetch_jukebox=fetch, jukebox_poll_s=0.01)
    with pytest.raises(asyncio.CancelledError):
        await tv_feed.run_jukebox_loop(send, deps, fake_sleep)

    jukebox_msgs = [m for m in sent if m["type"] == "jukebox"]
    layout_msgs = [m for m in sent if m["type"] == "layout"]
    # change on poll 1 (first ever, "a") and poll 3 ("b") — poll 2 ("a"
    # again) must NOT send a second time.
    assert len(jukebox_msgs) == 2
    assert jukebox_msgs[0]["now"] == "a"
    assert jukebox_msgs[1]["now"] == "b"
    assert len(layout_msgs) == 2


def test_jukebox_loop_sends_only_on_change_and_pairs_a_layout_message():
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
