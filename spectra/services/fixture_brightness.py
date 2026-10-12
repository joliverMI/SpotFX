"""THE FIXTURE'S OWN FIRMWARE BRIGHTNESS — read it before a capture run,
warn when it is low, and MEASURE AS IS. Never write it.

THE RULE (2026-10-12, the Admiral, data/wled-bri-audit/report.md, his
D1a): "Home assistant can set the WLED global brightness of any of these
lights, and spectra doesn't touch that value." Until that ruling this
module took every turned-down fixture to full for a capture and put his
level back afterwards (2026-08-31, hardened 2026-09-06). That was a
Spectra write to a value that is not Spectra's, so it is gone: a map,
commissioning pass, lever self-test or pose check now READS each fixture's
master brightness, says loudly when it is below full, and measures the room
exactly as it is. `fx/utils.py::WLED._wled_request` refuses any json/state
body carrying `bri` (VENDOR #78), so no capture path can quietly grow the
write back.

WHY THE READING STILL MATTERS (the 2026-08-31 finding, unchanged): his
first real map was taken with the fixture at TEN PERCENT firmware
brightness and every footprint came out ~10x dim, with nothing in the map
saying so. A footprint is relative luminance in the camera's own scale,
comparable only across captures taken under the same conditions
(spectra/models/room_map.py), and firmware brightness scales everything a
fixture emits, including the realtime stream a capture writes. So:

  1. READ IT AT PLAN TIME and warn LOUDLY when it is low — BEFORE the cost,
     naming what to do: raise it to 100% in Home Assistant (or on the
     WLED's own page) before pressing. `mapping_refusals.one_piece_warning`'s
     own discipline: a warning about what a map can't do belongs before the
     dark room, not after it.
  2. MEASURE AS IS, AND SAY SO IN THE RUN'S OWN NOTES (`measured_as_is`):
     which fixtures were captured below full and at what level, so a map
     taken that way is never mistaken for one taken at full.
  3. A NIGHT RUN RECORDS A REQUEST rather than writing (night_run's
     `brightness` block, read by the morning read): "raise X to 100% in
     Home Assistant before the next night run".

WHAT IT DOES NOT DO, stated rather than guessed at:

  * A NON-WLED FIXTURE HAS NO SUCH SETTING TO READ. Hue's brightness lives
    per-light in the bridge, e131/ddp/udp have no control channel at all,
    and a dummy has nothing. Those are reported as "not applicable" and are
    never given a fabricated 255 — a made-up full reading would make an
    unguarded fixture look guarded.
  * An UNREADABLE fixture is reported as unknown, never as fine.
"""
from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

#: WLED's master brightness is 0-255. Full is what a comparable capture
#: wants: the footprint should measure the fixture's real reach.
FULL = 255
#: Below this, a run is measuring the dimmer more than the room, and the
#: plan says so before he presses. 90% of full: high enough that his real
#: 10% is nowhere near it, low enough that a fixture a few percent off full
#: is not nagged about. A WARNING, never a refusal — the map is still real,
#: just not comparable with one taken at full, and the run says which.
LOW = 230

#: Only WLED exposes a master brightness this code can read. Named as a set
#: rather than tested for by attribute, so a future driver that gains one
#: is an explicit decision.
CONTROLLABLE_TYPES = {"wled"}


@dataclass
class FixtureBrightness:
    """One fixture's reading. `value` is None when the fixture HAS no such
    setting or it could not be read — the two are different and `state`
    says which, because "we could not ask" must never render as "it is
    fine"."""
    device_id: str
    #: "read" | "not_applicable" | "unreadable"
    state: str
    value: Optional[int] = None
    reason: str = ""

    @property
    def low(self) -> bool:
        return self.state == "read" and self.value is not None and self.value < LOW

    @property
    def percent(self) -> int:
        return round((self.value or 0) * 100 / FULL)

    def as_dict(self) -> dict:
        return {"device_id": self.device_id, "state": self.state,
                "value": self.value, "percent": self.percent if self.value
                is not None else None, "low": self.low, "reason": self.reason}


