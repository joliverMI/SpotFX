"""Device-preview strip API (data/spectra-device-preview-plan/report.md):

  GET  /api/device-preview/favorites — stored + effective (default-filled)
                                       favourite virtual ids
  PUT  /api/device-preview/favorites — replace the stored list
  GET  /api/device-preview/status    — relay state (paused/connected/fps)
  POST /api/device-preview/pause     — genuinely drops the upstream LedFX
                                       connection (see services/
                                       device_preview.py's module docstring
                                       for why "genuinely")
  POST /api/device-preview/resume    — reopens it
  WS   /api/device-preview/ws        — live frames + status pushes; a fresh
                                       connection gets one status message
                                       immediately so a newly-opened tab
                                       doesn't wait for the next mutation
                                       to know paused/connected state. Also
                                       IS the hidden-tab auto-pause signal
                                       (OQ-7, services/device_preview.py's
                                       docstring): connecting/disconnecting
                                       this socket calls relay.
                                       viewers_changed(), so the upstream
                                       LedFX connection genuinely drops the
                                       instant the last viewer disconnects
                                       and reopens the instant one returns
                                       — no separate pause/resume call
                                       needed, and the sticky pause() above
                                       is left untouched either way.
"""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from spectra.services import device_preview

router = APIRouter(prefix="/api", tags=["spectra-device-preview"])


class FavoritesBody(BaseModel):
    favorite_virtual_ids: list[str]


@router.get("/device-preview/favorites")
async def get_favorites():
    return device_preview.get_favorites()


@router.put("/device-preview/favorites")
async def put_favorites(body: FavoritesBody):
    result = device_preview.set_favorite_ids(body.favorite_virtual_ids)
    await device_preview.broadcast_status()
    return result


@router.get("/device-preview/status")
async def get_status():
    return device_preview.relay.status()


@router.post("/device-preview/pause")
async def post_pause():
    result = device_preview.pause()
    await device_preview.broadcast_status()
    return result


@router.post("/device-preview/resume")
async def post_resume():
    result = device_preview.resume()
    await device_preview.broadcast_status()
    return result


@router.websocket("/device-preview/ws")
async def device_preview_ws(ws: WebSocket):
    await device_preview.preview_ws_manager.connect(ws)
    device_preview.frame_hub.connect(ws)
    device_preview.relay.viewers_changed()
    try:
        await ws.send_json({"type": "device_preview_status", **device_preview.relay.status()})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        device_preview.preview_ws_manager.disconnect(ws)
        await device_preview.frame_hub.disconnect(ws)
        device_preview.relay.viewers_changed()
