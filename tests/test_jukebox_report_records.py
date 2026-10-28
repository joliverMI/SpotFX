"""What the guest book records FOR the post-party report (services/jukebox/
guests.py's REPORT RECORDS; the plan's §9 3.3 and §12 risk 3): one sample per
song start, each guest's first look at an add price, and adds turned away as
too late — driven over the fake Jukebox world, through the real guest calls."""
from __future__ import annotations

import asyncio

from services.jukebox import night_report as R, store
from tests.jukebox_world import jb_uri
from tests.test_jukebox_credits_play import _bal, _gift, _setup, _show
from tests.test_jukebox_guest_add import Catalog, _free, _hhmm, _night, _phone
from tests.test_jukebox_guest_add import _setup as _setup_free


def _run(coro):
    return asyncio.run(coro)


def test_one_sample_per_song_start_taken_on_a_guests_poll():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana = await _phone(g)
        await g.view(ana)
        book = g._book
        assert len(book.series) == 1 and book.sampled_plays == w.runner.night.plays
        for _ in range(5):                                   # polls within one song: no new sample
            await g.view(ana)
        assert len(book.series) == 1
        first = book.series[0]
        assert first.held == _bal(g, w, ana) and first.present == 1 and first.price_back is not None
        plays = w.runner.night.plays
        while w.runner.night.plays == plays:                 # the next song starts
            await w.run(5)
        await g.view(ana)
        assert len(book.series) == 2 and book.series[1].t_ms > first.t_ms
        assert store.load_guests().series[-1].t_ms == book.series[1].t_ms     # written through
    _run(go())


def test_free_play_samples_hold_no_credits():
    async def go():
        w = await _night(set_s=300)
        g = _setup_free(w, Catalog(w))
        ana = await _phone(g)
        await g.view(ana)
        x = g._book.series[0]
        assert x.held is None and x.price_back is None and x.back_wait_ms is not None
        assert (await g.search(ana, "J1 Song"))[0] == 200
        assert g._book.wants.wants == 0                      # free play: nothing to afford
    _run(go())


def test_a_first_look_is_one_want_until_the_guest_adds():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana = await _phone(g)                                # 4 welcome credits
        assert (await g.search(ana, "J1 Song"))[0] == 200
        wc = g._book.wants
        assert (wc.wants, wc.afford_now, wc.wish_more) == (1, 1, 0)   # 4 covers a song now
        await g.search(ana, "J2 Song")
        await g.search(ana, "J1 Song", 10)
        assert wc.wants == 1                                 # still the same want
        _gift(g, w, ana, 5)
        assert (await g.add(ana, jb_uri(0)))[1]["added"]["paid"] == 5      # 4, +1 not learned yet
        assert not g._book.phones[ana].want_open
        assert _bal(g, w, ana) == 4                          # 4 + 5 given - 5 for the song
        await g.search(ana, "J2 Song")                       # a new want, with a song waiting
        assert (wc.wants, wc.wish_more, wc.afford_more) == (2, 1, 1)   # a 2nd song soon costs 4
        m = R.measures(w.runner.night, list(g._wallet_for(w.runner.night.id, store.load_show()).led.entries),
                       int(w.clock.t * 1000), store.load_guests())
        assert m["afford_rate"]["value"] == wc.afford_now / wc.wants
    _run(go())


def test_a_guest_who_cant_afford_it_is_counted_as_such():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, _show(economy={"start_credits": 0}))
        ana = await _phone(g)
        assert _bal(g, w, ana) == 0
        await g.search(ana, "J1 Song")
        assert (g._book.wants.wants, g._book.wants.afford_now) == (1, 0)
    _run(go())


def test_an_add_turned_away_as_too_late_is_counted():
    async def go():
        w = await _night(set_s=300, jb_s=200, every=1)
        g = _setup_free(w, Catalog(w), show=_free(night_ends=_hhmm(w, 20), last_call_min=0))
        ana, ben, cy = await _phone(g), await _phone(g), await _phone(g)
        assert (await g.add(ana, jb_uri(0)))[0] == 200
        assert (await g.add(ben, jb_uri(1)))[0] == 200
        code, out = await g.add(cy, jb_uri(2))
        assert (code, out["reason"]) == (409, "too_late")
        assert g._book.refused == {"too_late": 1}
        assert store.load_guests().refused == {"too_late": 1}
        assert R.book_measures(w.runner.night, store.load_guests(), False,
                               int(w.clock.t * 1000))["refused_late"]["value"] == 1.0
    _run(go())

