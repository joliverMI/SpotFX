"""THE KNOWN AUDIO BUFFER — the executable spec for what SPECTRA does with
the number River publishes (spectra/services/known_buffer.py).

What these prove, in the order the contract states them:
  1. THE LADDER, expressed as a MULTIPLE — fresh at one period, stale at
     one, missing at `stale_periods`, and the same transitions after the
     period is retuned (which is the whole reason it is a multiple).
  2. STALE HOLDS THE VALUE AND SURFACES ITS AGE.
  3. MISSING FALLS TO THE FLOOR — never zero, and with no branch anywhere
     that means "no correction".
  4. The floor clamps and flags; the ceiling flags and does NOT clamp.
  5. The two feeds: a poll that records on good JSON and records NOTHING on
     bad, and an SSE subscriber that takes the current value on connect,
     applies a step AT ONCE across an epoch change, and reconnects.
  6. THE APPLICATION GATE: floor_clamped -> compensation 0 with the gate
     sentence; ungated -> the reference-based delta, worked in BOTH
     directions.
"""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from spectra import config as scfg
from spectra.services import known_buffer as kb
from spectra.services import room_controls as rc

PERIOD = 15.0
# A LIVE clock: the retention prune and the ladder both measure against
# wall time, so a frozen constant here would silently make every fixture
# reading both "missing" and instantly prunable.
NOW_MS = int(time.time() * 1000)


def _settings(**over):
    base = dict(known_buffer_source_url="http://river",
                known_buffer_floor_ms=500,
                known_buffer_ceiling_ms=1500,
                known_buffer_update_period_s=PERIOD,
                known_buffer_stale_periods=4.0)
    base.update(over)
    return rc.RoomControlState(**base)


@pytest.fixture
def room(tmp_path, monkeypatch):
    """Real RoomControlState on a temp file, so base_url()/_settings() read
    the same way production does."""
    path = tmp_path / "room_controls.json"
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", path)

    def write(**over):
        rc.save_room_controls(_settings(**over))
    write()
    return write


def _payload(value=500, t_ms=NOW_MS, **over):
    """River's real shape (captured live from parec-offset/2, 2026-09-17)."""
    body = {
        "schema": "parec-offset/2", "t_ms": t_ms,
        "effects_fire_later_by_ms": value, "source": "measured",
        "epoch": 0, "discontinuity": False, "step_cause": None,
        "floor_clamped": True, "governed": False, "parec_buffer_ms": 0.0,
        "flowing": False, "stale": False, "age_ms": 1200.0,
        "held_age_ms": None, "update_period_ms": 15000,
        "hold_limit_ms": 60000, "floor_ms": 500,
    }
    body.update(over)
    return body


# ── 1/2/3. the ladder ───────────────────────────────────────────────────
@pytest.mark.parametrize("age_s,expected", [
    (0.0, "fresh"),
    (PERIOD - 0.1, "fresh"),
    (PERIOD, "fresh"),           # the boundary belongs to fresh: age <= 1 period
    (PERIOD + 0.1, "stale"),
    (PERIOD * 4, "stale"),       # stale_periods = 4, inclusive
    (PERIOD * 4 + 0.1, "missing"),
])
def test_the_ladder_transitions_at_the_declared_multiples(room, age_s, expected):
    st = _settings()
    reading = kb.parse(_payload(t_ms=NOW_MS))
    now = NOW_MS + age_s * 1000.0
    assert kb.ladder_state(reading, st, now_ms=now) == expected


def test_the_ladder_is_a_multiple_so_it_survives_the_period_changing(room):
    """The same ages land in DIFFERENT states once the period is retuned —
    which is what "expressed as a MULTIPLE" buys. A ladder written in
    seconds would silently keep the old widths."""
    reading = kb.parse(_payload(t_ms=NOW_MS))
    slow = _settings(known_buffer_update_period_s=60.0)
    fast = _settings(known_buffer_update_period_s=5.0)
    at = NOW_MS + 30_000
    assert kb.ladder_state(reading, slow, now_ms=at) == "fresh"     # 30s <= 60s
    assert kb.ladder_state(reading, fast, now_ms=at) == "missing"   # 30s > 4x5s
    # and the STALE band moves with it, not with a frozen number of seconds
    assert kb.ladder_state(reading, fast, now_ms=NOW_MS + 15_000) == "stale"


