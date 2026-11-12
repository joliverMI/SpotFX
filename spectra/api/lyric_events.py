"""Word colours and imprints on the Test Bed (lyrics plan step 4): what each
matched word would do, the per-show switch and the three tuning settings.
spectra/services/lyric_events.py is the binding statement.

  GET  /api/testbed/lyric-events?uri=[&sample=]  what each word would do: this
                                          play's roll for the song playing, his kept
                                          roll, or a sample play numbered `sample`
  PUT  /api/testbed/lyric-events/show     turn word colours on or off for a show
  PUT  /api/testbed/lyric-events/keep     keep a play's roll as the song's plan, or
                                          (seed null) let every play roll again
  PUT  /api/testbed/lyric-events/settings the energy cut-off, minimum gap and
                                          imprint window
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from spectra.models.lyric_labels import SEED_MAX

from spectra.services import lyric_events, sung_labels
from spectra.services.trigger_engine import trigger_engine

router = APIRouter(prefix="/api/testbed/lyric-events", tags=["spectra-lyric-events"])


@router.get("")
async def get_actions(uri: str = Query(...),
                      sample: Optional[int] = Query(None, ge=0, le=SEED_MAX)):
    """`sample` rolls a throwaway play with that number, for the page only:
    nothing is stored and nothing reaches the room. Ignored for the song
    playing, which always shows the play under way."""
    try:
        preview = await asyncio.to_thread(trigger_engine.preview_lyric_events, uri, sample)
    except (lyric_events.StoreUnreadable, sung_labels.StoreUnreadable) as exc:
        raise HTTPException(500, str(exc)) from exc
    return lyric_events.preview_payload(preview, lyric_events.settings())


class ShowSwitch(BaseModel):
    uri: str
    enabled: bool


@router.put("/show")
async def put_show(body: ShowSwitch):
    try:
        return {"uri": body.uri, "enabled": lyric_events.set_show(body.uri, body.enabled)}
    except lyric_events.StoreUnreadable as exc:
        raise HTTPException(500, str(exc)) from exc


class KeepRoll(BaseModel):
    uri: str = Field(min_length=1)
    seed: Optional[int] = Field(None, ge=0, le=SEED_MAX)


@router.put("/keep")
async def put_keep(body: KeepRoll):
    try:
        return {"uri": body.uri, "kept_seed": lyric_events.keep_roll(body.uri, body.seed)}
    except lyric_events.StoreUnreadable as exc:
        raise HTTPException(500, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class TuningUpdate(BaseModel):
    energy_cutoff: Optional[float] = None
    min_gap_s: Optional[float] = None
    imprint_window_s: Optional[float] = None


@router.put("/settings")
async def put_settings(body: TuningUpdate):
    try:
        return lyric_events.update_settings(
            energy_cutoff=body.energy_cutoff, min_gap_s=body.min_gap_s,
            imprint_window_s=body.imprint_window_s).model_dump()
    except lyric_events.StoreUnreadable as exc:
        raise HTTPException(500, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
