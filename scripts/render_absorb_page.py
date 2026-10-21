#!/usr/bin/env python3
"""Screenshot the Absorb Music page (/absorb) at 1440, 1180 and 390 px.

Renders `spectra/web/harness/absorb.html` — the REAL chrome and the REAL
absorb/AbsorbPage.tsx against a mocked backend (see that file's header) —
in a headless Chromium, three states (a window mid-evening, the shipped
idle state, a window that stepped aside for his music) at each width, plus
one interaction (force recapture switched on, to show its meaning change),
and writes the PNGs to docs/evidence/absorb-page/.

It also FAILS, not just draws, on the two things a screenshot can hide:
a page that scrolls sideways at a width (document or any card wider than
its box), and a JavaScript error while rendering.

Never touches a live service: the harness is served from the built
`harness-dist` by a plain static server on a spare port (the vite dev
server would proxy an unmocked request to :8000), and the page's own
fetch is mocked before it renders.

    cd spectra/web && npx vite build --config vite.harness.config.ts
    .venv/bin/python scripts/render_absorb_page.py
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

OUT_DIR = REPO / "docs" / "evidence" / "absorb-page"
WIDTHS = (1440, 1180, 390)
STATES = ("running", "idle", "paused")

# Collect any page error from the very first script on.
ERROR_TRAP = """
window.__absorbErrors = [];
window.addEventListener('error', (e) => window.__absorbErrors.push(String(e.message || e)));
window.addEventListener('unhandledrejection', (e) => window.__absorbErrors.push('rejection: ' + String(e.reason)));
const _ce = console.error.bind(console);
console.error = (...a) => { window.__absorbErrors.push(a.map(String).join(' ')); _ce(...a); };
"""

READY = """(() => {
  const run = document.querySelector('.absorb-run-card');
  const att = document.querySelector('[data-testid="absorb-parked"]');
  return !!run && !!att && !/Reading…/.test(att.textContent || '');
})()"""

OVERFLOW = """(() => {
  const de = document.documentElement;
  const wide = [...document.querySelectorAll('.absorb-card, .absorb-tile, .absorb-window, .absorb-now')]
    .filter((el) => el.scrollWidth > el.clientWidth + 1)
    .map((el) => el.className + ' ' + el.scrollWidth + '>' + el.clientWidth);
  return { page: de.scrollWidth + 'x' + de.clientWidth, pageWide: de.scrollWidth > de.clientWidth + 1, wide };
})()"""


async def run() -> int:
    if websockets is None:
        print("SKIP: the `websockets` package is not installed in this interpreter")
        return 0
    if not (HARNESS_DIST / "absorb.html").is_file():
        print("SKIP: harness-dist/absorb.html is not built — run "
              "`cd spectra/web && npx vite build --config vite.harness.config.ts`")
        return 0
    chrome = find_chrome()
    if chrome is None:
        print("SKIP: no Chromium found")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    httpd = serve(HARNESS_DIST, free_port())
    base = f"http://127.0.0.1:{httpd.server_address[1]}/spectra/absorb.html"
    port = free_port()
    profile = f"/tmp/spectra-absorb-render-{port}"
    proc = subprocess.Popen(  # noqa: S603
        [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", "--window-size=1440,900"],
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

            async def render(state: str, width: int, name: str, after: str | None = None) -> None:
                await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 600})
                await cdp(ws, nid, "Emulation.setTouchEmulationEnabled", {"enabled": width < 600})
                if not await goto(ws, nid, f"{base}?state={state}", READY):
                    failures.append(f"{name}: the page never finished loading")
                    return
                if after:
                    await evaluate(ws, nid, after)
                await asyncio.sleep(0.8)
                o = await evaluate(ws, nid, OVERFLOW)
                errs = await evaluate(ws, nid, "window.__absorbErrors")
                mark = "✓"
                if o["pageWide"] or o["wide"]:
                    failures.append(f"{name}: scrolls sideways — page {o['page']}, {o['wide']}")
                    mark = "✗"
                if errs:
                    failures.append(f"{name}: page errors {errs}")
                    mark = "✗"
                await shoot(ws, nid, OUT_DIR / f"{name}.png")
                print(f"  {mark} {name}.png  (page {o['page']})")

            for state in STATES:
                for w in WIDTHS:
                    await render(state, w, f"{state}-{w}")
            # one interaction: force recapture ON — the meaning beside the
            # switch (and the preview's split) change with it
            await render("running", 1440, "running-force-recapture-on-1440", after="""(() => {
              const b = document.querySelector('[aria-label="Enable force recapture"]');
              if (b) b.click();
              return !!b;
            })()""")
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
