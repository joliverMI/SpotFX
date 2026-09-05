"""THE LEVER-IS-REAL SELF-TEST — "the setting is not the light", as a boot
check rather than a lesson somebody has to remember.

WHY IT EXISTS, and it is one evening's worth of evidence. On 2026-09-01 a
calibration session commanded three integration times through the browser
path — 10 ms, 60 ms and 200 ms, a factor of twenty end to end. Every one of
them was accepted. Every read-back agreed. And the measured light did not
move: footprint weights of 0.0, 0.0014 and 0.0051 against the
`light_field.UNSEEN_WEIGHT` of 1.0 an emitter must clear to count as seen
at all, while the camera's own converged regime wandered from 0.23 to 0.01
between two runs of the same thing. Nothing in the instrument could tell
the difference between that and a dark room, because everything in the
instrument was asking the DRIVER.

THE TWO CLAIMS, and why one cannot stand in for the other:

  * THE READ-BACK (`spectra/capture_client/camera.py`) proves the driver
    HOLDS the value. It is instant, it costs nothing, and it catches a
    control the camera never took. It cannot catch a control the camera
    took and ignored.
  * THIS (`run_selftest`) proves the SENSOR OBEYS it. It drives a known
    emitter — the run's own target machinery, nothing new acquired —
    commands two integration times a known factor apart, and watches the
    measured light. It costs about fifteen seconds of an already-dark room
    and it is the only thing in this codebase that can make the second
    claim.

Both run. Neither is a substitute for the other, and a run refused by
either says which.

THE MEASUREMENT IS THE MAP'S OWN, deliberately and completely:
`room_mapping._map_one` against a THROWAWAY room with no `save_room`, so
the number this judges is the same `lit - dark` footprint weight a real
capture produces and not a second idea of "how much light". That is
`exposure_test.py`'s own precedent, for the same reason: a second
implementation of "measure one emitter" would be a second thing to keep
true.

THREE CAPTURES, in this order, and the order is the design:

    A   the DIM regime   (commanded integration time E)
    B   the BRIGHT one   (commanded E x COMMANDED_FACTOR)
    B'  B again          (the SAME command, a second time)

A -> B answers "does more commanded time put more light in the frame".
B -> B' answers "does this camera hold still when nothing was asked to
change" — the invisible re-clamping his own eyes reported as "I can see
well, then it gets really dark". The repeat is taken at the BRIGHT regime
on purpose: a ratio between two near-noise readings is not a measurement of
anything.

THE TOLERANCES, and why each is where it is rather than tuned to pass:

  * SIGNAL: the bright regime must clear `light_field.UNSEEN_WEIGHT`, the
    same floor a real emitter must clear to be recorded as seen at all.
    Below it the readings are noise and no ratio between them means
    anything — which is precisely tonight's shape, and precisely why it is
    checked FIRST.
  * RESPONSE: the measured ratio must reach 1 + (F-1) x
    MIN_RESPONSE_FRACTION — a QUARTER of the commanded change. A sensor in
    its linear regime returns about F; ambient pedestal, black level and the
    lamp's own variation all pull that down, and clipping pulls it down
    hard. A quarter is loose enough that none of those can fail an honest
    camera and far tighter than the ~1.0 a disconnected lever produces.
  * REPEAT: within REPEAT_BAND either way. The map's own tie band for two
    readings of one regime is 10% (`exposure_test.TIE_FRACTION`), so 50% is
    five times looser than the instrument's known wobble — it cannot fire on
    ordinary noise, and the 23x wander that prompted this could not hide
    under it.
  * SATURATION IS EVIDENCE, NOT A FAILURE. A bright regime that CLIPS has
    demonstrated the lever works — you cannot clip a sensor by leaving its
    exposure alone — so a saturated B that measured more than A passes with
    a note rather than failing the ratio bar it can no longer meet.

WHAT IT NEVER DOES. It never writes a footprint (throwaway room, no
`save_room`). It never leaves the camera where it put it (the previous
request is restored in a `finally`). It never acquires anything: it drives
the emitter inside the SAME held room every capture uses, through the same
program, and if the room is not ours it refuses on the same ownership
sentence every other run does.

AND IT IS NOT A WALL. A verdict of `unprovable` or `unproven` — a camera
whose range cannot span the factor, frames that never arrived, an
ownership state — is CARRIED and never refuses: "we could not check" is not
"we checked and it is broken", the same distinction `night_exit` draws
between DARK and UNKNOWN and `witness` between contaminated and
witness_unavailable. Refusing on a check that could not be made would
invent a fault. The four verdicts in `mapping_refusals.LEVER_REFUSING` are
the ones that stop a run, and each of them is a MEASUREMENT.

WHERE IT RUNS. `spectra/services/capture_runs.py` — the one seam every
capture run passes through — calls `ensure()` before a map, a commissioning
pass or an exposure comparison whose session is the NATIVE client. The
verdict is cached ON THE SESSION OBJECT, which is what makes "at session
establishment, and after any reconnect" structural rather than remembered:
`mapping_session.open_session` builds a NEW session per WebSocket, so a
reconnect cannot inherit a verdict, and the cache key carries the pose id
as well, so a camera reopen inside one connection cannot either.

BROWSER SESSIONS ARE UNTOUCHED by all of this — no demotion, no new
refusal, nothing asked of a page that has no way to answer it. That
boundary is a later, separate build and he is owed the sentence when it
comes.

ONE UNPRICED COST, STATED RATHER THAN HIDDEN: a night run pays for this
ONCE per session (the cache above), about fifteen seconds of dark room
before its first item, and `night_run.price_items` does not include it in
the estimate it checks against the 05:30 planned end. Fifteen seconds
against a multi-hour window is not worth a second pricing path today; if a
night ever runs right up to that bound, this is the fifteen seconds nobody
counted.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from spectra.models.room_map import RoomMap
from spectra.services import (capture_settings, capture_source, light_field,
                              mapping_refusals)
from spectra.services import emitters as emitters_mod
from spectra.services import room_mapping

logger = logging.getLogger(__name__)

#: What the native capture client calls itself in `hello`. Re-exported from
#: `capture_source`, which owns the client-kind question outright since the
#: browser's demotion — this name stays because the callers and the proofs
#: that read it here read it here, not because there are two of them.
NATIVE_CLIENT = capture_source.NATIVE_CLIENT

#: HOW MUCH MORE TIME THE SECOND REGIME IS COMMANDED. Four is comfortably
#: past anything noise can fake and comfortably short of driving an
#: ordinary indoor exposure into the clip.
COMMANDED_FACTOR = 4.0
#: THE SMALLEST FACTOR THIS TEST CAN MAKE A CLAIM ON. A camera whose
#: declared exposure range cannot span this reports `unprovable` — see the
#: docstring on why that is carried and never refused.
MIN_PROVABLE_FACTOR = 2.0
#: The fraction of the commanded change the measured light must actually
#: show. See the docstring: a quarter.
MIN_RESPONSE_FRACTION = 0.25
#: The repeat band, either way, for two captures of the SAME command.
REPEAT_BAND = 1.5
#: A bright regime clipping this fraction of its frames has PROVED the
#: lever by itself. Two frames of a handful is enough to say so.
SATURATION_EVIDENCE = 0.02
#: The bright regime's commanded integration time when nothing else says
#: what to use: 1/50 s, a plainly ordinary indoor exposure.
DEFAULT_BRIGHT_EXPOSURE = 200


#: Is this the unattended capture client rather than a browser page? THE
#: ONE IMPLEMENTATION IS `capture_source.is_native` and this is that
#: function, not a copy of it: since the browser's demotion the same answer
#: decides whether this self-test is asked for at all AND whether a
#: calibration-grade run may go, and two functions agreeing today is not the
#: same as one function.
is_native = capture_source.is_native


def choose_regimes(lock: dict, requested: Optional[int] = None
                   ) -> tuple[Optional[int], Optional[int], str]:
    """(dim, bright, why-not) — two commanded integration times a known
    factor apart, inside whatever range this camera declares.

    THE BRIGHT ONE IS THE RUN'S OWN, when the run named one: proving the
    lever at the regime the run is about to use is a stronger statement
    than proving it somewhere else and assuming. Failing that it is the
    camera's currently read-back exposure, and failing that a plainly
    ordinary indoor one.

    A camera whose declared range cannot span `MIN_PROVABLE_FACTOR` gets
    (None, None, reason) and the caller reports `unprovable` — this
    function never invents a factor it cannot ask for."""
    rng = lock.get("exposure_time_range") or []
    lo = float(rng[0]) if len(rng) == 2 else float(capture_settings.MIN_EXPOSURE_TIME)
    hi = float(rng[1]) if len(rng) == 2 else float(capture_settings.MAX_EXPOSURE_TIME)
    if hi <= lo:
        return None, None, (f"this camera declares an exposure range of "
                            f"{lo:g}..{hi:g}, which spans nothing")
    if hi / max(lo, 1.0) < MIN_PROVABLE_FACTOR:
        return None, None, (
            f"this camera's declared exposure range ({lo:g}..{hi:g}) spans "
            f"less than the {MIN_PROVABLE_FACTOR:g}x this test needs to make "
            f"a claim, so the lever cannot be proven either way here")
    want = requested
    if want is None:
        want = lock.get("exposure_time")
    try:
        bright = float(want) if want is not None else float(DEFAULT_BRIGHT_EXPOSURE)
    except (TypeError, ValueError):
        bright = float(DEFAULT_BRIGHT_EXPOSURE)
    bright = max(lo, min(hi, bright))
    dim = max(lo, bright / COMMANDED_FACTOR)
    if bright / max(dim, 1e-9) < MIN_PROVABLE_FACTOR:
        # The bright end sat on the floor. Push it up instead of giving up:
        # the range is wide enough (checked above), so a factor exists.
        bright = min(hi, dim * COMMANDED_FACTOR)
    if bright / max(dim, 1e-9) < MIN_PROVABLE_FACTOR:
        return None, None, (
            f"no two integration times {MIN_PROVABLE_FACTOR:g}x apart fit "
            f"inside this camera's declared range ({lo:g}..{hi:g})")
    return int(round(dim)), int(round(bright)), ""


@dataclass
class Reading:
    """ONE COMMANDED REGIME, and what the room actually measured in it."""
    label: str
    exposure_time: Optional[int] = None
    ok: bool = False
    reason: str = ""
    weight: float = 0.0
    saturated_fraction: float = 0.0
    dark_frames: int = 0
    lit_frames: int = 0
    #: How long this reading waited after commanding its integration time
    #: before it measured anything — `capture_settings.regime_settle_s`.
    #: Recorded because a reading taken too soon is indistinguishable from
    #: a broken lever, and the number is the difference.
    regime_settle_s: float = 0.0
    lock: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"label": self.label, "exposure_time": self.exposure_time,
                "ok": self.ok, "reason": self.reason,
                "weight": round(self.weight, 4),
                "saturated_fraction": self.saturated_fraction,
                "dark_frames": self.dark_frames, "lit_frames": self.lit_frames,
                "regime_settle_s": self.regime_settle_s,
                "lock": self.lock}


@dataclass
class Verdict:
    """WHAT THE SELF-TEST FOUND, in both registers: a word a program
    branches on and a sentence a person reads."""
    verdict: str = mapping_refusals.LEVER_UNPROVEN
    reason: str = ""
    #: The fingerprint this verdict was earned under — session, pose, and
    #: what the run asked the camera for. A cached verdict is only ever
    #: reused for the identical fingerprint, so a reconnect, a camera reopen
    #: or a different ask re-earns it rather than inheriting it. See
    #: `fingerprint` for why it is NOT derived from the read-back.
    fingerprint: str = ""
    session_id: str = ""
    pose_id: str = ""
    emitter_id: str = ""
    emitter_label: str = ""
    commanded_factor: float = 0.0
    response_ratio: Optional[float] = None
    repeat_ratio: Optional[float] = None
    signal_floor: float = light_field.UNSEEN_WEIGHT
    #: Did the client holding this camera promise that a frame it sent is
    #: the newest one it had? True / False / None — `capture_source.
    #: serves_fresh_frames` owns the three answers. Carried onto the
    #: refusal sentence, which names a stale transport as the FIRST thing
    #: to check when the readings disagree and this is False.
    fresh_frames: Optional[bool] = None
    readings: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    seconds: float = 0.0
    at: float = field(default_factory=time.time)

    @property
    def proven(self) -> bool:
        """The levers were measured and they are real."""
        return self.verdict == mapping_refusals.LEVER_OK

    @property
    def refuses(self) -> bool:
        """Must a calibration-grade run stop on this? Only a MEASUREMENT
        says yes — see the module docstring on why `unprovable`/`unproven`
        never do."""
        return self.verdict in mapping_refusals.LEVER_REFUSING

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "reason": self.reason,
                "proven": self.proven, "refuses": self.refuses,
                "fingerprint": self.fingerprint,
                "session_id": self.session_id, "pose_id": self.pose_id,
                "emitter_id": self.emitter_id,
                "emitter_label": self.emitter_label,
                "commanded_factor": self.commanded_factor,
                "response_ratio": self.response_ratio,
                "repeat_ratio": self.repeat_ratio,
                "signal_floor": self.signal_floor,
                "fresh_frames": self.fresh_frames,
                "min_response_ratio": min_response_ratio(),
                "repeat_band": REPEAT_BAND,
                "readings": [r.as_dict() for r in self.readings],
                "problems": list(self.problems), "notes": list(self.notes),
                "seconds": round(self.seconds, 2), "at": self.at}


def min_response_ratio() -> float:
    """The measured ratio a connected lever must reach for a commanded
    factor of `COMMANDED_FACTOR` — a quarter of the commanded change."""
    return round(1.0 + (COMMANDED_FACTOR - 1.0) * MIN_RESPONSE_FRACTION, 4)


def fingerprint(session: Any, requested: Optional[int] = None) -> str:
    """WHAT A CACHED VERDICT IS ONLY EVER REUSED FOR: this session, this
    pose, and what the run asked the camera for.

    DELIBERATELY NOT THE RESOLVED REGIMES, and this is not a detail: the
    test COMMANDS an integration time, and a real V4L2 device keeps the last
    value it was given — so a fingerprint derived from the camera's current
    read-back would be different the moment the first self-test finished,
    and every later item in a queue would pay for another three captures of
    his dark room to re-learn the same fact. What identifies the context is
    the session, the pose and the ASK; the regimes are computed from it."""
    return (f"{getattr(session, 'id', '')}:{getattr(session, 'pose_id', '')}"
            f":{requested}")


def judge(readings: list, floor: float = light_field.UNSEEN_WEIGHT
          ) -> tuple[str, Optional[float], Optional[float], list]:
    """THE WHOLE DECISION, as a pure function of three readings.

    Pure so the word and the numbers can never disagree, and so the red,
    green and drift cases can be proven without a room. Returns
    (verdict, response_ratio, repeat_ratio, notes).

    ORDER IS THE ARGUMENT. Signal is checked before response because a
    ratio between two noise readings is not evidence of anything — tonight's
    own numbers are proportional to two significant figures and mean
    nothing. Response is checked before repeat because a lever that never
    moved has nothing to hold still."""
    notes: list[str] = []
    if len(readings) < 2 or not all(r.ok for r in readings[:2]):
        return mapping_refusals.LEVER_UNPROVEN, None, None, notes
    dim, bright = readings[0], readings[1]
    if bright.weight < floor:
        return mapping_refusals.LEVER_NO_SIGNAL, None, None, notes

    saturated = bright.saturated_fraction >= SATURATION_EVIDENCE
    if dim.weight < floor:
        # Nothing to something. That IS a response, and there is no honest
        # ratio to quote for it: a denominator under the floor is noise.
        notes.append(
            f"the dim regime measured {dim.weight:.3f}, under the {floor:g} "
            f"floor, and the bright one measured {bright.weight:.3f} — light "
            f"appeared where there was none, which is a response whatever "
            f"the ratio between them would have said")
        response = None
    else:
        response = round(bright.weight / dim.weight, 4)
        if response < min_response_ratio():
            if saturated and bright.weight > dim.weight:
                # A clipped bright regime cannot reach the ratio bar and has
                # already proved the point: you cannot clip a sensor by
                # leaving its exposure alone.
                notes.append(
                    f"the bright regime clipped "
                    f"{bright.saturated_fraction * 100:.1f}% of its frames, so "
                    f"its ratio ({response:g}x) is bounded by the sensor's "
                    f"own ceiling rather than by the lever — it measured "
                    f"more than the dim regime, which is the response this "
                    f"test is looking for")
            else:
                return (mapping_refusals.LEVER_NO_RESPONSE, response, None,
                        notes)

    if len(readings) < 3 or not readings[2].ok:
        notes.append("the repeat capture produced no reading, so this camera "
                     "was proven to respond but not to hold still")
        return mapping_refusals.LEVER_OK, response, None, notes
    repeat = readings[2]
    if repeat.weight < floor:
        return mapping_refusals.LEVER_DRIFT, response, 0.0, notes
    ratio = round(repeat.weight / bright.weight, 4)
    if ratio > REPEAT_BAND or ratio < 1.0 / REPEAT_BAND:
        return mapping_refusals.LEVER_DRIFT, response, ratio, notes
    return mapping_refusals.LEVER_OK, response, ratio, notes


# ── the run's scope ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Scope:
    """WHAT THE RUN IS ABOUT TO MEASURE, handed to the self-test so the
    self-test measures the same thing.

    THE DEFECT THIS EXISTS TO CLOSE: the self-test used to resolve its own
    plan over the WHOLE room at whole granularity and drive `plan.emitters[0]`
    — the first carrier's whole emitter — however narrowly the run itself was
    scoped. On his Living Room that is one carrier, `tv-mapper`, whose 560-px
    strip spans the TV backlight AND both kitchen sconces as pixel ranges of
    one run: a run scoped to the TV backlight's blocks had its verdict earned
    by lighting the kitchen. The verdict is a claim about the CAMERA, but the
    LIGHT it drives is his room, and a run must not drive fixtures it was not
    asked to touch.

    TWO KINDS OF FIELD. `emitter_ids`/`carrier_ids` are WHAT is in scope;
    `granularity`/`block_pixels` are the SHAPE the run will enumerate at,
    carried verbatim from the run so this record says what the run chose.

    THE SHAPE FOLLOWS THE RUN ONLY WHEN THE SCOPE NAMES EMITTER IDS
    (`plan_granularity`/`plan_block_pixels`, the ONE place that decides).
    An emitter's id comes from the granularity that produced it
    (`emitters.py`), so a block-scoped id simply does not exist in a
    whole-granularity plan, and an emitter-scoped self-test has to enumerate
    at the run's own shape or it could never resolve. Nothing else needs the
    shape, and following it anywhere else is a defect: a CARRIER-ONLY scope
    at whole granularity is exactly one emitter per carrier — that emitter IS
    in scope, `within` still narrows to it, and it puts strictly MORE light in
    frame than any one of its blocks; an UNSCOPED run at whole granularity
    takes `plan.emitters[0]`, byte-identical to before this class existed.
    The alternative, found on his own Living Room, is an ordinary map at the
    room's default granularity ("auto", which is BLOCK on a single-segment
    strip such as his TV wrap) earning its verdict on one 30-px block at the
    far end of the wrap: out of shot while the strip as a whole is not, a
    NO-SIGNAL verdict that is then cached and refuses every later item.

    `within` IS THE WHOLE FAIL-CLOSED GUARANTEE, and it is structural rather
    than a check somebody remembered to write: it returns the plan's own list
    verbatim when nothing is scoped, and a subset of it otherwise. There is
    no third answer, so there is nothing for a scoped run to widen to."""

    #: Emitter ids this run will map. Empty is "not scoped by emitter".
    emitter_ids: tuple = ()
    #: Carrier ids this run will map. Empty is "not scoped by carrier".
    carrier_ids: tuple = ()
    granularity: str = "whole"
    block_pixels: int = emitters_mod.DEFAULT_BLOCK_PIXELS

    @classmethod
    def of(cls, *, emitter_ids=None, carrier_ids=None,
           granularity: Optional[str] = None,
           block_pixels: Optional[int] = None) -> "Scope":
        """Build one from a run's own arguments, which are `None`-or-list
        where this is a tuple. An UNSCOPED run building this lands on exactly
        the default, so it costs nothing and changes nothing."""
        return cls(
            emitter_ids=tuple(e for e in (emitter_ids or []) if e),
            carrier_ids=tuple(c for c in (carrier_ids or []) if c),
            granularity=granularity or "whole",
            block_pixels=(block_pixels if block_pixels
                          else emitters_mod.DEFAULT_BLOCK_PIXELS))

    @property
    def scoped(self) -> bool:
        return bool(self.emitter_ids or self.carrier_ids)

    @property
    def plan_granularity(self) -> str:
        """The granularity the self-test enumerates its plan at: the run's
        own when the scope names emitter ids (the only case an id's shape is
        load-bearing), whole otherwise."""
        return self.granularity if self.emitter_ids else "whole"

    @property
    def plan_block_pixels(self) -> int:
        return (self.block_pixels if self.emitter_ids
                else emitters_mod.DEFAULT_BLOCK_PIXELS)

    def within(self, plan_emitters: list) -> list:
        """The emitters of `plan_emitters` this self-test may drive, in the
        PLAN'S OWN ORDER — so "the first one" is deterministic and is always
        one the run itself is about to map."""
        if not self.scoped:
            return plan_emitters
        chosen = plan_emitters
        if self.carrier_ids:
            want = set(self.carrier_ids)
            chosen = [e for e in chosen if e.carrier_id in want]
        if self.emitter_ids:
            want = set(self.emitter_ids)
            chosen = [e for e in chosen if e.emitter_id in want]
        return chosen


# ── the run ────────────────────────────────────────────────────────────────

async def run_selftest(room: RoomMap, deps: "room_mapping.RunDeps", *,
                       scope: Optional[Scope] = None,
                       requested_exposure: Optional[int] = None,
                       ) -> Verdict:
    """Drive one emitter three times and say whether this camera's exposure
    lever reaches its sensor.

    `scope` is the RUN'S OWN SCOPE (`Scope`), and it decides which of the
    plan's emitters this test may drive — and, ONLY when it names emitter
    ids, the shape the plan is enumerated at (`Scope.plan_granularity`, the
    one definition). A carrier-only scope and an unscoped run both enumerate
    at whole granularity, whatever shape the run itself maps at: the whole
    room at whole granularity is what every run that scopes nothing has
    always got, and a carrier-only scope drives the whole carrier.

    Everything it touches, it puts back: a throwaway room (nothing stored),
    the previous camera request (restored in a `finally`), the hold (closed
    in the same `finally`), and any virtual it had to bring up."""
    scope = scope or Scope()
    started = deps.clock()
    sess = deps.session
    out = Verdict(session_id=getattr(sess, "id", ""),
                  pose_id=getattr(sess, "pose_id", ""),
                  fresh_frames=capture_source.serves_fresh_frames(sess),
                  commanded_factor=COMMANDED_FACTOR)
    if out.fresh_frames is False:
        # A FACT, carried, never a refusal — see `stale_frame_pipeline`.
        # It is on the verdict BEFORE any capture so it is recorded even
        # when the run refuses on ownership two lines below.
        out.problems.append(mapping_refusals.stale_frame_pipeline(
            str((getattr(sess, "hello", None) or {}).get("host") or "")))

    refusal = sess.refusal()
    if refusal:
        out.verdict, out.reason = mapping_refusals.LEVER_UNPROVEN, refusal
        return out
    if not room.carrier_ids:
        out.verdict = mapping_refusals.LEVER_UNPROVEN
        out.reason = "this room has no carriers assigned yet"
        return out

    dim, bright, why_not = choose_regimes(sess.camera_lock_view(),
                                          requested_exposure)
    out.fingerprint = fingerprint(sess, requested_exposure)
    if dim is None or bright is None:
        out.verdict, out.reason = mapping_refusals.LEVER_UNPROVABLE, why_not
        return out

    try:
        live = await room_mapping.live_virtual_ids(deps.get_virtuals)
        plan = await room_mapping.resolve_plan(room, deps, live,
                                               scope.plan_granularity,
                                               scope.plan_block_pixels)
    except Exception as exc:                           # noqa: BLE001
        named = mapping_refusals.ownership_refusal(exc)
        if named is None:
            raise
        out.verdict, out.reason = mapping_refusals.LEVER_UNPROVEN, named
        return out
    out.problems.extend(plan.problems)
    # THE ONE SELECTION, and there is deliberately no second one. `within`
    # hands back the plan's own list verbatim for an unscoped run and a
    # subset of it for a scoped one, so "drive something the run is about to
    # map" is a property of the LIST rather than a check somebody remembered
    # to write — and there is no `plan.emitters[0]` left for a scoped run
    # that resolves nothing to widen to.
    candidates = scope.within(plan.emitters)
    if not candidates:
        out.verdict = mapping_refusals.LEVER_UNPROVEN
        out.reason = (
            mapping_refusals.lever_scope_unresolved(
                list(scope.emitter_ids or scope.carrier_ids),
                [e.emitter_id for e in plan.emitters],
                scope.plan_granularity, scope.plan_block_pixels)
            if scope.scoped else
            "nothing to light for the self-test — no carrier of "
            "this room is rendering right now")
        return out
    emitter = candidates[0]
    out.emitter_id = emitter.emitter_id
    out.emitter_label = emitter.label or emitter.emitter_id

    # NOTHING IS STORED — `exposure_test.py`'s own shape, for its own
    # reason: two regimes in one store would be two incomparable
    # measurements wearing one pose id.
    scratch = RoomMap(name=room.name, carrier_ids=list(room.carrier_ids),
                      axis=room.axis)
    quiet = replace(deps, save_room=None)
    live, activated, not_up = await room_mapping.activate_for_capture(
        plan, live, quiet)
    out.problems.extend(not_up)
    program = room_mapping.MappingProgram(live)
    sess.run_abort = None
    before = sess.camera_request
    try:
        for label, exposure in (("dim", dim), ("bright", bright),
                                ("repeat", bright)):
            out.readings.append(await _one_regime(
                label, exposure, scratch, program, emitter, live, quiet, out))
            if not out.readings[-1].ok and label != "repeat":
                break
    finally:
        # PUT THE CAMERA BACK. A self-test that left its own bright regime
        # running would silently retune the very run it just cleared.
        try:
            await sess.apply_camera(before)
        except Exception:                              # noqa: BLE001
            logger.warning("lever self-test: could not put the camera back",
                           exc_info=True)
        try:
            await quiet.close_hold()
        except Exception:                              # noqa: BLE001
            logger.warning("lever self-test: releasing the hold failed; the "
                           "hold sweep owns it from here", exc_info=True)
        left_on = await room_mapping.deactivate_after_capture(activated, quiet)
        if left_on:
            out.problems.append(
                f"left rendering after the self-test: {', '.join(left_on)}")

    out.seconds = deps.clock() - started
    # A CAMERA THAT WOULD NOT TAKE THE TEST'S OWN COMMANDS proves nothing
    # either way, so it is UNPROVABLE and never a refusal: the run may not
    # have asked for that lever at all, and if it did, its own
    # `camera_refusal` gate stops it by name with a better sentence than
    # this test could write.
    refused_lever = next((r for r in out.readings
                          if not r.ok and r.reason
                          and "did not take" in r.reason), None)
    if refused_lever is not None:
        out.verdict = mapping_refusals.LEVER_UNPROVABLE
        out.reason = (
            f"the lever self-test could not run: this camera would not take "
            f"the integration time it needs to command "
            f"({refused_lever.exposure_time} x100 us). {refused_lever.reason}")
        return out
    verdict, response, repeat, notes = judge(out.readings, out.signal_floor)
    out.verdict, out.response_ratio, out.repeat_ratio = verdict, response, repeat
    out.notes.extend(notes)
    if out.refuses:
        out.reason = mapping_refusals.lever_not_connected(out.as_dict())
    elif verdict == mapping_refusals.LEVER_UNPROVEN and not out.reason:
        out.reason = next((r.reason for r in out.readings if not r.ok),
                          "no regime produced a reading")
    elif out.proven:
        out.reason = (
            f"{out.emitter_label}: commanded {dim} then {bright} (x100 us) "
            f"and the measured light followed — "
            + (f"{response:g}x for a commanded {COMMANDED_FACTOR:g}x"
               if response is not None else "from nothing to a real reading")
            + (f", and a repeat of the same command landed within "
               f"{repeat:g}x" if repeat is not None else "")
            + ". This camera's exposure control reaches its sensor.")
    return out


async def _one_regime(label: str, exposure: int, scratch: RoomMap, program,
                      emitter, live: list, deps: "room_mapping.RunDeps",
                      out: Verdict) -> Reading:
    """Command this integration time, GATE ON THE READ-BACK, then take the
    map's own single-emitter measurement in it."""
    sess = deps.session
    reading = Reading(label=label, exposure_time=exposure)
    req = capture_settings.CameraRequest(
        frame_size=capture_settings.MAP_PROFILE, exposure_time=exposure)
    await sess.apply_camera(req)
    await sess.await_frame_size(req.frame_size, room_mapping.FRAME_SWITCH_WAIT_S)
    # WAIT FOR THE CAMERA TO ANSWER THIS request, not the previous one —
    # `capture_settings.CameraNegotiation.await_camera` carries why.
    await sess.await_camera(room_mapping.FRAME_SWITCH_WAIT_S)
    reading.lock = sess.camera_lock_view()
    problem = sess.camera_refusal()
    if problem:
        reading.reason = problem
        return reading
    # AND THEN WAIT FOR THE SENSOR, not just the driver. `await_camera`
    # returns when the DRIVER has answered; the frames a sensor was still
    # integrating when the control landed are exposed under the OLD regime,
    # and averaging them is how two identical commands came back
    # ten-thousand-fold apart on 2026-09-02. See
    # `capture_settings.regime_settle_s` for the arithmetic — it is paid
    # once per commanded regime, so an ordinary map, whose exposure never
    # moves mid-run, pays nothing.
    fps = sess.observed_fps() or 5.0
    reading.regime_settle_s = capture_settings.regime_settle_s(exposure, fps)
    await deps.sleep(reading.regime_settle_s)
    dark_c, lit_c, too_long, note = room_mapping.capture_windows(
        room_mapping.DARK_CAPTURE_S, room_mapping.LIT_CAPTURE_S, exposure,
        fps)
    if too_long:
        reading.reason = too_long
        return reading
    if note:
        out.notes.append(f"{label}: {note}")
    outcome = await room_mapping._map_one(                     # noqa: SLF001
        scratch, program, emitter,
        [v for v in emitter.virtual_ids if v in set(live)], deps,
        room_mapping.DARK_SETTLE_S, room_mapping.LIT_SETTLE_S, dark_c, lit_c,
        room_mapping.RUN_CEILING_FLOOR_S)
    reading.dark_frames, reading.lit_frames = outcome.dark_frames, outcome.lit_frames
    reading.saturated_fraction = outcome.saturated_fraction
    reading.weight = float(outcome.weight or 0.0)
    # AN UNSEEN EMITTER IS A REAL READING HERE, exactly as it is in the
    # exposure comparison: "this regime measured nothing" is the finding,
    # not a failed measurement — it is the whole of tonight's red case.
    reading.ok = outcome.mapped or outcome.unseen
    if not reading.ok:
        reading.reason = outcome.reason
    return reading


