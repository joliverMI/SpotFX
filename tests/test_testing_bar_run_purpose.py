"""THE BANNER NAMES THE RUN THAT IS HOLDING THE ROOM RIGHT NOW.

Reported live 2026-09-05 by the Admiral, watching the app during a real
proof run: "the ownership banner shows an OUTDATED test reason."

THE DEFECT, in one sentence: the TESTING IN PROGRESS bar's headline had two
possible sources for what was being tested, and neither of them was the
run. The auto fold could only say that SOMETHING held the room ("a flare
preview is driving your lights" — the label a mapping run trips, because a
map holds the room through `flare_preview_hold.open_program_hold`), and a
DECLARED take is a ttl-bounded human claim that outlives the run it was
made for. So a second run starting inside an earlier declaration wore the
EARLIER run's reason, for up to `test_session.MAX_TTL_S`, while a different
run held his room.

Proven here, not asserted:

  1. THE REPORTED CASE, end to end — a second run inside a still-live
     declaration for a first run shows the SECOND run's purpose. The same
     test also drives the PRE-FIX headline rule against the same state and
     proves it goes RED, because a regression test that cannot fail on the
     defect it was written for is decoration.
  2. EACH OF THE FOUR TAKE PATHS stamps its own purpose — observed from
     INSIDE the real `capture_runs.run_*` body, so this is the run saying
     what it is while it holds the lock, not a helper being called.
  3. THE STAMP CANNOT OUTLIVE ITS RUN, on the success path and on the
     raising one. A purpose that survives its run is the defect itself.
  4. `since` BELONGS TO WHATEVER THE HEADLINE NAMES — this run's words
     beside an earlier declaration's clock is the same lie in a hat.
  5. NOTHING ELSE MOVED: with no run live, a declaration still owns the
     headline exactly as it did before.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from spectra.models.room_map import RoomMap
from spectra.services import capture_runs, test_session


# ── the two headline rules, extracted so both can be driven ──────────────
# Kept verbatim in shape with `whoLine` in
# spectra/web/src/components/TestingBar.tsx; the .mjs check script drives
# the real TypeScript. This side proves the SERVER hands the bar what it
# needs to reach the right answer.

def headline(st: dict) -> str:
    """The shipped rule: a live run wins, then a declaration, then auto."""
    run = next((s for s in st["sources"] if s["kind"] == test_session.KIND_RUN),
               None)
    if run is not None:
        return f"{run['label']} ({run['detail']})" if run["detail"] else run["label"]
    if st["declared"]:
        return f"{st['declared']['actor']} — {st['declared']['reason']}"
    auto = [s for s in st["sources"] if s["kind"] == test_session.KIND_AUTO]
    return auto[0]["label"] if auto else "someone (undeclared)"


def headline_before_the_fix(st: dict) -> str:
    """The rule as it shipped before this fix: a declaration always won."""
    if st["declared"]:
        return f"{st['declared']['actor']} — {st['declared']['reason']}"
    auto = [s for s in st["sources"] if s["kind"] == test_session.KIND_AUTO]
    return auto[0]["label"] if auto else "someone (undeclared)"


@pytest.fixture(autouse=True)
def _quiet_other_sources(monkeypatch):
    """Every OTHER auto source off, so each test is about the run tier
    alone and cannot pass because an unrelated module left a hold behind.
    The capture-run source itself is kept — it is the subject."""
    from spectra.services import (flare_preview_hold, preview_pause,
                                  room_preview)
    monkeypatch.setattr(preview_pause, "active", lambda: False)
    monkeypatch.setattr(flare_preview_hold, "active", lambda: False)
    monkeypatch.setattr(room_preview, "active", lambda: False)
    yield
    # The stamp is a module global; a test that leaves one behind would make
    # the next one pass or fail for a reason nobody can find.
    capture_runs._clear()


class _Locked:
    """The run lock as it reads while a run holds it."""

    def locked(self) -> bool:
        return True


@pytest.fixture
def held(monkeypatch):
    """Report the run lock as held, the way it is during a real run."""
    monkeypatch.setattr(capture_runs, "_run_lock", _Locked())


# ── 1. the reported case ────────────────────────────────────────────────

def test_a_second_run_shows_its_own_purpose_not_the_first_runs(held):
    """His evening, exactly: a declaration made for run A, still inside its
    ttl, while run B holds the room."""
    test_session.declare("firstmate", "commissioning proof of the TV mapper",
                         3600)
    capture_runs._begin(capture_runs.KIND_MAP, "Living Room", "living-room",
                        "living-room")

    st = test_session.status()
    assert headline(st) == "mapping the light field on Living Room"
    assert "commissioning proof" not in headline(st)


def test_the_harness_goes_red_on_the_defect_it_was_written_for(held):
    """The same state, judged by the PRE-FIX rule, still shows the stale
    reason — so this test can genuinely fail on the bug."""
    test_session.declare("firstmate", "commissioning proof of the TV mapper",
                         3600)
    capture_runs._begin(capture_runs.KIND_MAP, "Living Room", "living-room",
                        "living-room")

    st = test_session.status()
    assert (headline_before_the_fix(st)
            == "firstmate — commissioning proof of the TV mapper")
    assert headline_before_the_fix(st) != headline(st)


def test_it_goes_red_on_the_unfixed_SERVER_half_too(held, monkeypatch):
    """The other half of the same defect: with the seam publishing nothing
    — `capture_runs` as it was — the fold has no run to prefer and the
    shipped rule falls straight back to the stale declaration. So this
    suite fails whichever half is missing, not only the display rule."""
    monkeypatch.setattr(capture_runs, "current_run", lambda: None)
    test_session.declare("firstmate", "commissioning proof of the TV mapper",
                         3600)
    capture_runs._begin(capture_runs.KIND_MAP, "Living Room", "living-room",
                        "living-room")

    st = test_session.status()
    assert not [s for s in st["sources"] if s["kind"] == test_session.KIND_RUN]
    assert headline(st) == "firstmate — commissioning proof of the TV mapper"


def test_the_declaration_is_not_discarded_only_dethroned(held):
    """Nothing is lost: the declared take is still on the payload and still
    in `sources`, so a reader who wants the human's note can have it."""
    test_session.declare("firstmate", "commissioning proof of the TV mapper",
                         3600)
    capture_runs._begin(capture_runs.KIND_MAP, "Living Room", "living-room",
                        "living-room")

    st = test_session.status()
    assert st["declared"]["reason"] == "commissioning proof of the TV mapper"
    kinds = [s["kind"] for s in st["sources"]]
    assert test_session.KIND_RUN in kinds and test_session.KIND_DECLARED in kinds


