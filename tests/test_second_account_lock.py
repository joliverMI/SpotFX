"""THE SECOND SPOTIFY ACCOUNT'S LOCK (fx/second_account.py).

The Admiral, 2026-11-01: the Settings-page switch "must be enabled in order
for the system to use the second account in any capacity other than reading
info ... a solid barrier so that the second user doesn't get their music
taken from them by the system". Turned off mid-play: stop only what the
system started, then let go, never touching the second user's own playback.
Ships OFF.

What this file holds, in order:
  1. the record: OFF when absent, three states, only ON lets a write through,
     every read fresh from disk (no stale "on");
  2. THE GATE IN THE CLIENT: every non-read request an account-B client
     could send — every spotipy write method, the raw verb helpers, the
     session itself — is refused (and NOTHING reaches the network) while the
     lock is off or unreadable; reads always pass;
  3. letting go: the one write the lock allows, and only of the system's own
     song on its own device;
  4. the capture lane end to end — the REAL CaptureGateway and the REAL
     gated client over a modelled Spotify — including the lock going off
     mid-song, and the client holding even when the lane's own check says
     yes;
  5. SpotFX's two lane users treat a locked account as "the hidden player
     can't be used", never as a song's failure;
  6. SPECTRA's switch (GET/PUT /api/second-account);
  7. THE GUARD: nothing builds an account-B client any other way. It is run
     against synthetic sources that bypass it too, so it is proven able to
     fail.

Nothing here reaches Spotify: every request lands on a fake transport.
"""
from __future__ import annotations

import ast
import asyncio
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlsplit

import pytest
import requests
from fastapi.testclient import TestClient

from fx import second_account as sa

REPO = Path(__file__).resolve().parent.parent
URI = "spotify:track:lanetest000000000000001"
THEIRS = "spotify:track:theirsong0000000000001"
DEV = "dev-capture-1"


def _off():
    """The shipped state: no record at all."""
    sa.LOCK_FILE.unlink(missing_ok=True)


# ═════════════════════════════════════════════════════════════════════════════
# 1. the record

def test_it_ships_off_and_off_refuses():
    _off()
    lk = sa.read()
    assert lk.state == sa.OFF and lk.enabled is False and lk.detail == "never turned on"
    assert sa.write_allowed() is False
    with pytest.raises(sa.SecondAccountLocked) as e:
        sa.check("start playback")
    assert e.value.state == sa.OFF and "start playback" in str(e.value)


def test_the_conftest_record_is_on_for_every_other_suite():
    assert sa.read().state == sa.ON and sa.write_allowed() is True


@pytest.mark.parametrize("content", [
    "{not json", "[]", '"on"', '{"enabled": "true"}', '{"enabled": 1}', '{}',
    '{"enabled": null}',
])
def test_an_unreadable_record_is_treated_as_locked(content):
    sa.LOCK_FILE.write_text(content)
    lk = sa.read()
    assert lk.state == sa.UNREADABLE and not lk.enabled and lk.detail
    assert sa.write_allowed() is False
    with pytest.raises(sa.SecondAccountLocked) as e:
        sa.check("pause")
    assert e.value.state == sa.UNREADABLE


def test_a_record_that_cannot_be_opened_is_unreadable():
    sa.LOCK_FILE.unlink()
    sa.LOCK_FILE.mkdir()                 # a directory where the file should be
    try:
        assert sa.read().state == sa.UNREADABLE and not sa.write_allowed()
    finally:
        sa.LOCK_FILE.rmdir()


def test_the_lock_is_read_fresh_every_time():
    sa.set_enabled(True, by="test")
    assert sa.write_allowed()
    sa.LOCK_FILE.write_text('{"enabled": false}')     # changed behind its back
    assert not sa.write_allowed()
    sa.LOCK_FILE.write_text('{"enabled": true}')
    assert sa.write_allowed()


def test_set_enabled_round_trips_atomically_with_a_bounded_history():
    _off()
    for i in range(sa.HISTORY_KEPT + 5):
        sa.set_enabled(i % 2 == 0, by="settings-page", now_ms=1000 + i)
    data = json.loads(sa.LOCK_FILE.read_text())
    last = sa.HISTORY_KEPT + 4
    assert data["enabled"] is (last % 2 == 0) and data["changed_at_ms"] == 1000 + last
    assert data["changed_by"] == "settings-page"
    assert len(data["history"]) == sa.HISTORY_KEPT
    assert not list(sa.LOCK_FILE.parent.glob("*.tmp"))
    with pytest.raises(TypeError):
        sa.set_enabled("yes", by="x")                  # type: ignore[arg-type]


def test_turning_it_on_over_an_unreadable_record_says_so():
    sa.LOCK_FILE.write_text("{garbage")
    sa.set_enabled(True, by="settings-page")
    assert sa.read().state == sa.ON
    assert "replaced_unreadable" in sa.history()[-1]


