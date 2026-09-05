"""THE LEVER-IS-REAL SELF-TEST, PROVEN IN BOTH DIRECTIONS.

A gate that refuses everything is a wall, not an instrument, so every
property here is proven twice: the RED case must refuse and the GREEN case
must PASS AND LET WORK THROUGH.

  RED     tonight's own measured shape — commanded 10 ms / 60 ms / 200 ms
          producing flat noise-level light (the browser path's real numbers:
          weights 0.0, 0.0014 and 0.0051, while the camera's own converged
          regime wandered 0.23 -> 0.01 between two runs of the same thing).
  GREEN   a camera whose measured light rises with commanded time. It
          passes, and the map that follows it runs.
  DRIFT   a camera whose sensitivity moves between two IDENTICAL commanded
          settings — the invisible re-clamping his own eyes reported as "I
          can see well, then it gets really dark".

The fake camera renders a real greyscale patch whose brightness is a
function of the COMMANDED integration time, so the whole judgement runs
through the production code: the map's own `_map_one`, the real footprint
arithmetic, the real refusal wording. Nothing here touches a room, a light
or a webcam.
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from spectra.models.room_map import AxisCalibration, Point, RoomMap
from spectra.services import capture_runs, lever_selftest, light_field
from spectra.services import capture_settings as cs
from spectra.services import mapping_refusals, room_mapping

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))

#: The lit patch, in grid cells. 8x8 cells at byte value V weighs
#: 64 * V / 255, so a byte of 40 already weighs 10 — comfortably clear of
#: `light_field.UNSEEN_WEIGHT`, and a byte of 0.05 weighs 0.013, which is
#: tonight's shape.
PATCH = 8


class _Camera:
    """A CAMERA MADE OF A RESPONSE CURVE. `respond` turns the commanded
    integration time into a camera byte; that is the ONLY thing separating
    an honest camera from tonight's."""

    def __init__(self, respond):
        self.respond = respond
        self.captures = 0

    def frame(self, exposure, lit: bool) -> np.ndarray:
        grid = np.zeros((36, 64), dtype=np.float64)
        if lit:
            value = float(self.respond(exposure, self.captures))
            grid[10:10 + PATCH, 20:20 + PATCH] = value
        return grid


class _Session(cs.SessionCameraDouble):
    """A connected, locked, NATIVE camera session."""
    pose_id = "pose-lever"
    id = "sess-lever"
    run_abort = None
    keep_full_frames = False
    lever_verdict = None

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

    def __init__(self, camera: _Camera, *, native=True):
        self.camera = camera
        self.camera_configs = []
        self.dark_next = True
        self.hello = {"client": lever_selftest.NATIVE_CLIENT,
                      "host": "capture-pi"} if native else {
            "user_agent": "Mozilla/5.0 (iPhone)"}
        self.camera_lock = dict(self.lock.as_dict())

    def refusal(self):
        return None

    def _camera_clock(self):
        return 0.0

    def _camera_lock_view(self):
        """A DRIVER THAT TAKES EVERY SETTING — which is tonight's whole
        point. The read-back always agrees with the request; only the
        measured light can tell an honest camera from a dead lever."""
        return {**self.camera_lock,
                "exposure_time": self.camera_request.exposure_time,
                "gain": self.camera_request.gain}

    async def gather(self, seconds, min_frames=1):
        exposure = self.camera_request.exposure_time
        lit = not self.dark_next
        self.dark_next = not self.dark_next
        if lit:
            self.camera.captures += 1
        grid = self.camera.frame(exposure, lit)
        return [grid, grid], [10, 10]


def _virtual(device):
    return {"active": True, "pixel_count": 20, "config": {"grouping": 1},
            "segments": [[device, 0, 19, False]],
            "effect": {"type": "singleColor", "config": {}}}


