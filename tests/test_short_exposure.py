"""THE SHORT-EXPOSURE COMMISSIONING REGIME, PROVEN IN BOTH DIRECTIONS.

The evening this is for is in `spectra/services/short_exposure.py`'s own
docstring: his kiosk Brio refused every commissioning run, night and
daylight, in TWO different shapes depending on `exposure_dynamic_framerate`
— DRIFT with it on, NO_RESPONSE with it off. Both refusals were correct.
The camera is honest in the short part of its range and is not honest above
it.

WHAT IS PROVEN HERE, and the last one is the point of the whole file:

  * the ceiling is DERIVED from the device's own reported frame rate, and
    says so when it had to assume one instead;
  * a run asking past it is SHORTENED AND TOLD; a run asking under it is
    never overridden upward; a run asking for nothing is COMMANDED the
    ceiling, but only on a camera whose read-back evidences the control;
  * `exposure_dynamic_framerate` is OWNED — his value read before the pin,
    written back on the un-pin — against the real `V4L2Camera` and a fake
    `v4l2-ctl` that remembers, so a read-back is a read-back;
  * THE LEVER SELF-TEST IS NOT WEAKENED. A camera that drifts inside the
    short regime still refuses; one that does not respond inside it still
    refuses; the two commands are still a real factor apart and one of them
    is still repeated. Moving WHERE it measures must not move WHETHER the
    readings have to agree, and a build that bought a passing run by
    relaxing the judgement would be worse than the refusals it replaced.

NOTHING HERE TOUCHES A CAMERA, A ROOM OR A LIGHT.
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from spectra import config as scfg
from spectra.capture_client import camera as cam
from spectra.capture_client.camera import V4L2Camera
from spectra.models.room_map import AxisCalibration, Point, RoomMap
from spectra.services import capture_settings as cs
from spectra.services import (lever_selftest, light_field, mapping_refusals,
                              room_mapping, short_exposure)

# His own camera's read-back shape: a 30 fps sensor declaring 3..2047 with
# the dynamic-framerate control present and ON.
BRIO = {"exposure_time_range": [3.0, 2047.0], "exposure_time": 250.0,
        "sensor_fps": 30.0, "dynamic_framerate": 1}


# ── 1. THE TWO DECLARATIONS OF ONE WIRE VALUE ──────────────────────────────

def test_the_client_and_the_server_mean_the_same_number_by_off():
    """`spectra/capture_client/` may not import `spectra.services` at all,
    so the value that turns the control off is declared twice. That is a
    drift risk, and this is the proof rather than the hope."""
    assert cam.DYNAMIC_FRAMERATE_OFF == short_exposure.DYNAMIC_FRAMERATE_OFF
    assert [n for n, _c in cam.SWITCHES] == [n for n, _w in cs.PINNED_SWITCHES]


# ── 2. THE CEILING ─────────────────────────────────────────────────────────

def test_the_ceiling_is_a_fraction_of_the_cameras_own_frame_interval():
    """DERIVED, and from the device's own answer: a sensor delivering 30
    frames a second cannot integrate for longer than 1/30 s per frame, which
    is 333 x100 us. The fraction of that a run may use is the one number
    that is a SETTING rather than a derivation — see the module docstring."""
    c = short_exposure.ceiling_for(BRIO)
    assert c.frame_interval_units == 333
    assert c.units == int(333 * short_exposure.DEFAULT_FRACTION) == 83
    assert c.measured_fps is True and c.sensor_fps == 30.0
    assert c.bound_by == "frame_interval"
    assert "its own reported 30 fps" in c.sentence()


def test_a_slower_sensor_gets_a_longer_ceiling():
    """The bound is physics, not a preference: a 5 fps sensor has 200 ms of
    frame interval and can honestly hold far more."""
    assert short_exposure.ceiling_for({**BRIO, "sensor_fps": 5.0}).units == 500
    assert short_exposure.ceiling_for({**BRIO, "sensor_fps": 60.0}).units == 41


def test_a_camera_that_will_not_say_its_frame_rate_is_assumed_and_says_so():
    """An assumption made silently is invisible. This one is named in the
    ceiling's own sentence, and it is the CONSERVATIVE direction: assuming
    30 fps can only ever produce a shorter ceiling than a slower real rate
    would."""
    c = short_exposure.ceiling_for({"exposure_time_range": [3.0, 2047.0]})
    assert c.measured_fps is False
    assert c.sensor_fps == short_exposure.ASSUMED_FPS
    assert "an assumed 30 fps" in c.sentence()


def test_a_camera_that_cannot_reach_the_ceiling_is_bounded_by_its_own_max():
    c = short_exposure.ceiling_for({**BRIO, "exposure_time_range": [3.0, 40.0]})
    assert c.units == 40 and c.bound_by == "device_max"
    assert "the highest integration time this camera declares" in c.sentence()


def test_the_ceiling_is_never_below_what_the_device_will_accept():
    """A ceiling under the device's own minimum is not a cautious run, it is
    a run every command of which the driver would refuse — a fault of ours
    arriving wearing the camera's name."""
    c = short_exposure.ceiling_for({**BRIO,
                                    "exposure_time_range": [100.0, 120.0]})
    assert c.units == 100 and c.bound_by == "device_min"
    assert "shorter regime is not available" in c.sentence()


