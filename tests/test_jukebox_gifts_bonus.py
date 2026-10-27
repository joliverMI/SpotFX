"""The host's gifts and the printed bonus cards (the plan's §1 rule 1, §4's
Free credits card, §9's N2 "one-time +5 bonus codes"): "Everyone +2" and a
gift to one phone; a bonus code good for +5 once, ever, one per phone a
night, with a cap on wrong tries; every credit through the night's ledger,
whose verify() must find it sound. Driven over the fake Jukebox world."""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from jukebox_guest import app as guest_app, key as guest_key
from routers import jukebox_guest_router, jukebox_router
from services.jukebox import bonus_codes, guests as G, night as night_mod, store
from tests.jukebox_world import World
from tests.test_jukebox_credits_play import _bal, _setup, _show, _sound
from tests.test_jukebox_guest_add import TOKEN, Catalog, Lib, _inline, _night, _phone


def _run(coro):
    return asyncio.run(coro)


# ═══ 1. the codes themselves ═══════════════════════════════════════════════

def test_codes_are_eight_unambiguous_characters_saved_before_they_are_handed_out():
    made = bonus_codes.mint(5, "Saturday")
    assert len(made) == 5 == len(set(made))
    assert all(len(c) == 8 and set(c) <= set(bonus_codes.ALPHABET) for c in made)
    assert not set("01ILOU") & set(bonus_codes.ALPHABET)
    s = bonus_codes.summary()
    assert s["unused"] == 5 and s["used"] == 0 and {r["batch"] for r in s["codes"]} == {"Saturday"}
    assert bonus_codes.pretty(made[0]) == f"{made[0][:4]}-{made[0][4:]}"
    assert bonus_codes.fold(f" {made[0][:4].lower()}-{made[0][4:]} ") == made[0]
    for bad in (0, bonus_codes.MINT_MAX + 1):
        try:
            bonus_codes.mint(bad)
            raise AssertionError(f"minting {bad} codes was accepted")
        except ValueError:
            pass


def test_a_code_is_claimed_once_ever_and_a_void_only_takes_an_unused_one():
    a, b = bonus_codes.mint(2)
    assert bonus_codes.claim(a, "n1", "Ana", 1) == ("ok", a)
    assert bonus_codes.claim(a, "n2", "Ben", 2) == ("spent", None)      # once, ever
    assert bonus_codes.claim("ZZZZ-ZZZZ", "n1", "Ana", 3) == ("unknown", None)
    assert bonus_codes.void(a) is False                                 # a used code is a record
    assert bonus_codes.void(b) is True and bonus_codes.claim(b, "n1", "Cy", 4) == ("unknown", None)
    row = next(r for r in bonus_codes.summary()["codes"] if r["used"])
    assert row["used_name"] == "Ana"


def test_an_unreadable_codes_file_is_never_written_over():
    bonus_codes.mint(1)
    store.BONUS_FILE.write_text("{ not json", encoding="utf-8")
    for call in (lambda: bonus_codes.mint(3), lambda: bonus_codes.claim("AAAA-AAAA", "n", "Ana", 1),
                 bonus_codes.summary):
        try:
            call()
            raise AssertionError("an unreadable codes file was read as empty")
        except ValueError:
            pass
    assert store.BONUS_FILE.read_text(encoding="utf-8") == "{ not json"


# ═══ 2. a guest uses a card ════════════════════════════════════════════════

def test_a_bonus_card_adds_its_credits_once_one_per_phone_a_night():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana, ben = await _phone(g), await _phone(g)
        c1, c2 = bonus_codes.mint(2)
        code, out = await g.redeem_bonus(ana, bonus_codes.pretty(c1).lower())
        assert code == 200 and out["bonus"]["amount"] == 5, out
        assert _bal(g, w, ana) == 4 + 5
        code, out = await g.redeem_bonus(ana, c2)                     # one per phone a night
        assert code == 409 and out["reason"] == "bonus_used_tonight"
        code, out = await g.redeem_bonus(ben, c1)                     # once, ever
        assert code == 409 and out["reason"] == "bonus_spent"
        assert (await g.redeem_bonus(ben, c2))[0] == 200 and _bal(g, w, ben) == 9
        hist = (await g.wallet_view(ana))[1]
        assert hist["bonus"] == {"amount": 5, "used": True, "tries_left": 5}
        assert any(r["kind"] == "qr_bonus" and r["delta"] == 5 for r in hist["history"])
        _sound(g, w)
    _run(go())


def test_wrong_codes_are_capped_and_the_qr_bonus_setting_is_the_amount():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, _show(economy={"qr_bonus": 3}))
        ana = await _phone(g)
        (good,) = bonus_codes.mint(1)
        for _ in range(G.BONUS_TRIES):
            code, out = await g.redeem_bonus(ana, "WRNG-CODE")
            assert code == 409 and out["reason"] == "bonus_unknown"
        code, out = await g.redeem_bonus(ana, good)
        assert code == 429 and out["reason"] == "bonus_tries"         # even a good one, now
        assert bonus_codes.summary()["unused"] == 1                    # the card is still good
        cy = await _phone(g)
        assert (await g.redeem_bonus(cy, good))[1]["bonus"]["amount"] == 3
    _run(go())