def test_the_record_follows_spectra_storage_dir(tmp_path):
    """An isolated SPECTRA (SPECTRA_STORAGE_DIR) writes its OWN record, so it
    can never unlock the real account; SpotFX, which never sets it, reads
    the real one."""
    code = ("from fx import second_account as s; "
            "print(s.LOCK_FILE); print(s.STARTED_FILE)")
    env = {"SPECTRA_STORAGE_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=REPO, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    lock, started = out.stdout.split()
    assert Path(lock) == tmp_path / "second_account.json"
    assert Path(started) == tmp_path / "second_account_started.json"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=REPO, env={"PATH": "/usr/bin:/bin"}, timeout=60)
    assert Path(out.stdout.split()[0]) == REPO / "storage" / "spectra" / "second_account.json"


@pytest.mark.parametrize("playback,end,ours,why", [
    (None, False, False, "not_playing"),
    ({"is_playing": False, "item": {"uri": URI}, "device": {"id": DEV}}, False, False, "not_playing"),
    ({"is_playing": True, "item": {"uri": URI}, "device": {"id": "phone"}}, False, False, "other_device"),
    ({"is_playing": True, "item": {"uri": URI}, "device": {"id": DEV}}, False, True, "system_song"),
    ({"is_playing": True, "item": {"uri": THEIRS}, "device": {"id": DEV}}, False, False, "other_song"),
    ({"is_playing": True, "item": {"uri": THEIRS}, "device": {"id": DEV}}, True, True, "continuation"),
    ({"is_playing": True, "item": {"uri": THEIRS}, "device": {"id": "phone"}}, True, False, "other_device"),
])
def test_what_counts_as_the_systems_own_playback(playback, end, ours, why):
    record = {"device_id": DEV, "uris": [URI]}
    assert sa.is_system_playback(record, playback, end_of_song=end) == (ours, why)
    assert sa.is_system_playback(None, playback) == (False, "nothing_started")


def test_a_context_started_plays_track_matches_the_stored_context():
    """start_playback(context_uri=...) stores [context_uri]; Spotify then
    reports the TRACK playing inside it, with the context's own uri on the
    side — that must still read as the system's own."""
    record = {"device_id": DEV, "uris": ["spotify:playlist:x"]}
    playback = {"is_playing": True, "item": {"uri": URI}, "device": {"id": DEV},
               "context": {"uri": "spotify:playlist:x"}}
    assert sa.is_system_playback(record, playback) == (True, "system_song")
    elsewhere = {**playback, "context": {"uri": "spotify:playlist:y"}}
    assert sa.is_system_playback(record, elsewhere) == (False, "other_song")


# ═════════════════════════════════════════════════════════════════════════════
# 2. the gate in the client — over a modelled Spotify

class Account:
    """Account B as Spotify holds it, behind the HTTP transport. Records
    every request that reaches it."""

    def __init__(self, clock=None, duration_ms: int = 20_000) -> None:
        self.clock = clock or time.monotonic
        self.duration_ms = duration_ms
        self.requests: list[tuple[str, str, dict]] = []
        self.playing: Optional[dict] = None       # {"uri", "device_id", "is_playing", "at"}
        self.on_request = None
        self.devices = [{"id": DEV, "name": "Serenity Capture", "volume_percent": 100,
                         "is_restricted": False}]

    def writes(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _ in self.requests if m not in ("GET", "HEAD", "OPTIONS")]

    def play_theirs(self, uri: str = THEIRS, device_id: str = "phone") -> None:
        self.playing = {"uri": uri, "device_id": device_id, "is_playing": True, "at": self.clock()}

    def handle(self, method: str, url: str, params=None, data=None) -> requests.Response:
        m = method.upper()
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        params = {**dict(parse_qsl(parts.query)), **dict(params or {})}
        self.requests.append((m, path, params))
        if self.on_request:
            self.on_request(m, path)
        body: Optional[dict] = {}
        status = 200
        if m == "GET" and path.endswith("/me/player"):
            if not self.playing:
                status, body = 204, None
            else:
                el = (self.clock() - self.playing["at"]) * 1000
                body = {"is_playing": self.playing["is_playing"],
                        "progress_ms": int(min(el, self.duration_ms)),
                        "item": {"uri": self.playing["uri"], "duration_ms": self.duration_ms},
                        "device": {"id": self.playing["device_id"], "name": "x"},
                        "context": self.playing.get("context")}
        elif m == "GET" and path.endswith("/me/player/devices"):
            body = {"devices": list(self.devices)}
        elif m == "GET" and path.endswith("/me"):
            body = {"id": "user-b"}
        elif m == "PUT" and path.endswith("/me/player/play"):
            uris = (json.loads(data) if data else {}).get("uris") or []
            self.playing = {"uri": uris[0] if uris else None,
                            "device_id": (params or {}).get("device_id"),
                            "is_playing": True, "at": self.clock()}
            status, body = 204, None
        elif m == "PUT" and path.endswith("/me/player/pause"):
            if self.playing:
                self.playing["is_playing"] = False
            status, body = 204, None
        elif m != "GET":
            status, body = 204, None
        r = requests.Response()
        r.status_code = status
        r._content = b"" if body is None else json.dumps(body).encode()
        r.url = url
        r.headers["Content-Type"] = "application/json"
        return r


