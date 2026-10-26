// Executable spec for HOME'S DROPS PANEL (predrop plan step 1 —
// spectra/web/src/home/HomeDrops.tsx and ./dropsPanel.ts; report section
// 3.6's acceptance: "a jsdom check driving the real component against a
// fake API (a part tap sends one `parts` call; the double tick one
// `approve`; undo restores both stores)").
//
// The REAL HomeDrops card, the REAL shared song-timeline view state
// (components/songTimelineView.tsx, so the tie-in is the real one), the
// REAL useDropEditor (its queue and undo stack) and the REAL api/client.ts,
// mounted under a real React 18 tree and a real @tanstack/react-query
// client in jsdom. Only two seams are faked: `fetch` (a recording fake of
// the SPECTRA routes this card calls) and `./api/spectraWs` (so a
// `drop_played` push can be driven directly).
//
//   ONE   the rows: time order, the title's review count, each part's
//         look (on / waiting / off / absent), a detection standing in for
//         one of his drops not listed twice
//   TWO   a part tap sends exactly ONE `parts` call with its next state
//   THREE the double tick sends exactly ONE `approve`
//   FOUR  Remove on one of his drops, then undo: the restore carries his
//         drop-store edits back AND the song-profile rows the other way
//         round (both stores, one step)
//   FIVE  the Testing toggle: one PUT of drop_testing, then the drop that
//         just played moves to the top, highlighted; a refused PUT is said,
//         never a silent nothing
//   SIX   the tie-in: a tap on the song timeline's drop pill selects it
//   SEVEN Remove's tooltip says what each trigger's own provenance says,
//         and the general rule for any it does not name — never a guess
//
// Run: node scripts/check_home_drops_panel.mjs
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
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
dom.window.ResizeObserver = globalThis.ResizeObserver;
dom.window.HTMLElement.prototype.scrollIntoView = function scrollIntoView() {
  this.setAttribute('data-scrolled', 'yes');
};
dom.window.requestAnimationFrame = (fn) => setTimeout(() => fn(Date.now()), 16);
dom.window.cancelAnimationFrame = (id) => clearTimeout(id);
globalThis.requestAnimationFrame = dom.window.requestAnimationFrame;
globalThis.cancelAnimationFrame = dom.window.cancelAnimationFrame;
dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {},
  addListener() {}, removeListener() {} });
globalThis.matchMedia = dom.window.matchMedia;

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

