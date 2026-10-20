"""Absorb Music's Spotify gateway (services/absorb_spotify.py) against a fake
spotipy client: link parsing, paged reads, what is left out, writes in
batches of 100, and find-or-create for Recently Captured. No network."""
from __future__ import annotations

import pytest

from services import absorb_spotify
from services.absorb_spotify import SpotifyGateway, parse_playlist_id


@pytest.fixture(autouse=True)
def _no_spacing(monkeypatch):
    monkeypatch.setattr(absorb_spotify, "MIN_CONTROL_SPACING_S", 0.0)


@pytest.mark.parametrize("link, pid", [
    ("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M", "37i9dQZF1DXcBWIGoYBM5M"),
    ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc123",
     "37i9dQZF1DXcBWIGoYBM5M"),
    ("37i9dQZF1DXcBWIGoYBM5M", "37i9dQZF1DXcBWIGoYBM5M"),
    ("", None),
    ("spotify:album:37i9dQZF1DXcBWIGoYBM5M", None),
    ("not a link", None),
])
def test_parse_playlist_id(link, pid):
    assert parse_playlist_id(link) == pid


class FakeSp:
    def __init__(self, items, user_playlists=()):
        self.items = items
        self._user_playlists = list(user_playlists)
        self.calls = []

    def playlist_items(self, pid, offset=0, limit=100, fields=None):
        self.calls.append(("playlist_items", offset))
        page = self.items[offset:offset + limit]
        return {"items": page, "next": "more" if offset + limit < len(self.items) else None}

    def playlist_remove_all_occurrences_of_items(self, pid, uris):
        self.calls.append(("remove", list(uris)))
        return {"snapshot_id": f"s{len(self.calls)}"}

    def playlist_add_items(self, pid, uris, position=None):
        self.calls.append(("add", list(uris), position))
        return {"snapshot_id": f"s{len(self.calls)}"}

    def playlist(self, pid, fields=None):
        self.calls.append(("playlist", pid))
        if pid == "gone":
            raise RuntimeError("404")
        return {"id": pid, "name": "Recently Captured" if pid == "rc-known" else "x",
                "snapshot_id": "snap"}

    def me(self):
        return {"id": "javi"}

    def user_playlists(self, user, limit=50, offset=0):
        page = self._user_playlists[offset:offset + limit]
        return {"items": page, "next": "more" if offset + limit < len(self._user_playlists) else None}

    def user_playlist_create(self, user, name, public, description):
        self.calls.append(("create", name, public))
        return {"id": "rc-new"}

    def devices(self):
        return {"devices": [{"name": "serenity", "id": "dev1"}, {"name": "Phone", "id": "p"}]}

    def start_playback(self, device_id=None, uris=None, context_uri=None):
        self.calls.append(("start_playback", device_id, list(uris or []), context_uri))

    def pause_playback(self, device_id=None):
        self.calls.append(("pause", device_id))


def _track(n, kind="track"):
    return {"track": {"uri": f"spotify:{kind}:{n}", "name": f"Song {n}",
                      "duration_ms": 1000, "artists": [{"name": "A"}]}}


def test_playlist_tracks_pages_dedupes_and_keeps_only_tracks():
    items = [_track(i) for i in range(230)] + [_track(5), _track("ep", "episode"),
                                               {"track": {"uri": "spotify:local:x"}},
                                               {"track": None}]
    sp = FakeSp(items)
    out = SpotifyGateway(sp).playlist_tracks("pid")
    assert [t["uri"] for t in out] == [f"spotify:track:{i}" for i in range(230)]
    assert out[0]["title"] == "A — Song 0"
    assert [c for c in sp.calls if c[0] == "playlist_items"] == \
        [("playlist_items", 0), ("playlist_items", 100), ("playlist_items", 200)]


def test_writes_go_in_batches_of_a_hundred():
    sp = FakeSp([])
    gw = SpotifyGateway(sp)
    uris = [f"spotify:track:{i}" for i in range(250)]
    gw.remove_tracks("pid", uris)
    gw.add_tracks_top("rc", uris)
    removes = [c for c in sp.calls if c[0] == "remove"]
    adds = [c for c in sp.calls if c[0] == "add"]
    assert [len(c[1]) for c in removes] == [100, 100, 50]
    assert [len(c[1]) for c in adds] == [100, 100, 50] and all(c[2] == 0 for c in adds)


def test_tracks_beyond_returns_what_a_trim_removes():
    sp = FakeSp([_track(i) for i in range(5)])
    assert SpotifyGateway(sp).tracks_beyond("rc", 3) == ["spotify:track:3", "spotify:track:4"]


def test_play_sends_uris_never_a_context():
    sp = FakeSp([])
    gw = SpotifyGateway(sp)
    gw.play("dev1", ["spotify:track:1", "spotify:track:2"])
    assert sp.calls[-1] == ("start_playback", "dev1", ["spotify:track:1", "spotify:track:2"], None)
    assert gw.device_id("Serenity") == "dev1"            # case-insensitive
    assert gw.device_id("Kitchen") is None


def test_find_or_create_reuses_then_finds_then_creates():
    owned = {"name": "Recently Captured", "id": "rc-found", "owner": {"id": "javi"}}
    theirs = {"name": "Recently Captured", "id": "rc-theirs", "owner": {"id": "someone"}}
    gw = SpotifyGateway(FakeSp([], [theirs, owned]))
    assert gw.find_or_create_playlist("Recently Captured", "rc-known") == "rc-known"
    assert gw.find_or_create_playlist("Recently Captured", "gone") == "rc-found"
    sp = FakeSp([], [theirs])
    assert SpotifyGateway(sp).find_or_create_playlist("Recently Captured") == "rc-new"
    assert ("create", "Recently Captured", False) in sp.calls
