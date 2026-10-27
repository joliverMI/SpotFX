"""Credits mode on the guest page (services/jukebox/guests.py + wallet.py,
the plan's §1 rulebook and PR 3.2): the welcome credits and top-ups, +1 a
vote, Adder credits for ▲, tips with the first credits doubled, priced adds,
bumps and play next, a skip paid alone or by chip-in (pledges back if the pot
isn't filled), the jail until break-out, refunds, and the host's skip lock.
Every credit goes through the night's ledger, whose own verify() must find
the file sound afterwards. Driven over the fake Jukebox world
(tests/jukebox_world.py), so what plays is what the engine plays."""
from __future__ import annotations

import asyncio
import random

from fastapi import FastAPI
from fastapi.testclient import TestClient

from jukebox_guest import app as guest_app, key as guest_key
from models.jukebox import EconomyConfig, ShowConfig
from routers import jukebox_guest_router, jukebox_router
from services.jukebox import economy, guests as G, night as night_mod, store
from tests.jukebox_world import World, jb_uri, set_uri
from tests.test_jukebox_guest_add import TOKEN, Catalog, Lib, _inline, _night, _phone


def _run(coro):
    return asyncio.run(coro)


def _show(**kw) -> ShowConfig:
    eco = kw.pop("economy", {})
    return ShowConfig(play_mode="credits", economy=EconomyConfig(**eco), **kw)


def _setup(w: World, show: ShowConfig | None = None, known=()) -> G.Guests:
    store.save_show(show or _show())

    async def sleep(s: float) -> None:
        await w.run(int(s) + 1)

    return G.Guests(G.GuestDeps(
        state=lambda: w.runner.guest_state(count=24), token_ok=lambda t: t == TOKEN,
        now_ms=lambda: int(w.clock.t * 1000), to_thread=_inline, rng=random.Random(1),
        runner=lambda: w.runner, gateway=lambda: Catalog(w), library_search=Lib([]),
        known=lambda uris: {u: u in set(known) for u in uris}, clock=w.clock, sleep=sleep))


def _wallet(g: G.Guests, w: World):
    return g._wallet_for(w.runner.night.id, store.load_show())


def _gift(g: G.Guests, w: World, pid: str, n: int) -> None:
    wal = _wallet(g, w)
    wal.noted([wal.led.grant(pid, "host_gift", n)])


def _bal(g: G.Guests, w: World, pid: str) -> int:
    return _wallet(g, w).balance(pid)


async def _phones(g: G.Guests, n: int) -> list[str]:
    return [await _phone(g) for _ in range(n)]


async def _until_playing(w: World, uri: str, limit: int = 900) -> None:
    for _ in range(limit):
        if w.player.current == uri:
            return
        await w.run(1)
    raise AssertionError(f"{uri} never played; played {w.played()}")


def _sound(g: G.Guests, w: World) -> None:
    assert _wallet(g, w).led.verify() == []


# ═══ 1. earning ════════════════════════════════════════════════════════════

def test_welcome_credits_half_now_the_rest_after_twenty_minutes_then_top_ups():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana = await _phone(g)
        view = (await g.view(ana))[1]["view"]
        assert view["me"]["credits"] == 4 and view["features"]["credits"] and view["start_credits"] == 8
        for _ in range(20):                                       # polling, 20 minutes
            w.clock.t += 60
            await g.view(ana)
        assert _bal(g, w, ana) == 8                               # the rest of the welcome credits
        for _ in range(25):                                       # to 45 minutes
            w.clock.t += 60
            await g.view(ana)
        assert _bal(g, w, ana) == 9                               # a top-up
        _gift(g, w, ana, 5)                                        # 14 held: top-ups pause at 10
        for _ in range(46):
            w.clock.t += 60
            await g.view(ana)
        assert _bal(g, w, ana) == 14
        _sound(g, w)
    _run(go())