def test_the_fraction_is_bounded_and_survives_a_typo(monkeypatch):
    """It sits on the path of every commissioning run, so an unparseable or
    absurd value must cost nothing."""
    monkeypatch.setenv("SPECTRA_SHORT_EXPOSURE_FRACTION", "not-a-number")
    assert scfg.short_exposure_fraction() == scfg.SHORT_EXPOSURE_FRACTION_DEFAULT
    monkeypatch.setenv("SPECTRA_SHORT_EXPOSURE_FRACTION", "9")
    assert short_exposure.fraction() == short_exposure.MAX_FRACTION
    monkeypatch.setenv("SPECTRA_SHORT_EXPOSURE_FRACTION", "-3")
    assert short_exposure.fraction() == short_exposure.MIN_FRACTION
    monkeypatch.setenv("SPECTRA_SHORT_EXPOSURE_FRACTION", "0.5")
    assert short_exposure.ceiling_for(BRIO).units == 166


def test_the_default_fraction_brackets_his_two_measured_points():
    """THE ANCHOR, asserted rather than left in prose. 62 x100 us produced a
    plainly real reading on both his nights; 250 did not. A default that
    allowed 250 would have changed nothing, and one that refused 62 would
    have thrown away the only regime known to work."""
    units = short_exposure.ceiling_for(BRIO).units
    assert units >= 62, "the regime known to have measured real light"
    assert units < 250, "the regime known to have failed, twice"


# ── 3. WHAT A RUN'S REQUEST BECOMES ────────────────────────────────────────

def test_a_request_past_the_ceiling_is_shortened_and_said():
    req, ceiling, note = short_exposure.cap(cs.CameraRequest(exposure_time=250),
                                            BRIO)
    assert req.exposure_time == ceiling.units == 83
    assert "250" in note and "83" in note
    assert req.dynamic_framerate == short_exposure.DYNAMIC_FRAMERATE_OFF


def test_a_request_under_the_ceiling_is_never_pushed_up():
    """A run asking for LESS light has its own reason, and this is a
    ceiling, not a target."""
    req, _c, note = short_exposure.cap(cs.CameraRequest(exposure_time=40), BRIO)
    assert req.exposure_time == 40 and note == ""


def test_a_request_naming_nothing_commands_the_ceiling():
    """The whole difference between a REGIME and a clamp. Left alone, the
    camera holds whatever it converged to before its lock — which on his own
    kiosk is the untrusted half of the range, and which pinning the
    frame-rate control off makes worse rather than better."""
    req, _c, note = short_exposure.cap(cs.CameraRequest(), BRIO)
    assert req.exposure_time == 83
    assert note.startswith("This run commands at most 83")


