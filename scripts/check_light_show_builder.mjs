// Executable spec for the Light Show BUILDER upgrade — the Admiral,
// 2026-10-11: "upgrade the UI for building sets and sequences. The UI for
// building events/actions in spotfx was really good ... I like the drag and
// drop ordering, the collapsability, the copy ability. I'd also like to be
// able to reference other sets within sets."
//
//   ONE   — the pure helpers (builderOps.ts): which sets a set calls, the
//           cycle test that keeps a looping set out of the picker, the
//           collapsed one-line summaries, a paste's fresh ids.
//   TWO   — the REAL LightShowPage.tsx under jsdom (only fetch and
//           ../queries stood in): steps start collapsed with a summary;
//           Expand all / Collapse all; a step drags to a new place with
//           the legacy editor's own library (dnd-kit) and Save posts the
//           new order; duplicate a step; copy a step and paste it into
//           another set with fresh ids; Copy set → Paste as new set.
//   THREE — set references: a "Run another set" step picks only sets that
//           would not loop, shows the steps it runs, opens the called set;
//           the called set says "Used by"; deleting it warns by name and
//           only then deletes with ?force=true.
//
// Run: node scripts/check_light_show_builder.mjs
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

const tmpDir = mkdtempSync(join(tmpdir(), 'lightshow-builder-'));

// ── ONE — pure helpers ─────────────────────────────────────────────────────
console.log('ONE — builderOps: references, cycles, summaries, fresh ids');
const opsOut = join(tmpDir, 'ops.cjs');
await esbuild.build({ entryPoints: [join(repo, 'spectra/web/src/lightshow/builderOps.ts')], bundle: true,
  format: 'cjs', platform: 'node', outfile: opsOut, logLevel: 'silent' });
const ops = require(opsOut);
const call = (id) => ({ id: `c-${id}`, kind: 'call_set', params: { set: id }, enabled: true });
const lib = [
  { id: 'A', name: 'A', actions: [call('B')] },
  { id: 'B', name: 'B', actions: [call('C')] },
  { id: 'C', name: 'C', actions: [] },
  { id: 'D', name: 'D', actions: [call('C')] },
];
ok(ops.calledIds([call('B'), call('B'), { kind: 'pause', params: {} }]).join() === 'B', 'calledIds lists each called set once');
ok(ops.wouldCycle('C', 'C', lib), 'a set calling itself is a cycle');
ok(ops.wouldCycle('C', 'A', lib), 'C calling A loops (A → B → C)');
ok(!ops.wouldCycle('A', 'D', lib), 'A calling D does not loop (a diamond is fine)');
ok(ops.callableSets('B', lib).map((s) => s.id).join() === 'C,D',
  `B may call C and D but not A (A runs B) (${ops.callableSets('B', lib).map((s) => s.id).join()})`);
ok(ops.callableSets('C', lib).length === 0, 'C may call nothing here: A, B and D all reach C');
ok(ops.callersOf('C', lib).map((s) => s.id).join() === 'B,D', 'C is used by B and D');
const kind = { kind: 'level', label: 'Level', params: [
  { name: 'target', type: 'target', label: 'Fixture or category' },
  { name: 'level', type: 'number', label: 'Level', unit: '' },
  { name: 'until', type: 'enum', label: 'Ends' }] };
const sum = ops.stepSummary({ kind: 'level', params: { target: { kind: 'fixture', id: 'porch' }, level: 0.4, until: 'scene_change' } },
  kind, { fixtures: new Map([['porch', 'Porch Rail']]) });
ok(sum === 'Porch Rail · level 0.4 · scene change', `a collapsed step reads in his words (${sum})`);
ok(ops.stepSummary(call('C'), { kind: 'call_set', params: [] }, { sets: new Map([['C', 'Defaults']]) }) === '“Defaults”',
  'a call names the set it runs');
ok(ops.stepSummary(call('Z'), { kind: 'call_set', params: [] }, { sets: new Map() }) === 'a set that no longer exists',
  'a call to a deleted set says so');
