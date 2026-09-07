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

     AND IT KEEPS TRYING, AND IT CONFIRMS BY READING THE FIXTURE BACK
     (2026-09-06). The restore shipped as ONE HTTP write at the vendored
     transport's blanket 0.5s, and on the sconce commissioning that was not
     enough: `tv-backlight` (.236) was taken to full and left there —
     "could NOT be put back to 84% (ValueError) — set it on the fixture
     itself" — until it was set by hand. The `(ValueError)` is a read
     timeout surfacing out of `fx.utils.WLED._wled_request`, and .236 is
     precisely the fixture `dark_fixture_watch` exists for: a controller
     that saturates under its own realtime stream. The RAISE succeeded
     because it happens before the stream has been hammering; the restore
     lands after ~35s of it. So a single shot at that controller was never
     a restore, it was a coin flip.

     Three things now hold, each an existing discipline arriving here:

       * THE BUDGET BINDS. `fx.utils.WLED_BRIGHTNESS_TIMEOUT_S` gives the
         brightness pair its own 3s, matching `dark_fixture_watch`'s —
         "an outer bound around this call never decides reachability,
         because the transport's default fires first" (live_host).
       * A 2xx IS NOT PROOF. Every write is CONFIRMED by reading `bri`
         back, the rule the Hue release path already follows (SPECTRA_SPEC
         §64) and `ambient._write_and_confirm` is built around; nothing in
         an accepted POST says the fixture carried it.
       * IT RETRIES, BOUNDED AND SPACED, inside a declared wall budget, so
         a dead controller cannot run a run's ending away with the clock.

     WHAT IS STILL SAID OUT LOUD, and the two sentences are NOT one. A
     write that was never accepted is "could NOT be put back … set it on
     the fixture itself" — his lounge is bright and he has to act. A write
     that WAS accepted but could never be confirmed is a different, softer
     sentence: sending him to a fixture by hand that probably did land is
     noise, and "we could not check" has never been allowed to render as
     "it is broken" in this codebase (`night_exit`'s DARK-vs-UNKNOWN,
     `witness`'s `witness_unavailable`, this module's own read/unreadable
     split).

     THE HONEST COST, stated rather than hidden: `fx.utils.WLED`'s methods
     are `async def` wrappers around BLOCKING `requests`, so this parks the
     event loop for as long as it runs. It is bounded by `RESTORE_BUDGET_S`
     (and `RAISE_BUDGET_S`) per fixture, it only spends that on a
     controller that is actually refusing, and it happens at the two ends
     of a run that has already held the room for minutes. A room handed
     back with his own brightness on it is worth those seconds; a
     background sweep would not be, which is why `dark_fixture_watch` runs
     its own reads off the loop and this does not.

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

import asyncio
import contextlib
import logging
import time
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

