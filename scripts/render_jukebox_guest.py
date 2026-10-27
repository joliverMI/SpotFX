#!/usr/bin/env python3
"""Render the Jukebox's GUEST PAGE on four phones and fail on what a phone
would get wrong (data/jukebox-plan/report.md §7.2 and phase 2 PR 2.1's
acceptance):

  * iPhone SE 375×667, iPhone 15/16 393×852, iPhone Pro Max 430×932 and
    Galaxy S25+ 412×891, each with its own safe areas (the notch or Dynamic
    Island, the home bar) — through Chromium's own safe-area emulation when
    it has it, else the page's --sa-* properties set to the phone's insets;
  * nothing scrolls sideways and no text overflows its box;
  * every button and link is at least 44 × 44 px;
  * the header starts below the top inset, the tab bar's buttons end above
    the bottom inset, and the vote buttons and the "your song" strip are on
    screen without scrolling and clear of the tab bar (the SE is the test);
  * first visit to a vote in TWO taps ("Let's go", then ▲), with real touch
    events, and the vote reaches SpotFX's guest book;
  * no page error and no content-security-policy violation.

It runs the REAL chain: the built page (spectra/web/guest-dist), served by
the REAL guest app (jukebox_guest/), forwarding over an in-process loopback
to SpotFX's REAL guest routes and services/jukebox/guests.py — only the
night itself is a fixed scene (a set song playing, a line of songs, art
drawn locally), switched between "plain", "your song is next", "your song
is playing", "your songs are in a time-out" and "no night". Free play's
pieces are checked too (PR 2.3): the skip line under the vote buttons, the
⇅ on a song the phone may move and its sheet (whose button reaches the
engine's bump), and the red time-out strip. Credits mode is checked too (PR
3.2): the credits chip, tip (with its three-second undo) and skip on Now, the
chip-in and skip confirmations (each reaching the night's ledger, the paid
skip reaching the engine), Queue's prices and the play-next confirmation,
the Shop with its history, and the jail card with its break-out. Every store
(the ledger included) is repointed to a temp directory first; nothing
touches a live service or his storage.

    cd spectra/web && npx vite build --config vite.guest.config.ts
    .venv/bin/python scripts/render_jukebox_guest.py

Screenshots: docs/evidence/jukebox-guest/.
"""
from __future__ import annotations

import asyncio
import io
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from check_ui_fidelity import (  # noqa: E402
    REPO, cdp, evaluate, find_chrome, free_port, wait_for_devtools, websockets,
)

DIST = REPO / "spectra" / "web" / "guest-dist"
OUT_DIR = REPO / "docs" / "evidence" / "jukebox-guest"
TOKEN = "party-token-for-the-render"
ME = "R" * 22
ANA, OTTER = "A" * 22, "O" * 22

IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
ANDROID_UA = ("Mozilla/5.0 (Linux; Android 15; SM-S936B) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Mobile Safari/537.36")
# name, width, height, scale, safe top, safe bottom, user agent
PHONES = (
    ("iphone-se", 375, 667, 2, 20, 0, IPHONE_UA),
    ("iphone-15", 393, 852, 3, 59, 34, IPHONE_UA),
    ("iphone-pro-max", 430, 932, 3, 59, 34, IPHONE_UA),
    ("galaxy-s25plus", 412, 891, 3, 24, 16, ANDROID_UA),
)


# ── the scene SpotFX's guest routes read ─────────────────────────────────────

