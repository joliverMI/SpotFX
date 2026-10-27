"""Search and add, and the host's controls (services/jukebox/guests.py and
night.py, the plan's PR 2.2): a guest finds a song — his library first, then
Spotify — and adds it by fair order (1st songs before 2nd songs, never ahead
of the song already sent to Spotify), within the show's rules (songs in line,
last call, nothing that would start after the night ends, explicit songs);
the host approves, blocks, renames and locks phones, and holds songs. The
plan's acceptance: "tests for fair order and last call; search never blocks
the event loop". Driven over the fake Jukebox world (tests/jukebox_world.py),
so the line the engine plays is the one these tests build."""
from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.jukebox import ShowConfig
from routers import jukebox_router
from services.jukebox import gateway, guests as G, night as night_mod, store
from tests.jukebox_world import World, jb_uri

TOKEN = "tonights-token"


def _run(coro):
    return asyncio.run(coro)


async def _inline(fn, *args):
    return fn(*args)


class Catalog:
    """Spotify's search, for the tests: every jukebox song of the world, and
    a few the world can't play. Counts its calls."""

    def __init__(self, w: World, explicit: set[str] = frozenset(),
                 track_delay_s: float = 0.0) -> None:
        self.w = w
        self.calls: list[str] = []
        self.songs = {jb_uri(i): {"uri": jb_uri(i), "title": f"J{i} Song", "artist": "Band",
                                  "duration_ms": w.player.durations[jb_uri(i)],
                                  "explicit": jb_uri(i) in explicit,
                                  "image": f"https://i.scdn.co/image/{i}", "thumb": ""}
                      for i in range(12)}
        self.fail = False
        self.delay = 0.0
        self.track_delay_s = track_delay_s

    def search(self, q, limit=10, offset=0):
        self.calls.append(f"search:{q}:{offset}")
        if self.delay:
            time.sleep(self.delay)          # a slow Spotify, blocking like spotipy
        if self.fail:
            raise RuntimeError("spotify down")
        hits = [m for m in self.songs.values() if q.lower().split()[0] in m["title"].lower()]
        return [dict(m) for m in hits[offset:offset + limit]]

    def tracks(self, uris):
        self.calls.append(f"tracks:{len(uris)}")
        return [dict(self.songs[u]) for u in uris if u in self.songs]

    def track(self, uri):
        self.calls.append("track")
        if self.track_delay_s:
            # a slow Spotify lookup: real time (the fake clock) passes before
            # the caller gets the metadata back, with nothing else about the
            # night having moved on
            self.w.clock.t += self.track_delay_s
        return dict(self.songs[uri]) if uri in self.songs else None


class Lib:
    def __init__(self, uris):
        self.uris = uris

    def __call__(self, q, limit):
        from services.jukebox.library import Song
        return [Song(u, u, "", u) for u in self.uris][:limit]


def _free(**kw) -> ShowConfig:
    """Free play: these are phase 2.2's rules for adding a song (credits mode,
    the default since PR 3.2, prices the same adds — test_jukebox_credits_play)."""
    return ShowConfig(**{"play_mode": "free", **kw})


def _setup(w: World, cat: Catalog, *, library=(), known=(), show: ShowConfig | None = None):
    store.save_show(show if show is not None else _free())
    return G.Guests(G.GuestDeps(
        state=lambda: w.runner.guest_state(count=24), token_ok=lambda t: t == TOKEN,
        now_ms=lambda: int(w.clock.t * 1000), to_thread=_inline, rng=random.Random(1),
        runner=lambda: w.runner, gateway=lambda: cat, library_search=Lib(list(library)),
        known=lambda uris: {u: u in set(known) for u in uris}, clock=w.clock))


async def _night(**cfg) -> World:
    w = World(**cfg)
    await w.start()
    await w.run(2)
    return w


async def _phone(g: G.Guests) -> str:
    code, out = await g.hello(None, TOKEN)
    assert code == 200, out
    assert (await g.join(out["phone"]))[0] == 200
    return out["phone"]


def _hhmm(w: World, minutes_after_start: float) -> str:
    start = datetime.fromtimestamp(w.runner.night.started_ms / 1000, G.HOUSE_TZ)
    t = start + timedelta(minutes=minutes_after_start)
    return f"{t.hour:02d}:{t.minute:02d}"