const fresh = ops.cloneFresh([call('C')]);
ok(fresh[0].id !== 'c-C' && fresh[0].params.set === 'C', 'a paste gets a fresh id but still calls the same set');
ok(ops.itemSummary({ kind: 'wait', arm: 'instant', wait: { kind: 'duration', seconds: 90, songs: [] } }, new Map()) === 'Wait 1:30',
  'a collapsed Wait says how long');
ok(ops.itemSummary({ kind: 'set', set_id: 'C', arm: 'high' }, new Map([['C', 'Drop']])) === 'Drop — Next High Trigger',
  'a collapsed Set item says the set and its arming');

// ── TWO/THREE — the mounted page ───────────────────────────────────────────
const P = (name, type, extra = {}) => ({ name, type, label: name, default: null, required: false,
  choices: null, min: null, max: null, unit: '', help: '', ...extra });
const KINDS = [
  { kind: 'display_mode', label: 'Display mode', group: 'setting', help: 'dark or light', restore: '', help_topic: 'show-actions',
    params: [P('mode', 'enum', { choices: ['default', 'dark', 'light'], default: 'dark' })] },
  { kind: 'pause', label: 'Pause', group: 'control', help: 'wait', restore: '', help_topic: 'show-sets',
    params: [P('seconds', 'number', { label: 'Wait', unit: 's', default: 2 })] },
  { kind: 'call_set', label: 'Run another set', group: 'control', help: 'run another set', restore: '',
    help_topic: 'show-set-references', params: [P('set', 'set', { label: 'Set', required: true })] },
  { kind: 'ha_volume', label: 'Music volume', group: 'home', help: 'a future kind', restore: '',
    help_topic: 'show-actions', params: [] },
];
let liveSets = [
  { id: 'defaults', name: 'Defaults', actions: [
    { id: 'd1', kind: 'display_mode', params: { mode: 'dark' }, enabled: true },
    { id: 'd2', kind: 'pause', params: { seconds: 3 }, enabled: true }],
    calls: [], used_by: [{ id: 'party', name: 'Party' }], used_in_sequences: [{ id: 'q1', name: 'Evening' }] },
  { id: 'party', name: 'Party', actions: [
    { id: 'p1', kind: 'call_set', params: { set: 'defaults' }, enabled: true },
    { id: 'p2', kind: 'display_mode', params: { mode: 'light' }, enabled: true },
    { id: 'p3', kind: 'pause', params: { seconds: 1 }, enabled: true }],
    calls: [{ id: 'defaults', name: 'Defaults', missing: false }], used_by: [], used_in_sequences: [] },
  { id: 'calm', name: 'Calm', actions: [], calls: [], used_by: [], used_in_sequences: [] },
];
const requests = [];
const fakeFetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const full = String(url).replace(/^https?:\/\/[^/]+/, '');
  const path = full.split('?')[0];
  const body = init.body ? JSON.parse(init.body) : null;
  requests.push({ method, path, full, body });
  let answer = {};
  if (method === 'GET' && path === '/spectra/api/light-show/sets') answer = { sets: liveSets };
  else if (method === 'GET' && path === '/spectra/api/light-show/catalogue') answer = { kinds: KINDS, room_effects: [], room_effect_schema: null, house_modes: [] };
  else if (method === 'GET' && path === '/spectra/api/light-show/targets') answer = { live: true, fixtures: [], categories: [] };
  else if (method === 'GET' && path === '/spectra/api/light-show/status') answer = { active: false, started_ms: null, baselines: [], room_effect: null, running_sets: [], recent_runs: [],
    output: { holds: [], levels: [], suspended: false, standdown: null, refusal: null }, brief: {} };
  else if (method === 'GET' && path === '/spectra/api/light-show/arms') answer = { armed: [], history: [], song: {}, last_crossed: {}, refusal: null };
  else if (method === 'POST' && path === '/spectra/api/light-show/sets') {
    const id = body.id ?? `new-${requests.length}`;
    const saved = { ...body, id, calls: [], used_by: [], used_in_sequences: [] };
    delete saved.after_id;
    liveSets = liveSets.some((s) => s.id === id) ? liveSets.map((s) => (s.id === id ? saved : s)) : [...liveSets, saved];
    answer = saved;
  } else if (method === 'DELETE') {
    liveSets = liveSets.filter((s) => !path.endsWith(`/${s.id}`));
    answer = { deleted: true };
  }
  return new Response(JSON.stringify(answer), { status: 200, headers: { 'Content-Type': 'application/json' } });
};
globalThis.fetch = fakeFetch;
dom.window.fetch = fakeFetch;
const confirms = [];
dom.window.confirm = (msg) => { confirms.push(msg); return true; };
globalThis.confirm = dom.window.confirm;

