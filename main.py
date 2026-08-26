"""
SpotFX — FastAPI application entry point.

Startup sequence:
  1. Mount the React SPA (web/dist) at /app; / redirects there
  2. Register API routers
  3. Start background tasks:
       - Song source loop (Spotify polling or LedFX WebSocket, per settings)
       - LedFX latency probe loop
       - Trigger engine loop
  4. WebSocket endpoint for real-time browser updates
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from config import settings, PROFILES_DIR, AUDIO_SHAPES_DIR
from models.state import state
from api import ledfx_client
from services.trigger_engine import TriggerEngine
from services.websocket_manager import ws_manager
from services.profile_manager import load_profile_by_uri, load_profile_by_title_artist, save_profile
from services.audio_shape_service import audio_shape_service
from models.song_profile import SongProfile
from routers import spotify, profiles, events, control, settings_router, audio_shape_router, auth, ai_triggers_router, effect_params_router, gradients_router, palettes_router, triggerless, device_manager, setlist_router, timing_viz_router, debug_router, morph_router, color_sets_router, lock_history_router, gif_assets_router, scenes_v2_router, shape_map_router, sequencer_router
from routers.settings_router import apply_settings_override
from services import effect_params

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logger = logging.getLogger("spotfx")


# ── Trigger engine (singleton) ────────────────────────────────────────────────
engine = TriggerEngine()


async def _on_state_update(app_state) -> None:
    """Called after each Spotify poll — load (or auto-create) profile and broadcast."""
    track = app_state.current_track
    if track and track.spotify_uri.startswith("guest:"):
        # Guest-owned playback (services/guest_source drives the engine).
        # Skip profile handling entirely: auto-creating profiles or starting
        # audio-shape capture for guest: URIs would write junk to storage.
        # Capture teardown must still run — pass None (the shutdown-flush
        # signal) so an in-flight capture stops without a new one starting
        # for the guest: URI.
        await audio_shape_service.on_track_change(None)
        await ws_manager.broadcast_state(app_state)
        return
    if track:
        profile = load_profile_by_uri(track.spotify_uri)
        if profile is None and track.title and track.artist:
            profile = load_profile_by_title_artist(track.title, track.artist)
            if profile:
                logger.info("Profile matched by title/artist fallback: %s", profile.filename)
        if profile is None:
            # Auto-create a blank profile for any new song
            profile = SongProfile(
                spotify_uri=track.spotify_uri,
                title=track.title,
                artist=track.artist,
                artist_genre=track.genres,
                duration_ms=track.duration_ms,
            )
            save_profile(profile)
            logger.info("Auto-created blank profile: %s", profile.filename)
        elif not profile.artist_genre and track.genres:
            profile.artist_genre = track.genres
            save_profile(profile)
        engine.load_profile(profile)

    # SPECTRA scene sequencer: observes song transitions (its only shipped
    # change-moment source). Dark unless sequencer.json config.enabled — the
    # first thing a moment does is check that flag. Guest playback (early
    # return above) is deliberately not fed.
    from services.scene_sequencer import scene_sequencer
    await scene_sequencer.on_track_state(track)

    await audio_shape_service.on_track_change(track)
    await ws_manager.broadcast_state(app_state)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure storage dirs exist
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_SHAPES_DIR.mkdir(parents=True, exist_ok=True)

    # Load effect parameter registry
    effect_params.load()

    # Load Morph last-known (virtual, effect) configs — empty file = fresh start
    from services import morph_effect_state
    morph_effect_state.load()

    # Ensure the shared scene-override temp scene exists on LedFX (idempotent).
    # Scene-override morphs (event.scene_override=True) rewrite + activate this
    # one scene rather than streaming individual virtual effect writes.
    # Canonical id uses hyphens because LedFX normalizes underscores → hyphens.
    asyncio.create_task(ledfx_client.ensure_scene("spotfx-morph-temp", "SpotFX Morph Temp"))

    # Seed device categories from static config (first-run migration)
    from services.device_category_service import seed_from_effect_params, migrate_roles
    seed_from_effect_params()
    migrate_roles()

    # Apply persisted settings overrides (takes precedence over .env defaults)
    apply_settings_override()

    # Restore persisted AppState flags
    from routers.settings_router import _load_settings_file
    _saved = _load_settings_file()
    if "audio_analysis_enabled" in _saved:
        state.audio_analysis_enabled = bool(_saved["audio_analysis_enabled"])
    if "auto_generate_enabled" in _saved:
        state.auto_generate_enabled = bool(_saved["auto_generate_enabled"])
    if "dinner_party_mode" in _saved:
        state.dinner_party_mode = bool(_saved["dinner_party_mode"])
    if "use_analyzed_triggerless" in _saved:
        state.use_analyzed_triggerless = bool(_saved["use_analyzed_triggerless"])
    if "ambient_mode_enabled" in _saved:
        state.ambient_mode_enabled = bool(_saved["ambient_mode_enabled"])
    if "ambient_groups" in _saved:
        state.ambient_groups = [str(g) for g in (_saved["ambient_groups"] or [])]
    if _saved.get("display_mode") in ("default", "dark", "light"):
        state.display_mode = _saved["display_mode"]
        state.display_mode_resolved = state.display_mode

    # Select song source based on settings
    if settings.song_source == "ledfx":
        from api.ledfx_song_client import polling_loop as _song_polling_loop
        _song_task_name = "ledfx-song-source"
        logger.info("Song source: LedFX (event-driven)")
    else:
        from api.spotify_client import polling_loop as _song_polling_loop
        _song_task_name = "spotify-poll"
        logger.info("Song source: Spotify API")

    # Always-on PCM ring buffer — fills continuously so force-recapture can
    # backfill song-start audio even when URI detection lags.
    from api.pcm_ring_buffer import pcm_ring_buffer
    pcm_ring_buffer.start()

    # Tune scheduler: processes storage/tune_schedule.json (queued/timed
    # training runs) — armed here so pending schedules survive restarts.
    from services import tune_scheduler

    # Light ownership: land a crash-orphaned handover (age-gated — never
    # fights a live orchestrator). Both worlds run this at startup; before
    # the S3 process split this world's call rode spectra's engine start,
    # which now happens in the SPECTRA process. stdlib-only import.
    from fx import light_ownership
    light_ownership.recover_stale_handover()

    # Launch background tasks
    tasks = [
        asyncio.create_task(_song_polling_loop(_on_state_update), name=_song_task_name),
        asyncio.create_task(ledfx_client.latency_loop(), name="ledfx-latency"),
        asyncio.create_task(ledfx_client.poll_virtual_states(), name="ledfx-virtual-poll"),
        # Always created, even with settings.legacy_trigger_engine_enabled
        # False (the retired default) — the loop still refreshes
        # state.timing every tick for SPECTRA's bridge (its xcorr sync),
        # it just fires nothing. See trigger_engine.run()'s own gate.
        asyncio.create_task(engine.run(), name="trigger-engine"),
        asyncio.create_task(tune_scheduler.worker_loop(), name="tune-scheduler"),
    ]
    # Write-plane wedge tripwire + systemd watchdog gating (its own task, not
    # inside latency_loop — monitoring must not die with the monitored).
    # Dark-compatible: without Type=notify/WatchdogSec in the unit
    # (deploy/spotfx.service), its sd_notify calls are no-ops.
    from services import write_plane_watchdog
    tasks.append(asyncio.create_task(
        write_plane_watchdog.run_supervised(), name="write-plane-watchdog"))
    # Record-vs-reality reconciler (report gate e3, 2026-08-13 two-writers
    # incident): while this process owns, SPECTRA's own liveness must not
    # report her live stack painting — the spot-effects half of the check;
    # spectra/services/ownership_reconciler.py is the other half.
    from services import spectra_liveness_reconciler
    tasks.append(asyncio.create_task(
        spectra_liveness_reconciler.run_supervised(),
        name="spectra-liveness-reconciler"))
    # Sync-as-a-property-of-writing (2026-08-25): profile_manager.save_profile
    # marks every trigger write, this drain lands the marks in the copy
    # SPECTRA fires from — so a writer nobody remembered to hook still
    # reaches his show. Upsert-only; see the module docstring.
    from services import profile_trigger_sync_queue
    tasks.append(asyncio.create_task(
        profile_trigger_sync_queue.run_supervised(),
        name="profile-trigger-sync-drain"))
    # Guest source: watches the snapcast Guest/AirPlay streams and drives the
    # engine in simple-triggerless mode while a guest session owns the speakers.
    from services import guest_source
    tasks.append(asyncio.create_task(guest_source.polling_loop(), name="guest-source"))
    # Re-assert Ambient Mode if it was left on across restarts (freeze the Hue
    # devices + hold them at the static color). Deferred as a task so a slow Hue
    # bridge can't stall startup. No parked-virtual selfheal needed — ambient no
    # longer deactivates virtuals.
    if state.ambient_mode_enabled:
        from services import ambient_mode
        # Restore the held group subset; legacy saves without group detail = all.
        _want = set(state.ambient_groups) or None
        tasks.append(asyncio.create_task(ambient_mode.set_groups(_want), name="ambient-restore"))

    logger.info("SpotFX started — http://%s:%d", settings.app_host, settings.app_port)
    yield
    # Shutdown
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await audio_shape_service.on_track_change(None)  # flush any in-progress capture
    pcm_ring_buffer.stop()
    logger.info("SpotFX shutdown complete.")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="SpotFX", version="0.1.0", lifespan=lifespan)

# API routers
app.include_router(spotify.router)
app.include_router(profiles.router)
app.include_router(events.router)
app.include_router(control.router)
app.include_router(settings_router.router)
app.include_router(audio_shape_router.router)
app.include_router(auth.router)
app.include_router(ai_triggers_router.router)
app.include_router(effect_params_router.router)
app.include_router(gradients_router.router)
app.include_router(palettes_router.router)
app.include_router(triggerless.router)
app.include_router(device_manager.router)
app.include_router(setlist_router.router)
app.include_router(timing_viz_router.router)
app.include_router(lock_history_router.router)
app.include_router(debug_router.router)
app.include_router(morph_router.router)
app.include_router(color_sets_router.router)
app.include_router(gif_assets_router.router)
app.include_router(scenes_v2_router.router)
app.include_router(shape_map_router.router)
app.include_router(sequencer_router.router)

# ── SPECTRA (her OWN process since the S3 split) ──────────────────────────────
# SPECTRA runs standalone (python -m spectra under spectra.service) so this
# app's interpreter bursts can never stall her render threads again (the
# 2026-08-13 frame-rate diagnosis). Nothing here imports spectra/ anymore —
# /spectra/* is a transparent reverse proxy, which is what keeps the owner's
# port-8000 bookmark and THE LIVENESS CONTRACT address
# (GET /spectra/api/liveness) serving verbatim. The SPECTRA process's own
# port (settings.spectra_port) is the direct address that does not share
# this event loop's stalls.
from services.spectra_proxy import SpectraProxy
app.mount("/spectra", SpectraProxy(settings.spectra_port))


# ── Service status (health check for external callers) ────────────────────────
@app.get("/api/service/status")
async def service_status():
    return {
        "status": "ok",
        "paused": state.paused,
        "audio_analysis_enabled": state.audio_analysis_enabled,
        "track": state.current_track.spotify_uri if state.current_track else None,
    }


@app.post("/api/analysis/toggle")
async def toggle_analysis():
    state.audio_analysis_enabled = not state.audio_analysis_enabled
    if not state.audio_analysis_enabled:
        await audio_shape_service.stop_capture()
    from routers.settings_router import _load_settings_file, _save_settings_file
    saved = _load_settings_file()
    saved["audio_analysis_enabled"] = state.audio_analysis_enabled
    _save_settings_file(saved)
    await ws_manager.broadcast_state(state)
    return {"audio_analysis_enabled": state.audio_analysis_enabled}


@app.post("/api/genre-blending/toggle")
async def toggle_genre_blending():
    from config import settings as _settings
    object.__setattr__(_settings, "genre_blending_enabled", not _settings.genre_blending_enabled)
    from routers.settings_router import _load_settings_file, _save_settings_file
    saved = _load_settings_file()
    saved["genre_blending_enabled"] = _settings.genre_blending_enabled
    _save_settings_file(saved)
    await ws_manager.broadcast_state(state)
    return {"genre_blending_enabled": _settings.genre_blending_enabled}


# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    # Push current state immediately on connect
    await ws_manager.broadcast_state(state)
    try:
        while True:
            # Keep connection alive; client may send simple pings
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


# ── React SPA (web/dist) ──────────────────────────────────────────────────────
class SPAStaticFiles(StaticFiles):
    """Serve web/dist with index.html fallback so client-side routes
    (/app/event/<id>) deep-link correctly.

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


WEB_DIST = Path(__file__).parent / "web" / "dist"
if WEB_DIST.exists():
    app.mount("/app", SPAStaticFiles(directory=str(WEB_DIST), html=True), name="app")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(str(WEB_DIST / "favicon.svg"), media_type="image/svg+xml")


@app.get("/")
async def root():
    return RedirectResponse(url="/app/")


# ── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # reload defaults OFF. The watchfiles reloader must not run under the systemd
    # service: every save in the source tree triggered a worker restart, and that
    # restart hung on persistent /ws WebSocket connections ("Waiting for
    # connections to close"), leaving the HTTP server dead while the event loop
    # kept ticking. Opt in for local dev with SPOTFX_DEV_RELOAD=1.
    reload = os.getenv("SPOTFX_DEV_RELOAD") == "1"
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=reload,
        # Bound graceful shutdown so SIGTERM (systemd stop, the /settings/restart
        # button, or a dev reload) force-closes lingering WebSockets after 3s
        # instead of waiting forever for browser tabs to disconnect.
        timeout_graceful_shutdown=3,
    )