def _art_png(rgb: tuple[int, int, int]) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (300, 300), rgb)
    d = ImageDraw.Draw(img)
    d.ellipse([60, 60, 240, 240], outline=(255, 255, 255), width=10)
    d.ellipse([135, 135, 165, 165], fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


ART = {f"/__art/{i}.png": _art_png(c) for i, c in enumerate(
    [(181, 72, 52), (41, 98, 176), (32, 140, 92), (150, 60, 160), (190, 150, 40),
     (90, 90, 100), (200, 80, 120), (40, 150, 160)])}


class Scene:
    def __init__(self) -> None:
        self.name = "plain"
        self.started_ms = int(time.time() * 1000) - 3_600_000
        self.added: list = []
        self.bumped: list = []
        self.me = ME                       # the phone a credits scene is about
        self.play_started = 1              # each phone's credits pass is its own play
        self.jailed = False                # credits jail, until a break-out
        self.calls: list = []              # the credits calls that reached the engine

    # the engine calls credits mode makes, for the scene: they land
    def quote_wait(self, rnd, fair=True, duration_ms=210_000) -> int:
        return 20 * 60_000

    def _starts_in(self, entry_id):
        return next((it.starts_in_ms for it in self.state().get("next") or []
                     if getattr(it, "entry_id", "") == entry_id), None)

    async def play_next(self, entry_id, max_back=None) -> dict:
        self.calls.append(("play_next", entry_id))
        return {"status": "moved", "starts_in_ms": 101_000}

    async def mark_paid(self, entry_id, paid, seq) -> dict:
        self.calls.append(("mark_paid", entry_id, paid))
        return {"status": "ok"}

    async def skip_by_vote(self, started_ms, uri, reason="votes") -> dict:
        self.calls.append(("skip", uri, reason))
        return {"status": "skipped"}

    async def pardon(self, phone, broke_out=False) -> dict:
        self.calls.append(("pardon", phone, broke_out))
        self.jailed = False
        return {"status": "pardoned"}

    async def jail(self, phone, songs=None) -> dict:
        return {"status": "jailed"}

    async def bump(self, entry_id, up, max_back=None) -> dict:
        """The engine's bump, for the scene: it lands (the scene's line stays put)."""
        self.bumped.append((entry_id, up))
        return {"status": "moved", "place": 2, "starts_in_ms": 10 * 60_000}

    async def add_entry(self, entry, *, fair: bool = True, latest_start_ms=None) -> dict:
        """The engine's add, for the scene: the song joins the back of the line."""
        self.added.append(entry)
        return {"status": "added", "entry": entry.model_dump(mode="json"),
                "starts_in_ms": 25 * 60_000}

    def state(self) -> dict:
        from models.jukebox import LineEntry, NowItem, SetItem
        from services.jukebox.program import ProgramItem
        if self.name == "idle":
            return {"running": False}
        sets = [SetItem(uri=f"spotify:track:set{i:019d}", title=t, artist=a, duration_ms=d,
                        image=f"/__art/{i % 8}.png", thumb=f"/__art/{i % 8}.png")
                for i, (t, a, d) in enumerate([
                    ("Winny", "Fred again.., Sammy Virji", 264000),
                    ("Ready to Run", "The Chicks", 232000),
                    ("Snakeskin Boots", "Miranda Lambert, Ella Langley", 249000),
                    ("The Chain - 2004 Remaster", "Fleetwood Mac", 270000),
                    ("Tom Sawyer", "Rush", 276000)])]
        mine_who = ME if self.name in ("mine_next", "mine_playing") else ANA
        line = [
            LineEntry(id="e1", uri="spotify:track:jbx0000000000000000001", title="Dopamine",
                      artist="Wooli, Tape B", duration_ms=159000, image="/__art/5.png",
                      thumb="/__art/5.png", added_by=mine_who,
                      state="playing" if self.name == "mine_playing" else "committed"),
            LineEntry(id="e2", uri="spotify:track:jbx0000000000000000002", title="Pop Off",
                      artist="Wooli", duration_ms=196000, image="/__art/6.png",
                      thumb="/__art/6.png", added_by="host"),
            LineEntry(id="e3", uri="spotify:track:jbx0000000000000000003",
                      title="El Apagón", artist="Bad Bunny", duration_ms=202000,
                      image="/__art/7.png", thumb="/__art/7.png", added_by=OTTER),
        ]
        if self.name == "credits":
            # credits mode: Ana's song playing (so there is someone to tip), and
            # this phone's own song far enough back to play next
            line[0].state = "playing"
            line.append(LineEntry(id="e4", uri="spotify:track:jbx0000000000000000004",
                                  title="Mr. Brightside", artist="The Killers", duration_ms=222000,
                                  image="/__art/3.png", thumb="/__art/3.png", added_by=self.me))
            now = NowItem(kind="jukebox", uri=line[0].uri, title="Dopamine", entry_id="e1",
                          started_ms=self.play_started)
            duration, remaining = 159000, 101000
            nxt = [ProgramItem("jukebox", line[1].uri, "Pop Off", "Wooli", 196000, entry_id="e2"),
                   ProgramItem("set", sets[2].uri, sets[2].title, sets[2].artist, 249000, set_index=2),
                   ProgramItem("jukebox", line[2].uri, "El Apagón", "Bad Bunny", 202000, entry_id="e3"),
                   ProgramItem("set", sets[3].uri, sets[3].title, sets[3].artist, 270000, set_index=3),
                   ProgramItem("jukebox", line[3].uri, "Mr. Brightside", "The Killers", 222000,
                               entry_id="e4")]
        elif self.name == "mine_playing":
            now = NowItem(kind="jukebox", uri=line[0].uri, title="Dopamine", entry_id="e1",
                          started_ms=1)
            duration, remaining = 159000, 101000
            nxt = [ProgramItem("jukebox", line[1].uri, "Pop Off", "Wooli", 196000, entry_id="e2"),
                   ProgramItem("set", sets[2].uri, sets[2].title, sets[2].artist, 249000, set_index=2),
                   ProgramItem("jukebox", line[2].uri, "El Apagón", "Bad Bunny", 202000, entry_id="e3"),
                   ProgramItem("set", sets[3].uri, sets[3].title, sets[3].artist, 270000, set_index=3)]
        else:
            now = NowItem(kind="set", uri=sets[1].uri, title="Ready to Run", set_index=1,
                          started_ms=1)
            duration, remaining = 232000, 158000 if self.name == "plain" else 40000
            nxt = [ProgramItem("jukebox", line[0].uri, "Dopamine", "Wooli, Tape B", 159000,
                               entry_id="e1", committed=True),
                   ProgramItem("jukebox", line[1].uri, "Pop Off", "Wooli", 196000, entry_id="e2"),
                   ProgramItem("set", sets[2].uri, sets[2].title, sets[2].artist, 249000, set_index=2),
                   ProgramItem("jukebox", line[2].uri, "El Apagón", "Bad Bunny", 202000, entry_id="e3"),
                   ProgramItem("set", sets[3].uri, sets[3].title, sets[3].artist, 270000, set_index=3)]
        from services.jukebox.program import with_start_times
        jail: dict = {}
        jail_kind: dict = {}
        if self.name == "jailed":
            # your song sits out a time-out: it keeps its place, the slots pass it
            line.append(LineEntry(id="e4", uri="spotify:track:jbx0000000000000000004",
                                  title="Mr. Brightside", artist="The Killers", duration_ms=222000,
                                  image="/__art/3.png", thumb="/__art/3.png", added_by=ME))
            jail = {ME: 13}
            jail_kind = {ME: "timeout"}
        if self.name == "credits" and self.jailed:
            jail = {self.me: 10 ** 9}           # credits mode's jail: until they break out
            jail_kind = {self.me: "breakout"}
        line += self.added
        nxt += [ProgramItem("jukebox", e.uri, e.title, e.artist, e.duration_ms, entry_id=e.id)
                for e in self.added]
        return {"running": True, "night_id": "render-night", "started_ms": self.started_ms,
                "now": now, "is_playing": True,
                "duration_ms": duration, "remaining_ms": remaining,
                "next": with_start_times(nxt, remaining), "line": line, "set_items": sets,
                "plays": 10, "jail": jail, "jail_kind": jail_kind, "no_skip": []}


class Catalog:
    """Spotify's search, for the render: real-looking songs with art drawn
    locally — one explicit, one long, two from his library (one "Ready")."""
    SONGS = [
        ("Dancing Queen", "ABBA", 231000, False), ("Dancing in the Moonlight", "Toploader", 232000, False),
        ("Dancing On My Own", "Robyn", 287000, False), ("Dance Monkey", "Tones And I", 209000, False),
        ("Dancing with a Stranger (with Normani)", "Sam Smith, Normani", 171000, False),
        ("Dancin (Krono Remix)", "Aaron Smith, Luvli", 197000, True),
        ("Dancing in the Dark", "Bruce Springsteen", 241000, False),
        ("Dancing Barefoot - Extended Live Version from the Archive", "Patti Smith Group", 412000, False),
        ("Dance the Night", "Dua Lipa", 176000, False), ("Dancing Days", "Led Zeppelin", 223000, False),
    ]

    def __init__(self) -> None:
        self.songs = [{"uri": f"spotify:track:dance{i:017d}", "title": t, "artist": a, "duration_ms": d,
                       "explicit": e, "image": f"/__art/{i % 8}.png", "thumb": f"/__art/{i % 8}.png"}
                      for i, (t, a, d, e) in enumerate(self.SONGS)]

    def search(self, q, limit=10, offset=0):
        return [dict(m) for m in self.songs[offset:offset + limit]]

    def tracks(self, uris):
        return [dict(m) for m in self.songs if m["uri"] in uris]

    def track(self, uri):
        return next((dict(m) for m in self.songs if m["uri"] == uri), None)


def build_server(tmp: Path, scene: Scene):
    """The guest app over loopback into SpotFX's real guest routes, plus two
    render-only paths (the art, and the scene switch) in front of it."""
    import httpx
    from fastapi import FastAPI

    from jukebox_guest import app as guest_app
    from models.jukebox import GuestBook, GuestPhone
    from routers import jukebox_guest_router
    from services.jukebox import guests, store
    for attr in ("CONFIG_FILE", "NIGHT_FILE", "SHOW_FILE", "GUEST_LINK_FILE", "GUESTS_FILE"):
        setattr(store, attr, tmp / f"{attr.lower()}.json")
    from services.jukebox import ledger
    ledger.LEDGER_DIR = tmp / "ledger"
    jukebox_guest_router.KEY_FILE = tmp / "guest_key"
    from datetime import datetime, timedelta
    from models.jukebox import ShowConfig
    from services.jukebox.library import Song
    ends = datetime.now(guests.HOUSE_TZ) + timedelta(hours=3)
    # free play for the phase-2 scenes; credits_pass switches to credits and back
    store.save_show(ShowConfig(night_ends=f"{ends.hour:02d}:{ends.minute:02d}", play_mode="free"))
    catalog = Catalog()
    library = [catalog.songs[0]["uri"], catalog.songs[6]["uri"]]
    book = guests.Guests(guests.GuestDeps(
        state=scene.state, token_ok=lambda t: t == TOKEN, runner=lambda: scene,
        gateway=lambda: catalog,
        library_search=lambda q, n: [Song(u, "", "", "") for u in library][:n],
        known=lambda uris: {u: u in (library[0], catalog.songs[3]["uri"]) for u in uris}))
    book._book = GuestBook(night_id="render-night", phones={
        ANA: GuestPhone(id=ANA, name="Disco Ana", joined=True),
        OTTER: GuestPhone(id=OTTER, name="Lucky Otter", joined=True)},
        # two ▼ already on the set song playing: the skip line has something to say
        votes={f"spotify:track:set{1:019d}@1": {ANA: -1, OTTER: -1}})
    guests.book = book
    spotfx = FastAPI()
    spotfx.include_router(jukebox_guest_router.router)
    app = guest_app.create_app(key_file=tmp / "guest_key", dist_dir=DIST,
                               transport=httpx.ASGITransport(app=spotfx))

    async def outer(asgi_scope, receive, send):
        path = asgi_scope.get("path", "")
        if asgi_scope["type"] == "http" and path in ART:
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"image/png")]})
            await send({"type": "http.response.body", "body": ART[path]})
            return
        if asgi_scope["type"] == "http" and path.startswith("/__scene/"):
            scene.name = path.rsplit("/", 1)[1]
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        await app(asgi_scope, receive, send)
    return outer, book


