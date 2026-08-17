"""Room-colour Preview — the Colour Set/Group editor's Preview button (owner
ask 2026-08-17, spectra/services/room_preview.py has the full mechanism).

  POST /api/room-preview/start   {card, hold} — snapshot + apply + arm the
                                 pause/auto-revert (tap: 5s, hold: 60s).
  POST /api/room-preview/update  {card}       — live-drag re-apply; no-op
                                 (applied=False) once the session has ended.
  POST /api/room-preview/release {}           — explicit release (second
                                 press / page navigating away); also the
                                 target of a sendBeacon on tab close.
  GET  /api/room-preview/status               — {active, hold, remaining_s,
                                 virtuals} for a reconciling page load.

`card` is the editor's current draft — round-trips through
spectra.services.color_sets.ColorSetCard (extra="ignore"), so an unsaved
draft previews without ever touching storage/color_sets.json."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from spectra.services import room_preview
from spectra.services.color_sets import ColorSetCard

router = APIRouter(prefix="/api/room-preview", tags=["spectra-room-preview"])


class PreviewStartRequest(BaseModel):
    card: ColorSetCard
    hold: bool = False


class PreviewUpdateRequest(BaseModel):
    card: ColorSetCard


@router.post("/start")
async def start_preview(body: PreviewStartRequest):
    return await room_preview.start(body.card, hold=body.hold)


@router.post("/update")
async def update_preview(body: PreviewUpdateRequest):
    return await room_preview.update(body.card)


@router.post("/release")
async def release_preview():
    return await room_preview.release()


@router.get("/status")
async def preview_status():
    return room_preview.status()
