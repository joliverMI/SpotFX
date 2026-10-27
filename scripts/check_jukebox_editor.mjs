// Executable spec for the Jukebox page (/jukebox — spectra/web/src/jukebox/,
// data/jukebox-plan/report.md §5 and phase 1 PR 1.3). The jsdom real-mount
// pattern of check_absorb_page.mjs: bundle the REAL source with esbuild,
// mount it under jsdom against a RECORDING fake of SpotFX's own
// /api/jukebox routes (no network — every request lands in `world.requests`
// and nothing else), and drive real events.
//
// Three things proven:
//   1. The editor's click rules (jukeboxEditor.ts, pure): a set song gets a
//      slot after it, a slot gets another right after it — never more than
//      three — and × removes one; the inputs are never mutated; the slot
//      counts and the program bar read the SERVER's projection; a song
//      within two of the playing one can't move; and the words.
//   2. The page, mounted: clicking a set song / a slot / × in Manual PUTs
//      exactly the slots the rule says; Auto → Manual copies the server's
//      own `manual_equivalent`; the sign-in warning shows; the Live tab is
//      read-only (no control in it writes) and shows the night.
//   3. Help: every topic is a real HELP_SECTIONS entry, the menu row's "?"
//      maps /jukebox to `jukebox`, /jukebox is in the Engine menu — and,
//      behaviourally, hovering the page's own controls opens each topic.
//
// Run: node scripts/check_jukebox_editor.mjs (tests/test_jukebox_editor.py).
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
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
  const tmp = mkdtempSync(join(tmpdir(), `jukebox-${name}-`));
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

function loadData(file, name) {
  const code = esbuild.transformSync(readFileSync(file, 'utf8'), { loader: 'ts', format: 'cjs' }).code;
  const tmp = mkdtempSync(join(tmpdir(), `jukebox-${name}-`));
  const outFile = join(tmp, 'out.cjs');
  writeFileSync(outFile, code);
  return require(outFile);
}

const t = (n) => `spotify:track:jukeboxcheck${String(n).padStart(8, '0')}`;
const setItem = (i, title) => ({ uri: t(i), title, artist: `Artist ${i}`, duration_ms: (200 + i) * 1000 });
const open = { kind: 'open', uri: '', title: '', artist: '', duration_ms: 0, set_index: null, entry_id: '', committed: false, starts_in_ms: null };
const setPI = (it, i) => ({ kind: 'set', uri: it.uri, title: it.title, artist: it.artist, duration_ms: it.duration_ms, set_index: i, entry_id: '', committed: false, starts_in_ms: null });

