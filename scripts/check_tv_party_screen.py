"""Real-browser proof for the Party screen (data/tv-display-plan/
plan.html PR 1.4, acceptance: "Render checks: no overflow, text >= 32 px,
art unaltered, attribution present").

Build first:
  (cd spectra/web && npx vite build --config vite.tv.config.ts)
Run:
  .venv/bin/python scripts/check_tv_party_screen.py

A REAL uvicorn server (spectra.app.create_app(), mounted under /spectra
exactly as production does) with `tv_feed.production_deps` swapped for a
canned scenario (a song playing, two "up next" items, a live guest link)
so the Party screen renders real content with no live SpotFX/engine
needed, and a REAL headless Chromium over raw CDP. Checks, on the actual
rendered DOM at 1920x1080:
  - no page overflow (scrollWidth == clientWidth, scrollHeight ==
    clientHeight);
  - every text node under .tv-party/.tv-callout computes a font-size of
    at least 32px (the plan's own §2.4 body floor);
  - the cover art's computed style never crops it (object-fit is
    "contain", never "cover") and carries no filter/blur, and its `src`
    is exactly the URL this script handed the feed — "unaltered";
  - the "Music from Spotify" attribution link is present with a real
    href.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
TV_DIST = os.path.join(REPO, "spectra", "web", "tv-dist")
CHROME = os.path.expanduser(
    "~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome")

ART_URL = "https://i.scdn.co/image/fake-cover-art-url"
OPEN_URL = "https://open.spotify.com/track/fakefakefakefakefake"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def _no_lifespan(app):
    yield


def _canned_deps():
    from spectra.services import tv_feed

    board = {
        "running": True, "reachable": True,
        "now": {
            "uri": "spotify:track:now", "title": "Dancing Queen", "artist": "ABBA",
            "image": ART_URL, "thumb": ART_URL, "open_url": OPEN_URL,
            "by": {"kind": "guest", "name": "Disco Ana"}, "up": 12, "down": 2,
            "duration_ms": 231000, "progress_ms": 127000, "is_playing": True,
        },
        "next": [
            {"uri": "spotify:track:n1", "title": "Mr. Brightside", "artist": "The Killers",
             "image": ART_URL, "thumb": ART_URL,
             "by": {"kind": "guest", "name": "Sunny Fox"}, "starts_in_ms": 5000},
            {"uri": "spotify:track:n2", "title": "September", "artist": "Earth, Wind & Fire",
             "image": ART_URL, "thumb": ART_URL, "by": {"kind": "set", "name": ""},
             "starts_in_ms": 240000},
        ],
        "board": {"title": "Tonight's top songs", "empty": "", "songs": [], "people": []},
        "link": "https://serenity.tail1234.ts.net:8443/?t=faketoken",
    }

    async def fetch(url):
        return dict(board)

    return tv_feed.TvFeedDeps(fetch_jukebox=fetch, clock_push_s=0.2, jukebox_poll_s=0.2,
                              show_clock=lambda: (127000, 127000, True), build_id=lambda: None)


class Server:
    def __init__(self, port: int) -> None:
        from fastapi import FastAPI

        from spectra.app import create_app
        from spectra.services import tv_feed
        import uvicorn

        tv_feed.production_deps = _canned_deps

        root = FastAPI(title="SPECTRA host (check)")
        root.mount("/spectra", create_app())
        root.router.lifespan_context = _no_lifespan
        self.server = uvicorn.Server(uvicorn.Config(
            root, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
        self.task = None

    async def start(self):
        self.task = asyncio.create_task(self.server.serve())
        for _ in range(300):
            if self.server.started:
                return
            await asyncio.sleep(0.05)
        raise RuntimeError("server did not start")

    async def stop(self):
        self.server.should_exit = True
        if self.task is not None:
            await asyncio.wait_for(self.task, timeout=10.0)


class CDPSession:
    def __init__(self, ws) -> None:
        self.ws = ws
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut is not None and not fut.done():
                        fut.set_result(msg.get("result", {}))
        except Exception:
            return

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        msg_id = self._next_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        await self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        return await asyncio.wait_for(fut, timeout=15.0)

    async def close(self) -> None:
        self._reader.cancel()


EXPR = """
JSON.stringify((function () {
  var party = document.querySelector('.tv-party');
  if (!party) return { ready: false };
  var smallText = [];
  party.querySelectorAll('*').forEach(function (el) {
    if (el.children.length > 0) return;  // only leaf text nodes
    var text = (el.textContent || '').trim();
    if (!text) return;
    var size = parseFloat(getComputedStyle(el).fontSize);
    if (size < 32) smallText.push({ tag: el.className || el.tagName, size: size, text: text.slice(0, 30) });
  });
  var art = party.querySelector('.tv-party-art');
  var artStyle = art ? getComputedStyle(art) : null;
  var link = Array.from(document.querySelectorAll('a')).find(function (a) {
    return a.textContent.indexOf('Music from Spotify') !== -1;
  });
  return {
    ready: true,
    smallText: smallText,
    artSrc: art ? art.getAttribute('src') : null,
    artObjectFit: artStyle ? artStyle.objectFit : null,
    artFilter: artStyle ? artStyle.filter : null,
    attributionHref: link ? link.getAttribute('href') : null,
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    scrollHeight: document.documentElement.scrollHeight,
    clientHeight: document.documentElement.clientHeight,
  };
})())
"""


async def main() -> int:
    if not os.path.isdir(TV_DIST):
        print(f"TV app build missing: {TV_DIST} — run "
             f"'(cd spectra/web && npx vite build --config vite.tv.config.ts)' first",
             file=sys.stderr)
        return 2
    if not os.path.exists(CHROME):
        print(f"headless Chromium not found at {CHROME}", file=sys.stderr)
        return 2

    http_port = free_port()
    server = Server(http_port)
    await server.start()
    base = f"http://127.0.0.1:{http_port}"
    print(f"== real server up on {base} (canned Party scenario) ==")

    cdp_port = free_port()
    profile_dir = tempfile.mkdtemp(prefix="tv-party-chrome-")
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
        f"--remote-debugging-port={cdp_port}", "--no-first-run",
        f"--user-data-dir={profile_dir}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                import urllib.request
                urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version", timeout=0.2)
                break
            except Exception:
                time.sleep(0.1)
        else:
            print("chrome did not come up", file=sys.stderr)
            return 2

        import urllib.request
        import websockets
        req = urllib.request.Request(
            f"http://127.0.0.1:{cdp_port}/json/new?{base}/spectra/tv/", method="PUT")
        target = json.loads(urllib.request.urlopen(req).read())
        ws_url = target["webSocketDebuggerUrl"]
        async with websockets.connect(ws_url, max_size=None) as ws:
            session = CDPSession(ws)
            await session.send("Emulation.setDeviceMetricsOverride", {
                "width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False,
            })
            # The page was already navigated by json/new; give the feed a
            # moment to connect and the first jukebox message to land.
            result = {"ready": False}
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                r = await session.send("Runtime.evaluate", {"expression": EXPR, "returnByValue": True})
                raw_val = r.get("result", {}).get("value")
                result = json.loads(raw_val) if raw_val else {"ready": False}
                if result.get("ready"):
                    break
                await asyncio.sleep(0.3)
            await session.close()

        if not result.get("ready"):
            print("FAIL: the Party screen never rendered", file=sys.stderr)
            return 1

        no_overflow = (result["scrollWidth"] == result["clientWidth"]
                       and result["scrollHeight"] == result["clientHeight"])
        print(f"  no overflow: {'OK' if no_overflow else 'FAIL'} "
              f"({result['scrollWidth']}x{result['scrollHeight']} vs "
              f"{result['clientWidth']}x{result['clientHeight']})")

        small = result["smallText"]
        print(f"  text >= 32px: {'OK' if not small else 'FAIL'}" + (f" {small}" if small else ""))

        art_ok = (result["artSrc"] == ART_URL and result["artObjectFit"] == "contain"
                 and result["artFilter"] in ("none", None))
        print(f"  art unaltered (src matches, object-fit:contain, no filter): "
              f"{'OK' if art_ok else 'FAIL'} "
              f"(src={result['artSrc']!r} fit={result['artObjectFit']!r} filter={result['artFilter']!r})")

        attribution_ok = bool(result["attributionHref"]) and "open.spotify.com" in (result["attributionHref"] or "")
        print(f"  attribution present: {'OK' if attribution_ok else 'FAIL'} "
              f"(href={result['attributionHref']!r})")

        ok = no_overflow and not small and art_ok and attribution_ok
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        await server.stop()
        import shutil
        shutil.rmtree(profile_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
