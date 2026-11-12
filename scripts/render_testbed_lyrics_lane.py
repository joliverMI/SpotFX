#!/usr/bin/env python3
"""Look at the test bed's Sung words lane in a real browser.

Renders `spectra/web/harness/testbedlyrics.html` — the REAL /testbed page
against a mocked backend — in a headless Chromium at 1440, 1180 and 390 px,
writes screenshots to docs/evidence/testbed-lyrics/, and FAILS on what a
screenshot can hide:

  - a page that scrolls sideways, or a JavaScript error;
  - printed words that overlap each other or run out of the lane;
  - a word and a flare with the same time not sharing an x;
  - a flagged song still drawing the guide lines or his two rows;
  - a song with no words, or stale ones, not saying so;
  - the roll (2026-11-12): the playing song not saying which play its plan
    is for, a chip without its chance, a word sitting out not looking it,
    "Keep this roll" not keeping it, or the Always / Chance / Never control
    not answering.

Never touches a live service: the harness is served from the built
`harness-dist` by a plain static server on a spare port.

    cd spectra/web && npx vite build --config vite.harness.config.ts
    .venv/bin/python scripts/render_testbed_lyrics_lane.py [--no-shots]
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

OUT_DIR = REPO / "docs" / "evidence" / "testbed-lyrics"
WIDTHS = (1440, 1180, 390)
KEEP_SHOTS = {"whole-song-1440", "zoomed-30s-1440", "zoomed-8s-1440", "flagged-1440", "zoomed-30s-390",
              "matches-1440", "matches-390", "roll-1440", "roll-390"}

ERROR_TRAP = """
window.__pageErrors = [];
window.addEventListener('error', (e) => window.__pageErrors.push(String(e.message || e)));
window.addEventListener('unhandledrejection', (e) => window.__pageErrors.push('rejection: ' + String(e.reason)));
const _ce = console.error.bind(console);
console.error = (...a) => { window.__pageErrors.push(a.map(String).join(' ')); _ce(...a); };
"""

READY = "!!document.querySelector('.testbed-song-search-row')"

# Tick "Only songs with sung words" (which also picks the Sung words engine).
PICK_ENGINE = """(() => {
  const box = [...document.querySelectorAll('label')]
    .find((l) => /Only songs with sung words/.test(l.textContent || ''))?.querySelector('input');
  if (box && !box.checked) box.click();
  return !!box;
})()"""


def pick_song(title: str) -> str:
    return f"""(() => {{
  const b = [...document.querySelectorAll('button')].find((x) => (x.textContent || '').startsWith({title!r}));
  if (b) b.click();
  return !!b;
}})()"""


def zoom(label: str) -> str:
    return f"""(() => {{
  const b = [...document.querySelectorAll('.testbed-zoom-row button')].find((x) => x.textContent === {label!r});
  if (b) b.click();
  return !!b;
}})()"""


def set_sensitivity(value: float) -> str:
    return f"""(() => {{
  const el = document.getElementById('testbed-emphasis-sensitivity');
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(el, {value!r});
  el.dispatchEvent(new Event('input', {{ bubbles: true }}));
  return true;
}})()"""


def set_position(ms: int) -> str:
    return f"""(() => {{
  const el = document.querySelector('.testbed-zoom-position');
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(el, {ms!r});
  el.dispatchEvent(new Event('input', {{ bubbles: true }}));
  return true;
}})()"""


LANE_FACTS = """(() => {
  const lane = document.querySelector('.testbed-lyrics-lane');
  const laneBox = lane ? lane.getBoundingClientRect() : null;
  const labels = [...document.querySelectorAll('.testbed-lyric-label')].map((el) => {
    const r = el.getBoundingClientRect();
    return { text: el.textContent, left: r.left, right: r.right, top: r.top, bottom: r.bottom };
  });
  let overlaps = 0;
  for (let i = 0; i < labels.length; i += 1) {
    for (let j = i + 1; j < labels.length; j += 1) {
      const a = labels[i]; const b = labels[j];
      if (a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom) overlaps += 1;
    }
  }
  const outsideList = laneBox ? labels.filter((l) => l.left < laneBox.left - 1 || l.right > laneBox.right + 1) : [];
  const outside = outsideList.length;
  const rows = [...document.querySelectorAll('.testbed-lane-label')].map((el) => el.textContent);
  const de = document.documentElement;
  const notes = [...document.querySelectorAll('.testbed-lyrics-group .empty-note, .testbed-lane-note .empty-note')].map((e) => e.textContent);
  return {
    hasLane: !!lane,
    marks: document.querySelectorAll('.testbed-lyric-mark').length,
    words: document.querySelectorAll('.testbed-lyric-word').length,
    guides: document.querySelectorAll('.testbed-lyric-guide').length,
    labels: labels.length, overlaps, outside,
    outsideList: outsideList.slice(0, 3).map((l) => [l.text, l.left, l.right, laneBox.left, laneBox.right]),
    caption: document.querySelector('.testbed-lyrics-flag')?.textContent ?? null,
    flagOverlapsLane: (() => {
      const f = document.querySelector('.testbed-lyrics-flag');
      if (!f || !laneBox) return false;
      const r = f.getBoundingClientRect();
      return r.bottom > laneBox.top + 0.5;
    })(),
    faintText: document.querySelectorAll('.testbed-lyric-word-text').length,
    flagged: !!document.querySelector('.testbed-lyrics-lane.flagged'),
    wordRows: rows.filter((r) => r === 'Word events').length,
    wordEvents: document.querySelectorAll('.testbed-word-event').length,
    haloed: document.querySelectorAll('.testbed-word-event.imprinted').length,
    wordedGuides: document.querySelectorAll('.testbed-lyric-guide.worded').length,
    notes,
    pageWide: de.scrollWidth > de.clientWidth + 1,
    page: de.scrollWidth + 'x' + de.clientWidth,
    count: [...document.querySelectorAll('span')].map((s) => s.textContent || '')
      .find((t) => /^\\d+ of \\d+ words$/.test(t)) ?? null,
  };
})()"""

# A flare and an emphasized word at the very same stored time.
SAME_X = """(() => {
  const marks = new Map([...document.querySelectorAll('.testbed-lyric-mark')]
    .map((el) => [el.dataset.ms, el]));
  for (const guide of document.querySelectorAll('.testbed-lyric-guide.flare')) {
    const mark = marks.get(guide.dataset.ms);
    if (!mark) continue;
    const m = mark.getBoundingClientRect();
    return { mark: m.left + m.width / 2, guide: guide.getBoundingClientRect().left, ms: guide.dataset.ms };
  }
  return { mark: null, guide: null, ms: null };
})()"""


MATCH_FACTS = """(() => {
  const chips = [...document.querySelectorAll('.testbed-match:not(.tick)')];
  const first = chips[0];
  let offset = null;
  if (first) {
    const left = first.getBoundingClientRect().left;
    const word = (first.querySelector('.testbed-match-text')?.textContent ?? '').split(' ')[0];
    const ticks = [...document.querySelectorAll('.testbed-lyric-word')]
      .filter((el) => el.title === word);
    if (ticks.length) offset = Math.min(...ticks.map((t) => Math.abs(t.getBoundingClientRect().left - left)));
  }
  return {
    chips: chips.length,
    guesses: document.querySelectorAll('.testbed-match.claude:not(.tick)').length,
    his: document.querySelectorAll('.testbed-match.his:not(.tick)').length,
    offset,
    status: document.querySelector('.testbed-match-status')?.textContent ?? null,
  };
})()"""

PANEL_TEXT = "document.querySelector('.testbed-match-panel')?.textContent ?? ''"

# THE ROLL: which play the Word actions are for, the chance on each chip,
# a word sitting out this play, and the selected word's panel.
ROLL_FACTS = """(() => {
  const chips = [...document.querySelectorAll('.testbed-word-action:not(.tick)')];
  const panels = [...document.querySelectorAll('.testbed-match-panel')];
  const panel = panels[panels.length - 1];
  const pressed = [...document.querySelectorAll('.testbed-pin button[aria-pressed="true"]')]
    .map((b) => b.textContent);
  const de = document.documentElement;
  return {
    line: document.querySelector('.testbed-roll')?.textContent ?? null,
    chips: chips.map((c) => c.textContent),
    // a crowded lane draws a word as a bare tick: its phrase is in its title
    satOut: [...document.querySelectorAll('.testbed-word-action.sat-out')]
      .map((c) => c.textContent || (c.title || '').split(' · ')[1]),
    satOutStyle: (() => {
      const c = document.querySelector('.testbed-word-action.sat-out');
      return c ? getComputedStyle(c).borderTopStyle : null;
    })(),
    panel: panel?.textContent ?? '',
    pins: document.querySelectorAll('.testbed-pin').length,
    pressed,
    pageWide: de.scrollWidth > de.clientWidth + 1,
  };
})()"""

click_sat_out = ("(() => { const c = document.querySelector('.testbed-word-action.sat-out'); "
                 "if (c) c.click(); return !!c; })()")


def press_pin(label_start: str) -> str:
    return f"""(() => {{
  const panels = [...document.querySelectorAll('.testbed-match-panel')];
  const b = [...panels[panels.length - 1].querySelectorAll('.testbed-pin button')]
    .find((x) => (x.textContent || '').startsWith({label_start!r}));
  if (b) b.click();
  return !!b;
}})()"""


SLOT_CLIP = """(() => {
  const group = document.querySelector('.testbed-lyrics-group');
  if (!group) return null;
  group.scrollIntoView({ block: 'start' });
  const r = group.getBoundingClientRect();
  // a screenshot clip is in page coordinates, not the viewport's
  return { x: Math.max(0, r.left + window.scrollX - 8), y: Math.max(0, r.top + window.scrollY - 8),
           width: Math.min(r.width + 16, document.documentElement.clientWidth), height: r.height + 16 };
})()"""

click_chip = "(() => { document.querySelector('.testbed-match:not(.tick)').click(); return true; })()"


def press(label: str) -> str:
    return f"""(() => {{
  const b = [...document.querySelectorAll('.testbed-match-section button')].find((x) => x.textContent === {label!r});
  if (b) b.click();
  return !!b;
}})()"""


def pick_words(first: int, last: int) -> str:
    return f"""(() => {{
  const words = [...document.querySelectorAll('.testbed-match-words button')];
  words[{first}].click();
  return new Promise((done) => setTimeout(() => {{ document.querySelectorAll('.testbed-match-words button')[{last}].click(); done(true); }}, 100));
}})()"""


def pick_target(name: str) -> str:
    return f"""(() => {{
  document.querySelector('.testbed-match-add input').dispatchEvent(new FocusEvent('focusin', {{ bubbles: true }}));
  return new Promise((done) => setTimeout(() => {{
    const option = [...document.querySelectorAll('.testbed-match-add div')].find((d) => d.textContent === 'Effect' + {name!r});
    if (option) option.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true }}));
    done(!!option);
  }}, 150));
}})()"""


async def run() -> int:
    shots = "--no-shots" not in sys.argv
    if websockets is None:
        print("SKIP: the `websockets` package is not installed in this interpreter")
        return 0
    if not (HARNESS_DIST / "testbedlyrics.html").is_file():
        print("SKIP: harness-dist/testbedlyrics.html is not built — run "
              "`cd spectra/web && npx vite build --config vite.harness.config.ts`")
        return 0
    chrome = find_chrome()
    if chrome is None:
        print("SKIP: no Chromium found")
        return 0
    if shots:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
    httpd = serve(HARNESS_DIST, free_port())
    base = f"http://127.0.0.1:{httpd.server_address[1]}/spectra/testbedlyrics.html"
    port = free_port()
    profile = f"/tmp/spectra-lyrics-render-{port}"
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

            async def ev(js: str):
                return await evaluate(ws, nid, js)

            async def settle() -> None:
                await asyncio.sleep(0.5)

            def check(name: str, cond: bool, detail: str = "") -> None:
                print(f"  {'✓' if cond else '✗'} {name}{(' — ' + detail) if detail else ''}")
                if not cond:
                    failures.append(f"{name} {detail}".strip())

            await cdp(ws, nid, "Page.enable")
            await cdp(ws, nid, "Runtime.enable")
            await cdp(ws, nid, "Page.addScriptToEvaluateOnNewDocument", {"source": ERROR_TRAP})

            async def shot(name: str) -> None:
                if shots and name in KEEP_SHOTS:
                    await shoot(ws, nid, OUT_DIR / f"{name}.png")

            for width in WIDTHS:
                print(f"\n{width}px")
                await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": 1000, "deviceScaleFactor": 1, "mobile": width < 600})
                if not await goto(ws, nid, base, READY):
                    failures.append(f"{width}: the page never loaded")
                    continue
                await settle()
                check("the song list has the sung-words filter", await ev(PICK_ENGINE))
                await settle()
                await ev(pick_song("A clean capture"))
                await settle()

                whole = await ev(LANE_FACTS)
                check("the lane is drawn", whole["hasLane"])
                check("every word is drawn faintly", whole["words"] > 100, f"{whole['words']} words")
                check("emphasized words are marked", whole["marks"] > 0, f"{whole['marks']} marks")
                check("the word events are guide lines through the lane", whole["guides"] == 3,
                      f"{whole['guides']} guides")
                check("the Word events row sits under it", whole["wordRows"] == 1)
                check("it draws the events a word reaches and the words firing alone",
                      whole["wordEvents"] == 3, f"{whole['wordEvents']} events")
                check("an event a word gives its colour to is haloed, on the row and in the lane",
                      whole["haloed"] == 1 and whole["wordedGuides"] == 2,
                      f"{whole['haloed']} haloed, {whole['wordedGuides']} worded guides")
                check("no printed word overlaps another", whole["overlaps"] == 0)
                check("no printed word leaves the lane", whole["outside"] == 0, str(whole.get("outsideList")))
                check("it does not scroll sideways", not whole["pageWide"], whole["page"])
                check("it says how many words it picked", bool(whole["count"]), str(whole["count"]))
                await shot(f"whole-song-{width}")

                await ev(zoom("30 s"))
                await settle()
                zoomed = await ev(LANE_FACTS)
                check("zooming prints a larger share of the marks it shows",
                      zoomed["marks"] > 0
                      and zoomed["labels"] / zoomed["marks"] >= whole["labels"] / whole["marks"],
                      f"{zoomed['labels']} of {zoomed['marks']}, was {whole['labels']} of {whole['marks']}")
                check("still no overlap when zoomed", zoomed["overlaps"] == 0)
                check("still inside the lane when zoomed", zoomed["outside"] == 0)
                same = await ev(SAME_X)
                check("a word and a flare at the same time share an x",
                      same["mark"] is not None and abs(same["mark"] - same["guide"]) <= 1.5,
                      f"mark {same['mark']} guide {same['guide']}")
                await shot(f"zoomed-30s-{width}")

                # The Word matches row (lyrics plan step 3).
                await ev(set_position(0))
                await settle()
                row = await ev(MATCH_FACTS)
                check("the Word matches row shows the guesses", row["chips"] >= 1, str(row))
                check("guesses are drawn as guesses", row["guesses"] == row["chips"], str(row))
                check("a chip sits under its first word", row["offset"] is not None and row["offset"] <= 1.5,
                      f"{row['offset']} px")
                check("a reading says what state it is in", "guess" in (row["status"] or ""), str(row["status"]))
                # the sentence PR #504 gave the row ("They reach your lights only on
                # a show you turn on below") — the check had kept step 3's wording
                check("it says it reaches nothing by itself",
                      "reach your lights only on a show" in (row["status"] or ""), str(row["status"]))
                await ev(click_chip)
                await settle()
                panel = await ev(PANEL_TEXT)
                check("selecting a match says what it is and why", "Claude" in panel and "names the colour" in panel, panel)
                check("and who it would reach", "Blood Red" in panel, panel)
                before_matches = row["chips"]
                await ev(press("Delete this match"))
                await settle()
                after = await ev(MATCH_FACTS)
                check("deleting takes it off the timeline", after["chips"] == before_matches - 1, str(after))
                check("and it can be brought back", "Bring back 1 deleted" in (after["status"] or ""), str(after["status"]))

                await ev(press("+ Add a match"))
                await settle()
                await ev(pick_words(0, 1))
                await settle()
                picked = await ev(PANEL_TEXT)
                check("two taps pick a phrase", "means" in picked, picked)
                await ev(pick_target("Fish"))
                await settle()
                await ev(press("Add"))
                await settle()
                added = await ev(MATCH_FACTS)
                check("an added match is drawn as his", added["his"] == 1, str(added))
                await shot(f"matches-{width}")
                errs = await ev("window.__pageErrors")
                check("no page errors in the matches", not errs, str(errs))

                # THE ROLL (2026-11-12): this play's words, each with its chance.
                await ev(zoom("Whole song"))
                await settle()
                roll = await ev(ROLL_FACTS)
                check("the playing song says which play its plan is for",
                      (roll["line"] or "").startswith("This play #") and "3 of 4 words play" in roll["line"],
                      str(roll["line"]))
                check("a chip carries its chance", any(c.endswith("· 91%") for c in roll["chips"]),
                      str(roll["chips"]))
                check("a word sitting out this play is drawn quieter, dotted",
                      roll["satOut"] in (["dull · 35%"], ["dull"]) and roll["satOutStyle"] == "dotted",
                      f"{roll['satOut']} {roll['satOutStyle']}")
                await ev(click_sat_out)
                await settle()
                picked = await ev(ROLL_FACTS)
                check("selecting it says it sits out, and how often it plays",
                      "Sits out this play" in picked["panel"] and "35% of plays" in picked["panel"],
                      picked["panel"])
                check("its panel offers Always / Chance / Never, on Chance",
                      picked["pressed"] == ["Chance 35%"], str(picked["pressed"]))
                check("the roll adds nothing that scrolls sideways", not picked["pageWide"])
                if shots and f"roll-{width}" in KEEP_SHOTS:
                    clip = await ev(SLOT_CLIP)
                    await settle()
                    clip = await ev(SLOT_CLIP)
                    await shoot(ws, nid, OUT_DIR / f"roll-{width}.png", clip=clip)
                await ev(press("Keep this roll"))
                await settle()
                kept = await ev(ROLL_FACTS)
                check("Keep this roll keeps it, says so, and offers to let it go",
                      "your kept roll #3a7f" in (kept["line"] or "")
                      and "Let it roll again" in (kept["line"] or "")
                      and "Keep this roll" not in (kept["line"] or ""), str(kept["line"]))
                await ev(press_pin("Always"))
                await settle()
                pinned = await ev(ROLL_FACTS)
                check("pinning it Always takes", "Always" in pinned["pressed"], str(pinned["pressed"]))
                await ev(press_pin("Chance"))
                await settle()
                await ev(press("Let it roll again"))
                await settle()
                errs = await ev("window.__pageErrors")
                check("no page errors in the roll", not errs, str(errs))

                await ev(zoom("8 s"))
                await settle()
                await ev(set_position(20000))
                await settle()
                close = await ev(LANE_FACTS)
                await shot(f"zoomed-8s-{width}")
                check("zoomed right in, the faint words are readable", close["faintText"] > 0,
                      f"{close['faintText']} of {close['words']} words printed")
                await ev(zoom("30 s"))
                await settle()

                before = zoomed["marks"]
                await ev(set_sensitivity(0.45))
                await settle()
                fewer = await ev(LANE_FACTS)
                check("lowering the sensitivity picks fewer words",
                      fewer["marks"] < before, f"{before} -> {fewer['marks']}")
                await ev(set_sensitivity(0.6))
                await settle()

                await ev(zoom("Whole song"))
                await settle()
                await ev(pick_song("A capture that slips"))
                await settle()
                flagged = await ev(LANE_FACTS)
                check("a slipping capture is flagged across the lane",
                      flagged["flagged"] and "cannot be compared" in (flagged["caption"] or ""))
                check("the warning sits clear of the printed words", not flagged["flagOverlapsLane"])
                check("its words are still drawn", flagged["words"] > 100)
                check("no guide lines on a flagged song", flagged["guides"] == 0)
                check("the Word events row is withheld", flagged["wordRows"] == 0)
                await shot(f"flagged-{width}")

                await ev(pick_song("Captured again since"))
                await settle()
                stale = await ev(LANE_FACTS)
                check("a stale song says why and draws nothing",
                      not stale["hasLane"] and any("captured again" in n for n in stale["notes"]),
                      str(stale["notes"]))

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
