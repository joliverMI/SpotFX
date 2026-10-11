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


# ── Playback context, read only (Show Playlists, phase 0) ────────────────────
# SPECTRA's Show Playlists key a program to the Spotify playlist he plays
# (spectra/services/show_playlists.py). These two reads let it NAME a
# context and offer the ones he has recently played. Neither starts, queues
# or changes playback.

def _context_type(uri: str) -> str:
    parts = (uri or "").split(":")
    return parts[1] if len(parts) >= 3 and parts[0] == "spotify" else ""


@router.get("/context-name")
async def get_context_name(uri: str):
    """The friendly name of a Spotify context URI ("spotify:playlist:…",
    an album, an artist). Read from what this process already observed,
    else resolved from Spotify (read-only, cached). `name` is "" when it
    cannot be resolved — never a guess."""
    import asyncio

    from api import spotify_client
    uri = (uri or "").strip()
    ctype = _context_type(uri)
    name = (state.observed_context_uris or {}).get(uri, "") if uri else ""
    if not name and ctype and spotify_client.is_authenticated():
        try:
            sp = spotify_client.get_spotify()
            name = await asyncio.to_thread(spotify_client._resolve_context_name, sp, uri, ctype)
        except Exception:                                # noqa: BLE001
            name = ""
    return {"uri": uri, "type": ctype, "name": name or ""}


@router.get("/contexts")
async def get_contexts():
    """The context playing now and the ones observed recently (newest
    last), with their names — the Show Playlists builder's "from Spotify"
    picker. Unlike /api/setlists/discoverable this keeps contexts a Set
    List already tracks."""
    track = state.current_track
    playing = None
    if track is not None and track.context_uri:
        playing = {"context_uri": track.context_uri, "type": track.context_type,
                   "name": (state.observed_context_uris or {}).get(track.context_uri, "")}
    recent = [{"context_uri": u, "type": _context_type(u), "name": n}
              for u, n in (state.observed_context_uris or {}).items() if u]
    return {"playing": playing, "recent": recent}
