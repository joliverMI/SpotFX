"""
SpotFX — Spotify OAuth router.

Flow:
  1. User visits /api/spotify/login    → redirected to Spotify authorize page
  2. Spotify redirects back to /api/spotify/callback?code=...
  3. We exchange the code for a token (spotipy caches it)
  4. spotify_client._sp is reset so next poll picks up the new token

Redirect URI registered in Spotify dashboard:
  http://127.0.0.1:8000/api/spotify/callback
"""
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse

import api.spotify_client as spotify_module
from api.spotify_client import get_spotify
from config import settings

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

    # Reset the shared client so the polling loop gets a fresh authenticated instance
    spotify_module._sp = None

    return RedirectResponse("/")


@router.get("/auth-status")
async def auth_status():
    """Quick check — is the Spotify token present and valid?"""
    try:
        sp = get_spotify()
        token = sp.auth_manager.get_cached_token()
        if token:
            return {"authenticated": True}
    except Exception:
        pass
    return {"authenticated": False, "login_url": "/api/spotify/login"}