def _waiting_titles(w: World) -> list[str]:
    return [e.title for e in w.runner.night.line if e.state in ("queued", "committed")]


# ═══ 1. fair order ═════════════════════════════════════════════════════════

def test_first_songs_go_before_second_songs():
    async def go():
        w = await _night(set_s=300)
        cat = Catalog(w)
        g = _setup(w, cat)
        ana, ben, cy = await _phone(g), await _phone(g), await _phone(g)
        assert (await g.add(ana, jb_uri(0)))[0] == 200          # Ana's 1st
        assert (await g.add(ana, jb_uri(1)))[0] == 200          # Ana's 2nd
        assert (await g.add(ben, jb_uri(2)))[0] == 200          # Ben's 1st: ahead of Ana's 2nd
        assert (await g.add(cy, jb_uri(3)))[0] == 200           # Cy's 1st: ahead of Ana's 2nd too
        assert _waiting_titles(w) == ["J0 Song", "J2 Song", "J3 Song", "J1 Song"]
        rounds = {e.title: e.round for e in w.runner.night.line}
        assert rounds == {"J0 Song": 1, "J1 Song": 2, "J2 Song": 1, "J3 Song": 1}
        # the view's places follow the same order
        view = (await g.view(ana))[1]["view"]
        places = {s["title"]: s["place"] for s in view["mine"]}
        assert places["J0 Song"] < places["J1 Song"]
    _run(go())


def test_fair_order_off_is_first_come():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, Catalog(w), show=_free(economy={"fair_order": False}))
        ana, ben = await _phone(g), await _phone(g)
        await g.add(ana, jb_uri(0))
        await g.add(ana, jb_uri(1))
        await g.add(ben, jb_uri(2))
        assert _waiting_titles(w) == ["J0 Song", "J1 Song", "J2 Song"]
    _run(go())


def test_nothing_passes_the_song_already_sent_to_spotify():
    async def go():
        w = await _night(set_s=60, every=1)
        g = _setup(w, Catalog(w))
        ana, ben = await _phone(g), await _phone(g)
        await g.add(ana, jb_uri(0))
        await g.add(ana, jb_uri(1))
        await w.run(20)                                    # into the commit window: J0 is sent
        assert w.runner.night.line[0].state == "committed"
        await w.runner.hold(w.runner.night.line[1].id, False)
        # Ben's 1st outranks Ana's 2nd but never the committed one
        await g.add(ben, jb_uri(2))
        assert _waiting_titles(w) == ["J0 Song", "J2 Song", "J1 Song"]
    _run(go())


def test_a_song_that_played_counts_toward_the_round():
    async def go():
        w = await _night(set_s=60, jb_s=60, every=1)
        g = _setup(w, Catalog(w))
        ana, ben = await _phone(g), await _phone(g)
        await g.add(ana, jb_uri(0))
        await w.run(120)                                   # J0 plays and ends
        assert w.runner.night.line[0].state == "played"
        await g.add(ana, jb_uri(1))                        # Ana's 2nd song tonight
        await g.add(ben, jb_uri(2))                        # Ben's 1st goes ahead of it
        assert _waiting_titles(w) == ["J2 Song", "J1 Song"]
    _run(go())


def test_songs_in_line_follow_the_show():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, Catalog(w))
        ana = await _phone(g)
        assert (await g.add(ana, jb_uri(0)))[0] == 200
        assert (await g.add(ana, jb_uri(1)))[0] == 200
        code, out = await g.add(ana, jb_uri(2))
        assert (code, out["reason"]) == (409, "too_many") and "2 songs" in out["detail"]
        store.save_show(_free(economy={"max_waiting": 3}))
        assert (await g.add(ana, jb_uri(2)))[0] == 200
        code, out = await g.add(ana, jb_uri(0))
        assert out["reason"] == "in_line"                  # one copy of a song in line
    _run(go())


# ═══ 2. last call, and nothing after the night ends ═══════════════════════

def test_requests_close_at_last_call():
    async def go():
        w = await _night(set_s=300)
        cat = Catalog(w)
        g = _setup(w, cat, show=_free(night_ends=_hhmm(w, 60), last_call_min=20))
        ana = await _phone(g)
        view = (await g.view(ana))[1]["view"]
        assert view["requests"]["open"] is True
        w.clock.t += 41 * 60                               # 41 min in: last call was at 40
        code, out = await g.add(ana, jb_uri(0))
        assert (code, out["reason"]) == (409, "requests_closed")
        assert out["detail"].startswith("Requests are closed for tonight — last call was at ")
        assert _waiting_titles(w) == []
        assert (await g.view(ana))[1]["view"]["requests"]["open"] is False
    _run(go())


