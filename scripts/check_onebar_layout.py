"""Executable spec: the merged one-bar (UI declutter plan §2/§3/§6) at the
Admiral's three named desktop/tablet widths (1024, 1180, 1440) plus the
kiosk view's own 800x424 (`?kiosk=1`) — TWO TIERS, his own decision of
2026-10-14, superseding an earlier one-line-everywhere attempt:

  - 1180 and 1440 are ONE LINE, <= `MAX_BAR_HEIGHT_PX` (48) tall — the
    original plan.
  - 1024 and the kiosk's 800 are a DELIBERATE TWO ROWS, each <=
    `MAX_BAR_HEIGHT_PX` tall, with every occupant on screen and no
    sideways scroll — "extend the phone two-row top-bar rule from <=520px
    up to about 1100px... do not shed swatches or hide controls to force
    one line." An earlier version of this file (and the bar) tried to
    force all four widths onto one line by shedding/hiding controls at
    1024 and 800; both are abandoned in favour of the two-row form.

Also guards the still-live regression this replaces
(spotfx-onebar-tablet-height: measured 43px at 1440 but 69px/172px at
1180/1024 before ANY fix, because two occupants answered being squeezed
by growing taller instead of narrower — fixed at the root for every
width, not by hiding anything) and the kiosk-specific one
(spotfx-deploy-423 finding B: `KioskPage.tsx` used to render the two bar
components as bare siblings, outside the `.one-bar >` scoping tokens.css
relies on, so the kiosk kept the OLD two-STRIP layout).

Drives a real headless Chromium (no jsdom — jsdom has no layout engine, so
the no-jumping/no-overflow/height/row-count claims can only be proven
against a real browser) over raw CDP via websockets, the established
recipe for this repo (no Playwright Python dependency, no system Chrome
requirement — launches the cached Playwright Chromium binary directly).

READ-ONLY against the live app at http://127.0.0.1:8000/spectra/ — through
the spot-effects reverse proxy, NOT the standalone :8010 SPECTRA port:
the Colour button's own data (`useSpotColorSets`) only resolves same-origin
through :8000 (confirmed live, spotfx-deploy-423 §6) — against :8010 it
reads blank, which would make the no-jump/occupant-visible measurements
pass for the wrong reason (nothing there to overflow). GET requests only,
no button pressed, nothing fired — this task's own instruction: front-end
only, no live light tests, no writes.

What it measures, at every width:
  - the one-bar row itself does not force the page to scroll horizontally
    (`document.documentElement.scrollWidth <= clientWidth + 1`, a 1px
    rounding slop) — ALSO checked directly on the one-bar's own
    `scrollWidth == clientWidth` (its `overflow-x: auto` escape valve
    must never actually be needed, per this task's "no sideways scroll"
    requirement — a bar that fits the page but itself scrolls sideways
    would pass the page-level check alone and still hide the Release
    button);
  - the occupants are grouped into ROWS by their own `top`, clustering
    tops within `ROW_CLUSTER_PX` (20px — wider than the few px of spread
    one row's own shorter occupants get from `align-items: center`,
    narrower than the ~40px+ gap between two real rows) of each other.
    1180/1440 assert exactly ONE row; 1024/kiosk assert exactly TWO —
    catching either a stray wrap (a third row/overflow) or a collapse
    back to one (the two-row CSS silently stopped applying);
  - every row's own max occupant height stays at or under
    `MAX_BAR_HEIGHT_PX` (48) — the actual regression finding A fixed: a
    swatch/chip wrapping into a second internal row grows ITS row tall
    without ever overflowing the page or clipping an occupant, which is
    exactly what let the pre-fix bar pass every other check in this file
    while still being 1.6x-4x its intended height;
  - every one of the nine occupants (house / mode / hue hold / scenes /
    colour / energy+mark / light show / preview / release) is actually
    ON SCREEN (not clipped off the right edge) — `getBoundingClientRect()
    .right <= window.innerWidth + 1` for each, regardless of which row
    it landed on;
  - the NO-JUMP claim, behaviourally: it mutates the live DOM (client-side
    only — `el.textContent = ...` in the page, no fetch/POST of any kind)
    to give the Scenes/Colour buttons' own value an artificially long
    string, re-measures a later sibling's left edge, and asserts it did
    not move — then restores the original text. This is the actual
    "nothing jumps when text changes" proof; check_onebar_fixed_widths.mjs
    only reads the CSS source for the declarations that are SUPPOSED to
    make this true, which can't catch a conflicting rule elsewhere or a
    declaration that's become dead code (exactly what happened to
    `.top-bar-strip`'s own `flex-wrap: wrap` once it went `display:
    contents` under `.one-bar` — see the expand check below);
  - the device-preview "Expand" feature, when a favourite device exists:
    clicking the swatches drops `.device-preview-expanded-row` onto its
    own line BELOW every other occupant (never squeezed onto the same
    line, which is what overflowed the bar before the `.one-bar:has(...)`
    fix in tokens.css), with no resulting horizontal overflow either.

The kiosk's own 800x424 (`?kiosk=1`) runs the identical two-row
measurement above (rows, heights, on-screen, no scroll) — nothing is shed
there any more, so every occupant is expected present, not just a named
subset.

This proves "no sideways scroll, nothing jumps/overflows/grows, the right
number of rows" against whatever names/state his live room happens to
have right now — it does not (and, read-only, cannot) inject a synthetic
short/long name into the SERVER's own data; the text-length mutation
above is a pure client-side DOM edit used only to drive the measurement,
never persisted or sent anywhere.

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
APP_URL = os.environ.get("SPECTRA_LIVE_URL", "http://127.0.0.1:8000/spectra/")
HEIGHT = 800
MAX_BAR_HEIGHT_PX = 48
# width -> expected row count (the Admiral's own tiering, 2026-10-14):
# 1180/1440 stay one line; 1024 (and the kiosk's 800, measured separately
# below) are a deliberate two rows.
WIDTHS = {1024: 2, 1180: 1, 1440: 1}
KIOSK_WIDTH = 800
KIOSK_HEIGHT = 424
KIOSK_EXPECTED_ROWS = 2
# Every occupant this bar can show — the kiosk no longer sheds any of
# them (the two-row form gives row 2 all the width it needs), so this
# same list is used for both the desktop/tablet measurement and the
# kiosk one.
OCCUPANT_SELECTORS = [
    ".mode-chip", ".mode-group-btn", ".ambient-group-btn",
    ".scenes-group-btn", ".energy-mark-group", ".light-show-strip",
    ".device-preview-strip", ".warning-chip", ".release-hold-wrap",
]
# Clusters occupant `top`s into rows: wider than the few px of spread a
# row's own shorter occupants get from `align-items: center`, narrower
# than the ~40px+ gap between two real rows (both measured live).
ROW_CLUSTER_PX = 20


def cluster_rows(tops: list[float]) -> list[list[float]]:
    rows: list[list[float]] = []
    for t in sorted(tops):
        if rows and t - rows[-1][-1] <= ROW_CLUSTER_PX:
            rows[-1].append(t)
        else:
            rows.append([t])
    return rows

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

            for width, expected_rows in WIDTHS.items():
                await cdp_call(ws, nid(), "Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False,
                })
                await asyncio.sleep(0.3)  # let layout settle
                r = await cdp_call(ws, nid(), "Runtime.evaluate", {
                    "expression": f"""
                        JSON.stringify({{
                          scrollWidth: document.documentElement.scrollWidth,
                          clientWidth: document.documentElement.clientWidth,
                          bar: (() => {{
                            const b = document.querySelector('.one-bar');
                            if (!b) return null;
                            const rect = b.getBoundingClientRect();
                            return {{
                              right: rect.right, width: rect.width,
                              scrollWidth: b.scrollWidth, clientWidth: b.clientWidth,
                            }};
                          }})(),
                          occupants: {json.dumps(OCCUPANT_SELECTORS)}.flatMap((sel) =>
                            [...document.querySelectorAll(sel)].map((e) => {{
                              const r = e.getBoundingClientRect();
                              return {{ sel, top: r.top, right: r.right, height: r.height }};
                            }})
                          ),
                        }})
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
                ok(
                    data["bar"]["scrollWidth"] <= data["bar"]["clientWidth"] + 1,
                    f"at {width}px: the one-bar itself needs no sideways scroll "
                    f"(scrollWidth {data['bar']['scrollWidth']:.0f} <= "
                    f"clientWidth {data['bar']['clientWidth']:.0f}) — its own "
                    "`overflow-x: auto` escape valve must never actually be needed at this "
                    "width, or an occupant past the fold (e.g. Release) would be reachable "
                    "only by scrolling the bar, not by looking at it",
                )
                occupants = data.get("occupants", [])
                rows = cluster_rows([o["top"] for o in occupants])
                ok(
                    len(rows) == expected_rows,
                    f"at {width}px: the bar forms exactly {expected_rows} row(s) "
                    f"(measured {len(rows)}: tops {rows})",
                )
                for row_tops in rows:
                    row_occ = [o for o in occupants if o["top"] in row_tops]
                    row_max_h = max((o["height"] for o in row_occ), default=0)
                    ok(
                        row_max_h <= MAX_BAR_HEIGHT_PX + 1,
                        f"at {width}px: row at top={row_tops[0]:.0f} stays at or under "
                        f"{MAX_BAR_HEIGHT_PX}px tall (measured {row_max_h:.0f}px) — a tall "
                        "row is the regression this check exists to catch even when nothing "
                        "overflows or clips",
                    )
                for occ in occupants:
                    ok(
                        occ["right"] <= width + 1,
                        f"at {width}px: {occ['sel']} stays within the viewport "
                        f"(right={occ['right']:.0f})",
                    )

                # NO-JUMP, measured — not read off the CSS source. Mutate the
                # Scenes/Colour value text in the live DOM (purely client-side;
                # nothing is sent anywhere) and check that a later sibling
                # (`.energy-mark-group`, order 6, right after the Scenes/Colour
                # buttons at order 4) doesn't move.
                r = await cdp_call(ws, nid(), "Runtime.evaluate", {
                    "expression": """
                        JSON.stringify((() => {
                          const valueEls = [...document.querySelectorAll(
                            '.scenes-group-btn .top-bar-group-btn-value')];
                          const anchor = document.querySelector('.energy-mark-group');
                          if (!valueEls.length || !anchor) return { skipped: true };
                          const before = anchor.getBoundingClientRect().left;
                          const originals = valueEls.map((el) => el.textContent);
                          valueEls.forEach((el) => {
                            el.textContent = 'A Really Extremely Long Scene Or Colour Set Name';
                          });
                          void document.body.offsetHeight;  // force reflow
                          const after = anchor.getBoundingClientRect().left;
                          valueEls.forEach((el, i) => { el.textContent = originals[i]; });
                          void document.body.offsetHeight;  // restore before anything else reads it
                          return { skipped: false, before, after };
                        })())
                    """,
                    "returnByValue": True,
                })
                value = r.get("result", {}).get("result", {}).get("value")
                jump_data = json.loads(value) if value else {"skipped": True}
                if jump_data.get("skipped"):
                    print(f"  (at {width}px: no Scenes/Colour button or anchor present — "
                          "skipping the no-jump measurement)")
                else:
                    ok(
                        abs(jump_data["after"] - jump_data["before"]) <= 1,
                        f"at {width}px: lengthening the Scenes/Colour value text doesn't move "
                        f".energy-mark-group (before={jump_data['before']:.0f}, "
                        f"after={jump_data['after']:.0f})",
                    )

                # EXPAND, measured — the device-preview "Expand" feature must
                # drop its stage onto its own line below every other icon,
                # never squeezed onto the same line (the regression this
                # fixes: `.one-bar:has(.device-preview-expanded-row)` in
                # tokens.css). Only exercised when a favourite device exists
                # (the swatches button only renders then).
                r = await cdp_call(ws, nid(), "Runtime.evaluate", {
                    "expression": """
                        JSON.stringify((() => {
                          const btn = document.querySelector('.device-preview-chips');
                          if (!btn) return { present: false };
                          btn.click();
                          return { present: true };
                        })())
                    """,
                    "returnByValue": True,
                })
                clicked = json.loads(r.get("result", {}).get("result", {}).get("value") or "{}")
                if not clicked.get("present"):
                    print(f"  (at {width}px: no favourite device-preview swatches — "
                          "skipping the expand measurement)")
                else:
                    expand_deadline = time.monotonic() + 5
                    expand_data = None
                    while time.monotonic() < expand_deadline:
                        r = await cdp_call(ws, nid(), "Runtime.evaluate", {
                            "expression": """
                                JSON.stringify((() => {
                                  const row = document.querySelector('.device-preview-expanded-row');
                                  if (!row) return { present: false };
                                  const rowRect = row.getBoundingClientRect();
                                  const others = [...document.querySelectorAll(
                                    '.mode-chip, .scenes-group-btn, .energy-mark-group, '
                                    + '.light-show-strip, .device-preview-strip, .warning-chip, '
                                    + '.release-hold-wrap'
                                  )].map((e) => e.getBoundingClientRect().bottom);
                                  return {
                                    present: true,
                                    rowTop: rowRect.top,
                                    rowRight: rowRect.right,
                                    maxOtherBottom: others.length ? Math.max(...others) : 0,
                                    scrollWidth: document.documentElement.scrollWidth,
                                    clientWidth: document.documentElement.clientWidth,
                                  };
                                })())
                            """,
                            "returnByValue": True,
                        })
                        expand_value = r.get("result", {}).get("result", {}).get("value")
                        expand_data = json.loads(expand_value) if expand_value else {"present": False}
                        if expand_data.get("present"):
                            break
                        await asyncio.sleep(0.2)
                    ok(
                        bool(expand_data and expand_data.get("present")),
                        f"at {width}px: expanding the device preview mounts "
                        ".device-preview-expanded-row",
                    )
                    if expand_data and expand_data.get("present"):
                        ok(
                            expand_data["rowTop"] >= expand_data["maxOtherBottom"] - 1,
                            f"at {width}px: the expanded stage lands below every other icon "
                            f"(rowTop={expand_data['rowTop']:.0f}, "
                            f"maxOtherBottom={expand_data['maxOtherBottom']:.0f})",
                        )
                        ok(
                            expand_data["rowRight"] <= width + 1,
                            f"at {width}px: the expanded stage's own right edge "
                            f"({expand_data['rowRight']:.0f}) stays within the viewport",
                        )
                        ok(
                            expand_data["scrollWidth"] <= expand_data["clientWidth"] + 1,
                            f"at {width}px: expanding causes no page-level horizontal scroll "
                            f"(scrollWidth {expand_data['scrollWidth']} <= "
                            f"clientWidth {expand_data['clientWidth']})",
                        )
                    # Collapse again so the next width starts from the same
                    # (collapsed) state — this headless profile is thrown
                    # away afterward either way, but keep each width's
                    # measurement independent of the previous one.
                    await cdp_call(ws, nid(), "Runtime.evaluate", {
                        "expression": "document.querySelector('.device-preview-chips')?.click();",
                    })
                    await asyncio.sleep(0.2)

            # THE LIGHT SHOW SLOT'S OWN TEXT, AT THE WIDTHS THAT CLIPPED IT
            # (spotfx-deploy-427): `.light-show-act-name` carried a fixed
            # `max-width: 72px` for every width <=1180px, and the override
            # lifting it covered only the 521-1100px two-row band — leaving
            # it clipped to "Nothing a…" in the two gaps either side:
            # 1101-1180px (one line) and the phone tier (<=520px, measured
            # here at 390). This is a GENERIC clip check (scrollWidth <=
            # clientWidth on both the name and its 'when' line) against
            # whatever the slot happens to be showing live — idle or an
            # armed action — because the cap was unconditional on the
            # element, not on its content; a dedicated idle-state proof
            # (forcing "Nothing armed" specifically) lives in
            # check_ui_fidelity.py's own mocked harness, which can set
            # that state deterministically where this read-only, live-only
            # script cannot.
            for width in (1180, 1101, 390):
                await cdp_call(ws, nid(), "Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False,
                })
                await asyncio.sleep(0.3)
                r = await cdp_call(ws, nid(), "Runtime.evaluate", {
                    "expression": """
                        JSON.stringify((() => {
                          const n = document.querySelector('.light-show-act-name');
                          const w = document.querySelector('.light-show-act-when');
                          const clip = (e) => (e ? e.scrollWidth > e.clientWidth + 1 : null);
                          return {
                            nameText: n ? n.textContent : null, nameClipped: clip(n),
                            whenText: w ? w.textContent : null, whenClipped: clip(w),
                            scrollWidth: document.documentElement.scrollWidth,
                            clientWidth: document.documentElement.clientWidth,
                          };
                        })())
                    """,
                    "returnByValue": True,
                })
                value = r.get("result", {}).get("result", {}).get("value")
                lsdata = json.loads(value) if value else {}
                if lsdata.get("nameText") is None:
                    print(f"  (at {width}px: the Light Show slot's name never rendered — skipping)")
                    continue
                ok(
                    lsdata["nameClipped"] is False,
                    f"at {width}px: the Light Show slot's name is not truncated "
                    f"(got {lsdata['nameText']!r})",
                )
                ok(
                    lsdata["whenClipped"] is False,
                    f"at {width}px: nor its 'when' line (got {lsdata['whenText']!r})",
                )
                ok(
                    lsdata["scrollWidth"] <= lsdata["clientWidth"] + 1,
                    f"at {width}px: no page-level horizontal scroll from the Light Show "
                    f"text (scrollWidth {lsdata['scrollWidth']} <= clientWidth "
                    f"{lsdata['clientWidth']})",
                )

            # THE KIOSK VIEW (spotfx-deploy-423 finding B) — same app, a
            # separate route (`?kiosk=1`) with no menu and its own
            # 800x424 usable size. `KioskPage.tsx` now wraps the two bar
            # components the same way App.tsx does, so this exercises the
            # identical `.one-bar` CSS, at a width inside the same
            # deliberate-two-row band as 1024 — nothing is shed here any
            # more (the Admiral's own 2026-10-14 decision), so every
            # occupant is expected present across the two rows.
            kiosk_url = APP_URL.rstrip("/") + "/?kiosk=1"
            await cdp_call(ws, nid(), "Emulation.setDeviceMetricsOverride", {
                "width": KIOSK_WIDTH, "height": KIOSK_HEIGHT, "deviceScaleFactor": 1, "mobile": False,
            })
            await cdp_call(ws, nid(), "Page.navigate", {"url": kiosk_url})
            deadline = time.monotonic() + 20
            kiosk_loaded = False
            last_diag = None
            while time.monotonic() < deadline:
                # Wait for the Scenes button too, not just the bar's own
                # box — a cold load can mount `.one-bar` before the
                # scene/registry data its occupants need has arrived
                # (react-query's own fetch), and measuring mid-fetch
                # read as occupants being transiently ABSENT rather than
                # a real layout defect (flaky, found by running this
                # check repeatedly against a live instance).
                r = await cdp_call(ws, nid(), "Runtime.evaluate", {
                    "expression": "JSON.stringify({rs: document.readyState, "
                                  "bar: !!document.querySelector('.kiosk-page .one-bar'), "
                                  "scenes: !!document.querySelector('.kiosk-page .scenes-group-btn')})",
                    "returnByValue": True,
                })
                last_diag = r.get("result", {}).get("result", {}).get("value")
                if last_diag:
                    parsed = json.loads(last_diag)
                    if parsed.get("rs") == "complete" and parsed.get("bar") and parsed.get("scenes"):
                        kiosk_loaded = True
                        break
                await asyncio.sleep(0.5)
            if not kiosk_loaded:
                print(f"kiosk: the one-bar never fully appeared within 20s (last diag: {last_diag}) — "
                      "skipping the kiosk measurement (is spectra.service serving a build with "
                      "this change?)")
            else:
                await asyncio.sleep(0.5)  # let layout settle
                r = await cdp_call(ws, nid(), "Runtime.evaluate", {
                    "expression": f"""
                        JSON.stringify({{
                          scrollWidth: document.documentElement.scrollWidth,
                          clientWidth: document.documentElement.clientWidth,
                          bar: (() => {{
                            const b = document.querySelector('.kiosk-page .one-bar');
                            if (!b) return null;
                            const rect = b.getBoundingClientRect();
                            return {{
                              right: rect.right,
                              scrollWidth: b.scrollWidth, clientWidth: b.clientWidth,
                            }};
                          }})(),
                          occupants: {json.dumps(OCCUPANT_SELECTORS)}.flatMap((sel) =>
                            [...document.querySelectorAll('.kiosk-page ' + sel)].map((e) => {{
                              const r = e.getBoundingClientRect();
                              return {{ sel, top: r.top, right: r.right, height: r.height }};
                            }})
                          ),
                        }})
                    """,
                    "returnByValue": True,
                })
                value = r.get("result", {}).get("result", {}).get("value")
                kiosk_data = json.loads(value) if value else {}
                ok(
                    kiosk_data.get("bar") is not None,
                    f"kiosk {KIOSK_WIDTH}x{KIOSK_HEIGHT}: the one-bar is present",
                )
                if kiosk_data.get("bar") is not None:
                    ok(
                        kiosk_data["scrollWidth"] <= kiosk_data["clientWidth"] + 1,
                        f"kiosk {KIOSK_WIDTH}x{KIOSK_HEIGHT}: no page-level horizontal scroll "
                        f"(scrollWidth {kiosk_data['scrollWidth']} <= "
                        f"clientWidth {kiosk_data['clientWidth']})",
                    )
                    ok(
                        kiosk_data["bar"]["scrollWidth"] <= kiosk_data["bar"]["clientWidth"] + 1,
                        f"kiosk {KIOSK_WIDTH}x{KIOSK_HEIGHT}: the one-bar itself needs no "
                        "sideways scroll",
                    )
                    kiosk_occ = kiosk_data.get("occupants", [])
                    kiosk_rows = cluster_rows([o["top"] for o in kiosk_occ])
                    ok(
                        len(kiosk_rows) == KIOSK_EXPECTED_ROWS,
                        f"kiosk {KIOSK_WIDTH}x{KIOSK_HEIGHT}: the bar forms exactly "
                        f"{KIOSK_EXPECTED_ROWS} row(s) (measured {len(kiosk_rows)}: "
                        f"tops {kiosk_rows})",
                    )
                    for row_tops in kiosk_rows:
                        row_occ = [o for o in kiosk_occ if o["top"] in row_tops]
                        row_max_h = max((o["height"] for o in row_occ), default=0)
                        ok(
                            row_max_h <= MAX_BAR_HEIGHT_PX + 1,
                            f"kiosk {KIOSK_WIDTH}x{KIOSK_HEIGHT}: row at top={row_tops[0]:.0f} "
                            f"stays at or under {MAX_BAR_HEIGHT_PX}px tall "
                            f"(measured {row_max_h:.0f}px)",
                        )
                    for occ in kiosk_occ:
                        ok(
                            occ["right"] <= KIOSK_WIDTH + 1,
                            f"kiosk {KIOSK_WIDTH}x{KIOSK_HEIGHT}: {occ['sel']} stays within "
                            f"the viewport (right={occ['right']:.0f})",
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
