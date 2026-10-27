"""
The guest app: the page guests open on their phones, as its own process
(`python -m jukebox_guest`, port 8020). See the package docstring for what
it keeps true; this module is the whole server.
"""
from __future__ import annotations

import json
import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from jukebox_guest import key as guest_key
from jukebox_guest.ratelimit import Limit, RateLimiter

logger = logging.getLogger("jukebox_guest")

REPO = Path(__file__).resolve().parent.parent
DIST_DIR = REPO / "spectra" / "web" / "guest-dist"
SPOTFX_URL = "http://127.0.0.1:8000"
PHONE_COOKIE = "jb_phone"
PHONE_HEADER = "X-Guest-Phone"
COOKIE_MAX_AGE_S = 24 * 3600
BODY_MAX = 2048
FORWARD_TIMEOUT_S = 4.0
_PHONE_RE = re.compile(r"^[A-Za-z0-9_-]{16,40}$")
_ASSET_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")

# THE ALLOWLIST: every route this app answers (method, path), and every
# SpotFX path it may ever call. Nothing else answers on :8020.
ROUTES: frozenset[tuple[str, str]] = frozenset({
    ("GET", "/"), ("GET", "/assets/{name}"), ("GET", "/manifest.webmanifest"),
    ("GET", "/icon.svg"), ("GET", "/icon-180.png"), ("GET", "/icon-512.png"),
    ("POST", "/g/hello"), ("POST", "/g/join"), ("POST", "/g/name"), ("POST", "/g/vote"),
    ("POST", "/g/search"), ("POST", "/g/add"), ("POST", "/g/bump"), ("GET", "/g/view"),
    ("POST", "/g/tip"), ("POST", "/g/skip"), ("POST", "/g/next"), ("POST", "/g/breakout"),
    ("GET", "/g/wallet"), ("GET", "/g/board"), ("POST", "/g/bonus"),
})
FORWARDS: dict[str, tuple[str, str]] = {
    "hello": ("POST", "/api/jukebox/guest/hello"),
    "join": ("POST", "/api/jukebox/guest/join"),
    "name": ("POST", "/api/jukebox/guest/name"),
    "vote": ("POST", "/api/jukebox/guest/vote"),
    "search": ("POST", "/api/jukebox/guest/search"),
    "add": ("POST", "/api/jukebox/guest/add"),
    "bump": ("POST", "/api/jukebox/guest/bump"),
    "tip": ("POST", "/api/jukebox/guest/tip"),
    "skip": ("POST", "/api/jukebox/guest/skip"),
    "next": ("POST", "/api/jukebox/guest/next"),
    "breakout": ("POST", "/api/jukebox/guest/breakout"),
    "wallet": ("GET", "/api/jukebox/guest/wallet"),
    "board": ("GET", "/api/jukebox/guest/board"),
    "bonus": ("POST", "/api/jukebox/guest/bonus"),
    "view": ("GET", "/api/jukebox/guest/view"),
}
STATIC_FILES = {"/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
                "/icon.svg": ("icon.svg", "image/svg+xml"),
                "/icon-180.png": ("icon-180.png", "image/png"),
                "/icon-512.png": ("icon-512.png", "image/png")}

LIMITS = {
    "view": Limit(rate=2.0, burst=6),          # a phone polls every 3 s
    "write": Limit(rate=2.0, burst=6),         # votes, names, "Let's go", adds
    "search": Limit(rate=1.0, burst=4),        # the page waits for typing to stop first
    "hello": Limit(rate=0.2, burst=6),         # per address: a dozen a minute
    "hello_all": Limit(rate=2.0, burst=40),    # new phones, the whole party (a QR rush)
    "all": Limit(rate=60.0, burst=120),        # every guest call together
}

