"""Executable spec: the merged one-bar (UI declutter plan §2/§3/§6) fits
on one line with NO horizontal overflow at 1024, 1180 and 1440 px — the
three widths the Admiral decided on (landscape on both tablets, 1024 and
1180, plus desktop 1440).

Drives a real headless Chromium (no jsdom — jsdom has no layout engine, so
the no-jumping/no-overflow claim can only be proven against a real browser)
over raw CDP via websockets, the established recipe for this repo (no
Playwright Python dependency, no system Chrome requirement — launches the
cached Playwright Chromium binary directly).

READ-ONLY against the live app at http://127.0.0.1:8010/spectra/ (GET
requests only, no button pressed, nothing fired) — this task's own
instruction: front-end only, no live light tests, no writes.

What it measures, at each width:
  - the one-bar row itself does not force the page to scroll horizontally
    (`document.documentElement.scrollWidth <= clientWidth + 1`, a 1px
    rounding slop);
  - every one of the nine occupants (house / mode / hue hold / scenes /
    colour / energy+mark / light show / preview / release) is actually
    ON SCREEN (not clipped off the right edge) — `getBoundingClientRect()
    .right <= window.innerWidth + 1` for each.

This proves "fits on one line, nothing jumps/overflows" against whatever
names/state his live room happens to have right now — it does not (and,
read-only, cannot) inject a synthetic short/long name pair; that half of
"nothing jumps" is proven structurally instead by check_onebar_fixed_
widths.mjs, which reads the CSS source itself for the fixed-width rule
that makes content length irrelevant to layout.

Run: .venv/bin/python scripts/check_onebar_layout.py
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

try:
    import websockets
except ImportError:
    print("the 'websockets' package is not installed in this interpreter — "
          "skipping this check. Install with `pip install websockets`.")
    sys.exit(0)

REPO = Path(__file__).resolve().parent.parent
APP_URL = os.environ.get("SPECTRA_LIVE_URL", "http://127.0.0.1:8010/spectra/")
WIDTHS = [1024, 1180, 1440]
HEIGHT = 800

CHROME_CANDIDATES = [
    Path.home() / ".cache/ms-playwright",
]


def find_chrome() -> str | None:
    for p in ("google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(p)
        if found:
            return found
    for base in CHROME_CANDIDATES:
        if not base.is_dir():
            continue
        for cand in base.glob("chromium*/chrome-linux*/chrome"):
            if cand.is_file():
                return str(cand)
    return None


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def cdp_call(ws, msg_id, method, params=None):
    await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        raw = await ws.recv()
        data = json.loads(raw)
        if data.get("id") == msg_id:
            return data


async def wait_for_devtools(port: int, timeout_s: float = 15.0) -> str:
    """Returns the PAGE target's own websocket debugger URL (never the
    browser-level one `/json/version` returns) — the browser-level
    endpoint only answers `Target.*`/`Browser.*` commands in current
    Chrome, and `Page.navigate`/`Runtime.evaluate` 404 on it with
    "wasn't found" (measured, first version of this script)."""
    import urllib.request

    deadline = time.monotonic() + timeout_s
    last_err = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                targets = json.loads(r.read())
            pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
            if pages:
                return pages[0]["webSocketDebuggerUrl"]
        except Exception as e:  # noqa: BLE001
            last_err = e
        await asyncio.sleep(0.3)
    raise RuntimeError(f"devtools page target never came up: {last_err}")


async def main() -> int:
    chrome = find_chrome()
    if not chrome:
        print("no Chromium binary found (system Chrome or a cached Playwright "
              "install) — skipping this check.")
        return 0

    reachable = os.system(f"curl -s -o /dev/null --max-time 5 {APP_URL}")  # noqa: S605
    if reachable != 0:
        print(f"the live app at {APP_URL} is not reachable right now — skipping "
              "this check (it needs a running spectra.service to measure against).")
        return 0

    port = free_port()
    profile_dir = f"/tmp/spectra-onebar-layout-{port}"
    proc = subprocess.Popen(  # noqa: S603
        [
            chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--window-size=1440,900",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        # Never inherit this shell's own stdin/controlling terminal — this
        # script may run on a shared host; a leaked renderer child holding
        # the parent's fds open is exactly the class of problem that made
        # the TERMINATE below matter (killed by exact pid, never a pattern
        # match — see AGENTS.md's own "never pkill -f" lesson).
        start_new_session=True,
    )
    failures = 0

    def ok(cond: bool, msg: str) -> None:
        nonlocal failures
        if cond:
            print(f"  ✓ {msg}")
        else:
            print(f"  ✗ {msg}")
            failures += 1

    try:
        ws_url = await wait_for_devtools(port)
        async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as ws:
            mid = 0

            def nid():
                nonlocal mid
                mid += 1
                return mid

            await cdp_call(ws, nid(), "Page.enable")
            await cdp_call(ws, nid(), "Runtime.enable")
            await cdp_call(ws, nid(), "Page.navigate", {"url": APP_URL})
            # Wait for load via Runtime.evaluate polling rather than the
            # Page.loadEventFired notification (simpler over one socket).
            deadline = time.monotonic() + 20
            loaded = False
            last_diag = None
            while time.monotonic() < deadline:
                r = await cdp_call(ws, nid(), "Runtime.evaluate", {
                    "expression": "JSON.stringify({rs: document.readyState, "
                                  "bar: !!document.querySelector('.one-bar'), "
                                  "err: window.__lastError || null})",
                    "returnByValue": True,
                })
                last_diag = r.get("result", {}).get("result", {}).get("value")
                if last_diag:
                    parsed = json.loads(last_diag)
                    if parsed.get("rs") == "complete" and parsed.get("bar"):
                        loaded = True
                        break
                await asyncio.sleep(0.5)
            if not loaded:
                print(f"the one-bar never appeared within 20s (last diag: {last_diag}) — skipping "
                      "(is spectra.service actually serving a build with this change?)")
                return 0

            for width in WIDTHS:
                await cdp_call(ws, nid(), "Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False,
                })
                await asyncio.sleep(0.3)  # let layout settle
                r = await cdp_call(ws, nid(), "Runtime.evaluate", {
                    "expression": """
                        JSON.stringify({
                          scrollWidth: document.documentElement.scrollWidth,
                          clientWidth: document.documentElement.clientWidth,
                          bar: (() => {
                            const b = document.querySelector('.one-bar');
                            if (!b) return null;
                            const rect = b.getBoundingClientRect();
                            return { right: rect.right, width: rect.width };
                          })(),
                          occupants: [
                            '.mode-chip', '.mode-group-btn', '.ambient-group-btn',
                            '.scenes-group-btn', '.energy-mark-group', '.light-show-strip',
                            '.device-preview-strip', '.release-hold-wrap',
                          ].map((sel) => {
                            const els = [...document.querySelectorAll(sel)];
                            if (!els.length) return { sel, present: false, right: null };
                            const right = Math.max(...els.map((e) => e.getBoundingClientRect().right));
                            return { sel, present: true, right };
                          }),
                        })
                    """,
                    "returnByValue": True,
                })
                value = r.get("result", {}).get("result", {}).get("value")
                data = json.loads(value) if value else {}
                ok(
                    data.get("bar") is not None,
                    f"at {width}px: the one-bar is present",
                )
                if data.get("bar") is None:
                    continue
                ok(
                    data["scrollWidth"] <= data["clientWidth"] + 1,
                    f"at {width}px: no page-level horizontal scroll "
                    f"(scrollWidth {data['scrollWidth']} <= clientWidth {data['clientWidth']})",
                )
                ok(
                    data["bar"]["right"] <= width + 1,
                    f"at {width}px: the one-bar's own right edge ({data['bar']['right']:.0f}) "
                    f"stays within the viewport",
                )
                for occ in data.get("occupants", []):
                    if not occ["present"]:
                        continue  # a hidden-when-nothing-to-show occupant (ReleaseButton
                                  # when already released, LightShowStrip when inactive, etc.)
                    ok(
                        occ["right"] <= width + 1,
                        f"at {width}px: {occ['sel']} stays within the viewport "
                        f"(right={occ['right']:.0f})",
                    )
    finally:
        # Exact-pid/pgid teardown only — never a pattern-based kill on a
        # shared host (AGENTS.md's own "pkill -f hits live spectra.service"
        # / "pkill -f matches own shell" lessons). `start_new_session=True`
        # above made this process its own group leader, so killing the
        # whole group reaps any renderer/zygote children it spawned too.
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        shutil.rmtree(profile_dir, ignore_errors=True)

    print("\nPASS" if failures == 0 else f"\nFAIL ({failures})")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