// ── 1. the pure rules ─────────────────────────────────────────────────────
console.log('§1 jukeboxEditor.ts — the click rules and the words');
const E = await bundle(`export * from ${JSON.stringify(join(web, 'src/jukebox/jukeboxEditor.ts'))};`, 'editor');
{
  const none = [];
  const a = E.clickSetSong(none, t(1));
  ok(a.length === 1 && a[0].after_uri === t(1) && a[0].count === 1, 'click a set song: one slot after it');
  ok(none.length === 0, 'the input list is never mutated');
  ok(E.clickSetSong(a, t(1)) === a, 'clicking a song that already has a slot changes nothing');
  const b = E.clickSlot(a, t(1));
  ok(E.slotsAfter(b, t(1)) === 2 && E.slotsAfter(a, t(1)) === 1, 'click a slot: another right after it (two in a row)');
  const c = E.clickSlot(b, t(1));
  ok(E.slotsAfter(c, t(1)) === 3, 'click again: three in a row');
  ok(E.clickSlot(c, t(1)) === c && E.slotsAfter(c, t(1)) === E.MAX_RUN, 'never more than three in a row');
  ok(E.clickSlot(none, t(9)) === none, 'clicking a slot that is not there changes nothing');
  const d = E.removeSlot(c, t(1));
  ok(E.slotsAfter(d, t(1)) === 2, '× removes one slot of a run');
  const e = E.removeSlot(E.removeSlot(d, t(1)), t(1));
  ok(e.length === 0, 'removing the last slot takes the run away');
  const other = E.clickSetSong(E.clickSetSong(none, t(1)), t(2));
  ok(E.slotsAfter(E.clickSlot(other, t(2)), t(1)) === 1, 'a click touches only its own song\'s run');

  const set = [setItem(0, 'A'), setItem(1, 'B'), setItem(2, 'C')];
  const lap = [setPI(set[0], 0), open, open, setPI(set[1], 1), setPI(set[2], 2), open];
  ok(JSON.stringify(E.slotsByIndex(lap, 3)) === '[2,0,1]', 'slot counts come from the server\'s projection');
  const segs = E.barSegments(lap, 1);
  ok(segs.length === 6 && segs.filter((s) => s.kind === 'slot').length === 3, 'the bar has one segment per item');
  ok(segs.find((s) => s.current)?.index === 1, 'the playing set song is marked on the bar');
  ok(E.canMove(5, null) && E.canMove(4, 2) && !E.canMove(3, 2) && !E.canMove(1, 2),
    'during a night only songs two or more ahead can move');
  ok(JSON.stringify(E.moved(['a', 'b', 'c', 'd'], 3, 1)) === '["a","d","b","c"]', 'moved() reorders a copy');

  ok(E.countLine({ set_songs: 38, slots: 21, unbounded: false, notes: [] }, 15)
    === '38 set songs · 21 jukebox slots ≈ 1.4 per guest at 15 guests', 'the count line, the plan\'s own example');
  ok(/as many slots as the line holds/.test(E.countLine({ set_songs: 5, slots: 0, unbounded: true, notes: [] }, 8)),
    'jukebox first has no fixed slot count');
  ok(/every set song/.test(E.ruleLine({ mode: 'auto', every: 1, run: 1, manual: [] }))
    && /2 jukebox slots in a row after every 3 set songs/.test(E.ruleLine({ mode: 'auto', every: 3, run: 2, manual: [] })),
  'the auto rule in words');
  ok(/click a set song/i.test(E.ruleLine({ mode: 'manual', every: 1, run: 1, manual: [] })), 'an empty manual program says how to start');

  ok(E.signInView({ state: 'ok', warning: null }) === null, 'no sign-in line while the sign-in is fine');
  ok(E.signInView({ state: 'soon', warning: 'w' })?.tone === 'warn', 'running out soon is a warning');
  ok(E.signInView({ state: 'refresh_failed', warning: 'x' })?.tone === 'danger', 'a refused sign-in is red');
  ok(JSON.stringify(E.nightWarnings({ warnings: ['sign', 'shuffle'], spotify_auth: { warning: 'sign' } }))
    === '["shuffle"]', 'the night\'s warnings without the sign-in line shown apart');
  ok(E.itemView({ ...open }).title === 'Open slot', 'an open slot reads as one');
  ok(E.itemView({ ...setPI(set[1], 1), kind: 'jukebox', committed: true }).sub.includes('sent to Spotify'),
    'a committed song says it was sent');
  ok(E.startsIn(0) === 'next' && E.startsIn(200_000) === 'in 3:20' && E.mmss(3_725_000) === '1:02:05', 'times');
}

// ── 2. the page, mounted ──────────────────────────────────────────────────
let jsdomMod;
try {
  jsdomMod = require('jsdom');
} catch {
  console.log('\njsdom not installed in spectra/web/node_modules (dev-only) — skipping §2-3.');
  report();
}
const { JSDOM } = jsdomMod;
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/jukebox' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
for (const k of ['HTMLElement', 'HTMLInputElement', 'Node', 'Element', 'MouseEvent', 'KeyboardEvent', 'Event', 'getComputedStyle']) {
  globalThis[k] = dom.window[k];
}
globalThis.localStorage = dom.window.localStorage;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SET = [setItem(0, 'Mr. Brightside'), setItem(1, 'Dancing Queen'), setItem(2, 'September'), setItem(3, 'Hey Ya!')];
let world;
function newWorld(kind) {
  const manual = kind === 'manual';
  const running = kind === 'running';
  return {
    config: { playlist: 'spotify:playlist:check', mode: manual ? 'manual' : 'auto', every: 2, run: 1,
              manual: manual ? [{ after_uri: t(1), count: 2 }] : [], run_out: 'again', commit_lead_s: 45 },
    running,
    requests: [],
  };
}
function lapFor(cfg) {
  const out = [];
  let since = 0;
  SET.forEach((it, i) => {
    out.push(setPI(it, i));
    let gap = 0;
    if (cfg.mode === 'manual') gap = cfg.manual.find((m) => m.after_uri === it.uri)?.count ?? 0;
    else { since += 1; if (since >= cfg.every) { gap = cfg.run; since = 0; } }
    for (let k = 0; k < gap; k += 1) out.push(open);
  });
  return out;
}
const sign = { state: 'soon', warning: 'SpotFX\'s Spotify sign-in runs out by 2026-11-05 (9 days left) — sign in again before then.', days_left: 9 };
function statusOf() {
  if (!world.running) return { night: null, running: false, now: null, next: [], line: [], warnings: [sign.warning], spotify_auth: sign, log: [], history: [] };
  return {
    night: { id: 'n', state: 'running', started_ms: 1, started_by: 'press', ended_ms: null, end_reason: '', end_detail: '', playlist_name: 'Saturday set', playlist_uri: '', played: 3, jukebox_played: 1 },
    running: true,
    now: { kind: 'set', uri: SET[1].uri, title: 'Dancing Queen', set_index: 1, entry_id: '', started_ms: 1 },
    remaining_ms: 40_000,
    next: [{ kind: 'jukebox', uri: 'spotify:track:j', title: 'Bad Romance', artist: 'Lady Gaga', duration_ms: 1, set_index: null, entry_id: 'e1', committed: true, starts_in_ms: 40_000 }],
    line: [{ id: 'e1', uri: 'spotify:track:j', title: 'Bad Romance', artist: 'Lady Gaga', duration_ms: 1, added_by: 'host', state: 'committed', doomed: false, commit_check: 'next' }],
    warnings: [sign.warning, 'Shuffle is on in Spotify, so the set won\'t play in order.'], spotify_auth: sign,
    log: ['started'], history: [],
  };
}

