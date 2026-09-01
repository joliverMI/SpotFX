"""THE FIXTURE'S OWN POWER SWITCH — read it before an overnight run, turn
on exactly what this run is about to drive, and put HIS state back.

HIS WORDS, on the night-run order: "Youll have to turn the lights on (if
necessary)". At 1am his fixtures may be powered off, and a capture run that
photographs a fixture nothing lit measures nothing at all — twice a night,
with a record that looks like a real map of a very dark room.

────────────────────────────────────────────────────────────────────────────
WHAT WAS ESTABLISHED, AND WHAT WAS NOT — read this before "simplifying" the
power-on away.
────────────────────────────────────────────────────────────────────────────

THE QUESTION: does a WLED that is powered OFF (`json/state` `on: false`)
display a realtime stream we push at it, or stay dark?

WHAT THIS FLEET HAS ACTUALLY OBSERVED, and it is one-directional evidence:
the standing dark recipe both captains adopted after the 2026-09-01
woke-up-lit morning is "RELEASE FIRST, THEN power the strips off — the off
only sticks once the stream is gone" (the seam document's own requirement,
formalised by the Admiral). That is the same claim from the other side: a
live realtime stream OVERRIDES an off state, so an off issued underneath one
does not hold. It says nothing about the order this run needs — off FIRST,
stream SECOND — and the two are not the same experiment. WLED's realtime
handling also carries a per-install "force max brightness" setting
(`fx/utils.py::WLED.force_max_brightness`) that changes how much of the
firmware's own dimming a stream is subject to, so the answer can differ
between two of his own fixtures.

WHAT COULD NOT BE ESTABLISHED FROM HERE: the answer for HIS fixtures, on his
firmware, at his settings. Establishing it means writing to a real strip in
his house, and this build is forbidden from driving his live room (and would
be wrong to, at 1am, to satisfy a curiosity). No test in this repo can
answer it, and inferring it from the release recipe would be exactly the
"plausible-looking answer" this codebase keeps refusing to produce.

SO THE RUN DOES NOT DEPEND ON THE ANSWER. It reads each fixture's power
state, turns ON only the ones it is about to drive that read off, CONFIRMS
the write took by reading it back, and restores what it found in a
`finally`. That act is:

  * correct if a powered-off WLED stays dark under a stream — it is the
    thing that makes the night's measurements exist at all;
  * harmless if a powered-off WLED displays the stream anyway — the fixture
    was about to be lit by our own stream regardless, so turning it on adds
    no light to his house that the run was not already going to put there,
    and the restore puts the switch back where it was;
  * and it REPORTS what it did per fixture either way, so the first real
    night's record settles the question as a by-product: a fixture that
    read `on: false` and produced a good footprint answers it one way, and
    the report says which fixtures were found off.

A NON-WLED FIXTURE IS NOT GUESSED AT. Hue's on/off lives per light in the
bridge and is reached by a different transport entirely; e131/ddp/udp have
no control channel; a dummy has nothing. Those are `not_applicable` and are
never given a fabricated `on: true` — the same rule
`spectra/services/fixture_brightness.py` holds for the same reason: a
made-up reading makes an unguarded fixture look guarded.

THE MODEL IS `fixture_brightness.owned`, deliberately. Same shape, same
guarantees, one layer over: read first, own for the body, restore in a
`finally` that runs on the failure path too, never let a restore failure
mask the body's own exception, and NAME a restore that could not be
delivered rather than swallowing it. The two are separate modules rather
than one because they are separate axes — a fixture can be on and dim, or
off and at full — and a run wants both, in that order (power, then
brightness: raising the brightness of a fixture that is off writes a value
nothing displays).

IT NEVER PERSISTS ANYTHING. His power state is held for the run's duration
and handed back; a crash between the two is covered by the report and by
the night record, not by a file — a stale stored power state landed at the
wrong moment is its own hazard, which is `fixture_brightness`' own ruling.
"""
from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

#: Only WLED exposes an on/off this code can read and set over its own API.
#: Named as a set rather than tested for by attribute, so a future driver
#: that gains one is an explicit decision — `fixture_brightness`' own rule.
CONTROLLABLE_TYPES = {"wled"}

STATE_READ = "read"
STATE_NOT_APPLICABLE = "not_applicable"
STATE_UNREADABLE = "unreadable"


@dataclass
class FixturePower:
    """One fixture's power reading. `on` is None when the fixture HAS no
    such switch this app can reach, or when it could not be read — the two
    are different and `state` says which, because "we could not ask" must
    never render as "it is on"."""
    device_id: str
    #: "read" | "not_applicable" | "unreadable"
    state: str
    on: Optional[bool] = None
    reason: str = ""

    @property
    def off(self) -> bool:
        return self.state == STATE_READ and self.on is False

    def as_dict(self) -> dict:
        return {"device_id": self.device_id, "state": self.state,
                "on": self.on, "off": self.off, "reason": self.reason}


def _wled(device):
    """The driver's own WLED helper, or None when this fixture has no power
    switch this app can speak to. Read off the LIVE driver object rather
    than the config, for `fixture_brightness._wled`'s own reason:
    `WLEDDevice.wled` is only built once the device has resolved its
    destination (fx/devices/wled.py), so its presence is the honest test of
    whether this fixture can be asked at all."""
    if str(getattr(device, "type", "") or "").lower() not in CONTROLLABLE_TYPES:
        return None
    return getattr(device, "wled", None)


