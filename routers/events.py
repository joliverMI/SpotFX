"""
SpotFX — Music Event API router.

Endpoints:
  GET    /api/events          — list all events
  GET    /api/events/{id}     — get one event
  POST   /api/events          — create / update event
  DELETE /api/events/{id}     — delete event
  POST   /api/events/{id}/fire — test-fire an event immediately
"""
from __future__ import annotations
import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models.music_event import Action, MusicEvent
from services.profile_manager import (
    FIXED_EVENT_IDS, FIXED_OVERRIDE_FIELDS,
    delete_event, get_event, list_events, reset_fixed_event, save_event,
)

router = APIRouter(prefix="/api/events", tags=["events"])


class PreviewBody(BaseModel):
    """Either a full (possibly unsaved) event, or one action subtree to wrap."""
    event: MusicEvent | None = None
    action: Action | None = None
    labels: list[str] = Field(default_factory=list)


@router.get("")
async def get_events():
    return [e.model_dump() for e in list_events()]


@router.get("/{event_id}")
async def get_event_by_id(event_id: str):
    event = get_event(event_id)
    if event is None:
        raise HTTPException(404, "Event not found")
    return event.model_dump()


@router.post("")
async def upsert_event(event: MusicEvent):
    if event.id in FIXED_EVENT_IDS:
        # A built-in's body stays synthesized; its settings (name, timeline
        # color, labels, energy, AI flag, fire offset) persist as overrides.
        save_event(event)
        return {"status": "saved", "id": event.id,
                "saved_fields": list(FIXED_OVERRIDE_FIELDS)}
    # The frozen classic editor doesn't know the composite shape — reject a
    # legacy-shape payload that would silently flatten a migrated event.
    existing = get_event(event.id)
    if (existing is not None and existing.event_type == "composite"
            and event.event_type != "composite"):
        raise HTTPException(
            409, "Event is composite — edit it in the new editor (/app/)")
    save_event(event)
    return {"status": "saved", "id": event.id}


@router.delete("/{event_id}")
async def remove_event(event_id: str):
    if event_id in FIXED_EVENT_IDS:
        raise HTTPException(403, "Built-in event cannot be deleted")
    ok = delete_event(event_id)
    if not ok:
        raise HTTPException(404, "Event not found")
    return {"status": "deleted"}


@router.post("/{event_id}/reset")
async def reset_event(event_id: str):
    """Drop the saved meta overrides on a built-in event, restoring its
    stock name / color / labels / energy / AI flag / fire offset."""
    if event_id not in FIXED_EVENT_IDS:
        raise HTTPException(400, "Only built-in events can be reset")
    changed = reset_fixed_event(event_id)
    return {"status": "reset" if changed else "already-default", "id": event_id}


@router.post("/preview")
async def preview_event(body: PreviewBody):
    """Fire an unsaved event draft / action subtree immediately (editor Preview).

    Nothing is persisted — the payload is wrapped in an in-memory composite
    and dispatched through the same path as a manual test-fire.
    """
    from main import engine
    if body.event is not None:
        event = body.event
    elif body.action is not None:
        event = MusicEvent(
            id="__preview__", name="Preview", event_type="composite",
            root=body.action,
        )
    else:
        raise HTTPException(422, "Provide either 'event' or 'action'")
    ok = await engine.fire_event_object_now(event, body.labels)
    if not ok:
        raise HTTPException(400, "Nothing to fire (empty preview)")
    return {"status": "fired"}


# NOTE: declared before /{event_id}/fire — route order matters or the
# parametrized path would swallow "phase-cycle".
@router.post("/phase-cycle/fire")
async def fire_phase_cycle():
    """Test the full Charge → Lull → Drop arc: fires the three fixed events
    spaced by the configured phase ramps (charge builds fully, lull settles,
    then the drop snaps). Returns immediately; the cycle runs in the
    background. Acts on whatever phase-capable effects are live, and runs the
    active scene's Charge/Lull/Drop lanes like any real fire."""
    from main import engine
    from config import settings
    charge_ms = int(settings.phase_charge_ramp_ms)
    lull_ms = int(settings.phase_lull_ramp_ms)

    async def _cycle() -> None:
        await engine.fire_event_now("fixed-charge")
        # let the build max out, then a beat of held tension
        await asyncio.sleep((charge_ms + 400) / 1000)
        await engine.fire_event_now("fixed-lull")
        await asyncio.sleep((lull_ms + 900) / 1000)
        await engine.fire_event_now("fixed-drop")

    asyncio.create_task(_cycle())
    return {
        "status": "started",
        "charge_ramp_ms": charge_ms,
        "lull_ramp_ms": lull_ms,
        "drop_ramp_ms": int(settings.phase_drop_ramp_ms),
    }


@router.post("/{event_id}/fire")
async def fire_event(event_id: str):
    from main import engine
    ok = await engine.fire_event_now(event_id)
    if not ok:
        raise HTTPException(404, "Event not found or has no actions")
    return {"status": "fired"}