globalThis.fetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const body = init.body ? JSON.parse(init.body) : undefined;
  world.requests.push({ method, url: String(url), body });
  const json = (b) => new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } });
  const u = String(url);
  if (u.startsWith('/api/jukebox/config')) {
    if (method === 'PUT') { world.config = { ...world.config, ...body }; return json({ dry_run: false, config: world.config }); }
    return json(world.config);
  }
  if (u.startsWith('/api/jukebox/status')) return json(statusOf());
  if (u.startsWith('/api/jukebox/preview')) {
    return json({ status: 'ok', playlist_name: 'Saturday set', set_songs: SET.length, set: SET,
      lap_items: lapFor(world.config), next: [], playhead: world.running ? 1 : null,
      manual_equivalent: [{ after_uri: t(1), count: 1 }, { after_uri: t(3), count: 1 }],
      lap: { set_songs: SET.length, slots: lapFor(world.config).filter((x) => x.kind === 'open').length, unbounded: false, notes: [] } });
  }
  return json({});
};

const P = await bundle(`
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import JukeboxPage from ${JSON.stringify(join(web, 'src/jukebox/JukeboxPage.tsx'))};
import { ToastProvider } from ${JSON.stringify(join(web, 'src/components/Toast.tsx'))};
let root = null;
const container = document.createElement('div');
document.body.appendChild(container);
export function mount() {
  if (root) act(() => { root.unmount(); });
  root = createRoot(container);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(ToastProvider, null,
        React.createElement(MemoryRouter, { initialEntries: ['/jukebox'] }, React.createElement(JukeboxPage)))));
  });
  return container;
}
export async function settle(ms = 30) {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => { await new Promise((r) => setTimeout(r, ms)); });
  }
}
export function actSync(fn) { act(fn); }
export function unmount() { if (root) act(() => { root.unmount(); }); root = null; }
`, 'page');

const $ = (c, sel) => c.querySelector(sel);
const text = (el) => (el ? el.textContent : '');
const click = async (el) => {
  P.actSync(() => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true, cancelable: true })));
  await P.settle();
};
const buttonByText = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent));
const puts = () => world.requests.filter((r) => r.method === 'PUT');
const writes = () => world.requests.filter((r) => r.method !== 'GET');

