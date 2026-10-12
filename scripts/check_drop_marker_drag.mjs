// Executable spec for THE DRAGGABLE DROP MARK on a scene's drop-sequence
// preview (2026-10-12, the Admiral: "I wanted to be able to edit red line
// for the drop in the preview drop sequence page for a scene, but I cannot
// click it and drag it ... the view is pretty crowded and it's hard to
// click on anything, and also, it should work on a touch screen (tablet)").
//
//   §1  dropMarkDrag.ts, the pure arithmetic: offset from ruler seconds
//       (left = earlier = negative), the 10 ms grid, the magnets (on the
//       mark, the room's value), the legal clamp, the lull floor the server
//       applies, the nudge steps.
//   §2  PreviewRuler.tsx, the REAL component under jsdom: the handle lives
//       in its own lane below the ruler, the line's own grab strip is
//       narrow (a press beside it still scrubs), a touch drag keeps the
//       grab offset (no jump on the first move), only the grabbing pointer
//       drives or ends it (a resting palm cannot), pointercancel cancels
//       rather than commits, ←/→ step it, and the SVG is touch-action:none
//       so the page never scrolls under a drag.
//   §3  SequencePreviewOverlay.tsx, the REAL component (fetch intercepted):
//       a touch drag of the handle writes the scene draft's drop timing,
//       the nudge buttons step from the offset in force, "Room's" puts the
//       scene back on null, the preview request carries the draft value,
//       and the panel says when it is not saved yet.
//
// Run: node scripts/check_drop_marker_drag.mjs   (needs the dev-only jsdom:
//   cd spectra/web && npm install --no-save jsdom)
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const webDir = join(repo, 'spectra/web');
const require = createRequire(join(webDir, 'package.json'));
const esbuild = require('esbuild');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const tmpDir = mkdtempSync(join(tmpdir(), 'drop-marker-drag-'));

async function bundle(entrySrc, tag) {
  const entryFile = join(tmpDir, `entry-${tag}.mjs`);
  writeFileSync(entryFile, entrySrc);
  const outFile = join(tmpDir, `out-${tag}.cjs`);
  const build = await esbuild.build({
    entryPoints: [entryFile], bundle: true, format: 'cjs', platform: 'node',
    jsx: 'automatic', loader: { '.css': 'empty' }, outfile: outFile,
    nodePaths: [join(webDir, 'node_modules')], logLevel: 'silent',
  });
  ok(build.errors.length === 0, build.errors.length === 0
    ? `${tag}: bundles cleanly with its real imports`
    : `${tag}: bundle failed: ${build.errors.map((e) => e.text).join('; ')}`);
  return require(outFile);
}

/* ── §1 the pure arithmetic ── */
console.log('§1 dropMarkDrag.ts — the drag\'s arithmetic');
const D = await bundle(
  `export * from ${JSON.stringify(join(webDir, 'src/scenes/tabs/dropMarkDrag.ts'))};`, 'pure');
{
  const info = { offset_ms: -400, applied_ms: -400, source: 'room', scene_offset_ms: null,
                 room_offset_ms: -400, min_ms: -2000, max_ms: 2000, floor_applied_ms: -1500 };
  ok(D.offsetAtS(9.6, 10) === -400, 'a line 0.4 s LEFT of the music mark is −400 ms (earlier = negative)');
  ok(D.offsetAtS(10.12, 10) === 120, 'a line right of the mark is a positive (later) offset');
  const nearRoom = D.snapOffsetMs(-421, D.magnetsFor(info));
  ok(nearRoom.ms === -400 && nearRoom.snappedTo === -400,
    'within 30 ms of the room\'s value the drag is pulled exactly onto it');
  const nearZero = D.snapOffsetMs(18, D.magnetsFor(info));
  ok(nearZero.ms === 0 && nearZero.snappedTo === 0, 'within 30 ms of the mark it lands exactly on 0');
  const grid = D.snapOffsetMs(-517, D.magnetsFor(info));
  ok(grid.ms === -520 && grid.snappedTo === null, 'elsewhere it lands on the 10 ms grid (−517 → −520)');
  ok(D.dragToOffset(5, 10, info).ms === -2000, 'a drag past the legal range stops at −2000');
  ok(D.dragToOffset(14, 10, info).ms === 2000, '… and at +2000 the other way');
  ok(D.appliedOffsetMs(-1800, info) === -1500,
    'an offset past the lull\'s floor is drawn where the server will draw it');
  ok(D.appliedOffsetMs(300, info) === 300, 'a later-than-mark offset is never clamped by the floor');
  ok(Math.abs(D.markSForOffset(-400, 10, info) - 9.6) < 1e-9, 'markSForOffset inverts offsetAtS');
  ok(D.nudgeOffsetMs(-400, -50, info) === -450 && D.nudgeOffsetMs(1990, 50, info) === 2000,
    'a nudge steps from the offset in force and is clamped');
  ok(D.effectiveOffsetMs(null, info) === -400 && D.effectiveOffsetMs(-250, info) === -250,
    'null = the room\'s value; a scene value wins');
  ok(D.signedMs(-400) === '−400 ms' && D.signedMs(30) === '+30 ms' && D.signedMs(0) === '0 ms',
    'the handle readout carries a true minus sign');
  ok(D.offsetWords(-400) === '400 ms early' && D.offsetWords(0) === 'on the mark',
    'the spoken value');
  ok(JSON.stringify(D.NUDGE_STEPS) === '[-50,-10,10,50]', 'the nudge buttons are −50/−10/+10/+50 ms');
}

