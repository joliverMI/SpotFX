"""
SpotFX — WebSocket connection manager.

Maintains all active browser connections and broadcasts state updates.
The frontend interpolates timestamps between broadcasts.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from models.state import AppState

logger = logging.getLogger(__name__)


def _recording_active() -> bool:
    """True when audio_shape_service is currently capturing a song. Read fresh
    from the singleton on every broadcast; lazy import avoids circular load."""
    try:
        from services.audio_shape_service import audio_shape_service
        return bool(audio_shape_service._recording_uri)
    except Exception:
        return False


def _last_capture() -> dict:
    """Snapshot of the most recent capture's terminal state (success or
    failure with reason tag). Used by Now Playing to render a green/red
    badge after a capture finishes."""
    try:
        from services.audio_shape_service import audio_shape_service
        return {
            "status": audio_shape_service._last_capture_status,
            "reason": audio_shape_service._last_capture_reason,
            "uri":    audio_shape_service._last_capture_uri,
        }
    except Exception:
        return {"status": None, "reason": "", "uri": None}


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
        # Fan-out in parallel with a per-client write deadline. Dead/stale
        # client sockets (closed-but-not-yet-cleaned, mobile gone to sleep)
        # would otherwise hang send_json on the TCP send buffer indefinitely
        # and pin every broadcast at the OS-level TCP timeout. We give each
        # client 1s to ack; misses are disconnected so they stop poisoning
        # subsequent broadcasts.
        conns = list(self._connections)
        if not conns:
            return
        async def _send(ws):
            # 250 ms is plenty for any healthy client (localhost ≪10 ms, LAN
            # ≪50 ms). Anything past this is almost certainly a stale tab or
            # a remote on flaky wifi — drop to keep the loop snappy.
            await asyncio.wait_for(ws.send_json(payload), timeout=0.25)
        results = await asyncio.gather(
            *(_send(ws) for ws in conns),
            return_exceptions=True,
        )
        for ws, result in zip(conns, results):
            if isinstance(result, Exception):
                if isinstance(result, asyncio.TimeoutError):
                    logger.info("WS client send timeout — disconnecting stale client")
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
            "recapture_active": state.recapture_active,
            "recapture_remaining": state.recapture_remaining,
            "recording_active": _recording_active(),
            "last_capture": _last_capture(),
            "use_unreviewed_ai_triggers": state.use_unreviewed_ai_triggers,
            "use_analyzed_triggerless": state.use_analyzed_triggerless,
            "analyzed_trigger_override": state.analyzed_trigger_override,
            "auto_generate_enabled": state.auto_generate_enabled,
            "dinner_party_mode": state.dinner_party_mode,
            "ambient_mode_enabled": state.ambient_mode_enabled,
            "ambient_groups": list(state.ambient_groups),
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
                "context_uri": track.context_uri,
                "context_type": track.context_type,
            }
        payload["timing"] = state.timing or {}
        # Last Scene Update — the scene the fixed Update/Reset Scene events act on.
        if state.last_scene_update_id:
            try:
                from services.profile_manager import get_event
                last_scene = get_event(state.last_scene_update_id)
                if last_scene is not None and last_scene.event_type == "scene_update":
                    payload["last_scene_id"] = last_scene.id
                    payload["last_scene_name"] = last_scene.name
                    payload["last_scene_color"] = last_scene.color
            except Exception:
                pass
        # Scene Group currently driving the scene (Scene Morph's target).
        if state.active_scene_group_id:
            try:
                from services.profile_manager import get_event
                grp = get_event(state.active_scene_group_id)
                if grp is not None and grp.event_type == "scene_group":
                    payload["active_scene_group_id"] = grp.id
                    payload["active_scene_group_name"] = grp.name
            except Exception:
                pass
        # Last Color Set the engine applied.
        if state.last_color_set_id:
            try:
                from services import color_set_store
                card = color_set_store.get_by_id(state.last_color_set_id)
                if card is not None:
                    payload["last_color_set_id"] = card.id
                    payload["last_color_set_name"] = card.name
                    payload["last_color_set_color"] = card.color
            except Exception:
                pass
        payload["next_track_uri"] = state.next_track_uri
        payload["next_track_title"] = state.next_track_title
        # Active Set List, if any
        if state.active_setlist_id:
            try:
                from services import setlist_store
                sl = setlist_store.get_by_id(state.active_setlist_id)
                if sl:
                    payload["active_setlist"] = {
                        "id": sl.id,
                        "name": sl.name,
                        "auto_activate": sl.auto_activate,
                        "auto_use_analyzed": sl.auto_use_analyzed,
                        "genre_blending": sl.genre_blending,
                    }
            except Exception:
                pass
        # Friendly playlist name (when known) for "Playing from: ..." UI line
        if track and track.context_uri and state.observed_context_uris:
            payload["context_name"] = state.observed_context_uris.get(track.context_uri, "")
        await self.broadcast(payload)

    async def broadcast_trigger_fired(
        self, trigger_id: str, event_name: str, color: str,
        scheduled_ms: int = 0, fired_at_ms: int = 0, effective_offset_ms: int = 0,
        event_type: str = "", summary: str = "", intensity: float | None = None,
    ) -> None:
        """Notify the UI that a trigger just fired (for the flash indicator).

        `event_type` lets the UI distinguish single/sequence/beat_sequence/morph_set
        for display purposes. `summary` is an optional short human string
        describing what concretely fired — used for morph_set lane picks so the
        Now Playing chip can show e.g. "Brightness: Strips → 0.6 · Color: hot".
        """
        payload = {
            "type":                "trigger_fired",
            "trigger_id":          trigger_id,
            "event_name":          event_name,
            "color":               color,
            "scheduled_ms":        scheduled_ms,
            "fired_at_ms":         fired_at_ms,
            "effective_offset_ms": effective_offset_ms,
        }
        if event_type:
            payload["event_type"] = event_type
        if summary:
            payload["summary"] = summary
        if intensity is not None:
            payload["intensity"] = intensity
        await self.broadcast(payload)


ws_manager = WebSocketManager()
