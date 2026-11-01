"""Real-browser proof for the TV app shell (data/tv-display-plan/
plan.html PR 1.1, acceptance: "<= 120 KB gz; renders at 1920x1080 and
1280x720 in the render harness").

Build first:
  (cd spectra/web && npx vite build --config vite.tv.config.ts)
Run:
  .venv/bin/python scripts/check_tv_app_shell.py

A REAL uvicorn server (spectra.app.create_app(), mounting the just-built
spectra/web/tv-dist/ at /tv exactly as spectra/app.py does in production)
and a REAL headless Chromium over raw CDP (the same workaround this repo's
other checks use — `chrome-devtools-axi` has a known `pageId` bug on this
host). Confirms: the built JS+CSS gzip total is under the 120 KB target;
the page loads with no console errors at both target viewports; the
earlier-registered /tv/probe route still answers (the ordering this file's
own comment in spectra/app.py depends on); and the three planes (System,
Info, Visual canvas) are all present in the DOM.
"""
from __future__ import annotations

import asyncio
import contextlib
import gzip
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
GZ_TARGET_BYTES = 120 * 1024
CHROME = os.path.expanduser(
    "~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def measure_gz_size(dist_dir: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(dist_dir):
        for name in files:
            if name.endswith((".js", ".css")):
                path = os.path.join(root, name)
                with open(path, "rb") as fh:
                    total += len(gzip.compress(fh.read(), compresslevel=9))
    return total


@contextlib.asynccontextmanager
async def _no_lifespan(app):
    yield


class Server:
    def __init__(self, port: int) -> None:
        from fastapi import FastAPI

        from spectra.app import create_app
        import uvicorn

        # Mount under /spectra, exactly as spectra/app.py::_standalone()
        # does for the real :8010 process — the TV build's own `base:
        # '/spectra/tv/'` (vite.tv.config.ts) bakes that prefix into every
        # asset reference, so a bare create_app() with no wrapper (the
        # shortcut scripts/check_tv_probe_page.py takes, safe there only
        # because the probe page's fetches are hand-written as relative
        # paths) would 404 every asset.
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
    """ONE reader task demuxing a CDP websocket into (a) replies to
    pending commands, matched by id, and (b) events (console messages,
    etc.) — two concurrent `ws.recv()` callers racing for the same
    messages would unpredictably steal each other's replies, which is
    what a naive per-call recv loop alongside a separate event listener
    does."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.console_errors: list[str] = []
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut is not None and not fut.done():
                        fut.set_result(msg.get("result", {}))
                elif msg.get("method") == "Runtime.consoleAPICalled":
                    if msg["params"].get("type") == "error":
                        args = msg["params"].get("args", [])
                        self.console_errors.append(" ".join(
                            str(a.get("value", a.get("description", ""))) for a in args))
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


async def check_viewport(cdp_port: int, page_url: str, width: int, height: int) -> tuple[bool, list[str]]:
    import urllib.request
    import websockets

    req = urllib.request.Request(
        f"http://127.0.0.1:{cdp_port}/json/new?about:blank", method="PUT")
    target = json.loads(urllib.request.urlopen(req).read())
    ws_url = target["webSocketDebuggerUrl"]
    async with websockets.connect(ws_url, max_size=None) as ws:
        session = CDPSession(ws)
        try:
            await session.send("Page.enable")
            await session.send("Runtime.enable")
            await session.send("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False,
            })
            await session.send("Page.navigate", {"url": page_url})
            await asyncio.sleep(2.0)

            dom = await session.send("Runtime.evaluate", {
                "expression": (
                    "JSON.stringify({"
                    "visual: !!document.querySelector('.tv-visual-plane'),"
                    "info: !!document.querySelector('.tv-info-plane'),"
                    "system: !!document.querySelector('.tv-system-plane'),"
                    "w: document.documentElement.scrollWidth,"
                    "cw: document.documentElement.clientWidth"
                    "})"
                ),
                "returnByValue": True,
            })
            raw_val = dom.get("result", {}).get("value")
            planes = json.loads(raw_val) if raw_val else {}
            console_errors = list(session.console_errors)
        finally:
            await session.close()

    ok = (bool(planes.get("visual")) and bool(planes.get("info"))
          and bool(planes.get("system")) and not console_errors
          and planes.get("w") == planes.get("cw"))
    return ok, console_errors


async def main() -> int:
    # The feed's jukebox relay would otherwise default to SpotFX's own
    # production port (:8000) — a real, possibly-in-use address on a
    # shared host. Point it at a certainly-unused port so a fetch fails
    # fast (connection refused) rather than touching anything real.
    os.environ["SPOTFX_PORT"] = str(free_port())

    if not os.path.isdir(TV_DIST):
        print(f"TV app build missing: {TV_DIST} — run "
             f"'(cd spectra/web && npx vite build --config vite.tv.config.ts)' first",
             file=sys.stderr)
        return 2
    if not os.path.exists(CHROME):
        print(f"headless Chromium not found at {CHROME}", file=sys.stderr)
        return 2

    gz_total = measure_gz_size(TV_DIST)
    print(f"gzipped JS+CSS total: {gz_total} bytes (target <= {GZ_TARGET_BYTES})")
    size_ok = gz_total <= GZ_TARGET_BYTES

    http_port = free_port()
    server = Server(http_port)
    await server.start()
    base = f"http://127.0.0.1:{http_port}"
    print(f"== real server up on {base} ==")

    cdp_port = free_port()
    profile_dir = tempfile.mkdtemp(prefix="tv-shell-chrome-")
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

        render_ok = True
        for (w, h) in [(1920, 1080), (1280, 720)]:
            ok, errors = await check_viewport(cdp_port, f"{base}/spectra/tv/", w, h)
            print(f"  {w}x{h}: {'OK' if ok else 'FAIL'}" + (f" errors={errors}" if errors else ""))
            render_ok = render_ok and ok

        import httpx
        async with httpx.AsyncClient(base_url=base, timeout=10.0) as http:
            probe_resp = await http.get("/spectra/tv/probe")
            probe_ok = probe_resp.status_code == 200 and "SPECTRA TV probe" in probe_resp.text
            print(f"  /tv/probe still reachable alongside the /tv mount: "
                  f"{'OK' if probe_ok else 'FAIL'} (status={probe_resp.status_code})")

        ok = size_ok and render_ok and probe_ok
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