def test_a_phone_that_was_away_gets_no_missed_top_ups():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana = await _phone(g)
        await g.view(ana)
        w.clock.t += 3 * 3600                                     # away three hours
        await g.view(ana)
        assert _bal(g, w, ana) == 8                               # the welcome credits, no top-ups
        for _ in range(46):
            w.clock.t += 60
            await g.view(ana)
        assert _bal(g, w, ana) == 9                               # top-ups resume from coming back
    _run(go())


def test_a_vote_earns_once_per_song_and_adder_credits_follow_the_song():
    async def go():
        w = await _night(set_s=60, jb_s=60)
        g = _setup(w)
        ana, ben, cy, dee = await _phones(g, 4)
        code, out = await g.vote(ben, "up")
        assert code == 200 and out["earned"] == 1 and _bal(g, w, ben) == 5
        assert (await g.vote(ben, "down"))[1]["earned"] == 0      # changing your vote pays nothing more
        _gift(g, w, ana, 10)
        assert (await g.add(ana, jb_uri(0)))[0] == 200
        await _until_playing(w, jb_uri(0))
        view = (await g.view(ana))[1]["view"]
        assert view["now"]["coming_in"] == {"ups": 0, "tips": 0}
        for p in (ben, cy, dee):
            await g.vote(p, "up")
        assert (await g.view(ana))[1]["view"]["now"]["coming_in"]["ups"] == 3
        before = _bal(g, w, ana)
        await w.run(61)                                           # J0 ends
        await g.view(ana)
        assert _bal(g, w, ana) == before + 3                      # +1 per ▲, once it has played
        await g.view(ana)
        assert _bal(g, w, ana) == before + 3                      # once
        _sound(g, w)
    _run(go())


def test_tips_go_to_the_adder_with_the_first_credits_doubled_never_host_or_self():
    async def go():
        w = await _night(set_s=60, jb_s=100)
        g = _setup(w)
        ana, ben = await _phones(g, 2)
        _gift(g, w, ana, 10)
        await g.add(ana, jb_uri(0))
        await _until_playing(w, jb_uri(0))
        a0, b0 = _bal(g, w, ana), _bal(g, w, ben)
        code, out = await g.tip(ben, 1)
        assert code == 200 and out["tipped"] == {"to": (await g.view(ana))[1]["view"]["me"]["name"],
                                                 "amount": 1, "bonus": 1}
        assert _bal(g, w, ben) == b0 - 1 and _bal(g, w, ana) == a0 + 2
        assert (await g.tip(ben, 2))[0] == 200
        code, out = await g.tip(ben, 1)
        assert code == 409 and out["reason"] == "tip_cap"
        assert (await g.tip(ana, 1))[1]["reason"] == "host_tip" or \
            (await g.tip(ana, 1))[1]["reason"] == "own_tip"
        view = (await g.view(ben))[1]["view"]
        assert view["now"]["tip"]["left"] == 0 and not view["now"]["tip"]["can"]
        _sound(g, w)
    _run(go())


def test_the_hosts_songs_take_no_tips():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ben = await _phone(g)
        code, out = await g.tip(ben, 1)
        assert code == 409 and out["reason"] == "host_tip"
        assert (await g.view(ben))[1]["view"]["now"]["tip"]["why"] == "The host's songs take no tips."
    _run(go())


# ═══ 2. spending ═══════════════════════════════════════════════════════════

KNOWN = [jb_uri(i) for i in range(12)]


