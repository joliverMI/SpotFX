"""The guest app (jukebox_guest/, its own process on :8020; the plan's PR
2.1): nothing but guest routes answers on it; every guest call becomes one
allowlisted SpotFX call carrying the guest app's key and the phone's own
code; it rate-limits before forwarding; and the party token in the page's
address never leaks. The last section drives the whole chain — the guest
app, over loopback, into SpotFX's real guest routes and the engine's fake
world — the way a phone would."""
from __future__ import annotations

import asyncio
import json
import random

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jukebox_guest import app as guest_app
from jukebox_guest import key as guest_key
from routers import jukebox_guest_router
from services.jukebox import guests as G
from services.jukebox import night as night_mod
from tests.jukebox_world import World

PHONE = "P" * 22
OTHER = "Q" * 22


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class SpotFX:
    """A recording stand-in for SpotFX's guest routes."""

    def __init__(self, status: int = 200, body: dict | None = None, fail: bool = False):
        self.calls: list[httpx.Request] = []
        self.status, self.body, self.fail = status, body, fail

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.fail:
            raise httpx.ConnectError("down")
        body = self.body
        if body is None:
            body = {"status": "ok", "phone": PHONE, "view": {"state": "running"}}
        return httpx.Response(self.status, json=body)

    def payloads(self) -> list[dict]:
        out = []
        for r in self.calls:
            out.append(dict(r.url.params) if r.method == "GET" else json.loads(r.content))
        return out


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "guest-dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>Jukebox</title>")
    (d / "assets" / "app-abc123.js").write_text("console.log(1)")
    (d / "manifest.webmanifest").write_text("{}")
    return d


def _client(tmp_path, dist, spotfx: SpotFX, clock=None, peer: str = "127.0.0.1") -> TestClient:
    """The guest app as Funnel reaches it: from tailscaled on loopback."""
    app = guest_app.create_app(key_file=tmp_path / "key", dist_dir=dist,
                               transport=httpx.MockTransport(spotfx.handler),
                               clock=clock or FakeClock())
    return TestClient(app, client=(peer, 50000))


# ═══ 1. nothing but guest routes answers ═══════════════════════════════════

def test_the_app_answers_exactly_the_allowlist():
    app = guest_app.create_app()
    got = {(m, r.path) for r in app.routes for m in getattr(r, "methods", ())}
    assert got == set(guest_app.ROUTES)


MASTER_PATHS = ("/api/jukebox/status", "/api/jukebox/night/start", "/api/jukebox/night/stop",
                "/api/jukebox/config", "/api/jukebox/line", "/api/jukebox/guest/view",
                "/api/jukebox/guest/hello", "/api/settings", "/api/spotify/status",
                "/spectra/", "/spectra/api/engine/status", "/docs", "/redoc", "/openapi.json",
                "/g", "/g/", "/g/stop", "/g/../api/settings", "/assets/../index.html",
                "/assets/%2e%2e%2findex.html")


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
def test_no_master_or_spectra_path_answers_and_none_is_forwarded(tmp_path, dist, method):
    sp = SpotFX()
    with _client(tmp_path, dist, sp) as c:
        for path in MASTER_PATHS:
            r = c.request(method, path, json={} if method != "GET" else None)
            assert r.status_code in (404, 405), (method, path, r.status_code)
    assert sp.calls == []


def test_every_forward_is_an_allowlisted_spotfx_path_with_the_key(tmp_path, dist):
    sp = SpotFX()
    with _client(tmp_path, dist, sp) as c:
        c.post("/g/hello", json={"token": "t"})
        c.post("/g/join", json={"name": "Ana"})
        c.post("/g/name", json={"shuffle": True})
        c.post("/g/vote", json={"vote": "up"})
        c.get("/g/view")
    allowed = {(m, p) for m, p in guest_app.FORWARDS.values()}
    key = (tmp_path / "key").read_text()
    assert len(sp.calls) == 5
    for r in sp.calls:
        assert (r.method, r.url.path) in allowed
        assert r.headers[guest_key.HEADER] == key
        assert str(r.url).startswith(guest_app.SPOTFX_URL)


# ═══ 2. the phone's code ═══════════════════════════════════════════════════