// ── the fixture song ──────────────────────────────────────────────────────
const URI = 'spotify:track:homedrops1';
const parts = (charge, lull, drop, pre = 'absent') => ({ charge, lull, pre_drop: pre, drop });
const seq = (over) => ({
  origin: 'detected', tier: 'suggested', detected_key: null, auto: null, moved: {},
  lull_off: false, charge_off: false, score: 1.1, break_beats: 3, step: 1, rise: 0.9,
  path: 'step', loud_before: true, capped: false, notes: [], needs_review: false,
  detection_lost: false, matches: [], his_marks_near: [], ...over,
});
const VIEW = {
  uri: URI, status: 'ok', reason: null,
  detector: { version: '1', stamp: 'x', detected_at: 1, confident_score: 1, suggested_score: 0.7 },
  song: { tempo_bpm: 120, beat_ms: 500, captured_from_ms: 0, captured_to_ms: 200000, duration_ms: 200000 },
  sequences: [
    seq({ key: 'drop:44000', state: 'suggested', charge_ms: 35000, lull_ms: 40000, drop_ms: 44000,
      parts: parts('waiting', 'waiting', 'waiting'), fires: false, fires_reason: 'waits_for_confirm' }),
    seq({ key: 'drop:90000', state: 'confident', tier: 'confident', charge_ms: 80000, lull_ms: 86000,
      drop_ms: 90000, parts: parts('waiting', 'waiting', 'waiting'), fires: true,
      fires_reason: 'analysed_show', playing: ['charge', 'lull', 'drop'] }),
    seq({ key: 'drop:130000', state: 'suggested', charge_ms: null, lull_ms: 126000, drop_ms: 130000,
      parts: parts('absent', 'waiting', 'off'), fires: false, fires_reason: 'switched_off' }),
    seq({ key: 'drop:169980', state: 'matches_yours', tier: 'confident', charge_ms: 160000,
      lull_ms: 166000, drop_ms: 169980, parts: parts('waiting', 'waiting', 'waiting'), fires: true,
      fires_reason: 'analysed_show', matches: [{ id: 'h-drop', kind: 'drop', timestamp_ms: 170000 }] }),
  ],
  excluded: [], counts: {}, authored: [], authored_lone: [],
  yours: [{
    key: 'his:h-drop',
    charge: { id: 'h-charge', kind: 'charge', timestamp_ms: 160100, enabled: true },
    lull: { id: 'h-lull', kind: 'lull', timestamp_ms: 166100, enabled: true },
    drop: { id: 'h-drop', kind: 'drop', timestamp_ms: 170000, enabled: true },
    enabled: true, detections: ['drop:169980'], detection: 'drop:169980',
  }],
  firing: { effective_mode: 'analysed', has_authored: true, analysed_applies: true,
    his_applies: false, testing: false },
  windows: [],
};
const PROV = {
  uri: URI, imported_profile: false,
  triggers: [
    // his charge here was placed on SPECTRA's own trigger card (fired copy only)
    { id: 'h-charge', imported: false, why: 'spectra_card', remove_would: 'delete' },
    { id: 'h-lull', imported: false, why: 'by_hand', remove_would: 'delete' },
    { id: 'h-drop', imported: false, why: 'by_hand', remove_would: 'delete' },
  ],
};
const EDITS_BEFORE = { overrides: {}, added: [] };
const EDITS_AFTER = { overrides: { 'drop:169980': { state: 'dismissed', dismissed_for: 'h-drop' } }, added: [] };
const PROFILE_CHANGES = [
  { id: 'h-charge', before: { id: 'h-charge', timestamp_ms: 160100, action: { kind: 'fire_response', event_class: 'charge' } }, after: null, index: 4, did: 'deleted', store: 'fired' },
  { id: 'h-lull', before: { id: 'h-lull', event_id: 'fixed-lull', timestamp_ms: 166100 }, after: null, index: 5, did: 'deleted' },
  { id: 'h-drop', before: { id: 'h-drop', event_id: 'fixed-drop', timestamp_ms: 170000 }, after: null, index: 6, did: 'deleted' },
];
const controls = { drop_testing: false, scene_change_mode: 'analysed' };
let failNextPut = false;
const STATUS = {
  increment: 'S3', dark: false,
  bridge: { connected: true, track: { uri: URI, title: 'Fixture', artist: 'Tests',
    duration_ms: 200000, is_playing: true, position_ms: 10000 } },
  triggers: { track_uri: URI, position_ms: 10000, last_drop: null },
};

const calls = [];
const json = (status, data) => ({ ok: status < 400, status, json: async () => data });
const answer = (result, extra = {}) => ({
  result, view: VIEW, before: EDITS_BEFORE, after: EDITS_BEFORE, rev_before: 'r0',
  rev_after: 'r0', profile: [], said: '', ...extra,
});
globalThis.fetch = async (url, opts = {}) => {
  const u = new URL(url, 'http://localhost');
  const method = (opts.method || 'GET').toUpperCase();
  const body = opts.body ? JSON.parse(opts.body) : undefined;
  calls.push({ method, path: u.pathname, search: u.search, body });
  const p = u.pathname;
  if (p === '/spectra/api/engine/status') return json(200, STATUS);
  if (p === '/spectra/api/room-controls' && method === 'GET') return json(200, controls);
  if (p === '/spectra/api/room-controls' && method === 'PUT') {
    if (failNextPut) {
      failNextPut = false;
      return json(503, { detail: 'the room settings could not be saved' });
    }
    Object.assign(controls, body);
    return json(200, { state: controls });
  }
  if (p === '/spectra/api/drop-sequences' && method === 'GET') return json(200, VIEW);
  if (p === '/spectra/api/drop-sequences/provenance') return json(200, PROV);
  if (p === '/spectra/api/drop-sequences/parts') return json(200, answer(body.key, { rev_after: 'r1', after: { overrides: { [body.key]: { parts: body.parts } }, added: [] } }));
  if (p === '/spectra/api/drop-sequences/approve') return json(200, answer(body.key, { rev_after: 'r2', after: { overrides: { [body.key]: { state: 'confirmed' } }, added: [] } }));
  if (p === '/spectra/api/drop-sequences/remove') {
    return json(200, answer(body.key, { before: EDITS_BEFORE, after: EDITS_AFTER, rev_before: 'r0',
      rev_after: 'r3', profile: PROFILE_CHANGES,
      said: 'deleted 3 triggers you placed by hand; dismissed 1 detection standing in for it' }));
  }
  if (p === '/spectra/api/drop-sequences/restore') return json(200, answer(null, { before: EDITS_AFTER, after: EDITS_BEFORE, rev_before: 'r3', rev_after: 'r0' }));
  return json(404, { detail: `not in this fixture: ${method} ${p}` });
};

