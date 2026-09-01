"""THE WIRE FRAME AND THE TWO LEVERS — the arithmetic that chose them, the
negotiation that applies them, and the refusals that stop either being
silent.

`scripts/check_commissioning.py` §3d is the end-to-end half (his own
composition, decoded at each frame size, judged on ACCURACY rather than on
a count). This is the fast deterministic half: the derivation, the ladder's
own invariants, "never upscale", the two gates, and the frame-rate coupling.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.models.room_map import GRID_H, GRID_W
from spectra.services import capture_settings as cs
from spectra.services import gray_code, light_field, mapping_refusals


# ── ONE: the ladder's own invariants ──────────────────────────────────────

def test_every_rung_divides_the_stored_grid_exactly_and_is_16_by_9():
    """THE PROMISE THE RAISE HAD TO KEEP. The map grid is unchanged at
    64x36, so a footprint taken through a 1080p frame has to be the same
    measurement as one through a 320x180 frame of the same scene — which is
    true exactly when every rung is a whole multiple of the grid, making
    `light_field.downsample` a box mean with no interpolation to explain."""
    for w, h in cs.PROFILES:
        assert w % GRID_W == 0 and h % GRID_H == 0, f"{w}x{h}"
        assert w // GRID_W == h // GRID_H, f"{w}x{h} is not a square scale"
        assert abs(w / h - 16 / 9) < 1e-9, f"{w}x{h} is not 16:9"
    assert cs.PROFILES == tuple(sorted(cs.PROFILES))
    assert cs.MAP_PROFILE == (320, 180), "night runs stay cheap"


def test_the_grid_is_the_same_whichever_rung_the_frame_arrived_at():
    import numpy as np
    flat = light_field.downsample(np.full(cs.MAP_PROFILE[::-1], 40.0))
    big = light_field.downsample(np.full(cs.COMMISSION_PROFILE[::-1], 40.0))
    assert np.allclose(flat, big)


# ── TWO: the arithmetic that chose 1920x1080 ──────────────────────────────

def test_the_commission_profile_is_derived_not_chosen():
    """1920x1080 is the SMALLEST rung carrying his 736-pixel composition
    with the pose margin the model insists on. If a rung is ever added, or
    his composition changes, this moves rather than going stale."""
    assert cs.COMMISSION_PROFILE == cs.commission_profile_for()
    got = cs.indices_supported(*cs.COMMISSION_PROFILE)
    assert got >= cs.REFERENCE_COMPOSITION * cs.COMMISSION_POSE_MARGIN
    # and the rung below it does NOT clear the margin — otherwise this is
    # maximum-picking wearing a derivation.
    below = cs.PROFILES[cs.PROFILES.index(cs.COMMISSION_PROFILE) - 1]
    assert (cs.indices_supported(*below)
            < cs.REFERENCE_COMPOSITION * cs.COMMISSION_POSE_MARGIN)


def test_no_pose_could_ever_have_worked_at_the_old_wire_frame():
    """THE FINDING THE WHOLE RAISE RESTS ON. A strip wrapped once around a
    screen images as a PERIMETER, and the whole perimeter of a 320x180
    frame — the television filling it edge to edge — is 1,000 camera
    pixels, against the ~1,472 his composition needs to be read at all."""
    whole_frame = cs.wrap_capacity_px(320, 180, fill=1.0)
    assert round(whole_frame) == 1000
    needed = cs.REFERENCE_COMPOSITION * gray_code.MIN_CAMERA_PX_PER_INDEX
    assert needed > whole_frame, (
        f"{cs.REFERENCE_COMPOSITION} indices need ~{needed:.0f} camera "
        f"pixels and the whole frame carries {whole_frame:.0f}")
    # and the raise clears it with real margin at an ordinary pose
    assert (cs.wrap_capacity_px(*cs.COMMISSION_PROFILE)
            > needed * cs.RESOLUTION_SAFETY_FACTOR_MARGIN())


def test_a_composition_bigger_than_every_rung_has_no_answer_rather_than_a_guess():
    assert cs.frame_for_indices(10_000_000) is None


# ── THREE: never upscale ──────────────────────────────────────────────────

def test_choose_never_returns_a_rung_bigger_than_the_camera():
    """A 1920x1080 frame drawn from a 1280x720 image holds no more detail
    than the 720p it came from — but the decode COUNTS CAMERA PIXELS, so
    interpolated ones would make an unreadable target report that it is
    readable."""
    assert cs.choose((1920, 1080), 1280, 720) == (1280, 720)
    assert cs.choose((1920, 1080), 1920, 1080) == (1920, 1080)
    assert cs.choose((1920, 1080), 640, 480) == (640, 360)
    assert cs.choose((320, 180), 1920, 1080) == (320, 180), \
        "a request is a ceiling too — a map never gets 1080p by accident"


def test_an_unknown_source_is_not_read_as_unlimited():
    assert cs.choose((1920, 1080), 0, 0) == (1920, 1080)


def test_an_upscaled_frame_is_named_and_never_counted():
    neg = cs.CameraNegotiation()
    neg.init_camera(cs.COMMISSION_PROFILE)
    said = neg.note_frame(1920, 1080, 1280, 720)
    assert said and "interpolation" in said
    assert neg.active_frame_size == cs.COMMISSION_PROFILE, \
        "the rejected frame never became the active size"
    assert neg.frame_refusal(cs.COMMISSION_PROFILE) == said


# ── FOUR: the two gates ───────────────────────────────────────────────────

def _double(**kw):
    d = cs.SessionCameraDouble()
    d.init_camera()
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def test_asking_for_nothing_manual_refuses_nothing():
    """THE CONTRACT FOR EVERY ORDINARY RUN: a camera with no manual controls
    at all maps exactly as it always did."""
    d = _double(camera_lock={"exposure_time": None, "gain": None,
                             "manual_refusals": ["no exposure control here"]})
    asyncio.run(d.apply_camera(cs.CameraRequest(frame_size=cs.MAP_PROFILE)))
    assert d.camera_refusal() is None
    assert d.frame_refusal(cs.MAP_PROFILE) is None


def test_a_lever_the_camera_did_not_take_refuses_by_name():
    d = _double(camera_lock={"exposure_time": 156.0, "gain": 0.0,
                             "exposure_time_range": [3.0, 2047.0],
                             "manual_refusals": [
                                 "asked for an integration time of 2000 and "
                                 "the device reports 156"]})
    asyncio.run(d.apply_camera(cs.request(frame_size=cs.MAP_PROFILE,
                                          exposure_time=2000, gain=64)))
    said = d.camera_refusal()
    assert said and "2000" in said and "156" in said
    assert "3..2047" in said, "it quotes what this camera actually offers"
    assert "Nothing was measured" in said


def test_a_camera_that_will_not_say_what_it_became_is_also_a_refusal():
    """The dangerous half: the frames still arrive and only the numbers are
    wrong, so silence about a lever is treated exactly like refusing it."""
    d = _double(camera_lock={"exposure_time": None, "gain": None,
                             "manual_refusals": []})
    asyncio.run(d.apply_camera(cs.request(exposure_time=2000)))
    said = d.camera_refusal()
    assert said and "never reported an integration time" in said


def test_an_honest_downgrade_is_a_result_and_never_a_refusal():
    """A camera that can only give 720p still runs — refusing it would
    strand a perfectly good camera, and the resolution report will refuse
    on its own MEASUREMENT if that rung cannot carry the target."""
    d = _double(camera_source=(1280, 720))
    got = asyncio.run(_apply_and_wait(d, cs.COMMISSION_PROFILE))
    assert got == (1280, 720)
    assert d.frame_refusal(cs.COMMISSION_PROFILE) is None


def test_a_client_that_never_adopts_the_size_refuses_by_name():
    d = _double(camera_source=(1920, 1080), adopts_frame_size=False)
    got = asyncio.run(_apply_and_wait(d, cs.COMMISSION_PROFILE, timeout=0.05))
    assert got == cs.MAP_PROFILE
    said = d.frame_refusal(cs.COMMISSION_PROFILE)
    assert said and "1920x1080" in said and "320x180" in said


async def _apply_and_wait(d, size, timeout=0.2):
    await d.apply_camera(cs.CameraRequest(frame_size=size))
    return await d.await_frame_size(size, timeout)


# ── FIVE: frame-rate honesty ──────────────────────────────────────────────

def test_a_long_integration_lowers_the_frames_a_window_can_buy():
    """A sensor integrating for E seconds delivers at most 1/E frames a
    second — no tap rate or window length changes that, and a run that
    left CAPTURE_S alone would quietly average one frame instead of four."""
    assert cs.achievable_fps(5.0, None) == 5.0
    assert cs.achievable_fps(5.0, 2000) == pytest.approx(5.0)      # 1/5 s
    assert cs.achievable_fps(5.0, 5000) == pytest.approx(2.0)      # 1/2 s
    assert cs.achievable_fps(5.0, 10_000) == pytest.approx(1.0)    # 1 s
    assert cs.frames_in(0.9, 5.0) == 4
    assert cs.frames_in(0.9, 1.0) == 0, "which is why the window must widen"
    assert cs.min_capture_s(2, 1.0) == 3.0


def test_the_widening_is_priced_and_a_run_that_asks_for_nothing_is_untouched():
    from spectra.services import room_mapping as rm
    same = rm.capture_windows(0.5, 1.5, None, 5.0)
    assert same == (0.5, 1.5, None, ""), \
        "no manual exposure means an EXACT pass-through of the shipped protocol"
    dark, lit, refusal, note = rm.capture_windows(0.5, 1.5, 10_000, 5.0)
    assert refusal is None and dark == 3.0 and lit == 3.0 and note
    # and the estimate prices the WIDENED run, not the one it isn't
    assert (rm.run_estimate_s(4, 0.7, dark, 0.7, lit)
            > rm.run_estimate_s(4, 0.7, 0.5, 0.7, 1.5))


def test_an_integration_time_no_legal_window_can_average_refuses_by_name():
    from spectra.services import room_mapping as rm
    _, _, refusal, _ = rm.capture_windows(0.5, 1.5, cs.MAX_EXPOSURE_TIME, 5.0)
    assert refusal and "frames a second" in refusal
    assert "raise the gain instead" in refusal, \
        "the refusal hands back the choice rather than only naming the bound"


# ── SIX: the request itself ───────────────────────────────────────────────

def test_a_clamped_lever_is_said_rather_than_silently_different():
    """Unlike the protocol waits, which fall silently back to their default:
    these are deliberate levers and a silently different value would
    mislead the very experiment they exist for."""
    req = cs.request(exposure_time=10 ** 9, gain=-5)
    assert req.exposure_time == cs.MAX_EXPOSURE_TIME
    assert req.gain == cs.MIN_GAIN
    assert len(req.notes) == 2 and "clamped" in req.notes[0]


def test_an_undeclared_frame_size_falls_back_and_says_so():
    req = cs.request(frame_size=(1000, 500))
    assert req.frame_size is None and "not one of the declared" in req.notes[0]


def test_an_all_default_request_asks_for_nothing_manual():
    req = cs.request()
    assert not req.manual and req.exposure_time is None and req.gain is None
    assert req.as_wire()["exposure_seconds"] is None


def test_the_exposure_unit_is_the_one_both_paths_already_speak():
    """100-microsecond units: V4L2's `exposure_time_absolute` and the W3C
    `exposureTime` constraint. Nothing converts, because a factor of ten in
    integration time is the difference between a readable frame and a white
    one."""
    assert cs.EXPOSURE_UNIT_S == 1e-4
    assert cs.request(exposure_time=2000).exposure_seconds == pytest.approx(0.2)


# ── the refusals' own wording ─────────────────────────────────────────────

def test_every_new_condition_has_a_sentence_that_says_what_to_do():
    said = [mapping_refusals.upscaled_frame(1920, 1080, 1280, 720),
            mapping_refusals.frame_size_not_adopted((1920, 1080), (320, 180),
                                                    (1280, 720), 3),
            mapping_refusals.manual_camera_unavailable(
                ["no control"], {"exposure_time": 2000}, {}),
            mapping_refusals.exposure_too_long(5.0, 0.2, 2, 10.0)]
    for sentence in said:
        assert len(sentence) > 80, sentence
        assert sentence == sentence.strip()
        # each one names an action, not just a state
        assert any(w in sentence for w in
                   ("Check", "check", "Set ", "Reload", "Ask", "restart",
                    "start the")), sentence


# ── SEVEN: the answer has to arrive before the gate reads it ──────────────

def test_the_gate_waits_for_the_camera_to_answer_this_request():
    """THE RACE THIS CLOSES, which is one line wide and would have been
    invisible: `apply_camera` sends and returns. Read the lock straight
    after it and you are reading the answer to the PREVIOUS request — for
    the first manual request, the converge-then-freeze one, which carries
    no refusals at all. The gate would pass and the run would proceed with
    numbers describing a regime nobody asked for."""
    d = _double()
    d.camera_lock = {"exposure_time": None, "gain": None,
                     "manual_refusals": []}
    # a camera that never answers
    d.answers_camera_config = False
    asyncio.run(d.apply_camera(cs.request(exposure_time=2000)))
    assert asyncio.run(d.await_camera(0.05)) is False
    # AND A TIMEOUT IS NOT A PASS: the gate then refuses on the missing
    # read-back rather than proceeding.
    assert d.camera_refusal() is not None


def test_a_request_with_no_levers_never_waits_at_all():
    """An ordinary run must cost nothing here — nothing about its numbers
    depends on an answer."""
    d = _double()
    d.answers_camera_config = False
    asyncio.run(d.apply_camera(cs.CameraRequest(frame_size=cs.MAP_PROFILE)))
    assert asyncio.run(d.await_camera(5.0)) is True


def test_an_answered_request_returns_at_once():
    d = _double()
    asyncio.run(d.apply_camera(cs.request(exposure_time=2000, gain=8)))
    assert asyncio.run(d.await_camera(0.05)) is True
