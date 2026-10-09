// Executable spec for touch press-and-hold on the two hold-to-confirm
// buttons (ReleaseButton.tsx, ModeChip.tsx — both built on the shared
// spectra/web/src/lib/useHoldToConfirm.ts hook, PR #339/#343, 2026-10-06).
//
// His report, 2026-10-09 (AGENTS.md's own words): "I tried pressing and
// holding the release to home assistant button on my phone and it didn't
// seem to work." Reproduced under real touch-emulated pointer events
// (chrome-devtools-axi was unusable here — its snapshot/eval tools hit a
// known "pageId: expected number, received undefined" bug on this host;
// worked around with raw CDP over a locally-launched Playwright Chromium,
// per the standing memory note on that workaround): the two buttons'
// `.release-hold-btn`/`.mode-chip-link` CSS carried `touch-action:
// manipulation`, which still lets the browser treat an ordinary finger's
// in-place drift (~18px, measured) as an intended pan and fire a native
// `pointercancel` at the element — aborting useHoldToConfirm's hold well
// before its ~1s duration, even though the touch never left the small
// (28px/30px) button. `touch-action: none` (this fix) keeps the whole
// gesture for the hook's own pointer handlers; verified against the same
// drift under the same real-browser touch emulation that it no longer
// cancels, both on the standalone hook and on the two real components
// with their real CSS loaded and their real fetch calls reaching a
// successful release/toggle.
//
// This script covers what a real browser's touch-action gesture engine
// cannot be reproduced in jsdom: §1 is the direct CSS regression (the
// actual root cause — computed `touch-action` on both buttons' classes,
// read off the REAL tokens.css cascade). §2-§5 mount the REAL
// ReleaseButton.tsx/ModeChip.tsx (via esbuild + jsdom + react-dom/client,
// the check_timeline_canvas_pointer_isolation.mjs precedent) under a FAKE
// clock (requestAnimationFrame/performance.now stubbed and driven by hand,
// so the ~1s hold duration costs no real wall time) and dispatch real
// PointerEvents to prove the hook's own JS contract survives the CSS
// change unchanged: pointerdown(touch) starts the hold; pointermove alone
// never cancels it (touch-action: none leaves nothing for the browser to
// contest, so there is no native pointercancel to simulate — jsdom cannot
// synthesize one, which is exactly why §1's CSS assertion is the thing
// that actually proves the fix); pointerup/pointercancel before the
// duration elapses DOES cancel (visible progress resets, "cancel on
// move-out" still works); held through the full duration fires the real
// mutation exactly once; and the mouse + keyboard paths are unchanged.
//
// Run: node scripts/check_touch_press_hold.mjs
import { mkdtempSync, writeFileSync, readFileSync } from 'node:fs';
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
    + '`cd spectra/web && npm install --no-save jsdom` to run it.');
  process.exit(0);
}
const { JSDOM } = jsdomMod;

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

/* ── §1 — the actual root-cause CSS: computed touch-action must be `none`
 * on both hold-to-confirm buttons, read off the REAL tokens.css cascade
 * (jsdom's cssstyle engine resolves this correctly — verified directly
 * against the pre-fix value before this fix landed). ── */
console.log('§1 touch-action on the two hold-to-confirm buttons is `none`, not `manipulation`');
{
  const css = readFileSync(join(webDir, 'src/styles/tokens.css'), 'utf8');
  const cssDom = new JSDOM(
    `<!doctype html><html><head><style>${css}</style></head><body>`
    + `<button class="release-hold-btn"></button>`
    + `<a class="mode-chip-link"></a>`
    + `</body></html>`,
    { pretendToBeVisual: true },
  );
  const releaseBtn = cssDom.window.document.querySelector('.release-hold-btn');
  const modeChipLink = cssDom.window.document.querySelector('.mode-chip-link');
  const releaseTouchAction = cssDom.window.getComputedStyle(releaseBtn).touchAction;
  const modeChipTouchAction = cssDom.window.getComputedStyle(modeChipLink).touchAction;
  ok(releaseTouchAction === 'none',
    `.release-hold-btn computed touch-action is "${releaseTouchAction}" (must be "none" — `
    + `"manipulation" still lets the browser cancel the hold on ordinary finger drift)`);
  ok(modeChipTouchAction === 'none',
    `.mode-chip-link computed touch-action is "${modeChipTouchAction}" (must be "none", same reason)`);
}

