"""THE NIGHT-RUN WIRE — the two pushes from Home Assistant, and the read the
morning backstop is built against.

  POST /api/night-run/start      Bearer   {"event": "sleep-window-start",
                                           "ts": ..., "source": ...}
  POST /api/night-run/abort      Bearer   {"event": "sleep-ended"
                                           | "light-touched"
                                           | "morning-routine", ...}
  GET  /api/night-run/would-start open    the preflight: would a start,
                                          arriving now, run? (a pure read)
  GET  /api/night-run/morning    open     what ran, and what changed
  GET  /api/night-run/fixtures   open     the two lists (below)
  GET  /api/night-run/queue      open     the declaration
  PUT  /api/night-run/queue      open     declare it

WHY THE TWO PUSHES CARRY A SECRET AND THE READS DO NOT. Everything else in
this app is unauthenticated: SPECTRA answers on his own LAN and its whole
authoring surface is reachable by anyone who can reach the port, which is
his standing posture and not this seam's to change. The two pushes are
different in kind — they are the only routes in SPECTRA an EXTERNAL system
initiates, and one of them starts a run that darkens his room for the night.
So they carry the Bearer secret both captains agreed, and the reads stay
open because River asked for a read with no auth and a read cannot start
anything.

THE SECRET LIVES IN THE ENVIRONMENT ONLY (`SPECTRA_NIGHT_RUN_TOKEN`), is
read AT REQUEST TIME (`config.night_run_token()`, so rotating it is a
restart and never a stale module global), is compared with
`hmac.compare_digest` so a wrong guess cannot be narrowed down by timing,
and is NEVER written to this repository, to a log line, or to a run record.

UNSET FAILS CLOSED. With no token provisioned every push is 401: a deploy
that forgot the environment variable refuses starts rather than accepting
anonymous ones.

ONE STOP ENDPOINT, THREE FACTS. `sleep-ended` and `light-touched` are the
same act — he stirred, and a touched house is his house. `morning-routine`
(his ~05:50 HA routine, which ends any overnight run whether or not this
side had a dawn line) does exactly the same three things to the room and is
recorded as `ended_by_morning`: an ORDINARY ending, not an incident. The
response says which (`state`, `ended_by_morning`).

THE ABORT RESPONSE CARRIES THE OUTCOME, so the house can restore its own
envelope off this reply rather than waiting for its next status poll —
`state` and `ended_by_morning` are the same words `GET /api/engine/status`
will report a moment later.

A DECLINED START IS HTTP 200. It is a normal recorded outcome, not an
error — the run declined by name, the night is on the record, and Home
Assistant's fire-and-forget push has nothing to retry. A 4xx here would
teach the other side to treat a working boundary as a fault.
"""
from __future__ import annotations

import hmac
import logging
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from spectra import config as scfg
from spectra.services import night_run

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/night-run", tags=["spectra-night-run"])


def _authorise(authorization: Optional[str]) -> None:
    """Bearer, constant-time, read fresh. 401 for absent AND mismatched —
    the same answer either way, on purpose: telling a caller which of the
    two it was is a free hint."""
    expected = scfg.night_run_token()
    presented = ""
    if authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:].strip()
    if not expected or not presented or not hmac.compare_digest(presented,
                                                                expected):
        # Never log the presented value.
        logger.warning("night run: rejected an unauthenticated push")
        raise HTTPException(401, "night-run pushes need the shared bearer "
                                 "token")


class EventBody(BaseModel):
    """Home Assistant's own payload, taken verbatim and recorded verbatim.
    Every field is optional: a fire-and-forget push must never fail
    validation over a field this side did not need."""
    event: str = ""
    ts: str = ""
    source: str = ""

    model_config = {"extra": "allow"}


