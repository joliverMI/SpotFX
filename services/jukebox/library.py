"""
SpotFX — the Jukebox's view of HIS LIBRARY (data/jukebox-plan/report.md §7.2,
phase 2 PR 2.2): the songs SpotFX has played before, searchable by title and
artist, so a guest's search shows "Ready: the lights already know these"
before anything from Spotify; and whether a song is KNOWN — its audio shape
is captured, so the lights follow it from the first beat.

THE LIBRARY is his profile store, storage/profiles/*.json (every song SpotFX
has played gets one, with its title, artist and `spotify_uri`), read as plain
dicts — the same read-only scan SPECTRA's song_library makes on its side. Only
real `spotify:track:` URIs are listed. ~1,600 files is about a second to
parse, so the index is built once and rebuilt only when the directory's mtime
moves (a profile added or removed) or it is older than REBUILD_AFTER_S (a
title edited in place).

KNOWN is the audio-shape index's own answer (services/audio_analyzer — the
same lookup a capture makes), never a second definition.

EVERYTHING HERE BLOCKS (disk reads): call it through asyncio.to_thread, never
on the event loop that runs the music.
"""
from __future__ import annotations

import json
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import BASE_DIR

PROFILES_DIR = BASE_DIR / "storage" / "profiles"
REBUILD_AFTER_S = 300.0


@dataclass(frozen=True)
class Song:
    uri: str
    title: str
    artist: str
    key: str            # folded "title artist", for matching


_lock = threading.Lock()
_index: Optional[list[Song]] = None
_built_at = 0.0
_built_mtime: Optional[int] = None


def fold(text: str) -> str:
    """Lowercase, accents off ("Apagón" matches "apagon"), punctuation to spaces."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join("".join(c if c.isalnum() else " " for c in t).split())


def _mtime() -> Optional[int]:
    try:
        return PROFILES_DIR.stat().st_mtime_ns
    except OSError:
        return None


def _build() -> list[Song]:
    seen: set[str] = set()
    out: list[Song] = []
    try:
        paths = sorted(PROFILES_DIR.glob("*.json"))
    except OSError:
        paths = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            continue
        uri = data.get("spotify_uri") or ""
        if not isinstance(uri, str) or not uri.startswith("spotify:track:") or uri in seen:
            continue
        seen.add(uri)
        title, artist = str(data.get("title") or ""), str(data.get("artist") or "")
        out.append(Song(uri, title, artist, fold(f"{title} {artist}")))
    return out


def index() -> list[Song]:
    global _index, _built_at, _built_mtime
    with _lock:
        mtime = _mtime()
        if (_index is None or mtime != _built_mtime
                or time.monotonic() - _built_at > REBUILD_AFTER_S):
            _index, _built_at, _built_mtime = _build(), time.monotonic(), mtime
        return _index


def search(query: str, limit: int = 5) -> list[Song]:
    """His songs whose title and artist hold every word of the query
    (accents and case ignored), best first: a title that starts with the
    query, then a title holding it, then the rest; ties by title."""
    words = fold(query).split()
    if not words:
        return []
    q = " ".join(words)
    hits = [s for s in index() if all(w in s.key for w in words)]

    def rank(s: Song) -> tuple:
        t = fold(s.title)
        return (0 if t.startswith(q) else 1 if q in t else 2, t)
    return sorted(hits, key=rank)[:limit]


def known(uri: str) -> bool:
    """The lights already know this song: its audio shape is captured."""
    from services import audio_analyzer
    try:
        return audio_analyzer._shape_filename_for(uri) is not None
    except Exception:                                              # noqa: BLE001
        return False


def reset() -> None:
    """Forget the index (tests repoint PROFILES_DIR)."""
    global _index, _built_mtime
    with _lock:
        _index, _built_mtime = None, None
