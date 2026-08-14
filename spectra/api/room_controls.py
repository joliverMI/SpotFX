"""SPECTRA's room-control surface (spectra-kept-equivalents) — agent-tellable
room-wide switches with a compact UI control on the room bar:

  GET /api/room-controls  — RoomControlState
  PUT /api/room-controls  — replace it (the frontend round-trips the whole
                            object, same shape as PUT /api/room-journey)

See services/room_controls.py for what each field means and where it's
applied (fx_executor + scene_compiler write seams for brightness_multiplier;
ambient_enabled/_color and global_transition_ms are state-only today — the
full Ambient/Dinner-Party room-MODES build is a separate checklist item).
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
    room_controls.save_room_controls(state)
    return {"status": "saved", **state.model_dump()}
