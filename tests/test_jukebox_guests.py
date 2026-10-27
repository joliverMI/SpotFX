"""Tonight's guests (services/jukebox/guests.py, the plan's PR 2.1): a phone
joins only with tonight's party token, gets a fun name it may change a few
times, votes once on the song playing (never its own), and gets ONE view of
everything its screen shows — with other phones' names, never their codes.
Driven over the fake Jukebox world (tests/jukebox_world.py), so the program
it reads is the engine's own."""
from __future__ import annotations

import asyncio
import json
import random

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.jukebox import GuestBook, NowItem
from routers import jukebox_guest_router, jukebox_router
from services.jukebox import gateway, guests as G, night as night_mod, store
from jukebox_guest import key as guest_key
from tests.jukebox_world import World, jb_uri

TOKEN = "tonights-token-abc"


def _run(coro):
    return asyncio.run(coro)


async def _inline(fn, *args):
    return fn(*args)


def _guests(w: World, seed: int = 1) -> G.Guests:
    return G.Guests(G.GuestDeps(state=lambda: w.runner.guest_state(count=24),
                                token_ok=lambda t: t == TOKEN,
                                now_ms=lambda: int(w.clock.t * 1000), to_thread=_inline,
                                rng=random.Random(seed)))


async def _night(**cfg) -> World:
    w = World(**cfg)
    await w.start()
    await w.run(2)
    return w


async def _phone(g: G.Guests, join: bool = True) -> str:
    code, out = await g.hello(None, TOKEN)
    assert code == 200, out
    pid = out["phone"]
    if join:
        assert (await g.join(pid))[0] == 200
    return pid


# ═══ 1. who may join ═══════════════════════════════════════════════════════

def test_with_no_night_the_page_says_so_and_registers_nobody():
    w = World()
    g = _guests(w)

    async def go():
        code, out = await g.hello(None, TOKEN)
        assert code == 200 and out["state"] == "idle" and "isn't playing" in out["detail"]
        assert (await g.view(G.new_phone_id()))[1]["state"] == "idle"
    _run(go())
    assert not store.GUESTS_FILE.exists()


def test_a_new_phone_needs_tonights_token_and_a_returning_one_does_not():
    async def go():
        w = await _night()
        g = _guests(w)
        for bad in (None, "", "wrong"):
            code, out = await g.hello(None, bad)
            assert (code, out["reason"]) == (403, "needs_link")
        code, out = await g.hello(None, TOKEN)
        pid = out["phone"]
        assert code == 200 and G.valid_phone_id(pid)
        me = out["view"]["me"]
        assert me["name"] and not me["joined"]
        # back with its code: no token needed
        code, again = await g.hello(pid, None)
        assert code == 200 and again["phone"] == pid and again["view"]["me"]["name"] == me["name"]
        # a code the book doesn't know is not let in on its own
        assert (await g.view(G.new_phone_id()))[0] == 403
    _run(go())


def test_a_phone_keeps_its_own_code_when_it_brings_one():
    async def go():
        w = await _night()
        g = _guests(w)
        mine = G.new_phone_id()
        code, out = await g.hello(mine, TOKEN)
        assert code == 200 and out["phone"] == mine
        code, out = await g.hello("not a code!", TOKEN)
        assert code == 200 and out["phone"] != "not a code!"
    _run(go())


def test_the_party_has_a_limit(monkeypatch):
    monkeypatch.setattr(G, "PHONES_MAX", 2)

    async def go():
        w = await _night()
        g = _guests(w)
        await _phone(g)
        await _phone(g)
        code, out = await g.hello(None, TOKEN)
        assert (code, out["reason"]) == (403, "party_full")
    _run(go())


def test_a_new_night_starts_an_empty_book():
    async def go():
        w = await _night()
        g = _guests(w)
        pid = await _phone(g)
        await w.runner.stop()
        assert (await g.view(pid))[1]["state"] == "idle"
        await w.start()
        await w.run(2)
        code, out = await g.hello(pid, None)            # last night's code alone: not enough
        assert (code, out["reason"]) == (403, "needs_link")
        code, out = await g.hello(pid, TOKEN)
        assert code == 200 and out["phone"] == pid
    _run(go())


# ═══ 2. names ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,want", [
    ("  Sunny   Fox ", ("Sunny Fox", "")), ("DJ Ana", ("DJ Ana", "")),
    ("José", ("José", "")), ("Zoë O'Neil", ("Zoë O'Neil", "")), ("--", (None, "name_bad")),
    ("Ana 🎉", (None, "name_bad")),
    ("x", (None, "name_bad")), ("a" * 21, (None, "name_bad")), ("<b>hi</b>", (None, "name_bad")),
    ("Host", (None, "name_blocked")), ("Sh1t Head", (None, "name_blocked")),
    ("Mr F.U.C.K", (None, "name_blocked")), (42, (None, "name_bad")),
])
def test_clean_name(raw, want):
    assert G.clean_name(raw) == want


