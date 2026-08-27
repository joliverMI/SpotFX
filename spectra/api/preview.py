"""Scrubbing previews for the two things a trigger can move that are NOT a
single flare kind: a scene-to-scene TRANSITION and the charge/lull/drop
SEQUENCE (2026-08-27, fm/flare-preview-offsets-everywhere — the second half
of his own sequencing, "start with the flares, then we will do lull charge
drop").

SAME SHAPE AS THE FLARE PREVIEW, deliberately and to the letter — see
spectra/api/flare_preview.py's docstring for the full reasoning behind each
piece, and spectra/services/flare_preview_hold.py for why there is exactly
ONE hold behind all three:

  POST /open   computes the timeline ONLY (hardware-free) and arms
               preview_pause, so HIS LIVE SHOW STOPS the instant a preview
               opens. No light changes yet. Call again on any control
               change (intensity, a gap slider) to recompute.
  POST /fire   runs ONE named STEP of the preview's program live and
               re-arms the pause. The frontend calls this once per cue per
               lap, timed against times THIS SERVER computed and returned —
               it never derives a moment of its own.
  heartbeat/close are shared with the flare preview because the HOLD is
  shared: one room, one Admiral, one hold at a time. They live here under
  /api/preview and the flare router keeps its own paths as thin aliases
  onto the same functions, so no client has to know which preview armed
  the hold it is keeping alive.

THE CEILING AND THE PAUSE-CAP APPLY UNCHANGED. Every arm routes through
flare_preview_hold.capped_pause_s() and every /fire checks
locked_until_reopen(), so a transition or a drop sequence cannot hold his
room past MAX_HOLD_DURATION_S any more than a flare can — the 13m54s
incident's fix is a property of the hold, not of the flare route that
happened to be written first.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from spectra.models.scene import SceneV2
from spectra.services import (flare_preview_hold, phase_preview, preview_pause,
                              scene_store, transition_preview)

router = APIRouter(prefix="/api/preview", tags=["spectra-preview"])

HEARTBEAT_TIMEOUT_S = flare_preview_hold.HEARTBEAT_TIMEOUT_S


def _scene(scene_id: str) -> SceneV2:
    scene = scene_store.get_by_id(scene_id)
    if scene is None:
        raise HTTPException(404, "scene not found")
    return scene


def _arm_pause() -> None:
    capped = flare_preview_hold.capped_pause_s(HEARTBEAT_TIMEOUT_S)
    if capped > 0:
        preview_pause.start(capped)


class TransitionRequest(BaseModel):
    to_scene_id: str
    # None = transition FROM the scene itself, i.e. a re-fire of the same
    # scene. That is a legitimate thing to look at (it is what an ordinary
    # same-effect crossfade looks like) and it is the only default that
    # needs no live-room read, so a preview never depends on what the room
    # happens to be showing when he opens it.
    from_scene_id: Optional[str] = None
    intensity: float = Field(default=1.0, ge=0.0, le=1.0)
    step: str = "fire"


class SequenceRequest(BaseModel):
    scene_id: str
    intensity: float = Field(default=1.0, ge=0.0, le=1.0)
    # How far each stretching class's NEXT mark sits ahead of it — the very
    # thing a charge/lull ramp stretches to fill, so it is the one control
    # that changes the drawn shape. Absent = the derived defaults that
    # reproduce the tuned unknown-gap ramps (phase_preview.DEFAULT_GAP_MS).
    charge_gap_ms: Optional[int] = Field(default=None, ge=200, le=60_000)
    lull_gap_ms: Optional[int] = Field(default=None, ge=200, le=60_000)
    step: str = "charge"

    def gaps(self) -> dict[str, int]:
        out: dict[str, int] = {}
        if self.charge_gap_ms is not None:
            out["charge"] = self.charge_gap_ms
        if self.lull_gap_ms is not None:
            out["lull"] = self.lull_gap_ms
        return out


@router.post("/transition/open")
async def open_transition(body: TransitionRequest):
    to_scene = _scene(body.to_scene_id)
    from_scene = (_scene(body.from_scene_id) if body.from_scene_id
                  else to_scene)
    timeline = await transition_preview.build_timeline(
        from_scene, to_scene, body.intensity)
    flare_preview_hold.clear_ceiling_lock()
    _arm_pause()
    return timeline


@router.post("/transition/fire")
async def fire_transition(body: TransitionRequest):
    to_scene = _scene(body.to_scene_id)
    from_scene = (_scene(body.from_scene_id) if body.from_scene_id
                  else to_scene)
    program = transition_preview.TransitionProgram(from_scene, to_scene)
    return await _fire(program, body.intensity, body.step)


@router.post("/sequence/open")
async def open_sequence(body: SequenceRequest):
    scene = _scene(body.scene_id)
    timeline = await phase_preview.build_timeline(
        scene, body.intensity, gaps=body.gaps())
    flare_preview_hold.clear_ceiling_lock()
    _arm_pause()
    return timeline


@router.post("/sequence/fire")
async def fire_sequence(body: SequenceRequest):
    scene = _scene(body.scene_id)
    program = phase_preview.PhaseSequenceProgram(scene, body.gaps())
    return await _fire(program, body.intensity, body.step)


async def _fire(program, intensity: float, step: str):
    if step not in program.steps:
        raise HTTPException(422, f"unknown step {step!r} for this preview")
    try:
        hold = await flare_preview_hold.open_program_hold(
            program, intensity, step=step,
            heartbeat_timeout_s=HEARTBEAT_TIMEOUT_S)
    except Exception as exc:
        raise HTTPException(502, f"live preview fire failed: {exc}")
    if hold.get("expired"):
        # The ceiling already fired and locked the session — never re-arm
        # the pause on top of a fire that itself refused to do anything.
        return hold
    _arm_pause()
    return hold


@router.post("/heartbeat")
async def heartbeat_preview():
    """Shared by every preview — the HOLD is shared, so its keep-alive is
    too. Identical semantics to the flare route this was factored out of."""
    if flare_preview_hold.locked_until_reopen():
        return {"active": False, "remaining_s": 0.0,
                "expired": True, "reason": "max_duration"}
    capped = flare_preview_hold.capped_pause_s(HEARTBEAT_TIMEOUT_S)
    if capped <= 0:
        return {"active": False, "remaining_s": 0.0,
                "expired": True, "reason": "max_duration"}
    preview_pause.start(capped)
    await flare_preview_hold.touch(HEARTBEAT_TIMEOUT_S)
    return {"active": True, "remaining_s": preview_pause.remaining_s()}


@router.post("/close")
async def close_preview():
    preview_pause.clear()
    release = await flare_preview_hold.close_hold()
    return {"active": False, "live": release}
