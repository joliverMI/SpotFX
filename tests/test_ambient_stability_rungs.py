"""THE AMBIENT GATE MEETS THE PER-RUN WIRE FRAME AND THE MANUAL LEVERS.

Two features landed the same day against the same capture path: the wire
frame is now per run and can be raised to 1920x1080, with two manual camera
levers (#231), and the room's own light is measured across every
commissioning stack (#232). They genuinely interact, so the composition is
proven rather than assumed:

  * the gate is the SAME GATE at every rung — same verdict on the same
    physical drift, and the same cost, because what it samples is bounded
    while the frame is not;
  * a raised — or honestly downgraded — read still gets its stability
    check, driven through the REAL run;
  * a long integration time widens every capture window, and the two dark
    references are averaged over the SAME widened window, or the gate
    would be comparing the run's own settings instead of the room.

No room, no network, no phone.
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from spectra.services import ambient_stability as amb
from spectra.services import capture_settings as cs
from spectra.services import commissioning, gray_code
from tests.test_ambient_stability import (DARK_LEVEL, FIELD_PEAK, LIT_LEVEL,
                                          _moving_cloud, _step_at)
from tests.test_commissioning import Harness


def _stack_at(width: int, height: int, layout, *, peak: float = FIELD_PEAK):
    """One reference pair at a given rung, rendered with the same blob
    machinery the decoder is proven against. `window_sigmas` keeps the blob
    cache to patches — a full-frame cache for 76 blobs of a 1080p frame is
    ~1.2 GB."""
    blobs: dict = {}
    scale = width / 320.0

    def frame(on):
        return gray_code.render_frame(
            layout, on, width=width, height=height,
            radius_px=2.0 * scale, dark_level=DARK_LEVEL,
            lit_level=DARK_LEVEL + peak, blobs=blobs, window_sigmas=5.0)

    return frame(set()), frame(set(layout))


# ── the same gate at every rung ───────────────────────────────────────────

@pytest.mark.parametrize("rung", cs.PROFILES)
def test_the_same_physical_drift_is_judged_the_same_at_every_rung(rung):
    """NOTHING HERE IS EXPRESSED IN THE CAMERA PIXELS OF ONE FRAME. The
    background set is a quantile (half the frame at any rung), the tile
    minimum is a fraction of a tile, and the bound is a fraction of `peak`,
    which is measured from the frames in hand. So the same drift, as a
    fraction of the fixture's own signal, lands on the same verdict whether
    the wire is carrying 320x180 or 1920x1080."""
    width, height = rung
    layout = Harness().layout
    dark, full = _stack_at(width, height, layout)
    track = amb.AmbientTrack.open(dark, full)

    assert track.measurable
    assert track.tiles_tracked == amb.TILE_GRID ** 2
    assert track.bound == pytest.approx(
        amb.DRIFT_FRACTION_OF_PEAK * track.peak, rel=1e-6)

    under = track.observe("under", dark + track.bound * 0.7, lamp_free=True)
    over = track.observe("over", dark + track.bound * 1.6, lamp_free=True)
    assert not under.exceeded
    assert over.exceeded and over.kind == "whole"


@pytest.mark.parametrize("rung", cs.PROFILES)
def test_what_the_gate_samples_is_bounded_while_the_frame_is_not(rung):
    """A 1080p frame is thirty-six times a 320x180 one. The measurement is
    not thirty-six times the work — the sample is fixed and bounded, which
    is what keeps this out of the SPECTRA process's own event loop as a
    45 ms block, twenty-three times a pass."""
    width, height = rung
    dark, full = _stack_at(width, height, Harness().layout)
    track = amb.AmbientTrack.open(dark, full)

    assert track.background_px >= amb.MIN_BACKGROUND_PX
    assert track.sampled_px == min(amb.SAMPLE_PX, track.background_px)
    assert track.sampled_px <= amb.SAMPLE_PX


def test_the_sample_is_the_same_pixels_every_capture_so_its_error_cancels():
    """The reason a bounded sample costs nothing in accuracy is not the
    sample size — it is that both levels of a difference are taken over the
    IDENTICAL pixels, so the sampling error is common-mode."""
    dark, full = _stack_at(1920, 1080, Harness().layout)
    track = amb.AmbientTrack.open(dark, full)
    first = np.array(track._whole_idx, copy=True)      # noqa: SLF001

    for k in range(4):
        track.observe(f"c{k}", dark + 0.25 * k, lamp_free=True)
    assert np.array_equal(track._whole_idx, first)     # noqa: SLF001
    # a frame identical to the reference must read as exactly no movement,
    # at any rung — that is what "common-mode" has to mean
    same = track.observe("same", dark, lamp_free=True)
    assert same.whole == 0.0 and same.regional == 0.0
    assert not same.exceeded


# ── through the real run, at a rung the camera negotiated ─────────────────

class RungRoom(Harness):
    """The harness rendering at a real wire rung, with a window in shot.

    It reuses the harness's own lamp — the writes the REAL program
    produced — and only changes the size of the picture the camera makes of
    them, which is exactly what the per-run frame does."""

    def __init__(self, *, rung, ambient=None, source=None, **kw):
        super().__init__(**kw)
        self.rung = tuple(rung)
        self._ambient = ambient or (lambda _seq: 0.0)
        self.session.camera_source = tuple(source or rung)
        self.session.init_camera(cs.MAP_PROFILE)
        self._scale = self.rung[0] / 320.0
        self._patch: dict = {}
        w, h = self.rung
        self._window = ((np.linspace(1.0, 0.0, w)[None, :] ** 2)
                        * np.linspace(1.0, 0.3, h)[:, None])

    def render(self, elapsed_ms: float = 1e9) -> np.ndarray:
        w, h = self.rung
        frame = gray_code.render_frame(
            self.layout, self._lit_indices(), width=w, height=h,
            radius_px=2.0 * self._scale, dark_level=DARK_LEVEL,
            lit_level=DARK_LEVEL + FIELD_PEAK, blobs=self._patch,
            window_sigmas=5.0)
        level = float(self._ambient(self._write_seq))
        if level:
            frame = frame + self._window * level
        return np.clip(frame, 0.0, 255.0)


RAISED = (1280, 720)


def test_a_raised_read_still_gets_its_stability_check():
    h = RungRoom(rung=RAISED, ambient=_moving_cloud(50.0), source=RAISED)
    result = h.run(layout=h.layout, instrument={})

    # the negotiation happened and is on the record, and the camera was
    # put back afterwards exactly as #231 requires
    assert result.camera["frame_size"] == {"width": 1280, "height": 720}
    assert h.session.frame_size == cs.MAP_PROFILE
    # ...and the gate ran on THOSE frames and refused
    assert result.refusal == "ambient"
    assert "window" in result.reason.lower()
    assert result.ambient["measurable"] and result.ambient["exceeded"]
    assert result.ambient["frame_px"] == 1280 * 720
    assert not result.table


def test_a_raised_read_of_a_steady_room_goes_all_the_way_through():
    """THE OTHER DIRECTION AT THE OTHER RUNG. A bigger frame must not make
    the gate twitchy — the bound is a fraction of a measured peak, not a
    count of camera pixels."""
    h = RungRoom(rung=RAISED, source=RAISED)
    result = h.run(layout=h.layout, instrument={})

    assert result.ok, result.reason
    assert result.camera["frame_size"] == {"width": 1280, "height": 720}
    assert result.ambient["measurable"] and not result.ambient["exceeded"]
    assert result.table["rows"]


def test_an_honest_downgrade_is_still_measured_and_still_gated():
    """The run asks for 1080p; this camera has 640x360. #231's rule is that
    an honest downgrade is a note, not a refusal — so the stability check
    has to work at whatever rung actually arrived."""
    h = RungRoom(rung=(640, 360), ambient=_step_at(6, 40.0), source=(640, 360))
    h._window = np.ones(h.rung[::-1])          # room-wide, so the level IS
    result = h.run(layout=h.layout, instrument={})   # the drift

    assert result.camera["frame_size"] == {"width": 640, "height": 360}
    assert any("not the 1920x1080" in n for n in result.notes)
    assert result.refusal == "ambient"
    assert result.ambient["frame_px"] == 640 * 360


# ── the manual levers ─────────────────────────────────────────────────────

def _long_exposure_session(h, exposure_time=5000):
    h.session.camera_lock = {"exposure_locked": True,
                             "white_balance_locked": True,
                             "exposure_time": float(exposure_time),
                             "gain": None, "manual_refusals": []}
    return cs.request(exposure_time=exposure_time)


def test_both_dark_references_are_averaged_over_the_same_widened_window():
    """THE ONE THING A LONG INTEGRATION COULD HAVE BROKEN. The gate's most
    unarguable reading is the opening dark against the closing one — and
    that comparison is only honest if both were taken the same way. A
    manual exposure widens every capture window (`capture_window`); a
    closing dark left on the shipped window would have been averaging a
    different number of frames and the difference would have read as the
    room moving."""
    h = RungRoom(rung=cs.MAP_PROFILE, source=cs.MAP_PROFILE)
    req = _long_exposure_session(h)
    widened, refusal = commissioning.capture_window(
        req.exposure_time, h.session.observed_fps()
        or commissioning.mapping_session.FRAME_FPS)
    assert refusal is None and widened > commissioning.CAPTURE_S

    result = h.run(layout=h.layout, instrument={}, camera=req)
    assert result.ok, result.reason
    windows = {c["label"]: c["capture_s"] for c in result.captures}
    assert windows["run1/dark"] == pytest.approx(widened)
    assert windows["run1/dark-end"] == pytest.approx(widened)
    assert windows and all(v == pytest.approx(widened)
                           for v in windows.values()), \
        "every capture in the stack, not just the references"
    assert result.ambient["measurable"] and not result.ambient["exceeded"]


def test_a_long_integration_does_not_stop_the_gate_seeing_the_weather():
    h = RungRoom(rung=cs.MAP_PROFILE, source=cs.MAP_PROFILE,
                 ambient=_moving_cloud(50.0))
    req = _long_exposure_session(h)
    result = h.run(layout=h.layout, instrument={}, camera=req)

    assert result.refusal == "ambient"
    assert result.ambient["exceeded"]
    assert any("integration time" in n for n in result.notes)


def test_a_lever_the_camera_refused_still_stops_before_the_gate_ever_runs():
    """PRECEDENCE, stated: #231's own gate is BEFORE the room goes dark, so
    a refused lever is a camera refusal and never an ambient one — the
    ambient gate has no frames to have an opinion about."""
    h = RungRoom(rung=cs.MAP_PROFILE, source=cs.MAP_PROFILE,
                 ambient=_moving_cloud(50.0))
    h.session.camera_lock = {"exposure_locked": True,
                             "white_balance_locked": True,
                             "exposure_time": 156.0, "gain": None,
                             "manual_refusals": ["asked 5000, device says 156"]}
    result = h.run(layout=h.layout, instrument={},
                   camera=cs.request(exposure_time=5000))

    assert result.refusal == "camera"
    assert not result.ambient
    assert not result.captures, "no light was ever driven"
