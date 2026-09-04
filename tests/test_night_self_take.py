"""THE SELF-TAKING NIGHT — the lever, the gates, and giving the room back.

WHAT THIS FILE MOST HAS TO PROTECT, and it is the first section: the
UNARMED path. `SPECTRA_NIGHT_SELF_TAKE` is absent on every deploy this build
lands on, and while it is absent a start arriving on a released room must
decline with `night_not_owned`'s own sentence, byte for byte, exactly as it
did before any of this existed. The worst case has to equal the status quo —
tonight simply not running — and a flag that leaks is the one way this build
can be worse than not shipping it.

The emitted-light proof of the QUIET take (zero non-black frames between the
take and the hold, on the real render pipeline) is its own file:
tests/test_quiet_take_dark.py. The CRASH path is
tests/test_night_take_crash_recovery.py, in a fresh interpreter, because
cold-start ordering is not something a warm pytest process can speak to.

Nothing here touches his room: the ownership record is repointed per test
(tests/test_night_run.py's own pattern), the night stores and the take
snapshot by conftest's autouse `_isolated_night_run`, and every handover and
release is a fake — no live stack is ever built.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from conftest import measuring_session
from fx import light_ownership as lo
from spectra import config as scfg
from spectra.services import (capture_queue, capture_runs, mapping_refusals,
                              night_run, night_take)

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
EVENT = {"event": "sleep-window-start", "ts": "2026-09-04T01:12:00Z",
         "source": "home-assistant"}


def _armed(monkeypatch, on=True):
    monkeypatch.setenv("SPECTRA_NIGHT_SELF_TAKE", "1" if on else "0")


def _fits(monkeypatch):
    async def price(items, now=None):
        return {"items": [{"name": i.name, "seconds": 30.0} for i in items],
                "total_seconds": 30.0, "window_seconds": 9999.0,
                "planned_end": time.time() + 9999,
                "planned_end_label": night_run.PLANNED_END_LABEL}
    monkeypatch.setattr(night_run, "price_items", price)


class _FakeHandover:
    """`run_handover` with the record moved and NOTHING driven. It records
    the arguments it was called with, which is where the QUIET flag is
    asserted — the light-level proof of what quiet MEANS is the other
    file's job."""

    def __init__(self, *, fail=False):
        self.calls: list[dict] = []
        self.fail = fail

    async def __call__(self, to_world, sides, *, quiet=False, **kw):
        self.calls.append({"to": to_world, "quiet": quiet, "sides": sides})
        if self.fail:
            raise RuntimeError("the stack would not come up")
        lo._save(lo.OwnershipRecord(owner=to_world))
        return lo.load()


class _FakeRelease:
    """`release_room`, recording WHEN it was called against a shared clock so
    the ordering assertions are about real sequence, not about who asserted
    first."""

    def __init__(self, log, *, verified=True, problems=()):
        self.log = log
        self.verified = verified
        self.problems = list(problems)
        self.calls: list[str] = []

    async def __call__(self, reason="release"):
        self.calls.append(reason)
        self.log.append("release")
        lo._save(lo.OwnershipRecord(owner=lo.RELEASED))

        class _Result:
            record = lo.load()
            from_world = lo.SPECTRA

        _Result.verified = self.verified
        _Result.problems = self.problems
        return _Result()


def _self_taking_night(monkeypatch, *, fail_take=False, blow_up=False,
                       release=None, log=None):
    """A whole armed night with a fake take and a fake release: the seam's
    own decisions, none of its I/O."""
    from spectra.services import flare_preview_hold

    log = log if log is not None else []
    _armed(monkeypatch)
    _owner(lo.RELEASED)
    night_run.save_declaration("nightly", ITEMS)
    measuring_session(monkeypatch)
    _fits(monkeypatch)

    handover = _FakeHandover(fail=fail_take)
    monkeypatch.setattr(night_take, "take_room",
                        _take_through(handover))
    release = release if release is not None else _FakeRelease(log)
    monkeypatch.setattr("spectra.services.release.release_room", release)

    async def listing():
        return [{"id": "tv-backlight", "type": "wled",
                 "config": {"name": "TV Backlight", "ip_address": "10.0.0.5"},
                 "virtuals": ["tv-mapper"]}]

    async def live_devices():
        return []

    async def run_queue(items, **kw):
        log.append("queue")
        if blow_up:
            raise RuntimeError("the queue blew up")
        return kw["run"]

    async def close_hold():
        log.append("close_hold")
        return {"reverted": True}

    async def build_exit(run):
        log.append("exit_report")

        class _R:
            def as_dict(self):
                return {"verified_at_the_light": True, "summary": "dark"}
        return _R()

    monkeypatch.setattr(night_run, "_device_listing", listing)
    monkeypatch.setattr(night_run, "_live_devices", live_devices)
    monkeypatch.setattr(night_run, "run_fixture_rows",
                        lambda items, entries: [])
    monkeypatch.setattr(night_run, "build_exit", build_exit)
    monkeypatch.setattr(night_run, "save_night", _logging_save(log))
    monkeypatch.setattr(capture_queue, "run_queue", run_queue)
    monkeypatch.setattr(flare_preview_hold, "close_hold", close_hold)
    return handover, release, log