def test_a_camera_that_has_never_reported_an_exposure_control_is_not_commanded():
    """ONLY A CONTROL THE CAMERA HAS SHOWN IT HAS IS EVER ASKED FOR.
    Commanding one on no evidence would make `camera_refusal` hold the run
    against a read-back nobody has — a working run refusing for a reason
    that is ours."""
    req, ceiling, note = short_exposure.cap(cs.CameraRequest(), {})
    assert ceiling.commandable is False
    assert req.exposure_time is None and note == ""
    assert req.dynamic_framerate is None, "nor is a switch it never reported"


def test_the_switch_is_pinned_only_when_the_camera_reported_having_it():
    """A camera with no `exposure_dynamic_framerate` cannot renegotiate its
    own frame rate, so there is nothing to pin — and asking for it would
    have to be either a refusal (wrong) or an ignored write (dishonest)."""
    without = {k: v for k, v in BRIO.items() if k != "dynamic_framerate"}
    assert short_exposure.pinnable(BRIO) is True
    assert short_exposure.pinnable(without) is False
    assert short_exposure.cap(cs.CameraRequest(), without)[0].dynamic_framerate \
        is None


def test_a_pinned_switch_makes_the_request_manual_so_it_is_waited_for():
    """`await_camera` returns immediately for a request that asks the camera
    for nothing. A request that pins the frame-rate control asks for
    something, and reading the lock before the camera has answered it is the
    one failure that function's docstring exists to describe."""
    assert cs.CameraRequest().manual is False
    assert cs.CameraRequest(dynamic_framerate=0).manual is True
    assert cs.CameraRequest(dynamic_framerate=0).as_wire()["dynamic_framerate"] == 0


# ── 4. OWNING THE SWITCH, against the real client ──────────────────────────

MENUS = """
User Controls

                           gain 0x00980913 (int)    : min=0 max=255 value=0
        white_balance_automatic 0x0098090c (bool)   : default=1 value=1

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3
				1: Manual Mode
				3: Aperture Priority Mode
         exposure_time_absolute 0x009a0902 (int)    : min=3 max=2047 value=166
    exposure_dynamic_framerate 0x009a0903 (bool)    : default=0 value=1
"""

DEFAULTS = {"auto_exposure": 3, "white_balance_automatic": 1,
            "exposure_time_absolute": 166, "gain": 0,
            "exposure_dynamic_framerate": 1}


class FakeCtl:
    """A `v4l2-ctl` that remembers what was written, so a read-back is a
    read-back and never the write echoing itself.
    `tests/test_camera_pinned_settings.py`'s own shape."""

    def __init__(self, values, *, stuck=(), menus=MENUS, parm="30.000"):
        self.values = dict(values)
        self.stuck = set(stuck)
        self.menus = menus
        self.parm = parm
        self.sets: list[tuple[str, int]] = []

    def __call__(self, args, timeout=5.0):
        if "--list-ctrls-menus" in args:
            return 0, self.menus
        if "--get-parm" in args:
            if self.parm is None:
                return 1, ""
            return 0, ("Streaming Parameters Video Capture:\n"
                       "\tCapabilities     : timeperframe\n"
                       f"\tFrames per second: {self.parm} (30/1)\n")
        for arg in args:
            if arg.startswith("--get-ctrl="):
                name = arg.split("=", 1)[1]
                if name not in self.values:
                    return 1, ""
                return 0, f"{name}: {self.values[name]}"
            if arg.startswith("--set-ctrl="):
                name, _, value = arg.split("=", 1)[1].partition("=")
                self.sets.append((name, int(value)))
                if name not in self.stuck:
                    self.values[name] = int(value)
                return 0, ""
        return 1, ""


