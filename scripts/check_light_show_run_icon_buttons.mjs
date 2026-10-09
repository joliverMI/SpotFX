// Executable spec for the Light Show Run view's "Sets — tap to run" row —
// the Admiral, 2026-10-08, verbatim: "on the Sets - tap to run section,
// make each row instead have buttons for each thing with an icon. fire
// now is the bolt, next scene change is a bunny icon, and then up arrow
// for next high triggher and down arrow for low trigger. i just tap it
// and it happens."
//
// Mounts the REAL RunView.tsx (esbuild-bundled with its real children —
// Icon, ArmBoard, ShowNowPanel …) under jsdom with `react-dom/client`,
// the check_light_show_pickers.mjs precedent. `../queries` (pulled in
// transitively through `./LightShowPage`, which RunView imports
// `ShowNowPanel` from) is stood in by a fixture module; `window.fetch` is
// stood in by canned /spectra/api/light-show answers recorded as they
// arrive — there is no backend here.
//
//   ONE   — each set row renders exactly four icon buttons (never a
//           name-button-opens-a-sheet control), each a real inline SVG
//           (iconRegistry.ts), never a raw Unicode glyph.
//   TWO   — a tap on each icon IS the complete action, with no
//           intermediate menu/sheet: bolt fires the set now; bunny arms
//           on the next scene change; up arrow arms on the next High
//           Trigger; down arrow arms on the next Low Trigger.
//   THREE — a set armed for MORE THAN ONE trigger at once shows an
//           "Armed for the …" tag for EVERY one of them, not just the
//           first (the regression this branch's own review commit fixed:
//           `.find` → `.filter`).
//   FOUR  — each armed tag's own Cancel button disarms exactly that arm
//           (DELETE /arms/<id>), not some other arm on the same set.
//   FIVE  — the specific icon button a set is armed on (bunny/up/down)
//           carries the `armed` class — filled/accent, clearly different
//           from idle — driven by live `arms` status, not a local click
//           flag: present on a FRESH render (no click at all) and gone
//           the instant `arms` no longer lists it (his ask, 2026-10-08:
//           "highlight" the armed button so it is right after a refresh
//           or when armed from Sonic/another screen).
//
// Run: node scripts/check_light_show_run_icon_buttons.mjs
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
// Quiet Hues is armed for TWO triggers at once (scene_change AND high) —
// the exact shape the review fix's regression covers (one row, several
// simultaneous arms). Blues has none.
const SETS = [
  { id: 'set-quiet', name: 'Quiet Hues', actions: [{ id: 'a1', kind: 'force_scene', params: {}, enabled: true }] },
  { id: 'set-blues', name: 'Blues', actions: [{ id: 'a2', kind: 'color_set_now', params: {}, enabled: true }] },
];
const ARMS = {
  armed: [
    { id: 'arm-sc', set_id: 'set-quiet', action: null, label: 'Quiet Hues', on: 'scene_change',
      repeat: false, song_uri: null, source: 'manual', finish_on_mark: false, created_ms: 0,
      expires_ms: null, status: 'armed', fire_count: 0, ended_ms: null, end_reason: '', last_outcome: null },
    { id: 'arm-high', set_id: 'set-quiet', action: null, label: 'Quiet Hues', on: 'high',
      repeat: false, song_uri: null, source: 'manual', finish_on_mark: false, created_ms: 0,
      expires_ms: null, status: 'armed', fire_count: 0, ended_ms: null, end_reason: '', last_outcome: null },
  ],
  history: [],
  song: { uri: null, position_ms: null, cues: null, expected_scene_change_s: null, expected_scene_change_is_floor: true },
  last_crossed: {},
  refusal: null,
};
const STATUS = {
  active: true, started_ms: 1, baselines: [], room_effect: null, running_sets: [], recent_runs: [],
  output: { holds: [], levels: [], suspended: false, standdown: null, refusal: null },
  brief: {},
};
const requests = []; // { method, path, body }
const ANSWERS = {
  'POST /spectra/api/light-show/sets/set-blues/fire': { id: 'run-1', name: 'Blues', set_id: 'set-blues',
    source: 'manual', started_ms: 1, ended_ms: 1, state: 'done', steps: [] },
  'POST /spectra/api/light-show/arms': { id: 'arm-new' },
};
const NodeResponse = globalThis.Response;
const fakeFetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const path = String(url).replace(/^https?:\/\/[^/]+/, '').split('?')[0];
  const body = init.body ? JSON.parse(init.body) : null;
  requests.push({ method, path, body });
  const answer = ANSWERS[`${method} ${path}`] ?? {};
  return new NodeResponse(JSON.stringify(answer), { status: 200, headers: { 'Content-Type': 'application/json' } });
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
const tmpDir = mkdtempSync(join(tmpdir(), 'lightshow-run-icons-'));
const fakeQueriesPath = join(tmpDir, 'fakeQueries.mjs');
writeFileSync(fakeQueriesPath, fakeQueriesSrc);