@pytest.fixture
def account(monkeypatch):
    acct = Account()

    def transport(self, method, url, params=None, data=None, **_kw):
        return acct.handle(method, url, params=params, data=data)
    monkeypatch.setattr(requests.Session, "request", transport)
    return acct


def _client():
    from api.spotify_capture import SecondAccountSpotify
    return SecondAccountSpotify(auth="token-b", retries=0, status_retries=0)


# every way a spotipy client could write to the account (play, pause, skip,
# queue, transfer, volume, seek, playlists, library, follows) plus the raw
# verb helpers and the session's own verbs
WRITES = {
    "start_playback": lambda c: c.start_playback(device_id=DEV, uris=[URI]),
    "start_playback_context": lambda c: c.start_playback(device_id=DEV, context_uri="spotify:playlist:x"),
    "pause_playback": lambda c: c.pause_playback(device_id=DEV),
    "next_track": lambda c: c.next_track(device_id=DEV),
    "previous_track": lambda c: c.previous_track(device_id=DEV),
    "seek_track": lambda c: c.seek_track(1000, device_id=DEV),
    "volume": lambda c: c.volume(50, device_id=DEV),
    "repeat": lambda c: c.repeat("off", device_id=DEV),
    "shuffle": lambda c: c.shuffle(True, device_id=DEV),
    "add_to_queue": lambda c: c.add_to_queue(URI, device_id=DEV),
    "transfer_playback": lambda c: c.transfer_playback(DEV, force_play=True),
    "playlist_add_items": lambda c: c.playlist_add_items("pid", [URI]),
    "playlist_remove": lambda c: c.playlist_remove_all_occurrences_of_items("pid", [URI]),
    "playlist_replace": lambda c: c.playlist_replace_items("pid", [URI]),
    "playlist_change_details": lambda c: c.playlist_change_details("pid", name="x"),
    "user_playlist_create": lambda c: c.user_playlist_create("user-b", "x"),
    "follow_playlist": lambda c: c.current_user_follow_playlist("pid"),
    "unfollow_playlist": lambda c: c.current_user_unfollow_playlist("pid"),
    "saved_tracks_add": lambda c: c.current_user_saved_tracks_add([URI]),
    "saved_tracks_delete": lambda c: c.current_user_saved_tracks_delete([URI]),
    "follow_artists": lambda c: c.user_follow_artists(["a"]),
    "raw_put": lambda c: c._put("me/player/play"),
    "raw_post": lambda c: c._post("me/player/next"),
    "raw_delete": lambda c: c._delete("me/tracks", ids=URI),
    "session_put": lambda c: c._session.put("https://api.spotify.com/v1/me/player/play"),
    "session_post": lambda c: c._session.post("https://api.spotify.com/v1/me/player/next"),
    "session_delete": lambda c: c._session.delete("https://api.spotify.com/v1/me/tracks"),
    "session_patch": lambda c: c._session.request("PATCH", "https://api.spotify.com/v1/x"),
}

READS = {
    "me": lambda c: c.me(),
    "devices": lambda c: c.devices(),
    "current_playback": lambda c: c.current_playback(),
    "track": lambda c: c.track(URI),
    "playlist_items": lambda c: c.playlist_items("pid"),
    "queue": lambda c: c.queue(),
}


@pytest.mark.parametrize("state", ["off", "unreadable"])
@pytest.mark.parametrize("name", sorted(WRITES))
def test_every_write_is_refused_and_never_leaves_while_locked(account, state, name):
    if state == "off":
        sa.set_enabled(False, by="test")
    else:
        sa.LOCK_FILE.write_text("{nope")
    c = _client()
    with pytest.raises(sa.SecondAccountLocked):
        WRITES[name](c)
    assert account.writes() == [], f"{name} reached Spotify while the lock was {state}"
    assert sa.started() is None


@pytest.mark.parametrize("name", sorted(WRITES))
def test_every_write_goes_through_while_on(account, name):
    sa.set_enabled(True, by="test")
    WRITES[name](_client())
    assert len(account.writes()) == 1


@pytest.mark.parametrize("name", sorted(READS))
def test_reads_always_pass_even_while_locked(account, name):
    _off()
    READS[name](_client())
    assert account.requests and account.writes() == []


def test_a_change_of_the_lock_reaches_a_client_that_already_exists(account):
    """No stale "on": the same client object obeys his press at once."""
    c = _client()
    sa.set_enabled(True, by="test")
    c.volume(40, device_id=DEV)
    sa.set_enabled(False, by="test")
    with pytest.raises(sa.SecondAccountLocked):
        c.volume(40, device_id=DEV)
    sa.set_enabled(True, by="test")
    c.volume(40, device_id=DEV)
    assert len(account.writes()) == 2


