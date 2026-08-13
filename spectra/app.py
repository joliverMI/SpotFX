"""The SPECTRA app — its own FastAPI application, mounted by spot-effects'
main.py at /spectra for the shared-process S1/S2 stages and ready to run
standalone the day S3 splits the processes (python -m spectra).

S2 runtime: the evolution engine (services/engine — bridge + drift
conductor + response engine, DARK against real lights). Starlette never
runs a mounted sub-app's lifespan, so the HOST owns start/stop: main.py's
lifespan calls spectra.services.engine.start()/stop() in the shared
process, and _standalone() wires the identical pair — the S3 split changes
which host calls them, nothing else.

NOTE the /api/status handler is a PLACEHOLDER status surface, deliberately
NOT the SPECTRA liveness endpoint contract — that named contract (per-
virtual frame-flush freshness through the real render path) lands with S3
ownership and must not be faked by an HTTP 200 that proves nothing.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from spectra import config
from spectra.api import engine as engine_api
from spectra.api import journey, registry, scenes, sequencer


class SPAStaticFiles(StaticFiles):
    """Serve the SPECTRA SPA with index.html fallback for client routes."""

    async def get_response(self, path: str, scope):
        from starlette.exceptions import HTTPException as StarletteHTTPException
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def create_app() -> FastAPI:
    app = FastAPI(title="SPECTRA", version="0.1.0")

    app.include_router(scenes.router)
    app.include_router(sequencer.router)
    app.include_router(registry.router)
    app.include_router(journey.router)
    app.include_router(engine_api.router)

    @app.websocket("/api/ws")
    async def ws_endpoint(ws: WebSocket):
        from spectra.services.ws import ws_manager
        await ws_manager.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)

    @app.get("/api/status")
    async def status():
        from spectra.services import (color_journey, engine, scene_store,
                                      sequencer_store)
        room = color_journey.load_room()
        seq = sequencer_store.load_config()
        return {
            "app": "SPECTRA",
            "increment": "S2",
            "scenes": len(scene_store.list_all()),
            "sequencer_enabled": seq.enabled,
            "bridge_connected": engine.bridge.connected,
            "engine_dark": engine.executor.mode == "recording",
            "light_ownership": "spot-effects",   # S3 hands over, owner's word
            "room_journey_degrees_per_min": room.journey.degrees_per_min,
            "room_wheel_position_deg": room.wheel_position_deg,
        }

    if config.WEB_DIST.exists():
        app.mount("/", SPAStaticFiles(directory=str(config.WEB_DIST), html=True),
                  name="spectra-app")
    else:
        @app.get("/")
        async def no_ui():
            return RedirectResponse(url="/spectra/api/status")

    return app


def _standalone() -> None:
    """Serve the same /spectra URL space the shared process mounts, so the
    frontend's absolute paths work identically after the S3 split. The
    engine start/stop pair mirrors main.py's — the host owns the lifespan
    because Starlette never runs a mounted sub-app's."""
    from contextlib import asynccontextmanager

    import uvicorn

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from spectra.services import engine
        await engine.start()
        yield
        await engine.stop()

    root = FastAPI(title="SPECTRA host", lifespan=lifespan)
    root.mount("/spectra", create_app())

    @root.get("/")
    async def to_app():
        return RedirectResponse(url="/spectra/")

    uvicorn.run(root, host="0.0.0.0", port=int(
        __import__("os").getenv("SPECTRA_PORT", "8010")))


if __name__ == "__main__":
    _standalone()