def test_an_add_is_priced_by_its_wait_locked_and_refunded_if_the_host_removes_it():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, known=KNOWN[1:])                            # J0 isn't learned yet: +1
        ana, ben = await _phones(g, 2)
        found = (await g.search(ana, "Song"))[1]
        prices = {r["uri"]: r["price"] for r in found["results"]}
        assert prices[jb_uri(1)] == 4 and prices[jb_uri(0)] == 5           # learn first +1
        assert [r["afford"] for r in found["results"] if r["uri"] == jb_uri(0)] == [False]
        code, out = await g.add(ana, jb_uri(1), price=prices[jb_uri(1)])
        assert code == 200 and out["added"]["paid"] == 4 and _bal(g, w, ana) == 0
        entry = w.runner.night.line[0]
        assert entry.paid == 4 and entry.paid_seq
        code, out = await g.add(ben, jb_uri(3), price=1)          # the page showed less
        assert code == 409 and out["reason"] == "price_changed" and out["price"] == 4
        assert len(w.runner.night.line) == 1                      # nothing added, nothing charged
        code, out = await g.add(ana, jb_uri(2))
        assert code == 409 and out["reason"] == "not_enough"
        await w.runner.remove(entry.id)                           # the host removes it
        await g.view(ana)
        assert _bal(g, w, ana) == 4                               # refunded
        hist = (await g.wallet_view(ana))[1]["history"]
        assert [h["kind"] for h in hist[:2]] == ["refund", "add"]
        _sound(g, w)
    _run(go())


def test_bumps_cost_credits_and_have_no_hourly_limit():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana, ben, cy = await _phones(g, 3)
        for p, i in ((ana, 0), (ben, 1), (cy, 2)):
            _gift(g, w, p, 20)
            await g.add(p, jb_uri(i))
        cy_j2 = next(e.id for e in w.runner.night.line if e.uri == jb_uri(2))
        view = (await g.view(cy))[1]["view"]
        row = next(s for s in view["next"] if s.get("entry_id") == cy_j2)
        assert row["bump"] == "up" and row["bump_price"] == economy.bump_up_price(0, EconomyConfig())
        before = _bal(g, w, cy)
        for _ in range(2):
            assert (await g.bump(cy, cy_j2, "up", price=10))[0] == 200
        assert _bal(g, w, cy) == before - 2 - 3                   # 2 + 0 behind, then 2 + 1 behind
        ana_j0 = next(e.id for e in w.runner.night.line if e.uri == jb_uri(0))
        code, out = await g.bump(ben, ana_j0, "down", price=1)   # dearer now than the page showed
        assert code == 409 and out["reason"] == "price_changed"
        _sound(g, w)
    _run(go())


def test_play_next_is_once_per_song_at_least_ten_minutes_away():
    async def go():
        w = await _night(set_s=300, jb_s=300, every=1, run=1)
        g = _setup(w, known=KNOWN)
        ps = await _phones(g, 4)
        for i, p in enumerate(ps):
            _gift(g, w, p, 40)
            await g.add(p, jb_uri(i))
        last = ps[-1]
        j3 = next(e.id for e in w.runner.night.line if e.uri == jb_uri(3))
        view = (await g.view(last))[1]["view"]
        q = next(s for s in view["mine"] if s["entry_id"] == j3)["next"]
        assert q["allowed"] and q["price"] >= 8
        code, out = await g.play_next(last, j3, price=q["price"])
        assert code == 200, out
        waiting = [e.uri for e in w.runner.night.line if e.state == "queued"]
        assert waiting[0] == jb_uri(3)
        code, out = await g.play_next(last, j3)
        assert out["reason"] == "at_front_next"
        j0 = next(e.id for e in w.runner.night.line if e.uri == jb_uri(0))
        assert (await g.play_next(ps[0], j0))[0] == 200           # 15 min away: allowed
        await g.play_next(last, j3)                               # behind J0 now, but it's had its turn
        assert (await g.play_next(last, j3))[1]["reason"] == "nexted"
        _sound(g, w)
    _run(go())


