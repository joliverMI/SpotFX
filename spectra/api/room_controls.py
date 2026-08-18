"""SPECTRA's room-control surface (spectra-kept-equivalents) — agent-tellable
room-wide switches with a compact UI control on the room bar:

  GET /api/room-controls  — RoomControlState
  PUT /api/room-controls  — replace it (the frontend round-trips the whole
                            object, same shape as PUT /api/room-journey)

See services/room_controls.py for what each field means and where it's
applied (fx_executor + scene_compiler write seams for brightness_multiplier;
global_transition_ms is state-only). ambient_mode/_color drive the live
Hue takeover in services/ambient.py via services/ambient_music_gate.py —
PUT reconciles it (only when the ambient fields actually changed, to
avoid re-triggering a stream reconnect on every unrelated slider commit)
and folds the outcome
into the response as `ambient_result` so the caller can tell a live takeover
from a state-only save (SPECTRA dark, or no Hue devices in the room).
display_mode/display_light_bg_*/dark_light_shield_* — the legacy global
Default/Dark/Light mode (services/dark_light.py) — PUT reconciles it the
same way (only when it actually changed) and folds the outcome into the
response as `dark_light_result`.
force_scene_enabled/force_scene_scene_id — the legacy Now Playing Force
Scene control — redirect every automatic scene pick at scene_sequencer.
fire_scene_by_id, AND (2026-08-18) fire the pinned scene immediately on
the edit that pins/repins it (room_controls.reconcile_force_scene_if_changed)
— see that function's own docstring for why the redirect alone isn't
enough. Folded into the response as `force_scene_result`.
ambient_hue_group_ids — WHICH Hue entertainment areas Ambient reaches
(services/ambient.py, "Hue entertainment-area selection"); [] = every
live Hue device (today's unmodified default).

  GET /room-controls/ambient-groups — {id, name} for every live Hue
  device the ambient_hue_group_ids picker can choose from (the direct
  analogue of legacy's GET /control/ambient-groups) — the room bar's
  group picker's data source.
"""
from __future__ import annotations

from fastapi import APIRouter

from spectra.services import ambient, room_controls
from spectra.services.room_controls import RoomControlState

router = APIRouter(prefix="/api", tags=["spectra-room-controls"])


@router.get("/room-controls")
async def get_room_controls():
    return room_controls.load_room_controls().model_dump()


@router.get("/room-controls/ambient-groups")
async def ambient_groups():
    return {"groups": await ambient.list_groups()}


@router.put("/room-controls")
async def put_room_controls(state: RoomControlState):
    previous = room_controls.load_room_controls()
    room_controls.save_room_controls(state)
    response: dict = {"status": "saved", **state.model_dump()}
    ambient_result = await room_controls.reconcile_ambient_if_changed(previous, state)
    if ambient_result is not None:
        response["ambient_result"] = ambient_result
    dark_light_result = await room_controls.reconcile_dark_light_if_changed(previous, state)
    if dark_light_result is not None:
        response["dark_light_result"] = dark_light_result
    force_scene_result = await room_controls.reconcile_force_scene_if_changed(previous, state)
    if force_scene_result is not None:
        response["force_scene_result"] = force_scene_result
    return response
