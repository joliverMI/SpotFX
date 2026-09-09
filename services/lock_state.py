"""
SpotFX — per-play sync-lock lifecycle, for the TopBar's lock badge.

OBSERVATION ONLY. Nothing here decides anything about timing, offsets,
lock thresholds or sweep behaviour — it records what the sweep in
`services/auto_offset_service.py` ALREADY decided and publishes it. Every
value it holds is copied from a decision that module had already made and
logged; no `note_*()` call may ever feed a value back into that sweep.
Read `AGENTS.md` "Timing and offset-direction conventions" and
`docs/SPECTRA_TIMING_CONVENTIONS.md` before adding a caller — this module
must stay on the reporting side of that line. It holds no offset the
engine reads and no threshold; `offset_ms`/`quality` are carried for the
badge's tooltip only.

WHY IT EXISTS (2026-09-08): the badge in `web/src/components/TopBar.tsx`
was driven ONLY by the `xcorr_monitor` websocket, which is the POST-LOCK
drift monitor — it runs only once a song hard-locks. With no monitor
message and any stored offset the badge printed the literal string
"Lock idle", so a song still searching, a song that finished at grade F,
and a song genuinely idle after a good lock all read identically. The
Admiral's report, verbatim: when a song has not locked the badge "should
be failed or still trying" — not "Lock idle".

FOUR PHASES, and the distinction that matters is between the last two:

  searching — the engine is actively searching this uri.
  locked    — this play reached a hard lock (the sweep's own
              `_locked_via_stop`, the same flag `lock_history.record()`
              is handed). Only this phase may ever render as idle.
  unlocked  — the engine FINISHED SEARCHING this song without one. This
              is the state the badge used to call "idle".
  skipped   — no sweep ran for this uri this play, and WHY (`reason`).
              Deliberately its own phase: "we did not check" and "we
              checked and it was fine" are different facts.

THE TERMINAL SIGNAL IS "THE ENGINE STOPPED SEARCHING", NOT "THE WINDOWS
RAN OUT" — and that distinction is load-bearing for what ships next. A
low-confidence result is NOT the end of a search: `note_outcome(locked=
False)` records the numbers and LEAVES the phase at `searching`, and only
`note_search_ended()` resolves the badge. Today that fires from the sweep
task's own done-callback, so "searching" cannot outlive the task that was
searching (a sweep killed by an unexpected exception or a cancellation
still resolves the badge instead of leaving it mid-search forever). When
the engine grows the ability to keep looking past a weak result, it keeps
its task alive and the badge stays "Searching…" with nothing to change
here; an engine that instead wants to declare itself done calls
`note_search_ended()` explicitly. Never re-key this off window
exhaustion, a `lock_history` write or a first-sweep boundary.

PUSH PLUS POLL, ONE RECORD. `note_*()` broadcasts a `lock_state` message
so a transition shows immediately, and `services/websocket_manager.py`'s
per-poll `broadcast_state` carries the SAME record (filtered to the
current track's uri) so a client that connected mid-song — which has
missed every event — is not blind, and a dropped or misordered event
self-corrects on the next poll. The frontend folds both into one store
field; neither is a second source of truth.

One record, not a history: the badge asks about the song playing NOW.
`services/lock_history.py` is the durable per-play record, untouched by
this.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

PHASE_SEARCHING = "searching"
PHASE_LOCKED = "locked"
PHASE_UNLOCKED = "unlocked"
PHASE_SKIPPED = "skipped"

WS_TYPE = "lock_state"

# The single current record, or None when nothing is known. Shape:
#   {uri, phase, windows_total, windows_done, offset_ms, quality,
#    reason, play_type, at_ms}
_record: Optional[dict[str, Any]] = None


def snapshot() -> Optional[dict[str, Any]]:
    """The current record (a copy), or None when nothing is known."""
    return dict(_record) if _record is not None else None


def for_uri(uri: Optional[str]) -> Optional[dict[str, Any]]:
    """The current record only when it belongs to `uri` — None otherwise,
    so a record for the previous song can never be rendered against the
    one now playing."""
    rec = _record
    if not uri or rec is None or rec.get("uri") != uri:
        return None
    return dict(rec)


def clear() -> None:
    """Drop the record (tests, process teardown)."""
    global _record
    _record = None


def _publish(rec: dict[str, Any]) -> None:
    """Install `rec` and push it, unless it is identical to what is already
    published. `on_track_change` re-runs on every Spotify poll, so an
    unchanged skip reason would otherwise re-broadcast once a second."""
    global _record
    if _record is not None and _same(_record, rec):
        return
    _record = rec
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Offline scripts and sync tests have no loop. The record still
        # stands, and the next state broadcast carries it. Checked BEFORE
        # building the coroutine so none is ever left un-awaited.
        return
    try:
        from services.websocket_manager import ws_manager
        loop.create_task(ws_manager.broadcast({"type": WS_TYPE, **rec}))
    except Exception:
        pass


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Equality ignoring the wall clock, which changes on every note."""
    return {k: v for k, v in a.items() if k != "at_ms"} == {
        k: v for k, v in b.items() if k != "at_ms"
    }