def test_shuffle_is_free_on_the_welcome_screen_and_renames_are_counted_after():
    async def go():
        w = await _night()
        g = _guests(w)
        pid = await _phone(g, join=False)
        seen = set()
        for _ in range(6):                               # free before "Let's go"
            code, out = await g.rename(pid, shuffle=True)
            assert code == 200
            seen.add(out["view"]["me"]["name"])
        assert len(seen) > 1
        code, out = await g.join(pid, "Disco Ana")
        assert out["view"]["me"] == {"name": "Disco Ana", "joined": True, "renames_left": 3}
        for left in (2, 1, 0):
            code, out = await g.rename(pid, shuffle=True)
            assert code == 200 and out["view"]["me"]["renames_left"] == left
        code, out = await g.rename(pid, "Another")
        assert (code, out["reason"]) == (422, "renames_used")
    _run(go())


def test_two_phones_cant_share_a_name():
    async def go():
        w = await _night()
        g = _guests(w)
        a = await _phone(g)
        b = await _phone(g, join=False)
        assert (await g.rename(a, "Disco Ana"))[0] == 200
        for call in (g.rename(b, "disco ana"), g.join(b, "DISCO ANA")):
            code, out = await call
            assert (code, out["reason"]) == (422, "name_taken")
    _run(go())


# ═══ 3. votes ══════════════════════════════════════════════════════════════

def test_votes_tally_change_and_withdraw_on_the_song_playing():
    async def go():
        w = await _night()
        g = _guests(w)
        a, b = await _phone(g), await _phone(g)
        code, out = await g.vote(a, "up")
        assert code == 200 and out["view"]["now"]["votes"] == {"up": 1, "down": 0}
        assert out["view"]["now"]["my_vote"] == 1
        await g.vote(b, "down")
        code, out = await g.vote(a, "down")                # changing a vote moves it
        assert out["view"]["now"]["votes"] == {"up": 0, "down": 2}
        code, out = await g.vote(a, "none")                # and taking it back
        assert out["view"]["now"]["votes"] == {"up": 0, "down": 1}
        assert out["view"]["now"]["my_vote"] == 0
        assert (await g.vote(a, "sideways"))[1]["reason"] == "bad_vote"
    _run(go())


def test_a_phone_votes_only_after_lets_go():
    async def go():
        w = await _night()
        g = _guests(w)
        pid = await _phone(g, join=False)
        code, out = await g.vote(pid, "up")
        assert (code, out["reason"]) == (409, "not_joined")
    _run(go())


def test_the_next_play_starts_a_fresh_tally():
    async def go():
        w = await _night(set_s=60)
        g = _guests(w)
        a = await _phone(g)
        await g.vote(a, "up")
        first = w.runner.night.now.uri
        await w.run(62)                                    # the next set song starts
        assert w.runner.night.now.uri != first
        out = (await g.view(a))[1]["view"]["now"]
        assert out["votes"] == {"up": 0, "down": 0} and out["my_vote"] == 0
    _run(go())


def test_a_play_is_the_song_and_when_it_started():
    one = NowItem(kind="set", uri="spotify:track:x", started_ms=1)
    two = NowItem(kind="set", uri="spotify:track:x", started_ms=2)
    assert G.play_key(one) != G.play_key(two)


def test_your_own_song_is_everyone_elses_to_vote_on():
    async def go():
        w = await _night(set_s=60, every=1)
        g = _guests(w)
        mine, other = await _phone(g), await _phone(g)
        assert (await w.runner.add(jb_uri(0), added_by=mine))["status"] == "added"
        await w.run(60)                                    # the jukebox slot plays it
        assert w.runner.night.now.kind == "jukebox"
        out = (await g.view(mine))[1]["view"]
        assert out["now"]["mine"] and not out["now"]["can_vote"]
        assert out["now"]["why_not"] == G.sentence("own_song")
        code, ref = await g.vote(mine, "up")
        assert (code, ref["reason"]) == (409, "own_song")
        assert (await g.vote(other, "up"))[0] == 200
        assert out["strip"]["tone"] == "playing"
    _run(go())


