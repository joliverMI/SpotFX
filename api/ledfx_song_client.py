"""
SpotFX — LedFX song source client.

Subscribes to LedFX's song_detected WebSocket event and drives the same
broadcast flow as spotify_client.polling_loop, with no Spotify API required.

Track changes arrive in ~1s (librespot onevent) vs 500ms–30s polling.
Genres are fetched from Last.fm since LedFX doesn't carry genre data.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from typing import Callable, Awaitable

from config import settings
from models.state import state, SpotifyTrackInfo, PrevTrackSnapshot
from api.lastfm import fetch_lastfm_genres

logger = logging.getLogger(__name__)

_RETRY_DELAY_S = 5
_event_data_logged = False  # log raw event_data once to confirm field shape


def _make_uri(artist: str, title: str) -> str:
    """Stable profile key for LedFX-sourced tracks."""
    return f"ledfx:{artist.lower().strip()}:{title.lower().strip()}"


async def polling_loop(broadcast_fn: Callable[..., Awaitable[None]]) -> None:
    """
    Event-driven loop that mirrors spotify_client.polling_loop's signature.

    Connects to LedFX WebSocket, subscribes to song_detected events, and
    calls broadcast_fn(state) on each new track — exactly as the Spotify
    polling loop does.
    """
    import websockets

    ws_url = (
        f"ws://{settings.ledfx_host.removeprefix('http://').removeprefix('https://')}"
        f":{settings.ledfx_port}/api/websocket"
    )

    logger.info("LedFX song source: connecting to %s", ws_url)

    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=20) as ws:
                await ws.send(json.dumps({
                    "id": 1,
                    "type": "subscribe_event",
                    "event_type": "song_detected",
                }))
                logger.info("LedFX song source: subscribed to song_detected events")

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue

                    if msg.get("type") != "event" or msg.get("event_type") != "song_detected":
                        continue

                    await _handle_event(msg, broadcast_fn)

        except Exception as exc:
            logger.warning("LedFX song source: connection lost (%s), retrying in %ds", exc, _RETRY_DELAY_S)
            await asyncio.sleep(_RETRY_DELAY_S)


async def _handle_event(
    msg: dict,
    broadcast_fn: Callable[..., Awaitable[None]],
) -> None:
    global _event_data_logged
    # LedFX wraps event payload in event_data; fall back to flat msg for older versions
    data = msg.get("event_data", msg)
    if not _event_data_logged:
        logger.debug("LedFX song_detected event_data: %s", data)
        _event_data_logged = True

    title = data.get("title", "")
    artist = data.get("artist", "")
    if not title and not artist:
        return

    duration_s = data.get("duration") or 0
    duration_ms = int(duration_s * 1000) if duration_s else 0
    playing = data.get("playing", True)
    uri = _make_uri(artist, title)

    # Snapshot the outgoing track before overwriting — used by Genre Blending.
    old = state.current_track
    if old is not None and old.spotify_uri != uri:
        implied_progress_ms = old.interpolated_progress_ms()
        if old.duration_ms:
            implied_progress_ms = min(implied_progress_ms, old.duration_ms)
        state.last_ended_track = PrevTrackSnapshot(
            spotify_uri=old.spotify_uri,
            genres=list(old.genres or []),
            duration_ms=old.duration_ms,
            last_known_progress_ms=implied_progress_ms,
        )

    # Broadcast immediately with no genres so the UI updates without delay
    track = SpotifyTrackInfo(
        spotify_uri=uri,
        title=title,
        artist=artist,
        duration_ms=duration_ms,
        progress_ms=0,
        is_playing=playing,
        fetched_at=time.monotonic(),
        device_name="LedFX",
        genres=[],
    )
    state.current_track = track
    state.on_target_device = True  # device check is irrelevant for LedFX source
    logger.info("LedFX song source: %s — %s", artist, title)
    await broadcast_fn(state)

    # Fetch genres in the background; do a second broadcast if we get any
    if artist:
        asyncio.create_task(_fetch_and_update_genres(uri, artist, broadcast_fn))


async def _fetch_and_update_genres(
    uri: str,
    artist: str,
    broadcast_fn: Callable[..., Awaitable[None]],
) -> None:
    genres = await asyncio.get_event_loop().run_in_executor(
        None, fetch_lastfm_genres, artist
    )
    # Only update if this track is still playing (user hasn't skipped again)
    if genres and state.current_track and state.current_track.spotify_uri == uri:
        state.current_track.genres = genres
        # Let the engine reconsider genre blending now that we have genres.
        try:
            from main import engine as _engine
            _engine.reconsider_genre_blend()
        except Exception as exc:
            logger.debug("reconsider_genre_blend skipped: %s", exc)
        await broadcast_fn(state)