const fakeQueriesPath = join(tmpDir, 'fakeQueries.mjs');
writeFileSync(fakeQueriesPath, `
export function useScenes() { return { data: [] }; }
export function useSpotColorSets() { return { data: [] }; }
export function useGradient2dProfiles() { return { data: {} }; }
export function useAmbientHueGroups() { return { data: { groups: [] } }; }
export function useSendSettingsMessage() { return { mutate: () => {}, mutateAsync: async () => ({}), isPending: false }; }
export function useTranscribeSettingsAudio() { return { mutate: () => {}, mutateAsync: async () => ({}), isPending: false }; }
export function useUndoLastSceneChange() { return { mutate: () => {}, mutateAsync: async () => ({}), isPending: false }; }
`);
const entryFile = join(tmpDir, 'entry.mjs');
writeFileSync(entryFile, `
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
  for (let i = 0; i < 6; i += 1) await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
}
export async function step(fn, ms = 10) { await act(async () => { fn(); await new Promise((r) => setTimeout(r, ms)); }); }
export function unmount() { act(() => root.unmount()); }
`);
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
        return (resolved === queriesFile || `${resolved}.ts` === queriesFile) ? { path: fakeQueriesPath } : null;
      });
    },
  }],
});
console.log('TWO — the Set editor: collapse, drag, duplicate, copy / paste');
ok(build.errors.length === 0, 'LightShowPage.tsx + its real children bundle cleanly');
const { container, mount, step } = require(outFile);
await mount();

const q = (sel, root = container) => root.querySelector(sel);
const qa = (sel, root = container) => [...root.querySelectorAll(sel)];
const click = async (el, ms) => step(() => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })), ms);
const button = (text, root = container) => qa('button', root).find((b) => b.textContent.trim().startsWith(text));
const setButtons = () => qa('.light-show-sets li button');
const steps = () => qa('li.light-show-step');
const settle = (ms = 30) => step(() => {}, ms);

ok(steps().length === 2, `the first set (Defaults) shows its two steps (${steps().length})`);
ok(steps().every((li) => !q('.light-show-params', li)) && qa('.light-show-step-summary').length === 2,
  'steps start COLLAPSED, each with its one-line summary');
ok(q('.light-show-step-summary', steps()[0]).textContent === 'dark', 'the summary says what the step does');
ok(qa('.light-show-sets li button')[0].textContent.includes('used by 2'), 'the set list badges "used by 2"');
ok(q('.light-show-refs')?.textContent.includes('Used by 2') && q('.light-show-refs').textContent.includes('Party')
  && q('.light-show-refs').textContent.includes('Evening (sequence)'), 'the editor names who uses this set');
await click(button('Expand all'));
ok(steps().every((li) => q('.light-show-params', li)), 'Expand all opens every step');
ok(Boolean(button('Collapse all')), 'and the control turns into Collapse all');
await click(button('Collapse all'));
ok(steps().every((li) => !q('.light-show-params', li)), 'Collapse all closes them again');
await click(q('.light-show-step-head', steps()[1]));
ok(Boolean(q('.light-show-params', steps()[1])) && !q('.light-show-params', steps()[0]), 'tapping one row opens just that step');
await click(q('.light-show-step-head', steps()[1]));

