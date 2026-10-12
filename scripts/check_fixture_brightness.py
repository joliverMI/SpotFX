"""WHAT A TURNED-DOWN FIXTURE DOES TO A MAP, and what the guard does about
it — measured on the real derivation, with the real vendored driver call.

THE LIVE FINDING THIS EXISTS FOR (2026-08-31): his fixture was at TEN
PERCENT firmware brightness for his first whole mapping run. Every footprint
in the stored map is ~10x dim; five blocks landed at 0.1 or less, which is
the unseen threshold's own tail, so pieces that were lit and in shot were
recorded as if the camera never saw them. The instrument was measuring his
dimmer and nothing in the map said so.

WHAT THIS SHOWS, in order:

  1. THE DAMAGE, through the real `light_field.footprint_from_frames`: the
     same room, the same emitter, the same camera — at 100% and at 10%.
     Weight scales with the dimmer, and the thumbnail does NOT, which is the
     trap: the picture looks identical while the measurement is gone.
  2. THE READ, against the real vendored `WLED.get_brightness` over a
     stubbed transport — and THE REFUSAL: since 2026-10-12 a WLED's
     brightness is Home Assistant's, so the real transport refuses a body
     carrying `bri` before anything reaches the wire.
  3. THE GUARD: the warning that lands before the cost (naming Home
     Assistant as the place to raise it), and a capture measured AS IS —
     nothing written, including when the capture raises.

Run from repo root: .venv/bin/python scripts/check_fixture_brightness.py
No LedFX, no network, no live storage, no camera, no fixture.
"""
from __future__ import annotations

import asyncio
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print = __import__("functools").partial(print, flush=True)   # noqa: A001

from spectra.models.room_map import (AxisCalibration, CaptureContext,  # noqa: E402
                                     GRID_H, GRID_W, Point)
from spectra.services import fixture_brightness as fb        # noqa: E402
from spectra.services import light_field                     # noqa: E402

FAILURES: list[str] = []
AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))


def check(cond, label):
    if not cond:
        FAILURES.append(label)
        print(f"FAIL: {label}")
        return False
    print(f"ok: {label}")
    return True


def _footprint(scale: float):
    """One emitter photographed at `scale` of full fixture brightness, put
    through the REAL derivation the run uses."""
    dark = np.full((GRID_H, GRID_W), 4.0)          # a room that is not black
    lit = dark.copy()
    lit[8:16, 20:40] += 200.0 * scale              # the fixture's own patch
    return light_field.footprint_from_frames(
        emitter_id="tv:blk3", virtual_ids=["tv"], dark_frames=[dark, dark],
        lit_frames=[lit, lit], axis=AXIS, capture=CaptureContext())


class _Response:
    ok = True

    def __init__(self, payload=None):
        self._payload = payload or {}

    def json(self):
        return self._payload