# ── 2. each take path stamps its own purpose ────────────────────────────

def _room(room_id="living-room", name="Living Room"):
    return RoomMap(room_id=room_id, name=name, carrier_ids=["tv-mapper"])


class _Result:
    """The smallest thing each run body reads back off its inner call."""
    ok = True
    partial = False
    reason = ""
    refusal = ""
    pose_id = "pose-1"
    seconds = 1.0
    references: list = []
    problems: list = []
    notes: list = []

    def as_dict(self):
        return {}


class _Sess:
    id = "sess-1"

    async def apply_camera(self, _req):
        return None

    async def await_frame_size(self, _size, _wait):
        return (320, 180)

    async def await_camera(self, _wait):
        return None

    def camera_lock_view(self):
        return {}

    def observed_fps(self):
        return 5.0

    def frame_refusal(self, _size):
        return ""

    def camera_refusal(self):
        return ""


@pytest.fixture
def seam(monkeypatch):
    """Drive the REAL `capture_runs.run_*` bodies with the light, the
    camera and the measurement stubbed out — everything this fix touches
    (the lock, the stamp, the clear) is the module's own."""
    from spectra.services import (commissioning, exposure_test, light_field,
                                  pose_fingerprint, room_mapping)
    monkeypatch.setattr(light_field, "get_room", lambda _id: _room())
    monkeypatch.setattr(light_field, "put_room", lambda _r: None)
    monkeypatch.setattr(capture_runs, "live_session", lambda: _Sess())
    monkeypatch.setattr(capture_runs, "_gate",
                        lambda kind, target, room_id: None)

    async def _no_preflight(*_a, **_k):
        return None
    monkeypatch.setattr(capture_runs, "_preflight", _no_preflight)
    monkeypatch.setattr(room_mapping, "production_deps", lambda _s: object())
    monkeypatch.setattr(commissioning, "save_result", lambda _r: {})

    seen: dict = {}

    def _observe(*_a, **_k):
        # WHAT THE BAR WOULD SAY, read from INSIDE the run body — while
        # this run holds the lock and is genuinely the thing driving lights.
        seen["run"] = capture_runs.current_run()
        return _Result()

    async def _inner(*a, **k):
        return _observe(*a, **k)

    monkeypatch.setattr(room_mapping, "run_mapping", _inner)
    monkeypatch.setattr(commissioning, "run_commission", _inner)
    monkeypatch.setattr(exposure_test, "compare_regimes", _inner)
    monkeypatch.setattr(pose_fingerprint, "measure", _inner)
    monkeypatch.setattr(pose_fingerprint, "camera_identity", lambda _s: {})
    return seen


