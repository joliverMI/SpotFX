"""THE POSE FINGERPRINT — telling A MOVED CAMERA from A CHANGED ROOM, and
saying which.

WHY IT MUST DISCRIMINATE, in the captain's own words and binding: "he
rearranges his own house; a calibration refusing because he moved a chair is
a system that expires for reasons he cannot see. It must NAME which it
believes changed — camera moved / room changed / cannot tell — and PREFER
SAYING IT CANNOT TELL OVER GUESSING."

WHAT IT IS ANCHORED ON, and why that choice and not the obvious one. The
obvious fingerprint is a reference IMAGE of the room: cheap, needs no
lights, and completely wrong for this — the ambient scene is the room's to
change, so a fingerprint made of it fires on a moved chair, a drawn curtain
and a different time of day, which is the exact failure above. This one is
anchored instead on what CAMERA GEOMETRY ALONE determines: where a handful
of KNOWN FIXTURES land their own light in the frame, measured by briefly
driving them through the instrument's existing capture machinery.

  A CAMERA MOVE shifts every fixture's image at once, and by a shared
  vector for the rotation part of the move.
  A ROOM CHANGE moves one fixture, or blocks one fixture's spill, and
  leaves the rest exactly where they were.

THAT ASYMMETRY IS THE WHOLE DISCRIMINATOR, and it is stated as a belief
rather than a proof because it has real limits, all of which fall to
"cannot tell" and never to a confident wrong answer:

  * A camera TRANSLATION (slid along the shelf rather than turned) produces
    parallax: near fixtures shift more than far ones, so the shifts are not
    a shared vector. That reads as INCOHERENT, and incoherent is
    `cannot_tell`, not `room_changed` — the run still happens and the
    comparability claim is withheld. How much leftover still counts as one
    shared shift is `COHERENCE_FRACTION`, and it is a FRACTION rather than a
    fixed band because a big camera move pushes edge anchors partly out of
    shot and they then shift less than the middle ones — see that constant.
  * ANCHORS THAT ALL LIGHT ONE CORNER of the frame move together whichever
    of the two happened, so a clustered anchor set cannot discriminate at
    all. That is checked AT ESTABLISHMENT (`MIN_ANCHOR_SPREAD`) and said
    then, so the weaker answer months later is a known property of the pose
    and not a surprise.
  * FEWER THAN `MIN_DISCRIMINATING` anchors cannot separate a shared shift
    from independent ones by construction: with one there is no "shared",
    and with two, any pair of shifts has a mean and residuals, so agreement
    proves nothing. Also checked and said at establishment.

THE SIX TOLERANCES BELOW ARE PRE-REGISTERED, in `commission_compare.py`'s
own discipline: each is DERIVED from something the instrument already
measures, not tuned until a case passed. Moving one is a decision about what
this instrument claims, not a tweak — and the honest act is to say so, not
to edit a number until a run goes green.

WHAT A VERDICT DOES. Exactly one of them stops a re-run:
`mapping_refusals.POSE_REFUSING` is `(POSE_CAMERA_MOVED,)`. The plan is
explicit that a moved camera must be a NAMED REFUSAL rather than silently
incomparable data; the captain is equally explicit that a rearranged room
must not refuse; and `cannot_tell` deliberately does not refuse either,
because a thin-anchored pose would then refuse forever on any change at all.
In those two cases what is withheld is the COMPARABILITY CLAIM, not the
measurement: the run happens, the numbers are real, and the record says what
they may be compared with.

WHAT IT COSTS, stated rather than hidden: one capture per anchor, of an
already-dark room, every time a calibration is re-run — about four seconds
each, so ~20 s for a five-anchor pose. Establishment costs more (it measures
up to `MAX_ESTABLISH_ANCHORS` carriers to find out which ones make good
anchors) and happens once per pose.

WHAT IT NEVER DOES. It never writes a footprint: the measurement runs
against a THROWAWAY room with no `save_room`, the same shape
`lever_selftest` and `exposure_test` already use, and for the same reason —
a fingerprint's readings are taken to be compared with each other and must
never be mistaken for the calibration's own map. It acquires nothing: it
drives the anchors inside the SAME held room every capture uses, through the
same program, and refuses on the same ownership sentence if the room is not
ours.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from spectra.models.calibration import MAX_REFERENCES, PoseReference
from spectra.models.room_map import RoomMap
from spectra.services import fixture_brightness, light_field, mapping_refusals
from spectra.services import emitters as emitters_mod
from spectra.services import room_mapping

logger = logging.getLogger(__name__)

#: HOW FAR AN ANCHOR'S LIGHT MAY LAND FROM WHERE IT LANDED BEFORE and still
#: count as not having moved, in normalized frame width.
#:
#: DERIVED: the stored map grid is 64 cells wide, so one cell is 0.0156 of
#: the frame. A centroid is a weighted average over many cells and is
#: therefore sub-cell precise; two grid cells is a band the instrument's own
#: repeat noise sits well inside (proven, not asserted, in
#: `tests/test_pose_fingerprint.py`) and is about 2 degrees of a typical
#: webcam's field of view — small enough that a real camera move clears it,
#: wide enough that a knock on the desk does not.
CENTROID_TOLERANCE = 0.03
#: HOW FAR PAST THAT an anchor must be to count as CLEARLY moved, for the
#: room-changed test only. The room signature is "some moved and others did
#: not", and a borderline camera nudge that pushed two anchors just over the
#: line and left two just under would fake it. Requiring the moved ones to
#: be three bands out and the still ones to be inside one makes that
#: impossible to confuse; anything in between falls to `cannot_tell`.
MOVE_SEPARATION = 3.0
#: HOW MUCH OF A SHARED SHIFT MAY BE LEFT OVER as per-anchor residual and
#: still count as one shared shift — the CAMERA signature.
#:
#: WHY THIS IS A FRACTION AND NOT THE ABSOLUTE BAND ABOVE, found by sweeping
#: it rather than by reasoning (`scripts/check_pose_fingerprint.py` §1): a
#: BIG camera move pushes anchors near the frame edge partly out of shot, so
#: their measured centroids shift LESS than the ones in the middle — real,
#: unavoidable, and growing with the size of the move. Judged against a fixed
#: band, a large and perfectly obvious camera move therefore fell to
#: `cannot_tell` while a small one was named. Coherence is inherently a
#: RELATIVE property (how much of the shift is shared), so the bound is
#: relative, with `CENTROID_TOLERANCE` kept as its FLOOR — under that, every
#: difference is inside the measurement's own noise anyway.
#:
#: A QUARTER is the codebase's own existing split between a real signal and
#: what is left over beside it (`lever_selftest.MIN_RESPONSE_FRACTION`): the
#: shared part must be four times the leftover before the word "shared"
#: means anything. Proven at both ends — a room change with one anchor still
#: put has a residual EQUAL to its common shift (ratio 1.0) and can never
#: reach this bar, and neither can parallax past a modest depth ratio.
COHERENCE_FRACTION = 0.25
#: HOW MUCH AN ANCHOR'S TOTAL LIGHT MAY VARY, either way, and still count as
#: unchanged. Wide on purpose: this is a SECONDARY signal (something put a
#: box in front of a sconce) and the primary discriminator is geometric.
#: `exposure_test.TIE_FRACTION` puts the instrument's own two-reading wobble
#: at 10%, so 2x is twenty times looser than that and cannot fire on noise.
WEIGHT_BAND = 2.0
#: THE FEWEST ANCHORS THAT CAN SEPARATE the two causes at all. With one
#: there is no shared shift to speak of; with two, any pair of shifts has a
#: mean and equal-and-opposite residuals, so their agreement is not
#: evidence. Three is the first count at which "they all moved by the same
#: vector" is a statement about the data rather than an identity.
MIN_DISCRIMINATING = 3
#: HOW SPREAD THE ANCHORS MUST BE across the frame before the discrimination
#: is attempted, in normalized frame width. DERIVED as five times
#: `CENTROID_TOLERANCE`: anchors closer together than a few times the band
#: that decides "moved" cannot show a difference between a shared shift and
#: independent ones, because the whole cluster subtends less frame than the
#: measurement's own precision needs.
MIN_ANCHOR_SPREAD = CENTROID_TOLERANCE * 5
#: HOW MANY CARRIERS AN ESTABLISHMENT PASS MEASURES before selecting the
#: best-spread `MAX_REFERENCES` from among them. A bound on a one-time cost:
#: eight carriers is about half a minute of dark room.
MAX_ESTABLISH_ANCHORS = 8

#: The fingerprint always drives WHOLE CARRIERS, never pixel ranges. A whole
#: carrier is the brightest and most reliably-centroided thing available, it
#: does not depend on the room having been mapped at any granularity (so a
#: pose can be established before the first map exists), and it needs no
#: sub-device capture — which would need SPECTRA to own the render path and
#: would refuse on a room the whole-carrier pass can measure fine.
ANCHOR_GRANULARITY = "whole"


# ── the measurement ────────────────────────────────────────────────────────

@dataclass
class Measurement:
    """What one fingerprint pass measured, and everything it could not."""
    references: list[PoseReference] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    pose_id: str = ""
    seconds: float = 0.0
    refusal: str = ""

    @property
    def seen(self) -> list[PoseReference]:
        return [r for r in self.references if r.seen]


def identity_from_hello(hello: Optional[dict]) -> dict:
    """WHOSE CAMERA THIS IS, from the client's own `hello`. A dict rather
    than a string so a reader can see what it was built from; compared
    field by field by `identity_changed`.

    Deliberately NOT the session id or the pose token: both die on a
    reconnect, which is precisely the case a fingerprint exists to survive
    (`mapping_session._adopt_pose` carries that reasoning)."""
    hello = hello or {}
    cam = hello.get("camera") or {}
    return {"client": str(hello.get("client") or ""),
            "host": str(hello.get("host") or ""),
            "kind": str(cam.get("kind") or ""),
            "device": str(cam.get("device") or ""),
            "user_agent": str(hello.get("user_agent") or "")}


def camera_identity(session: Any) -> dict:
    """`identity_from_hello` for a caller holding the session object rather
    than `capture_runs.session_view()`'s copy of its hello."""
    return identity_from_hello(getattr(session, "hello", None))


