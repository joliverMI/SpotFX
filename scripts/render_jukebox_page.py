#!/usr/bin/env python3
"""Screenshot the Jukebox page (/jukebox) at 1400×876, 876×1400 and 412×891.

Renders `spectra/web/harness/jukebox.html` — the REAL chrome and the REAL
jukebox/JukeboxPage.tsx against a mocked backend (see that file's header) —
in a headless Chromium (data/jukebox-plan/report.md §9, PR 1.3's
acceptance: the host tablet landscape and portrait, and a phone), three
states (a night running, the shipped idle state, slots placed by hand), the
Set list tab, the Live tab and the Credits tab of the running night, and writes the PNGs to
docs/evidence/jukebox-page/.

It also FAILS, not just draws, on the two things a screenshot can hide:
a page that scrolls sideways at a width (document or any card wider than
its box), and a JavaScript error while rendering.

Never touches a live service: the harness is served from the built
`harness-dist` by a plain static server on a spare port (the vite dev
server would proxy an unmocked request to :8000), and the page's own
fetch is mocked before it renders.

    cd spectra/web && npx vite build --config vite.harness.config.ts
    .venv/bin/python scripts/render_jukebox_page.py
"""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_ui_fidelity import (  # noqa: E402
    HARNESS_DIST, REPO, cdp, evaluate, find_chrome, free_port, goto, serve, shoot,
    wait_for_devtools, websockets,
)

OUT_DIR = REPO / "docs" / "evidence" / "jukebox-page"
VIEWPORTS = ((1400, 876), (876, 1400), (412, 891))
STATES = ("running", "idle", "manual")

# Collect any page error from the very first script on.
ERROR_TRAP = """
window.__jukeboxErrors = [];
window.addEventListener('error', (e) => window.__jukeboxErrors.push(String(e.message || e)));
window.addEventListener('unhandledrejection', (e) => window.__jukeboxErrors.push('rejection: ' + String(e.reason)));
const _ce = console.error.bind(console);
console.error = (...a) => { window.__jukeboxErrors.push(a.map(String).join(' ')); _ce(...a); };
"""

READY = """(() => {
  const page = document.querySelector('.jukebox-page');
  if (!page) return false;
  const text = page.textContent || '';
  if (/Reading the/.test(text)) return false;
  return !!document.querySelector('[data-testid="jukebox-set-card"], [data-testid="jukebox-live-card"]');
})()"""

OVERFLOW = """(() => {
  const de = document.documentElement;
  const wide = [...document.querySelectorAll('.jukebox-card, .jukebox-row, .jukebox-item, .jukebox-head, .jukebox-sign-in, .jukebox-field, .jukebox-price-row, .jukebox-preset')]
    .filter((el) => el.scrollWidth > el.clientWidth + 1)
    .map((el) => el.className + ' ' + el.scrollWidth + '>' + el.clientWidth);
  return { page: de.scrollWidth + 'x' + de.clientWidth, pageWide: de.scrollWidth > de.clientWidth + 1, wide };
})()"""


async def run() -> int:
    if websockets is None:
        print("SKIP: the `websockets` package is not installed in this interpreter")
        return 0
    if not (HARNESS_DIST / "jukebox.html").is_file():
        print("SKIP: harness-dist/jukebox.html is not built — run "
              "`cd spectra/web && npx vite build --config vite.harness.config.ts`")
        return 0
    chrome = find_chrome()
    if chrome is None:
        print("SKIP: no Chromium found")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    httpd = serve(HARNESS_DIST, free_port())
    base = f"http://127.0.0.1:{httpd.server_address[1]}/spectra/jukebox.html"
    port = free_port()
    profile = f"/tmp/spectra-jukebox-render-{port}"
    proc = subprocess.Popen(  # noqa: S603
        [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", "--window-size=1400,1400"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    failures: list[str] = []
    try:
        ws_url = await wait_for_devtools(port)
        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
            mid = [0]

            def nid() -> int:
                mid[0] += 1
                return mid[0]

            await cdp(ws, nid, "Page.enable")
            await cdp(ws, nid, "Runtime.enable")
            await cdp(ws, nid, "Page.addScriptToEvaluateOnNewDocument", {"source": ERROR_TRAP})

            async def render(state: str, size: tuple[int, int], name: str,
                             after: str | None = None) -> None:
                width, height = size
                await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": height, "deviceScaleFactor": 1,
                    "mobile": width < 600})
                await cdp(ws, nid, "Emulation.setTouchEmulationEnabled", {"enabled": width < 600})
                if not await goto(ws, nid, f"{base}?state={state}", READY):
                    failures.append(f"{name}: the page never finished loading")
                    return
                if after:
                    if not await evaluate(ws, nid, after):
                        failures.append(f"{name}: the interaction found nothing to press")
                        return
                await asyncio.sleep(0.8)
                o = await evaluate(ws, nid, OVERFLOW)
                errs = await evaluate(ws, nid, "window.__jukeboxErrors")
                mark = "✓"
                if o["pageWide"] or o["wide"]:
                    failures.append(f"{name}: scrolls sideways — page {o['page']}, {o['wide']}")
                    mark = "✗"
                if errs:
                    failures.append(f"{name}: page errors {errs}")
                    mark = "✗"
                await shoot(ws, nid, OUT_DIR / f"{name}.png")
                print(f"  {mark} {name}.png  (page {o['page']})")

            live_tab = """(() => {
              const b = [...document.querySelectorAll('.jukebox-tabs button')]
                .find((x) => x.textContent === 'Live');
              if (b) b.click();
              return !!b;
            })()"""
            for state in STATES:
                for size in VIEWPORTS:
                    await render(state, size, f"{state}-set-{size[0]}x{size[1]}")
            for size in VIEWPORTS:
                await render("running", size, f"running-live-{size[0]}x{size[1]}", after=live_tab)
            credits_tab = live_tab.replace("'Live'", "'Credits'")
            for size in VIEWPORTS:
                await render("running", size, f"running-credits-{size[0]}x{size[1]}", after=credits_tab)
    finally:
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
        shutil.rmtree(profile, ignore_errors=True)
        httpd.shutdown()
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
