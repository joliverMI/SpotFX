"""THE UNATTENDED QUEUE's own logic, fast and hermetic.

The whole path — real server, real socket, real client, real protocols — is
proven by `scripts/check_capture_queue_e2e.py` (run from
tests/test_light_field_checks.py). THIS file is the fast half: what the
runner does with each outcome it is handed, which is where the decisions
that matter at 3 am live — keeping a partial, carrying on past a refusal,
stopping when the camera goes away rather than burning every item's wait on
it, naming a pose change, and writing the record after every item rather
than at the end.

`capture_runs` is faked here ON PURPOSE. Its own behaviour is proven where
it runs against the real protocols; here it is the seam, so that a change
in what a run RETURNS is caught as a change in what the queue DOES.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from spectra import config as scfg
from spectra.services import capture_queue, capture_runs, mapping_refusals


def _outcome(status, *, kind=capture_runs.KIND_MAP, detail="", refusal="",
             pose="pose-1", result=None):
    return capture_runs.RunOutcome(
        kind=kind, status=status, detail=detail, refusal=refusal,
        pose_id=pose, session_id="sess-1", result=result or {})


class _Session:
    """`capture_runs.session_view()`'s answer, scripted."""

    def __init__(self, views):
        self.views = list(views)

    def __call__(self):
        return self.views[0] if len(self.views) == 1 else self.views.pop(0)


LOCKED = {"present": True, "locked": True, "session_id": "sess-1",
          "pose_id": "pose-1", "refusal": None, "client": {}}
NO_SESSION = {"present": False, "locked": False, "session_id": "",
              "pose_id": "", "refusal": mapping_refusals.NO_SESSION,
              "client": {}}
UNLOCKED = {"present": True, "locked": False, "session_id": "sess-1",
            "pose_id": "pose-1", "refusal": "this camera will not lock EXPOSURE",
            "client": {}}


def _run(items, monkeypatch, *, views=None, executes=None):
    monkeypatch.setattr(capture_runs, "session_view",
                        _Session(views or [LOCKED]))
    calls = []

    async def fake_execute(item):
        calls.append(item)
        got = executes.pop(0) if executes else _outcome("ok")
        return got

    monkeypatch.setattr(capture_queue, "_execute", fake_execute)

    async def no_sleep(_s):
        return None

    run = asyncio.run(capture_queue.run_queue(
        items, label="test", sleep=no_sleep, clock=_fake_clock()))
    return run, calls


def _fake_clock():
    t = {"n": 0.0}

    def clock():
        t["n"] += 0.25
        return t["n"]
    return clock


# ── 1. declaration ─────────────────────────────────────────────────────────

def test_a_declared_queue_is_validated_before_anything_starts():
    items = capture_queue.parse_items([
        {"kind": "map", "room_id": "r1", "label": "whole", "granularity": "whole"},
        {"kind": "commission", "room_id": "r1", "per_fixture": True}])
    assert [i.kind for i in items] == ["map", "commission"]
    assert items[0].name == "whole"


@pytest.mark.parametrize("bad,says", [
    ([], "non-empty"),
    ([{"kind": "nope", "room_id": "r"}], "kind must be"),
    ([{"kind": "map"}], "room_id is required"),
    ([{"kind": "map", "room_id": "r", "granularty": "whole"}], "granularty"),
    ([{"kind": "map", "room_id": "r"}] * (capture_queue.MAX_ITEMS + 1), "capped"),
])
def test_a_typo_is_refused_at_declaration_naming_the_item(bad, says):
    """Not at 3 am on the item nobody reads."""
    with pytest.raises(ValueError) as exc:
        capture_queue.parse_items(bad)
    assert says in str(exc.value)


# ── 2. what it does with each outcome ──────────────────────────────────────

def test_it_carries_on_past_a_refusal(monkeypatch):
    """One bad item must not cost the night."""
    items = capture_queue.parse_items([
        {"kind": "map", "room_id": "r1"},
        {"kind": "commission", "room_id": "r1"},
        {"kind": "map", "room_id": "r2"}])
    run, calls = _run(items, monkeypatch, executes=[
        _outcome("ok"),
        _outcome("refused", kind=capture_runs.KIND_COMMISSION,
                 detail="no-such-mapper is not rendering right now",
                 refusal="composition"),
        _outcome("ok")])
    assert len(calls) == 3
    assert [o.status for o in run.outcomes] == ["ok", "refused", "ok"]
    assert "not rendering" in run.outcomes[1].detail