/* ── jsdom for §2/§3 ── */
let jsdomMod;
try {
  jsdomMod = require('jsdom');
} catch {
  console.log('jsdom not installed in spectra/web/node_modules (dev-only, not a declared '
    + 'dependency) — skipping §2/§3. Install with `cd spectra/web && npm install --no-save jsdom`.');
  console.log(failures ? `\nFAIL — ${failures} check(s) failed` : '\nPASS (§1 only)');
  process.exit(failures ? 1 : 0);
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
globalThis.KeyboardEvent = dom.window.KeyboardEvent;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
dom.window.requestAnimationFrame = globalThis.requestAnimationFrame;
dom.window.cancelAnimationFrame = globalThis.cancelAnimationFrame;
dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {},
  addListener() {}, removeListener() {} });
globalThis.matchMedia = dom.window.matchMedia;
// jsdom has no layout and no pointer capture: the ruler's SVG is given a
// 680-px box at x=0 (1 viewBox unit = 1 px), so ruler seconds are exact.
const svgProto = dom.window.SVGElement.prototype;
svgProto.setPointerCapture = function () {};
svgProto.releasePointerCapture = function () {};
svgProto.getBoundingClientRect = function () {
  return { left: 0, top: 0, right: 680, bottom: 152, width: 680, height: 152, x: 0, y: 0, toJSON() {} };
};

const fire = (el, type, props) => {
  el.dispatchEvent(new dom.window.PointerEvent(type, {
    bubbles: true, cancelable: true, button: 0, buttons: 1, ...props,
  }));
};
const fireWin = (type, props) => {
  dom.window.dispatchEvent(new dom.window.PointerEvent(type, {
    bubbles: true, cancelable: true, button: 0, buttons: 1, ...props,
  }));
};
const fireKey = (el, props) => el.dispatchEvent(
  new dom.window.KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...props }));

// Ruler geometry: PAD_X 16, RULER_W 680 → 648 usable units.
const DUR = 10;
const sToX = (s) => 16 + (s / DUR) * 648;

