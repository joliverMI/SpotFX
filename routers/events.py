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

from models.music_event import MusicEvent
from services.profile_manager import list_events, get_event, save_event, delete_event

router = APIRouter(prefix="/api/events", tags=["events"])


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
    save_event(event)
    return {"status": "saved", "id": event.id}


@router.delete("/{event_id}")
async def remove_event(event_id: str):
    ok = delete_event(event_id)
    if not ok:
        raise HTTPException(404, "Event not found")
    return {"status": "deleted"}


@router.post("/{event_id}/fire")
async def fire_event(event_id: str):
    from main import engine
    ok = await engine.fire_event_now(event_id)
    if not ok:
        raise HTTPException(404, "Event not found or has no actions")
    return {"status": "fired"}