def _deps(session, **kw):
    async def get_virtuals():
        return {"strip": _virtual("strip-fixture")}

    async def chains():
        return {"strip": [{"id": "strip-fixture", "type": "wled"}]}

    async def open_hold(*a, **k):
        return {"held": True}

    async def close_hold():
        return None

    async def sleep(_s):
        return None

    kw.setdefault("open_hold", open_hold)
    return room_mapping.RunDeps(
        session=session, get_virtuals=get_virtuals, carrier_devices=chains,
        close_hold=close_hold, sleep=sleep, clock=lambda: 0.0,
        spectra_owns=lambda: True, **kw)


def _room():
    return RoomMap(name="Living room", carrier_ids=["strip"], axis=AXIS)


# ── the response curves ────────────────────────────────────────────────────

#: What a camera that was asked for nothing settles on, so an ordinary map
#: after a self-test still sees light. `n` is the lit capture's own number.
CONVERGED = 200


def honest(exposure, _n):
    """A sensor in its linear regime: more time, more light."""
    return 0.2 * float(exposure or CONVERGED)


def tonight(exposure, _n):
    """HIS OWN MEASURED SHAPE. The three commanded times produced weights of
    0.0, 0.0014 and 0.0051 — proportional to two significant figures and
    every one of them at the noise floor, which is exactly why the SIGNAL
    check has to come before the RESPONSE check."""
    return 0.0002 * float(exposure or CONVERGED)


def wanders(exposure, n):
    """The re-clamping camera: it obeys, and then its sensitivity moves
    under a command that did not. 0.23 -> 0.01 is the pair he actually saw,
    which is the twenty-three here."""
    return honest(exposure, n) / (23.0 if n >= 3 else 1.0)


# ── 1. THE JUDGEMENT, as a pure function ───────────────────────────────────

def _readings(weights, saturated=0.0):
    return [lever_selftest.Reading(label=label, exposure_time=e, ok=True,
                                   weight=w, saturated_fraction=saturated)
            for label, e, w in zip(("dim", "bright", "repeat"),
                                   (50, 200, 200), weights)]


def test_red_tonights_flat_noise_refuses():
    verdict, response, _repeat, _notes = lever_selftest.judge(
        _readings([0.0, 0.0014, 0.0051]))
    assert verdict == mapping_refusals.LEVER_NO_SIGNAL
    assert verdict in mapping_refusals.LEVER_REFUSING
    assert response is None, ("no ratio is quoted between two noise "
                              "readings — it would look like a response")


def test_red_a_dead_lever_with_real_light_refuses_as_no_response():
    verdict, response, _r, _n = lever_selftest.judge(
        _readings([40.0, 41.0, 41.0]))
    assert verdict == mapping_refusals.LEVER_NO_RESPONSE
    assert response == pytest.approx(1.025, abs=1e-3)


def test_green_a_connected_lever_passes():
    verdict, response, repeat, _n = lever_selftest.judge(
        _readings([10.0, 40.0, 39.0]))
    assert verdict == mapping_refusals.LEVER_OK
    assert verdict not in mapping_refusals.LEVER_REFUSING
    assert response == pytest.approx(4.0)
    assert repeat == pytest.approx(0.975)


def test_green_light_appearing_where_there_was_none_is_a_response():
    """A dim regime under the floor has no honest denominator, but going
    from nothing to a real reading is still a response."""
    verdict, response, _r, notes = lever_selftest.judge(
        _readings([0.2, 40.0, 41.0]))
    assert verdict == mapping_refusals.LEVER_OK
    assert response is None
    assert any("appeared where there was none" in n for n in notes)


def test_drift_between_two_identical_commands_refuses():
    verdict, _response, repeat, _n = lever_selftest.judge(
        _readings([10.0, 40.0, 40.0 / 23.0]))
    assert verdict == mapping_refusals.LEVER_DRIFT
    assert repeat < 1.0 / lever_selftest.REPEAT_BAND


def test_the_instruments_own_wobble_is_never_drift():
    """The map's own tie band for two readings of one regime is 10%
    (`exposure_test.TIE_FRACTION`). The repeat band is five times looser, so
    ordinary noise cannot fire it."""
    for repeat_weight in (36.0, 44.0):
        verdict, _resp, _rep, _n = lever_selftest.judge(
            _readings([10.0, 40.0, repeat_weight]))
        assert verdict == mapping_refusals.LEVER_OK


