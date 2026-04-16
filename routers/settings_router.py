"""
SpotFX — Settings API router.

Exposes runtime-adjustable settings. Changes take effect immediately and are
persisted to storage/settings.json so they survive server restarts.
"""
import json
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
    pre_brightness_lead_ms: Optional[int] = None
    pre_transition_lead_ms: Optional[int] = None
    smooth_ramp_ms: Optional[int] = None
    auto_generate_mode: Optional[str] = None   # "embedded" | "claude"
    show_ai_triggers: Optional[bool] = None
    show_advanced: Optional[bool] = None
    song_source: Optional[str] = None          # "spotify" | "ledfx"
    lastfm_api_key: Optional[str] = None
    lastfm_username: Optional[str] = None


@router.get("")
async def get_settings():
    return {
        "audio_latency_ms": settings.audio_latency_ms,
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
        "pre_brightness_lead_ms": settings.pre_brightness_lead_ms,
        "pre_transition_lead_ms": settings.pre_transition_lead_ms,
        "smooth_ramp_ms": settings.smooth_ramp_ms,
        "auto_generate_mode": settings.auto_generate_mode,
        "show_ai_triggers": settings.show_ai_triggers,
        "show_advanced": settings.show_advanced,
        "song_source": settings.song_source,
        "lastfm_api_key": settings.lastfm_api_key,
        "lastfm_username": settings.lastfm_username,
    }


@router.patch("")
async def patch_settings(patch: SettingsPatch):
    """Apply non-None values from patch to the live settings object and persist to disk."""
    data = patch.model_dump(exclude_none=True)
    for key, val in data.items():
        if hasattr(settings, key):
            object.__setattr__(settings, key, val)
    saved = _load_settings_file()
    saved.update(data)
    _save_settings_file(saved)
    return {"status": "updated"}
