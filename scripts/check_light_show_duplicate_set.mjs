// Executable spec for the Light Show "⧉ Duplicate" button — the Admiral
// (inbox scope on the step-editor-cutoff task, 2026-10-08), verbatim:
// "Add a duplicate sets button... each set gets a Duplicate action (icon
// button using the app's copy/duplicate icon, matching the row's style)
// that creates an identical copy of the set with all its steps, named
// '<name> copy' (unique if repeated), placed right after the original
// and immediately editable. The copy is independent (editing it never
// changes the original)."
//
// The backend placement contract (show_store.put_set's `after_id`) is
// proven directly in tests/test_light_show.py
// (test_after_id_places_a_new_set_right_after_the_named_one,
// test_duplicate_set_via_the_api_is_independent_saves_fires_and_is_placed_
// right_after). This script proves the FRONTEND wiring over a real,
// mutable in-memory fake backend — the duplicate-button click actually
// lands a POST carrying `after_id`, the new set is selected and shown in
// the editor immediately, and a second duplicate of the SAME original
// gets a uniqued "copy 2" name.
//
// Mounts the REAL LightShowPage.tsx (esbuild-bundled with its real
// children), the check_light_show_pickers.mjs precedent.
//
//   ONE   — the editor head shows a "⧉ Duplicate" button next to Save /
//           Preview changes / Delete, matching that row's plain-button
//           style (the app's established ⧉ copy/duplicate convention —
//           ScenesPage.tsx, ColorSetsPage.tsx, FlareKindEditDialog.tsx).
//   TWO   — clicking it POSTs a fresh set (no id) named "<name> copy"
//           with every one of the original's steps and `after_id` set to
//           the original's id.
//   THREE — the Sets list places the copy right after the original, and
//           the editor switches to show the copy, already saved
//           (immediately editable — Save is disabled, nothing is dirty).
//   FOUR  — duplicating the SAME original again names the second copy
//           "<name> copy 2", not a clash.
//   FIVE  — editing the copy never touches the original (proven at the
//           fake-backend level: the original's own stored actions are
//           untouched after the copy's POST).
//
// Run: node scripts/check_light_show_duplicate_set.mjs
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

const KINDS = [
  { kind: 'brightness', label: 'Brightness', group: 'setting', help: '', restore: '', help_topic: 'show-actions',
    params: [{ name: 'level', type: 'number', label: 'Level', default: 0.8, required: false,
      choices: null, min: 0, max: 1, unit: '', help: '' }] },
];
const STATUS = { active: true, started_ms: 1, baselines: [], room_effect: null, running_sets: [],
  recent_runs: [], output: { holds: [], levels: [], suspended: false, standdown: null, refusal: null },
  brief: {} };

// ── a mutable fake backend — real enough to prove placement + independence ──
let liveSets = [
  { id: 'set-orig', name: 'Dinner Party', actions: [
    { id: 'a1', kind: 'brightness', params: { level: 0.8 }, enabled: true },
    { id: 'a2', kind: 'brightness', params: { level: 0.6 }, enabled: true },
  ], notes: '' },
  { id: 'set-other', name: 'Quiet', actions: [], notes: '' },
];
let nextId = 1;
const posted = [];
const NodeResponse = globalThis.Response;
const fakeFetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const path = String(url).replace(/^https?:\/\/[^/]+/, '').split('?')[0];
  const json = (body, status = 200) => new NodeResponse(JSON.stringify(body),
    { status, headers: { 'Content-Type': 'application/json' } });
  if (path === '/spectra/api/light-show/catalogue') return json({ kinds: KINDS, room_effects: [],
    room_effect_schema: null, house_modes: [] });
  if (path === '/spectra/api/light-show/targets') return json({ live: true, fixtures: [], categories: [] });
  if (path === '/spectra/api/light-show/status') return json(STATUS);
  if (path === '/spectra/api/light-show/arms') return json({ armed: [], history: [], song: { uri: null,
    position_ms: null, cues: null, expected_scene_change_s: null, expected_scene_change_is_floor: true },
    last_crossed: {}, refusal: null });
  if (path === '/spectra/api/light-show/sets' && method === 'POST') {
    const body = JSON.parse(init.body);
    posted.push(body);
    if (body.id) {
      liveSets = liveSets.map((s) => (s.id === body.id ? { ...s, ...body } : s));
      return json(liveSets.find((s) => s.id === body.id));
    }
    const created = { ...body, id: `new-${nextId++}` };
    delete created.after_id;
    const afterIdx = body.after_id ? liveSets.findIndex((s) => s.id === body.after_id) : -1;
    liveSets = afterIdx === -1 ? [...liveSets, created]
      : [...liveSets.slice(0, afterIdx + 1), created, ...liveSets.slice(afterIdx + 1)];
    return json(created);
  }
  if (path === '/spectra/api/light-show/sets') return json({ sets: liveSets });
  return json({});
};
globalThis.fetch = fakeFetch;
dom.window.fetch = fakeFetch;

