"""THE TWO RUNS ACTUALLY ASK THE CAMERA, AND ACTUALLY PUT IT BACK.

`tests/test_capture_settings.py` proves the negotiation in isolation. This
proves the two things a run has to do with it, which is where the founding
defect of this whole area lived: a gate that was documented, believed, and
never wired (`preview_pause` at `fire_scene_by_id`, 2026-08-21). So every
assertion here is taken from the RUN's own output or the SESSION's own
state after it, never from the negotiation object a test set up itself.

  * a COMMISSIONING read asks for 1920x1080 and gives it back;
  * a MAP asks for 320x180 and never inherits the big frame;
  * a lever the camera did not take stops the run BEFORE any light;
  * a run that asks for nothing is byte-for-byte the protocol that shipped.
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from spectra.models.room_map import AxisCalibration, Point, RoomMap
from spectra.services import capture_settings as cs
from spectra.services import commissioning, room_mapping

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))


class _Session(cs.SessionCameraDouble):
    """A connected, locked camera that records what the run asked it for."""
    pose_id = "pose-levers"
    run_abort = None
    keep_full_frames = False

    class lock:
        exposure_locked = True
        white_balance_locked = True
        exposure_mode = "manual"
        white_balance_mode = "manual"

        @staticmethod
        def as_dict():
            return {"exposure_locked": True, "white_balance_locked": True,
                    "exposure_time": None, "gain": None,
                    "manual_refusals": []}

    def __init__(self):
        self.camera_configs = []
        self.dark_next = True
        self.full = []

    def refusal(self):
        return None

    async def gather(self, seconds, min_frames=1):
        value = 0.0 if self.dark_next else 0.5
        self.dark_next = not self.dark_next
        grid = np.full((36, 64), value, dtype=np.float64)
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


def _requested_sizes(session):
    return [(c["frame_size"] or {}).get("width") for c in session.camera_configs
            if c.get("frame_size")]


# ── the map ───────────────────────────────────────────────────────────────

def test_a_map_asks_for_the_maps_own_frame_and_never_inherits_the_big_one():
    """A footprint is a 64x36 grid, so 320x180 is what it needs; 1080p would
    cost 36x the bandwidth for nothing. The run ASSERTS the size rather than
    assuming it, because a commissioning pass earlier in the same session
    borrowed the big one."""
    sess = _Session()
    sess.init_camera(cs.COMMISSION_PROFILE)          # as a read would leave it
    sess.active_frame_size = cs.COMMISSION_PROFILE
    result = asyncio.run(room_mapping.run_mapping(
        _room(), _deps(sess), granularity="whole"))
    assert result.ok, result.reason
    assert sess.frame_size == cs.MAP_PROFILE
    assert result.camera["frame_size"] == {"width": 320, "height": 180}
    assert _requested_sizes(sess) == [320]


def test_a_map_that_asks_for_nothing_runs_the_shipped_protocol_exactly():
    sess = _Session()
    result = asyncio.run(room_mapping.run_mapping(
        _room(), _deps(sess), granularity="whole"))
    assert result.ok
    assert result.dark_capture_s == room_mapping.DARK_CAPTURE_S
    assert result.lit_capture_s == room_mapping.LIT_CAPTURE_S
    assert result.camera["requested"]["exposure_time"] is None
    assert result.camera["requested"]["gain"] is None
    assert not [n for n in result.notes if "integration time" in n]


def test_a_lever_the_camera_did_not_take_stops_the_map_before_any_light():
    sess = _Session()
    sess.camera_lock = {"exposure_time": 156.0, "gain": None,
                        "manual_refusals": ["asked 2000, device reports 156"]}
    holds = []

    async def open_hold(*a, **k):
        holds.append(k.get("step"))
        return {"held": True}

    result = asyncio.run(room_mapping.run_mapping(
        _room(), _deps(sess, open_hold=open_hold), granularity="whole",
        camera=cs.request(exposure_time=2000)))
    assert not result.ok and result.refusal == "camera"
    assert "156" in result.reason
    assert holds == [], "nothing was held, so no light was ever driven"
    assert not result.emitters


def test_a_long_integration_widens_the_maps_capture_windows_and_says_so():
    sess = _Session()
    sess.camera_lock = {"exposure_time": 10_000.0, "gain": 8.0,
                        "manual_refusals": []}
    result = asyncio.run(room_mapping.run_mapping(
        _room(), _deps(sess), granularity="whole",
        camera=cs.request(exposure_time=10_000, gain=8)))
    assert result.ok, result.reason
    assert result.lit_capture_s == 3.0 > room_mapping.LIT_CAPTURE_S
    assert any("widened" in n for n in result.notes)


# ── the commissioning read ────────────────────────────────────────────────

class _ReadSession(_Session):
    """The same camera, plus the full-resolution frames a read consumes."""

    def __init__(self, frames_per_capture=4):
        super().__init__()
        self.n = frames_per_capture

    async def gather_full(self, seconds, *, min_frames=1):
        w, h = self.active_frame_size
        return [type("TF", (), {"at_s": float(k),
                                "frame": np.zeros((h, w), dtype=np.uint8)})()
                for k in range(max(min_frames, self.n))]


def _mapper_virtuals():
    """A tiny stored composition: one copy-mapped carrier over one strip,
    plus the strip's own direct virtual the run substitutes to."""
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