def test_hello_sets_a_private_cookie_and_later_calls_name_that_phone(tmp_path, dist):
    sp = SpotFX()
    with _client(tmp_path, dist, sp) as c:
        r = c.post("/g/hello", json={"token": "tonight"})
        cookie = r.headers["set-cookie"]
        assert f"{guest_app.PHONE_COOKIE}={PHONE}" in cookie
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Secure" not in cookie
        c.post("/g/vote", json={"vote": "up", "phone": OTHER})   # a body can't name a phone
        c.get("/g/view")
    hello, vote, view = sp.payloads()
    assert hello == {"phone": None, "token": "tonight"}
    assert vote == {"phone": PHONE, "vote": "up"}
    assert view == {"phone": PHONE}


def test_the_cookie_is_secure_behind_https(tmp_path, dist):
    with _client(tmp_path, dist, SpotFX()) as c:
        r = c.post("/g/hello", json={}, headers={"X-Forwarded-Proto": "https"})
        assert "Secure" in r.headers["set-cookie"]


def test_a_phone_that_lost_its_cookie_comes_back_with_its_stored_code(tmp_path, dist):
    sp = SpotFX()
    with _client(tmp_path, dist, sp) as c:
        c.post("/g/hello", json={"phone": OTHER})
        c.cookies.clear()                                   # the cookie is gone again
        c.get("/g/view", headers={guest_app.PHONE_HEADER: OTHER})
        c.post("/g/hello", json={"phone": "bad code!"})
    assert sp.payloads()[0]["phone"] == OTHER
    assert sp.payloads()[1] == {"phone": OTHER}
    assert sp.payloads()[2]["phone"] is None


def test_spotfx_refusals_pass_through_with_their_sentence(tmp_path, dist):
    body = {"status": "refused", "reason": "needs_link", "detail": G.sentence("needs_link")}
    with _client(tmp_path, dist, SpotFX(status=403, body=body)) as c:
        r = c.post("/g/hello", json={})
        assert r.status_code == 403 and r.json() == body and "set-cookie" not in r.headers


# ═══ 3. limits ═════════════════════════════════════════════════════════════

def test_votes_are_rate_limited_per_phone_and_refill(tmp_path, dist):
    sp, clock = SpotFX(), FakeClock()
    with _client(tmp_path, dist, sp, clock) as c:
        c.cookies.set(guest_app.PHONE_COOKIE, PHONE)
        codes = [c.post("/g/vote", json={"vote": "up"}).status_code for _ in range(8)]
        assert codes[:6] == [200] * 6 and codes[6] == 429
        r = c.post("/g/vote", json={"vote": "up"})
        assert r.json()["reason"] == "slow_down" and int(r.headers["Retry-After"]) >= 1
        clock.t += 2.0
        assert c.post("/g/vote", json={"vote": "up"}).status_code == 200
    assert len(sp.calls) == 7                                  # the refused ones never left


def test_new_phones_are_limited_per_address(tmp_path, dist):
    sp = SpotFX(status=403, body={"status": "refused", "reason": "needs_link", "detail": "x"})
    with _client(tmp_path, dist, sp) as c:
        a = [c.post("/g/hello", json={}, headers={"X-Forwarded-For": "100.1.1.1"}).status_code
             for _ in range(8)]
        assert a.count(429) == 2
        assert c.post("/g/hello", json={}, headers={"X-Forwarded-For": "100.2.2.2"}).status_code == 403