def test_the_gate_never_patches_the_requests_module(account):
    """A falsy requests_session would make spotipy use the `requests` MODULE
    as its session; the client forces a real one, so gating it never gates
    the rest of the process."""
    from api.spotify_capture import SecondAccountSpotify
    before = requests.api.request
    c = SecondAccountSpotify(auth="t", requests_session=False)
    assert isinstance(c._session, requests.Session)
    assert requests.api.request is before
    _off()
    with pytest.raises(sa.SecondAccountLocked):
        c.next_track()
    # an ordinary Session elsewhere in the process is untouched by the lock
    requests.Session().put("https://api.spotify.com/v1/me/player/play")
    assert account.writes() == [("PUT", "/v1/me/player/play")]


def test_capture_client_is_the_gated_client(account, monkeypatch):
    from api import spotify_capture as cap
    from config import settings
    monkeypatch.setattr(settings, "spotipy_client_id", "client-id")
    monkeypatch.setattr(settings, "spotipy_client_secret", "client-secret")
    cap.TOKEN_CACHE.write_text(json.dumps({
        "access_token": "at-b", "refresh_token": "rt-b", "expires_at": int(time.time()) + 3600,
        "scope": cap.CAPTURE_SCOPES, "token_type": "Bearer"}))
    c = cap.capture_client()
    assert isinstance(c, cap.SecondAccountSpotify)
    _off()
    with pytest.raises(sa.SecondAccountLocked):
        c.start_playback(device_id=DEV, uris=[URI])
    assert c.me() == {"id": "user-b"}
    assert account.writes() == []


def test_the_sign_in_reads_account_b_through_the_gated_client(monkeypatch):
    from api import spotify_capture as cap
    from config import settings
    monkeypatch.setattr(settings, "spotipy_client_id", "client-id")
    monkeypatch.setattr(settings, "spotipy_client_secret", "client-secret")
    built = []
    real = cap.SecondAccountSpotify

    class Spy(real):
        def __init__(self, *a, **k):
            built.append(k.get("auth"))
            super().__init__(*a, **k)

        def me(self):
            return {"id": "user-b", "display_name": "B"}
    monkeypatch.setattr(cap, "SecondAccountSpotify", Spy)
    url = cap.authorize_url(now=10.0)
    state = url.split("state=")[1].split("&")[0]
    rec = cap.complete_sign_in("code", state, exchange=lambda c: {"access_token": "at-new",
                                                                  "refresh_token": "rt"},
                               main_id=lambda: "user-main", now=10.0)
    assert rec["user_id"] == "user-b" and built == ["at-new"]


# ═════════════════════════════════════════════════════════════════════════════
# 3. letting go — the one write the lock allows, and only of the system's own

def _started_then_locked(account, c):
    sa.set_enabled(True, by="test")
    c.start_playback(device_id=DEV, uris=[URI])
    assert sa.started()["device_id"] == DEV and sa.started()["uris"] == [URI]
    sa.set_enabled(False, by="test")
    account.requests.clear()


def test_turned_off_mid_play_the_systems_own_song_is_paused(account):
    c = _client()
    _started_then_locked(account, c)
    res = c.release_system_playback()
    assert res == {"paused": True, "why": "system_song"}
    assert account.writes() == [("PUT", "/v1/me/player/pause")]
    assert account.requests[-1][2] == {"device_id": DEV}
    assert sa.started() is None
    # and the permit was single use: the very next write is refused again
    with pytest.raises(sa.SecondAccountLocked):
        c.pause_playback(device_id=DEV)
    assert len(account.writes()) == 1


@pytest.mark.parametrize("theirs", [
    {"uri": THEIRS, "device_id": "phone", "is_playing": True},   # their phone
    {"uri": THEIRS, "device_id": DEV, "is_playing": True},       # their song, on the hidden player
    {"uri": URI, "device_id": "phone", "is_playing": True},      # the same song, on their phone
    {"uri": URI, "device_id": DEV, "is_playing": False},         # stopped already
])
def test_the_second_users_own_playback_is_never_touched(account, theirs):
    c = _client()
    _started_then_locked(account, c)
    account.playing = {**theirs, "at": time.monotonic()}
    res = c.release_system_playback()
    assert res["paused"] is False
    assert account.writes() == []
    assert sa.started() is None                   # the system has let go


def test_with_nothing_started_there_is_nothing_to_let_go_of(account):
    _off()
    account.play_theirs(device_id=DEV)
    assert _client().release_system_playback() == {"paused": False, "why": "nothing_started"}
    assert account.writes() == []


def test_the_end_of_the_systems_song_lets_go_of_its_continuation(account):
    c = _client()
    _started_then_locked(account, c)
    account.playing = {"uri": THEIRS, "device_id": DEV, "is_playing": True, "at": time.monotonic()}
    assert c.release_system_playback(end_of_song=True) == {"paused": True, "why": "continuation"}
    assert account.writes() == [("PUT", "/v1/me/player/pause")]


def test_a_context_started_play_is_recognised_and_released(account):
    """start_playback(context_uri=...) stores the context's own uri; Spotify
    then reports a TRACK playing inside that context, never the context uri
    itself as the item — release_system_playback must still recognise and
    pause it."""
    c = _client()
    sa.set_enabled(True, by="test")
    c.start_playback(device_id=DEV, context_uri="spotify:playlist:x")
    assert sa.started()["uris"] == ["spotify:playlist:x"]
    sa.set_enabled(False, by="test")
    account.requests.clear()
    account.playing = {"uri": URI, "device_id": DEV, "is_playing": True, "at": time.monotonic(),
                       "context": {"uri": "spotify:playlist:x"}}
    res = c.release_system_playback()
    assert res == {"paused": True, "why": "system_song"}
    assert account.writes() == [("PUT", "/v1/me/player/pause")]
    assert sa.started() is None