// ── the fake SPECTRA websocket ────────────────────────────────────────────
const fakeWsSrc = `
const listeners = new Set();
export function onSpectraMessage(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function __emit(msg) { listeners.forEach((fn) => fn(msg)); }
`;
const tmpDir = mkdtempSync(join(tmpdir(), 'home-drops-harness-'));
const fakeWsPath = join(tmpDir, 'fakeSpectraWs.mjs');
writeFileSync(fakeWsPath, fakeWsSrc);

const src = (p) => JSON.stringify(join(repo, 'spectra/web/src', p));
const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import HomeDrops from ${src('home/HomeDrops.tsx')};
export { removeTitle } from ${src('home/dropsPanel.ts')};
import { SongTimelineViewProvider, useSongTimelineView } from ${src('components/songTimelineView.tsx')};
import { __emit } from ${JSON.stringify(fakeWsPath)};

const container = document.createElement('div');
document.body.appendChild(container);
let root = null;
let askDrop = null;

function Asker() {
  const { selectDrop } = useSongTimelineView();
  askDrop = selectDrop;
  return null;
}

export async function settle(rounds = 8) {
  for (let i = 0; i < rounds; i += 1) {
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
  }
}

export async function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(MemoryRouter, { initialEntries: ['/'] },
        React.createElement(SongTimelineViewProvider, null,
          React.createElement(Asker), React.createElement(HomeDrops)))));
  });
  await settle();
  return container;
}

export async function click(el) {
  await act(async () => { el.dispatchEvent(new window.MouseEvent('click', { bubbles: true })); });
  await settle();
}

export async function push(msg) {
  await act(async () => { __emit(msg); });
  await settle();
}