@pytest.mark.parametrize("call,kind,purpose", [
    (lambda: capture_runs.run_map("living-room"),
     capture_runs.KIND_MAP, "mapping the light field on Living Room"),
    (lambda: capture_runs.run_commission("living-room"),
     capture_runs.KIND_COMMISSION, "a commissioning pass on tv-mapper"),
    (lambda: capture_runs.run_exposure_test("living-room"),
     capture_runs.KIND_EXPOSURE, "an exposure comparison on Living Room"),
    (lambda: capture_runs.run_pose_fingerprint("living-room"),
     capture_runs.KIND_FINGERPRINT, "a pose fingerprint on Living Room"),
])
def test_every_take_path_stamps_its_own_purpose(seam, call, kind, purpose):
    """All four, at the one seam — so a fifth kind added there inherits it
    rather than needing to remember."""
    asyncio.run(call())
    run = seam["run"]
    assert run is not None, "the run published nothing while it held the room"
    assert run.kind == kind
    assert run.purpose == purpose
    assert run.room_id == "living-room"


def test_the_run_source_the_bar_reads_carries_that_same_purpose(seam,
                                                                monkeypatch):
    """The whole way through: the stamp a real run body sets is what the
    fold puts in front of him."""
    heard: dict = {}

    async def _inner(*_a, **_k):
        heard["st"] = test_session.status()
        return _Result()
    from spectra.services import room_mapping
    monkeypatch.setattr(room_mapping, "run_mapping", _inner)

    asyncio.run(capture_runs.run_map("living-room"))
    assert headline(heard["st"]) == "mapping the light field on Living Room"


# ── 3. the stamp cannot outlive its run ─────────────────────────────────

def test_the_stamp_is_gone_the_moment_the_run_is(seam):
    asyncio.run(capture_runs.run_map("living-room"))
    assert capture_runs.current_run() is None
    assert test_session.status()["testing"] == "no"


def test_a_run_that_raises_still_stops_claiming_the_room(seam, monkeypatch):
    """The `finally` is what makes this true; a purpose surviving a crashed
    run is the defect wearing its own clothes."""
    from spectra.services import room_mapping

    async def _boom(*_a, **_k):
        raise RuntimeError("the room fell over")
    monkeypatch.setattr(room_mapping, "run_mapping", _boom)

    with pytest.raises(RuntimeError):
        asyncio.run(capture_runs.run_map("living-room"))
    assert capture_runs.current_run() is None
    assert capture_runs.running() is None


def test_running_still_reports_exactly_what_it_always_did(seam, monkeypatch):
    """`running()` feeds `GET /rooms`' `running_room` — its values are
    unchanged by the stamp riding alongside them."""
    seen: list = []
    from spectra.services import commissioning, room_mapping

    async def _inner(*_a, **_k):
        seen.append(capture_runs.running())
        return _Result()
    monkeypatch.setattr(room_mapping, "run_mapping", _inner)
    monkeypatch.setattr(commissioning, "run_commission", _inner)

    asyncio.run(capture_runs.run_map("living-room"))
    asyncio.run(capture_runs.run_commission("living-room"))
    assert seen == ["living-room", "living-room/commission"]


# ── 4. since belongs to whatever the headline names ─────────────────────

def test_since_follows_the_run_not_the_older_declaration(held):
    declared = test_session.declare("firstmate", "an earlier proof", 3600)
    time.sleep(0.02)
    capture_runs._begin(capture_runs.KIND_COMMISSION, "tv-mapper",
                        "living-room", "living-room/commission")

    st = test_session.status()
    assert st["since_ms"] > declared["since_ms"]
    assert st["since_ms"] == pytest.approx(
        capture_runs.current_run().started_ms)


def test_since_falls_back_to_the_declaration_when_no_run_is_live():
    declared = test_session.declare("firstmate", "driving fixtures by hand",
                                    3600)
    st = test_session.status()
    assert st["since_ms"] == declared["since_ms"]


# ── 5. nothing else moved ───────────────────────────────────────────────

def test_a_declaration_alone_still_owns_the_headline():
    """The declared half is for work the app cannot see — with no run
    live, it is still the best answer there is."""
    test_session.declare("an external agent", "driving fixtures", 60)
    st = test_session.status()
    assert headline(st) == "an external agent — driving fixtures"
    assert headline(st) == headline_before_the_fix(st)


def test_a_quiet_room_publishes_no_run_source():
    st = test_session.status()
    assert st["testing"] == "no"
    assert st["sources"] == []
    assert st["since_ms"] is None


def test_an_unnamed_future_kind_names_itself_rather_than_inventing(held):
    """RUN_PURPOSES is the phrase book; a kind added to the seam without an
    entry says its own name instead of borrowing somebody else's."""
    capture_runs._begin("spectrograph", "Living Room", "living-room",
                        "living-room")
    assert (capture_runs.current_run().purpose
            == "a spectrograph run on Living Room")
