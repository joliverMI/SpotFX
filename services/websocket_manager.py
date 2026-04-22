"""
SpotFX — WebSocket connection manager.

Maintains all active browser connections and broadcasts state updates.
The frontend interpolates timestamps between broadcasts.
"""
from __future__ import annotations
import json
import logging
from typing import Any

from fastapi import WebSocket

from models.state import AppState

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.debug("WS client connected. Total: %d", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard if False else None
        try:
            self._connections.remove(ws)
        except ValueError:
            pass
        logger.debug("WS client disconnected. Total: %d", len(self._connections))

    async def broadcast(self, payload: dict) -> None:
        dead = []
        for ws in list(self._connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_state(self, state: AppState) -> None:
        """Serialize AppState and broadcast to all clients."""
        from config import settings as _settings
        track = state.current_track
        payload: dict[str, Any] = {
            "type": "state",
            "paused": state.paused,
            "on_target_device": state.on_target_device,
            "ledfx_rtt_ms": round(state.ledfx_rtt_ms, 1),
            "audio_analysis_enabled": state.audio_analysis_enabled,
            "recapture_wavs": state.recapture_wavs,
            "use_unreviewed_ai_triggers": state.use_unreviewed_ai_triggers,
            "use_analyzed_triggerless": state.use_analyzed_triggerless,
            "analyzed_trigger_override": state.analyzed_trigger_override,
            "auto_generate_enabled": state.auto_generate_enabled,
            "dinner_party_mode": state.dinner_party_mode,
            "genre_blending_enabled": _settings.genre_blending_enabled,
            "track": None,
        }
        if track:
            payload["track"] = {
                "spotify_uri": track.spotify_uri,
                "title": track.title,
                "artist": track.artist,
                "duration_ms": track.duration_ms,
                "progress_ms": track.interpolated_progress_ms(),
                "is_playing": track.is_playing,
                "device_name": track.device_name,
                "genres": track.genres,
            }
        payload["timing"] = state.timing or {}
        await self.broadcast(payload)

    async def broadcast_trigger_fired(
        self, trigger_id: str, event_name: str, color: str,
        scheduled_ms: int = 0, fired_at_ms: int = 0, effective_offset_ms: int = 0,
    ) -> None:
        """Notify the UI that a trigger just fired (for the flash indicator)."""
        await self.broadcast({
            "type":                "trigger_fired",
            "trigger_id":          trigger_id,
            "event_name":          event_name,
            "color":               color,
            "scheduled_ms":        scheduled_ms,
            "fired_at_ms":         fired_at_ms,
            "effective_offset_ms": effective_offset_ms,
        })


ws_manager = WebSocketManager()
