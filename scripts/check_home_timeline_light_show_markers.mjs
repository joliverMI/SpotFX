// Executable spec: Home's audio-shape canvas markers for "kind": "high"/
// "low" ARE the Light Show's own High/Low Trigger cues — not a separate
// concept this build invented (firstmate's gap-check against the
// Admiral's words, "scenes, flares, drops, and light show triggers").
//
//   ONE   — BACKEND TRUTH, EXECUTED: drives the REAL
//           `spectra.api.upcoming.upcoming_for_song` (a Python subprocess,
//           `spectra/api/analysed_plan._plan_with_cues` monkeypatched to a
//           fixture plan) and asserts its ACTUAL OUTPUT emits `kind:
//           "high"/"low"` with `source: "show_cue"` straight off
//           `plan["show_cues"]` — and emits NOTHING for a cue with no
//           resolved timestamp — proving the handler's behaviour, not
//           just reading its source text. (The Timeline page's own
//           High/Low Trigger markers, which read from the SAME
//           `show_cues` store, already have their own dedicated
//           behavioural proof: scripts/check_timeline_light_show_markers.mjs.)
//   TWO   — FRONTEND: drawShapeMarkers (the new audio-shape canvas
//           overlay, the REAL songStrip.ts bundled with esbuild) draws
//           high/low as a flag and draws NOTHING for `kind: "colour"` —
//           proving the explicit-kind-check fix (a catch-all `else`
//           would have wrongly drawn a colour-set trigger as a Light Show
//           flag).
//   THREE — BEHAVIOURAL: mounting the REAL HomeTimeline.tsx and toggling
//           the "Light Show" icon off removes the high/low flags from
//           BOTH the full-song strip's SVG and the shape canvas's own
//           overlay, while scene/flare/drop markers are untouched — this
//           is also what proves `isLightShow` gates exactly `high`/`low`,
//           the two kinds ONE proved the backend actually emits.
//
// Run: node scripts/check_home_timeline_light_show_markers.mjs
//   (needs the dev-only jsdom: cd spectra/web && npm install --no-save jsdom)
//   (ONE needs a Python interpreter with spectra's own deps installed:
//   .venv/bin/python, else $PYTHON, else python3)
import { existsSync, mkdtempSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const webDir = join(repo, 'spectra/web');
const require = createRequire(join(webDir, 'package.json'));
const esbuild = require('esbuild');
const venvPy = join(repo, '.venv/bin/python');
const PYTHON = process.env.PYTHON || (existsSync(venvPy) ? venvPy : 'python3');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

console.log('ONE — the real /api/upcoming handler actually emits high/low from plan["show_cues"]');
{
  const probeScript = `
import json, os, sys

os.environ["SPECTRA_STORAGE_DIR"] = __import__("tempfile").mkdtemp(prefix="upcoming-probe-")
sys.path.insert(0, ${JSON.stringify(repo)})

import spectra.api.upcoming as upcoming_mod

URI = "spotify:track:check-home-timeline-light-show-markers"
BASE_PLAN = {
    "uri": URI, "effective_mode": "analysed", "has_authored": False,
    "applies": False, "reason": "fixture", "scene_changes": [], "flares": [],
    "scene_source": None, "rank_of": None,
    "drop_sequences": {"sequences": []},
}

def run(show_cues):
    plan = {**BASE_PLAN, "show_cues": show_cues}
    upcoming_mod._plan_with_cues = lambda uri: plan
    return upcoming_mod.upcoming_for_song(URI, limit=20)

with_cues = run({"high": {"timestamp_ms": 12345}, "low": {"timestamp_ms": 67890}})
without_cues = run({"high": None, "low": {"timestamp_ms": None}})
print(json.dumps({"with_cues": with_cues, "without_cues": without_cues}))
`;
  const raw = execFileSync(PYTHON, ['-c', probeScript], { cwd: repo, encoding: 'utf8' });
  const { with_cues: withCues, without_cues: withoutCues } = JSON.parse(raw);

  const high = withCues.events.find((e) => e.kind === 'high');
  const low = withCues.events.find((e) => e.kind === 'low');
  ok(!!high && high.ms === 12345 && high.source === 'show_cue',
    `a show_cues "high" cue is emitted as kind="high", ms=12345, source="show_cue" (got: ${JSON.stringify(high)})`);
  ok(!!low && low.ms === 67890 && low.source === 'show_cue',
    `a show_cues "low" cue is emitted as kind="low", ms=67890, source="show_cue" (got: ${JSON.stringify(low)})`);
  ok(!withCues.events.some((e) => e.kind !== 'high' && e.kind !== 'low'),
    'no other event kind is fabricated from the show_cues branch alone');

  ok(!withoutCues.events.some((e) => e.kind === 'high' || e.kind === 'low'),
    `a cue with no resolved timestamp_ms (None, or a dict carrying timestamp_ms=None) emits NOTHING `
    + `(got: ${JSON.stringify(withoutCues.events)})`);
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

console.log('TWO — frontend: drawShapeMarkers draws high/low as a flag and nothing for "colour"');
{
  const js = join(tmp, 'songStrip.mjs');
  await esbuild.build({
    entryPoints: [join(webDir, 'src/components/songStrip.ts')], bundle: true, format: 'esm',
    platform: 'node', logLevel: 'silent', outfile: js,
  });
  const { drawShapeMarkers, KIND_COLOR } = await import(js);

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

console.log('THREE — behavioural: mounting the real HomeTimeline and toggling "Light Show" off');
let jsdomMod;
try {
  jsdomMod = require('jsdom');
} catch {
  console.log('jsdom not installed in spectra/web/node_modules (dev-only, '
    + 'not a declared dependency) — skipping THREE. Install with '
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