def _wled(device):
    """The driver's own WLED helper, or None when this device has no master
    brightness to read. Read off the live driver object rather than the
    config: `WLEDDevice.wled` is only built once the device has actually
    resolved its destination (fx/devices/wled.py), so its presence is the
    honest test of whether this fixture can be asked at all."""
    if str(getattr(device, "type", "") or "").lower() not in CONTROLLABLE_TYPES:
        return None
    return getattr(device, "wled", None)


async def read_one(device) -> FixtureBrightness:
    """One fixture's master brightness. Never raises: a fixture that cannot
    be asked is a reported state, not a failed run — the plan route this
    feeds must not 500 because one lamp is asleep."""
    device_id = str(getattr(device, "id", "") or "")
    helper = _wled(device)
    if helper is None:
        kind = str(getattr(device, "type", "") or "unknown")
        return FixtureBrightness(
            device_id, "not_applicable",
            reason=f"a {kind} fixture has no master brightness this app can "
                   f"read")
    try:
        return FixtureBrightness(device_id, "read", int(await helper.get_brightness()))
    except Exception as exc:                            # noqa: BLE001
        logger.info("fixture_brightness: could not read %s: %s", device_id, exc)
        return FixtureBrightness(
            device_id, "unreadable",
            reason=f"{device_id} did not answer when asked how bright it is "
                   f"({type(exc).__name__}) — its brightness is unknown, so "
                   f"this run cannot tell whether it is turned down")


async def read_all(devices) -> list[FixtureBrightness]:
    return [await read_one(d) for d in devices]


def warning_for(readings: list[FixtureBrightness]) -> str:
    """The sentence, said LOUDLY and BEFORE the cost, or "" when there is
    nothing to say. One wording, here, so the plan and the run cannot
    describe his room differently — `mapping_refusals`' own rule."""
    low = [r for r in readings if r.low]
    if not low:
        return ""
    one = len(low) == 1
    named = ", ".join(f"{r.device_id} at {r.percent}%" for r in low)
    return (f"TURNED DOWN: {named}. A fixture's own brightness scales "
            f"everything it emits, so a map measured like this measures the "
            f"dimmer, not the room — this is what made the first map's "
            f"weights come out about ten times too small. Spectra does not "
            f"change a WLED's brightness (it is Home Assistant's): raise "
            f"{'it' if one else 'them'} to 100% in Home Assistant, or on the "
            f"WLED's own page, before pressing — otherwise this run measures "
            f"{'it as it is' if one else 'them as they are'}.")


def raise_request(readings: list[FixtureBrightness]) -> str:
    """The NIGHT RUN's version: no one is there to press anything, so the
    request is recorded for the morning rather than acted on."""
    low = [r for r in readings if r.low]
    if not low:
        return ""
    named = ", ".join(f"{r.device_id} (it was at {r.percent}%)" for r in low)
    return (f"Raise {named} to 100% in Home Assistant before the next night "
            f"run — Spectra never changes a WLED's brightness, so last night "
            f"measured {'it' if len(low) == 1 else 'them'} turned down and "
            f"{'its' if len(low) == 1 else 'their'} part of the map is not "
            f"comparable with one taken at full.")


@dataclass
class AsIsResult:
    """What `measured_as_is()` saw, so a run can SAY it in its notes."""
    dim: list[FixtureBrightness] = field(default_factory=list)

    @property
    def note(self) -> str:
        if not self.dim:
            return ""
        named = ", ".join(f"{r.device_id} at {r.percent}%" for r in self.dim)
        one = len(self.dim) == 1
        return (f"Measured {named} as {'it was' if one else 'they were'} — "
                f"a WLED's brightness is Home Assistant's and this run did "
                f"not change it, so {'its' if one else 'their'} part of "
                f"this capture is not comparable with one taken at full. "
                f"Raise {'it' if one else 'them'} to 100% in Home Assistant "
                f"before the next run for a comparable map.")


@contextlib.asynccontextmanager
async def measured_as_is(devices, readings: Optional[list[FixtureBrightness]] = None):
    """Frame a capture with the fixtures' own brightness, MEASURED AS IS.

    Writes nothing, on the way in or out — the read-only successor to the
    retired `owned()` (which took every dim fixture to full and put his
    level back). It reads the fixtures when the caller has no readings yet,
    and yields an `AsIsResult` naming every fixture captured below full, for
    the run's notes."""
    if readings is None:
        readings = await read_all(devices)
    yield AsIsResult(dim=[r for r in readings if r.low])
