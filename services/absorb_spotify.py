"""
SpotFX — Absorb Music's Spotify gateway: every Spotify call the runner makes,
in one place, all BLOCKING (spotipy is synchronous and sleeps synchronously
on a 429's Retry-After), so the runner only ever reaches it through
asyncio.to_thread and the event loop never waits on Spotify.

Playback is driven by TRACKS, never by a playlist context and never through
Spotify's queue API (report §4.4, D2): `play` sends a window of URIs. With no
context, SPECTRA's Show Playlists can never bind a light program to an
absorb run by accident, and absorb's own queue — not Spotify's — decides
what plays next.

Control calls (play, pause, playlist writes) are spaced at least
`MIN_CONTROL_SPACING_S` apart, so a bug that loops can never hammer the API.

`SpotifyGateway` is the interface; tests hand the runner a fake with the same
methods.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

MIN_CONTROL_SPACING_S = 0.5
PAGE = 100                       # Spotify's cap for playlist reads/writes per call

_PLAYLIST_RE = re.compile(r"(?:spotify:playlist:|open\.spotify\.com/playlist/)([A-Za-z0-9]+)")
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9]{16,40}$")


def parse_playlist_id(link: str) -> Optional[str]:
    """The playlist id inside a `spotify:playlist:…` URI or an
    open.spotify.com URL (query string ignored), or a bare id."""
    link = (link or "").strip()
    if not link:
        return None
    m = _PLAYLIST_RE.search(link)
    if m:
        return m.group(1)
    if _BARE_ID_RE.match(link):
        return link
    return None


class SpotifyGateway:
    def __init__(self, sp=None) -> None:
        self._sp = sp
        self._control_lock = threading.Lock()
        self._last_control = 0.0

    def _client(self):
        if self._sp is None:
            from api.spotify_client import get_spotify
            self._sp = get_spotify()
        return self._sp

    def _spaced(self) -> None:
        with self._control_lock:
            wait = MIN_CONTROL_SPACING_S - (time.monotonic() - self._last_control)
            if wait > 0:
                time.sleep(wait)
            self._last_control = time.monotonic()

    # ── devices and playback ────────────────────────────────────────────────

    def device_id(self, name: str) -> Optional[str]:
        devices = (self._client().devices() or {}).get("devices") or []
        for d in devices:
            if str(d.get("name", "")).lower() == name.lower():
                return d.get("id")
        return None

    def play(self, device_id: str, uris: list[str]) -> None:
        self._spaced()
        self._client().start_playback(device_id=device_id, uris=list(uris))

    def pause(self, device_id: Optional[str]) -> None:
        self._spaced()
        self._client().pause_playback(device_id=device_id)

    def current_playback(self) -> Optional[dict]:
        """What Spotify is playing right now — {uri, is_playing,
        device_name} — or None when nothing is. RAISES when Spotify can't
        say, which a caller must treat as "could be absorb's song"
        (services/absorb_silence.py never restores the volume over it)."""
        data = self._client().current_playback()
        if not data or not data.get("item"):
            return None
        return {"uri": (data.get("item") or {}).get("uri"),
                "is_playing": bool(data.get("is_playing")),
                "device_name": (data.get("device") or {}).get("name", "")}

    # ── playlists ───────────────────────────────────────────────────────────

    def resolve_playlist(self, link: str) -> Optional[dict]:
        pid = parse_playlist_id(link)
        if not pid:
            return None
        data = self._client().playlist(pid, fields="id,name,snapshot_id") or {}
        if not data.get("id"):
            return None
        return {"id": data["id"], "name": data.get("name") or "",
                "snapshot_id": data.get("snapshot_id") or ""}

    def playlist_snapshot(self, pid: str) -> Optional[str]:
        data = self._client().playlist(pid, fields="snapshot_id") or {}
        return data.get("snapshot_id")

    def playlist_tracks(self, pid: str) -> list[dict]:
        """Every Spotify track in the playlist, in order, first occurrence
        only. Local files and podcast episodes are left out — they have no
        capturable `spotify:track:` URI."""
        sp = self._client()
        out: list[dict] = []
        seen: set[str] = set()
        offset = 0
        while True:
            page = sp.playlist_items(
                pid, offset=offset, limit=PAGE,
                fields="items(track(uri,name,duration_ms,artists(name))),next,total",
            ) or {}
            items = page.get("items") or []
            for item in items:
                tr = (item or {}).get("track") or {}
                uri = tr.get("uri") or ""
                if not uri.startswith("spotify:track:") or uri in seen:
                    continue
                seen.add(uri)
                artists = ", ".join(a.get("name", "") for a in (tr.get("artists") or []))
                name = tr.get("name") or ""
                out.append({"uri": uri,
                            "title": f"{artists} — {name}" if artists else name,
                            "duration_ms": int(tr.get("duration_ms") or 0)})
            if not page.get("next") or not items:
                break
            offset += len(items)
        return out

    def remove_tracks(self, pid: str, uris: list[str]) -> Optional[str]:
        """Remove every occurrence of each URI (idempotent). Returns the
        playlist's new snapshot id."""
        snapshot = None
        for i in range(0, len(uris), PAGE):
            self._spaced()
            res = self._client().playlist_remove_all_occurrences_of_items(
                pid, uris[i:i + PAGE]) or {}
            snapshot = res.get("snapshot_id") or snapshot
        return snapshot

    def add_tracks_top(self, pid: str, uris: list[str]) -> Optional[str]:
        snapshot = None
        for i in range(0, len(uris), PAGE):
            self._spaced()
            res = self._client().playlist_add_items(pid, uris[i:i + PAGE], position=0) or {}
            snapshot = res.get("snapshot_id") or snapshot
        return snapshot

    def tracks_beyond(self, pid: str, keep: int) -> list[str]:
        """URIs at positions >= keep (what a trim to `keep` would remove)."""
        sp = self._client()
        out: list[str] = []
        offset = keep
        while True:
            page = sp.playlist_items(pid, offset=offset, limit=PAGE,
                                     fields="items(track(uri)),next") or {}
            items = page.get("items") or []
            out += [((it or {}).get("track") or {}).get("uri") or "" for it in items]
            if not page.get("next") or not items:
                break
            offset += len(items)
        return [u for u in out if u]

    def find_or_create_playlist(self, name: str, known_id: str = "") -> str:
        """His private playlist called `name`: the one `known_id` names if it
        still exists under that name, else the first of his own playlists
        with that name, else a new private one."""
        sp = self._client()
        if known_id:
            try:
                data = sp.playlist(known_id, fields="id,name") or {}
                if data.get("id") and data.get("name") == name:
                    return data["id"]
            except Exception:
                pass
        user_id = sp.me()["id"]
        offset = 0
        while True:
            page = sp.user_playlists(user_id, limit=50, offset=offset) or {}
            items = page.get("items") or []
            for pl in items:
                if pl.get("name") == name and (pl.get("owner") or {}).get("id") == user_id:
                    return pl["id"]
            if not page.get("next") or not items:
                break
            offset += len(items)
        self._spaced()
        pl = sp.user_playlist_create(
            user=user_id, name=name, public=False,
            description="Filled by SpotFX Absorb Music: every song it captured, newest first.")
        logger.info("Absorb: created playlist %r (id=%s)", name, pl["id"])
        return pl["id"]


_default: Optional[SpotifyGateway] = None


def default_gateway() -> SpotifyGateway:
    global _default
    if _default is None:
        _default = SpotifyGateway()
    return _default