def test_someone_elses_play_in_a_different_context_is_never_paused(account):
    """The same system context-started play, but the second user has since
    switched account B to a DIFFERENT context — that must be left alone."""
    c = _client()
    sa.set_enabled(True, by="test")
    c.start_playback(device_id=DEV, context_uri="spotify:playlist:x")
    sa.set_enabled(False, by="test")
    account.requests.clear()
    account.playing = {"uri": THEIRS, "device_id": DEV, "is_playing": True, "at": time.monotonic(),
                       "context": {"uri": "spotify:playlist:y"}}
    res = c.release_system_playback()
    assert res["paused"] is False
    assert account.writes() == []
    assert sa.started() is None


def test_the_permit_is_this_threads_alone(account):
    """While a release's own pause is in flight on one thread, a pause from
    another thread is still refused."""
    c = _client()
    _started_then_locked(account, c)
    in_flight, finish = threading.Event(), threading.Event()
    refused: list[bool] = []

    def hold(m, path):
        if m == "PUT" and not in_flight.is_set():
            in_flight.set()
            finish.wait(5)
    account.on_request = hold

    t = threading.Thread(target=c.release_system_playback)
    t.start()
    assert in_flight.wait(5)
    try:
        c.pause_playback(device_id=DEV)
    except sa.SecondAccountLocked:
        refused.append(True)
    finish.set()
    t.join(5)
    assert refused == [True]
    assert account.writes() == [("PUT", "/v1/me/player/pause")]


def test_a_play_refused_in_flight_leaves_no_record(account, monkeypatch):
    """The lock flips between start_playback's own check and the request
    leaving: refused at the session, and nothing is left on record."""
    sa.set_enabled(True, by="test")
    c = _client()
    real_note = sa.note_started

    def note_then_lock(*a, **k):
        real_note(*a, **k)
        sa.set_enabled(False, by="test")
    monkeypatch.setattr(sa, "note_started", note_then_lock)
    with pytest.raises(sa.SecondAccountLocked):
        c.start_playback(device_id=DEV, uris=[URI])
    assert account.writes() == [] and sa.started() is None


# ═════════════════════════════════════════════════════════════════════════════
# 4. the capture lane, end to end over the real gateway and the real client