def test_a_clipped_bright_regime_is_evidence_not_a_failure():
    """You cannot clip a sensor by leaving its exposure alone. A saturated
    bright regime that measured more than the dim one passes with a note
    rather than failing a ratio bar it can no longer meet."""
    verdict, response, _rep, notes = lever_selftest.judge(
        _readings([30.0, 40.0, 40.0], saturated=0.5))
    assert verdict == mapping_refusals.LEVER_OK
    assert response < lever_selftest.min_response_ratio()
    assert any("clipped" in n for n in notes)


def test_a_capture_that_produced_no_reading_is_unproven_not_broken():
    readings = _readings([10.0, 40.0, 40.0])
    readings[1].ok, readings[1].weight = False, 0.0
    verdict, _r, _rep, _n = lever_selftest.judge(readings)
    assert verdict == mapping_refusals.LEVER_UNPROVEN
    assert verdict not in mapping_refusals.LEVER_REFUSING, \
        "'we could not check' is not 'we checked and it is broken'"


# ── 2. THE WHOLE RUN, on the real capture machinery ────────────────────────

def _run(camera, **kw):
    sess = _Session(camera)
    return sess, asyncio.run(lever_selftest.run_selftest(
        _room(), _deps(sess), **kw))


def test_the_run_refuses_tonights_camera_by_name():
    sess, verdict = _run(_Camera(tonight))
    assert verdict.verdict == mapping_refusals.LEVER_NO_SIGNAL
    assert verdict.refuses and not verdict.proven
    # THE REFUSAL NAMES BOTH COMMANDS AND BOTH MEASUREMENTS.
    assert "integration time of 50" in verdict.reason
    assert "integration time of 200" in verdict.reason
    assert "below the 1 an emitter must clear" in verdict.reason
    assert "measure the camera" not in verdict.reason  # it says "mood"
    assert "calibration taken through it would measure nothing" in verdict.reason


def test_the_run_passes_an_honest_camera_and_says_what_it_measured():
    sess, verdict = _run(_Camera(honest))
    assert verdict.proven, verdict.reason
    assert not verdict.refuses
    assert verdict.response_ratio == pytest.approx(4.0, rel=0.01)
    assert verdict.repeat_ratio == pytest.approx(1.0, rel=0.01)
    assert "reaches its sensor" in verdict.reason
    assert [r.exposure_time for r in verdict.readings] == [50, 200, 200]


def test_the_run_catches_a_camera_that_re_clamps_between_two_identical_asks():
    _sess, verdict = _run(_Camera(wanders))
    assert verdict.verdict == mapping_refusals.LEVER_DRIFT
    assert verdict.refuses
    assert "IDENTICAL" in verdict.reason


def test_the_run_stores_nothing_and_puts_the_camera_back():
    sess = _Session(_Camera(honest))
    saved = []
    deps = _deps(sess, save_room=lambda room: saved.append(room))
    before = cs.CameraRequest(frame_size=cs.MAP_PROFILE)
    asyncio.run(sess.apply_camera(before))
    verdict = asyncio.run(lever_selftest.run_selftest(_room(), deps))
    assert verdict.proven
    assert saved == [], "a self-test never writes a footprint"
    assert sess.camera_request.exposure_time is None, \
        "it left its own bright regime running"


def test_a_camera_whose_range_cannot_span_the_factor_is_unprovable_not_refused():
    sess = _Session(_Camera(honest))
    sess.camera_lock = {**sess.camera_lock,
                        "exposure_time_range": [100.0, 120.0]}
    verdict = asyncio.run(lever_selftest.run_selftest(_room(), _deps(sess)))
    assert verdict.verdict == mapping_refusals.LEVER_UNPROVABLE
    assert not verdict.refuses, "inventing a fault out of a check we could " \
                                "not make is the one thing this must not do"
    assert "spans less than" in verdict.reason