// drag step 2 (pause) above step 1 with the handle — dnd-kit, as in the legacy editor
const rectAt = (i) => ({ x: 0, y: i * 60, left: 0, top: i * 60, right: 400, bottom: i * 60 + 50, width: 400, height: 50, toJSON() {} });
steps().forEach((li, i) => { li.getBoundingClientRect = () => rectAt(i); });
const pev = (type, y, pointerType = 'touch') => {
  const e = new dom.window.MouseEvent(type, { bubbles: true, cancelable: true, clientX: 200, clientY: y, button: 0 });
  Object.defineProperty(e, 'pointerId', { value: 3 });
  Object.defineProperty(e, 'isPrimary', { value: true });
  Object.defineProperty(e, 'pointerType', { value: pointerType });
  return e;
};
const handle = q('.light-show-step-handle', steps()[1]);
ok(Boolean(handle) && handle.getAttribute('aria-roledescription') === 'sortable', 'each step has a ⠿ sortable handle');
await step(() => handle.dispatchEvent(pev('pointerdown', 85)));
for (const y of [80, 70, 45, 20, 10]) await step(() => document.dispatchEvent(pev('pointermove', y)));
ok(steps()[1].classList.contains('dragging'), 'a finger drag lifts the step');
await step(() => document.dispatchEvent(pev('pointerup', 10)));
await settle();
ok(q('b', steps()[0]).textContent === 'Pause', 'released at the top, Pause is now step 1');
// a tap on the handle (no movement) is not a drag
const before = steps().map((li) => q('b', li).textContent).join();
await step(() => q('.light-show-step-handle', steps()[0]).dispatchEvent(pev('pointerdown', 25, 'mouse')));
await step(() => document.dispatchEvent(pev('pointerup', 25, 'mouse')));
ok(steps().map((li) => q('b', li).textContent).join() === before, 'a tap on the handle moves nothing');

await click(q('button[aria-label="Duplicate step"]', steps()[0]));
ok(steps().length === 3 && q('b', steps()[1]).textContent === 'Pause', 'duplicate puts a copy right after the step');
ok(Boolean(q('.light-show-params', steps()[1])), 'and opens the copy');
await click(button('Save'));
const savedDefaults = requests.filter((r) => r.method === 'POST' && r.path === '/spectra/api/light-show/sets').pop();
ok(savedDefaults?.body.actions.map((a) => a.kind).join() === 'pause,pause,display_mode',
  `Save posts the dragged order with the duplicate (${savedDefaults?.body.actions.map((a) => a.kind).join()})`);
ok(new Set(savedDefaults.body.actions.map((a) => a.id)).size === 3, 'the duplicate has its own id');
ok(!('used_by' in savedDefaults.body) && !('problems' in savedDefaults.body), 'served-only fields are not posted back');

await click(q('button[aria-label="Copy step"]', steps()[2]));
const clip = JSON.parse(localStorage.getItem('spectra.lightshow.clipboard.v1'));
ok(clip?.kind === 'steps' && clip.steps.length === 1 && clip.steps[0].kind === 'display_mode', 'Copy puts the step on the clipboard');
await click(setButtons().find((b) => b.textContent.startsWith('Calm')));
ok(steps().length === 0, 'Calm is empty');
const paste = button('Paste 1 step');
ok(Boolean(paste), 'Calm offers "Paste 1 step"');
await click(paste);
ok(steps().length === 1 && q('b', steps()[0]).textContent === 'Display mode', 'paste lands the copied step');
await click(button('Save'));
const savedCalm = requests.filter((r) => r.method === 'POST' && r.path === '/spectra/api/light-show/sets').pop();
ok(savedCalm?.body.id === 'calm' && savedCalm.body.actions[0].id !== clip.steps[0].id,
  'pasted into Calm with a FRESH id');

await click(setButtons().find((b) => b.textContent.startsWith('Party')));
await click(button('Copy set'));
const before2 = requests.length;
await click(button('Paste as new set'), 40);
const created = requests.slice(before2).find((r) => r.method === 'POST' && r.path === '/spectra/api/light-show/sets');
ok(created && !created.body.id && created.body.name === 'Party copy' && created.body.actions.length === 3,
  `Copy set → Paste as new set posts a new set (${created?.body.name}, ${created?.body.actions?.length} steps)`);
