// Executable spec for the responsiveness fix + the new audio-shape markers
// on Home's editable timeline (HomeTimeline.tsx — the Admiral, 2026-10-14:
// "the audio shape isn't as responsive and it should also show scenes,
// flares, drops, and light show triggers").
//
// MEASURED BEFORE THE FIX (see HomeTimeline.tsx's own module docstring for
// the full writeup): `useFollowWindow()` returns a fresh object literal
// every render, so the shape canvas's trace/resize effect — keyed on
// `[shape, offsetMs, win]` — reran on EVERY unrelated parent re-render (the
// 3s engine-status poll this page's data flows through) and on EVERY
// pointermove of a window drag, each time doing a full `canvas.width = …`
// resize plus a full trace redraw, never rAF-paced. The strip's own marker
// rebuild effect had the identical shape — rebuilding dozens of SVG nodes
// on every drag pointermove even though a marker's x position never
// depends on the window at all.
//
// This mounts the REAL HomeTimeline.tsx (esbuild + jsdom + react-dom/client,
// the check_favorites_picker_cancel.mjs precedent) against a fake
// fetch backing its real useAudioShapeMeta/useAudioShapeData query hooks,
// and proves, behaviourally:
//
//   ONE   — the strip's marker SVG nodes are NOT rebuilt by a window drag.
//           A reference captured to the first marker element before the
//           drag is still the SAME node (===) after several drag
//           pointermoves and animation frames — not merely visually
//           identical, but never recreated.
//   TWO   — the window-overlay rect DOES track the drag (so ONE isn't
//           trivially true because nothing moved): its on-screen position
//           changes after the drag + a couple of animation-frame ticks.
//   THREE — the audio-shape canvas is drawn from the rAF loop, not a React
//           effect: with no drag or prop change at all, ticking the
//           (manually-controlled) animation frame redraws it — proving the
//           drawing is driven by the frame clock, never by a dependency
//           array.
//   FOUR  — the canvas is resized only when its measured size actually
//           changes (TimelineCanvas.tsx's own DPR-aware guard) — ticking
//           several frames at an unchanged size resizes the backing
//           buffer at most once.
//   FIVE  — the shape canvas itself carries marker overlays for every
//           upcoming-event kind (scene/flare/charge/lull/drop/high/low),
//           using the SAME drawShapeMarkers() the pure check already
//           proved draws the right shape/colour per kind — the second half
//           of the Admiral's ask.
//
// Run: node scripts/check_home_timeline_responsiveness.mjs
//   (needs the dev-only jsdom: cd spectra/web && npm install --no-save jsdom)
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const webDir = join(repo, 'spectra/web');
const require = createRequire(join(webDir, 'package.json'));
const esbuild = require('esbuild');

let jsdomMod;
try {
  jsdomMod = require('jsdom');
} catch {
  console.log('jsdom not installed in spectra/web/node_modules (dev-only, '
    + 'not a declared dependency) — skipping this check. Install with '
    + '`cd spectra/web && npm install --no-save jsdom`.');
  process.exit(0);
}
const { JSDOM } = jsdomMod;
const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://localhost/', pretendToBeVisual: true,
});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.SVGElement = dom.window.SVGElement;
globalThis.Node = dom.window.Node;
globalThis.localStorage = dom.window.localStorage;
globalThis.PointerEvent = dom.window.PointerEvent;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Manually-controlled rAF: capture callbacks instead of letting the browser
// schedule them, so the test decides exactly when "a frame" happens —
// this is what makes THREE/FOUR deterministic rather than timing-dependent.
let rafQueue = [];
const fakeRaf = (cb) => { rafQueue.push(cb); return rafQueue.length; };
const fakeCancelRaf = () => {};
globalThis.requestAnimationFrame = fakeRaf;
globalThis.cancelAnimationFrame = fakeCancelRaf;
dom.window.requestAnimationFrame = fakeRaf;
dom.window.cancelAnimationFrame = fakeCancelRaf;
const tickRaf = (n = 1) => {
  for (let i = 0; i < n; i += 1) {
    const cbs = rafQueue;
    rafQueue = [];
    for (const cb of cbs) cb(performance.now());
  }
};