def test_a_camera_that_refuses_the_tests_own_command_is_unprovable():
    """The self-test needs to COMMAND two integration times. A camera that
    will not take them proves nothing either way — and refusing the run on
    it would be wrong, because the run may not have asked for that lever at
    all (and if it did, its own gate stops it with a better sentence)."""
    sess = _Session(_Camera(honest))
    sess.camera_lock = {**sess.camera_lock,
                        "manual_refusals": ["the driver refused "
                                            "exposure_time_absolute=200"]}
    sess._camera_lock_view = lambda: dict(sess.camera_lock)   # noqa: SLF001
    verdict = asyncio.run(lever_selftest.run_selftest(_room(), _deps(sess)))
    assert verdict.verdict == mapping_refusals.LEVER_UNPROVABLE
    assert not verdict.refuses
    assert "would not take" in verdict.reason


def test_the_bright_regime_is_the_one_the_run_itself_asked_for():
    """Proving the lever at the regime the run is about to use is a stronger
    statement than proving it somewhere else and assuming."""
    sess, verdict = _run(_Camera(honest), requested_exposure=800)
    assert [r.exposure_time for r in verdict.readings] == [200, 800, 800]


# ── 3. THE PREFLIGHT, at the one seam every run passes through ─────────────

def _wire(monkeypatch, sess, room):
    monkeypatch.setattr(capture_runs, "live_session", lambda: sess)
    monkeypatch.setattr(capture_runs.light_field, "get_room",
                        lambda _id: room)
    monkeypatch.setattr(capture_runs.light_field, "put_room",
                        lambda _room: None)
    monkeypatch.setattr(capture_runs.room_mapping, "production_deps",
                        lambda s: _deps(s))


def test_a_refusing_self_test_stops_a_map_before_any_light(monkeypatch):
    sess = _Session(_Camera(tonight))
    room = _room()
    _wire(monkeypatch, sess, room)
    lit = []
    monkeypatch.setattr(capture_runs.room_mapping, "run_mapping",
                        lambda *a, **k: lit.append(1))
    outcome = asyncio.run(capture_runs.run_map(room.id, granularity="whole"))
    assert outcome.status == capture_runs.STATUS_REFUSED
    assert outcome.refusal == "lever"
    assert lit == [], "the map never ran"
    assert outcome.lever["verdict"] == mapping_refusals.LEVER_NO_SIGNAL
    assert "exposure" in outcome.detail
    assert outcome.summary()["lever"]["proven"] is False


def test_a_passing_self_test_lets_the_map_through_and_rides_on_it(monkeypatch):
    """THE GATE THAT OPENS. A self-test that refused everything would be a
    wall — this is the half that proves it is not."""
    sess = _Session(_Camera(honest))
    room = _room()
    _wire(monkeypatch, sess, room)
    outcome = asyncio.run(capture_runs.run_map(room.id, granularity="whole"))
    assert outcome.status == capture_runs.STATUS_OK, outcome.detail
    assert outcome.lever["proven"] is True
    assert outcome.summary()["lever"]["verdict"] == mapping_refusals.LEVER_OK


def test_a_browser_session_is_never_self_tested_and_is_refused_earlier(monkeypatch):
    """THE SELF-TEST NEVER RUNS ON A BROWSER, and since the browser's
    demotion that is because the run is refused BEFORE it, for the broader
    reason: a browser cannot pin the camera at all, so there is nothing here
    to measure.

    THE ORDER MATTERS AND IS ASSERTED. A browser reaching the self-test and
    failing it would say "your camera is not obeying its exposure control",
    which is true of the browser and useless as an instruction — he would go
    and look at the camera. The refusal he gets instead names the client and
    the one next step, and no verdict is left on the session to be read
    later as a finding about that camera."""
    sess = _Session(_Camera(honest), native=False)
    room = _room()
    _wire(monkeypatch, sess, room)
    outcome = asyncio.run(capture_runs.run_map(room.id, granularity="whole"))
    assert outcome.status == capture_runs.STATUS_REFUSED
    assert outcome.refusal == "browser_session", outcome.detail
    # NOT the lever's refusal: this camera was never measured, and the record
    # must not imply it was.
    assert outcome.lever == {}
    assert sess.lever_verdict is None
    view = capture_runs.session_view()
    assert view["native"] is False and view["calibration_grade"] is False
    assert view["source"] == "browser"
    # AND THE SESSION ITSELF IS FINE. Aiming is what it is for.
    assert view["present"] and view["locked"] and view["aiming"] is True
    assert view["refusal"] is None, "the CAMERA lock is not what refused"