# ── the preflight ──────────────────────────────────────────────────────────

async def ensure(room: RoomMap, deps: "room_mapping.RunDeps", *,
                 requested_exposure: Optional[int] = None,
                 scope: Optional[Scope] = None) -> Verdict:
    """Run the self-test unless this session already earned the same verdict
    under the same fingerprint, and remember it on the session.

    THE CACHE IS THE SESSION OBJECT, which is what makes "at establishment,
    and after every reconnect" structural: `mapping_session.open_session`
    builds a new session per WebSocket, so a reconnect starts with nothing
    cached, and the fingerprint carries the pose id so a camera reopen
    inside one connection cannot inherit a verdict either.

    A verdict that REFUSES is cached like any other — re-driving the room
    three more times per queue item to re-learn the same fact would cost
    dark minutes and change nothing.

    THE CACHE KEY DELIBERATELY DOES NOT CARRY THE SCOPE. What this test
    proves is a fact about the CAMERA, not about the emitter it happened to
    light, so a queue of differently-scoped items pays for it once — which
    is the whole of "it is free after the first one". The scope decides
    which of his fixtures a self-test that actually RUNS may drive; it is
    not a second thing the verdict is about."""
    sess = deps.session
    want = fingerprint(sess, requested_exposure)
    held = getattr(sess, "lever_verdict", None)
    if isinstance(held, Verdict) and held.fingerprint == want and held.fingerprint:
        return held
    verdict = await run_selftest(room, deps, scope=scope,
                                 requested_exposure=requested_exposure)
    # An UNPROVEN verdict is never cached: it says nothing about the camera,
    # and the reason it could not run (ownership, no emitters, a lost
    # session) is exactly the kind of thing that clears on its own.
    if verdict.verdict != mapping_refusals.LEVER_UNPROVEN:
        try:
            sess.lever_verdict = verdict
        except Exception:                              # noqa: BLE001
            logger.debug("lever self-test: this session will not hold a "
                         "verdict", exc_info=True)
        # AND INTO THE CAMERA HOST'S OWN RECORD, so what this camera last
        # proved about its own lever outlives the connection that proved it
        # — the morning read of an overnight refusal is otherwise a session
        # object that no longer exists. Reporting only; it gates nothing,
        # and it never raises past here.
        try:
            from spectra.services import capture_health
            capture_health.note_session(sess, event="lever")
        except Exception:                              # noqa: BLE001
            logger.debug("lever self-test: the camera-host record refused "
                         "this verdict", exc_info=True)
    return verdict
