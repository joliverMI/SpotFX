// Executable spec for the Light Show "+ Add a step…" DIALOG fix — the
// Admiral, 2026-10-08, verbatim: "I'm trying to add a step to a Set, but
// it's so low on the page I can't see the options well, and it doesn't
// expand anywhere."
//
// Root cause (see AGENTS.md's SearchSelect section): "+ Add a step…" used
// to be an inline SearchSelect sitting at the BOTTOM of the steps list —
// on a set with several steps already, that control (and the dropdown it
// opens BELOW itself) sat right at the page's own bottom edge, where
// SearchSelect's own viewport-clamp logic has nothing below it to use
// (DROPDOWN_MIN_HEIGHT floor, 80px, "at the cost of overhanging it" per
// that component's own docstring).
//
// Fix: "+ Add a step…" is now a plain BUTTON that opens a DIALOG — the
// same fixed-overlay/centered-card shape every other dialog in this app
// uses (SpectraTriggerDialog.tsx, FlareKindEditDialog.tsx): `position:
// fixed; inset: 0`, so it is NEVER a descendant of the scrollable steps
// list and is NEVER subject to how far down the page the trigger button
// happened to be. Its own SearchSelect carries `autoFocus`, so the
// picker is already open and showing every kind the instant the dialog
// mounts — no second "open it" gesture needed.
//
// Mounts the REAL LightShowPage.tsx (esbuild-bundled with its real
// children), the check_light_show_pickers.mjs precedent — this script
// reuses that file's own harness shape, trimmed to a single large set.
//
//   ONE   — a set with many steps already (so "+ Add a step…" sits far
//           down the rendered list) still shows the control as an
//           ordinary button, never an inline picker.
//   TWO   — clicking it mounts a `position: fixed; inset: 0` overlay
//           (never inline at the bottom of the steps list) with its own
//           centered card, and the picker inside it is ALREADY OPEN
//           (autoFocus) showing every catalogue kind with no further
//           click.
//   THREE — picking a kind adds the step and closes the dialog.
//   FOUR  — clicking the dimmed backdrop closes it without adding a step.
//   FIVE  — the dialog's own Cancel button does the same.
//
// Run: node scripts/check_light_show_add_step_dialog.mjs
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

// ── fixtures — a set with NINE steps already, matching his real "Dinner
//    Party" shape, so "+ Add a step…" renders far down the page ──
const P = (name, type, extra = {}) => ({ name, type, label: name, default: null, required: false,
  choices: null, min: null, max: null, unit: '', help: '', ...extra });
const KINDS = [
  { kind: 'brightness', label: 'Brightness', group: 'setting', help: 'room brightness', restore: '', help_topic: 'show-actions',
    params: [P('level', 'number', { default: 0.8, min: 0, max: 1 })] },
  { kind: 'ambient', label: 'Ambient (Hue Hold)', group: 'setting', help: 'ambient', restore: '', help_topic: 'show-actions',
    params: [P('enabled', 'bool', { default: true })] },
  { kind: 'house_mode', label: 'House mode', group: 'setting', help: 'house mode', restore: '', help_topic: 'show-actions',
    params: [P('mode', 'house_mode')] },
  { kind: 'device_state', label: 'Device state', group: 'device', help: 'device state', restore: '', help_topic: 'show-actions',
    params: [P('target', 'target', { required: true }), P('state', 'enum', { choices: ['on', 'off'], default: 'on' })] },
  { kind: 'level', label: 'Level', group: 'device', help: 'level', restore: '', help_topic: 'show-actions',
    params: [P('target', 'target', { required: true }), P('level', 'number', { default: 0.5, min: 0, max: 1 })] },
  { kind: 'room_effect', label: 'Room effect', group: 'effect', help: 'room effect', restore: '', help_topic: 'show-actions',
    params: [P('effect', 'room_effect')] },
  { kind: 'scene', label: 'Fire scene', group: 'control', help: 'fire scene', restore: '', help_topic: 'show-actions',
    params: [P('scene', 'scene')] },
];
const manySteps = (n) => Array.from({ length: n }, (_, i) => ({
  id: `step-${i}`, kind: KINDS[i % KINDS.length].kind, params: {}, enabled: true,
}));
const SET = { id: 'set-1', name: 'Dinner Party', actions: manySteps(9) };
const STATUS = { active: true, started_ms: 1, baselines: [], room_effect: null, running_sets: [],
  recent_runs: [], output: { holds: [], levels: [], suspended: false, standdown: null, refusal: null },
  brief: {} };
