"""
SpotFX — Spotify router.

Endpoints:
  GET /api/spotify/status   — current playback info
  GET /api/spotify/callback  — OAuth redirect handler
"""
from fastapi import APIRouter
from models.state import state

router = APIRouter(prefix="/api/spotify", tags=["spotify"])


@router.get("/status")
async def get_status():
    """Return current Spotify playback state (interpolated)."""
    track = state.current_track
    if track is None:
        return {"playing": False, "track": None}
    return {
        "playing": track.is_playing,
        "track": {
            "spotify_uri": track.spotify_uri,
            "title": track.title,
            "artist": track.artist,
            "duration_ms": track.duration_ms,
            "progress_ms": track.interpolated_progress_ms(),
            "device_name": track.device_name,
        },
    }
