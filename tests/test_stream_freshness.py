"""A STAMP IS NOT A PHOTON — the stale-stream defect, in both directions.

THE EVENING THIS EXISTS FOR (2026-09-02, his laptop, the first time the
lever self-test met a real camera). Three commanded regimes measured:

    commanded  500 x100 us  ->  0.000
    commanded 2000 x100 us  ->  444.282
    commanded 2000 x100 us  ->  0.043      <- the SAME command

Two identical commands ten-thousand-fold apart, while every driver
read-back held Manual throughout. Nothing was wrong with the lever, and
nothing was wrong with the judgement: the frames were OLD. The client reads
pixels out of an ffmpeg pipe, and the transport between the two holds whole
frames — measured at up to NINETEEN 320x180 frames, 3.8 s at 5 fps, and it
SATURATES there because the frame loop paces itself at exactly the camera's
own rate and can never catch up (`scripts/check_stream_freshness.py` §1
measures it against a real pipe). 3.8 s is longer than a whole capture
phase, so a lit window can land entirely on frames whose photons predate
the lamp.

WHY NOTHING CAUGHT IT. Every proof of this path used
`camera.SyntheticCamera`, which is a function: it has no transport, no
queue, and a control change is visible in the very next frame. It is fresh
BY CONSTRUCTION, which is exactly why it could never have seen this. So
this file models the transport the synthetic camera does not have, and
drives the REAL `lever_selftest.run_selftest`, the REAL `room_mapping.
_map_one`, the REAL `light_field` footprint arithmetic and the REAL
`judge` through it.

THE TWO LAGS ARE DIFFERENT AND EACH HAS ITS OWN FIX. The TRANSPORT lag is
the queue, and no server-side window can see past it — that is the
client's own drain (`camera.newest_of`). The SENSOR lag is the frames a
control change has not reached yet, which no drain can reach — that is
`capture_settings.regime_settle_s`. Each is proven here with the other
one turned off, or a passing pair would say nothing about either.

RED-WHEN-LYING: every red case below is run against the shipped-that-night
behaviour (`drain=False`, `regime_settle_s -> 0`) and must FAIL there. A
proof bar that cannot fail on the defect it was written for is decoration.
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from spectra.capture_client import camera as cam
from spectra.models.room_map import AxisCalibration, Point, RoomMap
from spectra.services import capture_settings as cs
from spectra.services import (capture_source, lever_selftest, light_field,
                              mapping_refusals, room_mapping)

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))

#: The lit patch, in grid cells — the same shape `test_lever_selftest.py`
#: uses, so a weight here means what it means there.
PATCH = 8

#: THE REALISTIC BAND, in seconds of transport queue, and it is not
#: invented: 0.2 s is one frame at the wire's own 5 fps and 3.8 s is the
#: MEASURED saturation depth of the pipe plus the client's own StreamReader
#: limit at the map rung (`scripts/check_stream_freshness.py` §1). A
#: boundary is swept, never sampled once — this codebase has been caught
#: by a fixed band before (`pose_fingerprint.COHERENCE_FRACTION`).
LAG_BAND = (0.2, 0.6, 1.0, 1.6, 2.2, 3.0, 3.8)

#: How much deeper the queue gets each time the client blocks. Every
#: `apply_lock` runs BLOCKING `v4l2-ctl` subprocesses on the event loop and
#: the paced `read_lock` runs more; the loop reads no frames while they
#: run, so every one of them ratchets the backlog up and nothing ever
#: brings it down. This is what makes two IDENTICAL commands land on
#: opposite sides of the lit boundary.
STALL_PER_COMMAND_S = 0.5


# ── the transport the synthetic camera does not have ───────────────────────

class Stream:
    """A CAMERA WITH A QUEUE IN FRONT OF IT, on a virtual clock.

    Everything about the room is real: the lamp is driven by the real
    `_map_one`'s own hold writes and the exposure by the real
    `apply_camera`. What is modelled is exactly the two lags:

      * TRANSPORT — a frame read out at time t was captured at t - lag.
        With `drain` the client throws away everything queued behind the
        newest, so the lag is one frame period whatever the queue holds;
        without it the client hands back the oldest and the lag is the
        whole queue, which RATCHETS every time the client blocks.
      * SENSOR — a commanded integration time reaches the sensor
        `SENSOR_APPLY_FRAMES` frames later, so frames captured before then
        were exposed under the previous regime."""

    def __init__(self, *, lag_s: float, drain: bool, fps: float = 5.0,
                 stall_s: float = STALL_PER_COMMAND_S) -> None:
        self.fps = fps
        self.drain = drain
        self.stall_s = stall_s
        self.lag_s = lag_s
        self.now = 0.0
        #: (t, lit) and (t, exposure) — the world, as the production code
        #: actually drove it.
        self.lamp: list[tuple[float, bool]] = [(-1e9, False)]
        self.regimes: list[tuple[float, int]] = [(-1e9, 0)]
        self.reads: list[dict] = []

    # -- the world, written by the production code --------------------------
    def set_lamp(self, lit: bool) -> None:
        self.lamp.append((self.now, bool(lit)))

    def command(self, exposure) -> None:
        self.regimes.append((self.now, int(exposure or 0)))
        if not self.drain:
            # THE RATCHET. The client blocked on `v4l2-ctl` and read no
            # frames while it did; a drained client throws the extra away
            # for nothing (19 frames cost 23 ms, measured).
            self.lag_s += self.stall_s

    # -- what a frame read at `t` was actually looking at --------------------
    def _at(self, timeline, t):
        got = timeline[0][1]
        for when, value in timeline:
            if when <= t:
                got = value
        return got

    def _effective_exposure(self, photon_t: float) -> int:
        """The regime the SENSOR was in, which trails the command by
        `SENSOR_APPLY_FRAMES` frames however fresh the transport is."""
        return self._at(self.regimes,
                        photon_t - cs.SENSOR_APPLY_FRAMES / self.fps)

    def read(self, t: float) -> tuple[bool, int]:
        lag = (1.0 / self.fps) if self.drain else self.lag_s
        photon_t = t - lag
        return self._at(self.lamp, photon_t), self._effective_exposure(photon_t)


class _Session(cs.SessionCameraDouble):
    """A connected, locked, NATIVE session whose frames come off `Stream`."""
    pose_id = "pose-stream"
    id = "sess-stream"
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

    def __init__(self, stream: Stream, *, fresh_frames=True) -> None:
        self.stream = stream
        self.hello = {"client": lever_selftest.NATIVE_CLIENT,
                      "host": "capture-pi"}
        if fresh_frames is not None:
            self.hello["fresh_frames"] = bool(fresh_frames)
        self.camera_lock = dict(self.lock.as_dict())

    def refusal(self):
        return None

    def _camera_clock(self):
        return self.stream.now

    def _camera_lock_view(self):
        # THE DRIVER TAKES EVERYTHING, which is the whole point: nothing on
        # the read-back path can tell tonight's camera from an honest one.
        return {**self.camera_lock,
                "exposure_time": self.camera_request.exposure_time}

    def observed_fps(self):
        return self.stream.fps

    async def apply_camera(self, req):
        await super().apply_camera(req)
        self.stream.command(req.exposure_time)

    async def gather(self, seconds, min_frames=1):
        """Frames READ OUT over the next `seconds`, each carrying whatever
        the world looked like when its photons landed."""
        start, period = self.stream.now, 1.0 / self.stream.fps
        self.stream.now += seconds
        grids, maxima = [], []
        t = start
        while t <= start + seconds + 1e-9:
            lit, exposure = self.stream.read(t)
            grid = np.zeros((36, 64), dtype=np.float64)
            if lit:
                # A SENSOR IN ITS LINEAR REGIME: more integration time,
                # more light. Nothing here is broken — that is the finding.
                grid[10:10 + PATCH, 20:20 + PATCH] = 0.3 * exposure
            grids.append(grid)
            maxima.append(int(grid.max()))
            self.stream.reads.append(
                {"t": t, "lit": lit, "exposure": exposure,
                 # WHAT THIS READING ASKED FOR, beside what the sensor was
                 # actually in — the two disagree exactly while a regime
                 # change is still travelling.
                 "commanded": self.stream._at(self.stream.regimes, t)})
            t += period
        while len(grids) < max(1, min_frames):
            grids.append(grids[-1])
            maxima.append(maxima[-1])
        return grids, maxima


def _virtual(device):
    return {"active": True, "pixel_count": 20, "config": {"grouping": 1},
            "segments": [[device, 0, 19, False]],
            "effect": {"type": "singleColor", "config": {}}}


def _deps(session, stream: Stream):
    async def get_virtuals():
        return {"strip": _virtual("strip-fixture")}

    async def chains():
        return {"strip": [{"id": "strip-fixture", "type": "wled"}]}

    async def open_hold(_program, _level, *, step="dark", **_kw):
        # THE REAL PHASE STRUCTURE DRIVES THE MODEL: `_map_one` says which
        # step it is in and the lamp follows, so nothing about the timing
        # under test is invented here.
        stream.set_lamp(step == "lit")
        return {"held": True}

    async def close_hold():
        stream.set_lamp(False)

    async def sleep(seconds):
        stream.now += max(0.0, float(seconds))

    return room_mapping.RunDeps(
        session=session, get_virtuals=get_virtuals, carrier_devices=chains,
        open_hold=open_hold, close_hold=close_hold, sleep=sleep,
        clock=lambda: stream.now, spectra_owns=lambda: True)


def _room():
    return RoomMap(name="Living room", carrier_ids=["strip"], axis=AXIS)


def _run(*, lag_s: float, drain: bool, regime_settle: bool,
         stall_s: float = STALL_PER_COMMAND_S) -> lever_selftest.Verdict:
    stream = Stream(lag_s=lag_s, drain=drain, stall_s=stall_s)
    session = _Session(stream, fresh_frames=drain)
    if not regime_settle:
        # THE SHAPE THIS REPLACED: measure the moment the DRIVER answers.
        real = cs.regime_settle_s
        cs.regime_settle_s = lambda *_a, **_k: 0.0
        try:
            return asyncio.run(lever_selftest.run_selftest(
                _room(), _deps(session, stream)))
        finally:
            cs.regime_settle_s = real
    return asyncio.run(lever_selftest.run_selftest(
        _room(), _deps(session, stream)))


def _weights(verdict) -> list[float]:
    return [round(r.weight, 3) for r in verdict.readings]


# ── ONE: the drain rule itself ─────────────────────────────────────────────

def test_newest_of_returns_the_newest_and_says_what_it_dropped():
    queue = [b"a", b"b", b"c", b"d"]

    async def try_read(blocking):
        if queue:
            return queue.pop(0)
        return b"live" if blocking else None

    got, dropped = asyncio.run(cam.newest_of(try_read))
    assert got == b"d" and dropped == 3


def test_newest_of_waits_when_the_queue_is_empty_and_drops_nothing():
    async def try_read(blocking):
        return b"live" if blocking else None

    got, dropped = asyncio.run(cam.newest_of(try_read))
    assert got == b"live" and dropped == 0


def test_newest_of_is_bounded_so_a_fast_camera_cannot_spin_here():
    async def try_read(_blocking):
        return b"x"

    _got, dropped = asyncio.run(cam.newest_of(try_read, max_frames=5))
    assert dropped == 5


def test_a_dead_pipe_is_none_and_never_a_stale_frame():
    async def try_read(_blocking):
        return None

    got, dropped = asyncio.run(cam.newest_of(try_read))
    assert got is None and dropped == 0


# ── TWO: the sensor's own lag, and who declares freshness ──────────────────

def test_a_control_that_moved_costs_the_sensor_frames_and_they_are_counted():
    camera = cam.V4L2Camera("/dev/null")
    asyncio.run(camera.apply_lock(exposure_time=500))
    assert camera._apply_owed == cam.SENSOR_APPLY_FRAMES

    served = [b"old1", b"old2", b"old3", b"new"]

    async def read(_blocking):
        return served.pop(0) if served else None

    camera._read = read                                # type: ignore[method-assign]
    assert asyncio.run(camera.frame()) == b"new"
    assert camera.regime_discards == cam.SENSOR_APPLY_FRAMES
    assert camera._apply_owed == 0


def test_re_asking_for_the_value_already_pinned_costs_nothing():
    camera = cam.V4L2Camera("/dev/null")
    asyncio.run(camera.apply_lock(exposure_time=500))
    camera._apply_owed = 0
    # A RECONNECT'S RE-ASSERT writes the same values again; paying three
    # frames for it every time would make an ordinary drop expensive.
    asyncio.run(camera.apply_lock(exposure_time=500))
    assert camera._apply_owed == 0


def test_the_v4l2_backend_declares_fresh_frames_and_the_base_does_not():
    assert cam.V4L2Camera.fresh_frames is True
    assert cam.SyntheticCamera.fresh_frames is True
    # Nothing is promoted by silence: a new backend claims freshness by
    # implementing it, exactly as `capture_source.is_native` works.
    assert cam.BaseCamera.fresh_frames is False


def test_serves_fresh_frames_has_three_answers_and_none_is_not_no():
    class S:
        hello: dict = {}

    s = S()
    s.hello = {"client": "spectra-capture-client", "fresh_frames": True}
    assert capture_source.serves_fresh_frames(s) is True
    s.hello = {"client": "spectra-capture-client", "fresh_frames": False}
    assert capture_source.serves_fresh_frames(s) is False
    # THE BUILD THAT PRODUCED TONIGHT sends no such field, and a browser
    # cannot answer at all. Neither is a "no".
    s.hello = {"client": "spectra-capture-client"}
    assert capture_source.serves_fresh_frames(s) is None
    s.hello = {"user_agent": "Mozilla/5.0 (iPhone)"}
    assert capture_source.serves_fresh_frames(s) is None


def test_regime_settle_covers_the_sensor_and_the_transport_and_the_integration():
    # ARITHMETIC, not a tuned number: four frame periods plus the
    # integration the last of them spends collecting light.
    assert cs.regime_settle_s(2000, 5.0) == pytest.approx(
        (cs.SENSOR_APPLY_FRAMES + cs.TRANSPORT_LAG_FRAMES) / 5.0 + 0.2)
    # A LONG INTEGRATION CAPS THE FRAME RATE, so the settle grows with it
    # rather than pretending the tap's own rate still holds.
    assert cs.regime_settle_s(20_000, 30.0) > cs.regime_settle_s(200, 30.0)


# ── THREE: the whole self-test, over a modelled transport ──────────────────

def test_an_instant_camera_is_green_either_way():
    """THE CONTROL. A stream with no queue and no ratchet — the synthetic
    camera every other proof uses — passes with or without the fix, which
    is why it could never have caught this."""
    for drain in (False, True):
        for settle in (False, True):
            v = _run(lag_s=0.0, drain=drain, regime_settle=settle,
                     stall_s=0.0)
            assert v.verdict == mapping_refusals.LEVER_OK, (
                f"drain={drain} settle={settle}: {v.verdict} {_weights(v)}")


def test_the_shipped_code_reproduces_tonights_shape_on_a_real_transport():
    """RED, AND IT IS HIS OWN TRIPLE. The build of 2026-09-02 — no drain,
    no regime settle — against a queue at the MEASURED saturation depth
    that ratchets every time the client blocks.

    His readings were 0.000 / 444.282 / 0.043: a dim regime that measured
    nothing, a bright one that measured plenty, and a repeat of that SAME
    command that measured nothing again. The model reproduces the shape,
    not the numbers — the numbers are his lamp's."""
    v = _run(lag_s=3.8, drain=False, regime_settle=False)
    dim, bright, repeat = _weights(v)
    assert dim < light_field.UNSEEN_WEIGHT, f"reading 1: {_weights(v)}"
    assert bright > light_field.UNSEEN_WEIGHT, (
        f"the bright regime has to have measured something, or this is "
        f"merely a dark room and not tonight's shape: {_weights(v)}")
    assert repeat < light_field.UNSEEN_WEIGHT, f"reading 3: {_weights(v)}"
    # TWO IDENTICAL COMMANDS, ORDERS APART — his reading 2 against his 3.
    assert bright / max(repeat, 1e-6) > 100.0, (
        f"the repeat of an identical command should be orders away: "
        f"{bright} then {repeat}")
    assert v.refuses and v.verdict == mapping_refusals.LEVER_DRIFT, (
        f"{v.verdict}: {v.reason}")