def identity_changed(recorded: dict, now: dict) -> str:
    """A sentence naming which part of the camera's identity differs, or ""
    when it does not.

    An EMPTY recorded identity never counts as a change: a fingerprint taken
    before a client reported one has nothing to disagree with, and inventing
    a mismatch out of a blank is exactly the confident wrong answer this
    module exists to avoid. Only fields BOTH sides actually reported are
    compared, for the same reason."""
    if not recorded:
        return ""
    for key, word in (("host", "capture machine"), ("device", "camera device"),
                      ("client", "client")):
        was, is_now = recorded.get(key) or "", (now or {}).get(key) or ""
        if was and is_now and was != is_now:
            return f"the {word} is {is_now} now and was {was}"
    return ""


def spread(references: list[PoseReference]) -> float:
    """The widest distance between two anchors' centroids, in normalized
    frame width — how much geometry the discrimination has to work with."""
    seen = [r for r in references if r.seen]
    return max((math.dist((a.x, a.y), (b.x, b.y))
                for i, a in enumerate(seen) for b in seen[i + 1:]),
               default=0.0)


def discriminating(references: list[PoseReference]) -> tuple[bool, str]:
    """CAN THIS ANCHOR SET tell a moved camera from a changed room? Answered
    at establishment and recorded on the fingerprint, so the weaker answer
    later is a known property of the pose rather than a surprise."""
    seen = [r for r in references if r.seen]
    sp = spread(references)
    if len(seen) < MIN_DISCRIMINATING or sp < MIN_ANCHOR_SPREAD:
        return False, mapping_refusals.pose_not_discriminating(
            len(seen), sp, min_count=MIN_DISCRIMINATING,
            min_spread=MIN_ANCHOR_SPREAD)
    return True, ""