def test_a_song_that_would_start_after_the_night_ends_is_turned_away():
    async def go():
        # the night ends ~19 min in; 5-minute set songs, a 200 s slot after each
        w = await _night(set_s=300, jb_s=200, every=1)
        g = _setup(w, Catalog(w), show=_free(night_ends=_hhmm(w, 20), last_call_min=0))
        ana, ben, cy = await _phone(g), await _phone(g), await _phone(g)
        assert (await g.add(ana, jb_uri(0)))[0] == 200     # starts ~5 min in (after S0)
        assert (await g.add(ben, jb_uri(1)))[0] == 200     # ~13 min in (after S1)
        # Cy's would start ~22 min in (after S2): past the end
        before = list(_waiting_titles(w))
        code, out = await g.add(cy, jb_uri(2))
        assert (code, out["reason"]) == (409, "too_late")
        assert _waiting_titles(w) == before                # nothing was added
    _run(go())


def test_a_slow_track_lookup_does_not_let_a_too_late_song_through():
    async def go():
        # S0 is playing, 2 s in: 298 s left of it, so the song (which would
        # start the instant S0 ends) starts in 298 s. The night ends with
        # 318 s of budget left at the moment `add` is first called — plenty
        # of room — but the Spotify `track()` lookup takes 25 s, so by the
        # time the real end-of-night deadline is checked only 293 s of
        # budget are left: less than the 298 s the song needs.
        w = await _night(set_s=300, jb_s=200, every=1)
        cat = Catalog(w, track_delay_s=25.0)       # a slow Spotify `track()` call
        g = _setup(w, cat, show=_free(night_ends=_hhmm(w, 6), last_call_min=0))
        cy = await _phone(g)
        before = list(_waiting_titles(w))
        code, out = await g.add(cy, jb_uri(0))
        # with a fresh (post-lookup) clock the song would start after the
        # night ends, and must be refused even though the budget captured
        # BEFORE the lookup still had it fitting comfortably
        assert (code, out["reason"]) == (409, "too_late")
        assert _waiting_titles(w) == before                # nothing was added
    _run(go())


def test_the_night_end_is_the_next_one_after_the_start():
    show = _free(night_ends="00:00", last_call_min=20)
    start = datetime(2026, 10, 31, 20, 0, tzinfo=G.HOUSE_TZ)
    r = G.requests_state(show, int(start.timestamp() * 1000), int(start.timestamp() * 1000))
    ends = datetime.fromtimestamp(r["ends_at_ms"] / 1000, G.HOUSE_TZ)
    assert (ends.day, ends.hour, r["closes_at"]) == (1, 0, "11:40")


# ═══ 3. explicit songs ═════════════════════════════════════════════════════

def test_explicit_songs_follow_the_show():
    async def go():
        w = await _night(set_s=300)
        cat = Catalog(w, explicit={jb_uri(0)})
        g = _setup(w, cat)
        ana = await _phone(g)
        code, out = await g.add(ana, jb_uri(0))
        assert (code, out["reason"], out["detail"]) == (409, "explicit", G.sentence("explicit_no"))
        store.save_show(_free(explicit="after", explicit_after=_hhmm(w, 30)))
        code, out = await g.add(ana, jb_uri(0))
        assert out["reason"] == "explicit" and "allowed after" in out["detail"]
        w.clock.t += 31 * 60
        assert (await g.add(ana, jb_uri(0)))[0] == 200
        store.save_show(_free(explicit="extra"))
        assert G.explicit_rule(_free(explicit="extra"), 0, 0) == (True, "")
    _run(go())


# ═══ 4. search: his library first, then Spotify; cached; off the loop ═════

