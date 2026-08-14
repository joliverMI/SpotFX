"""SPECTRA per-song trigger API — the authoring surface's CRUD.
  GET    /api/triggers?uri=<spotify_uri>       — list, timestamp-sorted
  POST   /api/triggers?uri=<spotify_uri>       — upsert (validates the
      action's scene_id / set_id reference against SPECTRA's own stores;
      response actions carry no external reference). Always lands
      source="authored" — see upsert_trigger's docstring.
  DELETE /api/triggers/{trigger_id}?uri=...
  POST   /api/triggers/generate?uri=<spotify_uri> — front 3's mid-song
      generation pass (spectra.services.midsong_generator), idempotent.
Mounted under /spectra — a different namespace from the legacy per-song
trigger routes the ported timeline view still reads/writes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from spectra.models.trigger import SpectraTrigger
from spectra.services import color_sets, midsong_generator, scene_store, trigger_store

router = APIRouter(prefix="/api/triggers", tags=["spectra-triggers"])


def _validate_action(trigger: SpectraTrigger) -> None:
    action = trigger.action
    if action.kind == "fire_scene":
        if action.scene_id is not None and scene_store.get_by_id(action.scene_id) is None:
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
    """Every write through this human-facing endpoint lands source=
    "authored" (generator_key cleared) regardless of what the caller sent —
    the ownership-transfer rule front 3 depends on: dragging or editing a
    generated trigger claims it, so a later regenerate leaves it alone."""
    trigger = trigger.model_copy(update={"source": "authored", "generator_key": None})
    _validate_action(trigger)
    trigger_store.upsert(uri, trigger)
    return {"status": "saved", "id": trigger.id}


@router.post("/generate")
async def generate_triggers(uri: str = Query(...)):
    return midsong_generator.generate_for_song(uri)


@router.delete("/{trigger_id}")
async def delete_trigger(trigger_id: str, uri: str = Query(...)):
    if not trigger_store.delete(uri, trigger_id):
        raise HTTPException(404, "trigger not found")
    return {"status": "deleted"}
