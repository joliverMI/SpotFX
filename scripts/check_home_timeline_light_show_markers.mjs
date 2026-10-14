// Executable spec: Home's audio-shape canvas markers for "kind": "high"/
// "low" ARE the Light Show's own High/Low Trigger cues — not a separate
// concept this build invented (firstmate's gap-check against the
// Admiral's words, "scenes, flares, drops, and light show triggers").
//
//   ONE   — BACKEND TRUTH: spectra/api/upcoming.py's `/api/upcoming`
//           handler (the one source HomeTimeline/SongStrip read) sources
//           `kind: "high"/"low"` straight from `plan["show_cues"]`
//           (spectra/services/show_cues.py, the Light Show's own store),
//           stamped `source: "show_cue"` — read directly off the real
//           source file, not assumed from a comment.
//   TWO   — THE SAME STORE FEEDS THE TIMELINE PAGE'S OWN LIGHT SHOW
//           MARKERS: canvas/lightShowLayer.ts draws from `show_cues` too
//           (its own module docstring says so), so Home's high/low flags
//           and the Timeline's flags are provably the same feature, not
//           two different things that happen to share a name.
//   THREE — FRONTEND: HomeTimeline.tsx's `isLightShow` predicate matches
//           EXACTLY `high`/`low` — the "Light Show" icon toggle gates
//           precisely the kinds BACKEND TRUTH identified above, nothing
//           more and nothing less.
//   FOUR  — drawShapeMarkers (the new audio-shape canvas overlay) draws
//           high/low as a flag and draws NOTHING for `kind: "colour"` —
//           proving the explicit-kind-check fix (a catch-all `else`
//           would have wrongly drawn a colour-set trigger as a Light Show
//           flag).
//   FIVE  — BEHAVIOURAL: mounting the REAL HomeTimeline.tsx and toggling
//           the "Light Show" icon off removes the high/low flags from
//           BOTH the full-song strip's SVG and the shape canvas's own
//           overlay, while scene/flare/drop markers are untouched.
//
// Run: node scripts/check_home_timeline_light_show_markers.mjs
//   (needs the dev-only jsdom: cd spectra/web && npm install --no-save jsdom)
import { readFileSync, mkdtempSync, writeFileSync } from 'node:fs';
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

console.log('ONE — spectra/api/upcoming.py sources high/low from the Light Show\'s own show_cues store');
{
  const src = readFileSync(join(repo, 'spectra/api/upcoming.py'), 'utf8');
  ok(/The Light Show's High\/Low cues \(`?show_cues`?\)/.test(src),
    "the module docstring names show_cues as the source of the high/low cues");
  ok(/cues = plan\.get\("show_cues"\)/.test(src),
    'the handler reads `cues` straight off `plan.get("show_cues")`');
  ok(/for level in \("high", "low"\):/.test(src),
    'the loop that builds the high/low events is literally named "high"/"low"');
  ok(/"kind": level,[\s\S]{0,100}"source": "show_cue"/.test(src),
    'each emitted event is stamped kind=level (high/low) AND source="show_cue" — not a second, invented kind');
}

console.log('TWO — the Timeline page\'s own Light Show flag layer reads from the SAME store');
{
  const src = readFileSync(join(repo, 'spectra/web/src/timeline/canvas/lightShowLayer.ts'), 'utf8');
  ok(/High\/Low Trigger markers/.test(src) && /show_cues/.test(join(repo, 'spectra/web/src/timeline/lightShowMarkers.ts') && readFileSync(join(repo, 'spectra/web/src/timeline/lightShowMarkers.ts'), 'utf8')),
    'lightShowLayer.ts (Timeline\'s own audio-shape canvas) + lightShowMarkers.ts are built on the same show_cues-sourced High/Low Trigger concept Home now draws');
}

const tmp = mkdtempSync(join(tmpdir(), 'home-light-show-'));
const songStripFix = {
  name: 'songstrip-case-fix',
  setup(b) {
    b.onResolve({ filter: /components\/songStrip$/ }, () => (
      { path: join(webDir, 'src/components/songStrip.ts') }
    ));
  },
};