@pytest.fixture
def ctl(monkeypatch):
    fake = FakeCtl(DEFAULTS)
    monkeypatch.setattr(cam, "_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cam, "_run", fake)
    return fake


def test_pinning_the_switch_reads_his_value_first_then_writes_the_pin(ctl):
    camera = V4L2Camera()
    lock = asyncio.run(camera.apply_lock(dynamic_framerate=0))
    assert ("exposure_dynamic_framerate", 0) in ctl.sets
    assert lock.dynamic_framerate == 0
    assert camera._switch_original == {"dynamic_framerate": 1}  # noqa: SLF001


def test_re_asserting_a_pin_never_overwrites_the_remembered_value(ctl):
    """A reconnect and a camera reopen both re-assert the pinned regime. If
    the re-assert re-read the control it would remember the PIN as his
    setting, and the un-pin would then hand him back our own value forever."""
    camera = V4L2Camera()
    asyncio.run(camera.apply_lock(dynamic_framerate=0))
    asyncio.run(camera.apply_lock(dynamic_framerate=0))
    asyncio.run(camera.apply_lock(dynamic_framerate=0))
    assert camera._switch_original == {"dynamic_framerate": 1}  # noqa: SLF001


def test_un_pinning_hands_his_own_value_back(ctl):
    """THE OWN-THE-FLAG CONTRACT, `fixture_brightness.owned` one layer down.
    A run un-pins by naming the control null, which is exactly the
    all-default request every restore path already sends."""
    camera = V4L2Camera()
    asyncio.run(camera.apply_lock(dynamic_framerate=0))
    assert ctl.values["exposure_dynamic_framerate"] == 0
    lock = asyncio.run(camera.apply_lock(dynamic_framerate=None))
    assert ctl.values["exposure_dynamic_framerate"] == 1, "his own setting"
    assert lock.dynamic_framerate == 1
    assert camera._switch_original == {}                    # noqa: SLF001


def test_a_camera_without_the_control_is_left_completely_alone(ctl):
    """Absence is not a refusal and is not a write. A camera that cannot
    drop its own frame rate has nothing to pin."""
    ctl.menus = MENUS.replace(
        "    exposure_dynamic_framerate 0x009a0903 (bool)    : default=0 value=1\n",
        "")
    del ctl.values["exposure_dynamic_framerate"]
    lock = asyncio.run(V4L2Camera().apply_lock(dynamic_framerate=0))
    assert "exposure_dynamic_framerate" not in dict(ctl.sets)
    assert lock.dynamic_framerate is None
    assert lock.manual_refusals == [], "absence is never a refusal"


def test_a_driver_that_takes_the_write_and_keeps_its_value_is_refused(ctl):
    """The dangerous case, because the frames still arrive and only the
    numbers are wrong — the same rule the four levers live by."""
    ctl.stuck.add("exposure_dynamic_framerate")
    lock = asyncio.run(V4L2Camera().apply_lock(dynamic_framerate=0))
    assert lock.dynamic_framerate == 1
    assert any("dynamic_framerate=0" in r for r in lock.manual_refusals)


def test_the_sensor_frame_rate_is_read_off_the_device_not_the_tap_rate(ctl):
    """The client PACES ITS SENDS at 5 fps; the SENSOR negotiates its own
    frame interval and frequently ignores an unsupported request. Deriving
    the ceiling from the tap rate would give 2000 x100 us of headroom on a
    camera that physically has 333."""
    camera = V4L2Camera(fps=5.0)
    assert camera._read_sensor_fps() == 30.0               # noqa: SLF001
    ctl.parm = None
    assert camera._read_sensor_fps() is None, \
        "a camera that will not say is None, never a guess"  # noqa: SLF001


# ── 5. THE LEVER SELF-TEST IS NOT WEAKENED ─────────────────────────────────
#
# The whole build is worthless if it bought a passing run by softening the
# judgement, so the two REFUSING shapes are re-proven INSIDE the short
# regime, on the real capture machinery, using his own measured numbers.

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))


class _Camera:
    """A camera made of a response curve — `tests/test_lever_selftest.py`'s
    own shape, so the two files cannot hold two ideas of a fake camera."""

    def __init__(self, respond):
        self.respond = respond
        self.captures = 0

    def frame(self, exposure, lit: bool) -> np.ndarray:
        grid = np.zeros((36, 64), dtype=np.float64)
        if lit:
            grid[10:18, 20:28] = float(self.respond(exposure, self.captures))
        return grid