def select_anchors(measured: list[PoseReference],
                   limit: int = MAX_REFERENCES) -> list[PoseReference]:
    """The best `limit` anchors from a measured set: GREEDY FARTHEST-POINT,
    seeded by the strongest.

    SPREAD IS WHAT IS BEING MAXIMISED, not brightness, and that is the whole
    reason this is not just "take the five heaviest": anchors clustered in
    one part of the frame move together whichever of the two things
    happened, so a bright cluster is a worse fingerprint than a dimmer
    spread. Brightness still seeds it (the strongest footprint has the most
    reliable centroid) and still breaks ties, so this never prefers a
    whisper-signal anchor when a real one is equally far.

    Deterministic: no randomness, and ties resolve by weight then id."""
    usable = sorted([r for r in measured if r.seen and r.weight > 0.0],
                    key=lambda r: (-r.weight, r.emitter_id))
    if len(usable) <= limit:
        return usable
    chosen = [usable[0]]
    rest = usable[1:]
    while len(chosen) < limit and rest:
        best = max(rest, key=lambda r: (
            round(min(math.dist((r.x, r.y), (c.x, c.y)) for c in chosen), 6),
            r.weight))
        rest.remove(best)
        chosen.append(best)
    return chosen


async def measure(room: RoomMap, deps: "room_mapping.RunDeps", *,
                  emitter_ids: Optional[list[str]] = None,
                  hold_ceiling_s: Optional[float] = None) -> Measurement:
    """Drive the anchors and read back where each one's light landed.

    `emitter_ids` names the anchors to re-measure (a CHECK); omitted, this
    is an ESTABLISHMENT pass and it measures up to `MAX_ESTABLISH_ANCHORS`
    of the room's carriers so `select_anchors` has real centroids to choose
    from.

    Everything it touches, it puts back: a throwaway room (nothing stored),
    the hold (closed in a `finally`), and any virtual it had to bring up."""
    started = deps.clock()
    sess = deps.session
    out = Measurement(pose_id=getattr(sess, "pose_id", ""))

    refusal = sess.refusal() if sess is not None else mapping_refusals.NO_SESSION
    if refusal:
        out.refusal = refusal
        return out
    if not room.carrier_ids:
        out.refusal = mapping_refusals.pose_no_anchors(
            "this room has no carriers assigned yet")
        return out

    try:
        scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
        plan = await room_mapping.resolve_plan(
            room, deps, scope, ANCHOR_GRANULARITY,
            emitters_mod.DEFAULT_BLOCK_PIXELS)
    except Exception as exc:                           # noqa: BLE001
        named = mapping_refusals.ownership_refusal(exc)
        if named is None:
            raise
        out.refusal = named
        return out
    out.problems.extend(plan.problems)

    wanted = list(emitter_ids or [])
    if wanted:
        chosen = [e for e in plan.emitters if e.emitter_id in set(wanted)]
        for missing in [w for w in wanted
                        if w not in {e.emitter_id for e in chosen}]:
            # A RECORDED ANCHOR THAT NO LONGER RESOLVES is a fact, not a
            # crash: the carrier was removed from the room, or is not
            # rendering. It is carried into the judgement as an anchor with
            # no reading, which is what makes "it vanished" visible.
            out.problems.append(
                f"{missing} is a reference fixture of this pose and is not "
                f"available to light right now — it is counted as a "
                f"reference this pass could not read")
    else:
        chosen = list(plan.emitters)[:MAX_ESTABLISH_ANCHORS]
    if not chosen:
        out.refusal = mapping_refusals.pose_no_anchors(
            "no carrier of this room is rendering right now")
        return out

    # NOTHING IS STORED — `lever_selftest`'s own shape, for its own reason.
    scratch = RoomMap(name=room.name, carrier_ids=list(room.carrier_ids),
                      axis=room.axis)
    quiet = replace(deps, save_room=None)
    scope, activated, not_up = await room_mapping.activate_for_capture(
        plan, scope, quiet)
    out.problems.extend(not_up)
    program = room_mapping.MappingProgram(scope)
    ceiling = (hold_ceiling_s if hold_ceiling_s is not None
               else room_mapping.run_ceiling_s(
                   room_mapping.run_estimate_s(
                       len(chosen), room_mapping.DARK_SETTLE_S,
                       room_mapping.LIT_SETTLE_S,
                       room_mapping.DARK_CAPTURE_S,
                       room_mapping.LIT_CAPTURE_S)))
    if sess is not None:
        sess.run_abort = None
    try:
        # OWN THE FIXTURES' OWN FIRMWARE BRIGHTNESS for the pass, exactly as
        # `run_mapping` does, and give his levels back on the way out. It
        # matters MORE here than it does for a map: an anchor's weight is
        # compared against the same anchor's weight weeks later, and a
        # fixture left at 10% would move every one of those weights at once
        # — which this judges, correctly but uselessly, as "something
        # changed and I cannot tell what". Taking each fixture to full at
        # both ends removes that whole class of unreadable answer.
        async with fixture_brightness.owned(
                *await _brightness_guard(plan, quiet)) as owned:
            for emitter in chosen:
                lit = [v for v in emitter.virtual_ids if v in set(scope)]
                outcome = await room_mapping._map_one(      # noqa: SLF001
                    scratch, program, emitter, lit, quiet,
                    room_mapping.DARK_SETTLE_S, room_mapping.LIT_SETTLE_S,
                    room_mapping.DARK_CAPTURE_S, room_mapping.LIT_CAPTURE_S,
                    ceiling)
                out.references.append(
                    _reference_from(scratch, emitter, outcome))
                if getattr(sess, "run_abort", None):
                    out.problems.append(sess.run_abort)
                    break
        out.problems.extend(owned.problems)
        if owned.note:
            out.notes.append(owned.note)
    finally:
        try:
            await quiet.close_hold()
        except Exception:                              # noqa: BLE001
            logger.warning("pose fingerprint: releasing the hold failed; the "
                           "hold sweep owns it from here", exc_info=True)
        left_on = await room_mapping.deactivate_after_capture(activated, quiet)
        if left_on:
            out.problems.append(
                f"left rendering after the pose check: {', '.join(left_on)}")

    out.seconds = deps.clock() - started
    return out


