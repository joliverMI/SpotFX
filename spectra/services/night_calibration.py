"""A CALIBRATION AS THE NIGHT'S DECLARED QUEUE — step four of the
calibration practice (`/home/javi/fleet-spotfx/data/calibration-practice-
plan/plan.md` §7.4).

READ FIRST: `spectra/services/night_run.py` (the boundary and the planned
end), `spectra/services/calibration_runs.py` (what running a calibration
does), `spectra/services/amendment.py` (when a partial one is honest). This
module is the SEAM between them and holds no opinion of its own about any
of it.

WHAT IT MAKES TRUE, and it is the exact sentence of his standing direction:
"restart and edit the cals if needed without my intervention" — AT NIGHT.
Until this, the night ran a bare list of capture items and produced a room
map that could not say what took it; a calibration ran only when somebody
pressed something. Now the night's declaration may NAME a calibration, and
what the night measures lands in that calibration's own lineage exactly as
a daytime run does.

═══ ONE RECORD SYSTEM, ONE VALIDATOR, NO NIGHT MODE ═══

THE ITEMS ARE THE CALIBRATION'S OWN. A full run declares `cal.items`; an
amendment declares `amendment.resolve_subset(...)`'s output — the SAME
function the `/amend` route calls, so a night amendment and a pressed one
resolve identically, including the refusals for an item this calibration
does not declare. Both are then validated by `capture_queue.parse_items`,
the ONE validator, before anything is priced or held.

THE RUN IS `calibration_runs`' OWN. The night calls `run_calibration` /
`run_amendment` and passes `capture_queue.run_queue`'s `guard` and `save`
seams through them — it does not reimplement the walk, and it cannot skip a
gate, because there is no second path to skip one on. Every gate the button
applies applies here: the exposure lock, the lever self-test, the pose
fingerprint, the ambient stability gate, the witness, the hold ceiling, the
one-run-at-a-time lock and the ownership refusal.

THE RECORD IS THE CALIBRATION'S OWN. The night's record carries WHICH
calibration ran and the entry's own verdict; the measurements, the lineage
and the provenance live in `storage/spectra/calibrations/<id>.json` where a
pressed run puts them. There is no second store and no night-only copy of
anything.

═══ THE BOUNDARY IS UNTOUCHED ═══

A start event arriving while SPECTRA does not hold the room is DECLINED,
before the declaration is even resolved — this module is never reached on
that path. Nothing here asks for the room, waits for a handover, or knows
that nobody is awake. No piece of this design needed an exception to that,
which is worth saying plainly because the brief asked to be told if one did.

═══ THE HONESTY GATE APPLIES AT 2AM EXACTLY AS AT 2PM ═══

An amendment's own gate — the pose fingerprint must have MATCHED and the
pinned regime must be identical, or nothing runs — is `amendment.judge_mix`,
asked inside `calibration_runs`, and this module does not go near it. A
night amendment that fails it REFUSES BY NAME and the night records that
refusal as its outcome (`night_run.STATE_REFUSED`), which is a read in the
morning. It is never a silent skip, and it is never quietly widened into a
full re-take he did not declare: WHICH runs happen is his declaration, and
substituting a different one while he sleeps is precisely the class of
helpfulness this whole seam refuses.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from spectra.models.calibration import Calibration
from spectra.services import (amendment, calibration_store, capture_queue,
                              mapping_refusals)

logger = logging.getLogger(__name__)

#: The two shapes a calibration-backed night takes. `run` measures the whole
#: declaration; `amend` measures a named subset of it. The words are the
#: lineage's own (`models/calibration.KIND_RUN` / `KIND_AMENDMENT`) so a
#: reader never has to translate between two vocabularies.
MODE_RUN = "run"
MODE_AMEND = "amendment"

#: How the morning read and every log line name the two, in his nouns.
MODE_WORDS = {MODE_RUN: "calibration", MODE_AMEND: "an amendment to"}


@dataclass
class Target:
    """WHAT A CALIBRATION-BACKED NIGHT DECLARATION SAYS, parsed.

    `refusal` non-empty means the declaration itself is wrong — a name for
    something that is not stored, or two declarations in one file. It is
    refused at DECLARATION time (`night_run.save_declaration`) while he is
    awake, and again at start time in case the calibration was deleted in
    between."""
    calibration_id: str = ""
    mode: str = MODE_RUN
    #: For an amendment: the declared item names, his own words.
    items: list[str] = field(default_factory=list)
    overrides: dict = field(default_factory=dict)
    whole_carrier: bool = False
    force: bool = False
    refusal: str = ""

    @property
    def declared(self) -> bool:
        return bool(self.calibration_id)

    @property
    def word(self) -> str:
        return MODE_WORDS[self.mode]

    def as_dict(self) -> dict:
        return {"calibration_id": self.calibration_id, "mode": self.mode,
                "items": list(self.items), "overrides": dict(self.overrides),
                "whole_carrier": self.whole_carrier, "force": self.force}


def parse_target(declaration: Optional[dict]) -> Target:
    """Read the calibration half of a night declaration.

    A declaration with no `calibration_id` is not an error and is not this
    module's business — it is the plain item list the night has always
    taken, and `Target.declared` is False for it.

    A declaration carrying BOTH is refused: two declarations in one file is
    a question nobody would be awake to answer, and picking one for him is
    the guess this seam exists not to make."""
    body = declaration or {}
    cal_id = str(body.get("calibration_id") or "").strip()
    if not cal_id:
        return Target()
    if body.get("items"):
        return Target(refusal=mapping_refusals.night_calibration_ambiguous())
    amend = body.get("amend")
    if not amend:
        return Target(calibration_id=cal_id, mode=MODE_RUN,
                      force=bool(body.get("force")))
    if not isinstance(amend, dict):
        return Target(refusal=(
            "the 'amend' part of a night declaration names the declared "
            "items to re-measure and, optionally, what to override for that "
            "one run — it is an object, not a bare value."))
    return Target(calibration_id=cal_id, mode=MODE_AMEND,
                  items=[str(n) for n in (amend.get("items") or [])],
                  overrides=dict(amend.get("overrides") or {}),
                  whole_carrier=bool(amend.get("whole_carrier")),
                  force=bool(amend.get("force") or body.get("force")))


@dataclass
class Resolved:
    """The calibration and the item dicts a night will actually run.

    `items` is what gets PRICED against the planned end and what names the
    fixtures the night will turn on. The run itself resolves the same list
    again from the calibration, through the same functions — this is a read
    ahead of the room going dark, never a second declaration."""
    calibration: Optional[Calibration] = None
    items: list[dict] = field(default_factory=list)
    refusal: str = ""
    #: The machine word for `NightRun.refusal` when this refuses.
    refusal_kind: str = ""


def resolve(target: Target) -> Resolved:
    """The calibration, and the items it will run tonight.

    IT RESOLVES THROUGH THE SAME FUNCTIONS THE ROUTE DOES —
    `amendment.resolve_subset` for a subset and the calibration's own
    declaration for a full run — then hands the result to
    `capture_queue.parse_items`, the one validator. A night that names an
    item this calibration does not declare is refused HERE, before the room
    goes dark, with `amendment`'s own sentence.

    THE RESOLVED ITEMS ARE FOR PRICING ONLY. The run gets its items from the
    calibration again, inside `calibration_runs`, so this can never become a
    second declaration that drifts from the one that is measured."""
    out = Resolved()
    if target.refusal:
        out.refusal, out.refusal_kind = target.refusal, "bad_declaration"
        return out
    cal = calibration_store.load(target.calibration_id)
    if cal is None:
        out.refusal = mapping_refusals.night_calibration_missing(
            target.calibration_id)
        out.refusal_kind = "no_calibration"
        return out
    out.calibration = cal
    if not cal.items:
        out.refusal = mapping_refusals.calibration_nothing_declared()
        out.refusal_kind = "nothing_declared"
        return out
    if target.mode == MODE_AMEND:
        subset = amendment.resolve_subset(cal, target.items, target.overrides,
                                          whole_carrier=target.whole_carrier)
        if subset.refusal:
            out.refusal, out.refusal_kind = subset.refusal, "amendment"
            return out
        declared = subset.items
    else:
        declared = [dict(i) for i in cal.items]
    try:
        capture_queue.parse_items(declared)
    except ValueError as exc:
        out.refusal = (f"the declaration of calibration '{cal.name}' no "
                       f"longer parses: {exc}")
        out.refusal_kind = "bad_declaration"
        return out
    out.items = declared
    return out


async def execute(target: Target, resolved: Resolved, *, guard=None,
                  save=None, label: str = ""):
    """Run it, through `calibration_runs` and nothing else.

    Returns `(calibration, entry)` — the SAVED calibration and the one
    lineage entry, exactly what the `/run` and `/amend` routes return, so a
    night's outcome and a press's outcome are the same object read the same
    way."""
    from spectra.services import calibration_runs
    cal = resolved.calibration
    if target.mode == MODE_AMEND:
        return await calibration_runs.run_amendment(
            cal, list(target.items), overrides=dict(target.overrides),
            whole_carrier=target.whole_carrier, force=target.force,
            label=label, guard=guard, save=save)
    return await calibration_runs.run_calibration(
        cal, force=target.force, label=label, guard=guard, save=save)


def record(target: Target, resolved: Resolved, entry=None) -> dict:
    """WHAT THE NIGHT'S OWN RECORD CARRIES ABOUT THE CALIBRATION — a link
    and a verdict, never a copy of the lineage.

    The lineage lives in the calibration's own file and is the thing that
    must never be pruned; the night store is bounded and rewritten. Copying
    an entry in here would make the bounded file the one that grows and give
    two answers to "what did this measure"."""
    cal = resolved.calibration
    body = {
        **target.as_dict(),
        "name": getattr(cal, "name", ""),
        "room_id": getattr(cal, "room_id", ""),
        "declared_items": len(resolved.items),
    }
    if entry is None:
        return body
    return {**body,
            "entry_id": entry.id, "entry_kind": entry.kind,
            "status": entry.status, "detail": entry.detail,
            "refusal": entry.refusal,
            "emitters": entry.emitters,
            "applied": entry.applied,
            "unapplied_reason": entry.unapplied_reason,
            "superseded": dict(entry.superseded),
            "comparable": entry.comparable,
            "comparable_note": entry.comparable_note,
            "fingerprint": dict(entry.fingerprint),
            "mixed_carriers": list(entry.mixed_carriers),
            "notes": list(entry.notes)}
