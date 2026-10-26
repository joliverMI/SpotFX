#!/usr/bin/env python3
"""HOME'S DROPS PANEL, LAID OUT (predrop plan step 1 — report section 3.7's
acceptance: "a headless-Chromium layout check at 390 / 800 / 1180 px (no
sideways scroll, three cards in a row at 1180, stacked on a phone, 44 px
touch targets, the toggle bar on one line at 390 px)").

Renders `spectra/web/harness/homedrops.html` — the REAL quick-run cards and
the REAL Drops card (home/HomeQuickRuns.tsx, home/HomeDrops.tsx, home/
HomeDropEditor.tsx) inside Home's own `main.home-route`, against a mocked
backend — in a headless Chromium at each width, with a mouse and with a
finger (touch emulated: `(pointer: coarse)`, asserted, so a touch case
measures what it says), and in the wall kiosk's own frame (800 x 424, the
`?kiosk=1` page's `.kiosk-page` / `main.kiosk-main`, touch). Each case is
measured, a drop's editor opened, measured again, and the screenshots
written to docs/evidence/home-drops/. It FAILS, not just draws, when:

  - the page, a card, a row or a toggle bar scrolls sideways;
  - at 1180 the three cards are not in one row; at 390 they are not
    stacked; at 800 (and on the kiosk) Quick sequences / Quick actions do
    not share a row with the Drops card on its own full row below;
  - any row's toggle bar wraps onto a second line (every case);
  - an editor handle is smaller than 44 x 44 px, or — under a finger, at
    any width — a toggle button is shorter than 44 px or narrower than
    40 px (with a mouse the desktop's 34 x 32 is fine);
  - the page throws while rendering.

Never touches a live service: the harness is served from the built
`harness-dist` by a plain static server on a spare port.

    cd spectra/web && npx vite build --config vite.harness.config.ts
    .venv/bin/python scripts/check_home_drops_layout.py [--out DIR]

`--out` sends the screenshots elsewhere (tests/test_home_drops_layout.py
passes a temp folder, so a test run never rewrites the tracked evidence).
"""
from __future__ import annotations

import argparse
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

OUT_DIR = REPO / "docs" / "evidence" / "home-drops"
# (width, a finger?, the kiosk's frame?) — the phone is always a finger
CASES = ((390, True, False), (800, False, False), (800, True, False),
         (1180, False, False), (1180, True, False), (800, True, True))
KIOSK_HEIGHT = 424            # kiosk/kioskConfig.ts: 480 less HA's 56 px header

ERROR_TRAP = """
window.__dropsErrors = [];
window.addEventListener('error', (e) => window.__dropsErrors.push(String(e.message || e)));
window.addEventListener('unhandledrejection', (e) => window.__dropsErrors.push('rejection: ' + String(e.reason)));
"""

READY = """(() => {
  const rows = document.querySelectorAll('.home-drops-row');
  const seq = document.querySelector('.home-quick-seq-row');
  return rows.length === 4 && !!seq;
})()"""

MEASURE = """(() => {
  const de = document.documentElement;
  const r = (el) => { const b = el.getBoundingClientRect();
    return { l: Math.round(b.left), t: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height) }; };
  const cards = [...document.querySelectorAll('.home-quick-runs > .home-quick-card')].map((el) => ({
    drops: el.classList.contains('home-drops-card'), ...r(el) }));
  const grid = r(document.querySelector('.home-quick-runs'));
  const wide = [...document.querySelectorAll('.home-quick-card, .home-drops-row, .home-drops-bar')]
    .filter((el) => el.scrollWidth > el.clientWidth + 1)
    .map((el) => el.className + ' ' + el.scrollWidth + '>' + el.clientWidth);
  const bars = [...document.querySelectorAll('.home-drops-bar')].map((bar) => {
    const btns = [...bar.querySelectorAll(':scope > button')].map(r);
    const tops = new Set(btns.map((b) => b.t));
    const row = bar.closest('.home-drops-row').getBoundingClientRect();
    return { lines: tops.size, n: btns.length, minH: Math.min(...btns.map((b) => b.h)),
             minW: Math.min(...btns.map((b) => b.w)),
             inside: btns.every((b) => b.l >= row.left - 1 && b.l + b.w <= row.right + 1) };
  });
  const handles = [...document.querySelectorAll('.home-drop-editor-handle')].map(r);
  return { page: de.scrollWidth + 'x' + de.clientWidth, pageWide: de.scrollWidth > de.clientWidth + 1,
           cards, grid, wide, bars, handles, coarse: matchMedia('(pointer: coarse)').matches };
})()"""

OPEN_EDITOR = """(() => {
  const b = document.querySelector('.home-drops-row .home-drops-btn.edit');
  if (b) b.click();
  return !!b;
})()"""


def _tag(width: int, touch: bool, kiosk: bool) -> str:
    if kiosk:
        return f"kiosk-{width}"
    return f"{width}{'-touch' if touch and width > 520 else ''}"


