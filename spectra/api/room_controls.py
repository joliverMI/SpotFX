"""SPECTRA's room-control surface (spectra-kept-equivalents) — agent-tellable
room-wide switches with a compact UI control on the room bar:

  GET /api/room-controls  — RoomControlState
  PUT /api/room-controls  — a TRUE PARTIAL UPDATE (2026-08-30): the body's
                            keys are overlaid onto the CURRENT stored state
                            and the merged result is validated through
                            RoomControlState; every field the body does not
                            name is byte-preserved. The frontend still
                            round-trips the whole object, which overlays
                            every key and is therefore unchanged. Before
                            this, a partial body reset every unnamed field
                            to its model default and saved that — two of the
                            owner's real values were confirmed wiped that
                            way. The merge and the retired-`ambient_mode`
                            compatibility alias both live in services/
                            room_controls.py (merge_room_controls /
                            AMBIENT_MODE_ALIAS); read the block comment
                            above them before touching this handler.

See services/room_controls.py for what each field means and where it's
applied (fx_executor + scene_compiler write seams for brightness_multiplier;
global_transition_ms is state-only). ambient_enabled/ambient_on_music_pause/
_color drive the live Hue takeover in services/ambient.py via services/
ambient_music_gate.py — PUT reconciles it (only when the ambient fields
actually changed, to avoid re-triggering a stream reconnect on every
unrelated slider commit) and folds the outcome into the response as
`ambient_result`. Since 2026-08-30 that outcome is the START of the
transition, not its end — `{"status": "turning_on"/"turning_off", "intent",
"phase"}` — because blocking his press for the whole 15-22s sequence is
where "I don't know if it has started" began. The finished outcome arrives
on the pushed ambient_status websocket message and on GET /api/engine/
status's `ambient` key; a state-only save (SPECTRA dark, or no Hue devices
in the room) still says so there.
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

force_color_enabled/force_color_target_id — FORCE COLOUR (owner ask
2026-08-27), Force Scene's twin one axis over: the room's colour stops
changing and stays on the pinned colour SET or GROUP. Same active half for
the same reason — every gate it installs is a redirect on a choice
something else was about to make, so enabling/repinning applies the pinned
colours immediately (room_controls.reconcile_force_color_if_changed) rather
than waiting for an occasion that may never come. Folded into the response
as `force_color_result`. See spectra/services/force_color.py's module
docstring for the gates and the precedence rulings.
ambient_hue_group_ids — WHICH Hue entertainment areas Ambient reaches
(services/ambient.py, "Hue entertainment-area selection"); [] = every
live Hue device (today's unmodified default).

  GET /room-controls/ambient-groups — {id, name} for every live Hue
  device the ambient_hue_group_ids picker can choose from (the direct
  analogue of legacy's GET /control/ambient-groups) — the room bar's
  group picker's data source.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from spectra.services import ambient, room_controls

router = APIRouter(prefix="/api", tags=["spectra-room-controls"])


@router.get("/room-controls")
async def get_room_controls():
    return room_controls.load_room_controls().model_dump()


@router.get("/room-controls/ambient-groups")
async def ambient_groups():
    return {"groups": await ambient.list_groups()}


@router.put("/room-controls")
async def put_room_controls(body: Any = Body(...)):
    """A TRUE PARTIAL UPDATE: only the keys the caller actually SENT are
    overlaid onto the current stored state, the merged result is validated
    through RoomControlState exactly as the old whole-object bind was, and
    every unnamed field is byte-preserved.

    This handler used to bind `body` straight to RoomControlState, so a
    partial body silently reset every unnamed field to its model default
    and persisted that — real losses landed in the owner's own file (his
    av_sync_lead_ms calibration, his force_scene_scene_id pin). The merge
    lives in services/room_controls.merge_room_controls; read the block
    comment above it for why the merge is the fix and a per-key patch is
    not (the caller list is structurally unknowable through the proxy hop).

    A full-body PUT — the web UI's own shape — overlays every key and is
    therefore byte-identical to the previous behaviour. The retired
    `ambient_mode` key is accepted as a compatibility alias (see
    services/room_controls.AMBIENT_MODE_ALIAS); when a body carries both it
    and a new key, the NEW key wins and the response says so in
    `ambient_mode_alias`."""
    previous = room_controls.load_room_controls()
    try:
        state, alias_note = room_controls.merge_room_controls(previous, body)
    except room_controls.RoomControlsPatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    room_controls.save_room_controls(state)
    response: dict = {"status": "saved", **state.model_dump()}
    if alias_note is not None:
        response["ambient_mode_alias"] = alias_note
    ambient_result = await room_controls.reconcile_ambient_if_changed(previous, state)
    if ambient_result is not None:
        response["ambient_result"] = ambient_result
    dark_light_result = await room_controls.reconcile_dark_light_if_changed(previous, state)
    if dark_light_result is not None:
        response["dark_light_result"] = dark_light_result
    force_scene_result = await room_controls.reconcile_force_scene_if_changed(previous, state)
    if force_scene_result is not None:
        response["force_scene_result"] = force_scene_result
    force_color_result = await room_controls.reconcile_force_color_if_changed(previous, state)
    if force_color_result is not None:
        response["force_color_result"] = force_color_result
    return response
