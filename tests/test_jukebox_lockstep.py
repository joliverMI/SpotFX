"""§12's vote-farming guard (the abuse table: "the master flags phones that
always vote identically within a second"): services/jukebox/guests.py's
`lockstep`, driven on built guest books, then through the real guest vote
call over the fake Jukebox world, where the Guests tab's phone list carries
the flag."""
from __future__ import annotations

import asyncio

from models.jukebox import GuestBook, GuestPhone
from services.jukebox import guests as G, store
from tests.test_jukebox_credits_play import _setup
from tests.test_jukebox_guest_add import _night, _phone

W, N = G.LOCKSTEP_WINDOW_MS, G.LOCKSTEP_MIN_PLAYS


def _run(coro):
    return asyncio.run(coro)


def _book(*names: str) -> GuestBook:
    return GuestBook(phones={n: GuestPhone(id=n, name=n.title(), joined=True) for n in names})


def _cast(book: GuestBook, play: int, **votes: tuple[int, int]) -> None:
    """Votes on song `play`: phone=(+1 or -1, at ms)."""
    key = f"spotify:track:s{play}@{play * 300_000}"
    book.votes[key] = {p: v for p, (v, _) in votes.items()}
    book.vote_ms[key] = {p: t for p, (_, t) in votes.items()}


def _both(book: GuestBook, plays: int, gap_ms: int = 400, first: int = 0) -> None:
    for i in range(first, first + plays):
        t = i * 300_000 + 60_000
        _cast(book, i, ana=(1, t), ben=(1, t + gap_ms))


def test_two_phones_voting_alike_within_a_second_on_every_song_are_flagged():
    book = _book("ana", "ben", "cy")
    _both(book, N)
    for i in range(N):                                       # cy votes too, but on her own time
        book.votes[f"spotify:track:s{i}@{i * 300_000}"]["cy"] = 1
        book.vote_ms[f"spotify:track:s{i}@{i * 300_000}"]["cy"] = i * 300_000 + 90_000
    assert G.lockstep(book) == {"ana": [("ben", N)], "ben": [("ana", N)]}


def test_fewer_songs_than_the_minimum_is_no_flag():
    book = _book("ana", "ben")
    _both(book, N - 1)
    assert G.lockstep(book) == {}


def test_one_song_apart_breaks_always():
    t = 2 * 300_000 + 60_000
    for odd in ({"ana": (1, t), "ben": (-1, t + 200)},              # the other way
                {"ana": (1, t), "ben": (1, t + W + 1)},              # more than a second apart
                {"ana": (1, t)}):                                    # only one voted
        book = _book("ana", "ben")
        _both(book, N + 1, first=1)                                  # N alike besides the odd one
        _cast(book, 2, **odd)                                        # inside the span
        assert G.lockstep(book) == {}, odd
        _both(book, 1, first=2)                                      # the same song, alike: flagged
        assert G.lockstep(book)["ana"] == [("ben", N + 1)], odd
    book = _book("ana", "ben")
    _both(book, N, gap_ms=W)                                         # exactly a second apart counts
    assert G.lockstep(book)["ana"] == [("ben", N)]


def test_only_the_span_both_were_voting_counts():
    book = _book("ana", "ben")
    _cast(book, 0, ana=(1, 60_000))                          # before ben's first vote (not here yet)
    _both(book, N, first=1)
    _cast(book, N + 1, ben=(-1, (N + 1) * 300_000))          # after ana's last vote (gone home)
    assert G.lockstep(book)["ben"] == [("ana", N)]


def test_a_song_one_of_them_added_is_left_out():
    book = _book("ana", "ben")
    _both(book, N)
    key = f"spotify:track:s{N}@{N * 300_000}"                 # ana's own song: only ben can vote
    _cast(book, N, ben=(1, N * 300_000 + 60_000))
    book.play_by[key] = "ana"
    _cast(book, N + 1, ana=(1, (N + 1) * 300_000 + 60_000), ben=(1, (N + 1) * 300_000 + 60_300))
    assert G.lockstep(book)["ana"] == [("ben", N + 1)]
    del book.play_by[key]                                    # had anyone else added it: ana's silence counts
    assert G.lockstep(book) == {}


def test_three_phones_name_each_other_and_merged_or_blocked_phones_are_not_flagged():
    book = _book("ana", "ben", "cy")
    for i in range(N):
        t = i * 300_000 + 60_000
        _cast(book, i, ana=(1, t), ben=(1, t + 300), cy=(1, t + 600))
    flags = G.lockstep(book)
    assert [q for q, _ in flags["ana"]] == ["ben", "cy"] and [q for q, _ in flags["cy"]] == ["ana", "ben"]
    book.phones["cy"].merged_into = "ana"
    assert set(G.lockstep(book)) == {"ana", "ben"}
    book.phones["ben"].blocked = True
    assert G.lockstep(book) == {}


def test_a_vote_with_no_time_is_never_compared():
    book = _book("ana", "ben")
    _both(book, N, first=1)
    _cast(book, 3, ana=(1, 3 * 300_000 + 60_000), ben=(-1, 0))
    del book.vote_ms[f"spotify:track:s3@{3 * 300_000}"]["ben"]  # cast before times were kept
    assert G.lockstep(book) == {}                            # one song short now — but never "different"
    _both(book, 1, first=N + 1)
    assert G.lockstep(book)["ana"] == [("ben", N)]


# ═══ through the real guest calls ═══════════════════════════════════════════

async def _next_song(w) -> None:
    plays = w.runner.night.plays
    while w.runner.night.plays == plays:
        await w.run(5)


def test_the_guests_tab_flags_two_phones_tapping_together_and_a_merge_clears_it():
    async def go():
        w = await _night(set_s=120)
        g = _setup(w)
        ana, ben, cy = await _phone(g), await _phone(g), await _phone(g)
        for i in range(N):
            assert (await g.vote(ana, "up"))[0] == 200
            w.clock.t += 0.4                                            # ben taps 400 ms later
            assert (await g.vote(ben, "up"))[0] == 200
            await w.run(20)
            assert (await g.vote(cy, "down" if i % 2 else "up"))[0] == 200
            if i < N - 1:
                rows = {r["id"]: r for r in g.phones()["phones"]}
                assert rows[ana]["lockstep"] == []                     # not yet: fewer than N songs
                await _next_song(w)
        out = g.phones()
        rows = {r["id"]: r for r in out["phones"]}
        assert rows[ana]["lockstep"] == [{"id": ben, "name": rows[ben]["name"], "songs": N}]
        assert rows[ben]["lockstep"][0]["id"] == ana and rows[cy]["lockstep"] == []
        assert out["lockstep"] == 2
        assert store.load_guests().vote_ms                                 # the moments are kept
        # a vote taken back takes its moment with it
        await g.vote(ben, "none")
        key = next(k for k, v in g._book.votes.items() if ana in v and ben not in v)
        assert ben not in g._book.vote_ms[key]
        await g.vote(ben, "up")
        code, _ = await g.merge(ben, ana)                                  # one guest now
        assert code == 200
        rows = {r["id"]: r for r in g.phones()["phones"]}
        assert ben not in rows and rows[ana]["lockstep"] == []
    _run(go())