def test_a_partial_is_kept_and_the_declared_retry_re_runs_it(monkeypatch):
    items = capture_queue.parse_items([
        {"kind": "map", "room_id": "r1", "retries": 1}])
    run, calls = _run(items, monkeypatch, executes=[
        _outcome("partial", refusal="aborted",
                 result={"mapped_count": 3, "summary": "3 mapped"}),
        _outcome("ok", result={"mapped_count": 5, "summary": "5 mapped"})])
    assert len(calls) == 2, "the retry actually ran"
    got = run.outcomes[0]
    assert got.status == "ok" and got.attempts == 2
    assert [a["status"] for a in got.attempt_log] == ["partial", "ok"]
    assert got.attempt_log[0]["mapped_count"] == 3, (
        "the interrupted attempt's own measurements are on the record, not "
        "erased by the attempt that succeeded")


def test_a_refusal_is_never_retried(monkeypatch):
    """An unlocked camera or a released room refuses identically the second
    time and would just spend the night."""
    items = capture_queue.parse_items([
        {"kind": "map", "room_id": "r1", "retries": 3}])
    run, calls = _run(items, monkeypatch, executes=[
        _outcome("refused", refusal="camera_lock", detail="will not lock")])
    assert len(calls) == 1
    assert run.outcomes[0].attempts == 1


def test_a_partial_with_no_declared_retry_stands(monkeypatch):
    items = capture_queue.parse_items([{"kind": "map", "room_id": "r1"}])
    run, calls = _run(items, monkeypatch, executes=[
        _outcome("partial", refusal="aborted", result={"mapped_count": 2})])
    assert len(calls) == 1
    assert run.outcomes[0].status == "partial"


# ── 3. the session it is waiting on ────────────────────────────────────────

def test_no_session_stops_the_queue_and_names_it_once(monkeypatch):
    """Every remaining item is `not_run` with the SAME sentence — burning
    each one's own wait on the same missing camera would turn one lost
    client into an hour of nothing."""
    items = capture_queue.parse_items([
        {"kind": "map", "room_id": "r1", "session_wait_s": 0.0},
        {"kind": "map", "room_id": "r2", "session_wait_s": 0.0},
        {"kind": "map", "room_id": "r3", "session_wait_s": 0.0}])
    run, calls = _run(items, monkeypatch, views=[NO_SESSION])
    assert calls == [], "no light was driven"
    assert [o.status for o in run.outcomes] == ["not_run"] * 3
    assert all("no capture session arrived" in o.detail for o in run.outcomes)
    assert run.notes and "capture client" in run.notes[0]


def test_a_camera_that_will_not_lock_is_the_gates_own_sentence(monkeypatch):
    """Not "no session": the camera is THERE, and what refuses is the
    exposure gate, whose wording this must not restate."""
    items = capture_queue.parse_items([
        {"kind": "map", "room_id": "r1", "session_wait_s": 0.0}])
    run, calls = _run(items, monkeypatch, views=[UNLOCKED])
    assert calls == []
    assert run.outcomes[0].status == "not_run"
    assert run.outcomes[0].detail == UNLOCKED["refusal"]


def test_it_waits_for_a_session_that_arrives_late(monkeypatch):
    items = capture_queue.parse_items([
        {"kind": "map", "room_id": "r1", "session_wait_s": 60.0}])
    run, calls = _run(items, monkeypatch,
                      views=[NO_SESSION, NO_SESSION, LOCKED, LOCKED])
    assert len(calls) == 1 and run.outcomes[0].status == "ok"


# ── 4. the pose ────────────────────────────────────────────────────────────

def test_a_pose_change_mid_queue_is_named_not_silent(monkeypatch):
    """A map that is silently two measurements is the failure the exposure
    gate exists to prevent, arriving by another door."""
    second = {**LOCKED, "pose_id": "pose-2"}
    items = capture_queue.parse_items([
        {"kind": "map", "room_id": "r1"}, {"kind": "map", "room_id": "r2"}])
    run, _calls = _run(items, monkeypatch, views=[LOCKED, second],
                       executes=[_outcome("ok", pose="pose-1"),
                                 _outcome("ok", pose="pose-2")])
    assert run.outcomes[0].pose_changed is False
    assert run.outcomes[1].pose_changed is True
    assert "reopened during this queue" in run.outcomes[1].detail
    assert any("pose-1 -> pose-2" in n for n in run.notes)


# ── 5. the record ──────────────────────────────────────────────────────────