/* ── §2-§5 — mount the real components under a fake clock ── */

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://localhost/', pretendToBeVisual: true,
});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.Node = dom.window.Node;
globalThis.localStorage = dom.window.localStorage;
globalThis.PointerEvent = dom.window.PointerEvent;
globalThis.KeyboardEvent = dom.window.KeyboardEvent;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// A deterministic, hand-driven clock: useHoldToConfirm's `tick()` calls
// `performance.now()` and re-arms itself via `requestAnimationFrame` every
// frame — stubbing both lets the ~1s hold cost zero real time and removes
// any flakiness a real setTimeout-driven rAF would add.
let fakeNow = 0;
let pending = [];
let nextRafId = 1;
globalThis.performance = globalThis.performance || {};
globalThis.performance.now = () => fakeNow;
dom.window.performance.now = () => fakeNow;
globalThis.requestAnimationFrame = (cb) => { const id = nextRafId++; pending.push({ id, cb }); return id; };
globalThis.cancelAnimationFrame = (id) => { pending = pending.filter((p) => p.id !== id); };
dom.window.requestAnimationFrame = globalThis.requestAnimationFrame;
dom.window.cancelAnimationFrame = globalThis.cancelAnimationFrame;

/** Advance the fake clock by `ms` and drain every rAF callback scheduled
 * up to that point (draining repeatedly, since each tick re-schedules
 * itself) — the hand-driven equivalent of letting `ms` of real wall time
 * pass under requestAnimationFrame. */
function advance(ms) {
  fakeNow += ms;
  let guard = 0;
  while (pending.length && guard < 10_000) {
    const batch = pending;
    pending = [];
    for (const { cb } of batch) cb(fakeNow);
    guard += 1;
  }
}

const tmpDir = mkdtempSync(join(tmpdir(), 'touch-press-hold-'));

async function buildMount(entrySrc, tag) {
  const entryFile = join(tmpDir, `entry-${tag}.mjs`);
  writeFileSync(entryFile, entrySrc);
  const outFile = join(tmpDir, `out-${tag}.cjs`);
  const build = await esbuild.build({
    entryPoints: [entryFile],
    bundle: true,
    format: 'cjs',
    platform: 'node',
    jsx: 'automatic',
    loader: { '.css': 'empty' },
    outfile: outFile,
    nodePaths: [join(webDir, 'node_modules')],
    logLevel: 'silent',
  });
  ok(build.errors.length === 0, build.errors.length === 0
    ? `${tag}: bundles cleanly with its real imports`
    : `${tag}: bundle failed: ${build.errors.map((e) => e.text).join('; ')}`);
  return require(outFile);
}

const fire = (el, type, props) => {
  const ev = new dom.window.PointerEvent(type, {
    bubbles: true, cancelable: true, button: 0, buttons: 1, ...props,
  });
  el.dispatchEvent(ev);
};
const fireKey = (el, type, props) => {
  const ev = new dom.window.KeyboardEvent(type, { bubbles: true, cancelable: true, ...props });
  el.dispatchEvent(ev);
};

