"""SceneV2 API.
  GET    /api/scenes-v2                  — list
  GET    /api/scenes-v2/wheel-positions  — {set_id: ColorWheelPosition}
  GET    /api/scenes-v2/{id}             — get
  POST   /api/scenes-v2                  — upsert
  DELETE /api/scenes-v2/{id}             — delete
  POST   /api/scenes-v2/{id}/fire        — compile; dry_run=true (default) = no LedFX I/O
Never touches events.json or the trigger engine (legacy scene path)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models.scene_v2 import SceneV2
from services import color_set_store, color_wheel, scene_v2_compiler, scene_v2_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scenes-v2", tags=["scenes_v2"])


class FireRequest(BaseModel):
    dry_run: bool = True


@router.get("")
async def list_scenes():
    return [s.model_dump() for s in scene_v2_store.list_all()]


@router.get("/wheel-positions")
async def get_wheel_positions():
    positions = color_wheel.wheel_positions(color_set_store.list_all())
    return {sid: p.model_dump() for sid, p in positions.items()}


@router.get("/{scene_id}")
async def get_scene(scene_id: str):
    scene = scene_v2_store.get_by_id(scene_id)
    if scene is None:
        raise HTTPException(404, "SceneV2 not found")
    return scene.model_dump()


@router.post("")
async def upsert_scene(scene: SceneV2):
    scene_v2_store.save(scene)
    return {"status": "saved", "id": scene.id}


@router.delete("/{scene_id}")
async def delete_scene(scene_id: str):
    if not scene_v2_store.delete(scene_id):
        raise HTTPException(404, "SceneV2 not found")
    return {"status": "deleted"}


@router.post("/{scene_id}/fire")
async def fire_scene(scene_id: str, body: FireRequest | None = None):
    scene = scene_v2_store.get_by_id(scene_id)
    if scene is None:
        raise HTTPException(404, "SceneV2 not found")
    dry_run = body.dry_run if body is not None else True
    return await scene_v2_compiler.fire_scene(scene, dry_run=dry_run)
