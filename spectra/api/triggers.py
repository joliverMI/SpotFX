"""SPECTRA per-song trigger API — the authoring surface's CRUD.
  GET    /api/triggers?uri=<spotify_uri>       — list, timestamp-sorted
  POST   /api/triggers?uri=<spotify_uri>       — upsert (validates the
      action's scene_id / set_id / scene_pool member references against
      SPECTRA's own stores; response actions carry no external reference).
      Always lands source="authored" — see upsert_trigger's docstring.
  DELETE /api/triggers/{trigger_id}?uri=...
  POST   /api/triggers/generate?uri=<spotify_uri> — front 3's mid-song
      generation pass (spectra.services.midsong_generator), idempotent.
  POST   /api/triggers/sync-from-profile — land ONE song's legacy profile
      triggers in the fired copy (spectra.services.profile_trigger_sync).
      Called by the spot-effects process on every profile save so his
      Timeline edits reach the room; see that module's docstring for the
      four standing decisions it applies.
Mounted under /spectra — a different namespace from the legacy per-song
trigger routes the ported timeline view still reads/writes."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from spectra.models.trigger import SpectraTrigger
from spectra.services import (color_sets, midsong_generator, profile_sync_ledger,
                              profile_trigger_sync, scene_store, trigger_store)

router = APIRouter(prefix="/api/triggers", tags=["spectra-triggers"])


def _validate_action(trigger: SpectraTrigger) -> None:
    action = trigger.action
    if action.kind == "fire_scene":
        if action.scene_id is not None and scene_store.get_by_id(action.scene_id) is None:
            raise HTTPException(422, f"scene '{action.scene_id}' not found")
        if action.color_set_id and color_sets.get_by_id(action.color_set_id) is None:
            raise HTTPException(422, f"colour set '{action.color_set_id}' not found")
        for member in action.scene_pool or []:
            if scene_store.get_by_id(member.scene_id) is None:
                raise HTTPException(
                    422, f"scene_pool scene '{member.scene_id}' not found")
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


class ProfileTriggerSyncRequest(BaseModel):
    """One song's editor-copy triggers, exactly as they sit in
    storage/profiles/*.json. RAW legacy MusicTrigger dicts, not a typed
    model: this endpoint must accept whatever the predecessor's profile
    schema currently holds without SPECTRA importing its models (the S3
    import discipline — scripts/check_process_split.py section 1b), and an
    unrecognised field is the caller's business, not a 422."""
    spotify_uri: str = Field(min_length=1)
    triggers: list[dict] = Field(default_factory=list)


@router.post("/sync-from-profile")
async def sync_from_profile(body: ProfileTriggerSyncRequest):
    """Reconcile ONE song, editor copy -> fired copy, as a single batched
    write. Runs off the event loop (asyncio.to_thread): the batched write is
    a full read+rewrite of a ~9.5MB triggers.json (~126ms on his corpus), and
    this process's bridge polls / trigger ticks / WS broadcasts must not stall
    behind a human pressing Save."""
    def _run() -> dict:
        uri = body.spotify_uri
        fired = trigger_store._load_raw().get(uri, [])
        known = profile_sync_ledger.for_song(profile_sync_ledger.load(), uri)
        plan = profile_trigger_sync.plan_song(uri, body.triggers, fired, known)
        return profile_trigger_sync.apply_plan(plan)

    return await asyncio.to_thread(_run)