def test_unconfigured_is_its_own_answer_not_missing(room):
    room(known_buffer_source_url="")
    state = kb.state()
    assert state["state"] == "unconfigured"
    assert "not configured" in state["sentence"]
    # even unconfigured, the value it stands behind is the floor.
    assert state["effects_fire_later_by_ms"] == 500


def test_stale_holds_the_value_and_surfaces_its_age(room, monkeypatch):
    now = time.time() * 1000.0
    kb.record(_payload(value=900, t_ms=int(now - PERIOD * 2000)))
    state = kb.state()
    assert state["state"] == "stale"
    assert state["effects_fire_later_by_ms"] == 900       # HELD, not dropped
    assert state["published_ms"] == 900
    assert state["age_s"] >= PERIOD * 2 - 1
    assert "held for" in state["sentence"]


def test_missing_falls_to_the_floor_and_never_to_zero(room):
    """ZERO IS FORBIDDEN, AND SO IS EVERY SYNONYM FOR IT. There is no
    reading, no held value and no correction to apply — and the answer is
    still a real number: the floor."""
    state = kb.state()
    assert state["state"] == "missing"
    assert state["effects_fire_later_by_ms"] == 500
    assert state["effects_fire_later_by_ms"] != 0


def test_a_missing_reading_never_yields_zero_at_any_configured_floor(room):
    for floor in (1, 250, 500, 1200):
        room(known_buffer_floor_ms=floor)
        assert kb.state()["effects_fire_later_by_ms"] == floor
        assert kb.state()["effects_fire_later_by_ms"] != 0


def test_there_is_no_no_correction_branch_anywhere(room):
    """The forbidden synonym, proven structurally rather than by sampling:
    effective_value_ms is total (it returns an int on every path), and no
    input — including a reading that has aged out of the ladder entirely —
    produces None, 0, or an absent key in the state block."""
    st = _settings()
    assert isinstance(kb.effective_value_ms(None, st), int)
    ancient = kb.parse(_payload(value=0, t_ms=1))
    for reading in (None, ancient, kb.parse(_payload(value=500))):
        value = kb.effective_value_ms(reading, st)
        assert isinstance(value, int) and value >= st.known_buffer_floor_ms
    kb.record(_payload(value=700, t_ms=1))          # aged past every rung
    state = kb.state()
    assert state["state"] == "missing"
    assert state["effects_fire_later_by_ms"] == 500  # the floor, not 700, not 0
    assert state["published_ms"] == 700              # the history is not erased


# ── 4. floor clamps, ceiling flags ──────────────────────────────────────
def test_below_the_floor_holds_at_the_floor_and_is_flagged(room):
    kb.record(_payload(value=120))
    state = kb.state()
    assert state["published_ms"] == 120
    assert state["effects_fire_later_by_ms"] == 500
    assert "below_floor" in state["flags"]


def test_above_the_ceiling_is_flagged_and_NOT_clamped(room):
    """A variable buffer tracked accurately PASSES — the bounding that
    would hold it down is River's separate half, not ours."""
    kb.record(_payload(value=2400))
    state = kb.state()
    assert state["effects_fire_later_by_ms"] == 2400   # not 1500
    assert "above_ceiling" in state["flags"]


# ── 5a. the poll ────────────────────────────────────────────────────────
def _asgi_client(handler):
    """A real ASGI app behind httpx — a fake River, not a mocked method."""
    async def app(scope, receive, send):
        await handler(scope, receive, send)
    return lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://river")


def _json_app(status, body):
    async def handler(scope, receive, send):
        payload = json.dumps(body).encode() if not isinstance(body, bytes) else body
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": payload})
    return _asgi_client(handler)


def test_a_good_poll_records_the_reading(room):
    reading = asyncio.run(kb.poll_once(_json_app(200, _payload(value=640))))
    assert reading is not None and reading.effects_fire_later_by_ms == 640
    assert kb.state()["published_ms"] == 640
    assert kb.state()["via"] == "poll"


