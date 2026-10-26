// Executable spec for THE TIMELINE'S "THIS SONG CHANGED ELSEWHERE" HOLD
// (predrop plan step 1, report section 3.6: "A stale Timeline must not
// save them back ... a Timeline holding the song with unsaved edits cannot
// save a removed trigger back without saying the song changed").
//
// Home's Drops panel deletes or switches off his charge/lull/drop triggers
// in his song profile (routers/profiles.py's narrow edit), which broadcasts
// `profile_triggers_changed` on the root websocket. Every Timeline save
// posts the WHOLE profile, so a tab still holding the old copy would put a
// removed trigger back. The REAL Builder store (spectra/web/src/timeline/
// store.ts) and the REAL websocket hook (hooks/useBuilderWs.ts) are driven
// here; only `fetch` and the root websocket (api/ws.ts) are faked.
//
//   ONE   an unsaved edit + the broadcast: the save is HELD — nothing is
//         posted — until he chooses; "save mine anyway" posts once
//   TWO   "reload" drops his held edit and the next load starts a fresh
//         undo history (an old snapshot would resurrect the trigger too)
//   THREE a clean tab + the broadcast: the song is refetched (no hold),
//         and its reload starts a fresh undo history
//   FOUR  a broadcast for another song changes nothing
//
// Run: node scripts/check_timeline_changed_elsewhere.mjs
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
globalThis.localStorage = dom.window.localStorage;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

const posts = [];
globalThis.fetch = async (url, opts = {}) => {
  if ((opts.method || 'GET').toUpperCase() === 'POST') posts.push({ url, body: JSON.parse(opts.body) });
  return { ok: true, status: 200, json: async () => ({ status: 'saved', spectra_sync: { status: 'ok' } }) };
};

const fakeWsSrc = `
const listeners = new Map();
export function onMessage(type, fn) {
  if (!listeners.has(type)) listeners.set(type, new Set());
  listeners.get(type).add(fn);
  return () => listeners.get(type).delete(fn);
}
export function onConnectionChange() { return () => {}; }
export function __emit(msg) { (listeners.get(msg.type) || new Set()).forEach((fn) => fn(msg)); }
`;
const tmpDir = mkdtempSync(join(tmpdir(), 'timeline-changed-elsewhere-'));
const fakeWsPath = join(tmpDir, 'fakeWs.mjs');
writeFileSync(fakeWsPath, fakeWsSrc);

const src = (p) => JSON.stringify(join(repo, 'spectra/web/src', p));
const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useBuilderStore } from ${src('timeline/store.ts')};
import { useBuilderWs } from ${src('timeline/hooks/useBuilderWs.ts')};
import { __emit } from ${JSON.stringify(fakeWsPath)};

export const store = useBuilderStore;
export const invalidated = [];
const qc = new QueryClient();
const realInvalidate = qc.invalidateQueries.bind(qc);
qc.invalidateQueries = (arg) => { invalidated.push(arg?.queryKey); return realInvalidate(arg); };

function Hook({ uri }) { useBuilderWs(uri); return null; }

export async function mount(uri) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(Hook, { uri })));
  });
}

export async function emit(msg) {
  await act(async () => { __emit(msg); });
}