async def read_one(device) -> FixturePower:
    """One fixture's power state. Never raises: a fixture that cannot be
    asked is a reported state, not a failed night."""
    device_id = str(getattr(device, "id", "") or "")
    helper = _wled(device)
    if helper is None:
        kind = str(getattr(device, "type", "") or "unknown")
        return FixturePower(
            device_id, STATE_NOT_APPLICABLE,
            reason=f"a {kind} fixture has no power switch this app can read "
                   f"or set over its own API")
    try:
        return FixturePower(device_id, STATE_READ,
                            on=bool(await helper.get_power_state()))
    except Exception as exc:                            # noqa: BLE001
        logger.info("night_power: could not read %s: %s", device_id, exc)
        return FixturePower(
            device_id, STATE_UNREADABLE,
            reason=f"{device_id} did not answer when asked whether it is on "
                   f"({type(exc).__name__}) — its power state is unknown, so "
                   f"this run left its switch alone")


async def read_all(devices) -> list[FixturePower]:
    return [await read_one(d) for d in devices]


@dataclass
class PowerResult:
    """What `owned()` did, per fixture, so the night record can SAY it
    rather than leaving a reader to infer it from a switch that moved."""
    #: device_id -> what happened to it: "turned_on" | "already_on" |
    #: "left_alone" | "unreadable" | "not_applicable" | "failed"
    actions: dict[str, str] = field(default_factory=dict)
    #: device_id -> the state found BEFORE this run touched anything
    found: dict[str, Optional[bool]] = field(default_factory=dict)
    turned_on: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"actions": dict(self.actions), "found": dict(self.found),
                "turned_on": list(self.turned_on),
                "restored": list(self.restored),
                "problems": list(self.problems), "note": self.note}

    @property
    def note(self) -> str:
        if not self.turned_on:
            return ("Every fixture this run drives was already on, so its "
                    "power switch was not touched.")
        return (f"Turned {', '.join(self.turned_on)} on for the night's "
                f"captures and put the switch back afterwards.")


@contextlib.asynccontextmanager
async def owned(devices, readings: Optional[list[FixturePower]] = None):
    """Turn ON every controllable fixture in `devices` that reads off, for
    the body of this block, and put each one's own switch back on the way
    out — INCLUDING when the body raised.

    Only a fixture that was actually READ and is actually OFF is touched: a
    fixture already on needs no write (and no restore that could fail), and
    one we could not read is left completely alone rather than being set to
    a state we would then have to guess how to undo.

    THE WRITE IS CONFIRMED BY READING IT BACK, not by the POST returning.
    This codebase's standing lesson — the Hue bridge 2xx's a write whether
    or not the bulb took it (`spectra/services/ambient.py`), a returning
    effects PUT is never evidence the effect took (`fx/VENDOR.md` #29) — and
    it matters more here than usual: an unconfirmed power-on produces a
    night of footprints of a fixture that was never lit, which reads as a
    real map of a room with a dead light in it.

    A restore that fails is NAMED in the result, never swallowed and never
    allowed to replace the body's own exception. A lounge left switched on
    at 3am is exactly the kind of thing that has to be said out loud."""
    result = PowerResult()
    if readings is None:
        readings = await read_all(devices)
    by_id = {str(getattr(d, "id", "") or ""): d for d in devices}
    taken: list[tuple[object, bool, str]] = []
    for r in readings:
        result.found[r.device_id] = r.on
        if r.state == STATE_NOT_APPLICABLE:
            result.actions[r.device_id] = STATE_NOT_APPLICABLE
            continue
        if r.state == STATE_UNREADABLE:
            result.actions[r.device_id] = STATE_UNREADABLE
            result.problems.append(r.reason)
            continue
        if not r.off:
            result.actions[r.device_id] = "already_on"
            continue
        device = by_id.get(r.device_id)
        helper = _wled(device) if device is not None else None
        if helper is None:
            result.actions[r.device_id] = "left_alone"
            continue
        try:
            await helper.set_power_state(True)
            # READ IT BACK. A fixture that accepted the write and stayed off
            # must not be counted as lit.
            if not bool(await helper.get_power_state()):
                raise RuntimeError("the fixture still reads off after being "
                                   "told to turn on")
        except Exception as exc:                        # noqa: BLE001
            logger.warning("night_power: could not turn %s on: %s",
                           r.device_id, exc)
            result.actions[r.device_id] = "failed"
            result.problems.append(
                f"{r.device_id} was found switched off and could NOT be "
                f"turned on for the night's captures ({type(exc).__name__}: "
                f"{exc}) — anything measured of it tonight is a photograph "
                f"of an unlit fixture, not a footprint")
            continue
        taken.append((helper, False, r.device_id))
        result.actions[r.device_id] = "turned_on"
        result.turned_on.append(r.device_id)
    try:
        yield result
    finally:
        # HIS switch goes back whatever happened in there. This is also the
        # "restore his chosen dark state" half of an abort: at night the
        # state he chose IS off, and putting it back is what hands the house
        # over untouched.
        for helper, original, device_id in taken:
            try:
                await helper.set_power_state(original)
                result.restored.append(device_id)
            except Exception as exc:                    # noqa: BLE001
                logger.exception("night_power: could not restore %s",
                                 device_id)
                result.problems.append(
                    f"{device_id} was switched on for the night's captures "
                    f"and could NOT be switched back off "
                    f"({type(exc).__name__}) — it is still on; turn it off "
                    f"at the fixture or from Home Assistant")
