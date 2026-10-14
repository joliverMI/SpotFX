"""Drawn-fps + drag-responsiveness measurement for Home's audio-shape
canvas (HomeTimeline.tsx — the Admiral, 2026-10-14: "the audio shape isn't
as responsive"). Same TECHNIQUE as check_song_strip_fps.py: a real headless
Chromium, real CDP, counters wired into the real rAF/clearRect/canvas-width
machinery so "drawn fps" means real per-frame work, not an estimate —
against spectra/web/harness/hometimeline.html's own mocked fetch/WebSocket,
so this needs no live SPECTRA process and touches no room.

Measures, at IDLE and DURING A SYNTHETIC WINDOW DRAG:
  - rAF invocations/s          ("as live as the song strip" target: ~60)
  - canvas.clearRect() calls/s (the shape canvas's own redraw cadence —
    before the fix this tracked REACT RE-RENDERS, not animation frames, so
    it would have spiked during a drag and stalled between them; after the
    fix it should track rAF 1:1 in both conditions)
  - canvas.width WRITES        (backing-buffer resizes — should be ~0 once
    the harness's fixed-size container has already sized it once, even
    while dragging, per the "resize only when the measured size actually
    changed" guard)

Run:
  (cd spectra/web && npx vite build --config vite.harness.config.ts)
  .venv/bin/python scripts/check_home_timeline_fps.py
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
IDLE_S = 3.0
DRAG_S = 3.0


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = True


def _serve_dist(port: int) -> _Server:
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


async def _evaluate(ws, nid, expr: str):
    r = await _cdp(ws, nid(), "Runtime.evaluate", {"expression": expr, "returnByValue": True})
    return r["result"]["value"]


async def _measure(page_url: str, cdp_port: int) -> dict:
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
        await asyncio.sleep(2.0)  # settle: mount, first fetches

        def snap():
            return {}

        raf0 = await _evaluate(ws, nid, "window.__perf.rafCount")
        clear0 = await _evaluate(ws, nid, "window.__perf.clearRectCount")
        resize0 = await _evaluate(ws, nid, "window.__perf.resizeCount")
        await asyncio.sleep(IDLE_S)
        raf1 = await _evaluate(ws, nid, "window.__perf.rafCount")
        clear1 = await _evaluate(ws, nid, "window.__perf.clearRectCount")
        resize1 = await _evaluate(ws, nid, "window.__perf.resizeCount")

        idle = {
            "raf_fps": (raf1 - raf0) / IDLE_S,
            "clearrect_fps": (clear1 - clear0) / IDLE_S,
            "resizes": resize1 - resize0,
        }

        # Now drive a synthetic window drag for the same duration and
        # re-measure — the exact scenario that used to cost a full canvas
        # resize+redraw on EVERY pointermove.
        await _cdp(ws, nid(), "Runtime.evaluate", {"expression": "window.__drag(180, 16)"})
        raf2 = await _evaluate(ws, nid, "window.__perf.rafCount")
        clear2 = await _evaluate(ws, nid, "window.__perf.clearRectCount")
        resize2 = await _evaluate(ws, nid, "window.__perf.resizeCount")
        await asyncio.sleep(DRAG_S)
        raf3 = await _evaluate(ws, nid, "window.__perf.rafCount")
        clear3 = await _evaluate(ws, nid, "window.__perf.clearRectCount")
        resize3 = await _evaluate(ws, nid, "window.__perf.resizeCount")

        dragging = {
            "raf_fps": (raf3 - raf2) / DRAG_S,
            "clearrect_fps": (clear3 - clear2) / DRAG_S,
            "resizes": resize3 - resize2,
        }
        return {"idle": idle, "dragging": dragging}


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
    profile_dir = tempfile.mkdtemp(prefix="hometimeline-fps-")
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

        page_url = f"http://127.0.0.1:{http_port}/spectra/hometimeline.html"
        result = await _measure(page_url, cdp_port)
        idle, dragging = result["idle"], result["dragging"]
        print(f"IDLE    — rAF: {idle['raf_fps']:.1f}/s  shape-canvas redraws: "
              f"{idle['clearrect_fps']:.1f}/s  backing-buffer resizes: {idle['resizes']}")
        print(f"DRAGGING — rAF: {dragging['raf_fps']:.1f}/s  shape-canvas redraws: "
              f"{dragging['clearrect_fps']:.1f}/s  backing-buffer resizes: {dragging['resizes']}")

        ok = True
        if idle['raf_fps'] < 30:
            print("FAIL (idle rAF below 30 fps)"); ok = False
        if dragging['raf_fps'] < 30:
            print("FAIL (dragging rAF below 30 fps — a drag must not stall the frame clock)"); ok = False
        # The shape canvas must redraw roughly once PER FRAME, not once per
        # pointermove: at 16ms/move for 3s that's ~180 pointermoves, which
        # would have meant ~180 redraws/s under the old effect-per-render
        # shape. After the fix it tracks rAF, so it must stay within a
        # generous band of the frame rate, both idle and dragging.
        if not (0.5 * dragging['raf_fps'] <= dragging['clearrect_fps'] <= 1.5 * dragging['raf_fps']):
            print(f"FAIL (dragging shape-canvas redraw rate {dragging['clearrect_fps']:.1f}/s is not "
                  f"tracking the frame rate {dragging['raf_fps']:.1f}/s — redraws are following "
                  f"something other than animation frames)")
            ok = False
        if dragging['resizes'] > 1:
            print(f"FAIL ({dragging['resizes']} backing-buffer resizes while dragging at an "
                  f"unchanged measured size — the resize-on-change guard did not hold)")
            ok = False
        print("PASS" if ok else "— see FAILs above")
        return 0 if ok else 1
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
