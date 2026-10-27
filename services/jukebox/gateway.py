"""
SpotFX — the Jukebox's Spotify gateway: every Spotify call the program
engine makes, in one place, all BLOCKING (spotipy is synchronous and sleeps
synchronously on a 429's Retry-After), so the runner only ever reaches it
through `asyncio.to_thread` and the event loop never waits on Spotify — the
same pattern as Absorb's gateway (services/absorb_spotify.py).

EVERY call is spaced at least `MIN_CALL_SPACING_S` (0.5 s) after the one
before it — reads included, not just control calls (data/jukebox-plan/
report.md §9, PR 1.1), so a loop bug can never hammer the API and a commit's
read-back never races the POST it is checking.

The set is read through `/playlists/{id}/items` (spotipy's `playlist_items`
already calls that path, not the renamed `/tracks`: the February 2026
development-mode migration renamed it, and the study asked for `/items` from
day one), 100 at a time, IN ORDER WITH DUPLICATES KEPT — Spotify plays the
playlist by position, so the program has to count positions the same way.
Local files, podcast episodes and unplayable rows are left out: the context
skips them and they have no `spotify:track:` URI to queue.

`JukeboxGateway` is the interface; tests hand the runner a fake with the
same methods. `ReadOnlyGateway` is what the dry run uses: it refuses every
method that could change anything, structurally.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from services.absorb_spotify import parse_playlist_id

logger = logging.getLogger(__name__)

MIN_CALL_SPACING_S = 0.5
PAGE = 100                        # Spotify's cap for a playlist page
ITEM_FIELDS = ("items(track(uri,name,duration_ms,is_local,type,"
               "artists(name),album(images))),next,total")

_TRACK_ID = "spotify:track:"


def parse_track_uri(link: str) -> Optional[str]:
    """A `spotify:track:` URI from a URI, an open.spotify.com/track link or
    a bare id."""
    link = (link or "").strip()
    if not link:
        return None
    if link.startswith(_TRACK_ID):
        tid = link[len(_TRACK_ID):]
    elif "open.spotify.com/" in link and "/track/" in link:
        tid = link.split("/track/", 1)[1].split("?", 1)[0].split("/", 1)[0]
    else:
        tid = link
    tid = tid.strip()
    if 16 <= len(tid) <= 40 and tid.isalnum():
        return _TRACK_ID + tid
    return None


def _artists(obj: dict) -> str:
    return ", ".join(a.get("name", "") for a in (obj.get("artists") or []) if a)


# The album art the guest page shows, straight from Spotify's image servers
# (never copied or altered: report §2.3). Spotify lists an album's images
# largest first, usually 640, 300 and 64 px square.
IMAGE_MAX_PX = 640
THUMB_MIN_PX = 64


def art(obj: dict) -> tuple[str, str]:
    """(image, thumb) for a track: the largest image no wider than
    IMAGE_MAX_PX, and the smallest at least THUMB_MIN_PX wide (each falls
    back to whatever there is; ("", "") when Spotify gave none)."""
    images = [i for i in ((obj.get("album") or {}).get("images") or [])
              if isinstance(i, dict) and i.get("url")]
    if not images:
        return "", ""
    by_size = sorted(images, key=lambda i: int(i.get("width") or 0))
    big = [i for i in by_size if int(i.get("width") or 0) <= IMAGE_MAX_PX] or by_size
    small = [i for i in by_size if int(i.get("width") or 0) >= THUMB_MIN_PX] or by_size
    return big[-1]["url"], small[0]["url"]


class JukeboxGateway:
    """Every Spotify call the program engine makes. Blocking; spaced."""

    def __init__(self, sp: Any = None, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._sp = sp
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_call: Optional[float] = None

    def _client(self) -> Any:
        if self._sp is None:
            from api.spotify_client import get_spotify
            self._sp = get_spotify()
        return self._sp

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run one Spotify call no sooner than MIN_CALL_SPACING_S after the
        previous one ENDED. The lock spans the call, so two callers never
        overlap either."""
        with self._lock:
            if self._last_call is not None:
                wait = MIN_CALL_SPACING_S - (self._clock() - self._last_call)
                if wait > 0:
                    self._sleep(wait)
            try:
                return fn(*args, **kwargs)
            finally:
                self._last_call = self._clock()

    # ── devices and playback ────────────────────────────────────────────────

    def device_id(self, name: str) -> Optional[str]:
        devices = (self._call(self._client().devices) or {}).get("devices") or []
        for d in devices:
            if str(d.get("name", "")).lower() == name.lower():
                return d.get("id")
        return None

    def playback(self) -> Optional[dict]:
        """What the player is doing, or None when nothing is playing:
        {uri, is_playing, progress_ms, duration_ms, device_name, context_uri,
        shuffle, smart_shuffle, repeat}."""
        data = self._call(self._client().current_playback)
        if not data or not data.get("item"):
            return None
        item = data.get("item") or {}
        return {"uri": item.get("uri") or "",
                "is_playing": bool(data.get("is_playing")),
                "progress_ms": int(data.get("progress_ms") or 0),
                "duration_ms": int(item.get("duration_ms") or 0),
                "device_name": (data.get("device") or {}).get("name", ""),
                "context_uri": (data.get("context") or {}).get("uri", "") or "",
                "shuffle": bool(data.get("shuffle_state")),
                "smart_shuffle": bool(data.get("smart_shuffle")),
                "repeat": str(data.get("repeat_state") or "off")}

    def start_context(self, device_id: str, context_uri: str, position: int = 0) -> None:
        """Play the set playlist as the context, from `position`."""
        self._call(self._client().start_playback, device_id=device_id,
                   context_uri=context_uri, offset={"position": int(position)})

    def set_shuffle(self, on: bool, device_id: Optional[str] = None) -> None:
        self._call(self._client().shuffle, bool(on), device_id=device_id)

    def set_repeat(self, mode: str, device_id: Optional[str] = None) -> None:
        self._call(self._client().repeat, mode, device_id=device_id)

    def pause(self, device_id: Optional[str] = None) -> None:
        self._call(self._client().pause_playback, device_id=device_id)

    # ── the queue ───────────────────────────────────────────────────────────

    def add_to_queue(self, uri: str) -> None:
        """Commit one song: it plays before the context's next track. No
        device id — the ACTIVE device, which the runner has already checked
        is the target (spotipy's own advice: naming a device that isn't the
        one playing is refused by Spotify)."""
        self._call(self._client().add_to_queue, uri)

    def queue(self) -> dict:
        """{current: uri, queue: [uri, ...]} — Spotify's "Next in queue"
        items first, then the context's upcoming tracks."""
        data = self._call(self._client().queue) or {}
        cur = (data.get("currently_playing") or {}).get("uri") or ""
        return {"current": cur,
                "queue": [(q or {}).get("uri") or "" for q in (data.get("queue") or [])]}

    def next_track(self) -> None:
        """The repair path: skip a committed song he removed, as it starts."""
        self._call(self._client().next_track)

    def reorder(self, pid: str, range_start: int, insert_before: int,
                snapshot_id: str = "") -> Optional[str]:
        """Move ONE playlist item (`PUT /playlists/{id}/items`, range_length
        1); Spotify's own semantics: the item at `range_start` goes in front
        of the item now at `insert_before`. Returns the new snapshot id. The
        snapshot pins the edit to the version the positions were read from."""
        res = self._call(self._client().playlist_reorder_items, pid, range_start=range_start,
                         insert_before=insert_before, range_length=1,
                         snapshot_id=snapshot_id or None) or {}
        return res.get("snapshot_id")

    # ── reading the set and songs ───────────────────────────────────────────

    def resolve_playlist(self, link: str) -> Optional[dict]:
        pid = parse_playlist_id(link)
        if not pid:
            return None
        data = self._call(self._client().playlist, pid,
                          fields="id,name,uri,snapshot_id") or {}
        if not data.get("id"):
            return None
        return {"id": data["id"], "name": data.get("name") or "",
                "uri": data.get("uri") or f"spotify:playlist:{data['id']}",
                "snapshot_id": data.get("snapshot_id") or ""}

    def playlist_snapshot(self, pid: str) -> Optional[str]:
        data = self._call(self._client().playlist, pid, fields="snapshot_id") or {}
        return data.get("snapshot_id")

    def playlist_items(self, pid: str) -> list[dict]:
        """Every playable track in the playlist, in playlist order,
        duplicates kept: [{uri, title, artist, duration_ms, image, thumb}]."""
        sp = self._client()
        out: list[dict] = []
        offset = 0
        while True:
            page = self._call(sp.playlist_items, pid, offset=offset, limit=PAGE,
                              fields=ITEM_FIELDS, additional_types=("track",)) or {}
            items = page.get("items") or []
            for row in items:
                tr = (row or {}).get("track") or (row or {}).get("item") or {}
                uri = tr.get("uri") or ""
                if tr.get("is_local") or not uri.startswith(_TRACK_ID):
                    continue
                image, thumb = art(tr)
                out.append({"uri": uri, "title": tr.get("name") or "",
                            "artist": _artists(tr),
                            "duration_ms": int(tr.get("duration_ms") or 0),
                            "image": image, "thumb": thumb})
            if not page.get("next") or not items:
                break
            offset += len(items)
        return out

    def track(self, uri: str) -> Optional[dict]:
        tid = uri[len(_TRACK_ID):] if uri.startswith(_TRACK_ID) else uri
        data = self._call(self._client().track, tid) or {}
        if not data.get("uri"):
            return None
        return self._song(data)


    def search(self, query: str, limit: int = 10, offset: int = 0) -> list[dict]:
        """Spotify's own song search, `limit` a page: [{uri, title, artist,
        duration_ms, explicit, image, thumb}]."""
        data = self._call(self._client().search, q=query, limit=limit, offset=offset,
                          type="track") or {}
        return [self._song(t) for t in ((data.get("tracks") or {}).get("items") or [])
                if (t or {}).get("uri", "").startswith(_TRACK_ID) and not t.get("is_local")]

    def tracks(self, uris: list[str]) -> list[dict]:
        """Several songs in ONE call (up to 50) — the art, length and
        explicit flag of his own library's hits."""
        ids = [u[len(_TRACK_ID):] for u in uris if u.startswith(_TRACK_ID)][:50]
        if not ids:
            return []
        data = self._call(self._client().tracks, ids) or {}
        return [self._song(t) for t in (data.get("tracks") or []) if t and t.get("uri")]

    @staticmethod
    def _song(t: dict) -> dict:
        image, thumb = art(t)
        return {"uri": t["uri"], "title": t.get("name") or "", "artist": _artists(t),
                "duration_ms": int(t.get("duration_ms") or 0),
                "explicit": bool(t.get("explicit")), "image": image, "thumb": thumb}


READ_ONLY_METHODS = frozenset({"resolve_playlist", "playlist_snapshot", "playlist_items",
                               "track", "device_id", "playback", "queue", "search", "tracks"})


class ReadOnlyGateway:
    """A gateway that can only READ (the dry run's). Any method that could
    change playback, the queue or a playlist raises before it reaches
    Spotify — refused by construction, not by the caller's care."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        if name not in READ_ONLY_METHODS:
            raise PermissionError(f"the read-only gateway refuses {name!r}")
        return getattr(self._inner, name)


_default: Optional[JukeboxGateway] = None
_search: Optional[JukeboxGateway] = None


def default_gateway() -> JukeboxGateway:
    global _default
    if _default is None:
        _default = JukeboxGateway()
    return _default


def search_gateway() -> JukeboxGateway:
    """The guests' searches get their OWN gateway (its own spacing and lock),
    so a party typing into the search box can never queue in front of the
    engine's commit to Spotify's queue."""
    global _search
    if _search is None:
        _search = JukeboxGateway()
    return _search
