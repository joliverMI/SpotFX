"""Sonic's durable token-usage record — the Admiral's own ask, review page:
"how much token usage Sonic has used for the last query, the last day, and
the last week." He runs Sonic against a subscription (the "cli" backend,
settings_agent_cli.py — not yet authorised against his real account) or API
credits (the "api" backend, settings_agent.py, today's default), and was
already burned once by a model quota exhausting without warning — this is
him watching consumption before it bites, not curiosity after the fact.

THE BAR THIS MODULE EXISTS TO CLEAR: every figure is REAL REPORTED USAGE
read off the model runtime's own response for that call, captured at the
choke point that already holds the real runtime object —
settings_agent.run_turn() sums the Anthropic Python SDK's own
`response.usage` across a turn's tool-call rounds; settings_agent_cli.py
reads the `claude -p --output-format json` final `result` event's own
`usage`/`modelUsage`/`total_cost_usd` fields (already a whole-turn total —
the CLI's own internal tool-loop is opaque to us, but its final summary
isn't). Neither path estimates from character/word counts. If a call
completes with no usage data reported (a test double, a future backend
variant), record() is simply never called for it — no zero-value entry is
fabricated to stand in for a real measurement. See the two call sites for
the "usage_reported" guard that enforces this.

FIXED WINDOWS, NOT ROLLING — his own explicit ruling, overruling this
module's original rolling-24h/rolling-7d design: "choose Monday at 10:00
p.m. Eastern as the cutoff so each day runs from 10:00 p.m. to 10:00 p.m.
and each week runs from Monday 10:00 p.m." Both period functions below
answer "which fixed period is `now` currently inside" — DAY_BOUNDARY_HOUR
(22:00) local Eastern time for the day, the same boundary anchored to the
most recent Monday for the week. This is almost certainly aligned to his
subscription's own quota reset, which is why the review page frames these
as "what THIS PERIOD has used" (his framing) rather than a bare running
total — a window aligned to the reset tells him how much he has LEFT; a
rolling window only ever tells him how much he has SPENT.

Eastern means the real America/New_York tz-database zone (via stdlib
zoneinfo), never a fixed UTC offset — a hardcoded -5/-4 would silently
drift the boundary by an hour across the US DST transitions in March and
November and quietly mis-attribute usage across it. See
tests/test_sonic_usage.py for the DST-crossing proof.

BUCKETED AT READ TIME, NEVER AT WRITE TIME — summary()/`_sum()` apply the
period boundary to the stored per-call records (each just a wall_ms
timestamp plus that call's own token counts) fresh on every call, from
`now_ms` forward. Nothing is pre-bucketed or counter-incremented at write
time, so correcting DAY_BOUNDARY_HOUR (or the anchor weekday) later
re-buckets ALL of history correctly against the new boundary instead of
leaving old entries locked to whatever boundary was in effect when they
were written.

Durable, bounded, atomic tmp+replace — same discipline as fire_history.py's
show log (a separate store, not shared code: a different shape, one entry
per Sonic turn rather than per production fire). No DI seam of its own
(same class of store as fire_history.py/ambient_music_gate.py/
intensity_scale.py) — tests/conftest.py's autouse `_isolated_sonic_usage`
repoints config.SONIC_USAGE_FILE for every test; a new check script that
reaches record()/summary() for real needs the same repoint or it will
write into the real repo's storage/spectra/.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from spectra import config

logger = logging.getLogger(__name__)

USAGE_LOG_MAX_ENTRIES = 20_000

EASTERN = ZoneInfo("America/New_York")
# His own words: "Monday at 10:00 p.m. Eastern" — the day boundary hour
# (also the week boundary's time-of-day, anchored to Monday below).
DAY_BOUNDARY_HOUR = 22
WEEK_ANCHOR_WEEKDAY = 0  # Monday, per datetime.weekday()


def _atomic_write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load() -> list[dict]:
    path = config.SONIC_USAGE_FILE
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def _total_tokens(input_tokens: int, output_tokens: int,
                  cache_creation_input_tokens: int, cache_read_input_tokens: int) -> int:
    return (input_tokens or 0) + (output_tokens or 0) \
        + (cache_creation_input_tokens or 0) + (cache_read_input_tokens or 0)


def record(*, backend: str, model: str,
          input_tokens: int = 0, output_tokens: int = 0,
          cache_creation_input_tokens: int = 0, cache_read_input_tokens: int = 0,
          cost_usd: Optional[float] = None, session_id: Optional[str] = None,
          rounds: Optional[int] = None, now_ms: Optional[int] = None) -> None:
    """Append one durable usage entry. One entry per Sonic TURN, not per
    underlying API call — settings_agent.py sums its own multi-round
    Anthropic calls into one entry before calling this; settings_agent_cli.py's
    single `-p` subprocess call already reports one whole-turn total. Never
    raises: a broken usage record must never break the chat turn it's
    recording (same posture as fire_history.record_fire)."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    try:
        log = _load()
        log.append({
            "wall_ms": now_ms,
            "backend": backend,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation_input_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
            "total_tokens": _total_tokens(
                input_tokens, output_tokens,
                cache_creation_input_tokens, cache_read_input_tokens),
            "cost_usd": cost_usd,
            "session_id": session_id,
            "rounds": rounds,
        })
        if len(log) > USAGE_LOG_MAX_ENTRIES:
            log = log[-USAGE_LOG_MAX_ENTRIES:]
        _atomic_write_json(config.SONIC_USAGE_FILE, log)
    except Exception:
        logger.exception("sonic-usage record failed (backend=%s)", backend)


