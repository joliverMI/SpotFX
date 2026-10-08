// Executable spec for the Light Show editor's pickers — the Admiral,
// 2026-10-08: "make the drop downs for things like color set/group and
// scene, etc, in the lightshow edit be searchable and match the other ui
// elements that do this."
//
// Mounts the REAL LightShowPage.tsx (esbuild-bundled with its real
// children — StepEditor, ParamField, SearchSelect, ShowNowPanel …) under
// jsdom with `react-dom/client`, exactly the check_topbar_scene_colour_
// names.mjs precedent. Only the data layer is stood in: `../queries` by a
// fixture module and `window.fetch` by canned /spectra/api/light-show
// answers (there is no backend here).
//
//   ONE   — every scene / colour set or group / gradient / house mode /
//           room effect / category / fixture picker in a step is the shared
//           SearchSelect (a text input), never a plain <select>; the only
//           <select>s left are short fixed choices (an enum, the target
//           kind, the arm trigger).
//   TWO   — typing filters a picker the way the top bar's Force Scene /
//           Force Colour pickers do, with the SAME labels (a group ▤, a
//           disabled card ⛔ — lib/pickerOptions.ts), and picking writes
//           the id into the step.
//   THREE — the multi-pick lists (scenes, colour sets) add through the same
//           searchable picker and show what is chosen as removable chips.
//   FOUR  — "+ Add a step…" is searchable too, and the new effect-modifier
//           kinds (Pulse reactivity, Pulse brightness, Flares on / off) are
//           in it.
//   FIVE  — "Right now" lists a Pulse hold and a flares-off switch with an
//           End / Flares on button that posts to their own routes.
//
// Run: node scripts/check_light_show_pickers.mjs
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
const SCENES = [
  { id: 'sc-bh', name: 'Black Hole V2', labels: ['dark'], disabled: false },
  { id: 'sc-fish', name: 'Fish', labels: [], disabled: false },
  { id: 'sc-star', name: 'STAR', labels: [], disabled: true },
];
const CARDS = [
  { id: 'cs-blues', name: 'Blues', kind: 'group' },
  { id: 'cs-ocean', name: 'Ocean Blue', kind: 'set' },
  { id: 'cs-ember', name: 'Ember', kind: 'set', disabled: true },
];
const P = (name, type, extra = {}) => ({ name, type, label: name, default: null, required: false,
  choices: null, min: null, max: null, unit: '', help: '', ...extra });
const TARGET = P('target', 'target', { label: 'Fixture or category', required: true });
const KINDS = [
  { kind: 'force_scene', label: 'Force a scene', group: 'setting', help: '', restore: '', help_topic: 'show-actions',
    params: [P('on', 'bool', { default: true }), P('scene', 'scene')] },
  { kind: 'color_set_now', label: 'Apply a colour set now', group: 'setting', help: '', restore: '', help_topic: 'show-actions',
    params: [P('color_set', 'color_set')] },
  { kind: 'scenes_onoff', label: 'Scenes on / off', group: 'setting', help: '', restore: '', help_topic: 'show-actions',
    params: [P('scenes', 'scenes'), P('color_sets', 'color_sets')] },
  { kind: 'gradient', label: 'Drift gradient', group: 'setting', help: '', restore: '', help_topic: 'show-actions',
    params: [P('gradient', 'gradient'), P('mode', 'house_mode')] },
  { kind: 'flares', label: 'Flares on / off', group: 'effect', help: 'switch flares', restore: '', help_topic: 'show-flares',
    params: [TARGET, P('flares', 'enum', { choices: ['off', 'on'], default: 'off' })] },
  { kind: 'pulse_reactivity', label: 'Pulse reactivity', group: 'effect', help: 'pulse', restore: '', help_topic: 'show-pulse',
    params: [TARGET, P('reactivity', 'number', { min: 0, max: 1, default: 0.5 })] },
  { kind: 'pulse_brightness', label: 'Pulse brightness floor / ceiling', group: 'effect', help: 'pulse', restore: '', help_topic: 'show-pulse',
    params: [TARGET, P('floor', 'number', { min: 0, max: 1, default: 0 })] },
];
const SET = { id: 'set-1', name: 'Quiet Hues', actions: [
  { id: 'a1', kind: 'force_scene', params: { on: true }, enabled: true },
  { id: 'a2', kind: 'color_set_now', params: {}, enabled: true },
  { id: 'a3', kind: 'scenes_onoff', params: { scenes: ['sc-fish'] }, enabled: true },
  { id: 'a4', kind: 'gradient', params: {}, enabled: true },
  { id: 'a5', kind: 'flares', params: { target: { kind: 'category', id: null }, flares: 'off' }, enabled: true },
  { id: 'a6', kind: 'pulse_reactivity', params: { target: { kind: 'fixture', id: null } }, enabled: true },
] };
const STATUS = {
  active: true, started_ms: 1, baselines: [], room_effect: null, running_sets: [], recent_runs: [],
  output: { holds: [], levels: [], suspended: false, standdown: null, refusal: null,
    pulse_mods: [{ id: 'pm-1', virtual_ids: ['hues'], label: 'Singles', reactivity: 0.3,
      floor: null, ceiling: null, until: 'released', remaining_s: null }],
    flare_blocks: [{ id: 'fb-1', virtual_ids: ['hues'], label: 'Hue Living', until: 'released',
      remaining_s: null }] },
  brief: {},
};
const posted = [];
const ANSWERS = {
  'GET /spectra/api/light-show/catalogue': { kinds: KINDS, room_effects: [], room_effect_schema: null,
    house_modes: [{ id: 'hm-std', name: 'Standard' }, { id: 'hm-eve', name: 'Evening' }] },
  'GET /spectra/api/light-show/targets': { live: true,
    fixtures: [{ id: 'hue-living', name: 'Hue Living Room', type: 'hue', held_by_ambient: false },
      { id: 'porch', name: 'Porch Rail', type: 'wled', held_by_ambient: false }],
    categories: [{ name: 'Singles', fixtures: [] }, { name: 'Matrix', fixtures: [] }, { name: 'Strips', fixtures: [] }] },
  'GET /spectra/api/light-show/sets': { sets: [SET] },
  'GET /spectra/api/light-show/status': STATUS,
  'GET /spectra/api/light-show/arms': { armed: [], history: [], song: { uri: null, position_ms: null,
    cues: null, expected_scene_change_s: null, expected_scene_change_is_floor: true },
    last_crossed: {}, refusal: null },
};
const fakeFetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const path = String(url).replace(/^https?:\/\/[^/]+/, '').split('?')[0];
  if (method === 'POST') posted.push(path);
  const body = ANSWERS[`${method} ${path}`] ?? {};
  return new NodeResponse(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
};
const NodeResponse = globalThis.Response;
globalThis.fetch = fakeFetch;
dom.window.fetch = fakeFetch;

