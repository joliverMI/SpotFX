"""THE BROWSER IS A VIEWFINDER — proven in both directions, plus the
aiming path it keeps.

WHAT SETTLED THIS (2026-09-01). Three of the four failures that cost him an
evening are properties of the browser itself and no amount of our code above
one changes them: his Brio exposes no gain through a browser at all, its
read-back echoes the REQUEST rather than reporting the sensor (three
integration times a factor of twenty apart, all accepted, all agreed, and
the measured light never moved), and its auto exposure keeps re-adapting
underneath. The fourth was a cached tab running old capture code, and it
dies here for free: calibration cannot ride stale browser code because it
cannot ride the browser at all.

WHAT IS PROVED HERE, and the second half of each pair is why the first is
not just a wall:

  * every CALIBRATION-GRADE kind — map, commissioning, exposure comparison,
    pose fingerprint — refuses a browser-established session BY NAME, with
    nothing driven and nothing written;
  * the SAME harness with the SAME camera, differing only in what the client
    calls itself, passes straight through on a native session;
  * the route answers 409 with the SENTENCE, not a status word;
  * the sentence says WHY in his terms and WHAT to use, so it is an
    instruction rather than a rule;
  * a CALIBRATION run and the unattended QUEUE inherit it, because they go
    through the one seam — and the queue's wait says which camera was
    actually there instead of "no session";
  * THE AIMING PATH IS UNTOUCHED, end to end on the real session and the
    real routes: a browser connects, streams frames, has its lock read,
    serves the preview frame, and reports itself as first-class for aiming;
  * and the harness goes RED when the gate is removed — a proof that cannot
    fail on the defect it was written for is decoration.
"""
from __future__ import annotations

import asyncio
import base64

import numpy as np
import pytest

from spectra.models.room_map import AxisCalibration, Point, RoomMap
from spectra.services import capture_queue, capture_runs, capture_source
from spectra.services import capture_settings as cs
from spectra.services import (commissioning, exposure_test, mapping_refusals,
                              room_mapping)

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))

#: What a browser page says about itself in `hello`: a user agent and no
#: `client` field at all. This is the real shape — `RoomsPage.tsx` sends
#: exactly these keys — and it is deliberately NOT "client: browser": a
#: session that has not said what it is must be refused too, or an unknown
#: client is promoted by silence.
BROWSER_HELLO = {"user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)"}
NATIVE_HELLO = {"client": capture_source.NATIVE_CLIENT, "host": "capture-pi",
                "pose_name": "the north shelf", "client_version": "1.2.3"}


class _Session(cs.SessionCameraDouble):
    """A connected, LOCKED, entirely healthy camera session. The only thing
    that varies between the two directions of every proof below is what it
    calls itself — which is the whole claim: nothing about the camera, the
    room or the run differs."""
    pose_id = "pose-1"
    id = "sess-1"
    run_abort = None
    keep_full_frames = False
    lever_verdict = None
    closed = False

    class lock:
        exposure_locked = True
        white_balance_locked = True
        exposure_mode = "manual"
        white_balance_mode = "manual"
        locked = True

        @staticmethod
        def as_dict():
            return {"exposure_locked": True, "white_balance_locked": True,
                    "exposure_time": None, "gain": None,
                    "exposure_time_range": [3.0, 2047.0],
                    "manual_refusals": []}

    def __init__(self, hello: dict):
        self.hello = dict(hello)
        self.camera_configs = []
        self.dark_next = True
        self.camera_lock = dict(self.lock.as_dict())

    def refusal(self):
        return None

    def _camera_clock(self):
        return 0.0

    def _camera_lock_view(self):
        return dict(self.camera_lock)

    async def gather(self, seconds, min_frames=1):
        lit = not self.dark_next
        self.dark_next = not self.dark_next
        grid = np.full((36, 64), 200.0 if lit else 5.0, dtype=float)
        return [grid, grid], [220, 6]

    async def gather_full(self, seconds, min_frames=1):
        return await self.gather(seconds, min_frames)


def _room():
    return RoomMap(name="Living room", carrier_ids=["strip"], axis=AXIS)


def _virtual(device):
    return {"active": True, "pixel_count": 20, "config": {"grouping": 1},
            "segments": [[device, 0, 19, False]],
            "effect": {"type": "singleColor", "config": {}}}