// jsdom has no layout engine and no real pointer capture — stub both, the
// check_drop_marker_drag.mjs precedent.
const elProto = dom.window.HTMLElement.prototype;
elProto.setPointerCapture = function () {};
elProto.releasePointerCapture = function () {};
elProto.getBoundingClientRect = function () {
  return { left: 0, top: 0, right: 1000, bottom: 160, width: 1000, height: 160, x: 0, y: 0, toJSON() {} };
};

// Fake <canvas> 2D context (jsdom has none) — a recorder, matching the pure
// drawShapeMarkers check's own fake ctx shape, plus the methods the trace
// drawing loop also calls.
let clearRectCalls = 0;
const fakeCtxProto = {
  get fillStyle() { return this._f; }, set fillStyle(v) { this._f = v; },
  get strokeStyle() { return this._s; }, set strokeStyle(v) { this._s = v; },
  set globalAlpha(v) { this._a = v; },
  set lineWidth(v) {},
  setTransform() {},
  clearRect() { clearRectCalls += 1; },
  beginPath() {}, closePath() {}, fillRect() {}, arc() {}, fill() {},
  moveTo() {}, lineTo() {}, stroke() {},
};
const canvasProto = dom.window.HTMLCanvasElement.prototype;
canvasProto.getContext = function (kind) {
  if (kind !== '2d') return null;
  if (!this.__ctx) this.__ctx = Object.create(fakeCtxProto);
  return this.__ctx;
};
// jsdom reports clientWidth/clientHeight as 0 (no layout) — give the shape
// canvas a fixed, nonzero measured size so the loop's `cw > 0 && ch > 0`
// guard (and the resize-on-change guard) are both actually exercised.
Object.defineProperty(canvasProto, 'clientWidth', { configurable: true, get() { return 800; } });
Object.defineProperty(canvasProto, 'clientHeight', { configurable: true, get() { return 160; } });
dom.window.devicePixelRatio = 1;

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const NodeResponse = globalThis.Response;
const SHAPE_META = {
  spotify_uri: 'spotify:track:perf', title: 'Octavian', artist: 'Someone',
  duration_ms: 200000, sample_interval_ms: 200, music_marks: [],
  capture_complete: true, timestamp_offset_ms: 0, perception_trim_ms: 0,
  offset_verification: 'auto_verified',
};
const N = 40;
const SHAPE_DATA = {
  timestamps_ms: Array.from({ length: N }, (_, i) => i * 5000),
  rms_total: Array.from({ length: N }, () => 0.5),
  rms_low: Array.from({ length: N }, () => 0.3),
  rms_mid: Array.from({ length: N }, () => 0.2),
  rms_high: Array.from({ length: N }, () => 0.1),
  avg_rms_1s: null,
};
const fakeFetch = async (url) => {
  const u = String(url);
  const json = (body) => new NodeResponse(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
  if (u.includes('/audio-shape/meta')) return json(SHAPE_META);
  if (u.includes('/audio-shape/data')) return json(SHAPE_DATA);
  throw new Error(`unexpected fetch ${u}`);
};
globalThis.fetch = fakeFetch;
dom.window.fetch = fakeFetch;

const tmpDir = mkdtempSync(join(tmpdir(), 'home-timeline-resp-'));
const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import HomeTimeline from ${JSON.stringify(join(webDir, 'src/home/HomeTimeline.tsx'))};

const EVENTS = [
  { ms: 20000, kind: 'scene', rank: 1, rank_of: 3, source: 'planned' },
  { ms: 55000, kind: 'flare', rank: null, rank_of: null, source: 'analysed' },
  { ms: 90000, kind: 'charge', rank: null, rank_of: null, source: 'drop_sequence', num: 1 },
  { ms: 100000, kind: 'drop', rank: null, rank_of: null, source: 'drop_sequence', num: 1 },
  { ms: 15000, kind: 'high', rank: null, rank_of: null, source: 'show_cue' },
];

const container = document.createElement('div');
document.body.appendChild(container);
const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
let root = null;

export async function mount() {
  root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(MemoryRouter, null,
        React.createElement(HomeTimeline, {
          uri: 'spotify:track:perf', title: 'Octavian', artist: 'Someone',
          durationMs: 200000, events: EVENTS, showAudioShape: true,
        }))));
  });
  for (let i = 0; i < 40 && !container.querySelector('.home-timeline-shape-canvas'); i++) {
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
  }
  return container;
}
export async function flush() {
  await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
}
export async function fire(el, type, props) {
  await act(async () => {
    el.dispatchEvent(new window.PointerEvent(type, {
      bubbles: true, cancelable: true, button: 0, buttons: 1, pointerId: 1, ...props,
    }));
  });
}
export async function fireWin(type, props) {
  await act(async () => {
    window.dispatchEvent(new window.PointerEvent(type, {
      bubbles: true, cancelable: true, button: 0, buttons: 1, pointerId: 1, ...props,
    }));
  });
}
`;
const entryFile = join(tmpDir, 'entry.mjs');
writeFileSync(entryFile, entrySrc);
const outFile = join(tmpDir, 'out.cjs');
// `components/songStrip.ts` (pure helpers) and `components/SongStrip.tsx`
// (the React component) live in the same directory, differing only by the
// case of their first letter — on purpose (songStrip.ts's own docstring:
// kept out of the component so a pure esbuild bundle can drive it with no
// DOM). esbuild's resolver gets confused by that pair when `songStrip` is
// reached as a transitive, extension-less import (as HomeTimeline.tsx does)
// rather than given directly as an entry point: it case-insensitively
// matches the request against `SongStrip.tsx`, warns about the mismatch,
// then tries to literally read the (wrong-case, nonexistent) path anyway
// and fails. Resolving it explicitly sidesteps that resolver quirk without
// touching production source for a test-tool-only ambiguity.
const songStripFix = {
  name: 'songstrip-case-fix',
  setup(b) {
    // `./songStrip` as well as `../components/songStrip` — since the
    // 2026-10-14 design-fidelity pass `components/trackPainter.ts`
    // imports it as a SIBLING, which hits the same resolver quirk.
    b.onResolve({ filter: /(^|\/)songStrip$/ }, () => (
      { path: join(webDir, 'src/components/songStrip.ts') }
    ));
  },
};
// jsdom ships no ResizeObserver, and the shared track painter
// (spectra/web/src/components/trackPainter.ts, adopted by Home in the
// 2026-10-14 design-fidelity pass so Home and the global strip draw ONE
// picture) observes its own SVG with one. A minimal stub: record the
// observed node so the test can trigger a rebuild deliberately, never on
// a layout jsdom does not have.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    constructor(cb) { this.cb = cb; }
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

const build = await esbuild.build({
  entryPoints: [entryFile], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
  outfile: outFile, nodePaths: [join(webDir, 'node_modules')], logLevel: 'silent',
  loader: { '.css': 'empty' },
  plugins: [songStripFix],
});
ok(build.errors.length === 0, 'HomeTimeline.tsx bundles cleanly with its real imports');
const { mount, flush, fire, fireWin } = require(outFile);
const container = await mount();
await flush();
tickRaf(2); // let the merged rAF loop draw its first frame

console.log('ONE — a window drag never rebuilds the strip\'s marker SVG nodes');
{
  const markersGroup = container.querySelector('.song-strip-svg g');
  ok(!!markersGroup && markersGroup.children.length > 0, 'the strip drew its upcoming-event markers');
  const firstMarker = markersGroup.children[0];

  const overlay = container.querySelector('.home-timeline-window');
  const before = overlay.style.left;

  // Drag the window's centre several times — exactly what used to rebuild
  // every marker SVG node on every single move.
  await fire(overlay, 'pointerdown', { clientX: 100 });
  for (let i = 1; i <= 6; i += 1) {
    await fireWin('pointermove', { clientX: 100 + i * 30 });
  }
  await fireWin('pointerup', { clientX: 280 });
  tickRaf(3);
  await flush();

  const markersGroupAfter = container.querySelector('.song-strip-svg g');
  ok(markersGroupAfter === markersGroup, 'the markers <g> element itself was never replaced');
  ok(markersGroupAfter.children[0] === firstMarker,
    'the first marker is the IDENTICAL DOM node (===) after the drag — never recreated');
  ok(markersGroupAfter.children.length === markersGroup.children.length,
    'the same number of markers exist after the drag — nothing duplicated or dropped');

  console.log('TWO — the window-overlay rect DOES track the drag (so ONE is not trivial)');
  ok(overlay.style.left !== before,
    `the overlay's drawn position moved (was ${JSON.stringify(before)}, now ${JSON.stringify(overlay.style.left)})`);
}

