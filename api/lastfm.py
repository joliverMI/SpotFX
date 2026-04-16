"""
SpotFX — Last.fm genre lookup utility.

Shared by spotify_client.py (fallback genres) and ledfx_song_client.py
(primary genres when Spotify API is not in use).
"""
from __future__ import annotations
import json
import logging
import urllib.parse
import urllib.request

from config import settings

logger = logging.getLogger(__name__)

_LASTFM_JUNK = {
    "seen live", "favourite", "favorites", "loved", "love", "owned",
    "under 2000 listeners", "my favorites", "beautiful", "awesome",
    "amazing", "great", "good", "cool", "best", "classic",
}

_genre_cache: dict[str, list[str]] = {}


def fetch_lastfm_genres(artist_name: str) -> list[str]:
    """Fetch genre tags from Last.fm for an artist. Returns up to 5 tags."""
    if not settings.lastfm_api_key or not artist_name:
        return []
    if artist_name in _genre_cache:
        return _genre_cache[artist_name]
    url = (
        "http://ws.audioscrobbler.com/2.0/"
        f"?method=artist.getTopTags"
        f"&artist={urllib.parse.quote(artist_name)}"
        f"&api_key={settings.lastfm_api_key}"
        f"&format=json"
    )
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        tags = data.get("toptags", {}).get("tag", [])
        genres: list[str] = []
        for tag in tags:
            name = tag.get("name", "").lower().strip()
            count = int(tag.get("count", 0))
            if count < 10:
                break
            if name and name not in _LASTFM_JUNK:
                genres.append(name)
            if len(genres) >= 5:
                break
        _genre_cache[artist_name] = genres
        return genres
    except Exception:
        return []
