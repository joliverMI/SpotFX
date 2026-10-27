// Executable spec for THE PRE-DROP CONTROLS (predrop plan step 5): the
// Phase tab's Pre-drops card and the drop-sequence preview's pre-drop.
//
//   §1  preDropWindows.ts, the pure half: a scene's window per kind (its
//       own, else the registry's default, else the model's), which edits
//       to it may be written (inside the kind's bounds, min below max),
//       the looks an entry may pick per kind ("auto" named when the effect
//       declares one, its looks for the kind, "same" for the vocal intro
//       only), the gap clamped into a window, the preview's request, and
//       the preview's sentence when the server sends none.
//   §2  PhaseTab.tsx, the REAL tab under jsdom (fetch intercepted): the
//       card links its help topic; a kind's power button writes
//       enabled: false; a min edit inside the bounds commits on blur, one
//       at or past the max does not (and says why), and Enter commits too;
//       a look select writes the entry's pre_drop_looks; an effect that
//       declares no looks shows the muted line instead of selects.
//   §3  SequencePreviewOverlay.tsx, the REAL overlay: every open carries
//       the draft's windows and looks; the kind switch sends the kind and a
//       gap clamped into the draft's window; the slider is that window; the
//       ruler draws the server's mark_s in the pre-drop's orange (dashed
//       when the scene would not play it) and the panel says the server's
//       sentence, or a plain one when it sends none. §3b: every live fire
//       of the loop carries the same pre-drop fields as the open.
//
// Synthetic data; never his storage. Run: node scripts/check_pre_drop_phase_tab.mjs
// (§2/§3 need the dev-only jsdom: cd spectra/web && npm install --no-save jsdom)
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const webDir = join(repo, 'spectra/web');
const require = createRequire(join(webDir, 'package.json'));
const esbuild = require('esbuild');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const tmpDir = mkdtempSync(join(tmpdir(), 'pre-drop-phase-tab-'));
const src = (p) => JSON.stringify(join(webDir, 'src', p));

async function bundle(entrySrc, tag) {
  const entryFile = join(tmpDir, `entry-${tag}.mjs`);
  writeFileSync(entryFile, entrySrc);
  const outFile = join(tmpDir, `out-${tag}.cjs`);
  const build = await esbuild.build({
    entryPoints: [entryFile], bundle: true, format: 'cjs', platform: 'node',
    jsx: 'automatic', loader: { '.css': 'empty' }, outfile: outFile,
    nodePaths: [join(webDir, 'node_modules')], logLevel: 'silent',
  });
  ok(build.errors.length === 0, build.errors.length === 0
    ? `${tag}: bundles cleanly with its real imports`
    : `${tag}: bundle failed: ${build.errors.map((e) => e.text).join('; ')}`);
  return require(outFile);
}

const finish = () => {
  rmSync(tmpDir, { recursive: true, force: true });
  if (failures) {
    console.log(`\nFAILED: ${failures} check(s)`);
    process.exit(1);
  }
  console.log('\nOK: the pre-drop Phase tab controls behave as specified.');
  // jsdom and react-query leave timers behind; the checks are done
  process.exit(0);
};

// A registry with the pre-drop kinds and one effect that declares looks
// (synthetic — no real effect declares one yet).
const REGISTRY = {
  categories: {},
  effects: {
    fireworks: {
      params: {},
      pre_drop_looks: {
        looks: { burst: { label: 'Burst', kinds: ['spike', 'intro'] },
                 bloom: { label: 'Slow bloom', kinds: ['intro'] } },
        auto: { spike: 'burst', intro: 'bloom' },
      },
    },
    melt: { params: {} },
  },
  pre_drop: {
    kinds: {
      spike: { label: 'Spike', min_bound: 250, max_bound: 3000, default_min_ms: 350, default_max_ms: 2000 },
      intro: { label: 'Vocal intro', min_bound: 350, max_bound: 4500, default_min_ms: 350, default_max_ms: 4000 },
    },
  },
};
const entry = (id, target, effect, looks) => ({
  id, target_kind: 'category', target, effect_type: effect, params: {}, effect_steps: [],
  color: { mode: 'set', color_kind: null, color_value: null, bg_color: null, bg_mode: null },
  brightness: null, background_brightness: null, drift: {},
  ...(looks ? { pre_drop_looks: looks } : {}),
});