class QueueBody(BaseModel):
    """The declared night queue, in one of TWO shapes and never both.

    `items` is the original: the SAME items the capture-queue route takes
    (`capture_queue.QueueItem`), validated by the same function.

    `calibration_id` names a CALIBRATION for the night to run instead — its
    own declared queue, run through the same seam, landing in its own
    lineage (`spectra/services/night_calibration.py`). With `amend` it runs
    a NAMED SUBSET of that declaration: the same amend-in-part the `/amend`
    route takes, resolved by the same function, gated by the same honesty
    gate at 2am as at 2pm.

    Both are validated the whole way down AT DECLARATION — the calibration
    has to exist, an amendment's named items have to be ones it declares —
    so a mistake is refused while he is awake."""
    label: str = ""
    items: list[dict[str, Any]] = []
    calibration_id: str = ""
    #: {"items": [...], "overrides": {...}, "whole_carrier": bool}
    amend: Optional[dict[str, Any]] = None
    #: Run past a MEASURED CAMERA MOVE, as a press may. It NEVER runs past
    #: an amendment's mixing gate — `spectra/services/amendment.py`.
    force: bool = False


@router.post("/start")
async def start(body: EventBody,
                authorization: str | None = Header(default=None)):
    _authorise(authorization)
    run = await night_run.start(body.model_dump())
    return {"run_id": run.id, "state": run.state, "detail": run.detail,
            "refusal": run.refusal, "started": run.started,
            "fixtures": run.fixtures, "power": run.power}


@router.post("/abort")
async def abort(body: EventBody,
                authorization: str | None = Header(default=None)):
    _authorise(authorization)
    return await night_run.abort(body.model_dump())


@router.get("/would-start")
async def would_start():
    """THE PREFLIGHT — would a start event arriving right now run?

    His house PREPARES before it starts a night: River's side fires the
    "Dark Music" envelope, then pushes start. On 2026-09-01 that order lit
    his house up while he slept — the envelope fired, the start declined by
    name (no declared queue, the designed outcome), and a restore then ran
    against a night that never began. The agreed fix (the seam's addenda
    7-9) reverses it: ASK FIRST, PREPARE ONLY ON YES. On a no, nothing was
    ever touched, so his house is byte-identical by not-touching.

    OPEN, like every other read here, and River asked for it that way: a
    read cannot start anything. It writes nothing, holds nothing, drives no
    light and mutates no state — call it a hundred times and every store is
    byte-identical.

    THE ANSWER IS THE START'S OWN. `night_run.evaluate_start` is the one
    gate chain; `night_run.start` calls it too, so `reason` here is the
    literal sentence that start would have recorded, not a preflight
    rewording of it. A second implementation would be worse than no
    preflight — a confident wrong answer at 1am with nobody awake.

    A YES CAN GO STALE, and the design says so rather than pretending
    otherwise: closing that window would mean reserving something, which is
    preparation-before-confirmation in disguise. The house's safety does
    not rest on the yes — it snapshots before it prepares and restores on
    any answer from start that is not `running`."""
    return await night_run.would_start()


@router.get("/morning")
async def morning():
    """WHAT RAN LAST NIGHT AND WHAT CHANGED — one read, in his nouns.

    His own bar for this surface: he must be able to answer which
    calibration ran, what it measured, what changed against the previous
    one, and what waits on him, WITHOUT ASKING ANYONE and without reading a
    log. `spectra/services/morning_read.py` is the binding statement.

    Open, like every other read here: a read cannot start anything."""
    from spectra.services import morning_read
    return morning_read.build()


@router.get("/fixtures")
async def fixtures():
    """The morning backstop's whole scope: what the night TOOK, and what his
    Dark mode leaves standing regardless. Computed live — the shield list
    tracks his own pending shield decision with nothing to remember."""
    return await night_run.fixtures_export()


@router.get("/queue")
async def get_queue():
    declaration = night_run.load_declaration()
    return {"declared": declaration is not None,
            "queue": declaration,
            "night": night_run.status_brief()}


@router.put("/queue")
async def put_queue(body: QueueBody):
    try:
        stored = night_run.save_declaration(
            body.label, body.items, calibration_id=body.calibration_id,
            amend=body.amend, force=body.force)
    except ValueError as exc:
        # A DECLARATION error, refused now — while he is awake and can fix
        # it — rather than at 1am on the item nobody reads. `capture_queue`'s
        # own sentence, which names the offending item.
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return {"declared": True, "queue": stored}


@router.delete("/queue")
async def delete_queue():
    return {"declared": False, "cleared": night_run.clear_declaration()}
