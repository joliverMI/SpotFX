"""The Jukebox's board (services/jukebox/board.py, the plan's §1 rule 11,
§2.2 and §4's Board card; D1 (a)): "Tonight's top songs" ranks SONGS by ▲
with who added each; the people boards ship off and, when he turns one on,
name people only by their names; nothing the board says uses a game word.
Driven over the fake Jukebox world (tests/jukebox_world.py) through the real
guests.py calls, and the pure builder on a hand-made book."""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from jukebox_guest import app as guest_app, key as guest_key
from models.jukebox import GuestBook, GuestPhone, SetItem, ShowConfig
from routers import jukebox_guest_router, jukebox_router
from services.jukebox import board, guests as G, night as night_mod, show as show_mod, store
from tests.jukebox_world import World, jb_uri, set_uri
from tests.test_jukebox_credits_play import _gift, _setup, _show, _until_playing
from tests.test_jukebox_guest_add import TOKEN, Catalog, Lib, _inline, _night, _phone


def _run(coro):
    return asyncio.run(coro)


async def _evening(**show_kw):
    """Four phones; Ana's song gets three ▲, the set song before it two ▲ and
    a ▼, the host's own song one ▲."""
    w = await _night(set_s=60, jb_s=60, every=1, run=1)
    g = _setup(w, _show(**show_kw))
    ana, ben, cy, dee = [await _phone(g) for _ in range(4)]
    _gift(g, w, ana, 20)
    assert (await g.add(ana, jb_uri(0)))[0] == 200
    await w.runner.add_entry(w.runner.night.line[0].model_copy(
        update={"id": "h1", "uri": jb_uri(1), "title": "J1 Song", "added_by": "host"}))
    # the set song playing now
    for p, v in ((ana, "up"), (ben, "up"), (cy, "down")):
        assert (await g.vote(p, v))[0] == 200
    await _until_playing(w, jb_uri(0))
    for p in (ben, cy, dee):
        assert (await g.vote(p, "up"))[0] == 200
    await _until_playing(w, jb_uri(1))
    assert (await g.vote(ben, "up"))[0] == 200
    return w, g, {"ana": ana, "ben": ben, "cy": cy, "dee": dee}


def test_tonights_top_songs_rank_songs_by_up_votes_with_who_added_each():
    async def go():
        w, g, ps = await _evening()
        code, out = await g.board_view(ps["ana"])
        assert code == 200, out
        b = out["board"]
        assert b["title"] == "Tonight's top songs"
        rows = [(s["uri"], s["ups"], s["downs"], s["by"]["name"]) for s in b["songs"]]
        assert rows[0] == (jb_uri(0), 3, 0, (await g.view(ps["ana"]))[1]["view"]["me"]["name"])
        assert rows[1] == (set_uri(0), 2, 1, "Host's set")
        assert rows[2] == (jb_uri(1), 1, 0, "the host")
        assert all(s["open_url"].startswith("https://open.spotify.com/track/") for s in b["songs"])
        assert [s["mine"] for s in b["songs"]] == [True, False, False]     # Ana's own, marked
        assert [s["kind"] for s in b["songs"]] == ["jukebox", "set", "jukebox"]
        assert not any(s["mine"] for s in (await g.board_view(ps["ben"]))[1]["board"]["songs"])
        assert b["people"] == []                       # people boards ship off (D1)
        assert (await g.view(ps["ben"]))[1]["view"]["features"]["board"] is True
    _run(go())


