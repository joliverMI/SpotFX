"""The Live view's Room map (spectra/services/room_view.py):

  GET /api/room-view/poses              — the camera poses that have
                                          something to draw, newest first
  GET /api/room-view?pose=<id>          — one pose: the glow of every mapped
                                          emitter, every fixture pixel as a
                                          placed or unplaced piece, and his
                                          hand placements
  PUT /api/room-view/placements/{pose}  — merge hand placements (a null
                                          value removes one). The only write
                                          on this surface, and it writes only
                                          the view's own store.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from spectra.services import room_view

router = APIRouter(prefix="/api", tags=["spectra-room-view"])


class PlacementsBody(BaseModel):
    placements: dict[str, Optional[room_view.Placement]] = Field(max_length=500)


@router.get("/room-view/poses")
async def get_poses():
    return {"poses": await asyncio.to_thread(room_view.current_poses)}


@router.get("/room-view")
async def get_view(pose: str):
    view = await asyncio.to_thread(room_view.current_view, pose)
    if view is None:
        raise HTTPException(404, f"no camera pose {pose!r} has anything mapped")
    return view


@router.put("/room-view/placements/{pose_id}")
async def put_placements(pose_id: str, body: PlacementsBody):
    known = {p["pose_id"] for p in await asyncio.to_thread(room_view.current_poses)}
    if pose_id not in known:
        raise HTTPException(404, f"no camera pose {pose_id!r} has anything mapped")
    if any(len(key) > room_view.MAX_KEY_LENGTH for key in body.placements):
        raise HTTPException(422, "a placement key is too long")
    try:
        stored = await asyncio.to_thread(room_view.put_placements, pose_id, body.placements)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"pose_id": pose_id, "placements": stored}