def _deps(session, held: list):
    async def get_virtuals():
        return {"strip": _virtual("strip-fixture")}

    async def chains():
        return {"strip": [{"id": "strip-fixture", "type": "wled"}]}

    async def open_hold(*a, **k):
        # THE ROOM BEING ASKED FOR AT ALL, recorded — so "his room was never
        # taken dark" is an observation rather than an inference from a
        # status word. A refusal at the gate happens before this.
        held.append(True)
        return {"held": True}

    async def close_hold():
        return None

    async def sleep(_s):
        return None

    return room_mapping.RunDeps(
        session=session, get_virtuals=get_virtuals, carrier_devices=chains,
        open_hold=open_hold, close_hold=close_hold, sleep=sleep,
        clock=lambda: 0.0, spectra_owns=lambda: True)


def _wire(monkeypatch, sess, room, held):
    monkeypatch.setattr(capture_runs, "live_session", lambda: sess)
    monkeypatch.setattr(capture_runs.light_field, "get_room", lambda _id: room)
    monkeypatch.setattr(capture_runs.light_field, "put_room", lambda _r: None)
    monkeypatch.setattr(capture_runs.room_mapping, "production_deps",
                        lambda s: _deps(s, held))


# ── 1. every calibration-grade kind, both directions ───────────────────────

async def _run_kind(kind: str, room):
    """Drive one kind through the seam every caller uses."""
    if kind == capture_runs.KIND_MAP:
        return await capture_runs.run_map(room.id, granularity="whole")
    if kind == capture_runs.KIND_COMMISSION:
        return await capture_runs.run_commission(room.id, mapper_id="strip")
    if kind == capture_runs.KIND_EXPOSURE:
        return await capture_runs.run_exposure_test(room.id, exposure_time=400)
    return await capture_runs.run_pose_fingerprint(room.id)


@pytest.mark.parametrize("kind", capture_runs.CALIBRATION_GRADE)
def test_a_browser_session_refuses_every_calibration_grade_kind(monkeypatch, kind):
    """THE DEMOTION. Nothing is driven and nothing is written — the refusal
    happens at `_gate`, before the room is asked for."""
    room = _room()
    held: list = []
    _wire(monkeypatch, _Session(BROWSER_HELLO), room, held)

    # If the gate ever stopped firing, these would run for real; failing
    # loudly here beats reaching a light.
    for mod, name in ((room_mapping, "run_mapping"),
                      (commissioning, "run_commission"),
                      (exposure_test, "compare_regimes")):
        monkeypatch.setattr(mod, name, _never)

    outcome = asyncio.run(_run_kind(kind, room))
    assert outcome.status == capture_runs.STATUS_REFUSED
    assert outcome.refusal == "browser_session", outcome.detail
    assert held == [], "his room was never even asked for"
    assert outcome.result == {}, "nothing was measured"
    assert outcome.lever == {}, "and the camera was never tested"


def _never(*a, **k):
    raise AssertionError("a calibration-grade run reached a light on a "
                         "browser session")


@pytest.mark.parametrize("kind", capture_runs.CALIBRATION_GRADE)
def test_the_same_run_on_a_native_session_goes_straight_through(monkeypatch, kind):
    """THE OTHER DIRECTION, and it is the half that proves this is a gate
    rather than a wall: identical room, identical camera, identical harness
    — only `hello` differs."""
    room = _room()
    held: list = []
    sess = _Session(NATIVE_HELLO)
    _wire(monkeypatch, sess, room, held)
    # The lever self-test drives its own light and is proven in its own
    # file; here it stands aside so the CLIENT-KIND gate is what is measured.
    monkeypatch.setattr(capture_runs, "_preflight", _no_preflight)

    reached: list = []
    monkeypatch.setattr(room_mapping, "run_mapping", _reaches(reached, "map"))
    monkeypatch.setattr(commissioning, "run_commission",
                        _reaches(reached, "commission"))
    monkeypatch.setattr(exposure_test, "compare_regimes",
                        _reaches(reached, "exposure"))
    monkeypatch.setattr(capture_runs, "run_pose_fingerprint",
                        _pose_reaches(reached))

    outcome = asyncio.run(_run_kind(kind, room))
    assert reached, f"{kind} never reached its run"
    assert outcome is not None
    assert getattr(outcome, "refusal", "") != "browser_session"


async def _no_preflight(*a, **k):
    return None


def _reaches(log, word):
    async def run(*a, **k):
        log.append(word)
        return _Result()
    return run


