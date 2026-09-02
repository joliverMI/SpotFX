"""WHAT THE CAMERA IS ASKED TO DO FOR ONE RUN — the wire frame size and the
FOUR PINNED LEVERS (integration time, gain, white balance temperature,
focus), and what each of them COSTS.

PURE. No camera, no session, no store, no clock: sizes in, arithmetic out.
Both clients (`spectra/web/src/rooms/mappingCapture.ts` on a phone and
`spectra/capture_client/` on a machine with a webcam) and both runs (the
map and the commissioning pass) read the same numbers from here, so a
frame size the server asks for and a frame size a client sends cannot be
two different ideas.

────────────────────────────────────────────────────────────────────────────
ONE. THE WIRE FRAME, AND WHY IT IS NOT ONE NUMBER ANY MORE
────────────────────────────────────────────────────────────────────────────

Until 2026-09-01 the wire carried exactly 320x180 grey8, for everything.
That was right for the MAP — a footprint is "where does this fixture's
light land", stored as a 64x36 grid, and 320x180 downsamples into it by an
exact 5x5 box mean — and it is still what a map sends. Night runs stay
cheap: 57,600 bytes a frame.

It was fatal for COMMISSIONING, and the arithmetic says so without needing
a room (`gray_code.MIN_CAMERA_PX_PER_INDEX` carries the derivation):

    a gray-code decode needs about 2 camera pixels per composition index
    (gray bit 0 alternates in runs of TWO indices, so a pattern and its
    inverse differ over a two-index period — Nyquist, on the finest
    structure in the stack);

    his tv-mapper is 736 indices, so it needs ~1,472 camera pixels of
    IMAGED STRIP, and ~1,840 to clear the safety margin the instrument
    insists on (RESOLUTION_SAFETY_FACTOR);

    a strip wrapped once around a television images as a PERIMETER, and
    the whole perimeter of a 320x180 frame — the strip filling the frame
    edge to edge — is 2 x (320 + 180) = 1,000 camera pixels.

1,000 < 1,472. NO POSE CAN EVER WORK AT THAT FRAME SIZE. That is not a
statement about his room, his fixtures or how the phone is held; it is the
wire's own contract being smaller than the question. Both field runs of
2026-09-01 decoded 0 of 736 for exactly this reason.

At 1920x1080 the same wrap at a comfortable ~77%-of-frame-width pose images
a perimeter of about 2 x (1478 + 831) = 4,618 camera pixels — a factor of
2.5 over the 1,840 the margin asks for. That is the raise, and it is chosen
by that arithmetic rather than by picking the largest number available:
`frame_for_indices` below is the function, and `wrap_capacity_px` is the
perimeter model it uses.

THE STORED MAP GRID IS UNCHANGED at 64x36. Every rung of the ladder is an
exact whole multiple of it (5x, 10x, 15x, 20x, 30x) and 16:9, so
`light_field.downsample` stays an exact box mean with no interpolation to
explain, and a grid derived from a 1080p frame is directly comparable with
one derived from a 320x180 frame of the same scene.

PIXELS STAY grey8 AND UNCOMPRESSED AT EVERY RUNG. The no-lossy-codec rule
is absolute and has nothing to do with size: a lossy stage's quantisation
lands INSIDE the difference this instrument measures (`lit - dark`), where
nothing downstream can separate it from light. A bigger frame is more
bytes; it is never a reason to compress them.

────────────────────────────────────────────────────────────────────────────
TWO. NEVER UPSCALE. A CLIENT SENDS WHAT ITS CAMERA HAS.
────────────────────────────────────────────────────────────────────────────

A 1920x1080 frame drawn from a 1280x720 camera image contains no more
detail than the 720p it came from — but `resolution_report` counts CAMERA
PIXELS, so interpolated pixels would inflate the count and a target that
cannot be resolved would report that it can. That is precisely the
confident-wrong-answer the MARGINAL verdict exists to refuse, arriving
through a side door.

So `choose` picks the largest rung that is no larger than BOTH what the
server asked for and what the camera actually delivers, every client
reports its own source size on the wire, and a frame that arrives larger
than its source is named (`mapping_refusals.upscaled_frame`) rather than
counted. A camera that can only give 720p still runs — at 1280x720, which
is a 4x improvement on 320x180 and enough for a per-fixture target — and
the run says which rung it got.

────────────────────────────────────────────────────────────────────────────
THREE. THE FOUR PINNED LEVERS (`LEVER_BOUNDS`)
────────────────────────────────────────────────────────────────────────────

INTEGRATION TIME, GAIN, WHITE BALANCE TEMPERATURE and FOCUS. All four are
PER-RUN requests, all four default to "ask for nothing", and asking for
nothing preserves today's behaviour exactly: converge-then-freeze (let
auto-exposure settle on the scene, then lock it), which is what both
clients already do and what every map taken so far was taken under. Nothing
about his room changes unless a run asks.

THE LAST TWO ARE NATIVE-CLIENT ONLY, and that is a fact about the browser
rather than a policy: a page cannot reach `white_balance_temperature` or
`focus_absolute` at all, so a browser session reports both as not read —
which is what a run asking for one then refuses on. `spectra/capture_client/
camera.py` is where all four are written and read back.

AND A READ-BACK IS STILL NOT THE LIGHT. Every claim below is about what the
DRIVER holds. Whether the SENSOR obeys it needs a measurement, and that
lives in `spectra/services/lever_selftest.py`.

EXPOSURE TIME IS IN 100-MICROSECOND UNITS, on purpose and on both paths:
V4L2's `exposure_time_absolute` is in 100 us units and the W3C image-capture
`exposureTime` constraint is in 100 us units. So the wire carries the number
both sides already speak and NOTHING converts it — a unit conversion is a
place for a factor of ten to hide, and a factor of ten in integration time
is the difference between a readable frame and a white one.

GAIN AND FOCUS ARE PASSED THROUGH VERBATIM AND NEVER CONVERTED. V4L2
`gain`/`focus_absolute` and the browser's `iso` are device-specific scales
with no shared meaning; the only honest thing to do with the number is hand
it to the driver and report what the driver said it became. A conversion
here would be an invention. WHITE BALANCE is a temperature in Kelvin, which
IS a shared unit — and is still not converted, for the same reason: the
driver's own range is what finally applies.

ALL FOUR ARE READ BACK, ALWAYS, and `camera_refusal` checks every one of
them off ONE declaration (`LEVER_BOUNDS`) so a fifth cannot be added on one
side only. The rule the exposure lock already lives by: automating the
REQUEST is the point; automating the CONFIRMATION is forging the
instrument's signature. A returning write call is never evidence.

────────────────────────────────────────────────────────────────────────────
FOUR. FRAME-RATE HONESTY — a long integration is not free
────────────────────────────────────────────────────────────────────────────

A camera integrating for 1/5 s cannot deliver more than 5 frames a second,
whatever the tap rate asks for. That matters here because of a coupling
`room_mapping` already documents in one direction and this closes in the
other: at a fixed camera rate, `lit_capture_s` IS the frame count — the
session averages whatever ARRIVED in the window — and `MIN_FRAMES` (2) is
the floor below which an emitter is reported unmapped rather than averaged
from one frame.

So a 1/5 s integration silently halves what a 0.6 s window buys, and a 1 s
integration leaves it with one frame and no average at all. `achievable_fps`
and `min_capture_s` are what stop that being silent: a run that asks for a
long integration has its capture WINDOWS widened to still buy MIN_FRAMES,
and `run_estimate_s` prices the widened windows, so the minutes he is shown
before he presses are the minutes the room is actually dark. An exposure so
long that even the maximum window cannot buy MIN_FRAMES REFUSES by name
(`mapping_refusals.exposure_too_long`) rather than producing a run of
unmapped emitters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from spectra.models.room_map import GRID_H, GRID_W
from spectra.services import capture_source

# ── ONE: the wire-frame ladder ─────────────────────────────────────────────

#: Every rung is 16:9 AND an exact whole multiple of the stored 64x36 map
#: grid, so `light_field.downsample` is a box mean at any of them. Ordered
#: small to large; `choose` walks it downward.
PROFILES: tuple[tuple[int, int], ...] = tuple(
    (GRID_W * k, GRID_H * k) for k in (5, 10, 15, 20, 30))

#: THE MAP'S FRAME, unchanged: 320x180, ~58 KB a frame. A footprint is a
#: 64x36 grid; more pixels would cost bandwidth and buy nothing.
MAP_PROFILE = PROFILES[0]
#: HIS OWN COMPOSITION, the one this instrument was built for and the one
#: the raise is sized against: `tv-mapper` is 560 TV-backlight pixels plus
#: four sconce segments, 736 in the stored order.
REFERENCE_COMPOSITION = 736
#: HOW MUCH HEADROOM THE CHOSEN RUNG MUST HAVE over `REFERENCE_COMPOSITION`
#: at `REFERENCE_FILL`, and it is the reason the answer is 1920x1080 rather
#: than the bare minimum.
#:
#: `frame_for_indices(736)` is 960x540 — that rung carries about 924
#: indices at a 77% pose, i.e. 1.26x what he needs. A pose model is not a
#: pose: a hand-held shot is off-axis, the wrap is not a perfect rectangle,
#: and the sconces sit outside the television's own outline, so a rung
#: chosen at 1.26x would land ON the MARGINAL boundary in the room and
#: refuse. 2x is the bar; 1920x1080 carries ~1,848 (2.5x) and is the
#: smallest rung that clears it.
#:
#: This is what "arithmetic-driven, not maximum-picked" means here: the
#: largest rung and the chosen rung coincide today, and the function below
#: is what would pick a different one if the ladder or the composition
#: changed.
COMMISSION_POSE_MARGIN = 2.0


#: THE COMMISSIONING READ'S FRAME. Assigned below `commission_profile_for`,
#: which is defined further down beside the rest of the frame arithmetic —
#: it is a DERIVED number and this line is only where it is named.
COMMISSION_PROFILE: tuple[int, int] = (1920, 1080)

#: The full-resolution frame ring is bounded in BYTES, not frames — 200
#: frames is 11 MB at 320x180 and 414 MB at 1920x1080, and only one of
#: those is a ring. A commissioning capture window is ~1.5 s at a few
#: frames a second, so a couple of dozen frames is already generous.
FULL_RING_BYTES = 96 * 1024 * 1024
FULL_RING_MAX = 200
FULL_RING_MIN = 8


def is_profile(width: int, height: int) -> bool:
    """Is this one of the declared rungs? The wire rejects anything else
    rather than resampling a surprise — a frame of an undeclared shape
    means the client and the server disagree, and quietly stretching it
    would hide that."""
    return (int(width), int(height)) in PROFILES


def choose(requested: tuple[int, int],
           source_w: int = 0, source_h: int = 0) -> tuple[int, int]:
    """The largest rung no bigger than what was ASKED FOR and no bigger
    than what the camera actually DELIVERS. See "never upscale" above.

    An unknown source (0/absent) is not treated as "unlimited" by
    accident — it returns the request unchanged, and the server's own
    upscale check is what catches a client that then oversends."""
    want = tuple(requested)
    if want not in PROFILES:
        want = MAP_PROFILE
    if source_w <= 0 or source_h <= 0:
        return want
    for w, h in reversed(PROFILES):
        if w <= want[0] and h <= want[1] and w <= source_w and h <= source_h:
            return (w, h)
    return PROFILES[0]


def full_ring_len(width: int, height: int) -> int:
    """How many full-resolution frames of this size the ring may hold, on a
    fixed BYTE budget. See FULL_RING_BYTES."""
    per = max(1, int(width) * int(height))
    return max(FULL_RING_MIN, min(FULL_RING_MAX, FULL_RING_BYTES // per))


def frame_bytes(width: int, height: int) -> int:
    return int(width) * int(height)


# ── the arithmetic that chose the raise ────────────────────────────────────

#: How much of the frame's width a comfortably-framed television fills. Not
#: a tuning knob and nothing reads it at runtime: it is the pose assumed by
#: `frame_for_indices` when it answers "which rung clears N indices", and
#: it is stated so the answer can be checked rather than believed. 77% of
#: the frame's width leaves a real margin at the edges for a hand-held shot.
REFERENCE_FILL = 0.77


def wrap_capacity_px(width: int, height: int, fill: float = REFERENCE_FILL) -> float:
    """CAMERA PIXELS ALONG THE IMAGED STRIP for a strip wrapped once around
    a 16:9 screen filling `fill` of the frame's width — his tv-mapper's own
    shape, which is the composition this instrument was built for.

    A PERIMETER, not a width: that is what a wrap is, and it is why a
    320x180 frame cannot carry 736 indices even with the television filling
    it edge to edge (2 x (320 + 180) = 1,000).

    A MODEL OF ONE POSE, deliberately, and never used to decide a live run:
    a real run measures the imaged extent from its own reference pair
    (`gray_code.resolution_report`) and refuses on THAT. This function
    exists so "which frame size do we need" is arithmetic anyone can check,
    not a number someone picked."""
    w = float(width) * max(0.0, min(1.0, float(fill)))
    h = w * 9.0 / 16.0
    return 2.0 * (w + h)


def indices_supported(width: int, height: int, fill: float = REFERENCE_FILL,
                      *, safety: bool = True) -> float:
    """How many composition indices a frame of this size can carry at that
    pose — capacity divided by the camera pixels each index needs.

    `safety=True` (the default, and the honest one) uses the bar the
    instrument actually refuses on, MIN_CAMERA_PX_PER_INDEX x
    RESOLUTION_SAFETY_FACTOR, not the bare Nyquist limit: a target sitting
    on the Nyquist limit REFUSES as MARGINAL, so counting it as supported
    would describe a run that cannot happen."""
    from spectra.services import gray_code
    per = gray_code.MIN_CAMERA_PX_PER_INDEX
    if safety:
        per *= gray_code.RESOLUTION_SAFETY_FACTOR
    return wrap_capacity_px(width, height, fill) / max(1e-9, per)


def RESOLUTION_SAFETY_FACTOR_MARGIN() -> float:
    """The safety factor the instrument actually refuses on, read from
    `gray_code` rather than restated here — a second copy of a boundary is
    where two boundaries start disagreeing."""
    from spectra.services import gray_code
    return gray_code.RESOLUTION_SAFETY_FACTOR


def frame_for_indices(total: int, fill: float = REFERENCE_FILL
                      ) -> Optional[tuple[int, int]]:
    """The smallest rung that carries `total` indices at that pose, or None
    when no declared rung does. This is the function that chose 1920x1080
    for his 736."""
    for w, h in PROFILES:
        if indices_supported(w, h, fill) >= float(total):
            return (w, h)
    return None


def commission_profile_for(total: int = REFERENCE_COMPOSITION,
                           margin: float = COMMISSION_POSE_MARGIN,
                           fill: float = REFERENCE_FILL) -> tuple[int, int]:
    """The smallest rung carrying `total` indices with `margin` to spare at
    that pose, or the largest rung when none does. Called once at import to
    fix COMMISSION_PROFILE, so the constant is a derived number rather than
    a chosen one."""
    want = frame_for_indices(int(total * max(1.0, float(margin))), fill)
    return want or PROFILES[-1]


#: DERIVED, not chosen — see COMMISSION_POSE_MARGIN. Asserted in
#: `tests/test_capture_settings.py` against the ladder, so a future rung or
#: a changed composition moves this number rather than leaving a stale one.
COMMISSION_PROFILE = commission_profile_for()


# ── THREE: the levers ──────────────────────────────────────────────────────

#: Exposure time in 100-microsecond units — V4L2's `exposure_time_absolute`
#: and the W3C `exposureTime` constraint both. 1 = 0.1 ms, 2000 = 0.2 s.
#: Nothing converts it; see the docstring.
EXPOSURE_UNIT_S = 1e-4
#: The request's own bounds — a SANITY bound, deliberately wider than the
#: protocol's own. The floor is one unit; the ceiling is ten seconds, which
#: no camera in this room will offer and no hand-held pose could hold still
#: for.
#:
#: THE BINDING BOUND IS ELSEWHERE, ON PURPOSE. What actually stops a long
#: integration is that a capture must still average MIN_FRAMES inside one
#: legal window (`min_capture_s` against `room_mapping.MAX_CAPTURE_S`), and
#: that refusal NAMES the arithmetic (`mapping_refusals.exposure_too_long`).
#: Making this constant the real ceiling would put two bounds on the same
#: thing in two modules, which is where they drift; making it wide keeps
#: this one honest as what it is — a guard against a typo reaching a driver.
#: A device's OWN range is narrower still and is what finally applies; the
#: read-back reports where the value landed.
MIN_EXPOSURE_TIME = 1
MAX_EXPOSURE_TIME = 100_000
#: Gain is a device-specific scale with no shared meaning across drivers
#: (V4L2 `gain`, the browser's `iso`), so the only bound here is
#: non-negative and not absurd. The read-back is the statement.
MIN_GAIN = 0
MAX_GAIN = 100_000
#: WHITE BALANCE TEMPERATURE, in Kelvin — V4L2's `white_balance_temperature`
#: once the device's own auto white balance is off. A sanity bound only,
#: wide on purpose for the same reason the exposure one is: the device's own
#: declared range is narrower and is what finally applies, and the read-back
#: is the statement.
MIN_WHITE_BALANCE = 1_000
MAX_WHITE_BALANCE = 20_000
#: FOCUS, on the device's own scale (V4L2 `focus_absolute`) with no shared
#: meaning across drivers — so, like gain, the only bound is non-negative
#: and not absurd.
MIN_FOCUS = 0
MAX_FOCUS = 100_000

#: THE FOUR PINNED LEVERS, in one place so a fifth is one row rather than
#: eight edits: (field, min, max, unit words, words for a refusal).
LEVER_BOUNDS: tuple[tuple[str, int, int, str, str], ...] = (
    ("exposure_time", MIN_EXPOSURE_TIME, MAX_EXPOSURE_TIME, "100 us units",
     "an integration time"),
    ("gain", MIN_GAIN, MAX_GAIN, "", "a gain"),
    ("white_balance", MIN_WHITE_BALANCE, MAX_WHITE_BALANCE, "K",
     "a white balance temperature"),
    ("focus", MIN_FOCUS, MAX_FOCUS, "", "a focus"),
)


@dataclass
class CameraRequest:
    """WHAT A RUN ASKS THE CAMERA FOR. Every field optional; all-None is
    today's behaviour exactly (converge-then-freeze, whatever frame size
    the session already runs at).

    A REQUEST, never a claim: what actually happened is
    `mapping_session.LockState`'s read-back, which comes from the device."""
    frame_size: Optional[tuple[int, int]] = None
    exposure_time: Optional[int] = None
    gain: Optional[int] = None
    #: THE OTHER TWO PINNED LEVERS (2026-09-01): white balance TEMPERATURE
    #: in Kelvin and FOCUS on the device's own scale. Same discipline as the
    #: first two — a request, never a claim, and the read-back decides.
    white_balance: Optional[int] = None
    focus: Optional[int] = None
    #: what was clamped on the way in, in his words, so a bounded value is
    #: never silently different from the one he typed
    notes: list[str] = field(default_factory=list)

    @property
    def levers(self) -> dict:
        """The pinned levers this request actually names, by field."""
        return {name: getattr(self, name)
                for name, *_ in LEVER_BOUNDS
                if getattr(self, name) is not None}

    @property
    def manual(self) -> bool:
        """Does this ask for ANY of the four pinned levers? A request that
        asks for none must not make a camera that offers none refuse."""
        return bool(self.levers)

    @property
    def exposure_seconds(self) -> Optional[float]:
        if self.exposure_time is None:
            return None
        return self.exposure_time * EXPOSURE_UNIT_S

    def as_wire(self) -> dict:
        return {"frame_size": ({"width": self.frame_size[0],
                                "height": self.frame_size[1]}
                               if self.frame_size else None),
                "exposure_time": self.exposure_time, "gain": self.gain,
                "white_balance": self.white_balance, "focus": self.focus,
                "exposure_seconds": self.exposure_seconds,
                "notes": list(self.notes)}


