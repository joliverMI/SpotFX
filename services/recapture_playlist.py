"""
SpotFX — Recapture playlist management.

Builds and trims a Spotify playlist of songs that need (re)capture, so you can
start playback in the evening and walk away while SpotFX captures audio shapes
and pins offsets. As each song's capture succeeds, the runtime removes it from
the playlist via remove_track().

Selection modes:
  - "all"           — every profile (first-run bootstrap)
  - "missing_shape" — profiles without an audio_shape_file
  - "needs_recapture" — profiles flagged needs_recapture=True (future)
"""
from __future__ import annotations
import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

import spotipy

from api.spotify_client import get_spotify
from config import BASE_DIR
from services import profile_manager

logger = logging.getLogger(__name__)

PLAYLIST_NAME = "SpotFX Recapture"
PLAYLIST_DESCRIPTION = "Auto-managed by SpotFX. Songs are removed as they're successfully recaptured."


def _me_id(sp: spotipy.Spotify) -> str:
    return sp.me()["id"]


def find_playlist(sp: Optional[spotipy.Spotify] = None) -> Optional[str]:
    """Return the playlist id of the existing SpotFX Recapture playlist, or None.

    Pages through every one of his playlists, 50 at a time — callers that run
    once per captured song go through `_cached_playlist_id` instead. Whatever
    this finds (including "not there") is recorded in that cache."""
    sp = sp or get_spotify()
    user_id = _me_id(sp)
    offset = 0
    found: Optional[str] = None
    while True:
        page = sp.user_playlists(user_id, limit=50, offset=offset)
        for pl in page.get("items", []):
            if pl.get("name") == PLAYLIST_NAME and (pl.get("owner") or {}).get("id") == user_id:
                found = pl["id"]
                break
        if found or not page.get("next"):
            break
        offset += len(page.get("items", []))
    _remember_playlist_id(found)
    return found


# The playlist's id does not change once it exists, so remove_track() — run
# for every captured song — must not page through all his playlists to
# re-learn it each time (report §7.1). A found id is trusted for
# _PLAYLIST_FOUND_TTL_S; "not there" only for _PLAYLIST_ABSENT_TTL_S, because
# the playlist is normally built by scripts/recapture_playlist.py, a separate
# process whose creation this cache cannot hear about. In this process,
# find_playlist(), find_or_create_playlist() and a failed removal update it
# at once.
_PLAYLIST_FOUND_TTL_S = 1800.0
_PLAYLIST_ABSENT_TTL_S = 120.0
_playlist_cache_lock = threading.Lock()
_playlist_cache: Optional[tuple[Optional[str], float]] = None  # (id or None, monotonic expiry)


def _remember_playlist_id(pid: Optional[str]) -> None:
    global _playlist_cache
    ttl = _PLAYLIST_FOUND_TTL_S if pid else _PLAYLIST_ABSENT_TTL_S
    with _playlist_cache_lock:
        _playlist_cache = (pid, time.monotonic() + ttl)


def _forget_playlist_id() -> None:
    global _playlist_cache
    with _playlist_cache_lock:
        _playlist_cache = None


def _cached_playlist_id(sp: spotipy.Spotify, trust_absent: bool = True) -> Optional[str]:
    """find_playlist(), answered from the cache while it is fresh. With
    trust_absent=False a cached "not there" is looked up again — a caller
    about to CREATE the playlist must not make a duplicate on a stale no."""
    with _playlist_cache_lock:
        cached = _playlist_cache
    if (cached is not None and time.monotonic() < cached[1]
            and (cached[0] or trust_absent)):
        return cached[0]
    return find_playlist(sp)


def find_or_create_playlist(sp: Optional[spotipy.Spotify] = None) -> str:
    """Return the playlist id, creating an empty private playlist if missing."""
    sp = sp or get_spotify()
    pid = _cached_playlist_id(sp, trust_absent=False)
    if pid:
        return pid
    user_id = _me_id(sp)
    pl = sp.user_playlist_create(
        user=user_id,
        name=PLAYLIST_NAME,
        public=False,
        description=PLAYLIST_DESCRIPTION,
    )
    logger.info("Created %s (id=%s)", PLAYLIST_NAME, pl["id"])
    _remember_playlist_id(pl["id"])
    return pl["id"]


