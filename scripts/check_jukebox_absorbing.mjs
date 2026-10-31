// Executable spec for absorb-then-queue's screens (the Jukebox plan's phase
// 4, PR 4.3): the Absorbing tab's words (spectra/web/src/jukebox/
// jukeboxLearning.ts, pure), the tab itself mounted under jsdom against a
// RECORDING fake of SpotFX's /api/jukebox routes (no network), and the guest
// page's "learning" line (spectra/web/src/guest/logic.ts).
//
//   1. The words: an estimate is the server's own seconds, and none is shown
//      as none, never guessed; a row's buttons; the line badge only while a
//      song waits to be learned; the guest's line counts the estimate down
//      and goes away once the song is ready.
//   2. The tab, mounted: the song being learned with its progress bar, the
//      waiting songs with their times, the parked one with the lane's own
//      reason; "Play un-analysed now", "Learn again" and "Remove" POST/DELETE
//      exactly the engine's routes for that song, and nothing else writes.
//
// Run: node scripts/check_jukebox_absorbing.mjs (tests/test_jukebox_absorbing_page.py).
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const web = join(repo, 'spectra/web');
const require = createRequire(join(web, 'package.json'));
const esbuild = require('esbuild');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};
const report = () => {
  console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
  process.exit(failures === 0 ? 0 : 1);
};

async function bundle(entrySrc, name) {
  const tmp = mkdtempSync(join(tmpdir(), `absorbing-${name}-`));
  const entry = join(tmp, 'entry.mjs');
  writeFileSync(entry, entrySrc);
  const out = join(tmp, 'out.cjs');
  const r = await esbuild.build({
    entryPoints: [entry], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
    outfile: out, nodePaths: [join(web, 'node_modules')], logLevel: 'silent',
    loader: { '.css': 'empty' },
  });
  if (r.errors.length) throw new Error(r.errors.map((e) => e.text).join('; '));
  return require(out);
}

// ── 1. the words ──────────────────────────────────────────────────────────
console.log('§1 jukeboxLearning.ts and the guest page\'s learning line');
const W = await bundle(`export * from ${JSON.stringify(join(web, 'src/jukebox/jukeboxLearning.ts'))};`, 'words');
ok(W.etaWords(null) === 'no estimate yet', 'no estimate from the server is shown as none');
ok(W.etaWords(45) === 'ready in under a minute' && W.etaWords(206) === 'ready in ~3 min',
  'an estimate is the server\'s seconds, in minutes');
ok(W.stateWords('unanalysed', 'dry').includes('nothing else would play')
  && W.stateWords('unanalysed', 'host').includes('you let it through'), 'why a song plays un-analysed');
ok(W.tryWords({ attempts: 0, state: 'learning' }) === '' && W.tryWords({ attempts: 1, state: 'learning' }) === '2nd try'
  && W.tryWords({ attempts: 3, state: 'parked' }) === '', 'the try is shown from the 2nd on, never on a parked song');
ok(JSON.stringify(W.rowActions({ state: 'parked' })) === '["relearn","unanalysed"]'
  && JSON.stringify(W.rowActions({ state: 'waiting' })) === '["unanalysed"]'
  && W.rowActions({ state: 'learned' }).length === 0, 'each row offers the buttons its state allows');
ok(W.failWords({ attempts: 3, reason: 'gap' }, { gap: 'Part of the song\'s audio is missing.' })
  === '3 tries: Part of the song\'s audio is missing.', 'a parked song says why, in the lane\'s own words');
ok(W.lineBadge({ state: 'queued', known: false, ready: false, learn: { state: 'waiting', attempts: 0 } }) === 'waiting to learn'
  && W.lineBadge({ state: 'queued', known: false, ready: true, learn: { state: 'waiting', attempts: 0 } }) === null
  && W.lineBadge({ state: 'queued', known: true, learn: { state: 'learned', attempts: 0 } }) === null
  && W.lineBadge({ state: 'committed', known: false, learn: { state: 'learning', attempts: 0 } }) === null,
  'the line badge shows only while a waiting song is held back to be learned');
const st = (over = {}) => ({ available: true, reason: '', learn_first: true, max_attempts: 3,
  lane: { state: 'idle', job: null, progress_ms: null }, queue: [], parked: [], log: [],
  numbers: { overhead_s: 85, success: 0.75 }, ...over });