async def _brightness_guard(plan, deps) -> tuple[list, list]:
    """`(devices, readings)` for `fixture_brightness.owned` — the plan's own
    already-taken readings and the live driver objects they name. The plan
    read them while the room was still lit and nothing had been spent; this
    is the acting half, and reusing the plan's readings is what keeps the
    two from being two different opinions of the same fixture."""
    readings = [fixture_brightness.FixtureBrightness(
        device_id=b["device_id"], state=b["state"], value=b["value"],
        reason=b["reason"]) for b in (getattr(plan, "brightness", None) or [])]
    _, devices = await room_mapping.fixture_readings(
        plan, await room_mapping._chains(deps), deps)   # noqa: SLF001
    return devices, readings


def _reference_from(scratch: RoomMap, emitter, outcome) -> PoseReference:
    """One driven emitter -> one anchor reading. An emitter the camera could
    not see is a REAL reading (`seen=False`), not an omission: "we drove it
    and it was dark" and "we never drove it" are different facts, exactly as
    `EmitterFootprint.unseen` already says one level down."""
    fp = scratch.footprint(emitter.emitter_id)
    label = emitter.label or emitter.emitter_id
    if fp is None or not fp.mapped:
        return PoseReference(emitter_id=emitter.emitter_id, label=label,
                             weight=round(float(outcome.weight or 0.0), 4),
                             seen=False)
    x, y = light_field.centroid(fp.grid)
    return PoseReference(emitter_id=emitter.emitter_id, label=label,
                         x=round(x, 5), y=round(y, 5),
                         weight=round(fp.weight, 4), seen=True)


