"""Room colour journey + drift profiles — agent-adjusted surfaces (no
settings forms; the one graphical piece is a follow profile's curve, drawn
in the editor).

  GET /api/room-journey      — RoomColorState (journey declaration + wheel
                               position + the current destination bearing)
  PUT /api/room-journey      — replace the room's journey declaration
  GET /api/drift-profiles    — {profile_id: DriftProfile}
  PUT /api/drift-profiles    — replace the library (refs validated)
  POST /api/room-color/apply — apply a colour set (or a Group — §10, picks
                               one member and merges the group's own
                               override entries on top) to the room
                               directly ({"set_id": ...}): it becomes the
                               active set, the wheel anchors at its
                               position, colours land on live virtuals, the
                               journey travels on from there. The supported
                               manual surface for the owner/fleet (owner
                               defect fix — a room must never be set-less).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from spectra.services import color_journey, color_set_groups, drift_profiles, scene_store
from spectra.services.color_journey import RoomColorState
from spectra.services.drift_profiles import DriftProfile

router = APIRouter(prefix="/api", tags=["spectra-journey"])


class ApplySetRequest(BaseModel):
    set_id: str


@router.post("/room-color/apply")
async def apply_room_color(body: ApplySetRequest):
    try:
        card = color_set_groups.resolve_ref(body.set_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    from spectra.services import engine
    return await engine.conductor.apply_set_directly(card)


@router.get("/room-journey")
async def get_room_journey():
    return color_journey.load_room().model_dump()


@router.put("/room-journey")
async def put_room_journey(state: RoomColorState):
    # The journey declaration is the agent-adjusted part; wheel position,
    # active set, and the destination bearing are runtime state — preserve
    # the stored values so an agent PUT can't teleport the room's colour
    # story or steer its bearing by hand (the selector owns that).
    current = color_journey.load_room()
    color_journey.save_room(current.model_copy(update={"journey": state.journey}))
    return {"status": "saved",
            "degrees_per_min": state.journey.degrees_per_min}


@router.get("/drift-profiles")
async def get_drift_profiles():
    return {pid: p.model_dump() for pid, p in drift_profiles.load_all().items()}


@router.put("/drift-profiles")
async def put_drift_profiles(profiles: dict[str, DriftProfile]):
    mismatched = sorted(pid for pid, p in profiles.items() if pid != p.id)
    if mismatched:
        raise HTTPException(422, f"key does not match profile id: {', '.join(mismatched)}")
    # Profiles still referenced by scene drift declarations must survive.
    referenced = {ref.profile
                  for scene in scene_store.list_all()
                  for dev in scene.devices
                  for ref in dev.drift.values()
                  if ref.profile is not None}
    orphaned = sorted(referenced - set(profiles))
    if orphaned:
        raise HTTPException(
            422, f"scenes still reference drift profile id(s): {', '.join(orphaned)}")
    drift_profiles.save_all(profiles)
    return {"status": "saved", "profiles": len(profiles)}