#: How many times one brightness change is attempted before it is reported.
#: Three, not one: the 2026-09-06 defect was a single refused write, and a
#: controller saturating under its own stream refuses in bursts rather than
#: permanently — `ambient`'s straggler retries are the same shape against
#: the same class of problem (a mesh that drops writes with no error).
DELIVER_ATTEMPTS = 3
#: Between attempts. Spaced rather than hammered, and short enough that a
#: fixture which simply needed a moment is back before the run ends —
#: `AMBIENT_WRITE_STAGGER_MS`'s own 300ms band, rounded up a little because
#: what is congested here is one ESP's HTTP server, not a zigbee mesh.
DELIVER_SPACING_S = 0.4
#: The WALL budget one fixture's restore may spend, whatever the attempts
#: would otherwise cost. A ceiling this code can state is the point: it is
#: what stops a dead controller from turning "hand the room back" into a
#: minute of a blocked event loop. It is checked BEFORE each attempt after
#: the first, never mid-request — an in-flight HTTP call is not something
#: this can abandon — so the true ceiling is this plus ONE attempt's own
#: transport time (2 x `fx.utils.WLED_BRIGHTNESS_TIMEOUT_S`, the write and
#: its read-back). Stated rather than rounded off, because a bound that is
#: only approximately true is not a bound.
RESTORE_BUDGET_S = 10.0
#: The raise's own, deliberately smaller. A raise that fails is ALREADY
#: handled honestly — that fixture's captures are named as measured at his
#: own level and not comparable — so it is not worth delaying the start of
#: every run by the restore's budget to chase it.
RAISE_BUDGET_S = 4.0


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
class Delivery:
    """What one brightness change actually achieved. THREE outcomes, not
    two, because "we could not check" is a different fact from "it did not
    take" and collapsing them either strands a bright fixture silently or
    sends him to a fixture that is already fine.

      landed       a read-back positively showed the value on the fixture
      unconfirmed  a write was ACCEPTED but no read-back ever confirmed it
      failed       no write was ever accepted
    """
    outcome: str
    attempts: int = 0
    #: The last value the fixture actually reported, when it could be asked
    #: at all. None means it never answered.
    last_read: Optional[int] = None
    error: str = ""

    @property
    def landed(self) -> bool:
        return self.outcome == "landed"


async def _deliver(helper, value: int, budget_s: float,
                   sleep=None, clock=None) -> Delivery:
    """Put `value` on the fixture and CONFIRM it by reading `bri` back,
    retrying a controller that refuses, inside `budget_s` of wall clock.

    A 2xx from an ESP web server says the request was accepted, never that
    the fixture carried it — the same rule the Hue paths already follow
    (`ambient._write_and_confirm`, `release_fade`'s own read-back). Here
    the read-back has a second job: it is the only thing that can tell a
    controller which took the write from one that dropped it while
    saturated by the capture stream this very run is driving into it.

    A read-back that cannot be MADE is never read as a failed write — the
    write may well have landed, so it is carried as `unconfirmed` and the
    next attempt (if the budget allows) re-writes anyway, which is
    harmless because setting a brightness is idempotent."""
    sleep = sleep or asyncio.sleep
    clock = clock or time.monotonic
    deadline = clock() + budget_s
    accepted = False
    last_read: Optional[int] = None
    error = ""
    attempts = 0

    for attempt in range(DELIVER_ATTEMPTS):
        if attempt and clock() >= deadline:
            # The budget is spent. Checked HERE rather than mid-request:
            # an HTTP call already in flight is not something this can
            # abandon, which is why the constant states the ceiling as the
            # budget plus one attempt.
            logger.info("fixture_brightness: budget spent after %d "
                        "attempt(s) at %s", attempts, value)
            break
        attempts = attempt + 1
        try:
            await helper.set_brightness(value)
            accepted = True
        except Exception as exc:                    # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            logger.info("fixture_brightness: write of %s not accepted "
                        "(attempt %d): %s", value, attempts, exc)
        else:
            try:
                last_read = int(await helper.get_brightness())
            except Exception as exc:                # noqa: BLE001
                # NOT evidence the write failed. See the docstring.
                last_read = None
                error = f"{type(exc).__name__}: {exc}"
                logger.info("fixture_brightness: could not read back after "
                            "writing %s (attempt %d): %s", value, attempts,
                            exc)
            else:
                if last_read == int(value):
                    return Delivery("landed", attempts, last_read)
                error = (f"the fixture reports {last_read}, not "
                         f"{int(value)}")
                logger.info("fixture_brightness: write of %s did not take "
                            "(attempt %d): %s", value, attempts, error)
        if attempt == DELIVER_ATTEMPTS - 1:
            break
        if clock() + DELIVER_SPACING_S >= deadline:
            break
        await sleep(DELIVER_SPACING_S)

    if accepted and last_read is None:
        # It was taken, and the fixture then would not say. The softer
        # sentence — see the module docstring.
        return Delivery("unconfirmed", attempts, None, error)
    return Delivery("failed", attempts, last_read, error)