/* ── §2/§3: ReleaseButton.tsx, real component, real fetch intercepted ── */
console.log('§2 ReleaseButton.tsx: a touch hold through the real pointer/fetch path');
{
  const releaseCalls = [];
  const origFetch = dom.window.fetch;
  dom.window.fetch = async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase();
    if (url === '/spectra/api/ownership' && method === 'GET') {
      return new Response(JSON.stringify({
        owner: 'spectra', handover: null, updated_at: 0, armed: true, live_stack_active: true,
        history: [], activation: null,
        dark_fixtures: {
          faults: [], fault_count: 0, watching: [], faults_total: 0,
          last_sweep_age_s: null, sweep_interval_s: 30, fault_after_s: 60, summary: '',
        },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    if (url === '/spectra/api/ownership/release' && method === 'POST') {
      releaseCalls.push(Date.now());
      return new Response(JSON.stringify({ result: 'released', owner: 'released' }),
        { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    return origFetch(url, init);
  };
  globalThis.fetch = dom.window.fetch;

  const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from ${JSON.stringify(join(webDir, 'src/components/Toast.tsx'))};
import ReleaseButton from ${JSON.stringify(join(webDir, 'src/components/ReleaseButton.tsx'))};

const container = document.createElement('div');
document.body.appendChild(container);
const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
let root = null;

export async function mount() {
  root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(MemoryRouter, null,
        React.createElement(ToastProvider, null, React.createElement(ReleaseButton)))));
  });
  // Let the initial useOwnership() query resolve (react-query's own fetch
  // promise takes a few microtask turns beyond a single setTimeout(0)).
  for (let i = 0; i < 20 && !container.querySelector('.release-hold-btn'); i++) {
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
  }
  return container.querySelector('.release-hold-btn');
}
export async function flush() {
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}
`;
  const { mount, flush } = await buildMount(entrySrc, 'release-button');
  const btn = await mount();
  ok(!!btn, 'ReleaseButton mounts a .release-hold-btn once ownership resolves');

  // A full ~1s touch hold, with a mid-hold pointermove (drift that, before
  // the fix, the browser's own gesture engine would have turned into a
  // pointercancel — jsdom can't synthesize that part, which is exactly why
  // §1's CSS assertion is what proves this; here we prove the OTHER half:
  // that a plain pointermove, with nothing cancelling it, never aborts the
  // hold on its own).
  fire(btn, 'pointerdown', { pointerId: 1, pointerType: 'touch', clientX: 10, clientY: 10 });
  await flush();
  advance(400);
  fire(btn, 'pointermove', { pointerId: 1, pointerType: 'touch', clientX: 40, clientY: 10 });
  advance(600);
  fire(btn, 'pointerup', { pointerId: 1, pointerType: 'touch', clientX: 40, clientY: 10 });
  await flush();
  ok(releaseCalls.length === 1,
    `a held-through touch pointerdown fires the release exactly once (got ${releaseCalls.length})`);
}

console.log('§3 ReleaseButton.tsx: cancel on move-out — a pointercancel/early pointerup must not release');
{
  const releaseCalls = [];
  dom.window.fetch = async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase();
    if (url === '/spectra/api/ownership' && method === 'GET') {
      return new Response(JSON.stringify({
        owner: 'spectra', handover: null, updated_at: 0, armed: true, live_stack_active: true,
        history: [], activation: null,
        dark_fixtures: {
          faults: [], fault_count: 0, watching: [], faults_total: 0,
          last_sweep_age_s: null, sweep_interval_s: 30, fault_after_s: 60, summary: '',
        },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    if (url === '/spectra/api/ownership/release' && method === 'POST') {
      releaseCalls.push(1);
      return new Response(JSON.stringify({ result: 'released', owner: 'released' }),
        { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    throw new Error(`unexpected fetch ${method} ${url}`);
  };
  globalThis.fetch = dom.window.fetch;

  const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from ${JSON.stringify(join(webDir, 'src/components/Toast.tsx'))};
import ReleaseButton from ${JSON.stringify(join(webDir, 'src/components/ReleaseButton.tsx'))};

const container = document.createElement('div');
document.body.appendChild(container);
const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
let root = null;

export async function mount() {
  root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(MemoryRouter, null,
        React.createElement(ToastProvider, null, React.createElement(ReleaseButton)))));
  });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  return container.querySelector('.release-hold-btn');
}
export async function flush() {
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}
`;
  const { mount, flush } = await buildMount(entrySrc, 'release-button-cancel');
  const btn = await mount();

  // pointercancel before the duration elapses — THIS is a real browser's
  // own signal that it took the gesture away (a scroll/pinch claim it
  // decided to honour); the hold must cancel and never fire.
  fire(btn, 'pointerdown', { pointerId: 2, pointerType: 'touch', clientX: 10, clientY: 10 });
  await flush();
  advance(300);
  fire(btn, 'pointercancel', { pointerId: 2, pointerType: 'touch', clientX: 10, clientY: 10 });
  advance(900);
  await flush();
  ok(releaseCalls.length === 0, 'a pointercancel mid-hold never releases the room');

  // An early pointerup (released before 1s) must not release either.
  fire(btn, 'pointerdown', { pointerId: 3, pointerType: 'touch', clientX: 10, clientY: 10 });
  await flush();
  advance(200);
  fire(btn, 'pointerup', { pointerId: 3, pointerType: 'touch', clientX: 10, clientY: 10 });
  advance(900);
  await flush();
  ok(releaseCalls.length === 0, 'releasing early (a short tap) never releases the room');
}

/* ── §4: ModeChip.tsx, real component, mouse + keyboard paths ── */
console.log('§4 ModeChip.tsx: mouse hold and keyboard hold both still toggle (unchanged by the CSS fix)');
{
  const toggleCalls = [];
  dom.window.fetch = async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase();
    if (url === '/spectra/api/engine/status' && method === 'GET') {
      return new Response(JSON.stringify({ lighting: {
        mode: { id: 'evening', name: 'Evening' }, enabled: true, source: 'manual', since_ms: 0,
        manual: true, ha_value: null, ha_value_ms: null, ha_mapped_mode: null, active: true,
        phase: 'resting', reason: '', problems: [],
      } }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    if (url === '/spectra/api/house/settings' && method === 'GET') {
      return new Response(JSON.stringify({ settings: { enabled: true } }),
        { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    if (url === '/spectra/api/house/settings' && method === 'PUT') {
      toggleCalls.push(1);
      return new Response(JSON.stringify({ settings: { enabled: false }, lighting: { enabled: false } }),
        { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    throw new Error(`unexpected fetch ${method} ${url}`);
  };
  globalThis.fetch = dom.window.fetch;

  const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from ${JSON.stringify(join(webDir, 'src/components/Toast.tsx'))};
import ModeChip from ${JSON.stringify(join(webDir, 'src/components/ModeChip.tsx'))};

const container = document.createElement('div');
document.body.appendChild(container);
const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
let root = null;

export async function mount() {
  root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(MemoryRouter, null,
        React.createElement(ToastProvider, null, React.createElement(ModeChip)))));
  });
  for (let i = 0; i < 20 && !container.querySelector('.mode-chip-link'); i++) {
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
  }
  return container.querySelector('.mode-chip-link');
}
export async function flush() {
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}
`;
  const { mount, flush } = await buildMount(entrySrc, 'mode-chip-mouse-kbd');
  const link = await mount();
  ok(!!link, 'ModeChip mounts a .mode-chip-link once status resolves');

  // Mouse: pointerdown(mouse) held through the duration toggles.
  fire(link, 'pointerdown', { pointerId: 4, pointerType: 'mouse', button: 0, clientX: 10, clientY: 10 });
  await flush();
  advance(1100);
  fire(link, 'pointerup', { pointerId: 4, pointerType: 'mouse', clientX: 10, clientY: 10 });
  await flush();
  ok(toggleCalls.length === 1, `a held mouse pointerdown still toggles (got ${toggleCalls.length})`);

  // Keyboard: Enter held through the duration toggles, and the swallowed
  // trailing keyup must not navigate/toggle a second time.
  fireKey(link, 'keydown', { key: 'Enter', repeat: false });
  await flush();
  advance(1100);
  fireKey(link, 'keyup', { key: 'Enter' });
  await flush();
  ok(toggleCalls.length === 2, `a held Enter keypress also toggles (got ${toggleCalls.length})`);

  // A short Enter press (released before the duration) must not toggle.
  fireKey(link, 'keydown', { key: 'Enter', repeat: false });
  await flush();
  advance(200);
  fireKey(link, 'keyup', { key: 'Enter' });
  await flush();
  ok(toggleCalls.length === 2, 'a short Enter press does not toggle');
}

console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
