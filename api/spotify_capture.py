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

Nothing here plays, queues or reads playback. `capture_client()` hands the
token to the one thing that does — the capture lane (capture_lane/), which
plays only on "Serenity Capture" and checks it is account B first.

THE LOCK LIVES IN THE CLIENT (fx/second_account.py is the binding
statement; the Admiral, 2026-11-01: "a solid barrier so that the second user
doesn't get their music taken from them by the system"). Every account-B
client is a `SecondAccountSpotify`, whose HTTP session asks
`second_account.check()` before ANY request that isn't a read (GET/HEAD/
OPTIONS) leaves — play, pause, skip, queue, transfer, volume, playlist and
library writes alike, whichever spotipy method (or a raw `_put`/`_post`/
`_delete`, or the session itself) sends it. Reads always pass: the lock
stops the system USING the account, never reading it. The one write it lets
through while locked is letting go of the system's own song
(`release_system_playback`), and only after a fresh read has shown the song
playing now IS the one the system started, on the device it started it on.
tests/test_second_account_lock.py holds the gate, and fails if anything
builds an account-B client any other way.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

import spotipy
from spotipy.cache_handler import CacheFileHandler, MemoryCacheHandler
from spotipy.oauth2 import SpotifyOAuth

from config import PROFILES_DIR, settings
from fx import second_account

logger = logging.getLogger(__name__)

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


READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
PAUSE_PATH = "/me/player/pause"


class SecondAccountSpotify(spotipy.Spotify):
    """A spotipy client for ACCOUNT B whose every write asks the lock.

    The gate sits on the instance's own HTTP session (`session.request`),
    the one door every spotipy call — named method, `_internal_call`, or the
    session's own `put`/`post`/`delete` — goes through, so no method can be
    a way round it. The token refresh is not behind it: that is the auth
    manager's own session, and it reads nothing and plays nothing.
    """

    def __init__(self, *args, **kwargs) -> None:
        # a real Session, always: a falsy value would make spotipy use the
        # `requests` MODULE as its session, and gating that would gate the
        # whole process
        kwargs["requests_session"] = True
        super().__init__(*args, **kwargs)
        self._release_permit = threading.local()
        session = self._session
        send = session.request

        def request(method, url, *a, **k):
            verb = str(method).upper()
            if verb not in READ_METHODS:
                path = urlsplit(str(url)).path
                if not self._permitted(verb, path):
                    second_account.check(f"{verb} {path}")
            return send(method, url, *a, **k)

        session.request = request

    def _permitted(self, verb: str, path: str) -> bool:
        """The release's own pause, once, on this thread only."""
        if getattr(self._release_permit, "armed", False) and verb == "PUT" \
                and path.endswith(PAUSE_PATH):
            self._release_permit.armed = False
            return True
        return False

    def start_playback(self, device_id=None, context_uri=None, uris=None, offset=None,
                       position_ms=None):
        """A play the system starts: asked of the lock first, then written
        down (second_account.note_started) BEFORE it leaves, so letting go
        later — even after a crash — can tell the system's song from the
        second user's."""
        second_account.check("start playback")
        second_account.note_started(device_id, list(uris or ([context_uri] if context_uri else [])))
        try:
            return super().start_playback(device_id=device_id, context_uri=context_uri,
                                          uris=uris, offset=offset, position_ms=position_ms)
        except second_account.SecondAccountLocked:
            second_account.clear_started()        # locked in between: nothing left
            raise

    def release_system_playback(self, *, end_of_song: bool = False) -> dict:
        """Let go of the play the system started: pause it if — and only if
        — a fresh read shows it is what is playing now, on the device the
        system started it on (second_account.is_system_playback). Allowed
        while the lock is off: stopping the system's own song is what
        turning it off asks for. Anything else is left alone.

        `end_of_song` lets a different song on the system's own device
        straight after its song ended (Spotify carrying on from the system's
        play) count as the system's — the capture lane passes it only on a
        song's natural end."""
        record = second_account.started()
        if not record:
            return {"paused": False, "why": "nothing_started"}
        playback = self.current_playback()
        ours, why = second_account.is_system_playback(record, playback, end_of_song=end_of_song)
        if not ours:
            second_account.clear_started()        # nothing of the system's is playing now
            logger.info("Second account: let go without pausing (%s)", why)
            return {"paused": False, "why": why}
        self._release_permit.armed = True
        try:
            self.pause_playback(device_id=record["device_id"])
        finally:
            self._release_permit.armed = False
        second_account.clear_started()
        logger.info("Second account: paused the system's own song (%s)", why)
        return {"paused": True, "why": why}


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
    who = who or (lambda access: SecondAccountSpotify(auth=access, requests_timeout=10).me())
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


def capture_client() -> SecondAccountSpotify:
    """A client signed in as account B, for the capture lane (capture_lane/)
    — the ONE place anything plays with this token, and every write it sends
    asks the second account's lock first (SecondAccountSpotify). Its refresh
    writes TOKEN_CACHE only; the main token file is never opened here."""
    return SecondAccountSpotify(auth_manager=_oauth(CacheFileHandler(cache_path=str(TOKEN_CACHE))),
                                requests_timeout=10)


def signed_in_user() -> Optional[dict]:
    """The record of who account B is — `{user_id, checked_not_main}` — or
    None when it isn't signed in. Reads two small files; never calls
    Spotify."""
    st = status()
    if not st["signed_in"] or not st["user_id"]:
        return None
    return {"user_id": st["user_id"], "checked_not_main": st["checked_not_main"]}


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