# Album art loads straight from Spotify's image servers; nothing else leaves.
CSP = ("default-src 'self'; img-src 'self' https://i.scdn.co https://*.scdn.co data:; "
       "style-src 'self'; script-src 'self'; connect-src 'self'; font-src 'self'; "
       "manifest-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    # the party token is in the page's own address: never send it on to anyone
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

SENTENCES = {
    "slow_down": "Too many taps at once — try again in a moment.",
    "unavailable": "The Jukebox isn't answering right now. Try again in a moment.",
    "too_big": "That request is too big.",
    "bad_request": "That request didn't make sense.",
}


def _refuse(code: str, status: int, **headers: str) -> JSONResponse:
    return JSONResponse({"status": "refused", "reason": code, "detail": SENTENCES[code]},
                        status_code=status, headers=headers or None)


def _valid_phone(v: Any) -> bool:
    return isinstance(v, str) and bool(_PHONE_RE.match(v))


def _client(request: Request) -> str:
    """Who is asking, for the per-address limit. Behind Tailscale Funnel
    every connection comes from tailscaled on loopback, so the first
    X-Forwarded-For hop is the phone's; a direct connection is its peer."""
    peer = request.client.host if request.client else ""
    xff = request.headers.get("x-forwarded-for", "")
    if peer in ("127.0.0.1", "::1") and xff:
        return xff.split(",")[0].strip()[:64]
    return peer


def method_of(name: str) -> str:
    return FORWARDS[name][0]


def create_app(*, spotfx_url: str = SPOTFX_URL, key_file: Path = guest_key.DEFAULT_FILE,
               dist_dir: Path = DIST_DIR, transport: Optional[httpx.AsyncBaseTransport] = None,
               clock: Callable[[], float] = time.monotonic) -> FastAPI:
    state: dict[str, Any] = {"key": None, "client": None}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if state["client"] is not None:
            await state["client"].aclose()

    # no /docs, /redoc or /openapi.json: nothing but the allowlist answers
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    limiter = RateLimiter(LIMITS, clock=clock)

    def key(reload: bool = False) -> str:
        if reload or not state["key"]:
            state["key"] = guest_key.load_or_create(key_file)
        return state["key"]

    def http() -> httpx.AsyncClient:
        if state["client"] is None:
            state["client"] = httpx.AsyncClient(base_url=spotfx_url, transport=transport,
                                                timeout=FORWARD_TIMEOUT_S)
        return state["client"]

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    def phone_of(request: Request) -> Optional[str]:
        cookie = request.cookies.get(PHONE_COOKIE)
        if _valid_phone(cookie):
            return cookie
        header = request.headers.get(PHONE_HEADER)
        return header if _valid_phone(header) else None

    def limited(request: Request, kind: str, who: str) -> Optional[JSONResponse]:
        for k, key_ in (("all", "party"), (kind, who)):
            wait = limiter.take(k, key_)
            if wait:
                return _refuse("slow_down", 429, **{"Retry-After": str(max(1, round(wait)))})
        return None

    async def body_of(request: Request) -> Optional[dict]:
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > BODY_MAX):
            return None
        raw = await request.body()
        if len(raw) > BODY_MAX:
            return None
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    async def forward(name: str, payload: dict) -> tuple[int, dict]:
        method, path = FORWARDS[name]
        for attempt in (0, 1):
            headers = {guest_key.HEADER: key(reload=attempt == 1)}
            try:
                if method == "GET":
                    r = await http().get(path, params=payload, headers=headers)
                else:
                    r = await http().post(path, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                logger.warning("guest app: SpotFX unreachable (%s)", type(exc).__name__)
                return 503, {"status": "refused", "reason": "unavailable",
                             "detail": SENTENCES["unavailable"]}
            if r.status_code == 401 and attempt == 0:
                continue                     # the key file changed under us: read it again
            try:
                body = r.json()
            except ValueError:
                body = None
            if r.status_code >= 500 or r.status_code == 401 or not isinstance(body, dict):
                logger.warning("guest app: SpotFX answered %s on %s", r.status_code, path)
                return 503, {"status": "refused", "reason": "unavailable",
                             "detail": SENTENCES["unavailable"]}
            return r.status_code, body
        return 503, {"status": "refused", "reason": "unavailable", "detail": SENTENCES["unavailable"]}

    def api(code: int, body: dict) -> JSONResponse:
        return JSONResponse(body, status_code=code, headers={"Cache-Control": "no-store"})

    # ── the page ────────────────────────────────────────────────────────────

    @app.get("/")
    async def index() -> Response:
        page = dist_dir / "index.html"
        if not page.is_file():
            return HTMLResponse("<!doctype html><meta charset=utf-8><title>Jukebox</title>"
                                "<p>The guest page isn't built on this machine yet.</p>",
                                status_code=503)
        return FileResponse(page, media_type="text/html",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/assets/{name}")
    async def asset(name: str) -> Response:
        path = dist_dir / "assets" / name
        if not _ASSET_RE.match(name) or not path.is_file():
            return Response(status_code=404)
        return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})

    def _static(route: str):
        filename, media = STATIC_FILES[route]

        async def serve() -> Response:
            path = dist_dir / filename
            if not path.is_file():
                return Response(status_code=404)
            return FileResponse(path, media_type=media, headers={"Cache-Control": "public, max-age=3600"})
        return serve

    for route in STATIC_FILES:
        app.add_api_route(route, _static(route), methods=["GET"])

    # ── the guest calls ─────────────────────────────────────────────────────

    @app.post("/g/hello")
    async def hello(request: Request) -> Response:
        stop = limited(request, "hello", _client(request))
        if stop is None:
            wait = limiter.take("hello_all", "party")
            if wait:
                stop = _refuse("slow_down", 429, **{"Retry-After": str(max(1, round(wait)))})
        if stop:
            return stop
        body = await body_of(request)
        if body is None:
            return _refuse("too_big", 413)
        token = body.get("token") if isinstance(body.get("token"), str) else None
        hint = body.get("phone")
        phone = phone_of(request) or (hint if _valid_phone(hint) else None)
        code, out = await forward("hello", {"phone": phone, "token": token})
        resp = api(code, out)
        pid = out.get("phone")
        if code == 200 and _valid_phone(pid):
            secure = (request.headers.get("x-forwarded-proto") == "https"
                      or request.url.scheme == "https")
            resp.set_cookie(PHONE_COOKIE, pid, max_age=COOKIE_MAX_AGE_S, httponly=True,
                            samesite="lax", secure=secure, path="/")
        return resp

    async def _phone_call(request: Request, name: str, kind: str,
                          fields: tuple[str, ...]) -> Response:
        phone = phone_of(request)
        stop = limited(request, kind, phone or _client(request))
        if stop:
            return stop
        if method_of(name) == "GET":
            payload: dict = {"phone": phone or ""}
        else:
            body = await body_of(request)
            if body is None:
                return _refuse("too_big", 413)
            payload = {"phone": phone}
            for f in fields:
                if f in body:
                    payload[f] = body[f]
        code, out = await forward(name, payload)
        return api(code, out)

    @app.post("/g/join")
    async def join(request: Request) -> Response:
        return await _phone_call(request, "join", "write", ("name",))

    @app.post("/g/name")
    async def rename(request: Request) -> Response:
        return await _phone_call(request, "name", "write", ("name", "shuffle"))

    @app.post("/g/vote")
    async def vote(request: Request) -> Response:
        return await _phone_call(request, "vote", "write", ("vote",))

    @app.post("/g/search")
    async def search(request: Request) -> Response:
        return await _phone_call(request, "search", "search", ("q", "offset"))

    @app.post("/g/add")
    async def add(request: Request) -> Response:
        return await _phone_call(request, "add", "write", ("uri", "price"))

    @app.post("/g/bump")
    async def bump(request: Request) -> Response:
        return await _phone_call(request, "bump", "write", ("entry_id", "direction", "price"))

    @app.post("/g/tip")
    async def tip(request: Request) -> Response:
        return await _phone_call(request, "tip", "write", ("units",))

    @app.post("/g/skip")
    async def skip(request: Request) -> Response:
        return await _phone_call(request, "skip", "write", ("how", "amount", "price"))

    @app.post("/g/next")
    async def play_next(request: Request) -> Response:
        return await _phone_call(request, "next", "write", ("entry_id", "price"))

    @app.post("/g/breakout")
    async def breakout(request: Request) -> Response:
        return await _phone_call(request, "breakout", "write", ())

    @app.post("/g/bonus")
    async def bonus(request: Request) -> Response:
        return await _phone_call(request, "bonus", "write", ("code",))

    @app.get("/g/wallet")
    async def wallet(request: Request) -> Response:
        return await _phone_call(request, "wallet", "view", ())

    @app.get("/g/board")
    async def board(request: Request) -> Response:
        return await _phone_call(request, "board", "view", ())

    @app.get("/g/view")
    async def view(request: Request) -> Response:
        return await _phone_call(request, "view", "view", ())

    return app
