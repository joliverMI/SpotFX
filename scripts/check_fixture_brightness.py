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
  2. THE READ, against the real vendored `WLED.get_brightness`/
     `set_brightness` over a stubbed transport, so the wire shape is proved
     rather than assumed.
  3. THE GUARD: the warning that lands before the cost, and the
     take-it-to-full-and-give-it-back around a capture — including when the
     capture raises, the case that would otherwise leave his lounge lit.

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
    from fx.utils import WLED
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
        await wled.set_brightness(read)            # the RESTORE shape
    finally:
        fx_utils.requests.post = original_post
        fx_utils.requests.get = original_get

    check(read == 26, f"get_brightness reads json/state's `bri` ({read}/255 "
                      f"= {round(read * 100 / 255)}%, his own level)")
    check(sent[0]["json"] == {"bri": 26},
          f"set_brightness sends THE VALUE IT WAS GIVEN {sent[0]['json']} — "
          f"upstream's double `max` forced every input to 255, so a restore "
          f"would silently have set full and called itself a restore")
    check(sent[0]["url"] == "http://1.2.3.4/json/state" and "data" not in sent[0],
          f"as a JSON body to {sent[0]['url']} — upstream form-encoded it to "
          f"a double-slashed URL")

    print("\n== 3. the guard ==")
    readings = [fb.FixtureBrightness("tv-backlight", "read", 26),
                fb.FixtureBrightness("sconce", "read", 255),
                fb.FixtureBrightness("hue-lamp", "not_applicable")]
    warning = fb.warning_for(readings)
    print(f"   plan warning: {warning}")
    check("TURNED DOWN" in warning and "tv-backlight at 10%" in warning,
          "the plan names the fixture and its level BEFORE the room goes "
          "dark — a warning after a four-minute run has arrived too late")
    check("sconce" not in warning and "hue-lamp" not in warning,
          "and says nothing about a fixture at full, or one with no such "
          "setting to read (never a fabricated 255)")

    class _Helper:
        def __init__(self, value):
            self.value, self.writes = value, []

        async def get_brightness(self):
            return self.value

        async def set_brightness(self, v):
            self.writes.append(int(v))
            self.value = int(v)

    class _Device:
        def __init__(self, i, h):
            self.id, self.type, self.wled = i, "wled", h

    helper = _Helper(26)
    async with fb.owned([_Device("tv-backlight", helper)]) as owned:
        during = helper.value
    check(during == 255 and helper.value == 26,
          f"the capture runs at full ({during}) and his own level comes back "
          f"({helper.value}) — writes {helper.writes}")
    check(owned.restored == ["tv-backlight"] and not owned.problems,
          "and the run can SAY it did, rather than a reader inferring it")

    crashed = _Helper(26)
    try:
        async with fb.owned([_Device("tv-backlight", crashed)]):
            raise RuntimeError("the run died mid-capture")
    except RuntimeError:
        pass
    check(crashed.value == 26,
          "THE FAILURE PATH: a run that dies mid-capture still hands his "
          "brightness back — leaving his lounge at full would be a worse "
          "bug than the one this fixes")

    if FAILURES:
        print(f"\nFAILED {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("\nFIXTURE BRIGHTNESS: MEASURED, WARNED BEFORE THE COST, OWNED FOR "
          "THE CAPTURE, GIVEN BACK")
    return 0


if __name__ == "__main__":
    status = 1
    try:
        status = asyncio.run(main())
    except Exception:                                          # noqa: BLE001
        import traceback
        traceback.print_exc()
    os._exit(status)
