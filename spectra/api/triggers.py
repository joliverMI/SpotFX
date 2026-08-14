"""SPECTRA per-song trigger API — the authoring surface's CRUD.
  GET    /api/triggers?uri=<spotify_uri>       — list, timestamp-sorted
  POST   /api/triggers?uri=<spotify_uri>       — upsert (validates the
      action's scene_id / set_id reference against SPECTRA's own stores;
      response actions carry no external reference)
  DELETE /api/triggers/{trigger_id}?uri=...
Mounted under /spectra — a different namespace from the legacy per-song
trigger routes the ported timeline view still reads/writes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from spectra.models.trigger import SpectraTrigger
from spectra.services import color_sets, scene_store, trigger_store

router = APIRouter(prefix="/api/triggers", tags=["spectra-triggers"])


def _validate_action(trigger: SpectraTrigger) -> None:
    action = trigger.action
    if action.kind == "fire_scene":
        if scene_store.get_by_id(action.scene_id) is None:
            raise HTTPException(422, f"scene '{action.scene_id}' not found")
        if action.color_set_id and color_sets.get_by_id(action.color_set_id) is None:
            raise HTTPException(422, f"colour set '{action.color_set_id}' not found")
    elif action.kind == "select_color_set":
        if color_sets.get_by_id(action.set_id) is None:
            raise HTTPException(422, f"colour set '{action.set_id}' not found")


@router.get("")
async def list_triggers(uri: str = Query(...)):
    return [t.model_dump() for t in trigger_store.list_for_song(uri)]


@router.post("")
async def upsert_trigger(trigger: SpectraTrigger, uri: str = Query(...)):
    _validate_action(trigger)
    trigger_store.upsert(uri, trigger)
    return {"status": "saved", "id": trigger.id}


@router.delete("/{trigger_id}")
async def delete_trigger(trigger_id: str, uri: str = Query(...)):
    if not trigger_store.delete(uri, trigger_id):
        raise HTTPException(404, "trigger not found")
    return {"status": "deleted"}
