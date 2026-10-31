"""THE CAPTURE ACCOUNT'S SIGN-IN (G2, the Jukebox plan's phase 4).

Phase 4 plays songs on a hidden player, "Serenity Capture", under a SECOND
Spotify account (account B), so SpotFX can learn them while the house plays
normally (data/jukebox-plan/report.md §9). That account authorises the same
developer app as the main one, as its own user. This module is ITS sign-in,
and the one rule it exists to keep:

  IT NEVER TOUCHES THE MAIN ACCOUNT'S SIGN-IN. api/spotify_client.py keeps
  ONE token (storage/.spotify_token_cache) and everything SpotFX polls
  follows it; if account B signed in at /api/spotify/login, SpotFX would
  quietly start following account B instead of his music. So account B has
  its own routes (routers/auth.py, /api/spotify/capture/*), its own redirect
  URI (settings.spotipy_capture_redirect_uri, registered on his app
  2026-10-30), its own token file (TOKEN_CACHE) and its own record
  (RECORD_FILE). The main token file is only ever READ here, never written.

Three more things it keeps true:

- SPOTIFY ALWAYS ASKS WHO IS SIGNING IN (show_dialog). Without it Spotify
  approves silently as whoever the browser is already signed in as — which
  is how the main account's re-login went on 2026-10-30.
- THE MAIN ACCOUNT CAN NEVER LAND IN THE CAPTURE FILE. The code is exchanged
  into memory first; the account is read back (GET /me) and compared with
  the main account's (read with the main token's current access token,
  read-only: no refresh, no write). The same account is REFUSED and nothing
  is written. A main account that can't be read is not a refusal — the
  sign-in lands and says it could not check.
- A SIGN-IN STARTS FROM ITS OWN LINK. The login route hands Spotify a fresh
  state; the callback accepts only a state it issued in the last
  STATE_TTL_S, once.

Nothing here plays, queues or reads playback. The capture worker that will
use this token is phase 4's own work.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Callable, Optional

import spotipy
from spotipy.cache_handler import CacheFileHandler, MemoryCacheHandler
from spotipy.oauth2 import SpotifyOAuth

from config import PROFILES_DIR, settings

# What the capture worker needs on "Serenity Capture": start a song there and
# read its progress. Nothing about playlists or the library.
CAPTURE_SCOPES = ("user-read-playback-state user-read-currently-playing "
                  "user-modify-playback-state")

TOKEN_CACHE = PROFILES_DIR.parent / ".spotify_token_cache_capture"
RECORD_FILE = PROFILES_DIR.parent / "spotify_capture_auth.json"
MAIN_TOKEN_CACHE = PROFILES_DIR.parent / ".spotify_token_cache"   # read only

STATE_TTL_S = 15 * 60
LIFETIME_DAYS = 180              # Spotify's refresh tokens, like the main one
DAY_MS = 86_400_000

_states: dict[str, float] = {}   # issued state -> monotonic time


class SignInRefused(Exception):
    """A sign-in that must not land, with the sentence that says why."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def _oauth(cache_handler) -> SpotifyOAuth:
    return SpotifyOAuth(
        client_id=settings.spotipy_client_id,
        client_secret=settings.spotipy_client_secret,
        redirect_uri=settings.spotipy_capture_redirect_uri,
        scope=CAPTURE_SCOPES,
        show_dialog=True,
        open_browser=False,
        cache_handler=cache_handler,
    )


def authorize_url(now: Optional[float] = None) -> str:
    """Spotify's sign-in page for account B, with a fresh state."""
    now = time.monotonic() if now is None else now
    for s, t in list(_states.items()):
        if now - t > STATE_TTL_S:
            del _states[s]
    state = secrets.token_urlsafe(24)
    _states[state] = now
    return _oauth(MemoryCacheHandler()).get_authorize_url(state=state)


def _take_state(state: str, now: float) -> bool:
    issued = _states.pop(state, None) if state else None
    return issued is not None and now - issued <= STATE_TTL_S


def _main_account_id() -> Optional[str]:
    """The main account's Spotify id from its token's CURRENT access token —
    read only (no refresh, nothing written). None when it can't be read."""
    try:
        token = json.loads(MAIN_TOKEN_CACHE.read_text())
        access = token.get("access_token")
        if not access:
            return None
        return (spotipy.Spotify(auth=access, requests_timeout=10).me() or {}).get("id")
    except Exception:
        return None


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def complete_sign_in(code: str, state: str, *,
                     exchange: Optional[Callable[[str], dict]] = None,
                     who: Optional[Callable[[str], dict]] = None,
                     main_id: Optional[Callable[[], Optional[str]]] = None,
                     now_ms: Optional[int] = None,
                     now: Optional[float] = None) -> dict:
    """Exchange the code, check the account, then — and only then — write
    the capture token. Returns what landed; raises SignInRefused."""
    now = time.monotonic() if now is None else now
    if not _take_state(state, now):
        raise SignInRefused("stale", "This sign-in didn't start from the capture "
                            "sign-in link, or it took too long. Open "
                            "/api/spotify/capture/login again in a private window.")
    exchange = exchange or (lambda c: _oauth(MemoryCacheHandler()).get_access_token(
        c, as_dict=True, check_cache=False))
    who = who or (lambda access: spotipy.Spotify(auth=access, requests_timeout=10).me())
    main_id = main_id or _main_account_id
    token = exchange(code)
    me = who(token["access_token"]) or {}
    user_id = me.get("id")
    if not user_id:
        raise SignInRefused("unreadable", "Spotify didn't say which account signed "
                            "in. Nothing was saved; try the link again.")
    main = main_id()
    if main is not None and main == user_id:
        raise SignInRefused("main_account", "That is the MAIN account, so nothing was "
                            "saved. Close this window, open a new private window, "
                            "and sign in as account B.")
    CacheFileHandler(cache_path=str(TOKEN_CACHE)).save_token_to_cache(token)
    record = {
        "authorized_at_ms": int(time.time() * 1000) if now_ms is None else int(now_ms),
        "user_id": user_id,
        "display_name": me.get("display_name") or user_id,
        "product": me.get("product"),
        "checked_not_main": main is not None,
    }
    _write_json(RECORD_FILE, record)
    return record


def status(now_ms: Optional[int] = None) -> dict:
    """Whether account B is signed in, as whom, and until when. Reads two
    small files; never calls Spotify."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    try:
        token = json.loads(TOKEN_CACHE.read_text())
    except Exception:
        token = None
    try:
        record = json.loads(RECORD_FILE.read_text())
    except Exception:
        record = None
    signed_in = bool(token and token.get("refresh_token"))
    out = {"signed_in": signed_in, "login_url": "/api/spotify/capture/login",
           "user_id": None, "display_name": None, "product": None,
           "authorized_at_ms": None, "expires_at_ms": None, "days_left": None,
           "checked_not_main": None}
    if signed_in and record:
        at = int(record.get("authorized_at_ms") or 0)
        exp = at + LIFETIME_DAYS * DAY_MS
        out.update(user_id=record.get("user_id"), display_name=record.get("display_name"),
                   product=record.get("product"), authorized_at_ms=at, expires_at_ms=exp,
                   days_left=max(0, -(-(exp - now_ms) // DAY_MS)),   # whole days, rounded up
                   checked_not_main=record.get("checked_not_main"))
    return out
