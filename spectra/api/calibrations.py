"""THE CALIBRATION RECORD's wire.

  GET    /api/calibrations              every calibration, small view
  POST   /api/calibrations              create one (name, room, placement,
                                        camera regime, envelope, declared
                                        items, tag registry)
  GET    /api/calibrations/{id}         the whole artefact — pose, camera,
                                        envelope, declaration, the full
                                        append-only lineage, and PROVENANCE
                                        resolved against the live room map
  PUT    /api/calibrations/{id}         edit the DECLARATION (name,
                                        placement, camera regime, envelope,
                                        items, tag registry). The lineage is
                                        never touched; the edit itself is
                                        recorded as an entry.
  POST   /api/calibrations/{id}/pose    take or RE-ANCHOR the pose — drives
                                        lights
  POST   /api/calibrations/{id}/run     run it — pose check, then the
                                        declared queue

THERE IS NO DELETE, and that is the point of the artefact: the lineage is
append-only, and a route that could drop a calibration would be a route that
erases work that cost dark rooms to produce. `calibration_store.delete`
exists for a test to clean up after itself and is deliberately not wired
here.

TWO OF THESE ROUTES TOUCH A LIGHT, and both do it through
`spectra/services/capture_runs.py` — the ONE seam — so the exposure lock,
the lever self-test, the ownership boundary, the hold ceiling and the
one-run-at-a-time lock apply exactly as they do to the map button. This
module adds no gate of its own and composes no sentence of its own: every
refusal here is `mapping_refusals`' own wording.

REGISTERED BEFORE `rooms.router` is not needed (the prefix does not collide),
but this router is registered with the rest in `spectra/app.py`.

WHY A RUN IS AWAITED HERE AND A CAPTURE QUEUE IS NOT: a queue is started by
an ssh line that must not hold a socket for forty minutes, and its record is
followed by polling. A calibration run is a deliberate press with an answer
worth waiting for, and the answer — the lineage entry, with the pose
judgement and the comparability claim on it — is exactly what the caller
asked for. A caller that does not want to wait can watch the same run
through `GET /api/rooms/capture-queue`, because it IS a capture queue.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from spectra.models.calibration import (Calibration, Envelope, PinnedCamera,
                                        TagRegistration)
from spectra.services import (calibration_runs, calibration_store,
                              capture_queue, capture_runs, light_field,
                              pose_fingerprint)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["spectra-calibrations"])


class CalibrationBody(BaseModel):
    """A calibration's DECLARATION — everything about it that a human
    decides, and nothing that a run measures.

    `items` is the capture queue's own item shape and is validated by
    `capture_queue.parse_items`, the ONE validator: a declaration with a typo
    in it is refused HERE, with the item named, rather than at 3 am on the
    item nobody reads."""
    name: str = ""
    room_id: str = ""
    #: HIS OWN NAME for where the camera stands ("the north shelf"). Free
    #: text, said once, and carried on every refusal that mentions the pose.
    placement: Optional[str] = None
    camera: Optional[PinnedCamera] = None
    envelope: Optional[Envelope] = None
    items: Optional[list[dict[str, Any]]] = None
    #: THE TAG REGISTRY — every physical ArUco tag, with the black square's
    #: side as HE MEASURED IT after printing. STORAGE ONLY: nothing in this
    #: build reads it and there is no tag-detection code here. It is carried
    #: from day one so the vision step lands into a record that already holds
    #: measured truth rather than having to ask him for it later. A
    #: non-positive side is refused by the model itself — that is not a
    #: measurement — and two entries for one tag id are refused by name
    #: below, because one physical tag has one size.
    tags: Optional[list[TagRegistration]] = None


class RunBody(BaseModel):
    label: str = ""
    #: RUN PAST A MEASURED CAMERA MOVE. An explicit press wins and the
    #: record NAMES the contradiction (`overrode_camera_moved`) — the Force
    #: Scene precedent. It never re-anchors the pose as a side effect.
    force: bool = False


class PoseBody(BaseModel):
    placement: Optional[str] = None
    label: str = ""


def _not_found(cal_id: str) -> JSONResponse:
    return JSONResponse(status_code=404,
                        content={"detail": f"no calibration {cal_id}"})


@router.get("/calibrations")
async def list_calibrations():
    return {"calibrations": [c.as_summary() for c in calibration_store.load_all()],
            "session": capture_runs.session_view(),
            # The pose fingerprint's own pre-registered tolerances, published
            # so a page never hard-codes one and a reader can check the
            # judgement's arithmetic rather than believe it.
            "fingerprint": {
                "centroid_tolerance": pose_fingerprint.CENTROID_TOLERANCE,
                "move_separation": pose_fingerprint.MOVE_SEPARATION,
                "coherence_fraction": pose_fingerprint.COHERENCE_FRACTION,
                "weight_band": pose_fingerprint.WEIGHT_BAND,
                "min_discriminating": pose_fingerprint.MIN_DISCRIMINATING,
                "min_anchor_spread": pose_fingerprint.MIN_ANCHOR_SPREAD,
                "max_references": pose_fingerprint.MAX_REFERENCES}}


@router.post("/calibrations")
async def create_calibration(body: CalibrationBody):
    """Create one. The room must exist — a calibration is a pose IN a room,
    and one pointing at nothing could never be run."""
    if not body.name.strip():
        return JSONResponse(status_code=400,
                            content={"detail": "a calibration needs a name"})
    if light_field.get_room(body.room_id) is None:
        return JSONResponse(status_code=400, content={
            "detail": f"no room {body.room_id} — a calibration is a pose in a "
                      f"room, so it needs one that exists"})
    problem = _validate_items(body.items or []) or _validate_tags(body.tags)
    if problem is not None:
        return problem
    cal = Calibration(name=body.name.strip(), room_id=body.room_id,
                      camera=body.camera or PinnedCamera(),
                      envelope=body.envelope or Envelope(),
                      items=list(body.items or []),
                      tags=list(body.tags or []))
    if body.placement is not None:
        cal.pose.placement = body.placement
    calibration_store.save(cal)
    return calibration_runs.view(cal)


@router.get("/calibrations/{cal_id}")
async def get_calibration(cal_id: str):
    cal = calibration_store.load(cal_id)
    if cal is None:
        return _not_found(cal_id)
    return calibration_runs.view(cal)


@router.put("/calibrations/{cal_id}")
async def update_declaration(cal_id: str, body: CalibrationBody):
    """EDIT THE DECLARATION — what this calibration measures, in what
    regime, under what envelope, and what he calls the placement.

    THE LINEAGE IS UNTOUCHED and the edit is itself recorded as an entry
    (the plan's "editing the declaration keeps lineage"): a later reader can
    see that run 4 measured a different list from run 3, which is the only
    way two runs that do not line up ever make sense.

    THE POSE IS NOT EDITABLE HERE. Re-anchoring is `POST /pose` because it
    drives lights and starts a new comparable series; the only part of the
    pose this touches is his own NAME for the placement, which is a label
    and not a measurement."""
    cal = calibration_store.load(cal_id)
    if cal is None:
        return _not_found(cal_id)
    if body.items is not None:
        problem = _validate_items(body.items)
        if problem is not None:
            return problem
    if body.tags is not None:
        problem = _validate_tags(body.tags)
        if problem is not None:
            return problem

    changes: list[str] = []
    if body.name and body.name.strip() != cal.name:
        changes.append(f"name: {cal.name!r} -> {body.name.strip()!r}")
        cal.name = body.name.strip()
    if body.placement is not None and body.placement != cal.pose.placement:
        changes.append(f"placement: {cal.pose.placement!r} -> "
                       f"{body.placement!r}")
        cal.pose.placement = body.placement
    if body.camera is not None and not body.camera.same_as(cal.camera):
        changes.append("camera settings: "
                       + "; ".join(cal.camera.differences(body.camera)))
        cal.camera = body.camera
    if body.envelope is not None and body.envelope != cal.envelope:
        changes.append(f"envelope: needs dark={body.envelope.dark_required}, "
                       f"window={body.envelope.window!r}")
        cal.envelope = body.envelope
    if body.items is not None and body.items != cal.items:
        changes.append(f"declared items: {len(cal.items)} -> "
                       f"{len(body.items)}")
        cal.items = list(body.items)
    if body.tags is not None and body.tags != cal.tags:
        changes.append(_tag_change(cal.tags, body.tags))
        cal.tags = list(body.tags)

    if changes:
        calibration_runs.record_declaration_change(cal, changes)
        calibration_store.save(cal)
    return {**calibration_runs.view(cal), "changed": changes}


@router.post("/calibrations/{cal_id}/pose")
async def take_pose(cal_id: str, body: Optional[PoseBody] = None):
    """TAKE OR RE-ANCHOR THE POSE. Drives lights, through the one seam.

    Re-anchoring starts a NEW comparable series: runs before it and after it
    are each comparable among themselves and not with each other. That is
    said on the entry rather than being something a reader has to work out
    from two timestamps."""
    cal = calibration_store.load(cal_id)
    if cal is None:
        return _not_found(cal_id)
    cal, entry = await calibration_runs.establish_pose(
        cal, placement=body.placement if body else None,
        label=body.label if body else "")
    body_out = {**calibration_runs.view(cal), "entry": entry.model_dump()}
    if entry.status == capture_runs.STATUS_REFUSED:
        # AN ANTICIPATED CONDITION, not a server fault — and the record was
        # still written, which is why the whole calibration comes back with
        # it rather than a bare sentence.
        return JSONResponse(status_code=409, content=body_out)
    return body_out


@router.post("/calibrations/{cal_id}/run")
async def run_calibration(cal_id: str, body: Optional[RunBody] = None):
    """RUN IT: check the pose, then run the declared queue through the same
    machinery a button press uses, then append one lineage entry.

    409 for a refusal, with the whole record: the refusal IS an entry, and a
    caller that only got a sentence would have to go and read the store to
    find out that the refusal was recorded."""
    cal = calibration_store.load(cal_id)
    if cal is None:
        return _not_found(cal_id)
    cal, entry = await calibration_runs.run_calibration(
        cal, force=body.force if body else False,
        label=body.label if body else "")
    body_out = {**calibration_runs.view(cal), "entry": entry.model_dump(),
                "queue": capture_queue.status()["current"]}
    if entry.status == capture_runs.STATUS_REFUSED:
        return JSONResponse(status_code=409, content=body_out)
    return body_out


def _validate_tags(tags) -> Optional[JSONResponse]:
    """ONE PHYSICAL TAG, ONE SIZE. Two entries for one id is a contradiction
    rather than a list, and the one that lost would silently scale every pose
    it anchored — which is the whole reason the size is measured and stored
    at all. A non-positive side never reaches here: `TagRegistration` refuses
    it, because that is not a measurement."""
    if not tags:
        return None
    seen: set[int] = set()
    for t in tags:
        if t.tag_id in seen:
            return JSONResponse(status_code=400, content={
                "detail": f"tag {t.tag_id} is registered twice. One physical "
                          f"tag has one measured size — registering it twice "
                          f"means one of the two readings silently scales "
                          f"every pose it anchors, and nothing downstream "
                          f"could tell which."})
        seen.add(t.tag_id)
    return None


def _tag_change(was, now) -> str:
    """What an edit did to the registry, in his words — sizes included,
    because the size IS the fact this registry exists to hold."""
    before = {t.tag_id: t for t in was}
    after = {t.tag_id: t for t in now}
    parts = []
    for tag_id in sorted(set(after) - set(before)):
        t = after[tag_id]
        parts.append(f"tag {tag_id} added at {t.measured_side_mm:g} mm"
                     + (f" on {t.mount}" if t.mount else ""))
    for tag_id in sorted(set(before) - set(after)):
        parts.append(f"tag {tag_id} removed")
    for tag_id in sorted(set(before) & set(after)):
        a, b = before[tag_id], after[tag_id]
        if a.measured_side_mm != b.measured_side_mm:
            parts.append(f"tag {tag_id} re-measured "
                         f"{a.measured_side_mm:g} -> {b.measured_side_mm:g} mm")
        if a.mount != b.mount:
            parts.append(f"tag {tag_id} moved to {b.mount or 'no mount named'}")
    return "tag registry: " + ("; ".join(parts) or "reordered")


def _validate_items(items: list[dict]) -> Optional[JSONResponse]:
    """ONE VALIDATOR, NEVER A SECOND. A declared item is a capture-queue
    item, so `capture_queue.parse_items` is what says whether it is a good
    one — refusing here, at declaration, with the item named."""
    if not items:
        return None
    try:
        capture_queue.parse_items(items)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return None