const fakeQueriesSrc = `
export function useScenes() { return { data: ${JSON.stringify(SCENES)} }; }
export function useSpotColorSets() { return { data: ${JSON.stringify(CARDS)} }; }
export function useGradient2dProfiles() { return { data: { 'g-sunset': { name: 'Sunset' }, 'g-sea': { name: 'Deep Sea' } } }; }
export function useAmbientHueGroups() { return { data: { groups: [{ id: 'a1', name: 'Living' }] } }; }
export function useSendSettingsMessage() { return { mutate: () => {}, mutateAsync: async () => ({}), isPending: false }; }
export function useTranscribeSettingsAudio() { return { mutate: () => {}, mutateAsync: async () => ({}), isPending: false }; }
export function useUndoLastSceneChange() { return { mutate: () => {}, mutateAsync: async () => ({}), isPending: false }; }
`;
const tmpDir = mkdtempSync(join(tmpdir(), 'lightshow-pickers-'));
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
const stepNamed = (label) => steps().find((li) => li.querySelector('b')?.textContent === label);
const paramNamed = (li, label) => [...li.querySelectorAll('label.light-show-param, div.light-show-param')]
  .find((l) => l.querySelector('.light-show-param-label')?.textContent.startsWith(label));
const dropdown = () => container.querySelector('div[style*="z-index: 60"]');
const options = () => [...(dropdown()?.children ?? [])].map((d) => d.textContent);
const setNative = (input, value) => {
  const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, value);
  input.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
};
const focus = async (input) => step(() => { input.focus(); input.dispatchEvent(new dom.window.FocusEvent('focusin', { bubbles: true })); });
const type = async (input, text) => step(() => setNative(input, text));
const choose = async (label) => step(() => {
  const opt = [...dropdown().children].find((d) => d.textContent.endsWith(label));
  opt.dispatchEvent(new dom.window.MouseEvent('mousedown', { bubbles: true }));
});
const close = async (input) => step(() => {
  document.body.dispatchEvent(new dom.window.MouseEvent('mousedown', { bubbles: true }));
  input.blur();
});

console.log('ONE — entity pickers are the shared SearchSelect, never a <select>');
ok(steps().length === SET.actions.length, `the set's ${SET.actions.length} steps render`);
const sceneField = paramNamed(stepNamed('Force a scene'), 'scene');
ok(sceneField && !sceneField.querySelector('select') && sceneField.querySelector('input[type=text]'),
  'scene: a searchable text input, no <select>');
for (const [kind, label] of [['Apply a colour set now', 'color_set'], ['Drift gradient', 'gradient'],
  ['Drift gradient', 'mode']]) {
  const f = paramNamed(stepNamed(kind), label);
  ok(f && !f.querySelector('select') && f.querySelector('input[type=text]'), `${label}: searchable, no <select>`);
}
const remaining = [...container.querySelectorAll('.light-show-steps select')];
const allowed = remaining.every((s) => [...s.options].length <= 4);
ok(allowed, `only short fixed choices stay <select>s (${remaining.length}: ${remaining.map((s) => [...s.options].map((o) => o.value).join('/')).join(', ')})`);

