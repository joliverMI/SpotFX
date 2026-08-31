"""THE FIXTURE'S OWN FIRMWARE BRIGHTNESS — read it before a mapping run,
take it to full for the capture, and put HIS level back afterwards.

THE LIVE FINDING (2026-08-31, the captain's verdict on his first real map):
his fixture was at TEN PERCENT firmware brightness for the whole run. Every
footprint in the stored map is therefore ~10x dim — five blocks at 0.1 or
less, which is the threshold tail, and blocks plainly in shot reading a
fraction of what the same room's whole-device map measured. The instrument
was measuring his dimmer, not his room, and NOTHING in the map said so.

WHY THIS IS A REAL AXIS AND NOT A KNOB WE INVENTED: a footprint is relative
luminance in the camera's own scale, comparable only across captures taken
under the same conditions (spectra/models/room_map.py). Exposure lock is
already refused-if-absent for exactly that reason. Firmware brightness is
the SAME class of condition one layer down — it scales everything the
fixture emits, including the realtime stream a capture writes — and it was
simply unguarded. A map taken at 10% is not a dim map, it is an
UNCOMPARABLE one: nothing downstream can tell it from a room whose fixtures
genuinely land a tenth as much light.

TWO ACTS, deliberately separate:

  1. READ IT AT PLAN TIME and warn LOUDLY when it is low — BEFORE the cost.
     A plan is what he reads before pressing, and a warning that arrives
     after a four-minute dark-room run has arrived too late to act on. This
     is the same discipline `mapping_refusals.one_piece_warning` already
     follows: a warning about what a map CAN'T do belongs before the dark
     room, not after it.

  2. OWN IT FOR THE CAPTURE and give it back. Take the fixture to full for
     the seconds it is being photographed, then restore HIS level — the
     same own-the-flag pattern `room_mapping.activate_for_capture` already
     uses for a substitute virtual's `active` flag, and for the same
     reason: the hold's snapshot covers the EFFECT on a virtual, and cannot
     restore a firmware setting it never observed.

     THE RESTORE RUNS ON THE FAILURE PATH TOO. A run that dies mid-capture
     leaving his lounge at full brightness would be a worse bug than the one
     this fixes, so `owned()` is a context manager whose restore is in a
     `finally` and which never lets a restore failure mask the original
     error. A restore that genuinely could not be delivered is REPORTED by
     name (`problems`), never swallowed — the fleet's standing lesson.

WHAT IT DOES NOT DO, stated rather than guessed at:

  * A NON-WLED FIXTURE HAS NO SUCH SETTING TO READ. Hue's brightness lives
    per-light in the bridge, e131/ddp/udp have no control channel at all,
    and a dummy has nothing. Those are reported as "not applicable" and are
    never given a fabricated 255 — a made-up full reading would make an
    unguarded fixture look guarded, which is the exact failure this module
    exists to end.
  * It never PERSISTS anything. His level is held for the run's duration and
    handed back; a crash between the two is covered by the report, not by a
    file, because a stale stored brightness landed at the wrong moment is
    its own hazard.
"""
from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

#: WLED's master brightness is 0-255. Full is what a capture wants: the
#: footprint should measure the fixture's real reach, and any clipping that
#: causes is already REPORTED (capture.saturated_fraction) rather than
#: avoided by measuring a dimmer fixture than he owns — the same reasoning
#: `room_mapping.LIT_BRIGHTNESS` is set to 1.0 for.
FULL = 255
#: Below this, a run is measuring the dimmer more than the room, and the
#: plan says so before he presses. 90% of full: high enough that his real
#: 10% is nowhere near it, low enough that a fixture a few percent off full
#: is not nagged about. A WARNING, never a refusal — the map is still real
#: and, since the capture now takes the fixture to full anyway, still
#: comparable; the warning is what tells him the previous maps were not.
LOW = 230

#: Only WLED exposes a master brightness this code can read and set. Named
#: as a set rather than tested for by attribute, so a future driver that
#: gains one is an explicit decision.
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
    brightness to speak of. Read off the live driver object rather than the
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
                   f"read or set")
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
    named = ", ".join(f"{r.device_id} at {r.percent}%" for r in low)
    return (f"TURNED DOWN: {named}. A fixture's own brightness scales "
            f"everything it emits, so a map measured like this measures the "
            f"dimmer, not the room — this is what made the first map's "
            f"weights come out about ten times too small. This run will take "
            f"{'it' if len(low) == 1 else 'them'} to full for the seconds "
            f"each piece is photographed and put your own level back "
            f"afterwards, so you do not have to.")


@dataclass
class OwnResult:
    """What `owned()` did, so a run can say it rather than a reader having to
    infer it from a brightness that moved."""
    raised: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def note(self) -> str:
        if not self.raised:
            return ""
        return (f"Turned {', '.join(self.raised)} up to full for the capture "
                f"and put your own brightness back afterwards.")


@contextlib.asynccontextmanager
async def owned(devices, readings: Optional[list[FixtureBrightness]] = None):
    """Take every controllable fixture to full for the body of this block,
    and put each one's own level back on the way out — INCLUDING when the
    body raised.

    Only a fixture that was actually READ and is actually BELOW full is
    touched: a fixture already at full needs no write (and no restore that
    could fail), and one we could not read is left completely alone rather
    than being set to a value we would then have to guess how to undo.

    A restore that fails is NAMED in the result, never swallowed and never
    allowed to replace the body's own exception — the run's real failure is
    the more important one, and a lounge left bright is exactly the kind of
    thing that must be said out loud rather than logged."""
    result = OwnResult()
    if readings is None:
        readings = await read_all(devices)
    by_id = {str(getattr(d, "id", "") or ""): d for d in devices}
    taken: list[tuple[object, int, str]] = []
    for r in readings:
        if r.state != "read" or r.value is None or r.value >= FULL:
            continue
        device = by_id.get(r.device_id)
        helper = _wled(device) if device is not None else None
        if helper is None:
            continue
        try:
            await helper.set_brightness(FULL)
        except Exception as exc:                        # noqa: BLE001
            logger.warning("fixture_brightness: could not raise %s: %s",
                           r.device_id, exc)
            result.problems.append(
                f"{r.device_id} could not be turned up for the capture "
                f"({type(exc).__name__}) — its part of this map is measured "
                f"at {r.percent}% brightness and is not comparable with the "
                f"rest")
            continue
        taken.append((helper, r.value, r.device_id))
        result.raised.append(f"{r.device_id} ({r.percent}% -> 100%)")
    try:
        yield result
    finally:
        # HIS level goes back whatever happened in there.
        for helper, original, device_id in taken:
            try:
                await helper.set_brightness(original)
                result.restored.append(device_id)
            except Exception as exc:                    # noqa: BLE001
                logger.exception("fixture_brightness: could not restore %s",
                                 device_id)
                result.problems.append(
                    f"{device_id} was turned up to full for the capture and "
                    f"could NOT be put back to {round(original * 100 / FULL)}% "
                    f"({type(exc).__name__}) — set it on the fixture itself")