def test_people_boards_are_his_switches_and_name_people_only_by_name():
    async def go():
        w, g, ps = await _evening(board_top_pickers=True, board_top_voters=True,
                                  board_most_generous=True)
        _gift(g, w, ps["ben"], 10)
        _gift(g, w, ps["cy"], 10)
        assert (await g.tip(ps["ben"], 1))[0] == 409   # the host's song takes no tips
        out = (await g.board_view(ps["dee"]))[1]["board"]
        names = {pid: (await g.view(pid))[1]["view"]["me"]["name"] for pid in ps.values()}
        people = {p["id"]: p for p in out["people"]}
        assert set(people) == {"pickers", "voters", "generous"}
        assert people["pickers"]["rows"] == [{"name": names[ps["ana"]], "value": 3}]
        voters = {r["name"]: r["value"] for r in people["voters"]["rows"]}
        assert voters == {names[ps["ben"]]: 3, names[ps["cy"]]: 2, names[ps["ana"]]: 1,
                          names[ps["dee"]]: 1}
        assert people["voters"]["rows"][0]["name"] == names[ps["ben"]]
        text = json.dumps(out)
        assert not any(pid in text for pid in ps.values())   # never a phone's id
        # "most generous" is a credits board: free play shows no such board
        store.save_show(store.load_show().model_copy(update={"play_mode": "free"}))
        out = (await g.board_view(ps["dee"]))[1]["board"]
        assert {p["id"] for p in out["people"]} == {"pickers", "voters"}
    _run(go())


def test_most_generous_counts_the_credits_given_as_tips():
    async def go():
        w = await _night(set_s=60, jb_s=60, every=1, run=1)
        g = _setup(w, _show(board_most_generous=True))
        ana, ben, cy = [await _phone(g) for _ in range(3)]
        for p in (ana, ben, cy):
            _gift(g, w, p, 20)
        assert (await g.add(ana, jb_uri(0)))[0] == 200
        await _until_playing(w, jb_uri(0))
        assert (await g.tip(ben, 1))[0] == 200
        assert (await g.tip(ben, 1))[0] == 200
        assert (await g.tip(cy, 1))[0] == 200
        out = (await g.board_view(ana))[1]["board"]
        gen = next(p for p in out["people"] if p["id"] == "generous")
        names = {pid: (await g.view(pid))[1]["view"]["me"]["name"] for pid in (ben, cy)}
        assert gen["rows"] == [{"name": names[ben], "value": 2}, {"name": names[cy], "value": 1}]
    _run(go())


def test_the_board_can_be_off():
    async def go():
        w = await _night(set_s=60)
        g = _setup(w, _show(board_on=False))
        ana = await _phone(g)
        assert (await g.view(ana))[1]["view"]["features"]["board"] is False
        code, out = await g.board_view(ana)
        assert code == 409 and out["reason"] == "board_off" and out["detail"]
    _run(go())


def test_the_host_sees_every_people_board_marked_and_the_song_playing():
    async def go():
        w, g, ps = await _evening(board_top_voters=True)
        out = g.host_board()
        assert out["running"] and out["settings"]["board_top_voters"] is True
        shown = {p["id"]: p["shown"] for p in out["board"]["people"]}
        assert shown == {"pickers": False, "voters": True, "generous": False}
        assert out["now"]["uri"] == jb_uri(1) and out["now"]["up"] == 1
        assert out["now"]["by"] == {"kind": "host", "name": "the host"}
        assert not any(pid in json.dumps(out) for pid in ps.values())
    _run(go())


def test_a_song_that_played_twice_is_one_row_and_a_song_with_no_up_is_left_off():
    book = GuestBook(night_id="n", phones={"a" * 22: GuestPhone(id="a" * 22, name="Ana"),
                                           "b" * 22: GuestPhone(id="b" * 22, name="Ben")},
                     votes={f"{set_uri(0)}@100": {"a" * 22: 1},
                            f"{set_uri(0)}@900": {"a" * 22: 1, "b" * 22: 1},
                            f"{set_uri(1)}@500": {"a" * 22: -1, "b" * 22: 1},
                            f"{set_uri(2)}@600": {"a" * 22: 1, "b" * 22: 1, "c" * 22: -1},
                            f"{set_uri(3)}@700": {"b" * 22: -1}})
    gs = {"set_items": [SetItem(uri=set_uri(i), title=f"S{i}", artist="A", duration_ms=1)
                        for i in range(4)], "line": []}
    rows = board.top_songs(book, gs)
    assert [(r["title"], r["ups"], r["downs"], r["plays"]) for r in rows] == [
        ("S0", 3, 0, 2), ("S2", 2, 1, 1), ("S1", 1, 1, 1)]
    assert set_uri(3) not in {r["uri"] for r in rows}
    assert board.top_voters(book) == [{"name": "Ana", "value": 4}, {"name": "Ben", "value": 4}]
    assert len(board.top_songs(book, gs, limit=2)) == 2


