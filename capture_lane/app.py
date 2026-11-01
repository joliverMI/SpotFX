"""
The capture lane's whole server: three routes on loopback, each needing the
lane's key (capture_lane.key), so only SpotFX on this machine drives it.

  GET  /status   what the lane is doing, the song, its progress, and the
                 outcomes of its last songs (what SpotFX reads)
  POST /learn    {uri, title, artist, duration_ms, genres?, job_id?} — start
                 one song; 409 while another is running; 423 while the
                 second account is switched off (fx/second_account.py)
  POST /cancel   {job_id?} — stop the running one (the lane lets go on the
                 way out: the system's own song is paused, nothing else)

With `recover_on_start` (the real process, capture_lane/__main__.py), a play
the system started before the lane last stopped is let go of first
(Lane.recover).

No docs, no OpenAPI, nothing else answers.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from capture_lane import key as lane_key
from capture_lane.lane import SENTENCES, Busy, Job, Lane, Locked

ROUTES = frozenset({("GET", "/status"), ("POST", "/learn"), ("POST", "/cancel")})
BODY_MAX = 4096


def create_app(lane: Optional[Lane] = None, key: Optional[str] = None,
               recover_on_start: bool = False) -> FastAPI:
    lane = lane or Lane()
    secret = key if key is not None else lane_key.load_or_create()

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(lane.recover()) if recover_on_start else None
        try:
            yield
        finally:
            if task is not None and not task.done():
                task.cancel()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.lane = lane

    def refused(req: Request) -> Optional[JSONResponse]:
        if not lane_key.matches(req.headers.get(lane_key.HEADER), secret):
            return JSONResponse({"detail": "not allowed"}, status_code=401)
        return None

    async def body(req: Request) -> dict:
        raw = await req.body()
        if len(raw) > BODY_MAX:
            raise ValueError("body too large")
        import json
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise ValueError("body must be an object")
        return data

    @app.get("/status")
    async def status(req: Request):
        if (r := refused(req)) is not None:
            return r
        return lane.status()

    @app.post("/learn")
    async def learn(req: Request):
        if (r := refused(req)) is not None:
            return r
        try:
            data = await body(req)
            uri = str(data["uri"])
            if not uri.startswith("spotify:track:"):
                raise ValueError("uri must be a spotify:track: uri")
            duration_ms = int(data["duration_ms"])
            if duration_ms <= 0:
                raise ValueError("duration_ms must be positive")
            job = Job(uri=uri, title=str(data.get("title") or ""), artist=str(data.get("artist") or ""),
                      duration_ms=duration_ms,
                      genres=[str(g) for g in (data.get("genres") or [])][:20])
            if data.get("job_id"):
                job.job_id = str(data["job_id"])[:40]
        except (KeyError, TypeError, ValueError) as exc:
            return JSONResponse({"detail": f"bad request: {exc}"}, status_code=400)
        try:
            lane.learn(job)
        except Busy as exc:
            return JSONResponse({"detail": "busy", "uri": str(exc)}, status_code=409)
        except Locked:
            return JSONResponse({"detail": "locked", "reason": "account_locked",
                                 "sentence": SENTENCES["account_locked"]}, status_code=423)
        return JSONResponse({"job_id": job.job_id, "state": lane.state}, status_code=202)

    @app.post("/cancel")
    async def cancel(req: Request):
        if (r := refused(req)) is not None:
            return r
        try:
            data = await body(req)
        except ValueError as exc:
            return JSONResponse({"detail": f"bad request: {exc}"}, status_code=400)
        return {"cancelled": lane.cancel(data.get("job_id"))}

    return app