def test_free_play_keeps_the_card_for_a_credits_night():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, _show().model_copy(update={"play_mode": "free"}))
        ana = await _phone(g)
        (c,) = bonus_codes.mint(1)
        code, out = await g.redeem_bonus(ana, c)
        assert code == 409 and out["reason"] == "credits_off"
        assert bonus_codes.summary()["unused"] == 1
    _run(go())


def test_a_card_whose_credits_cant_be_written_stays_good(monkeypatch):
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana = await _phone(g)
        (c,) = bonus_codes.mint(1)
        wal = g._wallet_for(w.runner.night.id, store.load_show())

        def broken(*a, **k):
            raise OSError("disk full")
        monkeypatch.setattr(wal.led, "grant", broken)
        try:
            await g.redeem_bonus(ana, c)
            raise AssertionError("a failed write was answered as a success")
        except OSError:
            pass
        assert bonus_codes.summary()["unused"] == 1
    _run(go())


# ═══ 3. the host's gifts ═══════════════════════════════════════════════════

def test_everyone_plus_two_reaches_every_phone_at_the_party_and_no_one_else():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w)
        ana, ben = await _phone(g), await _phone(g)
        code, out = await g.hello(None, TOKEN)                          # on the welcome screen
        lurker = out["phone"]
        cy = await _phone(g)
        await g.host_set(cy, blocked=True)
        code, out = await g.gift("everyone", 2)
        assert code == 200 and out["gift"]["phones"] == 2 and out["gift"]["amount"] == 2
        assert (_bal(g, w, ana), _bal(g, w, ben), _bal(g, w, lurker), _bal(g, w, cy)) == (6, 6, 0, 4)
        assert not any(pid in json.dumps(out) for pid in (ana, ben, lurker, cy))
        code, out = await g.gift(ben, 5)
        assert code == 200 and _bal(g, w, ben) == 11
        assert (await g.gift(cy, 2))[1]["reason"] == "gift_not_in"
        assert (await g.gift("A" * 22, 2))[1]["reason"] == "no_phone"
        for bad in (0, G.GIFT_MAX + 1, "lots"):
            assert (await g.gift("everyone", bad))[1]["reason"] == "gift_amount"
        hist = (await g.wallet_view(ana))[1]["history"]
        assert hist[0]["what"] == "From the host" and hist[0]["delta"] == 2
        _sound(g, w)
    _run(go())


def test_gifts_are_credits_mode_and_need_a_night():
    async def go():
        w = await _night(set_s=300)
        g = _setup(w, _show().model_copy(update={"play_mode": "free"}))
        await _phone(g)
        assert (await g.gift("everyone", 2))[1]["reason"] == "credits_off"
    _run(go())
    g = G.Guests(G.GuestDeps(state=lambda: {"running": False}))
    assert _run(g.gift("everyone", 2))[1]["reason"] == "not_running"


# ═══ 4. the doors ══════════════════════════════════════════════════════════

def test_the_gift_and_bonus_doors(monkeypatch):
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
        r = c.post("/api/jukebox/bonus-codes", json={"count": 3, "batch": "Party 1"})
        assert r.status_code == 200 and len(r.json()["made"]) == 3 and r.json()["unused"] == 3
        assert c.post("/api/jukebox/bonus-codes", json={"count": 0}).status_code == 422
        made = r.json()["made"]
        assert c.delete(f"/api/jukebox/bonus-codes/{made[2]}").json()["unused"] == 2
        assert c.delete(f"/api/jukebox/bonus-codes/{made[2]}").status_code == 404
        store.save_config(store.load_config().model_copy(update={"playlist": w.cfg.playlist}))
        assert c.post("/api/jukebox/night/start", json={}).json()["status"] == "running"
        ana = c.portal.call(_phone, g)
        body = {"phone": ana, "code": made[0]}
        assert c.post("/api/jukebox/guest/bonus", json=body).status_code == 401
        r = c.post("/api/jukebox/guest/bonus", json=body, headers={guest_key.HEADER: key})
        assert r.status_code == 200 and r.json()["bonus"]["amount"] == 5
        r = c.post("/api/jukebox/gift", json={"to": "everyone", "amount": 2})
        assert r.status_code == 200 and r.json()["gift"]["phones"] == 1
        assert c.get("/api/jukebox/bonus-codes").json()["used"] == 1
    assert ("POST", "/g/bonus") in guest_app.ROUTES
    assert guest_app.FORWARDS["bonus"] == ("POST", "/api/jukebox/guest/bonus")