def _take_through(handover):
    """Point `night_run`'s take at the REAL `take_room` driving a fake
    handover — the snapshot, the released-only check and the announcement
    are all the production ones; only the thing that would touch lights is
    replaced. The original is bound here, before the patch, or the wrapper
    would call itself."""
    real = night_take.take_room

    async def take(run_id, **kw):
        return await real(run_id, sides={}, run_handover=handover)
    return take


def _logging_save(log):
    real = night_run.save_night

    def save(run, path=None):
        log.append(f"save:{run.state}")
        return real(run, path)
    return save


# ── 1. THE UNARMED PATH IS TODAY'S PATH, BYTE FOR BYTE ─────────────────────

@pytest.mark.parametrize("owner", [lo.RELEASED, lo.SPOT_EFFECTS,
                                   lo.HANDING_OVER])
def test_unarmed_a_start_on_a_room_we_do_not_hold_declines_exactly_as_before(
        monkeypatch, owner):
    """THE HEADLINE SAFETY PROPERTY. With the lever absent, the sentence,
    the machine word, the state and the record are the ones this seam has
    always produced — and the sentence is compared against
    `mapping_refusals.night_not_owned`'s own output rather than a copy of
    its text, so a reworded refusal cannot pass this by accident."""
    monkeypatch.delenv("SPECTRA_NIGHT_SELF_TAKE", raising=False)
    _owner(owner)
    night_run.save_declaration("nightly", ITEMS)
    measuring_session(monkeypatch)

    run = _run(night_run.start(EVENT))

    # The owner as the RECORD reads it: `handing-over` with no handover
    # block is not a settled owner, and `load()` falls back to the shipped
    # default — which is a fact about the record, not about this gate.
    settled = lo.load().owner
    assert run.state == night_run.STATE_DECLINED
    assert run.refusal == "not_owned"
    assert run.detail == mapping_refusals.night_not_owned(settled)
    assert run.take == {}, "an unarmed night recorded a take block"
    assert lo.load().owner == settled, "an unarmed night moved the record"
    assert night_take.load_snapshot() is None, \
        "an unarmed night wrote a pre-take snapshot"


def test_unarmed_the_preflight_says_no_and_says_the_lever_is_off(monkeypatch):
    """A `not_owned` no is the DESIGNED outcome unarmed and a genuine
    problem armed, so the preflight publishes which deploy this is — nobody
    should have to read an env var over his shoulder to know."""
    monkeypatch.delenv("SPECTRA_NIGHT_SELF_TAKE", raising=False)
    _owner(lo.RELEASED)
    night_run.save_declaration("nightly", ITEMS)
    measuring_session(monkeypatch)

    out = _run(night_run.would_start())

    assert out["would_start"] is False
    assert out["code"] == "not_owned"
    assert out["self_take"] == {"armed": False, "holding": False}
    assert "will_take_room" not in out


def test_unarmed_nothing_in_night_take_can_be_reached(monkeypatch):
    """The lever is asked at CALL time, in one place, and the gate chain is
    the only thing that consults it. Flipping the environment mid-process
    flips the answer with nothing to restart — which is also what makes the
    test above and the test below able to disagree in one interpreter."""
    monkeypatch.delenv("SPECTRA_NIGHT_SELF_TAKE", raising=False)
    assert night_take.armed() is False
    monkeypatch.setenv("SPECTRA_NIGHT_SELF_TAKE", "1")
    assert night_take.armed() is True
    monkeypatch.setenv("SPECTRA_NIGHT_SELF_TAKE", "true")
    assert night_take.armed() is False, \
        "only the literal 1 arms this — a truthy-looking value must not"


# ── 2. ARMED: WHICH ROOMS MAY BE TAKEN, AND WHICH MAY NOT ──────────────────

@pytest.mark.parametrize("owner", [lo.SPOT_EFFECTS, lo.HANDING_OVER])
def test_armed_it_still_never_displaces_a_live_writer(monkeypatch, owner):
    """`released` is the ONLY owner state a take is attempted from. A room
    held by the older process, or mid-handover, declines exactly as it
    always did: displacing a live writer while he sleeps is not what he
    asked for."""
    _armed(monkeypatch)
    _owner(owner)
    night_run.save_declaration("nightly", ITEMS)
    measuring_session(monkeypatch)

    run = _run(night_run.start(EVENT))

    settled = lo.load().owner
    assert run.refusal == "not_owned"
    assert run.detail == mapping_refusals.night_not_owned(settled)
    assert lo.load().owner == settled
    assert night_take.load_snapshot() is None


