"""HIS OWN EVENING, REPLAYED — and what the short-exposure regime does to it.

THE MEASUREMENTS (2026-09-09, his kiosk Brio, both taken with the whole
production instrument). The lever self-test refused every commissioning run,
and it refused in TWO DIFFERENT SHAPES depending on one V4L2 control:

    exposure_dynamic_framerate = 1 (as found)
        night   commanded  62 -> 6.49    commanded 250 -> 33.61  again -> 16.03
        day     commanded  62 -> 5.68    commanded 250 -> 11.77  again -> 24.73
    exposure_dynamic_framerate = 0 (pinned off)
        commanded  62 -> 12.577          commanded 250 -> 2.46

WHAT THIS SCRIPT SHOWS, in order, and every number below is computed by the
production code rather than quoted:

  1. THE INSTRUMENT WAS RIGHT BOTH TIMES. His three reading sets are driven
     through the REAL `lever_selftest.judge` and produce the verdicts he
     actually got. Nothing was wrong with the refusals.
  2. THE CEILING, derived by the real `short_exposure.ceiling_for` from what
     his camera reports about itself — and WHERE HIS TWO COMMANDS SIT
     against it. This is the whole claim: 62 is inside, 250 is not.
  3. THE LIGHT BUDGET, which is the question the brief calls item 4. His own
     62-unit readings are the evidence, and the arithmetic is stated rather
     than hoped: what the allowed regime should measure, and what the
     fixture-brightness compensation is and is NOT worth.
  4. THE JUDGEMENT IS UNCHANGED. The same drift and the same
     more-time-less-light shapes, moved into the short regime, still refuse
     — through the same `judge`, against the same four constants.
  5. THE PIN'S OWN ROUND TRIP, through the REAL client message handler and
     the REAL `V4L2Camera` against a `v4l2-ctl` that remembers: his value is
     read before the pin and written back on the un-pin.

Run from repo root: .venv/bin/python scripts/check_short_exposure.py
No camera, no network, no live storage, no fixture, no room.

WHAT IT CANNOT SHOW, said here rather than left to be assumed: whether HIS
camera, at HIS pose, measures enough light at 83 x100 us. That needs a
camera on the kiosk, and there is not one. §3 is the arithmetic that says it
should; only a live Calibration One can say that it does.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print = __import__("functools").partial(print, flush=True)   # noqa: A001

from spectra.capture_client import camera as cam             # noqa: E402
from spectra.capture_client.camera import V4L2Camera         # noqa: E402
from spectra.capture_client.session import CaptureClient     # noqa: E402
from spectra.services import capture_settings as cs          # noqa: E402
from spectra.services import fixture_brightness as fb        # noqa: E402
from spectra.services import (lever_selftest, light_field,   # noqa: E402
                              mapping_refusals, room_mapping, short_exposure)

FAILURES: list[str] = []

#: His camera's own read-back: a 30 fps sensor declaring 3..2047, with the
#: dynamic-framerate control present and ON.
BRIO = {"exposure_time_range": [3.0, 2047.0], "exposure_time": 250.0,
        "sensor_fps": 30.0, "dynamic_framerate": 1}

#: (label, commanded, measured) x3, exactly as measured.
HIS_EVENING = [
    ("night, dynamic framerate ON", [(62, 6.49), (250, 33.61), (250, 16.03)]),
    ("day,   dynamic framerate ON", [(62, 5.68), (250, 11.77), (250, 24.73)]),
    ("       dynamic framerate OFF", [(62, 12.577), (250, 2.46)]),
]


def check(cond, label):
    if not cond:
        FAILURES.append(label)
        print(f"FAIL: {label}")
    else:
        print(f"  ok  {label}")


def readings(pairs):
    return [lever_selftest.Reading(label=name, exposure_time=e, ok=True,
                                   weight=w)
            for name, (e, w) in zip(("dim", "bright", "repeat"), pairs)]


# ── 1 ──────────────────────────────────────────────────────────────────────

def section_one():
    print("\n1. HIS OWN EVENING, THROUGH THE REAL JUDGE")
    got = {}
    for label, pairs in HIS_EVENING:
        verdict, response, repeat, _notes = lever_selftest.judge(
            readings(pairs))
        got[label] = verdict
        print(f"   {label}: {verdict}"
              f"  response={response}  repeat={repeat}")
    check(got["night, dynamic framerate ON"] == mapping_refusals.LEVER_DRIFT,
          "his night run, with the control ON, is DRIFT — the same command "
          "measured 33.61 then 16.03")
    check(got["day,   dynamic framerate ON"] == mapping_refusals.LEVER_DRIFT,
          "and so is his daylight run, which is what rules out the room")
    check(got["       dynamic framerate OFF"] == mapping_refusals.LEVER_NO_RESPONSE,
          "with the control OFF it is NO_RESPONSE — 4x the commanded time "
          "measured a fifth of the light")
    check(all(v in mapping_refusals.LEVER_REFUSING for v in got.values()),
          "every one of them refuses, which is why no commissioning run "
          "ever started")


# ── 2 ──────────────────────────────────────────────────────────────────────

def section_two():
    print("\n2. THE CEILING, DERIVED FROM WHAT HIS CAMERA SAYS ABOUT ITSELF")
    c = short_exposure.ceiling_for(BRIO)
    print(f"   sensor {c.sensor_fps:g} fps (measured={c.measured_fps}) -> one "
          f"frame interval = {c.frame_interval_units} x100 us")
    print(f"   fraction {c.used_fraction:g} -> ceiling {c.units} x100 us "
          f"({c.seconds:.4g}s), bound by {c.bound_by}")
    print(f"   his 62 is {'INSIDE' if 62 <= c.units else 'OUTSIDE'} it; "
          f"his 250 is {'INSIDE' if 250 <= c.units else 'OUTSIDE'} it")
    check(c.frame_interval_units == 333,
          "one frame interval at 30 fps is 333 x100 us — physics, not a "
          "preference: a sensor cannot integrate longer than its own frame")
    check(62 <= c.units < 250,
          "the ceiling brackets his two measured points: above the command "
          "that measured real light, below the one that did not")
    check(not c.caps(62) and c.caps(250),
          "so a run asking for 62 is untouched and one asking for 250 is "
          "shortened")
    req, _c, note = short_exposure.cap(cs.CameraRequest(exposure_time=250),
                                       BRIO)
    print(f"   cap(250) -> {req.exposure_time}, dynamic_framerate="
          f"{req.dynamic_framerate}")
    print(f"   said: {note}")
    check(req.exposure_time == c.units and note,
          "the shortening is SAID, never a silent substitution")
    check(req.dynamic_framerate == short_exposure.DYNAMIC_FRAMERATE_OFF,
          "and the frame-rate control is pinned off in the same request — "
          "bounding the exposure while the camera may still renegotiate its "
          "own timing would have bounded nothing")


# ── 3 ──────────────────────────────────────────────────────────────────────

def section_three():
    print("\n3. THE LIGHT BUDGET — will the allowed regime still see?")
    floor = light_field.UNSEEN_WEIGHT
    ceiling = short_exposure.ceiling_for(BRIO).units
    his = [("night", 62, 6.49), ("day", 62, 5.68), ("off", 62, 12.577)]
    print(f"   the floor an emitter must clear: {floor:g}")
    for label, commanded, weight in his:
        scaled = weight * ceiling / commanded
        print(f"   his {label} run measured {weight:g} at {commanded} -> a "
              f"linear camera at {ceiling} would measure {scaled:.1f} "
              f"({scaled / floor:.0f}x the floor)")
        check(scaled > floor,
              f"his own {label} reading, scaled to the allowed regime, is "
              f"over the floor with margin")
    # The compensation, stated honestly rather than implied.
    gain = fb.FULL / 214.0                     # his measured .236 level, 84%
    print(f"   fixture brightness compensation: 84% -> 100% is x{gain:.2f}")
    print(f"   the lamp itself has NO headroom left: "
          f"room_mapping.LIT_BRIGHTNESS={room_mapping.LIT_BRIGHTNESS}, "
          f"fixture_brightness.FULL={fb.FULL}")
    check(gain > 1.0,
          "taking his fixture to full is worth about a fifth more light — "
          "real, and NOT a substitute for the margin above")
    check(fb.FULL == 255,
          "full firmware brightness is already the ceiling, so this is the "
          "whole of the compensation available on the light side")


# ── 4 ──────────────────────────────────────────────────────────────────────

def section_four():
    print("\n4. THE JUDGEMENT DID NOT MOVE")
    print(f"   COMMANDED_FACTOR={lever_selftest.COMMANDED_FACTOR} "
          f"MIN_PROVABLE_FACTOR={lever_selftest.MIN_PROVABLE_FACTOR} "
          f"MIN_RESPONSE_FRACTION={lever_selftest.MIN_RESPONSE_FRACTION} "
          f"REPEAT_BAND={lever_selftest.REPEAT_BAND}")
    check((lever_selftest.COMMANDED_FACTOR,
           lever_selftest.MIN_PROVABLE_FACTOR,
           lever_selftest.MIN_RESPONSE_FRACTION,
           lever_selftest.REPEAT_BAND) == (4.0, 2.0, 0.25, 1.5),
          "the four constants the verdict is decided by are untouched")
    # His own two failing shapes, moved into the short regime's commands.
    drift = readings([(21, 16.6), (83, 66.4), (83, 2.9)])
    verdict, _r, ratio, _n = lever_selftest.judge(drift)
    print(f"   his 23x drift at 21/83/83 -> {verdict} (repeat {ratio})")
    check(verdict == mapping_refusals.LEVER_DRIFT,
          "a camera that drifts INSIDE the short regime still refuses")
    backwards = readings([(21, 40.0), (83, 6.0), (83, 6.0)])
    verdict, ratio, _rp, _n = lever_selftest.judge(backwards)
    print(f"   more-time-less-light at 21/83 -> {verdict} (response {ratio})")
    check(verdict == mapping_refusals.LEVER_NO_RESPONSE,
          "and so does one that answers more time with less light")
    honest = readings([(21, 4.2), (83, 16.6), (83, 16.7)])
    verdict, ratio, repeat, _n = lever_selftest.judge(honest)
    print(f"   a linear camera at 21/83 -> {verdict} (response {ratio}, "
          f"repeat {repeat})")
    check(verdict == mapping_refusals.LEVER_OK,
          "a gate that refuses everything is a wall: an honest camera still "
          "passes inside the short regime")


# ── 5 ──────────────────────────────────────────────────────────────────────

MENUS = """
Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3
				1: Manual Mode
				3: Aperture Priority Mode
         exposure_time_absolute 0x009a0902 (int)    : min=3 max=2047 value=166
    exposure_dynamic_framerate 0x009a0903 (bool)    : default=0 value=1
