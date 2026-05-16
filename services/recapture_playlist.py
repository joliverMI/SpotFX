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
    """Return the playlist id of the existing SpotFX Recapture playlist, or None."""
    sp = sp or get_spotify()
    user_id = _me_id(sp)
    offset = 0
    while True:
        page = sp.user_playlists(user_id, limit=50, offset=offset)
        for pl in page.get("items", []):
            if pl.get("name") == PLAYLIST_NAME and (pl.get("owner") or {}).get("id") == user_id:
                return pl["id"]
        if not page.get("next"):
            return None
        offset += len(page.get("items", []))


def find_or_create_playlist(sp: Optional[spotipy.Spotify] = None) -> str:
    """Return the playlist id, creating an empty private playlist if missing."""
    sp = sp or get_spotify()
    pid = find_playlist(sp)
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
    """Remove a single track from the recapture playlist. Returns True if removed."""
    if not spotify_uri.startswith("spotify:track:"):
        return False
    sp = get_spotify()
    pid = find_playlist(sp)
    if not pid:
        return False
    try:
        sp.playlist_remove_all_occurrences_of_items(pid, [spotify_uri])
        logger.info("Removed %s from recapture playlist", spotify_uri)
        return True
    except Exception as exc:
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