def test_armed_a_released_room_is_taken_quietly_and_the_take_is_recorded(
        monkeypatch):
    """THE TAKE. The handover runs in QUIET mode — the flag the other file
    proves the meaning of at the light — and the record carries both the
    owner it found and the timestamp, which is half of Order 22."""
    handover, _release, _log = _self_taking_night(monkeypatch)

    run = _run(_start_and_finish())

    assert run.state == night_run.STATE_COMPLETE
    assert handover.calls, "the night never asked for the room"
    assert handover.calls[0]["to"] == lo.SPECTRA
    assert handover.calls[0]["quiet"] is True, \
        "the night took the room with the SHOW ON — this is the 1am defect"
    assert run.take["self_taken"] is True
    assert run.take["owner_before"] == lo.RELEASED
    assert run.take["taken_at"] > 0
    assert run.take["quiet"] is True


def test_the_snapshot_names_the_same_night_the_record_does(monkeypatch):
    """THE THREAD CRASH RECOVERY HANGS ON, and it was got wrong once: the
    take mints an id for its snapshot and the record mints one for itself.
    Two ids and the cold start looks up a night nobody recorded — the
    crashed night's record stays at "running" forever, no terminal state is
    re-posted, and River's re-dark never fires. One id, minted before the
    take, used for both."""
    seen: dict = {}
    real_take = night_take.take_room

    async def handover(to_world, sides, *, quiet=False, **kw):
        seen["snapshot"] = night_take.load_snapshot()
        lo._save(lo.OwnershipRecord(owner=to_world))
        return lo.load()

    async def take(run_id, **kw):
        return await real_take(run_id, sides={}, run_handover=handover)

    from spectra.services import flare_preview_hold

    _armed(monkeypatch)
    _owner(lo.RELEASED)
    night_run.save_declaration("nightly", ITEMS)
    measuring_session(monkeypatch)
    _fits(monkeypatch)
    monkeypatch.setattr(night_take, "take_room", take)
    # NO LIVE ACCESS, EVER: the real `release_room` reaches an external
    # LedFX over HTTP and runs `systemctl is-active`. Its own behaviour is
    # proven elsewhere in this file; here it only has to move the record.
    monkeypatch.setattr("spectra.services.release.release_room",
                        _FakeRelease([]))

    async def listing():
        return []

    async def close_hold():
        return {"reverted": True}

    async def build_exit(run):
        class _R:
            def as_dict(self):
                return {"verified_at_the_light": True, "summary": "dark"}
        return _R()

    monkeypatch.setattr(night_run, "_device_listing", listing)
    monkeypatch.setattr(night_run, "_live_devices", listing)
    monkeypatch.setattr(night_run, "run_fixture_rows", lambda i, e: [])
    monkeypatch.setattr(night_run, "build_exit", build_exit)
    monkeypatch.setattr(flare_preview_hold, "close_hold", close_hold)
    monkeypatch.setattr(capture_queue, "run_queue",
                        lambda items, **kw: _noop(kw["run"]))

    run = _run(_start_and_finish())

    assert seen["snapshot"]["run_id"] == run.id, (
        "the pre-take snapshot names a different night from the record — a "
        "crash would leave that record stuck at running forever")


async def _noop(value):
    return value


def test_armed_the_snapshot_is_written_before_the_record_moves(monkeypatch):
    """A crash IN the take must be recoverable too, so the pre-take snapshot
    lands before anything moves. Proven by making the handover itself look
    at the disk."""
    seen: dict = {}

    async def handover(to_world, sides, *, quiet=False, **kw):
        seen["snapshot"] = night_take.load_snapshot()
        seen["owner_at_handover"] = lo.load().owner
        lo._save(lo.OwnershipRecord(owner=to_world))
        return lo.load()

    _armed(monkeypatch)
    _owner(lo.RELEASED)
    measuring_session(monkeypatch)

    result = _run(night_take.take_room("night-1", sides={},
                                       run_handover=handover))

    assert result.took is True
    assert seen["snapshot"] is not None, \
        "the take moved the record before recording what it found"
    assert seen["snapshot"]["owner_before"] == lo.RELEASED
    assert seen["snapshot"]["run_id"] == "night-1"
    assert seen["owner_at_handover"] == lo.RELEASED


def test_a_take_that_fails_declines_the_night_and_leaves_no_snapshot(
        monkeypatch):
    """THE WORST CASE IS THE STATUS QUO. `run_handover` lands single-owner
    on every failure path, so a take that will not come up leaves the room
    released with nothing lit — and the night is a plain recorded decline,
    which is exactly a night that did not run."""
    handover, _release, _log = _self_taking_night(monkeypatch, fail_take=True)

    run = _run(night_run.start(EVENT))

    assert run.state == night_run.STATE_DECLINED
    assert run.refusal == "take_failed"
    assert "released" in run.detail
    assert run.take["self_taken"] is False
    assert night_take.load_snapshot() is None, \
        "a failed take left a snapshot a cold start would act on"


