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
//   FIVE  the Testing toggle: one PUT of drop_testing; the drop that just
//         played lights up IN PLACE (rows never move, any mode); a refused
//         PUT is said, never a silent nothing
//   SIX   the tie-in: a tap on the song timeline's drop pill selects it
//   SEVEN Remove's tooltip says what each trigger's own provenance says,
//         and the general rule for any it does not name — never a guess
//   EIGHT the PRE-DROP's button (predrop plan step 4): its look follows the
//         server's parts.pre_drop (his own drop's YoursRow.pre_drop.part),
//         its glyph follows its kind, a tap sends exactly ONE `parts` call
//         {pre_drop} — on his own drop too, asking nothing first — and a
//         waiting pre-drop counts for review and lights the double tick
//   NINE  the editor's PRE-DROP handle: a drag sends ONE `handles` call
//         {pre_drop: ms} snapped to its kind's rail (a spike to the hits, a
//         vocal intro to the entries) and held inside its kind's lead range;
//         ◀ ▶ step along that rail; one tap on its glyph sends ONE
//         `pre-drop-kind`; ＋ Pre-drop sends ONE `fill {handle: pre_drop}`;
//         his own drop's moves under his key; undo goes through `restore`
//   TEN   NEXT AND JUMP (2026-10-28, his Q1-Q5): the next drop that will
//         play wears the purple outline and a countdown to its server
//         `fire_ms` (not its mark); a row that does not play is skipped;
//         the time is a Jump button that zooms the shared window to the
//         whole drop and turns Follow off
//   ELEVEN DOUBLE-TAP (his Q9): a second tap within DOUBLE_TAP_MS switches
//         the part off — two calls, the second queued behind the first —
//         and ONE undo step puts both back
//   TWELVE HIGH CONFIDENCE (his Q10-Q12): a waiting part on a confident
//         tier is drawn approved with a detector dot (class `confident`),
//         left out of "to review"; a tap on it switches it off
//
// Run: node scripts/check_home_drops_panel.mjs
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
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
// jsdom has no pointer capture: the editor's handles call it on pointerdown
dom.window.HTMLElement.prototype.setPointerCapture = function setPointerCapture() {};
dom.window.HTMLElement.prototype.releasePointerCapture = function releasePointerCapture() {};
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
      parts: parts('waiting', 'waiting', 'waiting'), fires: false, fires_reason: 'waits_for_confirm',
      fire_ms: 43900 }),
    seq({ key: 'drop:90000', state: 'confident', tier: 'confident', charge_ms: 80000, lull_ms: 86000,
      drop_ms: 90000, parts: parts('waiting', 'waiting', 'waiting', 'waiting'), fires: true,
      fires_reason: 'analysed_show', playing: ['charge', 'lull', 'drop'], fire_ms: 89900,
      pre_drop_ms: 89200, pre_drop_kind: 'spike', pre_drop_auto: 89200, pre_drop_tier: 'confident',
      pre_drop_score: 1.15, pre_drop_off: false, pre_drop_was: null }),
    seq({ key: 'drop:130000', state: 'suggested', charge_ms: null, lull_ms: 126000, drop_ms: 130000,
      parts: parts('absent', 'waiting', 'off', 'off'), fires: false, fires_reason: 'switched_off',
      pre_drop_ms: null, pre_drop_kind: 'intro', pre_drop_auto: 127000, pre_drop_tier: 'suggested',
      pre_drop_score: 1.05, pre_drop_off: true, pre_drop_was: 127000 }),
    seq({ key: 'drop:169980', state: 'matches_yours', tier: 'confident', charge_ms: 160000,
      lull_ms: 166000, drop_ms: 169980, parts: parts('waiting', 'waiting', 'waiting'), fires: true,
      fires_reason: 'analysed_show', matches: [{ id: 'h-drop', kind: 'drop', timestamp_ms: 170000 }],
      fire_ms: 169880 }),
  ],
  excluded: [], counts: {}, authored: [], authored_lone: [],
  yours: [{
    key: 'his:h-drop',
    charge: { id: 'h-charge', kind: 'charge', timestamp_ms: 160100, enabled: true },
    lull: { id: 'h-lull', kind: 'lull', timestamp_ms: 166100, enabled: true },
    drop: { id: 'h-drop', kind: 'drop', timestamp_ms: 170000, enabled: true },
    enabled: true, detections: ['drop:169980'], detection: 'drop:169980', fire_ms: 169900,
    pre_drop: { ms: 169400, kind: 'spike', auto: 169400, off: false, was: null, moved: false,
      lead_ms: 600, score: 1.2, tier: 'confident', part: 'on' },
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
// the snap rails: bass spikes and beats, and the pre-drop's own two rails
const RAILS = {
  uri: URI, status: 'ok', reason: null, beat_ms: 500, captured_from_ms: 0,
  spikes: [[90000, 0.9], [170000, 0.9]],
  beats: [[88000, 1], [88500, 0], [89000, 0], [89500, 0], [90000, 1]],
  hits: [[88600, 0.5], [89200, 0.8], [89700, 0.4], [89800, 0.6], [169300, 0.4], [169400, 0.8]],
  entries: [[87000, 0.6], [88800, 0.7]],
};
let revN = 0;
// parts answers chain their revisions, as the real store's do, so a
// double-tap's second write starts where the first one ended
let partsRev = 'r0';
let partsN = 0;
let failNextPut = false;
const STATUS = {
  increment: 'S3', dark: false,
  bridge: { connected: true, track: { uri: URI, title: 'Fixture', artist: 'Tests',
    duration_ms: 200000, is_playing: true, position_ms: 10000 } },
  triggers: { track_uri: URI, position_ms: 10000, last_drop: null },
};

const calls = [];
// a fresh copy per answer, as a real server sends: handing back the fixture's
// own objects would let an in-place change slip past react-query's
// structural sharing and leave the page drawing the old view
const json = (status, data) => ({ ok: status < 400, status, json: async () => structuredClone(data) });
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
  if (p === '/spectra/api/drop-sequences/parts') {
    partsN += 1;
    const before = partsRev;
    partsRev = `pr${partsN}`;
    return json(200, answer(body.key, { rev_before: before, rev_after: partsRev,
      before: { overrides: { tick: partsN - 1 }, added: [] },
      after: { overrides: { tick: partsN }, added: [] } }));
  }
  if (p === '/spectra/api/drop-sequences/approve') return json(200, answer(body.key, { rev_after: 'r2', after: { overrides: { [body.key]: { state: 'confirmed' } }, added: [] } }));
  if (p === '/spectra/api/drop-sequences/remove') {
    return json(200, answer(body.key, { before: EDITS_BEFORE, after: EDITS_AFTER, rev_before: 'r0',
      rev_after: 'r3', profile: PROFILE_CHANGES,
      said: 'deleted 3 triggers you placed by hand; dismissed 1 detection standing in for it' }));
  }
  if (p === '/spectra/api/drop-sequences/restore') return json(200, answer(null, { before: EDITS_AFTER, after: EDITS_BEFORE, rev_before: 'r3', rev_after: 'r0' }));
  if (p === '/spectra/api/drop-sequences/rails') return json(200, RAILS);
  if (['handles', 'fill', 'pre-drop-kind'].some((x) => p === `/spectra/api/drop-sequences/${x}`)) {
    // what the server does to the view (spectra/services/drop_sequences.py),
    // so the editor's next drag starts where the last one landed
    const s = VIEW.sequences.find((q) => q.key === body.key);
    if (s && body.handles && 'pre_drop' in body.handles) s.pre_drop_ms = body.handles.pre_drop;
    if (s && body.kind) s.pre_drop_kind = body.kind;
    const his = VIEW.yours.find((r) => r.key === body.key);
    if (his && body.handles && 'pre_drop' in body.handles) his.pre_drop.ms = body.handles.pre_drop;
    revN += 1;
    return json(200, answer(body.key, { rev_before: 'r0', rev_after: `rp${revN}`,
      after: { overrides: { [body.key]: { touched: revN } }, added: [] } }));
  }
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
export { removeTitle, buildPanelRows, snapPreDrop, stepPreDrop, clampPreDrop, nextDropKey, nextPartState, DOUBLE_TAP_MS } from ${src('home/dropsPanel.ts')};
export { seedShowClockFromStatus } from ${src('lib/showClock.ts')};
export { ICONS } from ${src('components/iconRegistry.ts')};
export { PRE_DROP_COLOR } from ${src('timeline/dropSequences.ts')};
import { SongTimelineViewProvider, useSongTimelineView } from ${src('components/songTimelineView.tsx')};
import { __emit } from ${JSON.stringify(fakeWsPath)};

const container = document.createElement('div');
document.body.appendChild(container);
let root = null;
let askDrop = null;

let viewState = null;
function Asker() {
  const v = useSongTimelineView();
  askDrop = v.selectDrop;
  viewState = v;
  return null;
}
export function view() { return viewState; }

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

/** Two clicks with no settle between them — a double-tap. */
export async function dblTap(el) {
  await act(async () => {
    el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  });
  await settle(12);
}

export async function push(msg) {
  await act(async () => { __emit(msg); });
  await settle();
}

export async function ask(uri, ms) {
  await act(async () => { askDrop(uri, ms); });
  await settle();
}

/** A real pointer gesture: down on the handle, then moves and the up on
 * the window, where the editor listens. */
export async function drag(el, xs, id = 7) {
  const PE = window.PointerEvent;
  await act(async () => {
    el.dispatchEvent(new PE('pointerdown', { bubbles: true, pointerId: id, clientX: xs[0] }));
  });
  for (const x of xs) {
    await act(async () => { window.dispatchEvent(new PE('pointermove', { pointerId: id, clientX: x })); });
  }
  await act(async () => {
    window.dispatchEvent(new PE('pointerup', { pointerId: id, clientX: xs[xs.length - 1] }));
  });
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
      // components/songStrip.ts sits beside SongStrip.tsx: esbuild matches an
      // extension-less transitive import of it case-insensitively and fails
      // (AGENTS.md's own note) — resolve it straight to the .ts file
      b.onResolve({ filter: /(^|\/)songStrip$/ }, () => (
        { path: join(repo, 'spectra/web/src/components/songStrip.ts') }
      ));
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
const timeOf = (r) => r.querySelector('.home-drops-time-text')?.textContent;
const rowByTime = (t) => rowsEls().find((r) => timeOf(r) === t);
const partBtn = (row, part) => row.querySelector(`.home-drops-btn.part.${part}`);
const posts = (path) => calls.filter((c) => c.method !== 'GET' && c.path === `/spectra/api/drop-sequences/${path}`);

console.log('ONE  the rows, their parts and the review count');
{
  const times = rowsEls().map(timeOf);
  ok(JSON.stringify(times) === JSON.stringify(['0:44.0', '1:30.0', '2:10.0', '2:50.0']),
    `one row per drop, in time order, the stand-in not listed twice (${times.join(', ')})`);
  const title = container.querySelector('.home-quick-title')?.textContent ?? '';
  ok(/Drops · 1 to review/.test(title),
    `the title counts the drops a suggestion waits on — high confidence left out ("${title.trim()}")`);
  const a = rowByTime('0:44.0');
  ok(partBtn(a, 'charge').classList.contains('waiting') && partBtn(a, 'lull').classList.contains('waiting')
    && partBtn(a, 'drop').classList.contains('waiting'), 'a suggestion: every part waiting (dashed)');
  ok(partBtn(a, 'pre_drop').classList.contains('absent') && partBtn(a, 'pre_drop').disabled,
    'a drop with no pre-drop: its pre-drop button faint and inert');
  const c = rowByTime('2:10.0');
  ok(partBtn(c, 'drop').classList.contains('off') && c.classList.contains('dim'),
    'a switched-off drop: its drop part striped off, the row dimmed');
  ok(/drop off · plays nothing/.test(c.querySelector('.home-drops-state')?.textContent ?? ''),
    'and it says so: reviewed, plays nothing (his Q6)');
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

console.log('FIVE  Testing: one PUT; the drop that just played lights up in place');
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
  const order = () => JSON.stringify(rowsEls().map(timeOf));
  const was = order();
  await H.push({ type: 'drop_played', uri: URI, key: 'drop:90000', at_ms: Date.now(), position_ms: 90000 });
  const lit = rowByTime('1:30.0');
  ok(lit.classList.contains('justplayed') && /just played/.test(lit.textContent) && order() === was,
    'the drop that just played lights up in its own place — the rows never move');
  ok(rowsEls().filter((r) => r.classList.contains('justplayed')).length === 1, 'one row lit at a time');
  await H.push({ type: 'drop_played', uri: URI, key: 'drop:169980', at_ms: Date.now() + 1, position_ms: 170000 });
  ok(rowByTime('2:50.0').classList.contains('justplayed')
    && !rowByTime('1:30.0').classList.contains('justplayed') && order() === was,
    'a stand-in playing for his drop lights his row, in place, until the next one plays');
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

console.log('EIGHT the pre-drop button: its look, its glyph, one call a tap');
{
  const pathOf = (btn) => btn?.querySelector('svg path')?.getAttribute('d');
  const b = rowByTime('1:30.0');
  const pb = partBtn(b, 'pre_drop');
  ok(pb.classList.contains('confident') && !pb.disabled && pb.getAttribute('data-kind') === 'spike',
    'a waiting spike pre-drop on its own confident tier: drawn approved (confident), and it can be tapped');
  ok(pathOf(pb) === H.ICONS.preDrop, 'a spike wears the spike glyph (preDrop)');
  ok(/a spike/.test(pb.title) && /high confidence/.test(pb.title)
    && /colour fades across it/.test(pb.title),
    `its tooltip names the kind, the state, and that it does not play yet ("${pb.title}")`);
  ok(/spike pre-drop/.test(b.querySelector('.home-drops-state')?.textContent ?? ''),
    'the row\'s state line names the pre-drop\'s kind');
  const c = rowByTime('2:10.0');
  const pc = partBtn(c, 'pre_drop');
  ok(pc.classList.contains('off') && pathOf(pc) === H.ICONS.preDropVoice
    && pc.getAttribute('data-kind') === 'intro',
    'a switched-off vocal intro: striped, wearing the vocal-intro glyph (preDropVoice)');
  ok(/pre-drop off/.test(c.querySelector('.home-drops-state')?.textContent ?? ''),
    'and the state line says its pre-drop is off');
  const d = rowByTime('2:50.0');
  const pd = partBtn(d, 'pre_drop');
  ok(pd.classList.contains('on') && pathOf(pd) === H.ICONS.preDrop,
    'his own drop\'s pre-drop reads YoursRow.pre_drop.part (on)');
  ok(!/your trigger/.test(pd.title), 'and is never called one of his triggers');

  const inertBefore = posts('parts').length;
  await H.click(partBtn(rowByTime('0:44.0'), 'pre_drop'));
  ok(posts('parts').length === inertBefore, 'a tap on an absent pre-drop sends nothing');

  const before = posts('parts').length;
  await H.click(pb);
  await H.click(pc);
  await H.click(pd);
  const sent = posts('parts').slice(before);
  ok(sent.length === 3, `three taps, three calls (${sent.length})`);
  ok(sent[0]?.body.key === 'drop:90000'
    && JSON.stringify(sent[0]?.body.parts) === JSON.stringify({ pre_drop: 'off' }),
    `high confidence (it looks approved) → off: ${JSON.stringify(sent[0]?.body)}`);
  ok(sent[1]?.body.key === 'drop:130000'
    && JSON.stringify(sent[1]?.body.parts) === JSON.stringify({ pre_drop: 'on' }),
    `off → on: ${JSON.stringify(sent[1]?.body)}`);
  ok(sent[2]?.body.key === 'his:h-drop'
    && JSON.stringify(sent[2]?.body.parts) === JSON.stringify({ pre_drop: 'off' }),
    `his own drop's pre-drop, on → off, through the same call: ${JSON.stringify(sent[2]?.body)}`);
  ok(!posts('remove').slice(1).length && !calls.some((x) => /confirm_id/.test(JSON.stringify(x.body ?? {}))),
    'nothing asked first (the pre-drop lives in the drop store, never his song profile)');

  // a waiting pre-drop on his own drop waits for him: review count + double tick
  const yoursWaiting = { ...VIEW, yours: [{ ...VIEW.yours[0],
    pre_drop: { ...VIEW.yours[0].pre_drop, part: 'waiting', tier: 'suggested' } }] };
  const hisRow = H.buildPanelRows(yoursWaiting, { testing: false }).find((r) => r.kind === 'yours');
  ok(hisRow?.canApprove && hisRow.waiting && hisRow.parts.pre_drop === 'waiting',
    'his own drop with a waiting pre-drop counts for review and lights the double tick');
  const none = { ...VIEW, yours: [{ ...VIEW.yours[0], pre_drop: null }] };
  const hisNone = H.buildPanelRows(none, { testing: false }).find((r) => r.kind === 'yours');
  ok(hisNone?.parts.pre_drop === 'absent' && !hisNone.canApprove,
    'his own drop with no pre-drop: absent, nothing to approve');
  const unworked = { ...VIEW, yours: [{ ...VIEW.yours[0] }] };
  delete unworked.yours[0].pre_drop;
  ok(H.buildPanelRows(unworked, { testing: false }).find((r) => r.kind === 'yours')
    ?.parts.pre_drop === 'absent', 'not worked out yet: absent too');
}

console.log('NINE the editor\'s pre-drop handle');
{
  // the pure rules first
  ok(H.clampPreDrop('spike', 10000, 9900) === 9750 && H.clampPreDrop('spike', 10000, 5000) === 7000,
    'a spike stays 250–3000 ms before its drop');
  ok(H.clampPreDrop('intro', 10000, 9800) === 9650 && H.clampPreDrop('intro', 10000, 4000) === 5500,
    'a vocal intro stays 350–4500 ms before its drop');
  ok(H.snapPreDrop('intro', 88850, RAILS, 168).ms === 88800
    && H.snapPreDrop('spike', 89650, RAILS, 168).ms === 89700,
    'each kind snaps to its own rail');
  ok(/free/.test(H.snapPreDrop('spike', 88850, RAILS, 168).what),
    'a spike far from any hit is placed free (a vocal entry is not its rail)');
  ok(H.stepPreDrop('spike', 89200, 1, RAILS)?.ms === 89700
    && H.stepPreDrop('intro', 88800, -1, RAILS)?.ms === 87000,
    '◀ ▶ step along the kind\'s own rail');

  const editorOf = () => container.querySelector('.home-drop-editor');
  const stripBox = () => {
    const strip = container.querySelector('.home-drop-editor-strip');
    strip.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 96, right: 1000,
      bottom: 96, x: 0, y: 0, toJSON() { return this; } });
    return strip;
  };
  // 1:30's window: two beats before its charge (80000) to two after its drop
  const START = 79000, SPAN = 12000;
  const xAt = (ms) => ((ms - START) / SPAN) * 1000;

  await H.click(rowByTime('1:30.0').querySelector('.home-drops-btn.edit'));
  ok(!!editorOf(), 'the pencil opens the editor in place');
  stripBox();
  let ph = editorOf().querySelector('.home-drop-editor-handle.pre_drop');
  ok(ph && ph.getAttribute('data-kind') === 'spike'
    && ph.querySelector('svg path')?.getAttribute('d') === H.ICONS.preDrop,
    'its fourth handle: the pre-drop, wearing its kind\'s glyph');
  ok(editorOf().querySelector('.home-drop-editor-strip').classList.contains('has-pre'),
    'the strip makes room for a handle over its top edge');
  ok(ph.style.getPropertyValue('--part').toLowerCase() === H.PRE_DROP_COLOR.toLowerCase(),
    `the handle is the pre-drop's orange (${ph.style.getPropertyValue('--part')})`);
  {
    // the 44 px target and touch-action: none are the shared handle class's;
    // the pre-drop's own rules may move it, never take either away
    const css = readFileSync(join(repo, 'spectra/web/src/styles/tokens.css'), 'utf8');
    const block = (sel) => {
      const i = css.indexOf(`${sel} {`);
      return i < 0 ? '' : css.slice(i, css.indexOf('}', i));
    };
    const base = block('.home-drop-editor-handle');
    const own = block('.home-drop-editor-handle.pre_drop');
    ok(/touch-action:\s*none/.test(base) && /width:\s*44px/.test(base) && /height:\s*44px/.test(base)
      && own && !/touch-action|width|height/.test(own),
      'a 44 px touch target with touch-action: none, which its own rule leaves alone');
  }

  let before = posts('handles').length;
  await H.drag(ph, [xAt(89200), xAt(89500), xAt(89650)]);
  let sent = posts('handles').slice(before);
  ok(sent.length === 1 && sent[0].body.key === 'drop:90000'
    && JSON.stringify(sent[0].body.handles) === JSON.stringify({ pre_drop: 89700 }),
    `a drag saves once, snapped to the nearest hit: ${JSON.stringify(sent[0]?.body)}`);

  before = posts('handles').length;
  ph = editorOf().querySelector('.home-drop-editor-handle.pre_drop');
  await H.drag(ph, [xAt(89700), xAt(89950)]);
  sent = posts('handles').slice(before);
  ok(sent.length === 1 && sent[0].body.handles.pre_drop === 89750,
    `dragged too close to its drop, a spike is held 250 ms before it: ${JSON.stringify(sent[0]?.body)}`);

  before = posts('handles').length;
  await H.click(editorOf().querySelector('.home-drop-editor-stepbtn.pre-earlier'));
  sent = posts('handles').slice(before);
  ok(sent.length === 1 && sent[0].body.handles.pre_drop === 89700,
    `◀ steps back to the previous hit: ${JSON.stringify(sent[0]?.body)}`);

  // 300 ms before its drop: a vocal intro (350–4500 ms) cannot sit there, so
  // the switch the server would refuse is never sent
  let kb = editorOf().querySelector('.home-drop-editor-kind');
  ok(kb?.disabled && /350–4500 ms/.test(kb.title) && /300 ms/.test(kb.title),
    `a switch that cannot fit is off, and says why ("${kb?.title}")`);
  before = posts('pre-drop-kind').length;
  await H.click(kb);
  ok(posts('pre-drop-kind').length === before, 'and a tap on it sends nothing');

  before = posts('handles').length;
  await H.click(editorOf().querySelector('.home-drop-editor-stepbtn.pre-earlier'));
  sent = posts('handles').slice(before);
  ok(sent.length === 1 && sent[0].body.handles.pre_drop === 89200,
    `◀ again, back to the hit before that: ${JSON.stringify(sent[0]?.body)}`);

  kb = editorOf().querySelector('.home-drop-editor-kind');
  ok(kb && !kb.disabled && /a spike/.test(kb.title) && /vocal intro/.test(kb.title),
    `800 ms before its drop the switch is on, saying what it is and what a tap makes it ("${kb?.title}")`);
  before = posts('pre-drop-kind').length;
  await H.click(kb);
  sent = posts('pre-drop-kind').slice(before);
  ok(sent.length === 1 && sent[0].body.key === 'drop:90000' && sent[0].body.kind === 'intro',
    `one tap on its glyph, one pre-drop-kind call: ${JSON.stringify(sent[0]?.body)}`);
  ph = editorOf().querySelector('.home-drop-editor-handle.pre_drop');
  ok(ph?.getAttribute('data-kind') === 'intro'
    && ph.querySelector('svg path')?.getAttribute('d') === H.ICONS.preDropVoice,
    'the handle now wears the vocal intro\'s glyph');

  before = posts('handles').length;
  stripBox();
  await H.drag(ph, [xAt(89200), xAt(89000), xAt(88850)]);
  sent = posts('handles').slice(before);
  ok(sent.length === 1 && sent[0].body.handles.pre_drop === 88800,
    `a vocal intro snaps to a vocal entry, never a hit: ${JSON.stringify(sent[0]?.body)}`);

  // undo: the pre-drop edit goes back through restore like every other edit
  const lastRev = `rp${revN}`;
  before = posts('restore').length;
  await H.click(container.querySelector('.home-drops-undo'));
  sent = posts('restore').slice(before);
  ok(sent.length === 1 && sent[0].body.expect === lastRev
    && JSON.stringify(sent[0].body.edits) === JSON.stringify(EDITS_BEFORE),
    `undo puts his edits back through one restore (expect ${lastRev}): ${JSON.stringify(sent[0]?.body)}`);

  // ＋ Pre-drop on a drop that has none
  await H.click(rowByTime('0:44.0').querySelector('.home-drops-btn.edit'));
  ok(!editorOf().querySelector('.home-drop-editor-handle.pre_drop'),
    'a drop with no pre-drop: no pre-drop handle');
  const add = editorOf().querySelector('.home-drop-editor-act.add-pre-drop');
  ok(!!add, 'and its editor offers ＋ Pre-drop');
  before = posts('fill').length;
  await H.click(add);
  sent = posts('fill').slice(before);
  ok(sent.length === 1 && sent[0].body.key === 'drop:44000' && sent[0].body.handle === 'pre_drop',
    `＋ Pre-drop: one fill by the rules: ${JSON.stringify(sent[0]?.body)}`);

  // his own drop: the pre-drop moves under his key
  await H.click(rowByTime('2:50.0').querySelector('.home-drops-btn.edit'));
  stripBox();
  const HS = 159100, HSPAN = 11900;
  const hx = (ms) => ((ms - HS) / HSPAN) * 1000;
  ph = editorOf().querySelector('.home-drop-editor-handle.pre_drop');
  before = posts('handles').length;
  await H.drag(ph, [hx(169400), hx(169320)]);
  sent = posts('handles').slice(before);
  ok(sent.length === 1 && sent[0].body.key === 'his:h-drop'
    && JSON.stringify(sent[0].body.handles) === JSON.stringify({ pre_drop: 169300 }),
    `his own drop's pre-drop moves under his key, snapped to a hit: ${JSON.stringify(sent[0]?.body)}`);
}

console.log('TEN  next and Jump: the countdown runs to the fire moment');
{
  await H.click(container.querySelector('.home-drop-editor .home-drop-editor-close')
    ?? rowByTime('2:50.0').querySelector('.home-drops-btn.edit'));
  // the show clock at 0:30, paused: 0:44 does not play (a suggestion the
  // server says waits), so the next drop is 1:30 — the one that will play
  await H.push({ type: 'clock', show_clock_ms: 30000, position_ms: 30000, is_playing: false });
  const nextRows = rowsEls().filter((r) => r.classList.contains('next'));
  ok(nextRows.length === 1 && timeOf(nextRows[0]) === '1:30.0',
    `one row is next, and it is the next that will PLAY (${nextRows.map(timeOf).join(',')})`);
  const chip = rowByTime('1:30.0').querySelector('.home-drops-count');
  ok(chip && chip.textContent === '59.9s',
    `its countdown runs to fire_ms 1:29.9 (mark 1:30.0 + drop timing), not the mark ("${chip?.textContent}")`);
  ok(!rowByTime('0:44.0').querySelector('.home-drops-count'), 'a row that does not play has no countdown');
  await H.push({ type: 'clock', show_clock_ms: 89000, position_ms: 89000, is_playing: false });
  ok(rowByTime('1:30.0').querySelector('.home-drops-count')?.classList.contains('soon'),
    'inside the last three seconds it fills and glows (soon)');
  await H.push({ type: 'clock', show_clock_ms: 89950, position_ms: 89950, is_playing: false });
  const after = rowsEls().find((r) => r.classList.contains('next'));
  ok(after && timeOf(after) === '2:50.0'
    && after.querySelector('.home-drops-count')?.classList.contains('flash'),
    'once it fires the next one takes over, and its countdown flashes');
  ok(after.querySelector('.home-drops-count')?.textContent === '79.9s',
    'his own drop counts to the stand-in that plays for it (fire_ms 2:49.88)');
  {
    const css = readFileSync(join(repo, 'spectra/web/src/styles/tokens.css'), 'utf8');
    ok(/\.home-drops-list\s*\{[^}]*overflow-y:\s*auto/.test(css),
      'the list scrolls inside the card');
    ok(!['1:30.0', '2:50.0'].some((t) => rowByTime(t).getAttribute('data-scrolled')),
      'keeping just-played and next in view never scrolls the page (no scrollIntoView)');
  }
  ok(H.nextDropKey([{ key: 'a', plays: true, fireMs: 1000 }, { key: 'b', plays: false, fireMs: 500 }], 0) === 'a'
    && H.nextDropKey([{ key: 'a', plays: true, fireMs: 1000 }], 1000) === null
    && H.nextDropKey([{ key: 'a', plays: true, fireMs: 1000 }], null) === null,
    'nextDropKey: only rows that play, only drops not fired yet, nothing without a clock');

  const jump = rowByTime('1:30.0').querySelector('.home-drops-time');
  ok(jump.querySelector('svg path')?.getAttribute('d') === H.ICONS.jump
    && /Jump/.test(jump.getAttribute('aria-label') ?? ''),
    'the row\'s time is a Jump button (the time and an arrow)');
  await H.click(jump);
  const v = H.view();
  ok(v.win.follow === false && v.win.manualWin && v.win.manualWin.startMs <= 80000
    && v.win.manualWin.endMs >= 90000,
    `Jump shows the whole drop on the audio shape and turns Follow off (${JSON.stringify(v.win.manualWin)})`);
}

console.log('ELEVEN double-tap: off, behind the first tap, one undo step');
{
  const btn = partBtn(rowByTime('0:44.0'), 'charge');
  ok(btn.classList.contains('waiting'), 'a lower-confidence suggestion (dashed)');
  const before = posts('parts').length;
  const firstN = partsN + 1;
  await H.dblTap(btn);
  const sent = posts('parts').slice(before);
  ok(sent.length === 2 && JSON.stringify(sent[0].body.parts) === JSON.stringify({ charge: 'on' })
    && JSON.stringify(sent[1].body.parts) === JSON.stringify({ charge: 'off' }),
    `the first tap acts at once (on), the second switches it off: ${JSON.stringify(sent.map((x) => x.body.parts))}`);
  const undoBtn = container.querySelector('.home-drops-undo');
  ok(/double-tap/.test(undoBtn.title), `the undo step names the double-tap ("${undoBtn.title}")`);
  const r0 = posts('restore').length;
  await H.click(undoBtn);
  const rs = posts('restore').slice(r0);
  ok(rs.length === 1 && rs[0].body.expect === `pr${firstN + 1}`
    && JSON.stringify(rs[0].body.edits) === JSON.stringify({ overrides: { tick: firstN - 1 }, added: [] }),
    `ONE undo puts both taps back — to before the first (${JSON.stringify(rs[0]?.body)})`);
  ok(!/charge approved at 0:44.0/.test(container.querySelector('.home-drops-undo').title),
    'and the first tap is not left on the stack as a step of its own');

  const conf = partBtn(rowByTime('1:30.0'), 'lull');
  const b2 = posts('parts').length;
  await H.dblTap(conf);
  const sent2 = posts('parts').slice(b2);
  ok(sent2.length === 1 && JSON.stringify(sent2[0].body.parts) === JSON.stringify({ lull: 'off' }),
    `a double-tap on a part the first tap already switched off sends nothing more (${sent2.length})`);
}

console.log('TWELVE high confidence: drawn approved, with the detector dot');
{
  const b = rowByTime('1:30.0');
  ok(['charge', 'lull', 'drop'].every((p) => partBtn(b, p).classList.contains('confident')
    && partBtn(b, p).getAttribute('aria-pressed') === 'true'),
    'a confident detection: every waiting part drawn approved (confident), pressed');
  ok(b.querySelector('.home-drops-btn.approve').classList.contains('half')
    && !b.querySelector('.home-drops-btn.approve').disabled,
    'its double tick is half-lit (only the detector approved it) and still makes it yours');
  ok(/high confidence · plays on its own/.test(b.querySelector('.home-drops-state')?.textContent ?? ''),
    'its line says high confidence, plays on its own');
  const a = rowByTime('0:44.0');
  ok(!a.querySelector('.home-drops-btn.approve').classList.contains('half'),
    'a suggestion\'s double tick is not half-lit');
  ok(H.nextPartState('confident') === 'off' && H.nextPartState('waiting') === 'on'
    && H.nextPartState('on') === 'off' && H.nextPartState('off') === 'on'
    && H.nextPartState('absent') === null, 'a tap: confident or on → off, waiting or off → on');
  const css = readFileSync(join(repo, 'spectra/web/src/styles/tokens.css'), 'utf8');
  ok(/\.home-drops-btn\.part\.confident::after\s*\{[^}]*border-radius:\s*50%/.test(css),
    'the detector dot is drawn (a small circle on the part)');
  // the server's answer under triggers-only: a confident drop waits and says why
  const waitsView = { ...VIEW, sequences: VIEW.sequences.map((q) => (q.key === 'drop:90000'
    ? { ...q, fires: false, fires_reason: 'analysed_show_off' } : q)) };
  const row = H.buildPanelRows(waitsView, { testing: false }).find((r) => r.key === 'drop:90000');
  ok(/high confidence · waits: only your own triggers play on this song/.test(row.stateLine)
    && !row.waiting, `where only his own triggers play it waits, says so, and is still not "to review" ("${row.stateLine}")`);
}

if (failures) {
  console.log(`\nFAIL: ${failures} check(s) failed`);
  process.exit(1);
}

console.log('\nOK: Home\'s Drops panel behaves as specified.');
process.exit(0);