def test_a_song_outside_the_program_cant_be_voted_on():
    async def go():
        w = await _night()
        g = _guests(w)
        pid = await _phone(g)
        w.player.foreign_context = "spotify:playlist:someone-elses"
        w.player.start_context(3)
        await w.run(1)
        assert w.runner.night.now.kind == "foreign"
        code, out = await g.vote(pid, "up")
        assert (code, out["reason"]) == (409, "not_votable")
    _run(go())


# ═══ 4. the view ═══════════════════════════════════════════════════════════

def test_the_view_names_who_added_each_song_and_never_shows_a_code():
    async def go():
        w = await _night(set_s=60, every=1)
        g = _guests(w)
        ana, ben = await _phone(g), await _phone(g)
        await g.rename(ana, "Disco Ana")
        await w.runner.add(jb_uri(0), added_by=ana)
        await w.runner.add(jb_uri(1), added_by="host")
        view = (await g.view(ben))[1]["view"]
        assert view["now"]["by"] == {"kind": "set", "name": "Host's set"}
        kinds = [(s["kind"], s["by"]["name"]) for s in view["next"]]
        assert ("jukebox", "Disco Ana") in kinds and ("jukebox", "the host") in kinds
        assert all(s["kind"] in ("set", "jukebox") for s in view["next"])   # no open slots
        assert [s["place"] for s in view["next"]] == list(range(1, len(view["next"]) + 1))
        text = json.dumps(view)
        assert ana not in text and ben not in text
        assert view["next"][0]["open_url"].startswith("https://open.spotify.com/track/")
    _run(go())


def test_your_songs_strip_goes_queued_then_next_then_playing():
    async def go():
        w = await _night(set_s=60, every=2)
        g = _guests(w)
        pid = await _phone(g)
        assert (await g.view(pid))[1]["view"]["strip"]["tone"] == "none"
        await w.runner.add(jb_uri(0), added_by=pid)
        strip = (await g.view(pid))[1]["view"]["strip"]
        assert strip["tone"] == "queued" and strip["place"] == 2 and strip["starts_in_ms"] > 0
        seen = []
        for _ in range(240):
            await w.run(1)
            tone = (await g.view(pid))[1]["view"]["strip"]["tone"]
            if not seen or seen[-1] != tone:
                seen.append(tone)
        assert seen[:3] == ["queued", "next", "playing"]
        assert seen[-1] == "none"                        # it played: nothing waiting
    _run(go())


def test_the_book_is_kept_on_disk():
    async def go():
        w = await _night()
        g = _guests(w)
        pid = await _phone(g)
        await g.vote(pid, "up")
        saved = GuestBook.model_validate(json.loads(store.GUESTS_FILE.read_text()))
        assert saved.night_id == w.runner.night.id and saved.phones[pid].joined
        again = _guests(w)                              # a restart reads it back
        assert (await again.view(pid))[1]["view"]["now"]["my_vote"] == 1
    _run(go())


def test_album_art_is_the_largest_up_to_640_and_the_smallest_from_64():
    obj = {"album": {"images": [{"url": "big", "width": 640}, {"url": "mid", "width": 300},
                                {"url": "small", "width": 64}]}}
    assert gateway.art(obj) == ("big", "small")
    assert gateway.art({"album": {"images": [{"url": "huge", "width": 1200}]}}) == ("huge", "huge")
    assert gateway.art({}) == ("", "")


# ═══ 5. the door: SpotFX's guest routes answer the guest app's key only ═══

def test_the_guest_routes_need_the_guest_apps_key(monkeypatch):
    w = World()
    w.runner = night_mod.JukeboxRunner(w.deps)
    monkeypatch.setattr(night_mod, "runner", w.runner)
    app = FastAPI()
    app.include_router(jukebox_guest_router.router)
    app.include_router(jukebox_router.router)
    key = guest_key.load_or_create(jukebox_guest_router.KEY_FILE)
    with TestClient(app) as c:
        for headers in ({}, {guest_key.HEADER: "nope"}):
            assert c.post("/api/jukebox/guest/hello", json={}, headers=headers).status_code == 401
            assert c.get("/api/jukebox/guest/view", headers=headers).status_code == 401
        r = c.post("/api/jukebox/guest/hello", json={"token": "x"}, headers={guest_key.HEADER: key})
        assert r.status_code == 200 and r.json()["state"] == "idle"
        assert c.get("/api/jukebox/status").json()["guests"] == {"phones": 0, "joined": 0}


def test_the_key_file_is_made_once_and_private(tmp_path):
    path = tmp_path / "k"
    a = guest_key.load_or_create(path)
    assert guest_key.load_or_create(path) == a and len(a) > 30
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert guest_key.matches(a, a) and not guest_key.matches(None, a) and not guest_key.matches("x", a)
