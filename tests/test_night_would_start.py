"""THE WOULD-START PREFLIGHT — one predicate, both directions, no footprint.

WHY IT EXISTS, in one sentence: his house PREPARES before it starts a night
(River's side fires the "Dark Music" envelope, then pushes start), so on
2026-09-01 the envelope fired, the start declined by name — no declared
queue, the DESIGNED outcome — and his house sat lit while he slept. The
agreed fix (the seam's addenda 7-9) reverses the order: ask first, prepare
only on yes.

THE THING THIS FILE MOST HAS TO PROTECT is not the preflight's answer but
the fact that there is only ONE answer. A preflight computing its own copy
of the gates would be worse than none: it would be a confident wrong answer
at 1am with nobody awake, which is the failure this codebase refuses
everywhere else it measures anything. So the first section is the DRIFT
TEST, and it goes red the moment `start` or `would_start` grows a gate of
its own.

Nothing here touches his room: the ownership record is repointed per test
(tests/test_night_run.py's own pattern), the night stores by conftest's
autouse `_isolated_night_run`, and no queue is ever actually run.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from fx import light_ownership as lo
from spectra.services import (capture_queue, mapping_refusals, night_run)

_ORIGINAL_OWNERSHIP_FILE = lo.OWNERSHIP_FILE


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _own_file(tmp_path):
    lo.OWNERSHIP_FILE = tmp_path / "ownership.json"
    yield
    lo.OWNERSHIP_FILE = _ORIGINAL_OWNERSHIP_FILE


def _owner(owner):
    lo._save(lo.OwnershipRecord(owner=owner))


ITEMS = [{"kind": "map", "room_id": "lounge", "label": "lounge blocks"}]
EVENT = {"event": "sleep-window-start", "ts": "2026-09-02T01:00:00Z",
         "source": "home-assistant"}


def _fits(monkeypatch, *, total=30.0, window=9999.0):
    """Price a queue as comfortably fitting, without resolving a real room.
    `price_items` is the module-level function BOTH callers reach through
    the one gate chain, so patching it here patches exactly one thing."""
    async def price(items, now=None):
        return {"items": [{"name": i.name, "seconds": total} for i in items],
                "total_seconds": total, "window_seconds": window,
                "planned_end": time.time() + window,
                "planned_end_label": night_run.PLANNED_END_LABEL}
    monkeypatch.setattr(night_run, "price_items", price)


# ── THE DRIFT TEST — one predicate, proven two ways ────────────────────────

def test_start_and_would_start_are_computed_by_the_same_function(monkeypatch):
    """THE ONE-PREDICATE GUARANTEE, proven at RUNTIME rather than read off
    the source: replace the single gate chain with a sentinel and watch BOTH
    callers answer with it.

    If either one ever grows its own copy of a gate, that copy will not
    consult this sentinel and this test goes red — which is the whole point.
    An assertion about how the code is written could be satisfied by a
    second implementation sitting quietly beside the first; this one cannot.
    """
    _owner(lo.SPECTRA)
    night_run.save_declaration("nightly", ITEMS)
    calls: list[str] = []

    async def sentinel(*, now=None):
        calls.append("asked")
        return night_run.StartGate(False, "sentinel_refusal",
                                   "a sentence only the shared gate could "
                                   "have produced")

    monkeypatch.setattr(night_run, "evaluate_start", sentinel)

    preflight = _run(night_run.would_start())
    assert preflight["would_start"] is False
    assert preflight["code"] == "sentinel_refusal"
    assert preflight["reason"].startswith("a sentence only the shared gate")

    run = _run(night_run.start(EVENT))
    assert run.state == night_run.STATE_DECLINED
    assert run.refusal == "sentinel_refusal"
    assert run.detail.startswith("a sentence only the shared gate")

    assert calls == ["asked", "asked"], \
        "one of the two callers did not go through the shared gate chain"


def test_neither_caller_keeps_a_private_veto(monkeypatch):
    """The other direction, and the sharper half: with the shared gate
    answering YES in a world where every real gate would say no (the room
    released, nothing declared, a foreign queue running), BOTH callers must
    still say yes.

    A caller that kept a private copy of any gate would veto here — which
    is exactly the drift a preflight cannot survive, and exactly what a
    sentinel returning a refusal cannot catch on its own."""
    _owner(lo.RELEASED)
    monkeypatch.setattr(capture_queue, "running", lambda: True)

    async def sentinel(*, now=None):
        return night_run.StartGate(
            True, price={"total_seconds": 1.0, "window_seconds": 99.0,
                         "planned_end": time.time() + 99,
                         "planned_end_label": night_run.PLANNED_END_LABEL})

    async def nothing(*a, **kw):
        return []

    async def run_queue(items, **kw):
        return kw["run"]

    async def close_hold():
        return {"reverted": True}

    from spectra.services import flare_preview_hold
    monkeypatch.setattr(night_run, "evaluate_start", sentinel)
    monkeypatch.setattr(night_run, "_device_listing", nothing)
    monkeypatch.setattr(night_run, "_live_devices", nothing)
    monkeypatch.setattr(night_run, "run_fixture_rows",
                        lambda items, entries: [])
    monkeypatch.setattr(capture_queue, "run_queue", run_queue)
    monkeypatch.setattr(flare_preview_hold, "close_hold", close_hold)

    async def main():
        preflight = await night_run.would_start()
        run = await night_run.start(EVENT)
        state = run.state
        await night_run._task
        return preflight, state

    preflight, state = _run(main())
    assert preflight["would_start"] is True, \
        "the preflight vetoed a yes the shared gate gave — it kept a gate"
    assert state == night_run.STATE_RUNNING, \
        "the start vetoed a yes the shared gate gave — it kept a gate"


@pytest.mark.parametrize("name", ["start", "would_start"])
def test_neither_caller_carries_a_gate_of_its_own(name):
    """The callgraph half of the same guarantee: no gate NAME appears in
    either caller's own body. A new gate added to one and not the other is
    exactly the drift the preflight cannot survive.

    Read out of the SOURCE FILE BY NAME (`ast`), not by
    `inspect.getsource` — that resolves a live function object's recorded
    line numbers against whatever the file says now, so an edit to the
    module while a long test run is in flight makes it quote a DIFFERENT
    function entirely. Caught doing exactly that here; a proof that can
    accuse the wrong function is not a proof."""
    import ast
    tree = ast.parse(
        open(night_run.__file__, "r", encoding="utf-8").read())
    fn = next(n for n in tree.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == name)
    body = ast.unparse(fn)
    assert "evaluate_start(" in body
    for gate in ("spectra_owns(", "capture_queue.running(",
                 "load_declaration(", "price_items(",
                 "parse_items(", "night_not_owned(",
                 "night_already_running(", "night_will_not_fit(",
                 "NO_DECLARED_NIGHT_QUEUE"):
        assert gate not in body, \
            (f"{name} applies '{gate}' itself — the preflight and the start "
             f"must share ONE gate chain, or they will disagree")


# ── EVERY NO IS THE START'S OWN SENTENCE ───────────────────────────────────
#
# Asserted against what `start()` ACTUALLY RECORDS in the same conditions,
# never against a copy of the sentence written into this file: a test that
# quoted the wording would go green on a preflight that had quietly grown
# its own.

def _both(monkeypatch, **_kw) -> tuple[dict, night_run.NightRun]:
    preflight = _run(night_run.would_start())
    run = _run(night_run.start(EVENT))
    return preflight, run


@pytest.mark.parametrize("owner", [lo.RELEASED, lo.SPOT_EFFECTS,
                                   lo.HANDING_OVER])
def test_not_owned_says_exactly_what_the_start_would_say(owner, monkeypatch):
    """THE BOUNDARY, asked without touching it. The preflight never takes
    the room, asks for it, or queues behind a handover — it only reports
    that the start would not either."""
    _owner(owner)
    night_run.save_declaration("nightly", ITEMS)
    preflight, run = _both(monkeypatch)

    assert preflight["would_start"] is False
    assert preflight["code"] == "not_owned" == run.refusal
    assert preflight["reason"] == run.detail


def test_no_declared_queue_says_exactly_what_the_start_would_say(monkeypatch):
    """THE COMMON CASE, and the one that lit his house up: no queue
    declared. On this answer the envelope never fires, so his house is
    byte-identical by not having been touched."""
    _owner(lo.SPECTRA)
    preflight, run = _both(monkeypatch)

    assert preflight["would_start"] is False
    assert preflight["code"] == "no_declared_queue" == run.refusal
    assert preflight["reason"] == run.detail
    assert preflight["declared"] is False


def test_a_declaration_that_no_longer_parses_declines_identically(
        monkeypatch):
    """A hand-edited file, or a renamed field: a sentence, never a 3am
    traceback — and the same sentence on both sides, including the parser's
    own detail spliced onto the end of it."""
    _owner(lo.SPECTRA)
    night_run.save_declaration("nightly", ITEMS)
    import json
    with open(night_run._queue_path(), "r+", encoding="utf-8") as fh:
        body = json.load(fh)
        body["items"] = [{"kind": "nope", "room_id": "lounge"}]
        fh.seek(0), fh.truncate()
        json.dump(body, fh)

    preflight, run = _both(monkeypatch)
    assert preflight["code"] == "no_declared_queue" == run.refusal
    assert preflight["reason"] == run.detail
    assert "no longer parses" in preflight["reason"]


def test_will_not_fit_says_exactly_what_the_start_would_say(monkeypatch):
    """The blinds open just after his 05:30 routine, so this is a bound and
    not a preference — and the preflight is where the house learns it
    BEFORE preparing an envelope for a night that will not run."""
    _owner(lo.SPECTRA)
    night_run.save_declaration("nightly", ITEMS)
    _fits(monkeypatch, total=7200.0, window=600.0)

    preflight, run = _both(monkeypatch)
    assert preflight["would_start"] is False
    assert preflight["code"] == "will_not_fit" == run.refusal
    assert preflight["reason"] == run.detail
    # The numbers that ARE the reason, carried for River's side to show.
    assert preflight["priced_seconds"] == 7200.0
    assert preflight["window_seconds"] == 600.0


def test_a_night_already_running_declines_by_name(monkeypatch):
    """A duplicate push from a fire-and-forget HA automation is not a fault
    — and it is not a reason to start a second run over the first."""
    _owner(lo.SPECTRA)
    night_run.save_declaration("nightly", ITEMS)
    night_run.current = night_run.NightRun(id="abc123def456",
                                           state=night_run.STATE_RUNNING)
    try:
        preflight, run = _both(monkeypatch)
    finally:
        night_run.current = None

    assert preflight["would_start"] is False
    assert preflight["code"] == "already_running" == run.refusal
    assert preflight["reason"] == run.detail
    assert preflight["reason"] == mapping_refusals.night_already_running(
        "abc123def456")


def test_a_foreign_capture_queue_running_declines_by_name(monkeypatch):
    """Somebody started a queue from the page or the command line. It holds
    the same room and the same camera, so the night leaves it alone —
    stopping HIS queue to run ours would be helping ourselves to more than
    the room."""
    _owner(lo.SPECTRA)
    night_run.save_declaration("nightly", ITEMS)
    monkeypatch.setattr(capture_queue, "running", lambda: True)

    preflight, run = _both(monkeypatch)
    assert preflight["would_start"] is False
    assert preflight["code"] == "already_running" == run.refusal
    assert preflight["reason"] == run.detail
    assert preflight["reason"] == \
        mapping_refusals.NIGHT_FOREIGN_QUEUE_RUNNING


# ── THE HONEST YES ─────────────────────────────────────────────────────────

def test_a_yes_is_followed_by_a_night_that_actually_runs(monkeypatch):
    """A preflight that says no too readily is a wall by another name, so
    the yes path is proven as hard as the no path: yes, then start in the
    same conditions, and the night is RUNNING."""
    _owner(lo.SPECTRA)
    night_run.save_declaration("nightly", ITEMS)
    _fits(monkeypatch)

    async def listing():
        return []

    async def run_queue(items, **kw):
        return kw["run"]

    async def live_devices():
        return []

    async def close_hold():
        return {"reverted": True}

    from spectra.services import flare_preview_hold
    monkeypatch.setattr(night_run, "_device_listing", listing)
    monkeypatch.setattr(night_run, "_live_devices", live_devices)
    monkeypatch.setattr(night_run, "run_fixture_rows",
                        lambda items, entries: [])
    monkeypatch.setattr(capture_queue, "run_queue", run_queue)
    monkeypatch.setattr(flare_preview_hold, "close_hold", close_hold)

    async def main():
        preflight = await night_run.would_start()
        run = await night_run.start(EVENT)
        state_at_start = run.state
        await night_run._task
        return preflight, run, state_at_start

    preflight, run, state_at_start = _run(main())

    assert preflight["would_start"] is True
    assert "reason" not in preflight and "code" not in preflight
    assert preflight["declared"] is True
    assert preflight["items"] == 1
    assert preflight["label"] == "nightly"
    assert preflight["priced_seconds"] == 30.0
    assert state_at_start == night_run.STATE_RUNNING, \
        "the preflight said yes and the real start did not run"
    assert run.state == night_run.STATE_COMPLETE


def test_the_yes_carries_the_planned_end_and_the_price(monkeypatch):
    """Cheap, already computed by the gate chain, and River's side may show
    it: the bound the night is measured against, and what the declared
    queue costs against it."""
    _owner(lo.SPECTRA)
    night_run.save_declaration("nightly", ITEMS)
    _fits(monkeypatch, total=1800.0, window=14400.0)

    preflight = _run(night_run.would_start())
    assert preflight["would_start"] is True
    assert preflight["planned_end"] == pytest.approx(
        night_run.planned_end_at(), abs=1.0)
    assert preflight["planned_end_label"] == night_run.PLANNED_END_LABEL
    assert preflight["priced_seconds"] == 1800.0
    assert preflight["window_seconds"] == 14400.0


# ── ZERO SIDE EFFECTS, PROVEN RATHER THAN CLAIMED ──────────────────────────

@pytest.mark.parametrize("owner", [lo.SPECTRA, lo.RELEASED])
def test_asking_repeatedly_changes_nothing_on_disk(owner, monkeypatch):
    """A pure read. Every store this seam owns is compared BYTE FOR BYTE
    before and after ten calls — including the run store, which is where a
    preflight that recorded its own decline would show up immediately."""
    _owner(owner)
    night_run.save_declaration("nightly", ITEMS)
    _fits(monkeypatch)

    from spectra import config as scfg
    paths = [scfg.NIGHT_QUEUE_FILE, scfg.NIGHT_RUNS_FILE,
             lo.OWNERSHIP_FILE]

    def snapshot():
        out = {}
        for p in paths:
            try:
                with open(p, "rb") as fh:
                    out[str(p)] = fh.read()
            except OSError:
                out[str(p)] = None
        return out

    before = snapshot()
    for _ in range(10):
        _run(night_run.would_start())
    assert snapshot() == before

    # And nothing in memory either: no night was created, and the module's
    # own live-night global is untouched.
    assert night_run.current is None
    assert night_run.last_night() is None
    assert night_run.load_nights() == []


def test_the_preflight_never_reaches_the_room(monkeypatch):
    """It resolves the gates and stops. The device listing, the live device
    layer and the hold are all things a START touches — a read that reached
    any of them would be preparation wearing a different hat."""
    _owner(lo.SPECTRA)
    night_run.save_declaration("nightly", ITEMS)
    _fits(monkeypatch)

    async def boom(*a, **kw):
        raise AssertionError("the preflight reached the room")

    monkeypatch.setattr(night_run, "_device_listing", boom)
    monkeypatch.setattr(night_run, "_live_devices", boom)
    monkeypatch.setattr(night_run, "save_night", boom)

    assert _run(night_run.would_start())["would_start"] is True


# ── THE WIRE ───────────────────────────────────────────────────────────────

def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def test_the_route_is_open_and_answers_the_start_s_own_sentence():
    """OPEN, because River asked for a read with no auth and a read cannot
    start anything — unlike the two pushes, which carry the bearer."""
    _owner(lo.RELEASED)
    with _client() as client:
        resp = client.get("/api/night-run/would-start")
    assert resp.status_code == 200
    body = resp.json()
    assert body["would_start"] is False
    assert body["code"] == "not_owned"
    assert body["reason"] == mapping_refusals.night_not_owned(lo.RELEASED)
    # The read did not record a night.
    assert night_run.load_nights() == []