def test_the_take_refuses_if_the_room_stopped_being_free_after_the_preflight(
        monkeypatch):
    """The named staleness window: he took the room back between the
    preflight's yes and the start arriving. Checked again at the take, where
    it is a refusal rather than an argument."""
    _armed(monkeypatch)
    _owner(lo.SPOT_EFFECTS)

    async def handover(*a, **kw):
        raise AssertionError("the take ran on a room it does not own")

    result = _run(night_take.take_room("night-1", sides={},
                                       run_handover=handover))

    assert result.took is False
    assert result.refusal == "not_released"
    assert night_take.load_snapshot() is None


def test_a_stop_arriving_during_the_take_hands_the_room_straight_back(
        monkeypatch):
    """A TOUCHED HOUSE IS HIS HOUSE, and the self-taking night widened the
    one window where that could be missed: the take spends real seconds
    holding the room before there is any night for an abort to stop, and
    `capture_queue.stop()` is a no-op with nothing running. He gets up
    mid-handover, and without this the night goes on holding a room he is
    standing in."""
    from spectra.services import flare_preview_hold

    _armed(monkeypatch)
    _owner(lo.RELEASED)
    night_run.save_declaration("nightly", ITEMS)
    measuring_session(monkeypatch)
    _fits(monkeypatch)
    log: list = []
    release = _FakeRelease(log)
    monkeypatch.setattr("spectra.services.release.release_room", release)

    real_take = night_take.take_room

    async def handover(to_world, sides, *, quiet=False, **kw):
        # HE STIRS while the handover is in flight — arriving through the
        # real abort endpoint, with no night for it to stop.
        await night_run.abort({"event": "sleep-ended"}, grace_s=0.0)
        lo._save(lo.OwnershipRecord(owner=to_world))
        return lo.load()

    async def take(run_id, **kw):
        return await real_take(run_id, sides={}, run_handover=handover)

    async def close_hold():
        return {"reverted": True}

    async def nothing():
        return []

    monkeypatch.setattr(night_take, "take_room", take)
    monkeypatch.setattr(night_run, "_device_listing", nothing)
    monkeypatch.setattr(night_run, "_live_devices", nothing)
    monkeypatch.setattr(flare_preview_hold, "close_hold", close_hold)
    monkeypatch.setattr(capture_queue, "run_queue",
                        lambda items, **kw: _boom())

    run = _run(night_run.start(EVENT))

    assert run.state == night_run.STATE_DECLINED
    assert run.refusal == "stopped_during_take"
    assert ("a light was touched in the house while SPECTRA was still "
            "taking the room") not in run.detail  # this one was sleep-ended
    assert "the sleep window ended while SPECTRA was still taking the room" \
        in run.detail
    assert release.calls, "the room he got up in was kept"
    assert lo.load().owner == lo.RELEASED
    assert night_take.load_snapshot() is None
    # BOTH ENDS STILL, even for a night that never ran: taken, then given
    # back within seconds.
    events = [a["event"] for a in run.take["announce"]]
    assert events == [night_take.EVENT_TAKEN, night_take.EVENT_GIVEN_BACK]


async def _boom():
    raise AssertionError("a night stopped during its take ran its queue")


# ── 3. THE INSTRUMENT GATE ─────────────────────────────────────────────────

@pytest.mark.parametrize("view,why", [
    ({"present": False}, "nothing connected"),
    ({"present": True, "locked": False}, "connected but not locked"),
    ({"present": True, "locked": True,
      "calibration_refusal": "a browser may aim but may not measure. "},
     "a browser"),
    ({"present": True, "locked": True,
      "unable": "this machine has no camera. "}, "impaired"),
])
def test_a_night_that_cannot_measure_declines_before_it_takes_anything(
        monkeypatch, view, why):
    """A ROOM MUST NEVER BE TAKEN FOR A NIGHT THAT CANNOT MEASURE — and by
    the same argument never held dark all night for one, which is why this
    gate applies to a self-taking night and an ordinary one alike."""
    _armed(monkeypatch)
    _owner(lo.RELEASED)
    night_run.save_declaration("nightly", ITEMS)
    monkeypatch.setattr(capture_runs, "session_view", lambda: dict(view))

    async def handover(*a, **kw):
        raise AssertionError(f"a room was taken with {why}")

    monkeypatch.setattr(night_take, "take_room", _take_through(handover))

    run = _run(night_run.start(EVENT))

    assert run.state == night_run.STATE_DECLINED
    assert run.refusal == "no_instrument"
    assert "nothing can measure tonight" in run.detail
    assert lo.load().owner == lo.RELEASED
    assert night_take.load_snapshot() is None


