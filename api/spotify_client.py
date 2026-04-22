"""
SpotFX — Spotify Web API client (OAuth via Spotipy).

Handles:
  - OAuth token acquisition and refresh
  - Fetching currently playing track on the configured device
  - Adaptive polling intervals based on playback state
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Optional

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from config import settings, PROFILES_DIR
from models.state import state, SpotifyTrackInfo, PrevTrackSnapshot
from api.lastfm import fetch_lastfm_genres

logger = logging.getLogger(__name__)

SCOPES = "user-read-playback-state user-read-currently-playing"

_sp: Optional[spotipy.Spotify] = None
_artist_genre_cache: dict[str, list[str]] = {}
_burst_until: float = 0.0  # monotonic timestamp until which to use burst poll rate


def _fetch_artist_genres(sp: spotipy.Spotify, artist_id: str, artist_name: str = "") -> list[str]:
    """Return cached genre list for an artist, using Spotify then Last.fm as fallback."""
    if artist_id in _artist_genre_cache:
        return _artist_genre_cache[artist_id]
    try:
        genres = sp.artist(artist_id).get("genres", [])
    except Exception:
        genres = []
    if not genres and artist_name:
        genres = fetch_lastfm_genres(artist_name)
    _artist_genre_cache[artist_id] = genres
    return genres


def _make_auth_manager() -> SpotifyOAuth:
    return SpotifyOAuth(
        client_id=settings.spotipy_client_id,
        client_secret=settings.spotipy_client_secret,
        redirect_uri=settings.spotipy_redirect_uri,
        scope=SCOPES,
        cache_path=str(PROFILES_DIR.parent / ".spotify_token_cache"),
        open_browser=False,
    )


def get_spotify() -> spotipy.Spotify:
    """Return (or create) the authenticated Spotipy client."""
    global _sp
    if _sp is None:
        _sp = spotipy.Spotify(auth_manager=_make_auth_manager())
    return _sp


def is_authenticated() -> bool:
    """Return True if a cached token exists and is usable."""
    try:
        token = _make_auth_manager().get_cached_token()
        return bool(token)
    except Exception:
        return False


def _poll_interval_ms() -> int:
    """
    Calculate how long to wait before the next Spotify poll.

    Rules:
    - If within the song-start burst window: use poll_interval_end_song_ms.
    - If we're near the end of a song (within poll_end_song_burst_duration_ms),
      use poll_interval_end_song_ms (max 500 ms).
    - If idle for >10 min: poll_interval_idle_ms.
    - If paused: poll_interval_paused_ms.
    - Otherwise (playing): poll_interval_playing_ms.
    """
    if time.monotonic() < _burst_until:
        return settings.poll_interval_end_song_ms

    track = state.current_track
    if track and track.is_playing:
        remaining_ms = track.duration_ms - track.interpolated_progress_ms()
        burst_window = settings.poll_end_song_burst_duration_ms
        if remaining_ms <= burst_window:
            return settings.poll_interval_end_song_ms

    idle_seconds = time.monotonic() - state.last_activity_time
    if idle_seconds > 600:  # 10 minutes
        return settings.poll_interval_idle_ms

    if track and not track.is_playing:
        return settings.poll_interval_paused_ms

    return settings.poll_interval_playing_ms


def fetch_current_track() -> Optional[SpotifyTrackInfo]:
    """
    Poll Spotify for the currently playing track on the configured device.
    Updates state.current_track in place.
    Returns the new TrackInfo or None if nothing is playing.
    """
    try:
        sp = get_spotify()
        data = sp.current_playback()
    except Exception as exc:
        logger.error("Spotify poll failed: %s", exc)
        return None

    if not data or not data.get("item"):
        state.current_track = None
        state.on_target_device = False
        return None

    device_name = (data.get("device") or {}).get("name", "")
    state.on_target_device = (
        device_name.lower() == settings.spotify_device_name.lower()
        and bool(data.get("is_playing"))
    )

    item = data["item"]
    first_artist = item["artists"][0] if item.get("artists") else {}
    artist_id   = first_artist.get("id", "")
    artist_name = first_artist.get("name", "")
    genres = _fetch_artist_genres(sp, artist_id, artist_name) if artist_id else []
    info = SpotifyTrackInfo(
        spotify_uri=item["uri"],
        title=item["name"],
        artist=", ".join(a["name"] for a in item["artists"]),
        duration_ms=item["duration_ms"],
        progress_ms=data["progress_ms"] or 0,
        is_playing=data["is_playing"],
        fetched_at=time.monotonic(),
        device_name=device_name,
        genres=genres,
    )
    global _burst_until
    old = state.current_track
    old_uri = old.spotify_uri if old else None
    if info.spotify_uri != old_uri:
        if old is not None:
            state.last_ended_track = PrevTrackSnapshot(
                spotify_uri=old.spotify_uri,
                genres=list(old.genres or []),
                duration_ms=old.duration_ms,
                last_known_progress_ms=old.interpolated_progress_ms(),
            )
            logger.info(
                "URI change: %s → %s (prev progress=%dms/%dms, playing=%s)",
                old_uri, info.spotify_uri,
                state.last_ended_track.last_known_progress_ms,
                old.duration_ms, info.is_playing,
            )
        if info.is_playing:
            _burst_until = time.monotonic() + settings.poll_start_burst_duration_ms / 1000.0
            logger.debug("New song detected — burst polling for %dms", settings.poll_start_burst_duration_ms)
    state.current_track = info
    state.last_poll_time = time.monotonic()
    if info.is_playing:
        state.last_activity_time = time.monotonic()
    return info


async def polling_loop(broadcast_fn) -> None:
    """
    Async polling loop.  Calls fetch_current_track() at the adaptive interval,
    then calls broadcast_fn(state) so the WebSocket layer can push updates.

    Waits quietly if Spotify is not yet authenticated — the /auth/login flow
    will set the cached token and reset _sp, at which point polling resumes.
    """
    logger.info("Spotify polling loop started.")
    while True:
        if not is_authenticated():
            logger.info(
                "Spotify not authenticated — visit http://127.0.0.1:8000/api/spotify/login"
            )
            await asyncio.sleep(5)
            continue

        fetch_current_track()
        await broadcast_fn(state)
        interval_ms = _poll_interval_ms()
        await asyncio.sleep(interval_ms / 1000)
