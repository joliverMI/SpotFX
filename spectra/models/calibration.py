"""THE CALIBRATION RECORD — a calibration stops being a ritual and becomes a
durable, named, re-runnable artefact.

His words, the premise (`/home/javi/fleet-spotfx/data/calibration-practice-
plan/plan.md`): "we need a really clean system for doing many calibrations
and for you to be able to restart and edit the cals if needed without my
intervention." Until this, a calibration was a sequence of button presses
whose only trace was a room map that could not say what produced it, taken
at a camera pose nothing recorded, under settings nobody wrote down. A
second run a week later was a NEW ritual, and whether its numbers could be
compared with the first was a matter of memory.

WHAT A CALIBRATION IS, then, and every field below is one of these:

  IDENTITY      a name he chose and when it was created.
  POSE          the camera, HIS OWN NAME for where it stands ("the north
                shelf"), and a FINGERPRINT — see `PoseFingerprint`, and
                `spectra/services/pose_fingerprint.py` for the binding
                statement on what it can and cannot tell apart.
  CAMERA        the pinned regime (the four levers and the frame size), plus
                the LEVER SELF-TEST verdict that proved it reaches the
                sensor. A regime nothing proved is a regime, not evidence.
  ENVELOPE      what darkness it needs. Declared, so a run at the wrong hour
                is a stated mismatch rather than a mysteriously dim map.
  QUEUE         the declared items, in the capture queue's OWN declaration
                format. `spectra/services/capture_queue.parse_items` is the
                one validator; this model stores what that function accepted
                and never re-parses it into a second dialect.
  TAGS          the TAG REGISTRY: every physical ArUco tag, with the black
                square's side as HE MEASURED IT after printing — measured,
                never nominal, because a tag whose real size differs from
                its nominal one silently scales every pose it anchors.
                Empty by default and STORAGE ONLY in this step: nothing
                reads it and no tag-detection code exists here. It is
                carried from day one so the vision step lands into a record
                that already holds measured truth. See `TagRegistration`.
  LINEAGE       an APPEND-ONLY list of every run: when, what it declared,
                how each item landed, what the fingerprint said, what the
                witness said, which footprints it produced, and which
                earlier run's footprints those replaced.

FOUR KINDS OF ENTRY, and the second is the 2026-09-01 addition: `run` (the
whole declaration), `amendment` (a NAMED SUBSET of it, re-measured on its
own — `spectra/services/amendment.py` is the binding statement for when
that is honest), `fingerprint` (a pose taken or re-anchored), and
`declaration` (the declared items, the camera regime or the envelope were
edited). `RUN_KINDS` is the pair that MEASURED something, and every reader
asking "what has this calibration actually produced" uses that rather than
testing for the word "run" — an amendment produces footprints exactly as a
run does, and a reader that missed it would report his newest measurement
as belonging to nobody.

THE LINEAGE IS APPEND-ONLY, AND THAT IS THE HONESTY RAIL. Nothing in this
model has a way to edit or drop a past run: `Calibration.append_run` is the
only mutator of `runs`, and it appends. A re-run that replaces a footprint
RECORDS the supersession (`CalibrationRun.superseded`) rather than erasing
the run that measured it first. Editing the DECLARATION is append-only too:
the edit is its own entry and it carries the WHOLE PRIOR DECLARATION
(`CalibrationRun.previous_declaration`), so what run 3 actually asked for is
recoverable after run 4 asked for something else — never rewritten in place.

WHAT EACH RUN MEASURED IS RECORDED AS A NUMBER, not only as a list of ids
(`ItemOutcomeRecord.measurements`). The room map holds only the LATEST
footprint per emitter, so a superseded grid is gone the moment it is
replaced — and a diff between two of this calibration's own lineage entries
would then have nothing to read. One small row per emitter, bounded by the
run's own `emitters.MAX_EMITTERS_PER_RUN`, is what makes drift across a
calibration's own selves DETECTABLE from stored data instead of narrated.
An entry written before this field existed carries none, and
`spectra/services/calibration_diff.py` reports that as UNMEASURED rather
than as a change.

RESULTS ARE A LINK, NOT A COPY. A run records the emitter ids it produced;
the footprints themselves live in `storage/spectra/room_maps.json`, which
remains the live store. Resolving one against the other is a READ
(`spectra/services/calibration_store.provenance`), and a calibration
pointing at footprints that are no longer there REPORTS that rather than
implying they exist — the same "absence is a read" rule
`EmitterFootprint.unseen` already answers for an emitter nobody could see.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

#: How many references a fingerprint may carry. Each one costs a capture of
#: a dark room every time the fingerprint is checked, so this is a real
#: bound and not a formality — `spectra/services/pose_fingerprint.py` owns
#: the reasoning and the selection.
MAX_REFERENCES = 5

#: THE ENTRY KINDS. `run` measures the whole declaration; `amendment`
#: measures a NAMED SUBSET of it (spectra/services/amendment.py);
#: `fingerprint` takes or re-anchors the pose; `declaration` records an edit
#: to what this calibration declares.
KIND_RUN = "run"
KIND_AMENDMENT = "amendment"
KIND_FINGERPRINT = "fingerprint"
KIND_DECLARATION = "declaration"
#: THE KINDS THAT MEASURED SOMETHING, and the reason this is a constant
#: rather than a literal at each reader: an amendment produces footprints
#: exactly as a run does, so a reader still testing `kind == "run"` would
#: report his newest measurement as belonging to nobody. Every provenance,
#: origin and comparability read uses this tuple.
RUN_KINDS = (KIND_RUN, KIND_AMENDMENT)


class TagRegistration(BaseModel):
    """ONE PHYSICAL ARUCO TAG, and the only number about it that is not a
    guess: the side of its black square as HE MEASURED IT, in millimetres,
    after printing.

    WHY MEASURED AND NOT NOMINAL, which is the whole reason this exists as a
    stored field rather than a constant in a future vision module: a printed
    tag whose real side differs from the nominal one SILENTLY SCALES every
    pose it anchors. A driver told "this square is 100 mm" when it is 97
    reports a camera 3% further away and every distance derived from it is
    wrong by the same factor, with nothing anywhere to notice — the same
    class of failure as a map taken at 10% firmware brightness, arriving
    through a different door. So the measurement is his, taken once with a
    ruler, and recorded here as the truth a later step reads.

    NOTHING IN THIS STEP READS IT. There is no tag-detection code anywhere in
    this build; the registry is STORAGE ONLY, carried from day one so the
    vision step lands into a record that already holds measured truth rather
    than having to go back and ask him for it.

    ONE THING DELIBERATELY NOT INVENTED HERE, and named so the vision step
    knows it is an open question rather than an oversight: an ArUco id is
    only unique WITHIN a dictionary (id 7 of DICT_4X4_50 and id 7 of
    DICT_6X6_250 are different tags). The captain named three fields and
    these are those three; if the vision step needs the dictionary too, it is
    an additive field then, decided by whoever knows which dictionary he
    actually printed."""
    #: The tag's ArUco id, as printed.
    tag_id: int = Field(ge=0)
    #: The black square's side, MEASURED with a ruler after printing, in mm.
    #: Must be positive: a zero or negative reading is not a measurement.
    measured_side_mm: float = Field(gt=0.0)
    #: HIS OWN NAME for where this tag is stuck ("the left window frame").
    #: Free text, his words, once — the same register as the pose's own
    #: `placement`.
    mount: str = ""


class PoseReference(BaseModel):
    """ONE ANCHOR: an emitter this pose can see, and WHERE ITS LIGHT LANDED
    IN THE FRAME when the fingerprint was taken.

    `x`/`y` are the weighted centroid of that emitter's footprint in
    NORMALIZED CAMERA-FRAME coordinates — the same space
    `spectra/models/room_map.Point` uses, and for the same reason: it is
    where something landed in the picture, never a position in the room.
    This model's fence (nothing here is a fixture coordinate) is unchanged
    by it; a centroid is a one-number summary of the measurement the grid
    already is, not a new kind of fact.

    `seen` False is a real reading too: this anchor was driven and the
    camera saw nothing of it. Kept, because "we drove it and it was dark"
    and "we never drove it" are different facts."""
    emitter_id: str
    label: str = ""
    x: float = 0.0
    y: float = 0.0
    weight: float = 0.0
    seen: bool = True


class PoseFingerprint(BaseModel):
    """WHAT MAKES A LATER RUN COMPARABLE WITH AN EARLIER ONE — or names why
    it is not.

    `spectra/services/pose_fingerprint.py` is the binding statement for what
    this can and cannot discriminate. The two things to know here:

      * `discriminating` is decided AT ESTABLISHMENT, not at the moment of a
        refusal. A fingerprint anchored on too few references, or on
        references that all light the same corner of the frame, can detect
        that SOMETHING changed and can never say whether it was the camera
        or the room. He is told that when the fingerprint is taken, so it is
        never a surprise arriving as a refusal months later.
      * `spread` is the widest distance between two of its anchors, in the
        same normalized frame units. It is recorded rather than only judged,
        so a reader can see how much geometry the discrimination had to work
        with."""
    #: WHOSE CAMERA, as the client's own `hello` described it — client name,
    #: host, and whatever the driver said about the device. Compared as a
    #: FACT on the record (a different camera is a different pose by
    #: definition); never used to authorise anything.
    camera: dict = Field(default_factory=dict)
    #: HIS OWN NAME for where the camera stands. Free text, his words, once.
    placement: str = ""
    #: The session pose token this fingerprint was taken under. Useful for
    #: reading the run back against `EmitterFootprint.capture.pose_id`; NOT
    #: a comparison key — a pose token dies with a camera reopen, which is
    #: exactly the case this fingerprint exists to survive.
    pose_id: str = ""
    references: list[PoseReference] = Field(default_factory=list)
    spread: float = 0.0
    discriminating: bool = False
    #: The sentence for whatever this fingerprint's own state needs saying —
    #: today, that it cannot discriminate and why.
    note: str = ""
    taken_at: float = 0.0
    #: The run that took it, so re-anchoring is traceable in the lineage.
    taken_by_run: str = ""

    @property
    def established(self) -> bool:
        return bool(self.references)


class PinnedCamera(BaseModel):
    """THE REGIME THIS CALIBRATION IS MEASURED IN, in the wire's own units —
    `spectra/services/capture_settings.py` is the binding statement, and
    nothing here converts anything. `exposure_time` is in 100-microsecond
    units on both the V4L2 and the browser path; `gain` and `focus` are the
    device's own scales; `white_balance` is a temperature in Kelvin.

    All four None is today's behaviour exactly — converge on the scene, then
    freeze — which is a REGIME, just not a pinned one, and a calibration
    that declares none says so rather than implying it pinned zero.

    `frame_size` is not declared here: a map's frame is 320x180 and a
    commissioning read's is derived from the composition's own arithmetic.
    It is REPORTED per run instead (`CalibrationRun.camera`), which is where
    an honest downgrade to what the camera actually has belongs."""
    exposure_time: Optional[int] = None
    gain: Optional[int] = None
    white_balance: Optional[int] = None
    focus: Optional[int] = None

    @property
    def pinned(self) -> bool:
        return any(v is not None for v in
                   (self.exposure_time, self.gain, self.white_balance,
                    self.focus))

    def same_as(self, other: "PinnedCamera") -> bool:
        """Identical in every lever, INCLUDING which ones are unset. Half of
        the cross-time comparability claim (the other half is the pose
        fingerprint): a footprint is `lit - dark` in a camera's own byte
        scale, and two regimes produce two scales."""
        return (self.exposure_time, self.gain, self.white_balance,
                self.focus) == (other.exposure_time, other.gain,
                                other.white_balance, other.focus)

    def differences(self, other: "PinnedCamera") -> list[str]:
        """Which levers disagree, in his words, so a withheld comparability
        claim can say WHAT changed rather than only that something did."""
        out = []
        for name in ("exposure_time", "gain", "white_balance", "focus"):
            a, b = getattr(self, name), getattr(other, name)
            if a != b:
                out.append(f"{name.replace('_', ' ')}: "
                           f"{'not pinned' if a is None else a} -> "
                           f"{'not pinned' if b is None else b}")
        return out


class Envelope(BaseModel):
    """WHAT DARKNESS THIS CALIBRATION NEEDS. Declared, not enforced here: the
    dark room itself is the hold's job and the house's own light is the
    witness's, and neither of those is a thing this record should try to
    second-guess. What it does is make the requirement READABLE, so a run
    taken at noon is a stated mismatch on the record instead of a map that
    is quietly worse than the one before it.

    `window` is his own word for when it should run ("night", "any", "dark
    music") — free text on purpose: the night seam already owns the real
    scheduling (spectra/services/night_run.py) and a second vocabulary here
    would be a second thing to keep true."""
    dark_required: bool = True
    window: str = "night"
    note: str = ""


class EmitterMeasurement(BaseModel):
    """WHAT ONE EMITTER MEASURED, on the run that measured it — a small,
    bounded row kept on the lineage entry itself.

    WHY IT IS HERE AND NOT ONLY IN THE ROOM MAP: `room_maps.json` holds the
    LATEST footprint per emitter, so the instant a re-run replaces one the
    earlier grid is gone. A diff between two of a calibration's own lineage
    entries would then have nothing to read, and "has this fixture drifted"
    would be a thing somebody remembered rather than a thing anybody could
    compute. One row per emitter, capped by `emitters.MAX_EMITTERS_PER_RUN`,
    is the whole cost.

    IT IS A SUMMARY AND NEVER THE GRID. Copying a 2,304-cell footprint into
    every lineage entry would make the one file that must never be pruned
    the unbounded one — `ItemOutcomeRecord`'s own discipline, one level
    down."""
    emitter_id: str
    carrier_id: str = ""
    label: str = ""
    #: The footprint's total relative luminance — "how much light this
    #: emitter landed in this room", in THIS run's camera scale. Comparable
    #: only with a run whose pose matched and whose pinned regime was
    #: identical; `calibration_diff` is the one place that judgement is
    #: applied.
    weight: float = 0.0
    mapped: bool = False
    #: RAN, and the camera saw nothing of it from this pose. A real reading,
    #: kept, exactly as `EmitterFootprint.unseen` keeps it one level down —
    #: which is what lets a diff say "it vanished from view" rather than
    #: "it was not measured".
    unseen: bool = False


class ItemOutcomeRecord(BaseModel):
    """One declared item's landing, as the queue reported it. A SUMMARY, the
    same discipline `capture_queue.ItemOutcome` already keeps: the full map
    is in `room_maps.json` and the full judged table in `commissioning.json`,
    and copying either in here would make a growing per-calibration file the
    unbounded one."""
    index: int = 0
    name: str = ""
    kind: str = ""
    room_id: str = ""
    status: str = ""
    detail: str = ""
    refusal: str = ""
    attempts: int = 0
    pose_id: str = ""
    seconds: float = 0.0
    #: Emitter ids this item produced a footprint for — the provenance link,
    #: resolved against the live room map on read.
    emitters: list[str] = Field(default_factory=list)
    #: The witness's own counts for this item (clean / contaminated /
    #: unclaimed), verbatim from the run.
    witness: dict = Field(default_factory=dict)
    #: WHAT EACH OF THOSE EMITTERS ACTUALLY MEASURED. Empty on an entry
    #: written before this field existed, which `calibration_diff` reports
    #: as UNMEASURED rather than as a change — absence is a read.
    measurements: list[EmitterMeasurement] = Field(default_factory=list)


class CalibrationRun(BaseModel):
    """ONE ENTRY IN THE LINEAGE. Never edited, never dropped.

    A REFUSED RUN IS AN ENTRY TOO, and that is deliberate — the same reason
    `night_run` records a DECLINED night and `commissioning` stores a refused
    pass: "did it run last night?" must be a read, never a silence
    indistinguishable from the seam being broken."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    at: float = Field(default_factory=time.time)
    #: One of `RUN_KINDS` (something was measured) or `KIND_FINGERPRINT` /
    #: `KIND_DECLARATION`.
    kind: str = KIND_RUN
    label: str = ""
    status: str = ""
    detail: str = ""
    refusal: str = ""
    seconds: float = 0.0
    session_id: str = ""
    pose_id: str = ""
    #: The QUEUE RUN this was executed as, so the ordinary run surfaces
    #: (`GET /api/rooms/capture-queue`) and the lineage name the same thing.
    queue_run_id: str = ""
    #: WHICH ITEMS this run declared, by name — a calibration whose
    #: declaration is edited later must still be readable against what each
    #: past run actually asked for.
    items: list[ItemOutcomeRecord] = Field(default_factory=list)
    #: THE DECLARATION THIS ENTRY ACTUALLY RAN, verbatim, in the capture
    #: queue's own item shape. A `run` carries the whole declaration as it
    #: stood; an `amendment` carries only the named subset it re-measured,
    #: WITH whatever this amendment overrode. Kept because the declaration
    #: on the calibration is the CURRENT one and an edit moves it: without
    #: this, "what did run 3 ask for" stops being answerable the moment
    #: run 4 asks for something else.
    declared: list[dict] = Field(default_factory=list)
    #: THE NAMES THIS AMENDMENT ASKED FOR, as he wrote them. Empty on every
    #: other kind. Kept separately from `declared` because an amendment that
    #: names one item and overrides its granularity has two facts in it, and
    #: a reader deserves both.
    amended: list[str] = Field(default_factory=list)
    #: FOR A `declaration` ENTRY: the WHOLE declaration as it stood BEFORE
    #: the edit (items, camera regime, envelope, name, placement). This is
    #: what makes "append-only, never rewritten" true of the declaration and
    #: not only of the run list — the prior declaration is recoverable from
    #: the lineage rather than overwritten in place. Empty on every other
    #: kind.
    previous_declaration: dict = Field(default_factory=dict)
    #: The pose fingerprint judgement this run was gated on
    #: (spectra/services/pose_fingerprint.Judgement.as_dict()).
    fingerprint: dict = Field(default_factory=dict)
    #: The lever self-test verdict the run's own camera earned
    #: (spectra/services/lever_selftest.Verdict.as_dict()), or {} on a
    #: browser session, which this step leaves untouched.
    lever: dict = Field(default_factory=dict)
    #: The regime this run was measured in, and what the camera answered.
    camera: dict = Field(default_factory=dict)
    #: WHETHER THIS RUN'S NUMBERS MAY BE COMPARED with earlier runs of the
    #: same calibration, and why not when they may not. Gated on the pose
    #: fingerprint matching AND the pinned regime being identical.
    comparable: bool = False
    comparable_note: str = ""
    #: emitter_id -> the id of the run whose footprint this one replaced.
    #: PER EMITTER, which is the whole of amend-in-part: a run that
    #: re-measured three ranges of a wrapped TV supersedes those three and
    #: leaves the rest of that carrier's footprints exactly where they were,
    #: still credited to the run that took them. No measurement ever
    #: disappears from the record without the record saying what replaced it.
    superseded: dict[str, str] = Field(default_factory=dict)
    #: THE MIXING GATE'S OWN WORKING, for an amendment: which carriers it
    #: would have left holding footprints from more than one run, which
    #: emitters it was taking, and the claim (or the refusal) that decided
    #: it. `spectra/services/amendment.MixVerdict.as_dict()`. Empty on every
    #: full run, which mixes nothing by construction.
    mix: dict = Field(default_factory=dict)
    #: THE CARRIERS THIS ENTRY LEFT HOLDING FOOTPRINTS FROM MORE THAN ONE
    #: RUN, and the claim that made mixing honest. Empty when nothing mixed.
    #: `spectra/services/amendment.py` is the binding statement: mixing is
    #: allowed ONLY when the pose fingerprint MATCHED and the pinned regime
    #: is identical to the run that took the footprints being left in place.
    mixed_carriers: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def emitters(self) -> list[str]:
        out: list[str] = []
        for item in self.items:
            for e in item.emitters:
                if e not in out:
                    out.append(e)
        return out


class Calibration(BaseModel):
    """The artefact. See the module docstring."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    room_id: str
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    pose: PoseFingerprint = Field(default_factory=PoseFingerprint)
    camera: PinnedCamera = Field(default_factory=PinnedCamera)
    #: THE LEVER SELF-TEST THAT PROVED THIS REGIME reaches the sensor — the
    #: step-one check, carried here so "these numbers were taken by a camera
    #: whose exposure control was measured, not merely read back" is a
    #: property of the artefact and not only of one run's log.
    lever: dict = Field(default_factory=dict)
    envelope: Envelope = Field(default_factory=Envelope)
    #: THE DECLARED QUEUE, in `capture_queue`'s own item shape. Stored as
    #: plain dicts because that module's `parse_items` is the ONE validator
    #: and re-typing its fields here would be a second one that drifts.
    items: list[dict] = Field(default_factory=list)
    #: THE TAG REGISTRY — every physical ArUco tag this calibration's pose
    #: may be anchored on, with the side length HE MEASURED after printing.
    #: EMPTY by default, so its arrival changed nothing about any record.
    #: Storage only in this step: nothing reads it, and there is no
    #: tag-detection code anywhere in this build. See `TagRegistration`.
    tags: list[TagRegistration] = Field(default_factory=list)
    #: APPEND-ONLY. `append_run` is the only thing that writes it.
    runs: list[CalibrationRun] = Field(default_factory=list)

    @property
    def ran(self) -> bool:
        """Has this calibration ever actually measured anything? ABSENCE IS A
        READ: a calibration that never ran says so, rather than reporting an
        empty result set that looks like a run finding nothing.

        AN AMENDMENT COUNTS. It drove lights and produced footprints; a
        calibration whose only measurement came from one would otherwise
        read as never having run."""
        return any(r.kind in RUN_KINDS for r in self.runs)

    @property
    def last_run(self) -> Optional[CalibrationRun]:
        """The most recent entry that MEASURED something, amendment or not —
        which is what the regime half of the comparability claim is compared
        against, and what a reader means by "the last run"."""
        for r in reversed(self.runs):
            if r.kind in RUN_KINDS:
                return r
        return None

    @property
    def last_full_run(self) -> Optional[CalibrationRun]:
        """The most recent entry that ran the WHOLE declaration. Distinct
        from `last_run` on purpose: "when did this calibration last measure
        everything it declares" and "when did it last measure anything" are
        different questions and an amendment answers only the second."""
        for r in reversed(self.runs):
            if r.kind == KIND_RUN:
                return r
        return None

    def run(self, run_id: str) -> Optional[CalibrationRun]:
        return next((r for r in self.runs if r.id == run_id), None)

    def append_run(self, entry: CalibrationRun) -> CalibrationRun:
        """THE ONLY MUTATOR OF THE LINEAGE, and it appends. There is
        deliberately no counterpart that edits or removes one."""
        self.runs.append(entry)
        self.updated_at = time.time()
        return entry

    def emitter_origin(self) -> dict[str, str]:
        """emitter_id -> the id of the MOST RECENT run of this calibration
        that produced it. What a new run's `superseded` map is computed
        against, and what a provenance read answers with."""
        origin: dict[str, str] = {}
        for r in self.runs:
            if r.kind not in RUN_KINDS:
                continue
            for e in r.emitters:
                origin[e] = r.id
        return origin

    def tag(self, tag_id: int) -> Optional[TagRegistration]:
        return next((t for t in self.tags if t.tag_id == tag_id), None)

    def as_summary(self) -> dict:
        """The small view a list renders — never the whole lineage."""
        last = self.last_run
        return {"id": self.id, "name": self.name, "room_id": self.room_id,
                "tags": len(self.tags),
                "created_at": self.created_at, "updated_at": self.updated_at,
                "placement": self.pose.placement,
                "pose_established": self.pose.established,
                "pose_discriminating": self.pose.discriminating,
                "declared_items": len(self.items),
                "runs": len([r for r in self.runs if r.kind == KIND_RUN]),
                "amendments": len([r for r in self.runs
                                   if r.kind == KIND_AMENDMENT]),
                "ran": self.ran,
                "camera": self.camera.model_dump(),
                "envelope": self.envelope.model_dump(),
                "last_run": ({"id": last.id, "at": last.at,
                              "status": last.status, "detail": last.detail,
                              "comparable": last.comparable}
                             if last is not None else None)}


def declaration_snapshot(cal: "Calibration") -> dict:
    """THE WHOLE DECLARATION, as it stands right now — what a `declaration`
    entry keeps as `previous_declaration` so the prior one survives an edit.

    Everything a human declares and nothing a run measures: the pose
    fingerprint, the lever verdict and the lineage are all excluded, because
    an edit does not touch them and a snapshot that carried them would grow
    the append-only file by the whole record on every rename."""
    return {"name": cal.name, "placement": cal.pose.placement,
            "camera": cal.camera.model_dump(),
            "envelope": cal.envelope.model_dump(),
            "items": [dict(i) for i in cal.items],
            "tags": [t.model_dump() for t in cal.tags]}


def new_run_entry(kind: str = KIND_RUN, **kw: Any) -> CalibrationRun:
    return CalibrationRun(kind=kind, **kw)
