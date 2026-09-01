"""THE TWO BUILDS THAT LANDED THE SAME DAY, AT THE SAME CHOKE POINTS.

The night run (#230) and the camera's per-run frame size and manual levers
(#231) both reach `capture_queue.run_queue`, `capture_runs.run_map` /
`run_commission` and `room_mapping.run_mapping` — and they compose rather
than one winning. The rebase merged cleanly; a clean merge is not evidence
that the SEMANTICS composed, which is what this file is for.

Four things, and each was a way one build could have silently swallowed the
other:

  * a queue item can DECLARE the levers, because `QueueItem`'s own contract
    is "the SAME arguments the route takes" and both routes take them — an
    unattended run must not be the one place his camera cannot be told what
    to do;
  * the night's planned-end pricing uses the windows the run will ACTUALLY
    use, which a manual integration time WIDENS. Pricing the declared ones
    would price short against the one bound that must never be over-run;
  * 230's per-item guard still vetoes, and my levers still travel, in the
    same queue;
  * one `MappingResult` carries BOTH records — the witness's verdict and the
    camera's — and neither displaced the other.
"""
from __future__ import annotations

import asyncio

from spectra.services import capture_queue, capture_runs, night_run
from spectra.services import capture_settings as cs
from spectra.services import room_mapping


def _run(coro):
    return asyncio.run(coro)


# ── the levers reach an unattended run ────────────────────────────────────

def test_a_queue_item_can_declare_the_levers_because_the_routes_take_them():
    """`QueueItem`'s own docstring: "everything else is that run's own
    arguments, which are the SAME arguments the route takes — a queue file
    is a list of button presses, not a second dialect". Both run routes
    take `exposure_time`/`gain`, so a queue file has to."""
    items = capture_queue.parse_items([
        {"kind": "map", "room_id": "r1", "exposure_time": 2000, "gain": 64},
        {"kind": "commission", "room_id": "r1", "exposure_time": 5000}])
    assert (items[0].exposure_time, items[0].gain) == (2000, 64)
    assert items[1].exposure_time == 5000 and items[1].gain is None


def test_a_typo_in_a_lever_is_still_refused_at_declaration():
    """The allowlist is derived from the dataclass, so adding a field must
    not have widened it to anything — a queue file with a typo still fails
    at declaration and not at 3 am."""
    try:
        capture_queue.parse_items(
            [{"kind": "map", "room_id": "r1", "exposure_tyme": 2000}])
    except ValueError as exc:
        assert "exposure_tyme" in str(exc)
    else:                                              # pragma: no cover
        raise AssertionError("an unknown field was accepted")


def test_the_levers_actually_travel_from_a_queue_item_to_the_run(monkeypatch):
    """Declared is not the same as delivered. This reads what
    `capture_runs` was CALLED with."""
    seen = {}

    async def fake_map(room_id, **kw):
        seen["map"] = kw
        return capture_runs.RunOutcome(kind=capture_runs.KIND_MAP,
                                       status=capture_runs.STATUS_OK)

    async def fake_commission(room_id, **kw):
        seen["commission"] = kw
        return capture_runs.RunOutcome(kind=capture_runs.KIND_COMMISSION,
                                       status=capture_runs.STATUS_OK)

    monkeypatch.setattr(capture_runs, "run_map", fake_map)
    monkeypatch.setattr(capture_runs, "run_commission", fake_commission)
    item, = capture_queue.parse_items(
        [{"kind": "map", "room_id": "r1", "exposure_time": 2000, "gain": 64}])
    _run(capture_queue._execute(item))                  # noqa: SLF001
    assert seen["map"]["exposure_time"] == 2000
    assert seen["map"]["gain"] == 64
    item, = capture_queue.parse_items(
        [{"kind": "commission", "room_id": "r1", "gain": 8}])
    _run(capture_queue._execute(item))                  # noqa: SLF001
    assert seen["commission"]["gain"] == 8
    assert seen["commission"]["exposure_time"] is None


# ── the night's bound is priced against the real windows ──────────────────

def _price(monkeypatch, emitters=4, **item_fields):
    """Price one map item against a stubbed plan, so the arithmetic under
    test is the only variable."""
    from spectra.models.room_map import RoomMap
    from spectra.services import light_field

    room = RoomMap(name="Living room", carrier_ids=["strip"])

    class _Plan:
        pass

    plan = _Plan()
    plan.emitters = list(range(emitters))

    async def resolve_plan(*_a, **_k):
        return plan

    async def live_virtual_ids(*_a, **_k):
        return ["strip"]

    class _Deps:
        get_virtuals = staticmethod(lambda: {})

    monkeypatch.setattr(light_field, "get_room", lambda _id: room)
    monkeypatch.setattr(room_mapping, "resolve_plan", resolve_plan)
    monkeypatch.setattr(room_mapping, "live_virtual_ids", live_virtual_ids)
    monkeypatch.setattr(room_mapping, "production_deps", lambda _s: _Deps())
    items = capture_queue.parse_items(
        [{"kind": "map", "room_id": "r1", "label": "one", **item_fields}])
    return _run(night_run.price_items(items))


