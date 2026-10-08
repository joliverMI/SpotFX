// Executable spec for queries.ts's useRoomControlsForcePush() — his
// 2026-10-08 report: "when i had the light show turn off forced color, it
// didn't seem to update the icon/button on the top bar." (RoomControlsBar
// shows a lock icon for force_scene_enabled/force_color_enabled, PR #370.)
//
// Root cause: useRoomControls() has no poll of its own (only a 10s
// staleTime) — it only refetches on mount, on window refocus, or when
// THIS browser's own save invalidates it. A Light Show step turns Force
// Colour off by calling spectra/services/room_controls.apply_patch
// directly (never this browser's PUT), so the change never reached the
// cache until something else happened to refetch it. apply_patch now
// broadcasts a `room_controls_force` message on the SPECTRA websocket
// whenever any of the four force fields change (see its own docstring);
// useRoomControlsForcePush() is the client half, folding that push
// straight into the SAME ['spectra-room-controls'] cache entry
// useRoomControls() reads — the useAmbientStatusPush() precedent.
//
// This renders the REAL queries.ts module (via esbuild) under a REAL
// @tanstack/react-query QueryClient and a REAL React 18 tree (jsdom +
// react-dom/client, same harness shape as check_topbar_scene_colour_
// names.mjs), with only `./api/spectraWs` (the WebSocket singleton)
// redirected to a fixture that lets the test drive messages directly
// instead of opening a real socket. `./api/client` (apiGet/apiPut) is
// left as the REAL module — nothing in this test ever calls it, because
// the query cache is pre-seeded via `queryClient.setQueryData` before
// mount, which the hook's own 10s staleTime then treats as fresh (no
// mount-time refetch to stub).
//
// Two cases:
//   1. A pushed `room_controls_force` message with Force Colour OFF
//      (and nothing else in the payload declaring it was ever on) lands
//      in the cache the probe reads — the literal "Light Show turned it
//      off" case.
//   2. A pushed message turning Force Scene ON lands too, and an
//      unrelated message type is ignored.
//
// Run: node scripts/check_room_controls_force_push.mjs
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

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

// ── a fake `./api/spectraWs` — the one real seam this test controls, so a
// push can be driven directly instead of needing a real WebSocket/jsdom
// socket shim. Mirrors the real module's `onSpectraMessage` signature
// exactly (subscribe, return an unsubscribe) and adds `__emit` for the
// driver to call. ──
const fakeWsSrc = `
const listeners = new Set();
export function onSpectraMessage(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function __emit(msg) { listeners.forEach((fn) => fn(msg)); }
`;
const tmpDir = mkdtempSync(join(tmpdir(), 'room-controls-push-harness-'));
const fakeWsPath = join(tmpDir, 'fakeSpectraWs.mjs');
writeFileSync(fakeWsPath, fakeWsSrc);

const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useRoomControls, useRoomControlsForcePush } from ${JSON.stringify(join(repo, 'spectra/web/src/queries.ts'))};
import { __emit } from ${JSON.stringify(fakeWsPath)};

const container = document.createElement('div');
document.body.appendChild(container);
let root = null;
let queryClient = null;

function Probe() {
  const { data } = useRoomControls();
  useRoomControlsForcePush();
  if (!data) return React.createElement('div', { id: 'probe', 'data-loaded': 'false' });
  return React.createElement('div', {
    id: 'probe',
    'data-loaded': 'true',
    'data-force-scene-enabled': String(data.force_scene_enabled),
    'data-force-scene-scene-id': data.force_scene_scene_id ?? '',
    'data-force-color-enabled': String(data.force_color_enabled),
    'data-force-color-target-id': data.force_color_target_id ?? '',
    'data-brightness-multiplier': String(data.brightness_multiplier),
  });
}

export async function mount(initial) {
  queryClient = new QueryClient();
  queryClient.setQueryData(['spectra-room-controls'], initial);
  if (root) await act(async () => { root.unmount(); });
  root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(QueryClientProvider, { client: queryClient },
      React.createElement(Probe)));
  });
  return container.innerHTML;
}