def test_play_next_counts_against_the_push_back_cap_per_song():
    """The cap is per song, whatever moved it (the firstmate's ruling on PR
    2.3, "a play-next jump if it pushes songs back" included): every song a
    play next jumps past is a place further back, and a guest's play next
    is refused — before anything is charged — once one of them is already
    at the cap. The host's Play next counts the same way but is never
    refused."""
    async def go():
        w = await _night(set_s=300, jb_s=300, every=1, run=1)
        g = _setup(w, known=KNOWN)
        ps = await _phones(g, 4)
        for i, p in enumerate(ps):
            _gift(g, w, p, 80)
            await g.add(p, jb_uri(i))
        line = w.runner.night.line
        ids = {i: next(e.id for e in line if e.uri == jb_uri(i)) for i in range(4)}
        by = {e.id: e for e in line}
        waiting = [e.id for e in line if e.state == "queued"]
        jumped = waiting[:waiting.index(ids[3])]
        assert jumped and all(by[x].pushed_back == 0 for x in jumped)
        # one song it would jump past is already at the cap: refused, nothing charged
        cap = g.deps.show().economy.bump_down_max_places
        by[jumped[-1]].pushed_back = cap
        row = next(s for s in (await g.view(ps[3]))[1]["view"]["mine"] if s["entry_id"] == ids[3])
        assert row["next"]["allowed"] is False and "as far as it can go" in row["next"]["why"]
        before = g._wallet.balance(ps[3])
        code, out = await g.play_next(ps[3], ids[3], price=row["next"]["price"])
        assert code == 409 and out["reason"] == "next_pushed_max", out
        assert g._wallet.balance(ps[3]) == before and not by[ids[3]].nexted
        # below the cap: it lands, and every song it jumped past is a place back
        by[jumped[-1]].pushed_back = cap - 1
        row = next(s for s in (await g.view(ps[3]))[1]["view"]["mine"] if s["entry_id"] == ids[3])
        assert row["next"]["allowed"]
        code, out = await g.play_next(ps[3], ids[3], price=row["next"]["price"])
        assert code == 200, out
        assert [by[x].pushed_back for x in jumped] == [1] * (len(jumped) - 1) + [cap]
        # the host's Play next (a move to the front): counted, never refused —
        # even past a song already at the cap
        waiting = [e.id for e in line if e.state == "queued"]
        host_jumped = waiting[:waiting.index(ids[2])]
        by[host_jumped[-1]].pushed_back = cap
        before_counts = [by[x].pushed_back for x in host_jumped]
        out = await w.runner.move(ids[2], 0)
        assert out["status"] == "moved"
        assert [by[x].pushed_back for x in host_jumped] == [c + 1 for c in before_counts]
        assert [e.id for e in w.runner.night.line if e.state == "queued"][0] == ids[2]
    _run(go())


def test_play_next_is_refused_for_a_song_under_ten_minutes_away():
    async def go():
        w = await _night(set_s=60, jb_s=60)
        g = _setup(w, known=KNOWN)
        ana, ben = await _phones(g, 2)
        for p, i in ((ana, 0), (ben, 1)):
            _gift(g, w, p, 40)
            await g.add(p, jb_uri(i))
        j1 = next(e.id for e in w.runner.night.line if e.uri == jb_uri(1))
        row = next(s for s in (await g.view(ben))[1]["view"]["mine"] if s["entry_id"] == j1)
        assert row["next"]["allowed"] is False and "10 minutes" in row["next"]["why"]
        code, out = await g.play_next(ben, j1)
        assert code == 409 and out["reason"] == "next_too_soon"
    _run(go())


def test_a_skip_paid_alone_after_the_first_seconds():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana = await _phone(g)
        _gift(g, w, ana, 100)
        code, out = await g.skip(ana, "pay")
        assert code == 409 and out["reason"] == "skip_grace"
        await w.run(20)
        price = (await g.view(ana))[1]["view"]["now"]["skip"]["price"]
        code, out = await g.skip(ana, "pay", price=price)
        assert code == 200 and out["skip"]["skipped"] and out["skip"]["paid"] == price
        await w.run(1)
        assert w.played() == ["S0", "S1"]
        assert any("paid to skip" in x for x in w.runner.night.log)
        _sound(g, w)
    _run(go())