def test_the_instrument_gate_carries_the_sessions_own_sentence(monkeypatch):
    """It never describes his camera a second time. The view already
    resolves which of the several things is wrong, through
    `capture_source`/`mapping_refusals`' own functions — composing a rival
    description here is how two surfaces start telling him different
    stories about one camera."""
    own = ("This is a browser session, and a browser is a viewfinder. ")
    _owner(lo.SPECTRA)
    night_run.save_declaration("nightly", ITEMS)
    monkeypatch.setattr(capture_runs, "session_view",
                        lambda: {"present": True, "locked": True,
                                 "calibration_refusal": own})

    out = _run(night_run.would_start())

    assert out["would_start"] is False
    assert out["code"] == "no_instrument"
    assert own.strip() in out["reason"]


def test_the_instrument_gate_sits_after_the_declaration_and_before_pricing(
        monkeypatch):
    """ORDER, asserted rather than described: "no queue declared" is the
    cheaper and more actionable answer when both are true, and pricing (a
    real read of rooms and plans) is never spent on a night that has
    nothing to look through."""
    _owner(lo.SPECTRA)
    monkeypatch.setattr(capture_runs, "session_view",
                        lambda: {"present": False})

    async def price(items, now=None):
        raise AssertionError("a night with no camera was priced")

    monkeypatch.setattr(night_run, "price_items", price)

    # No declaration at all: the declaration's answer wins.
    assert _run(night_run.would_start())["code"] == "no_declared_queue"

    # Declared, but nothing to look through: the instrument's answer wins,
    # and pricing was never reached (the raise above proves it).
    night_run.save_declaration("nightly", ITEMS)
    assert _run(night_run.would_start())["code"] == "no_instrument"


def test_a_camera_read_that_blows_up_declines_rather_than_500ing(monkeypatch):
    """Home Assistant fires and forgets at 1am, so a traceback out of this
    gate is a night nobody can explain in the morning. An unreadable view is
    treated as "we cannot say anything can measure" — the same answer as no
    camera, landing as an ordinary recorded decline."""
    _armed(monkeypatch)
    _owner(lo.RELEASED)
    night_run.save_declaration("nightly", ITEMS)

    def boom():
        raise RuntimeError("the health store is corrupt")

    monkeypatch.setattr(capture_runs, "session_view", boom)

    run = _run(night_run.start(EVENT))

    assert run.state == night_run.STATE_DECLINED
    assert run.refusal == "no_instrument"
    assert "could not be read" in run.detail
    assert lo.load().owner == lo.RELEASED
    assert night_take.load_snapshot() is None


# ── 4. THE PREFLIGHT SAYS WHAT A YES MEANS FOR HIS ROOM ────────────────────

def test_an_armed_yes_on_a_released_room_says_it_will_take_it(monkeypatch):
    _armed(monkeypatch)
    _owner(lo.RELEASED)
    night_run.save_declaration("nightly", ITEMS)
    measuring_session(monkeypatch)
    _fits(monkeypatch)

    out = _run(night_run.would_start())

    assert out["would_start"] is True
    assert out["will_take_room"] is True
    assert out["self_take"]["armed"] is True


def test_a_yes_on_a_room_we_already_hold_takes_nothing(monkeypatch):
    """The original meaning of a yes, unchanged: SPECTRA already holds the
    lights and the night changes nothing about whose they are."""
    _armed(monkeypatch)
    _owner(lo.SPECTRA)
    night_run.save_declaration("nightly", ITEMS)
    measuring_session(monkeypatch)
    _fits(monkeypatch)

    out = _run(night_run.would_start())

    assert out["would_start"] is True
    assert out["will_take_room"] is False


def test_the_preflight_still_writes_nothing_when_it_would_take_the_room(
        monkeypatch):
    """A preflight that took a room would be the worst thing in this seam.
    Ten calls, and the record, the stores and the snapshot are all
    untouched."""
    _armed(monkeypatch)
    _owner(lo.RELEASED)
    night_run.save_declaration("nightly", ITEMS)
    measuring_session(monkeypatch)
    _fits(monkeypatch)

    before = lo.load().owner
    runs_before = night_run.load_nights()
    for _ in range(10):
        assert _run(night_run.would_start())["would_start"] is True

    assert lo.load().owner == before
    assert night_run.load_nights() == runs_before
    assert night_take.load_snapshot() is None


# ── 5. GIVING IT BACK, ON EVERY EXIT ───────────────────────────────────────

def test_a_finished_night_gives_the_room_back_and_announces_both_ends(
        monkeypatch):
    log: list = []
    _handover, release, log = _self_taking_night(monkeypatch, log=log)

    run = _run(_start_and_finish())

    assert release.calls, "a self-taken night kept the room"
    assert lo.load().owner == lo.RELEASED
    assert night_take.load_snapshot() is None
    assert run.take["given_back"] is True
    assert run.take["given_back_at"] >= run.take["taken_at"]
    assert run.take["why"] == night_take.WHY_FINISHED
    events = [a["event"] for a in run.take["announce"]]
    assert events == [night_take.EVENT_TAKEN, night_take.EVENT_GIVEN_BACK], \
        "Order 22 is BOTH ends — taken and given back, never one"