/* ── §1 the pure half ── */
console.log('§1 preDropWindows.ts — windows, edits, looks, the preview request');
const W = await bundle(`export * from ${src('scenes/tabs/preDropWindows.ts')};`, 'pure');
{
  const bare = { id: 's', devices: [] };
  const sp = W.windowFor(bare, 'spike');
  const it = W.windowFor(bare, 'intro');
  ok(sp.enabled && sp.min_ms === 350 && sp.max_ms === 2000 && it.min_ms === 350 && it.max_ms === 4000,
    'a scene without windows (an older server) gets the model\'s defaults: spike 350-2000, intro 350-4000');
  const reg = { ...REGISTRY, pre_drop: { kinds: { ...REGISTRY.pre_drop.kinds,
    spike: { ...REGISTRY.pre_drop.kinds.spike, default_min_ms: 400, default_max_ms: 1800 } } } };
  const rs = W.windowFor(bare, 'spike', reg);
  ok(rs.min_ms === 400 && rs.max_ms === 1800, 'the registry\'s defaults win over the fallback');
  const own = { enabled: false, min_ms: 600, max_ms: 900 };
  ok(W.windowFor({ ...bare, pre_drop_spike: own }, 'spike') === own, 'a scene\'s own window is used as it is');
  const m = W.kindMeta(REGISTRY, 'spike');
  const win = { enabled: true, min_ms: 350, max_ms: 2000 };
  let r = W.editWindow(win, 'min_ms', '500', m);
  ok(r.ok && r.window.min_ms === 500 && r.window.max_ms === 2000, 'a min inside the bounds is applied');
  r = W.editWindow(win, 'min_ms', '2500', m);
  ok(!r.ok && /shortest gap must stay below the longest \(2000 ms\)/.test(r.note),
    `a min past the max is refused, saying why — ${r.note}`);
  r = W.editWindow(win, 'min_ms', '2000', m);
  ok(!r.ok, 'a min EQUAL to the max is refused too (min < max)');
  r = W.editWindow(win, 'max_ms', '300', m);
  ok(!r.ok && /longest gap must stay above the shortest \(350 ms\)/.test(r.note), 'a max under the min is refused');
  r = W.editWindow(win, 'min_ms', '200', m);
  ok(!r.ok && /spike window runs 250-3000 ms, so 200 ms was not applied/.test(r.note),
    `outside the kind's bounds is refused — ${r.note}`);
  r = W.editWindow(win, 'max_ms', '3500', m);
  ok(!r.ok, 'a spike max past 3000 is refused');
  r = W.editWindow(win, 'max_ms', 'abc', m);
  ok(!r.ok && /number of milliseconds/.test(r.note), 'a non-number is refused');
  const im = W.kindMeta(undefined, 'intro');
  r = W.editWindow({ enabled: true, min_ms: 350, max_ms: 4000 }, 'max_ms', '4500', im);
  ok(r.ok && r.window.max_ms === 4500, 'a vocal intro\'s max may reach 4500 (fallback bounds)');

  ok(W.lookOptions(undefined, 'spike') === null && W.lookOptions({ looks: {}, auto: {} }, 'intro') === null,
    'an effect declaring no looks has no options (the card shows the muted line)');
  const decl = REGISTRY.effects.fireworks.pre_drop_looks;
  const so = W.lookOptions(decl, 'spike');
  ok(JSON.stringify(so) === JSON.stringify([
    { value: 'auto', label: 'Recommended (Burst)' }, { value: 'burst', label: 'Burst' }]),
  `the spike: Recommended names the auto look, then the looks for the spike, never "same" — ${JSON.stringify(so)}`);
  const io = W.lookOptions(decl, 'intro');
  ok(io.map((o) => o.value).join() === 'auto,burst,bloom,same' && io[0].label === 'Recommended (Slow bloom)'
    && io.at(-1).label === 'Same as spike', `the vocal intro adds "Same as spike" — ${io.map((o) => o.label).join(' | ')}`);
  const kept = W.lookOptions(decl, 'spike', 'sparkle');
  ok(kept.at(-1).value === 'sparkle' && /not declared/.test(kept.at(-1).label),
    'a stored look the effect no longer declares is still shown, named as such');
  ok(W.noLooksLine('melt') === 'melt has no pre-drop look yet — its lull plays as before', 'the muted line');
  ok(W.clampGap(800, { enabled: true, min_ms: 1000, max_ms: 1500 }) === 1000
    && W.clampGap(2000, { enabled: true, min_ms: 350, max_ms: 1800 }) === 1800
    && W.clampGap(1234.4, win) === 1234, 'a gap is clamped into the window (and to whole ms)');
  const scene = { id: 's', devices: [entry('e1', 'Matrix', 'fireworks', { spike: 'burst', intro: 'same' }),
    entry('e2', 'Strips', 'melt')] };
  const req = W.previewPreDropRequest(scene, 'spike', 900, REGISTRY);
  ok(JSON.stringify(req) === JSON.stringify({
    pre_drop_kind: 'spike', pre_drop_gap_ms: 900,
    pre_drop_spike: { enabled: true, min_ms: 350, max_ms: 2000 },
    pre_drop_intro: { enabled: true, min_ms: 350, max_ms: 4000 },
    pre_drop_looks: { e1: { spike: 'burst', intro: 'same' }, e2: { spike: 'auto', intro: 'auto' } } }),
  `the preview request: kind, gap, both draft windows, every entry's looks — ${JSON.stringify(req)}`);
  const base = { kind: 'spike', gap_ms: 800, mark_s: 8.2, window: win, told: [], member_lull: null };
  ok(W.preDropSentence({ ...base, plays: true, reason: 'plays', sentence: 'From the server.' }) === 'From the server.',
    'the server\'s sentence is said as it is');
  ok(W.preDropSentence({ ...base, plays: true, reason: 'plays', sentence: '' })
    === 'A spike 800 ms before the drop plays on this scene: the drop\'s colour change fades across it.',
  'without one: a pre-drop that plays');
  ok(/^A vocal intro 5000 ms before the drop does not play on this scene \(outside_window\): the lull runs as before and the drop's colour change is instant\.$/
    .test(W.preDropSentence({ ...base, kind: 'intro', gap_ms: 5000, plays: false, reason: 'outside_window', sentence: '' })),
  'without one: a pre-drop that does not play');
}