class LaneClock:
    """The lane's fake clock, which can also act at a moment in the song."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.at: list[tuple[float, object]] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.t += max(0.0, s)
        for when, fn in list(self.at):
            if self.t >= when:
                self.at.remove((when, fn))
                fn()
        await asyncio.sleep(0)


def _lane(tmp_path, monkeypatch, account, *, unlocked=None):
    from capture_lane import spotify as lane_spotify
    from capture_lane.spotify import CaptureGateway
    from tests.test_capture_lane import FakeReader, make
    monkeypatch.setattr(lane_spotify, "MIN_CONTROL_SPACING_S", 0.0)
    monkeypatch.setattr(lane_spotify, "READ_SPACING_S", 0.0)
    clock = LaneClock()
    account.clock = clock
    gw = CaptureGateway(_client())
    lane, _sp, rd, clock, d, analysed = make(tmp_path, monkeypatch, spotify=gw, clock=clock,
                                             reader=FakeReader(clock))
    if unlocked is not None:
        lane.deps.unlocked = unlocked
    return lane, clock, rd, d


def _learn(lane):
    from tests.test_capture_lane import job

    async def go():
        lane.learn(job())
        return await lane.wait()
    return asyncio.run(go())


def test_the_lane_learns_a_song_while_the_lock_is_on(tmp_path, monkeypatch, account):
    sa.set_enabled(True, by="test")
    lane, clock, rd, d = _lane(tmp_path, monkeypatch, account)
    out = _learn(lane)
    assert out.status == "ok", (out.reason, out.detail)
    assert account.writes() == [("PUT", "/v1/me/player/play"), ("PUT", "/v1/me/player/pause")]
    assert out.released == "system_song" and sa.started() is None


def test_off_the_lane_takes_no_song_and_touches_nothing(tmp_path, monkeypatch, account):
    from capture_lane.lane import Locked
    lane, clock, rd, d = _lane(tmp_path, monkeypatch, account)
    _off()
    from tests.test_capture_lane import job
    with pytest.raises(Locked):
        lane.learn(job())
    assert account.requests == [] and rd.started is None
    assert lane.status()["unlocked"] is False


def test_turned_off_mid_song_the_lane_stops_its_song_within_a_poll(tmp_path, monkeypatch, account):
    sa.set_enabled(True, by="test")
    lane, clock, rd, d = _lane(tmp_path, monkeypatch, account)
    off_at = []

    def off():
        sa.set_enabled(False, by="settings-page")
        off_at.append(len(account.requests))
    clock.at.append((clock.t + 8.0, off))
    out = _learn(lane)
    assert out.reason == "account_locked" and out.status == "failed"
    assert out.released == "system_song"
    after = [(m, p) for m, p, _ in account.requests[off_at[0]:] if m != "GET"]
    assert after == [("PUT", "/v1/me/player/pause")]
    assert account.playing["is_playing"] is False
    assert not list(d.glob("*.npz")) and sa.started() is None


def test_turned_off_after_the_second_user_took_over_nothing_of_theirs_is_paused(
        tmp_path, monkeypatch, account):
    sa.set_enabled(True, by="test")
    lane, clock, rd, d = _lane(tmp_path, monkeypatch, account)

    def theirs():
        account.play_theirs()                  # they hit play on their phone
        sa.set_enabled(False, by="settings-page")
    clock.at.append((clock.t + 8.0, theirs))
    out = _learn(lane)
    assert out.status == "failed"
    assert out.released == "other_device"
    assert account.writes() == [("PUT", "/v1/me/player/play")]       # no pause, ever
    assert account.playing == {**account.playing, "uri": THEIRS, "is_playing": True}


def test_the_client_holds_even_when_the_lanes_own_check_says_yes(tmp_path, monkeypatch, account):
    """The lane's check is a courtesy; the barrier is the client. With the
    lane told the lock is on while the record says off, the play is still
    refused before it leaves."""
    _off()
    lane, clock, rd, d = _lane(tmp_path, monkeypatch, account, unlocked=lambda: True)
    out = _learn(lane)
    assert out.reason == "account_locked" and account.writes() == []
    assert sa.started() is None


def test_a_low_volume_is_not_raised_while_locked(tmp_path, monkeypatch, account):
    _off()
    account.devices[0]["volume_percent"] = 40
    lane, clock, rd, d = _lane(tmp_path, monkeypatch, account, unlocked=lambda: True)
    out = _learn(lane)
    assert out.reason == "account_locked" and account.writes() == []


def test_the_lane_route_refuses_while_locked(tmp_path, monkeypatch, account):
    from capture_lane.app import create_app
    lane, *_ = _lane(tmp_path, monkeypatch, account)
    _off()
    from capture_lane import key as lane_key
    c = TestClient(create_app(lane=lane, key="k"))
    r = c.post("/learn", json={"uri": URI, "duration_ms": 20_000}, headers={lane_key.HEADER: "k"})
    assert r.status_code == 423 and r.json()["reason"] == "account_locked"
    assert account.requests == []


def test_the_lane_client_reads_423_as_the_lane_being_unusable():
    import httpx

    from services.jukebox.lane_client import LaneClient, LaneUnavailable

    def handler(request):
        return httpx.Response(423, json={"detail": "locked", "reason": "account_locked",
                                         "sentence": "The second Spotify account is switched off."})
    lc = LaneClient(base_url="http://lane", key="k", transport=httpx.MockTransport(handler))
    with pytest.raises(LaneUnavailable, match="switched off"):
        asyncio.run(lc.learn({"uri": URI}))


@pytest.mark.parametrize("playing,paused", [("system", True), ("theirs", False), (None, False)])
def test_at_its_start_the_lane_lets_go_of_a_play_from_before_a_crash(
        tmp_path, monkeypatch, account, playing, paused):
    lane, clock, rd, d = _lane(tmp_path, monkeypatch, account)
    sa.note_started(DEV, [URI])
    _off()
    if playing == "system":
        account.playing = {"uri": URI, "device_id": DEV, "is_playing": True, "at": clock()}
    elif playing == "theirs":
        account.play_theirs(device_id=DEV)
    res = asyncio.run(lane.recover())
    assert res["paused"] is paused
    assert account.writes() == ([("PUT", "/v1/me/player/pause")] if paused else [])
    assert sa.started() is None
    assert asyncio.run(lane.recover()) is None            # nothing left to let go of


def test_the_real_lane_process_recovers_at_start():
    """The real entrypoint (capture_lane/__main__.py) builds its app with
    recover_on_start=True — but what matters is that the app's lifespan
    actually RUNS Lane.recover() at startup, not that some source line looks
    right. Drive the real create_app()/lifespan over a fake lane and prove
    it."""
    from capture_lane.app import create_app

    class FakeLane:
        def __init__(self) -> None:
            self.calls = 0
            self.ran = threading.Event()

        async def recover(self):
            self.calls += 1
            self.ran.set()
            return None

    recovering = FakeLane()
    with TestClient(create_app(lane=recovering, key="k", recover_on_start=True)):
        assert recovering.ran.wait(5), "recover() was never called at startup"
    assert recovering.calls == 1

    not_recovering = FakeLane()
    with TestClient(create_app(lane=not_recovering, key="k", recover_on_start=False)):
        pass
    assert not_recovering.calls == 0


# ═════════════════════════════════════════════════════════════════════════════
# 5. SpotFX's lane users: locked = the hidden player can't be used

def test_the_jukebox_learner_sends_nothing_while_locked_and_songs_play_unanalysed():
    from tests.test_jukebox_learning import Rig, _run

    async def go():
        sa.set_enabled(False, by="settings-page")
        r = Rig()
        await r.start()
        eid = await r.add(0)
        assert r.entry(eid).ready and r.lane.learned_jobs == []
        assert not r.learner.available and "switched off" in r.learner.reason
        sa.set_enabled(True, by="settings-page")
        await r.run(1)
        assert r.learner.available and [j["uri"] for j in r.lane.learned_jobs] == [r.entry(eid).uri]
    _run(go())


def test_a_song_the_lane_gave_up_on_because_of_the_lock_uses_no_try():
    from services.jukebox import learning as L
    from tests.test_jukebox_learning import Rig, _run
    assert "account_locked" in L.NOT_A_TRY and "account_locked" not in L.LANE_DOWN

    async def go():
        r = Rig()
        await r.start()
        eid = await r.add(0)
        await r.run(1)
        assert r.lane.job is not None
        r.lane.finish("failed", "account_locked")
        await r.run(1)
        e = r.entry(eid)
        assert e.learn.attempts == 0 and e.learn.state in ("waiting", "learning")
        assert r.learner.down_until == 0.0
    _run(go())


def test_the_absorb_backlog_rests_while_locked_and_cancels_its_song():
    from services import absorb_lane as AL
    from tests.test_absorb_lane import World, _run
    assert "account_locked" in AL.NOT_A_TRY

    async def go():
        w = World()
        await w.tick()
        assert w.lane.job is not None                    # it was learning
        sa.set_enabled(False, by="settings-page")
        await w.tick()
        assert w.backlog.state == "resting" and "switched off" in w.backlog.reason
        assert w.lane.cancelled and w.lane.job is None
        jobs = len(w.lane.jobs)
        await w.tick()
        assert len(w.lane.jobs) == jobs                  # nothing new while locked
    _run(go())


# ═════════════════════════════════════════════════════════════════════════════
# 6. SPECTRA's switch

@pytest.fixture
def spectra():
    from fastapi import FastAPI

    from spectra.api import second_account as api
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_the_switch_reads_off_when_nothing_was_ever_set(spectra):
    _off()
    st = spectra.get("/api/second-account").json()
    assert st["enabled"] is False and st["state"] == "off" and "only reads" in st["sentence"]


def test_the_switch_turns_on_and_off(spectra):
    _off()
    st = spectra.put("/api/second-account", json={"enabled": True}).json()
    assert st["enabled"] is True and st["changed_by"] == "settings-page"
    assert sa.write_allowed()
    st = spectra.put("/api/second-account", json={"enabled": False}).json()
    assert st["enabled"] is False and not sa.write_allowed()
    assert [h["enabled"] for h in st["history"]] == [True, False]


def test_turning_it_off_while_the_system_plays_says_it_is_letting_go(spectra):
    sa.set_enabled(True, by="test")
    sa.note_started(DEV, [URI])
    st = spectra.put("/api/second-account", json={"enabled": False}).json()
    assert "letting go" in st["letting_go"] and st["system_started"]["uris"] == [URI]


@pytest.mark.parametrize("body", [{"enabled": "true"}, {"enabled": 1}, {}, {"enabled": None},
                                  {"enabled": True, "source": "sonic"}])
def test_the_switch_takes_only_a_real_true_or_false(spectra, body):
    _off()
    assert spectra.put("/api/second-account", json=body).status_code == 422
    assert sa.read().state == sa.OFF


def test_an_unreadable_record_reads_as_locked_and_says_so(spectra):
    sa.LOCK_FILE.write_text("{bad")
    st = spectra.get("/api/second-account").json()
    assert st["enabled"] is False and st["state"] == "unreadable" and "can't be read" in st["sentence"]


def test_the_switch_is_mounted_on_spectra():
    from spectra.app import create_app
    assert TestClient(create_app()).get("/api/second-account").status_code == 200


def test_sonic_cannot_reach_the_switch():
    """A barrier protecting another person's music moves only on his press:
    no Sonic operation names it (spectra/api/second_account.py's docstring)."""
    from spectra.services import settings_agent
    for name, op in settings_agent.ALL_OPERATIONS.items():
        text = f"{name} {op.summary} {op.instructions}".lower()
        assert "second account" not in text and "second_account" not in text, name


# ═════════════════════════════════════════════════════════════════════════════
# 7. THE GUARD — nothing builds an account-B client any other way

# What hands out account B — its client, the class, its OAuth builder, its
# token file and scopes. Everything else api/spotify_capture.py offers (the
# sign-in, `status`, `signed_in_user`, the main account's id) builds no
# account-B client, so anyone may use it.
RESTRICTED = {"capture_client", "SecondAccountSpotify", "_oauth", "TOKEN_CACHE",
              "CAPTURE_SCOPES"}
# the one module allowed to ask for the client
CLIENT_USERS = {"capture_lane/spotify.py": {"capture_client"}}
HOME = "api/spotify_capture.py"
# the redirect URI is the setting's own definition and its one reader
REDIRECT_OK = {"config.py", HOME}
# the gate's insides belong to the gated class alone
PRIVATE = ("_release_permit", "_permitted")


def _scan(rel: str, src: str) -> list[str]:
    """Every place a source reaches account B's client or credentials
    without being allowed to, or reaches into the gate."""
    if rel == HOME:
        return _scan_home(src)
    problems: list[str] = []
    tree = ast.parse(src)
    allowed = CLIENT_USERS.get(rel, set())
    aliases: set[str] = set()
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, ast.ImportFrom) and node.module == "api.spotify_capture":
            for a in node.names:
                if a.name in RESTRICTED and a.name not in allowed:
                    problems.append(f"{rel}:{line} imports {a.name} from api.spotify_capture")
        elif isinstance(node, ast.ImportFrom) and node.module == "api":
            aliases |= {a.asname or a.name for a in node.names if a.name == "spotify_capture"}
        elif isinstance(node, ast.Import):
            aliases |= {a.asname or a.name for a in node.names if a.name == "api.spotify_capture"}
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, ast.Attribute):
            owner = node.value
            dotted = (getattr(owner, "id", None)
                      or (f"{getattr(owner.value, 'id', '')}.{owner.attr}"
                          if isinstance(owner, ast.Attribute) else None))
            if dotted in aliases and node.attr in RESTRICTED and node.attr not in allowed:
                problems.append(f"{rel}:{line} reaches {dotted}.{node.attr}")
            if node.attr in PRIVATE:
                problems.append(f"{rel}:{line} reaches the gate's {node.attr}")
            if node.attr == "spotipy_capture_redirect_uri" and rel not in REDIRECT_OK:
                problems.append(f"{rel}:{line} reads account B's redirect URI")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if ".spotify_token_cache_capture" in node.value:
                problems.append(f"{rel}:{line} names account B's token file")
    return problems


