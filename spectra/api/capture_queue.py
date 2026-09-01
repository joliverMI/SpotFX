"""THE UNATTENDED CAPTURE QUEUE's wire.

  POST /api/rooms/capture-queue        start a declared list of runs
  GET  /api/rooms/capture-queue        the live queue, the session it is
                                       waiting on, and recent queues
  POST /api/rooms/capture-queue/stop   stop after the run in flight

WHY IT STARTS AND RETURNS RATHER THAN RUNNING ON THE SOCKET: an unattended
caller is usually one line — an ssh command, a systemd unit, the capture
client itself once its camera is locked — and none of those should hold a
connection open for forty minutes of dark room. The POST validates the
declared list (refusing a typo AT DECLARATION, not at 3 am on the item
nobody reads), starts the run and hands back its id; `GET` is how anything
follows it, and `spectra/services/capture_queue.py` writes the record to
disk after every item so a killed process has still explained itself.

REGISTERED BEFORE `rooms.router` in spectra/app.py so `/rooms/capture-queue`
can never be eaten by a `/rooms/{room_id}` pattern.

Every refusal on this path is `mapping_refusals`' own sentence. This module
composes none of its own.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from spectra.services import capture_queue, capture_runs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["spectra-capture-queue"])


class QueueBody(BaseModel):
    """A declared queue. `items` is a list of the SAME arguments the map and
    commissioning routes take, plus `label`, `retries` and
    `session_wait_s` — see `capture_queue.QueueItem`."""
    label: str = ""
    items: list[dict[str, Any]] = []


@router.post("/rooms/capture-queue")
async def start_queue(body: QueueBody):
    if capture_queue.running():
        return JSONResponse(status_code=409, content={
            "detail": "a capture queue is already running",
            "queue": capture_queue.status()["current"]})
    try:
        items = capture_queue.parse_items(body.items)
    except ValueError as exc:
        # A DECLARATION error, not a run failure: nothing was started and
        # nothing was written, and the sentence names the item.
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    run = await capture_queue.start(items, label=body.label)
    return {"started": True, "queue": run.as_dict(),
            "session": capture_runs.session_view()}


@router.get("/rooms/capture-queue")
async def queue_status(limit: int = 5):
    st = capture_queue.status()
    st["recent"] = st["recent"][:max(1, min(20, limit))]
    return st


@router.post("/rooms/capture-queue/stop")
async def stop_queue():
    stopped = capture_queue.stop()
    return {"stopping": stopped, "queue": capture_queue.status()["current"]}
