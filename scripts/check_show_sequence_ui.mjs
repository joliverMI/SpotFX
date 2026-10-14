// Executable spec for the Light Show's SEQUENCE tab (SequenceView.tsx) —
// the Admiral, 2026-10-09: "A 'Show Sequence' is a sequence of pre-armed
// sets ... We can build them in a new tab, along with build, run."
//
// Mounts the REAL SequenceView.tsx under jsdom (react-dom/client), with
// window.fetch stood in by canned /spectra/api/light-show answers — the
// check_light_show_run_icon_buttons.mjs precedent; no backend.
//
//   ONE   — the pure helpers (reorder, the pointer drag's landing index,
//           done/current/upcoming, the clock).
//   ONE-B — Run is the sub-view it lands on with no click (2026-10-13:
//           "make the sequence running page the default for the lightshow
//           tab"), and its Quick start row of recently started sequences
//           — name, "last ran …", one tap posts sequence-run/start, and a
//           sequence the loaded list no longer knows about is left out.
//   TWO   — Build: items render, a Set item's four arming icons (the
//           chosen one lit), + Wait, a song-list Wait's search over the
//           songs SPECTRA knows, adding/removing songs, a POINTER drag
//           (mouse and finger alike) reordering items, Save posting what
//           the screen shows, Duplicate.
//   THREE — Run: the current item highlighted with the server's own
//           "waiting for" sentence, done/upcoming items, every control
//           posting its route, Resume replacing Pause when paused.
//
// Run: node scripts/check_show_sequence_ui.mjs
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
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.Node = dom.window.Node;
globalThis.localStorage = dom.window.localStorage;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {},
  addListener() {}, removeListener() {} });
globalThis.matchMedia = dom.window.matchMedia;

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};


// ── fixtures ──
const SETS = [
  { id: 'set-a', name: 'Quiet Hues', actions: [{ id: 'a1', kind: 'force_scene', params: {}, enabled: true }] },
  { id: 'set-b', name: 'Blues', actions: [{ id: 'a2', kind: 'color_set_now', params: {}, enabled: true }] },
];
const SEQ = {
  id: 'seq-1', name: 'Friday', loop: false, problems: [],
  items: [
    { id: 'i1', kind: 'set', set_id: 'set-a', arm: 'high', title: 'Quiet Hues — next High Trigger', problems: [] },
    { id: 'i2', kind: 'wait', arm: 'instant', wait: { kind: 'duration', seconds: 90, trigger: 'scene_change', count: 1, songs: [] },
      title: 'Wait 1:30', problems: [] },
    { id: 'i3', kind: 'set', set_id: 'set-b', arm: 'instant', title: 'Blues — fires at once', problems: [] },
  ],
};
const RUN = {
  id: 'run-1', sequence_id: 'seq-1', name: 'Friday', items: SEQ.items, loop: false,
  state: 'running', active: true, index: 1, loops_done: 0, started_ms: 1, ended_ms: null,
  end_reason: '', paused_reason: '', awaiting_fire: false, firing: false, waiting_reason: '',
  wait_count: 0, wait_left_s: 75, waiting_for: 'waiting 1:15 more',
  log: [{ at_ms: 1, what: 'started', index: 0, item: 'Quiet Hues — next High Trigger', detail: 'by button' }],
};
let runStatus = { run: null, refusal: null, playing_uri: null };
// "seq-1" is Friday, a real sequence the loaded `sequences` list knows about;
// "seq-ghost" stands in for a sequence that has since been deleted — the
// server already leaves such a row out, but the view double-checks against
// what it has loaded too, so this proves that defensive filter fires.
const RECENT = { recent: [
  { sequence_id: 'seq-1', name: 'Friday', last_started_ms: Date.now() - 3600 * 1000 },
  { sequence_id: 'seq-ghost', name: 'Deleted one', last_started_ms: Date.now() - 2 * 3600 * 1000 },
] };
const SONGS = [
  { uri: 'spotify:track:apagon', title: 'El Apagón', artist: 'Bad Bunny' },
  { uri: 'spotify:track:dopa', title: 'Dopamine', artist: 'Purple Disco Machine' },
];
const requests = [];
const NodeResponse = globalThis.Response;
const fakeFetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const full = String(url).replace(/^https?:\/\/[^/]+/, '');
  const path = full.split('?')[0];
  const body = init.body ? JSON.parse(init.body) : null;
  requests.push({ method, path, full, body });
  let answer = {};
  if (method === 'GET' && path === '/spectra/api/light-show/sequences') answer = { sequences: [SEQ] };
  else if (method === 'GET' && path === '/spectra/api/light-show/sequences/recent') answer = RECENT;
  else if (method === 'GET' && path === '/spectra/api/light-show/sequence-run') answer = runStatus;
  else if (method === 'GET' && path === '/spectra/api/light-show/songs') {
    const q = decodeURIComponent((full.split('q=')[1] || '').split('&')[0]).toLowerCase();
    answer = { songs: SONGS.filter((s) => `${s.title} ${s.artist}`.toLowerCase().includes(q)),
      playing: { uri: 'spotify:track:now', title: 'Now Song', artist: 'Someone' } };
  } else if (method === 'POST' && path === '/spectra/api/light-show/sequences') answer = { ...body, id: body.id || 'seq-new' };
  else if (method === 'POST' && path.endsWith('/duplicate')) answer = { ...SEQ, id: 'seq-copy', name: 'Friday copy' };
  else if (method === 'POST' && path.startsWith('/spectra/api/light-show/sequence-run/')) answer = runStatus;
  return new NodeResponse(JSON.stringify(answer), { status: 200, headers: { 'Content-Type': 'application/json' } });
};
globalThis.fetch = fakeFetch;
dom.window.fetch = fakeFetch;
dom.window.Element.prototype.setPointerCapture = function () {};
dom.window.Element.prototype.releasePointerCapture = function () {};