const toasts = [];
const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import RunView from ${JSON.stringify(join(repo, 'spectra/web/src/lightshow/RunView.tsx'))};
export const container = document.createElement('div');
document.body.appendChild(container);
let root = null;
let sets = ${JSON.stringify(SETS)};
let arms = ${JSON.stringify(ARMS)};
let status = ${JSON.stringify(STATUS)};
const toasts = globalThis.__toasts__ = [];
function App() {
  return React.createElement(RunView, {
    sets, status, arms,
    onChangeArms: () => {},
    onEndShowDone: () => {},
    toast: (msg, kind) => toasts.push({ msg, kind }),
  });
}
export async function mount() {
  root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(MemoryRouter, null, React.createElement(App)));
  });
  for (let i = 0; i < 5; i += 1) await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
}
export async function rerenderWithArms(newArms) {
  arms = newArms;
  await act(async () => {
    root.render(React.createElement(MemoryRouter, null, React.createElement(App)));
  });
  await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
}
export async function step(fn) { await act(async () => { fn(); await new Promise((r) => setTimeout(r, 15)); }); }
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
ok(build.errors.length === 0, 'RunView.tsx + its real children (Icon, ArmBoard, ShowNowPanel) bundle cleanly');
const { container, mount, step, rerenderWithArms, unmount } = require(outFile);
await mount();

const rows = () => [...container.querySelectorAll('li.light-show-run-set-row')];
const rowFor = (name) => rows().find((li) => li.querySelector('.light-show-run-set-name')?.textContent.startsWith(name));
const iconBtns = (row) => [...row.querySelectorAll('button.light-show-run-set-icon-btn')];
const svgD = (btn) => btn.querySelector('svg path')?.getAttribute('d');
const click = async (btn) => step(() => btn.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));

console.log('ONE — each row is four real icon buttons, no sheet');
ok(rows().length === SETS.length, `both sets render as rows (${rows().length})`);
ok(container.querySelector('.light-show-run-sheet') === null, 'the old open/close sheet is gone');
ok(container.querySelector('.light-show-run-set-button') === null, 'the old name-button-opens-sheet control is gone');
const blues = rowFor('Blues');
const blueBtns = iconBtns(blues);
ok(blueBtns.length === 4, `Blues row has 4 icon buttons (${blueBtns.length})`);
const [boltBtn, bunnyBtn, upBtn, downBtn] = blueBtns;
ok(boltBtn.title === 'Fire now' && !!svgD(boltBtn), 'button 1 is Fire now, a real inline SVG');
ok(bunnyBtn.title === 'Arm: next scene change' && !!svgD(bunnyBtn), 'button 2 is Arm: next scene change, a real inline SVG');
ok(upBtn.title === 'Arm: next High Trigger' && !!svgD(upBtn), 'button 3 is Arm: next High Trigger, a real inline SVG');
ok(downBtn.title === 'Arm: next Low Trigger' && !!svgD(downBtn), 'button 4 is Arm: next Low Trigger, a real inline SVG');
ok(svgD(boltBtn) !== svgD(bunnyBtn) && svgD(bunnyBtn) !== svgD(upBtn) && svgD(upBtn) !== svgD(downBtn),
  'all four render genuinely different glyphs, not the same path repeated');
ok(![boltBtn, bunnyBtn, upBtn, downBtn].some((b) => /[⌀-⟿]/.test(b.textContent)),
  'no button falls back to a raw Unicode glyph in its text content');

console.log('TWO — a tap IS the action, no intermediate menu');
await click(boltBtn);
ok(requests.some((r) => r.method === 'POST' && r.path === '/spectra/api/light-show/sets/set-blues/fire'),
  `bolt fires the set now (${requests.map((r) => `${r.method} ${r.path}`).join(', ')})`);
requests.length = 0;

