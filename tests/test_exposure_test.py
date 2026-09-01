"""THE EXPOSURE COMPARISON — tonight's two-minute question, proven offline.

What it has to get right, and each of these was a way it could have been
worthless:

  * it MEASURES the difference (two real captures through the map's own
    protocol), rather than reporting the settings it asked for;
  * it STORES NOTHING — two regimes are two byte scales, and one stored
    pose carrying both would be exactly the lie `mapping_session._adopt_pose`
    exists to prevent;
  * it PUTS THE CAMERA BACK, on every path out, or every run after it
    inherits a long integration time;
  * "the default regime saw nothing" is a RESULT, not a failure — it is the
    interesting half of "could not, at default camera settings";
  * a request naming neither lever is refused, because it would be
    comparing a regime with itself and reporting the noise.
"""
from __future__ import annotations

import asyncio

import numpy as np

from spectra.models.room_map import AxisCalibration, Point, RoomMap
from spectra.services import capture_settings as cs
from spectra.services import exposure_test, light_field, room_mapping

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))


class _Session(cs.SessionCameraDouble):
    """A camera whose BRIGHTNESS depends on the regime it was put in — which
    is the whole thing being measured. `manual_gain` is how much more light
    a frame carries once a manual integration time or gain is asked for."""
    pose_id = "pose-exp"
    run_abort = None

    def __init__(self, manual_gain=3.0):
        self.camera_configs = []
        self.manual_gain = manual_gain
        self.dark_next = True
        self.camera_lock = {"exposure_time": None, "gain": None,
                            "manual_refusals": []}

    class lock:
        exposure_locked = True
        white_balance_locked = True
        exposure_mode = "manual"
        white_balance_mode = "manual"

    def refusal(self):
        return None

    async def _send_camera_config(self, payload):
        await super()._send_camera_config(payload)
        # The device answers with what it became — the read-back the gate
        # reads, never the request.
        self.camera_lock = {
            "exposure_time": payload.get("exposure_time"),
            "gain": payload.get("gain"), "manual_refusals": []}

    async def gather(self, seconds, min_frames=1):
        req = self.camera_request
        scale = self.manual_gain if req.manual else 1.0
        value = 0.0 if self.dark_next else 0.05 * scale
        self.dark_next = not self.dark_next
        grid = np.full((36, 64), value * 255.0, dtype=np.float64)
        return [grid, grid], [10, 10]


def _virtual(device):
    return {"active": True, "pixel_count": 20, "config": {"grouping": 1},
            "segments": [[device, 0, 19, False]],
            "effect": {"type": "singleColor", "config": {}}}


def _deps(session, saved=None):
    async def get_virtuals():
        return {"strip": _virtual("strip-fixture")}

    async def chains():
        return {"strip": [{"id": "strip-fixture", "type": "wled"}]}

    async def open_hold(*a, **k):
        return {"held": True}

    async def sleep(_s):
        return None

    def save_room(room):
        (saved if saved is not None else []).append(room)

    return room_mapping.RunDeps(
        session=session, get_virtuals=get_virtuals, carrier_devices=chains,
        open_hold=open_hold, close_hold=lambda: asyncio.sleep(0), sleep=sleep,
        clock=lambda: 0.0, spectra_owns=lambda: True, save_room=save_room)


def _room():
    return RoomMap(name="Living room", carrier_ids=["strip"], axis=AXIS)


def _run(session, saved=None, **kw):
    kw.setdefault("exposure_time", 2000)
    kw.setdefault("gain", 64)
    return asyncio.run(exposure_test.compare_regimes(
        _room(), _deps(session, saved), **kw))


# ── the measurement ───────────────────────────────────────────────────────