async def main() -> int:
    print("== 1. what a turned-down fixture does to the measurement ==")
    full = _footprint(1.0)
    dimmed = _footprint(0.10)                      # his actual level
    print(f"   at 100%: weight {full.weight:8.2f}")
    print(f"   at  10%: weight {dimmed.weight:8.2f}")
    ratio = dimmed.weight / full.weight if full.weight else 0.0
    check(abs(ratio - 0.10) < 0.02,
          f"weight scales with the FIXTURE's own brightness "
          f"({ratio * 100:.1f}% of full) — a map taken like this measures "
          f"the dimmer, not the room")
    check(dimmed.weight < light_field.UNSEEN_WEIGHT * 40,
          f"and at {dimmed.weight:.1f} it is close enough to the unseen "
          f"threshold ({light_field.UNSEEN_WEIGHT}) that a smaller piece of "
          f"the same fixture records as NEVER SEEN — which is exactly what "
          f"happened to five of his blocks")

    a = light_field.thumbnail(full)
    b = light_field.thumbnail(dimmed)
    same = max(abs(x - y) for ra, rb in zip(a, b) for x, y in zip(ra, rb))
    check(same < 1e-6,
          f"THE TRAP: the two thumbnails are IDENTICAL (max cell difference "
          f"{same:.2e}) — normalized to each footprint's own peak, so the "
          f"picture is blind to the magnitude it normalized away. This is "
          f"why a weight is now shown beside every thumbnail and a faint "
          f"footprint says so (light_field.faint_ids)")

    print("\n== 2. the real vendored driver call, at the wire ==")
    from fx import utils as fx_utils
    from fx.utils import WLED, WLEDBrightnessRefused
    sent: list[dict] = []

    def _post(url, timeout=None, **kwargs):
        sent.append({"url": url, **kwargs})
        return _Response()

    def _get(url, timeout=None, **kwargs):
        return _Response({"bri": 26, "on": True})

    original_post, original_get = fx_utils.requests.post, fx_utils.requests.get
    fx_utils.requests.post, fx_utils.requests.get = _post, _get
    try:
        wled = WLED("1.2.3.4")
        read = await wled.get_brightness()
        refused = ""
        try:
            await WLED._wled_request(fx_utils.requests.post, "1.2.3.4",
                                     "json/state", json={"bri": 255})
        except WLEDBrightnessRefused as exc:
            refused = str(exc)
        await WLED._wled_request(fx_utils.requests.post, "1.2.3.4",
                                 "json/state", json={"on": True})
    finally:
        fx_utils.requests.post, fx_utils.requests.get = original_post, original_get
    check(read == 26, f"get_brightness reads json/state's `bri` ({read}/255 "
                      f"= {round(read * 100 / 255)}%)")
    check(not hasattr(WLED, "set_brightness"),
          "the vendored set_brightness is gone — nothing here writes it")
    check(refused and "Home Assistant" in refused,
          f"the real transport REFUSES a `bri` body before it reaches the "
          f"wire: {refused!r}")
    check(sent == [{"url": "http://1.2.3.4/json/state", "json": {"on": True}}],
          f"…and a power-only body still goes out untouched ({sent})")

    print("\n== 3. the guard: warned before the cost, measured as is ==")

    class _Helper:
        def __init__(self, value):
            self.value, self.writes = value, []

        async def get_brightness(self):
            return self.value

        async def set_brightness(self, v):             # must never be called
            self.writes.append(v)

    class _Device:
        def __init__(self, did, helper):
            self.id, self.type, self.wled = did, "wled", helper

    helper = _Helper(26)
    readings = await fb.read_all([_Device("tv-backlight", helper)])
    warning = fb.warning_for(readings)
    print(f"   plan warning: {warning}")
    check("TURNED DOWN" in warning and "Home Assistant" in warning,
          "the plan warns before the room goes dark, and names Home "
          "Assistant as where he raises it")
    async with fb.measured_as_is([_Device("tv-backlight", helper)],
                                 readings) as as_is:
        during = helper.value
    print(f"   run note: {as_is.note}")
    check(during == 26 and helper.writes == [],
          "the capture runs at HIS level and writes nothing")
    crashed = _Helper(26)
    try:
        async with fb.measured_as_is([_Device("tv-backlight", crashed)]):
            raise RuntimeError("the capture died")
    except RuntimeError:
        pass
    check(crashed.writes == [],
          "a capture that raises writes nothing either — there is nothing to "
          "put back")

    if FAILURES:
        print(f"\nFAILED {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("\nFIXTURE BRIGHTNESS: MEASURED, WARNED BEFORE THE COST, MEASURED "
          "AS IS — NEVER WRITTEN (it is Home Assistant's)")
    return 0


if __name__ == "__main__":
    status = 1
    try:
        status = asyncio.run(main())
    except Exception:                                          # noqa: BLE001
        import traceback
        traceback.print_exc()
    os._exit(status)
