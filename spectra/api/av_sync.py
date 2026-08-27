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
  GET  /api/av-sync/apply-proposal what his Apply press would write:
                                   the live estimate (or the newest stored
                                   run) translated into the room's
                                   av_sync_lead_ms, with the direction
                                   spelled out. READ-ONLY — the write
                                   itself is his press through the
                                   established PUT /api/room-controls,
                                   never a bespoke writer here.

The proposal endpoint refuses exactly where the instrument refuses: a
weak/ambiguous/unstable estimate carries its own reason forward with
applicable=False and no proposed value, so the page has nothing to offer
rather than a guess. spectra/services/av_sync_lead.py holds the sign law.

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


@router.get("/av-sync/apply-proposal")
async def get_apply_proposal():
    """What his Apply press would write, computed SERVER-SIDE so the sign
    translation has exactly one implementation (the page renders this, it
    never re-derives it — the flare-preview trigger_mark_s precedent).

    The estimate comes from the LIVE session when one is connected, else
    the newest stored run, so the dialogue can never be opened against a
    number the instrument has since walked back. Read-only."""
    from spectra.services import av_sync_lead

    measurements = sessions.load_measurements()
    recent = av_sync_lead.recent_runs(measurements)
    estimate: Optional[dict] = None
    source = "none"
    sess = sessions.current
    if sess is not None:
        estimate = sess.estimate().as_dict()
        source = "live"
    elif measurements:
        estimate = measurements[-1]
        source = "stored"
    prop = av_sync_lead.proposal(estimate, av_sync_lead.current_lead_ms(),
                                 recent=recent)
    body = prop.as_dict()
    body["source"] = source
    body["spread_ms"] = av_sync_lead.spread_ms(recent)
    body["two_runs_note"] = av_sync_lead.TWO_RUNS_NOTE
    body["lead_min_ms"] = av_sync_lead.LEAD_MIN_MS
    body["lead_max_ms"] = av_sync_lead.LEAD_MAX_MS
    return body


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
