"""SPECTRA scene API.
  GET    /api/scenes                  — list
  GET    /api/scenes/wheel-positions  — {set_id: ColorWheelPosition}
  GET    /api/scenes/{id}             — get
  POST   /api/scenes                  — upsert (validates set-filter ids and
                                        named drift-profile refs)
  DELETE /api/scenes/{id}             — delete
  POST   /api/scenes/{id}/fire        — resolve + compile at a CHOSEN
      intensity; dry_run=true (default) stops at the seam and returns the
      writes plus the per-binding resolution report — the editor's test-fire
      shows exactly what a real fire at that intensity would send. dry_run=
      false is the owner's real Fire button (HTTP to the external LedFX
      service until the S3 handover).
Mounted under /spectra — the legacy scene paths are a different app."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from spectra.models.scene import SceneV2
from spectra.services import (color_sets, color_wheel, drift_profiles,
                              scene_compiler, scene_store)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scenes", tags=["spectra-scenes"])


class FireRequest(BaseModel):
    dry_run: bool = True
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)


@router.get("")
async def list_scenes():
    return [s.model_dump() for s in scene_store.list_all()]


@router.get("/wheel-positions")
async def get_wheel_positions():
    positions = color_wheel.wheel_positions(color_sets.list_all())
    return {sid: p.model_dump() for sid, p in positions.items()}


@router.get("/{scene_id}")
async def get_scene(scene_id: str):
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise HTTPException(404, "scene not found")
    return scene.model_dump()


@router.post("")
async def upsert_scene(scene: SceneV2):
    # Per-set-only filter: group cards never enter a scene's set filter.
    group_ids = scene_store.group_ids_in_filter(scene)
    if group_ids:
        names = {c.id: c.name for c in color_sets.list_all()}
        offenders = ", ".join(f"'{names.get(i, i)}' ({i})" for i in group_ids)
        raise HTTPException(422, (
            f"accepted_set_ids may only reference kind='set' Colour Sets; "
            f"{offenders} is a group — list its member sets instead"))
    # Named drift refs must exist — a dangling profile would silently drift
    # nothing; the store only guards hand-edited files.
    known = set(drift_profiles.load_all())
    dangling = sorted({ref.profile for dev in scene.devices
                       for ref in dev.drift.values()
                       if ref.profile is not None and ref.profile not in known})
    if dangling:
        raise HTTPException(422, f"unknown drift profile id(s): {', '.join(dangling)}")
    scene_store.save(scene)
    return {"status": "saved", "id": scene.id}


@router.delete("/{scene_id}")
async def delete_scene(scene_id: str):
    if not scene_store.delete(scene_id):
        raise HTTPException(404, "scene not found")
    return {"status": "deleted"}


@router.post("/{scene_id}/fire")
async def fire_scene(scene_id: str, body: FireRequest | None = None):
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise HTTPException(404, "scene not found")
    body = body or FireRequest()
    try:
        return await scene_compiler.fire_scene(
            scene, intensity=body.intensity, dry_run=body.dry_run)
    except Exception as exc:
        if body.dry_run:
            raise
        raise HTTPException(502, f"live fire failed: {exc}")