def test_a_commissioning_read_asks_for_1080p_and_gives_it_back():
    """AND GIVES IT BACK IN THE `finally`: a read borrows a 1080p wire, and
    leaving it in place would make every ordinary footprint run after it
    cost thirty-six times the bandwidth.

    The run itself ends in a refusal here (a synthetic camera returning
    black frames cannot resolve anything) — which is the point: the camera
    is put back on EVERY path out, not only the happy one."""
    sess = _ReadSession()

    async def get_virtuals():
        return _mapper_virtuals()

    async def chains():
        return {"tv-mapper": [{"id": "tv-backlight", "type": "wled"}]}

    async def activate(_vid):
        return None

    async def deactivate(_vid):
        return None

    async def open_hold(*a, **k):
        return {"held": True}

    async def sleep(_s):
        return None

    deps = room_mapping.RunDeps(
        session=sess, get_virtuals=get_virtuals, carrier_devices=chains,
        open_hold=open_hold, close_hold=lambda: asyncio.sleep(0),
        sleep=sleep, clock=lambda: 0.0, spectra_owns=lambda: True,
        activate=activate, deactivate=deactivate)
    result = asyncio.run(commissioning.run_commission("tv-mapper", deps))
    assert _requested_sizes(sess)[0] == 1920, "it asked for 1080p first"
    assert _requested_sizes(sess)[-1] == 320, "and asked for 320x180 back"
    assert sess.frame_size == cs.MAP_PROFILE, "put back in the finally"
    assert result.camera["frame_size"] == {"width": 1920, "height": 1080}, \
        "and the record says which frame this read actually got"
    assert not sess.keep_full_frames, "the ring is off again too"


def test_the_read_frame_is_the_arithmetics_answer_not_a_preference():
    assert commissioning.READ_PROFILE == cs.COMMISSION_PROFILE
    assert cs.COMMISSION_PROFILE == cs.commission_profile_for()


def test_a_read_widens_its_capture_window_for_a_long_integration():
    plain, refusal = commissioning.capture_window(None, 5.0)
    assert (plain, refusal) == (commissioning.CAPTURE_S, None), \
        "asking for nothing is an exact pass-through"
    wide, refusal = commissioning.capture_window(5000, 5.0)
    assert refusal is None and wide == 1.5 > commissioning.CAPTURE_S
    _, refusal = commissioning.capture_window(cs.MAX_EXPOSURE_TIME, 5.0)
    assert refusal and "frames a second" in refusal
