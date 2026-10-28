"""The Live tab's economy panel (the plan's §9 3.3 "Live economy panel"; §7's
host Live view: "the economy right now, recent events"). The credits right
now are the post-party report's own section read while the night runs; the
prices are the ones a guest's Shop shows; the recent events are the ledger's
groups in words, routine entries counted instead of listed."""
from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.jukebox import EconomyConfig
from routers import jukebox_router
from services.jukebox import economy_live, guests as G, ledger as L, night as night_mod, night_report, store
from tests.jukebox_world import World, jb_uri
from tests.test_jukebox_credits_play import _bal, _gift, _setup, _show, _wallet
from tests.test_jukebox_guest_add import TOKEN, Catalog, Lib, _inline, _night, _phone


def _run(coro):
    return asyncio.run(coro)


def _led() -> L.Ledger:
    t = [1000]

    def now() -> int:
        t[0] += 1000
        return t[0]
    return L.Ledger("n1", EconomyConfig(), persist=False, now_ms=now)


NAMES = {"a": "Disco Ana", "b": "Lucky Otter", "c": "Velvet Moose"}
TITLES = {"spotify:track:x": "Take On Me", "e1": "Dopamine"}


def test_events_are_the_ledgers_groups_in_words_newest_first():
    led = _led()
    for p in ("a", "b", "c"):
        led.grant(p, "start", 4)                          # routine: counted, not listed
    led.vote("a", "spotify:track:x@5", own_song=False)    # routine
    led.spend("a", "add", 3, "e1")
    led.tip("b", "a", "spotify:track:x@5", 2, adder_is_host=False)
    for p in ("a", "b", "c"):                             # "Everyone +2" is one moment
        led.grant(p, "host_gift", 2)
    led.zero("c")
    led.merge("b", "a")
    ev = economy_live.events(led.entries, NAMES, TITLES)
    words = [f"{e['who']} {e['what']}" for e in ev]
    assert words[0] == "the host merged Lucky Otter into Disco Ana"
    assert words[1] == "the host took Velvet Moose's 6 credits back" and ev[1]["credits"] == -6
    assert ev[2]["credits"] == 2 and ev[2]["kind"] == "host_gift" and ev[2]["phones"] == 3
    assert words[2] == "the host gave 3 guests 2 each"
    assert words[3] == "Lucky Otter tipped Disco Ana 2 on “Take On Me” (+2 bonus)" and ev[3]["credits"] == -2
    assert words[4] == "Disco Ana added “Dopamine”" and ev[4]["credits"] == -3
    assert len(ev) == 5                                   # no votes, no welcomes
    assert economy_live.routine_counts(led.entries) == {"votes": 1, "free": 12}


def test_everyone_plus_two_is_one_event_and_the_list_is_bounded():
    led = L.Ledger("n1", EconomyConfig(), persist=False, now_ms=lambda: 7)
    for p in ("a", "b", "c"):
        led.grant(p, "host_gift", 2)
    ev = economy_live.events(led.entries, NAMES, TITLES)
    assert len(ev) == 1 and ev[0]["what"] == "gave 3 guests 2 each" and ev[0]["phones"] == 3
    apart = L.Ledger("n1", EconomyConfig(), persist=False, now_ms=iter([10_000, 40_000, 40_050]).__next__)
    for p in ("a", "b", "c"):                         # two gifts half a minute apart are two
        apart.grant(p, "host_gift", 2)
    assert [e["what"] for e in economy_live.events(apart.entries, NAMES, TITLES)] == [
        "gave 2 guests 2 each", "gave Disco Ana 2"]
    led2 = _led()
    for i in range(40):
        led2.grant("a", "qr_bonus" if i == 0 else "host_gift", 1)
    assert len(economy_live.events(led2.entries, NAMES, TITLES)) == economy_live.EVENTS_SHOWN


def test_the_credits_right_now_are_the_reports_own_numbers():
    led = _led()
    led.grant("a", "start", 4)
    led.grant("b", "start", 4)
    led.spend("a", "add", 3, "e1")
    now = economy_live.credits_now(led.entries, 2.0, guests=2)
    cs = night_report.credits_section(led.entries, 2.0)
    assert (now["held"], now["minted"], now["unspent_share"]) == (cs["held_at_end"], cs["minted"], cs["unspent_share"])
    assert now["held"] == 5 and now["held_per_guest"] == 2.5 and now["adds"] == 1
    assert economy_live.credits_now([], None, guests=0)["held_per_guest"] is None


def test_the_panel_reads_a_running_credits_night():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana, ben = await _phone(g), await _phone(g)
        _gift(g, w, ana, 10)
        code, out = await g.add(ana, jb_uri(0))
        assert code == 200, out
        out = g.economy()
        assert out["running"] and out["play_mode"] == "credits" and out["joined"] == 2
        c = out["credits"]
        assert c["held"] == _bal(g, w, ana) + _bal(g, w, ben) and c["held_per_guest"] == c["held"] / 2
        assert c["adds"] == 1 and c["free"] == 8
        p = out["prices"]
        assert p["add_first"] >= show_base() and p["jail_fee"] == 10 and p["next_from"] >= 8
        assert out["events"][0]["what"].startswith("added ") and out["events"][0]["who"] == g._book.phones[ana].name
        assert not any(pid in str(out) for pid in (ana, ben))      # names only, never a phone's code
        assert _wallet(g, w).led.verify() == []
    _run(go())


def show_base() -> int:
    return EconomyConfig().add_base


def test_free_play_and_no_night_say_so():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, _show().model_copy(update={"play_mode": "free"}))
        a = await _phone(g)
        assert (await g.vote(a, "up"))[0] == 200
        out = g.economy()
        assert out["credits"] is None and out["prices"] is None and out["events"] == []
        assert out["votes"] == 1 and out["time_outs"] == 0
    _run(go())
    g = G.Guests(G.GuestDeps(state=lambda: {"running": False}))
    assert g.economy()["running"] is False


def test_the_economy_route(monkeypatch):
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
    app.include_router(jukebox_router.router)
    with TestClient(app) as c:
        assert c.get("/api/jukebox/economy").json() == {"running": False, "play_mode": "credits"}
        store.save_config(store.load_config().model_copy(update={"playlist": w.cfg.playlist}))
        assert c.post("/api/jukebox/night/start", json={}).json()["status"] == "running"
        c.portal.call(_phone, g)
        out = c.get("/api/jukebox/economy").json()
        assert out["running"] and out["credits"]["held"] == 4 and out["events"] == []