const tmpDir = mkdtempSync(join(tmpdir(), 'lightshow-sequence-ui-'));
const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import SequenceView from ${JSON.stringify(join(repo, 'spectra/web/src/lightshow/SequenceView.tsx'))};
export * as ops from ${JSON.stringify(join(repo, 'spectra/web/src/lightshow/sequenceOps.ts'))};
export const container = document.createElement('div');
document.body.appendChild(container);
let root = null;
const toasts = globalThis.__toasts__ = [];
export async function mount() {
  root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(MemoryRouter, null, React.createElement(SequenceView, { sets: ${JSON.stringify(SETS)},
      toast: (msg, kind) => toasts.push({ msg, kind }) })));
  });
  await settle();
}
export async function settle(ms = 30) {
  for (let i = 0; i < 4; i += 1) await act(async () => { await new Promise((r) => setTimeout(r, ms)); });
}
export async function step(fn, ms = 20) { await act(async () => { fn(); await new Promise((r) => setTimeout(r, ms)); }); }
export function unmount() { act(() => root.unmount()); }
`;
const entryFile = join(tmpDir, 'entry.mjs');
writeFileSync(entryFile, entrySrc);
const outFile = join(tmpDir, 'out.cjs');
const build = await esbuild.build({
  entryPoints: [entryFile], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
  outfile: outFile, nodePaths: [join(repo, 'spectra/web/node_modules')], logLevel: 'silent',
  loader: { '.css': 'empty', '.svg': 'text' },
});
ok(build.errors.length === 0, 'SequenceView.tsx + its real children bundle cleanly');
const { container, mount, step, settle, unmount, ops } = require(outFile);

console.log('ONE — the pure helpers');
ok(JSON.stringify(ops.reorder(['a', 'b', 'c', 'd'], 0, 2)) === '["b","c","a","d"]', 'reorder moves an item down');
ok(JSON.stringify(ops.reorder(['a', 'b', 'c', 'd'], 3, 0)) === '["d","a","b","c"]', 'reorder moves an item up');
const rows4 = [0, 1, 2, 3].map((i) => ({ top: i * 100, bottom: i * 100 + 90 }));
ok(ops.dropIndex(120, rows4, 0) === 0, 'dragging row 0 to the top half of row 1 leaves it first');
ok(ops.dropIndex(160, rows4, 0) === 1, 'past row 1\'s middle it lands second');
ok(ops.dropIndex(999, rows4, 0) === 3, 'below everything it lands last');
ok(ops.dropIndex(10, rows4, 3) === 0, 'dragging the last row to the very top lands first');
ok(ops.itemPhase(0, 1, true) === 'done' && ops.itemPhase(1, 1, true) === 'current'
  && ops.itemPhase(2, 1, true) === 'upcoming', 'done / current / upcoming');
ok(ops.clock(90) === '1:30' && ops.clock(3725) === '1:02:05', 'clock');

await mount();
const q = (sel, root = container) => root.querySelector(sel);
const qa = (sel, root = container) => [...root.querySelectorAll(sel)];
const click = async (el) => step(() => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
const setInput = async (el, value) => step(() => {
  const proto = Object.getPrototypeOf(el);
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
  el.dispatchEvent(new dom.window.Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
}, 300);
const button = (text, root = container) => qa('button', root).find((b) => b.textContent.trim().startsWith(text));

console.log('ONE-B — Run is the default landing sub-view, with a Quick start row');
const tabs = qa('.show-seq-sub button[role=tab]');
ok(tabs.map((t) => t.textContent.trim()).join('|').startsWith('Build|Run'), 'Build and Run sub-tabs');
ok(tabs[1].getAttribute('aria-selected') === 'true' && tabs[0].getAttribute('aria-selected') === 'false',
  'Run is selected on mount, with no click');
ok(Boolean(q('.show-seq-recent')), 'the Quick start card is shown');
const recentBtns = qa('.show-seq-recent-btn');
ok(recentBtns.length === 1, `only the sequence still in the loaded list is offered (${recentBtns.length})`);
ok(recentBtns[0].textContent.includes('Friday') && recentBtns[0].textContent.includes('last ran')
  && recentBtns[0].textContent.includes('ago'), `shows the name and when it last ran (${recentBtns[0].textContent})`);
requests.length = 0;
await click(recentBtns[0]);
const qstart = requests.find((r) => r.method === 'POST' && r.path === '/spectra/api/light-show/sequence-run/start');
ok(Boolean(qstart) && qstart.body.sequence_id === 'seq-1' && qstart.body.replace === false,
  'one tap posts sequence-run/start for that sequence, nothing already running');

console.log('TWO — Build: items, the four arming icons, Waits, the song search, duplicate');
await click(tabs[0]);
ok(qa('li.show-seq-item').length === 3, `the sequence's three items render (${qa('li.show-seq-item').length})`);
ok(qa('li.show-seq-item .light-show-step-summary').length === 3, 'items start collapsed, each with a one-line summary');
await click(button('Expand all'));
ok(qa('.show-seq-arm').length === 2, 'Expand all opens every item');
const first = qa('li.show-seq-item')[0];
const armBtns = qa('.show-seq-arm button', first);
ok(armBtns.length === 4 && armBtns.every((b) => b.querySelector('svg path')), 'a Set item shows four icon buttons, real SVG');
ok(armBtns[2].classList.contains('armed') && armBtns[2].getAttribute('aria-checked') === 'true',
  'the High arrow is the lit one for an item armed on High');
