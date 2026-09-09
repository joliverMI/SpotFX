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
from spectra.services import midsong_generator, profile_sync_ledger, profile_trigger_sync, trigger_store

router = APIRouter(prefix="/api/triggers", tags=["spectra-triggers"])


def _validate_action(trigger: SpectraTrigger) -> None:
    """trigger_store.validate_action is the shared choke point — also used
    by spectra/services/testbed_promote.py's push-to-real gate, so a
    reference check can never be laxer through one write surface than the
    other."""
    try:
        trigger_store.validate_action(trigger.action)
    except trigger_store.InvalidTriggerAction as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("")
async def list_triggers(uri: str = Query(...)):
    return [t.model_dump() for t in trigger_store.list_for_song(uri)]


@router.post("")
async def upsert_trigger(trigger: SpectraTrigger, uri: str = Query(...)):
    """Every write through this human-facing endpoint lands source=
    "authored" (generator_key cleared) regardless of what the caller sent —
    the ownership-transfer rule front 3 depends on: dragging or editing a
    generated trigger claims it, so a later regenerate leaves it alone.

    The store call runs off the event loop (asyncio.to_thread, the
    sync-from-profile precedent below). It is a full read+rewrite of a
    ~9.5MB triggers.json (~126ms on his corpus) AND it takes
    trigger_store.write_lock, which an off-loop writer — the mid-song
    generator, a test-bed promotion — may already be holding across its own
    read+write. Waiting for either on the loop stalls this process's bridge
    poll, the 200ms trigger tick and every WS broadcast behind one save."""
    trigger = trigger.model_copy(update={"source": "authored", "generator_key": None})
    _validate_action(trigger)
    await asyncio.to_thread(trigger_store.upsert, uri, trigger)
    return {"status": "saved", "id": trigger.id}


@router.post("/generate")
async def generate_triggers(uri: str = Query(...)):
    """Off the loop too: the generator writes the same store under the same
    lock, one upsert per seeded section."""
    return await asyncio.to_thread(midsong_generator.generate_for_song, uri)


@router.delete("/{trigger_id}")
async def delete_trigger(trigger_id: str, uri: str = Query(...)):
    """Off the loop for the same reason as the upsert above — same whole-file
    rewrite, same write_lock."""
    if not await asyncio.to_thread(trigger_store.delete, uri, trigger_id):
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
    # FALSE = upsert-only: add and update, never remove. Sent by every
    # AUTOMATIC writer (import, post-capture generation, post-recapture
    # realign) so an unattended write can never destroy his authored rows.
    # Absent (the default) keeps the whole-song semantics an explicit
    # Timeline save relies on, including his deliberate deletions — an older
    # caller that predates this field is unchanged by it.
    delete_missing: bool = True


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
        plan = profile_trigger_sync.plan_song(uri, body.triggers, fired, known,
                                              delete_missing=body.delete_missing)
        return profile_trigger_sync.apply_plan(plan)

    return await asyncio.to_thread(_run)
