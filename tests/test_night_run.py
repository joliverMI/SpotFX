"""THE NIGHT-RUN SEAM — the boundary, the planned end, the export, the
abort, and the auth.

THE ONE THING IN THIS FILE THAT IS NOT NEGOTIABLE, and the reason it is the
first test: a start event arriving while SPECTRA does not hold the room
DECLINES, records the declined night, and does nothing else. The Admiral's
word — "it does not help itself to his room while he sleeps. That boundary
is worth more than an occasional missed night." A test that only checked
the happy path would let that erode silently.

Nothing here touches his room: the light-ownership record is repointed per
test (tests/test_release.py's own pattern), the night stores are repointed
by conftest's autouse `_isolated_night_run`, and the queue is driven with
fakes rather than a real capture run.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from fx import light_ownership as lo
from spectra.services import capture_queue, mapping_refusals, night_run

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
EVENT = {"event": "sleep-window-start", "ts": "2026-09-01T01:00:00Z",
         "source": "home-assistant"}


# ── THE BOUNDARY ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("owner", [lo.RELEASED, lo.SPOT_EFFECTS,
                                   lo.HANDING_OVER])
def test_a_start_while_we_do_not_hold_the_room_declines_by_name(owner):
    _owner(owner)
    night_run.save_declaration("nightly", ITEMS)
    run = _run(night_run.start(EVENT))
    assert run.state == night_run.STATE_DECLINED
    assert run.refusal == "not_owned"
    assert "does not hold the lights" in run.detail
    assert "never takes the room" in run.detail


def test_a_declined_night_is_recorded_durably_and_is_a_normal_outcome():
    """Declined-by-name is a RECORDED OUTCOME, not an error: "did last night
    run?" has to be a read, never a silence indistinguishable from the seam
    being broken."""
    _owner(lo.RELEASED)
    night_run.save_declaration("nightly", ITEMS)
    run = _run(night_run.start(EVENT))

    stored = night_run.load_nights()
    assert [n["run_id"] for n in stored] == [run.id]
    assert stored[0]["state"] == night_run.STATE_DECLINED
    assert stored[0]["trigger"]["event"] == "sleep-window-start"
    assert night_run.status_brief()["state"] == night_run.STATE_DECLINED
    assert night_run.status_brief()["active"] is False


def test_a_declined_night_touches_nothing(monkeypatch):
    """Read the ownership record FIRST, before anything else is resolved or
    driven — a declined night must not be able to have had a side effect."""
    _owner(lo.RELEASED)
    night_run.save_declaration("nightly", ITEMS)

    async def boom():
        raise AssertionError("the declined night read the live device layer")

    monkeypatch.setattr(night_run, "_device_listing", boom)
    monkeypatch.setattr(night_run, "price_items", boom)
    run = _run(night_run.start(EVENT))
    assert run.state == night_run.STATE_DECLINED


def test_no_declared_queue_declines_by_name():
    _owner(lo.SPECTRA)
    run = _run(night_run.start(EVENT))
    assert run.refusal == "no_declared_queue"
    assert run.detail == mapping_refusals.NO_DECLARED_NIGHT_QUEUE
    assert night_run.load_nights()[0]["refusal"] == "no_declared_queue"


def test_a_declaration_is_validated_when_it_is_declared():
    """Refuse a typo while he is awake and has hours to fix it, not at 1am
    on the item nobody reads. `capture_queue.parse_items` is the ONE
    validator — a night queue and a daytime queue are one dialect."""
    with pytest.raises(ValueError) as exc:
        night_run.save_declaration("bad", [{"kind": "nope",
                                            "room_id": "lounge"}])
    assert "kind must be" in str(exc.value)
    assert night_run.load_declaration() is None


# ── THE HARD PLANNED END ───────────────────────────────────────────────────

def test_the_planned_end_is_the_next_0530_house_time():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(night_run.HOUSE_TZ)

    evening = datetime(2026, 9, 1, 22, 0, tzinfo=tz).timestamp()
    small_hours = datetime(2026, 9, 2, 2, 0, tzinfo=tz).timestamp()
    expected = datetime(2026, 9, 2, 5, 30, tzinfo=tz).timestamp()

    assert night_run.planned_end_at(evening) == expected
    assert night_run.planned_end_at(small_hours) == expected
    assert night_run.seconds_until_planned_end(small_hours) == 3.5 * 3600


def test_a_queue_that_cannot_fit_before_his_morning_declines_by_name(
        monkeypatch):
    """The blinds open just after his 05:30 routine and daylight in the
    frame is a CONTAMINANT, so this is a bound and not a preference."""
    _owner(lo.SPECTRA)
    night_run.save_declaration("nightly", ITEMS)

    async def price(items, now=None):
        return {"items": [{"name": "lounge blocks", "seconds": 7200.0}],
                "total_seconds": 7200.0, "window_seconds": 600.0,
                "planned_end": time.time() + 600,
                "planned_end_label": night_run.PLANNED_END_LABEL}

    monkeypatch.setattr(night_run, "price_items", price)
    run = _run(night_run.start(EVENT))
    assert run.refusal == "will_not_fit"
    assert "blinds open" in run.detail
    assert "05:30 house time" in run.detail
    assert run.price["total_seconds"] == 7200.0
    assert night_run.load_nights()[0]["refusal"] == "will_not_fit"


def test_the_per_item_guard_refuses_an_item_that_would_run_into_the_morning():
    """Checked before EVERY item, not once at the top: a queue that fitted
    at 01:00 has not necessarily got room for item six at 05:28."""
    price = {"items": [{"name": "a", "seconds": 60.0},
                       {"name": "b", "seconds": 3600.0}]}
    # 10 minutes left before his morning.
    guard = night_run.fits_guard(price, clock=lambda: 0.0)
    from types import SimpleNamespace
    import spectra.services.night_run as nr
    original = nr.seconds_until_planned_end
    try:
        nr.seconds_until_planned_end = lambda now=None: 600.0
        assert guard(SimpleNamespace(name="a")) is None
        refusal = guard(SimpleNamespace(name="b"))
    finally:
        nr.seconds_until_planned_end = original
    assert refusal and "not started" in refusal
    assert "05:30 house time" in refusal


def test_an_unpriced_item_is_never_vetoed_by_the_bound():
    """The bound cannot judge what it could not price, so it does not
    pretend to. `capture_runs` still applies every real gate."""
    from types import SimpleNamespace
    guard = night_run.fits_guard({"items": [{"name": "a", "seconds": 0.0}]})
    assert guard(SimpleNamespace(name="a")) is None


def test_a_guard_refusal_stops_the_queue_before_the_room_goes_dark():
    """`capture_queue.run_queue`'s guard seam: the refused item and every
    item after it are `not_run` with the guard's own sentence, and the
    queue never reaches the session gate — nothing is held, nothing goes
    dark. Asked BEFORE each item, which is what "never schedule capture
    work past his morning" actually requires."""
    items = capture_queue.parse_items([
        {"kind": "map", "room_id": "r1", "label": "one"},
        {"kind": "map", "room_id": "r2", "label": "two"},
        {"kind": "map", "room_id": "r3", "label": "three"}])

    async def main():
        return await capture_queue.run_queue(
            items, label="night", save=lambda run: {},
            guard=lambda item: "out of time before his morning")

    run = _run(main())
    assert [o.status for o in run.outcomes] == \
        [capture_queue.STATUS_NOT_RUN] * 3
    assert {o.refusal for o in run.outcomes} == {"guard"}
    assert run.notes == ["out of time before his morning"]
    assert run.done