ok(created && created.body.actions[0].params.set === 'defaults' && created.body.actions[0].id !== 'p1',
  'its "Run another set" step still calls Defaults, with a fresh id');

console.log('THREE — sets that call sets');
await click(setButtons().find((b) => b.textContent.startsWith('Party') && !b.textContent.includes('copy')));
ok(q('.light-show-refs')?.textContent.includes('Runs') && q('.light-show-refs').textContent.includes('Defaults'),
  'Party says it runs Defaults');
const callRow = steps()[0];
ok(callRow.classList.contains('call') && q('.light-show-step-summary', callRow).textContent === '“Defaults”',
  'the call step reads "Run another set · “Defaults”" collapsed');
await click(q('.light-show-step-head', callRow));
const called = q('.light-show-called', steps()[0]);
ok(called && called.textContent.includes('Defaults') && called.textContent.includes('Pause'),
  'open, it lists the steps it will run');
const input = q('.light-show-param input', steps()[0]);
await step(() => { input.focus(); input.dispatchEvent(new dom.window.Event('focus', { bubbles: true })); });
const opts = qa('div[style*="z-index: 60"] > div').map((d) => d.textContent);
ok(!opts.includes('Party'), `the picker never offers the set itself (${opts.join(' | ')})`);
await click(q('button[aria-label="Open Defaults"]', steps()[0]));
ok(q('.light-show-editor-head input').value === 'Defaults', '↗ opens the called set in the editor');
// Defaults is called by Party: its picker must not offer Party (Party → Defaults → Party would loop)
await click(button('Expand all'));
await click(button('+ Add a step'));
const dlgInput = q('div[style*="position: fixed"] input');
ok(Boolean(dlgInput), 'the add-step dialog opens');
const kindsShown = qa('div[style*="z-index: 60"] > div').map((d) => d.textContent);
ok(kindsShown.some((t) => t.includes('Run another set')), '"Run another set" is in the catalogue picker');
ok(kindsShown.some((t) => t.includes('Music volume')), 'a kind in a group this page never heard of still lists');
const pick = qa('div[style*="z-index: 60"] > div').find((d) => d.textContent.includes('Run another set'));
await step(() => pick.dispatchEvent(new dom.window.MouseEvent('mousedown', { bubbles: true })));
await step(() => pick.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
const newCall = steps().find((li) => li.classList.contains('call'));
ok(Boolean(newCall) && Boolean(q('.light-show-params', newCall)), 'the new call step opens ready to pick');
const ci = q('.light-show-param input', newCall);
await step(() => { ci.focus(); ci.dispatchEvent(new dom.window.Event('focus', { bubbles: true })); });
const callOpts = qa('div[style*="z-index: 60"] > div').map((d) => d.textContent);
ok(!callOpts.includes('Party') && !callOpts.includes('Defaults') && callOpts.includes('Calm'),
  `Defaults may not call Party (it would loop) nor itself (${callOpts.join(' | ')})`);
ok(/runs? this one/.test(q('.light-show-param-note', newCall)?.textContent ?? ''), 'and the editor says why a set is missing');

// delete warns by name, then deletes forced
confirms.length = 0;
await click(button('Discard') ?? button('Save'), 20);
await click(setButtons().find((b) => b.textContent.startsWith('Defaults')));
await click(button('Delete'), 40);
ok(confirms.some((m) => m.includes('Party') && m.includes('fail')),
  `deleting a used set warns, naming who uses it (${confirms.at(-1)})`);
const del = requests.filter((r) => r.method === 'DELETE').pop();
ok(del?.full.endsWith('/light-show/sets/defaults?force=true'), 'and only then deletes it, forced');

if (failures) { console.log(`\n${failures} check(s) failed`); process.exit(1); }
console.log('\nall passed');
process.exit(0);
