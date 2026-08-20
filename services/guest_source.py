"""
SpotFX — Guest source (Snapcast Guest / AirPlay streams).

When someone casts to the librespot "Serenity Guest" Connect device or the
"Serenity" AirPlay target, playback belongs to THEIR account — the Spotify Web
API exposes nothing about it, so the normal Spotify poller reports "nothing
playing" and the whole engine sits idle while music fills the house.

This service polls the local snapserver's JSON-RPC (Server.GetStatus). When a
watched guest stream is `playing` and holds at least one group, it synthesizes
a `guest:` SpotifyTrackInfo from the stream's scraped metadata (title/duration
when snapserver could parse them) and loads a blank in-memory SongProfile into
the trigger engine. A blank profile has zero triggers, so the engine's
existing triggerless machinery takes over: it resolves the default triggerless
TrainingProfile ("Dinner Party") and fires its start/scene/flare events on
intervals — simple triggerless lighting for guest playback, no per-song
timelines. A title change in the stream metadata counts as a new song and
regenerates the interval triggers (start event re-fires).

This firing goes through the SAME run() loop that legacy per-song profile
firing does, gated by the SAME settings.legacy_trigger_engine_enabled flag
(engine retired 2026-08-20). With that flag at its retired-default False,
guest playback still loads its blank profile (state stays correct) but the
interval triggers above never actually fire — guest sessions go quiet along
with the rest of the legacy engine. Named, not silently lost: see the PR
that retired the loop for the reasoning. A SPECTRA-native guest-playback
light source would be a separate, deliberate follow-up, not a side effect
of flipping the flag back on (which restores full legacy firing, including
this).

Ownership rules:
  - Javi's real Spotify always wins: while a real (non-guest) track is
    playing, this service stands down and never touches state.
  - api/spotify_client.fetch_current_track has the mirror-image guards: a
    "nothing playing" or paused-Spotify answer does NOT clobber a guest-owned
    current_track; only an actively PLAYING real track takes over.
  - Guest tracks are never persisted: main._on_state_update short-circuits
    for guest: URIs, so no SongProfile files are auto-created and no
    audio-shape capture starts (guest artist metadata is unreliable, and
    capture would write junk shapes).

Snapserver gotcha (see Homelab CLAUDE.md): its HTTP server mishandles
keep-alive on POST /jsonrpc — every second request on a reused connection
returns an empty body. A fresh httpx client per poll = a fresh connection per
request, which sidesteps this deterministically.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Optional

import httpx

from config import settings
from models.state import state, SpotifyTrackInfo

logger = logging.getLogger(__name__)

GUEST_URI_PREFIX = "guest:"


def is_guest_uri(uri: Optional[str]) -> bool:
    return bool(uri) and uri.startswith(GUEST_URI_PREFIX)


async def _get_server_status() -> Optional[dict]:
    """One Server.GetStatus call on a fresh connection. None on any failure."""
    payload = {"jsonrpc": "2.0", "method": "Server.GetStatus", "id": 1}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(settings.snapcast_rpc_url, json=payload)
            r.raise_for_status()
            return r.json()["result"]["server"]
    except Exception as exc:
        logger.debug("guest source: snapcast poll failed: %s", exc)
        return None


def _pick_active_guest(server: dict) -> Optional[tuple[str, dict]]:
    """First watched stream that is playing AND has ≥1 group routed to it."""
    streams = {s.get("id"): s for s in server.get("streams", [])}
    group_counts: dict[str, int] = {}
    for g in server.get("groups", []):
        sid = g.get("stream_id")
        group_counts[sid] = group_counts.get(sid, 0) + 1
    for sid in settings.guest_streams:
        s = streams.get(sid)
        if s and s.get("status") == "playing" and group_counts.get(sid, 0) > 0:
            return sid, s
    return None


async def _broadcast() -> None:
    try:
        from services.websocket_manager import ws_manager
        await ws_manager.broadcast_state(state)
    except Exception:
        pass


async def _release(reason: str) -> None:
    """Drop guest ownership of playback state (no-op if we don't own it)."""
    cur = state.current_track
    if cur is not None and is_guest_uri(cur.spotify_uri):
        logger.info("guest source: releasing playback state (%s)", reason)
        state.current_track = None
        state.on_target_device = False
        await _broadcast()


async def _load_guest_track(sid: str, uri: str, title: str, artist: str,
                            duration_ms: int) -> None:
    """Take ownership: synthesize the track + blank profile, arm the engine."""
    from main import engine  # deferred import, same pattern as routers
    from models.song_profile import SongProfile

    device = "Serenity Guest" if sid == "Guest" else sid
    info = SpotifyTrackInfo(
        spotify_uri=uri,
        title=title,
        artist=artist or device,
        duration_ms=duration_ms,
        progress_ms=0,
        is_playing=True,
        fetched_at=time.monotonic(),
        device_name=device,
        genres=[],
    )
    state.current_track = info
    state.on_target_device = True  # engine gate; device check is meaningless here
    state.last_activity_time = time.monotonic()

    # In-memory only — never saved, so no junk in storage/profiles. Zero
    # triggers → the engine's triggerless path resolves the default
    # TrainingProfile and generates interval triggers from duration_ms.
    profile = SongProfile(
        spotify_uri=uri, title=title, artist=info.artist, duration_ms=duration_ms,
    )
    engine.load_profile(profile)
    logger.info(
        "guest source: '%s' playing on %s → triggerless (%s — %s, %d ms)",
        sid, device, info.artist, title, duration_ms,
    )
    await _broadcast()


async def _tick() -> None:
    cur = state.current_track
    real_playing = (
        cur is not None and not is_guest_uri(cur.spotify_uri) and cur.is_playing
    )
    if real_playing:
        # Javi's Spotify owns the room (a playing real track already replaced
        # any guest track via fetch_current_track). Nothing to do.
        return

    server = await _get_server_status()
    if server is None:
        return  # snapserver unreachable — keep current state, retry next poll

    active = _pick_active_guest(server)
    if active is None:
        await _release("guest stream idle or groups moved away")
        return

    sid, stream = active
    md = (stream.get("properties") or {}).get("metadata") or {}
    title = (md.get("title") or "").strip() or f"{sid} stream"
    artist = (md.get("artist") or "").strip()
    try:
        duration_ms = int(float(md.get("duration") or 0) * 1000)
    except (TypeError, ValueError):
        duration_ms = 0
    if duration_ms <= 0:
        duration_ms = settings.guest_default_duration_ms

    key = f"{sid}|{title}|{duration_ms}"
    uri = GUEST_URI_PREFIX + hashlib.md5(key.encode()).hexdigest()[:12]

    if cur is not None and is_guest_uri(cur.spotify_uri) and cur.spotify_uri == uri:
        return  # same guest song, progress interpolates on its own
    await _load_guest_track(sid, uri, title, artist, duration_ms)


async def polling_loop() -> None:
    """Background task launched from main.lifespan."""
    if not settings.guest_source_enabled:
        logger.info("guest source: disabled (guest_source_enabled=false)")
        return
    logger.info(
        "guest source: watching snapcast streams %s every %.0fs (%s)",
        settings.guest_streams, settings.guest_poll_interval_s,
        settings.snapcast_rpc_url,
    )
    while True:
        try:
            await _tick()
        except Exception as exc:
            logger.error("guest source: tick failed: %r", exc)
        await asyncio.sleep(settings.guest_poll_interval_s)