def test_a_chip_in_pot_skips_when_it_is_full_and_comes_back_if_it_isnt():
    async def go():
        w = await _night(set_s=60)
        g = _setup(w)
        ana, ben, cy = await _phones(g, 3)
        for p in (ana, ben, cy):
            _gift(g, w, p, 100)
        await w.run(20)
        price = (await g.view(ana))[1]["view"]["now"]["skip"]["price"]
        half = price // 2
        assert (await g.skip(ana, "chip", amount=half))[1]["skip"]["skipped"] is False
        view = (await g.view(ben))[1]["view"]
        assert view["now"]["skip"]["pot"] == half and view["now"]["skip"]["need"] == price - half
        code, out = await g.skip(ben, "chip", amount=price)      # capped at what's needed
        assert out["skip"]["skipped"] and out["skip"]["paid"] == price - half
        assert _bal(g, w, ben) == 104 - (price - half)
        # next song: a pot that isn't filled comes back when the song ends
        await w.run(2)
        await w.run(20)
        a0 = _bal(g, w, cy)
        assert (await g.skip(cy, "chip", amount=2))[0] == 200
        assert _bal(g, w, cy) == a0 - 2
        await w.run(60)                                           # the song ends
        await g.view(cy)
        assert _bal(g, w, cy) == a0                               # pledge returned
        _sound(g, w)
    _run(go())


def test_a_down_vote_can_fill_a_pot_by_lowering_the_price():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ps = await _phones(g, 6)
        for p in ps:
            _gift(g, w, p, 100)
        await w.run(20)
        price = (await g.view(ps[0]))[1]["view"]["now"]["skip"]["price"]
        await g.skip(ps[0], "chip", amount=price - 4)
        for p in ps[1:]:
            await g.vote(p, "down")
            if w.runner.night.now.kind == "skipping":
                break
        assert w.runner.night.now.kind == "skipping"              # the ▼ brought the price to the pot
    _run(go())


# ═══ 3. the jail, the skip lock, the night's end ═══════════════════════════

def test_credits_jail_lasts_until_the_guest_breaks_out():
    async def go():
        w = await _night(set_s=60, jb_s=60)
        g = _setup(w, _show(economy={"jail_scale": False, "skip_grace_s": 0}))
        ps = await _phones(g, 7)
        ana = ps[0]
        _gift(g, w, ana, 30)
        await g.add(ana, jb_uri(0))
        await g.add(ana, jb_uri(1))
        await _until_playing(w, jb_uri(0))
        for p in ps[1:6]:
            await g.vote(p, "down")
        view = (await g.view(ana))[1]["view"]
        assert view["me"]["jail"]["in"] and view["me"]["jail"]["kind"] == "breakout"
        assert view["strip"]["jail_kind"] == "breakout"
        await w.run(60 * 8)                                       # songs go by: still in jail
        assert ana in w.runner.night.jail
        code, out = await g.add(ana, jb_uri(5))
        assert out["reason"] == "jailed_credits" and "10 credits" in out["detail"]
        before = _bal(g, w, ana)
        code, out = await g.break_out(ana)
        assert code == 200 and out["broke_out"]["paid"] == 10 and _bal(g, w, ana) == before - 10
        assert ana not in w.runner.night.jail
        assert (await g.view(ana))[1]["view"]["me"]["jail"]["count"] == 0
        assert (await g.break_out(ana))[1]["reason"] == "not_jailed_self"
        _sound(g, w)
    _run(go())