def test_the_record_is_written_after_every_item(monkeypatch):
    """Nobody is watching: a queue killed by a reboot has still explained
    everything it did up to that point."""
    items = capture_queue.parse_items([
        {"kind": "map", "room_id": "r1"}, {"kind": "map", "room_id": "r2"}])
    seen: list[int] = []
    monkeypatch.setattr(capture_runs, "session_view", _Session([LOCKED]))

    async def fake_execute(_item):
        return _outcome("ok")

    monkeypatch.setattr(capture_queue, "_execute", fake_execute)
    real_save = capture_queue.save_queue

    def spy(run, path=None):
        seen.append(len(run.outcomes))
        return real_save(run, path)

    async def no_sleep(_s):
        return None

    asyncio.run(capture_queue.run_queue(items, sleep=no_sleep, save=spy))
    assert seen[:2] == [1, 2], f"written as it went, not at the end: {seen}"
    stored = json.loads(scfg.CAPTURE_QUEUE_FILE.read_text())["queues"]
    assert len(stored) == 1 and len(stored[0]["items"]) == 2
    assert stored[0]["finished_at"] > 0


def test_the_store_is_bounded(monkeypatch):
    for i in range(capture_queue.MAX_STORED_QUEUES + 3):
        run = capture_queue.QueueRun(id=f"q{i}", label="x", started_at=float(i),
                                     items=[])
        capture_queue.save_queue(run)
    stored = json.loads(scfg.CAPTURE_QUEUE_FILE.read_text())["queues"]
    assert len(stored) == capture_queue.MAX_STORED_QUEUES


def test_a_run_summary_never_carries_a_decode_array():
    """The queue log holds a SUMMARY per run; the full record lives in its
    own store. Copying a commissioning run's decodes in here would make the
    one file nobody watches the unbounded one."""
    outcome = capture_runs.RunOutcome(
        kind=capture_runs.KIND_COMMISSION, status="ok",
        result={"verdict": "pass", "mapper_id": "tv-mapper",
                "decodes": [{"huge": list(range(10000))}],
                "captures": [{"also": "huge"}]})
    summary = outcome.summary()
    assert summary["verdict"] == "pass"
    assert "decodes" not in summary and "captures" not in summary


# ── 6. stopping ────────────────────────────────────────────────────────────

def test_stop_marks_the_remaining_items_and_says_how_many(monkeypatch):
    items = capture_queue.parse_items([
        {"kind": "map", "room_id": "r1"}, {"kind": "map", "room_id": "r2"},
        {"kind": "map", "room_id": "r3"}])
    monkeypatch.setattr(capture_runs, "session_view", _Session([LOCKED]))

    async def fake_execute(_item):
        capture_queue.stop()
        return _outcome("ok")

    monkeypatch.setattr(capture_queue, "_execute", fake_execute)

    async def no_sleep(_s):
        return None

    run = asyncio.run(capture_queue.run_queue(items, sleep=no_sleep))
    assert run.outcomes[0].status == "ok"
    assert [o.status for o in run.outcomes[1:]] == ["stopped", "stopped"]
    assert "2 remaining items did not run" in run.outcomes[1].detail
    assert "measured before that is kept" in run.outcomes[1].detail


# ── 7. the routes ──────────────────────────────────────────────────────────

def test_the_route_hands_back_the_id_the_store_will_carry(monkeypatch):
    """A caller that got an id for a queue the runner had not installed yet
    would be reading a different record than the one it started."""
    from fastapi.testclient import TestClient

    from spectra.app import create_app

    monkeypatch.setattr(capture_runs, "session_view", _Session([NO_SESSION]))
    with TestClient(create_app()) as client:
        r = client.post("/api/rooms/capture-queue", json={
            "label": "ids", "items": [
                {"kind": "map", "room_id": "r1", "session_wait_s": 0.0}]})
        assert r.status_code == 200
        started = r.json()["queue"]["id"]
        got = client.get("/api/rooms/capture-queue").json()
        assert got["current"]["id"] == started
        assert got["session"] == NO_SESSION


def test_the_route_refuses_a_bad_declaration_with_400_and_the_sentence():
    from fastapi.testclient import TestClient

    from spectra.app import create_app

    with TestClient(create_app()) as client:
        r = client.post("/api/rooms/capture-queue", json={
            "items": [{"kind": "map", "room_id": "r", "granularty": "whole"}]})
        assert r.status_code == 400 and "granularty" in r.json()["detail"]


def test_the_capture_queue_path_is_not_eaten_by_a_room_id_pattern():
    """It is registered BEFORE rooms.router for exactly this reason."""
    from fastapi.testclient import TestClient

    from spectra.app import create_app

    with TestClient(create_app()) as client:
        assert client.get("/api/rooms/capture-queue").status_code == 200