def test_it_measures_the_difference_rather_than_reporting_the_request():
    sess = _Session(manual_gain=3.0)
    out = _run(sess)
    assert out.ok, out.reason
    got = {r.label: r for r in out.regimes}
    assert set(got) == {"default", "manual"}
    assert got["manual"].weight > got["default"].weight
    assert out.better == "manual"
    assert abs(out.ratio - 3.0) < 0.2, out.ratio
    # the numbers came from real captures, not from the request
    assert got["manual"].lit_frames >= 2 and got["default"].lit_frames >= 2


def test_two_regimes_within_the_tie_band_are_a_tie_not_a_winner():
    """A footprint weight is a sum over 2,304 cells of a noisy difference.
    Calling a 3% gap a win would report the instrument's own wobble as a
    finding."""
    out = _run(_Session(manual_gain=1.03))
    assert out.ok and out.better == "tie", out.ratio


def test_a_default_regime_that_saw_nothing_is_a_result_not_a_failure():
    """THE INTERESTING HALF of "could not, at default camera settings": a
    regime measuring nothing is a real reading, so the comparison completes
    and says which regime saw the light."""
    sess = _Session(manual_gain=200.0)
    sess.__class__.gather = _gather_dark_default(sess.__class__.gather)
    out = _run(sess)
    got = {r.label: r for r in out.regimes}
    assert got["default"].unseen and got["default"].ok
    assert "measured no usable light" in got["default"].reason
    assert out.ok and out.better == "manual" and out.ratio is None
    assert "no ratio" in out.summary


def _gather_dark_default(real):
    async def gather(self, seconds, min_frames=1):
        if not self.camera_request.manual:
            grid = np.zeros((36, 64), dtype=np.float64)
            return [grid, grid], [0, 0]
        return await real(self, seconds, min_frames)
    return gather


# ── what it must never do ─────────────────────────────────────────────────

def test_it_stores_nothing_however_often_it_is_run():
    """Two regimes are two byte scales. One stored pose carrying both would
    be exactly the "one measurement labelled as two" — or worse, two
    labelled as one — that the pose model exists to prevent."""
    saved = []
    room = _room()
    out = asyncio.run(exposure_test.compare_regimes(
        room, _deps(_Session(), saved), exposure_time=2000, gain=64))
    assert out.ok
    assert saved == [], "save_room was never called"
    assert room.footprints == [], "and his room object is untouched"


def test_it_puts_the_camera_back_on_every_path_out():
    sess = _Session()
    _run(sess)
    assert not sess.camera_request.manual, \
        "a later run must not inherit this comparison's integration time"
    # and even when a regime refuses part-way
    hostile = _Session()
    hostile.camera_lock = {"exposure_time": 156.0, "gain": None,
                           "manual_refusals": ["asked 2000, got 156"]}

    async def _fixed(payload):
        hostile.camera_configs.append(payload)
        got = cs.choose(hostile.frame_size, *hostile.camera_source)
        hostile.note_frame(got[0], got[1], *hostile.camera_source)

    hostile._send_camera_config = _fixed
    out = _run(hostile)
    assert not out.ok
    assert not hostile.camera_request.manual


def test_a_request_naming_neither_lever_is_refused():
    out = _run(_Session(), exposure_time=None, gain=None)
    assert not out.ok and out.refusal == "no_levers"
    assert "same regime" in out.reason


def test_the_summary_says_what_the_comparison_does_not_license():
    out = _run(_Session(manual_gain=3.0))
    assert "NOT two footprints of one pose" in out.summary
    assert "must not be compared with any other footprint" in out.summary
    assert "Nothing was stored" in out.summary


# ── the verdict function on its own ───────────────────────────────────────

def test_verdict_is_one_definition_so_the_word_and_the_number_agree():
    assert exposure_test.verdict(10.0, 30.0) == ("manual", 3.0)
    assert exposure_test.verdict(30.0, 10.0)[0] == "default"
    assert exposure_test.verdict(10.0, 10.5)[0] == "tie"
    assert exposure_test.verdict(0.0, 5.0) == ("manual", None), \
        "a zero default has no ratio rather than an invented infinity"
    assert exposure_test.verdict(0.0, 0.0) == ("tie", None)
