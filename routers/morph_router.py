"""
SpotFX — Morph API router.

  GET  /api/morph/aspects             — Aspect catalog
  POST /api/morph/import-scene/{id}   — Convert a LedFX scene into a starter
                                        morph_set MusicEvent and persist it
"""
from fastapi import APIRouter, HTTPException

from services import morph_aspects, scene_absorb
from services.profile_manager import save_event

router = APIRouter(prefix="/api/morph", tags=["morph"])


@router.get("/aspects")
async def list_aspects():
    """Return the full Aspect catalog the builder UI needs to render Morph Step editors."""
    return morph_aspects.aspect_catalog()


@router.post("/import-scene/{scene_id}")
async def import_scene(scene_id: str):
    """Convert a LedFX scene into a starter morph_set MusicEvent and save it.

    Returns the newly persisted event so the builder can navigate straight to it.
    404 when the scene doesn't exist on LedFX or has no importable virtuals
    (no active + imported + in-scope virtuals)."""
    event = await scene_absorb.import_scene(scene_id)
    if event is None:
        raise HTTPException(404, f"Scene '{scene_id}' has no importable virtuals on this LedFX")
    save_event(event)
    return {"event_id": event.id, "event": event.model_dump()}