def test_a_long_integration_is_priced_at_the_windows_the_run_will_use(monkeypatch):
    """THE COMPOSITION FAILURE THIS CATCHES. A manual integration time holds
    the camera to 1/E frames a second, so `run_mapping` WIDENS both capture
    windows to still average MIN_FRAMES. Priced at its DECLARED windows, an
    item would be priced short against the 05:30 bound — the one bound that
    must not be over-run, and the reason the guard exists at all."""
    plain = _price(monkeypatch)
    slow = _price(monkeypatch, exposure_time=10_000)     # 1 s integration
    assert slow["total_seconds"] > plain["total_seconds"], (
        f"a 1s integration was priced at {slow['total_seconds']}s, the same "
        f"as {plain['total_seconds']}s without one")
    # and it SAYS why, rather than being a number that is simply bigger
    assert "WIDENED" in (slow["items"][0]["note"] or "")
    # the widened windows are the run's own, from the run's own function
    dark, lit, _r, _n = room_mapping.capture_windows(
        room_mapping.DARK_CAPTURE_S, room_mapping.LIT_CAPTURE_S, 10_000, 5.0)
    assert slow["total_seconds"] == room_mapping.run_estimate_s(
        4, room_mapping.DARK_SETTLE_S, dark, room_mapping.LIT_SETTLE_S, lit)


def test_an_item_with_no_lever_is_priced_exactly_as_before(monkeypatch):
    """The other half of the same contract: a queue declared before the
    levers existed must price identically."""
    priced = _price(monkeypatch)
    assert priced["total_seconds"] == room_mapping.run_estimate_s(
        4, room_mapping.DARK_SETTLE_S, room_mapping.DARK_CAPTURE_S,
        room_mapping.LIT_SETTLE_S, room_mapping.LIT_CAPTURE_S)
    assert not priced["items"][0]["note"]


# ── the guard and the levers in one queue ─────────────────────────────────

def test_the_guard_still_vetoes_while_the_levers_still_travel(monkeypatch):
    """230's per-item veto and #231's per-item camera settings meet on the
    same items. The guard lets the first through and refuses the second;
    the first's levers still arrive, and the second is `not_run` with the
    guard's own sentence."""
    seen = []

    async def fake_map(room_id, **kw):
        seen.append((room_id, kw.get("exposure_time"), kw.get("gain")))
        return capture_runs.RunOutcome(kind=capture_runs.KIND_MAP,
                                       status=capture_runs.STATUS_OK)

    class _Lock:
        locked = True

    class _Session:
        """Only what `capture_runs.session_view` reads — the queue's own
        session gate is not what this test is about, and stubbing more of
        it would be stubbing the thing under test's neighbours."""
        lock = _Lock()
        id = "sess-1"
        pose_id = "pose-1"
        hello: dict = {}

        @staticmethod
        def refusal():
            return None

    monkeypatch.setattr(capture_runs, "run_map", fake_map)
    monkeypatch.setattr(capture_runs, "live_session", lambda: _Session())
    items = capture_queue.parse_items([
        {"kind": "map", "room_id": "r1", "label": "one",
         "exposure_time": 2000, "gain": 64, "session_wait_s": 0.0},
        {"kind": "map", "room_id": "r2", "label": "two",
         "exposure_time": 3000, "session_wait_s": 0.0}])

    async def main():
        return await capture_queue.run_queue(
            items, label="night", save=lambda run: {},
            guard=lambda item: (None if item.name == "one"
                                else "out of time before his morning"))

    run = _run(main())
    assert seen == [("r1", 2000, 64)], \
        "the allowed item ran, and its levers travelled with it"
    assert run.outcomes[0].status == capture_runs.STATUS_OK
    assert run.outcomes[1].status == capture_queue.STATUS_NOT_RUN
    assert run.outcomes[1].refusal == "guard"


# ── one result carries both records ───────────────────────────────────────

def test_a_mapping_result_carries_the_witness_and_the_camera_together():
    """Neither build's record displaced the other's in `as_dict`."""
    result = room_mapping.MappingResult(room_id="r1", ok=True)
    result.camera = {"frame_size": {"width": 320, "height": 180}}
    body = result.as_dict()
    assert body["camera"] == {"frame_size": {"width": 320, "height": 180}}
    assert body["witness"] == {"clean": 0, "contaminated": 0, "unclaimed": 0}


def test_a_commissioning_result_carries_both_too():
    from spectra.services import commissioning
    result = commissioning.RunResult(mapper_id="tv-mapper", ok=True)
    result.camera = {"frame_size": {"width": 1920, "height": 1080}}
    result.witness = {"status": "clean"}
    body = result.as_dict()
    assert body["camera"]["frame_size"]["width"] == 1920
    assert body["witness"] == {"status": "clean"}


def test_the_run_deps_carry_both_builds_seams():
    """`RunDeps` gained the witness/wall seams from one build and is read by
    the other's camera negotiation — one dataclass, both sets of fields."""
    fields = set(room_mapping.RunDeps.__dataclass_fields__)
    assert {"wall", "witness", "witness_sweep"} <= fields
    assert {"session", "get_virtuals", "open_hold", "close_hold"} <= fields
