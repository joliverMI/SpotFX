"""The songs SPECTRA knows, searchable by title and artist — what a Show
Sequence's song-list Wait picks from (spectra/services/show_sequence.py).

THE SOURCE IS HIS PROFILE LIBRARY, storage/profiles/*.json: every song
SpotFX has ever played gets one, it carries the title, the artist and the
`spotify_uri` the bridge reports while it plays — exactly the identity a
song-list Wait has to compare against. Read as plain dicts, never imported
as a model (the S3 import-discipline rule), the same read-only scan
`testbed_marks._profile_index` makes. Only real `spotify:track:` URIs are
listed: a profile still keyed by a legacy `ledfx:` pseudo-URI is a song the
bridge will never report under that id, so a Wait listing it could never
be satisfied.

ONE PASS, CACHED. ~1,600 profiles / ~9 MB is ~1 s to parse, so the index is
built once (in a worker thread when called from a route) and rebuilt only
when the directory's own mtime moves (a profile added or removed) or the
cache is older than REBUILD_AFTER_S (a title edited in place).
"""
from __future__ import annotations

import json
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Optional

from spectra import config

REBUILD_AFTER_S = 300.0
DEFAULT_LIMIT = 40


@dataclass(frozen=True)
class Song:
    uri: str
    title: str
    artist: str

    def as_dict(self) -> dict:
        return {"uri": self.uri, "title": self.title, "artist": self.artist}


_lock = threading.Lock()
_index: Optional[list[Song]] = None
_built_mono: float = 0.0
_built_sig: Optional[tuple] = None


def _signature() -> Optional[tuple]:
    d = config.PROFILES_DIR
    try:
        st = d.stat()
    except OSError:
        return None
    return (str(d), st.st_mtime_ns)


def _build() -> list[Song]:
    d = config.PROFILES_DIR
    seen: dict[str, Song] = {}
    if not d.exists():
        return []
    for path in d.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        uri = data.get("spotify_uri") or ""
        if not uri.startswith("spotify:track:") or uri in seen:
            continue
        title = (data.get("title") or "").strip()
        artist = (data.get("artist") or "").strip()
        seen[uri] = Song(uri, title or uri, artist)
    return sorted(seen.values(), key=lambda s: (s.title.lower(), s.artist.lower()))


def songs() -> list[Song]:
    global _index, _built_mono, _built_sig
    with _lock:
        sig = _signature()
        stale = (_index is None or sig != _built_sig
                 or time.monotonic() - _built_mono > REBUILD_AFTER_S)
        if stale:
            _index = _build()
            _built_sig = sig
            _built_mono = time.monotonic()
        return list(_index)


def _fold(text: str) -> str:
    """Case- and accent-insensitive ("Apagón" matches "apagon")."""
    norm = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


def search(query: str = "", limit: int = DEFAULT_LIMIT) -> list[Song]:
    """Every word of the query must appear in the title or the artist.
    Title-prefix matches rank first. An empty query lists from the top."""
    words = [w for w in _fold(query).split() if w]
    out: list[tuple[int, Song]] = []
    for s in songs():
        hay = _fold(f"{s.title} {s.artist}")
        if all(w in hay for w in words):
            rank = 0 if (words and _fold(s.title).startswith(words[0])) else 1
            out.append((rank, s))
    out.sort(key=lambda r: r[0])
    return [s for _r, s in out[:max(1, limit)]]


def lookup(uri: str) -> Optional[Song]:
    return next((s for s in songs() if s.uri == uri), None)


def reset() -> None:
    """Tests."""
    global _index, _built_mono, _built_sig
    with _lock:
        _index = None
        _built_mono = 0.0
        _built_sig = None