# ── the judgement ──────────────────────────────────────────────────────────

@dataclass
class AnchorDelta:
    """ONE ANCHOR, THEN AND NOW."""
    emitter_id: str
    label: str = ""
    dx: float = 0.0
    dy: float = 0.0
    distance: float = 0.0
    #: Both readings produced a centroid, so a shift VECTOR exists. False
    #: when either side saw nothing — a real change, but not a direction.
    vector: bool = False
    seen_before: bool = True
    seen_now: bool = True
    weight_before: float = 0.0
    weight_now: float = 0.0
    weight_ratio: Optional[float] = None
    moved: bool = False
    far: bool = False
    changed: bool = False
    why: str = ""

    def as_dict(self) -> dict:
        return {"emitter_id": self.emitter_id, "label": self.label,
                "dx": round(self.dx, 5), "dy": round(self.dy, 5),
                "distance": round(self.distance, 5), "vector": self.vector,
                "seen_before": self.seen_before, "seen_now": self.seen_now,
                "weight_before": self.weight_before,
                "weight_now": self.weight_now,
                "weight_ratio": (round(self.weight_ratio, 3)
                                 if self.weight_ratio is not None else None),
                "moved": self.moved, "far": self.far, "changed": self.changed,
                "why": self.why}


@dataclass
class Judgement:
    """WHAT THE FINGERPRINT FOUND, in both registers at once: a word a
    program branches on and a sentence a person reads."""
    verdict: str = mapping_refusals.POSE_CANNOT_TELL
    reason: str = ""
    #: The machine-readable half of "why not something more definite" — for
    #: the sentence, never a second wording of the verdict itself.
    why: str = ""
    deltas: list[AnchorDelta] = field(default_factory=list)
    common_shift: float = 0.0
    common_dx: float = 0.0
    common_dy: float = 0.0
    max_residual: float = 0.0
    anchor_spread: float = 0.0
    discriminating: bool = True
    identity_note: str = ""
    problems: list[str] = field(default_factory=list)
    at: float = field(default_factory=time.time)

    @property
    def matched(self) -> bool:
        return self.verdict == mapping_refusals.POSE_MATCH

    @property
    def refuses(self) -> bool:
        """Does this stop a re-run? Only a MEASURED CAMERA MOVE does — see
        `mapping_refusals.POSE_REFUSING`, and the module docstring on why a
        changed room and a cannot-tell deliberately do not."""
        return self.verdict in mapping_refusals.POSE_REFUSING

    @property
    def checked(self) -> int:
        return len(self.deltas)

    @property
    def moved(self) -> int:
        return sum(1 for d in self.deltas if d.changed)

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "reason": self.reason,
                "why": self.why, "matched": self.matched,
                "refuses": self.refuses, "checked": self.checked,
                "moved": self.moved,
                "common_shift": round(self.common_shift, 5),
                "common_dx": round(self.common_dx, 5),
                "common_dy": round(self.common_dy, 5),
                "max_residual": round(self.max_residual, 5),
                "anchor_spread": round(self.anchor_spread, 5),
                "discriminating": self.discriminating,
                "identity_note": self.identity_note,
                "centroid_tolerance": CENTROID_TOLERANCE,
                "move_separation": MOVE_SEPARATION,
                "coherence_fraction": COHERENCE_FRACTION,
                "coherence_allowance": round(
                    coherence_allowance(self.common_shift), 5),
                "weight_band": WEIGHT_BAND,
                "min_discriminating": MIN_DISCRIMINATING,
                "min_anchor_spread": MIN_ANCHOR_SPREAD,
                "deltas": [d.as_dict() for d in self.deltas],
                "problems": list(self.problems), "at": self.at}


