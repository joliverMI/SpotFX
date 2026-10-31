"""The Jukebox's Spotify gateway (services/jukebox/gateway.py): every call
spaced at least 0.5 s after the one before it — reads included — the set
read through `/items` in order with duplicates kept, and a read-only wrapper
that refuses every write before it reaches Spotify."""
from __future__ import annotations

import pytest

from services.jukebox import gateway as gw_mod
from services.jukebox.gateway import (
    JukeboxGateway, MIN_CALL_SPACING_S, ReadOnlyGateway, parse_track_uri,
)


class Clock:
    def __init__(self) -> None:
        self.t = 100.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def _track(i: int, local: bool = False, uri: str = "") -> dict:
    return {"track": {"uri": uri or f"spotify:track:t{i:019d}", "name": f"Song {i}",
                      "duration_ms": 200_000 + i, "is_local": local,
                      "artists": [{"name": "A"}, {"name": "B"}]}}


class FakeSpotipy:
    """Records when each method was called; one 'call' advances the clock by
    `cost` seconds (a real request takes time)."""

    def __init__(self, clock: Clock, cost: float = 0.05) -> None:
        self.clock, self.cost = clock, cost
        self.times: list[tuple[str, float]] = []
        self.pages: list[dict] = []
        self.items_args: list[dict] = []
        self.track_data: dict = {}
        self.artist_data: dict = {}
        self.artist_calls: list[str] = []

    def _hit(self, name: str) -> None:
        self.times.append((name, self.clock.t))
        self.clock.t += self.cost

    def devices(self):
        self._hit("devices")
        return {"devices": [{"name": "Serenity", "id": "d1"}]}

    def add_to_queue(self, uri, device_id=None):
        self._hit("add_to_queue")

    def queue(self):
        self._hit("queue")
        return {"currently_playing": {"uri": "spotify:track:a"},
                "queue": [{"uri": "spotify:track:b"}, {"uri": "spotify:track:c"}]}

    def next_track(self, device_id=None):
        self._hit("next_track")

    def current_playback(self):
        self._hit("current_playback")
        return {"item": {"uri": "spotify:track:a", "duration_ms": 1000}, "is_playing": True,
                "progress_ms": 10, "device": {"name": "Serenity"},
                "context": {"uri": "spotify:playlist:p"}, "shuffle_state": True,
                "smart_shuffle": False, "repeat_state": "context"}

    def playlist_items(self, pid, **kw):
        self._hit("playlist_items")
        self.items_args.append(kw)
        return self.pages[kw["offset"] // 100]

    def track(self, tid):
        self._hit("track")
        return dict(self.track_data)

    def artist(self, artist_id):
        self._hit("artist")
        self.artist_calls.append(artist_id)
        return dict(self.artist_data.get(artist_id) or {})


def test_every_call_is_spaced_reads_included():
    clock = Clock()
    sp = FakeSpotipy(clock)
    g = JukeboxGateway(sp, clock=clock, sleep=clock.sleep)
    g.device_id("Serenity")
    g.queue()
    g.add_to_queue("spotify:track:x")
    g.queue()
    g.next_track()
    g.playback()
    starts = [t for _, t in sp.times]
    ends = [t + sp.cost for t in starts]
    for prev_end, start in zip(ends, starts[1:]):
        assert start - prev_end >= MIN_CALL_SPACING_S - 1e-9
    assert len(clock.slept) == 5


def test_a_call_after_a_long_gap_does_not_wait():
    clock = Clock()
    sp = FakeSpotipy(clock)
    g = JukeboxGateway(sp, clock=clock, sleep=clock.sleep)
    g.queue()
    clock.t += 5
    g.queue()
    assert clock.slept == []


def test_a_failing_call_still_counts_for_spacing():
    clock = Clock()
    sp = FakeSpotipy(clock)

    def boom(*a, **k):
        sp._hit("add_to_queue")
        raise RuntimeError("429")
    sp.add_to_queue = boom
    g = JukeboxGateway(sp, clock=clock, sleep=clock.sleep)
    with pytest.raises(RuntimeError):
        g.add_to_queue("spotify:track:x")
    g.queue()
    assert clock.slept and clock.slept[0] == pytest.approx(MIN_CALL_SPACING_S)


def test_the_set_is_read_through_items_in_order_with_duplicates_kept():
    clock = Clock()
    sp = FakeSpotipy(clock)
    first = [_track(i) for i in range(100)]
    second = [_track(100), _track(0), _track(101, local=True),
              {"track": {"uri": "spotify:episode:podcast0000000000", "name": "Ep"}},
              {"track": None}, {"item": _track(102)["track"]}]
    sp.pages = [{"items": first, "next": "more"}, {"items": second, "next": None}]
    g = JukeboxGateway(sp, clock=clock, sleep=clock.sleep)
    items = g.playlist_items("p")
    assert len(items) == 103
    assert items[101]["uri"] == items[0]["uri"]          # the duplicate is kept, in place
    assert items[-1]["uri"].endswith("102")              # an `item` key is read too
    assert items[0]["artist"] == "A, B" and items[0]["duration_ms"] == 200_000
    assert [a["offset"] for a in sp.items_args] == [0, 100]
    assert all(a["limit"] == 100 for a in sp.items_args)


def test_spotipys_playlist_items_calls_the_items_path():
    """The study asked for `/items` from day one (the February 2026 rename);
    spotipy's playlist_items is the path the gateway reads through."""
    import spotipy
    seen = {}

    class S(spotipy.Spotify):
        def _get(self, url, args=None, payload=None, **kwargs):
            seen["url"] = url
            return {"items": [], "next": None}
    S(auth="x").playlist_items("abc", limit=100, offset=0)
    assert seen["url"] == "playlists/abc/items"


def test_playback_and_queue_are_reduced_to_what_the_engine_reads():
    clock = Clock()
    g = JukeboxGateway(FakeSpotipy(clock), clock=clock, sleep=clock.sleep)
    pb = g.playback()
    assert pb["shuffle"] is True and pb["context_uri"] == "spotify:playlist:p"
    assert g.queue() == {"current": "spotify:track:a",
                         "queue": ["spotify:track:b", "spotify:track:c"]}


def test_track_genres_looks_up_the_tracks_primary_artist():
    clock = Clock()
    sp = FakeSpotipy(clock)
    sp.track_data = {"artists": [{"id": "jbx-genre-test-artist-1", "name": "Test Artist"}]}
    sp.artist_data = {"jbx-genre-test-artist-1": {"genres": ["synthwave", "chillwave"]}}
    g = JukeboxGateway(sp, clock=clock, sleep=clock.sleep)
    assert g.track_genres("spotify:track:xyz") == ["synthwave", "chillwave"]
    assert sp.artist_calls == ["jbx-genre-test-artist-1"]


def test_track_genres_is_empty_when_the_track_has_no_artist():
    clock = Clock()
    sp = FakeSpotipy(clock)
    sp.track_data = {"artists": []}
    g = JukeboxGateway(sp, clock=clock, sleep=clock.sleep)
    assert g.track_genres("spotify:track:xyz") == []
    assert sp.artist_calls == []


def test_track_genres_artist_read_is_spaced_and_locked_like_every_other_call():
    """The genre lookup makes TWO Spotify calls (track, then artist) — both
    must obey the gateway's own spacing/lock contract, not just the first."""
    clock = Clock()
    sp = FakeSpotipy(clock)
    sp.track_data = {"artists": [{"id": "jbx-genre-spacing-test", "name": "Spacing Artist"}]}
    sp.artist_data = {"jbx-genre-spacing-test": {"genres": ["lofi"]}}
    g = JukeboxGateway(sp, clock=clock, sleep=clock.sleep)
    g.queue()                                  # an earlier call, to prime spacing
    assert g.track_genres("spotify:track:xyz") == ["lofi"]
    assert [name for name, _ in sp.times] == ["queue", "track", "artist"]
    starts = [t for _, t in sp.times]
    ends = [t + sp.cost for t in starts]
    for prev_end, start in zip(ends, starts[1:]):
        assert start - prev_end >= MIN_CALL_SPACING_S - 1e-9
    assert len(clock.slept) == 2                # before `track`, and before `artist`


@pytest.mark.parametrize("link, expected", [
    ("spotify:track:4uLU6hMCjMI75M1A2tKUQC", "spotify:track:4uLU6hMCjMI75M1A2tKUQC"),
    ("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC?si=abc",
     "spotify:track:4uLU6hMCjMI75M1A2tKUQC"),
    ("https://open.spotify.com/intl-de/track/4uLU6hMCjMI75M1A2tKUQC",
     "spotify:track:4uLU6hMCjMI75M1A2tKUQC"),
    ("4uLU6hMCjMI75M1A2tKUQC", "spotify:track:4uLU6hMCjMI75M1A2tKUQC"),
    ("spotify:playlist:4uLU6hMCjMI75M1A2tKUQC", None),
    ("not a link", None),
    ("", None),
])
def test_parse_track_uri(link, expected):
    assert parse_track_uri(link) == expected


def test_the_read_only_gateway_refuses_every_write():
    calls = []

    class Inner:
        def __getattr__(self, name):
            def f(*a, **k):
                calls.append(name)
            return f
    ro = ReadOnlyGateway(Inner())
    ro.playlist_items("p")
    ro.resolve_playlist("p")
    for name in ("add_to_queue", "next_track", "start_context", "set_shuffle",
                 "set_repeat", "pause", "reorder"):
        with pytest.raises(PermissionError):
            getattr(ro, name)
    assert calls == ["playlist_items", "resolve_playlist"]


def test_every_public_write_is_outside_the_read_only_allowlist():
    writes = {n for n in dir(JukeboxGateway) if not n.startswith("_")} - gw_mod.READ_ONLY_METHODS
    assert writes == {"add_to_queue", "next_track", "start_context", "set_shuffle",
                      "set_repeat", "pause", "reorder"}
