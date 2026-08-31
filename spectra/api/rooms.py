"""ROOMS + the light-field mapping wire.

  GET    /api/rooms                       every room, with each emitter's
                                          mapped/not state and a small heat
                                          thumbnail (numbers, not an image)
  POST   /api/rooms                       create / update a room (name,
                                          devices, axis calibration)
  DELETE /api/rooms/{room_id}             remove a room (its footprints go
                                          with it — a map belongs to a pose,
                                          and a deleted room has no pose)
  GET    /api/rooms/devices               the used-by-default device list,
                                          the SAME ground truth /devices
                                          shows (device_console + device_usage)
  WS     /api/rooms/map/ws                the phone's capture session
  GET    /api/rooms/map/status            live session status + refusal
  GET    /api/rooms/map/frame/latest      newest tapped frame, as an 8-bit
                                          greyscale PGM, for checking aim
  POST   /api/rooms/{room_id}/map         RUN the mapping protocol
  GET    /api/rooms/{room_id}/footprint/{emitter_id}
                                          one footprint's full grid

THE RUN IS THE ONLY ROUTE HERE THAT TOUCHES A LIGHT, and it refuses before
it does so when the phone's camera is not locked — the refusal names the
phone and the capability rather than saying "mapping failed"
(spectra/services/mapping_session.py's docstring is the binding statement).
Everything else is a read or a store write.

Nothing here decides where a fixture is. The map records where each
emitter's light LANDS (spectra/models/room_map.py).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from spectra.models.room_map import AxisCalibration, RoomMap
from spectra.services import light_field, mapping_session, room_mapping

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["spectra-rooms"])

#: One mapping run at a time, process-wide — a second one would fight the
#: first for the held room and for the same phone's frames.
_run_lock = asyncio.Lock()
_running: Optional[str] = None


class RoomBody(BaseModel):
    id: Optional[str] = None
    name: str
    device_ids: list[str] = []
    axis: Optional[AxisCalibration] = None


def _room_view(room: RoomMap) -> dict:
    fps = []
    for f in room.footprints:
        fps.append({
            "emitter_id": f.emitter_id, "label": f.label,
            "virtual_ids": f.virtual_ids, "mapped": f.mapped,
            "weight": round(f.weight, 4),
            "axis_profile": [round(v, 5) for v in f.axis_profile],
            "thumbnail": light_field.thumbnail(f),
            "capture": f.capture.model_dump(),
        })
    return {**room.model_dump(exclude={"footprints"}),
            "footprints": fps,
            "mapped_ids": room.mapped_ids(),
            "unmapped_ids": room.unmapped_ids()}


@router.get("/rooms")
async def list_rooms():
    return {"rooms": [_room_view(r) for r in light_field.load_rooms()]}


@router.post("/rooms")
async def upsert_room(body: RoomBody):
    """Create or update. An existing room keeps its FOOTPRINTS across an
    edit — renaming a room or adding a device must not silently discard
    measurements that took a dark room to collect. Removing a device DOES
    drop its footprint: it is no longer part of this room."""
    existing = light_field.get_room(body.id) if body.id else None
    room = existing or RoomMap(name=body.name)
    room.name = body.name
    room.device_ids = list(dict.fromkeys(body.device_ids))
    if body.axis is not None:
        room.axis = body.axis
    keep = set(room.device_ids)
    room.footprints = [f for f in room.footprints if f.emitter_id in keep]
    return _room_view(light_field.put_room(room))


@router.delete("/rooms/{room_id}")
async def remove_room(room_id: str):
    if not light_field.delete_room(room_id):
        return JSONResponse(status_code=404, content={"detail": "no such room"})
    return {"deleted": room_id}


@router.get("/rooms/devices")
async def room_devices():
    """The device list the Room Builder picks from — the SAME listing the
    devices page shows, including its `in_use` flag, so "the devices he
    uses" means one thing in this app and is never re-derived here."""
    from spectra.services import device_console
    listing = await device_console.list_devices()
    devices = [{"id": d["id"], "name": (d.get("config") or {}).get("name") or d["id"],
                "type": d.get("type"), "in_use": d.get("in_use"),
                "virtuals": d.get("virtuals") or []}
               for d in listing.get("devices") or []]
    return {"devices": devices, "usage": listing.get("usage"),
            "source": listing.get("source")}