def test_a_direct_connection_cant_choose_its_own_address(tmp_path, dist):
    """X-Forwarded-For counts only from tailscaled on loopback: a phone
    reaching the app directly can't dodge its limit by inventing one."""
    sp = SpotFX(status=403, body={"status": "refused", "reason": "needs_link", "detail": "x"})
    with _client(tmp_path, dist, sp, peer="192.168.40.77") as c:
        codes = [c.post("/g/hello", json={}, headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
                 for i in range(8)]
        assert codes.count(429) == 2


def test_a_big_body_is_refused_before_anything_is_sent(tmp_path, dist):
    sp = SpotFX()
    with _client(tmp_path, dist, sp) as c:
        c.cookies.set(guest_app.PHONE_COOKIE, PHONE)
        r = c.post("/g/join", content=json.dumps({"name": "x" * 5000}),
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 413
    assert sp.calls == []


# ═══ 4. when SpotFX can't answer, and the page itself ═════════════════════

def test_spotfx_down_is_a_sentence_not_a_stack_trace(tmp_path, dist):
    with _client(tmp_path, dist, SpotFX(fail=True)) as c:
        r = c.get("/g/view")
        assert r.status_code == 503 and r.json()["reason"] == "unavailable"


def test_a_rejected_key_is_read_again_once(tmp_path, dist):
    calls = []

    def handler(request):
        calls.append(request.headers[guest_key.HEADER])
        if len(calls) == 1:
            (tmp_path / "key").write_text("a-new-key")
            return httpx.Response(401, json={"detail": "no"})
        return httpx.Response(200, json={"status": "ok", "view": {}})
    app = guest_app.create_app(key_file=tmp_path / "key", dist_dir=dist,
                               transport=httpx.MockTransport(handler))
    with TestClient(app) as c:
        assert c.get("/g/view").status_code == 200
    assert calls[1] == "a-new-key" and calls[0] != calls[1]


def test_every_answer_carries_the_security_headers(tmp_path, dist):
    with _client(tmp_path, dist, SpotFX()) as c:
        for r in (c.get("/?t=secret"), c.get("/g/view"), c.get("/assets/app-abc123.js"),
                  c.get("/nope")):
            assert r.headers["Referrer-Policy"] == "no-referrer"
            assert "i.scdn.co" in r.headers["Content-Security-Policy"]
            assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
            assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert c.get("/?t=secret").headers["Cache-Control"] == "no-cache"
        assert "immutable" in c.get("/assets/app-abc123.js").headers["Cache-Control"]
        assert c.get("/g/view").headers["Cache-Control"] == "no-store"


def test_an_unbuilt_page_says_so(tmp_path):
    with _client(tmp_path, tmp_path / "missing", SpotFX()) as c:
        r = c.get("/")
        assert r.status_code == 503 and "isn't built" in r.text


def test_the_entry_point_refuses_the_masters_ports():
    from jukebox_guest.__main__ import main
    assert main(["--port", "8000"]) == 2 and main(["--port", "8010"]) == 2


# ═══ 5. the whole chain, the way a phone uses it ═══════════════════════════

def test_two_phones_join_and_vote_through_the_guest_app(tmp_path, dist, monkeypatch):
    """The guest app → loopback → SpotFX's real guest routes → guests.py →
    the engine's fake world. First visit to a vote: "Let's go", then ▲."""
    from services.jukebox import guest_link, store

    async def go():
        w = World()
        await w.start()
        await w.run(2)
        monkeypatch.setattr(night_mod, "runner", w.runner)
        guest_link.GuestLink().ensure_token()
        token = store.load_guest_link()[1].token
        monkeypatch.setattr(G, "book", G.Guests(G.GuestDeps(rng=random.Random(3))))
        spotfx = FastAPI()
        spotfx.include_router(jukebox_guest_router.router)
        guest = guest_app.create_app(key_file=jukebox_guest_router.KEY_FILE, dist_dir=dist,
                                     transport=httpx.ASGITransport(app=spotfx))
        phones = []
        for _ in range(2):
            c = httpx.AsyncClient(transport=httpx.ASGITransport(app=guest), base_url="http://guest")
            r = await c.post("/g/hello", json={"token": token})
            assert r.status_code == 200, r.text
            assert r.json()["view"]["me"]["joined"] is False
            phones.append(c)
        a, b = phones
        r = await a.post("/g/join", json={})                  # tap 1: Let's go
        assert r.json()["view"]["me"]["joined"]
        r = await a.post("/g/vote", json={"vote": "up"})      # tap 2: ▲
        assert r.status_code == 200 and r.json()["view"]["now"]["my_vote"] == 1
        await b.post("/g/join", json={})
        view = (await b.get("/g/view")).json()["view"]
        assert view["now"]["votes"] == {"up": 1, "down": 0} and view["now"]["my_vote"] == 0
        stranger = httpx.AsyncClient(transport=httpx.ASGITransport(app=guest),
                                     base_url="http://guest")
        assert (await stranger.post("/g/hello", json={"token": "guess"})).status_code == 403
        assert (await stranger.post("/g/vote", json={"vote": "down"})).status_code == 403
        for c in (a, b, stranger):
            await c.aclose()
    asyncio.run(go())