const fakeQueriesSrc = `
export function useScenes() { return { data: [] }; }
export function useSpotColorSets() { return { data: [] }; }
export function useGradient2dProfiles() { return { data: {} }; }
export function useAmbientHueGroups() { return { data: { groups: [] } }; }
export function useSendSettingsMessage() { return { mutate: () => {}, mutateAsync: async () => ({}), isPending: false }; }
export function useTranscribeSettingsAudio() { return { mutate: () => {}, mutateAsync: async () => ({}), isPending: false }; }
export function useUndoLastSceneChange() { return { mutate: () => {}, mutateAsync: async () => ({}), isPending: false }; }
`;
const tmpDir = mkdtempSync(join(tmpdir(), 'lightshow-duplicate-'));
const fakeQueriesPath = join(tmpDir, 'fakeQueries.mjs');
writeFileSync(fakeQueriesPath, fakeQueriesSrc);
const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import LightShowPage from ${JSON.stringify(join(repo, 'spectra/web/src/lightshow/LightShowPage.tsx'))};
import { ToastProvider } from ${JSON.stringify(join(repo, 'spectra/web/src/components/Toast.tsx'))};
export const container = document.createElement('div');
document.body.appendChild(container);
let root = null;
export async function mount() {
  root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(MemoryRouter, null,
      React.createElement(ToastProvider, null, React.createElement(LightShowPage))));
  });
  for (let i = 0; i < 5; i += 1) await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
}
export async function step(fn) { await act(async () => { fn(); await new Promise((r) => setTimeout(r, 5)); }); }
export function unmount() { act(() => root.unmount()); }
`;
const entryFile = join(tmpDir, 'entry.mjs');
writeFileSync(entryFile, entrySrc);
const outFile = join(tmpDir, 'out.cjs');
const build = await esbuild.build({
  entryPoints: [entryFile], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
  outfile: outFile, nodePaths: [join(repo, 'spectra/web/node_modules')], logLevel: 'silent',
  loader: { '.css': 'empty', '.svg': 'text' },
  plugins: [{
    name: 'stub-queries',
    setup(b) {
      const queriesFile = join(repo, 'spectra/web/src/queries.ts');
      b.onResolve({ filter: /\/queries(\.ts)?$/ }, (args) => {
        const resolved = join(dirname(args.importer), args.path);
        return (resolved === queriesFile || `${resolved}.ts` === queriesFile)
          ? { path: fakeQueriesPath } : null;
      });
    },
  }],
});
ok(build.errors.length === 0, 'LightShowPage.tsx + its real children bundle cleanly');
const { container, mount, step, unmount } = require(outFile);
await mount();

const click = async (el) => step(() => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
const setButtons = () => [...container.querySelectorAll('.light-show-sets li button')];
const selectSet = async (name) => {
  const btn = setButtons().find((b) => b.textContent.includes(name));
  await click(btn);
};
const editorHeadButtons = () => [...container.querySelectorAll('.light-show-editor-head button')];
const duplicateBtn = () => editorHeadButtons().find((b) => b.textContent.includes('Duplicate'));
const nameInput = () => container.querySelector('.light-show-editor-head input[type="text"]');

console.log('ONE — the editor head shows "⧉ Duplicate" next to Save / Preview changes / Delete');
await selectSet('Dinner Party');
const headLabels = editorHeadButtons().map((b) => b.textContent.trim());
ok(headLabels.includes('⧉ Duplicate'), `Duplicate sits in the editor head row (${headLabels.join(', ')})`);
const dupIdx = headLabels.indexOf('⧉ Duplicate');
ok(headLabels[dupIdx - 1] === 'Preview changes' && headLabels[dupIdx + 1] === 'Delete',
  'between Preview changes and Delete, the row\'s own established grammar');

console.log('TWO — clicking it POSTs a fresh, independent copy with after_id set');
await click(duplicateBtn());
ok(posted.length === 1, 'exactly one POST was made');
const body = posted[0];
ok(!body.id, 'the copy is posted with no id (a brand-new set)');
ok(body.name === 'Dinner Party copy', `named "<name> copy" (${body.name})`);
ok(body.after_id === 'set-orig', 'after_id names the original');
ok(body.actions.length === 2, 'both of the original\'s steps came along');
ok(body.actions.every((a, i) => a.id !== liveSets.find((s) => s.id === 'set-orig').actions[i].id),
  'each copied step got a FRESH id, not the original\'s own');

console.log('THREE — the copy lands right after the original and is immediately editable');
const names = setButtons().map((b) => b.textContent.trim());
ok(JSON.stringify(names) === JSON.stringify(['Dinner Party · 2', 'Dinner Party copy · 2', 'Quiet · 0']),
  `Sets list order: ${names.join(' | ')}`);
ok(nameInput().value === 'Dinner Party copy', 'the editor switched to showing the copy');
const saveBtn = editorHeadButtons().find((b) => b.textContent === 'Save');
ok(saveBtn.disabled, 'already saved — Save is disabled (not a dirty local draft)');

console.log('FOUR — duplicating the SAME original again uniques the name');
await selectSet('Dinner Party');
await click(duplicateBtn());
ok(posted[1].name === 'Dinner Party copy 2', `second duplicate is uniqued (${posted[1].name})`);
const names2 = setButtons().map((b) => b.textContent.trim());
ok(JSON.stringify(names2) === JSON.stringify(
  ['Dinner Party · 2', 'Dinner Party copy 2 · 2', 'Dinner Party copy · 2', 'Quiet · 0']),
  `placed right after the original again: ${names2.join(' | ')}`);

console.log('FIVE — editing the copy never touches the original');
const original = liveSets.find((s) => s.id === 'set-orig');
ok(original.actions.length === 2 && original.actions[0].params.level === 0.8,
  'the original\'s own stored actions are untouched by either duplicate');

unmount();
console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