@router.get("/rooms/map/status")
async def map_status():
    return {**mapping_session.status(),
            "running_room": _running,
            "protocol": {
                "dark_settle_s": room_mapping.DARK_SETTLE_S,
                "dark_capture_s": room_mapping.DARK_CAPTURE_S,
                "lit_settle_s": room_mapping.LIT_SETTLE_S,
                "lit_capture_s": room_mapping.LIT_CAPTURE_S,
                "min_frames": room_mapping.MIN_FRAMES,
            }}


@router.get("/rooms/map/frame/latest")
async def map_frame_latest():
    """The newest tapped frame, so a human can check the phone's aim.

    Served as a binary PGM (P5) — the raw greyscale bytes with a 15-byte
    header — because that is what arrived; re-encoding it would put an
    image library in a path that needs none, and this is a diagnostic view,
    not an asset. Never stored."""
    sess = mapping_session.current
    frame = sess.frames.latest() if (sess is not None and not sess.closed) else None
    if frame is None:
        return JSONResponse(status_code=404, content={"detail": "no tapped frame"})
    header = f"P5\n{frame.width} {frame.height}\n255\n".encode("ascii")
    return Response(content=header + frame.data, media_type="image/x-portable-graymap",
                    headers={"Cache-Control": "no-store"})


@router.post("/rooms/{room_id}/map")
async def run_map(room_id: str):
    """Run the mapping protocol for every device in this room.

    One run at a time; a second request while one is live is refused by
    name rather than queued — two runs would fight over the same held room
    and the same phone."""
    global _running
    room = light_field.get_room(room_id)
    if room is None:
        return JSONResponse(status_code=404, content={"detail": "no such room"})
    sess = mapping_session.current
    if sess is None or sess.closed:
        return JSONResponse(status_code=409, content={
            "detail": "no phone connected — open this page on the phone that "
                      "will do the capture and start its camera"})
    if _run_lock.locked():
        return JSONResponse(status_code=409, content={
            "detail": f"a mapping run is already in progress ({_running})"})
    async with _run_lock:
        _running = room_id
        try:
            result = await room_mapping.run_mapping(
                room, room_mapping.production_deps(sess))
        finally:
            _running = None
    body = result.as_dict()
    body["room"] = _room_view(light_field.get_room(room_id) or room)
    return body


@router.get("/rooms/{room_id}/footprint/{emitter_id}")
async def get_footprint(room_id: str, emitter_id: str):
    room = light_field.get_room(room_id)
    fp = room.footprint(emitter_id) if room else None
    if fp is None:
        return JSONResponse(status_code=404, content={"detail": "not mapped"})
    from spectra.models.room_map import GRID_H, GRID_W
    return {"emitter_id": fp.emitter_id, "width": GRID_W, "height": GRID_H,
            "grid": fp.grid, "axis_profile": fp.axis_profile,
            "weight": fp.weight, "capture": fp.capture.model_dump()}


@router.websocket("/rooms/map/ws")
async def rooms_map_ws(ws: WebSocket):
    await ws.accept()
    sess = await mapping_session.open_session(ws.send_json)
    try:
        while True:
            msg = await ws.receive_json()
            if isinstance(msg, dict):
                await sess.handle(msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        # A malformed message must not leave a run holding the room: the
        # session close below drops every ring, and any hold in flight is
        # reverted by flare_preview_hold's own sweep on its own clock.
        logger.exception("room mapping ws: session %s failed", sess.id)
    finally:
        sess.run_abort = sess.run_abort or "the phone disconnected"
        await mapping_session.close_session(sess)