const ANSWERS = {
  'GET /spectra/api/light-show/catalogue': { kinds: KINDS, room_effects: [], room_effect_schema: null,
    house_modes: [{ id: 'hm-std', name: 'Standard' }] },
  'GET /spectra/api/light-show/targets': { live: true,
    fixtures: [{ id: 'porch', name: 'Porch Rail', type: 'wled', held_by_ambient: false }],
    categories: [{ name: 'Singles', fixtures: [] }] },
  'GET /spectra/api/light-show/sets': { sets: [SET] },
  'GET /spectra/api/light-show/status': STATUS,
  'GET /spectra/api/light-show/arms': { armed: [], history: [], song: { uri: null, position_ms: null,
    cues: null, expected_scene_change_s: null, expected_scene_change_is_floor: true },
    last_crossed: {}, refusal: null },
};
const posted = [];
const NodeResponse = globalThis.Response;
const fakeFetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const path = String(url).replace(/^https?:\/\/[^/]+/, '').split('?')[0];
  if (method === 'POST') posted.push(path);
  const body = ANSWERS[`${method} ${path}`] ?? {};
  return new NodeResponse(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
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
const tmpDir = mkdtempSync(join(tmpdir(), 'lightshow-addstep-'));
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

const steps = () => [...container.querySelectorAll('li.light-show-step')];
const overlay = () => [...container.querySelectorAll('div')]
  .find((d) => d.getAttribute('style')?.includes('position: fixed') && d.getAttribute('style')?.includes('inset: 0'));
const dropdown = () => container.querySelector('div[style*="z-index: 60"]');
const options = () => [...(dropdown()?.children ?? [])].map((d) => d.textContent);
const click = async (el) => step(() => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));

console.log('ONE — a set with nine steps already renders "+ Add a step…" as a plain button');
ok(steps().length === 9, 'all nine steps render');
const addBtn = [...container.querySelectorAll('.light-show-add button')]
  .find((b) => b.textContent.includes('Add a step'));
ok(addBtn && addBtn.tagName === 'BUTTON', 'the control is a button');
ok(!container.querySelector('.light-show-add input'), 'no inline SearchSelect input sits in the steps flow');
ok(!overlay(), 'no dialog overlay before it is clicked');

console.log('TWO — clicking it opens a fixed, full-viewport dialog with the picker ALREADY open');
await click(addBtn);
const ov = overlay();
ok(!!ov, 'a position:fixed, inset:0 overlay mounted — never inline at the page\'s own bottom edge');
ok(ov.querySelector('.card-title')?.textContent.includes('Add a step'), 'the dialog card is titled "Add a step"');
ok(options().length === KINDS.length, `the picker is open with no further click — all ${KINDS.length} kinds shown (${options().length})`);
ok(KINDS.every((k) => options().some((t) => t.endsWith(k.label))), 'every catalogue kind is offered');

console.log('THREE — picking a kind adds the step and closes the dialog');
const opt = [...dropdown().children].find((d) => d.textContent.endsWith('Fire scene'));
await step(() => opt.dispatchEvent(new dom.window.MouseEvent('mousedown', { bubbles: true })));
ok(steps().length === 10, 'a tenth step was added');
ok(!overlay(), 'the dialog closed itself');

console.log('FOUR — clicking the dimmed backdrop closes it without adding a step');
await click(addBtn);
ok(!!overlay(), 'reopened');
await click(overlay());
ok(!overlay(), 'backdrop click closed it');
ok(steps().length === 10, 'no step was added by the backdrop click');

console.log('FIVE — the dialog\'s own Cancel button does the same');
await click(addBtn);
const cancelBtn = [...overlay().querySelectorAll('button')].find((b) => b.textContent === 'Cancel');
ok(!!cancelBtn, 'a Cancel button exists');
await click(cancelBtn);
ok(!overlay(), 'Cancel closed the dialog');
ok(steps().length === 10, 'no step was added by Cancel');

unmount();
console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
