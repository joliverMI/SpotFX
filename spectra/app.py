"""The SPECTRA app — its own FastAPI application, its own PROCESS
(python -m spectra, spectra.service). The S3 process split is DONE: the
spot-effects process no longer mounts or starts anything under spectra/ —
it serves /spectra/* through a thin reverse proxy (services/spectra_proxy)
so the owner's port-8000 addresses survive verbatim. The split exists
because one shared interpreter let spot-effects' 90 ms–5 s GIL bursts
freeze every render thread (the 2026-08-13 frame-rate diagnosis, verdict +
§c); process isolation is what made the old LedFX path smooth.

Runtime: the evolution engine (services/engine — bridge + drift conductor
+ response engine). The bridge reaches spot-effects over real sockets
(ws://127.0.0.1:$SPOTFX_PORT/ws) — the same URLs it used in the shared
process, which is why the split needed no bridge change. _standalone()
owns the engine start/stop pair (Starlette never runs a mounted sub-app's
lifespan, so the host has always owned it — the split changed which host,
nothing else).

S3: light ownership + the SPECTRA LIVENESS ENDPOINT CONTRACT live in
api/ownership.py — GET /spectra/api/liveness serves per-virtual frame-flush
freshness through the real render path (never delete or repoint without the
Admiral's word). /api/status stays the human status surface; the liveness
contract is the checker's.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from spectra import config
from spectra.api import engine as engine_api
from spectra.api import (device_preview, feedback, fire_history,
                         flare_preview, gradient2d, intensity_scale, journey,
                         ownership, registry, room_controls, room_preview,
                         scenes, sequencer, settings_console, show_review,
                         sonic_usage, spec, triggers)


class SPAStaticFiles(StaticFiles):
    """Serve the SPECTRA SPA with index.html fallback for client routes.

    Cache-Control: hashed files under /assets/ are content-addressed (a
    new build always produces a new filename), so they're safe to cache
    forever. index.html — and the SPA-fallback response served here for
    any unknown client route — is what NAMES those hashed files, so it
    must revalidate on every request; with no Cache-Control at all,
    browsers apply heuristic caching and can reuse a stale index.html
    without revalidating, pinning a phone to an old bundle indefinitely
    even though the new build is deployed and served correctly (see
    AGENTS.md's "SPA index.html must never be heuristically cached").
    """

    async def get_response(self, path: str, scope):
        from starlette.exceptions import HTTPException as StarletteHTTPException
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404:
                raise
            response = await super().get_response("index.html", scope)
            path = "index.html"
        if path.startswith("assets/"):
            response.headers["cache-control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["cache-control"] = "no-cache"
        return response


def create_app() -> FastAPI:
    app = FastAPI(title="SPECTRA", version="0.1.0")

    app.include_router(scenes.router)
    app.include_router(sequencer.router)
    app.include_router(registry.router)
    app.include_router(journey.router)
    app.include_router(room_preview.router)
    app.include_router(flare_preview.router)
    app.include_router(engine_api.router)
    app.include_router(ownership.router)
    app.include_router(room_controls.router)
    app.include_router(device_preview.router)
    app.include_router(settings_console.router)
    app.include_router(triggers.router)
    app.include_router(fire_history.router)
    app.include_router(feedback.router)
    app.include_router(show_review.router)
    app.include_router(intensity_scale.router)
    app.include_router(sonic_usage.router)
    app.include_router(spec.router)
    app.include_router(gradient2d.router)

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
        import sys as _sys

        from fx import light_ownership
        from spectra.services import (color_journey, engine, scene_store,
                                      sequencer_store)
        room = color_journey.load_room()
        seq = sequencer_store.load_config()
        return {
            "app": "SPECTRA",
            "increment": "S3",
            # 0.001 in the standalone process (_standalone sets it — the
            # Stage-1 GIL mitigation); interpreter default elsewhere. The
            # process-split spec asserts this on the real child process.
            "switch_interval_s": _sys.getswitchinterval(),
            "scenes": len(scene_store.list_all()),
            "sequencer_enabled": seq.enabled,
            "bridge_connected": engine.bridge.connected,
            "engine_dark": engine.executor.mode == "recording",
            "light_ownership": light_ownership.load().owner,
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


@asynccontextmanager
async def _standalone_lifespan(app):
    """The SPECTRA process's startup/shutdown pair. Module-level so the
    lifecycle specs enter the REAL sequence, not a re-enactment."""
    import asyncio
    import logging
    import os

    logger = logging.getLogger("spectra")
    from spectra.services import (ambient_music_gate, device_preview, engine,
                                   flare_preview_hold, frame_watchdog,
                                   handover, ownership_reconciler,
                                   param_watchdog)
    await engine.start()
    await device_preview.start()
    # Restart mid-reign: if the ownership record says spectra owns, the
    # live stack reactivates itself through the guarded activation path
    # (grant + readiness gate). Failure stays dark-but-owned and keeps
    # serving — liveness 503 is the alarm.
    await handover.resume_own_room()
    # A flare preview's live hold (spectra/services/flare_preview_hold.py)
    # can't survive a restart on its own — its release deadline is
    # in-memory only, same as preview_pause's own `_until`, and dies with
    # the old process. Same shape as fx/light_ownership.py's own
    # recover_stale_handover(): a durable, timestamped record, landed back
    # to a known-safe state at startup because a restart is proof nothing
    # is still managing it. Must run AFTER resume_own_room() re-activates
    # the live stack — reverting is itself a real fx_seam write.
    await flare_preview_hold.recover_stale_hold()
    # Freeze state is in-memory only on the fresh HueDevice objects
    # resume_own_room() just built (fx/devices/hue.py's own docstring) — a
    # restart while ambient was genuinely holding a quiet room would
    # otherwise silently drop the takeover while the room bar still shows
    # it ON. Routed through the mode precedence gate (services/
    # ambient_music_gate.py), NOT a blind reconcile(True, ...): mode
    # "always" holds immediately regardless (unconditional by design), but
    # "auto" needs a real playback read first — the bridge hasn't
    # connected yet at this exact point, so is_playing() reads unknown and
    # the gate correctly holds off rather than freezing a room that might
    # actually be mid-song — the same decision the first real bridge
    # broadcast makes moments later (engine.py's _on_track_uri) picks the
    # hold back up automatically once playback is confirmed quiet. No-ops
    # fast if ambient_mode is "off".
    await ambient_music_gate.reconcile_now()
    watchdog_task = asyncio.create_task(
        frame_watchdog.run_supervised(), name="spectra-frame-watchdog")
    # Record-vs-reality reconciler (report gate e3, 2026-08-13 two-writers
    # incident): while THIS process owns, ledfx.service must be inactive and
    # no foreign realtime source may hold her WLEDs — the spectra half of
    # the check; services/spectra_liveness_reconciler.py is the other half.
    reconciler_task = asyncio.create_task(
        ownership_reconciler.run_supervised(), name="spectra-ownership-reconciler")
    # Ambient's own status-honesty verifier (2026-08-15 overnight defect —
    # ambient_music_gate.py's module docstring, "Status honesty"): a
    # claimed hold otherwise only ever gets re-checked by a state-changing
    # write, so under "always" mode it can go stale forever once genuinely
    # held. GET-only, own short cadence, independent of bridge broadcasts.
    ambient_verify_task = asyncio.create_task(
        ambient_music_gate.run_supervised(), name="spectra-ambient-verifier")
    # The flare preview hold's OWN safety mechanism (its module docstring:
    # "deadline-driven, not close-driven") — an always-on sweep checking
    # every SWEEP_INTERVAL_S whether a hold's deadline has lapsed and
    # reverting it if so. This is what actually protects a browser-closed/
    # connection-dropped session; recover_stale_hold() above only covers
    # the separate restart case.
    flare_preview_sweep_task = asyncio.create_task(
        flare_preview_hold.run_supervised(), name="spectra-flare-preview-sweep")
    # The param orphan watchdog (owner ask 2026-08-21, after an effect was
    # left stuck running backwards with nothing holding it there): every
    # SWEEP_INTERVAL_S, any engine-baselined effect param sitting away from
    # its baseline with no pending release, no drift mechanism and no tween
    # in flight for ORPHAN_GRACE_S gets restored — loudly (WARNING log,
    # fire_history "watchdog" bucket, a count on /api/liveness). Stands
    # down by itself while the engine is dark or a preview holds the room.
    param_watchdog_task = asyncio.create_task(
        param_watchdog.run_supervised(), name="spectra-param-watchdog")
    logger.info("SPECTRA started — own process, pid %d", os.getpid())
    yield
    all_tasks = (watchdog_task, reconciler_task, ambient_verify_task,
                flare_preview_sweep_task, param_watchdog_task)
    for task in all_tasks:
        task.cancel()
    for task in all_tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    await engine.stop()
    await device_preview.stop()
    # Release the room outputs cleanly on SIGTERM (deploy restarts): a
    # torn-down Hue DTLS session / DDP sender re-handshakes instantly on
    # the next activation, a killed one has to time out first (§4d).
    # No-op while dark. The ownership record is NOT touched — the next
    # start's resume_own_room() re-lights the room she still owns.
    from spectra.services.live_host import live
    if live.active:
        engine.go_dark()
        await live.deactivate()
    logger.info("SPECTRA shutdown complete.")


def _standalone() -> None:
    """The SPECTRA process entry. Serves the same /spectra URL space the
    shared process used to mount, so the frontend's absolute paths and the
    LIVENESS CONTRACT's path are identical whether a client arrives direct
    (port $SPECTRA_PORT) or through the spot-effects proxy (port 8000)."""
    import logging
    import os
    import sys

    import uvicorn

    # Stage 1's promised GIL mitigation (PR #18: "to be applied when the
    # facade ever goes live"; overdue per the 2026-08-13 diagnosis §D).
    # 0.001 s is the benchmarked value: under saturated pure-Python load
    # beside five 62 fps virtuals it restored ~57 fps for ~2 % extra compute.
    # It bounds COOPERATIVE bytecode holds only — this process's own API must
    # stay cheap (JSON reads), and C-level holds (large json parses) don't
    # yield regardless, which is exactly why the heavy spot-effects loop now
    # lives in another interpreter. The spot-effects process keeps the 5 ms
    # default: it has no render threads, so tightening it would only tax its
    # bursty pure-Python code.
    sys.setswitchinterval(0.001)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    root = FastAPI(title="SPECTRA host", lifespan=_standalone_lifespan)
    root.mount("/spectra", create_app())

    @root.get("/")
    async def to_app():
        return RedirectResponse(url="/spectra/")

    uvicorn.run(
        root,
        host=os.getenv("SPECTRA_HOST", "0.0.0.0"),
        port=int(os.getenv("SPECTRA_PORT", "8010")),
        # Same bound as main.py: SIGTERM must not wait forever on lingering
        # WebSockets (the proxy holds one open per browser tab).
        timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    _standalone()