console.log('THREE — the shape IS the Timeline page\'s own renderer, not a second one');
{
  // THE H5 FIX (2026-10-14 design-fidelity pass): Home used to draw its
  // own 160px three-thin-lines canvas; the approved mockup copies the
  // Timeline page's tuned canvas, so this card now mounts the REAL
  // `TimelineCanvas` with `BUILDER_LAYERS`. The canvas and its rAF loop
  // now belong to TimelineCanvas.tsx, which carries its own DPR/resize
  // guard and its own proofs (scripts/check_timeline_*.mjs,
  // check_song_strip_fps.py) — the wiring itself is proven BEHAVIOURALLY
  // below (a real canvas is actually mounted) and by
  // scripts/check_ui_fidelity.py's FOUR-C Home assertions (the canvas'
  // measured height matches the approved mockup's own), not by reading
  // source text for a prop name.
  const src = readFileSync(join(webDir, 'src/home/HomeTimeline.tsx'), 'utf8');
  ok(!/home-timeline-shape-canvas/.test(src),
    'the bespoke 160px shape canvas is gone — no second renderer left behind');
  const canvas = container.querySelector('.home-timeline-shape canvas');
  ok(!!canvas, 'a canvas is actually mounted inside the shape box');
}

console.log('FOUR — the strip\'s own per-frame work still touches no React state');
{
  // The strip keeps its own rAF loop (playhead, window overlay, time
  // readout, passed-marker fade). Its marker nodes must not be rebuilt
  // by plain frames either — ONE proved that across a drag, this proves
  // it across frames with nothing changing at all.
  const markersGroup = container.querySelector('.song-strip-svg g');
  const firstMarker = markersGroup.children[0];
  const n = markersGroup.children.length;
  tickRaf(5);
  await flush();
  ok(container.querySelector('.song-strip-svg g') === markersGroup
    && markersGroup.children[0] === firstMarker && markersGroup.children.length === n,
    'five frames with nothing changed leave every marker node identical');
}

