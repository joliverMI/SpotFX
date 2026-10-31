"""
SpotFX — Absorb Music API (services/absorb.py is the runner).

  GET  /api/absorb/config        his settings
  PUT  /api/absorb/config        a PARTIAL update — only the keys sent change;
                                 an unknown key or an out-of-range value is a
                                 422 naming it. `?dry_run=true` validates
                                 exactly the same way and writes nothing (it
                                 answers the config the edit WOULD leave) —
                                 Sonic asks "go ahead?" only about a change
                                 this validator accepts
  GET  /api/absorb/run           the current (or last) run, plus earlier ones
  POST /api/absorb/start         open a window now (his press)
  POST /api/absorb/stop          end the window
  POST /api/absorb/skip-song     move on from the song playing now
  POST /api/absorb/retry         un-park one song ({"uri": ...})
  GET  /api/absorb/parked        every song parked across runs (the ledger),
                                 newest first — what Retry acts on; reads only
  GET  /api/absorb/playlists     his Spotify playlists (his own and the ones
                                 he follows), with whether Absorb could edit
                                 each — for linking one by NAME (Sonic) —
                                 reads only
  GET  /api/absorb/preview       already captured / to capture / to re-capture
                                 for the linked playlist — reads only
  GET  /api/absorb/lane          the backlog on the hidden player (phase 4,
                                 services/absorb_lane.py): what it is doing
                                 or why it rests — reads only; switched by
                                 PUT /config's use_capture_lane
  GET  /api/absorb/schedule      the schedule: switched on or not, his windows
                                 in house time, the one open now, the next
                                 one, and what the schedule did with each
                                 recent occurrence (opened / waiting /
                                 refused, with its reason) — reads only.
                                 Windows are edited through PUT /config.

A refusal to open is a RECORDED outcome answered with 200 and its reason
(`{"status": "refused", "reason": ..., "detail": ...}`), never a silence and
never an error: "did it run, and why not?" must be a read.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError

from services import absorb, absorb_schedule, absorb_store

router = APIRouter(prefix="/api/absorb", tags=["absorb"])


@router.get("/config")
async def get_config() -> dict:
    return absorb_store.load_config().model_dump(mode="json")


@router.put("/config")
async def put_config(request: Request, dry_run: bool = False) -> dict:
    try:
        patch = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="expected a JSON object")
    try:
        cfg = absorb.apply_config_patch(patch, save=not dry_run)
        if not dry_run and isinstance(patch, dict) and "use_capture_lane" in patch:
            from services import absorb_lane
            absorb_lane.backlog.kick()        # switched: act (or stop) now, not in 30 s
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=[
            {"field": ".".join(str(p) for p in e["loc"]), "error": e["msg"]}
            for e in exc.errors()])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return cfg.model_dump(mode="json")


@router.get("/run")
async def get_run(history: int = 5) -> dict:
    """The live (or last) run in full, and earlier runs as summaries."""
    current = absorb.runner.run or absorb_store.latest_run()
    earlier = [r for r in absorb_store.earlier_runs()
               if current is None or r.get("id") != current.id]
    return {
        "brief": absorb.brief(current),
        "run": current.model_dump(mode="json") if current else None,
        "earlier": earlier[:max(0, min(history, 20))],
    }


class StartBody(BaseModel):
    started_by: str = "press"


@router.post("/start")
async def start(body: Optional[StartBody] = None) -> dict:
    return await absorb.runner.start(started_by=(body.started_by if body else "press"))


@router.post("/stop")
async def stop() -> dict:
    return await absorb.runner.stop()


@router.post("/skip-song")
async def skip_song() -> dict:
    return await absorb.runner.skip_song()


class RetryBody(BaseModel):
    uri: str


@router.post("/retry")
async def retry(body: RetryBody) -> dict:
    return {"uri": body.uri, "unparked": await absorb.unpark(body.uri)}


@router.get("/parked")
async def parked() -> dict:
    return {"parked": absorb.parked_songs()}


@router.get("/playlists")
async def playlists() -> dict:
    try:
        return {"playlists": await absorb.playlists()}
    except Exception as exc:
        return {"playlists": None, "detail": absorb.sentence("spotify_error", str(exc)[:120])}


@router.get("/preview")
async def preview() -> dict:
    try:
        return await absorb.preview()
    except Exception as exc:
        return {"linked": True, "resolved": False,
                "detail": absorb.sentence("spotify_error", str(exc)[:120])}


@router.get("/lane")
async def get_lane() -> dict:
    """Absorb's backlog on the hidden player (services/absorb_lane.py): on
    or off, what it is doing or why it rests, the song it is learning, and
    what it learned or failed lately — reads only."""
    from services import absorb_lane
    return {"enabled": bool(absorb_store.load_config().use_capture_lane),
            **absorb_lane.backlog.status()}


@router.get("/schedule")
async def schedule(outcomes: int = 20) -> dict:
    return absorb_schedule.status(limit=max(0, min(outcomes, 60)))
