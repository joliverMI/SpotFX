"""WHAT CHANGED BETWEEN TWO OF A CALIBRATION'S OWN SELVES — computed from
stored data, never narrated.

WHY IT EXISTS. Amendments make a calibration cheap to re-run in part, and a
lineage of twelve entries is only worth keeping if a person can ask it a
question. The plan's own claim is that "two calibrations with the same
fingerprint and settings are comparable across time — which is what makes
drift DETECTABLE instead of arguable", and this module is what turns that
sentence into an answer: which emitters were re-measured, which of them moved
BEYOND THE INSTRUMENT'S OWN NOISE, and which appeared or vanished.

IT READS THE LINEAGE, NOT THE ROOM MAP, and that is the whole reason
`ItemOutcomeRecord.measurements` exists. `room_maps.json` keeps only the
LATEST footprint per emitter, so the moment a re-run supersedes one the
earlier grid is gone; a diff against the live map could only ever compare
the newest reading with itself. Each entry carries its own small weight row
per emitter, so two entries can be compared long after both their footprints
have been replaced.

═══ THREE THINGS IT REFUSES TO DO ═══

IT NEVER CLAIMS A COMPARISON THE RECORD DOES NOT SUPPORT. Weights are `lit -
dark` in one camera's own view and one camera's own brightness scale, so two
entries' numbers mean the same thing only when the pose matched and the
pinned regime was identical. `comparable` on the result says whether they
do, with the reason when they do not — and the numbers are still reported,
because withholding a measurement he asked for teaches him nothing. What is
withheld is the CLAIM, exactly as it is everywhere else on this path.

IT NEVER TREATS ABSENCE AS A CHANGE. An entry written before measurements
were recorded carries none; its emitters are reported UNMEASURED, and a
diff whose two sides are both unmeasured says so rather than reporting
"nothing moved", which would read identically to a room that had not
drifted. Absence is a read — `EmitterFootprint.unseen`'s own rule, two
levels up.

IT NEVER TUNES ITS OWN THRESHOLD. `NOISE_FRACTION` is DERIVED, in
`commission_compare.py`'s pre-registration discipline: it is
`exposure_test.TIE_FRACTION`, the instrument's own measured two-reading
wobble, which that module already uses to refuse calling a 3% difference a
win. Reusing it rather than picking a second number is the point — one
instrument, one idea of what its own noise is. Moving it is a decision about
what this diff CLAIMS, not a tweak to make a run read green.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from spectra.models.calibration import (RUN_KINDS, Calibration,
                                        CalibrationRun, PinnedCamera)
from spectra.services import exposure_test

logger = logging.getLogger(__name__)

#: HOW FAR AN EMITTER'S WEIGHT MAY MOVE between two entries and still be the
#: instrument repeating itself rather than the room changing.
#:
#: DERIVED, not chosen: `exposure_test.TIE_FRACTION` is this codebase's own
#: measured answer to "how much do two readings of the SAME regime differ",
#: and it is used there to refuse calling a 3% difference a win. A footprint
#: weight is a sum over 2,304 cells of a noisy difference at both ends, so
#: the same wobble governs both questions. One instrument, one idea of its
#: own noise.
NOISE_FRACTION = exposure_test.TIE_FRACTION

#: The words a per-emitter row can carry. `unmeasured` is a state and never
#: a change — see the module docstring.
SAME = "same"
MOVED = "moved"
APPEARED = "appeared"
VANISHED = "vanished"
LOST_SIGHT = "lost_sight"
CAME_INTO_VIEW = "came_into_view"
UNMEASURED = "unmeasured"


@dataclass
class EmitterDelta:
    emitter_id: str
    label: str = ""
    carrier_id: str = ""
    state: str = SAME
    before: Optional[float] = None
    after: Optional[float] = None
    #: after / before. None whenever either side is missing or zero — a
    #: ratio against nothing is not a number, and reporting one would be the
    #: confident wrong answer this whole path is built to refuse.
    ratio: Optional[float] = None
    seen_before: bool = True
    seen_after: bool = True
    note: str = ""

    def as_dict(self) -> dict:
        return {"emitter_id": self.emitter_id, "label": self.label,
                "carrier_id": self.carrier_id, "state": self.state,
                "before": self.before, "after": self.after,
                "ratio": round(self.ratio, 3) if self.ratio is not None
                else None,
                "seen_before": self.seen_before, "seen_after": self.seen_after,
                "note": self.note}


@dataclass
class Diff:
    calibration_id: str = ""
    a: str = ""
    b: str = ""
    a_at: float = 0.0
    b_at: float = 0.0
    #: WHETHER THE TWO SETS OF NUMBERS MEAN THE SAME THING. Both halves of
    #: the model's own rule: one pose, one pinned regime.
    comparable: bool = False
    comparable_note: str = ""
    deltas: list[EmitterDelta] = field(default_factory=list)
    #: Which declared items each side ran, by name — the reason two entries
    #: can legitimately share no emitters at all.
    a_items: list[str] = field(default_factory=list)
    b_items: list[str] = field(default_factory=list)
    summary: str = ""
    refusal: str = ""

    @property
    def counts(self) -> dict:
        out: dict[str, int] = {}
        for d in self.deltas:
            out[d.state] = out.get(d.state, 0) + 1
        return out

    def as_dict(self) -> dict:
        return {"calibration_id": self.calibration_id, "a": self.a,
                "b": self.b, "a_at": self.a_at, "b_at": self.b_at,
                "comparable": self.comparable,
                "comparable_note": self.comparable_note,
                "a_items": self.a_items, "b_items": self.b_items,
                "counts": self.counts, "summary": self.summary,
                "refusal": self.refusal,
                "noise_fraction": NOISE_FRACTION,
                "deltas": [d.as_dict() for d in self.deltas]}


def measurable_runs(cal: Calibration) -> list[CalibrationRun]:
    """The entries a diff can be taken between: the ones that MEASURED
    something and were not refused. A refused run is a real entry in the
    lineage and has no numbers in it, so offering it as a side of a
    comparison would only produce a page of `unmeasured`."""
    return [r for r in cal.runs
            if r.kind in RUN_KINDS and r.status != "refused"]


def diff(cal: Calibration, a_id: str, b_id: str) -> Diff:
    """WHAT CHANGED between lineage entry `a` and lineage entry `b`.

    Order is his: `a` is the earlier side by convention (the API defaults to
    the two most recent measuring entries in lineage order), and nothing
    here sorts them — a reader who deliberately asks for a comparison the
    other way round gets it the way round they asked."""
    out = Diff(calibration_id=cal.id, a=a_id, b=b_id)
    a, b = cal.run(a_id), cal.run(b_id)
    missing = [i for i, r in ((a_id, a), (b_id, b)) if r is None]
    if missing:
        out.refusal = (f"this calibration has no lineage entry "
                       f"{' or '.join(missing)}. Its entries are: "
                       f"{', '.join(r.id for r in cal.runs) or 'none'}.")
        return out
    for label, run in (("a", a), ("b", b)):
        if run.kind not in RUN_KINDS:
            out.refusal = (
                f"{run.id} is a '{run.kind}' entry — it took a pose or "
                f"recorded an edit and measured nothing, so there is nothing "
                f"in it to compare. Diff two runs or amendments.")
            return out
    out.a_at, out.b_at = a.at, b.at
    out.a_items = [i.name or f"item {i.index + 1}" for i in a.items]
    out.b_items = [i.name or f"item {i.index + 1}" for i in b.items]
    out.comparable, out.comparable_note = _comparable(cal, a, b)

    before, after = _measurements(a), _measurements(b)
    for emitter_id in sorted(set(before) | set(after)):
        out.deltas.append(_delta(emitter_id, before.get(emitter_id),
                                 after.get(emitter_id)))
    out.summary = _summary(out)
    return out


def _measurements(run: CalibrationRun) -> dict:
    """emitter_id -> its measurement row on this entry. An entry written
    before measurements were recorded yields {} and every one of its
    emitters therefore reads UNMEASURED rather than as a change."""
    got = {}
    for item in run.items:
        for m in item.measurements:
            got[m.emitter_id] = m
    return got


def _delta(emitter_id: str, before, after) -> EmitterDelta:
    """One emitter, then and now. EVERY BRANCH REPORTS A STATE THAT IS TRUE
    OF THE RECORD — never a number invented to fill a side that has none."""
    d = EmitterDelta(emitter_id=emitter_id,
                     label=(after.label if after is not None else
                            (before.label if before is not None else "")),
                     carrier_id=(after.carrier_id if after is not None else
                                 (before.carrier_id if before is not None
                                  else "")))
    if before is None and after is None:                # unreachable by
        d.state = UNMEASURED                            # construction; kept
        return d                                        # honest anyway
    if before is None:
        d.state = APPEARED
        d.after, d.seen_after = after.weight, not after.unseen
        d.note = ("this emitter was not measured by the earlier entry — it "
                  "is new to this comparison, not necessarily new to the "
                  "room")
        return d
    if after is None:
        d.state = VANISHED
        d.before, d.seen_before = before.weight, not before.unseen
        d.note = ("the later entry did not measure this emitter — an "
                  "amendment measures only what it names, so this is "
                  "usually that and not a fixture that disappeared")
        return d

    d.before, d.after = before.weight, after.weight
    d.seen_before, d.seen_after = not before.unseen, not after.unseen
    if before.unseen and after.unseen:
        d.state = SAME
        d.note = "the camera saw nothing of it either time"
        return d
    if before.unseen:
        d.state = CAME_INTO_VIEW
        d.note = ("the camera saw nothing of it before and sees it now — a "
                  "second pose, a fixture switched on, or something that was "
                  "in the way")
        return d
    if after.unseen:
        d.state = LOST_SIGHT
        d.note = ("the camera saw it before and sees nothing of it now — "
                  "something is in the way, or the fixture is not lighting")
        return d

    if before.weight > 0.0:
        d.ratio = after.weight / before.weight
        if abs(d.ratio - 1.0) > NOISE_FRACTION:
            d.state = MOVED
            d.note = (f"its light in this room is "
                      f"{'up' if d.ratio > 1.0 else 'down'} "
                      f"{abs(d.ratio - 1.0) * 100:.0f}%, past the "
                      f"{NOISE_FRACTION * 100:.0f}% this instrument repeats "
                      f"itself within")
        else:
            d.state = SAME
    else:
        # A zero before and a real after is not a ratio. It is also not
        # `came_into_view` — that word is reserved for the recorded `unseen`
        # reading, which is a fact the run wrote down rather than one
        # inferred from arithmetic.
        d.state = MOVED if after.weight > 0.0 else SAME
        d.note = ("the earlier reading was zero, so there is no ratio to "
                  "quote")
    return d


def _comparable(cal: Calibration, a: CalibrationRun,
                b: CalibrationRun) -> tuple[bool, str]:
    """DO THESE TWO ENTRIES' NUMBERS MEAN THE SAME THING? The model's own
    rule, unchanged and not re-derived: one pose, one pinned regime.

    Each entry already carries its OWN comparability claim, computed when it
    ran (`calibration_runs._comparability`). This asks the pairwise
    question, which is not the same one: two entries can each be comparable
    with the series and still have been taken under different regimes if a
    declaration edit sat between them."""
    if not (a.comparable and b.comparable):
        which = a if not a.comparable else b
        why = which.comparable_note or "no reason was recorded"
        return False, (
            f"{which.id} does not claim to be comparable with the rest of "
            f"this calibration — {why} The numbers below are real and the "
            f"comparison between them is not claimed.")
    was = PinnedCamera(**((a.camera or {}).get("pinned") or {}))
    now = PinnedCamera(**((b.camera or {}).get("pinned") or {}))
    if not was.same_as(now):
        return False, (
            "these two entries were measured with different camera settings "
            "(" + "; ".join(was.differences(now)) + "). A footprint is a "
            "difference in the camera's own brightness scale, so a changed "
            "regime is a changed scale: the numbers below are real and the "
            "comparison between them is not claimed.")
    return True, ("Both entries matched this calibration's pose and used the "
                  "same pinned camera settings, so their numbers are in the "
                  "same scale and a difference between them is a difference "
                  "in the room.")


def _summary(out: Diff) -> str:
    """The sentence a person reads first. It leads with what a reader is
    asking the diff for — did anything move — and never hides an unmeasured
    side behind a reassuring count."""
    c = out.counts
    if not out.deltas:
        return ("these two entries measured nothing in common — there is "
                "nothing to compare")
    unmeasured = c.get(UNMEASURED, 0)
    parts = []
    if c.get(MOVED):
        parts.append(f"{c[MOVED]} moved beyond the instrument's own noise")
    if c.get(SAME):
        parts.append(f"{c[SAME]} unchanged")
    for word, phrase in ((APPEARED, "newly measured"),
                         (VANISHED, "not measured this time"),
                         (CAME_INTO_VIEW, "came into view"),
                         (LOST_SIGHT, "lost from view")):
        if c.get(word):
            parts.append(f"{c[word]} {phrase}")
    if unmeasured:
        parts.append(f"{unmeasured} with no recorded reading on either side")
    line = ", ".join(parts)
    return line if out.comparable else f"{line} — {out.comparable_note}"