export async function push(msg) {
  // react-query's notifyManager schedules every cache-write notification
  // on a real setTimeout(fn, 0) macrotask (query-core/src/notifyManager.ts
  // systemSetTimeoutZero), never a microtask act() alone would flush — so
  // the emit itself and the wait for that scheduled callback both have to
  // sit inside one act() for the probe's re-render to have committed by
  // the time this returns.
  await act(async () => {
    __emit(msg);
    await new Promise((resolve) => { setTimeout(resolve, 0); });
  });
  return container.innerHTML;
}

export function fetchCount() {
  // Nothing in this harness ever calls apiGet — a non-zero count here
  // would mean the probe refetched instead of adopting the push, which
  // is exactly the "within a second, no round trip" property this fix
  // relies on. queryClient tracks this itself via the query's state.
  return queryClient.getQueryState(['spectra-room-controls'])?.fetchStatus ?? 'idle';
}
`;
const entryFile = join(tmpDir, 'entry.mjs');
writeFileSync(entryFile, entrySrc);
const outFile = join(tmpDir, 'out.cjs');

const build = await esbuild.build({
  entryPoints: [entryFile],
  bundle: true,
  format: 'cjs',
  platform: 'node',
  jsx: 'automatic',
  outfile: outFile,
  nodePaths: [join(repo, 'spectra/web/node_modules')],
  plugins: [{
    name: 'stub-spectra-ws',
    setup(buildApi) {
      const wsFile = join(repo, 'spectra/web/src/api/spectraWs.ts');
      buildApi.onResolve({ filter: /\/spectraWs(\.ts)?$/ }, (args) => {
        const resolved = join(dirname(args.importer), args.path);
        if (resolved === wsFile || `${resolved}.ts` === wsFile) {
          return { path: fakeWsPath };
        }
        return null;
      });
    },
  }],
  logLevel: 'silent',
});
ok(build.errors.length === 0, build.errors.length === 0
  ? 'queries.ts (real useRoomControls/useRoomControlsForcePush) bundles cleanly'
  : `bundle failed: ${build.errors.map((e) => e.text).join('; ')}`);
const { mount, push, fetchCount } = require(outFile);

const attr = (html, name) => {
  const m = html.match(new RegExp(`${name}="([^"]*)"`));
  return m ? m[1] : null;
};

const BASE_ROOM = {
  force_scene_enabled: false, force_scene_scene_id: null,
  force_color_enabled: false, force_color_target_id: null,
  brightness_multiplier: 1.0,
};

console.log('§1 a Light Show step turns Force Colour off — pushed, no refetch');
{
  // The pin was on before the push — mirroring his real report, where the
  // room-controls cache he's already looking at shows it forced.
  const before = await mount({ ...BASE_ROOM, force_color_enabled: true, force_color_target_id: 'set-1' });
  ok(attr(before, 'data-force-color-enabled') === 'true', 'before the push: Force Colour reads on');

  const after = await push({
    type: 'room_controls_force',
    force_scene_enabled: false, force_scene_scene_id: null,
    force_color_enabled: false, force_color_target_id: 'set-1',
  });
  ok(attr(after, 'data-force-color-enabled') === 'false',
    "after the push: Force Colour reads off — the top bar's lock icon condition flips with no refetch");
  ok(attr(after, 'data-force-scene-enabled') === 'false', 'Force Scene is untouched by a Force Colour push');
  ok(attr(after, 'data-brightness-multiplier') === '1', 'a field the push never names is left exactly as it was');
  ok(fetchCount() === 'idle', 'the cache was never refetched — the push wrote it directly');
}

console.log('§2 Force Scene turns on, via the same push; an unrelated message type is ignored');
{
  await mount({ ...BASE_ROOM });
  await push({ type: 'drift_leg', irrelevant: true });
  const stillOff = await push({ type: 'sequencer_pick', irrelevant: true });
  ok(attr(stillOff, 'data-force-scene-enabled') === 'false',
    'a differently-typed SPECTRA broadcast does not touch the force fields');

  const after = await push({
    type: 'room_controls_force',
    force_scene_enabled: true, force_scene_scene_id: 'scene-9',
    force_color_enabled: false, force_color_target_id: null,
  });
  ok(attr(after, 'data-force-scene-enabled') === 'true', 'Force Scene reads on after the push');
  ok(attr(after, 'data-force-scene-scene-id') === 'scene-9', 'the pinned scene id arrives with it');
}

console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
