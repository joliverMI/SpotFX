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
stall; AGENTS.md's "THE PREVIEW STREAM IS PROTOCOL 2" section — "THE
STREAM IS A PASSENGER ON THE EVENT LOOP" — is the standing evidence): the
stall shows up as added round-trip delay, never as skew, PROVIDED both
timestamps are taken as close to the actual recv/send as possible.
`handle_ping`'s own `before_pong_send` hook exists so a test can
PROVE that resistance by injecting a real delay there, rather than trusting
the formula by inspection.

THE SLEEP TIMEOUT (PR 1.5, plan row 1.5/Q8: "black after 10 min with no
night and no music") is tracked by a process-wide `ActivityTracker` — one
instance, shared by every connected TV (the room's own idle time is a
single fact, not a per-connection one). `resolve_layout` is pure (idle
seconds in, a layout string out); the tracker is the one piece of real
mutable state, and it lives OUTSIDE `TvFeedDeps` on purpose: a fresh
`TvFeedDeps()` is built per connection (`production_deps()`), so putting a
stateful tracker INSIDE it would give every TV its own idea of how long
the room has been idle. `TvFeedDeps.idle_s` is the swappable seam a test
injects instead.

THE "BOARD WENT STALE" FALLBACK (plan §2.2: "a night runs but the screen
has been unchanged a while, or between nights: a slow deck") is a SECOND,
independent reason to show "attract" — a running night always counts as
"active" for the sleep clock above (`idle_s` stays pinned at 0 the whole
time a night plays), so without this a genuinely running-but-quiet night
(no votes, the same song still playing) would show "party" forever. It is
tracked the same way — a second process-wide `ActivityTracker` instance,
`_board_activity` — fed by whether the relayed board ACTUALLY changed this
tick: the exact same comparison `run_jukebox_loop` already makes for its
own send-on-change dedup (`board != last_board`), never a second,
differently-computed notion of "changed". `sleep` still wins outright over
this (checked first in `resolve_layout`); this fallback only fires while a
night IS running and is NOT idle in the `ActivityTracker`/`SLEEP_TIMEOUT_S`
sense — `jukebox_running` falsy already resolves to "attract" on its own,
via `director_layout`.

THE JUKEBOX RELAY READS SPOTFX'S OWN `GET /api/jukebox/tv` (PR 1.3,
services/jukebox/guests.py::Guests.tv_view — now/votes/next 3/board/link/
revision, the leaner purpose-built shape the plan's own row 1.3 names).
`run_jukebox_loop` is written against `TvFeedDeps.fetch_jukebox`, a single
swappable seam — PR 1.2's own first version pointed this at the older
`GET /api/jukebox/board` (PR 466) because 1.3's endpoint didn't exist yet;
this is that one-line follow-up, not a second relay implementation.
`running` — whether a night is playing right now — is read FROM that same
fetched payload, not from a second call: polling it separately to decide
whether to poll it is circular, and SpotFX's own read is already lean
(no Spotify call — guests.py's own `_running()`/`tv_view()` docstrings),
so polling it every second regardless of state is cheap.
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
            resp = await client.get("/api/jukebox/tv")
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


#: Plan row 1.5/Q8: "black after 10 min with no night and no music".
SLEEP_TIMEOUT_S = 600.0

#: Plan §2.2's second reason for "attract": "a night runs but the screen
#: has been unchanged a while" — independent of SLEEP_TIMEOUT_S, which
#: only covers "between nights" (no night running AND no music playing).
#: A running night always counts as "active" for SLEEP_TIMEOUT_S, so
#: without this a quiet-but-running night (no votes, same song still
#: playing) would show "party" forever.
UNCHANGED_TIMEOUT_S = 180.0


class ActivityTracker:
    """How long some boolean "activity" signal has been false. Two
    process-wide instances share this one shape for two different
    signals: `_activity` (fed by "a night is running OR music is
    playing", driving the SLEEP_TIMEOUT_S clock) and `_board_activity`
    (fed by "the relayed board actually changed this tick", driving the
    UNCHANGED_TIMEOUT_S fallback) — both are process-wide, not
    per-connection, because each is a single fact about the room/the
    board, not a per-connection one (see the module docstring for the
    full reasoning). A fresh tracker starts "just became active" (never
    "already idle") so a process restart can't trip either timeout
    before actually observing the real elapsed time."""

    def __init__(self) -> None:
        self._last_active_ms: Optional[float] = None

    def idle_s(self, active: bool, now_ms: float) -> float:
        if active or self._last_active_ms is None:
            self._last_active_ms = now_ms
            return 0.0
        return (now_ms - self._last_active_ms) / 1000.0


_activity = ActivityTracker()
_board_activity = ActivityTracker()


def _default_idle_s(active: bool, now_ms: float) -> float:
    return _activity.idle_s(active, now_ms)


def _default_board_unchanged_s(changed: bool, now_ms: float) -> float:
    return _board_activity.idle_s(changed, now_ms)


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
    idle_s: Callable[[bool, float], float] = _default_idle_s
    board_unchanged_s: Callable[[bool, float], float] = _default_board_unchanged_s
    clock_push_s: float = CLOCK_PUSH_S
    jukebox_poll_s: float = JUKEBOX_POLL_S


def production_deps() -> TvFeedDeps:
    return TvFeedDeps()


# ── pure message builders ───────────────────────────────────────────────────

def director_layout(jukebox_running: Optional[bool]) -> str:
    """The director's plain two-state split: "party" while a night plays,
    "attract" otherwise. `None` (we don't know yet — no board read has
    landed) reads as "attract", the calmer of the two, never a guess at
    "party". `resolve_layout` below layers "sleep" on top of this — this
    function alone never names it."""
    return "party" if jukebox_running else "attract"


def resolve_layout(jukebox_running: Optional[bool], idle_s: float,
                   board_unchanged_s: float = 0.0) -> str:
    """The full director decision (plan row 1.5, Q8: "black after 10 min
    with no night and no music"; plan §2.2's own second reason, "a night
    runs but the screen has been unchanged a while"). `idle_s` and
    `board_unchanged_s` are both computed by the caller's own
    `ActivityTracker` instances, never derived here, so this stays a pure
    function of its three inputs. Precedence: `sleep` wins outright once
    `idle_s` crosses `SLEEP_TIMEOUT_S`, regardless of anything else; else,
    while a night IS running, `attract` wins too once `board_unchanged_s`
    crosses `UNCHANGED_TIMEOUT_S` — a NEW, independent reason to fall
    back, never reached while `jukebox_running` is falsy (that case is
    already "attract" via `director_layout` below); else exactly
    `director_layout`'s plain split."""
    if idle_s >= SLEEP_TIMEOUT_S:
        return "sleep"
    if jukebox_running and board_unchanged_s >= UNCHANGED_TIMEOUT_S:
        return "attract"
    return director_layout(jukebox_running)


def config_message(hello: dict[str, Any], jukebox_running: Optional[bool],
                   build_id: Optional[str] = None, idle_s: float = 0.0) -> dict:
    """The server's reply to a client's `hello`. `look`/`display_lead_ms`
    are `None` placeholders — a look needs the screen fixture (phase 3);
    a display lead needs an `/avsync` measurement of this screen (phase 2)
    — carried now so the wire shape doesn't change when either lands.
    `build_id` is the DEPLOYED build's own id (read off disk, never the
    client's own `hello.build_id` echoed back) — the client's
    `shouldReload()` compares this against what it's actually running.
    `idle_s` (default 0 — the caller passes the real value) lets a
    reconnecting TV land on "sleep" immediately rather than waiting for
    the jukebox loop's own next tick to correct an initial "attract".
    `board_unchanged_s` (unparameterized here, always `resolve_layout`'s
    own default of 0) deliberately does NOT get the same treatment — the
    caller has no board-change comparison to make yet at handshake time,
    so a reconnecting TV during a stale-but-running night briefly shows
    "party" until the jukebox loop's own very first tick (which always
    sends a `layout` message, win or lose) corrects it, within one poll
    interval."""
    return {
        "type": "config",
        "layout": resolve_layout(jukebox_running, idle_s),
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


def _layout_payload(layout: str) -> dict:
    return {"type": "layout", "layout": layout}


def jukebox_message(board: Optional[dict]) -> dict:
    """`board` is SpotFX's own `GET /api/jukebox/tv` response verbatim
    (see the module docstring), or `None` when the relay couldn't reach
    SpotFX at all (a transient fetch failure, named rather than silently
    repeating the last good payload forever)."""
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
    That same comparison (`board_changed` below) is ALSO what feeds
    `deps.board_unchanged_s` — the one definition of "did the board just
    change", shared by the send-on-change dedup (did we need to tell the
    TV) and the staleness clock (how long since it last told us something
    new) rather than two independently-computed notions that could
    disagree.

    The LAYOUT, separately, is re-resolved on EVERY tick regardless of
    whether the board changed — a `layout` message is sent only when the
    RESOLVED layout itself changes, never tied to the board's own change
    (PR 1.2's original pairing). This split is what makes sleep AND the
    unchanged-board fallback possible: the room can sit with an
    unchanging, not-running board for the whole 10-minute sleep timeout,
    or an unchanging, RUNNING board for the whole 3-minute attract
    fallback, and nothing would ever re-check either clock if the layout
    push only ever rode along with a board change that, by definition,
    isn't happening during either stretch."""
    last_board: Any = object()  # never equals a real payload — forces the first send
    last_layout: Optional[str] = None
    while True:
        try:
            http_url = deps.http_url()
            board = await deps.fetch_jukebox(http_url)
            running = board.get("running") if isinstance(board, dict) else None
            board_changed = board != last_board
            if board_changed:
                last_board = board
                await send(jukebox_message(board))

            _show, _pos, is_playing = deps.show_clock()
            now_ms = await deps.now_ms()
            idle_s = deps.idle_s(bool(running) or is_playing, now_ms)
            board_unchanged_s = deps.board_unchanged_s(board_changed, now_ms)
            layout = resolve_layout(running, idle_s, board_unchanged_s)
            if layout != last_layout:
                last_layout = layout
                await send(_layout_payload(layout))
        except (WebSocketDisconnect, RuntimeError):
            return
        except Exception:                                  # noqa: BLE001
            logger.warning("tv feed: jukebox loop ended unexpectedly", exc_info=True)
            return
        await sleep(deps.jukebox_poll_s)
