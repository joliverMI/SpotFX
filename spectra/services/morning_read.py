"""THE MORNING READ — "what ran last night, and what changed", in one read.

HIS BAR, verbatim through the captain: he must be able to answer WHAT RAN
LAST NIGHT AND WHAT CHANGED without asking anyone — which calibration ran,
what it measured, what changed against the previous one, and what waits on
him — as a plain statement in his nouns, NEVER A LOG TO INTERPRET.

That last clause is the whole design constraint, and it is why this module
exists rather than another field on the night record. Every fact this needs
is already stored somewhere honest: `night_run`'s own record, the
calibration's append-only lineage, `calibration_diff`'s computed deltas,
`night_exit`'s read-at-the-light report, the witness summary. What was
missing was a place where they are ONE ANSWER rather than five surfaces he
has to know about and cross-reference at breakfast.

═══ WHAT IT IS NOT ═══

IT COMPUTES NOTHING OF ITS OWN AND JUDGES NOTHING. Every number here is read
from a store or from `calibration_diff`, which is this codebase's one
judgement about whether two sets of numbers may be compared. This module
composes sentences; if a claim is not already made by something else, it is
not made here.

IT NEVER INVENTS AN OUTCOME. A night that declined says so. A night that
refused says which gate. A night still running says so. A night that has
never happened says THAT, rather than returning an empty shape that reads
like a night which measured nothing — the absence-is-a-read standard this
codebase applies to unseen emitters, to unavailable witnesses and to
never-taken poses.

═══ THE FOUR ANSWERS, in his order ═══

  WHAT RAN        the calibration by NAME (or "a declared item list"),
                  whether it was a full run or an amendment, and what
                  happened to it.
  WHAT IT MEASURED   emitters measured, and — the part that matters after a
                  cut-short amendment — whether any of it was APPLIED.
  WHAT CHANGED    `calibration_diff` between the entry this night produced
                  and the previous measuring entry of the same calibration.
                  It names when the two are not claimed comparable rather
                  than showing numbers that cannot be read together.
  WHAT WAITS ON HIM   the short list of things only he can do: take the
                  lights back, put the camera back, re-run an amendment
                  that applied nothing, turn off a fixture the run left lit.
                  EMPTY IS AN ANSWER and is said out loud.
"""
from __future__ import annotations

import logging
from typing import Optional

from spectra.services import (calibration_diff, calibration_store,
                              night_calibration)

logger = logging.getLogger(__name__)

#: NIGHT STATE WORDS ARE READ FROM `night_run` AT CALL TIME, inside each
#: function, never imported at module scope and never copied here. Two
#: reasons: a state word defined twice is a state word that will eventually
#: mean two things, and `night_run` imports `night_calibration`, which this
#: module also imports — a module-scope import back the other way is a cycle.


def build(night: Optional[dict] = None) -> dict:
    """THE ONE READ. Pass a night record, or let it read the current/most
    recent one."""
    from spectra.services import night_run
    if night is None:
        night = night_run.last_night()
    if not night:
        return _never_ran()

    state = night.get("state") or ""
    cal_link = dict(night.get("calibration") or {})
    cal = (calibration_store.load(cal_link.get("calibration_id") or "")
           if cal_link.get("calibration_id") else None)

    out = {
        "run_id": night.get("run_id"),
        "state": state,
        "started": night.get("started"),
        "ended": night.get("ended"),
        "calibration": cal_link,
        "ran": _what_ran(night, cal_link, state),
        "measured": _what_it_measured(night, cal_link),
        "changed": _what_changed(cal, cal_link),
        "waiting": _what_waits(night, cal_link, state),
    }
    out["summary"] = _summary(out, state)
    return out


def _never_ran() -> dict:
    """ABSENCE IS A READ. "No night has ever run here" and "a night ran and
    measured nothing" are different facts and must not read alike."""
    return {"run_id": None, "state": "idle", "started": None, "ended": None,
            "calibration": {}, "ran": "No night run has happened yet.",
            "measured": "Nothing has been measured overnight.",
            "changed": {"available": False,
                        "summary": ("There is nothing to compare — no night "
                                    "has measured anything yet.")},
            "waiting": [],
            "summary": ("No night run has happened yet. Declare what the "
                        "night should run, and the next sleep window will "
                        "run it.")}


def _what_it_was(cal_link: dict) -> str:
    """HIS NOUN FOR WHAT THE NIGHT WAS DECLARED TO RUN. A calibration has a
    NAME; only a night that ran a plain list has nothing to name."""
    if not cal_link.get("calibration_id"):
        return "a declared item list"
    word = night_calibration.MODE_WORDS.get(cal_link.get("mode") or "",
                                            "calibration")
    return f"{word} '{cal_link.get('name') or cal_link['calibration_id']}'"


def _what_ran(night: dict, cal_link: dict, state: str) -> str:
    """ONE SENTENCE naming what the night was declared to run and what
    became of it. His nouns: a calibration has a NAME, not an id."""
    from spectra.services import night_run
    what = _what_it_was(cal_link)
    if state == night_run.STATE_DECLINED:
        return (f"Last night did not run {what}: {night.get('detail') or ''}"
                ).strip()
    if state == night_run.STATE_REFUSED:
        return (f"Last night held the room and {what} refused. "
                f"{night.get('detail') or ''}").strip()
    if state == night_run.STATE_RUNNING:
        # Never `str.capitalize()` here — it lowercases the rest of the
        # string, which would turn a calibration's own name into something
        # he never wrote.
        return f"{what[:1].upper()}{what[1:]} is running right now."
    if state == night_run.STATE_ENDED_BY_MORNING:
        return (f"Last night ran {what} and stopped at his morning routine, "
                f"which is where every night ends.")
    if state == night_run.STATE_ABORTED:
        return (f"Last night ran {what} and stopped early: "
                f"{night.get('detail') or 'the house was touched.'}")
    if state == night_run.STATE_FAILED:
        return (f"Last night ran {what} and stopped on an error. "
                f"{night.get('detail') or ''}").strip()
    return f"Last night ran {what}. {night.get('detail') or ''}".strip()