def test_search_puts_his_library_first_with_its_badges():
    async def go():
        w = await _night(set_s=300)
        cat = Catalog(w, explicit={jb_uri(5)})
        cat.songs[jb_uri(4)]["duration_ms"] = 6 * 60_000
        g = _setup(w, cat, library=[jb_uri(3)], known=[jb_uri(3), jb_uri(1)])
        ana = await _phone(g)
        await g.add(ana, jb_uri(1))
        code, out = await g.search(ana, "Song", 0)
        assert code == 200
        res = out["results"]
        assert res[0]["uri"] == jb_uri(3) and res[0]["library"] and res[0]["known"]
        assert [r["uri"] for r in res].count(jb_uri(3)) == 1          # not twice
        by = {r["uri"]: r for r in res}
        assert by[jb_uri(1)]["in_line"] and not by[jb_uri(1)]["can_add"]
        assert by[jb_uri(1)]["known"]
        assert by[jb_uri(4)]["long"] and by[jb_uri(4)]["can_add"]
        assert by[jb_uri(5)]["explicit"] and not by[jb_uri(5)]["can_add"]
        assert by[jb_uri(5)]["why_not"] == G.sentence("explicit_no")
        assert by[jb_uri(0)]["open_url"].startswith("https://open.spotify.com/track/")
        assert out["more"] is True and out["next_offset"] == 10
    _run(go())


def test_search_is_cached_and_pages_skip_the_library():
    async def go():
        w = await _night(set_s=300)
        cat = Catalog(w)
        g = _setup(w, cat, library=[jb_uri(3)])
        ana = await _phone(g)
        await g.search(ana, "Song", 0)
        calls = list(cat.calls)
        await g.search(ana, "  song ", 0)                  # the same query, again
        assert cat.calls == calls
        await g.search(ana, "Song", 10)
        assert cat.calls[len(calls):] == ["search:Song:10"]
    _run(go())


def test_a_bad_query_or_a_failed_spotify_is_a_sentence():
    async def go():
        w = await _night(set_s=300)
        cat = Catalog(w)
        g = _setup(w, cat)
        ana = await _phone(g)
        assert (await g.search(ana, "x", 0))[1]["reason"] == "bad_query"
        cat.fail = True
        code, out = await g.search(ana, "J9", 0)
        assert (code, out["reason"]) == (503, "search_failed")
    _run(go())


def test_search_never_blocks_the_event_loop():
    """Spotify answering slowly (a blocking 0.4 s, as spotipy does) must not
    stall the loop that runs the music: a heartbeat keeps ticking."""
    async def go():
        w = World(set_s=300)
        w.deps.to_thread = night_mod._default_to_thread
        await w.start()
        await w.run(2)
        cat = Catalog(w)
        cat.delay = 0.4
        g = G.Guests(G.GuestDeps(
            state=lambda: w.runner.guest_state(count=24), token_ok=lambda t: t == TOKEN,
            now_ms=lambda: int(w.clock.t * 1000), rng=random.Random(1),
            runner=lambda: w.runner, gateway=lambda: cat, library_search=Lib([jb_uri(3)]),
            known=lambda uris: {u: False for u in uris}))
        ana = await _phone(g)
        gaps: list[float] = []

        async def heartbeat():
            last = time.perf_counter()
            for _ in range(60):
                await asyncio.sleep(0.01)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now
        beat = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.05)                          # the heartbeat is ticking first
        code, _ = await g.search(ana, "Song", 0)
        await beat
        assert code == 200 and len(cat.calls) >= 2         # the slow calls really ran
        assert max(gaps) < 0.15, f"the loop stalled for {max(gaps):.2f} s"
    _run(go())


def test_guests_search_on_their_own_gateway():
    assert gateway.search_gateway() is not gateway.default_gateway()
    assert gateway.search_gateway() is gateway.search_gateway()


# ═══ 5. the host's controls ════════════════════════════════════════════════

def test_new_phones_wait_for_approval_when_the_show_says_so():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, Catalog(w), show=_free(approve_new_phones=True))
        ana = await _phone(g)
        view = (await g.view(ana))[1]["view"]
        assert view["me"]["approved"] is False and not view["now"]["can_vote"]
        assert (await g.vote(ana, "up"))[1]["reason"] == "not_approved"
        assert (await g.add(ana, jb_uri(0)))[1]["reason"] == "not_approved"
        assert g.phones()["pending"] == 1
        assert (await g.host_set(ana, approved=True))[0] == 200
        assert (await g.vote(ana, "up"))[0] == 200
        assert (await g.add(ana, jb_uri(0)))[0] == 200
    _run(go())


