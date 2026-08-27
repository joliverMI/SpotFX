"""Flare scrubbing-preview timeline (owner ask, data/timeline-preview-
scrub-flares-and-drop-sequences — "flares first") AND its live hold (owner
correction, same day — see spectra/services/flare_preview_hold.py's own
docstring for the full history of why the hold is not optional: previewing
a flare with no live component left his real fixtures showing nothing).

OPEN AND FIRE ARE SEPARATE CALLS (2026-08-21, data/preview-loops-and-
fires-on-the-trigger — his report: "the preview only happens once, it
should happen every time, and it should fire with the same timing as if
the playhead was crossing a trigger"). Before this, /open did both in one
call — computed the timeline AND fired live, instantly, regardless of
where the drawn trigger mark sat. Now:

  POST /api/flare-preview/open       {scene_id, kind_name, intensity} —
      computes the isolated single-kind timeline ONLY (spectra/services/
      flare_preview.build_timeline — the browser's scrub/markers, incl.
      the new animation_anchor_s/trigger_mark_s fields) and arms the
      "automatically pauses the trigger engine" preview_pause for
      HEARTBEAT_TIMEOUT_S. Does NOT fire live — no light changes yet.
      OPENING A PREVIEW STILL STOPS HIS LIVE SHOW the instant it opens
      (the pause is unconditional, ahead of any actual fire): with the
      trigger engine paused, any triggers firing mid-song go silent for as
      long as the preview stays open. Call again whenever the intensity
      slider changes — recomputes the timeline at the new value (still no
      live fire; the frontend resets its playhead and waits for the mark
      like a fresh open).
  POST /api/flare-preview/fire       {scene_id, kind_name, intensity} —
      the live half: fires the scene + kind for real
      (flare_preview_hold.open_hold) so his fixtures show what the
      timeline predicts, and re-arms the pause. The frontend calls this
      once per loop cycle, timed to land exactly when its own simulated
      playhead crosses animation_anchor_s — never on open itself, and
      every loop, not once — so a fresh preview waits for its own trigger
      mark before anything changes, then repeats that same wait on every
      subsequent lap, "the same timing as if the playhead was crossing a
      trigger."
  POST /api/flare-preview/heartbeat  {} — re-arms the pause AND the live
      hold's own release DEADLINE, without recomputing/re-firing anything;
      the frontend pings this on an interval shorter than
      HEARTBEAT_TIMEOUT_S for as long as the overlay stays open, the same
      "keep it paused while I'm looking" shape room_preview's own
      hold-timer serves for a drag session. A lapsed heartbeat (tab
      closed, connection dropped) is indistinguishable from an explicit
      close from here — both let the deadline lapse, and
      flare_preview_hold.run_supervised()'s own independent sweep (NOT
      this endpoint) is what actually reverts, within
      HEARTBEAT_TIMEOUT_S + SWEEP_INTERVAL_S of the last heartbeat.
  POST /api/flare-preview/close      {} — explicit release: reverts his
      room to exactly what was live before the preview opened (closing the
      overlay / navigating away); also the target of a sendBeacon on tab
      close, mirroring ColorSetsPage.tsx's own unmount pattern.

A service restart mid-hold is handled separately, at process startup —
spectra/app.py's lifespan calls flare_preview_hold.recover_stale_hold().

MAXIMUM HOLD CEILING (2026-08-21): his room was held 13m54s by a client
that never stopped heartbeating — HEARTBEAT_TIMEOUT_S bounds ABANDONMENT,
not an actively heartbeating client, which is exactly what happened. See
flare_preview_hold.py's own "MAXIMUM HOLD CEILING" docstring section for
the full mechanism (MAX_HOLD_DURATION_S, the absolute ceiling; the reason
180s was chosen; why it locks against a client that keeps calling /fire or
/heartbeat afterward). Every endpoint here that arms preview_pause routes
its duration through flare_preview_hold.capped_pause_s() rather than the
raw HEARTBEAT_TIMEOUT_S, so preview_pause — the thing that actually
refuses his scene changes — can never stay armed past the same ceiling
that reverts the lights; /open additionally clears a fired ceiling's lock
(clear_ceiling_lock()), since a genuine fresh open is a deliberate new
look, never a bare heartbeat."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from spectra.models.scene import FlareKind, SceneV2
from spectra.services import (flare_preview, flare_preview_hold,
                              preview_pause, scene_store)

router = APIRouter(prefix="/api/flare-preview", tags=["spectra-flare-preview"])

# Owned by flare_preview_hold.py (its own module docstring has the full
# release-safety reasoning) — reused here verbatim, never a second,
# separately-tuned number, so there is one window to explain to him rather
# than two. Comfortably longer than the frontend's own heartbeat interval
# (planned 5s): a couple of missed beats (a slow tab, a brief network
# hiccup) must not un-pause the trigger engine out from under a preview
# that's still open.
HEARTBEAT_TIMEOUT_S = flare_preview_hold.HEARTBEAT_TIMEOUT_S


class OpenRequest(BaseModel):
    scene_id: str
    kind_name: str
    intensity: float = Field(default=1.0, ge=0.0, le=1.0)


def _resolve_scene_and_kind(scene_id: str, kind_name: str) -> tuple[SceneV2, FlareKind]:
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise HTTPException(404, "scene not found")
    kind = next((k for k in scene.flare_kinds if k.name == kind_name), None)
    if kind is None:
        raise HTTPException(404, "flare kind not found on scene")
    return scene, kind


@router.post("/open")
async def open_preview(body: OpenRequest):
    scene, kind = _resolve_scene_and_kind(body.scene_id, body.kind_name)
    timeline = await flare_preview.build_timeline(scene, kind, body.intensity)
    # A real /open is a deliberate new look — a mount, or him moving the
    # intensity slider — never a bare heartbeat, so it's always allowed to
    # clear a ceiling lock from a prior session and let a new one begin.
    flare_preview_hold.clear_ceiling_lock()
    capped = flare_preview_hold.capped_pause_s(HEARTBEAT_TIMEOUT_S)
    if capped > 0:
        preview_pause.start(capped)
    return timeline


@router.post("/fire")
async def fire_preview(body: OpenRequest):
    scene, kind = _resolve_scene_and_kind(body.scene_id, body.kind_name)
    try:
        hold = await flare_preview_hold.open_hold(
            scene, kind, body.intensity, heartbeat_timeout_s=HEARTBEAT_TIMEOUT_S)
    except Exception as exc:
        raise HTTPException(502, f"live preview fire failed: {exc}")
    if hold.get("expired"):
        # The ceiling already fired and locked the session — do NOT re-arm
        # preview_pause on top of a fire that itself refused to do anything.
        return hold
    capped = flare_preview_hold.capped_pause_s(HEARTBEAT_TIMEOUT_S)
    if capped > 0:
        preview_pause.start(capped)
    return hold


# HEARTBEAT AND CLOSE ARE SHARED WITH EVERY OTHER PREVIEW, because the
# HOLD is shared (one room, one Admiral, one hold at a time — spectra/
# services/flare_preview_hold.py). Since 2026-08-27 they live in
# spectra/api/preview.py alongside the transition and drop-sequence
# previews, and these are thin aliases onto the SAME functions so no
# client has to know which preview armed the hold it is keeping alive, and
# nothing that already calls these paths had to change.


@router.post("/heartbeat")
async def heartbeat_preview():
    from spectra.api import preview as preview_api
    return await preview_api.heartbeat_preview()


@router.post("/close")
async def close_preview():
    from spectra.api import preview as preview_api
    return await preview_api.close_preview()