def _new(uri: str, phase: str, **fields: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "uri": uri,
        "phase": phase,
        "windows_total": 0,
        "windows_done": 0,
        "offset_ms": None,
        "quality": None,
        "reason": None,
        "play_type": None,
        "at_ms": int(time.time() * 1000),
    }
    rec.update(fields)
    return rec


def note_searching(uri: str, *, windows_total: int,
                   play_type: Optional[str] = None) -> None:
    """The engine has started searching `uri`."""
    _publish(_new(uri, PHASE_SEARCHING,
                  windows_total=int(windows_total), play_type=play_type))


def note_window_done(uri: str) -> None:
    """One sweep window finished — live progress for the badge. Ignored
    unless a search for this uri is still the published record, so a late
    window from a cancelled sweep cannot revive a resolved badge."""
    rec = _record
    if rec is None or rec.get("uri") != uri or rec.get("phase") != PHASE_SEARCHING:
        return
    nxt = dict(rec)
    nxt["windows_done"] = int(rec.get("windows_done", 0)) + 1
    nxt["at_ms"] = int(time.time() * 1000)
    _publish(nxt)


def note_outcome(uri: str, *, locked: bool, offset_ms: Optional[int] = None,
                 quality: Optional[float] = None,
                 reason: Optional[str] = None) -> None:
    """The sweep has produced a result for `uri`. `locked` is the sweep's
    own hard-lock flag, copied verbatim — this module never re-derives it.

    A hard lock resolves the badge at once. A result WITHOUT one does not:
    the numbers are recorded and the phase stays `searching`, because a
    weak result is not the same event as the engine giving up. See the
    module docstring — `note_search_ended()` is what resolves it."""
    rec = _record
    if rec is None or rec.get("uri") != uri:
        return
    _publish(_new(
        uri, PHASE_LOCKED if locked else rec.get("phase", PHASE_SEARCHING),
        windows_total=int(rec.get("windows_total", 0)),
        windows_done=int(rec.get("windows_done", 0)),
        offset_ms=None if offset_ms is None else int(offset_ms),
        quality=None if quality is None else round(float(quality), 3),
        reason=reason,
        play_type=rec.get("play_type"),
    ))


def note_search_ended(uri: str, reason: Optional[str] = None) -> None:
    """The engine has FINISHED searching `uri`. A record still reading
    `searching` becomes `unlocked` — it looked and did not find a lock.
    Any already-resolved phase is left exactly as it stands."""
    try:
        rec = _record
        if rec is None or rec.get("uri") != uri or rec.get("phase") != PHASE_SEARCHING:
            return
        nxt = dict(rec)
        nxt["phase"] = PHASE_UNLOCKED
        # A reason already stashed by note_outcome ("no_measurements") is more
        # specific than anything the end-of-search caller can say, so it wins.
        nxt["reason"] = rec.get("reason") or reason
        nxt["at_ms"] = int(time.time() * 1000)
        _publish(nxt)
    except Exception:  # also used as a task done-callback, which must not raise
        logger.debug("lock_state.note_search_ended failed", exc_info=True)


def note_skipped(uri: str, reason: str) -> None:
    """No sweep will run for `uri` this play, and why."""
    _publish(_new(uri, PHASE_SKIPPED, reason=reason))