def test_nothing_the_board_says_is_a_game_word():
    """§2.2 / D1 (a): no "win", "score", "points", "level", "game" — not in
    the board's titles, units or empty line, nor in the settings' words."""
    every_on = ShowConfig(board_top_pickers=True, board_top_voters=True, board_most_generous=True)
    out = board.build_board(GuestBook(), {"line": [], "set_items": []}, every_on, tips={})
    assert {p["id"] for p in out["people"]} == {"pickers", "voters", "generous"}
    said = board.words_of(out) + [f["label"] for f in show_mod.guest_fields() if f["card"] == "Board"]
    assert all(not board.banned_in(s) for s in said), [s for s in said if board.banned_in(s)]
    assert board.banned_in("you win!") == ["win"]          # the check can fail


def test_the_board_settings_ship_as_planned_and_go_through_the_one_validator():
    s = ShowConfig()
    assert (s.board_on, s.board_top_pickers, s.board_top_voters, s.board_most_generous,
            s.board_on_tv) == (True, False, False, False, False)
    new = show_mod.apply_patch(s, {"board_top_voters": True, "board_on_tv": True})
    assert new.board_top_voters and new.board_on_tv
    try:
        show_mod.apply_patch(s, {"board_on": "maybe"})
        raise AssertionError("a non-switch value was accepted")
    except ValueError:
        pass
    cards = {f["key"]: (f["card"], f["kind"]) for f in show_mod.guest_fields()}
    assert all(cards[k] == ("Board", "bool") for k in (
        "board_on", "board_top_pickers", "board_top_voters", "board_most_generous", "board_on_tv"))


def test_the_board_doors(monkeypatch):
    w = World(set_s=300)
    w.deps.load_config = store.load_config
    w.runner = night_mod.JukeboxRunner(w.deps)
    monkeypatch.setattr(night_mod, "runner", w.runner)
    store.save_show(_show())
    g = G.Guests(G.GuestDeps(token_ok=lambda t: t == TOKEN, to_thread=_inline,
                             now_ms=lambda: int(w.clock.t * 1000),
                             gateway=lambda: Catalog(w), library_search=Lib([]),
                             known=lambda uris: {u: False for u in uris}))
    monkeypatch.setattr(G, "book", g)
    app = FastAPI()
    app.include_router(jukebox_guest_router.router)
    app.include_router(jukebox_router.router)
    key = guest_key.load_or_create(jukebox_guest_router.KEY_FILE)
    with TestClient(app) as c:
        assert c.get("/api/jukebox/board").json()["running"] is False
        store.save_config(store.load_config().model_copy(update={"playlist": w.cfg.playlist}))
        assert c.post("/api/jukebox/night/start", json={}).json()["status"] == "running"
        ana = c.portal.call(_phone, g)
        assert c.get("/api/jukebox/guest/board", params={"phone": ana}).status_code == 401
        r = c.get("/api/jukebox/guest/board", params={"phone": ana},
                  headers={guest_key.HEADER: key})
        assert r.status_code == 200 and r.json()["board"]["songs"] == []
        host = c.get("/api/jukebox/board").json()
        assert host["running"] and host["board"]["songs"] == [] and "now" in host
    assert ("GET", "/g/board") in guest_app.ROUTES
    assert guest_app.FORWARDS["board"] == ("GET", "/api/jukebox/guest/board")
