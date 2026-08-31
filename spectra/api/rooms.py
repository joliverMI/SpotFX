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
  GET    /api/rooms/{room_id}/plan        what a run at a given granularity
                                          WOULD light, and for how long —
                                          read-only, so a nineteen-emitter
                                          run is never a surprise
  POST   /api/rooms/{room_id}/map         RUN the mapping protocol at the
                                          granularity chosen for THIS run
  GET    /api/rooms/{room_id}/footprint/{emitter_id}
                                          one footprint's full grid

THE RUN IS THE ONLY ROUTE HERE THAT TOUCHES A LIGHT, and it refuses before
it does so when the phone's camera is not locked — the refusal names the
phone and the capability rather than saying "mapping failed"
(spectra/services/mapping_session.py's docstring is the binding statement).
Everything else is a read or a store write.

GRANULARITY IS PER RUN, never a stored global: `granularity` and
`block_pixels` are arguments to the map/plan routes. The room remembers the
last values only so the page's control comes back where he left it, which
is a different thing from a setting the runs read
(spectra/services/emitters.py is the binding statement for what each
granularity means).

Nothing here decides where a fixture is. The map records where each
emitter's light LANDS (spectra/models/room_map.py); a sub-device emitter's
id names a PIXEL RANGE, which is an addressing fact from the device
configuration and never a position in the room.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from spectra.models.room_map import AxisCalibration, RoomMap
from spectra.services import emitters as emitters_mod
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
    granularity: Optional[str] = None
    block_pixels: Optional[int] = None


class MapBody(BaseModel):
    """The granularity THIS run uses. Both optional: omitted means the
    room's own remembered choice, which is itself only a seed for the
    page's control."""
    granularity: Optional[str] = None
    block_pixels: Optional[int] = None


def _run_granularity(room: RoomMap, granularity: Optional[str],
                     block_pixels: Optional[int]) -> tuple[str, int]:
    g = (granularity or room.granularity or emitters_mod.DEFAULT_GRANULARITY)
    g = g.strip().lower()
    if g not in emitters_mod.GRANULARITIES:
        g = emitters_mod.DEFAULT_GRANULARITY
    try:
        block = int(block_pixels if block_pixels is not None
                    else (room.block_pixels or emitters_mod.DEFAULT_BLOCK_PIXELS))
    except (TypeError, ValueError):
        block = emitters_mod.DEFAULT_BLOCK_PIXELS
    block = max(emitters_mod.MIN_BLOCK_PIXELS,
                min(emitters_mod.MAX_BLOCK_PIXELS, block))
    return g, block


def _room_view(room: RoomMap) -> dict:
    fps = []
    for f in room.footprints:
        fps.append({
            "emitter_id": f.emitter_id, "label": f.label,
            "device_id": f.device, "whole_device": f.whole_device,
            "ranges": [r.model_dump() for r in f.ranges],
            "virtual_ids": f.virtual_ids, "mapped": f.mapped,
            "weight": round(f.weight, 4),
            "axis_profile": [round(v, 5) for v in f.axis_profile],
            "thumbnail": light_field.thumbnail(f),
            "capture": f.capture.model_dump(),
        })
    return {**room.model_dump(exclude={"footprints"}),
            "footprints": fps,
            "mapped_ids": room.mapped_ids(),
            "mapped_devices": room.mapped_devices(),
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
    if body.granularity is not None:
        room.granularity = _run_granularity(room, body.granularity, None)[0]
    if body.block_pixels is not None:
        room.block_pixels = _run_granularity(room, None, body.block_pixels)[1]
    keep = set(room.device_ids)
    # Matched on the footprint's DEVICE, not its emitter id: a device mapped
    # per segment carries several emitter ids and none of them is the device
    # id, so an emitter-id match would silently discard every measurement
    # taken at a sub-device granularity on the next room edit.
    room.footprints = [f for f in room.footprints if f.device in keep]
    return _room_view(light_field.put_room(room))


@router.delete("/rooms/{room_id}")
async def remove_room(room_id: str):
    if not light_field.delete_room(room_id):
        return JSONResponse(status_code=404, content={"detail": "no such room"})
    return {"deleted": room_id}


@router.get("/rooms/devices")
async def room_devices():
    """The device list the Room Builder picks from — the same listing the
    devices page shows, including its `in_use` flag (so "the devices he
    uses" means one thing in this app and is never re-derived here),
    MINUS everything that emits no light.

    That subtraction is the one difference between the two pages, and it is
    deliberate: `in_use` answers "does this back something driven" — right
    for /devices, wrong here, where the act is photographing what a fixture
    lights. `emitters.emits_light` carries the ruling and is the single
    place a future non-physical type joins it."""
    from spectra.services import device_console, emitters
    listing = await device_console.list_devices()
    devices = [{"id": d["id"], "name": (d.get("config") or {}).get("name") or d["id"],
                "type": d.get("type"), "in_use": d.get("in_use"),
                "virtuals": d.get("virtuals") or []}
               for d in listing.get("devices") or []
               if emitters.emits_light(d)]
    return {"devices": devices, "usage": listing.get("usage"),
            "source": listing.get("source")}


@router.get("/rooms/map/status")
async def map_status():
    return {**mapping_session.status(),
            "running_room": _running,
            "granularities": list(emitters_mod.GRANULARITIES),
            "block_pixels_default": emitters_mod.DEFAULT_BLOCK_PIXELS,
            "max_emitters_per_run": emitters_mod.MAX_EMITTERS_PER_RUN,
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


@router.get("/rooms/{room_id}/plan")
async def plan_map(room_id: str, granularity: Optional[str] = None,
                   block_pixels: Optional[int] = None):
    """What a run at this granularity WOULD light, without lighting it.

    Read-only and camera-free, deliberately: a nineteen-emitter run takes
    the room dark for over a minute, which is a different act from a
    two-emitter one, and he should see which he is about to press rather
    than learn it from a progress bar. It reports the granularity each
    device actually resolves to (his "auto" default is per device) and
    everything the enumeration declined to split, by name."""
    room = light_field.get_room(room_id)
    if room is None:
        return JSONResponse(status_code=404, content={"detail": "no such room"})
    g, block = _run_granularity(room, granularity, block_pixels)
    deps = room_mapping.production_deps(None)
    try:
        scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
    except Exception as exc:                           # noqa: BLE001
        return JSONResponse(status_code=503, content={
            "detail": f"cannot read the live virtuals: {exc}"})
    plan = await room_mapping.resolve_plan(room, deps, scope, g, block)
    body = plan.as_dict()
    body["sub_device"] = any(not e.whole_device for e in plan.emitters)
    body["spectra_owns"] = room_mapping.spectra_owns_lights()
    if body["sub_device"] and not body["spectra_owns"]:
        body["problems"] = list(body["problems"]) + [
            "SPECTRA is not driving the lights, so a sub-device run would be "
            "refused: the range lamp lives in this process."]
    return body


@router.post("/rooms/{room_id}/map")
async def run_map(room_id: str, body: Optional[MapBody] = None):
    """Run the mapping protocol for every emitter in this room, at the
    granularity chosen for THIS run.

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
    g, block = _run_granularity(room, body.granularity if body else None,
                                body.block_pixels if body else None)
    async with _run_lock:
        _running = room_id
        try:
            result = await room_mapping.run_mapping(
                room, room_mapping.production_deps(sess),
                granularity=g, block_pixels=block)
        finally:
            _running = None
    # Remember the choice for the page's control only — a run always takes
    # its own granularity as an argument, so this is never what one reads.
    stored = light_field.get_room(room_id) or room
    if (stored.granularity, stored.block_pixels) != (g, block):
        stored.granularity, stored.block_pixels = g, block
        light_field.put_room(stored)
    out = result.as_dict()
    out["room"] = _room_view(light_field.get_room(room_id) or stored)
    return out


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