AUDIO_SHAPES_DIR = BASE_DIR / "storage" / "audio_shapes"


def _needs_recapture_uris() -> list[tuple[str, int]]:
    """
    Scan audio_shapes sidecar JSONs for needs_recapture=True.
    Returns (spotify_uri, flag_count) tuples sorted by flag_count descending
    so chronic offenders are played first.
    """
    results: list[tuple[str, int]] = []
    for path in AUDIO_SHAPES_DIR.glob("*.json"):
        if ".bak." in path.name or ".librosa." in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data.get("needs_recapture"):
            continue
        uri = data.get("spotify_uri", "")
        if uri.startswith("spotify:track:"):
            results.append((uri, data.get("needs_recapture_flag_count", 0)))
    results.sort(key=lambda t: t[1], reverse=True)
    return results


def select_uris(mode: str = "all") -> list[str]:
    """Return Spotify track URIs for profiles matching the selection mode."""
    if mode == "needs_recapture":
        return [uri for uri, _count in _needs_recapture_uris()]

    profiles = profile_manager.list_profiles()
    out: list[str] = []
    for p in profiles:
        uri = p.get("spotify_uri") or ""
        if not uri.startswith("spotify:track:"):
            continue
        if mode == "missing_shape" and p.get("has_audio_shape"):
            continue
        out.append(uri)
    # de-dup, preserve order
    seen: set[str] = set()
    deduped = []
    for u in out:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


def _replace_tracks(sp: spotipy.Spotify, playlist_id: str, uris: list[str]) -> None:
    """Replace the playlist contents with `uris`. Spotify caps add/replace at 100/call."""
    if not uris:
        sp.playlist_replace_items(playlist_id, [])
        return
    sp.playlist_replace_items(playlist_id, uris[:100])
    for i in range(100, len(uris), 100):
        sp.playlist_add_items(playlist_id, uris[i : i + 100])


def build(mode: str = "all") -> dict:
    """Create/refresh the recapture playlist with songs matching `mode`."""
    sp = get_spotify()
    pid = find_or_create_playlist(sp)
    uris = select_uris(mode)
    _replace_tracks(sp, pid, uris)
    logger.info("Recapture playlist refreshed: mode=%s tracks=%d id=%s", mode, len(uris), pid)
    return {"playlist_id": pid, "mode": mode, "track_count": len(uris)}


def remove_track(spotify_uri: str) -> bool:
    """Remove a single track from the recapture playlist. Returns True if removed.

    BLOCKING (Spotify HTTP): an async caller runs it with asyncio.to_thread."""
    if not spotify_uri.startswith("spotify:track:"):
        return False
    sp = get_spotify()
    pid = _cached_playlist_id(sp)
    if not pid:
        return False
    try:
        sp.playlist_remove_all_occurrences_of_items(pid, [spotify_uri])
        logger.info("Removed %s from recapture playlist", spotify_uri)
        return True
    except Exception as exc:
        # The cached id may be the reason (the playlist was deleted and
        # rebuilt elsewhere); look it up afresh next time.
        _forget_playlist_id()
        logger.warning("Failed to remove %s from recapture playlist: %s", spotify_uri, exc)
        return False


def list_devices() -> list[dict]:
    """Return available Spotify Connect devices for picking a playback target."""
    sp = get_spotify()
    return (sp.devices() or {}).get("devices", []) or []


def start_playback(playlist_id: Optional[str] = None, device_name: Optional[str] = None) -> dict:
    """
    Start playback of the recapture playlist on the named device (or current active device).
    Returns a dict with the device used.
    """
    sp = get_spotify()
    pid = playlist_id or find_or_create_playlist(sp)
    device_id = None
    if device_name:
        for d in list_devices():
            if d.get("name", "").lower() == device_name.lower():
                device_id = d.get("id")
                break
        if not device_id:
            raise RuntimeError(f"No Spotify Connect device named {device_name!r} is available.")
    sp.start_playback(device_id=device_id, context_uri=f"spotify:playlist:{pid}")
    return {"playlist_id": pid, "device_id": device_id, "device_name": device_name or "(current)"}
