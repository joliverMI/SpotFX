"""The host's Zero and Merge (the plan's §4 host buttons, §9 3.3's Guests tab,
§12's cookie-reset and second-phone guards). Zero takes a phone's credits to
0 and forgoes any welcome credits it hasn't had; Merge makes two phones one
guest — songs, votes, time-out and credits join the kept phone, and both
codes act as that one guest. Every credit through the night's ledger, whose
verify() must find it sound — including a merge replayed from its file."""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.jukebox import EconomyConfig, GuestBook, GuestPhone
from routers import jukebox_router
from services.jukebox import board, bonus_codes, guests as G, ledger as L, night as night_mod, night_report, store
from services.jukebox.wallet import Wallet
from tests.jukebox_world import World, jb_uri
from tests.test_jukebox_credits_play import _bal, _gift, _setup, _show, _sound, _wallet
from tests.test_jukebox_guest_add import TOKEN, Catalog, Lib, _inline, _night, _phone


def _run(coro):
    return asyncio.run(coro)


def _led(**kw) -> L.Ledger:
    return L.Ledger("n1", EconomyConfig(**kw), persist=False, now_ms=lambda: 1)


# ═══ 1. the ledger ═════════════════════════════════════════════════════════

def test_zero_takes_a_phone_to_exactly_nothing_and_never_below():
    led = _led()
    led.grant("a", "start", 4)
    led.spend("a", "add", 3)
    e = led.zero("a", "the host")
    assert e.kind == "host_zero" and e.delta == -1 and led.balance("a") == 0
    try:
        led.zero("a")
        raise AssertionError("zeroing an empty phone was accepted")
    except L.LedgerError as err:
        assert err.code == "nothing_to_zero"
    assert led.verify() == []


def test_a_merge_moves_the_balance_and_counts_the_two_phones_as_one_guest():
    led = _led(gift_double_first=5, tip_max_per_song=3)
    led.grant("old", "start", 4)
    led.grant("old", "host_gift", 10)
    led.vote("old", "song@1", own_song=False)                    # paid once, on the old phone
    led.tip("old", "adder", "song@1", 2, adder_is_host=False)    # 2 taps, 2 of the 5 doubled
    spend = led.spend("old", "add", 4)
    led.grant("new", "start", 4)
    out, inn = led.merge("old", "new")
    assert (out.kind, out.delta, out.ref) == ("merge_out", -9, "new")
    assert (inn.kind, inn.delta, inn.ref, inn.link) == ("merge_in", 9, "old", out.seq)
    assert led.balance("old") == 0 and led.balance("new") == 13 and led.owner("old") == "new"
    assert led.vote("new", "song@1", own_song=False) is None     # one person, one paid vote
    assert led.tipped_on("new", "song@1") == 2                   # and one tip allowance a song
    tip = led.tip("new", "adder", "song@1", 1, adder_is_host=False)
    assert [p.kind for p in tip] == ["tip_out", "tip_in", "tip_bonus"]
    try:
        led.tip("new", "adder", "song@1", 1, adder_is_host=False)
        raise AssertionError("a 4th tap on one song was accepted across the two phones")
    except L.LedgerError as err:
        assert err.code == "tip_cap"
    assert led.given("new") == 3                                 # the double-first allowance, shared
    # a write naming the retired phone lands on the guest it joined
    assert led.grant("old", "topup", 1).phone == "new"
    assert led.refund(spend.seq).phone == "new"                  # the old phone's song, refunded
    assert led.balance("old") == 0 and led.verify() == []


def test_merges_follow_their_chain_and_refuse_the_impossible():
    led = _led()
    led.grant("c", "start", 4)
    led.merge("c", "b")
    led.merge("b", "a")
    assert led.owner("c") == "a" and led.balance("a") == 4 and led.merged_out() == {"c": "a", "b": "a"}
    for gone, kept, code in (("b", "a", "merged"), ("a", "a", "merge_self"), ("a", "c", "merge_self")):
        try:
            led.merge(gone, kept)
            raise AssertionError(f"merging {gone} into {kept} was accepted")
        except L.LedgerError as err:
            assert err.code == code
    assert led.verify() == []


def test_a_merge_replays_from_its_file(tmp_path):
    path = tmp_path / "n1.jsonl"
    led = L.Ledger("n1", EconomyConfig(), path=path, now_ms=lambda: 1)
    led.grant("old", "start", 4)
    led.vote("old", "s@1", own_song=False)
    led.merge("old", "new")
    led.zero("new")
    again = L.Ledger("n1", EconomyConfig(), path=path, now_ms=lambda: 1)
    assert again.owner("old") == "new" and again.voted_paid("new", "s@1")
    assert again.balance("new") == 0 and again.verify() == []