def test_the_guard_never_stops_a_queue_it_allows():
    """A guard that says None changes nothing at all — the seam must be a
    veto, never a gate everything has to opt through."""
    items = capture_queue.parse_items(
        [{"kind": "map", "room_id": "r1", "label": "one",
          "session_wait_s": 0.0}])
    calls = []

    async def main():
        return await capture_queue.run_queue(
            items, label="night", save=lambda run: {},
            guard=lambda item: calls.append(item.name) or None)

    run = _run(main())
    assert calls == ["one"]
    # It got past the guard and stopped at the SESSION gate instead — the
    # real precondition, unchanged and un-weakened by this seam.
    assert run.outcomes[0].refusal == "session"


def test_the_guard_defaults_to_nothing_so_every_existing_caller_is_unchanged():
    import inspect
    sig = inspect.signature(capture_queue.run_queue)
    assert sig.parameters["guard"].default is None


# ── THE EXPORT: TWO LISTS ──────────────────────────────────────────────────

_ENTRIES = [
    {"id": "tv-backlight", "type": "wled",
     "config": {"name": "TV Backlight", "ip_address": "10.0.0.5"},
     "virtuals": ["tv-mapper"]},
    {"id": "porch-rail", "type": "wled",
     "config": {"name": "Porch Rail", "ip_address": "10.0.0.7"},
     "virtuals": ["single-color-effect"]},
    {"id": "hue-lights", "type": "hue",
     "config": {"name": "Hue Lights", "ip_address": "10.0.0.9"},
     "virtuals": ["hues"]},
]


