"""The 2D drift gradient library — GET/PUT the whole profile dict, same
shape as GET/PUT /api/sequencer/curves and GET/PUT /api/drift-profiles.
Which gradient (if any) is currently ACTIVE lives on RoomControlState
(active_gradient_id) via GET/PUT /api/room-controls, not here.

  GET/PUT /api/gradients2d
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from spectra.models.gradient2d import GradientProfile
from spectra.services import gradient2d_store

router = APIRouter(prefix="/api", tags=["spectra-gradient2d"])


@router.get("/gradients2d")
async def get_gradients2d():
    return {pid: p.model_dump() for pid, p in gradient2d_store.load_all().items()}


@router.put("/gradients2d")
async def put_gradients2d(profiles: dict[str, GradientProfile]):
    mismatched = sorted(pid for pid, p in profiles.items() if pid != p.id)
    if mismatched:
        raise HTTPException(422, f"key does not match profile id: {', '.join(mismatched)}")
    gradient2d_store.save_all(profiles)
    return {"status": "saved", "profiles": len(profiles)}