def coherence_allowance(common_shift: float) -> float:
    """How much per-anchor residual a shared shift of this size may carry and
    still read as ONE shift. See `COHERENCE_FRACTION` for why it grows with
    the shift and why `CENTROID_TOLERANCE` is its floor."""
    return max(CENTROID_TOLERANCE, COHERENCE_FRACTION * float(common_shift))


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def _delta(before: PoseReference, now: Optional[PoseReference]) -> AnchorDelta:
    d = AnchorDelta(emitter_id=before.emitter_id, label=before.label,
                    seen_before=before.seen,
                    weight_before=before.weight)
    if now is None:
        d.seen_now = False
        d.changed = True
        d.why = "this reference fixture could not be read at all this time"
        return d
    d.seen_now = now.seen
    d.weight_now = now.weight
    if before.seen and now.seen:
        d.vector = True
        d.dx, d.dy = now.x - before.x, now.y - before.y
        d.distance = math.hypot(d.dx, d.dy)
        d.moved = d.distance > CENTROID_TOLERANCE
        d.far = d.distance > CENTROID_TOLERANCE * MOVE_SEPARATION
        if before.weight > 0.0:
            d.weight_ratio = now.weight / before.weight
        heavy = (d.weight_ratio is not None
                 and (d.weight_ratio > WEIGHT_BAND
                      or d.weight_ratio < 1.0 / WEIGHT_BAND))
        d.changed = d.moved or heavy
        if d.moved:
            d.why = (f"its light landed {d.distance * 100:.1f}% of the "
                     f"frame's width from where it did before")
        elif heavy:
            d.why = (f"it landed in the same place and measured "
                     f"{d.weight_ratio:.2f}x the light it did before")
        return d
    # One side saw nothing. A change, and never a direction.
    d.changed = before.seen != now.seen
    if d.changed:
        d.why = ("it lit up for the camera before and not this time"
                 if before.seen else
                 "the camera could not see it before and can now")
    return d