/* ── §2 the real PreviewRuler ── */
console.log('§2 PreviewRuler.tsx — the drag mark under a finger');
{
  const R = await bundle(`
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import PreviewRuler from ${JSON.stringify(join(webDir, 'src/scenes/tabs/PreviewRuler.tsx'))};
const container = document.createElement('div');
document.body.appendChild(container);
let root = null;
export function mount(props) {
  if (!root) root = createRoot(container);
  act(() => { root.render(React.createElement(PreviewRuler, props)); });
  return container;
}
export { act };
`, 'ruler');
  const log = [];
  const props = (over = {}) => ({
    durationS: DUR, playheadS: 1, triggerMarkS: null,
    bands: [{ from_s: 6, to_s: 8.6, label: 'lull ramp', tone: 'accent' }],
    marks: [{ at_s: 6, label: 'lull', tone: 'hot' }],
    onScrub: (s) => log.push(['scrub', s]),
    dragMark: {
      at_s: 8.6, label: 'drop', readout: '−400 ms', valueText: '400 ms early', title: 'drag',
      active: false,
      onDrag: (s) => log.push(['drag', s]),
      onDragEnd: (s) => log.push(['end', s]),
      onDragCancel: () => log.push(['cancel']),
      onStep: (dir, big) => log.push(['step', dir, big]),
    },
    dragRef: { at_s: 9, label: 'mark' },
    ...over,
  });
  const c = R.mount(props());
  const svg = c.querySelector('svg');
  ok(svg.style.touchAction === 'none', 'the ruler SVG is touch-action:none — the page never scrolls under a drag');
  ok(svg.getAttribute('viewBox') === '0 0 680 152',
    'a 44-unit handle lane is added under the 108-unit ruler (viewBox 680×152)');
  const handle = c.querySelector('[data-testid="drag-mark-handle"]');
  const handleRect = handle.querySelector('rect');
  ok(+handleRect.getAttribute('y') >= 108,
    'the handle sits in its own lane, below every band, tick and mark label');
  ok(+handleRect.getAttribute('width') >= 44 && +handleRect.getAttribute('height') >= 32,
    `the handle is finger-sized (${handleRect.getAttribute('width')}×${handleRect.getAttribute('height')})`);
  ok(handle.getAttribute('role') === 'slider' && handle.getAttribute('tabindex') === '0'
     && handle.getAttribute('aria-valuetext') === '400 ms early',
    'the handle is a focusable slider that says its value');
  ok(handle.textContent.includes('drop −400 ms'), 'the handle names the mark and shows the offset itself');
  const strip = c.querySelector('[data-testid="drag-mark-line"]');
  const stripW = +strip.getAttribute('width');
  ok(stripW >= 14 && stripW <= 24, `the line's own grab strip is ${stripW} units — enough to hit, not a wall`);
  const markGroup = c.querySelector('[data-testid="drag-mark"]');
  ok(svg.lastElementChild === markGroup, 'the drag mark is drawn LAST — above every other layer');
  ok(!!c.querySelector('[data-testid="drag-ref"]'), 'the music\'s own mark is drawn as a reference line');

  // a press BESIDE the line (outside its strip) scrubs, it does not grab
  log.length = 0;
  fire(svg, 'pointerdown', { pointerId: 1, pointerType: 'touch', clientX: sToX(8.6) - 20, clientY: 50 });
  fireWin('pointerup', { pointerId: 1, pointerType: 'touch', clientX: sToX(8.6) - 20, clientY: 50 });
  ok(log.length > 0 && log.every((e) => e[0] === 'scrub'),
    'a press 20 units beside the line scrubs — the mark steals nothing it is not on');

  // a touch drag of the handle, grabbed 12 units right of the line
  log.length = 0;
  fire(handleRect, 'pointerdown', { pointerId: 7, pointerType: 'touch', clientX: sToX(8.6) + 12, clientY: 130 });
  ok(log.length === 1 && log[0][0] === 'drag' && Math.abs(log[0][1] - 8.6) < 1e-6,
    'grabbing reports the line where it IS — no jump to the finger');
  fireWin('pointermove', { pointerId: 7, pointerType: 'touch', clientX: sToX(8.6) + 12 - 32.4, clientY: 130 });
  const moved = log.at(-1);
  ok(moved[0] === 'drag' && Math.abs(moved[1] - 8.1) < 1e-6,
    `a 0.5 s finger move moves the line 0.5 s, grab offset kept (${moved[1].toFixed(3)} s)`);
  // a second finger (a resting palm) moves and lifts — it must do nothing
  const before = log.length;
  fireWin('pointermove', { pointerId: 9, pointerType: 'touch', clientX: 20, clientY: 130 });
  fireWin('pointerup', { pointerId: 9, pointerType: 'touch', clientX: 20, clientY: 130 });
  ok(log.length === before, 'a second pointer neither drives nor ends the drag');
  ok(!log.some((e) => e[0] === 'scrub'), 'the drag never scrubs the playhead');
  fireWin('pointerup', { pointerId: 7, pointerType: 'touch', clientX: sToX(8.6) + 12 - 64.8, clientY: 130 });
  const end = log.at(-1);
  ok(end[0] === 'end' && Math.abs(end[1] - 7.6) < 1e-6, 'lifting the grabbing finger commits where it lifted');
  // after it ended, a stray move does nothing
  const n = log.length;
  fireWin('pointermove', { pointerId: 7, pointerType: 'touch', clientX: 300, clientY: 130 });
  ok(log.length === n, 'nothing listens once the gesture has ended');

  // the line strip grabs too
  log.length = 0;
  fire(strip, 'pointerdown', { pointerId: 11, pointerType: 'mouse', clientX: sToX(8.6) + 3, clientY: 50 });
  fireWin('pointermove', { pointerId: 11, pointerType: 'mouse', clientX: sToX(8.6) + 3 + 64.8, clientY: 50 });
  fireWin('pointerup', { pointerId: 11, pointerType: 'mouse', clientX: sToX(8.6) + 3 + 64.8, clientY: 50 });
  ok(log[0][0] === 'drag' && log.at(-1)[0] === 'end' && Math.abs(log.at(-1)[1] - 9.6) < 1e-6
     && !log.some((e) => e[0] === 'scrub'),
    'the red line itself grabs (the thing he tried to click), moving it 1 s right');
  // a right-click does not grab
  log.length = 0;
  fire(strip, 'pointerdown', { pointerId: 12, pointerType: 'mouse', button: 2, clientX: sToX(8.6), clientY: 50 });
  ok(!log.some((e) => e[0] === 'drag'), 'a right mouse button does not grab');
  fireWin('pointerup', { pointerId: 12, pointerType: 'mouse', clientX: sToX(8.6), clientY: 50 });

  // the browser taking the touch cancels — never commits
  log.length = 0;
  fire(handleRect, 'pointerdown', { pointerId: 13, pointerType: 'touch', clientX: sToX(8.6), clientY: 130 });
  fireWin('pointermove', { pointerId: 13, pointerType: 'touch', clientX: sToX(8.6) - 40, clientY: 130 });
  fireWin('pointercancel', { pointerId: 13, pointerType: 'touch' });
  ok(log.at(-1)[0] === 'cancel' && !log.some((e) => e[0] === 'end'),
    'a pointercancel drops the drag instead of committing it');

  // keyboard
  log.length = 0;
  fireKey(handle, { key: 'ArrowLeft' });
  fireKey(handle, { key: 'ArrowRight', shiftKey: true });
  ok(JSON.stringify(log) === JSON.stringify([['step', -1, false], ['step', 1, true]]),
    '←/→ on the handle step it (Shift = the big step)');

  // held: highlighted, readout bubble at the top
  const c2 = R.mount(props({ dragMark: { ...props().dragMark, active: true } }));
  ok(!!c2.querySelector('[data-testid="drag-mark-bubble"]'),
    'while held the readout shows in a bubble at the top (the finger covers the handle)');
  // no dragMark: the ruler is the old one, byte for byte in shape
  const c3 = R.mount(props({ dragMark: null, dragRef: null }));
  ok(c3.querySelector('svg').getAttribute('viewBox') === '0 0 680 108'
     && !c3.querySelector('[data-testid="drag-mark"]'),
    'without a drag mark the ruler keeps its own height and draws no handle (the other previews)');
}