def test_the_verdict_is_earned_once_per_session_and_never_inherited(monkeypatch):
    sess = _Session(_Camera(honest))
    room = _room()
    _wire(monkeypatch, sess, room)
    asyncio.run(capture_runs.run_map(room.id, granularity="whole"))
    first = sess.lever_verdict
    assert first is not None and first.proven
    captures = sess.camera.captures
    asyncio.run(capture_runs.run_map(room.id, granularity="whole"))
    assert sess.lever_verdict is first, "a queue pays for it once"
    assert sess.camera.captures > captures, "the MAP still lit the room"

    # AND IT STILL PAYS ONCE WHEN THE CAMERA REMEMBERS THE TEST'S OWN
    # COMMAND. A real V4L2 device keeps the last integration time it was
    # given, so a fingerprint derived from the read-back would differ on
    # every later item and re-buy three captures of his dark room each time.
    sess.camera_lock = {**sess.camera_lock, "exposure_time": 800.0}
    sess._camera_lock_view = lambda: dict(sess.camera_lock)   # noqa: SLF001
    asyncio.run(capture_runs.run_map(room.id, granularity="whole"))
    assert sess.lever_verdict is first, \
        "the camera moving under its own test must not re-buy the test"

    # A CAMERA REOPEN INSIDE ONE CONNECTION mints a new pose, and the
    # fingerprint carries it — so the verdict cannot be inherited across one.
    sess.pose_id = "pose-after-a-reopen"
    asyncio.run(capture_runs.run_map(room.id, granularity="whole"))
    assert sess.lever_verdict is not first
    assert sess.lever_verdict.pose_id == "pose-after-a-reopen"


def test_the_gate_goes_red_on_the_defect_it_was_written_for(monkeypatch):
    """A proof bar that cannot fail on its own defect is decoration. With
    the preflight removed, tonight's camera runs a whole map and reports
    success — which is precisely the evening this build exists to end."""
    sess = _Session(_Camera(tonight))
    room = _room()
    _wire(monkeypatch, sess, room)
    monkeypatch.setattr(capture_runs, "_preflight",
                        lambda *a, **k: _none())
    outcome = asyncio.run(capture_runs.run_map(room.id, granularity="whole"))
    assert outcome.lever == {}
    # AND THE ANSWER IT GIVES INSTEAD IS THE MISDIAGNOSIS OF THAT EVENING:
    # a camera-shaped fault reported as a room-shaped one, sending him to
    # move a camera that was standing in exactly the right place.
    assert "visible from where the phone was standing" in outcome.detail
    assert "Move to somewhere that can see them" in outcome.detail
    assert "exposure" not in outcome.detail


async def _none():
    return None


# ── 4. THE FLOOR IS THE MAP'S OWN ──────────────────────────────────────────

def test_the_signal_floor_is_the_one_a_real_emitter_must_clear():
    assert lever_selftest.Verdict().signal_floor == light_field.UNSEEN_WEIGHT


# ── 5. THE SELF-TEST DRIVES WHAT THE RUN DRIVES ────────────────────────────
#
# THE DEFECT: the self-test resolved its OWN plan over the whole room at
# whole granularity and drove `plan.emitters[0]`, however narrowly the run
# itself was scoped. On his Living Room that is one carrier — `tv-mapper`,
# a 560-px strip spanning the TV backlight AND both kitchen sconces as pixel
# ranges of one run — so a run scoped to the backlight's blocks earned its
# verdict by lighting the kitchen. The run's scope never reached the test.
#
# The `strip` here is that shape in miniature: ONE carrier, 20 pixels,
# four blocks of five, standing in for four regions of one physical strip.