def _period_start_ms(now_ms: int) -> tuple[int, int]:
    """Returns (day_start_ms, week_start_ms) — the start of the fixed
    22:00-Eastern day period and the Monday-22:00-Eastern week period that
    `now_ms` currently falls inside. Both are computed the same way: take
    today's boundary-hour instant in Eastern local time; if `now` hasn't
    reached it yet, the period actually started at yesterday's (for the
    day) — or last week's Monday's (for the week) — instance of it."""
    now = datetime.fromtimestamp(now_ms / 1000, tz=EASTERN)
    today_boundary = now.replace(hour=DAY_BOUNDARY_HOUR, minute=0, second=0, microsecond=0)

    day_start = today_boundary if now >= today_boundary else today_boundary - timedelta(days=1)

    days_since_anchor = (now.weekday() - WEEK_ANCHOR_WEEKDAY) % 7
    week_start = today_boundary - timedelta(days=days_since_anchor)
    if now < week_start:
        week_start -= timedelta(days=7)

    return int(day_start.timestamp() * 1000), int(week_start.timestamp() * 1000)


def _sum(entries: list[dict]) -> dict:
    cost_entries = [e.get("cost_usd") for e in entries if e.get("cost_usd") is not None]
    return {
        "query_count": len(entries),
        "total_tokens": sum(e.get("total_tokens", 0) for e in entries),
        "input_tokens": sum(e.get("input_tokens", 0) for e in entries),
        "output_tokens": sum(e.get("output_tokens", 0) for e in entries),
        "cache_creation_input_tokens": sum(e.get("cache_creation_input_tokens", 0) for e in entries),
        "cache_read_input_tokens": sum(e.get("cache_read_input_tokens", 0) for e in entries),
        "cost_usd": sum(cost_entries) if cost_entries else None,
    }


def summary(*, now_ms: Optional[int] = None) -> dict:
    """{last_query, day, week, as_of_ms, ...} for the review page.

    - last_query: the most recent recorded turn's own figures, or None if
      Sonic has never completed a turn with reported usage.
    - day / week: TRUE SUMS over the durable log within the current fixed
      period (see module docstring) — never an extrapolation, and
      recomputed against the boundary fresh on every call (bucketed at
      read time, not write time). Each carries its own `period_start_ms`
      so the UI can label "since <date>".
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    log = _load()

    last_query = None
    if log:
        last = log[-1]
        last_query = {
            "wall_ms": last.get("wall_ms"),
            "backend": last.get("backend"),
            "model": last.get("model"),
            "session_id": last.get("session_id"),
            "total_tokens": last.get("total_tokens", 0),
            "input_tokens": last.get("input_tokens", 0),
            "output_tokens": last.get("output_tokens", 0),
            "cache_creation_input_tokens": last.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": last.get("cache_read_input_tokens", 0),
            "cost_usd": last.get("cost_usd"),
        }

    day_start_ms, week_start_ms = _period_start_ms(now_ms)
    day = _sum([e for e in log if e.get("wall_ms", 0) >= day_start_ms])
    day["period_start_ms"] = day_start_ms
    week = _sum([e for e in log if e.get("wall_ms", 0) >= week_start_ms])
    week["period_start_ms"] = week_start_ms

    return {
        "last_query": last_query,
        "day": day,
        "week": week,
        "as_of_ms": now_ms,
        "timezone": "America/New_York",
        "day_boundary_hour_local": DAY_BOUNDARY_HOUR,
    }
