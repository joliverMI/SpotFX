"""SpotFX's Spotify sign-in age (services/spotify_auth_age.py): the record
the OAuth callback writes, the six states over a fake token cache, the
warning line from 14 days before the 6-month end, a refused refresh seen on
the real poll, and the jukebox master status carrying the line."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from spotipy.oauth2 import SpotifyOauthError

from services import spotify_auth_age as age

DAY = age.DAY_MS
T0 = 1_780_000_000_000          # a fixed "now" for the sign-in


def _cache(token: str = "refresh-token-AAA") -> None:
    age.TOKEN_CACHE.write_text(json.dumps({"access_token": "at", "refresh_token": token,
                                           "expires_at": 1}))


def test_no_token_cache_is_not_signed_in():
    s = age.status(T0)
    assert s["state"] == "no_token" and "isn't signed in" in s["warning"]


def test_a_sign_in_before_the_record_existed_is_unknown_never_guessed():
    _cache()
    s = age.status(T0)
    assert s["state"] == "unknown"
    assert s["authorized_at_ms"] is None and s["expires_at_ms"] is None
    assert "isn't recorded" in s["warning"]


@pytest.mark.parametrize("days_after, state, days_left", [
    (0, "ok", 180),
    (165, "ok", 15),
    (166, "soon", 14),
    (179.5, "soon", 1),
    (180, "expired", 0),
    (400, "expired", 0),
])
def test_the_clock_and_the_warning(days_after, state, days_left):
    _cache()
    age.record_authorization(T0)
    s = age.status(T0 + int(days_after * DAY))
    assert (s["state"], s["days_left"]) == (state, days_left)
    assert s["expires_at_ms"] == T0 + 180 * DAY
    assert s["warn_from_ms"] == T0 + 166 * DAY
    if state == "ok":
        assert s["warning"] is None
    elif state == "soon":
        assert "runs out by" in s["warning"] and f"{days_left} day" in s["warning"]
    else:
        assert "ran out on" in s["warning"]


def test_the_record_never_holds_the_token_itself():
    _cache("super-secret-refresh-token")
    age.record_authorization(T0)
    raw = age.RECORD_FILE.read_text()
    assert "super-secret-refresh-token" not in raw
    assert json.loads(raw)["refresh_fingerprint"] == age.fingerprint("super-secret-refresh-token")


def test_a_rotated_refresh_token_is_noted_and_the_clock_keeps_counting_from_the_sign_in():
    _cache("first")
    age.record_authorization(T0)
    _cache("second")                                  # Spotify handed back a new one on a refresh
    s = age.status(T0 + 170 * DAY)
    assert s["rotated"] is True
    assert (s["state"], s["days_left"]) == ("soon", 10)


def test_a_refused_refresh_outranks_every_date_and_is_recorded_once():
    _cache()
    age.record_authorization(T0)
    err = SpotifyOauthError("error: invalid_grant", error="invalid_grant",
                            error_description="Refresh token revoked")
    assert age.note_refresh_failure(err, now_ms=T0 + DAY) is True
    first = age.RECORD_FILE.read_text()
    assert age.note_refresh_failure(err, now_ms=T0 + 2 * DAY) is True
    assert age.RECORD_FILE.read_text() == first        # stamped once
    s = age.status(T0 + 3 * DAY)
    assert s["state"] == "refresh_failed" and "refused" in s["warning"]


def test_other_failures_say_nothing_about_the_sign_in():
    _cache()
    age.record_authorization(T0)
    assert age.note_refresh_failure(ConnectionError("network down")) is False
    assert age.note_refresh_failure(SpotifyOauthError("x", error="server_error")) is False
    assert age.status(T0)["state"] == "ok"


def test_a_successful_poll_clears_a_refusal_and_otherwise_touches_nothing():
    age.note_refresh_ok()
    assert not age.RECORD_FILE.exists()                # no failure noted: no disk write
    _cache()
    age.record_authorization(T0)
    age.note_refresh_failure(SpotifyOauthError("x", error="invalid_grant"), now_ms=T0)
    age.note_refresh_ok()
    assert age.status(T0)["state"] == "ok"


# ── the two writers, through their real callers ─────────────────────────────

class _Auth:
    def __init__(self, token: str) -> None:
        self.token = token

    def get_access_token(self, code, as_dict=False, check_cache=False):
        _cache(self.token)                             # spotipy caches the new token
        return "access"

    def get_cached_token(self):
        return {"access_token": "a"}


class _Sp:
    def __init__(self, token="from-callback", playback=None, raises=None) -> None:
        self.auth_manager = _Auth(token)
        self._playback, self._raises = playback, raises

    def current_playback(self):
        if self._raises is not None:
            raise self._raises
        return self._playback


def test_the_oauth_callback_starts_the_clock(monkeypatch):
    from routers import auth
    import api.spotify_client as client
    monkeypatch.setattr(auth, "get_spotify", lambda: _Sp())
    monkeypatch.setattr(client, "_sp", None)
    app = FastAPI()
    app.include_router(auth.router)
    c = TestClient(app)
    r = c.get("/api/spotify/callback?code=abc", follow_redirects=False)
    assert r.status_code in (302, 307)
    rec = age.load_record()
    assert rec["source"] == "callback"
    assert rec["refresh_fingerprint"] == age.fingerprint("from-callback")
    s = c.get("/api/spotify/auth-age").json()
    assert s["state"] == "ok" and s["days_left"] == 180
    assert c.get("/api/spotify/auth-status").json()["sign_in"]["state"] == "ok"


def test_a_refused_refresh_on_the_real_poll_is_recorded_and_cleared(monkeypatch):
    import api.spotify_client as client
    from models.state import state
    for attr in ("current_track", "on_target_device", "poll_ok"):
        monkeypatch.setattr(state, attr, getattr(state, attr))
    _cache()
    age.record_authorization(T0)
    dead = SpotifyOauthError("error: invalid_grant", error="invalid_grant",
                             error_description="Refresh token revoked")
    monkeypatch.setattr(client, "get_spotify", lambda: _Sp(raises=dead))
    assert client.fetch_current_track() is None
    assert age.status()["state"] == "refresh_failed"
    monkeypatch.setattr(client, "get_spotify", lambda: _Sp(playback=None))
    client.fetch_current_track()                        # the token works again
    assert age.status()["state"] != "refresh_failed"


# ── where the line is read ──────────────────────────────────────────────────

def test_the_jukebox_master_status_carries_the_line():
    from services.jukebox import night
    _cache()
    s = night.JukeboxRunner(night.JukeboxDeps(gateway=None)).status()
    assert s["spotify_auth"]["state"] == "unknown"
    assert s["warnings"][0] == s["spotify_auth"]["warning"]
    age.record_authorization()
    s = night.JukeboxRunner(night.JukeboxDeps(gateway=None)).status()
    assert s["spotify_auth"]["state"] == "ok" and s["warnings"] == []


def test_the_supervised_check_logs_a_standing_warning(monkeypatch, caplog):
    _cache()
    age.record_authorization(age._now_ms() - 170 * DAY)
    sleeps = []

    async def stop_after_two(s):
        sleeps.append(s)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError
    monkeypatch.setattr(age.asyncio, "sleep", stop_after_two)
    with caplog.at_level("WARNING"), pytest.raises(asyncio.CancelledError):
        asyncio.run(age.run_supervised(interval_s=1))
    lines = [r.getMessage() for r in caplog.records if "Spotify sign-in" in r.getMessage()]
    assert len(lines) == 2 and "runs out by" in lines[0]


def test_an_unknown_sign_in_is_logged_once_a_process(monkeypatch, caplog):
    _cache()
    sleeps = []

    async def stop_after_three(s):
        sleeps.append(s)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError
    monkeypatch.setattr(age.asyncio, "sleep", stop_after_three)
    with caplog.at_level("WARNING"), pytest.raises(asyncio.CancelledError):
        asyncio.run(age.run_supervised(interval_s=1))
    assert sum("isn't recorded" in r.getMessage() for r in caplog.records) == 1