BLOCKS = ["strip:blk0[0-4]", "strip:blk1[5-9]",
          "strip:blk2[10-14]", "strip:blk3[15-19]"]


def _scoped(camera, **scope_kw):
    sess = _Session(camera)
    return sess, asyncio.run(lever_selftest.run_selftest(
        _room(), _deps(sess), scope=lever_selftest.Scope.of(**scope_kw)))


def test_a_scoped_run_drives_the_scoped_emitter_not_the_first_one():
    """A run scoped to the THIRD block must light the third block. Before
    this, it lit `plan.emitters[0]` — a different part of his room."""
    _sess, verdict = _scoped(_Camera(honest), emitter_ids=[BLOCKS[2]],
                             granularity="block", block_pixels=5)
    assert verdict.proven, verdict.reason
    assert verdict.emitter_id == BLOCKS[2]
    assert verdict.emitter_id != BLOCKS[0], \
        "the whole point: never the whole-room first emitter"


def test_a_scoped_run_drives_the_FIRST_scoped_emitter_in_plan_order():
    """Deterministic, and always one the run itself is about to map."""
    _sess, verdict = _scoped(_Camera(honest),
                             emitter_ids=[BLOCKS[3], BLOCKS[1]],
                             granularity="block", block_pixels=5)
    assert verdict.emitter_id == BLOCKS[1], "plan order, not argument order"


def test_a_carrier_scoped_run_stays_inside_that_carrier():
    _sess, verdict = _scoped(_Camera(honest), carrier_ids=["strip"],
                             granularity="block", block_pixels=5)
    assert verdict.proven, verdict.reason
    assert verdict.emitter_id in BLOCKS


def test_an_unresolvable_scope_FAILS_CLOSED_and_never_widens():
    """THE WHOLE POINT OF THE SCOPE. A verdict earned on a different emitter
    than the run maps is a confident answer about the wrong target, which is
    exactly the class this instrument exists to refuse. It reports that it
    could not check — never a check made on something else."""
    sess, verdict = _scoped(_Camera(honest), emitter_ids=["strip:blk9[45-49]"],
                            granularity="block", block_pixels=5)
    assert verdict.verdict == mapping_refusals.LEVER_UNPROVEN
    assert verdict.emitter_id == "", "no emitter was driven at all"
    assert verdict.emitter_id != BLOCKS[0]
    assert not verdict.refuses, \
        "'we could not check' is not 'we checked and it is broken'"
    assert verdict.readings == [], "and nothing was lit finding that out"
    assert "strip:blk9[45-49]" in verdict.reason
    assert "was NOT checked" in verdict.reason
    assert sess.camera_configs == [], "the camera was never even commanded"


def test_a_scope_at_the_wrong_granularity_fails_closed_too():
    """An emitter's id comes from the granularity that produced it, so a
    block id asked for at whole granularity cannot resolve — and must not
    quietly become the whole carrier."""
    _sess, verdict = _scoped(_Camera(honest), emitter_ids=[BLOCKS[0]],
                             granularity="whole")
    assert verdict.verdict == mapping_refusals.LEVER_UNPROVEN
    assert verdict.emitter_id == ""


def test_the_fail_closed_verdict_is_never_cached_so_it_cannot_stick():
    sess = _Session(_Camera(honest))
    deps = _deps(sess)
    scope = lever_selftest.Scope.of(emitter_ids=["nope"], granularity="block",
                                    block_pixels=5)
    verdict = asyncio.run(lever_selftest.ensure(_room(), deps, scope=scope))
    assert verdict.verdict == mapping_refusals.LEVER_UNPROVEN
    assert sess.lever_verdict is None


