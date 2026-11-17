#!/usr/bin/env python3
"""Look at the Sung labels page in a real browser.

Renders `spectra/web/harness/sunglabels.html` — the REAL page against a mocked
backend — at 1440, 820 and 390 px, writes screenshots to docs/evidence/
sung-labels/, and FAILS on what a screenshot can hide: a page that scrolls
sideways, a JavaScript error, a chip that will not come off, a word that will
not add, drafting that does not go a batch at a time.

Never touches a live service: the harness is served from the built
`harness-dist` by a plain static server on a spare port.

    cd spectra/web && npx vite build --config vite.harness.config.ts
    .venv/bin/python scripts/render_sung_labels.py [--no-shots]
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
    HARNESS_DIST, REPO, cdp, evaluate, find_chrome, free_port, goto, harness_stale, serve,
    shoot, wait_for_devtools, websockets,
)

OUT_DIR = REPO / "docs" / "evidence" / "sung-labels"
WIDTHS = (1440, 820, 390)

ERROR_TRAP = """
window.__pageErrors = [];
window.addEventListener('error', (e) => window.__pageErrors.push(String(e.message || e)));
window.addEventListener('unhandledrejection', (e) => window.__pageErrors.push('rejection: ' + String(e.reason)));
const _ce = console.error.bind(console);
console.error = (...a) => { window.__pageErrors.push(a.map(String).join(' ')); _ce(...a); };
"""

READY = "!!document.querySelector('.sung-card')"

FACTS = """(() => {
  const de = document.documentElement;
  const cards = [...document.querySelectorAll('.sung-card')];
  return {
    cards: cards.length,
    seed: document.querySelectorAll('.sung-card .sung-chip.seed').length,
    claude: document.querySelectorAll('.sung-card .sung-chip.claude').length,
    his: document.querySelectorAll('.sung-card .sung-chip.his').length,
    pageWide: de.scrollWidth > de.clientWidth + 1,
    page: de.scrollWidth + 'x' + de.clientWidth,
    chipsOutside: cards.flatMap((c) => {
      const box = c.getBoundingClientRect();
      return [...c.querySelectorAll('.sung-chip')].filter((x) => x.getBoundingClientRect().right > box.right + 1);
    }).length,
    draftButton: [...document.querySelectorAll('.sung-toolbar button')].map((b) => b.textContent)[0],
    heads: [...document.querySelectorAll('.sung-heading')].map((h) => h.textContent),
    glyphs: [...document.querySelectorAll('.sung-glyph')].map((g) => g.textContent).join(''),
    notes: [...document.querySelectorAll('.sung-note')].map((n) => n.textContent),
    heartWords: (() => {
      const card = [...document.querySelectorAll('.sung-card')]
        .find((c) => c.querySelector('strong') && c.querySelector('strong').textContent === 'Heart');
      return card ? card.querySelector('.sung-chips').textContent : '';
    })(),
    labels: [...document.querySelectorAll('.sung-card')][0]
      ? [...document.querySelectorAll('.sung-card')][0].querySelector('.sung-chips').textContent : '',
  };
})()"""

REMOVE_CHERRY = """(() => {
  const chip = [...document.querySelectorAll('.sung-chip')].find((c) => c.firstChild.textContent === 'cherry');
  chip.querySelector('button').click();
  return true;
})()"""

HEART_CARD = """[...document.querySelectorAll('.sung-card')].find(
  (c) => c.querySelector('strong') && c.querySelector('strong').textContent === 'Heart')"""

# The row's own acceptance: a word added to the Heart and a seed word taken off
# it both outlast the page reading the list again.
EDIT_HEART = """(() => {
  const card = %s;
  const kiss = [...card.querySelectorAll('.sung-chip')].find((c) => c.firstChild.textContent === 'kiss');
  kiss.querySelector('button').click();
  const input = card.querySelector('.sung-add');
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(input, 'sweetheart');
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  return true;
})()""" % HEART_CARD

SEARCH_LOVE = """(() => {
  const box = document.querySelector('.sung-toolbar input');
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(box, 'love');
  box.dispatchEvent(new Event('input', { bubbles: true }));
  return true;
})()"""

ADD_WORD = """(() => {
  const input = document.querySelector('.sung-card .sung-add');
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(input, 'passion');
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  return true;
})()"""

PRESS_DRAFT = "(() => { document.querySelector('.sung-toolbar button').click(); return true; })()"
PRESS_POWER = "(() => { document.querySelector('.sung-auto button[role=switch]').click(); return true; })()"
DRAFTED = "window.__harness.drafted"
AUTO_READ = "window.__harness.auto_read"


async def run() -> int:
    shots = "--no-shots" not in sys.argv
    if websockets is None:
        print("SKIP: the `websockets` package is not installed in this interpreter")
        return 0
    sunglabels_html = HARNESS_DIST / "sunglabels.html"
    if not sunglabels_html.is_file():
        print("SKIP: harness-dist/sunglabels.html is not built — run "
              "`cd spectra/web && npx vite build --config vite.harness.config.ts`")
        return 0
    stale = harness_stale(
        sunglabels_html,
        REPO / "spectra/web/harness/sunglabels.tsx",
        REPO / "spectra/web/src/sunglabels",
    )
    if stale is not None:
        print(f"SKIP: stale harness bundle — rebuild (newer than harness-dist/sunglabels.html: "
              f"{stale.relative_to(REPO)}) — run "
              "`cd spectra/web && npx vite build --config vite.harness.config.ts`")
        return 0
    chrome = find_chrome()
    if chrome is None:
        print("SKIP: no Chromium found")
        return 0
    if shots:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
    httpd = serve(HARNESS_DIST, free_port())
    base = f"http://127.0.0.1:{httpd.server_address[1]}/spectra/sunglabels.html"
    port = free_port()
    profile = f"/tmp/spectra-sung-labels-{port}"
    proc = subprocess.Popen(  # noqa: S603
        [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", "--window-size=1440,1000"],
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

            async def ev(js: str):
                return await evaluate(ws, nid, js)

            def check(name: str, cond: bool, detail: str = "") -> None:
                print(f"  {'✓' if cond else '✗'} {name}{(' — ' + detail) if detail else ''}")
                if not cond:
                    failures.append(f"{name} {detail}".strip())

            await cdp(ws, nid, "Page.enable")
            await cdp(ws, nid, "Runtime.enable")
            await cdp(ws, nid, "Page.addScriptToEvaluateOnNewDocument", {"source": ERROR_TRAP})

            for width in WIDTHS:
                print(f"\n{width}px")
                await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": 1000, "deviceScaleFactor": 1, "mobile": width < 600})
                if not await goto(ws, nid, base, READY):
                    failures.append(f"{width}: the page never loaded")
                    continue
                await asyncio.sleep(0.4)
                facts = await ev(FACTS)
                check("every card is shown", facts["cards"] == 11, str(facts["cards"]))
                check("each shape draws its glyph", facts["glyphs"] == "♥★◆", facts["glyphs"])
                check("the rows are headed, shapes last",
                      [h.split(" (")[0] for h in facts["heads"]] == ["Colour sets", "Effects", "Shapes"]
                      and facts["heads"][-1].endswith("?"),   # the Shapes row's own help link
                      str(facts["heads"]))
                check("only the shape sharing a word with an effect says who wins",
                      len(facts["notes"]) == 1 and "the shape is the one the show follows" in facts["notes"][0],
                      str(facts["notes"]))
                check("chips say where they came from", facts["seed"] > 0 and facts["claude"] > 0, str(facts))
                check("it does not scroll sideways", not facts["pageWide"], facts["page"])
                check("no chip leaves its card", facts["chipsOutside"] == 0, str(facts["chipsOutside"]))
                check("it says how many are waiting", "Draft meanings for 3" in facts["draftButton"],
                      facts["draftButton"])
                if shots:
                    await shoot(ws, nid, OUT_DIR / f"page-{width}.png")

                await ev(EDIT_HEART)
                await asyncio.sleep(0.3)
                heart = await ev(FACTS)
                check("a word added to the Heart and a seed word taken off both survive the re-read",
                      "sweetheart" in heart["heartWords"] and "kiss" not in heart["heartWords"],
                      heart["heartWords"])

                await ev(SEARCH_LOVE)
                await asyncio.sleep(0.3)
                searched = await ev(FACTS)
                check("the search box filters shapes too",
                      searched["heads"][-1].startswith("Shapes (1)") and searched["glyphs"] == "♥",
                      str(searched["heads"]) + " " + searched["glyphs"])
                if shots:
                    await shoot(ws, nid, OUT_DIR / f"shapes-search-{width}.png")
                if not await goto(ws, nid, base, READY):
                    failures.append(f"{width}: the page never came back after the search")
                    continue
                await asyncio.sleep(0.4)

                await ev(REMOVE_CHERRY)
                await asyncio.sleep(0.3)
                after = await ev(FACTS)
                check("a word comes off", "cherry" not in after["labels"], after["labels"])

                await ev(ADD_WORD)
                await asyncio.sleep(0.3)
                added = await ev(FACTS)
                check("a word goes on, and is marked as his", added["his"] == 1 and "passion" in added["labels"],
                      str(added["his"]))

                await ev(PRESS_DRAFT)
                await asyncio.sleep(0.8)
                drafted = await ev(DRAFTED)
                check("drafting goes a batch at a time", drafted == [["ice", "hype"], ["night"]], str(drafted))
                final = await ev(FACTS)
                check("a drafted page offers a re-draft", "again" in final["draftButton"], final["draftButton"])
                check("the drafted words appear", final["claude"] > facts["claude"], str(final["claude"]))

                await ev(PRESS_POWER)
                await asyncio.sleep(0.3)
                check("the automatic-reading switch switches", await ev(AUTO_READ) is True)

                errs = await ev("window.__pageErrors")
                check("no page errors", not errs, str(errs))
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
    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
