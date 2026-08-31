"""ROOM EFFECTS — the wire for the one built field kind (Dim Wave) over a
room's measured light map.

  GET    /api/room-effects                every authored effect + the field
                                          interface's own catalogue (which
                                          kinds exist, which are BUILT)
  POST   /api/room-effects                create / update one
  DELETE /api/room-effects/{effect_id}    remove one
  GET    /api/room-effects/status         what is running, the live gains,
                                          and the MEASURED write cost
  POST   /api/room-effects/{id}/start     hold the room and run it
  POST   /api/room-effects/stop           stop and hand the room back
  POST   /api/room-effects/heartbeat      keep the held room alive while the
                                          page is open

START AND STOP ARE THE ONLY ROUTES THAT TOUCH A LIGHT, and both go through
the one held-room seam (spectra/services/room_effects.py's docstring). The
page must heartbeat: stop calling and the hold lapses on its own within
flare_preview_hold's own window, and the room comes back with no route
having been called at all — a closed tab is a handled case, not a lost show.

`preview` and `run` are THE SAME MECHANISM here, deliberately: both hold the
room, both compose on top of the running show, both are bounded by the
hold's 3-minute ceiling. There is no second, longer-lived path to get wrong.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from spectra.services import flare_preview_hold, light_field, room_effects
from spectra.services.light_field_fields import KINDS

router = APIRouter(prefix="/api", tags=["spectra-room-effects"])


class EffectBody(BaseModel):
    id: Optional[str] = None
    room_id: str
    name: str = "Dim Wave"
    kind: str = "dim_wave"
    wavelength: float = 1.0
    speed: float = 0.25
    depth: float = 0.6
    carrier_ids: list[str] = []


@router.get("/room-effects")
async def list_effects():
    return {"effects": [e.model_dump() for e in room_effects.load_effects()],
            "kinds": KINDS,
            "tick_hz": room_effects.TICK_HZ}


@router.post("/room-effects")
async def upsert_effect(body: EffectBody):
    if body.kind not in KINDS:
        return JSONResponse(status_code=400, content={
            "detail": f"unknown effect kind {body.kind!r}"})
    if not KINDS[body.kind]["built"]:
        return JSONResponse(status_code=400, content={
            "detail": f"{body.kind!r} is declared in the field interface but "
                      f"not built in this slice — only 'dim_wave' drives "
                      f"lights today"})
    if light_field.get_room(body.room_id) is None:
        return JSONResponse(status_code=404, content={"detail": "no such room"})
    data = body.model_dump()
    if not data.get("id"):
        data.pop("id", None)
    spec = room_effects.RoomEffectSpec(**data)
    return room_effects.put_effect(spec).model_dump()


@router.delete("/room-effects/{effect_id}")
async def remove_effect(effect_id: str):
    if not room_effects.delete_effect(effect_id):
        return JSONResponse(status_code=404, content={"detail": "no such effect"})
    return {"deleted": effect_id}


@router.get("/room-effects/status")
async def effect_status():
    return room_effects.status()


@router.post("/room-effects/stop")
async def stop_effect():
    return await room_effects.stop()


@router.post("/room-effects/heartbeat")
async def heartbeat():
    """Re-arm the held room. No recompute, no re-fire — the same contract
    flare_preview_hold.touch has, reused rather than re-implemented."""
    await flare_preview_hold.touch(room_effects.HOLD_HEARTBEAT_S)
    return {"held": flare_preview_hold.active()}


@router.post("/room-effects/{effect_id}/start")
async def start_effect(effect_id: str):
    spec = next((e for e in room_effects.load_effects() if e.id == effect_id), None)
    if spec is None:
        return JSONResponse(status_code=404, content={"detail": "no such effect"})
    room = light_field.get_room(spec.room_id)
    if room is None:
        return JSONResponse(status_code=404, content={"detail": "no such room"})
    try:
        result = await room_effects.start(room, spec)
    except Exception as exc:                           # noqa: BLE001
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    if not result.get("running"):
        return JSONResponse(status_code=409, content=result)
    return result