@dataclass
class OwnResult:
    """What `owned()` did, so a run can say it rather than a reader having to
    infer it from a brightness that moved."""
    raised: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def note(self) -> str:
        """The sentence a run puts in its NOTES. Every caller reads it after
        the block has exited, so it reports what actually happened rather
        than what was intended: claiming his brightness went back while a
        `problems` entry two lines down says it did not is exactly the kind
        of confident wrong answer this module was extended to stop
        (2026-09-06)."""
        if not self.raised:
            return ""
        head = (f"Turned {', '.join(self.raised)} up to full for the "
                f"capture")
        if not self.restored:
            # Nothing was confirmed back. The problems carry the detail and
            # the instruction; this must not contradict them.
            return f"{head} — see the problems for what came back."
        back = ", ".join(self.restored)
        if len(self.restored) == len(self.raised):
            return f"{head} and put your own brightness back afterwards."
        return (f"{head}. Your own brightness is confirmed back on {back} — "
                f"see the problems for the rest.")


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
        got = await _deliver(helper, FULL, RAISE_BUDGET_S)
        if got.outcome == "failed":
            logger.warning("fixture_brightness: could not raise %s: %s",
                           r.device_id, got.error)
            result.problems.append(
                f"{r.device_id} could not be turned up for the capture "
                f"({got.error}) — its part of this map is measured "
                f"at {r.percent}% brightness and is not comparable with the "
                f"rest")
            continue
        # An UNCONFIRMED raise is still owned: the write was accepted, so
        # the fixture is very likely at full and MUST be put back. Leaving
        # it out of `taken` to be tidy is exactly how a lounge gets left
        # bright with nothing recorded that it was ever touched.
        taken.append((helper, r.value, r.device_id))
        result.raised.append(f"{r.device_id} ({r.percent}% -> 100%)")
        if got.outcome == "unconfirmed":
            result.problems.append(
                f"{r.device_id} took the write to full for the capture but "
                f"would not then say how bright it is ({got.error}) — if it "
                f"was still at {r.percent}%, its part of this map is not "
                f"comparable with the rest. Your own level is put back "
                f"either way.")
    try:
        yield result
    finally:
        # HIS level goes back whatever happened in there.
        for helper, original, device_id in taken:
            percent = round(original * 100 / FULL)
            try:
                got = await _deliver(helper, original, RESTORE_BUDGET_S)
            except Exception as exc:                    # noqa: BLE001
                # _deliver swallows the transport's own failures; anything
                # reaching here is unexpected, and a restore must still
                # never replace the body's exception.
                logger.exception("fixture_brightness: restoring %s raised",
                                 device_id)
                got = Delivery("failed", 0, None, f"{type(exc).__name__}: {exc}")
            if got.landed:
                result.restored.append(device_id)
                continue
            if got.outcome == "unconfirmed":
                # It was ACCEPTED. Telling him to go and set a fixture that
                # probably already carries his level is noise — but the
                # unchecked half must still reach him.
                logger.warning("fixture_brightness: restored %s to %s but "
                               "could not confirm it: %s", device_id,
                               original, got.error)
                result.problems.append(
                    f"{device_id} was put back to {percent}% after the "
                    f"capture, but would not then confirm it ({got.error}) — "
                    f"it is most likely fine; check it if it looks bright")
                continue
            logger.error("fixture_brightness: could not restore %s to %s "
                         "after %d attempt(s): %s", device_id, original,
                         got.attempts, got.error)
            reads = ("" if got.last_read is None else
                     f", it is reporting {round(got.last_read * 100 / FULL)}%")
            result.problems.append(
                f"{device_id} was turned up to full for the capture and "
                f"could NOT be put back to {percent}% "
                f"({got.error} after {got.attempts} attempts{reads}) — set "
                f"it on the fixture itself")