def test_verify_catches_a_bad_zero_a_lone_merge_and_a_write_after_a_merge(tmp_path):
    def forged(lines: list[dict]) -> list[str]:
        path = tmp_path / "forged.jsonl"
        path.write_text("".join(json.dumps({"ref": "", "link": None, "group": d["seq"], "note": "",
                                            "at_ms": 1, **d}) + "\n" for d in lines))
        return L.Ledger("forged", EconomyConfig(), path=path).verify()

    start = {"seq": 1, "phone": "a", "delta": 4, "kind": "start"}
    assert any("a zero that left" in v for v in forged([start, {"seq": 2, "phone": "a", "delta": -1, "kind": "host_zero"}]))
    assert any("no matching merge_out" in v for v in forged([start, {"seq": 2, "phone": "b", "delta": 4, "kind": "merge_in", "ref": "a"}]))
    merged = [start, {"seq": 2, "phone": "a", "delta": -4, "kind": "merge_out", "ref": "b"},
              {"seq": 3, "phone": "b", "delta": 4, "kind": "merge_in", "ref": "a", "link": 2, "group": 2}]
    assert forged(merged) == []
    assert any("after it was merged" in v
               for v in forged(merged + [{"seq": 4, "phone": "a", "delta": 1, "kind": "topup"}]))


def test_the_wallet_forgoes_a_zeroed_welcome_and_carries_a_merged_one():
    cfg = EconomyConfig()
    w = Wallet("n1", cfg, persist=False)
    w.noted([w.led.grant("a", "start", 4)])
    w.noted([w.led.zero("a")])
    due, _ = w.due_grants("a", joined_ms=0, last_tick=None, now_ms=30 * 60_000, cfg=cfg)
    assert "start_rest" not in [k for k, _ in due]               # a reset buys nothing more
    w.noted([w.led.grant("old", "start", 4), w.led.grant("old", "start_rest", 4),
             w.led.grant("old", "qr_bonus", 5)])
    w.noted([w.led.grant("new", "start", 4)])
    w.noted(w.led.merge("old", "new"))
    due, _ = w.due_grants("new", joined_ms=0, last_tick=None, now_ms=30 * 60_000, cfg=cfg)
    assert [k for k, _ in due if k.startswith("start")] == []   # no second welcome
    assert "qr_bonus" in w.got["new"]                           # and no second bonus card


# ═══ 2. the guests ═════════════════════════════════════════════════════════

def test_a_cookie_reset_merged_back_is_one_guest_with_its_songs_credits_and_name():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        old = await _phone(g)
        await g.rename(old, "Disco Ana")
        _gift(g, w, old, 10)
        code, out = await g.add(old, jb_uri(0))
        assert code == 200, out
        codes = bonus_codes.mint(2)
        assert (await g.redeem_bonus(old, codes[0]))[0] == 200
        w.clock.t += 600
        new = await _phone(g)                                     # cleared cookies: a fresh welcome
        old_name = g._book.phones[old].name
        held = _bal(g, w, old) + _bal(g, w, new)
        code, out = await g.merge(old, new)
        assert code == 200, out
        assert out["merged"]["songs"] == 1 and out["merged"]["name"] == old_name
        book = g._book
        assert book.phones[new].name == old_name and book.phones[old].merged_into == new
        assert [p["id"] for p in out["phones"]] == [new]
        assert out["phones"][0]["merged_from"] and out["phones"][0]["credits"] == held
        assert all(e.added_by == new for e in w.runner.night.line if e.uri == jb_uri(0))
        # the old code still works, as the guest it joined
        view = (await g.view(old))[1]["view"]
        assert view["me"]["name"] == old_name and view["me"]["credits"] == held
        code, out = await g.hello(old, None)
        assert code == 200 and out["phone"] == new                # its page is handed the kept code
        assert (await g.redeem_bonus(new, codes[1]))[1]["reason"] == "bonus_used_tonight"
        w.clock.t += 30 * 60
        await g.view(new)
        assert not [e for e in _wallet(g, w).led.history(new) if e.kind == "start_rest"]
        assert g.summary(w.runner.night.id)["phones"] == 1
        _sound(g, w)
    _run(go())


def test_a_time_out_and_a_vote_carry_over_and_the_kept_vote_stands():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, _show().model_copy(update={"play_mode": "free", "free_jail_songs": 3}))
        a, b = await _phone(g), await _phone(g)
        assert (await g.vote(a, "up"))[0] == 200 and (await g.vote(b, "down"))[0] == 200
        assert (await w.runner.jail(b, 3))["status"] == "jailed"
        g._book.phones[b].jail_open = True
        code, out = await g.merge(b, a)
        assert code == 200, out
        st = w.runner.guest_state()
        assert G.jailed_now(st, a) == 3 and b not in st["jail"]
        key = G.play_key(st["now"])
        assert g._book.votes[key] == {a: 1}                      # one guest, the kept vote
        assert g._book.phones[a].jail_open
        assert store.load_guests().merged == {b: a}               # saved with the book
        assert not list(L.LEDGER_DIR.glob("*.jsonl"))              # free play: no ledger written
    _run(go())


