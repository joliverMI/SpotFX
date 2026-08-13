"""
SpotFX — Shape Map API router (proxy to LedFX's /api/virtuals/{id}/shape).

Endpoints:
  GET  /api/shape-maps/{virtual_id}   — current map text + compiled summary
  POST /api/shape-maps/{virtual_id}   — {text, dry_run}: validate/preview or
                                        apply; LedFX's per-line errors and
                                        visualizer payload pass through.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api import ledfx_client

router = APIRouter(prefix="/api/shape-maps", tags=["shape-maps"])


class ShapeMapBody(BaseModel):
    text: str
    dry_run: bool = False


@router.get("/{virtual_id}")
async def get_shape_map(virtual_id: str):
    res = await ledfx_client.get_virtual_shape(virtual_id)
    if not res:
        raise HTTPException(status_code=502, detail="LedFX unreachable")
    return res


@router.post("/{virtual_id}")
async def post_shape_map(virtual_id: str, body: ShapeMapBody):
    res = await ledfx_client.put_virtual_shape(
        virtual_id, body.text, dry_run=body.dry_run
    )
    if not res:
        raise HTTPException(status_code=502, detail="LedFX unreachable")
    return res