/* ── jsdom for §2/§3 ── */
let jsdomMod;
try {
  jsdomMod = require('jsdom');
} catch {
  console.log('§2-§3 skipped: jsdom is not installed in spectra/web/node_modules (dev-only) — '
    + '`cd spectra/web && npm install --no-save jsdom` to run them');
  finish();
}
const { JSDOM } = jsdomMod;
const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://localhost/', pretendToBeVisual: true,
});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.SVGElement = dom.window.SVGElement;
globalThis.Node = dom.window.Node;
globalThis.localStorage = dom.window.localStorage;
globalThis.PointerEvent = dom.window.PointerEvent;
globalThis.KeyboardEvent = dom.window.KeyboardEvent;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
dom.window.requestAnimationFrame = globalThis.requestAnimationFrame;
dom.window.cancelAnimationFrame = globalThis.cancelAnimationFrame;
dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {},
  addListener() {}, removeListener() {} });
globalThis.matchMedia = dom.window.matchMedia;
dom.window.navigator.sendBeacon = () => true;
const svgProto = dom.window.SVGElement.prototype;
svgProto.setPointerCapture = function () {};
svgProto.releasePointerCapture = function () {};
// React's act() bookkeeping and React Router's v7 notices are noise here:
// every assertion below waits for the real fetch/render to settle first.
const quiet = (orig) => (...args) => {
  const text = String(args[0] ?? '');
  if (text.includes('not wrapped in act') || text.includes('React Router Future Flag')) return;
  orig(...args);
};
console.error = quiet(console.error);
console.warn = quiet(console.warn);

