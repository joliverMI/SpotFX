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

SCOPES = (
    "user-read-playback-state user-read-currently-playing "
    "user-modify-playback-state "
    "playlist-read-private playlist-modify-private playlist-modify-public"
)

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
    - If we're near the end of a song (within max(poll_end_song_burst_duration_ms,
      pretransition_burst_window_ms)), use poll_interval_end_song_ms.
      The widened window covers Spotify-side mix transitions where the URI flip
      happens earlier than a natural song end.
    - If idle for >10 min: poll_interval_idle_ms.
    - If paused: poll_interval_paused_ms.
    - Otherwise (playing): poll_interval_playing_ms.
    """
    if time.monotonic() < _burst_until:
        return settings.poll_interval_end_song_ms

    track = state.current_track
    if track and track.is_playing:
        remaining_ms = track.duration_ms - track.interpolated_progress_ms()
        burst_window = max(
            settings.poll_end_song_burst_duration_ms,
            settings.pretransition_burst_window_ms,
        )
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
        # Stamp the progress clock NOW — before the genre lookup below, which
        # can add hundreds of ms (sp.artist + Last.fm fallback) on the first
        # poll of a new artist. Stamping after it made interpolated progress
        # run behind by that amount until the next poll — a visible playhead
        # (and trigger-timing) stutter right at song start.
        t_fetched = time.monotonic()
    except Exception as exc:
        logger.error("Spotify poll failed: %s", exc)
        return None

    if not data or not data.get("item"):
        state.current_track = None
        state.on_target_device = False
        return None

    device_name = (data.get("device") or {}).get("name", "")
    state.on_target_device = (
        device_name.lower() in (n.lower() for n in settings.spotify_device_names)
        and bool(data.get("is_playing"))
    )

    item = data["item"]
    first_artist = item["artists"][0] if item.get("artists") else {}
    artist_id   = first_artist.get("id", "")
    artist_name = first_artist.get("name", "")
    genres = _fetch_artist_genres(sp, artist_id, artist_name) if artist_id else []
    ctx = data.get("context") or {}
    context_uri = ctx.get("uri", "") or ""
    context_type = ctx.get("type", "") or ""
    info = SpotifyTrackInfo(
        spotify_uri=item["uri"],
        title=item["name"],
        artist=", ".join(a["name"] for a in item["artists"]),
        duration_ms=item["duration_ms"],
        progress_ms=data["progress_ms"] or 0,
        is_playing=data["is_playing"],
        fetched_at=t_fetched,
        device_name=device_name,
        genres=genres,
        context_uri=context_uri,
        context_type=context_type,
    )
    global _burst_until
    old = state.current_track
    old_uri = old.spotify_uri if old else None
    old_context_uri = old.context_uri if old else ""
    if info.spotify_uri != old_uri:
        if old is not None:
            state.last_ended_track = PrevTrackSnapshot(
                spotify_uri=old.spotify_uri,
                genres=list(old.genres or []),
                duration_ms=old.duration_ms,
                last_known_progress_ms=old.interpolated_progress_ms(),
            )
            logger.info(
                "URI change: %s → %s (prev progress=%dms/%dms, playing=%s, context=%s)",
                old_uri, info.spotify_uri,
                state.last_ended_track.last_known_progress_ms,
                old.duration_ms, info.is_playing, info.context_uri or "-",
            )
        if info.is_playing:
            _burst_until = time.monotonic() + settings.poll_start_burst_duration_ms / 1000.0
            logger.debug("New song detected — burst polling for %dms", settings.poll_start_burst_duration_ms)
        # Refresh queue + apply Set List context overrides on URI change.
        try:
            _refresh_queue(sp)
        except Exception as exc:
            logger.debug("Queue fetch failed (non-fatal): %s", exc)
    state.current_track = info
    state.last_poll_time = time.monotonic()
    if info.is_playing:
        state.last_activity_time = time.monotonic()

    # Track observed context URIs so the Set List page can offer them as
    # discoverable. Resolve the friendly name lazily.
    if context_uri:
        if context_uri not in state.observed_context_uris:
            state.observed_context_uris[context_uri] = _resolve_context_name(sp, context_uri, context_type)
        # bound the dict to keep memory tiny
        if len(state.observed_context_uris) > 30:
            # drop the oldest insertion
            first_key = next(iter(state.observed_context_uris))
            state.observed_context_uris.pop(first_key, None)

    # Apply or revert Set List runtime overrides whenever the context changes.
    if info.spotify_uri != old_uri or info.context_uri != old_context_uri:
        try:
            from services import setlist_runtime
            setlist_runtime.apply_for_context(info.context_uri)
        except Exception as exc:
            logger.debug("setlist_runtime.apply_for_context failed: %s", exc)

    return info


# ── Queue + context helpers ──────────────────────────────────────────────────

_context_name_cache: dict[str, str] = {}


def _refresh_queue(sp: spotipy.Spotify) -> None:
    """Read /me/player/queue and populate state.next_track_*. Cheap; only on URI change."""
    try:
        q = sp.queue() or {}
    except Exception as exc:
        logger.debug("Spotify queue fetch failed: %s", exc)
        return
    queue_items = q.get("queue") or []
    if not queue_items:
        state.next_track_uri = ""
        state.next_track_title = ""
        return
    nxt = queue_items[0]
    state.next_track_uri = nxt.get("uri", "") or ""
    title = nxt.get("name", "") or ""
    artists = nxt.get("artists") or []
    artist_str = ", ".join(a.get("name", "") for a in artists)
    state.next_track_title = f"{artist_str} — {title}" if artist_str else title

    # Pre-warm analyzed-trigger cache for the next track if it has librosa data
    # already. Background thread; never blocks. No-op when the song has no shape.
    if state.next_track_uri:
        try:
            import asyncio as _aio
            _aio.get_event_loop().run_in_executor(
                None,
                lambda uri=state.next_track_uri: _safe_prewarm(uri),
            )
        except Exception:
            pass


def _safe_prewarm(spotify_uri: str) -> None:
    try:
        from services import analyzed_trigger_store
        from services.librosa_service import get_analysis_by_uri
        if not get_analysis_by_uri(spotify_uri):
            return  # no shape → nothing to pre-warm
        analyzed_trigger_store.generate_for_uri(spotify_uri, save_cache=True)
        logger.info("Pre-warming analyzed-triggers cache for next: %s", spotify_uri)
    except Exception as exc:
        logger.debug("Pre-warm failed for %s: %s", spotify_uri, exc)


def _resolve_context_name(sp: spotipy.Spotify, context_uri: str, context_type: str) -> str:
    """Best-effort friendly name for a context URI. Cached per session."""
    if not context_uri:
        return ""
    if context_uri in _context_name_cache:
        return _context_name_cache[context_uri]
    name = ""
    try:
        if context_type == "playlist":
            data = sp.playlist(context_uri.split(":")[-1], fields="name") or {}
            name = data.get("name", "") or ""
        elif context_type == "album":
            data = sp.album(context_uri.split(":")[-1]) or {}
            name = data.get("name", "") or ""
        elif context_type == "artist":
            data = sp.artist(context_uri.split(":")[-1]) or {}
            name = data.get("name", "") or ""
    except Exception:
        pass
    _context_name_cache[context_uri] = name
    return name


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