@pytest.mark.parametrize("lag_s", LAG_BAND)
def test_no_depth_of_a_queued_transport_reads_honestly_without_the_fix(lag_s):
    """RED, SWEPT. Not one point in the realistic band comes back OK on the
    shipped code — and each depth fails DIFFERENTLY (no signal, no
    response, drift), which is why a single sampled point would have said
    so little about the others."""
    v = _run(lag_s=lag_s, drain=False, regime_settle=False)
    assert v.verdict != mapping_refusals.LEVER_OK, (
        f"a {lag_s:g}s queue read as an honest camera: {_weights(v)}")


@pytest.mark.parametrize("lag_s", LAG_BAND)
def test_every_depth_in_the_band_reads_consistently_once_the_client_drains(lag_s):
    """GREEN, SWEPT. The whole band, including the measured 3.8 s
    saturation: the readings agree with each other and follow the command.
    Draining is what makes the depth stop mattering — throwing away 19
    frames costs 23 ms."""
    v = _run(lag_s=lag_s, drain=True, regime_settle=True)
    assert v.verdict == mapping_refusals.LEVER_OK, (
        f"{lag_s:g}s queue: {v.verdict} {_weights(v)} — {v.reason}")
    assert v.response_ratio >= lever_selftest.min_response_ratio()
    # THE DRIFT GATE IS UNCHANGED AND STILL STRICT — it is now simply
    # comparing two readings of the same world.
    assert (1.0 / lever_selftest.REPEAT_BAND
            <= v.repeat_ratio <= lever_selftest.REPEAT_BAND)


