"""THE CALIBRATION STORE — one file per calibration, and provenance as a
READ against the live room map.

`spectra/models/calibration.py` is the binding statement for what a
calibration IS. This module is the persistence and the provenance
resolution, and it holds no opinion about poses, cameras or runs.

WHY A DIRECTORY (`storage/spectra/calibrations/<id>.json`) rather than one
bounded file, which is what nearly every other store here is: those stores
hold a HISTORY that ages out (the last 20 queues, the last 100
measurements, a ring of 10 scene backups) and a bound is the right answer
for them. A calibration is not history — it is a named artefact he creates
deliberately, one at a time, and its lineage is the one part that must never
be pruned. A single-file store would have to choose between capping the
lineage (losing the thing it is for) and growing without bound in a file
every read parses whole.

ATOMIC WRITES, tmp+`os.replace`, the convention across spectra/ (see
`light_field.save_rooms`): a run that dies mid-write must not leave half a
calibration behind — and here that matters more than usual, because the
lineage is the record of work that cost dark rooms to produce.

PROVENANCE IS A READ, NEVER A COPY. `provenance()` resolves a run's recorded
emitter ids against `room_maps.json` AS IT IS NOW. Three answers, and the
third is the honesty rail this step exists for:

  present     the footprint is there and this run is still its most recent
              producer in this calibration.
  superseded  the footprint is there and a LATER run or AMENDMENT of this
              calibration produced it — the earlier reading is history, and
              the record says which entry replaced it. Supersession is PER
              EMITTER: an amendment that re-measured three ranges of a
              wrapped TV supersedes exactly those three, and the rest of
              that carrier stays `present`, still credited to the run that
              took it.
  missing     the footprint is NOT in the room map any more (the room was
              re-mapped at a different granularity, a carrier was removed,
              the room was deleted). Reported by name. A calibration
              pointing at footprints that no longer exist must never imply
              they do.

The room map remains the live store throughout: nothing here writes it, and
nothing here caches a grid.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Optional

from spectra import config
from spectra.models.calibration import RUN_KINDS, Calibration
from spectra.services import light_field

logger = logging.getLogger(__name__)

#: How a run's recorded emitter id resolves against the room map today.
PRESENT = "present"
SUPERSEDED = "superseded"
MISSING = "missing"
#: THE ENTRY MEASURED IT AND NEVER APPLIED IT — a cut-short amendment, whose
#: readings live in the lineage while the room map was put back exactly as it
#: was (`spectra/services/amendment.py`). Deliberately NOT folded into
#: `superseded`: nothing replaced these, and nothing about the map ever
#: carried them.
UNAPPLIED = "unapplied"


def _dir(path=None):
    return config.CALIBRATIONS_DIR if path is None else path


def _file(cal_id: str, path=None):
    return os.path.join(str(_dir(path)), f"{cal_id}.json")


def _safe_id(cal_id: str) -> str:
    """A calibration id is a filename, so it may only be the characters an
    id is made of. Refused rather than sanitised: a silently different id
    would write a file nothing can find again."""
    clean = "".join(ch for ch in str(cal_id) if ch.isalnum() or ch in "-_")
    if not clean or clean != str(cal_id):
        raise ValueError(f"{cal_id!r} is not a calibration id")
    return clean


def load(cal_id: str, path=None) -> Optional[Calibration]:
    try:
        p = _file(_safe_id(cal_id), path)
    except ValueError:
        return None
    try:
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as fh:
            return Calibration(**json.load(fh))
    except Exception:                                  # noqa: BLE001
        logger.exception("calibration store: unreadable calibration %s", p)
        return None


def load_all(path=None) -> list[Calibration]:
    """Every calibration, newest first. An unreadable one is LOGGED and
    skipped rather than taking the listing down with it — one corrupt file
    must not hide the rest of his work."""
    d = str(_dir(path))
    if not os.path.isdir(d):
        return []
    out: list[Calibration] = []
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        cal = load(name[:-len(".json")], path)
        if cal is not None:
            out.append(cal)
    return sorted(out, key=lambda c: c.created_at, reverse=True)


def save(cal: Calibration, path=None) -> Calibration:
    """Atomic tmp+replace into the calibration's own file."""
    d = str(_dir(path))
    p = _file(_safe_id(cal.id), path)
    cal.updated_at = time.time()
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix="calibration", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cal.model_dump(), fh, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return cal