export async function tick(ms = 10) {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)); });
}
`;
const entryFile = join(tmpDir, 'entry.mjs');
writeFileSync(entryFile, entrySrc);
const outFile = join(tmpDir, 'out.cjs');
const build = await esbuild.build({
  entryPoints: [entryFile], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
  outfile: outFile, nodePaths: [join(repo, 'spectra/web/node_modules')],
  plugins: [{
    name: 'stub-root-ws',
    setup(b) {
      const wsFile = join(repo, 'spectra/web/src/api/ws.ts');
      b.onResolve({ filter: /\/api\/ws(\.ts)?$/ }, (args) => {
        const resolved = join(dirname(args.importer), args.path);
        if (resolved === wsFile || `${resolved}.ts` === wsFile) return { path: fakeWsPath };
        return null;
      });
    },
  }],
  logLevel: 'silent',
});
ok(build.errors.length === 0, build.errors.length === 0
  ? 'the real Builder store and websocket hook bundle cleanly'
  : `bundle failed: ${build.errors.map((e) => e.text).join('; ')}`);
const H = require(outFile);
const S = H.store;

const URI = 'spotify:track:stale1';
const profile = (triggers) => ({
  spotify_uri: URI, title: 'Stale', artist: 'Tests', artist_genre: [], duration_ms: 200000,
  labels: [], verified: false, notes: '', triggers, setlist_triggers: {},
});
const T = (id, ms, ev) => ({ id, timestamp_ms: ms, event_id: ev, labels: [], enabled: true, intensity: 0.5 });
const WITH = [T('t-charge', 10000, 'fixed-charge'), T('t-drop', 20000, 'fixed-drop'), T('t-flare', 30000, 'fixed-shape-flare')];
const REMOVED = WITH.filter((t) => t.id !== 't-drop');

await H.mount(URI);

console.log('ONE  an unsaved edit, then the broadcast: the save is held');
{
  S.getState().loadProfile(profile(WITH));
  S.getState().mutateProfile((p) => { p.triggers[2].timestamp_ms = 31000; });
  ok(S.getState().dirty, 'the Timeline holds an unsaved edit of the OLD copy');
  await H.emit({ type: 'profile_triggers_changed', uri: URI, ids: ['t-drop'] });
  ok(S.getState().changedElsewhere === true, 'it now knows the song changed elsewhere');
  const before = posts.length;
  await S.getState().flushSave();
  await H.tick(450);                          // past the 400 ms autosave too
  ok(posts.length === before, 'nothing is posted: the removed drop is not saved back');
  ok(S.getState().dirty, 'his edit is still there, held, not lost');
  S.getState().resolveChangedElsewhere('save');
  await H.tick();
  const sent = posts.slice(before);
  ok(sent.length === 1 && sent[0].url === '/api/profiles'
    && sent[0].body.triggers.some((t) => t.id === 't-drop'),
    'only "save mine anyway" posts — once, and he was told it puts it back');
}

console.log('TWO  "reload": his held edit is dropped and history starts fresh');
{
  S.getState().loadProfile(profile(WITH));
  S.getState().mutateProfile((p) => { p.triggers[2].timestamp_ms = 32000; });
  await H.emit({ type: 'profile_triggers_changed', uri: URI, ids: ['t-drop'] });
  ok(S.getState().changedElsewhere, 'held');
  ok(S.getState().undoStack.length > 0, 'there is an old snapshot to undo to');
  S.getState().resolveChangedElsewhere('reload');
  ok(!S.getState().dirty && !S.getState().changedElsewhere, 'the held edit is dropped');
  S.getState().loadProfile(profile(REMOVED));  // the refetch landing
  ok(S.getState().undoStack.length === 0 && S.getState().redoStack.length === 0,
    'the reload starts a fresh undo history (an old snapshot would resurrect the drop)');
  ok(!S.getState().profile.triggers.some((t) => t.id === 't-drop'), 'the fresh copy is loaded');
}

console.log('THREE a clean tab: the song is refetched, history fresh');
{
  S.getState().loadProfile(profile(WITH));
  await H.tick(850);                          // past the store's 800 ms undo coalescing
  S.getState().mutateProfile((p) => { p.triggers[2].timestamp_ms = 33000; });
  await S.getState().flushSave();             // saved: clean again, history kept
  ok(!S.getState().dirty && S.getState().undoStack.length > 0, 'a clean tab with an undo history');
  const before = H.invalidated.length;
  await H.emit({ type: 'profile_triggers_changed', uri: URI, ids: ['t-drop'] });
  ok(!S.getState().changedElsewhere, 'nothing is held — there is nothing unsaved');
  ok(H.invalidated.slice(before).some((k) => JSON.stringify(k) === JSON.stringify(['profile', URI])),
    'the song is refetched');
  S.getState().loadProfile(profile(REMOVED));
  ok(S.getState().undoStack.length === 0, 'and its reload starts a fresh undo history');
}

console.log('FOUR a broadcast for another song changes nothing');
{
  S.getState().loadProfile(profile(WITH));
  S.getState().mutateProfile((p) => { p.triggers[2].timestamp_ms = 34000; });
  const before = H.invalidated.length;
  await H.emit({ type: 'profile_triggers_changed', uri: 'spotify:track:other', ids: ['x'] });
  ok(!S.getState().changedElsewhere && H.invalidated.length === before, 'not this song: untouched');
}

if (failures) {
  console.log(`\nFAIL: ${failures} check(s) failed`);
  process.exit(1);
}
console.log('\nOK: a stale Timeline never saves a removed trigger back silently.');
process.exit(0);