@pytest.mark.parametrize("lag_s", (0.2, 1.6, 3.8))
def test_every_frame_of_a_reading_was_exposed_in_the_regime_it_commanded(lag_s):
    """The SENSOR half, with the transport half already fixed — and each is
    proven with the other turned off, or a passing pair would say nothing
    about either.

    A drained client still hands back frames the commanded integration
    time has not reached yet. Without `regime_settle_s` a reading's DARK
    REFERENCE is taken in the PREVIOUS regime and then subtracted from a
    lit capture taken in the new one, which is precisely "two readings
    that are not of the same world"."""
    def straddles(settle: bool) -> bool:
        stream = Stream(lag_s=lag_s, drain=True)
        session = _Session(stream, fresh_frames=True)
        real = cs.regime_settle_s
        if not settle:
            cs.regime_settle_s = lambda *_a, **_k: 0.0
        try:
            asyncio.run(lever_selftest.run_selftest(
                _room(), _deps(session, stream)))
        finally:
            cs.regime_settle_s = real
        return any(r["exposure"] != r["commanded"] for r in stream.reads
                   if r["commanded"])

    assert straddles(False), (
        "the red control did not reproduce the straddle it exists to "
        "prove — this test would then pass for the wrong reason")
    assert not straddles(True), (
        "a capture window was still exposed in a regime it had not "
        "commanded, with the settle in place")


def test_the_refusal_names_the_stale_stream_first_when_the_client_did_not_say():
    v = _run(lag_s=1.0, drain=False, regime_settle=False)
    assert v.fresh_frames is False
    assert mapping_refusals.STALE_STREAM_FIRST_CHECK in v.reason, v.reason
    assert any("did not report whether its frames are fresh" in p
               for p in v.problems), v.problems


def test_a_fresh_client_is_never_told_to_look_at_its_own_build():
    v = _run(lag_s=0.0, drain=True, regime_settle=True, stall_s=0.0)
    assert v.fresh_frames is True
    assert mapping_refusals.STALE_STREAM_FIRST_CHECK not in (v.reason or "")
    assert not any("fresh" in p for p in v.problems)