def _scan_home(src: str) -> list[str]:
    """In the home module itself: every spotipy client built is the gated
    one — except the MAIN account's read-only `me()` in _main_account_id —
    and every SecondAccountSpotify gets its session from spotipy (never a
    falsy requests_session, which would gate the `requests` module)."""
    problems: list[str] = []
    for fn in ast.walk(ast.parse(src)):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for call in ast.walk(fn):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "Spotify"
                    and getattr(call.func.value, "id", "") == "spotipy"
                    and fn.name != "_main_account_id"):
                problems.append(f"{HOME}:{call.lineno} builds a plain spotipy.Spotify in {fn.name}")
    return problems


def _sources():
    skip = {"tests", ".venv", "node_modules", "storage", ".git", "web", "spectra/web"}
    for p in sorted(REPO.rglob("*.py")):
        rel = p.relative_to(REPO).as_posix()
        if any(rel == s or rel.startswith(s + "/") for s in skip):
            continue
        yield rel, p.read_text(encoding="utf-8", errors="replace")


def test_no_module_reaches_account_b_except_through_the_gated_client():
    problems = [x for rel, src in _sources() for x in _scan(rel, src)]
    assert problems == [], "\n".join(problems)


def test_the_capture_lane_writes_only_through_its_gateway():
    """No module of the lane process calls a spotipy write method itself."""
    writes = {"start_playback", "pause_playback", "next_track", "previous_track",
              "add_to_queue", "transfer_playback", "volume", "seek_track", "_put", "_post",
              "_delete", "_session"}
    for p in (REPO / "capture_lane").glob("*.py"):
        if p.name == "spotify.py":
            continue
        tree = ast.parse(p.read_text())
        hits = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in writes]
        assert hits == [], f"{p.name} calls {hits}"