await click(armBtns[1]);
ok(qa('.show-seq-arm button', qa('li.show-seq-item')[0])[1].classList.contains('armed'), 'tapping the bunny re-arms it on scene change');
await click(button('+ Wait'));
ok(qa('li.show-seq-item').length === 4, '+ Wait adds an item');
if (!q('.show-seq-wait', qa('li.show-seq-item')[3])) await click(q('.show-seq-item-head', qa('li.show-seq-item')[3]));
const waitRow = qa('li.show-seq-item')[3];
await setInput(q('.show-seq-wait select', waitRow), 'song_list');
const search = q('input[type=search]', qa('li.show-seq-item')[3]);
ok(Boolean(search), 'a song-list Wait shows a song search');
await setInput(search, 'apag');
await settle(100);
ok(requests.some((r) => r.full.includes('/light-show/songs?q=apag')), 'typing searches the songs SPECTRA knows');
const results = qa('.show-seq-song-results li', qa('li.show-seq-item')[3]);
ok(results.length === 1 && results[0].textContent.includes('El Apagón — Bad Bunny'), 'the match is listed with its artist');
await click(q('button', results[0]));
await click(button('+ Playing now', qa('li.show-seq-item')[3]));
const chosen = qa('.show-seq-song-list li', qa('li.show-seq-item')[3]);
ok(chosen.length === 2, `added songs appear on the Wait's list (${chosen.length})`);
await click(q('button', chosen[1]));
ok(qa('.show-seq-song-list li', qa('li.show-seq-item')[3]).length === 1, '✕ removes a song from the list');

