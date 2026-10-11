"""A Spotify context's friendly name ("40! Lightshow" for
"spotify:playlist:…") — the Show Playlists' "Playing from" line and the
builder's context chips (spectra/services/show_playlists.py).

READ ONLY, AND NEVER A SPOTFX IMPORT (the S3 import discipline): the playing
context's name arrives on the bridge (SpotFX's own `context_name` on every
"state" message); any other context is asked of SpotFX over HTTP
(`GET /api/spotify/context-name`, the bridge's `_poll_settings` pattern).
Cached per process — a playlist's name changes rarely, and an unresolved
name is retried after MISS_RETRY_S rather than held as "" forever.

Blocking (an HTTP call): route handlers run it in a worker thread.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

HTTP_TIMEOUT_S = 4.0
MISS_RETRY_S = 300.0

_cache: dict[str, tuple[str, float]] = {}


def _bridge_name(uri: str) -> Optional[str]:
    try:
        from spectra.services import engine
        if engine.bridge.context_uri() == uri:
            return engine.bridge.context_name()
    except Exception:                                    # noqa: BLE001
        return None
    return None


def _http_url() -> str:
    try:
        from spectra.services import engine
        return engine.bridge.http_url
    except Exception:                                    # noqa: BLE001
        from spectra.services.bridge import default_http_url
        return default_http_url()


def _ask_spotfx(uri: str) -> str:
    try:
        r = httpx.get(f"{_http_url()}/api/spotify/context-name", params={"uri": uri},
                      timeout=HTTP_TIMEOUT_S)
        if r.status_code == 200:
            return str((r.json() or {}).get("name") or "")
    except Exception:                                    # noqa: BLE001
        pass
    return ""


def name_for(uri: str) -> str:
    """The name, or "" when it cannot be resolved — never a guess."""
    uri = (uri or "").strip()
    if not uri:
        return ""
    live = _bridge_name(uri)
    if live:
        _cache[uri] = (live, time.monotonic())
        return live
    hit = _cache.get(uri)
    if hit is not None and (hit[0] or time.monotonic() - hit[1] < MISS_RETRY_S):
        return hit[0]
    name = _ask_spotfx(uri)
    _cache[uri] = (name, time.monotonic())
    return name


def reset() -> None:
    """Tests."""
    _cache.clear()