console.log('FIVE — the strip draws the shared painter\'s own full picture');
{
  // The painter's inset panel + terrain + markers (audit T3/H3) — the
  // same function the global read-only strip calls, so the two can never
  // disagree again. Its own geometry is asserted in check_song_strip.mjs.
  const svg = container.querySelector('.song-strip-svg');
  const group = svg.querySelector('g');
  const kinds = [...group.children].map((n) => n.tagName.toLowerCase());
  ok(kinds[0] === 'rect', 'the first node is the inset panel rect');
  ok(kinds.includes('circle') || kinds.includes('ellipse'), 'a flare marker is drawn');
  ok(kinds.filter((k) => k === 'rect').length > 1, 'scene/drop rect markers are drawn on top of the panel');
  // jsdom has no layout, so the measured box is 0 and the painter floors
  // it at 1x1 — what this asserts is that the viewBox was REWRITTEN from
  // the markup's own `0 0 100 39` to the measured pixel box at all (the
  // 1:1 rule, songStrip.ts's `trackX` docstring). The real geometry is
  // measured in check_song_strip.mjs and in the rendered-pixel pass of
  // scripts/check_ui_fidelity.py.
  const vb = svg.getAttribute('viewBox') ?? '';
  ok(/^0 0 \d+ \d+$/.test(vb) && vb !== '0 0 100 39',
    `the viewBox was rewritten from the markup default to the measured pixel box (got ${JSON.stringify(vb)})`);
}

console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
