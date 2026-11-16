#!/usr/bin/env python3
"""Look at the Scenes page's WORDS tab, and its preview, in a real browser.

Word Shapes row W2.1. Renders `spectra/web/harness/wordstab.html` — the REAL
response editor and the REAL flare-preview overlay against a mocked backend
(see that harness's own docstring) — at 1440, 820 and 390 px, writes
screenshots to docs/evidence/words-tab/, and FAILS on what a screenshot
hides:

  * the three spans are drawn in his words and in order — forms, holds,
    releases — and the "forms" span ENDS EXACTLY ON the word's own mark,
    which is the whole claim of the row ("the shape completes ON the word");
  * their widths carry the room's real envelope (hold = 1.6x the form,
    release = 1.5x it, on the plan's defaults at full Energy);
  * the trigger mark reads "the word" and is NOT draggable here;
  * the picker's options are the shape LIBRARY's three, heart preselected,
    and pressing one re-opens the timeline AND carries that shape into the
    live fire (never the server's default);
  * adding the Words section really declares a Word Shape kind and attaches
    it, and the save's advisory note draws on that kind's own card;
  * no sideways scroll at any width, and no page error anywhere.

Never touches a live service: the harness is served from the built
`harness-dist` by a plain static server on a spare port, and its `fetch` is
mocked, so nothing reaches SPECTRA, LedFX, a fixture or a light.

    cd spectra/web && npx vite build --config vite.harness.config.ts
    .venv/bin/python scripts/render_words_tab.py [--no-shots]
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

OUT_DIR = REPO / "docs" / "evidence" / "words-tab"
WIDTHS = (1440, 820, 390)

ERROR_TRAP = """
window.__pageErrors = [];
window.addEventListener('error', (e) => window.__pageErrors.push(String(e.message || e)));
window.addEventListener('unhandledrejection', (e) => window.__pageErrors.push('rejection: ' + String(e.reason)));
const _ce = console.error.bind(console);
console.error = (...a) => { window.__pageErrors.push(a.map(String).join(' ')); _ce(...a); };
"""

READY = "!!document.querySelector('.card-title')"

TAB_FACTS = """(() => {
  const de = document.documentElement;
  // innerText is the RENDERED text, and .card-title is uppercased by CSS —
  // so every word match here is case-insensitive on purpose.
  const text = document.body.innerText;
  const low = text.toLowerCase();
  const buttons = [...document.querySelectorAll('button')].map((b) => b.textContent.trim());
  return {
    title: (document.querySelector('.card-title') || {}).textContent || '',
    hasWordsHeading: low.includes('words'),
    hint: low.includes('a sung word that reaches a shape fires this section'),
    addSection: buttons.filter((b) => b.includes('respond to words')).length,
    addKind: buttons.filter((b) => b.includes('+ Word Shape kind')).length,
    previewButtons: buttons.filter((b) => b === '▶ Preview').length,
    glyphs: (text.match(/💟/g) || []).length,
    laneMembers: [...document.querySelectorAll('[data-lane]')].length,
    bandRange: (text.match(/\\[0\\.00–1\\.00\\)/) || [''])[0],
    notes: [...document.querySelectorAll('div')].map((d) => d.textContent)
      .filter((t) => t && t.startsWith('ⓘ ')).length,
    pageWide: de.scrollWidth > de.clientWidth + 1,
    page: de.scrollWidth + 'x' + de.clientWidth,
  };
})()"""

OPEN_PREVIEW = """(() => {
  const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === '▶ Preview');
  if (!b) return false;
  b.click();
  return true;
})()"""

ADD_SECTION = """(() => {
  const b = [...document.querySelectorAll('button')].find((x) => x.textContent.includes('respond to words'));
  if (!b) return false;
  b.click();
  return true;
})()"""

# Everything the ruler draws, measured in SCREEN pixels so the geometry claim
# is about what he actually sees, not about attributes.
RULER = """(() => {
  const card = [...document.querySelectorAll('.card')].find(
    (c) => c.querySelector('.card-title')
      && c.querySelector('.card-title').textContent.includes('Preview —'));
  if (!card) return { open: false };
  const svg = card.querySelector('svg');
  if (!svg) return { open: true, ruler: false, text: card.innerText };
  const labels = [...svg.querySelectorAll('text')]
    .map((t) => ({ t: t.textContent.trim(), x: t.getBoundingClientRect().left }));
  const spanLabels = labels.filter((o) => ['forms', 'holds', 'releases'].includes(o.t))
    .sort((a, z) => a.x - z.x).map((o) => o.t);
  const trigLine = svg.querySelector('line[stroke="#ff5a3c"]');
  const trig = trigLine ? trigLine.getBoundingClientRect() : null;
  // The three spans are the accent rects; the ruler's own background is
  // panel-coloured, and for this kind type no animation-span rect is drawn.
  const spans = [...svg.querySelectorAll('rect[fill="var(--accent)"]')]
    .map((r) => r.getBoundingClientRect())
    .filter((r) => r.width > 0)
    .sort((a, z) => a.left - z.left)
    .map((r) => ({ left: r.left, right: r.right, width: r.width }));
  const picker = [...card.querySelectorAll('button')]
    .filter((b) => ['Heart', 'Star', 'Diamond'].includes(b.textContent.trim()))
    .map((b) => ({ name: b.textContent.trim(), on: b.classList.contains('primary') }));
  return {
    open: true, ruler: true,
    spanLabels,
    spans,
    triggerCenter: trig ? trig.left + trig.width / 2 : null,
    triggerLabel: (labels.find((o) => o.t === 'the word') || {}).t || '',
    hasTriggerWord: labels.some((o) => o.t === 'the word'),
    hasOldTrigger: labels.some((o) => o.t === 'trigger'),
    picker,
    draggable: !!(trigLine && getComputedStyle(trigLine.parentElement).cursor === 'ew-resize'),
    text: card.innerText,
  };
})()"""

PICK = """(() => {
  const card = [...document.querySelectorAll('.card')].find(
    (c) => c.querySelector('.card-title')
      && c.querySelector('.card-title').textContent.includes('Preview —'));
  const b = [...card.querySelectorAll('button')].find((x) => x.textContent.trim() === '%s');
  if (!b) return false;
  b.click();
  return true;
})()"""


async def run() -> int:  # noqa: C901, PLR0912, PLR0915
    shots = "--no-shots" not in sys.argv
    if websockets is None:
        print("SKIP: the `websockets` package is not installed in this interpreter")
        return 0
    if not (HARNESS_DIST / "wordstab.html").is_file():
        print("SKIP: harness-dist/wordstab.html is not built — run "
              "`cd spectra/web && npx vite build --config vite.harness.config.ts`")
        return 0
    chrome = find_chrome()
    if chrome is None:
        print("SKIP: no Chromium found")
        return 0
    if shots:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
    httpd = serve(HARNESS_DIST, free_port())
    base = f"http://127.0.0.1:{httpd.server_address[1]}/spectra/wordstab.html"
    port = free_port()
    profile = f"/tmp/spectra-words-tab-{port}"
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
                    "width": width, "height": 1000, "deviceScaleFactor": 1,
                    "mobile": width < 600})

                # ── the tab, as W2.5's data script leaves it ──────────────
                if not await goto(ws, nid, base, READY):
                    failures.append(f"{width}: the page never loaded")
                    continue
                await asyncio.sleep(0.4)
                facts = await ev(TAB_FACTS)
                check("the Words section is there", facts["hasWordsHeading"])
                check("and says a sung word is the only thing that fires it", facts["hint"])
                check("the Word Shape kind draws its glyph", facts["glyphs"] >= 1,
                      str(facts["glyphs"]))
                check("the band covers the whole Energy range",
                      facts["bandRange"] == "[0.00–1.00)", facts["bandRange"])
                check("its lanes are drawn", facts["laneMembers"] > 0, str(facts["laneMembers"]))
                check("a kind can be previewed", facts["previewButtons"] >= 1,
                      str(facts["previewButtons"]))
                check("another Word Shape kind can be declared", facts["addKind"] == 1,
                      str(facts["addKind"]))
                check("it does not scroll sideways", not facts["pageWide"], facts["page"])
                if shots:
                    await shoot(ws, nid, OUT_DIR / f"words-tab-{width}.png")

                # ── the preview: the picker and the three marks ───────────
                check("the Preview button opens", await ev(OPEN_PREVIEW) is True)
                await asyncio.sleep(0.9)
                r = await ev(RULER)
                check("the overlay is open", bool(r.get("open") and r.get("ruler")),
                      "" if r.get("ruler") else str({k: v for k, v in r.items() if k != "text"})[:160])
                if not r.get("ruler"):
                    continue
                check("the picker offers the shape library's three, heart on",
                      [p["name"] for p in r["picker"]] == ["Heart", "Star", "Diamond"]
                      and [p["on"] for p in r["picker"]] == [True, False, False],
                      str(r["picker"]))
                check("the ruler is drawn in his words, in order",
                      r["spanLabels"] == ["forms", "holds", "releases"], str(r["spanLabels"]))
                check("the trigger mark reads 'the word', not 'trigger'",
                      r["hasTriggerWord"] and not r["hasOldTrigger"],
                      f"{r['triggerLabel']!r}")
                check("and it does not drag here", not r["draggable"])
                spans = r["spans"]
                check("three spans, drawn edge to edge", len(spans) == 3
                      and abs(spans[0]["right"] - spans[1]["left"]) < 1.5
                      and abs(spans[1]["right"] - spans[2]["left"]) < 1.5, str(spans))
                if len(spans) == 3:
                    gap = abs(spans[0]["right"] - r["triggerCenter"])
                    check("THE FORM ENDS ON THE WORD", gap < 1.5, f"{gap:.2f}px")
                    hold_ratio = spans[1]["width"] / spans[0]["width"]
                    rel_ratio = spans[2]["width"] / spans[0]["width"]
                    check("the hold is the room's own 0.8 s against a 0.5 s form",
                          abs(hold_ratio - 1.6) < 0.08, f"x{hold_ratio:.2f}")
                    check("and the release is 1.5x the form",
                          abs(rel_ratio - 1.5) < 0.08, f"x{rel_ratio:.2f}")
                check("it says the forming time IS the lead",
                      "forms over 500 ms" in r["text"] and "IS the" in r["text"],
                      "forms over 500 ms" if "forms over 500 ms" in r["text"] else "missing")
                check("and that a Words band ignores a per-kind offset",
                      "does not drag" in r["text"])
                opens = await ev("window.__harness.opens")
                check("the timeline was asked for heart", opens[-1]["shape"] == "heart",
                      str(opens[-1]))
                if shots:
                    await shoot(ws, nid, OUT_DIR / f"preview-heart-{width}.png")

                # ── picking a shape re-opens AND reaches the live fire ────
                check("Star can be picked", await ev(PICK % "Star") is True)
                # The loop fires when the playhead reaches the form's start,
                # 1.5 s into a 6 s lap, and a pick restarts the playhead at
                # 0 — exactly as a fresh open does. Wait for the real thing
                # rather than asserting a fire that has not happened yet.
                await asyncio.sleep(2.6)
                opens = await ev("window.__harness.opens")
                check("the timeline re-opened for star", opens[-1]["shape"] == "star",
                      str(opens[-1]))
                r2 = await ev(RULER)
                check("and the picker now shows Star on",
                      [p["on"] for p in r2["picker"]] == [False, True, False],
                      str(r2["picker"]))
                check("the sentence names the shape it is drawing",
                      "The Star forms" in r2["text"],
                      "The Star forms" if "The Star forms" in r2["text"] else "missing")
                fires = await ev("window.__harness.fires")
                check("the live fire carries the picked shape, not the default",
                      bool(fires) and fires[-1]["shape"] == "star",
                      str(fires[-1] if fires else None))
                if shots:
                    await shoot(ws, nid, OUT_DIR / f"preview-star-{width}.png")

                # ── the save's advisory note, on the kind it names ────────
                if not await goto(ws, nid, f"{base}?warn=1", READY):
                    failures.append(f"{width}: the warning page never loaded")
                    continue
                await asyncio.sleep(0.4)
                warned = await ev(TAB_FACTS)
                check("the save's note draws on the card, not as an error",
                      warned["notes"] == 1, str(warned["notes"]))
                if shots and width == WIDTHS[0]:
                    await shoot(ws, nid, OUT_DIR / "words-tab-warning.png")

                # ── a scene with no Words section ─────────────────────────
                if not await goto(ws, nid, f"{base}?bare=1", READY):
                    failures.append(f"{width}: the bare page never loaded")
                    continue
                await asyncio.sleep(0.4)
                bare = await ev(TAB_FACTS)
                check("a scene with no Words section offers to add one",
                      bare["addSection"] == 1 and bare["previewButtons"] == 0,
                      str(bare["addSection"]))
                if shots and width == WIDTHS[0]:
                    await shoot(ws, nid, OUT_DIR / "words-tab-empty.png")
                check("adding it works", await ev(ADD_SECTION) is True)
                await asyncio.sleep(0.4)
                added = await ev(TAB_FACTS)
                check("and it arrives with a Word Shape kind on a full-range band",
                      added["glyphs"] >= 1 and added["bandRange"] == "[0.00–1.00)"
                      and added["previewButtons"] == 1,
                      f"{added['glyphs']} {added['bandRange']!r} {added['previewButtons']}")

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