def start_uvicorn(app, port: int):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           access_log=False, lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    return server


# ── in the page ──────────────────────────────────────────────────────────────

TRAP = """
window.__guestErrors = [];
window.addEventListener('error', (e) => window.__guestErrors.push(String(e.message || e)));
window.addEventListener('unhandledrejection', (e) => window.__guestErrors.push('rejection: ' + String(e.reason)));
document.addEventListener('securitypolicyviolation', (e) => window.__guestErrors.push('CSP: ' + e.violatedDirective + ' ' + e.blockedURI));
const _ce = console.error.bind(console);
console.error = (...a) => { window.__guestErrors.push(a.map(String).join(' ')); _ce(...a); };
"""

SAFE_VARS = """(() => {{
  const s = document.documentElement.style;
  s.setProperty('--sa-top', '{top}px'); s.setProperty('--sa-bottom', '{bottom}px');
}})()"""

CHECKS = """((saTop, saBottom) => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const de = document.documentElement;
  const visible = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const out = { scrollX: de.scrollWidth > vw + 1 ? de.scrollWidth + '>' + vw : '', overflow: [], small: [], safe: [], fold: [] };
  for (const el of document.body.querySelectorAll('*')) {
    if (!visible(el) || el.closest('svg')) continue;
    if (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX !== 'hidden')
      out.overflow.push((el.className || el.tagName) + ' ' + el.scrollWidth + '>' + el.clientWidth);
    else if (el.scrollWidth > el.clientWidth + 1 && el.children.length === 0)
      out.overflow.push('clipped ' + (el.className || el.tagName));
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 || r.left < -1) out.overflow.push('off-screen ' + (el.className || el.tagName));
  }
  for (const el of document.querySelectorAll('button, a, input, [role=button]')) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 44 - 0.5 || r.height < 44 - 0.5)
      out.small.push((el.getAttribute('aria-label') || el.textContent.trim() || el.className).slice(0, 30) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
  }
  const head = document.querySelector('.g-header .g-brand, .g-header .g-name-chip, .g-welcome-title');
  if (head && head.getBoundingClientRect().top < saTop - 0.5) out.safe.push('header under the top inset');
  const tabs = [...document.querySelectorAll('.g-tab, .g-btn-go')];
  for (const t of tabs) if (t.getBoundingClientRect().bottom > vh - saBottom + 0.5) out.safe.push('a bottom button under the home bar');
  const bar = document.querySelector('.g-tabbar');
  const limit = bar ? bar.getBoundingClientRect().top : vh - saBottom;
  for (const sel of ['.g-strip', '.g-vote-up', '.g-vote-down']) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const r = el.getBoundingClientRect();
    if (window.scrollY > 0 || r.bottom > limit + 0.5 || r.top < 0) out.fold.push(sel + ' bottom ' + Math.round(r.bottom) + ' > ' + Math.round(limit));
  }
  return out;
})(%d, %d)"""


