"""AMEND-IN-PART — re-measuring a NAMED SUBSET of a calibration, and the one
gate that decides whether the result may sit beside what the map already
holds.

WHY IT EXISTS, and it is the captain's own framing of what makes the
practice his rather than ours: he (or the fleet, unattended) can change one
fixture without spending an evening re-taking everything. The plan's §4 in
his words — "amending a calibration = declaring a SUBSET (one fixture, one
changed parameter) and re-running just it under the same pose fingerprint
and pinned settings; the record appends the amendment with its own evidence
and supersedes only the touched footprints."

AN AMENDMENT IS AN ORDINARY RUN OF A SMALLER DECLARATION. It goes through
`capture_runs` — the ONE seam — so the exposure lock, the lever self-test,
the ambient gate, the witness, the hold ceiling, the one-run-at-a-time lock
and the ownership boundary all apply exactly as they do to a button press.
Nothing here acquires a capability a full run lacks, and there is no
amendment mode anywhere in this codebase that a capture behaves differently
under. THE NEVER-TAKES-HIS-ROOM BOUNDARY IS UNMOVED: an amendment runs only
when SPECTRA already holds the lights and is REFUSED by `mapping_refusals`'
own sentence when it does not. No piece of this design needed an exception
to it, which is worth saying because the brief asked to be told if one did.

═══ THE GATE, and it is the whole honesty of this step ═══

Supersession is PER EMITTER, so an amendment that re-measures three ranges
of a wrapped television leaves the rest of that television's footprints
exactly where they were. THOSE FOOTPRINTS ARE THEN READ TOGETHER — by a
room effect resolving one carrier's gain mask, by a diff, by his eye on the
Rooms page — and a footprint is `lit - dark` IN ONE CAMERA'S OWN VIEW AND
ONE CAMERA'S OWN BRIGHTNESS SCALE. Two readings of one carrier are
therefore comparable with each other on exactly two conditions, and both
are already the model's own:

  1. THE POSE FINGERPRINT MATCHED. Not `cannot_tell`, not `room_changed`,
     not `unestablished` — MATCHED. This is stricter than what stops a full
     run, and deliberately so: a full run replaces the whole carrier, so its
     numbers are internally consistent whatever the camera did and only the
     comparability CLAIM against earlier runs is withheld. A mixed carrier
     has no such fallback — the inconsistency is inside one carrier's own
     footprints, where nothing downstream could ever notice it.

  2. THE PINNED REGIME IS IDENTICAL to the one the run that took the KEPT
     footprints used — every lever, including which ones are unset
     (`PinnedCamera.same_as`). Two regimes are two scales, and the pose
     matching perfectly does not save them.

WHEN EITHER FAILS THE AMENDMENT REFUSES BY NAME AND NOTHING RUNS
(`mapping_refusals.amendment_would_mix`), naming the two ways out: re-take
the WHOLE carrier (`whole_carrier=True`, which mixes nothing and so is
always allowed), or put the camera back and re-anchor the pose. IT NEVER
MIXES SILENTLY, and there is deliberately no force flag for this one. A
force flag exists for the pose gate on a FULL run because an explicit press
there costs only a comparability claim the record then names; here it would
cost a carrier whose own footprints disagree with each other with nothing
able to tell — the difference between a stated limitation and a quiet lie.

WHEN IT PASSES, MIXING IS STILL NEVER SILENT: the entry records
`mixed_carriers` and carries `mapping_refusals.amendment_mixed_note`, and
provenance keeps saying which run each surviving footprint came from
(`calibration_store.provenance` — a READ against the live map, never a
copy).

AN AMENDMENT THAT MIXES NOTHING SKIPS THE GATE ENTIRELY, by construction
and not by exception: if every stored footprint of every carrier it touches
is being re-measured, there is no second reading left to be inconsistent
with. That is the common case — amending one fixture of a room usually
re-takes that whole fixture — and it is why the gate is not a tax on the
ordinary path.

A FOOTPRINT THIS CALIBRATION NEVER PRODUCED counts as a failed gate, not a
pass. A carrier mapped from the Rooms page button carries no pose and no
regime this record knows, so "the camera had not moved since" is not
something anybody can say about it; unknown provenance is `cannot_tell` one
level up, and this module treats it the same way for the same reason.

WHAT IS NOT HERE: any judgement about whether the amended numbers DIFFER
from the ones they replaced. That is `spectra/services/calibration_diff.py`,
computed from stored data and never narrated.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from spectra.models.calibration import RUN_KINDS, Calibration, PinnedCamera
from spectra.models.room_map import RoomMap
from spectra.services import mapping_refusals

logger = logging.getLogger(__name__)

#: The item fields an amendment may override for its own run. Deliberately
#: the CAPTURE parameters and never `kind` or `room_id`: changing either of
#: those makes it a different declaration, which is an edit
#: (`PUT /api/calibrations/{id}`) and not an amendment.
OVERRIDABLE = ("granularity", "block_pixels", "dark_settle_s", "lit_settle_s",
               "dark_capture_s", "lit_capture_s", "carrier_ids",
               "emitter_ids", "retries", "targets", "per_fixture",
               "mapper_id", "repeat")


def item_name(item: dict, index: int) -> str:
    """WHAT HE CALLS ONE DECLARED ITEM. Its label when it has one, else its
    position — the same name `capture_queue.QueueItem.name` renders, so an
    amendment names items the way the queue log already does."""
    label = str((item or {}).get("label") or "").strip()
    return label or f"item {index + 1}"


def declared_names(cal: Calibration) -> list[str]:
    return [item_name(item, i) for i, item in enumerate(cal.items)]


# ── resolving the subset ───────────────────────────────────────────────────

@dataclass
class Subset:
    """The items an amendment will actually run, and what it was asked."""
    items: list[dict] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    refusal: str = ""


def resolve_subset(cal: Calibration, names: list[str],
                   overrides: Optional[dict] = None,
                   whole_carrier: bool = False) -> Subset:
    """The named declared items, with this amendment's overrides applied.

    A NAME THAT IS NOT DECLARED IS A REFUSAL, never a skip: an amendment
    that quietly measured three of the four things he named would report
    success while leaving the fourth at last month's reading.

    `whole_carrier` DROPS `emitter_ids` from the resolved items — the named
    way out of the mixing gate below, and the reason that gate can refuse
    outright rather than needing a force flag. It never widens beyond the
    carriers the item already names: "re-take the whole carrier" means the
    whole of THAT carrier, not the whole room.

    The result is still validated by `capture_queue.parse_items` at the
    caller — the ONE validator — so an override with a typo in it is refused
    before the room goes dark."""
    wanted = [str(n).strip() for n in (names or []) if str(n).strip()]
    if not wanted:
        return Subset(refusal=mapping_refusals.amendment_nothing_named())
    by_name = {item_name(item, i): (i, item)
               for i, item in enumerate(cal.items)}
    missing = [n for n in wanted if n not in by_name]
    if missing:
        return Subset(refusal=mapping_refusals.amendment_unknown_item(
            missing, declared_names(cal)))

    out: list[dict] = []
    for name in wanted:
        _, item = by_name[name]
        merged = dict(item)
        for key, value in (overrides or {}).items():
            if key not in OVERRIDABLE:
                return Subset(refusal=(
                    f"{key!r} is not something an amendment may change for "
                    f"one run — it may change "
                    f"{mapping_refusals.and_list(list(OVERRIDABLE))}. "
                    f"Changing anything else is an edit to the declaration, "
                    f"which is recorded as its own entry in the lineage."))
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        if whole_carrier:
            merged.pop("emitter_ids", None)
        # The label travels with the item so the queue log, the lineage entry
        # and his own name for it are one name.
        merged.setdefault("label", name)
        out.append(merged)
    return Subset(items=out, names=wanted)


# ── the gate ───────────────────────────────────────────────────────────────

@dataclass
class MixVerdict:
    """WOULD THIS AMENDMENT LEAVE ONE CARRIER HOLDING TWO NIGHTS' WORK, and
    may those two readings be read together?"""
    #: carrier -> the emitter ids this amendment would leave in place.
    kept: dict = field(default_factory=dict)
    #: carrier -> the emitter ids this amendment would re-measure.
    taking: dict = field(default_factory=dict)
    refusal: str = ""
    note: str = ""

    @property
    def mixes(self) -> bool:
        return bool(self.kept)

    @property
    def carriers(self) -> list[str]:
        return sorted(self.kept)

    def as_dict(self) -> dict:
        return {"mixes": self.mixes, "carriers": self.carriers,
                "kept": {c: sorted(v) for c, v in self.kept.items()},
                "taking": {c: sorted(v) for c, v in self.taking.items()},
                "refusal": self.refusal, "note": self.note}


def judge_mix(cal: Calibration, room: Optional[RoomMap], items: list[dict],
              pose_verdict: str) -> MixVerdict:
    """THE GATE. Computed from STORED DATA before anything is driven, so his
    room never goes dark for an amendment that was always going to refuse.

    `pose_verdict` is `pose_fingerprint.Judgement.verdict` — this module
    never re-derives it and holds no opinion of its own about poses.

    IT REASONS OVER THE EMITTER IDS AN ITEM NAMES (`emitter_ids`), because
    those are the only scoped runs that can leave a sibling behind: a
    carrier-scoped or unscoped item re-takes each carrier it touches WHOLE
    (`room_mapping.scope_plan` drops it, footprints of any older granularity
    included), so there is nothing left to be inconsistent with. That is
    also why changing a carrier's granularity is an ordinary ungated
    amendment and re-measuring PART of one is not.

    IT PREDICTS FROM STORED DATA and is not the last word: if a run's own
    plan turns out to mix where this expected it would not,
    `scope_plan`'s one-granularity-per-carrier invariant is the second net
    and refuses there, having spent nothing but the pose check."""
    verdict = MixVerdict()
    if room is None:
        return verdict
    by_carrier: dict = {}
    for item in items:
        for emitter_id in (item.get("emitter_ids") or []):
            if emitter_id:
                by_carrier.setdefault(_carrier_of(room, emitter_id),
                                      set()).add(emitter_id)
    for carrier_id, taking in sorted(by_carrier.items()):
        if not carrier_id:
            continue
        verdict.taking[carrier_id] = set(taking)
        left = {f.emitter_id for f in room.emitters_for_carrier(carrier_id)
                } - taking
        if left:
            verdict.kept[carrier_id] = left
    if not verdict.mixes:
        return verdict

    reason = _incomparable_reason(cal, pose_verdict, verdict.kept)
    if reason:
        verdict.refusal = mapping_refusals.amendment_would_mix(
            mapping_refusals.and_list(verdict.carriers), reason,
            sum(len(v) for v in verdict.kept.values()))
    else:
        verdict.note = mapping_refusals.amendment_mixed_note(verdict.carriers)
    return verdict


def _carrier_of(room: RoomMap, emitter_id: str) -> str:
    """The carrier a NAMED emitter belongs to, from the stored map.

    An id the map has never seen resolves to its own carrier prefix if it
    has one, and to itself otherwise — enough to group the request, and
    never enough to claim the map holds something it does not. Whether the
    id resolves to a real emitter at all is `room_mapping.scope_plan`'s
    question, asked against the live plan rather than guessed at here."""
    fp = room.footprint(emitter_id)
    if fp is not None:
        return fp.carrier
    return emitter_id.split(":", 1)[0] if ":" in emitter_id else emitter_id


def _incomparable_reason(cal: Calibration, pose_verdict: str,
                         kept: dict) -> str:
    """WHY the kept footprints may not be read beside new ones, or "" when
    they may. Both halves are checked and the FIRST failure is reported —
    they fail for different reasons and a merged sentence would hide which.

    THE POSE HALF IS STRICTER HERE THAN IT IS FOR A FULL RUN, and the module
    docstring says why: a full run replaces the whole carrier, so only its
    claim against earlier runs is withheld; a mixed carrier's inconsistency
    is inside its own footprints."""
    if pose_verdict != mapping_refusals.POSE_MATCH:
        if pose_verdict == mapping_refusals.POSE_CAMERA_MOVED:
            return ("the camera has moved since they were taken, so they see "
                    "the room from somewhere else.")
        if pose_verdict == mapping_refusals.POSE_UNESTABLISHED:
            return ("this calibration has no pose recorded, so nothing can "
                    "say whether the camera is where it was when they were "
                    "taken.")
        if pose_verdict == mapping_refusals.POSE_ROOM_CHANGED:
            return ("the room has changed since they were taken — the "
                    "readings are each good and they are good about "
                    "different rooms.")
        return ("the pose check could not tell whether the camera is where "
                "it was when they were taken, and a mixed carrier has no "
                "way to notice later that it was not.")

    origin = cal.emitter_origin()
    now = cal.camera
    for carrier_id in sorted(kept):
        for emitter_id in sorted(kept[carrier_id]):
            run_id = origin.get(emitter_id)
            if not run_id:
                # NOT PRODUCED BY THIS CALIBRATION — mapped from the Rooms
                # page, or by a calibration that no longer exists. Nobody can
                # say what pose or what regime took it, so it is the same
                # answer as `cannot_tell` and for the same reason.
                return (f"{emitter_id} was not measured by this calibration, "
                        f"so nothing records the camera settings or the pose "
                        f"it was taken under.")
            run = cal.run(run_id)
            was = PinnedCamera(**((getattr(run, "camera", None) or {})
                                  .get("pinned") or {}))
            if not now.same_as(was):
                return (f"{emitter_id} was measured with different camera "
                        f"settings ("
                        f"{'; '.join(was.differences(now))}).")
    return ""


def amendable(cal: Calibration) -> bool:
    """Is there anything to amend? A calibration that has never measured
    anything has no subset worth re-taking — run it first."""
    return bool(cal.items) and any(r.kind in RUN_KINDS for r in cal.runs)