def test_a_failed_night_still_gives_the_room_back(monkeypatch):
    """A night that blew up must not leave his room held at 3am."""
    _handover, release, _log = _self_taking_night(monkeypatch, blow_up=True)

    run = _run(_start_and_finish())

    assert run.state == night_run.STATE_FAILED
    assert release.calls
    assert lo.load().owner == lo.RELEASED
    assert run.take["given_back"] is True


@pytest.mark.parametrize("event,state,why", [
    ("sleep-ended", night_run.STATE_ABORTED, night_take.WHY_ABORTED),
    ("light-touched", night_run.STATE_ABORTED, night_take.WHY_ABORTED),
    (mapping_refusals.MORNING_ROUTINE, night_run.STATE_ENDED_BY_MORNING,
     night_take.WHY_MORNING),
])
def test_every_abort_flavour_gives_the_room_back(monkeypatch, event, state,
                                                 why):
    """A touched house is his house — and on a self-taken night his house is
    not his again until the room is RELEASED, not merely until the hold
    reverts. His morning routine is an ORDINARY ending and takes the same
    path with its own recorded state."""
    _handover, release, _log = _self_taking_night(monkeypatch)

    async def main():
        run = await night_run.start(EVENT)
        out = await night_run.abort({"event": event}, grace_s=0.0)
        return run, out

    run, out = _run(main())

    assert out["state"] == state
    assert out["gave_room_back"] is True
    assert out["room_owner"] == lo.RELEASED
    assert release.calls
    assert lo.load().owner == lo.RELEASED
    assert run.take["why"] == why


def test_the_abort_order_is_stop_then_release_then_state_then_announce(
        monkeypatch):
    """THE ORDER IS THE SEMANTICS: the room is his again BEFORE he is told
    it is. River's own re-dark rides the night's terminal state, so a state
    that landed before the release would tell the house to restore over a
    room SPECTRA still held."""
    log: list = []
    _handover, _release, log = _self_taking_night(monkeypatch, log=log)

    async def main():
        await night_run.start(EVENT)
        log.clear()
        return await night_run.abort({"event": "sleep-ended"}, grace_s=0.0)

    _run(main())

    assert "close_hold" in log, log
    assert "release" in log, log
    stamped = [i for i, entry in enumerate(log)
               if entry.startswith("save:aborted")]
    assert stamped, log
    assert log.index("close_hold") < log.index("release") < stamped[0], (
        "stop, release, THEN the terminal state — got " + repr(log))


def test_the_give_back_is_idempotent_across_the_abort_and_the_run_task(
        monkeypatch):
    """The abort path and the run task's own finish both reach it, in an
    order nothing guarantees. The second call finds no snapshot and does
    nothing — the room is released once, not twice."""
    _handover, release, _log = _self_taking_night(monkeypatch)

    async def main():
        await night_run.start(EVENT)
        await night_run.abort({"event": "sleep-ended"}, grace_s=0.0)
        await night_run._task

    _run(main())

    assert len(release.calls) == 1, \
        f"the room was released {len(release.calls)} times"


def test_a_night_that_did_not_take_the_room_never_gives_it_back(monkeypatch):
    """Whose the lights are afterwards is not this seam's to change. A night
    that ran on a room SPECTRA already held leaves the record exactly as it
    found it."""
    from spectra.services import flare_preview_hold

    _armed(monkeypatch)
    _owner(lo.SPECTRA)
    night_run.save_declaration("nightly", ITEMS)
    measuring_session(monkeypatch)
    _fits(monkeypatch)

    released: list = []

    async def release(reason="x"):
        released.append(reason)
        raise AssertionError("a night that took nothing released the room")

    monkeypatch.setattr("spectra.services.release.release_room", release)

    async def listing():
        return []

    async def live_devices():
        return []

    async def run_queue(items, **kw):
        return kw["run"]

    async def close_hold():
        return {"reverted": True}

    async def build_exit(run):
        class _R:
            def as_dict(self):
                return {"verified_at_the_light": True, "summary": "dark"}
        return _R()

    monkeypatch.setattr(night_run, "_device_listing", listing)
    monkeypatch.setattr(night_run, "_live_devices", live_devices)
    monkeypatch.setattr(night_run, "run_fixture_rows", lambda i, e: [])
    monkeypatch.setattr(night_run, "build_exit", build_exit)
    monkeypatch.setattr(capture_queue, "run_queue", run_queue)
    monkeypatch.setattr(flare_preview_hold, "close_hold", close_hold)

    run = _run(_start_and_finish())

    assert run.state == night_run.STATE_COMPLETE
    assert run.take == {}
    assert released == []
    assert lo.load().owner == lo.SPECTRA
    # AND IT COST NOTHING: the holding check is a file stat and every step
    # after it — including capturing the driver handles, which is a real
    # device read — happens only on the far side of it. This path is
    # byte-identical to before the self-taking build existed.
    assert run.instruments is None, (
        "a night that took nothing paid for the give-back's instrument "
        "capture anyway")