@pytest.mark.parametrize("status,body", [
    (500, {"error": "boom"}),
    (200, b"not json at all"),
    (200, {"t_ms": NOW_MS}),                              # no value
    (200, {"effects_fire_later_by_ms": 500}),             # no timestamp
    (200, {"effects_fire_later_by_ms": -5, "t_ms": NOW_MS}),
    (200, {"effects_fire_later_by_ms": "soon", "t_ms": NOW_MS}),
])
def test_a_bad_poll_records_nothing_and_the_ladder_ages_the_last_good_one(
        room, status, body):
    kb.record(_payload(value=640))
    before = kb.state()["published_ms"]
    assert asyncio.run(kb.poll_once(_json_app(status, body))) is None
    after = kb.state()
    assert after["published_ms"] == before == 640     # untouched
    assert after["poll_failures"] == 1
    assert after["last_error"]


def test_an_unconfigured_poll_asks_nobody(room):
    room(known_buffer_source_url="")
    asked = []

    def factory():
        asked.append(1)
        raise AssertionError("must not build a client when unconfigured")
    assert asyncio.run(kb.poll_once(factory)) is None
    assert not asked


# ── 5b. the SSE subscriber ──────────────────────────────────────────────
def _sse_app(batches):
    """A fake River /events: each call to the app serves ONE connection,
    emitting the next batch of events and then ENDING the stream — which
    is what a River restart looks like from here."""
    state = {"n": 0}

    async def handler(scope, receive, send):
        idx = min(state["n"], len(batches) - 1)
        state["n"] += 1
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        for payload in batches[idx]:
            body = ("event: offset\ndata: " + json.dumps(payload) + "\n\n").encode()
            await send({"type": "http.response.body", "body": body,
                        "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})
    return _asgi_client(handler), state


def test_the_subscriber_takes_the_current_value_on_connect(room):
    factory, _ = _sse_app([[_payload(value=700)]])
    asyncio.run(kb.run_sse_supervised(factory, connects=1))
    state = kb.state()
    assert state["published_ms"] == 700
    assert state["via"] == "events"
    assert state["readings_seen"] == 1


def test_a_step_with_a_new_epoch_is_applied_at_once_and_never_smoothed(room):
    """A drain is a DISCONTINUITY: the new value replaces the old outright.
    Anything between the two — a mean, a ramp, a filtered value — would be
    SPECTRA inventing a buffer River never published."""
    factory, _ = _sse_app([[
        _payload(value=1400, epoch=3),
        _payload(value=520, t_ms=NOW_MS + 1, epoch=4, discontinuity=True,
                 step_cause="drain"),
    ]])
    asyncio.run(kb.run_sse_supervised(factory, connects=1))
    state = kb.state()
    assert state["published_ms"] == 520          # exactly the step, at once
    assert state["published_ms"] not in (1400, 960, 1400 - 440)
    assert state["river"]["epoch"] == 4
    assert "discontinuity" in state["flags"]


def test_the_subscriber_reconnects_after_the_stream_drops(room, monkeypatch):
    monkeypatch.setattr(kb, "SSE_BACKOFF_MIN_S", 0.0)
    factory, calls = _sse_app([[_payload(value=700)],
                               [_payload(value=810, t_ms=NOW_MS + 5000)]])
    asyncio.run(kb.run_sse_supervised(factory, connects=2))
    assert calls["n"] == 2                       # it really did reconnect
    assert kb.state()["published_ms"] == 810     # and re-synced on connect


def test_a_malformed_event_never_drops_the_subscription(room):
    async def handler(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        for body in (b": keepalive\n\n",
                     b"event: offset\ndata: {broken\n\n",
                     b"event: offset\ndata: " + json.dumps(_payload(value=777)).encode() + b"\n\n"):
            await send({"type": "http.response.body", "body": body, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})
    asyncio.run(kb.run_sse_supervised(_asgi_client(handler), connects=1))
    assert kb.state()["published_ms"] == 777


def test_sse_framing_survives_a_split_across_chunks():
    """The pure framing helpers, so a reading is never lost to where a TCP
    read happened to land."""
    events, carry = kb._sse_events("event: offset\ndata: {\"a\":", "")
    assert events == [] and carry
    events, carry = kb._sse_events(" 1}\n\nevent: offset\ndata: {}\n\n", carry)
    assert len(events) == 2 and carry == ""
    assert kb._sse_data(events[0]) == '{"a": 1}'


# ── 6. the application gate + the reference-based delta ─────────────────
def test_floor_clamped_applies_nothing_and_says_why(room):
    kb.record(_payload(value=500, floor_clamped=True, governed=False))
    state = kb.state()
    assert state["applied"] is False
    assert state["compensation_ms"] == 0
    assert state["apply_gate"] == "waiting for the bounding half (floor_clamped)"
    assert state["reference_ms"] is None          # a floor cannot anchor a delta
    assert "nothing is applied yet" in state["sentence"]


def test_an_unknown_gate_is_never_read_as_an_open_one(room):
    kb.record({"effects_fire_later_by_ms": 800, "t_ms": int(time.time() * 1000)})
    assert kb.state()["applied"] is False


def test_the_first_ungated_reading_anchors_the_reference_at_zero(room):
    """Going live changes nothing in his room: the compensation is 0 on the
    first reading the gate accepts."""
    now = int(time.time() * 1000)
    kb.record(_payload(value=900, t_ms=now, floor_clamped=False, governed=True))
    state = kb.state()
    assert state["applied"] is True
    assert state["reference_ms"] == 900
    assert state["compensation_ms"] == 0
    assert state["apply_gate"] == ""


def test_the_compensation_is_the_delta_from_the_reference_both_ways(room):
    """Worked, both directions. Reference 900.
         buffer grows to 1200 -> +300, fire 300 ms LATER
         buffer drains to 620 ->  -280, fire 280 ms less late"""
    now = int(time.time() * 1000)
    kb.record(_payload(value=900, t_ms=now, floor_clamped=False, governed=True))
    kb.record(_payload(value=1200, t_ms=now + 1000, floor_clamped=False, governed=True))
    assert kb.state()["compensation_ms"] == 300
    kb.record(_payload(value=620, t_ms=now + 2000, epoch=1, discontinuity=True,
                       floor_clamped=False, governed=True))
    assert kb.state()["compensation_ms"] == -280


def test_the_reference_re_bases_on_an_av_sync_lead_apply(room):
    """That measurement absorbed the buffer AS IT STOOD, so the delta has to
    start again from there — otherwise the same milliseconds are counted
    twice."""
    now = int(time.time() * 1000)
    kb.record(_payload(value=900, t_ms=now, floor_clamped=False, governed=True))
    kb.record(_payload(value=1200, t_ms=now + 1000, floor_clamped=False, governed=True))
    assert kb.state()["compensation_ms"] == 300
    assert kb.rebase_reference() == 1200
    assert kb.state()["compensation_ms"] == 0


def test_rebasing_with_nothing_to_anchor_on_returns_none(room):
    assert kb.rebase_reference() is None
    kb.record(_payload(value=500, floor_clamped=True))
    assert kb.rebase_reference() is None


# ── the raw series ──────────────────────────────────────────────────────
def test_every_reading_is_logged_for_the_drift_picture(room):
    kb.record(_payload(value=500, t_ms=NOW_MS))
    kb.record(_payload(value=640, t_ms=NOW_MS + 15000))
    rows = kb.read_log()
    assert [r["effects_fire_later_by_ms"] for r in rows] == [500, 640]
    assert rows[0]["parec_buffer_ms"] == 0.0
    assert rows[0]["source"] == "measured" and rows[0]["via"] == ""


def test_the_log_is_pruned_to_the_retention_window(room):
    """A reading older than the window does not survive a write — including
    its own, which is the honest behaviour: the file is the LAST SEVEN
    DAYS, not the last seven days plus whatever arrived stamped older."""
    old = int(time.time() * 1000 - (kb.LOG_RETENTION_S + 3600) * 1000)
    kb.record(_payload(value=500, t_ms=old))
    kb.record(_payload(value=640, t_ms=NOW_MS))
    rows = kb.read_log()
    assert [r["effects_fire_later_by_ms"] for r in rows] == [640]


def test_a_reading_is_never_lost_to_a_log_that_cannot_be_written(room, monkeypatch):
    monkeypatch.setattr(scfg, "KNOWN_BUFFER_LOG_FILE",
                        scfg.SPECTRA_STORAGE / "nope" / "\0bad")
    kb.record(_payload(value=640))
    assert kb.state()["published_ms"] == 640


# ── ordering ────────────────────────────────────────────────────────────
def test_a_late_poll_response_never_overwrites_a_newer_step(room):
    """The poll and the subscriber run independently, so a slow /offset
    response can land after a step it predates."""
    now = int(time.time() * 1000)
    kb.record(_payload(value=1400, t_ms=now, epoch=2), via="events")
    kb.record(_payload(value=900, t_ms=now - 9000, epoch=2), via="poll")
    assert kb.state()["published_ms"] == 1400
