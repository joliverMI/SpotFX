"""Light ownership + the SPECTRA LIVENESS ENDPOINT (S3).

  GET  /api/ownership          — the durable ownership record, inspectable:
      owner, in-flight handover (step/from/to/age), armed latch, whether the
      live stack is up, history trail.
  POST /api/ownership/handover — the owner's switch: {"to": "spectra" |
      "spot-effects"}. REFUSED (403) unless the SPECTRA_HANDOVER_ARMED
      latch is set on the process; 409 when the record refuses (already
      owner / already in flight); 412 when the to-side's go-day preparation
      is missing (the readiness gate — refused BEFORE quiesce, room
      untouched, the error names the preparation and its command); on a
      step failure returns 502 with the landing — always a settled single
      owner, never split. FROM `released`, "to": "spectra" runs this SAME
      staged, readiness-gated handover — the way back from the panic
      release (spectra/services/handover.py's from_world==RELEASED
      handling); still requires SPECTRA_HANDOVER_ARMED, same as any other
      handover.
  POST /api/ownership/release  — THE PANIC HANDLE (spectra/services/
      release.py): one press, no body, no confirmation — the press is the
      consent. NOT gated by SPECTRA_HANDOVER_ARMED (going to no-writer is
      always safe to allow). Idempotent — pressing it again while already
      released just repeats the note in history. 409 only if a handover is
      genuinely mid-flight (settle it, or wait for the stale-handover
      recovery, then press again). The record always lands `released`;
      cleanup runs against BOTH worlds regardless of which the record said
      owned, and a post-release verification read-back decides the result:
      200 result="released" when confirmed, 207
      result="released-unverified" with `problems` when a device could not
      be confirmed dark (the caller should treat this as still-lit until
      proven otherwise, not as success).
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
        owner=spectra      healthy iff the live stack is up, every ACTIVE
                           virtual flushed within stale_after_s, AND every
                           config-declared virtual actually came up
                           (activation_gaps == {} — the crystal lazy-
                           activation class, report gate e3, 2026-08-14:
                           a virtual absent from "every ACTIVE virtual"
                           above is invisible to that check alone, which
                           is exactly how a partial activation used to
                           report healthy). activation_gaps is additive to
                           the v1 contract — {} on every prior-shape
                           response, non-empty only on this new failure
                           class; existing consumers reading known keys are
                           unaffected. write_seam (added 2026-08-14,
                           spectra-room-fault-diagnosis) is likewise
                           additive and informational-only, never affecting
                           `healthy`: fx_seam.stats()'s count of requested
                           effect-type switches the write seam had to land
                           as an instant PUT to avoid fx/facade.py's
                           stale-tween-PUT drop (frame freshness alone
                           can't tell a virtual streaming the WRONG effect
                           apart from a healthy one). param_watchdog
                           (added 2026-08-21) is additive and informational
                           the same way: the param orphan watchdog's
                           restore count/suspicions/give-ups
                           (spectra/services/param_watchdog.py), so a
                           recurring orphan is visible on the fleet's own
                           check rather than merely handled.
        owner=spot-effects healthy iff SPECTRA is correctly DARK (a live
                           stack without ownership is the split-brain
                           tripwire → 503).
        owner=released     healthy-DARK iff the SPECTRA live stack is down
                           (the panic release's job) — a deliberately
                           released room reports state "released", healthy
                           200, same as any other correctly-dark state; a
                           live stack while released is the same split-brain
                           tripwire as above → 503.
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
from spectra.services import fx_seam
from spectra.services import handover as handover_svc
from spectra.services import param_watchdog
from spectra.services import release as release_svc
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
    except handover_svc.HandoverRefused as exc:
        return JSONResponse(
            {"result": "refused-preparation-missing", "error": str(exc),
             "record": _record_json()}, status_code=412)
    except handover_svc.HandoverFailed as exc:
        return JSONResponse(
            {"result": "failed-landed-single-owner", "error": str(exc),
             "record": _record_json()}, status_code=502)
    return {"result": "committed", "owner": record.owner,
            "record": _record_json()}


@router.post("/ownership/release")
async def post_release():
    """THE PANIC HANDLE. No body, no confirmation, not armed-gated — the
    press is the consent. 409 only if a handover is genuinely mid-flight.
    The record always lands `released`; when post-release verification
    can't confirm reality matches (a device still lit), this reports
    result="released-unverified" with the specific `problems` instead of a
    clean "released", at HTTP 207 — loud, not silent, per the merge-scout
    two-writers report (2026-08-13)."""
    try:
        result = await release_svc.release_room("owner panic release (API)")
    except light_ownership.OwnershipError as exc:
        raise HTTPException(409, str(exc))
    if not result.verified:
        return JSONResponse(
            {"result": "released-unverified", "owner": result.record.owner,
             "problems": result.problems, "record": _record_json()},
            status_code=207)
    return {"result": "released", "owner": result.record.owner,
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

    activation_gaps = live.activation_gaps() if live.active else {}
    if record.owner == light_ownership.SPECTRA:
        state = "live" if live.active else "dark"
        # The crystal lazy-activation class (report gate e3, folded in as
        # first-class alongside the reconciler, 2026-08-13): a config-
        # declared virtual that never came up is a loud failure here too,
        # continuously — not just at the one-shot handover verification
        # that first reported success on it.
        healthy = live.active and not activation_gaps and all(
            v["fresh"] for v in virtuals.values() if v["active"])
    elif record.owner == light_ownership.HANDING_OVER:
        state = "switching"
        healthy = False
    elif record.owner == light_ownership.RELEASED:
        state = "split-brain" if live.active else "released"
        healthy = not live.active
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
            "activation_gaps": activation_gaps,
            # Additive (spectra-room-fault-diagnosis, 2026-08-14): frame
            # freshness alone can't distinguish "streaming the right effect"
            # from "streaming a stale one" — see fx_seam.stats()'s own
            # docstring. Informational only; never affects `healthy`.
            "write_seam": fx_seam.stats(),
            # Additive (2026-08-21, the param orphan watchdog —
            # spectra/services/param_watchdog.py): how many effect params
            # it has found orphaned away from baseline and restored, what
            # it currently suspects, what it gave up on. A RECURRING
            # orphan is something to SEE here, not something a restart
            # fixes — informational only, never affects `healthy`.
            "param_watchdog": param_watchdog.liveness_summary(),
        },
        status_code=200 if healthy else 503,
    )
