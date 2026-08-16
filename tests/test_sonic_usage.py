"""Sonic's durable token-usage record (spectra/services/sonic_usage.py) —
the review page's "last query / this day / this week" figures. Offline,
no network required.

  1. Fixed-window period boundaries: Monday 22:00 America/New_York,
     including the Monday-before-the-boundary-hour edge case and a real
     DST-crossing proof (spring-forward and fall-back use the correct
     local UTC offset, never a hardcoded one) — his own overruling ask.
  2. record()/summary(): real per-call figures land, rolled up correctly
     into day/week TRUE SUMS bucketed at READ time against stored wall_ms
     timestamps (not pre-bucketed at write time) — proven by moving `now`
     across a boundary against the SAME stored log and getting a
     different, correct answer.
  3. Durability across a process restart: a fresh module import (no
     leftover in-memory state) reconstructs the identical summary from
     disk alone.
  4. Both real backends actually capture REAL reported usage, never a
     fabricated estimate: settings_agent.run_turn() (the "api" backend)
     sums real Anthropic SDK response.usage across tool rounds and
     records nothing when no round ever reports one; settings_agent_cli.py
     (the "cli"/subscription backend) is proven against a REAL captured
     transcript fixture (tests/fixtures/cli_transcript_applied.json) — the
     recorded entry matches that fixture's own `usage`/`modelUsage`/
     `total_cost_usd` fields exactly — and a fixture with no `usage` key
     at all (cli_transcript_manifest_mismatch.json) records nothing rather
     than a fabricated zero.
"""
from __future__ import annotations

import asyncio
import importlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
EASTERN = ZoneInfo("America/New_York")


def _run(coro):
    return asyncio.run(coro)


def _load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


def _ms(y, mo, d, h, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=EASTERN).timestamp() * 1000)


# ═══ 1. fixed-window period boundaries ═══════════════════════════════════

def test_day_period_starts_at_2200_eastern_before_the_boundary():
    from spectra.services import sonic_usage as su

    # Wednesday 3pm ET — the boundary hasn't happened yet today, so the
    # current day period started YESTERDAY at 22:00.
    now_ms = _ms(2026, 8, 19, 15)
    day_start, _ = su._period_start_ms(now_ms)
    assert day_start == _ms(2026, 8, 18, 22)


def test_day_period_starts_at_2200_eastern_after_the_boundary():
    from spectra.services import sonic_usage as su

    now_ms = _ms(2026, 8, 19, 23)
    day_start, _ = su._period_start_ms(now_ms)
    assert day_start == _ms(2026, 8, 19, 22)


def test_week_period_anchors_to_the_most_recent_monday_2200():
    from spectra.services import sonic_usage as su

    # 2026-08-19 is a Wednesday; the week's own Monday is 2026-08-17.
    now_ms = _ms(2026, 8, 19, 15)
    _, week_start = su._period_start_ms(now_ms)
    assert week_start == _ms(2026, 8, 17, 22)


def test_week_period_on_monday_before_its_own_boundary_uses_last_week():
    """The edge case his ruling calls out explicitly: standing on Monday
    itself, before 10pm, the current week period has NOT yet rolled over —
    it's still the week that started the PRIOR Monday at 22:00."""
    from spectra.services import sonic_usage as su

    now_ms = _ms(2026, 8, 17, 9)  # Monday 9am ET
    _, week_start = su._period_start_ms(now_ms)
    assert week_start == _ms(2026, 8, 10, 22)


def test_week_period_on_monday_after_its_own_boundary_rolls_over():
    from spectra.services import sonic_usage as su

    now_ms = _ms(2026, 8, 17, 23)  # Monday 11pm ET
    _, week_start = su._period_start_ms(now_ms)
    assert week_start == _ms(2026, 8, 17, 22)


def test_day_boundary_observes_real_dst_spring_forward():
    """2026-03-08 is the US spring-forward date (EST -05:00 -> EDT -04:00
    at 2am local). A day boundary straddling it must still land on the
    correct WALL-CLOCK 22:00, which means a DIFFERENT UTC offset either
    side of the transition — a fixed offset would get one of these two
    wrong."""
    from spectra.services import sonic_usage as su

    before = datetime(2026, 3, 1, 22, tzinfo=EASTERN)
    after = datetime(2026, 3, 15, 22, tzinfo=EASTERN)
    assert before.utcoffset().total_seconds() == -5 * 3600
    assert after.utcoffset().total_seconds() == -4 * 3600

    day_start, _ = su._period_start_ms(_ms(2026, 3, 1, 23))
    assert day_start == int(before.timestamp() * 1000)
    day_start, _ = su._period_start_ms(_ms(2026, 3, 15, 23))
    assert day_start == int(after.timestamp() * 1000)


