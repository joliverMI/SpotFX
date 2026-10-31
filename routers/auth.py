"""
SpotFX — Spotify OAuth router.

Flow:
  1. User visits /api/spotify/login    → redirected to Spotify authorize page
  2. Spotify redirects back to /api/spotify/callback?code=...
  3. We exchange the code for a token (spotipy caches it)
  4. spotify_client._sp is reset so next poll picks up the new token

Redirect URI registered in Spotify dashboard:
  http://127.0.0.1:8000/api/spotify/callback

THE CAPTURE ACCOUNT (account B, G2) signs in at /api/spotify/capture/login —
never at /api/spotify/login, which would replace the main account's one
token. Its own redirect URI, token file and checks: api/spotify_capture.py.
"""
import asyncio
import html

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse

import api.spotify_client as spotify_module
from api import spotify_capture
from api.spotify_client import get_spotify
from services import spotify_auth_age

router = APIRouter(prefix="/api/spotify", tags=["auth"])


@router.get("/login")
async def login():
    """Redirect the browser to Spotify's OAuth authorization page."""
    sp = get_spotify()
    auth_url = sp.auth_manager.get_authorize_url()
    return RedirectResponse(auth_url)


@router.get("/callback")
async def callback(request: Request, code: str = "", error: str = ""):
    """
    Spotify redirects here after the user approves access.
    Exchange the code for a token, reset the client, then redirect home.
    """
    if error:
        return HTMLResponse(f"<h2>Auth failed: {error}</h2>", status_code=400)
    if not code:
        return HTMLResponse("<h2>No auth code received.</h2>", status_code=400)

    # Exchange code → token (spotipy caches it automatically)
    sp = get_spotify()
    sp.auth_manager.get_access_token(code, as_dict=False, check_cache=False)
    # Spotify's refresh tokens die six months after this moment: start the
    # recorded clock (services/spotify_auth_age.py).
    spotify_auth_age.record_authorization()

    # Reset the shared client so the polling loop gets a fresh authenticated instance
    spotify_module._sp = None

    return RedirectResponse("/")


@router.get("/auth-status")
async def auth_status():
    """Quick check — is the Spotify token present and valid? `sign_in` is
    how old the sign-in is and the warning line, if one is due."""
    sign_in = spotify_auth_age.status()
    try:
        sp = get_spotify()
        token = sp.auth_manager.get_cached_token()
        if token:
            return {"authenticated": True, "sign_in": sign_in}
    except Exception:
        pass
    return {"authenticated": False, "login_url": "/api/spotify/login", "sign_in": sign_in}


@router.get("/auth-age")
async def auth_age():
    """How old SpotFX's Spotify sign-in is, when it runs out (Spotify's
    refresh tokens die six months after sign-in), and the warning line from
    14 days before. Reads two small files; never calls Spotify."""
    return spotify_auth_age.status()


# ── The capture account (account B) — api/spotify_capture.py ────────────────

def _page(title: str, lines: list[str], status_code: int = 200) -> HTMLResponse:
    body = "".join(f"<p>{html.escape(line)}</p>" for line in lines)
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title>"
        "<body style='font-family:system-ui,sans-serif;max-width:32rem;margin:2rem auto;"
        "padding:0 1rem;line-height:1.5'>"
        f"<h2>{html.escape(title)}</h2>{body}</body>", status_code=status_code)


@router.get("/capture/login")
async def capture_login():
    """Spotify's sign-in page for the capture account. Spotify always asks
    who is signing in (show_dialog)."""
    return RedirectResponse(spotify_capture.authorize_url())


@router.get("/capture/callback")
async def capture_callback(code: str = "", state: str = "", error: str = ""):
    """Exchange the code for the capture account's own token — refused, with
    nothing saved, when it is the main account."""
    if error:
        return _page("Capture sign-in didn't finish",
                     [f"Spotify said: {error}.", "Nothing was saved."], 400)
    if not code:
        return _page("Capture sign-in didn't finish",
                     ["Spotify sent no sign-in code.", "Nothing was saved."], 400)
    try:
        rec = await asyncio.to_thread(spotify_capture.complete_sign_in, code, state)
    except spotify_capture.SignInRefused as refused:
        return _page("Capture sign-in refused", [refused.message],
                     409 if refused.reason == "main_account" else 400)
    except Exception as e:                                  # noqa: BLE001
        return _page("Capture sign-in didn't finish",
                     [f"Spotify answered with an error: {e}.", "Nothing was saved."], 502)
    lines = [f"Signed in as {rec['display_name']} ({rec['user_id']}) for Serenity Capture.",
             "The main account's sign-in was not touched."]
    if rec.get("product") not in (None, "premium"):
        lines.append(f"This account is \"{rec['product']}\", not Premium — the capture "
                     "player needs a Premium account to be controlled.")
    if not rec.get("checked_not_main"):
        lines.append("SpotFX couldn't read the main account just now, so it could not "
                     "check this is a different account. Check the name above.")
    lines.append("You can close this window.")
    return _page("Capture account signed in", lines)


@router.get("/capture/status")
async def capture_status():
    """Whether the capture account is signed in, as whom, and until when.
    Reads two small files; never calls Spotify."""
    return spotify_capture.status()
