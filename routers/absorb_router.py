"""
SpotFX — Absorb Music API (services/absorb.py is the runner).

  GET  /api/absorb/config        his settings
  PUT  /api/absorb/config        a PARTIAL update — only the keys sent change;
                                 an unknown key or an out-of-range value is a
                                 422 naming it
  GET  /api/absorb/run           the current (or last) run, plus earlier ones
  POST /api/absorb/start         open a window now (his press)
  POST /api/absorb/stop          end the window
  POST /api/absorb/skip-song     move on from the song playing now
  POST /api/absorb/retry         un-park one song ({"uri": ...})
  GET  /api/absorb/preview       already captured / to capture / to re-capture
                                 for the linked playlist — reads only

A refusal to open is a RECORDED outcome answered with 200 and its reason
(`{"status": "refused", "reason": ..., "detail": ...}`), never a silence and
never an error: "did it run, and why not?" must be a read.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError

from services import absorb, absorb_store

router = APIRouter(prefix="/api/absorb", tags=["absorb"])


@router.get("/config")
async def get_config() -> dict:
    return absorb_store.load_config().model_dump(mode="json")


@router.put("/config")
async def put_config(request: Request) -> dict:
    try:
        patch = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="expected a JSON object")
    try:
        cfg = absorb.apply_config_patch(patch)
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


@router.get("/preview")
async def preview() -> dict:
    try:
        return await absorb.preview()
    except Exception as exc:
        return {"linked": True, "resolved": False,
                "detail": absorb.sentence("spotify_error", str(exc)[:120])}