def _check(width: int, m: dict, failures: list[str], editor: bool,
           touch: bool = False, kiosk: bool = False) -> list[str]:
    name = f"{_tag(width, touch, kiosk)}{' editor' if editor else ''}"
    bad: list[str] = []
    if m["coarse"] != touch:
        bad.append(f"(pointer: coarse) is {m['coarse']}, but this case is "
                   f"{'a finger' if touch else 'a mouse'} — it would measure the wrong layout")
    if m["pageWide"] or m["wide"]:
        bad.append(f"scrolls sideways — page {m['page']}, {m['wide']}")
    cards = m["cards"]
    if len(cards) != 3:
        bad.append(f"expected three cards, found {len(cards)}")
    elif width >= 1180:
        if len({c["t"] for c in cards}) != 1:
            bad.append(f"the three cards are not in one row: tops {[c['t'] for c in cards]}")
    elif width <= 520:
        tops = [c["t"] for c in cards]
        if not all(a < b for a, b in zip(tops, tops[1:])) or len({c["l"] for c in cards}) != 1:
            bad.append(f"the cards are not stacked: {cards}")
    else:
        a, b, d = cards
        if not (a["t"] == b["t"] and d["t"] > a["t"] and d["drops"]):
            bad.append(f"at {width} the two quick cards should share a row, the Drops card below: {cards}")
        elif abs(d["w"] - m["grid"]["w"]) > 2:
            bad.append(f"the Drops card should span the row: {d['w']} vs {m['grid']['w']}")
    for i, bar in enumerate(m["bars"]):
        if bar["n"] != 7:
            bad.append(f"row {i}: {bar['n']} toggles, not 7")
        if bar["lines"] != 1:
            bad.append(f"row {i}: the toggle bar wraps onto {bar['lines']} lines")
        if not bar["inside"]:
            bad.append(f"row {i}: a toggle sticks out of its row")
        if touch and (bar["minH"] < 44 or bar["minW"] < 40):
            bad.append(f"row {i}: under a finger a toggle is only {bar['minW']}x{bar['minH']} px")
    if editor:
        if not m["handles"]:
            bad.append("the editor opened with no handles")
        for h in m["handles"]:
            if h["w"] < 44 or h["h"] < 44:
                bad.append(f"an editor handle is {h['w']}x{h['h']} px, under 44 x 44")
    for b in bad:
        failures.append(f"{name}: {b}")
    return bad


async def run(out_dir: Path = OUT_DIR) -> int:
    if websockets is None:
        print("SKIP: the `websockets` package is not installed in this interpreter")
        return 0
    if not (HARNESS_DIST / "homedrops.html").is_file():
        print("SKIP: harness-dist/homedrops.html is not built — run "
              "`cd spectra/web && npx vite build --config vite.harness.config.ts`")
        return 0
    chrome = find_chrome()
    if chrome is None:
        print("SKIP: no Chromium found")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    httpd = serve(HARNESS_DIST, free_port())
    base = f"http://127.0.0.1:{httpd.server_address[1]}/spectra/homedrops.html"
    port = free_port()
    profile = f"/tmp/spectra-home-drops-{port}"
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
            for width, touch, kiosk in CASES:
                case = _tag(width, touch, kiosk)
                await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": KIOSK_HEIGHT if kiosk else 1000,
                    "deviceScaleFactor": 1, "mobile": width < 600})
                await cdp(ws, nid, "Emulation.setTouchEmulationEnabled",
                          {"enabled": touch, "maxTouchPoints": 5 if touch else 1})
                if not await goto(ws, nid, base + ("?kiosk=1" if kiosk else ""), READY):
                    failures.append(f"{case}: the page never finished loading")
                    continue
                await asyncio.sleep(0.6)
                for editor in (False, True):
                    if editor:
                        await evaluate(ws, nid, OPEN_EDITOR)
                        await asyncio.sleep(0.6)
                    m = await evaluate(ws, nid, MEASURE)
                    bad = _check(width, m, failures, editor, touch, kiosk)
                    tag = f"{case}{'-editor' if editor else ''}"
                    await shoot(ws, nid, out_dir / f"home-drops-{tag}.png")
                    bars = m["bars"]
                    print(f"  {'✗' if bad else '✓'} {tag}: page {m['page']}, cards "
                          f"{[(c['l'], c['t'], c['w']) for c in m['cards']]}, bars "
                          f"{[b['lines'] for b in bars]} line(s), toggle "
                          f"{min((b['minW'] for b in bars), default=0)}x"
                          f"{min((b['minH'] for b in bars), default=0)} px"
                          + (f", handles {[(h['w'], h['h']) for h in m['handles']]}" if editor else ""))
                errs = await evaluate(ws, nid, "window.__dropsErrors")
                if errs:
                    failures.append(f"{case}: page errors {errs}")
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
    print(f"\nwrote {out_dir}/")
    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    sys.exit(asyncio.run(run(ap.parse_args().out)))