console.log('THREE/FOUR — frontend: the Light Show toggle and drawShapeMarkers both check high/low explicitly');
{
  const js = join(tmp, 'songStrip.mjs');
  await esbuild.build({
    entryPoints: [join(webDir, 'src/components/songStrip.ts')], bundle: true, format: 'esm',
    platform: 'node', logLevel: 'silent', outfile: js,
  });
  const { drawShapeMarkers, KIND_COLOR } = await import(js);

  const homeSrc = readFileSync(join(webDir, 'src/home/HomeTimeline.tsx'), 'utf8');
  const m = homeSrc.match(/const isLightShow = \(k: UpcomingEvent\['kind'\]\) => (.+);/);
  ok(!!m, 'HomeTimeline.tsx defines isLightShow as a plain predicate (so its literal text can be checked)');
  ok(m[1].replace(/\s/g, '') === "k==='high'||k==='low'",
    `isLightShow checks exactly 'high'/'low' — the same two kinds ONE/TWO identified as the Light Show's `
    + `own cues, nothing more and nothing less (got: ${m[1]})`);

  const makeCtx = () => {
    const calls = [];
    return {
      calls,
      set fillStyle(v) { calls.push(['fillStyle', v]); },
      set strokeStyle(v) { calls.push(['strokeStyle', v]); },
      set globalAlpha(v) { calls.push(['globalAlpha', v]); },
      set lineWidth(v) {},
      fillRect(...a) { calls.push(['fillRect', ...a]); },
      beginPath() { calls.push(['beginPath']); },
      arc(...a) { calls.push(['arc', ...a]); },
      fill() { calls.push(['fill']); },
      moveTo(...a) { calls.push(['moveTo', ...a]); },
      lineTo(...a) { calls.push(['lineTo', ...a]); },
      stroke() { calls.push(['stroke']); },
    };
  };
  const xAt = (ms) => ms / 100;

  {
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [{ ms: 5000, kind: 'high', rank: null, rank_of: null, source: 'show_cue' }], xAt, 1000);
    ok(ctx.calls.some((c) => c[0] === 'strokeStyle' && c[1] === KIND_COLOR.high),
      'a Light Show HIGH trigger draws a flag in KIND_COLOR.high');
  }
  {
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [{ ms: 5000, kind: 'low', rank: null, rank_of: null, source: 'show_cue' }], xAt, 1000);
    ok(ctx.calls.some((c) => c[0] === 'strokeStyle' && c[1] === KIND_COLOR.low),
      'a Light Show LOW trigger draws a flag in KIND_COLOR.low');
  }
  {
    // The regression this explicit check guards against: a colour-set
    // trigger (reachable through /api/upcoming's "his own triggers fire
    // instead" branch) must NOT be drawn as a Light Show flag.
    const ctx = makeCtx();
    drawShapeMarkers(ctx, [{ ms: 5000, kind: 'colour', rank: null, rank_of: null, source: 'authored' }], xAt, 1000);
    ok(ctx.calls.length === 1 && ctx.calls[0][0] === 'globalAlpha' && ctx.calls[0][1] === 1,
      `a "colour" (select_color_set) trigger draws NOTHING — never mistaken for a Light Show flag `
      + `(calls: ${JSON.stringify(ctx.calls)})`);
  }
}