def _pose_reaches(log):
    async def run(*a, **k):
        log.append("fingerprint")
        return capture_runs.RunOutcome(kind=capture_runs.KIND_FINGERPRINT,
                                       status=capture_runs.STATUS_OK)
    return run


class _Result:
    """The minimum a run result has to look like for the seam to wrap it."""
    ok = True
    partial = False
    reason = ""
    refusal = ""
    pose_id = "pose-1"
    seconds = 1.0

    def as_dict(self):
        return {"ok": True}


# ── 2. the harness must go RED on the defect it was written for ────────────

def test_without_the_gate_a_browser_maps_the_room(monkeypatch):
    """THE PROOF THAT THE PROOF WORKS. Remove the demotion — and only the
    demotion — and the very same browser session runs a map to completion.
    That is the world before this change, reproduced on demand, so the tests
    above cannot be passing for some other reason."""
    room = _room()
    held: list = []
    _wire(monkeypatch, _Session(BROWSER_HELLO), room, held)
    monkeypatch.setattr(capture_source, "calibration_grade", lambda _s: True)
    monkeypatch.setattr(capture_runs, "_preflight", _no_preflight)
    reached: list = []
    monkeypatch.setattr(room_mapping, "run_mapping", _reaches(reached, "map"))

    outcome = asyncio.run(capture_runs.run_map(room.id, granularity="whole"))
    assert reached == ["map"], "ungated, the browser measures his room"
    assert outcome.refusal != "browser_session"


# ── 3. the sentence ────────────────────────────────────────────────────────

def test_the_refusal_says_why_in_his_terms_and_what_to_use():
    """A REFUSAL THAT NAMES ONLY THE RULE sends him to argue with the rule.
    Every clause asserted here is one he lived through on 1 September."""
    said = mapping_refusals.browser_not_calibration_grade(
        {"user_agent": "Mozilla/5.0 (iPhone)"}, action="map")
    low = said.lower()
    # WHY, in the camera's terms and not ours
    assert "gain" in low, "his Brio's missing lever"
    assert "read-back" in low and "asked for" in low, "the echo"
    assert "re-adapting" in low, "the auto mechanism he watched"
    # WHAT IT COST — nothing
    assert "nothing was measured" in low and "nothing was written" in low
    # WHAT THE PAGE IS STILL FOR
    assert "aiming" in low
    # WHAT TO USE, as a command he can type
    assert mapping_refusals.CLIENT_COMMAND in said
    # AND WHICH RUN, so a queue log read at breakfast names the item
    assert said.startswith("Mapping this room")
    assert mapping_refusals.browser_not_calibration_grade(
        {}, action="commission").startswith("A commissioning pass")


def test_the_positive_twin_names_whose_camera_will_measure():
    """The other half of the same honesty: two devices in one room, and a
    Start button that says which one takes the readings."""
    said = mapping_refusals.calibration_source_note(
        capture_source.describe(_Session(NATIVE_HELLO)))
    assert "capture-pi" in said and "the north shelf" in said
    assert "1.2.3" in said


# ── 4. the route ───────────────────────────────────────────────────────────

def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def test_the_route_answers_409_with_the_sentence(monkeypatch):
    """409 and the WORDING — the shape every anticipated refusal on this
    path already answers with, so a page shows an instruction rather than a
    code. Proven through `PREFLIGHT_REFUSALS`, which is why a route cannot
    forget a gate added at the seam."""
    assert "browser_session" in capture_runs.PREFLIGHT_REFUSALS
    monkeypatch.setattr(capture_runs, "live_session",
                        lambda: _Session(BROWSER_HELLO))
    with _client() as client:
        room = client.post("/api/rooms", json={
            "name": "Lounge", "carrier_ids": ["strip"],
            "axis": {"kind": "vertical", "floor": {"x": 0.5, "y": 1.0},
                     "ceiling": {"x": 0.5, "y": 0.0}}}).json()
        r = client.post(f"/api/rooms/{room['id']}/map", json={})
        assert r.status_code == 409, r.text
        assert r.json()["refusal"] == "browser_session"
        assert mapping_refusals.CLIENT_COMMAND in r.json()["detail"]

        # AND THE PAGE CAN SEE IT COMING, from the same function the gate
        # calls — so it can say so before he presses without inventing a
        # second wording that could drift from the refusal he then gets.
        status = client.get("/api/rooms/map/status").json()["capture_source"]
        assert status["present"] and status["locked"]
        assert status["source"] == "browser"
        assert status["calibration_grade"] is False
        assert status["calibration_refusal"] == r.json()["detail"].replace(
            "Mapping this room", "This measurement")
        # NEVER "the session is broken": it is doing its job.
        assert status["aiming"] is True and status["refusal"] is None


