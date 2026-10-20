"""The recapture playlist's id is CACHED (services/recapture_playlist.py,
report data/absorb-music-plan §7.1 / §14 item 3).

remove_track() runs once per captured song, and it used to find the
"SpotFX Recapture" playlist by paging through every one of his playlists,
50 at a time, every time. Now the lookup is remembered: a found id for
_PLAYLIST_FOUND_TTL_S, "not there" for the shorter _PLAYLIST_ABSENT_TTL_S,
and a failed removal forgets it.

No Spotify: get_spotify() is replaced by a fake that counts every call."""
from __future__ import annotations

import pytest

import services.recapture_playlist as rp

ME = "javi"
PID = "recapture-playlist-id"


class FakeSpotify:
    def __init__(self, *, pages: int = 3, has_playlist: bool = True,
                 remove_raises: bool = False) -> None:
        self.me_calls = 0
        self.page_calls = 0
        self.removed: list[tuple[str, list[str]]] = []
        self.created: list[str] = []
        self.remove_raises = remove_raises
        self._items: list[dict] = [
            {"id": f"other-{i}", "name": f"Mix {i}", "owner": {"id": ME}}
            for i in range(50 * pages - 1)
        ]
        if has_playlist:
            self._items.append({"id": PID, "name": rp.PLAYLIST_NAME, "owner": {"id": ME}})

    def me(self):
        self.me_calls += 1
        return {"id": ME}

    def user_playlists(self, user, limit=50, offset=0):
        assert user == ME
        self.page_calls += 1
        items = self._items[offset:offset + limit]
        more = offset + limit < len(self._items)
        return {"items": items, "next": "more" if more else None}

    def playlist_remove_all_occurrences_of_items(self, pid, uris):
        if self.remove_raises:
            raise RuntimeError("404 not found")
        self.removed.append((pid, list(uris)))

    def user_playlist_create(self, user, name, public, description):
        self.created.append(name)
        new = {"id": "created-id", "name": name, "owner": {"id": ME}}
        self._items.append(new)
        return new


@pytest.fixture
def spotify(monkeypatch):
    # raising=False: the cache exists only since the fix, and this file is
    # run against the pre-fix module as its red control.
    monkeypatch.setattr(rp, "_playlist_cache", None, raising=False)

    def install(fake: FakeSpotify) -> FakeSpotify:
        monkeypatch.setattr(rp, "get_spotify", lambda: fake)
        return fake

    return install


def _expire_cache():
    pid, _expiry = rp._playlist_cache
    rp._playlist_cache = (pid, 0.0)


def test_removing_many_songs_pages_his_playlists_once(spotify):
    """THE DEFECT: each removal used to re-page all three pages."""
    sp = spotify(FakeSpotify(pages=3))
    uris = [f"spotify:track:t{i}" for i in range(5)]
    for uri in uris:
        assert rp.remove_track(uri) is True
    assert sp.page_calls == 3        # one full lookup, for the first song only
    assert sp.me_calls == 1
    assert sp.removed == [(PID, [u]) for u in uris]


def test_a_found_id_is_looked_up_again_once_it_expires(spotify):
    sp = spotify(FakeSpotify(pages=2))
    rp.remove_track("spotify:track:a")
    _expire_cache()
    rp.remove_track("spotify:track:b")
    assert sp.page_calls == 4


def test_an_absent_playlist_is_remembered_briefly_too(spotify):
    sp = spotify(FakeSpotify(pages=2, has_playlist=False))
    assert rp.remove_track("spotify:track:a") is False
    assert rp.remove_track("spotify:track:b") is False
    assert sp.page_calls == 2
    assert rp._PLAYLIST_ABSENT_TTL_S < rp._PLAYLIST_FOUND_TTL_S
    _expire_cache()
    assert rp.remove_track("spotify:track:c") is False
    assert sp.page_calls == 4


def test_a_failed_removal_forgets_the_cached_id(spotify):
    sp = spotify(FakeSpotify(pages=1, remove_raises=True))
    assert rp.remove_track("spotify:track:a") is False
    assert rp._playlist_cache is None
    sp.remove_raises = False
    assert rp.remove_track("spotify:track:b") is True
    assert sp.page_calls == 2


def test_a_non_track_uri_never_reaches_spotify(spotify):
    sp = spotify(FakeSpotify())
    assert rp.remove_track("ledfx:artist:title") is False
    assert (sp.me_calls, sp.page_calls) == (0, 0)


def test_find_or_create_does_not_duplicate_on_a_stale_absent_answer(spotify):
    """A cached "not there" is fine for skipping a removal, but creating the
    playlist on it could make a second one if it has appeared since."""
    sp = spotify(FakeSpotify(pages=1, has_playlist=False))
    assert rp.remove_track("spotify:track:a") is False          # caches "absent"
    sp._items.append({"id": PID, "name": rp.PLAYLIST_NAME, "owner": {"id": ME}})
    assert rp.find_or_create_playlist(sp) == PID
    assert sp.created == []


def test_find_or_create_remembers_what_it_created(spotify):
    sp = spotify(FakeSpotify(pages=1, has_playlist=False))
    assert rp.find_or_create_playlist(sp) == "created-id"
    pages = sp.page_calls
    assert rp.remove_track("spotify:track:a") is True
    assert sp.page_calls == pages
    assert sp.removed == [("created-id", ["spotify:track:a"])]