const json = (body, status = 200) => new Response(JSON.stringify(body),
  { status, headers: { 'Content-Type': 'application/json' } });
const opens = [];
const fires = [];
// §3b runs the loop for real: a short ruler with one cue, so it fires each lap
let shortLoop = false;
const preDropFor = (body) => {
  if (!body.pre_drop_kind) return null;
  const win = body.pre_drop_kind === 'spike' ? body.pre_drop_spike : body.pre_drop_intro;
  const gap = body.pre_drop_gap_ms;
  const plays = win.enabled && gap >= win.min_ms && gap <= win.max_ms;
  return {
    kind: body.pre_drop_kind, gap_ms: gap, mark_s: 9 - gap / 1000, window: win, plays,
    reason: plays ? 'plays' : 'kind_off',
    // the vocal intro answers without a sentence: the panel says its own
    sentence: body.pre_drop_kind === 'spike' ? `SERVER: a spike ${gap} ms out plays here.` : '',
    told: [], member_lull: null,
  };
};
const timeline = (body) => ({
  scene_id: 's1', scene_name: 'Test', intensity: 1, duration_s: shortLoop ? 0.3 : 10,
  gaps: { charge: 4444, lull: 2778 }, hang_fraction: 0.1,
  drop_timing: { offset_ms: 0, applied_ms: 0, source: 'room', scene_offset_ms: null, room_offset_ms: 0,
                 min_ms: -2000, max_ms: 2000, floor_applied_ms: -2000 },
  marks: [
    { event_class: 'lull', mark_s: 5.4, music_mark_s: 5.4, fire_at_s: 5.4, ramp_start_s: 5.4,
      ramp_end_s: 7.6, hang_end_s: 8.6, ramp_ms: 2200, hang_ms: 238, gap_ms: 2378, stretched: true,
      trigger_offset_ms: 0, drop_timing_offset_ms: 0, lead_ms: 0, anchor_rule: 'switch_end' },
    { event_class: 'drop', mark_s: 9, music_mark_s: 9, fire_at_s: 9, ramp_start_s: 9, ramp_end_s: 9.4,
      hang_end_s: 9.4, ramp_ms: 400, hang_ms: 0, gap_ms: null, stretched: false, trigger_offset_ms: 0,
      drop_timing_offset_ms: 0, lead_ms: 0, anchor_rule: 'drop_start' },
  ],
  cues: shortLoop ? [{ step: 'lull', at_s: 0, label: 'lull' }] : [], phase_targets: ['v1'], drop_switch: null,
  pre_drop: preDropFor(body),
});
dom.window.fetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const body = init.body ? JSON.parse(init.body) : undefined;
  if (url === '/spectra/api/registry' && method === 'GET') return json(REGISTRY);
  if (url === '/spectra/api/scenes' && method === 'GET') return json([]);
  if (url === '/spectra/api/preview/sequence/open' && method === 'POST') {
    opens.push(body);
    return json(timeline(body));
  }
  if (url === '/spectra/api/preview/sequence/fire' && method === 'POST') {
    fires.push(body);
    return json({ active: true, remaining_s: 10 });
  }
  if (url.startsWith('/spectra/api/flare-preview/') || url.startsWith('/spectra/api/preview/')) {
    return json({ active: true, remaining_s: 10 });
  }
  return json({ detail: `not in this fixture: ${method} ${url}` }, 404);
};
globalThis.fetch = dom.window.fetch;