def test_zero_takes_a_guests_credits_and_answers_honestly():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana = await _phone(g)
        code, out = await g.zero(ana)
        assert code == 200 and out["zeroed"]["credits"] == 4 and _bal(g, w, ana) == 0
        assert (await g.zero(ana))[1]["reason"] == "nothing_to_zero"
        w.clock.t += 25 * 60
        await g.view(ana)
        hist = (await g.wallet_view(ana))[1]["history"]
        assert hist[0]["what"] == "Set to zero by the host" and not any(h["kind"] == "start_rest" for h in hist)
        assert (await g.zero("Z" * 22))[1]["reason"] == "no_phone"
        _sound(g, w)
    _run(go())
    async def free():
        w = await _night(set_s=300)
        g = _setup(w, _show().model_copy(update={"play_mode": "free"}))
        assert (await g.zero(await _phone(g)))[1]["reason"] == "credits_off"
    _run(free())


def test_a_merge_refuses_what_it_cannot_do():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        a, b, c = await _phone(g), await _phone(g), await _phone(g)
        await g.host_set(c, blocked=True)
        assert (await g.merge(a, a))[1]["reason"] == "merge_self"
        assert (await g.merge(c, a))[1]["reason"] == "merge_blocked"
        assert (await g.merge("Z" * 22, a))[1]["reason"] == "no_phone"
        assert (await g.merge(b, a))[0] == 200
        assert (await g.merge(b, a))[1]["reason"] == "merged_phone"
        assert (await g.zero(b))[1]["reason"] == "merged_phone"
        _sound(g, w)
    _run(go())


def test_the_engine_moves_every_song_and_keeps_the_longer_time_out():
    async def go():
        w = await _night(set_s=300)
        r = w.runner
        n = r.night
        from models.jukebox import LineEntry
        n.line += [LineEntry(id="e1", uri="u:1", added_by="old", state="played"),
                   LineEntry(id="e2", uri="u:2", added_by="old"),
                   LineEntry(id="e3", uri="u:3", added_by="new")]
        await r.jail("old", 5)
        await r.jail("new", 2)
        out = await r.merge_phone("old", "new")
        assert out == {"status": "merged", "songs": 2}
        assert [e.added_by for e in n.line if e.id.startswith("e")] == ["new", "new", "new"]
        assert n.jail["new"] - n.plays == 5 and "old" not in n.jail
    _run(go())


# ═══ 3. the doors, the board and the report ═════════════════════════════════

def test_the_zero_and_merge_routes(monkeypatch):
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
        store.save_config(store.load_config().model_copy(update={"playlist": w.cfg.playlist}))
        assert c.post("/api/jukebox/night/start", json={}).json()["status"] == "running"
        a, b = c.portal.call(_phone, g), c.portal.call(_phone, g)
        r = c.post(f"/api/jukebox/guests/{a}/zero")
        assert r.status_code == 200 and r.json()["zeroed"]["credits"] == 4
        assert c.post(f"/api/jukebox/guests/{a}/zero").status_code == 409
        r = c.post(f"/api/jukebox/guests/{a}/merge", json={"retire": b})
        assert r.status_code == 200 and [p["id"] for p in r.json()["phones"]] == [a]
        assert r.json()["phones"][0]["credits"] == 4
        assert c.post(f"/api/jukebox/guests/{a}/merge", json={"retire": a}).status_code == 422
        assert c.post(f"/api/jukebox/guests/{a}/merge", json={}).status_code == 422


def test_the_board_and_the_report_count_a_merged_guest_once():
    led = _led()
    led.grant("old", "host_gift", 10)
    led.tip("old", "x", "s@1", 2, adder_is_host=False)
    led.grant("new", "start", 4)
    led.merge("old", "new")
    led.tip("new", "x", "s@2", 1, adder_is_host=False)
    assert board.tips_given(led.entries) == {"new": 3}
    assert night_report.credits_section(led.entries, 1.0)["phones"] == 2   # new and x, not old
    book = GuestBook(night_id="n1", phones={
        "new": GuestPhone(id="new", name="Ana"), "old": GuestPhone(id="old", name="Ana old", merged_into="new")})
    assert board._people({"new": 3, "old": 9}, book, 5) == [{"name": "Ana", "value": 3}]


def test_a_chained_merge_points_every_retired_phone_at_the_guest():
    """X into B, then B into C: X's stored `merged_into` reads C, the phone it
    now belongs to — not B, itself retired (#469's review finding)."""
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        x, b, c = await _phone(g), await _phone(g), await _phone(g)
        assert (await g.merge(x, b))[0] == 200
        assert (await g.merge(b, c))[0] == 200
        book = g._book
        assert book.phones[x].merged_into == c and book.phones[b].merged_into == c
        assert book.merged == {x: c, b: c}
        assert store.load_guests().phones[x].merged_into == c
        assert (await g.view(x))[1]["view"]["me"]["name"] == book.phones[c].name
        _sound(g, w)
    _run(go())