export async function ask(uri, ms) {
  await act(async () => { askDrop(uri, ms); });
  await settle();
}
`;
const entryFile = join(tmpDir, 'entry.mjs');
writeFileSync(entryFile, entrySrc);
const outFile = join(tmpDir, 'out.cjs');
const build = await esbuild.build({
  entryPoints: [entryFile], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
  outfile: outFile, nodePaths: [join(repo, 'spectra/web/node_modules')],
  loader: { '.css': 'empty' },
  plugins: [{
    name: 'stub-spectra-ws',
    setup(b) {
      const wsFile = join(repo, 'spectra/web/src/api/spectraWs.ts');
      b.onResolve({ filter: /\/spectraWs(\.ts)?$/ }, (args) => {
        const resolved = join(dirname(args.importer), args.path);
        if (resolved === wsFile || `${resolved}.ts` === wsFile) return { path: fakeWsPath };
        return null;
      });
    },
  }],
  logLevel: 'silent',
});
ok(build.errors.length === 0, build.errors.length === 0
  ? 'the real HomeDrops card bundles cleanly'
  : `bundle failed: ${build.errors.map((e) => e.text).join('; ')}`);
const H = require(outFile);

const container = await H.mount();
const rowsEls = () => [...container.querySelectorAll('.home-drops-row')];
const rowByTime = (t) => rowsEls().find((r) => r.querySelector('.home-drops-time')?.textContent === t);
const partBtn = (row, part) => row.querySelector(`.home-drops-btn.part.${part}`);
const posts = (path) => calls.filter((c) => c.method !== 'GET' && c.path === `/spectra/api/drop-sequences/${path}`);

console.log('ONE  the rows, their parts and the review count');
{
  const times = rowsEls().map((r) => r.querySelector('.home-drops-time')?.textContent);
  ok(JSON.stringify(times) === JSON.stringify(['0:44.0', '1:30.0', '2:10.0', '2:50.0']),
    `one row per drop, in time order, the stand-in not listed twice (${times.join(', ')})`);
  const title = container.querySelector('.home-quick-title')?.textContent ?? '';
  ok(/Drops · 2 to review/.test(title), `the title counts the drops waiting for him ("${title.trim()}")`);
  const a = rowByTime('0:44.0');
  ok(partBtn(a, 'charge').classList.contains('waiting') && partBtn(a, 'lull').classList.contains('waiting')
    && partBtn(a, 'drop').classList.contains('waiting'), 'a suggestion: every part waiting (dashed)');
  ok(partBtn(a, 'pre_drop').classList.contains('absent') && partBtn(a, 'pre_drop').disabled,
    'the pre-drop is absent and cannot be tapped (no pre-drop detection yet)');
  const c = rowByTime('2:10.0');
  ok(partBtn(c, 'drop').classList.contains('off') && c.classList.contains('dim'),
    'a switched-off drop: its drop part striped off, the row dimmed');
  ok(/switched off/.test(c.querySelector('.home-drops-state')?.textContent ?? ''), 'and it says so');
  ok(partBtn(c, 'charge').classList.contains('absent'), 'a drop with no charge: faint');
  const d = rowByTime('2:50.0');
  ok(['charge', 'lull', 'drop'].every((p) => partBtn(d, p).classList.contains('on')),
    'his own drop: its three triggers on');
  ok(/yours · placed by hand/.test(d.querySelector('.home-drops-state')?.textContent ?? ''),
    'his own drop says it was placed by hand (the root process\'s rule)');
  ok(d.querySelector('.home-drops-btn.approve').disabled, 'his own drop needs no approval');
  const bars = rowsEls().map((r) => r.querySelectorAll('.home-drops-bar > button').length);
  ok(bars.every((n) => n === 7), `seven toggles per bar (${bars.join(',')})`);
  const b = rowByTime('1:30.0');
  ok(b.querySelector('.home-drops-dot').classList.contains('yes')
    && !a.querySelector('.home-drops-dot').classList.contains('yes'),
    'the green dot follows the server\'s "fires"');
}

console.log('TWO  a part tap sends exactly one `parts` call');
{
  const before = posts('parts').length;
  await H.click(partBtn(rowByTime('0:44.0'), 'lull'));
  const sent = posts('parts').slice(before);
  ok(sent.length === 1, `one call (${sent.length})`);
  ok(sent[0] && sent[0].body.key === 'drop:44000' && sent[0].body.uri === URI
    && JSON.stringify(sent[0].body.parts) === JSON.stringify({ lull: 'on' }),
    `a waiting lull goes on: ${JSON.stringify(sent[0]?.body)}`);
  await H.click(partBtn(rowByTime('2:10.0'), 'drop'));
  const back = posts('parts').slice(before + 1);
  ok(back.length === 1 && JSON.stringify(back[0].body.parts) === JSON.stringify({ drop: 'on' }),
    'an off drop goes back on with one call');
}

console.log('THREE the double tick sends exactly one `approve`');
{
  const before = posts('approve').length;
  await H.click(rowByTime('1:30.0').querySelector('.home-drops-btn.approve'));
  const sent = posts('approve').slice(before);
  ok(sent.length === 1 && sent[0].body.key === 'drop:90000' && !('parts' in sent[0].body),
    `one approve for the whole drop: ${JSON.stringify(sent[0]?.body)}`);
}

console.log('FOUR  Remove on his own drop, then undo: both stores, one step');
{
  const d = rowByTime('2:50.0');
  ok(/delete 3 triggers you placed by hand/.test(d.querySelector('.home-drops-btn.remove').title),
    'Remove says what it will do before he taps it');
  await H.click(d.querySelector('.home-drops-btn.remove'));
  const sent = posts('remove');
  ok(sent.length === 1 && sent[0].body.key === 'his:h-drop', 'one remove for his drop');
  const note = container.querySelector('.home-drops-note')?.textContent ?? '';
  ok(/deleted 3 triggers you placed by hand/.test(note), `the note says what it did ("${note}")`);
  const undoBtn = container.querySelector('.home-drops-undo');
  ok(undoBtn && !undoBtn.disabled, 'the undo arrow is live');
  await H.click(undoBtn);
  const restore = posts('restore');
  ok(restore.length === 1, `one restore (${restore.length})`);
  const rb = restore[0]?.body ?? {};
  ok(JSON.stringify(rb.edits) === JSON.stringify(EDITS_BEFORE) && rb.expect === 'r3',
    'the drop store goes back to his edits before, only if they are still the after');
  const prof = rb.profile ?? [];
  ok(prof.length === 3 && prof.every((r, i) => r.from === null
    && JSON.stringify(r.to) === JSON.stringify(PROFILE_CHANGES[i].before)
    && r.index === PROFILE_CHANGES[i].index),
    'and every song-profile row comes back where it sat (from what the edit left, to what it was)');
  ok(prof[0].store === 'fired' && prof.slice(1).every((r) => !('store' in r)),
    'a card-born row keeps its store (the fired copy), and a profile row names none');
}

console.log('FIVE  Testing: one PUT, and the drop that just played goes to the top');
{
  const before = calls.filter((c) => c.method === 'PUT' && c.path === '/spectra/api/room-controls').length;
  const toggle = container.querySelector('.home-drops-testing');
  ok(toggle && toggle.getAttribute('aria-checked') === 'false' && !toggle.textContent.trim(),
    'an icon-only switch, off');
  await H.click(toggle);
  const puts = calls.filter((c) => c.method === 'PUT' && c.path === '/spectra/api/room-controls').slice(before);
  ok(puts.length === 1 && JSON.stringify(puts[0].body) === JSON.stringify({ drop_testing: true }),
    `one partial PUT of drop_testing: ${JSON.stringify(puts[0]?.body)}`);
  ok(container.querySelector('.home-drops-testing').classList.contains('on')
    && container.querySelector('.home-drops-card').classList.contains('testing'), 'it glows');
  await H.push({ type: 'drop_played', uri: URI, key: 'drop:44000', at_ms: Date.now(), position_ms: 44000 });
  const first = rowsEls()[0];
  ok(first.querySelector('.home-drops-time')?.textContent === '0:44.0'
    && first.classList.contains('justplayed') && /just played/.test(first.textContent),
    'the drop that just played is first, highlighted');
  await H.push({ type: 'drop_played', uri: URI, key: 'drop:169980', at_ms: Date.now() + 1, position_ms: 170000 });
  ok(rowsEls()[0].querySelector('.home-drops-time')?.textContent === '2:50.0',
    'a stand-in playing for his drop lifts his row');
  failNextPut = true;
  await H.click(container.querySelector('.home-drops-testing'));
  const said = container.querySelector('.home-drops-note');
  ok(said?.classList.contains('error')
    && /Drop testing is still on: the room settings could not be saved/.test(said.textContent)
    && container.querySelector('.home-drops-testing').classList.contains('on'),
    `a refused toggle says so and keeps glowing ("${said?.textContent}")`);
}

console.log('SIX  the tie-in: a tap on the song timeline\'s drop pill selects it');
{
  await H.ask(URI, 130040);
  const c = rowByTime('2:10.0');
  ok(c.classList.contains('sel') && c.getAttribute('data-scrolled') === 'yes',
    'the nearest drop is selected and scrolled into view');
  await H.ask('spotify:track:another', 44000);
  ok(rowByTime('2:10.0').classList.contains('sel'), 'a tap for another song selects nothing here');
}

console.log('SEVEN Remove\'s words never guess where a trigger came from');
{
  const yours = { key: 'his:d', kind: 'yours', yours: {
    charge: { id: 'c', enabled: true }, lull: null, drop: { id: 'd', enabled: true } } };
  const prov = (rows) => ({ uri: URI, imported_profile: false, triggers: rows });
  ok(H.removeTitle(yours, prov([{ id: 'c', remove_would: 'delete' }, { id: 'd', remove_would: 'disable' }]))
    === 'Remove: delete 1 trigger you placed by hand, switch off 1 imported trigger',
    'each trigger by what its own provenance says');
  ok(/placed by hand: deleted; imported: switched off/.test(
    H.removeTitle(yours, prov([{ id: 'c', remove_would: 'delete' }]))),
    'one the answer does not name: the general rule, not a guess that it is imported');
  ok(/placed by hand: deleted; imported: switched off/.test(H.removeTitle(yours, null)),
    'no answer at all: the general rule');
}

if (failures) {
  console.log(`\nFAIL: ${failures} check(s) failed`);
  process.exit(1);
}

console.log('\nOK: Home\'s Drops panel behaves as specified.');
process.exit(0);