def judge(reference: list[PoseReference], observed: list[PoseReference], *,
          identity_note: str = "", problems: Optional[list[str]] = None
          ) -> Judgement:
    """THE WHOLE DECISION, as a pure function of two anchor readings.

    Pure so the word and the numbers can never disagree, and so every case —
    a still camera, a moved one, a rearranged room, a parallax translation,
    a thin anchor set — is provable without a room. `lever_selftest.judge`'s
    own shape, for the same reason.

    ORDER IS THE ARGUMENT, and each step is a reason not to guess:

      0  A DIFFERENT CAMERA is a different pose by definition, and the
         cheapest thing to know. Decided before any geometry.
      1  NOTHING CHANGED -> match. The common case, and it must be reachable
         without any of the harder tests firing.
      2  TOO FEW OR TOO CLUSTERED ANCHORS -> cannot tell. Checked before
         either signature, because with thin anchors both signatures are
         reachable by accident.
      3  THEY ALL MOVED BY THE SAME VECTOR -> the camera. Nothing in the
         room can do that to every fixture at once.
      4  SOME MOVED AND OTHERS DID NOT -> the room. A camera that moved
         would have moved all of them.
      5  ANYTHING ELSE -> cannot tell, said as such.
    """
    out = Judgement(identity_note=identity_note,
                    problems=list(problems or []))
    by_id = {r.emitter_id: r for r in observed}
    out.deltas = [_delta(r, by_id.get(r.emitter_id)) for r in reference]
    out.anchor_spread = spread(reference)
    ok, note = discriminating(reference)
    out.discriminating = ok

    if identity_note:
        out.verdict = mapping_refusals.POSE_CAMERA_MOVED
        out.why = identity_note
        out.reason = mapping_refusals.pose_verdict_sentence(out.as_dict())
        return out

    if not out.deltas:
        out.verdict = mapping_refusals.POSE_CANNOT_TELL
        out.why = "this pose has no reference fixtures recorded"
        out.reason = mapping_refusals.pose_verdict_sentence(out.as_dict())
        return out

    vectors = [d for d in out.deltas if d.vector]
    if vectors:
        out.common_dx = _median([d.dx for d in vectors])
        out.common_dy = _median([d.dy for d in vectors])
        out.common_shift = math.hypot(out.common_dx, out.common_dy)
        out.max_residual = max(math.hypot(d.dx - out.common_dx,
                                          d.dy - out.common_dy)
                               for d in vectors)

    changed = [d for d in out.deltas if d.changed]
    if not changed:
        out.verdict = mapping_refusals.POSE_MATCH
        out.reason = mapping_refusals.pose_verdict_sentence(out.as_dict())
        return out

    if not ok:
        out.verdict = mapping_refusals.POSE_CANNOT_TELL
        out.why = note
        out.reason = mapping_refusals.pose_verdict_sentence(out.as_dict())
        return out
    if len(vectors) < MIN_DISCRIMINATING:
        out.verdict = mapping_refusals.POSE_CANNOT_TELL
        out.why = (f"only {len(vectors)} of this pose's "
                   f"{len(out.deltas)} reference fixtures produced a reading "
                   f"this time, and telling the two apart needs "
                   f"{MIN_DISCRIMINATING}")
        out.reason = mapping_refusals.pose_verdict_sentence(out.as_dict())
        return out

    # 3 — A SHARED VECTOR. Every anchor moved, and after removing the shared
    # part what is left over is a small MINORITY of it. Only a camera can do
    # this: nothing in a room moves every fixture's image by one vector.
    if (out.common_shift > CENTROID_TOLERANCE
            and out.max_residual <= coherence_allowance(out.common_shift)
            and all(d.vector for d in out.deltas)):
        out.verdict = mapping_refusals.POSE_CAMERA_MOVED
        out.reason = mapping_refusals.pose_verdict_sentence(out.as_dict())
        return out

    # 4 — INDEPENDENT CHANGE. At least one anchor is unambiguously where it
    # was and at least one is unambiguously not, with no shared shift to
    # explain it. A camera that moved would have moved the still one too.
    still = [d for d in vectors if not d.moved]
    far = [d for d in vectors if d.far]
    if still and far and out.common_shift <= CENTROID_TOLERANCE:
        out.verdict = mapping_refusals.POSE_ROOM_CHANGED
        out.reason = mapping_refusals.pose_verdict_sentence(out.as_dict())
        return out

    # 4b — NOTHING MOVED GEOMETRICALLY, but some anchors read differently and
    # others did not: a fixture blocked, dimmed or gone dark. Requiring an
    # UNCHANGED anchor beside the changed one is what keeps this from firing
    # on a camera whose whole exposure regime drifted, which would move every
    # anchor's weight together.
    if (not any(d.moved for d in out.deltas)
            and any(d.changed for d in out.deltas)
            and any(not d.changed for d in out.deltas)):
        out.verdict = mapping_refusals.POSE_ROOM_CHANGED
        out.reason = mapping_refusals.pose_verdict_sentence(out.as_dict())
        return out

    # 5 — SOMETHING CHANGED AND THIS CANNOT SAY WHICH. The honest answer for
    # a camera slid sideways (parallax makes near anchors shift more than far
    # ones, so there is no shared vector), for a room rearranged wholesale,
    # and for the two happening together.
    out.verdict = mapping_refusals.POSE_CANNOT_TELL
    out.why = _cannot_tell_why(out)
    out.reason = mapping_refusals.pose_verdict_sentence(out.as_dict())
    return out


def _cannot_tell_why(out: Judgement) -> str:
    """Say WHAT the evidence looked like, not just that it was inconclusive.
    A refusal a person cannot act on is the failure this whole module is
    built against."""
    if not all(d.vector for d in out.deltas):
        blind = sum(1 for d in out.deltas if not d.vector)
        return (f"{blind} of this pose's {len(out.deltas)} reference "
                f"fixtures could not be read this time, and a fixture that "
                f"vanished from the shot looks the same whether the camera "
                f"turned away from it or something was put in front of it")
    if (out.common_shift > CENTROID_TOLERANCE
            and out.max_residual > coherence_allowance(out.common_shift)):
        return (f"every reference fixture moved, but by different amounts "
                f"(a shared shift of {out.common_shift * 100:.1f}% of the "
                f"frame with up to {out.max_residual * 100:.1f}% left over) "
                f"— that is what a camera slid sideways looks like, and it "
                f"is also what a room rearranged all at once looks like")
    return (f"{out.moved} of {out.checked} reference fixtures read "
            f"differently, and the pattern is not clear enough to say "
            f"whether the camera moved or the room did")