def test_an_unscoped_run_is_byte_identical_to_before_the_scope_existed():
    """EVERY caller that does not scope must behave exactly as it did: the
    whole room, whole granularity, `plan.emitters[0]`."""
    _s1, plain = _run(_Camera(honest))
    _s2, empty_scope = _scoped(_Camera(honest))
    _s3, explicit_none = _scoped(_Camera(honest), emitter_ids=None,
                                 carrier_ids=None, granularity=None,
                                 block_pixels=None)
    assert plain.emitter_id == "strip", "the whole carrier, as always"
    for other in (empty_scope, explicit_none):
        assert other.emitter_id == plain.emitter_id
        assert other.verdict == plain.verdict
        assert [r.exposure_time for r in other.readings] == \
            [r.exposure_time for r in plain.readings]
        assert [r.weight for r in other.readings] == \
            [r.weight for r in plain.readings]


def test_an_empty_scope_is_exactly_the_default_scope():
    """Structural, not asserted by sampling: an unscoped run builds the same
    object the omitted argument defaults to."""
    assert lever_selftest.Scope.of() == lever_selftest.Scope()
    assert not lever_selftest.Scope().scoped
    assert lever_selftest.Scope.of(emitter_ids=[], carrier_ids=None) == \
        lever_selftest.Scope()


def test_within_hands_back_the_plans_own_list_when_nothing_is_scoped():
    """THE FAIL-CLOSED GUARANTEE IS A PROPERTY OF THE LIST, which is what
    makes it structural: there is no third answer for a scoped run to widen
    to, so there is no fallback branch to forget."""
    class _E:
        def __init__(self, eid, cid):
            self.emitter_id, self.carrier_id = eid, cid

    plan = [_E("a", "c1"), _E("b", "c1"), _E("c", "c2")]
    assert lever_selftest.Scope().within(plan) is plan
    assert [e.emitter_id for e in
            lever_selftest.Scope.of(carrier_ids=["c2"]).within(plan)] == ["c"]
    assert lever_selftest.Scope.of(emitter_ids=["zz"]).within(plan) == []


# ── 6. AND THE RUN ITSELF HANDS ITS OWN SCOPE OVER ─────────────────────────

def test_run_map_gives_the_self_test_its_own_scope(monkeypatch):
    sess = _Session(_Camera(honest))
    room = _room()
    _wire(monkeypatch, sess, room)
    seen = {}

    async def spy(_room, _deps, *, requested_exposure=None, scope=None):
        seen["scope"] = scope
        return lever_selftest.Verdict(verdict=mapping_refusals.LEVER_OK)

    monkeypatch.setattr(lever_selftest, "ensure", spy)
    asyncio.run(capture_runs.run_map(room.id, granularity="block",
                                     block_pixels=5,
                                     emitter_ids=[BLOCKS[2]],
                                     carrier_ids=["strip"], remember=False))
    assert seen["scope"] == lever_selftest.Scope(
        emitter_ids=(BLOCKS[2],), carrier_ids=("strip",),
        granularity="block", block_pixels=5)


def test_run_map_unscoped_hands_over_the_default_scope(monkeypatch):
    sess = _Session(_Camera(honest))
    room = _room()
    _wire(monkeypatch, sess, room)
    seen = {}

    async def spy(_room, _deps, *, requested_exposure=None, scope=None):
        seen["scope"] = scope
        return lever_selftest.Verdict(verdict=mapping_refusals.LEVER_OK)

    monkeypatch.setattr(lever_selftest, "ensure", spy)
    asyncio.run(capture_runs.run_map(room.id, granularity="whole",
                                     remember=False))
    assert not seen["scope"].scoped
    assert seen["scope"].granularity == "whole"


def test_a_map_scoped_to_one_block_lights_only_that_block_end_to_end(monkeypatch):
    """THE ACCEPTANCE, on the real seam: the self-test's own measurement
    names the scoped block, and the map that follows it runs."""
    sess = _Session(_Camera(honest))
    room = _room()
    _wire(monkeypatch, sess, room)
    outcome = asyncio.run(capture_runs.run_map(
        room.id, granularity="block", block_pixels=5,
        emitter_ids=[BLOCKS[1]], remember=False))
    assert outcome.lever["proven"] is True, outcome.detail
    assert outcome.lever["emitter_id"] == BLOCKS[1]
