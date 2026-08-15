"""SPECTRA's room-control surface (spectra-kept-equivalents) — agent-tellable
room-wide switches with a compact UI control on the room bar:

  GET /api/room-controls  — RoomControlState
  PUT /api/room-controls  — replace it (the frontend round-trips the whole
                            object, same shape as PUT /api/room-journey)

See services/room_controls.py for what each field means and where it's
applied (fx_executor + scene_compiler write seams for brightness_multiplier;
global_transition_ms is state-only). ambient_enabled/_color drive the live
Hue takeover in services/ambient.py — PUT reconciles it (only when the
ambient fields actually changed, to avoid re-triggering a stream
reconnect/reconnect on every unrelated slider commit) and folds the outcome
into the response as `ambient_result` so the caller can tell a live takeover
from a state-only save (SPECTRA dark, or no Hue devices in the room).
force_scene_enabled/force_scene_scene_id — the legacy Now Playing Force
Scene control — redirect every automatic scene pick at scene_sequencer.
fire_scene_by_id.
"""
from __future__ import annotations

from fastapi import APIRouter

from spectra.services import room_controls
from spectra.services.room_controls import RoomControlState

router = APIRouter(prefix="/api", tags=["spectra-room-controls"])


@router.get("/room-controls")
async def get_room_controls():
    return room_controls.load_room_controls().model_dump()


@router.put("/room-controls")
async def put_room_controls(state: RoomControlState):
    previous = room_controls.load_room_controls()
    room_controls.save_room_controls(state)
    response: dict = {"status": "saved", **state.model_dump()}
    ambient_result = await room_controls.reconcile_ambient_if_changed(previous, state)
    if ambient_result is not None:
        response["ambient_result"] = ambient_result
    return response