# ── 5. the queue inherits it, and says which camera was there ──────────────

def test_the_queues_wait_names_the_browser_rather_than_no_session(monkeypatch):
    """A QUEUE RUNS NOTHING BUT CALIBRATION-GRADE WORK, so a page left open
    on a phone is a present, locked, healthy session that can run no item of
    one. Reporting that as "no capture session" would send a reader to look
    for a machine that was plugged in the whole time."""
    monkeypatch.setattr(capture_runs, "live_session",
                        lambda: _Session(BROWSER_HELLO))

    async def nap(_s):
        return None

    ticks = iter([0.0, 1.0, 99.0])
    view, refusal = asyncio.run(capture_queue.wait_for_session(
        0.5, sleep=nap, clock=lambda: next(ticks)))
    assert view is None
    assert mapping_refusals.CLIENT_COMMAND in refusal
    assert "no capture session" not in refusal.lower()


def test_the_queues_wait_is_satisfied_by_the_capture_client(monkeypatch):
    """The other direction, on the same wait."""
    monkeypatch.setattr(capture_runs, "live_session",
                        lambda: _Session(NATIVE_HELLO))

    async def nap(_s):
        return None

    view, refusal = asyncio.run(capture_queue.wait_for_session(
        0.5, sleep=nap, clock=lambda: 0.0))
    assert refusal == ""
    assert view and view["calibration_grade"] is True


# ── 5b. a whole CALIBRATION refuses, and the refusal is an entry ───────────

def test_a_calibration_run_refuses_a_browser_and_records_why(monkeypatch, tmp_path):
    """A CALIBRATION IS A RUN OF A DECLARATION, so it inherits this at the
    seam — but it reaches the answer one step earlier, at its own session
    wait, which is better: it never takes the room at all and the sentence
    lands in the LINEAGE, where "what happened last night" is read from.

    A REFUSED RUN IS AN ENTRY, never a silence — `night_run`'s own
    declined-night precedent, and the reason a morning read can answer at
    all."""
    from spectra.models.calibration import Calibration, PinnedCamera
    from spectra.services import (calibration_runs, calibration_store,
                                  light_field, mapping_session)

    monkeypatch.setattr(calibration_runs, "SESSION_WAIT_S", 0.0)
    monkeypatch.setattr(mapping_session, "current", _Session(BROWSER_HELLO))
    room = light_field.put_room(_room())
    cal = calibration_store.save(Calibration(
        name="North shelf", room_id=room.id, camera=PinnedCamera(),
        items=[{"kind": "map", "room_id": room.id, "granularity": "whole",
                "label": "the whole room"}]))

    cal, entry = asyncio.run(calibration_runs.run_calibration(cal))
    assert entry.status == capture_runs.STATUS_REFUSED
    assert entry.refusal == "session"
    assert mapping_refusals.CLIENT_COMMAND in entry.detail
    assert "browser" in entry.detail.lower()
    # NAMED FOR THIS CALLER. A queue log and a calibration's lineage are
    # read by the same person at breakfast, and "press this again" is an
    # instruction neither of them was standing at a button for.
    assert entry.detail.startswith("Running a calibration")
    assert "press this again" not in entry.detail
    # THE LINEAGE HOLDS IT — a refused night is a fact about the night.
    assert calibration_store.load(cal.id).runs[-1].status == \
        capture_runs.STATUS_REFUSED


# ── 6. THE VIEWFINDER STILL WORKS, end to end ──────────────────────────────

def _until(ws, kind: str, tries: int = 20) -> dict:
    for _ in range(tries):
        msg = ws.receive_json()
        if msg.get("type") == kind:
            return msg
    raise AssertionError(f"never saw a {kind}")


def _grey(width=320, height=180, value=90):
    return base64.b64encode(
        bytes([value]) * (width * height)).decode("ascii")


