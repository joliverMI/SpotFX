"""AV-sync API — the phone audio/visual-offset instrument's wire
(spectra/services/av_sync_session.py has the mechanism + privacy
statement; spectra/web/src/avsync/ is the phone page).

  WS   /api/av-sync/ws             the phone's session. Phone → server:
                                   hello / pong / audio / video / frame /
                                   measure {mode, duration_s} / stop.
                                   Server → phone: welcome / hello_ack /
                                   ping / estimate / measure_started /
                                   measure_done / config / error.
  GET  /api/av-sync/status         live session status (numbers only) +
                                   the privacy summary
  GET  /api/av-sync/measurements   the persisted records (the ONLY thing
                                   this feature ever writes to disk)
  POST /api/av-sync/frame-tap      {enabled, fps, width} — the vision-
                                   stage seam's switch (default off);
                                   pushed to the phone as a `config` msg
  GET  /api/av-sync/frame/latest   newest tapped frame as image/jpeg
                                   (404 when the tap is off / empty)
  GET  /api/av-sync/frame/meta     its timestamps/size, no pixels

Nothing here drives lights on connect: a pattern run starts ONLY on an
explicit `measure` message from the phone (his press), and the driver's
own revert contract lands the room back (av_sync_pattern.py).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from spectra.services import av_sync_session as sessions

router = APIRouter(prefix="/api", tags=["spectra-av-sync"])


class FrameTapBody(BaseModel):
    enabled: bool
    fps: float = 1.0
    width: int = 320


@router.get("/av-sync/status")
async def get_status():
    return sessions.status()


@router.get("/av-sync/measurements")
async def get_measurements(limit: Optional[int] = None):
    items = sessions.load_measurements()
    if limit:
        items = items[-int(limit):]
    return {"measurements": items, "privacy": sessions.PRIVACY_SUMMARY}


@router.post("/av-sync/frame-tap")
async def post_frame_tap(body: FrameTapBody):
    sess = sessions.current
    if sess is None or sess.closed:
        return JSONResponse(status_code=409, content={"detail": "no live av-sync session"})
    cfg = sess.frames.configure(enabled=body.enabled, fps=body.fps, width=body.width)
    await sess.send({"type": "config", "frame_tap": cfg})
    return {"frame_tap": cfg}


@router.get("/av-sync/frame/meta")
async def get_frame_meta():
    sess = sessions.current
    if sess is None or sess.closed:
        return JSONResponse(status_code=404, content={"detail": "no live av-sync session"})
    return sess.frames.status()


@router.get("/av-sync/frame/latest")
async def get_frame_latest():
    sess = sessions.current
    frame = sess.frames.latest() if (sess is not None and not sess.closed) else None
    if frame is None:
        return JSONResponse(status_code=404, content={"detail": "no tapped frame"})
    return Response(content=frame.data, media_type=frame.mime,
                    headers={"X-Captured-At-Phone-Ms": str(frame.captured_at_phone_ms),
                             "X-Captured-At-Server-S": str(frame.captured_at_server_s),
                             "Cache-Control": "no-store"})


@router.websocket("/av-sync/ws")
async def av_sync_ws(ws: WebSocket):
    await ws.accept()
    sess = await sessions.open_session(ws.send_json)
    try:
        while True:
            msg = await ws.receive_json()
            if isinstance(msg, dict):
                await sess.handle(msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        # a malformed frame must not leave the room mid-pattern: close
        # reverts the pattern and drops every ring either way
        pass
    finally:
        await sessions.close_session(sess)