def test_a_give_back_that_cannot_be_confirmed_is_reported_not_swallowed(
        monkeypatch):
    """`release_room` always lands the record at `released`; whether reality
    matched is a separate answer, and it is the one that has to survive to
    breakfast."""
    log: list = []
    release = _FakeRelease(log, verified=False,
                           problems=["Hue light(s) not confirmed off: hall"])
    _self_taking_night(monkeypatch, release=release, log=log)

    run = _run(_start_and_finish())

    assert run.take["given_back"] is True
    assert run.take["verified"] is False
    assert "hall" in run.take["problems"][0]
    assert "COULD NOT BE CONFIRMED" in run.take["detail"]
    # And the snapshot is still dropped: the record HAS landed at released,
    # so a snapshot left behind would make the next cold start try to give
    # back a room it no longer holds.
    assert night_take.load_snapshot() is None


def test_a_room_taken_back_by_him_is_named_rather_than_released_over(
        monkeypatch):
    """He reached for the ownership bar himself mid-night. There is nothing
    of ours holding his room any more — say so, rather than releasing over
    the top of whatever has it now."""
    _owner(lo.RELEASED)
    night_take.save_snapshot(run_id="night-1", owner_before=lo.RELEASED)
    lo._save(lo.OwnershipRecord(owner=lo.SPOT_EFFECTS))

    async def release(reason="x"):
        raise AssertionError("released over a room somebody else holds")

    result = _run(night_take.give_back(why=night_take.WHY_ABORTED,
                                       run_id="night-1", release=release))

    assert result.given_back is False
    assert result.to == lo.SPOT_EFFECTS
    assert "did not need giving back" in result.detail
    assert night_take.load_snapshot() is None
    assert lo.load().owner == lo.SPOT_EFFECTS


# ── 6. THE ANNOUNCEMENT IS SILENT, DURABLE AND ON THE POLLED SURFACE ───────

def test_the_take_and_the_give_back_are_both_on_the_polled_status(
        monkeypatch):
    """River's HA sensors read this. "Spectra took the room 01:12, gave it
    back 02:30, released clean" has to be arithmetic on her side, which is
    why both ends are unix timestamps rather than prose."""
    _self_taking_night(monkeypatch)

    _run(_start_and_finish())
    brief = night_run.status_brief()

    assert brief["take"]["self_taken"] is True
    assert brief["take"]["taken_at"] > 0
    assert brief["take"]["given_back"] is True
    assert brief["take"]["given_back_at"] >= brief["take"]["taken_at"]
    assert brief["take"]["given_back_to"] == lo.RELEASED
    assert brief["take"]["holding"] is False
    assert brief["self_take"]["armed"] is True
    assert brief["active"] is False


def test_holding_is_read_from_the_durable_snapshot_not_from_memory(
        monkeypatch):
    """"Is SPECTRA holding his room right now" must be answerable by a
    process that has just come back from a crash and has no in-memory
    record at all — which is exactly when it matters most."""
    night_run.current = None
    assert night_run.status_brief()["take"]["holding"] is False

    night_take.save_snapshot(run_id="night-1", owner_before=lo.RELEASED)

    assert night_run.status_brief()["take"]["holding"] is True
    assert night_run.self_take_brief()["holding"] is True


def test_nothing_on_this_path_makes_a_sound(monkeypatch):
    """An announce at 01:12 would wake him and defeat the night, so both
    ends are a durable record and a status field and NOTHING else. Asserted
    against the source: no notification, push, speech or HA call anywhere in
    the module."""
    import pathlib
    body = pathlib.Path(night_take.__file__).read_text()
    body = body.split('"""', 2)[2]        # past the module docstring
    for forbidden in ("notify", "notification", "push_", "speak", "tts",
                      "httpx", "requests.", "post("):
        assert forbidden not in body, \
            f"the announcement path grew a {forbidden!r} — it must stay silent"


# ── 7. THE HOUSE ENVELOPE IS NOT OURS TO FIRE ──────────────────────────────

def test_the_self_taking_flow_fires_no_house_scene(monkeypatch):
    """SETTLED WITH RIVER, 2026-09-03: the self-taking flow fires NO "Dark
    Music". His sleeping house IS the envelope, the quiet take darkens only
    SPECTRA's own fixtures, and a stray house light is the contamination
    witness's business. Asserted against the source so nobody adds it back
    helpfully."""
    import pathlib
    body = pathlib.Path(night_take.__file__).read_text()
    body = body.split('"""', 2)[2]
    for forbidden in ("dark music", "dark_music", "scene.turn_on",
                      "scene.create", "home_assistant", "hass"):
        assert forbidden not in body.lower(), \
            f"the self-taking flow reached for {forbidden!r} — the house " \
            f"lights are Home Assistant's"


# ── 8. THE OTHER TWO SOURCES OF LIGHT, ON THE REAL SIDE ────────────────────
#
# tests/test_quiet_take_dark.py proves the FIRST one at the emitted light:
# the stack comes up black. These two are the others, and each would put
# light in his room on its own even with every virtual black.