def _shield(monkeypatch, categories, virtuals=()):
    from spectra.services import dark_light, room_controls
    state = room_controls.RoomControlState(
        dark_light_shield_categories=list(categories),
        dark_light_shield_virtuals=list(virtuals))
    monkeypatch.setattr(room_controls, "load_room_controls", lambda: state)
    monkeypatch.setattr(
        dark_light, "_shielded_set",
        lambda cats, virts: ({"hues", "single-color-effect"}
                             if "Singles" in cats else set(virts)))


def test_the_export_names_the_run_fixtures_and_the_standing_lit(monkeypatch):
    """The two lists together are the morning backstop's WHOLE scope. The
    first alone is the gap he already fell into on 2026-09-01."""
    _shield(monkeypatch, ["Singles"])

    async def listing():
        return list(_ENTRIES)

    monkeypatch.setattr(night_run, "_device_listing", listing)
    night_run.current = night_run.NightRun(
        id="abc", state=night_run.STATE_COMPLETE, started=1.0, ended=2.0,
        fixtures=[{"id": "tv-backlight", "name": "TV Backlight",
                   "address": "10.0.0.5"}])

    body = _run(night_run.fixtures_export())
    assert body["run_id"] == "abc"
    assert [f["id"] for f in body["fixtures"]] == ["tv-backlight"]
    standing = {f["id"]: f for f in body["standing_lit_under_dark"]}
    assert set(standing) == {"hue-lights", "porch-rail"}
    assert standing["hue-lights"]["address"] == "10.0.0.9"
    assert standing["porch-rail"]["shielded_via"] == ["single-color-effect"]


def test_the_shield_list_tracks_a_config_change_with_nothing_to_remember(
        monkeypatch):
    """NEVER A HARDCODED LIST: his pending Dark-shield decision has to reach
    River's backstop automatically, not by somebody editing two
    repositories."""
    async def listing():
        return list(_ENTRIES)

    monkeypatch.setattr(night_run, "_device_listing", listing)

    _shield(monkeypatch, ["Singles"])
    before = {f["id"] for f in
              _run(night_run.fixtures_export())["standing_lit_under_dark"]}
    assert before == {"hue-lights", "porch-rail"}

    # He narrows the shield to one virtual.
    _shield(monkeypatch, [], virtuals=["tv-mapper"])
    after = {f["id"] for f in
             _run(night_run.fixtures_export())["standing_lit_under_dark"]}
    assert after == {"tv-backlight"}, \
        "the export did not follow the live shield configuration"


# ── ABORT ──────────────────────────────────────────────────────────────────

class _Session:
    def __init__(self):
        self.closed = False
        self.run_abort = None


def _running_night():
    run = night_run.NightRun(id="live", state=night_run.STATE_RUNNING,
                             started=time.time(),
                             fixtures=[{"id": "tv-backlight"}])
    night_run.current = run
    return run


