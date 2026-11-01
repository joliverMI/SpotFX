"""`Guests.tv_view()` + `GET /api/jukebox/tv` (data/tv-display-plan/
plan.html PR 1.3) — the leaner, TV-specific read SPECTRA's feed relay
(spectra/services/tv_feed.py) actually calls, as opposed to `host_board()`
(`/board`, the master's own pages). Driven over the real fake Jukebox
world (tests/jukebox_world.py), reusing test_jukebox_board.py's own
`_evening()` fixture scenario (set song -> two jukebox songs, votes on
each) rather than building a second one."""
from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import jukebox_router
from services.jukebox import guests as G, store
from tests.jukebox_world import jb_uri, set_uri
from tests.test_jukebox_board import _evening


def _run(coro):
    return asyncio.run(coro)


def test_tv_view_when_no_night_is_running():
    w = None  # a fresh Guests() with the module-level default deps
    out = G.Guests().tv_view()
    assert out["running"] is False
    assert out["now"] is None
    assert out["next"] == []
    assert out["board"] is None
    assert "revision" in out


def test_tv_view_mirrors_now_next_and_board_without_a_phones_id():
    async def go():
        w, g, ps = await _evening()
        out = g.tv_view()
        assert out["running"] is True

        # now playing: the second jukebox song (host's), per _evening()'s
        # own script — live votes, progress fields, attribution by name.
        assert out["now"]["uri"] == jb_uri(1)
        assert out["now"]["by"] == {"kind": "host", "name": "the host"}
        assert out["now"]["up"] == 1
        assert out["now"]["down"] == 0
        assert isinstance(out["now"]["duration_ms"], int)
        assert isinstance(out["now"]["progress_ms"], int)

        # the board: only the ranked songs — no people boards (they ship
        # off by default, matching host_board()'s own equivalent check).
        assert out["board"]["title"] == "Tonight's top songs"
        assert out["board"]["people"] == []
        songs_by_uri = {s["uri"]: s for s in out["board"]["songs"]}
        assert songs_by_uri[jb_uri(0)]["ups"] == 3
        assert songs_by_uri[set_uri(0)]["ups"] == 2

        # never a phone's id anywhere in the payload
        import json
        text = json.dumps(out)
        for pid in ps.values():
            assert pid not in text
    _run(go())


def test_tv_view_link_is_named_only_while_the_guest_link_is_actually_live():
    async def go():
        w, g, ps = await _evening()
        out = g.tv_view()
        assert out["link"] is None  # the guest link ships off by default
    _run(go())


def test_tv_view_revision_changes_on_a_vote_but_not_on_a_repeat_read():
    async def go():
        w, g, ps = await _evening()
        first = g.tv_view()
        second = g.tv_view()
        assert first["revision"] == second["revision"]

        assert (await g.vote(ps["dee"], "up"))[0] == 200
        third = g.tv_view()
        assert third["revision"] != first["revision"]
    _run(go())


def test_tv_route_answers_the_same_shape_as_the_direct_call(monkeypatch):
    from jukebox_guest import key as guest_key
    from routers import jukebox_guest_router
    from tests.jukebox_world import World
    from tests.test_jukebox_guest_add import TOKEN, Catalog, Lib, _inline
    from services.jukebox import night as night_mod

    w = World(set_s=300)
    w.deps.load_config = store.load_config
    w.runner = night_mod.JukeboxRunner(w.deps)
    monkeypatch.setattr(night_mod, "runner", w.runner)
    store.save_show(store.load_show())
    g = G.Guests(G.GuestDeps(token_ok=lambda t: t == TOKEN, to_thread=_inline,
                             now_ms=lambda: int(w.clock.t * 1000),
                             gateway=lambda: Catalog(w), library_search=Lib([]),
                             known=lambda uris: {u: False for u in uris}))
    monkeypatch.setattr(G, "book", g)
    app = FastAPI()
    app.include_router(jukebox_guest_router.router)
    app.include_router(jukebox_router.router)
    guest_key.load_or_create(jukebox_guest_router.KEY_FILE)
    with TestClient(app) as c:
        r = c.get("/api/jukebox/tv")
        assert r.status_code == 200
        body = r.json()
        assert body["running"] is False
        assert body == g.tv_view()