const H = await bundle(`
import React, { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import PhaseTab from ${src('scenes/tabs/PhaseTab.tsx')};
import SequencePreviewOverlay from ${src('scenes/tabs/SequencePreviewOverlay.tsx')};

export const state = { writes: [], scene: null };
const roots = [];
function mountInto(el) {
  const box = document.createElement('div');
  document.body.appendChild(box);
  const root = createRoot(box);
  roots.push(root);
  return { box, root };
}
export async function unmountAll() {
  await act(async () => { roots.splice(0).forEach((r) => r.unmount()); });
}
export async function settle(ms = 30) {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)); });
}
function wrap(child) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return React.createElement(QueryClientProvider, { client: qc },
    React.createElement(MemoryRouter, null, child));
}
export async function mountTab(initial) {
  state.writes = [];
  const { box, root } = mountInto();
  function Host() {
    const [scene, setScene] = useState(initial);
    state.scene = scene;
    return React.createElement(PhaseTab, {
      scene, scenes: [scene],
      setScene: (s) => { state.writes.push(s); setScene(s); },
    });
  }
  await act(async () => { root.render(wrap(React.createElement(Host))); });
  return box;
}
export async function mountOverlay(scene) {
  const { box, root } = mountInto();
  await act(async () => {
    root.render(wrap(React.createElement(SequencePreviewOverlay, { scene, onClose: () => {} })));
  });
  return box;
}
`, 'tab');

const setValue = (el, value) => {
  const proto = el.tagName === 'SELECT' ? dom.window.HTMLSelectElement.prototype : dom.window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, String(value));
};
const type = (el, value) => {
  setValue(el, value);
  el.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
};
const blur = (el) => el.dispatchEvent(new dom.window.FocusEvent('focusout', { bubbles: true }));
const click = (el) => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));

