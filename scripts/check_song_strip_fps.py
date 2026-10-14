"""Drawn-fps measurement for the global SongStrip (song-layout-plan,
data/ui-layout-plan/report.md §4.2: "no frame-rate measurement was taken —
slice 3 should measure it with the existing scripts/preview_perf rig's
drawn-fps method").

Uses that rig's own TECHNIQUE (a real headless Chromium, real CDP, a
counter wired to requestAnimationFrame so "drawn fps" means real per-frame
work, not an estimate) rather than its full harness: `preview_perf`'s own
`:live`/`:map` systems are purpose-built for the device-preview/Live-view
feature (a real dummy-device fx host, a link emulator, LedFX comparison) and
are not a drop-in fit for this global, read-only strip. Instead this drives
`spectra/web/harness/songstrip.html` (built alongside the existing
harness pages by `vite.harness.config.ts`) — the REAL SongStrip component,
a REAL rAF loop doing REAL SVG-attribute/textContent writes every tick
(never a React render), against a MOCKED fetch/WebSocket so the measurement
needs no live SPECTRA process and touches no room: zero network, zero
light risk, matching this repo's standing rule that nothing under
`scripts/` may point at live hardware for a perf check.

`window.requestAnimationFrame` is wrapped once in the harness's own
bootstrap (songstrip.tsx) to count invocations in `window.__perf.rafCount`
— since SongStrip's rAF loop performs its attribute/textContent writes on
EVERY tick unconditionally (no "skip this frame" branch), counting rAF
invocations IS counting drawn frames here, the same equivalence
`preview_perf`'s own README states for the Live view's WebGL/2D-fallback
renderer.

Run:
  (cd spectra/web && npx vite build --config vite.harness.config.ts)
  .venv/bin/python scripts/check_song_strip_fps.py
"""
from __future__ import annotations

import asyncio
import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

import websockets

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS_DIST = os.path.join(REPO, "spectra", "web", "harness-dist")
CHROME = os.path.expanduser(
    "~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome")
MEASURE_S = 6.0


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = True


def _serve_dist(port: int) -> _Server:
    # The harness build's `base: '/spectra/'` (vite.harness.config.ts) means
    # every asset reference inside the built HTML is rooted at "/spectra/"
    # — strip that one prefix before resolving against HARNESS_DIST, the
    # same convention preview_perf's own start_spectra() serves under.
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=HARNESS_DIST, **kw)

        def translate_path(self, path):
            if path.startswith("/spectra/"):
                path = path[len("/spectra"):]
            elif path == "/spectra":
                path = "/"
            return super().translate_path(path)

        def log_message(self, *a):  # quiet
            pass

    srv = _Server(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


async def _cdp(ws, msg_id: int, method: str, params: dict | None = None) -> dict:
    await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        raw = json.loads(await ws.recv())
        if raw.get("id") == msg_id:
            return raw.get("result", {})


async def _measure(page_url: str, cdp_port: int) -> float:
    import urllib.request
    req = urllib.request.Request(
        f"http://127.0.0.1:{cdp_port}/json/new?{page_url}", method="PUT")
    targets = json.loads(urllib.request.urlopen(req).read())
    ws_url = targets["webSocketDebuggerUrl"]
    async with websockets.connect(ws_url, max_size=None) as ws:
        mid = 0

        def nid():
            nonlocal mid
            mid += 1
            return mid

        await _cdp(ws, nid(), "Page.enable")
        await _cdp(ws, nid(), "Runtime.enable")
        # Let the page settle (mount, first fetches, first WS push) before
        # starting the window — matches the rig's own settle convention.
        await asyncio.sleep(2.0)
        t0 = await _cdp(ws, nid(), "Runtime.evaluate",
                        {"expression": "window.__perf.rafCount", "returnByValue": True})
        start_count = t0["result"]["value"]
        t_start = time.monotonic()
        await asyncio.sleep(MEASURE_S)
        t1 = await _cdp(ws, nid(), "Runtime.evaluate",
                        {"expression": "window.__perf.rafCount", "returnByValue": True})
        end_count = t1["result"]["value"]
        elapsed = time.monotonic() - t_start
        return (end_count - start_count) / elapsed


async def main() -> int:
    if not os.path.isdir(HARNESS_DIST):
        print(f"harness build missing: {HARNESS_DIST} — run "
             f"'(cd spectra/web && npx vite build --config vite.harness.config.ts)' first",
             file=sys.stderr)
        return 2
    if not os.path.exists(CHROME):
        print(f"headless Chromium not found at {CHROME}", file=sys.stderr)
        return 2

    http_port = _free_port()
    srv = _serve_dist(http_port)
    cdp_port = _free_port()
    profile_dir = tempfile.mkdtemp(prefix="songstrip-fps-")
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
        f"--remote-debugging-port={cdp_port}", "--no-first-run",
        "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
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

        page_url = f"http://127.0.0.1:{http_port}/spectra/songstrip.html"
        fps = await _measure(page_url, cdp_port)
        print(f"SongStrip drawn fps (rAF invocations/s, {MEASURE_S:.0f}s window): {fps:.1f}")
        print("PASS" if fps >= 30 else "FAIL (below 30 fps)")
        return 0 if fps >= 30 else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        srv.shutdown()
        import shutil
        shutil.rmtree(profile_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
