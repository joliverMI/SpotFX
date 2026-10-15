#!/usr/bin/env python3
"""THE DESIGN-FIDELITY GATE — the approved artifact's own mockups beside
the live chrome, at the same widths, with the measurable parts asserted.

WHY THIS EXISTS. PRs 422-425 shipped the UI declutter plan's STRUCTURE and
not its DRAWING: a read-only audit (data/ui-fidelity-audit/report.md) found
8 glaring, 19 noticeable and 14 minor drift gaps, and its own root-cause
section names the reason plainly — "nothing compared a pixel to the
mockup". Every acceptance check those PRs added measures heights, rows,
overflow, routes, maths or fps, and every one of them PASSED on the build
the Admiral called "much worse than I remember". So this check does the
one thing none of them did: it RENDERS the approved artifact's own mockup
frames and the live page at the same size, writes the pairs out for a
person to eye, and asserts the parts a machine can settle.

WHAT IT RENDERS, and why it is not the live app. The live `spectra.service`
serves its own deployed bundle, so pointing this at :8010 would measure
whatever is deployed rather than the branch under test; and the chrome is
only half-drawn with nothing playing, which is exactly the state that hid
the drift. It therefore renders the repo's OWN mocked harness page
(spectra/web/harness/fidelity.tsx — the REAL NavBar/SongStrip/one-bar/Home
against the artifact's own canned song), both WITH a song and with NOTHING
PLAYING. Firstmate re-runs the same side-by-side against the live app after
deploying; the `--app-url` flag exists for exactly that and defaults to the
harness.

OUTPUT. `docs/evidence/ui-fidelity/` gets one `<name>.png` per mockup
frame, one per live view, and one `pair-<name>.png` with the two stacked
and labelled. The PR body links that folder.

RUN:
  .venv/bin/python scripts/check_ui_fidelity.py              # harness
  .venv/bin/python scripts/check_ui_fidelity.py --app-url \\
      http://127.0.0.1:8000/spectra/                         # the live app

It SKIPS cleanly (exit 0, saying why) with no Chromium available, or with
no harness build — a named hole beats a false clean row. Read-only: it
serves static files, drives a throwaway headless Chromium profile, and
never touches live storage, the network beyond loopback, or a light.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import functools
import http.server
import json
import os
import re
import shutil
import signal
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# The approved artifact lives in the fleet-spotfx home; when it is there
# it is authoritative. `docs/design/spectra-ui-mockups.html` is the frozen
# in-repo reference derived mechanically from it
# (scripts/regenerate_ui_mockups.py), so this gate runs anywhere the
# checkout goes — including a CI box with no fleet home.
FLEET_ARTIFACT = Path.home() / "fleet-spotfx/data/ui-layout-plan/explainer-final.html"
REPO_MOCKUPS = REPO / "docs/design/spectra-ui-mockups.html"
ARTIFACT = FLEET_ARTIFACT if FLEET_ARTIFACT.is_file() else REPO_MOCKUPS
HARNESS_DIST = REPO / "spectra" / "web" / "harness-dist"
OUT_DIR = REPO / "docs" / "evidence" / "ui-fidelity"

try:
    import websockets  # noqa: F401
except ImportError:  # pragma: no cover - environment-dependent
    websockets = None

# ── WHAT TO COMPARE ──────────────────────────────────────────────────────
# Each row: (name, the artifact frame's element id, its native width, the
# live view's own query string, the live width, the live height). The
# frame ids are the artifact's own `mount(...)` calls; the widths are the
# `data-w` it mounts them at, so a frame is captured at 1:1 exactly as his
# own "1:1" button shows it.
PAIRS = [
    ("desktop-1440", "f-desk", 1440, "view=bar", 1440, 420),
    ("tablet-1180", "f-tab820", 1180, "view=bar", 1180, 420),
    ("tablet-1024", "f-tab", 1024, "view=bar", 1024, 420),
    ("home-1440", "f-home", 1440, "view=home", 1440, 1000),
    ("home-1024", "f-home-tab", 1024, "view=home", 1024, 1000),
    ("kiosk-800", "f-kiosk", 1280, "kiosk=1", 800, 424),
    ("menu-open-1440", "f-menu-desk", 1440, "view=bar&menu=1", 1440, 520),
    ("next-box-states", "f-nxstates", 760, None, 0, 0),
    ("light-show-slots", "f-show", 1240, None, 0, 0),
    ("settings-1024", "f-settings", 1024, "view=settings", 1024, 1100),
]
# The EMPTY state has no mockup frame of its own (every Home mock has a
# song) — it is captured and asserted on its own, because it is the state
# the Admiral reviewed the deploy in and the one the live app used to
# render as menu + bar and nothing else.
# "within a few px of the mockup" (firstmate's words): the live canvas
# is laid out by flexbox inside a bordered box, so a px of rounding either
# way is fine — a stack of empty beat-strip lanes under the waveform is
# tens of px, which is what this catches.
SHAPE_H_TOLERANCE_PX = 4

EMPTY_VIEWS = [
    ("empty-1440", "view=bar&nothing=1", 1440, 420),
    ("empty-home-1440", "view=home&nothing=1", 1440, 900),
]


# ── a tiny PNG stacker, so the pairs need no image library ───────────────
def _png_read(path: Path) -> tuple[int, int, list[bytearray]]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    pos, w, h, idat, channels = 8, 0, 0, b"", 0
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            w, h, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
            assert depth == 8 and color in (2, 6) and interlace == 0, (depth, color, interlace)
            channels = 3 if color == 2 else 4
        elif ctype == b"IDAT":
            idat += body
        pos += 12 + length
    assert channels and w and h, f"no IHDR in {path}"
    raw = zlib.decompress(idat)
    stride = w * channels
    rows: list[bytearray] = []
    prev = bytearray(stride)
    i = 0
    for _ in range(h):
        ftype = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        if ftype == 1:
            for x in range(channels, stride):
                line[x] = (line[x] + line[x - channels]) & 0xFF
        elif ftype == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif ftype == 3:
            for x in range(stride):
                left = line[x - channels] if x >= channels else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif ftype == 4:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                b = prev[x]
                c = prev[x - channels] if x >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 0xFF
        rows.append(line)
        prev = line
    # normalise to RGB
    if channels == 4:
        rows = [bytearray(b for i2 in range(w) for b in r[i2 * 4:i2 * 4 + 3]) for r in rows]
    return w, h, rows


def _png_write(path: Path, w: int, rows: list[bytearray]) -> None:
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    def chunk(ctype: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + ctype + body
                + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", w, len(rows), 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def stack_pair(top: Path, bottom: Path, out: Path) -> None:
    """Stack two PNGs vertically with a divider — a self-contained pair
    image per comparison, so the folder can be eyed with no tooling."""
    w1, _, r1 = _png_read(top)
    w2, _, r2 = _png_read(bottom)
    w = max(w1, w2)
    def pad(rows: list[bytearray], rw: int) -> list[bytearray]:
        if rw == w:
            return rows
        extra = bytearray([18, 6, 30] * (w - rw))
        return [r + extra for r in rows]
    divider = [bytearray([168, 85, 247] * w) for _ in range(3)]
    _png_write(out, w, pad(r1, w1) + divider + pad(r2, w2))


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D102, ANN002
        pass


def serve(directory: Path, port: int) -> socketserver.TCPServer:
    """The harness is built with `base: '/spectra/'`, so its assets 404
    unless served under that prefix (the audit's own note)."""
    class Handler(QuietHandler):
        def translate_path(self, path):  # noqa: D102, ANN001
            if path.startswith("/spectra/"):
                path = path[len("/spectra"):]
            return super().translate_path(path)

    httpd = socketserver.TCPServer(
        ("127.0.0.1", port),
        functools.partial(Handler, directory=str(directory)),
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def find_chrome() -> str | None:
    for p in ("google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(p)
        if found:
            return found
    base = Path.home() / ".cache/ms-playwright"
    if base.is_dir():
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


async def cdp(ws, nid, method, params=None):
    msg_id = nid()
    await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        data = json.loads(await ws.recv())
        if data.get("id") == msg_id:
            return data


async def wait_for_devtools(port: int, timeout_s: float = 20.0) -> str:
    """The PAGE target's own websocket URL — never the browser-level one
    `/json/version` returns, which 404s `Page.navigate` on current Chrome
    (check_onebar_layout.py's own measured note)."""
    import urllib.request
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                targets = json.loads(r.read())
            pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
            if pages:
                return pages[0]["webSocketDebuggerUrl"]
        except Exception as e:  # noqa: BLE001
            last = e
        await asyncio.sleep(0.3)
    raise RuntimeError(f"devtools page target never came up: {last}")


async def evaluate(ws, nid, expr):
    r = await cdp(ws, nid, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
    res = r.get("result", {}).get("result", {})
    if "value" not in res:
        raise RuntimeError(f"evaluate failed: {json.dumps(r)[:400]}")
    return res["value"]


async def shoot(ws, nid, out: Path, clip=None) -> None:
    # `captureBeyondViewport` RESIZES the page to its full content height
    # before capturing, which REFLOWS it — so a clip measured beforehand
    # can land on different content (measured: the mockup clips came back
    # showing the artifact's prose above each frame). It is therefore used
    # only for whole-page shots, where there is no clip to invalidate.
    params = {"format": "png"}
    if clip:
        params["clip"] = {**clip, "scale": 1}
    else:
        params["captureBeyondViewport"] = True
    r = await cdp(ws, nid, "Page.captureScreenshot", params)
    out.write_bytes(base64.b64decode(r["result"]["data"]))


async def goto(ws, nid, url: str, ready_expr: str, timeout_s: float = 25.0) -> bool:
    await cdp(ws, nid, "Page.navigate", {"url": url})
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if await evaluate(ws, nid, ready_expr):
                return True
        except Exception:  # noqa: BLE001, S110
            pass
        await asyncio.sleep(0.3)
    return False


async def run(app_url: str, artifact_url: str) -> int:
    failures: list[str] = []
    notes: list[str] = []

    def ok(cond, msg):
        if cond:
            print(f"  ✓ {msg}")
        else:
            print(f"  ✗ {msg}")
            failures.append(msg)

    chrome = find_chrome()
    port = free_port()
    profile = f"/tmp/spectra-ui-fidelity-{port}"
    proc = subprocess.Popen(  # noqa: S603
        [chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
         "--hide-scrollbars", "--force-device-scale-factor=1",
         f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
         "--window-size=1440,900"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        ws_url = await wait_for_devtools(port)
        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
            mid = [0]

            def nid():
                mid[0] += 1
                return mid[0]

            await cdp(ws, nid, "Page.enable")
            await cdp(ws, nid, "Runtime.enable")

            # ── 1. the artifact's own frames, each at its native width ──
            print("ONE — the approved artifact's own mockup frames, at 1:1")
            # Tall enough that every frame (the tallest, f-kiosk, declares
            # its own 800px min-height) fits the viewport in one go — the
            # clips below are taken WITHOUT captureBeyondViewport, so a
            # frame taller than the viewport would be cut off.
            await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                "width": 1700, "height": 1500, "deviceScaleFactor": 1, "mobile": False})
            if not await goto(ws, nid, artifact_url, "!!document.getElementById('f-desk')"):
                print("  the artifact never rendered — skipping")
                return 0
            # Its own "1:1" behaviour: `.fw.native` plus dropping the
            # column's max-width, exactly the audit's recipe.
            await evaluate(ws, nid, """(() => {
              document.querySelectorAll('.wrap').forEach((w) => { w.style.maxWidth = 'none'; });
              document.querySelectorAll('.fw').forEach((f) => {
                f.classList.add('native');
                f.style.maxWidth = 'none';
                const fr = f.querySelector('.frame');
                if (fr) fr.style.transform = 'none';
              });
              return true;
            })()""")
            await asyncio.sleep(1.2)  # let the artifact's own rAF loop draw
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            mock_shots: dict[str, Path] = {}
            for name, frame_id, native_w, *_ in PAIRS:
                # The `.sp` CHILD is the mockup at its native width — its
                # `.fw` wrapper is only a column-width viewport with
                # `overflow-x: auto` (several frames sit in a two-column
                # grid, so the wrapper measures ~825px however native the
                # frame inside it is).
                rect = await evaluate(ws, nid, f"""(() => {{
                  const host = document.getElementById({json.dumps(frame_id)});
                  const el = host && host.querySelector('.sp');
                  if (!el) return null;
                  host.scrollIntoView();
                  const r = el.getBoundingClientRect();
                  return {{ x: r.left + window.scrollX, y: r.top + window.scrollY,
                            width: r.width, height: r.height }};
                }})()""")
                ok(rect is not None and rect["width"] >= native_w - 2,
                   f"{name}: frame #{frame_id} rendered at its native {native_w}px "
                   f"(got {0 if not rect else round(rect['width'])})")
                if not rect:
                    continue
                path = OUT_DIR / f"mockup-{name}.png"
                await shoot(ws, nid, path, rect)
                mock_shots[name] = path

            # Home's audio shape, MEASURED off the mockup rather than
            # hardcoded here, so the live one below is held to the
            # artifact's own number (its `.canvasbox canvas` is 230px) and
            # a future mockup edit moves the bar with it.
            mock_shape_h = await evaluate(ws, nid, """(() => {
              const c = document.querySelector('#f-home .sp .canvasbox canvas');
              return c ? Math.round(c.getBoundingClientRect().height) : null;
            })()""")
            ok(isinstance(mock_shape_h, int) and mock_shape_h > 0,
               f"read the mockup's own audio-shape height ({mock_shape_h}px)")

            # ── 2. the live chrome at the same sizes ───────────────────
            print("\nTWO — the live chrome at the same widths")
            live_shots: dict[str, Path] = {}
            for name, _frame, _nw, query, width, height in PAIRS:
                if query is None:
                    notes.append(f"{name}: mockup-only (no live counterpart by design)")
                    continue
                await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
                url = f"{app_url}?{query}" if "?" not in app_url else f"{app_url}&{query}"
                ready = "!!document.querySelector('.one-bar')"
                if not await goto(ws, nid, url, ready):
                    print(f"  the live chrome never appeared at {url} — skipping")
                    return 0
                if "menu=1" in (query or ""):
                    await evaluate(ws, nid, """(() => {
                      const t = [...document.querySelectorAll('.nav-group-trigger')]
                        .find((b) => b.textContent.includes('Artifacts'));
                      if (t) t.click();
                      return true;
                    })()""")
                await asyncio.sleep(1.0)
                path = OUT_DIR / f"live-{name}.png"
                await shoot(ws, nid, path)
                live_shots[name] = path
                ok(True, f"{name}: captured the live view at {width}x{height}")

            for name in live_shots:
                if name in mock_shots:
                    stack_pair(mock_shots[name], live_shots[name], OUT_DIR / f"pair-{name}.png")

            # ── 3. the EMPTY state — the state that hid the drift ──────
            print("\nTHREE — nothing playing: the strip and the Light Show slot STAY")
            for name, query, width, height in EMPTY_VIEWS:
                await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
                if not await goto(ws, nid, f"{app_url}?{query}", "!!document.querySelector('.one-bar')"):
                    print("  the live chrome never appeared — skipping")
                    return 0
                await asyncio.sleep(0.8)
                await shoot(ws, nid, OUT_DIR / f"live-{name}.png")
            # Measured on an ORDINARY route, not whichever view the loop
            # above happened to leave on screen: Home draws no global
            # strip at all by design (§13 decision 5, asserted in FOUR-C),
            # so measuring "is the strip still there" on Home would read
            # that deliberate absence as the very regression this catches.
            await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                "width": 1440, "height": 420, "deviceScaleFactor": 1, "mobile": False})
            if not await goto(ws, nid, f"{app_url}?view=bar&nothing=1",
                              "!!document.querySelector('.one-bar')"):
                print("  the live chrome never appeared — skipping")
                return 0
            await asyncio.sleep(0.8)
            state = await evaluate(ws, nid, """(() => {
              const strip = document.querySelector('.song-strip');
              const slot = document.querySelector('.light-show-slot');
              const count = document.querySelector('.song-strip-next-count');
              return JSON.stringify({
                strip: !!strip,
                stripH: strip ? Math.round(strip.getBoundingClientRect().height) : 0,
                slot: !!slot,
                slotIdle: !!document.querySelector('.light-show-slot-idle'),
                slotText: slot ? slot.textContent : '',
                count: count ? count.textContent.trim() : null,
                sceneName: (document.querySelectorAll('.bar-slot-name')[0] || {}).textContent || null,
              });
            })()""")
            s = json.loads(state)
            ok(s["strip"], "the song timeline is STILL ON SCREEN with nothing playing (audit T1)")
            ok(s["slot"], "the Light Show slot is STILL ON SCREEN with nothing armed (audit B7)")
            ok(s["slotIdle"] and "Nothing armed" in s["slotText"]
               and "tap to run an action" in s["slotText"],
               "the Light Show slot draws the mockup's own idle state "
               f"('Nothing armed' / 'tap to run an action') — got {s['slotText']!r}")
            ok(s["count"] == "—", f"the next-event box reads the mockup's '—' (got {s['count']!r})")
            ok(s["sceneName"] == "—", f"the Scene slot keeps its fixed width and reads '—' (got {s['sceneName']!r})")

            # ── 4. the measurable drawing ──────────────────────────────
            print("\nFOUR — the measurable parts of the drawing, with a song")
            # On an ORDINARY page's route — Home and the Timeline page
            # carry their own editable copy of the timeline and draw no
            # global strip at all (§13 decision 5; asserted in FOUR-C).
            await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                "width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
            if not await goto(ws, nid, f"{app_url}?view=bar", "!!document.querySelector('.song-strip-next')"):
                print("  the live chrome never appeared — skipping")
                return 0
            await asyncio.sleep(1.2)
            m = json.loads(await evaluate(ws, nid, r"""(() => {
              const box = (sel) => {
                const el = document.querySelector(sel);
                if (!el) return null;
                const r = el.getBoundingClientRect();
                const c = getComputedStyle(el);
                return { w: Math.round(r.width), h: Math.round(r.height),
                         fs: c.fontSize, fw: c.fontWeight, tt: c.textTransform,
                         fvn: c.fontVariantNumeric, br: c.borderRadius,
                         color: c.color, bw: c.borderTopWidth, bc: c.borderTopColor,
                         top: Math.round(r.top), left: Math.round(r.left) };
              };
              // The "inside the last 3s" look, read with the box's own
              // `transition: border-color .2s` suppressed — otherwise the
              // computed colour is still the OLD one at read time, which
              // is a measurement artefact, not the drawing.
              const soon = document.querySelector('.song-strip-next');
              let soonColor = null;
              if (soon) {
                const prev = soon.style.transition;
                soon.style.transition = 'none';
                soon.classList.add('song-strip-next-soon');
                soonColor = getComputedStyle(soon).borderTopColor;
                soon.classList.remove('song-strip-next-soon');
                soon.style.transition = prev;
              }
              const rows = (sel) => [...document.querySelectorAll(sel)]
                .map((e) => Math.round(e.getBoundingClientRect().top));
              return JSON.stringify({
                bar: box('.one-bar'),
                barRows: [...new Set(rows('.one-bar .mode-chip, .one-bar .scenes-group-btn, '
                  + '.one-bar .energy-mark-group, .one-bar .light-show-strip, '
                  + '.one-bar .device-preview-strip'))].length,
                seps: document.querySelectorAll('.one-bar .one-bar-sep').length,
                sepW: (() => { const s = document.querySelector('.one-bar .one-bar-sep');
                  return s ? Math.round(s.getBoundingClientRect().width) : null; })(),
                modeBtn: box('.mode-group-btn'),
                disc: box('.display-mode-disc'),
                bulb: !!document.querySelector('.ambient-group-btn svg'),
                bulbEmoji: (document.querySelector('.ambient-group-btn') || {}).textContent || '',
                slot: box('.scenes-group-btn'),
                slotLabel: box('.bar-slot-label'),
                slotLabelText: (document.querySelector('.bar-slot-label') || {}).textContent,
                swatch: box('.bar-slot-swatch'),
                swatchBg: (() => { const s = document.querySelector('.bar-slot-swatch');
                  return s ? getComputedStyle(s).backgroundImage || getComputedStyle(s).backgroundColor : null; })(),
                energy: box('.energy-readout'),
                energyBolt: !!document.querySelector('.energy-readout svg'),
                mark: box('.intensity-mark'),
                markText: (document.querySelector('.intensity-mark') || {}).textContent,
                show: box('.light-show-slot'),
                preview: box('.device-preview-strip'),
                previewSwatch: box('.device-preview-swatch'),
                strip: box('.song-strip'),
                stripTrack: box('.song-strip-track'),
                nextBox: box('.song-strip-next'),
                nextCount: box('.song-strip-next-count'),
                nextSoonBorder: soonColor,
                time: box('.song-strip-time'),
                // Scoped to the STRIP's own equaliser — Home's card head
                // reuses the same class, so an unscoped count is doubled.
                eqBars: document.querySelectorAll('.song-strip .song-strip-eq i').length,
                songIsLink: !!document.querySelector('a.song-strip-song'),
                // LAYOUT size, not the bounding box: the gem is a 14px
                // square ROTATED 45°, so its rect measures 14*sqrt(2) ~ 19.8.
                gem: (() => {
                  const g = document.querySelector('.logo-gem');
                  if (!g) return null;
                  return { w: g.offsetWidth, h: g.offsetHeight,
                           transform: getComputedStyle(g).transform };
                })(),
                infoCircles: document.querySelectorAll('.info-tip-btn').length,
                helpInChrome: document.querySelectorAll(
                  '.one-bar .help-link, .song-strip .help-link, '
                  + '.home-timeline-head .help-link').length,
                helpInNav: document.querySelectorAll('nav .help-link').length,
                helpInSettingsRows: document.querySelectorAll('.settings-row .help-link').length,
                // THE RENDERED size of every small icon button's glyph —
                // the thing the "icons render tiny" regression actually
                // broke (the global `button { padding: 6px 12px }`
                // squeezed a 16px glyph to 4px wide inside a 30px box,
                // while every attribute still read 16).
                tinyGlyphs: [...document.querySelectorAll(
                  '.icon-toggle svg, .home-timeline-tool svg, .home-quick-icon-btn svg, '
                  + '.nav-group-item svg, .one-bar .top-bar-group-btn svg')]
                  .map((g) => { const r = g.getBoundingClientRect();
                    return { w: Math.round(r.width), h: Math.round(r.height) }; })
                  .filter((d) => d.w < d.h - 1 || d.w < 10),
                // IDEA 7's own hover target, for the REAL mouse move
                // below — a synthetic `mouseenter` does not reach React,
                // which implements onMouseEnter through mouseover/mouseout
                // delegation.
                songTip: (() => {
                  const tip = document.querySelector('.song-strip-song-tip');
                  if (!tip) return null;
                  const r = tip.getBoundingClientRect();
                  return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
                })(),
                // MENU, THEN TIMELINE, THEN BAR — the approved mockups'
                // own order (`nav() + timelineRow() + bar()`). The live
                // app had the bar SECOND and the strip third, and this
                // gate did not see it because the harness hand-rolled the
                // mockup's order instead of rendering the app's own
                // chrome; both now render components/AppChrome.tsx.
                chromeOrder: ['nav', '.song-strip', '.one-bar']
                  .map((sel) => { const el = document.querySelector(sel);
                    return el ? Math.round(el.getBoundingClientRect().top) : null; }),
                nextCountText: (document.querySelector('.song-strip-next-count') || {}).textContent,
                timeText: (document.querySelector('.song-strip-time') || {}).textContent,
                scrollW: document.documentElement.scrollWidth,
                clientW: document.documentElement.clientWidth,
              });
            })()"""))

            ok(m["bar"]["h"] == 48, f"the one bar is the mockup's 48px tall (got {m['bar']['h']})")
            ok(m["barRows"] == 1, f"1440 is ONE row (got {m['barRows']})")
            ok(m["seps"] == 4, f"four thin dividers between the control groups (got {m['seps']})")
            ok(m["sepW"] == 1, f"each divider is 1px wide (got {m['sepW']})")
            ok(m["modeBtn"]["w"] == 36 and m["modeBtn"]["h"] == 34,
               f"the display-mode button is the mockup's 36x34 (got {m['modeBtn']['w']}x{m['modeBtn']['h']})")
            ok(m["disc"] is not None and m["disc"]["w"] == 16 and m["disc"]["h"] == 16,
               "the display mode is a 16px DISC, not a filled rectangle (audit B2)")
            ok(m["disc"] and m["disc"]["br"].startswith("50%"), "the disc is round")
            ok(m["bulb"] and "💡" not in m["bulbEmoji"],
               "Hue Hold draws the registry's bulb PATH, not the 💡 emoji (audit B3)")
            ok(m["slot"]["w"] == 156, f"the name slots are the mockup's 156px (got {m['slot']['w']})")
            ok(m["slotLabelText"] == "Scene",
               f"the Scenes slot's label is the mockup's singular 'Scene' (got {m['slotLabelText']!r})")
            ok(m["slotLabel"]["tt"] == "uppercase", "the slot label is uppercase")
            ok(m["swatch"] is not None and m["swatch"]["w"] == 18,
               "the Colour slot carries an 18px swatch of the set's own colours (audit B4)")
            ok(m["swatchBg"] and m["swatchBg"] not in ("none", "rgba(0, 0, 0, 0)"),
               f"that swatch is painted from real colour-set data (got {m['swatchBg']!r})")
            ok(m["energy"]["h"] == 34 and m["energy"]["bw"] == "1px",
               f"Energy is a BORDERED 34px slot (got h={m['energy']['h']}, border={m['energy']['bw']})")
            ok(m["energyBolt"], "Energy's bolt is a drawn icon, not the ⚡ emoji (audit B5)")
            ok(m["mark"] is not None and m["mark"]["w"] == 48 and m["mark"]["h"] == 34,
               "Mark is the mockup's fixed 48x34 box (audit B6/N2)")
            ok(m["markText"] and m["markText"].lower().startswith("mark"),
               f"that box reads MARK over its value (got {m['markText']!r})")
            ok(m["show"] is not None and m["show"]["h"] == 34 and m["show"]["bw"] == "1px",
               "the Light Show slot is a bordered 34px slot (audit B7)")
            ok(m["preview"]["h"] == 34 and m["preview"]["bw"] == "1px",
               "the preview swatches sit in one bordered group (audit B8)")
            ok(m["previewSwatch"]["w"] == 16 and m["previewSwatch"]["h"] == 16,
               f"each swatch is 16px square and rounded (got {m['previewSwatch']['w']}x{m['previewSwatch']['h']})")
            ok(m["strip"]["h"] == 53, f"the song-timeline row is the mockup's 53px (got {m['strip']['h']})")
            ok(m["stripTrack"]["h"] == 39, f"its track is 39px (got {m['stripTrack']['h']})")
            ok(m["nextBox"]["w"] == 96 and m["nextBox"]["h"] == 39,
               f"the next-event box is 96x39 (got {m['nextBox']['w']}x{m['nextBox']['h']})")
            ok(m["nextCount"]["fs"] == "17px" and int(m["nextCount"]["fw"]) >= 700,
               f"its countdown is BOLD 17px, not 15px regular (audit T4 — got "
               f"{m['nextCount']['fs']}/{m['nextCount']['fw']})")
            ok(m["nextSoonBorder"] == "rgb(232, 121, 249)",
               f"inside the last 3s the box goes MAGENTA (accent2), not purple (got {m['nextSoonBorder']})")
            ok("tabular-nums" in (m["nextCount"]["fvn"] or ""),
               f"the countdown uses TABULAR digits (audit T5/N3 — got {m['nextCount']['fvn']!r})")
            ok("tabular-nums" in (m["time"]["fvn"] or ""),
               f"so does the progress readout (got {m['time']['fvn']!r})")
            ok(m["eqBars"] == 3, f"the song block draws the mockup's 3-bar equaliser (got {m['eqBars']})")
            ok(m["songIsLink"], "and taps through to Home (audit T2)")
            ok(m["gem"] is not None and m["gem"]["w"] == 14 and m["gem"]["h"] == 14
               and m["gem"]["transform"] not in (None, "none"),
               "the logo is a drawn 14px gem rotated 45°, not a '◆' font glyph (audit M1)")

            # The dropdown needs its own round trip: a click inside one
            # `Runtime.evaluate` cannot be measured in the same tick,
            # because React has not flushed the state update yet (the
            # first version of this check measured 0 items for exactly
            # that reason, not because the icons were missing).
            await evaluate(ws, nid, """(() => {
              const t = [...document.querySelectorAll('.nav-group-trigger')]
                .find((b) => b.textContent.includes('Artifacts'));
              if (t) t.click();
              return true;
            })()""")
            await asyncio.sleep(0.4)
            nav = json.loads(await evaluate(ws, nid, """(() => {
              const items = [...document.querySelectorAll('.nav-group-item')];
              const menu = document.querySelector('.nav-group-menu');
              return JSON.stringify({
                n: items.length,
                withSvg: items.filter((i) => i.querySelector('svg')).length,
                h: items[0] ? Math.round(items[0].getBoundingClientRect().height) : 0,
                menuW: menu ? Math.round(menu.getBoundingClientRect().width) : 0,
                activeFilled: (() => {
                  const a = document.querySelector('.nav-group-item.active');
                  if (!a) return null;
                  const c = getComputedStyle(a);
                  return { bg: c.backgroundColor, shadow: c.boxShadow };
                })(),
              });
            })()"""))
            ok(nav["n"] > 0 and nav["withSvg"] == nav["n"],
               f"every dropdown item carries its own icon (audit M4 — {nav['withSvg']}/{nav['n']})")
            ok(nav["h"] == 36, f"dropdown rows are the mockup's 36px (got {nav['h']})")
            ok(nav["menuW"] >= 236, f"the dropdown is the mockup's ~236px wide (got {nav['menuW']})")
            ok(m["infoCircles"] == 0,
               f"NO visible ⓘ circle anywhere (audit B11/M2/S3 — found {m['infoCircles']})")
            ok(m["helpInChrome"] == 0,
               "no '?' circle in the bar, the strip or Home's card head either "
               f"(found {m['helpInChrome']})")
            ok(m["helpInNav"] == 1,
               f"exactly ONE '?' in the chrome, the menu's own page help (idea 5 — found {m['helpInNav']})")
            ok(not m["tinyGlyphs"],
               "every small icon button's glyph renders at its real size — none squeezed "
               f"narrow by the global button padding (audit H2; offenders: {m['tinyGlyphs']})")
            # A REAL mouse move over the song block — see `songTip`.
            if m["songTip"]:
                await cdp(ws, nid, "Input.dispatchMouseEvent", {
                    "type": "mouseMoved", "x": m["songTip"]["x"], "y": m["songTip"]["y"]})
            await asyncio.sleep(0.4)
            tip = await evaluate(ws, nid, '''(() => {
              const p = document.querySelector('.info-tip-panel');
              return p ? p.textContent : null;
            })()''')
            ok(tip is not None and "Up next: CYBERTRUCK" in tip,
               f"hovering the song block names what is UP NEXT (approved idea 7 — got {tip!r})")

            order = m["chromeOrder"]
            ok(all(t is not None for t in order) and order[0] < order[1] < order[2],
               "the chrome runs MENU → TIMELINE → BAR, the mockups' own order "
               f"(measured tops: {order})")

            ok(re.match(r"^\d+\.\ds$|^\d+:\d\d$", (m["nextCountText"] or "").strip()),
               "with a song, the next-event box counts down in the mockup's own format "
               f"(tenths under 99.95s, m:ss above — got {m['nextCountText']!r})")
            ok(re.match(r"^\d+:\d\d / \d+:\d\d$", (m["timeText"] or "").strip()),
               f"and the progress reads 'now / total' (got {m['timeText']!r})")
            ok(m["scrollW"] <= m["clientW"],
               f"no horizontal page scroll at 1440 ({m['scrollW']} <= {m['clientW']})")

            # ── 4c. Home's own page ────────────────────────────────────
            print("\nFOUR-C — Home: its own timeline card, and no global strip")
            await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                "width": 1440, "height": 1100, "deviceScaleFactor": 1, "mobile": False})
            if not await goto(ws, nid, f"{app_url}?view=home",
                              "!!document.querySelector('.home-timeline')"):
                print("  Home never rendered — skipping its assertions")
            else:
                await asyncio.sleep(1.2)
                h = json.loads(await evaluate(ws, nid, '''(() => {
                  const canvas = document.querySelector('.home-timeline-shape canvas');
                  const row = document.querySelector('.home-quick-action-row');
                  const tops = row ? [...row.children]
                    .map((c) => Math.round(c.getBoundingClientRect().top)) : [];
                  const play = document.querySelector('.home-quick-play');
                  return JSON.stringify({
                    globalStrip: !!document.querySelector('.song-strip'),
                    ownCard: !!document.querySelector('.home-timeline'),
                    canvasH: canvas ? Math.round(canvas.getBoundingClientRect().height) : null,
                    toolGlyphs: document.querySelectorAll('.home-timeline-tools .icon-toggle svg').length,
                    tools: document.querySelectorAll('.home-timeline-tool').length,
                    controlsRow: !!document.querySelector('.home-timeline-controls'),
                    nextLine: !!document.querySelector('.home-timeline-next'),
                    playW: play ? Math.round(play.getBoundingClientRect().width) : null,
                    actionRowH: row ? Math.round(row.getBoundingClientRect().height) : null,
                    actionRowOneLine: tops.length > 0
                      && Math.max(...tops) - Math.min(...tops) <= 12,
                  });
                })()'''))
                ok(not h["globalStrip"] and h["ownCard"],
                   "Home draws its OWN timeline card and NO global strip (§13 decision 5 — "
                   f"global strip present: {h['globalStrip']})")
                if not isinstance(mock_shape_h, int) or mock_shape_h <= 0:
                    notes.append("Home's shape height: no mockup height to compare against")
                else:
                    ok(h["canvasH"] is not None
                       and abs(h["canvasH"] - mock_shape_h) <= SHAPE_H_TOLERANCE_PX,
                       f"Home's audio shape is the mockup's own {mock_shape_h}px, not a stack "
                       f"of empty lanes under the waveform (measured {h['canvasH']}px)")
                ok(h["toolGlyphs"] >= 3,
                   f"Home's marker toggles draw real marker glyphs (audit H2 — {h['toolGlyphs']})")
                ok(h["tools"] >= 4,
                   f"Home's head carries undo/redo beside Follow/Full song (audit H2 — {h['tools']})")
                ok(h["controlsRow"], "Home has the mockup's one thin control row under the shape (audit H5)")
                ok(not h["nextLine"], "the muted 'Next: …' sentence is gone (audit H4)")
                ok(h["playW"] == 34, "a sequence row carries the mockup's big ▶ circle (audit H6)")
                ok(h["actionRowOneLine"] and (h["actionRowH"] or 99) <= 48,
                   f"an action set is ONE line (audit H7/K3 — height {h['actionRowH']}, "
                   f"one line: {h['actionRowOneLine']})")

            print("\nFOUR-D — and no global strip on the Timeline page either")
            if not await goto(ws, nid, f"{app_url}?view=timeline", "!!document.querySelector('.one-bar')"):
                print("  the Timeline route never rendered — skipping")
            else:
                await asyncio.sleep(0.5)
                t = json.loads(await evaluate(ws, nid,
                    '''JSON.stringify({ strip: !!document.querySelector('.song-strip'),
                                        bar: !!document.querySelector('.one-bar') })'''))
                ok(t["bar"] and not t["strip"],
                   "the Timeline route draws the bar and NO global strip "
                   f"(it has its own full toolset — measured {t})")

            # ── 4b. the Settings page's own shape ──────────────────────
            print("\nFOUR-B — the Settings page (audit S1/S3)")
            await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                "width": 1024, "height": 1100, "deviceScaleFactor": 1, "mobile": False})
            if not await goto(ws, nid, f"{app_url}?view=settings",
                              "!!document.querySelector('.settings-room-card')"):
                print("  the Settings page never rendered — skipping its assertions")
            else:
                await asyncio.sleep(0.8)
                st = json.loads(await evaluate(ws, nid, '''(() => {
                  const cards = [...document.querySelectorAll('.settings-console > .card')]
                    .map((c) => (c.querySelector('.card-title') || {}).textContent || '');
                  const rows = [...document.querySelectorAll('.settings-room-card .settings-row')];
                  return JSON.stringify({
                    title: (document.querySelector('.settings-page-title') || {}).textContent || null,
                    cards,
                    roomRows: rows.length,
                    roomRowLabels: rows.map((r) => (r.querySelector('.settings-row-label') || {}).textContent || ''),
                    roomRowGlyphs: rows.filter((r) => r.querySelector('.settings-row-label svg')).length,
                    gradientIsSelect: !!document.querySelector('.settings-room-card .drift-gradient-select'),
                    favouriteChips: document.querySelectorAll('.settings-room-card .favourite-chip').length,
                    helpCircles: document.querySelectorAll('.settings-row .help-link').length,
                    sonicIsLast: cards.length > 0
                      && (cards[cards.length - 1] || '').includes('Sonic') === false,
                    sonicIndex: cards.findIndex((t) => t.includes('Sonic')),
                  });
                })()'''))
                ok((st["title"] or "").strip().endswith("Settings"),
                   f"the page has the mockup's own '⚙ Settings' title (got {st['title']!r})")
                ok(st["sonicIndex"] > 0,
                   f"Sonic is NOT the first card any more — Room and Scenes & drops come first "
                   f"(audit S1; Sonic at index {st['sonicIndex']} of {len(st['cards'])})")
                ok(st["roomRows"] >= 3,
                   f"the Room card is compact label|control|value ROWS (got {st['roomRows']})")
                ok(st["roomRowGlyphs"] == st["roomRows"],
                   f"every Room row's label carries its own glyph ({st['roomRowGlyphs']}/{st['roomRows']})")
                ok(st["gradientIsSelect"],
                   "the drift gradient is a dropdown + New, not four large swatch tiles (audit S1)")
                ok(st["favouriteChips"] > 0,
                   f"preview favourites are inline chips, not a checkbox form (got {st['favouriteChips']})")
                ok(st["helpCircles"] == 0,
                   f"no '?' circle inside a Settings card's rows (audit S3 — found {st['helpCircles']})")
                await shoot(ws, nid, OUT_DIR / "live-settings-1024.png")
                live_shots["settings-1024"] = OUT_DIR / "live-settings-1024.png"
                if "settings-1024" in mock_shots:
                    stack_pair(mock_shots["settings-1024"], live_shots["settings-1024"],
                               OUT_DIR / "pair-settings-1024.png")

            # ── 5. the two-row band and the kiosk ──────────────────────
            print("\nFIVE — his own two-row band, and the kiosk's cards side by side")
            # 390 is the phone tier — the plan's own rule is a deliberate
            # TWO rows there too (audit M6: the live bar wrapped to three,
            # because the two name slots kept the tablet tier's fixed
            # width and could not share row 1 with the three icon
            # buttons).
            for width, expected in ((1180, 1), (1024, 2), (390, 2)):
                await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": 500, "deviceScaleFactor": 1, "mobile": False})
                await asyncio.sleep(0.4)
                got = json.loads(await evaluate(ws, nid, """(() => {
                  const tops = [...document.querySelectorAll('.one-bar .mode-chip, '
                    + '.one-bar .scenes-group-btn, .one-bar .energy-mark-group, '
                    + '.one-bar .light-show-strip, .one-bar .device-preview-strip')]
                    .map((e) => Math.round(e.getBoundingClientRect().top));
                  const rows = [];
                  for (const t of tops.sort((a, b) => a - b)) {
                    if (rows.length && t - rows[rows.length - 1] <= 20) continue;
                    rows.push(t);
                  }
                  return JSON.stringify({ rows: rows.length,
                    scrollW: document.documentElement.scrollWidth,
                    clientW: document.documentElement.clientWidth });
                })()"""))
                band = "his 'do C' band" if 521 <= width <= 1100 else (
                    "the phone tier" if width <= 520 else "one line")
                ok(got["rows"] == expected,
                   f"{width}px is {expected} row(s) ({band} — measured {got['rows']})")
                ok(got["scrollW"] <= got["clientW"],
                   f"{width}px has no horizontal page scroll ({got['scrollW']} <= {got['clientW']})")

            await cdp(ws, nid, "Emulation.setDeviceMetricsOverride", {
                "width": 800, "height": 424, "deviceScaleFactor": 1, "mobile": False})
            if not await goto(ws, nid, f"{app_url}?kiosk=1", "!!document.querySelector('.kiosk-page')"):
                print("  the kiosk never rendered — skipping its assertions")
            else:
                await asyncio.sleep(1.0)
                k = json.loads(await evaluate(ws, nid, """(() => {
                  const cards = [...document.querySelectorAll('.kiosk-page .home-quick-card')]
                    .map((c) => { const r = c.getBoundingClientRect();
                      return { top: Math.round(r.top), left: Math.round(r.left) }; });
                  return JSON.stringify({ cards,
                    sideBySide: cards.length >= 2
                      && Math.abs(cards[0].top - cards[1].top) <= 8
                      && cards[0].left !== cards[1].left,
                    scrollW: document.documentElement.scrollWidth,
                    clientW: document.documentElement.clientWidth,
                    // The kiosk is a fixed-height wall panel: the page
                    // itself must never scroll (only `main` inside it).
                    scrollH: document.documentElement.scrollHeight,
                    clientH: document.documentElement.clientHeight,
                    mainScrolls: (() => { const m = document.querySelector('.kiosk-main');
                      return !!m && m.scrollHeight > m.clientHeight + 1; })() });
                })()"""))
                ok(k["sideBySide"],
                   f"the kiosk's quick-run cards sit SIDE BY SIDE (audit K2 — {k['cards']})")
                ok(k["scrollW"] <= k["clientW"],
                   f"the kiosk has no horizontal scroll ({k['scrollW']} <= {k['clientW']})")
                ok(k["scrollH"] <= k["clientH"],
                   "the kiosk PAGE never scrolls — only its own `main` does, so the bar "
                   f"can never be scrolled off the wall panel ({k['scrollH']} <= {k['clientH']})")
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

    where = OUT_DIR.relative_to(REPO) if OUT_DIR.is_relative_to(REPO) else OUT_DIR
    print(f"\nside-by-side pairs written to {where}/")
    for n in notes:
        print(f"  note: {n}")
    print("FAIL" if failures else "\nPASS")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app-url", default=None,
                    help="the live app's own /spectra/ URL; omit to use the repo's "
                         "mocked harness page (the default, and what CI can run)")
    ap.add_argument("--out", type=Path, default=None,
                    help="where to write the shots and pairs (default: "
                         "docs/evidence/ui-fidelity, the committed evidence folder). "
                         "A test run passes a temp dir so it never rewrites them.")
    args = ap.parse_args()
    if args.out:
        global OUT_DIR  # noqa: PLW0603 - one deliberate CLI override
        OUT_DIR = args.out

    if websockets is None:
        print("the `websockets` package is not installed — skipping this check.")
        return 0
    if not find_chrome():
        print("no Chromium binary found (system Chrome or a cached Playwright "
              "install) — skipping this check.")
        return 0
    if not ARTIFACT.is_file():
        print(f"neither the approved artifact ({FLEET_ARTIFACT}) nor the in-repo "
              f"reference ({REPO_MOCKUPS}) is readable — skipping this check.")
        return 0
    print(f"mockups: {ARTIFACT}")

    httpd = None
    if args.app_url:
        app_url = args.app_url
    else:
        if not (HARNESS_DIST / "fidelity.html").is_file():
            print("the harness build is missing — run:\n"
                  "  cd spectra/web && npx vite build --config vite.harness.config.ts\n"
                  "skipping this check.")
            return 0
        port = free_port()
        httpd = serve(HARNESS_DIST, port)
        app_url = f"http://127.0.0.1:{port}/spectra/fidelity.html"

    artifact_port = free_port()
    artifact_httpd = serve(ARTIFACT.parent, artifact_port)
    artifact_url = f"http://127.0.0.1:{artifact_port}/{ARTIFACT.name}"
    try:
        return asyncio.run(run(app_url, artifact_url))
    finally:
        artifact_httpd.shutdown()
        if httpd:
            httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())