console.log('TWO — typing filters, labels match the top bar, picking writes the id');
let input = sceneField.querySelector('input[type=text]');
await focus(input);
ok(options().some((t) => t.endsWith('⛔ STAR')), 'a disabled scene is ⛔-prefixed, as in Force Scene');
await type(input, 'fi');
ok(options().length === 1 && options()[0].endsWith('Fish'), `"fi" filters the scenes to Fish (${options().join(' | ')})`);
await type(input, 'dark');
ok(options().length === 1 && options()[0].endsWith('Black Hole V2'), 'a scene\'s labels are searchable too');
await choose('Black Hole V2');
ok(input.value === 'Black Hole V2', `picking shows its name (${input.value})`);
ok(container.querySelector('.light-show-editor-head button:not([disabled])')?.textContent.includes('Fire'),
  'the editor is still live after a pick');
const csInput = paramNamed(stepNamed('Apply a colour set now'), 'color_set').querySelector('input');
await focus(csInput);
ok(options().some((t) => t.endsWith('▤ Blues')) && options().some((t) => t.endsWith('⛔ Ember')),
  'colour groups ▤ and disabled cards ⛔, as in Force Colour');
await type(csInput, 'blue');
ok(options().length === 2, `"blue" finds the Blues group and Ocean Blue (${options().join(' | ')})`);
await choose('Ocean Blue');
ok(csInput.value === 'Ocean Blue', 'picking a colour set writes it');
const modeInput = paramNamed(stepNamed('Drift gradient'), 'mode').querySelector('input');
await focus(modeInput);
await type(modeInput, 'eve');
ok(options().length === 1 && options()[0].endsWith('Evening'), 'house modes filter too');
await close(modeInput);

console.log('THREE — multi-pick lists add through the same picker, chips remove');
const scenesField = paramNamed(stepNamed('Scenes on / off'), 'scenes');
const chipLabels = () => [...scenesField.querySelectorAll('button.active')].map((b) => b.textContent);
ok(chipLabels().length === 1 && chipLabels()[0].startsWith('Fish'), 'the chosen scene shows as a chip');
const addScene = scenesField.querySelector('input');
await focus(addScene);
ok(!options().some((t) => t.endsWith('Fish')), 'an already-chosen scene is not offered again');
await type(addScene, 'black');
await choose('Black Hole V2');
ok(chipLabels().length === 2, 'adding through the search adds a chip');
await step(() => scenesField.querySelector('button.active').dispatchEvent(
  new dom.window.MouseEvent('click', { bubbles: true })));
ok(chipLabels().length === 1 && chipLabels()[0].startsWith('Black Hole'), 'a chip click removes it');

console.log('TARGETS — category and fixture are searchable');
const catField = paramNamed(stepNamed('Flares on / off'), 'Fixture or category');
const catInput = catField.querySelector('input');
ok(catInput && catField.querySelectorAll('select').length === 1, 'category: a search input beside the 3-way kind select');
await focus(catInput);
await type(catInput, 'sing');
await choose('Singles');
ok(catInput.value === 'Singles', 'Singles picked by typing');
const fixInput = paramNamed(stepNamed('Pulse reactivity'), 'Fixture or category').querySelector('input');
await focus(fixInput);
await type(fixInput, 'hue');
ok(options().length === 1 && options()[0].endsWith('Hue Living Room'), 'fixtures filter by name and type');
await choose('Hue Living Room');

console.log('FOUR — "+ Add a step…" is searchable and has the new kinds');
const add = container.querySelector('.light-show-add input');
ok(add && !container.querySelector('.light-show-add select'), 'Add a step is a search input');
await focus(add);
ok(['Pulse reactivity', 'Pulse brightness floor / ceiling', 'Flares on / off']
  .every((k) => options().some((t) => t.endsWith(k))), 'the three new kinds are offered');
await type(add, 'flare');
await choose('Flares on / off');
ok(steps().length === SET.actions.length + 1, 'picking one adds the step');

console.log('FIVE — Right now shows the Pulse hold and the flares-off switch');
const now = container.querySelector('.light-show-now');
ok(now?.textContent.includes('reactivity 0.3') && now.textContent.includes('Flares off for Hue Living'),
  'both holds are listed');
const flaresOnBtn = [...now.querySelectorAll('button')].find((b) => b.textContent === 'Flares on');
await step(() => flaresOnBtn.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
const endBtn = [...now.querySelectorAll('button')].find((b) => b.textContent === 'End');
await step(() => endBtn.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
ok(posted.includes('/spectra/api/light-show/flare-blocks/fb-1/end')
  && posted.includes('/spectra/api/light-show/pulse-mods/pm-1/end'),
  `the buttons post to their own end routes (${posted.join(', ')})`);

unmount();
console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
