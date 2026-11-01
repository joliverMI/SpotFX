"""THE TV FEED (data/tv-display-plan/plan.html PR 1.2) — one WebSocket,
`/spectra/api/tv/ws`, carrying everything the TV app shell (PR 1.1) needs
that a static build can't: the hello/config handshake, an NTP-style
ping/pong clock, a 4 Hz show-clock anchor, the layout director's pick, and
a relay of SpotFX's own Jukebox board.

WHY CLIENT-INITIATED PING. The plan's own architecture table puts it as
"client time -> server receive and send times" — the TV asks, the server
answers with its own two timestamps, and the TV does the NTP arithmetic
(spectra/web/src/tv/clock.ts). This is the opposite direction from
`av_sync_session.ClockMap` (server-initiated, built for a phone filming a
fixture) — deliberately not reused here: a TV is a passive display that
should decide its own ping cadence and survive a reconnect without the
server tracking a per-client schedule.

WHY THE SERVER SIDE CANNOT JUST TIMESTAMP ONCE. The classic 4-timestamp
NTP formula — `offset = ((server_recv - client_send) + (server_send -
client_recv)) / 2` — is specifically resistant to a PROCESSING delay
between `server_recv` and `server_send` (SPECTRA's event loop is known to
stall; AGENTS.md's §7.1 note on the preview stream is the standing
evidence): the stall shows up as added round-trip delay, never as skew,
PROVIDED both timestamps are taken as close to the actual recv/send as
possible. `handle_ping`'s own `before_pong_send` hook exists so a test can
PROVE that resistance by injecting a real delay there, rather than trusting
the formula by inspection.

THE JUKEBOX RELAY READS SPOTFX'S EXISTING `GET /api/jukebox/board`
(PR 466), NOT the leaner purpose-built `/api/jukebox/tv` the plan's own
row 1.3 adds — this PR is sequenced before that endpoint exists. `run_
jukebox_loop` is written against `TvFeedDeps.fetch_jukebox`, a single
swappable seam, so 1.3's own PR is a one-line change (point it at the new
endpoint) rather than a second relay implementation. `running` — whether a
night is playing right now — is read FROM that same fetched payload (the
board endpoint already carries it), not from a second call: polling it
separately to decide whether to poll it is circular, and SpotFX's own
board read is already a lean, no-Spotify-call read (board.py's own
docstring), so polling it every second regardless of state is cheap.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from fastapi import WebSocketDisconnect

logger = logging.getLogger(__name__)

#: "4 Hz anchors" — the plan's own §7.1 feed table, row `clock`.
CLOCK_PUSH_S = 0.25
#: The relay's own poll cadence. SpotFX's board read is lean (no Spotify
#: call), so polling it every second while a TV is connected is cheap, and
#: a 1 s poll structurally bounds "a vote reaches a test client" at
#: poll_interval + negligible send time — comfortably under the plan's own
#: 1.5 s acceptance bound.
JUKEBOX_POLL_S = 1.0


async def _default_now_ms() -> float:
    return time.time() * 1000.0


async def _default_before_pong_send() -> None:
    """No-op in production; a test overrides this to inject a real delay
    between recording server_recv_ms and server_send_ms, proving the NTP
    offset formula survives it (see the module docstring)."""
    return None


def _default_night_http_url() -> str:
    from spectra.services import bridge
    return bridge.default_http_url()


async def _default_fetch_jukebox(http_url: str) -> Optional[dict]:
    import httpx
    try:
        async with httpx.AsyncClient(base_url=http_url, timeout=5.0) as client:
            resp = await client.get("/api/jukebox/board")
            resp.raise_for_status()
            return resp.json()
    except Exception:                                      # noqa: BLE001
        logger.warning("tv feed: jukebox relay fetch failed", exc_info=True)
        return None


def _default_show_clock() -> tuple[Optional[int], Optional[int], bool]:
    from spectra.services import engine
    show = engine.current_show_clock_ms()
    position = engine.bridge.effective_position_ms()
    playing = bool(engine.bridge.is_playing())
    return show, position, playing


def _default_build_id() -> Optional[str]:
    """The TV app's own build id, read off the plain-text manifest
    vite.tv.config.ts writes beside the build — "build-id reload" (PR
    1.1's own acceptance row) means a TV holding a STALE build reloads
    itself; `None` when no build is deployed (dev, or before `npx vite
    build --config vite.tv.config.ts` has ever run) is a normal, named
    absence, never a reason to instruct a reload."""
    from spectra import config as scfg
    path = scfg.TV_DIST / "build-id.txt"
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


@dataclass
class TvFeedDeps:
    """Every seam `run_clock_loop`/`run_jukebox_loop`/`handle_ping` touch,
    all swappable — the same shape as `GuestDeps`/`RunDeps` elsewhere in
    this codebase. Production defaults lazily import the real modules so
    importing this file never pulls in the bridge/engine at module load."""
    now_ms: Callable[[], Awaitable[float]] = _default_now_ms
    before_pong_send: Callable[[], Awaitable[None]] = _default_before_pong_send
    http_url: Callable[[], str] = _default_night_http_url
    fetch_jukebox: Callable[[str], Awaitable[Optional[dict]]] = _default_fetch_jukebox
    show_clock: Callable[[], tuple[Optional[int], Optional[int], bool]] = _default_show_clock
    build_id: Callable[[], Optional[str]] = _default_build_id
    clock_push_s: float = CLOCK_PUSH_S
    jukebox_poll_s: float = JUKEBOX_POLL_S


def production_deps() -> TvFeedDeps:
    return TvFeedDeps()


# ── pure message builders ───────────────────────────────────────────────────

def director_layout(jukebox_running: Optional[bool]) -> str:
    """The layout director's phase-1.2 rule: "party" while a night plays,
    "attract" otherwise — the richer idle-timeout/sleep/burn-in state
    machine (plan row 1.5) isn't built yet, so this is deliberately the
    two-state version. `None` (we don't know yet — no board read has
    landed) reads as "attract", the calmer of the two, never a guess at
    "party"."""
    return "party" if jukebox_running else "attract"


def config_message(hello: dict[str, Any], jukebox_running: Optional[bool],
                   build_id: Optional[str] = None) -> dict:
    """The server's reply to a client's `hello`. `look`/`display_lead_ms`
    are `None` placeholders — a look needs the screen fixture (phase 3);
    a display lead needs an `/avsync` measurement of this screen (phase 2)
    — carried now so the wire shape doesn't change when either lands.
    `build_id` is the DEPLOYED build's own id (read off disk, never the
    client's own `hello.build_id` echoed back) — the client's
    `shouldReload()` compares this against what it's actually running."""
    return {
        "type": "config",
        "layout": director_layout(jukebox_running),
        "look": None,
        "display_lead_ms": None,
        "build_id": build_id,
    }


def clock_message(show_clock_ms: Optional[int], position_ms: Optional[int],
                  is_playing: bool, server_ms: float) -> dict:
    return {
        "type": "clock",
        "show_clock_ms": show_clock_ms,
        "position_ms": position_ms,
        "is_playing": is_playing,
        "server_ms": server_ms,
    }


def layout_message(jukebox_running: Optional[bool]) -> dict:
    return {"type": "layout", "layout": director_layout(jukebox_running)}


def jukebox_message(board: Optional[dict]) -> dict:
    """`board` is SpotFX's own `GET /api/jukebox/board` response verbatim
    (see the module docstring on why — this PR predates the leaner
    `/api/jukebox/tv` endpoint PR 1.3 adds), or `None` when the relay
    couldn't reach SpotFX at all (a transient fetch failure, named rather
    than silently repeating the last good payload forever)."""
    if board is None:
        return {"type": "jukebox", "running": None, "reachable": False}
    return {"type": "jukebox", "reachable": True, **board}


async def handle_ping(msg: dict[str, Any], deps: TvFeedDeps) -> dict:
    """`{"type": "ping", "t": <client_send_ms>}` -> `{"type": "pong",
    "client_t":..., "server_recv_ms":..., "server_send_ms":...}`. The two
    server timestamps bracket whatever this coroutine does between them
    (`before_pong_send`, a no-op in production) — see the module docstring
    for why that's what keeps the NTP offset formula honest under a
    stall."""
    server_recv_ms = await deps.now_ms()
    await deps.before_pong_send()
    server_send_ms = await deps.now_ms()
    return {
        "type": "pong",
        "client_t": msg.get("t"),
        "server_recv_ms": server_recv_ms,
        "server_send_ms": server_send_ms,
    }


# ── the two per-connection background loops ─────────────────────────────────

async def run_clock_loop(send: Callable[[dict], Awaitable[None]], deps: TvFeedDeps,
                         sleep: Callable[[float], Awaitable[None]]) -> None:
    """Pushes a `clock` message at `deps.clock_push_s` (4 Hz in production)
    until cancelled. Errors from a dead socket are swallowed — the caller
    cancels this task on disconnect; a send racing that cancellation must
    never crash the connection's teardown."""
    while True:
        try:
            show_clock_ms, position_ms, is_playing = deps.show_clock()
            server_ms = await deps.now_ms()
            await send(clock_message(show_clock_ms, position_ms, is_playing, server_ms))
        except (WebSocketDisconnect, RuntimeError):
            return
        except Exception:                                  # noqa: BLE001
            logger.warning("tv feed: clock loop ended unexpectedly", exc_info=True)
            return
        await sleep(deps.clock_push_s)


async def run_jukebox_loop(send: Callable[[dict], Awaitable[None]], deps: TvFeedDeps,
                           sleep: Callable[[float], Awaitable[None]]) -> None:
    """Polls SpotFX's board at `deps.jukebox_poll_s` (1 Hz) and sends a
    `jukebox` message only when the payload actually changed — a plain
    dict-equality check against the last sent payload, cheap and exact,
    never a hash (the payload is already small: now + next 3 + the board).
    Also sends a `layout` message on the SAME change, since the director's
    pick depends on this exact payload's `running` field and nothing else
    here recomputes it independently."""
    last: Any = object()  # never equals a real payload — forces the first send
    while True:
        try:
            http_url = deps.http_url()
            board = await deps.fetch_jukebox(http_url)
            if board != last:
                last = board
                running = board.get("running") if isinstance(board, dict) else None
                await send(jukebox_message(board))
                await send(layout_message(running))
        except (WebSocketDisconnect, RuntimeError):
            return
        except Exception:                                  # noqa: BLE001
            logger.warning("tv feed: jukebox loop ended unexpectedly", exc_info=True)
            return
        await sleep(deps.jukebox_poll_s)