@pytest.mark.parametrize("rel,src", [
    ("services/sneaky.py",
     "import spotipy\nfrom api.spotify_capture import TOKEN_CACHE\n"
     "sp = spotipy.Spotify(auth_manager=x)\n"),
    ("services/sneaky.py", "from api.spotify_capture import capture_client\nc = capture_client()\n"),
    ("services/sneaky.py", "from api.spotify_capture import SecondAccountSpotify as S\n"),
    ("services/sneaky.py", "path = 'storage/.spotify_token_cache_capture'\n"),
    ("services/sneaky.py", "from api import spotify_capture\nspotify_capture._oauth(None)\n"),
    ("services/sneaky.py", "from api import spotify_capture as sc\nsc.capture_client()\n"),
    ("services/sneaky.py", "import api.spotify_capture\napi.spotify_capture.capture_client()\n"),
    ("services/sneaky.py", "from config import settings\nu = settings.spotipy_capture_redirect_uri\n"),
    ("capture_lane/lane.py", "client._release_permit.armed = True\n"),
    ("capture_lane/lane.py", "from api.spotify_capture import capture_client\n"),
    ("api/spotify_capture.py",
     "import spotipy\ndef capture_client():\n    return spotipy.Spotify(auth='x')\n"),
])
def test_the_guard_fails_on_a_bypass(rel, src):
    """Red controls: each of these would reach account B round the gate, and
    the guard names it."""
    assert _scan(rel, src) != []
