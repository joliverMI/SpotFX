"""Real-browser proof for the Attract, Sleep and lost-connection screens
(data/tv-display-plan/plan.html PR 1.5, acceptance: "Render checks: deck
cycles, QR corner swaps, drift — no element static for > 10 min; pure
black after the sleep timeout; 5s mark / 60s black on a lost connection").

Build first:
  (cd spectra/web && npx vite build --config vite.tv.config.ts)
Run:
  .venv/bin/python scripts/check_tv_attract_sleep.py

Three scenarios, each a REAL uvicorn server (spectra.app.create_app(),
mounted under /spectra exactly as production does) with
`tv_feed.production_deps` swapped for a canned scenario, and a REAL
headless Chromium over raw CDP:

  ATTRACT — no night running, idle time held at 0 (never sleeps). Checks
  the deck (.tv-attract) renders, every visible leaf text node is >= 32px
  (the plan's own §2.4 body floor), and the card actually changes within
  one ATTRACT_CARD_MS wait (burn-in's own cadence — the pure arithmetic is
  proven exhaustively offline by scripts/check_tv_burnin.mjs; this is the
  one real-render confirmation that the component actually reads it).

  HAZE DIMS DURING ATTRACT — compares the Visual plane canvas's total
  rendered pixel brightness between a party-layout page and an
  attract-layout one (VisualPlane.tsx's dimRef), proving the dim actually
  reaches the frame rather than just sitting in the source.

  SLEEP — idle time held far past SLEEP_TIMEOUT_S from the very first
  `config` message. Checks the page is pure black (.tv-sleep present, no
  .tv-visual-plane/.tv-system-plane painted underneath — PR 1.5's own
  "sleep is a separate, smaller tree" design) and the DOM holds nothing
  that could itself become a burn-in risk.

  LOST CONNECTION — a normal (attract) connection, then the server is
  stopped out from under the open WebSocket. Checks nothing appears
  before 5s (the quiet-blip window), a dim "Reconnecting…" mark appears
  between 5s and 60s at >= 32px, and the full-black overlay appears at
  60s. This scenario alone takes over a minute of real wall-clock time —
  it is a one-off manual proof, not meant for a fast per-commit loop.
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


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def _no_lifespan(app):
    yield


def _attract_deps():
    from spectra.services import tv_feed

    board = {
        "running": False, "reachable": True,
        "now": {
            "uri": "spotify:track:now", "title": "Dancing Queen", "artist": "ABBA",
            "image": "", "thumb": "", "open_url": "",
            "by": {"kind": "guest", "name": "Disco Ana"}, "up": 1, "down": 0,
            "duration_ms": 231000, "progress_ms": 1000, "is_playing": False,
        },
        "next": [],
        "board": {"title": "Tonight's top songs", "empty": "", "songs": [
            {"uri": "spotify:track:t1", "title": "Mr. Brightside", "artist": "The Killers",
             "by": {"kind": "guest", "name": "Sunny Fox"}, "ups": 4},
        ], "people": []},
        "link": "https://serenity.tail1234.ts.net:8443/?t=faketoken",
    }

    async def fetch(url):
        return dict(board)

    return tv_feed.TvFeedDeps(
        fetch_jukebox=fetch, clock_push_s=0.2, jukebox_poll_s=0.2,
        show_clock=lambda: (None, None, False), build_id=lambda: None,
        idle_s=lambda active, now_ms: 0.0,
    )


def _party_deps():
    from spectra.services import tv_feed

    board = {
        "running": True, "reachable": True,
        "now": {
            "uri": "spotify:track:now", "title": "Dancing Queen", "artist": "ABBA",
            "image": "", "thumb": "", "open_url": "",
            "by": {"kind": "guest", "name": "Disco Ana"}, "up": 1, "down": 0,
            "duration_ms": 231000, "progress_ms": 1000, "is_playing": True,
        },
        "next": [],
        "board": {"title": "Tonight's top songs", "empty": "", "songs": [], "people": []},
        "link": None,
    }

    async def fetch(url):
        return dict(board)

    return tv_feed.TvFeedDeps(
        fetch_jukebox=fetch, clock_push_s=0.2, jukebox_poll_s=0.2,
        show_clock=lambda: (1000, 1000, True), build_id=lambda: None,
        idle_s=lambda active, now_ms: 0.0,
    )


def _sleep_deps():
    from spectra.services import tv_feed

    async def fetch(url):
        return {"running": False, "reachable": True, "now": None, "next": [],
                "board": {"title": "", "empty": "", "songs": [], "people": []},
                "link": None}

    return tv_feed.TvFeedDeps(
        fetch_jukebox=fetch, clock_push_s=0.2, jukebox_poll_s=0.2,
        show_clock=lambda: (None, None, False), build_id=lambda: None,
        idle_s=lambda active, now_ms: 0.0 if active else 9999.0,
    )


class Server:
    def __init__(self, port: int, deps_factory) -> None:
        from fastapi import FastAPI

        from spectra.app import create_app
        from spectra.services import tv_feed
        import uvicorn

        tv_feed.production_deps = deps_factory

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
            with contextlib.suppress(asyncio.CancelledError, Exception):
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


async def _spawn_chrome(profile_prefix: str):
    cdp_port = free_port()
    profile_dir = tempfile.mkdtemp(prefix=profile_prefix)
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
        f"--remote-debugging-port={cdp_port}", "--no-first-run",
        f"--user-data-dir={profile_dir}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version", timeout=0.2)
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("chrome did not come up")
    return proc, cdp_port, profile_dir


async def _open_page(cdp_port: int, url: str) -> CDPSession:
    import urllib.request
    import websockets
    req = urllib.request.Request(f"http://127.0.0.1:{cdp_port}/json/new?{url}", method="PUT")
    target = json.loads(urllib.request.urlopen(req).read())
    ws_url = target["webSocketDebuggerUrl"]
    ws = await websockets.connect(ws_url, max_size=None)
    session = CDPSession(ws)
    await session.send("Emulation.setDeviceMetricsOverride", {
        "width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False,
    })
    return session


ATTRACT_EXPR = """
JSON.stringify((function () {
  var attract = document.querySelector('.tv-attract');
  var small = [];
  if (attract) {
    attract.querySelectorAll('*').forEach(function (el) {
      if (el.children.length > 0) return;
      var text = (el.textContent || '').trim();
      if (!text) return;
      var size = parseFloat(getComputedStyle(el).fontSize);
      if (size < 32) small.push({ cls: el.className, size: size, text: text.slice(0, 30) });
    });
  }
  return {
    present: !!attract,
    text: attract ? attract.textContent : null,
    small: small,
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  };
})())
"""

SLEEP_EXPR = """
JSON.stringify({
  sleepPresent: !!document.querySelector('.tv-sleep'),
  visualPresent: !!document.querySelector('.tv-visual-plane'),
  systemPresent: !!document.querySelector('.tv-system-plane'),
  attractPresent: !!document.querySelector('.tv-attract'),
  bg: getComputedStyle(document.querySelector('.tv-sleep') || document.body).backgroundColor,
  bodyChildrenCount: document.body.children.length,
})
"""

LOST_EXPR = """
JSON.stringify((function () {
  var mark = document.querySelector('.tv-lost-mark');
  var black = document.querySelector('.tv-lost-black');
  return {
    markPresent: !!mark,
    markText: mark ? mark.textContent : null,
    markSize: mark ? parseFloat(getComputedStyle(mark).fontSize) : null,
    blackPresent: !!black,
  };
})())
"""

#: Sums every pixel channel in the Visual plane's canvas, and also reports
#: the pixel count — the fixed `#06040b` background fill (rgb 6+4+11=21
#: per pixel) contributes a large CONSTANT offset to the raw sum that is
#: identical in every scenario and swells the ratio toward 1 if left in;
#: subtracting `21 * width * height` isolates the haze-dependent part,
#: which is what actually scales with dimRef's alpha.
HAZE_SUM_EXPR = """
JSON.stringify((function () {
  var c = document.querySelector('.tv-visual-plane');
  if (!c) return { present: false };
  var ctx = c.getContext('2d');
  var data = ctx.getImageData(0, 0, c.width, c.height).data;
  var sum = 0;
  for (var i = 0; i < data.length; i += 4) sum += data[i] + data[i + 1] + data[i + 2];
  return { present: true, sum: sum, pixels: c.width * c.height };
})())
"""
BACKGROUND_SUM_PER_PIXEL = 6 + 4 + 11  # #06040b


async def check_attract() -> bool:
    port = free_port()
    server = Server(port, _attract_deps)
    await server.start()
    base = f"http://127.0.0.1:{port}"
    proc, cdp_port, profile_dir = await _spawn_chrome("tv-attract-chrome-")
    try:
        session = await _open_page(cdp_port, f"{base}/spectra/tv/")
        try:
            # Give the first config/jukebox message a moment to land.
            seen_texts = set()
            deadline = time.monotonic() + 18.0  # > ATTRACT_CARD_MS (15s) + settle
            result = {"present": False}
            while time.monotonic() < deadline:
                r = await session.send("Runtime.evaluate", {"expression": ATTRACT_EXPR, "returnByValue": True})
                raw_val = r.get("result", {}).get("value")
                result = json.loads(raw_val) if raw_val else {"present": False}
                if result.get("present"):
                    seen_texts.add(result.get("text"))
                await asyncio.sleep(0.5)
        finally:
            await session.close()

        present = result.get("present", False)
        print(f"  .tv-attract present: {'OK' if present else 'FAIL'}")
        small = result.get("small") or []
        print(f"  text >= 32px: {'OK' if not small else 'FAIL'}" + (f" {small}" if small else ""))
        no_overflow = result.get("scrollWidth") == result.get("clientWidth")
        print(f"  no overflow: {'OK' if no_overflow else 'FAIL'}")
        cycles = len(seen_texts) > 1
        print(f"  the deck cycles within one card period: {'OK' if cycles else 'FAIL'} "
              f"(saw {len(seen_texts)} distinct card renderings)")
        return bool(present and not small and no_overflow and cycles)
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        await server.stop()
        import shutil
        shutil.rmtree(profile_dir, ignore_errors=True)


async def _haze_sum(deps_factory, profile_prefix: str) -> float:
    port = free_port()
    server = Server(port, deps_factory)
    await server.start()
    base = f"http://127.0.0.1:{port}"
    proc, cdp_port, profile_dir = await _spawn_chrome(profile_prefix)
    try:
        session = await _open_page(cdp_port, f"{base}/spectra/tv/")
        try:
            await asyncio.sleep(1.5)  # let the feed connect and VisualPlane paint a frame
            r = await session.send("Runtime.evaluate", {"expression": HAZE_SUM_EXPR, "returnByValue": True})
            result = json.loads(r.get("result", {}).get("value") or "{}")
        finally:
            await session.close()
        if not result.get("present"):
            raise RuntimeError("VisualPlane canvas never appeared")
        baseline = BACKGROUND_SUM_PER_PIXEL * float(result["pixels"])
        return float(result["sum"]) - baseline
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        await server.stop()
        import shutil
        shutil.rmtree(profile_dir, ignore_errors=True)


async def check_haze_dims() -> bool:
    """The haze dims during 'attract' (plan's own "a very dim haze",
    VisualPlane.tsx's dimRef, 0.4x) — proven on the rendered canvas, not
    just by reading the source: the haze-dependent part of a party-layout
    canvas's total pixel brightness (raw sum minus the fixed background's
    own constant contribution) should land near 0.4x of the attract one's,
    within generous tolerance for the blobs' drifting overlap."""
    party_haze = await _haze_sum(_party_deps, "tv-haze-party-chrome-")
    attract_haze = await _haze_sum(_attract_deps, "tv-haze-attract-chrome-")
    print(f"  party haze-dependent brightness: {party_haze:.0f}")
    print(f"  attract haze-dependent brightness: {attract_haze:.0f}")
    ratio = attract_haze / party_haze if party_haze else float("inf")
    print(f"  ratio (expect ~0.4): {ratio:.3f}")
    dimmer = 0.25 <= ratio <= 0.55
    print(f"  attract is noticeably (and roughly correctly) dimmer than party: "
          f"{'OK' if dimmer else 'FAIL'}")
    return dimmer