console.log('FIVE — behavioural: mounting the real HomeTimeline and toggling "Light Show" off');
let jsdomMod;
try {
  jsdomMod = require('jsdom');
} catch {
  console.log('jsdom not installed in spectra/web/node_modules (dev-only, '
    + 'not a declared dependency) — skipping FIVE. Install with '
    + '`cd spectra/web && npm install --no-save jsdom`.');
  console.log(failures ? `\n${failures} FAILED` : '\nall passed (jsdom-based section skipped)');
  process.exit(failures ? 1 : 0);
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
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let rafQueue = [];
const fakeRaf = (cb) => { rafQueue.push(cb); return rafQueue.length; };
globalThis.requestAnimationFrame = fakeRaf;
globalThis.cancelAnimationFrame = () => {};
dom.window.requestAnimationFrame = fakeRaf;
dom.window.cancelAnimationFrame = globalThis.cancelAnimationFrame;
const tickRaf = (n = 1) => {
  for (let i = 0; i < n; i += 1) {
    const cbs = rafQueue;
    rafQueue = [];
    for (const cb of cbs) cb(performance.now());
  }
};

dom.window.HTMLElement.prototype.getBoundingClientRect = function () {
  return { left: 0, top: 0, right: 1000, bottom: 160, width: 1000, height: 160, x: 0, y: 0, toJSON() {} };
};

const fakeCtxProto = {
  get fillStyle() { return this._f; }, set fillStyle(v) { this._f = v; },
  get strokeStyle() { return this._s; }, set strokeStyle(v) { this._s = v; },
  set globalAlpha(v) {}, set lineWidth(v) {}, setTransform() {}, clearRect() {},
  beginPath() {}, closePath() {}, fillRect() {}, arc() {}, fill() {}, moveTo() {}, lineTo() {}, stroke() {},
};
const canvasCalls = [];
const recordingCtx = Object.create(fakeCtxProto);
for (const m of ['fillRect', 'arc', 'fill', 'moveTo', 'lineTo', 'stroke', 'beginPath']) {
  recordingCtx[m] = (...a) => canvasCalls.push([m, ...a]);
}
const canvasProto = dom.window.HTMLCanvasElement.prototype;
canvasProto.getContext = function (kind) {
  if (kind !== '2d') return null;
  return recordingCtx;
};
Object.defineProperty(canvasProto, 'clientWidth', { configurable: true, get() { return 800; } });
Object.defineProperty(canvasProto, 'clientHeight', { configurable: true, get() { return 160; } });
dom.window.devicePixelRatio = 1;

const NodeResponse = globalThis.Response;
const SHAPE_META = {
  spotify_uri: 'spotify:track:perf', title: 'x', artist: 'y', duration_ms: 200000,
  sample_interval_ms: 200, music_marks: [], capture_complete: true,
  timestamp_offset_ms: 0, perception_trim_ms: 0, offset_verification: 'auto_verified',
};
const SHAPE_DATA = { timestamps_ms: [], rms_total: [], rms_low: [], rms_mid: [], rms_high: [], avg_rms_1s: null };
const fakeFetch = async (url) => {
  const u = String(url);
  const json = (body) => new NodeResponse(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
  if (u.includes('/audio-shape/meta')) return json(SHAPE_META);
  if (u.includes('/audio-shape/data')) return json(SHAPE_DATA);
  throw new Error(`unexpected fetch ${u}`);
};
globalThis.fetch = fakeFetch;
dom.window.fetch = fakeFetch;

const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import HomeTimeline from ${JSON.stringify(join(webDir, 'src/home/HomeTimeline.tsx'))};

const EVENTS = [
  { ms: 20000, kind: 'scene', rank: 1, rank_of: 3, source: 'planned' },
  { ms: 55000, kind: 'flare', rank: null, rank_of: null, source: 'analysed' },
  { ms: 100000, kind: 'drop', rank: null, rank_of: null, source: 'drop_sequence', num: 1 },
  { ms: 15000, kind: 'high', rank: null, rank_of: null, source: 'show_cue' },
  { ms: 150000, kind: 'low', rank: null, rank_of: null, source: 'show_cue' },
];

const container = document.createElement('div');
document.body.appendChild(container);
const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

export async function mount() {
  const root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(MemoryRouter, null,
        React.createElement(HomeTimeline, {
          uri: 'spotify:track:perf', title: 'x', artist: 'y',
          durationMs: 200000, events: EVENTS, showAudioShape: true,
        }))));
  });
  for (let i = 0; i < 40 && !container.querySelector('.home-timeline-shape-canvas'); i++) {
    await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
  }
  return container;
}
export async function flush() {
  await act(async () => { await new Promise((r) => setTimeout(r, 5)); });
}
export async function click(el) {
  await act(async () => {
    el.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
  });
}
`;
const entryFile = join(tmp, 'entry.mjs');
writeFileSync(entryFile, entrySrc);
const outFile = join(tmp, 'out.cjs');
const build = await esbuild.build({
  entryPoints: [entryFile], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
  outfile: outFile, nodePaths: [join(webDir, 'node_modules')], logLevel: 'silent',
  loader: { '.css': 'empty' }, plugins: [songStripFix],
});
ok(build.errors.length === 0, 'HomeTimeline.tsx bundles cleanly');
const { mount, flush, click } = require(outFile);
const container = await mount();
await flush();
tickRaf(2);

const strip = () => container.querySelector('.song-strip-svg g');
const lightShowToggle = () => [...container.querySelectorAll('.home-timeline-toggles button')]
  .find((b) => b.getAttribute('title') === 'Light Show');

const svgKinds = () => [...strip().children].map((el) => (
  el.tagName === 'rect' && el.getAttribute('y') === '15' ? 'scene'
    : el.tagName === 'circle' ? 'flare'
    : el.tagName === 'rect' ? 'drop-like'
    : el.tagName === 'line' ? 'flag' : '?'
));

const before = svgKinds();
ok(before.filter((k) => k === 'flag').length === 2, `both high/low flags are drawn on the strip before toggling (${before})`);
ok(lightShowToggle()?.getAttribute('aria-checked') === 'true', 'the "Light Show" toggle starts ON');

await click(lightShowToggle());
tickRaf(2);
await flush();

const after = svgKinds();
ok(after.filter((k) => k === 'flag').length === 0, `toggling "Light Show" off removes both flags from the strip (${after})`);
ok(after.filter((k) => k === 'scene').length === 1 && after.filter((k) => k === 'flare').length === 1
   && after.filter((k) => k === 'drop-like').length === 1,
  'scene/flare/drop markers are untouched by the Light Show toggle');

canvasCalls.length = 0;
tickRaf(1);
const flagOnCanvas = canvasCalls.some((c, i) => c[0] === 'moveTo' && c[2] === 0
  && canvasCalls[i + 1] && canvasCalls[i + 1][0] === 'lineTo' && canvasCalls[i + 1][1] === c[1] && canvasCalls[i + 1][2] === 8);
ok(!flagOnCanvas, 'with "Light Show" toggled off, the shape canvas\'s own overlay draws no flag either');

console.log(failures ? `\n${failures} FAILED` : '\nall passed — high/low ARE the Light Show\'s own High/Low Trigger cues, drawn consistently everywhere, and "colour" is never mistaken for one');
process.exit(failures ? 1 : 0);
