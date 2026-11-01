"""Real-browser proof for the TV probe page (data/tv-display-plan/
plan.html PR 0.1, acceptance: "Runs in a desktop browser and a headless
one; stores a result; touches no light").

A REAL uvicorn server (spectra.app.create_app(), isolated storage — no
light ownership, no fx import anywhere on this path) and a REAL headless
Chromium (the Playwright build already on this host) over raw CDP
(`chrome-devtools-axi` has a known `pageId` bug on this host, per standing
memory — raw CDP over `websockets` is the documented workaround). The page
runs its own 10-ish-second fps/ping battery unattended and POSTs its own
result; this script only opens the tab and waits for that POST to land,
exactly as a person opening this page on the TV would.

Run: .venv/bin/python scripts/check_tv_probe_page.py
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

import httpx
import websockets

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
CHROME = os.path.expanduser(
    "~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def _no_lifespan(app):
    yield


class Server:
    def __init__(self, port: int, storage_dir: str) -> None:
        from spectra import config as scfg
        scfg.TV_PROBE_FILE = os.path.join(storage_dir, "tv_probe_results.json")
        from spectra.app import create_app
        import uvicorn

        app = create_app()
        app.router.lifespan_context = _no_lifespan
        self.server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
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


async def _cdp(ws, msg_id: int, method: str, params: dict | None = None) -> dict:
    await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        raw = json.loads(await ws.recv())
        if raw.get("id") == msg_id:
            return raw.get("result", {})


async def drive_probe(page_url: str, cdp_port: int) -> None:
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
        log = await _cdp(ws, nid(), "Runtime.evaluate", {"expression": "0"})
        # Just confirming the tab answers; the page runs its own battery.
        assert "result" in log or log == {}


async def main() -> int:
    if not os.path.exists(CHROME):
        print(f"headless Chromium not found at {CHROME}", file=sys.stderr)
        return 2

    http_port = free_port()
    storage_dir = tempfile.mkdtemp(prefix="tv-probe-storage-")
    server = Server(http_port, storage_dir)
    await server.start()
    base = f"http://127.0.0.1:{http_port}"
    print(f"== real server up on {base} (storage isolated at {storage_dir}) ==")

    cdp_port = free_port()
    profile_dir = tempfile.mkdtemp(prefix="tv-probe-chrome-")
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

        page_url = f"{base}/tv/probe"
        await drive_probe(page_url, cdp_port)

        async with httpx.AsyncClient(base_url=base, timeout=10.0) as http:
            deadline = time.monotonic() + 30.0
            row = None
            while time.monotonic() < deadline:
                rows = (await http.get("/api/tv/probe/results")).json()
                if rows and rows[0].get("ping_ms"):
                    row = rows[0]
                    break
                await asyncio.sleep(0.5)

        if row is None:
            print("FAIL: no probe result landed within 30s", file=sys.stderr)
            return 1

        print(f"stored probe_id={row['probe_id']!r}")
        print(f"  user_agent: {row.get('user_agent', '')[:60]}")
        print(f"  webgl1={row.get('webgl1')} webgl2={row.get('webgl2')}")
        print(f"  fps tiers: {list((row.get('fps') or {}).keys())}")
        print(f"  ping samples: {len(row.get('ping_ms') or [])}")

        ok = (bool(row.get("user_agent")) and bool(row.get("fps"))
              and bool(row.get("ping_ms")))
        print("PASS" if ok else "FAIL (missing expected fields)")
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
        shutil.rmtree(storage_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