/* ── §2 the real Phase tab ── */
console.log('§2 PhaseTab.tsx — the Pre-drops card writes the scene draft');
{
  const SCENE = {
    id: 's1', name: 'Test', labels: [], flare_kinds: [], responses: {}, update_kind: null,
    color_journey: { mode: 'inherit', pace_factor: 1, journey: null },
    choreography: { enabled: false, transition_ms: 800, transition_mode: 'Add', anchor_frac: 0.45 },
    entry_ramp_ms: 0, trigger_offset_ms: 0, accept_all_sets: true, accepted_set_ids: [],
    display_availability: 'default', preferred_color_set_mode: 'default', disabled: false,
    dwell_curve: null, drop_shock_enabled: true, drop_timing_offset_ms: null,
    pre_drop_spike: { enabled: true, min_ms: 350, max_ms: 2000 },
    pre_drop_intro: { enabled: true, min_ms: 350, max_ms: 4000 },
    devices: [entry('e1', 'Matrix', 'fireworks', { spike: 'auto', intro: 'auto' }), entry('e2', 'Strips', 'melt')],
  };
  const c = await H.mountTab(SCENE);
  await H.settle(60);
  const card = c.querySelector('[data-testid="pre-drop-card"]');
  ok(!!card, 'the Pre-drops card is on the Phase tab');
  const title = card?.previousElementSibling;
  ok(title && /Pre-drops/.test(title.textContent) && title.querySelector('a[href*="pre-drop-scene-window"]'),
    'its title links the pre-drop-scene-window help topic');
  ok(/falls inside this scene's window plays here/.test(card.textContent) && /colour change is instant/.test(card.textContent),
    'it says what the window means');
  const shock = [...c.querySelectorAll('.card-title')].map((t) => t.textContent.trim());
  ok(shock.findIndex((t) => t.startsWith('Drop Shockwave')) < shock.findIndex((t) => t.startsWith('Pre-drops')),
    'it comes after the Drop Shockwave block');

  // the power button
  const spikeRow = () => c.querySelector('[data-testid="pre-drop-row-spike"]');
  const power = spikeRow().querySelector('button[role="switch"]');
  ok(power?.getAttribute('aria-checked') === 'true'
    && power.getAttribute('aria-label') === 'Disable Spike pre-drops on this scene', 'the spike\'s power button is on');
  click(power);
  await H.settle();
  ok(H.state.writes.length === 1 && JSON.stringify(H.state.writes[0].pre_drop_spike)
    === '{"enabled":false,"min_ms":350,"max_ms":2000}',
  `tapping it writes enabled: false — ${JSON.stringify(H.state.writes[0]?.pre_drop_spike)}`);
  ok(JSON.stringify(H.state.writes[0].pre_drop_intro) === JSON.stringify(SCENE.pre_drop_intro),
    'the vocal intro\'s window is left alone');
  click(spikeRow().querySelector('button[role="switch"]'));
  await H.settle();
  ok(H.state.writes.at(-1).pre_drop_spike.enabled === true, 'and back on');

  // min / max edits
  const minField = () => spikeRow().querySelector('input[aria-label="Spike: shortest gap to the drop, ms"]');
  const maxField = () => spikeRow().querySelector('input[aria-label="Spike: longest gap to the drop, ms"]');
  ok(minField()?.value === '350' && maxField()?.value === '2000'
    && minField().getAttribute('min') === '250' && maxField().getAttribute('max') === '3000',
  'the fields show the window, bounded by the registry\'s 250-3000');
  let n = H.state.writes.length;
  type(minField(), '6');
  await H.settle();
  ok(H.state.writes.length === n && !spikeRow().querySelector('[data-testid="pre-drop-note-spike"]'),
    'a half-typed number is not judged while typing');
  type(minField(), '600');
  blur(minField());
  await H.settle();
  ok(H.state.writes.length === n + 1 && JSON.stringify(H.state.writes.at(-1).pre_drop_spike)
    === '{"enabled":true,"min_ms":600,"max_ms":2000}', 'a min inside the bounds commits on blur');
  n = H.state.writes.length;
  type(minField(), '2400');
  blur(minField());
  await H.settle();
  const note = spikeRow().querySelector('[data-testid="pre-drop-note-spike"]');
  ok(H.state.writes.length === n, 'a min at or past the max is NOT written');
  ok(note && /shortest gap must stay below the longest \(2000 ms\), so 2400 ms was not applied/.test(note.textContent),
    `the row says why — ${note?.textContent}`);
  ok(minField().value === '600', 'and the field goes back to the value in force');
  type(maxField(), '1500');
  maxField().dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  await H.settle();
  ok(H.state.writes.length === n + 1 && H.state.writes.at(-1).pre_drop_spike.max_ms === 1500
    && !spikeRow().querySelector('[data-testid="pre-drop-note-spike"]'),
  'Enter commits a max too, and the note clears');
  n = H.state.writes.length;
  const introMax = c.querySelector('[data-testid="pre-drop-row-intro"] input[aria-label="Vocal intro: longest gap to the drop, ms"]');
  type(introMax, '5000');
  blur(introMax);
  await H.settle();
  ok(H.state.writes.length === n && /vocal intro window runs 350-4500 ms/.test(
    c.querySelector('[data-testid="pre-drop-note-intro"]')?.textContent ?? ''),
  'a vocal intro max past its 4500 bound is refused, saying so');

  // the looks
  const fw = c.querySelector('[data-testid="pre-drop-looks-e1"]');
  const selects = [...fw.querySelectorAll('select')];
  ok(selects.length === 2, 'an entry whose effect declares looks: one select per kind');
  ok([...selects[0].options].map((o) => o.textContent).join(' | ') === 'Recommended (Burst) | Burst'
    && [...selects[1].options].map((o) => o.textContent).join(' | ')
      === 'Recommended (Slow bloom) | Burst | Slow bloom | Same as spike',
  `their options — ${[...selects[1].options].map((o) => o.textContent).join(' | ')}`);
  n = H.state.writes.length;
  setValue(selects[1], 'same');
  selects[1].dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  await H.settle();
  const w = H.state.writes.at(-1);
  ok(H.state.writes.length === n + 1 && JSON.stringify(w.devices[0].pre_drop_looks) === '{"spike":"auto","intro":"same"}'
    && w.devices[1].pre_drop_looks === undefined,
  `a look select writes that entry's pre_drop_looks only — ${JSON.stringify(w.devices.map((d) => d.pre_drop_looks))}`);
  const melt = c.querySelector('[data-testid="pre-drop-looks-e2"]');
  ok(!melt.querySelector('select') && melt.querySelector('.pre-drop-no-looks')?.textContent
    === 'melt has no pre-drop look yet — its lull plays as before',
  'an effect with no looks shows the muted line instead of selects');
  await H.unmountAll();
}