def test_day_boundary_observes_real_dst_fall_back():
    """2026-11-01 is the US fall-back date (EDT -04:00 -> EST -05:00)."""
    from spectra.services import sonic_usage as su

    before = datetime(2026, 10, 25, 22, tzinfo=EASTERN)
    after = datetime(2026, 11, 8, 22, tzinfo=EASTERN)
    assert before.utcoffset().total_seconds() == -4 * 3600
    assert after.utcoffset().total_seconds() == -5 * 3600

    day_start, _ = su._period_start_ms(_ms(2026, 10, 25, 23))
    assert day_start == int(before.timestamp() * 1000)
    day_start, _ = su._period_start_ms(_ms(2026, 11, 8, 23))
    assert day_start == int(after.timestamp() * 1000)


# ═══ 2. record()/summary(): real rollups, bucketed at read time ═════════

def test_summary_with_no_recorded_calls_is_honestly_empty():
    from spectra.services import sonic_usage as su

    result = su.summary(now_ms=_ms(2026, 8, 19, 15))
    assert result["last_query"] is None
    assert result["day"]["query_count"] == 0
    assert result["day"]["total_tokens"] == 0
    assert result["week"]["query_count"] == 0


def test_summary_sums_real_entries_into_day_and_week_windows():
    from spectra.services import sonic_usage as su

    # Monday 2026-08-17 22:00 ET is this week's day/week anchor.
    su.record(backend="cli", model="claude-sonnet-5",
             input_tokens=100, output_tokens=50,
             cache_creation_input_tokens=0, cache_read_input_tokens=0,
             cost_usd=0.01, now_ms=_ms(2026, 8, 10, 12))  # last week — outside both
    su.record(backend="cli", model="claude-sonnet-5",
             input_tokens=10, output_tokens=5,
             cache_creation_input_tokens=0, cache_read_input_tokens=0,
             cost_usd=0.001, now_ms=_ms(2026, 8, 18, 12))  # this week, not today
    su.record(backend="api", model="claude-sonnet-5",
             input_tokens=7, output_tokens=3,
             cache_creation_input_tokens=1, cache_read_input_tokens=2,
             now_ms=_ms(2026, 8, 19, 12))  # today AND this week — the last entry

    now_ms = _ms(2026, 8, 19, 15)
    result = su.summary(now_ms=now_ms)

    assert result["last_query"]["total_tokens"] == 7 + 3 + 1 + 2
    assert result["last_query"]["backend"] == "api"

    assert result["day"]["query_count"] == 1
    assert result["day"]["total_tokens"] == 7 + 3 + 1 + 2
    assert result["day"]["period_start_ms"] == _ms(2026, 8, 18, 22)

    assert result["week"]["query_count"] == 2
    assert result["week"]["total_tokens"] == (10 + 5) + (7 + 3 + 1 + 2)
    assert result["week"]["cost_usd"] == pytest.approx(0.001)  # the last-week entry's cost excluded
    assert result["week"]["period_start_ms"] == _ms(2026, 8, 17, 22)


def test_moving_now_across_the_boundary_re_buckets_the_same_stored_log():
    """Bucketed at READ time, never write time: the exact same durable
    entries answer differently depending only on what `now_ms` summary()
    is asked with — proving nothing was pre-assigned to a bucket when it
    was written."""
    from spectra.services import sonic_usage as su

    su.record(backend="cli", model="m", input_tokens=1, output_tokens=1,
             cache_creation_input_tokens=0, cache_read_input_tokens=0,
             now_ms=_ms(2026, 8, 18, 21, 30))  # just before Tue 22:00 boundary

    just_before = su.summary(now_ms=_ms(2026, 8, 18, 21, 45))
    just_after = su.summary(now_ms=_ms(2026, 8, 18, 22, 15))

    assert just_before["day"]["query_count"] == 1, "still inside the day period that started Mon 22:00"
    assert just_after["day"]["query_count"] == 0, "a new day period started at 22:00 — the old entry rolled out"
    assert just_after["week"]["query_count"] == 1, "the week period (anchored Monday) is unaffected"


# ═══ 3. durability across a process restart ══════════════════════════════

def test_summary_survives_a_fresh_module_import():
    """Simulates a process restart: record through one import of the
    module, reload it fresh (dropping any module-level state — there is
    none, that's the point), and confirm the reloaded module reconstructs
    the identical summary purely from the file on disk."""
    from spectra import config as scfg
    from spectra.services import sonic_usage as su

    su.record(backend="cli", model="claude-sonnet-5",
             input_tokens=42, output_tokens=17,
             cache_creation_input_tokens=3, cache_read_input_tokens=5,
             cost_usd=0.0021, session_id="sess-restart-proof",
             now_ms=_ms(2026, 8, 19, 12))

    saved_path = scfg.SONIC_USAGE_FILE
    su2 = importlib.reload(su)  # config.SONIC_USAGE_FILE is unaffected by reloading THIS module

    result = su2.summary(now_ms=_ms(2026, 8, 19, 15))
    assert result["last_query"]["total_tokens"] == 42 + 17 + 3 + 5
    assert result["last_query"]["session_id"] == "sess-restart-proof"

    on_disk = json.loads(saved_path.read_text())
    assert len(on_disk) == 1
    assert on_disk[0]["session_id"] == "sess-restart-proof"
    assert on_disk[0]["cost_usd"] == pytest.approx(0.0021)