async def check_sleep() -> bool:
    port = free_port()
    server = Server(port, _sleep_deps)
    await server.start()
    base = f"http://127.0.0.1:{port}"
    proc, cdp_port, profile_dir = await _spawn_chrome("tv-sleep-chrome-")
    try:
        session = await _open_page(cdp_port, f"{base}/spectra/tv/")
        try:
            result = {"sleepPresent": False}
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                r = await session.send("Runtime.evaluate", {"expression": SLEEP_EXPR, "returnByValue": True})
                raw_val = r.get("result", {}).get("value")
                result = json.loads(raw_val) if raw_val else {"sleepPresent": False}
                if result.get("sleepPresent"):
                    break
                await asyncio.sleep(0.3)
        finally:
            await session.close()

        sleep_ok = result.get("sleepPresent", False)
        print(f"  .tv-sleep present: {'OK' if sleep_ok else 'FAIL'}")
        pure = not result.get("visualPresent") and not result.get("systemPresent") and not result.get("attractPresent")
        print(f"  nothing else renders underneath (no visual/system/attract plane): "
              f"{'OK' if pure else 'FAIL'}")
        bg = result.get("bg")
        black_ok = bg in ("rgb(0, 0, 0)", "rgba(0, 0, 0, 1)")
        print(f"  background is pure black: {'OK' if black_ok else 'FAIL'} (got {bg!r})")
        return bool(sleep_ok and pure and black_ok)
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        await server.stop()
        import shutil
        shutil.rmtree(profile_dir, ignore_errors=True)


