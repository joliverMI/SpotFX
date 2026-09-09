"""THE SHORT-EXPOSURE COMMISSIONING REGIME — the part of a camera's exposure
range it can actually hold, and the one control that decides where that
part ends.

PURE. No camera, no session, no store, no clock: a read-back dict and a
request in, a bounded request and a sentence out. Both runs that command an
integration time for their own reasons (the lever self-test and the
commissioning pass) read the ceiling from here, so "how short is short" is
one number rather than two that agree today.

────────────────────────────────────────────────────────────────────────────
ONE. THE EVENING THIS EXISTS FOR (2026-09-09, his kiosk Brio)
────────────────────────────────────────────────────────────────────────────

`lever_selftest.run_selftest` refused every commissioning run on that camera,
night AND daylight, and it refused in TWO DIFFERENT SHAPES depending on one
V4L2 control:

  `exposure_dynamic_framerate = 1` (as found) -> verdict DRIFT. The SAME
  commanded integration time measured different light run to run:

      night   commanded  62 -> 6.49      day   commanded  62 -> 5.68
              commanded 250 -> 33.61           commanded 250 -> 11.77
              commanded 250 -> 16.03           commanded 250 -> 24.73

  `exposure_dynamic_framerate = 0` (pinned off) -> verdict NO_RESPONSE:
  commanded 62 measured 12.577 and commanded 250 measured 2.46. MORE
  commanded time, LESS measured light.

Neither verdict was wrong and neither is the instrument being fussy. Read
together they say something specific and useful: this camera is honest in
the SHORT part of its exposure range and is not honest above it, and the
control that separates the two halves is the one named above. `exposure_
dynamic_framerate` is what lets a UVC camera DROP ITS FRAME RATE to achieve
an integration time longer than one frame interval. Leave it on and the
camera renegotiates its own timing underneath a measurement — which is
drift, measured. Pin it off and a command that needs it simply cannot be
delivered — which is no response, measured. There is no third setting in
which the long end of that range becomes trustworthy, so the answer is to
stop asking for it.

────────────────────────────────────────────────────────────────────────────
TWO. THE CEILING, AND WHICH HALF OF IT IS DERIVED
────────────────────────────────────────────────────────────────────────────

DERIVED, from physics and from the device's own answer: a sensor delivering
F frames a second cannot integrate for longer than 1/F seconds per frame.
That is the whole reason `exposure_dynamic_framerate` exists, and with it
pinned off the frame interval IS the ceiling. So:

    frame_interval_units = 1 / (F * capture_settings.EXPOSURE_UNIT_S)

and F is READ OFF THE DEVICE — `v4l2-ctl --get-parm`, carried to the server
as `CameraLock.sensor_fps` — never assumed while the camera is willing to
say. A camera that will not say is handled below, and SAYS that it was
assumed.

NOT DERIVED, and this is stated rather than dressed up: WHERE INSIDE that
interval this camera stops being trustworthy. His two measured points
bracket it and do not locate it — 62 units (6.2 ms) produced a plainly real
reading on both nights, 250 units (25 ms) did not, and the frame interval of
a 30 fps stream is 333 units, so the failing command was at 75% of the
arithmetic bound and the good one at 19%. A boundary cannot be interpolated
from two points, and inventing one and calling it derived would be exactly
the confident wrong answer this whole instrument exists to refuse.

So the fraction of the frame interval a run may use is A BOUNDED SETTING
(`spectra/config.py::short_exposure_fraction`, env
`SPECTRA_SHORT_EXPOSURE_FRACTION`) with a CONSERVATIVE DEFAULT
(`DEFAULT_FRACTION`) anchored on those two measured points — comfortably
above the one that worked, comfortably below the one that did not — and the
`Ceiling` this module returns says in words which bound it landed on and
whether the frame rate behind it was measured or assumed. When a live camera
is back, the honest way to move it is to MEASURE more points (the lever
self-test is exactly that instrument) and re-anchor, not to nudge it until a
run passes.

WHAT IT IS NOT: a tolerance. `lever_selftest`'s own bars — COMMANDED_FACTOR,
MIN_RESPONSE_FRACTION, REPEAT_BAND, MIN_PROVABLE_FACTOR — and
`commission_compare`'s five pre-registered tolerances are untouched by this
module and must stay untouched. This moves WHERE the self-test measures,
into the range this camera can hold. It does not move WHETHER the readings
must agree once it has measured them. A camera that drifts inside the short
regime still refuses, and that is the point: if the short regime were bought
by relaxing the judgement, the instrument would be decoration.

────────────────────────────────────────────────────────────────────────────
THREE. OWN THE FLAG, AND GIVE IT BACK
────────────────────────────────────────────────────────────────────────────

`exposure_dynamic_framerate` is HIS camera's setting, not this app's. A run
pins it off for its own duration and the client puts back the value it read
off the device before the pin — the `fixture_brightness.owned` contract one
layer down, living in `spectra/capture_client/camera.py` because that is the
only thing that can read the camera. A run un-pins by naming the control
null, which every restore path here already does by re-applying the request
it saved.

IT IS A SWITCH, NOT A FIFTH LEVER, and the difference is a refusal. The four
pinned levers (`capture_settings.LEVER_BOUNDS`) are asked for by a run, and
a camera that does not HAVE one refuses the run by name — right, because the
run asked. This is asked for by the INSTRUMENT, about a control most cameras
do not have, so ABSENCE IS NOT A REFUSAL: a camera with no such control
cannot renegotiate its frame rate under a measurement and has nothing to
pin. A camera that HAS it and did not take the write is refusing exactly as
much as any lever that read back wrong, and is refused on the read-back like
one.

────────────────────────────────────────────────────────────────────────────
FOUR. WHAT THE SHORT REGIME COSTS, AND WHO PAYS IT
────────────────────────────────────────────────────────────────────────────

A shorter integration collects less light, so an emitter that used to clear
`light_field.UNSEEN_WEIGHT` may stop clearing it.

THE BEST EVIDENCE AVAILABLE WITHOUT A CAMERA SAYS IT SHOULD NOT, and it is
his own: the 62-unit command that he actually ran measured footprint weights
of 6.49, 5.68 and 12.577 against a floor of 1.0 — five to twelve times the
bar — and the ceiling this module derives for that camera is 83, which is
LONGER than 62. So the regime this build allows is not a reduction from the
regime known to have seen his room; it is the regime known to have seen it,
plus a third again. `scripts/check_short_exposure.py` §3 computes that from
his numbers rather than asserting it. What none of it settles is whether HIS
pose, on the night, clears the floor — only a live camera can say that.

Three things follow anyway, and none of them is a fudge:

  * THE FIXTURE GOES TO FULL. `fixture_brightness.owned` already takes every
    controllable fixture to full firmware brightness for a capture and puts
    his own level back; the map, the commissioning pass and the pose
    fingerprint have always run inside it and THE LEVER SELF-TEST NEVER DID.
    It does now, which is the compensation this build can actually deliver.
  * THERE IS NO HEADROOM LEFT IN THE LAMP, and saying so is more use than
    pretending otherwise: `room_mapping.LIT_BRIGHTNESS` is already 1.0, the
    commissioning pattern lamp already writes `brightness: 1.0`, and
    `fixture_brightness.FULL` is already 255. Full is full.
  * SO A REGIME THAT STILL CANNOT SEE SAYS THAT. It is reported as what it
    is — "not enough light at the exposure this camera can hold" — never as
    a pass, and never by lowering the floor. `mapping_refusals.
    lever_not_connected` names the cap in the NO_SIGNAL sentence so the
    reader is sent to the light rather than to the camera.

GAIN IS DELIBERATELY NOT RAISED to compensate. It is one of his four pinned
levers, a run that wants it names it, and raising it unasked would lift the
sensor's own noise into the very `lit - dark` difference this instrument
measures — trading a shortage of signal for a fabrication of it.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from spectra import config as scfg
from spectra.services import capture_settings

#: THE WIRE VALUE that turns the control off. The wire carries the driver's
#: own scale for every camera control (integration time in V4L2's own
#: 100-microsecond units, gain verbatim), so this is V4L2's own menu value
#: and nothing converts. The client declares the same number for itself
#: (`spectra/capture_client/camera.py::DYNAMIC_FRAMERATE_OFF`) because that
#: package may not import `spectra.services` at all; the two are asserted
#: equal in `tests/test_short_exposure.py` rather than left to agree.
DYNAMIC_FRAMERATE_OFF = 0
DYNAMIC_FRAMERATE_ON = 1

#: The frame rate assumed when the camera will not report its own. 30 is the
#: rate a UVC webcam negotiates when nothing else is asked for, and it is the
#: rate his own Brio evidence is consistent with. An assumed rate is always
#: SAID (`Ceiling.measured_fps`), and it only ever produces a SHORTER
#: ceiling than a slower real rate would — the conservative direction.
ASSUMED_FPS = 30.0

#: How much of one frame interval a commissioning-grade run may command.
#: SEE SECTION TWO: anchored on his two measured points, not derived from
#: them. At the assumed 30 fps this is 83 x100 us (8.3 ms) — a third above
#: the 62 that measured real light on both nights, a third of the 250 that
#: did not.
DEFAULT_FRACTION = 0.25
#: The bounds `config.short_exposure_fraction` clamps into. The floor is not
#: zero: a fraction that rounds the ceiling below a device's own minimum
#: leaves no regime to measure in at all, which is a broken run rather than
#: a cautious one.
MIN_FRACTION = 0.02
MAX_FRACTION = 1.0

#: The absolute floor for a derived ceiling, in the wire's own units. One
#: unit is 100 us; below a handful of them no sensor is integrating anything
#: and every reading is read noise. A camera whose declared minimum is
#: higher than this still wins — `ceiling_for` never asks for less than the
#: device says it can do.
MIN_CEILING_UNITS = 5


def fraction() -> float:
    """The configured fraction of one frame interval, bounded."""
    return max(MIN_FRACTION, min(MAX_FRACTION, scfg.short_exposure_fraction()))


@dataclass(frozen=True)
class Ceiling:
    """THE LONGEST INTEGRATION TIME A COMMISSIONING-GRADE RUN MAY COMMAND on
    this camera, and every input that produced it.

    Every field is reported rather than only the answer, because the answer
    depends on one number that may have been assumed — and a reader deciding
    whether to trust a refusal needs to know which."""
    units: int
    #: The frame rate the ceiling was derived against, and whether the
    #: camera itself said it. `measured_fps` False means ASSUMED_FPS.
    sensor_fps: float = ASSUMED_FPS
    measured_fps: bool = False
    used_fraction: float = DEFAULT_FRACTION
    #: One whole frame interval, in wire units — the physical bound before
    #: the fraction is applied.
    frame_interval_units: int = 0
    #: The device's own declared range, when it declares one.
    device_min: Optional[int] = None
    device_max: Optional[int] = None
    #: "frame_interval" | "device_max" | "device_min" — which bound decided.
    bound_by: str = "frame_interval"
    #: Does this camera's read-back evidence an integration-time control at
    #: all? A lock that reports neither a value nor a range is a camera that
    #: has never shown it has one, and NOTHING HERE COMMANDS ONE — asking a
    #: camera for a control it has not reported having is how a run that
    #: worked yesterday starts refusing by name for a reason that is ours.
    commandable: bool = False

    @property
    def seconds(self) -> float:
        return self.units * capture_settings.EXPOSURE_UNIT_S

    def caps(self, exposure_time: Optional[int]) -> bool:
        """Would this ceiling actually change what was asked for?"""
        return exposure_time is not None and int(exposure_time) > self.units

    def sentence(self) -> str:
        """What a run puts in its notes, in one line, naming which bound
        decided and whether the rate behind it was measured."""
        how = (f"its own reported {self.sensor_fps:g} fps"
               if self.measured_fps else
               f"an assumed {self.sensor_fps:g} fps (this camera does not "
               f"report its frame rate)")
        if self.bound_by == "device_max":
            return (f"This run commands at most {self.units} x100 us "
                    f"({self.seconds:.4g}s) — the highest integration time "
                    f"this camera declares. Its frame interval at {how} "
                    f"would have allowed {self.frame_interval_units}.")
        if self.bound_by == "device_min":
            return (f"This run commands at most {self.units} x100 us "
                    f"({self.seconds:.4g}s) — the LOWEST integration time "
                    f"this camera will accept, which is already longer than "
                    f"the {int(self.frame_interval_units * self.used_fraction)} "
                    f"its frame interval at {how} allows. Nothing this "
                    f"camera can be commanded sits inside the range it can "
                    f"hold steady, so a shorter regime is not available "
                    f"here.")
        return (f"This run commands at most {self.units} x100 us "
                f"({self.seconds:.4g}s): {self.used_fraction:g} of one frame "
                f"interval at {how}. Longer than one frame interval needs the "
                f"camera to drop its frame rate mid-measurement, which is the "
                f"regime this instrument does not trust.")

    def as_dict(self) -> dict:
        return {"units": self.units, "seconds": round(self.seconds, 6),
                "sensor_fps": self.sensor_fps,
                "measured_fps": self.measured_fps,
                "fraction": self.used_fraction,
                "frame_interval_units": self.frame_interval_units,
                "device_min": self.device_min, "device_max": self.device_max,
                "bound_by": self.bound_by, "commandable": self.commandable,
                "sentence": self.sentence()}


def ceiling_for(lock: Optional[dict]) -> Ceiling:
    """The short-exposure ceiling for the camera this read-back describes.

    Reads three things and nothing else: the sensor's own frame rate
    (`sensor_fps`, measured by the client off the device), the device's
    declared exposure range (`exposure_time_range`), and the configured
    fraction. Never touches a session, never sends anything, and is
    therefore safe to call from a plan, a refusal or a proof."""
    lock = lock or {}
    raw_fps = lock.get("sensor_fps")
    try:
        fps = float(raw_fps) if raw_fps is not None else 0.0
    except (TypeError, ValueError):
        fps = 0.0
    measured = fps > 0.0
    if not measured:
        fps = ASSUMED_FPS
    frac = fraction()
    interval_units = int(1.0 / (fps * capture_settings.EXPOSURE_UNIT_S))
    units = int(interval_units * frac)

    rng = lock.get("exposure_time_range") or []
    dev_lo = dev_hi = None
    if len(rng) == 2:
        try:
            dev_lo, dev_hi = int(float(rng[0])), int(float(rng[1]))
        except (TypeError, ValueError):
            dev_lo = dev_hi = None

    bound_by = "frame_interval"
    if dev_hi is not None and dev_hi < units:
        # The camera cannot reach the arithmetic ceiling at all. Its own
        # declared maximum is then the honest answer, and nothing here has
        # to do anything about it.
        units, bound_by = dev_hi, "device_max"
    # NEVER BELOW WHAT THE DEVICE SAYS IT CAN DO. A ceiling under the
    # device's own minimum is not a cautious run, it is a run with no legal
    # command in it — every command would be refused by the driver, which is
    # a fault of ours wearing the camera's name. The floor-up is SAID
    # (`bound_by == "device_min"`), because a camera whose shortest legal
    # exposure is already past its own frame interval has no short regime
    # available and a reader is owed that rather than a number.
    floor = max(MIN_CEILING_UNITS, dev_lo or 0)
    if units < floor:
        units = floor
        bound_by = "device_min" if dev_lo and floor == dev_lo else bound_by
    if dev_hi is not None:
        units = min(units, dev_hi)
    units = max(units, capture_settings.MIN_EXPOSURE_TIME)
    return Ceiling(units=units, sensor_fps=fps, measured_fps=measured,
                   used_fraction=frac, frame_interval_units=interval_units,
                   device_min=dev_lo, device_max=dev_hi, bound_by=bound_by,
                   commandable=(lock.get("exposure_time") is not None
                                or bool(rng)))


def pinnable(lock: Optional[dict]) -> bool:
    """Has this camera REPORTED having the frame-rate control?

    ONLY A CONTROL THE CAMERA HAS SHOWN IT HAS IS EVER PINNED. `None` in the
    read-back means one of two things and neither is a reason to write: the
    camera has no such control (nothing to pin — it cannot renegotiate its
    own frame rate, which is the whole hazard), or nothing has read the lock
    yet (in which case a pin would be asking for a control on no evidence,
    and `capture_settings.camera_refusal` would then hold the run against a
    read-back nobody has). Both are answered by not asking."""
    return (lock or {}).get("dynamic_framerate") is not None


def cap(req: "capture_settings.CameraRequest", lock: Optional[dict],
        *, command_default: bool = True
        ) -> tuple["capture_settings.CameraRequest", Ceiling, str]:
    """Put this run's camera request inside the short regime.

    Returns `(request, ceiling, note)`. The request comes back with:

      * `exposure_time` at or under the ceiling — the caller's own value
        when it already was (a run asking for LESS light is never overridden
        upward), the ceiling itself otherwise;
      * `dynamic_framerate` pinned off WHEN THIS CAMERA HAS THE CONTROL
        (`pinnable`), because a request that bounds the exposure and leaves
        the camera free to renegotiate its frame rate has bounded nothing —
        and because asking a camera for a control it never reported is how
        a working run starts refusing for a reason that is ours.

    `command_default=True` is what makes this a REGIME rather than a clamp:
    a run that names no integration time would otherwise be measured at
    whatever the camera converged to before its lock, which on his own
    camera is the untrusted half of the range and is precisely what pinning
    the frame-rate control off makes worse. So the ceiling is COMMANDED when
    nothing else says — BUT ONLY on a camera whose read-back evidences an
    integration-time control at all (`Ceiling.commandable`), for the same
    reason the switch is only pinned when the camera has it.
    `command_default=False` is for a caller that wants the clamp without the
    command.

    `note` is empty when nothing changed for this camera, and is the
    sentence a run puts in its own notes otherwise — never a silent
    substitution."""
    ceiling = ceiling_for(lock)
    asked = req.exposure_time
    if asked is None:
        exposure = (ceiling.units if command_default and ceiling.commandable
                    else None)
    else:
        exposure = min(int(asked), ceiling.units)
    out = replace(req, exposure_time=exposure,
                  dynamic_framerate=(DYNAMIC_FRAMERATE_OFF if pinnable(lock)
                                     else req.dynamic_framerate))
    if asked is not None and exposure != int(asked):
        note = (f"The integration time asked for ({int(asked)} x100 us) is "
                f"longer than this camera can hold steady, and was shortened "
                f"to {exposure}. " + ceiling.sentence())
    elif asked is None and exposure is not None:
        note = ceiling.sentence()
    else:
        note = ""
    return out, ceiling, note
