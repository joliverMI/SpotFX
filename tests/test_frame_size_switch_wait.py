"""A CLIENT THAT CAN DELIVER 1920x1080 IS NEVER REFUSED FOR TAKING A MOMENT
TO START.

THE EVENING THIS EXISTS FOR (2026-09-06, the sconce commissioning). The same
camera, the same pose, three presses: 22:09 negotiated 1920x1080 and ran;
22:44 REFUSED with "this run needs 1920x1080 frames and the camera is still
sending 320x180 ... 2 frames arrived at the old size while this run waited";
22:46 succeeded again. Nothing about the camera changed between them — the
run's bound did not fit the act it had commanded.

WHAT THE CLIENT ACTUALLY DOES when a `config` names a new frame size AND a
lever in the same message (`spectra/capture_client/session.py::_apply_config`):

  * `camera.set_frame_size` CLOSES the pixel pipe and re-spawns the decoder
    at the new capture size, waiting for the first frame to arrive there —
    and it allows ITSELF 15 s for that one act;
  * every control is written and re-read out of the device, twice over the
    switch;
  * the lever that moved arms `SENSOR_APPLY_FRAMES`, so the next frames are
    DISCARDED before one is sent at all.

All three used to share ONE fixed 4.0 s window, so the exposure settle spent
the frame size's own wait and a camera that switched a second later was
refused by name. These specs model that client — silent through the reopen,
a straggler or two at the old size, then full resolution — and drive the
REAL commissioning run over it.

THE NEGATIVE CONTROL IS HALF THE PROOF: a client that never switches at all
must still refuse by name, or the fix is "wait forever and always pass".
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from spectra.models.room_map import AxisCalibration, Point
from spectra.services import capture_settings as cs
from spectra.services import commissioning, room_mapping

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))

#: MODELLED SECONDS PER READ OF THE CLOCK. The wait polls; time passes while
#: it does. Advancing the model's clock on every read is what lets a bound
#: measured in seconds be proven in milliseconds — the same trick
#: `tests/test_ambient_transition.py` uses to interrupt a real sequence.
CLOCK_STEP_S = 0.25
CLIENT_FPS = 5.0


class _SlowClient(cs.SessionCameraDouble):
    """A REAL CLIENT'S SHAPE THROUGH A FRAME-SIZE SWITCH, on a modelled
    clock: a straggler or two still at the old size, then silence while the
    pipe restarts and the sensor pays for the lever, then frames at the size
    that was asked for.

    It inherits the negotiation rather than modelling it — every decision
    under test is the production one."""

    pose_id = "pose-slow"
    run_abort = None
    keep_full_frames = False

    #: modelled seconds the PIPE RESTART costs — close the decoder, re-spawn
    #: it at the new capture size, wait for a first frame there. 2.0 sits
    #: comfortably INSIDE the shipped 4.0 s window, which is what makes the
    #: levered case below a statement about the lever and not about the size.
    switch_after_s = 2.0
    #: modelled seconds the SENSOR SETTLE costs on top, and only when the
    #: same message named a lever: `apply_lock` arms SENSOR_APPLY_FRAMES and
    #: the frames that follow are DISCARDED before one is sent at all.
    settle_after_s = 3.0
    #: frames already in flight at the old size when the config lands —
    #: exactly what the refusal sentence counted that night.
    stragglers = 2
    #: False models the client this refusal was WRITTEN for: an old tab that
    #: never adopts the size at all.
    switches = True

    def __init__(self, exposure_time=None):
        self.camera_configs = []
        self.dark_next = True
        self.full = []
        self.n = 4
        self._t = 0.0
        self._switch_at = float("inf")
        self._owed = 0
        self._next_frame_at = 0.0
        self.frame_times: list[float] = []
        self.camera_lock = {"exposure_time": exposure_time, "gain": None,
                            "white_balance": None, "focus": None,
                            "manual_refusals": []}
        # the lock this session already had, from before this run asked for
        # anything — a live session is never without one.
        self.camera_lock_at = 0.0

    # ── the modelled clock, and the frames it carries ─────────────────────
    def _camera_clock(self) -> float:
        self._t += CLOCK_STEP_S
        self._deliver()
        return self._t

    def _camera_frame_times(self) -> list:
        return self.frame_times[-16:]

    def _deliver(self) -> None:
        while self._next_frame_at <= self._t:
            at, self._next_frame_at = (self._next_frame_at,
                                       self._next_frame_at + 1.0 / CLIENT_FPS)
            if at < self._switch_at:
                if self._owed <= 0:
                    continue          # the pipe is closed: nothing is sent
                self._owed -= 1
                got = self.active_frame_size
            elif not self.switches:
                got = self.active_frame_size
            else:
                got = cs.choose(self.frame_size, *self.camera_source)
            self.note_frame(got[0], got[1], *self.camera_source)
            self.frame_times.append(at)
            # every frame carries the camera's own lock, so this is also
            # "when did the camera last answer" — see mapping_session.
            self.camera_lock_at = at

    async def _send_camera_config(self, payload: dict) -> None:
        self.camera_configs.append(payload)
        size = payload.get("frame_size") or {}
        want = (int(size.get("width") or 0), int(size.get("height") or 0))
        levered = any(payload.get(name) is not None
                      for name, *_ in cs.LEVER_BOUNDS)
        cost = 0.0
        if want and want != tuple(self.active_frame_size):
            cost += self.switch_after_s
        if levered:
            cost += self.settle_after_s
        self._switch_at = self._t + cost
        self._owed = self.stragglers

    # ── the rest of a session a run needs ─────────────────────────────────
    class lock:
        exposure_locked = True
        white_balance_locked = True
        exposure_mode = "manual"
        white_balance_mode = "manual"

        @staticmethod
        def as_dict():
            return {"exposure_locked": True, "white_balance_locked": True,
                    "manual_refusals": []}

    def refusal(self):
        return None

    async def gather(self, seconds, min_frames=1):
        grid = np.full((36, 64), 0.5, dtype=np.float64)
        return [grid, grid], [10, 10]

    async def gather_full(self, seconds, *, min_frames=1):
        w, h = self.active_frame_size
        return [type("TF", (), {"at_s": float(k),
                                "frame": np.zeros((h, w), dtype=np.uint8)})()
                for k in range(max(min_frames, self.n))]


def _mapper_virtuals():
    def v(vid, segments, mapping="span", active=True):
        pixels = sum(hi - lo + 1 for _d, lo, hi in segments)
        return {"id": vid, "active": active,
                "segments": [[d, lo, hi, False, 0] for d, lo, hi in segments],
                "pixel_count": pixels,
                "config": {"mapping": mapping, "rows": 1, "grouping": 1},
                "effect": {"type": "singleColor", "config": {}}}
    return {"tv-mapper": v("tv-mapper", [("tv-backlight", 0, 15)],
                           mapping="copy"),
            "tv-backlight": v("tv-backlight", [("tv-backlight", 0, 15)],
                              active=False)}


def _deps(sess):
    async def get_virtuals():
        return _mapper_virtuals()

    async def chains():
        return {"tv-mapper": [{"id": "tv-backlight", "type": "wled"}]}

    async def nothing(*_a, **_k):
        return None

    async def open_hold(*_a, **_k):
        return {"held": True}

    return room_mapping.RunDeps(
        session=sess, get_virtuals=get_virtuals, carrier_devices=chains,
        open_hold=open_hold, close_hold=lambda: asyncio.sleep(0),
        sleep=nothing, clock=lambda: 0.0, spectra_owns=lambda: True,
        activate=nothing, deactivate=nothing)


def _frame_refusal(result) -> str:
    return (result.reason
            if result.refusal == "camera" and "still sending" in result.reason
            else "")


# ── the defect ────────────────────────────────────────────────────────────

def test_a_read_waits_out_a_client_whose_lever_delays_the_switch():
    """RED on the shipped 4.0 s window; the whole defect in one assertion.

    This client restarts its pipe in 2.0 s — well inside the shipped window
    — and then pays 3.0 s of sensor settle for the integration time that
    arrived in the SAME message. 5.0 s of honest work against a 4.0 s bound
    that both costs had to share."""
    sess = _SlowClient(exposure_time=1000)
    result = asyncio.run(commissioning.run_commission(
        "tv-mapper", _deps(sess), camera=cs.request(exposure_time=1000)))
    assert not _frame_refusal(result), _frame_refusal(result)
    assert result.camera["frame_size"] == {"width": 1920, "height": 1080}, \
        "the run read at full resolution, not at the map's frame"


def test_the_same_client_without_a_lever_already_worked():
    """THE CONTROL THAT MAKES THE ONE ABOVE A STATEMENT ABOUT THE LEVER.
    The identical client, the identical 2.0 s pipe restart, no integration
    time in the message — green on the shipped code and green after. It is
    the settle arriving in the same message that pushed the other one past
    a window they had to share, which is why the field failure was flaky and
    why it was worse with a lever."""
    sess = _SlowClient()
    result = asyncio.run(commissioning.run_commission("tv-mapper",
                                                      _deps(sess)))
    assert not _frame_refusal(result), _frame_refusal(result)
    assert result.camera["frame_size"] == {"width": 1920, "height": 1080}


# ── the negative control ──────────────────────────────────────────────────

def test_a_client_that_never_switches_is_still_refused_by_name():
    """Half the proof: the patience must not be "wait forever and pass"."""
    sess = _SlowClient(exposure_time=1000)
    sess.switches = False
    sess.stragglers = 10_000          # keeps sending 320x180, forever
    result = asyncio.run(commissioning.run_commission(
        "tv-mapper", _deps(sess), camera=cs.request(exposure_time=1000)))
    said = _frame_refusal(result)
    assert said and "1920x1080" in said and "320x180" in said
    assert result.camera["frame_size"] == {"width": 320, "height": 180}


# ── the bound itself ──────────────────────────────────────────────────────

def test_the_bound_is_the_three_costs_added_not_shared():
    """The arithmetic, stated: a config carrying a frame size AND a lever
    pays the pipe restart AND the sensor settle AND a frame period — one
    after the other on the client, so added here."""
    plain = cs.frame_switch_wait_s(None, CLIENT_FPS, lever_moved=False)
    levered = cs.frame_switch_wait_s(1000, CLIENT_FPS, lever_moved=True)
    assert plain == pytest.approx(cs.CLIENT_RESIZE_BUDGET_S + 1.0 / CLIENT_FPS)
    assert levered == pytest.approx(
        plain + cs.regime_settle_s(1000, CLIENT_FPS))
    assert levered > room_mapping.FRAME_SWITCH_WAIT_S, \
        "the run's own constant was shorter than the act it commanded"


def test_a_caller_asking_for_longer_still_gets_longer():
    """The caller's number is a FLOOR, never a ceiling: the negotiation is
    the only place that knows what the client was asked to do, so it raises
    a short bound and never lowers a long one."""
    d = _SlowClient()
    d.switch_after_s = 0.0
    asyncio.run(d.apply_camera(cs.CameraRequest(frame_size=cs.COMMISSION_PROFILE)))
    assert d.switch_wait_s() >= cs.CLIENT_RESIZE_BUDGET_S