/* ── §3 the real drop-sequence preview ── */
console.log('§3 SequencePreviewOverlay.tsx — the kind switch, the gap, the mark');
{
  const SCENE = {
    id: 's1', name: 'Test', labels: [], flare_kinds: [], responses: {}, update_kind: null,
    color_journey: { mode: 'inherit', pace_factor: 1, journey: null },
    choreography: { enabled: false, transition_ms: 800, transition_mode: 'Add', anchor_frac: 0.45 },
    entry_ramp_ms: 0, trigger_offset_ms: 0, accept_all_sets: true, accepted_set_ids: [],
    display_availability: 'default', preferred_color_set_mode: 'default', disabled: false,
    dwell_curve: null, drop_shock_enabled: true, drop_timing_offset_ms: null,
    // a DRAFT window narrower than the defaults: 800 clamps to 1000; 2000 to 1800
    pre_drop_spike: { enabled: true, min_ms: 1000, max_ms: 1500 },
    pre_drop_intro: { enabled: false, min_ms: 350, max_ms: 1800 },
    devices: [entry('e1', 'Matrix', 'fireworks', { spike: 'burst', intro: 'same' }), entry('e2', 'Strips', 'melt')],
  };
  const c = await H.mountOverlay(SCENE);
  await H.settle(300);
  const first = opens.at(-1);
  ok(first && first.pre_drop_kind === null && typeof first.pre_drop_gap_ms === 'number',
    'it opens with no pre-drop (kind null)');
  ok(JSON.stringify(first.pre_drop_spike) === JSON.stringify(SCENE.pre_drop_spike)
    && JSON.stringify(first.pre_drop_intro) === JSON.stringify(SCENE.pre_drop_intro)
    && JSON.stringify(first.pre_drop_looks) === '{"e1":{"spike":"burst","intro":"same"},"e2":{"spike":"auto","intro":"auto"}}',
  `every open carries the draft's windows and looks — ${JSON.stringify(first.pre_drop_looks)}`);
  ok(!c.querySelector('[data-testid="pre-drop-gap"]') && !c.querySelector('[data-testid="pre-drop-line"]'),
    'no gap slider and no pre-drop line while it is off');
  const kindBtn = (k) => c.querySelector(`button[data-pre-drop-kind="${k}"]`);
  ok(kindBtn('off')?.getAttribute('aria-pressed') === 'true' && kindBtn('spike') && kindBtn('intro')
    && kindBtn('intro').textContent.includes('Vocal intro'), 'the switch: Off (pressed), Spike, Vocal intro');
  click(kindBtn('spike'));
  await H.settle(300);
  const sp = opens.at(-1);
  ok(sp.pre_drop_kind === 'spike' && sp.pre_drop_gap_ms === 1000,
    `Spike sends the kind and a gap clamped into the draft window (800 → 1000) — ${sp.pre_drop_kind} ${sp.pre_drop_gap_ms}`);
  const gap = c.querySelector('[data-testid="pre-drop-gap"]');
  ok(gap && gap.getAttribute('min') === '1000' && gap.getAttribute('max') === '1500' && gap.value === '1000',
    'the gap slider is the draft\'s spike window');
  const orange = [...c.querySelectorAll('svg line')].filter((l) => l.getAttribute('stroke') === '#fb923c');
  const label = [...c.querySelectorAll('svg text')].find((t) => t.textContent === 'spike');
  ok(orange.length === 1 && Math.abs(Number(orange[0].getAttribute('x1')) - (16 + (8 / 10) * (680 - 32))) < 0.01
    && !orange[0].getAttribute('stroke-dasharray') && label?.getAttribute('fill') === '#fb923c',
  'the ruler draws the server\'s mark_s (8.0 s) in the pre-drop orange, solid when it plays');
  ok(c.querySelector('[data-testid="pre-drop-line"]')?.textContent.includes('SERVER: a spike 1000 ms out plays here.'),
    'and the panel says the server\'s sentence');
  type(gap, '1230');
  await H.settle(300);
  ok(opens.at(-1).pre_drop_gap_ms === 1230 && opens.at(-1).pre_drop_kind === 'spike', 'moving the slider sends the new gap');
  click(kindBtn('intro'));
  await H.settle(300);
  const io = opens.at(-1);
  ok(io.pre_drop_kind === 'intro' && io.pre_drop_gap_ms === 1800,
    `Vocal intro sends its own gap, clamped into its window (2000 → 1800) — ${io.pre_drop_gap_ms}`);
  const dashed = [...c.querySelectorAll('svg line')].filter((l) => l.getAttribute('stroke') === '#fb923c');
  ok(dashed.length === 1 && dashed[0].getAttribute('stroke-dasharray') === '3,2'
    && [...c.querySelectorAll('svg text')].some((t) => t.textContent === 'vocal intro'),
  'a pre-drop this scene does not play (its kind is off) is drawn dashed');
  ok(/^Pre-drop: A vocal intro 1800 ms before the drop does not play on this scene \(kind_off\)/.test(
    c.querySelector('[data-testid="pre-drop-line"]')?.textContent ?? ''),
  `with no sentence from the server the panel says it plainly — ${c.querySelector('[data-testid="pre-drop-line"]')?.textContent}`);
  click(kindBtn('spike'));
  await H.settle(300);
  ok(opens.at(-1).pre_drop_gap_ms === 1230, 'each kind keeps its own gap');
  click(kindBtn('off'));
  await H.settle(300);
  ok(opens.at(-1).pre_drop_kind === null && !c.querySelector('[data-testid="pre-drop-line"]')
    && ![...c.querySelectorAll('svg line')].some((l) => l.getAttribute('stroke') === '#fb923c'),
  'Off: kind null again, and no orange line');
  await H.unmountAll();

  console.log('§3b the live loop: each fire carries the same pre-drop as the open');
  shortLoop = true;
  globalThis.requestAnimationFrame = (fn) => setTimeout(() => fn(performance.now()), 16);
  globalThis.cancelAnimationFrame = (id) => clearTimeout(id);
  dom.window.requestAnimationFrame = globalThis.requestAnimationFrame;
  dom.window.cancelAnimationFrame = globalThis.cancelAnimationFrame;
  // act() flushes React's queued work only when its scope ends, so the loop
  // is waited on in short scopes: each one lets the next frame be scheduled
  const run = async (ms) => { for (let t = 0; t < ms; t += 50) await H.settle(50); };
  const nFires = fires.length;
  const c2 = await H.mountOverlay(SCENE);
  await run(800);
  const f0 = fires.length > nFires ? fires.at(-1) : null;
  ok(f0 && f0.step === 'lull' && f0.pre_drop_kind === null
    && JSON.stringify(f0.pre_drop_spike) === JSON.stringify(SCENE.pre_drop_spike)
    && JSON.stringify(f0.pre_drop_looks) === JSON.stringify(first.pre_drop_looks),
  `a fire with the switch off: kind null, the draft's windows and looks — ${JSON.stringify(f0 && { kind: f0.pre_drop_kind, looks: f0.pre_drop_looks })}`);
  click(c2.querySelector('button[data-pre-drop-kind="spike"]'));
  await run(800);
  const f1 = fires.at(-1);
  ok(f1 && f1.pre_drop_kind === 'spike' && f1.pre_drop_gap_ms === 1000,
    `after Spike, the next fires carry the kind and its clamped gap — ${f1?.pre_drop_kind} ${f1?.pre_drop_gap_ms}`);
  await H.unmountAll();
  globalThis.requestAnimationFrame = () => 0;
  globalThis.cancelAnimationFrame = () => {};
}

dom.window.close();
finish();