def _abort(monkeypatch, trigger, *, session=None, running_run=True):
    from spectra.services import capture_runs as runs_mod
    from spectra.services import flare_preview_hold, mapping_session
    reverted = {"called": False}

    async def close_hold():
        reverted["called"] = True
        return {"reverted": True}

    monkeypatch.setattr(flare_preview_hold, "close_hold", close_hold)
    monkeypatch.setattr(mapping_session, "current", session)
    monkeypatch.setattr(runs_mod, "running", lambda: None)
    monkeypatch.setattr(capture_queue, "stop", lambda: running_run)
    return _run(night_run.abort(trigger)), reverted


def test_abort_tells_the_run_in_flight_stops_the_queue_and_reverts_the_hold(
        monkeypatch):
    """Three pieces of EXISTING machinery, in an order that is the
    semantics: tell the run (it stops at its next capture boundary WITH ITS
    PARTIALS KEPT), stop the queue, hand the room back regardless."""
    run = _running_night()
    session = _Session()
    result, reverted = _abort(monkeypatch,
                              {"event": "sleep-ended"}, session=session)

    assert session.run_abort, "the run in flight was never told to stop"
    assert "stopped because the sleep window ended" in session.run_abort
    assert result["stopped_queue"] is True
    assert reverted["called"], "the room was not handed back"
    assert result["hold_reverted_here"] is True
    assert run.state == night_run.STATE_ABORTED
    assert night_run.status_brief()["active"] is False


def test_a_light_touch_aborts_identically():
    """A touched house is his house — Home Assistant forwards both, and they
    are the same act."""
    assert "a light was touched" in mapping_refusals.night_aborted(
        "light-touched")


def test_the_morning_routine_is_an_ordinary_ending_not_an_abort(monkeypatch):
    """His ~05:50 HA routine ends any overnight run whether or not this side
    had a dawn line. A night that ran until his morning ran exactly as long
    as it was ever going to; folding it into `aborted` would make every
    ordinary night read as an incident."""
    run = _running_night()
    session = _Session()
    result, _ = _abort(monkeypatch, {"event": "morning-routine"},
                       session=session)

    assert run.state == night_run.STATE_ENDED_BY_MORNING
    assert result["ended_by_morning"] is True
    assert result["state"] == night_run.STATE_ENDED_BY_MORNING
    assert "ordinary ending, not an interruption" in run.detail
    assert night_run.status_brief()["ended_by_morning"] is True
    assert night_run.status_brief()["state"] == \
        night_run.STATE_ENDED_BY_MORNING


def test_the_abort_response_never_fabricates_an_exit_report(monkeypatch):
    """The exit report is read AT THE LIGHT and takes real network reads, so
    it lands on the record moments later. "pending" is honest; an empty
    report presented as one would not be."""
    _running_night()
    result, _ = _abort(monkeypatch, {"event": "sleep-ended"},
                       session=_Session())
    assert result["exit"] == "pending"


def test_aborting_with_nothing_running_is_a_stated_no_op(monkeypatch):
    night_run.current = None
    result, reverted = _abort(monkeypatch, {"event": "sleep-ended"},
                              running_run=False)
    assert result["aborted"] is False
    assert result["run_id"] is None
    # The room is still handed back — close_hold is idempotent and doing it
    # unconditionally is cheaper than being clever about it.
    assert reverted["called"]


# ── ENGINE STATUS: the house's restore trigger ─────────────────────────────

def test_engine_status_carries_the_night_state_unambiguously():
    """River's binding note: the house restores its own "Dark Music"
    envelope off this. One boolean, derived from ONE set of ended states, so
    nothing on that side has to enumerate our words."""
    night_run.current = None
    idle = night_run.status_brief()
    assert idle["state"] == "idle" and idle["active"] is False

    _running_night()
    assert night_run.status_brief()["active"] is True

    for state in night_run.ENDED_STATES:
        night_run.current.state = state
        assert night_run.status_brief()["active"] is False, state


def test_the_night_state_is_on_the_engine_status_surface(monkeypatch):
    from spectra.services import engine
    _running_night()
    body = engine.status()
    assert body["night_run"]["run_id"] == "live"
    assert body["night_run"]["active"] is True