def delete(cal_id: str, path=None) -> bool:
    """Remove a whole calibration. Deliberately NOT reachable from the API
    in this step: the lineage is append-only, and the one act that would
    destroy it is not a thing to expose beside four routes that cannot.
    Kept here so a test can clean up after itself without reaching into the
    filesystem behind this module's back."""
    try:
        p = _file(_safe_id(cal_id), path)
    except ValueError:
        return False
    if not os.path.exists(p):
        return False
    os.unlink(p)
    return True


# ── provenance ─────────────────────────────────────────────────────────────

def provenance(cal: Calibration, room=None, map_path=None) -> dict:
    """WHAT THIS CALIBRATION'S RUNS PRODUCED, resolved against the room map
    as it is right now.

    `room` may be handed in (a caller that already loaded it); otherwise it
    is read. A MISSING room is not an error either — it is the extreme case
    of the same honesty rail, and it says so."""
    if room is None:
        room = light_field.get_room(cal.room_id, map_path)
    origin = cal.emitter_origin()
    if room is None:
        rows = [{"emitter_id": e, "state": MISSING, "run_id": run_id,
                 "label": "", "weight": 0.0, "pose_id": "", "mapped": False}
                for e, run_id in origin.items()]
        return {"room_id": cal.room_id, "room_present": False,
                "note": (f"the room this calibration was taken in is no "
                         f"longer stored, so none of its "
                         f"{len(rows)} footprint(s) can be found"),
                "counts": _counts(rows), "emitters": rows}

    rows = []
    for run in cal.runs:
        # RUN_KINDS, never the literal "run": an AMENDMENT produces
        # footprints exactly as a full run does, and a provenance read that
        # skipped it would report his newest measurement as belonging to
        # nobody while still listing the older one it superseded.
        if run.kind not in RUN_KINDS:
            continue
        for emitter_id in run.emitters:
            fp = room.footprint(emitter_id)
            if not run.applied:
                # MEASURED, NEVER APPLIED. Whatever the map holds for this
                # emitter today belongs to some other run; calling that
                # `superseded` would say this entry's reading was replaced,
                # when it was never in the map at all.
                state = UNAPPLIED
            elif fp is None:
                state = MISSING
            elif origin.get(emitter_id) != run.id:
                state = SUPERSEDED
            else:
                state = PRESENT
            rows.append({
                "emitter_id": emitter_id, "state": state, "run_id": run.id,
                "run_at": run.at,
                "superseded_by": (origin.get(emitter_id)
                                  if state == SUPERSEDED else ""),
                "label": fp.label if fp is not None else "",
                "mapped": bool(fp is not None and fp.mapped),
                "unseen": bool(fp is not None and fp.unseen),
                "weight": round(fp.weight, 4) if fp is not None else 0.0,
                "pose_id": fp.capture.pose_id if fp is not None else ""})
    return {"room_id": cal.room_id, "room_present": True,
            "note": _provenance_note(rows), "counts": _counts(rows),
            "emitters": rows}


def _counts(rows: list[dict]) -> dict:
    out = {PRESENT: 0, SUPERSEDED: 0, MISSING: 0, UNAPPLIED: 0}
    for r in rows:
        out[r["state"]] = out.get(r["state"], 0) + 1
    return out


def _provenance_note(rows: list[dict]) -> str:
    """The sentence a person reads. Absence gets its own wording — a
    calibration that never ran is not a calibration whose footprints went
    missing, and the two must not read alike."""
    if not rows:
        return ("this calibration has not produced a footprint yet — nothing "
                "to trace")
    counts = _counts(rows)
    parts = [f"{counts[PRESENT]} still standing"]
    if counts[SUPERSEDED]:
        parts.append(f"{counts[SUPERSEDED]} replaced by a later run of this "
                     f"same calibration")
    if counts[UNAPPLIED]:
        parts.append(f"{counts[UNAPPLIED]} measured by an amendment that was "
                     f"cut short and never applied — the readings are in the "
                     f"lineage and the room map was left exactly as it was")
    if counts[MISSING]:
        parts.append(f"{counts[MISSING]} no longer in the room map at all "
                     f"(the room was re-mapped or the carrier removed) — "
                     f"this calibration measured them, and they are not "
                     f"there now")
    return ", ".join(parts)