def _what_it_measured(night: dict, cal_link: dict) -> str:
    """WHAT LANDED, and — after a cut-short amendment — whether any of it
    reached his room. Those are two different facts and the second is the
    one the Admiral's ruling exists to make legible."""
    queue = dict(night.get("queue") or {})
    counts = dict(queue.get("counts") or {})
    if cal_link.get("calibration_id"):
        emitters = list(cal_link.get("emitters") or [])
        if not emitters:
            return ("Nothing was measured — see what ran, above, for why. "
                    "The room map is exactly as it was.")
        if cal_link.get("applied") is False:
            return (f"It measured {len(emitters)} fixture part"
                    f"{'' if len(emitters) == 1 else 's'} and APPLIED NONE "
                    f"of it: the room map is exactly as it was. "
                    f"{cal_link.get('unapplied_reason') or ''}").strip()
        superseded = len(cal_link.get("superseded") or {})
        line = (f"It measured {len(emitters)} fixture part"
                f"{'' if len(emitters) == 1 else 's'}, replacing "
                f"{superseded} earlier reading"
                f"{'' if superseded == 1 else 's'} of this same "
                f"calibration.")
        if cal_link.get("comparable") is False:
            line += (f" These numbers are NOT claimed comparable with the "
                     f"earlier ones: {cal_link.get('comparable_note') or ''}")
        return line.strip()
    if not counts:
        return ("Nothing was measured — see what ran, above, for why. The "
                "room map is exactly as it was.")
    return queue.get("summary") or "Nothing was measured."


def _what_changed(cal, cal_link: dict) -> dict:
    """WHAT CHANGED AGAINST THE PREVIOUS ONE — `calibration_diff`, never a
    second arithmetic and never a narration.

    A NIGHT THAT LANDED UNAPPLIED IS STILL DIFFED, deliberately: its
    readings are in the lineage and comparing them is exactly how he decides
    whether to run it again. What the diff cannot do is claim they are in
    his room, and `applied` above says they are not."""
    if cal is None:
        return {"available": False,
                "summary": ("This night did not run a calibration, so there "
                            "is no previous reading of the same fixtures to "
                            "compare it with. A plain item list measures the "
                            "room; a calibration is what remembers.")}
    entry_id = cal_link.get("entry_id") or ""
    runs = calibration_diff.measurable_runs(cal)
    ids = [r.id for r in runs]
    if entry_id not in ids:
        return {"available": False, "calibration_id": cal.id,
                "summary": ("Nothing was measured last night, so there is "
                            "nothing to compare with the reading before it. "
                            "The last measurement this calibration holds is "
                            "still the one it held yesterday.")}
    index = ids.index(entry_id)
    if index == 0:
        return {"available": False, "calibration_id": cal.id,
                "summary": (f"This is the first measurement "
                            f"'{cal.name}' has ever taken, so there is "
                            f"nothing before it to compare against. Every "
                            f"later run is compared with this one.")}
    got = calibration_diff.diff(cal, ids[index - 1], entry_id)
    if got.refusal:
        return {"available": False, "calibration_id": cal.id,
                "summary": got.refusal}
    body = got.as_dict()
    body["available"] = True
    return body


def _what_waits(night: dict, cal_link: dict, state: str) -> list[str]:
    """THE SHORT LIST OF THINGS ONLY HE CAN DO. In his nouns, one sentence
    each, and NEVER a restatement of something that needs no act — a list
    padded with facts is a list nobody reads twice.

    Every entry here is sourced from a record: the night's own refusal, the
    calibration's `applied` flag, the exit report's own `problems`. Nothing
    is inferred."""
    from spectra.services import night_run
    out: list[str] = []
    if state == night_run.STATE_DECLINED:
        if night.get("refusal") == "not_owned":
            out.append("Take the lights back on the ownership bar — the "
                       "night never takes the room, so tonight's queue can "
                       "only run once SPECTRA holds it.")
        elif night.get("refusal") in ("no_declared_queue", "no_calibration",
                                      "bad_declaration", "nothing_declared"):
            out.append("Fix what the night is declared to run — it declined "
                       "for the reason above and measured nothing.")
        elif night.get("refusal") == "will_not_fit":
            out.append("Declare a shorter queue, or let it start earlier: it "
                       "could not finish before the blinds open.")
    if state == night_run.STATE_REFUSED:
        out.append(f"Deal with the refusal above and run it again — "
                   f"{night.get('detail') or 'it refused by name.'}")
    if cal_link.get("applied") is False:
        out.append(f"Run the amendment to "
                   f"'{cal_link.get('name') or 'this calibration'}' again: "
                   f"it was cut short, so nothing it measured was applied "
                   f"and your room is still on the previous calibration.")
    for problem in (night.get("exit") or {}).get("problems") or []:
        out.append(problem)
    return out


def _summary(out: dict, state: str) -> str:
    """THE ONE LINE, if he reads nothing else."""
    waiting = out["waiting"]
    tail = ("Nothing waits on you."
            if not waiting else
            f"{len(waiting)} thing{'' if len(waiting) == 1 else 's'} "
            f"wait{'s' if len(waiting) == 1 else ''} on you.")
    changed = out["changed"].get("summary") or ""
    return f"{out['ran']} {out['measured']} {changed} {tail}".strip()