ok(W.headline(st({ available: false, reason: 'The hidden player isn\'t running, so new songs play un-analysed.' }), true)
  .includes('isn\'t running'), 'the headline gives the server\'s own reason when it can\'t learn');
ok(W.headline(st({ learn_first: false }), true).startsWith('Learning first is off'), 'and says when learning first is off');
ok(W.headline(st(), false).includes('while a night runs'), 'with no night it says when learning happens');
ok(W.progress(st({ lane: { state: 'capturing', progress_ms: 111_000, job: { duration_ms: 222_000 } } })) === 0.5
  && W.progress(st()) === null, 'the progress bar is the server\'s progress, or none');

const G = await bundle(`export * from ${JSON.stringify(join(web, 'src/guest/logic.ts'))};`, 'guest');
const mine = (learning) => ({ state: 'waiting', jailed: false, held: false, starts_in_ms: null, place: null, learning });
ok(G.myStatus(mine({ state: 'learning', eta_s: 300, ready: false }), 60_000, Date.now())
  === 'The lights are learning it · ready in ~4 min · keeps its place', 'a guest\'s own song counts the estimate down');
ok(G.myStatus(mine({ state: 'waiting', eta_s: null, ready: false }), 0, Date.now())
  === 'Waiting for the lights to learn it · keeps its place', 'with no estimate, no time is shown');
ok(G.myStatus(mine({ state: 'parked', eta_s: null, ready: false }), 0, Date.now()).includes('host will decide'),
  'a song it couldn\'t learn says the host decides');
ok(G.learningLine({ state: 'learned', eta_s: null, ready: true }, 0) === null
  && G.learningLine(undefined, 0) === null, 'a ready song reads like any other');
const strip = G.stripText({ tone: 'queued', title: 'Rasputin', place: null, starts_in_ms: null, held: false, count: 1,
                            learning: { state: 'learning', eta_s: 120, ready: false } }, 0, Date.now(), true);
ok(strip.label === 'Your song is being learned' && strip.detail === 'ready in ~2 min · keeps its place',
  `the strip says your song is being learned, in one short line (${strip.detail})`);
const parkedStrip = G.stripText({ tone: 'queued', title: 'Rasputin', place: null, starts_in_ms: null, held: false,
                                  count: 1, learning: { state: 'parked', eta_s: null, ready: false } }, 0, Date.now(), true);
ok(parkedStrip.label.includes("couldn't learn") && parkedStrip.detail === 'the host will decide',
  'a parked song\'s strip says the host decides');

// ── 2. the tab, mounted ───────────────────────────────────────────────────
let jsdomMod;
try {
  jsdomMod = require('jsdom');
} catch {
  console.log('\njsdom not installed in spectra/web/node_modules (dev-only) — skipping §2.');
  report();
}
const { JSDOM } = jsdomMod;
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/jukebox' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
for (const k of ['HTMLElement', 'HTMLInputElement', 'Node', 'Element', 'MouseEvent', 'KeyboardEvent', 'FocusEvent', 'Event', 'getComputedStyle']) {
  globalThis[k] = dom.window[k];
}
globalThis.localStorage = dom.window.localStorage;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const LEARNING = st({
  lane: { state: 'capturing', progress_ms: 101_000, job: { job_id: 'j1', uri: 'u4', title: 'Rasputin', artist: 'Boney M.', duration_ms: 222_000 } },
  queue: [
    { entry_id: 'e4', uri: 'u4', title: 'Rasputin', artist: 'Boney M.', duration_ms: 222_000, added_by: 'p1', state: 'learning', attempts: 1, reason: 'stalled', detail: '', eta_s: 206, ready: false, held: false },
    { entry_id: 'e5', uri: 'u5', title: 'Toxic', artist: 'Britney Spears', duration_ms: 199_000, added_by: 'host', state: 'waiting', attempts: 0, reason: '', detail: '', eta_s: 703, ready: false, held: false },
  ],
  parked: [
    { entry_id: 'e7', uri: 'u7', title: 'Bohemian Rhapsody', artist: 'Queen', duration_ms: 354_000, added_by: 'p2', state: 'parked', attempts: 3, reason: 'governor_drain', detail: '', eta_s: null, ready: false, held: false },
  ],
  sentences: { governor_drain: 'Audio was dropped on the way to the lane.' },
});
const requests = [];
const json = (body) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
globalThis.fetch = async (input, init) => {
  const url = String(input);
  const method = (init?.method ?? 'GET').toUpperCase();
  requests.push({ method, url });
  if (url.includes('/api/jukebox/learning')) return json(LEARNING);
  if (url.includes('/api/jukebox/line/')) return json({ status: 'ok' });
  return json({});
};

