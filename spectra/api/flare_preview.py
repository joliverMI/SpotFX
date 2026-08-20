"""Flare scrubbing-preview timeline (owner ask, data/timeline-preview-
scrub-flares-and-drop-sequences — "flares first").

  POST /api/flare-preview/open       {scene_id, kind_name, intensity} —
      computes the isolated single-kind timeline (spectra/services/
      flare_preview.build_timeline) and arms the "automatically pauses the
      trigger engine" preview_pause for HEARTBEAT_TIMEOUT_S. Call again
      (same session) whenever the intensity slider changes — each call both
      recomputes the timeline and re-arms the pause.
  POST /api/flare-preview/heartbeat  {} — re-arms the pause without
      recomputing anything; the frontend pings this on an interval shorter
      than HEARTBEAT_TIMEOUT_S for as long as the overlay stays open, the
      same "keep it paused while I'm looking" shape room_preview's own
      hold-timer serves for a drag session.
  POST /api/flare-preview/close      {} — explicit release (closing the
      overlay / navigating away); also the target of a sendBeacon on tab
      close, mirroring ColorSetsPage.tsx's own unmount pattern.

No live write of any kind — see flare_preview.py's own docstring."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from spectra.services import flare_preview, preview_pause, scene_store

router = APIRouter(prefix="/api/flare-preview", tags=["spectra-flare-preview"])

# Comfortably longer than the frontend's own heartbeat interval (planned
# 5s) — a couple of missed beats (a slow tab, a brief network hiccup) must
# not un-pause the trigger engine out from under a preview that's still
# open.
HEARTBEAT_TIMEOUT_S = 15.0


class OpenRequest(BaseModel):
    scene_id: str
    kind_name: str
    intensity: float = Field(default=1.0, ge=0.0, le=1.0)


@router.post("/open")
async def open_preview(body: OpenRequest):
    scene = scene_store.get_by_id(body.scene_id)
    if scene is None:
        raise HTTPException(404, "scene not found")
    kind = next((k for k in scene.flare_kinds if k.name == body.kind_name), None)
    if kind is None:
        raise HTTPException(404, "flare kind not found on scene")
    timeline = await flare_preview.build_timeline(scene, kind, body.intensity)
    preview_pause.start(HEARTBEAT_TIMEOUT_S)
    return timeline


@router.post("/heartbeat")
async def heartbeat_preview():
    preview_pause.start(HEARTBEAT_TIMEOUT_S)
    return {"active": True, "remaining_s": preview_pause.remaining_s()}


@router.post("/close")
async def close_preview():
    preview_pause.clear()
    return {"active": False}