def request(*, frame_size: Optional[tuple[int, int]] = None,
            exposure_time=None, gain=None, white_balance=None,
            focus=None) -> CameraRequest:
    """A bounded request from whatever a caller sent. Out-of-range values
    are CLAMPED AND SAID — unlike the protocol waits, which fall silently
    back to their default, because these are deliberate levers and a
    silently different value would mislead the very experiment they exist
    for."""
    req = CameraRequest(frame_size=(tuple(frame_size)
                                    if frame_size and is_profile(*frame_size)
                                    else None))
    if frame_size and req.frame_size is None:
        req.notes.append(
            f"{frame_size[0]}x{frame_size[1]} is not one of the declared "
            f"frame sizes ({_ladder_words()}) — the session's own size is "
            f"used instead")
    asked = {"exposure_time": exposure_time, "gain": gain,
             "white_balance": white_balance, "focus": focus}
    for name, lo, hi, unit, _words in LEVER_BOUNDS:
        setattr(req, name, _clamp_int(asked[name], lo, hi, name, unit,
                                      req.notes))
    return req


def _ladder_words() -> str:
    return ", ".join(f"{w}x{h}" for w, h in PROFILES)


def _clamp_int(value, lo: int, hi: int, name: str, unit: str,
               notes: list[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        notes.append(f"{name}={value!r} is not a number and was ignored")
        return None
    if v < lo or v > hi:
        notes.append(f"{name} {v} was outside {lo}..{hi}"
                     f"{' ' + unit if unit else ''} and was clamped to "
                     f"{max(lo, min(hi, v))}")
        v = max(lo, min(hi, v))
    return v


# ── FOUR: frame-rate honesty ───────────────────────────────────────────────

def achievable_fps(tap_fps: float, exposure_time: Optional[int]) -> float:
    """The frames a second a run can actually expect: the tap's own rate,
    or the integration time's own ceiling, whichever is lower.

    A sensor integrating for E seconds cannot produce more than 1/E frames
    a second — no pipeline, tap rate or capture window changes that."""
    fps = float(tap_fps) if tap_fps and tap_fps > 0 else 1.0
    if exposure_time:
        fps = min(fps, 1.0 / max(1e-9, exposure_time * EXPOSURE_UNIT_S))
    return max(1e-6, fps)


#: One frame interval of slack over the bare arithmetic. A window of exactly
#: `frames / fps` catches MIN_FRAMES only if the first frame lands on the
#: instant the window opens, which nothing guarantees.
CAPTURE_SLACK_FRAMES = 1.0


def min_capture_s(frames: int, fps: float) -> float:
    """The shortest capture window that can be expected to deliver `frames`
    at this rate — what a long integration must widen the two capture
    windows to, or `MIN_FRAMES` is quietly unreachable."""
    return round((max(1, int(frames)) + CAPTURE_SLACK_FRAMES)
                 / max(1e-6, float(fps)), 3)


def frames_in(capture_s: float, fps: float) -> int:
    """How many frames a window of this length buys at this rate — the
    other direction, for pricing and for saying what a run is about to
    average."""
    return int(max(0.0, float(capture_s)) * max(0.0, float(fps)))


# ── THE NEGOTIATION ITSELF, written once ───────────────────────────────────

class CameraNegotiation:
    """WHAT A CAPTURE SESSION DOES ABOUT ITS CAMERA'S PER-RUN SETTINGS —
    every field and every decision, in one place, inherited by the real
    `mapping_session.MappingSession` AND by every test double.

    WHY A MIXIN RATHER THAN SEVEN MODELS OF IT. There are seven fake
    sessions across `tests/` and `scripts/`, and each of them exists to
    prove something about a run. A gate they MODEL is a gate no proof
    actually exercises — the codebase's own founding defect on this path was
    a hold that reported itself as set while the show kept firing, with
    every test asking the preview side and passing. So the doubles inherit
    the real negotiation and only supply the four things a session owns: how
    to send, what time it is, when frames arrived, and what the camera's
    lock read back.

    IT DECIDES NOTHING ABOUT LIGHT AND HOLDS NO FRAMES. It records what was
    asked for, what arrived, and what the device answered, and it turns
    those into the two refusals (`frame_refusal`, `camera_refusal`) — both
    read off the ARRIVALS and the READ-BACK, never off the request."""

    # ── the four hooks a session supplies ─────────────────────────────────
    async def _send_camera_config(self, payload: dict) -> None:
        """Put this run's request on the wire. The real session sends a
        `config` message; a double may record it."""
        raise NotImplementedError

    def _camera_clock(self) -> float:
        raise NotImplementedError

    def camera_lock_view(self) -> dict:
        """The camera's read-back, for a caller that wants to record it.
        Public because a run puts it in its own result; `_camera_lock_view`
        is the hook an owner overrides."""
        return self._camera_lock_view()

    def _camera_frame_times(self) -> list:
        """Arrival times of the most recent frames, newest last. Used only
        for `observed_fps`; an empty list means "not enough to say"."""
        return []

    def _camera_lock_view(self) -> dict:
        """The camera's own read-back, in `LockState.as_dict()` shape."""
        return {}

    def _camera_lock_stamp(self) -> float:
        """WHEN that read-back last changed, on the same clock
        `_camera_clock` runs on. `await_camera` needs it to tell an answer
        to THIS request from the answer to the last one — see there. A
        session that cannot say returns 0.0, which makes the wait a plain
        timeout rather than a wrong answer."""
        return 0.0

    def _on_frame_size_change(self, size: tuple) -> None:
        """Told when the requested size changes, so an owner holding
        full-resolution frames can drop what it has: frames of two shapes
        cannot be averaged into one stack."""

    # ── state ─────────────────────────────────────────────────────────────
    #
    # DECLARED AS CLASS DEFAULTS, and that is deliberate: every method below
    # ASSIGNS (`self.x = ...`) rather than mutating, so the defaults are only
    # ever read before a session has been asked for anything, and a double
    # that inherits this gets a working, honest starting state without
    # having to remember a call in its own `__init__`. `init_camera` below
    # is a RESET for an owner that wants a different starting size — the
    # real session calls it; a spec's double does not have to.
    frame_size: tuple = MAP_PROFILE
    active_frame_size: tuple = MAP_PROFILE
    source_size: tuple = (0, 0)
    camera_request: "CameraRequest" = CameraRequest()
    #: when the last request was sent, on `_camera_clock`'s own clock
    camera_request_at: float = 0.0
    pending_size_frames: int = 0
    upscaled: str = ""

    def init_camera(self, frame_size: tuple = MAP_PROFILE) -> None:
        """Call from the owner's `__init__`. `frame_size` is what this
        session runs at until a run asks otherwise — the map's own 320x180."""
        #: what was ASKED FOR
        self.frame_size: tuple = tuple(frame_size)
        #: what ACTUALLY ARRIVED. Never the same field: a client whose
        #: camera cannot reach the request downgrades honestly, and
        #: everything that stacks frames reads THIS one.
        self.active_frame_size: tuple = tuple(frame_size)
        #: the camera's own image size, as the client reports it — what an
        #: upscale is measured against. (0, 0) until a client says.
        self.source_size: tuple = (0, 0)
        self.camera_request: CameraRequest = CameraRequest()
        self.camera_request_at: float = 0.0
        #: frames that arrived at a size this session is not asking for.
        #: Ordinary for a moment after a request; the number a run's wait
        #: reports if the client never switches. NOT an error.
        self.pending_size_frames: int = 0
        #: a frame that arrived LARGER than the camera it came from, worded.
        self.upscaled: str = ""

    # ── asking ────────────────────────────────────────────────────────────
    async def apply_camera(self, req: CameraRequest) -> None:
        """Send this run's camera request — frame size, integration time,
        gain — as ONE message, and remember what was asked.

        THIS MAKES NO CLAIM ABOUT WHAT HAPPENED. It sends. What the camera
        actually did arrives back in the next lock/frame message and lands
        in the session's `LockState`, which is the only thing anything is
        allowed to read as fact. Automating the request is the point;
        automating the confirmation would be forging the instrument's
        signature."""
        self.camera_request = req
        # WHEN THIS WAS ASKED, so `await_camera` can tell the answer to THIS
        # request from the answer to the last one.
        self.camera_request_at = self._camera_clock()
        if req.frame_size:
            self.frame_size = tuple(req.frame_size)
            self._on_frame_size_change(self.frame_size)
        await self._send_camera_config({"type": "config", **req.as_wire()})

    async def await_camera(self, timeout: float, *, poll: float = 0.05
                           ) -> bool:
        """Wait until the camera has ANSWERED the request just sent, and
        return whether it did.

        WHY THIS EXISTS, and it is not belt and braces: `apply_camera` sends
        and returns. If the manual-lever gate read the lock straight after
        it, it would be reading the read-back from the PREVIOUS request —
        which for the very first manual request is the converge-then-freeze
        one, carrying no refusals at all. The gate would pass, the run would
        proceed, and its numbers would describe a regime nobody asked for.
        That is precisely the failure `manual_camera_unavailable` exists to
        stop, arriving one line earlier than the check.

        A request that asks for NEITHER lever needs no answer to be honest —
        nothing about its numbers depends on one — so it returns at once and
        an ordinary run costs nothing here.

        A TIMEOUT IS NOT A PASS. It returns False and the gate then runs on
        whatever is there, where a manual request with no read-back lands on
        "the camera never reported an integration time back" and refuses."""
        import asyncio
        if not self.camera_request.manual:
            return True
        deadline = self._camera_clock() + max(0.0, timeout)
        while True:
            if self._camera_lock_stamp() >= self.camera_request_at:
                return True
            if self._camera_clock() >= deadline:
                return False
            await asyncio.sleep(poll)

    async def await_frame_size(self, size: tuple, timeout: float, *,
                               poll: float = 0.05) -> tuple:
        """Wait until frames are arriving at `size` — or at the client's own
        honest downgrade of it — and return the size that actually arrived.

        A client that CANNOT reach the rung sends the largest one it can and
        says so on every frame, so "smaller than asked for" is a RESULT, not
        a failure: this returns it and the caller decides. A client that
        never switches at all times out, and the caller refuses by name
        rather than stacking frames of two shapes."""
        import asyncio
        want = tuple(size)
        deadline = self._camera_clock() + max(0.0, timeout)
        while True:
            got = self.active_frame_size
            if got == want:
                return got
            # A settled DOWNGRADE needs no more waiting: the camera cannot
            # do better, so time changes nothing.
            if (self.source_size != (0, 0)
                    and got == choose(want, *self.source_size)):
                return got
            if self._camera_clock() >= deadline:
                return got
            await asyncio.sleep(poll)

    # ── what arrived ──────────────────────────────────────────────────────
    def note_frame(self, width: int, height: int,
                   source_w: int = 0, source_h: int = 0) -> Optional[str]:
        """Record one arriving frame's shape. Returns a REFUSAL SENTENCE
        when the frame must not be counted (it is bigger than the camera it
        came from), else None.

        Called before the frame is stored, so a rejected one never reaches
        a ring."""
        if source_w > 0 and source_h > 0:
            self.source_size = (int(source_w), int(source_h))
            if width > source_w or height > source_h:
                # NEVER COUNTED. Interpolated pixels would inflate
                # `gray_code.resolution_report`'s camera-pixel count and let
                # an unreadable target report that it is readable — the
                # confident-wrong-answer the MARGINAL verdict exists to
                # refuse, arriving through a side door.
                from spectra.services import mapping_refusals
                self.upscaled = mapping_refusals.upscaled_frame(
                    width, height, source_w, source_h)
                return self.upscaled
        self.active_frame_size = (int(width), int(height))
        if self.active_frame_size != self.frame_size:
            self.pending_size_frames += 1
        return None

    def observed_fps(self) -> float:
        """The rate frames are ACTUALLY arriving at, from their own
        timestamps — never the rate the tap asked for. A long integration
        time lowers what a camera can deliver and the run pricing has to
        know the real number. 0.0 until there are two frames to time."""
        times = list(self._camera_frame_times())[-16:]
        if len(times) < 2:
            return 0.0
        span = times[-1] - times[0]
        return round((len(times) - 1) / span, 3) if span > 0 else 0.0

    # ── the two gates ─────────────────────────────────────────────────────
    def frame_refusal(self, want: tuple) -> Optional[str]:
        """An upscale seen on the wire, or a client that never adopted a
        size it could have reached.

        AN HONEST DOWNGRADE IS NOT A REFUSAL and never returns a sentence:
        the run carries on at the rung the camera actually has and says
        which it got, because a 1280x720 read of one fixture is a real
        measurement and refusing it would strand a perfectly good camera.
        The resolution report then refuses on its own terms if that rung
        cannot carry the target — which is a measurement, not a guess."""
        if self.upscaled:
            return self.upscaled
        got = self.active_frame_size
        if got == tuple(want):
            return None
        if got == choose(tuple(want), *self.source_size):
            return None
        from spectra.services import mapping_refusals
        return mapping_refusals.frame_size_not_adopted(
            tuple(want), got, self.source_size, self.pending_size_frames)

    def camera_refusal(self) -> Optional[str]:
        """THE MANUAL LEVERS' OWN GATE, or None when nothing manual was
        asked for or everything asked for was taken.

        Separate from the exposure LOCK's refusal on purpose: the lock is
        the instrument's founding honesty and gates every run ever; these
        gate only a run that asked for them. A run that asks for neither
        must behave exactly as it did before they existed, and this
        returning None for an all-default request is what guarantees it.

        Read off the LOCK — the device's read-back — never off the request.
        A returning write call is never evidence."""
        req = self.camera_request
        if not req.manual:
            return None
        lock = self._camera_lock_view()
        refused = [str(x) for x in (lock.get("manual_refusals") or [])]
        # A camera that would not say what a pinned control became is
        # refusing just as much as one that named a control it does not
        # have — and more dangerously, because the frames still arrive and
        # only the numbers are wrong. Checked for ALL FOUR levers off one
        # declaration, so a fifth cannot be added on one side only.
        for name, _lo, _hi, _unit, words in LEVER_BOUNDS:
            if getattr(req, name) is not None and lock.get(name) is None:
                refused.append(f"the camera never reported {words} back, so "
                               f"there is nothing to check the request "
                               f"against")
        if not refused:
            return None
        from spectra.services import mapping_refusals
        return mapping_refusals.manual_camera_unavailable(
            refused, req.as_wire(), lock)

    def camera_status(self) -> dict:
        return {"frame_size": {"width": self.frame_size[0],
                               "height": self.frame_size[1]},
                "active_frame_size": {"width": self.active_frame_size[0],
                                      "height": self.active_frame_size[1]},
                "source_size": {"width": self.source_size[0],
                                "height": self.source_size[1]},
                "frame_sizes": [{"width": w, "height": h} for w, h in PROFILES],
                "camera_request": self.camera_request.as_wire(),
                "pending_size_frames": self.pending_size_frames,
                "upscaled": self.upscaled,
                "observed_fps": self.observed_fps()}


class SessionCameraDouble(CameraNegotiation):
    """A WELL-BEHAVED CLIENT'S HALF OF THE NEGOTIATION, for the fake
    sessions the executable specs and the tests drive.

    THE SAME PRECEDENT `spectra/capture_client/camera.py::SyntheticCamera`
    sets, and for the same reason: the specs must prove this whole path
    without a camera, a room or a light, and a double that MODELS the
    negotiation instead of running it proves nothing about the real one. So
    this inherits every decision from `CameraNegotiation` above and supplies
    only what a client does — adopt the largest rung its (declared) camera
    can reach, and report where it came from.

    WHAT IT MUST NEVER GROW is a way to report a lock it did not have. It
    holds no opinion about the exposure lock at all: `camera_lock` is
    whatever the owning fake declares, exactly as SyntheticCamera's is.

    A spec that wants the MISBEHAVING cases — a client that never adopts a
    size, one that upscales, a camera that will not take a manual lever —
    gets them by setting `camera_source`, calling `note_frame` itself, or
    declaring a lock with `manual_refusals`. None of them is reachable by
    accident.

    IT DECLARES ITSELF THE NATIVE CAPTURE CLIENT, since the browser's
    demotion, and that is the same "add a capability here, not in seven
    places" rule this class already exists for: every spec that drives a
    capture run is a spec about the RUN, and a double silently reading as a
    browser would refuse every one of them for a reason none of them is
    about. A spec that IS about the browser says so — one line,
    `hello = {"user_agent": ...}` — which is how the demotion gets exercised
    rather than modelled. `spectra/services/capture_source.py` is the
    binding statement."""

    #: What this double's camera can deliver. The top rung by default (a
    #: spec is not usually about the camera's limits); lower it to make a
    #: run negotiate down.
    camera_source: tuple = (1920, 1080)
    #: What the lock reads back, in `LockState.as_dict()` shape. A spec
    #: about the manual levers replaces this.
    camera_lock: dict = {}
    #: How long a client takes to adopt a new size, in this double's terms:
    #: True adopts instantly (the normal case), False never adopts (the
    #: refusal case).
    adopts_frame_size: bool = True

    #: A double whose camera does not answer a request at all — how a spec
    #: makes `await_camera` time out without touching the gate.
    answers_camera_config: bool = True

    #: WHAT THIS DOUBLE SAYS IT IS. The native capture client by default —
    #: see the docstring. An instance that sets its own `hello` (a browser,
    #: a named host, a pose label) overrides this entirely, as it always did.
    hello: dict = {"client": capture_source.NATIVE_CLIENT}

    async def _send_camera_config(self, payload: dict) -> None:
        self.camera_configs = getattr(self, "camera_configs", [])
        self.camera_configs.append(payload)
        if self.answers_camera_config:
            # A real client answers with a `lock` message; this double
            # answers by stamping, which is the same fact one layer down.
            self.camera_lock_at = self._camera_clock()
        if not self.adopts_frame_size:
            return
        got = choose(self.frame_size, *self.camera_source)
        self.note_frame(got[0], got[1], *self.camera_source)

    camera_lock_at: float = 0.0

    def _camera_lock_stamp(self) -> float:
        return self.camera_lock_at

    def _camera_lock_view(self) -> dict:
        if self.camera_lock:
            return dict(self.camera_lock)
        # A double whose owning fake declares a plain `lock` object gets its
        # read-back from that, so a spec about the exposure lock and a spec
        # about the manual levers describe ONE camera.
        lock = getattr(self, "lock", None)
        return lock.as_dict() if hasattr(lock, "as_dict") else {}

    def _camera_clock(self) -> float:
        clock = getattr(self, "_clock", None)
        if callable(clock):
            return float(clock())
        import time as _time
        return _time.monotonic()
