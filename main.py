"""
SpotFX — FastAPI application entry point.

Startup sequence:
  1. Mount static frontend files
  2. Register API routers
  3. Start background tasks:
       - Song source loop (Spotify polling or LedFX WebSocket, per settings)
       - LedFX latency probe loop
       - Trigger engine loop
  4. WebSocket endpoint for real-time browser updates
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import settings, PROFILES_DIR, AUDIO_SHAPES_DIR
from models.state import state
from api import ledfx_client
from services.trigger_engine import TriggerEngine
from services.websocket_manager import ws_manager
from services.profile_manager import load_profile_by_uri, load_profile_by_title_artist, save_profile
from services.audio_shape_service import audio_shape_service
from models.song_profile import SongProfile
from routers import spotify, profiles, events, control, settings_router, audio_shape_router, auth, ai_triggers_router, ai_suggestions_router, effect_params_router, gradients_router, palettes_router, triggerless, device_manager
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

    # Select song source based on settings
    if settings.song_source == "ledfx":
        from api.ledfx_song_client import polling_loop as _song_polling_loop
        _song_task_name = "ledfx-song-source"
        logger.info("Song source: LedFX (event-driven)")
    else:
        from api.spotify_client import polling_loop as _song_polling_loop
        _song_task_name = "spotify-poll"
        logger.info("Song source: Spotify API")

    # Launch background tasks
    tasks = [
        asyncio.create_task(_song_polling_loop(_on_state_update), name=_song_task_name),
        asyncio.create_task(ledfx_client.latency_loop(), name="ledfx-latency"),
        asyncio.create_task(ledfx_client.poll_virtual_states(), name="ledfx-virtual-poll"),
        asyncio.create_task(engine.run(), name="trigger-engine"),
    ]
    logger.info("SpotFX started — http://%s:%d", settings.app_host, settings.app_port)
    yield
    # Shutdown
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await audio_shape_service.on_track_change(None)  # flush any in-progress capture
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
app.include_router(ai_suggestions_router.router)
app.include_router(effect_params_router.router)
app.include_router(gradients_router.router)
app.include_router(palettes_router.router)
app.include_router(triggerless.router)
app.include_router(device_manager.router)


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


# ── Static frontend ───────────────────────────────────────────────────────────
FRONTEND_DIR = Path(__file__).parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(str(FRONTEND_DIR / "favicon.svg"), media_type="image/svg+xml")


@app.get("/")
async def root():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

@app.get("/{page}.html")
async def serve_page(page: str):
    path = FRONTEND_DIR / f"{page}.html"
    if path.exists():
        return FileResponse(str(path))
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ── Dev runner ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )
