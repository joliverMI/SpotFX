// Executable spec for TimelineCanvas.tsx's per-pointer isolation
// (spectra/web/src/timeline/canvas/TimelineCanvas.tsx and its web/
// twin), added alongside touch panning 2026-10-08 and hardened the same
// day (PR "no-mistakes(review): Fix touch beat-snap radius scale and
// pointer-id cross-contamination"): "a second, unrelated pointer's own
// move/up/cancel (a resting palm beside a panning finger) must never
// touch state that belongs to [the dragging pointer]."
//
// Before that hardening, `dragging`/`panStart` were pointer-agnostic:
// `move()` called `onDragMove` on ANY pointer's move while `dragging`
// was true, and `up()` unconditionally ended the drag
// (`dragging = false; onDragEnd(ev, g)`) on ANY pointer's `pointerup` —
// so a second finger (or a resting palm) lifting off while a marker was
// mid-drag on the FIRST finger silently ended that drag using the
// SECOND finger's own event.
//
// This renders the REAL component via esbuild + jsdom + react-dom/client
// (the check_topbar_scene_colour_names.mjs precedent), dispatches real
// PointerEvents with two distinct pointerIds, and asserts on the
// `pointer` prop's own callback invocations (never source text) that:
//   1. a second pointer's MOVE while pointer A is dragging never drives
//      A's onDragMove with pointer B's own event;
//   2. a second pointer's UP while pointer A is still dragging never
//      ends A's drag;
//   3. pointer A's own subsequent move/up still drive its own drag
//      correctly, end to end.
//
// Run: node scripts/check_timeline_canvas_pointer_isolation.mjs
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const require = createRequire(join(repo, 'spectra/web/package.json'));
const esbuild = require('esbuild');

let jsdomMod;
try {
  jsdomMod = require('jsdom');
} catch {
  console.log('jsdom not installed in spectra/web/node_modules (dev-only, '
    + 'not a declared dependency) — skipping this check. Install with '
    + '`cd spectra/web && npm install --no-save jsdom` to run it.');
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
globalThis.HTMLCanvasElement = dom.window.HTMLCanvasElement;
globalThis.PointerEvent = dom.window.PointerEvent;
globalThis.Node = dom.window.Node;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
// The real draw loop's own requestAnimationFrame is irrelevant to pointer
// handling (a separate useEffect owns pointerdown/move/up) — stub it to a
// no-op so the test exits promptly instead of chasing jsdom's rAF timers.
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};

// jsdom has neither Pointer Capture nor a real canvas backend — both are
// unrelated to the pointer-id isolation under test, so they're stubbed
// rather than worked around. getContext('2d') already returns null in
// jsdom (logged, not thrown) and the component's own `if (ctx && w > 0)`
// guard already skips drawing on that, so no `canvas` npm package is
// needed to prove this.
const canvasProto = dom.window.HTMLCanvasElement.prototype;
canvasProto.setPointerCapture = function () {};
canvasProto.releasePointerCapture = function () {};
Object.defineProperty(canvasProto, 'clientWidth', { get() { return 1000; }, configurable: true });
Object.defineProperty(canvasProto, 'clientHeight', { get() { return 100; }, configurable: true });
canvasProto.getBoundingClientRect = function () {
  return { left: 0, top: 0, right: 1000, bottom: 100, width: 1000, height: 100, x: 0, y: 0, toJSON() {} };
};

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const tmpDir = mkdtempSync(join(tmpdir(), 'canvas-pointer-'));