/* ── §3 the real SequencePreviewOverlay ── */
console.log('§3 SequencePreviewOverlay.tsx — the drag writes this scene\'s drop timing');
{
  // React's act() bookkeeping and React Router's v7 notices are noise here:
  // every assertion below waits for the real fetch/render to settle first.
  const quiet = (orig) => (...args) => {
    const text = String(args[0] ?? '');
    if (text.includes('not wrapped in act') || text.includes('React Router Future Flag')) return;
    orig(...args);
  };
  console.error = quiet(console.error);
  console.warn = quiet(console.warn);
  const opens = [];
  const json = (body) => new Response(JSON.stringify(body),
    { status: 200, headers: { 'Content-Type': 'application/json' } });
  const timeline = (body) => {
    const sceneMs = body.drop_timing_offset_ms;
    const offset = sceneMs ?? -400;
    const music = 9.0;
    return {
      scene_id: 's1', scene_name: 'Test', intensity: 1, duration_s: DUR,
      gaps: { charge: 4444, lull: 2778 }, hang_fraction: 0.1,
      drop_timing: { offset_ms: offset, applied_ms: offset,
                     source: sceneMs == null ? 'room' : 'scene', scene_offset_ms: sceneMs ?? null,
                     room_offset_ms: -400, min_ms: -2000, max_ms: 2000, floor_applied_ms: -2000 },
      marks: [
        { event_class: 'charge', mark_s: 1, music_mark_s: 1, fire_at_s: 1, ramp_start_s: 1, ramp_end_s: 5,
          hang_end_s: 5.4, ramp_ms: 4000, hang_ms: 400, gap_ms: 4444, stretched: true,
          trigger_offset_ms: 0, drop_timing_offset_ms: 0, lead_ms: 0, anchor_rule: 'switch_end' },
        { event_class: 'lull', mark_s: 5.4, music_mark_s: 5.4, fire_at_s: 5.4, ramp_start_s: 5.4,
          ramp_end_s: 7.6, hang_end_s: 8.6, ramp_ms: 2200, hang_ms: 238, gap_ms: 2378,
          stretched: true, trigger_offset_ms: 0, drop_timing_offset_ms: 0, lead_ms: 0,
          anchor_rule: 'switch_end' },
        { event_class: 'drop', mark_s: music + offset / 1000, music_mark_s: music,
          fire_at_s: music + offset / 1000, ramp_start_s: music + offset / 1000,
          ramp_end_s: music + offset / 1000 + 0.4, hang_end_s: music + offset / 1000 + 0.4,
          ramp_ms: 400, hang_ms: 0, gap_ms: null, stretched: false, trigger_offset_ms: 0,
          drop_timing_offset_ms: offset, lead_ms: 0, anchor_rule: 'drop_start' },
      ],
      cues: [], phase_targets: ['v1'], drop_switch: null,
    };
  };
  let savedSceneMs = null;
  dom.window.fetch = async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase();
    if (url === '/spectra/api/preview/sequence/open' && method === 'POST') {
      const body = JSON.parse(init.body);
      opens.push(body);
      return json(timeline(body));
    }
    if (url === '/spectra/api/scenes' && method === 'GET') {
      return json([{ id: 's1', name: 'Test', drop_timing_offset_ms: savedSceneMs }]);
    }
    if (url.startsWith('/spectra/api/flare-preview/') || url.startsWith('/spectra/api/preview/')) {
      return json({ active: true, remaining_s: 10 });
    }
    throw new Error(`unexpected fetch ${method} ${url}`);
  };
  globalThis.fetch = dom.window.fetch;
  dom.window.navigator.sendBeacon = () => true;

  const O = await bundle(`
import React, { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import SequencePreviewOverlay from ${JSON.stringify(join(webDir, 'src/scenes/tabs/SequencePreviewOverlay.tsx'))};
import { newScene } from ${JSON.stringify(join(webDir, 'src/types.ts'))};

const container = document.createElement('div');
document.body.appendChild(container);
const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
export const writes = [];
function Host() {
  const [scene, setScene] = useState({ ...newScene('s1'), name: 'Test' });
  return React.createElement(SequencePreviewOverlay, {
    scene, onClose: () => {},
    onDropOffsetChange: (ms) => { writes.push(ms); setScene({ ...scene, drop_timing_offset_ms: ms }); },
  });
}
export async function mount() {
  const root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(MemoryRouter, null, React.createElement(Host))));
  });
  return container;
}
export async function settle(ms = 260) {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)); });
}
`, 'overlay');
  const c = await O.mount();
  await O.settle();
  ok(opens.length >= 1 && 'drop_timing_offset_ms' in opens[0] && opens[0].drop_timing_offset_ms === null,
    'the preview request carries the draft\'s drop timing (null = the room\'s)');
  const value = () => c.querySelector('[data-testid="drop-timing-value"]')?.textContent;
  ok(value() === '−400 ms', `the panel shows the offset in force (${value()})`);
  ok(!c.querySelector('[data-testid="drop-timing-unsaved"]'), 'nothing to save yet');
  const reset = c.querySelector('[data-testid="drop-timing-reset"]');
  ok(reset && reset.disabled, '"Room\'s" is disabled while the scene already uses the room\'s');
  const plainDrop = [...c.querySelectorAll('svg text')].filter((t) => t.textContent === 'drop');
  const handles = c.querySelectorAll('[data-testid="drag-mark-handle"]');
  ok(plainDrop.length === 0 && handles.length === 1,
    'the drop is drawn once — as the draggable mark, not also as a plain one');

  // nudge buttons
  const btn = (d) => c.querySelector(`.drop-nudge-btn[data-nudge="${d}"]`);
  ok([-50, -10, 10, 50].every((d) => btn(d) && parseFloat(dom.window.getComputedStyle(btn(d)).minHeight) >= 40),
    'the four nudge buttons are there and at least 40 px tall (a finger target)');
  btn(-50).dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
  await O.settle();
  ok(O.writes.at(-1) === -450, `−50 steps from the room's −400 to −450 on this scene (wrote ${O.writes.at(-1)})`);
  ok(opens.at(-1).drop_timing_offset_ms === -450, 'the preview reopens with the draft value — it plays it at once');
  ok(value() === '−450 ms', 'the panel follows');
  ok(!!c.querySelector('[data-testid="drop-timing-unsaved"]'), '… and says it is not saved yet');
  btn(10).dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
  await O.settle();
  ok(O.writes.at(-1) === -440, '+10 steps from the scene\'s own value');

  // a touch drag of the handle: the drop line is at 9 − 0.44 = 8.56 s
  const handleRect = c.querySelector('[data-testid="drag-mark-handle"] rect');
  const x0 = sToX(8.56);
  fire(handleRect, 'pointerdown', { pointerId: 21, pointerType: 'touch', clientX: x0 + 5, clientY: 130 });
  await O.settle(0);
  fireWin('pointermove', { pointerId: 21, pointerType: 'touch', clientX: x0 + 5 - 64.8 * 0.3, clientY: 130 });
  await O.settle(0);
  ok(value() === '−740 ms', `while held the value follows the finger, snapped (${value()})`);
  ok(!!c.querySelector('[data-testid="drag-mark-bubble"]'), 'and the held readout shows');
  fireWin('pointerup', { pointerId: 21, pointerType: 'touch', clientX: x0 + 5 - 64.8 * 0.3, clientY: 130 });
  await O.settle();
  ok(O.writes.at(-1) === -740, `lifting writes this scene's drop timing (${O.writes.at(-1)})`);
  ok(opens.at(-1).drop_timing_offset_ms === -740, 'and the preview reopens with it');

  // dragging back near the room's value snaps onto it
  const x1 = sToX(9 - 0.74);
  fire(handleRect, 'pointerdown', { pointerId: 22, pointerType: 'touch', clientX: x1, clientY: 130 });
  fireWin('pointermove', { pointerId: 22, pointerType: 'touch', clientX: x1 + 64.8 * 0.35, clientY: 130 });
  fireWin('pointerup', { pointerId: 22, pointerType: 'touch', clientX: x1 + 64.8 * 0.35, clientY: 130 });
  await O.settle();
  ok(O.writes.at(-1) === -400, `a drag landing within 30 ms of the room's value lands on it exactly (${O.writes.at(-1)})`);

  // "Room's" puts the scene back on null
  btn(-10).dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
  await O.settle();
  c.querySelector('[data-testid="drop-timing-reset"]').dispatchEvent(
    new dom.window.MouseEvent('click', { bubbles: true }));
  await O.settle();
  ok(O.writes.at(-1) === null, '"Room\'s" puts the scene back on the room\'s drop timing (null)');
  ok(opens.at(-1).drop_timing_offset_ms === null, 'and the preview follows');
  ok(!c.querySelector('[data-testid="drop-timing-unsaved"]'), 'back where it was saved: no "not saved" note');
}

console.log(failures ? `\nFAIL — ${failures} check(s) failed` : '\nPASS');
process.exit(failures ? 1 : 0);