def test_a_blocked_phone_is_out_for_the_night():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, Catalog(w))
        ana = await _phone(g)
        await g.host_set(ana, blocked=True)
        for call in (g.view(ana), g.vote(ana, "up"), g.add(ana, jb_uri(0)), g.hello(ana, TOKEN)):
            code, out = await call
            assert (code, out["reason"]) == (403, "blocked")
    _run(go())


def test_the_host_renames_and_locks_a_name():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, Catalog(w))
        ana, ben = await _phone(g), await _phone(g)
        await g.rename(ben, "Taken Name")
        assert (await g.host_set(ana, name="taken name"))[1]["reason"] == "name_taken"
        code, out = await g.host_set(ana, name="Dinner Ana", name_locked=True)
        assert code == 200
        mine = next(p for p in out["phones"] if p["id"] == ana)
        assert mine["name"] == "Dinner Ana" and mine["name_locked"]
        assert (await g.rename(ana, "Something Else"))[1]["reason"] == "name_locked"
        assert (await g.rename(ana, shuffle=True))[1]["reason"] == "name_locked"
    _run(go())


def test_the_word_filter_is_the_shows():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, Catalog(w), show=_free(word_filter=False, renames_per_night=1))
        ana = await _phone(g)
        assert (await g.rename(ana, "Killer Queen"))[0] == 200
        assert (await g.rename(ana, "Another"))[1]["reason"] == "renames_used"
    _run(go())


def test_a_held_song_keeps_its_place_and_the_slot_passes_it():
    async def go():
        w = await _night(set_s=60, every=1)
        g = _setup(w, Catalog(w))
        ana, ben = await _phone(g), await _phone(g)
        await g.add(ana, jb_uri(0))
        await g.add(ben, jb_uri(1))
        first = w.runner.night.line[0]
        assert (await w.runner.hold(first.id, True))["status"] == "held"
        view = (await g.view(ana))[1]["view"]
        assert view["mine"][0]["held"] and view["strip"]["held"]
        await w.run(30)                                    # the commit window of the set song
        sent = [e.title for e in w.runner.night.line if e.state == "committed"]
        assert sent == ["J1 Song"]                         # the held one was passed over
        assert w.runner.night.line[0].id == first.id       # and kept its place
        assert (await w.runner.hold(first.id, False))["status"] == "released"
        assert (await w.runner.hold(w.runner.night.line[1].id, True))["reason"] == "committed_fixed"
    _run(go())


def test_the_hosts_routes(monkeypatch):
    w = World(set_s=300)
    w.deps.load_config = store.load_config
    w.runner = night_mod.JukeboxRunner(w.deps)
    monkeypatch.setattr(night_mod, "runner", w.runner)
    cat = Catalog(w)
    g = G.Guests(G.GuestDeps(token_ok=lambda t: t == TOKEN, to_thread=_inline,
                             now_ms=lambda: int(w.clock.t * 1000),
                             gateway=lambda: cat, library_search=Lib([]),
                             known=lambda uris: {u: False for u in uris}))
    monkeypatch.setattr(G, "book", g)
    store.save_show(_free())
    app = FastAPI()
    app.include_router(jukebox_router.router)
    with TestClient(app) as c:
        assert c.get("/api/jukebox/guests").json() == {"running": False, "phones": []}
        store.save_config(store.load_config().model_copy(update={"playlist": w.cfg.playlist}))
        assert c.post("/api/jukebox/night/start", json={}).json()["status"] == "running"
        ana = c.portal.call(_phone, g)
        assert c.portal.call(g.add, ana, jb_uri(0))[0] == 200
        phones = c.get("/api/jukebox/guests").json()["phones"]
        assert [(p["id"], p["waiting"]) for p in phones] == [(ana, 1)]
        r = c.post(f"/api/jukebox/guests/{ana}", json={"blocked": True, "name": "Gone"})
        assert r.status_code == 200 and r.json()["phones"][0]["blocked"]
        assert c.post("/api/jukebox/guests/nope", json={"approved": True}).status_code == 404
        entry = w.runner.night.line[0].id
        assert c.post(f"/api/jukebox/line/{entry}/hold", json={"held": True}).json()["status"] == "held"
        assert c.post(f"/api/jukebox/line/{entry}/hold", json={"held": False}).json()["status"] == "released"
