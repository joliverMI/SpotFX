"""S2 evolution-engine observability + the dark event injector.

  GET  /api/engine/status — the whole engine surface: executor mode (S2 is
      "recording" — DARK against real lights until S3), conductor state
      (journey custody/position, active mechanisms, last leg), recent
      surges, bridge health. The Scenes-page status strip reads this.
  POST /api/engine/event  — inject one response event at a chosen intensity
      (the responses tabs' preview-of-record: in production it executes
      against the RecordingExecutor, so the surge is computed, logged, and
      visible — and no light moves). "update" is a valid class here too
      (spectra-trigger-migration-scoping RULING.md) even though it isn't a
      ResponseClass — it's the same manual test-fire surface the other four
      classes already have, routed to ResponseEngine.on_update instead of
      on_event. As of the 2026-08-20 placeholder (on_update's own
      docstring), this fires the "flare" class at 2x the given intensity —
      no longer a bypass of band selection, just a different intensity
      input.
  POST /api/engine/baseline/{scene_id} — re-baseline the engine on a scene
      WITHOUT firing anything: resolve at the given intensity, hand the
      writes to the conductor. This is how the engine adopts a scene while
      it stays dark (fires are S3's business).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from spectra.models.scene import RESPONSE_CLASSES
from spectra.services import engine, scene_compiler, scene_store
from spectra.services.binding_resolver import FireContext

router = APIRouter(prefix="/api/engine", tags=["spectra-engine"])

EVENT_CLASSES = (*RESPONSE_CLASSES, "update")


class EventRequest(BaseModel):
    event_class: str = Field(alias="class")
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)

    model_config = {"populate_by_name": True}


class BaselineRequest(BaseModel):
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    color_set_id: str | None = None


@router.get("/status")
async def get_status():
    return engine.status()


@router.post("/event")
async def post_event(body: EventRequest):
    if body.event_class not in EVENT_CLASSES:
        raise HTTPException(422, f"class must be one of {EVENT_CLASSES}")
    if body.event_class == "update":
        record = await engine.responses.on_update(body.intensity)
    else:
        record = await engine.responses.on_event(body.event_class, body.intensity)
    released = await engine.responses.flush_releases()
    return {**record, "releases_flushed": released}


@router.post("/baseline/{scene_id}")
async def post_baseline(scene_id: str, body: BaselineRequest | None = None):
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise HTTPException(404, "scene not found")
    body = body or BaselineRequest()
    from spectra.services import color_set_groups, color_sets
    color_set = (color_sets.get_by_id(body.color_set_id)
                 if body.color_set_id else None)
    if color_set is not None:
        color_set = color_set_groups.resolve_for_fire(color_set)  # §10
    ctx = FireContext(body.intensity)
    resolved = scene_compiler.resolve_scene(scene, ctx)
    writes = scene_compiler.compile_scene(resolved, color_set)
    engine.on_scene_fired(scene, writes, color_set.id if color_set else None)
    return {"status": "baselined", "scene_id": scene_id,
            "mechanisms": len(engine.conductor.mechanisms),
            "virtuals": len(writes)}