"""


class RememberingCtl:
    """A `v4l2-ctl` that remembers what was written, so a read-back is a
    read-back and never the write echoing itself."""

    def __init__(self):
        self.values = {"auto_exposure": 3, "exposure_time_absolute": 166,
                       "exposure_dynamic_framerate": 1}
        self.sets: list[tuple[str, int]] = []

    def __call__(self, args, timeout=5.0):
        if "--list-ctrls-menus" in args:
            return 0, MENUS
        if "--get-parm" in args:
            return 0, "\tFrames per second: 30.000 (30/1)\n"
        for arg in args:
            if arg.startswith("--get-ctrl="):
                name = arg.split("=", 1)[1]
                return ((0, f"{name}: {self.values[name]}")
                        if name in self.values else (1, ""))
            if arg.startswith("--set-ctrl="):
                name, _, value = arg.split("=", 1)[1].partition("=")
                self.sets.append((name, int(value)))
                self.values[name] = int(value)
                return 0, ""
        return 1, ""


async def section_five():
    print("\n5. THE PIN'S ROUND TRIP, THROUGH THE REAL CLIENT AND CAMERA")
    ctl = RememberingCtl()
    real_tool, real_run = cam._tool, cam._run          # noqa: SLF001
    cam._tool = lambda name: f"/usr/bin/{name}"        # noqa: SLF001
    cam._run = ctl                                     # noqa: SLF001
    try:
        camera = V4L2Camera()
        client = CaptureClient("ws://unused", camera)

        class Ws:
            sent: list = []

            async def send(self, raw):
                Ws.sent.append(raw)

        # WHAT THE SERVER ACTUALLY PUTS ON THE WIRE for a commissioning run.
        req, _c, _n = short_exposure.cap(cs.CameraRequest(exposure_time=250),
                                         BRIO)
        wire = {"type": "config", **req.as_wire()}
        print(f"   server sends: exposure_time={wire['exposure_time']} "
              f"dynamic_framerate={wire['dynamic_framerate']}")
        await client._apply_config(Ws(), wire)         # noqa: SLF001
        print(f"   camera controls now: {ctl.values}")
        check(ctl.values["exposure_dynamic_framerate"] == 0,
              "the pin reached the driver")
        check(camera._switch_original == {"dynamic_framerate": 1},  # noqa: SLF001
              "and HIS value was read out of the device first, before "
              "anything of ours touched it")
        check(camera.lock.dynamic_framerate == 0,
              "the read-back reports it, so a driver that had ignored the "
              "write would be refused by name")

        # RE-ASSERTING (a reconnect, a camera reopen) must not turn the pin
        # itself into "his setting".
        await client._reassert()                       # noqa: SLF001
        check(camera._switch_original == {"dynamic_framerate": 1},  # noqa: SLF001
              "a re-assert does not overwrite the remembered value")

        # AND THE RESTORE: the all-default request every run's `finally`
        # already sends is what hands it back.
        back = cs.CameraRequest(frame_size=cs.MAP_PROFILE)
        await client._apply_config(                    # noqa: SLF001
            Ws(), {"type": "config", **back.as_wire()})
        print(f"   after the run's own restore: {ctl.values}")
        check(ctl.values["exposure_dynamic_framerate"] == 1,
              "his own setting is back on the camera")
        check(camera._switch_original == {},           # noqa: SLF001
              "and nothing is left owed")
    finally:
        cam._tool, cam._run = real_tool, real_run      # noqa: SLF001


async def main() -> int:
    section_one()
    section_two()
    section_three()
    section_four()
    await section_five()
    if FAILURES:
        print(f"\nFAILED {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("\nSHORT-EXPOSURE REGIME: DERIVED FROM THE CAMERA, BOUNDED, SAID, "
          "AND THE LEVER STILL REFUSES EVERYTHING IT DID BEFORE")
    print("UNVERIFIED AGAINST A LIVE CAMERA — there is none on the kiosk.")
    return 0


if __name__ == "__main__":
    status = 1
    try:
        status = asyncio.run(main())
    except Exception:                                          # noqa: BLE001
        import traceback
        traceback.print_exc()
    os._exit(status)