# ═══ 4a. the "api" backend (settings_agent.py) captures REAL usage ═══════

class _Usage:
    def __init__(self, input_tokens, output_tokens,
                cache_creation_input_tokens=0, cache_read_input_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


class _Block:
    def __init__(self, type, **kw):
        self.type = type
        for k, v in kw.items():
            setattr(self, k, v)


class _Response:
    def __init__(self, content, usage=None):
        self.content = content
        self.usage = usage


class _Messages:
    def __init__(self, responses):
        self._responses = list(responses)

    async def create(self, **kwargs):
        return self._responses.pop(0)


class _Client:
    def __init__(self, responses):
        self.messages = _Messages(responses)


def test_run_turn_records_real_usage_reported_by_the_sdk_response(monkeypatch):
    from spectra.services import settings_agent as sa
    from spectra.services import sonic_usage as su

    reply = _Response([_Block("text", text="done")],
                      usage=_Usage(input_tokens=123, output_tokens=45,
                                  cache_creation_input_tokens=6, cache_read_input_tokens=7))
    monkeypatch.setattr(sa, "_client", lambda: _Client([reply]))

    _run(sa.run_turn(None, "hello"))

    result = su.summary(now_ms=int(__import__("time").time() * 1000) + 60_000)
    assert result["last_query"]["backend"] == "api"
    assert result["last_query"]["input_tokens"] == 123
    assert result["last_query"]["output_tokens"] == 45
    assert result["last_query"]["total_tokens"] == 123 + 45 + 6 + 7


def test_run_turn_records_nothing_when_the_sdk_response_reports_no_usage(monkeypatch):
    """A test double (or a hypothetical future response shape) with no
    `.usage` must never produce a fabricated all-zero entry — see
    sonic_usage.py's module docstring."""
    from spectra.services import settings_agent as sa
    from spectra.services import sonic_usage as su

    reply = _Response([_Block("text", text="done")], usage=None)
    monkeypatch.setattr(sa, "_client", lambda: _Client([reply]))

    _run(sa.run_turn(None, "hello"))

    result = su.summary()
    assert result["last_query"] is None


def test_run_turn_records_partial_usage_even_when_a_later_round_raises(monkeypatch):
    """Real tokens were spent on the first round even though the turn as
    a whole failed on the second — that spend must survive, not vanish
    with the exception."""
    from spectra.services import settings_agent as sa
    from spectra.services import sonic_usage as su

    tool_use = _Block("tool_use", id="tu_1", name="get_settings", input={})
    first = _Response([tool_use], usage=_Usage(input_tokens=10, output_tokens=20))

    class _FailingMessages(_Messages):
        async def create(self, **kwargs):
            if self._responses:
                return self._responses.pop(0)
            raise RuntimeError("simulated API failure")

    class _FailingClient:
        def __init__(self, responses):
            self.messages = _FailingMessages(responses)

    monkeypatch.setattr(sa, "_client", lambda: _FailingClient([first]))

    with pytest.raises(RuntimeError):
        _run(sa.run_turn(None, "hello"))

    result = su.summary()
    assert result["last_query"]["input_tokens"] == 10
    assert result["last_query"]["output_tokens"] == 20


# ═══ 4b. the "cli" backend (settings_agent_cli.py) captures REAL usage,═══
# proven against an ACTUAL captured transcript, not a hand-built one ══════

def test_cli_backend_records_the_exact_figures_a_real_transcript_reported():
    """cli_transcript_applied.json is a REAL captured `claude -p` run
    (see test_settings_agent_cli.py's own docstring) — its final `result`
    event's own usage/modelUsage/total_cost_usd are the ground truth this
    asserts against, not a re-derivation."""
    from spectra.services import settings_agent_cli as sac
    from spectra.services import sonic_usage as su

    events = _load_fixture("cli_transcript_applied.json")
    final = next(e for e in reversed(events) if e.get("type") == "result")

    sac._record_usage(events)

    result = su.summary()
    lq = result["last_query"]
    assert lq["backend"] == "cli"
    assert lq["model"] == next(iter(final["modelUsage"]))
    assert lq["input_tokens"] == final["usage"]["input_tokens"]
    assert lq["output_tokens"] == final["usage"]["output_tokens"]
    assert lq["cache_creation_input_tokens"] == final["usage"]["cache_creation_input_tokens"]
    assert lq["cache_read_input_tokens"] == final["usage"]["cache_read_input_tokens"]
    assert lq["cost_usd"] == pytest.approx(final["total_cost_usd"])


def test_cli_backend_records_nothing_when_the_transcript_has_no_usage_key():
    """cli_transcript_manifest_mismatch.json's own result event has no
    `usage` key at all — the honest "runtime didn't report it" case;
    nothing must be recorded rather than a fabricated zero."""
    from spectra.services import settings_agent_cli as sac
    from spectra.services import sonic_usage as su

    events = _load_fixture("cli_transcript_manifest_mismatch.json")
    sac._record_usage(events)

    result = su.summary()
    assert result["last_query"] is None