console.log('\n§2 the editor, mounted — every click PUTs the slots the rule says');
{
  world = newWorld('manual');
  const c = P.mount();
  await P.settle();
  ok(!!$(c, '[data-testid="jukebox-set-list"]'), 'the running order renders');
  ok(c.querySelectorAll('.jukebox-slot').length === 2, 'Dancing Queen shows its two hand-placed slots');
  ok(text($(c, '[data-testid="jukebox-sign-in"]')).includes('runs out by'), 'the Spotify sign-in line shows its date');

  await click($(c, '[data-testid="set-song-2"]'));
  let last = puts().at(-1)?.body;
  ok(JSON.stringify(last) === JSON.stringify({ manual: [{ after_uri: t(1), count: 2 }, { after_uri: t(2), count: 1 }] }),
    `clicking September PUTs a slot after it (${JSON.stringify(last)})`);

  await click($(c, '[data-testid="slot-1-0"]'));
  last = puts().at(-1)?.body;
  ok(JSON.stringify(last.manual.find((m) => m.after_uri === t(1))) === JSON.stringify({ after_uri: t(1), count: 3 }),
    'clicking a slot PUTs another right after it (three in a row)');

  const x = c.querySelector('.jukebox-slot-x');
  await click(x);
  last = puts().at(-1)?.body;
  ok(last.manual.find((m) => m.after_uri === t(1))?.count === 2, '× PUTs one slot fewer');
  P.unmount();
}
{
  world = newWorld('auto');
  const c = P.mount();
  await P.settle();
  ok(c.querySelectorAll('.jukebox-slot-btn').length === 0, 'in Auto the slots are shown, not clickable');
  ok(!$(c, '[data-testid="set-song-0"]'), 'in Auto a set song is not a slot button');
  await click(buttonByText(c, /^Manual$/));
  const last = puts().at(-1)?.body;
  ok(last?.mode === 'manual' && JSON.stringify(last.manual) === JSON.stringify([{ after_uri: t(1), count: 1 }, { after_uri: t(3), count: 1 }]),
    'Auto → Manual copies the server\'s own manual_equivalent');
  const sel = c.querySelector('select[aria-label="When the set runs out"]');
  ok(!!sel, 'the run-out choice is on the page');
  P.unmount();
}
{
  world = newWorld('running');
  const c = P.mount();
  await P.settle();
  ok(c.querySelector('input[aria-label="Set playlist link"]')?.disabled === true,
    'the set playlist can\'t be swapped under a running night');
  ok(c.querySelectorAll('.jukebox-handle-off').length === 3,
    'the playing song and the one after it (and every earlier one) can\'t be dragged');
  const before = writes().length;
  await click(buttonByText(c, /^Live$/));
  ok(text($(c, '[data-testid="jukebox-night"]')).includes('Running since') && text($(c, '[data-testid="jukebox-night"]')).includes('Saturday set'),
    'the Live tab names the night');
  ok(text($(c, '[data-testid="jukebox-now"]')).includes('Dancing Queen') && text($(c, '[data-testid="jukebox-now"]')).includes('Set 2'),
    'and what is playing');
  ok(text($(c, '[data-testid="jukebox-next"]')).includes('sent to Spotify'), 'the committed song says it was sent');
  ok(text($(c, '[data-testid="jukebox-live-card"]')).includes('Shuffle is on')
    && !text($(c, '[data-testid="jukebox-live-card"]')).includes('runs out by'),
  'the night\'s own warning shows on Live; the sign-in line is not shown twice');
  const live = c.querySelector('[data-testid="jukebox-live-card"]')?.parentElement;
  for (const b of live ? [...live.querySelectorAll('button')] : []) await click(b);
  ok(writes().length === before, 'nothing on the Live tab writes — it is read-only');
  P.unmount();
}

// ── 3. help ───────────────────────────────────────────────────────────────
console.log('\n§3 help — every topic is real and reachable from the page');
{
  const topics = ['jukebox', 'jukebox-set-list', 'jukebox-slots', 'jukebox-live', 'jukebox-sign-in'];
  const { HELP_SECTIONS } = loadData(join(web, 'src/help/helpContent.ts'), 'help');
  const knownIds = new Set();
  for (const section of HELP_SECTIONS) {
    knownIds.add(section.id);
    for (const e of section.entries ?? []) knownIds.add(e.id);
    for (const sub of section.subsections ?? []) {
      knownIds.add(sub.id);
      for (const e of sub.entries ?? []) knownIds.add(e.id);
    }
  }
  for (const id of topics) ok(knownIds.has(id), `"${id}" is a real section/entry in HELP_SECTIONS`);
  const { topicForPath } = loadData(join(web, 'src/help/routeTopics.ts'), 'routes');
  ok(topicForPath('/jukebox') === 'jukebox', 'the menu row\'s "?" opens jukebox on /jukebox');
  const { NAV_GROUPS, activeGroupId, ALL_NAV_ROUTES } = loadData(join(web, 'src/nav/navGroups.ts'), 'nav');
  const item = NAV_GROUPS.find((g) => g.id === 'engine')?.items?.find((it) => it.to === '/jukebox');
  ok(!!item && item.icon === 'note' && activeGroupId('/jukebox') === 'engine' && ALL_NAV_ROUTES.includes('/jukebox'),
    '/jukebox is in the Engine menu');

  const reached = new Set();
  const hoverAll = (c) => {
    for (const tip of [...c.querySelectorAll('.info-tip')]) {
      P.actSync(() => tip.dispatchEvent(new dom.window.MouseEvent('mouseover', { bubbles: true, cancelable: true })));
    }
    for (const a of [...document.querySelectorAll('.info-tip-panel a.help-link')]) {
      const id = new URLSearchParams((a.getAttribute('href') || '').split('?')[1] || '').get('topic');
      if (id) reached.add(id);
    }
  };
  world = newWorld('running');
  const c = P.mount();
  await P.settle();
  hoverAll(c);
  await click(buttonByText(c, /^Live$/));
  hoverAll(c);
  ok(topics.every((id) => reached.has(id)) && reached.size === topics.length,
    `hovering the page's own controls opens exactly the five jukebox topics (${[...reached].sort().join(', ')})`);
  P.unmount();
}

report();
