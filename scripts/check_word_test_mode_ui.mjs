// Executable spec for WORD TEST MODE's three UI surfaces (2026-11-17 — the
// Admiral: "did we implement a system to 'test' where all word flares
// (shape or color) fire, no matter the confidence? how do i turn that on?",
// and "Settings, no auto off").
//
// The REAL components, mounted under a real React 18 tree and a real
// @tanstack/react-query client in jsdom, with ONE seam faked: `fetch` (a
// recording fake of GET/PUT /spectra/api/room-controls, the same shape
// check_home_drops_panel.mjs uses for the Testing toggle).
//
//   ONE   the Settings card (settings/WordTestModeCard.tsx): off, it says
//         so and the box is clear; one tick sends exactly ONE PUT carrying
//         word_test_mode true and NOTHING else changed; it then says ON and
//         says it stays on until he turns it off; the card states the three
//         boundaries he is owed (a Never pin, the minimum gap, nothing
//         written)
//   THREE the roll line (testbed/lyricEvents.ts, pure): the counts are the
//         server's own, and the line says WHY they read 22 of 22
//
// (There was once a TWO, a top-bar banner — removed on his 2026-11-18 word,
// "I don't need the banner for the word shape test mode"; see the night-run
// doc's "why its own bar" paragraph for the history.)
//
// Run: node scripts/check_word_test_mode_ui.mjs
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
dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {},
  addListener() {}, removeListener() {} });
globalThis.matchMedia = dom.window.matchMedia;

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

// ── the fake room-controls seam ───────────────────────────────────────────
// A deliberately WIDE state: the PUT is a true partial-merge on the server
// (room_controls.py), and the point of the "nothing else changed" check
// below is that these neighbours come back untouched.
const controls = {
  brightness_multiplier: 0.8,
  scene_change_mode: 'analysed',
  drop_testing: false,
  word_test_mode: false,
  word_shape_form_slow_s: 0.9,
};
const calls = [];
const json = (status, data) => ({ ok: status < 400, status, json: async () => structuredClone(data) });
globalThis.fetch = async (url, opts = {}) => {
  const u = new URL(url, 'http://localhost');
  const method = (opts.method || 'GET').toUpperCase();
  const body = opts.body ? JSON.parse(opts.body) : undefined;
  calls.push({ method, path: u.pathname, body });
  if (u.pathname === '/spectra/api/room-controls' && method === 'GET') return json(200, controls);
  if (u.pathname === '/spectra/api/room-controls' && method === 'PUT') {
    Object.assign(controls, body);
    return json(200, { state: controls });
  }
  return json(404, { detail: `not in this fixture: ${method} ${u.pathname}` });
};

const src = (p) => JSON.stringify(join(repo, 'spectra/web/src', p));
const tmpDir = mkdtempSync(join(tmpdir(), 'word-test-mode-'));
const entryFile = join(tmpDir, 'entry.mjs');
writeFileSync(entryFile, `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import WordTestModeCard from ${src('settings/WordTestModeCard.tsx')};
export * as events from ${src('testbed/lyricEvents.ts')};

const container = document.createElement('div');
document.body.appendChild(container);

export async function settle(rounds = 8) {
  for (let i = 0; i < rounds; i += 1) {
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
  }
}

export async function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(MemoryRouter, { initialEntries: ['/settings'] },
        React.createElement(WordTestModeCard))));
  });
  await settle();
  return container;
}

export async function click(el) {
  await act(async () => { el.dispatchEvent(new window.MouseEvent('click', { bubbles: true })); });
  await settle();
}
`);
const outFile = join(tmpDir, 'out.cjs');
const build = await esbuild.build({
  entryPoints: [entryFile], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
  outfile: outFile, nodePaths: [join(repo, 'spectra/web/node_modules')],
  loader: { '.css': 'empty' },
  plugins: [{
    name: 'song-strip-fix',
    setup(b) {
      // components/songStrip.ts sits beside SongStrip.tsx: esbuild matches
      // an extension-less import of it case-insensitively and fails
      // (AGENTS.md's own note; check_home_drops_panel.mjs carries the same
      // two lines). Vite resolves it fine.
      b.onResolve({ filter: /(^|\/)songStrip$/ }, () => (
        { path: join(repo, 'spectra/web/src/components/songStrip.ts') }
      ));
    },
  }],
  logLevel: 'silent',
});
ok(build.errors.length === 0, build.errors.length === 0
  ? 'the real card and bar bundle cleanly'
  : `bundle failed: ${build.errors.map((e) => e.text).join('; ')}`);
const H = require(outFile);

const container = await H.mount();
const puts = () => calls.filter((c) => c.method === 'PUT');
const card = () => container.querySelector('.settings-word-test-card');
const box = () => card().querySelector('input[type=checkbox]');

console.log('ONE  the Settings card');
{
  ok(card() !== null, 'the card is on the page');
  ok(box() !== null && box().checked === false, 'off by default, the box clear');
  const state = card().querySelector('.settings-word-test-state').textContent;
  ok(/^Off/.test(state), `off, it says so ("${state.slice(0, 24)}…")`);
  const note = card().querySelector('.settings-word-test-note').textContent;
  ok(/Never/.test(note), 'the card says a Never pin still never plays');
  ok(/minimum gap/.test(note) && /8 s/.test(note),
    'and that the 8 s minimum gap still holds — the rule he will otherwise read as a bug');
  ok(/not written to/.test(note), 'and that his pins and kept rolls are not written to');

  const before = puts().length;
  await H.click(box());
  const sent = puts().slice(before);
  ok(sent.length === 1 && sent[0].body.word_test_mode === true,
    `one tick sends exactly ONE PUT turning it on (${sent.length} PUT(s))`);
  ok(sent.length === 1 && sent[0].body.brightness_multiplier === 0.8
    && sent[0].body.drop_testing === false
    && sent[0].body.word_shape_form_slow_s === 0.9,
    'and carries every other setting back unchanged');
  ok(controls.word_test_mode === true, 'the store now holds it on');
  const on = card().querySelector('.settings-word-test-state');
  ok(on.classList.contains('on') && /^ON/.test(on.textContent),
    'the card says ON');
  ok(/until you turn it off/.test(on.textContent),
    'and says it stays on until he turns it off — there is no auto-off');
  ok(card().classList.contains('settings-word-test-on'),
    'and the card itself wears the on state');
}

console.log('THREE  the roll line');
{
  const ev = H.events;
  const roll = { state: 'sample', seed: 1, tag: '0001', started_ms: 0, kept: false,
                 kept_seed: null, playing: false, n_words: 22, n_won: 22, test_mode: true };
  const line = ev.rollWords(roll);
  ok(/22 of 22 words would play/.test(line), 'the counts are the server\'s own');
  ok(/Word test mode is on/.test(line),
    `and the line says WHY they read that way ("${line}")`);
  ok(!/Word test mode/.test(ev.rollWords({ ...roll, test_mode: false })),
    'and says nothing of it while the switch is off');
  ok(!/Word test mode/.test(ev.rollWords({ ...roll, test_mode: undefined })),
    'an older server that does not send the flag reads as off');
}

console.log(failures === 0 ? '\nALL CHECKS PASSED' : `\n${failures} CHECK(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