await click(bunnyBtn);
const armReq1 = requests.find((r) => r.method === 'POST' && r.path === '/spectra/api/light-show/arms');
ok(armReq1 && armReq1.body?.set_id === 'set-blues' && armReq1.body?.on === 'scene_change',
  `bunny arms on scene_change for set-blues (${JSON.stringify(armReq1?.body)})`);
ok(globalThis.__toasts__.some((t) => t.msg === 'Armed for the next scene change'),
  'the toast names the next scene change');
requests.length = 0;

await click(upBtn);
const armReq2 = requests.find((r) => r.method === 'POST' && r.path === '/spectra/api/light-show/arms');
ok(armReq2 && armReq2.body?.on === 'high', `up arrow arms on=high (${JSON.stringify(armReq2?.body)})`);
requests.length = 0;

await click(downBtn);
const armReq3 = requests.find((r) => r.method === 'POST' && r.path === '/spectra/api/light-show/arms');
ok(armReq3 && armReq3.body?.on === 'low', `down arrow arms on=low (${JSON.stringify(armReq3?.body)})`);
requests.length = 0;

console.log('THREE — a set armed for more than one trigger shows every arm, not just one');
const quiet = rowFor('Quiet Hues');
const tags = [...quiet.querySelectorAll('.light-show-run-set-armed-tag')];
ok(tags.length === 2, `Quiet Hues shows BOTH its arms, not just the first (${tags.length})`);
ok(tags.some((t) => t.textContent.includes('next scene change'))
  && tags.some((t) => t.textContent.includes('next High Trigger')),
  `the two tags name the two different arms (${tags.map((t) => t.textContent).join(' | ')})`);
ok([...blues.querySelectorAll('.light-show-run-set-armed-tag')].length === 0,
  'an unarmed set (Blues) shows no armed tag at all');

console.log('FOUR — each arm\'s own Cancel disarms exactly that arm');
const sceneTag = tags.find((t) => t.textContent.includes('next scene change'));
const cancelBtn = sceneTag.querySelector('button');
await click(cancelBtn);
ok(requests.some((r) => r.method === 'DELETE' && r.path === '/spectra/api/light-show/arms/arm-sc'),
  `Cancel on the scene-change tag deletes exactly arm-sc, not arm-high (${requests.map((r) => `${r.method} ${r.path}`).join(', ')})`);

console.log('(negative control) removing an arm from the fixture removes its tag');
await rerenderWithArms({ ...ARMS, armed: ARMS.armed.filter((a) => a.id !== 'arm-sc') });
const quietAfter = rowFor('Quiet Hues');
const tagsAfter = [...quietAfter.querySelectorAll('.light-show-run-set-armed-tag')];
ok(tagsAfter.length === 1 && tagsAfter[0].textContent.includes('next High Trigger'),
  `only the remaining arm (High Trigger) still shows a tag (${tagsAfter.map((t) => t.textContent).join(' | ')})`);

console.log('FIVE — the armed icon itself is highlighted, driven by live arms status');
// Fresh render (no clicks at all): Quiet Hues is armed on scene_change
// AND high in the ORIGINAL fixture, proving the highlight comes from the
// initial arms poll, not from a click earlier in this same script.
await rerenderWithArms(ARMS);
const [, quietBunny, quietUp, quietDown] = iconBtns(rowFor('Quiet Hues'));
ok(quietBunny.classList.contains('armed') && quietUp.classList.contains('armed'),
  'bunny (scene_change) and up arrow (high) are both marked armed');
ok(!quietDown.classList.contains('armed'), 'down arrow (low) — not armed — carries no armed class');
ok(quietBunny.getAttribute('aria-pressed') === 'true' && quietDown.getAttribute('aria-pressed') === 'false',
  'aria-pressed reflects the same live state for assistive tech');
const [blueBolt2, blueBunny2] = iconBtns(rowFor('Blues'));
ok(!blueBolt2.classList.contains('armed') && !blueBunny2.classList.contains('armed'),
  'an unarmed set\'s buttons carry no armed class at all');

await rerenderWithArms({ ...ARMS, armed: ARMS.armed.filter((a) => a.id !== 'arm-high') });
const [, quietBunny2, quietUp2] = iconBtns(rowFor('Quiet Hues'));
ok(quietBunny2.classList.contains('armed') && !quietUp2.classList.contains('armed'),
  'disarming the High arm clears ONLY that icon\'s highlight, scene_change stays lit');

unmount();
console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