// Build a fresh `mount()` for a given TimelineCanvas.tsx (its own tmp
// bundle, its own container+root) — run once per twin below. `nodeModulesDir`
// must be the SAME app's own node_modules the component itself resolves
// `react`/`react-dom` against — mixing in the other app's copy bundles
// two distinct React instances together and throws "Invalid hook call".
async function buildMount(componentPath, nodeModulesDir, tag) {
  const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import TimelineCanvas from ${JSON.stringify(componentPath)};

const container = document.createElement('div');
document.body.appendChild(container);
let root = null;

export function mount(layers, pointer) {
  if (root) act(() => { root.unmount(); });
  root = createRoot(container);
  const view = { librosaFilters: {} };
  const data = {};
  act(() => {
    root.render(React.createElement(TimelineCanvas, {
      layers, data, view,
      getWin: () => ({ startMs: 0, endMs: 20000 }),
      getNowMs: () => null,
      height: 100,
      pointer,
    }));
  });
  return container.querySelector('canvas');
}
`;
  const entryFile = join(tmpDir, `entry-${tag}.mjs`);
  writeFileSync(entryFile, entrySrc);
  const outFile = join(tmpDir, `out-${tag}.cjs`);
  const build = await esbuild.build({
    entryPoints: [entryFile],
    bundle: true,
    format: 'cjs',
    platform: 'node',
    jsx: 'automatic',
    outfile: outFile,
    nodePaths: [nodeModulesDir],
    logLevel: 'silent',
  });
  ok(build.errors.length === 0, build.errors.length === 0
    ? `${tag}: TimelineCanvas.tsx bundles cleanly with its real touchPan.ts/frame.ts imports`
    : `${tag}: bundle failed: ${build.errors.map((e) => e.text).join('; ')}`);
  return require(outFile).mount;
}

const fire = (canvas, type, props) => {
  const ev = new dom.window.PointerEvent(type, {
    bubbles: true, cancelable: true, button: 0, buttons: 1, ...props,
  });
  canvas.dispatchEvent(ev);
};

async function runSuite(label, mount) {
console.log(`${label}: a second pointer (a resting palm) must not drive or end the first pointer's drag`);
{
  // One layer: anything left of x=50 hits a draggable marker; everything
  // else is empty graph.
  const layers = [{
    z: 0, visible: () => true, draw: () => {},
    hitTest: (x) => (x < 50 ? { kind: 'trigger-intensity', id: 't1' } : null),
  }];
  const calls = { dragMove: [], dragEnd: [], pan: [] };
  const pointer = {
    onHit: () => {},
    onDragMove: (ev) => calls.dragMove.push(ev.pointerId),
    onDragEnd: (ev) => calls.dragEnd.push(ev.pointerId),
    onPan: (deltaMs) => calls.pan.push(deltaMs),
  };
  const canvas = mount(layers, pointer);
  ok(!!canvas, 'canvas element mounted');

  const A = 11;
  const B = 22;
  // A touches down on the marker — starts a drag owned by A.
  fire(canvas, 'pointerdown', { pointerId: A, clientX: 10, clientY: 10, pointerType: 'touch' });
  // B touches down on empty graph (a second, unrelated finger/palm).
  fire(canvas, 'pointerdown', { pointerId: B, clientX: 200, clientY: 10, pointerType: 'touch' });

  // B moves — this must NEVER be read as A's drag continuing.
  fire(canvas, 'pointermove', { pointerId: B, clientX: 210, clientY: 10, pointerType: 'touch' });
  ok(calls.dragMove.length === 0,
    'pointer B\'s own move does not drive pointer A\'s drag (onDragMove not called for it)');

  // B lifts off — this must NEVER end A's still-active drag.
  fire(canvas, 'pointerup', { pointerId: B, clientX: 210, clientY: 10, pointerType: 'touch' });
  ok(calls.dragEnd.length === 0,
    'pointer B lifting off does not end pointer A\'s drag');

  // A is still dragging: its own move must still drive onDragMove.
  fire(canvas, 'pointermove', { pointerId: A, clientX: 20, clientY: 10, pointerType: 'touch' });
  ok(calls.dragMove.length === 1 && calls.dragMove[0] === A,
    'pointer A\'s own move still drives its own drag, carrying its own pointerId');

  // A finally lifts off — THIS is what must end A's drag.
  fire(canvas, 'pointerup', { pointerId: A, clientX: 20, clientY: 10, pointerType: 'touch' });
  ok(calls.dragEnd.length === 1 && calls.dragEnd[0] === A,
    'pointer A\'s own up ends its own drag, carrying its own pointerId');
}

console.log(`${label}: a second pointer's pan-candidate lifecycle is independent of an unrelated active pan`);
{
  const layers = [{ z: 0, visible: () => true, draw: () => {}, hitTest: () => null }];
  const panDeltas = [];
  const pointer = { onHit: () => {}, onPan: (d) => panDeltas.push(d) };
  const canvas = mount(layers, pointer);

  const A = 31;
  const B = 42;
  // A touches empty graph and drags horizontally far enough to lock into
  // a pan (TOUCH_PAN_LOCK_PX = 6).
  fire(canvas, 'pointerdown', { pointerId: A, clientX: 100, clientY: 50, pointerType: 'touch' });
  fire(canvas, 'pointermove', { pointerId: A, clientX: 130, clientY: 50, pointerType: 'touch' });
  ok(panDeltas.length === 1, 'A\'s horizontal touch move locks into an active pan');

  // A second finger (B) touches down on empty graph and immediately lifts
  // off without ever moving far enough to resolve a direction.
  fire(canvas, 'pointerdown', { pointerId: B, clientX: 500, clientY: 50, pointerType: 'touch' });
  fire(canvas, 'pointerup', { pointerId: B, clientX: 500, clientY: 50, pointerType: 'touch' });

  // A's pan must still be alive — a further move from A must still pan.
  fire(canvas, 'pointermove', { pointerId: A, clientX: 160, clientY: 50, pointerType: 'touch' });
  ok(panDeltas.length === 2,
    'B touching down and lifting off mid-gesture does not kill A\'s already-locked-in pan');
}
}

const spectraMount = await buildMount(
  join(repo, 'spectra/web/src/timeline/canvas/TimelineCanvas.tsx'),
  join(repo, 'spectra/web/node_modules'), 'spectra-web');
await runSuite('spectra/web §1/§2', spectraMount);

const builderMount = await buildMount(
  join(repo, 'web/src/builder/canvas/TimelineCanvas.tsx'),
  join(repo, 'web/node_modules'), 'web-builder');
await runSuite('web (spot-effects twin) §1/§2', builderMount);

console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