async def check_lost_connection() -> bool:
    port = free_port()
    server = Server(port, _attract_deps)
    await server.start()
    base = f"http://127.0.0.1:{port}"
    proc, cdp_port, profile_dir = await _spawn_chrome("tv-lost-chrome-")
    try:
        session = await _open_page(cdp_port, f"{base}/spectra/tv/")
        try:
            # Let it connect first.
            await asyncio.sleep(1.5)
            r = await session.send("Runtime.evaluate", {"expression": LOST_EXPR, "returnByValue": True})
            before = json.loads(r.get("result", {}).get("value") or "{}")
            before_ok = not before.get("markPresent") and not before.get("blackPresent")
            print(f"  connected: nothing shown: {'OK' if before_ok else 'FAIL'}")

            # Pull the rug: stop the server, killing the open socket.
            await server.stop()
            t0 = time.monotonic()

            async def poll_until(predicate, timeout_s):
                deadline = time.monotonic() + timeout_s
                last = {}
                while time.monotonic() < deadline:
                    rr = await session.send("Runtime.evaluate", {"expression": LOST_EXPR, "returnByValue": True})
                    last = json.loads(rr.get("result", {}).get("value") or "{}")
                    if predicate(last):
                        return last, time.monotonic() - t0
                    await asyncio.sleep(0.5)
                return last, time.monotonic() - t0

            # Still quiet right after the drop (< 5s window).
            quiet, elapsed_quiet = await poll_until(
                lambda s: s.get("markPresent") or s.get("blackPresent"), 4.0)
            quiet_ok = not quiet.get("markPresent") and not quiet.get("blackPresent")
            print(f"  quiet blip (<5s): {'OK' if quiet_ok else 'FAIL'} (at {elapsed_quiet:.1f}s)")

            mark, elapsed_mark = await poll_until(lambda s: s.get("markPresent"), 8.0)
            mark_ok = (mark.get("markPresent") and (mark.get("markSize") or 0) >= 32
                      and "Reconnecting" in (mark.get("markText") or ""))
            print(f"  'Reconnecting…' mark appears ~5s in, >= 32px: {'OK' if mark_ok else 'FAIL'} "
                  f"(at {elapsed_mark:.1f}s, text={mark.get('markText')!r}, size={mark.get('markSize')!r})")

            black, elapsed_black = await poll_until(lambda s: s.get("blackPresent"), 65.0)
            black_ok = bool(black.get("blackPresent"))
            print(f"  full black appears ~60s in: {'OK' if black_ok else 'FAIL'} (at {elapsed_black:.1f}s)")

            return bool(before_ok and quiet_ok and mark_ok and black_ok)
        finally:
            await session.close()
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        import shutil
        shutil.rmtree(profile_dir, ignore_errors=True)


async def main() -> int:
    if not os.path.isdir(TV_DIST):
        print(f"TV app build missing: {TV_DIST} — run "
             f"'(cd spectra/web && npx vite build --config vite.tv.config.ts)' first",
             file=sys.stderr)
        return 2
    if not os.path.exists(CHROME):
        print(f"headless Chromium not found at {CHROME}", file=sys.stderr)
        return 2

    print("== ATTRACT ==")
    attract_ok = await check_attract()
    print("== HAZE DIMS DURING ATTRACT ==")
    haze_ok = await check_haze_dims()
    print("== SLEEP ==")
    sleep_ok = await check_sleep()
    print("== LOST CONNECTION (takes over a minute) ==")
    lost_ok = await check_lost_connection()

    ok = attract_ok and haze_ok and sleep_ok and lost_ok
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