def test_a_browser_can_still_aim_the_camera(monkeypatch):
    """WHAT THE PAGE KEEPS, proven rather than promised — on the REAL
    session and the REAL routes, with a browser `hello` and no capture
    client anywhere: connect, stream frames, have the lock read back, and
    serve the preview frame the axis taps are placed on.

    This is the test that would go red if "demote the browser" had been
    implemented as "refuse the browser", which is the mistake this build is
    one wrong line away from."""
    with _client() as client:
        with client.websocket_connect("/api/rooms/map/ws") as ws:
            assert ws.receive_json()["type"] == "welcome"
            ws.send_json({"type": "hello", **BROWSER_HELLO,
                          "secure_context": True,
                          "lock": {"reported": True, "exposure_locked": True,
                                   "white_balance_locked": True,
                                   "exposure_mode": "manual",
                                   "white_balance_mode": "manual",
                                   "source": "getSettings"}})
            # The session's own keepalive pings arrive on the same socket
            # and are not what this is about.
            ack = _until(ws, "hello_ack")
            # THE LOCK IS READ AND ACCEPTED. Aiming needs no more than this,
            # and the demotion did not touch it.
            assert ack["refusal"] is None

            ws.send_json({"type": "frame", "mime": "image/grey8",
                          "width": 320, "height": 180,
                          "source_width": 1280, "source_height": 720,
                          "captured_at_ms": 1.0, "data": _grey()})

            # THE PREVIEW FRAME — what he taps twice to calibrate the axis.
            for _ in range(50):
                got = client.get("/api/rooms/map/frame/latest")
                if got.status_code == 200:
                    break
            assert got.status_code == 200, "the aiming preview still serves"
            assert got.headers["content-type"].startswith("image/x-portable")

            status = client.get("/api/rooms/map/status").json()
            # THE FRAME LANDED — the stream a person aims by is running, not
            # merely permitted.
            assert status["session"]["counts"]["frames"] >= 1
            assert status["session"]["refusal"] is None
            src = status["capture_source"]
            assert src["present"] and src["locked"]
            # SAID POSITIVELY, because it is a capability and not a
            # consolation: this session is exactly the right tool for aiming.
            assert src["aiming"] is True
            assert src["source"] == "browser"
            assert "aims it" in src["measured_by"]
            assert "capture client" in src["measured_by"], (
                "and it names where a MEASUREMENT would come from instead, "
                "which is the whole point of the line")
            # ...and the session is still counted as a camera host, named as
            # a browser rather than as "the capture client".
            assert "browser session" in status["camera_host"]["sentence"].lower()


# ── 7. one seam, asserted structurally ─────────────────────────────────────

def test_no_production_path_reaches_a_calibration_run_around_the_gate():
    """THE GATE IS ONE `if` AND IT IS WORTH EXACTLY AS MUCH AS THE CLAIM
    THAT EVERYTHING GOES THROUGH IT. So this reads the source: nothing under
    `spectra/` calls a calibration-grade run's own entry point except
    `capture_runs`, which is where the gate lives.

    A grep rather than a call graph on purpose — the same shape
    `tests/test_av_sync_apply.py` uses to assert there is no second clock
    shift. It cannot prove intent; it CAN fail the day someone adds a second
    door, which is the day this matters."""
    import pathlib
    doors = ("run_mapping(", "run_commission(", "compare_regimes(",
             "pose_fingerprint.measure(")
    offenders = []
    for path in pathlib.Path("spectra").rglob("*.py"):
        if path.name in ("capture_runs.py", "room_mapping.py",
                         "commissioning.py", "exposure_test.py",
                         "pose_fingerprint.py"):
            continue                       # each defines its own entry point
        text = path.read_text()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("def ", "async def ")):
                continue               # a route of the same NAME, not a call
            if any(d in line for d in doors) and "capture_runs." not in line:
                offenders.append(f"{path}: {line.strip()}")
    assert offenders == [], (
        "a calibration-grade run is reachable without passing the client-kind "
        "gate:\n" + "\n".join(offenders))


# ── 8. the words themselves ────────────────────────────────────────────────

def test_a_session_that_says_nothing_is_never_promoted_by_silence():
    """The conservative default, asserted rather than assumed: an unknown
    client is a browser as far as this gate is concerned."""
    class _Mute:
        hello: dict = {}
    assert capture_source.kind(_Mute()) == capture_source.KIND_BROWSER
    assert capture_source.calibration_grade(_Mute()) is False
    # NO SESSION AT ALL IS NOT THIS GATE'S CONDITION — `NO_SESSION` is, and
    # two refusals for one condition is how a page starts contradicting
    # itself. So this composes no sentence for it.
    assert capture_source.calibration_refusal(None) is None
    assert capture_source.calibration_refusal(_Mute()) is not None