async def run() -> int:
    if websockets is None:
        print("SKIP: the `websockets` package is not installed in this interpreter")
        return 0
    if not (DIST / "index.html").is_file():
        print("SKIP: spectra/web/guest-dist is not built — run "
              "`cd spectra/web && npx vite build --config vite.guest.config.ts`")
        return 0
    chrome = find_chrome()
    if chrome is None:
        print("SKIP: no Chromium found")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="jukebox-guest-render-"))
    scene = Scene()
    app, book = build_server(tmp, scene)
    port = free_port()
    server = start_uvicorn(app, port)
    base = f"http://127.0.0.1:{port}"
    dport = free_port()
    profile = f"/tmp/jukebox-guest-render-{dport}"
    proc = subprocess.Popen(  # noqa: S603
        [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={dport}", f"--user-data-dir={profile}", "--window-size=500,1000"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    failures: list[str] = []
    try:
        ws_url = await wait_for_devtools(dport)
        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
            mid = [0]

            def nid() -> int:
                mid[0] += 1
                return mid[0]

            for m in ("Page.enable", "Runtime.enable", "Network.enable"):
                await cdp(ws, nid, m)
            await cdp(ws, nid, "Page.addScriptToEvaluateOnNewDocument", {"source": TRAP})

            async def wait_for(expr: str, timeout: float = 12.0) -> bool:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    try:
                        if await evaluate(ws, nid, expr):
                            return True
                    except Exception:  # noqa: BLE001, S110
                        pass
                    await asyncio.sleep(0.2)
                return False

            async def tap(selector: str) -> bool:
                r = await evaluate(ws, nid, f"""(() => {{ const el = document.querySelector({selector!r});
                    if (!el) return null; el.scrollIntoView({{block: 'center'}});
                    const b = el.getBoundingClientRect();
                    return [b.left + b.width / 2, b.top + b.height / 2]; }})()""")
                if not r:
                    return False
                pt = [{"x": r[0], "y": r[1]}]
                await cdp(ws, nid, "Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": pt})
                await cdp(ws, nid, "Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                return True

            async def fresh(phone: tuple, me: str | None) -> bool:
                name, w, h, scale, top, bottom, ua = phone
                art_path = "/__art/0.png"
                # The previous phone's page — and its running poll loop — must
                # be torn down BEFORE clearing cookies/storage, or an in-flight
                # /g/hello response can re-set the jb_phone cookie and the
                # jukebox.phone localStorage entry right after the clear (or
                # after the planted phone code below is written), registering
                # this phone as the old guest instead.
                await cdp(ws, nid, "Page.navigate", {"url": "about:blank"})
                await wait_for("location.href === 'about:blank'")
                await cdp(ws, nid, "Network.clearBrowserCookies")
                await cdp(ws, nid, "Storage.clearDataForOrigin",
                          {"origin": base, "storageTypes": "all"})
                await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                    "width": w, "height": h, "deviceScaleFactor": scale, "mobile": True})
                await cdp(ws, nid, "Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
                await cdp(ws, nid, "Emulation.setUserAgentOverride", {"userAgent": ua})
                r = await cdp(ws, nid, "Emulation.setSafeAreaInsetsOverride",
                              {"insets": {"top": top, "bottom": bottom, "left": 0, "right": 0}})
                native = "error" not in r
                url = f"{base}/?t={TOKEN}"
                await cdp(ws, nid, "Page.navigate", {"url": base + art_path})
                await wait_for(
                    f"location.pathname === {art_path!r} && document.readyState === 'complete'")
                if me:
                    await evaluate(ws, nid, f"localStorage.setItem('jukebox.phone', {me!r}); true")
                await cdp(ws, nid, "Page.navigate", {"url": url})
                ok = await wait_for("!!document.querySelector('.g-welcome, .g-now, .g-message, .g-queue')")
                if ok and not native:
                    await evaluate(ws, nid, SAFE_VARS.format(top=top, bottom=bottom))
                return ok

            async def check(phone: tuple, shot: str) -> None:
                name, w, h, scale, top, bottom, ua = phone
                # measured as the screen first shows: from the top of the page
                await evaluate(ws, nid, "window.scrollTo(0, 0); true")
                await asyncio.sleep(0.5)
                o = await evaluate(ws, nid, CHECKS % (top, bottom))
                errs = await evaluate(ws, nid, "window.__guestErrors")
                problems = ([o["scrollX"]] if o["scrollX"] else []) + o["overflow"] + o["small"] + \
                    o["safe"] + o["fold"] + [f"error: {e}" for e in errs]
                r = await cdp(ws, nid, "Page.captureScreenshot", {"format": "png"})
                import base64
                (OUT_DIR / f"{name}-{shot}.png").write_bytes(base64.b64decode(r["result"]["data"]))
                mark = "✓" if not problems else "✗"
                print(f"  {mark} {name}-{shot}.png")
                for p in problems:
                    failures.append(f"{name} {shot}: {p}")

            def ledger_kinds(pid: str) -> list:
                w = book._wallet
                return [e.kind for e in w.led.history(pid)] if w else []

            async def credits_pass(phone: tuple) -> None:
                from models.jukebox import ShowConfig
                from services.jukebox import store
                name = phone[0]
                cme = ("C" * 21) + str(PHONES.index(phone))
                show = store.load_show()
                store.save_show(ShowConfig(**{**show.model_dump(), "play_mode": "credits"}))
                scene.name, scene.me, scene.jailed = "credits", cme, False
                scene.play_started = 2 + PHONES.index(phone)   # a fresh play: a fresh skip pot
                calls = lambda kind: sum(1 for c in scene.calls if c[0] == kind)  # noqa: E731
                skips0, nexts0, pardons0 = calls("skip"), calls("play_next"), calls("pardon")
                book._wallet_for("render-night", store.load_show()).led.grant(cme, "host_gift", 60)
                book._wallet = None            # reopened from the ledger, as after a restart
                try:
                    if not await fresh(phone, cme):
                        failures.append(f"{name}: credits: the page never loaded")
                        return
                    if await wait_for("!!document.querySelector('.g-welcome .g-btn-go')", 4):
                        if not await evaluate(ws, nid, "!!document.querySelector('.g-welcome-credits')"):
                            failures.append(f"{name}: credits: the welcome screen doesn't name the credits")
                        await tap(".g-btn-go")
                    if not await wait_for("!!document.querySelector('.g-credit-actions .g-btn-skip:not([disabled])')"
                                          " && /🎟 6[0-9]/.test(document.querySelector('.g-credits-chip')?.textContent || '')"):
                        failures.append(f"{name}: credits: no credits chip, or no skip button on Now")
                        return
                    await check(phone, "14-credits-now")
                    # tip: held three seconds with an Undo, then it lands in the ledger
                    await tap(".g-btn-tip")
                    if not await wait_for("!!document.querySelector('.g-toast-undo .g-undo')", 2):
                        failures.append(f"{name}: credits: a tip has no undo")
                    await check(phone, "15-tip-undo")
                    await tap(".g-undo")
                    await asyncio.sleep(3.5)
                    if "tip_out" in ledger_kinds(cme):
                        failures.append(f"{name}: credits: Undo didn't stop the tip")
                    await tap(".g-btn-tip")
                    if not await wait_for("!document.querySelector('.g-toast-undo')", 6) or \
                            not await wait_for("!!document.querySelector('.g-toast')", 4):
                        failures.append(f"{name}: credits: the tip never landed")
                    if "tip_out" not in ledger_kinds(cme):
                        failures.append(f"{name}: credits: the tip isn't in the ledger")
                    await wait_for("!document.querySelector('.g-toast')", 7)
                    # chip in: the sheet of amounts, one of them reaching the pot
                    await tap(".g-skip-row .g-btn-ghost")
                    if not await wait_for("!!document.querySelector('.g-sheet .g-amounts .g-btn-primary')", 4):
                        failures.append(f"{name}: credits: Chip in has no amounts")
                    await check(phone, "16-chip-in-sheet")
                    await tap(".g-sheet .g-amounts .g-btn-primary")
                    if not await wait_for("!document.querySelector('.g-sheet')", 6) or \
                            "skip_pledge" not in ledger_kinds(cme):
                        failures.append(f"{name}: credits: chipping in didn't reach the pot")
                    await wait_for("!document.querySelector('.g-toast')", 7)
                    # skip: it asks once, then pays the rest and the engine skips
                    await tap(".g-btn-skip")
                    if not await wait_for("!!document.querySelector('.g-sheet .g-btn-primary:not([disabled])')", 4):
                        failures.append(f"{name}: credits: the skip asks nothing")
                    await check(phone, "17-skip-confirm")
                    await tap(".g-sheet .g-btn-primary")
                    if not await wait_for("!document.querySelector('.g-sheet')", 6) or \
                            calls("skip") != skips0 + 1 or "skip" not in ledger_kinds(cme):
                        failures.append(f"{name}: credits: the paid skip didn't reach the engine")
                    await wait_for("!document.querySelector('.g-toast')", 7)
                    # Queue: prices on your song, and play next asks once
                    await tap(".g-tab:nth-child(2)")
                    if not await wait_for("[...document.querySelectorAll('.g-queue button')]"
                                          ".some((b) => /Play next · \\d/.test(b.textContent))", 6):
                        failures.append(f"{name}: credits: no priced Play next on your song")
                    await check(phone, "18-credits-queue")
                    await evaluate(ws, nid, """(() => { const b = [...document.querySelectorAll('.g-queue button')]
                      .find((x) => /Play next · \\d/.test(x.textContent)); b?.setAttribute('data-render', 'next'); return !!b; })()""")
                    await tap("[data-render=next]")
                    if not await wait_for("!!document.querySelector('.g-sheet .g-btn-primary:not([disabled])')", 4):
                        failures.append(f"{name}: credits: play next asks nothing")
                    await check(phone, "19-play-next-confirm")
                    await tap(".g-sheet .g-btn-primary")
                    if not await wait_for("!document.querySelector('.g-sheet')", 6) or \
                            calls("play_next") != nexts0 + 1 or "play_next" not in ledger_kinds(cme):
                        failures.append(f"{name}: credits: play next didn't reach the engine and the ledger")
                    await wait_for("!document.querySelector('.g-toast')", 7)
                    # the Shop: the balance, the prices, the history
                    await tap(".g-credits-chip")
                    if not await wait_for("document.querySelectorAll('.g-shop .g-history li').length >= 5"
                                          " && document.querySelectorAll('.g-shop .g-tile').length >= 5", 6):
                        failures.append(f"{name}: credits: the Shop has no tiles or no history")
                    await check(phone, "20-shop")
                    # jail: the card on Now, and a break-out that reaches the engine
                    scene.jailed = True
                    await tap(".g-tab:nth-child(1)")
                    if not await wait_for("!!document.querySelector('.g-jail-card .g-btn-primary:not([disabled])')"
                                          " && !!document.querySelector('.g-strip-jail')", 8):
                        failures.append(f"{name}: credits: no jail card with a break-out")
                    await check(phone, "21-jail-card")
                    # the red strip is the way out, on every screen: one tap opens the sheet
                    await tap(".g-strip-btn")
                    await wait_for("!!document.querySelector('.g-sheet .g-btn-primary:not([disabled])')", 4)
                    await tap(".g-sheet .g-btn-primary")
                    if not await wait_for("!document.querySelector('.g-jail-card')", 8) or \
                            calls("pardon") != pardons0 + 1 or ("pardon", cme, True) not in scene.calls \
                            or "jail_breakout" not in ledger_kinds(cme):
                        failures.append(f"{name}: credits: breaking out didn't reach the engine and the ledger")
                finally:
                    store.save_show(ShowConfig(**{**store.load_show().model_dump(), "play_mode": "free"}))
                    scene.name, scene.me, scene.jailed, scene.play_started = "plain", ME, False, 1

            for phone in PHONES:
                name = phone[0]
                print(name)
                # ── first visit to a vote: TWO taps ──
                scene.name = "plain"
                if not await fresh(phone, None):
                    failures.append(f"{name}: the page never loaded")
                    continue
                if not await wait_for("!!document.querySelector('.g-welcome .g-btn-go')"):
                    failures.append(f"{name}: no welcome screen on a first visit")
                    continue
                await check(phone, "1-welcome")
                if phone is PHONES[0]:
                    # the checks themselves can fail: a 30 px button and a box
                    # wider than the phone, planted on the page, must be named
                    o = await evaluate(ws, nid, """(() => {
                      const b = document.createElement('button'); b.textContent = 'tiny';
                      b.style.width = '30px'; b.style.height = '30px'; b.style.minHeight = '0';
                      const d = document.createElement('div'); d.className = 'planted-wide';
                      d.style.width = '2000px'; d.style.height = '4px';
                      const w = document.querySelector('.g-welcome'); w.prepend(b); w.prepend(d);
                      return true; })()""") and await evaluate(ws, nid, CHECKS % (phone[4], phone[5]))
                    if not (o["small"] and (o["overflow"] or o["scrollX"])):
                        failures.append("red control: a planted 30 px button or a too-wide box went unnoticed")
                    else:
                        print("  ✓ red control: the planted problems are named")
                    await fresh(phone, None)
                    await wait_for("!!document.querySelector('.g-welcome .g-btn-go')")
                await tap(".g-btn-go")                                      # tap 1
                if not await wait_for("!!document.querySelector('.g-vote-up:not([disabled])')"):
                    failures.append(f"{name}: Let's go didn't lead to the vote buttons")
                    continue
                await check(phone, "2-now")
                await tap(".g-vote-up")                                     # tap 2
                voted = await wait_for("document.querySelector('.g-vote-up')?.getAttribute('aria-pressed') === 'true'")
                tally = book._book.votes if book._book else {}
                if not voted or not any(v == 1 for plays in tally.values() for v in plays.values()):
                    failures.append(f"{name}: two taps did not land a vote in SpotFX's book")
                if not await wait_for("!!document.querySelector('.g-skip-line')", 4):
                    failures.append(f"{name}: no skip line under the vote buttons")
                await check(phone, "3-voted")
                await tap(".g-tab:nth-child(2)")
                await wait_for("!!document.querySelector('.g-queue')")
                await check(phone, "4-queue")
                # ── free play: move someone else's song down (the sheet) ──
                if await wait_for("!!document.querySelector('.g-move-btn')", 4):
                    await tap(".g-move-btn")
                    await wait_for("!!document.querySelector('.g-sheet .g-move-song')")
                    await check(phone, "11-move-sheet")
                    before = len(scene.bumped)
                    await tap(".g-sheet .g-btn-primary")
                    if not await wait_for("!!document.querySelector('.g-toast')", 6) or \
                            len(scene.bumped) != before + 1:
                        failures.append(f"{name}: the move sheet's button didn't move the song")
                    await wait_for("!document.querySelector('.g-toast')", 7)
                else:
                    failures.append(f"{name}: no ⇅ on a song the phone may move")
                await tap(".g-name-chip")
                await wait_for("!!document.querySelector('.g-sheet')")
                await check(phone, "5-name-sheet")
                # ── find a song and add it ──
                await evaluate(ws, nid, "document.querySelector('.g-sheet-backdrop')?.click(); true")
                await tap(".g-tab:nth-child(3)")
                if not await wait_for("!!document.querySelector('#g-search')"):
                    failures.append(f"{name}: no Add screen")
                    continue
                await tap("#g-search")
                await cdp(ws, nid, "Input.insertText", {"text": "danc"})
                if not await wait_for("document.querySelectorAll('.g-result').length >= 10"):
                    failures.append(f"{name}: no search results")
                    continue
                await check(phone, "9-add-results")
                ready = await evaluate(ws, nid, """(() => {
                  const h = [...document.querySelectorAll('.g-add .g-h2')].map((x) => x.textContent);
                  return h[0]?.startsWith('Ready') && !!document.querySelector('.g-badge-ready')
                    && !!document.querySelector('.g-badge-explicit') && !!document.querySelector('.g-badge-long'); })()""")
                if not ready:
                    failures.append(f"{name}: the Ready section, or the Ready/explicit/long badges, are missing")
                await tap(".g-add-btn:not([disabled])")
                if not await wait_for("!!document.querySelector('.g-toast')"):
                    failures.append(f"{name}: adding a song showed no confirmation")
                await check(phone, "10-added")
                scene.added.clear()
                # ── your song: next, then playing (the strip, the banner) ──
                scene.name = "mine_next"
                if not await fresh(phone, ME):
                    failures.append(f"{name}: reload failed")
                    continue
                if await wait_for("!!document.querySelector('.g-welcome .g-btn-go')", 3):
                    await tap(".g-btn-go")
                await wait_for("!!document.querySelector('.g-strip-next')")
                scene.name = "mine_playing"
                if not await wait_for("!!document.querySelector('.g-banner-playing')", 8):
                    failures.append(f"{name}: no 'your song is playing' banner on the change")
                await check(phone, "6-mine-playing")
                if phone[6] == IPHONE_UA:
                    if await wait_for("!!document.querySelector('.g-home-hint')", 3):
                        await tap(".g-home-hint")
                        await wait_for("!!document.querySelector('.g-sheet')")
                        addr = await evaluate(ws, nid, "location.search")
                        if f"p={ME}" not in addr:
                            failures.append(f"{name}: the Home Screen address doesn't carry the phone's code")
                        await check(phone, "7-home-screen-sheet")
                    else:
                        failures.append(f"{name}: no Add to Home Screen hint on an iPhone")
                # ── your songs in a time-out (free play's jail) ──
                await evaluate(ws, nid, "document.querySelector('.g-sheet-backdrop')?.click(); true")
                scene.name = "jailed"
                await tap(".g-tab:nth-child(1)")
                if not await wait_for("!!document.querySelector('.g-strip-jail')", 8):
                    failures.append(f"{name}: a time-out didn't turn the strip red")
                if not await wait_for("!document.querySelector('.g-banner')", 4):
                    failures.append(f"{name}: the 'your song is playing' banner outlived the song")
                await check(phone, "12-time-out")
                await tap(".g-tab:nth-child(2)")
                if not await wait_for("!!document.querySelector('.g-row-jailed')", 4):
                    failures.append(f"{name}: your song in a time-out isn't marked on Queue")
                if await evaluate(ws, nid, "!!document.querySelector('.g-move-btn')"):
                    failures.append(f"{name}: ⇅ is offered during a time-out")
                await check(phone, "13-time-out-queue")
                # ── credits mode (PR 3.2) ──
                await credits_pass(phone)
                # ── no night ──
                scene.name = "idle"
                await fresh(phone, None)
                await check(phone, "8-no-night")
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
        shutil.rmtree(profile, ignore_errors=True)
        server.should_exit = True
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nwrote {OUT_DIR.relative_to(REPO)}/")
    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