const P = await bundle(`
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import AbsorbingTab from ${JSON.stringify(join(web, 'src/jukebox/AbsorbingTab.tsx'))};
import { ToastProvider } from ${JSON.stringify(join(web, 'src/components/Toast.tsx'))};
const container = document.createElement('div');
document.body.appendChild(container);
let root = null;
export function mount(status) {
  root = createRoot(container);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(ToastProvider, null,
        React.createElement(MemoryRouter, null, React.createElement(AbsorbingTab, { status })))));
  });
  return container;
}
export async function settle(ms = 30) {
  for (let i = 0; i < 6; i += 1) await act(async () => { await new Promise((r) => setTimeout(r, ms)); });
}
export function actSync(fn) { act(fn); }
export function unmount() { if (root) act(() => { root.unmount(); }); root = null; }
`, 'tab');

console.log('\n§2 the Absorbing tab, mounted');
const c = P.mount({ running: true, line: [] });
await P.settle();
const $ = (sel) => c.querySelector(sel);
const text = (el) => (el ? el.textContent : '');
ok(text($('[data-testid="jukebox-absorbing-headline"]')).includes('2 songs are being learned or waiting'),
  'the headline counts what is being learned or waiting');
const now = $('[data-testid="jukebox-absorbing-now"]');
ok(text(now).includes('Rasputin') && text(now).includes('2nd try') && text(now).includes('ready in ~3 min'),
  'the song being learned shows its try and the server\'s estimate');
const bar = now?.querySelector('[role="progressbar"]');
ok(bar?.getAttribute('aria-valuenow') === '45', `the bar shows how far through it is (${bar?.getAttribute('aria-valuenow')}%)`);
ok(text($('[data-testid="jukebox-absorbing-waiting"]')).includes('Toxic')
  && text($('[data-testid="jukebox-absorbing-waiting"]')).includes('ready in ~12 min'), 'a waiting song shows when it will be ready');
const parked = $('[data-testid="jukebox-absorbing-parked"]');
ok(text(parked).includes('3 tries: Audio was dropped on the way to the lane.'), 'a parked song says why, in the lane\'s words');
const writes = () => requests.filter((r) => r.method !== 'GET');
ok(writes().length === 0, 'reading the tab writes nothing');
const press = async (root, label) => {
  const b = [...root.querySelectorAll('button')].find((x) => x.textContent === label);
  P.actSync(() => b.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
  await P.settle();
  return !!b;
};
await press(parked, 'Learn again');
ok(writes().at(-1)?.method === 'POST' && writes().at(-1)?.url.endsWith('/api/jukebox/line/e7/relearn'),
  'Learn again POSTs that song\'s relearn');
await press(parked, 'Play un-analysed now');
ok(writes().at(-1)?.url.endsWith('/api/jukebox/line/e7/unanalysed'), 'Play un-analysed now POSTs that song\'s unanalysed');
await press(parked, 'Remove');
ok(writes().at(-1)?.method === 'DELETE' && writes().at(-1)?.url.endsWith('/api/jukebox/line/e7'),
  'Remove is the line\'s own remove');
await press($('[data-testid="jukebox-absorbing-waiting"]'), 'Play un-analysed now');
ok(writes().at(-1)?.url.endsWith('/api/jukebox/line/e5/unanalysed'), 'a waiting song can be let through too');
ok(writes().length === 4 && writes().every((r) => r.url.includes('/api/jukebox/line/')),
  'nothing else on the tab writes');
ok(!!c.querySelector('[data-testid="jukebox-absorbing-numbers"]'), 'the small print says what the estimates are built from');
P.unmount();
report();