def test_a_quiet_take_never_switches_the_engine_live(tmp_path, monkeypatch):
    """`engine.go_live` is what points the drift conductor and the response
    engine at real lights. A quiet take must never call it — and `fx_seam`
    must still work, because it routes on the OWNERSHIP RECORD plus the
    facade host and not on the engine's executor, which is the whole reason
    the night's capture writes still land.

    The REAL `SpectraSide` against the headless harness (dummy device,
    silenced audio, temp record) — tests/test_process_split.py's own rig."""
    from fx import headless, light_ownership as real_lo
    from spectra.services import engine, fx_seam, handover
    from spectra.services.live_host import live

    monkeypatch.setattr(real_lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")
    real_lo._save(real_lo.OwnershipRecord(owner=real_lo.RELEASED))
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(
        str(config_dir),
        initial_effect={"type": "singleColor", "config": {"color": "#ffffff"}})

    async def scenario():
        side = handover.SpectraSide(config_dir=str(config_dir),
                                    open_audio=False, quiet=True)
        record = await handover.run_handover(
            real_lo.SPECTRA, {real_lo.SPECTRA: side}, grace_s=0.0, quiet=True)
        try:
            assert record.owner == real_lo.SPECTRA
            assert live.active, "a quiet take did not bring the stack up"
            assert engine.executor.mode == "recording", (
                "the quiet take switched the engine LIVE — the show would "
                "start moving colour in his sleeping room within seconds")
            # AND THE ROOM IS WRITABLE: the night's own capture writes go
            # through fx_seam, which asks the ownership record, not the
            # engine. A take that came up dark and unusable would be no
            # take at all.
            virtuals = await fx_seam.get_virtuals()
            assert virtuals, "the quiet take left nothing writable"
        finally:
            engine.go_dark()
            await live.deactivate()

    _run(scenario())


def test_an_ordinary_take_back_does_switch_the_engine_live(tmp_path,
                                                           monkeypatch):
    """THE CONTROL for the test above, kept in the file: without it, "the
    engine stayed dark" could be true because this rig never switches it
    live at all."""
    from fx import headless, light_ownership as real_lo
    from spectra.services import engine, handover
    from spectra.services.live_host import live

    monkeypatch.setattr(real_lo, "OWNERSHIP_FILE", tmp_path / "ownership.json")
    real_lo._save(real_lo.OwnershipRecord(owner=real_lo.RELEASED))
    headless.silence_audio()
    config_dir = tmp_path / "fx-live"
    headless.write_headless_config(str(config_dir))

    async def scenario():
        side = handover.SpectraSide(config_dir=str(config_dir),
                                    open_audio=False)
        await handover.run_handover(real_lo.SPECTRA,
                                    {real_lo.SPECTRA: side}, grace_s=0.0)
        try:
            assert engine.executor.mode == "facade", (
                "the ordinary take-back did not go live, so the quiet "
                "test's assertion proves nothing")
        finally:
            engine.go_dark()
            await live.deactivate()

    _run(scenario())


def test_a_quiet_take_does_not_apply_the_stored_ambient_intent(monkeypatch):
    """A HOLD IS HUE BULBS LIT. `reconcile_now` exists to land a hold he
    pressed for while the room was released — and a quiet take that ran it
    would come up dark and then light his Hue at ambient colour a moment
    later. It is SKIPPED, not forgotten: the intent stays in
    RoomControlState and the next ordinary take-back applies it."""
    from fx import light_ownership as real_lo
    from spectra.services import ambient_music_gate, handover

    reconciles: list = []

    async def reconcile_now(*, wait=True):
        reconciles.append(wait)
        return {}

    monkeypatch.setattr(ambient_music_gate, "reconcile_now", reconcile_now)

    class _Side:
        name = real_lo.SPECTRA

        async def readiness_problems(self):
            return []

        async def activate(self):
            pass

        async def verify_active(self):
            return True

        async def quiesce(self):
            pass

        async def verify_quiesced(self):
            return True

        async def deactivate(self):
            pass

    async def scenario(quiet):
        real_lo._save(real_lo.OwnershipRecord(owner=real_lo.RELEASED))
        await handover.run_handover(real_lo.SPECTRA,
                                    {real_lo.SPECTRA: _Side()},
                                    grace_s=0.0, quiet=quiet)

    _run(scenario(True))
    assert reconciles == [], (
        "the quiet take ran the ambient reconcile — a stored hold would "
        "light his Hue bulbs moments after a take that came up dark")

    # THE CONTROL: an ordinary take-back still applies it, unchanged.
    _run(scenario(False))
    assert reconciles == [False], (
        "the ordinary take-back stopped applying the stored ambient "
        "intent — this build must not have taken that away")


async def _start_and_finish():
    run = await night_run.start(EVENT)
    if night_run._task is not None:
        await night_run._task
    return run