def test_the_host_keeps_a_song_from_skips_in_both_modes():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana = await _phone(g)
        _gift(g, w, ana, 100)
        await w.run(20)
        assert (await w.runner.set_skip_lock(set_uri(0), True))["status"] == "locked"
        view = (await g.view(ana))[1]["view"]
        assert view["now"]["skip"]["locked"] and not view["now"]["skip"]["can"]
        code, out = await g.skip(ana, "pay")
        assert code == 409 and out["reason"] == "skip_locked"
        assert (await w.runner.skip_by_vote(w.runner.night.now.started_ms, set_uri(0)))["reason"] \
            == "skip_locked"
        store.save_show(ShowConfig(play_mode="free", economy=EconomyConfig(skip_grace_s=0)))  # free play
        ps = await _phones(g, 3)
        for p in ps:
            await g.vote(p, "down")
        assert w.player.current == set_uri(0)                     # the room's vote can't either
        await w.runner.set_skip_lock(set_uri(0), False)
        await g.vote(ps[0], "none")
        await g.vote(ps[0], "down")
        await w.run(1)
        assert w.player.current == set_uri(1)
    _run(go())


def test_a_paid_song_that_never_played_is_refunded_when_the_night_ends():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, known=KNOWN)
        ana = await _phone(g)
        _gift(g, w, ana, 10)
        await g.add(ana, jb_uri(0))
        assert _bal(g, w, ana) == 14 - 4
        await w.runner.stop()
        code, out = await g.view(ana)
        assert out["state"] == "idle"
        assert g._wallet.balance(ana) == 14
        assert g._wallet.led.verify() == []
    _run(go())


# ═══ 4. free play is untouched; the page's words; the doors ═════════════════

def test_free_play_has_no_credits_and_refuses_credit_calls():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, ShowConfig(play_mode="free"))
        ana = await _phone(g)
        view = (await g.view(ana))[1]["view"]
        assert not view["features"]["credits"] and "credits" not in view["me"]
        assert view["now"]["skip"]["mode"] == "vote" and "tip" not in view["now"]
        for call in (g.tip(ana, 1), g.skip(ana, "pay"), g.break_out(ana), g.wallet_view(ana)):
            code, out = await call
            assert code == 409 and out["reason"] == "credits_off"
        found = (await g.search(ana, "Song"))[1]
        assert "price" not in found["results"][0]
    _run(go())


def test_the_house_rules_and_the_shop_say_the_credits_rules():
    rules = G.house_rules(_show())
    assert any("Skips cost credits" in r for r in rules)
    assert any("break out (10 credits)" in r for r in rules)
    assert any("can't be bought, sold, traded or cashed out" in r for r in rules)

    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana = await _phone(g)
        code, out = await g.wallet_view(ana)
        assert code == 200 and out["balance"] == 4 and out["earned"]["free"] == 4
        assert [t["id"] for t in out["shop"]] == ["add", "next", "skip", "chip", "bump", "breakout"]
        assert out["history"][0]["what"] == "Welcome credits" and out["history"][0]["delta"] == 4
        assert "cashed out" in out["disclaimer"]
    _run(go())


def test_the_guest_doors_for_credits(monkeypatch, tmp_path):
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
        store.save_config(store.load_config().model_copy(update={"playlist": w.cfg.playlist}))
        assert c.post("/api/jukebox/night/start", json={}).json()["status"] == "running"
        ana = c.portal.call(_phone, g)
        h = {guest_key.HEADER: key}
        for path, body in (("tip", {"phone": ana}), ("skip", {"phone": ana, "how": "pay"}),
                           ("next", {"phone": ana, "entry_id": "x"}), ("breakout", {"phone": ana})):
            assert c.post(f"/api/jukebox/guest/{path}", json=body).status_code == 401
            assert c.post(f"/api/jukebox/guest/{path}", json=body, headers=h).status_code in (200, 404, 409)
        r = c.get("/api/jukebox/guest/wallet", params={"phone": ana}, headers=h)
        assert r.status_code == 200 and r.json()["balance"] == 4
        r = c.post("/api/jukebox/skip-lock", json={"uri": set_uri(0), "locked": True})
        assert r.json()["status"] == "locked" and w.runner.night.no_skip == [set_uri(0)]
    assert {("POST", "/g/tip"), ("POST", "/g/skip"), ("POST", "/g/next"), ("POST", "/g/breakout"),
            ("GET", "/g/wallet")} <= set(guest_app.ROUTES)
