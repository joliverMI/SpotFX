#!/usr/bin/env python3
"""Render the printable guest card (spectra/web/src/jukebox/JukeboxCardsPage.tsx,
the plan's §9 N2) in real Chromium and print it to a Letter PDF, then
measure it in print media:

  * eight cards fit one Letter page (two across, four down), none split
    across a page;
  * every QR code is at least one inch square on paper, with room for its
    quiet zone;
  * the controls don't print, and nothing on the sheet overflows its card;
  * the longest Wi-Fi the page takes (a 32-character name, a 63-character
    password printed as text too) still fits each card;
  * no page error.

It uses the built harness (spectra/web/harness/jukeboxcards.html, a mocked
party link and eight unused codes), types a made-up Wi-Fi in, and never
touches a live service. That every QR decodes back to what its card says is
scripts/check_jukebox_cards.mjs's job (jsQR, on the very same modules).

    cd spectra/web && npx vite build --config vite.harness.config.ts
    .venv/bin/python scripts/render_jukebox_cards.py

Writes docs/evidence/jukebox-cards/ (or `--out DIR`): cards.pdf, sheet.png,
controls.png, longest.png.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
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

OUT_DIR = REPO / "docs" / "evidence" / "jukebox-cards"
PX_PER_IN = 96

TRAP = """
window.__cardErrors = [];
window.addEventListener('error', (e) => window.__cardErrors.push(String(e.message || e)));
window.addEventListener('unhandledrejection', (e) => window.__cardErrors.push('rejection: ' + String(e.reason)));
const _ce = console.error.bind(console);
console.error = (...a) => { window.__cardErrors.push(a.map(String).join(' ')); _ce(...a); };
"""
READY = "!!document.querySelector('input[aria-label=\"Wi-Fi network name\"]') && !/Reading/.test(document.body.textContent)"
SETTER = """
  const set = (sel, v) => {
    const el = document.querySelector(sel);
    const proto = Object.getPrototypeOf(el);
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };"""
TYPE = """(() => {""" + SETTER + """
  set('input[aria-label="Wi-Fi network name"]', 'Serenity Guests');
  set('input[aria-label="Wi-Fi password"]', 'made-up-harness-password');
  set('input[aria-label="How many cards"]', '8');
  return true;
})()"""
# the longest a name (32) and a WPA password (63) can be, printed as text too
LONGEST = """(() => {""" + SETTER + """
  set('input[aria-label="Wi-Fi network name"]', 'WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW');
  set('input[aria-label="Wi-Fi password"]', 'W'.repeat(63));
  const box = [...document.querySelectorAll('label')].find((l) => /password as text/.test(l.textContent)).querySelector('input');
  if (!box.checked) box.click();
  return true;
})()"""
MEASURE = """(() => {
  const cards = [...document.querySelectorAll('[data-testid="jukebox-card"]')];
  const qrs = [...document.querySelectorAll('.jukebox-card-qr')].map((q) => q.getBoundingClientRect());
  const over = cards.filter((c) => c.scrollWidth > c.clientWidth + 1 || c.scrollHeight > c.clientHeight + 1).length;
  const controls = document.querySelector('.jukebox-cards-controls');
  return { cards: cards.length, minQr: Math.min(...qrs.map((r) => Math.min(r.width, r.height))),
           overflow: over, controlsShown: !!controls && getComputedStyle(controls).display !== 'none',
           cardW: cards[0]?.getBoundingClientRect().width, cardH: cards[0]?.getBoundingClientRect().height };
})()"""


async def run(out_dir: Path = OUT_DIR) -> int:
    if websockets is None:
        print("SKIP: the `websockets` package is not installed in this interpreter")
        return 0
    if not (HARNESS_DIST / "jukeboxcards.html").is_file():
        print("SKIP: harness-dist/jukeboxcards.html is not built — run "
              "`cd spectra/web && npx vite build --config vite.harness.config.ts`")
        return 0
    chrome = find_chrome()
    if chrome is None:
        print("SKIP: no Chromium found")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    httpd = serve(HARNESS_DIST, free_port())
    base = f"http://127.0.0.1:{httpd.server_address[1]}/spectra/jukeboxcards.html"
    port = free_port()
    profile = f"/tmp/spectra-jukebox-cards-{port}"
    proc = subprocess.Popen(  # noqa: S603
        [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", "--window-size=1000,1400"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    failures: list[str] = []
    try:
        ws_url = await wait_for_devtools(port)
        async with websockets.connect(ws_url, max_size=128 * 1024 * 1024) as ws:
            mid = [0]

            def nid() -> int:
                mid[0] += 1
                return mid[0]

            await cdp(ws, nid, "Page.enable")
            await cdp(ws, nid, "Runtime.enable")
            await cdp(ws, nid, "Page.addScriptToEvaluateOnNewDocument", {"source": TRAP})
            await cdp(ws, nid, "Emulation.setDeviceMetricsOverride",
                      {"width": 1000, "height": 1400, "deviceScaleFactor": 1, "mobile": False})
            if not await goto(ws, nid, base, READY):
                print("FAIL: the page never loaded")
                return 1
            await shoot(ws, nid, out_dir / "controls.png")
            await evaluate(ws, nid, TYPE)
            await asyncio.sleep(0.8)
            screen = await evaluate(ws, nid, MEASURE)
            if screen["cards"] != 8:
                failures.append(f"8 cards asked for, {screen['cards']} drawn")
            await shoot(ws, nid, out_dir / "sheet.png")
            # in print media: the controls hide, the sheet is what prints
            await cdp(ws, nid, "Emulation.setEmulatedMedia", {"media": "print"})
            await asyncio.sleep(0.3)
            printed = await evaluate(ws, nid, MEASURE)
            if printed["controlsShown"]:
                failures.append("the controls would print")
            if printed["minQr"] < PX_PER_IN - 0.5:
                failures.append(f"a QR code prints {printed['minQr'] / PX_PER_IN:.2f} in — under an inch")
            if printed["overflow"]:
                failures.append(f"{printed['overflow']} card(s) overflow their box")
            # two across and four down within Letter's printable area (8.5×11 in, 0.35 in margins)
            usable_w, usable_h = (8.5 - 0.7) * PX_PER_IN, (11 - 0.7) * PX_PER_IN
            if 2 * printed["cardW"] > usable_w or 4 * printed["cardH"] > usable_h:
                failures.append(f"two by four cards ({printed['cardW']:.0f}×{printed['cardH']:.0f} px each) "
                                f"don't fit Letter's {usable_w:.0f}×{usable_h:.0f} px")
            # the longest Wi-Fi, password printed too: still one card each
            await cdp(ws, nid, "Emulation.setEmulatedMedia", {"media": ""})
            await evaluate(ws, nid, LONGEST)
            await asyncio.sleep(0.5)
            await cdp(ws, nid, "Emulation.setEmulatedMedia", {"media": "print"})
            await asyncio.sleep(0.3)
            longest = await evaluate(ws, nid, MEASURE)
            if longest["overflow"]:
                failures.append(f"with the longest Wi-Fi printed, {longest['overflow']} card(s) overflow")
            await shoot(ws, nid, out_dir / "longest.png")
            await cdp(ws, nid, "Emulation.setEmulatedMedia", {"media": ""})
            await evaluate(ws, nid, TYPE)
            await asyncio.sleep(0.5)
            box_on = await evaluate(ws, nid, "[...document.querySelectorAll('label')].find((l) => /password as text/.test(l.textContent)).querySelector('input').checked")
            if box_on:
                await evaluate(ws, nid, "([...document.querySelectorAll('label')].find((l) => /password as text/.test(l.textContent)).querySelector('input').click(), true)")
            await asyncio.sleep(0.3)
            await cdp(ws, nid, "Emulation.setEmulatedMedia", {"media": "print"})
            r = await cdp(ws, nid, "Page.printToPDF", {"paperWidth": 8.5, "paperHeight": 11,
                                                      "preferCSSPageSize": True, "printBackground": True})
            pdf = base64.b64decode(r["result"]["data"])
            (out_dir / "cards.pdf").write_bytes(pdf)
            pages = pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")
            if pages != 1:
                failures.append(f"eight cards printed on {pages} pages, not one")
            errs = await evaluate(ws, nid, "window.__cardErrors")
            if errs:
                failures.append(f"page errors {errs}")
            print(f"  cards {printed['cards']}, each {printed['cardW'] / PX_PER_IN:.2f}×{printed['cardH'] / PX_PER_IN:.2f} in, "
                  f"QR {printed['minQr'] / PX_PER_IN:.2f} in, {pages} page(s)")
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
        httpd.shutdown()
    print(f"\nwrote {out_dir}/")
    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="where to write the PDF and screenshots")
    sys.exit(asyncio.run(run(ap.parse_args().out)))
