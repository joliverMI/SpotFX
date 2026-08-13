"""Light ownership + the SPECTRA LIVENESS ENDPOINT (S3).

  GET  /api/ownership          — the durable ownership record, inspectable:
      owner, in-flight handover (step/from/to/age), armed latch, whether the
      live stack is up, history trail.
  POST /api/ownership/handover — the owner's switch: {"to": "spectra" |
      "spot-effects"}. REFUSED (403) unless the SPECTRA_HANDOVER_ARMED
      latch is set on the process; 409 when the record refuses (already
      owner / already in flight); on a step failure returns 502 with the
      landing — always a settled single owner, never split.
  POST /api/ownership/recover  — land a crash-orphaned handover (age-gated;
      also runs automatically at engine start).

  GET  /api/liveness — THE BINDING CONTRACT (data/spectra-design-decisions
      .md): a stable address whose handler traverses the real render/write
      path, reporting PER-VIRTUAL FRAME-FLUSH FRESHNESS (stamps fed by the
      render loop's own VirtualUpdateEvent, fired after assemble+flush).
      Stable address, shared process today and standalone after the split:
          /spectra/api/liveness
      (spectra/app.py mounts this router under /spectra in main.py; the
      standalone entry serves the identical URL space, so the fleet's
      external checker survives the switchover with at most a host:port
      change.) HTTP 200 when healthy, 503 when not:
        owner=spectra      healthy iff the live stack is up and every ACTIVE
                           virtual flushed within stale_after_s.
        owner=spot-effects healthy iff SPECTRA is correctly DARK (a live
                           stack without ownership is the split-brain
                           tripwire → 503).
        handing-over       503, state "switching" — truthful during the
                           brief window the room changes hands.
      Never delete or repoint without the Admiral's word.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from fx import light_ownership
from spectra import config
from spectra.services import handover as handover_svc
from spectra.services.live_host import STALE_AFTER_S, live

router = APIRouter(prefix="/api", tags=["spectra-ownership"])

LIVENESS_CONTRACT = "spectra-liveness-v1"
LIVENESS_ADDRESS = "/spectra/api/liveness"


class HandoverRequest(BaseModel):
    to: str


def _record_json() -> dict:
    record = light_ownership.load()
    out = {
        "owner": record.owner,
        "handover": record.handover.to_json() if record.handover else None,
        "updated_at": record.updated_at,
        "armed": config.handover_armed(),
        "live_stack_active": live.active,
        "history": record.history,
    }
    if record.handover:
        out["handover"]["age_s"] = round(
            time.time() - record.handover.started_at, 1)
    return out


@router.get("/ownership")
async def get_ownership():
    return _record_json()


@router.post("/ownership/handover")
async def post_handover(body: HandoverRequest):
    if body.to not in light_ownership.WORLDS:
        raise HTTPException(422, f"to must be one of {light_ownership.WORLDS}")
    if not config.handover_armed():
        raise HTTPException(
            403, "handover not armed — the room changes hands only on the "
            "owner's word (export SPECTRA_HANDOVER_ARMED=1; see "
            "docs/SPECTRA_HANDOVER.md)")
    try:
        record = await handover_svc.run_handover(
            body.to, handover_svc.production_sides())
    except light_ownership.OwnershipError as exc:
        raise HTTPException(409, str(exc))
    except handover_svc.HandoverFailed as exc:
        return JSONResponse(
            {"result": "failed-landed-single-owner", "error": str(exc),
             "record": _record_json()}, status_code=502)
    return {"result": "committed", "owner": record.owner,
            "record": _record_json()}


@router.post("/ownership/recover")
async def post_recover():
    landed = light_ownership.recover_stale_handover()
    return {"recovered": landed, "record": _record_json()}


@router.get("/liveness")
async def get_liveness():
    record = light_ownership.load()
    virtuals = live.liveness()
    devices = {}
    if live.host is not None:
        devices = {d.id: {"type": d.type, "online": bool(d.is_online)}
                   for d in live.host.devices.values()}

    if record.owner == light_ownership.SPECTRA:
        state = "live" if live.active else "dark"
        healthy = live.active and all(
            v["fresh"] for v in virtuals.values() if v["active"])
    elif record.owner == light_ownership.HANDING_OVER:
        state = "switching"
        healthy = False
    else:
        state = "split-brain" if live.active else "dark"
        healthy = not live.active

    return JSONResponse(
        {
            "contract": LIVENESS_CONTRACT,
            "address": LIVENESS_ADDRESS,
            "owner": record.owner,
            "state": state,
            "healthy": healthy,
            "stale_after_s": STALE_AFTER_S,
            "virtuals": virtuals,
            "devices": devices,
        },
        status_code=200 if healthy else 503,
    )