console.log('     drag the new Wait (row 4) to the top with the pointer (dnd-kit, the legacy editor\'s own library)');
const rectAt = (i) => ({ x: 0, y: i * 100, left: 0, top: i * 100, right: 300, bottom: i * 100 + 90,
  width: 300, height: 90, toJSON() {} });
qa('li.show-seq-item').forEach((li, i) => { li.getBoundingClientRect = () => rectAt(i); });
const handle = q('.light-show-step-handle', qa('li.show-seq-item')[3]);
ok(Boolean(handle) && handle.getAttribute('aria-roledescription') === 'sortable',
  'each item has its own ⠿ drag handle (a dnd-kit sortable activator)');
const pev = (type, y) => {
  const e = new dom.window.MouseEvent(type, { bubbles: true, cancelable: true, clientX: 150, clientY: y, button: 0 });
  Object.defineProperty(e, 'pointerId', { value: 7 });
  Object.defineProperty(e, 'isPrimary', { value: true });
  Object.defineProperty(e, 'pointerType', { value: 'touch' });
  return e;
};
await step(() => handle.dispatchEvent(pev('pointerdown', 345)));
await step(() => document.dispatchEvent(pev('pointermove', 330)));
await step(() => document.dispatchEvent(pev('pointermove', 150)));
await step(() => document.dispatchEvent(pev('pointermove', 30)));
ok(qa('li.show-seq-item')[3].classList.contains('dragging'), 'the lifted item is marked while dragging');
await step(() => document.dispatchEvent(pev('pointerup', 30)));
await settle(50);
ok(qa('li.show-seq-item')[0].classList.contains('wait'),
  'released at the top, the Wait is now item 1');
await click(button('Save'));
const saved = requests.filter((r) => r.method === 'POST' && r.path === '/spectra/api/light-show/sequences').pop();
ok(saved && saved.body.items.length === 4, 'Save posts all four items');
ok(saved && saved.body.items[0].kind === 'wait' && saved.body.items[0].wait.kind === 'song_list'
  && saved.body.items[0].wait.songs.map((s) => s.uri).join() === 'spotify:track:apagon',
  `the saved order and song list are what the screen shows (${JSON.stringify(saved?.body.items[0])})`);
ok(saved && saved.body.items[1].arm === 'scene_change', 'the re-armed set saved its new arming');
ok(saved && !('title' in saved.body.items[1]), 'the served-only title is not posted back');
await settle();
await click(button('Duplicate'));
ok(requests.some((r) => r.method === 'POST' && r.path === '/spectra/api/light-show/sequences/seq-1/duplicate'),
  'Duplicate asks the server for the copy');

console.log('THREE — Run: the current item, what it waits for, the controls');
runStatus = { run: RUN, refusal: null, playing_uri: null };
await click(tabs[1]);
await settle(450);
const cur = q('.show-seq-run-item.current');
ok(Boolean(cur) && cur.getAttribute('aria-current') === 'step', 'the current item is highlighted');
ok(cur && cur.textContent.includes('Wait 1:30') && cur.textContent.includes('waiting 1:15 more'),
  `it says what it is waiting for (${cur?.textContent})`);
ok(qa('.show-seq-run-item.done').length === 1 && qa('.show-seq-run-item.upcoming').length === 1, 'done and upcoming items');
ok(q('.show-seq-waiting')?.textContent === 'waiting 1:15 more', 'the headline sentence is the server\'s, verbatim');
for (const [label, path] of [['⏸ Pause', 'pause'], ['◀ Previous', 'previous'], ['Next ▶', 'next'], ['Fire now', 'fire-now'], ['■ Stop', 'stop']]) {
  requests.length = 0;
  const b = button(label);
  ok(Boolean(b), `${label} button`);
  if (b) await click(b);
  ok(requests.some((r) => r.method === 'POST' && r.path === `/spectra/api/light-show/sequence-run/${path}`),
    `${label} posts /sequence-run/${path}`);
}
runStatus = { run: { ...RUN, state: 'paused', paused_reason: 'paused by hand', waiting_for: 'paused — paused by hand' }, refusal: null, playing_uri: null };
await settle(450);
ok(Boolean(button('▶ Resume')) && !button('⏸ Pause'), 'paused: Resume replaces Pause');

unmount();
console.log(failures ? `${failures} FAILED` : 'all passed');
process.exit(failures ? 1 : 0);
