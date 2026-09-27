"""GET /api/analysed-plan?uri= — the planned analysed events for one song,
read-only: the SCENE CHANGES its generated cues will make and the FLARES
its unselected transitions will fire (spectra/services/analysed_flares.py).
Drawn by the debug page's audio-shape canvas as upcoming markers.

No second copy of the computation: flares come from the trigger engine's
own cached plan when `uri` is the song it is playing (the exact list it
fires), else from analysed_flares.plan_for_song — the one function that
plan was built by. Scene changes are the song's enabled stored GENERATED
fire_scene triggers (what actually fires), falling back to the plan's kept
cues while none are stored yet (the first play, before auto-generation
lands). Both lists are empty, with `applies: false` and the reason, when
the room's per-song mode does not let analysed events fire
(analysed_flares.analysed_flares_allowed — the same rule tick() applies).

Every time is SONG time, the stored-trigger convention (timestamp + the
trigger's own offset). `show_clock_shift_ms` is how far the trigger clock
reads ahead of the bridge's effective position right now, so a client
drawing against its own playhead can place a marker where the event fires.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from spectra.services import analysed_flares, trigger_store
from spectra.services.room_controls import load_room_controls
from spectra.services.trigger_engine import TriggerEngine, trigger_engine

router = APIRouter(prefix="/api", tags=["spectra-analysed-plan"])


def _plan(uri: str) -> dict:
    stored = trigger_store.list_for_song(uri)
    mode = TriggerEngine._effective_mode_for_song(
        load_room_controls().scene_change_mode, stored)
    has_authored = any(t.source == "authored" for t in stored)
    base = {"uri": uri, "effective_mode": mode, "has_authored": has_authored}
    if not analysed_flares.analysed_flares_allowed(mode, has_authored):
        reason = ("transitions only — analysed events never fire"
                  if mode == "transitions"
                  else "this song has your own triggers — analysed events are off for it")
        return {**base, "applies": False, "reason": reason,
                "scene_changes": [], "flares": [], "scene_source": None}

    cached = trigger_engine.cached_flare_triggers(uri)
    plan = None
    if cached is not None:
        flares = [{"timestamp_ms": t.timestamp_ms, "intensity": t.action.intensity}
                  for t in cached]
    else:
        plan = analysed_flares.plan_for_song(uri, stored)
        flares = [{"timestamp_ms": m.timestamp_ms, "intensity": m.intensity}
                  for m in plan.flares]

    def planned():
        nonlocal plan
        if plan is None:
            plan = analysed_flares.plan_for_song(uri, stored)
        return plan.scene_cues

    moments, scene_source = analysed_flares.scene_change_moments(stored, planned)
    scene = [{"timestamp_ms": m.timestamp_ms, "intensity": m.intensity}
             for m in moments]
    return {**base, "applies": True, "reason": None, "scene_source": scene_source,
            "scene_changes": scene, "flares": flares}


@router.get("/analysed-plan")
async def get_analysed_plan(uri: str = Query(..., min_length=1)):
    from spectra.services import engine
    body = await asyncio.to_thread(_plan, uri)
    try:
        body["show_clock_shift_ms"] = engine.show_clock_shift_ms()
    except Exception:
        body["show_clock_shift_ms"] = 0
    return body
