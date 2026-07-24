"""
SpotFX — Settings API router.

Exposes runtime-adjustable settings. Changes take effect immediately and are
persisted to storage/settings.json so they survive server restarts.
"""
import asyncio
import json
import os
import signal
from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from config import settings

SETTINGS_FILE = Path("storage/settings.json")


def _load_settings_file() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_settings_file(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def apply_settings_override() -> None:
    """Load storage/settings.json and apply to the in-memory settings singleton."""
    for key, val in _load_settings_file().items():
        if hasattr(settings, key):
            object.__setattr__(settings, key, val)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPatch(BaseModel):
    audio_latency_ms: Optional[int] = None
    active_timing_device: Optional[str] = None
    timing_device_offsets: Optional[dict[str, int]] = None
    ledfx_trigger_buffer_ms: Optional[int] = None
    builder_zoom_window_s: Optional[int] = None
    builder_future_buffer_s: Optional[int] = None
    audio_input_device: Optional[str] = None
    spotify_device_name: Optional[str] = None
    ledfx_host: Optional[str] = None
    ledfx_port: Optional[int] = None
    audio_analysis_max_songs: Optional[int] = None
    shape_average_window_ms: Optional[int] = None
    shape_scale_overall: Optional[float] = None
    shape_scale_total: Optional[float] = None
    shape_scale_bass: Optional[float] = None
    shape_scale_mid: Optional[float] = None
    shape_scale_high: Optional[float] = None
    quiet_baseline_window_s: Optional[int] = None
    quiet_min_duration_ms: Optional[int] = None
    audio_shape_min_capture_pct: Optional[float] = None
    smooth_ramp_ms: Optional[int] = None
    hue_blend_transitions: Optional[bool] = None
    auto_generate_mode: Optional[str] = None   # "embedded" | "claude"
    show_ai_triggers: Optional[bool] = None
    show_advanced: Optional[bool] = None
    genre_blending_enabled: Optional[bool] = None
    force_scene_enabled: Optional[bool] = None
    force_scene_event_id: Optional[str] = None
    suppress_triggers_during_capture: Optional[bool] = None
    xcorr_monitor_enabled: Optional[bool] = None
    song_source: Optional[str] = None          # "spotify" | "ledfx"
    lastfm_api_key: Optional[str] = None
    lastfm_username: Optional[str] = None
    spotipy_client_id: Optional[str] = None
    spotipy_client_secret: Optional[str] = None
    spotipy_redirect_uri: Optional[str] = None
    ambient_target_category: Optional[str] = None
    ambient_color_mode: Optional[str] = None
    ambient_color: Optional[str] = None
    ambient_kelvin: Optional[int] = None
    ambient_brightness: Optional[int] = None
    ambient_wake_scene: Optional[str] = None
    ambient_transition_s: Optional[float] = None
    ambient_fade_brightness: Optional[int] = None
    ambient_catchup_s: Optional[float] = None


@router.get("")
async def get_settings():
    return {
        "audio_latency_ms": settings.audio_latency_ms,
        "active_timing_device": settings.active_timing_device,
        "timing_device_offsets": settings.timing_device_offsets,
        "ledfx_trigger_buffer_ms": settings.ledfx_trigger_buffer_ms,
        "builder_zoom_window_s": settings.builder_zoom_window_s,
        "builder_future_buffer_s": settings.builder_future_buffer_s,
        "audio_input_device": settings.audio_input_device,
        "spotify_device_name": settings.spotify_device_name,
        "ledfx_host": settings.ledfx_host,
        "ledfx_port": settings.ledfx_port,
        "ledfx_base_url": settings.ledfx_url,
        "poll_interval_playing_ms": settings.poll_interval_playing_ms,
        "poll_interval_paused_ms": settings.poll_interval_paused_ms,
        "poll_interval_idle_ms": settings.poll_interval_idle_ms,
        "audio_analysis_max_songs": settings.audio_analysis_max_songs,
        "shape_average_window_ms": settings.shape_average_window_ms,
        "shape_scale_overall": settings.shape_scale_overall,
        "shape_scale_total": settings.shape_scale_total,
        "shape_scale_bass": settings.shape_scale_bass,
        "shape_scale_mid": settings.shape_scale_mid,
        "shape_scale_high": settings.shape_scale_high,
        "quiet_baseline_window_s": settings.quiet_baseline_window_s,
        "quiet_min_duration_ms": settings.quiet_min_duration_ms,
        "audio_shape_min_capture_pct": settings.audio_shape_min_capture_pct,
        "smooth_ramp_ms": settings.smooth_ramp_ms,
        "hue_blend_transitions": settings.hue_blend_transitions,
        "auto_generate_mode": settings.auto_generate_mode,
        "show_ai_triggers": settings.show_ai_triggers,
        "show_advanced": settings.show_advanced,
        "genre_blending_enabled": settings.genre_blending_enabled,
        "force_scene_enabled": settings.force_scene_enabled,
        "force_scene_event_id": settings.force_scene_event_id,
        "suppress_triggers_during_capture": settings.suppress_triggers_during_capture,
        "xcorr_monitor_enabled": settings.xcorr_monitor_enabled,
        "song_source": settings.song_source,
        "lastfm_api_key": settings.lastfm_api_key,
        "lastfm_username": settings.lastfm_username,
        "spotipy_client_id": settings.spotipy_client_id,
        "spotipy_client_secret": settings.spotipy_client_secret,
        "spotipy_redirect_uri": settings.spotipy_redirect_uri,
        "ambient_target_category": settings.ambient_target_category,
        "ambient_color_mode": settings.ambient_color_mode,
        "ambient_color": settings.ambient_color,
        "ambient_kelvin": settings.ambient_kelvin,
        "ambient_brightness": settings.ambient_brightness,
        "ambient_wake_scene": settings.ambient_wake_scene,
        "ambient_transition_s": settings.ambient_transition_s,
        "ambient_fade_brightness": settings.ambient_fade_brightness,
        "ambient_catchup_s": settings.ambient_catchup_s,
    }


@router.post("/restart")
async def restart_server():
    """Signal the process group so systemd (Restart=always) brings SpotFX back.

    SIGTERM first for a clean shutdown — uvicorn's timeout_graceful_shutdown=3
    guarantees it can't hang on open WebSockets the way it used to. A SIGKILL
    fallback 5s later is a hard backstop in case graceful shutdown is wedged for
    any other reason, so the restart button can never leave the server in the
    half-down limbo we hit before."""
    async def _kill():
        pgid = os.getpgid(os.getpid())
        await asyncio.sleep(0.15)  # let the response flush first
        os.killpg(pgid, signal.SIGTERM)
        await asyncio.sleep(5.0)
        # Still alive? force it. (Unreached if SIGTERM already exited the process.)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    asyncio.create_task(_kill())
    return {"status": "restarting"}


@router.patch("")
async def patch_settings(patch: SettingsPatch):
    """Apply non-None values from patch to the live settings object and persist to disk."""
    data = patch.model_dump(exclude_none=True)
    prev_force_on = settings.force_scene_enabled
    prev_force_eid = settings.force_scene_event_id
    for key, val in data.items():
        if hasattr(settings, key):
            object.__setattr__(settings, key, val)
    saved = _load_settings_file()
    saved.update(data)
    _save_settings_file(saved)
    # If Ambient Mode is live and its target/color changed, re-apply in the
    # background (the Hue work can take several seconds — don't hang the save).
    if any(k.startswith("ambient_") for k in data):
        from models.state import state
        if state.ambient_mode_enabled:
            from services import ambient_mode
            asyncio.create_task(ambient_mode.reapply())
    # Force Scene: turning it on or picking a different scene asserts the
    # forced scene right away instead of waiting for the next scene pick.
    # Fired in the background — lane ramps can take seconds.
    if (settings.force_scene_enabled and settings.force_scene_event_id
            and (not prev_force_on
                 or settings.force_scene_event_id != prev_force_eid)):
        from main import engine
        asyncio.create_task(
            engine.fire_event_now(settings.force_scene_event_id))
    return {"status": "updated"}
