"""THE CAPTURE ACCOUNT'S SIGN-IN (api/spotify_capture.py, G2): account B
signs in through its own routes, its own redirect URI and its own token
file — and the main account's sign-in is never touched. Driven through the
real routes and the real spotipy OAuth/cache code, with only Spotify's two
answers (the token exchange and GET /me) stubbed."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest
import spotipy
from fastapi import FastAPI
from fastapi.testclient import TestClient
from spotipy.oauth2 import SpotifyOAuth

from api import spotify_capture as cap

MAIN_ID, B_ID = "main-account", "account-b"
CAPTURE_CALLBACK = "http://127.0.0.1:8000/api/spotify/capture/callback"


@pytest.fixture(autouse=True)
def app_credentials(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "spotipy_client_id", "client-id")
    monkeypatch.setattr(settings, "spotipy_client_secret", "client-secret")


@pytest.fixture
def spotify(monkeypatch):
    """Spotify's two answers. `who` maps an access token to the account it
    belongs to; the exchange hands back a token for `self.signs_in_as`."""
    class World:
        signs_in_as = B_ID
        product = "premium"
        exchanged: list = []

    world = World()

    def get_access_token(self, code=None, as_dict=True, check_cache=True):
        token = {"access_token": f"at-{world.signs_in_as}", "refresh_token": f"rt-{code}",
                 "expires_at": 9_999_999_999, "scope": self.scope, "token_type": "Bearer"}
        world.exchanged.append((code, self.redirect_uri, type(self.cache_handler).__name__))
        self.cache_handler.save_token_to_cache(token)      # what spotipy itself does
        return token if as_dict else token["access_token"]

    def me(self):
        access = self._auth
        uid = access[len("at-"):]
        return {"id": uid, "display_name": uid.replace("-", " ").title(),
                "product": world.product}

    monkeypatch.setattr(SpotifyOAuth, "get_access_token", get_access_token)
    monkeypatch.setattr(spotipy.Spotify, "me", me)
    return world


@pytest.fixture
def client(monkeypatch):
    from routers import auth
    import api.spotify_client as main_client
    # the capture flow must never build the MAIN account's auth manager
    def no_main(*a, **k):
        raise AssertionError("the capture sign-in reached the main account's sign-in")
    monkeypatch.setattr(main_client, "_make_auth_manager", no_main)
    monkeypatch.setattr(auth, "get_spotify", no_main)
    app = FastAPI()
    app.include_router(auth.router)
    return TestClient(app)


def _main_token():
    cap.MAIN_TOKEN_CACHE.write_text(json.dumps(
        {"access_token": f"at-{MAIN_ID}", "refresh_token": "rt-main", "expires_at": 1}))
    return cap.MAIN_TOKEN_CACHE.read_bytes()


def _login(client) -> dict:
    r = client.get("/api/spotify/capture/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    url = urlparse(r.headers["location"])
    assert url.netloc == "accounts.spotify.com"
    return {k: v[0] for k, v in parse_qs(url.query).items()}


def test_the_link_is_its_own_and_spotify_always_asks_who(client):
    q = _login(client)
    assert q["redirect_uri"] == CAPTURE_CALLBACK
    assert q["show_dialog"] == "True", "never a silent approval as whoever is signed in"
    assert set(q["scope"].split()) == {"user-read-playback-state", "user-read-currently-playing",
                                       "user-modify-playback-state"}
    assert q["state"] and q["state"] != _login(client)["state"]


def test_account_b_signs_in_and_the_main_sign_in_is_untouched(client, spotify):
    main_before = _main_token()
    q = _login(client)
    r = client.get(f"/api/spotify/capture/callback?code=c1&state={q['state']}")
    assert r.status_code == 200 and "Account B" in r.text and "account-b" in r.text
    assert cap.MAIN_TOKEN_CACHE.read_bytes() == main_before, "the main token is never written"
    saved = json.loads(cap.TOKEN_CACHE.read_text())
    assert saved["access_token"] == "at-account-b" and saved["refresh_token"] == "rt-c1"
    assert spotify.exchanged == [("c1", CAPTURE_CALLBACK, "MemoryCacheHandler")], \
        "exchanged into memory, written only after the account check"
    s = client.get("/api/spotify/capture/status").json()
    assert s["signed_in"] and s["user_id"] == B_ID and s["checked_not_main"] is True
    assert s["days_left"] == cap.LIFETIME_DAYS


def test_the_main_account_is_refused_and_nothing_is_saved(client, spotify):
    """The 2026-10-30 shape: a browser already signed in as the main account."""
    main_before = _main_token()
    spotify.signs_in_as = MAIN_ID
    q = _login(client)
    r = client.get(f"/api/spotify/capture/callback?code=c2&state={q['state']}")
    assert r.status_code == 409 and "MAIN account" in r.text
    assert not cap.TOKEN_CACHE.exists() and not cap.RECORD_FILE.exists()
    assert cap.MAIN_TOKEN_CACHE.read_bytes() == main_before
    assert client.get("/api/spotify/capture/status").json()["signed_in"] is False


def test_a_sign_in_must_start_from_its_own_link_once(client, spotify):
    r = client.get("/api/spotify/capture/callback?code=c3&state=made-up")
    assert r.status_code == 400 and not cap.TOKEN_CACHE.exists()
    q = _login(client)
    assert client.get(f"/api/spotify/capture/callback?code=c4&state={q['state']}").status_code == 200
    cap.TOKEN_CACHE.unlink()
    again = client.get(f"/api/spotify/capture/callback?code=c5&state={q['state']}")
    assert again.status_code == 400 and not cap.TOKEN_CACHE.exists(), "a state is good once"
    assert spotify.exchanged[-1][0] == "c4", "a refused state never reaches Spotify"


def test_a_state_older_than_its_window_is_refused(spotify):
    url = cap.authorize_url(now=1000.0)
    state = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(cap.SignInRefused) as e:
        cap.complete_sign_in("c6", state, now=1000.0 + cap.STATE_TTL_S + 1)
    assert e.value.reason == "stale" and not cap.TOKEN_CACHE.exists()


def test_an_unreadable_main_account_lands_and_says_it_could_not_check(client, spotify):
    spotify.product = "free"
    q = _login(client)                                     # no main token on disk
    r = client.get(f"/api/spotify/capture/callback?code=c7&state={q['state']}")
    assert r.status_code == 200
    assert "could not check" in r.text and "not Premium" in r.text
    s = client.get("/api/spotify/capture/status").json()
    assert s["signed_in"] and s["checked_not_main"] is False and s["product"] == "free"


def test_spotify_saying_no_saves_nothing(client):
    r = client.get("/api/spotify/capture/callback?error=access_denied")
    assert r.status_code == 400 and "access_denied" in r.text
    assert not cap.TOKEN_CACHE.exists()


def test_nobody_signed_in_reads_as_not_signed_in(client):
    s = client.get("/api/spotify/capture/status").json()
    assert s == {**s, "signed_in": False, "user_id": None, "expires_at_ms": None,
                 "login_url": "/api/spotify/capture/login"}