class _Session(cs.SessionCameraDouble):
    pose_id = "pose-short"
    id = "sess-short"
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
                    **BRIO, "exposure_time": None, "manual_refusals": []}

    def __init__(self, camera):
        self.camera = camera
        self.camera_configs = []
        self.dark_next = True
        self.hello = {"client": lever_selftest.NATIVE_CLIENT}
        self.camera_lock = dict(self.lock.as_dict())

    def refusal(self):
        return None

    def _camera_clock(self):
        return 0.0

    def _camera_lock_view(self):
        out = {**self.camera_lock,
               "exposure_time": self.camera_request.exposure_time}
        if self.camera_request.dynamic_framerate is not None:
            out["dynamic_framerate"] = self.camera_request.dynamic_framerate
        return out

    async def gather(self, seconds, min_frames=1):
        lit = not self.dark_next
        self.dark_next = not self.dark_next
        if lit:
            self.camera.captures += 1
        grid = self.camera.frame(self.camera_request.exposure_time, lit)
        return [grid, grid], [10, 10]


def _deps(session, **kw):
    async def get_virtuals():
        return {"strip": {"active": True, "pixel_count": 20,
                          "config": {"grouping": 1},
                          "segments": [["strip-fixture", 0, 19, False]],
                          "effect": {"type": "singleColor", "config": {}}}}

    async def chains():
        return {"strip": [{"id": "strip-fixture", "type": "wled"}]}

    async def open_hold(*a, **k):
        return {"held": True}

    async def nothing(*a, **k):
        return None

    return room_mapping.RunDeps(
        session=session, get_virtuals=get_virtuals, carrier_devices=chains,
        open_hold=open_hold, close_hold=nothing, sleep=nothing,
        clock=lambda: 0.0, spectra_owns=lambda: True, **kw)


def _run(respond, **kw):
    sess = _Session(_Camera(respond))
    return sess, asyncio.run(lever_selftest.run_selftest(
        RoomMap(name="Living room", carrier_ids=["strip"], axis=AXIS),
        _deps(sess), **kw))


def test_a_camera_that_drifts_inside_the_short_regime_still_refuses():
    """HIS OWN MEASURED DRIFT, 23x between two identical commands, moved
    into the short regime. The band it has to clear (`REPEAT_BAND`) is
    untouched and it still fails it."""
    def wanders(exposure, n):
        return 0.2 * float(exposure or 200) / (23.0 if n >= 3 else 1.0)

    _sess, verdict = _run(wanders)
    assert verdict.verdict == mapping_refusals.LEVER_DRIFT
    assert verdict.refuses
    assert max(r.exposure_time for r in verdict.readings) <= 83


def test_a_camera_that_does_not_respond_inside_the_short_regime_still_refuses():
    """The `exposure_dynamic_framerate=0` half of his evening: commanded 62
    measured 12.577 and commanded 250 measured 2.46 — MORE time, LESS light.
    A camera behaving that way inside the short regime is refused exactly as
    hard, and `MIN_RESPONSE_FRACTION` did not move to allow it."""
    def backwards(exposure, _n):
        return 40.0 if (exposure or 0) <= 40 else 6.0

    _sess, verdict = _run(backwards)
    assert verdict.verdict == mapping_refusals.LEVER_NO_RESPONSE
    assert verdict.refuses


def test_the_judgement_constants_did_not_move():
    """A build that made a run pass by lowering a bar would have measured
    nothing. These are the four numbers the verdict is decided by, and this
    file exists to make moving one a deliberate, visible act."""
    assert lever_selftest.COMMANDED_FACTOR == 4.0
    assert lever_selftest.MIN_PROVABLE_FACTOR == 2.0
    assert lever_selftest.MIN_RESPONSE_FRACTION == 0.25
    assert lever_selftest.REPEAT_BAND == 1.5
    assert light_field.UNSEEN_WEIGHT == 1.0


def test_two_different_commands_and_one_repeat_survive_the_cap():
    """The SHAPE of the test — A, B, B again — is what makes drift
    detectable at all. A ceiling that collapsed the two commands into one
    would have quietly deleted the repeat's meaning."""
    _sess, verdict = _run(lambda e, _n: 0.2 * float(e or 200))
    dim, bright, repeat = (r.exposure_time for r in verdict.readings)
    assert dim < bright and bright == repeat
    assert bright / dim >= lever_selftest.MIN_PROVABLE_FACTOR
