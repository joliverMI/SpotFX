// Executable spec for the Light Show's PLAYLISTS tab (PlaylistView.tsx) and
// the playlist Run card + banner (PlaylistRunCard.tsx) — Show Playlists,
// phase 1 (data/playlist-plan/report.md slice 1c).
//
// Mounts the REAL components under jsdom (react-dom/client), with
// window.fetch stood in by canned /spectra/api and /api answers — the
// check_show_sequence_ui.mjs precedent; no backend.
//
//   ONE   — the pure helpers (a pasted Spotify link, the wire body with
//           served-only fields stripped, a pasted entry's fresh ids, the
//           outcome lines).
//   TWO   — Build: the program, its Spotify playlist chip and the recently
//           played offers, song cards collapsed to a summary and expanded
//           to their steps with the four timing icons (the chosen one lit),
//           copy / paste a song's steps, + Song from the search, Save
//           posting what the screen shows, Follow now, the Follow switch.
//   THREE — Run card + banner: the headline, each step's state, up next
//           with what it will arm, Fire now / Skip / Stop posting their
//           routes, the banner's Stop following.
//
// Run: node scripts/check_show_playlist_ui.mjs
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
dom.window.confirm = () => true;

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

// ── fixtures ──
const CTX = 'spotify:playlist:forty';
const SETS = [
  { id: 'set-heavy', name: 'Heavy Calm', actions: [{ id: 'a1', kind: 'pause', params: {}, enabled: true }] },
  { id: 'set-show', name: 'Show Mode', actions: [{ id: 'a2', kind: 'pause', params: {}, enabled: true }] },
];
const step = (id, set_id, on, title) => ({ id, set_id, on, repeat: false, finish_on_mark: true,
  enabled: true, title, problems: [] });
const PL = {
  id: 'pl-1', name: '40! Lightshow', contexts: [CTX], context_names: { [CTX]: '40! Lightshow' },
  auto_follow: true, follow_songs_anywhere: false, unlisted_song: 'default', problems: [],
  on_start: { sequence_id: null, replace_running_sequence: false, steps: [] },
  default_song: null, on_end: { steps: [], end_show: false },
  songs: [
    { id: 'e1', uri: 'spotify:track:one', title: 'Yonaguni', artist: 'Bad Bunny', enabled: true,
      steps: [step('s1', 'set-heavy', 'low', 'Heavy Calm — Low Trigger')], summary: 'Heavy Calm — Low Trigger' },
    { id: 'e2', uri: 'spotify:track:two', title: 'Moscow Mule', artist: 'Bad Bunny', enabled: true,
      steps: [], summary: 'nothing' },
  ],
};
const RUN = {
  id: 'run-1', playlist_id: 'pl-1', name: '40! Lightshow', state: 'following', active: true,
  via: 'context', started_by: 'auto-follow', context_uri: CTX, started_ms: 1, ended_ms: null,
  end_reason: '', paused_reason: '', song_uri: 'spotify:track:one', song_title: 'Yonaguni',
  song_artist: 'Bad Bunny', entry_source: 'listed', songs_count: 3,
  song_steps: [
    { step_id: 's1', set_id: 'set-heavy', set_name: 'Heavy Calm', on: 'low', status: 'armed', arm_id: 'a', at_ms: 1, detail: '' },
    { step_id: 's2', set_id: 'set-show', set_name: 'Show Mode', on: 'song_start', status: 'fired', arm_id: null, at_ms: 1, detail: '' },
    { step_id: 's3', set_id: 'set-show', set_name: 'Show Mode', on: 'high', status: 'missed', arm_id: 'b', at_ms: 1, detail: 'its song ended before the trigger' },
  ],
  start_steps: [], songs_seen: [], log: [{ at_ms: 1, what: 'started', detail: 'by auto-follow', song: '' }],
};
const STATUS = {
  run: RUN, refusal: null, follow_enabled: true, playing_uri: 'spotify:track:one',
  playing_from: { uri: CTX, type: 'playlist', name: '40! Lightshow', program: '40! Lightshow' },
  up_next: { uri: 'spotify:track:two', title: 'Bad Bunny — Moscow Mule', entry_source: 'listed', summary: 'Show Mode — High Trigger' },
};
const SONGS = [{ uri: 'spotify:track:tit', title: 'Tití Me Preguntó', artist: 'Bad Bunny' }];
const requests = [];
const NodeResponse = globalThis.Response;
const fakeFetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const full = String(url).replace(/^https?:\/\/[^/]+/, '');
  const path = full.split('?')[0];
  const body = init.body ? JSON.parse(init.body) : null;
  requests.push({ method, path, full, body });
  let answer = {};
  if (method === 'GET' && path === '/spectra/api/light-show/playlists') answer = { playlists: [PL], follow_enabled: true };
  else if (method === 'GET' && path === '/spectra/api/light-show/sequences') answer = { sequences: [] };
  else if (method === 'GET' && path === '/spectra/api/light-show/playlist-run') answer = STATUS;
  else if (method === 'GET' && path === '/api/spotify/contexts') {
    answer = { playing: null, recent: [{ context_uri: CTX, type: 'playlist', name: '40! Lightshow' },
      { context_uri: 'spotify:playlist:tanner', type: 'playlist', name: 'Tanner 2' }] };
  } else if (method === 'GET' && path === '/spectra/api/light-show/songs') {
    const q = decodeURIComponent((full.split('q=')[1] || '').split('&')[0]).toLowerCase();
    answer = { songs: SONGS.filter((s) => `${s.title} ${s.artist}`.toLowerCase().includes(q)), playing: null };
  } else if (method === 'GET' && path === '/spectra/api/light-show/context-name') answer = { name: 'Pasted One' };
  else if (method === 'POST' && path === '/spectra/api/light-show/playlists') answer = { ...body, id: body.id || 'pl-new' };
  else if (method === 'PUT' && path === '/spectra/api/light-show/playlists/follow') answer = { follow_enabled: body.enabled };
  else if (method === 'POST' && path.startsWith('/spectra/api/light-show/playlist-run/')) answer = STATUS;
  return new NodeResponse(JSON.stringify(answer), { status: 200, headers: { 'Content-Type': 'application/json' } });
};
globalThis.fetch = fakeFetch;
dom.window.fetch = fakeFetch;

const tmpDir = mkdtempSync(join(tmpdir(), 'lightshow-playlist-ui-'));
const src = (f) => JSON.stringify(join(repo, 'spectra/web/src/lightshow', f));
const entrySrc = `
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import PlaylistView from ${src('PlaylistView.tsx')};
import { PlaylistBanner } from ${src('PlaylistRunCard.tsx')};
export * as ops from ${src('playlistOps.ts')};
export const container = document.createElement('div');
document.body.appendChild(container);
let root = null;
const toasts = globalThis.__toasts__ = [];
export async function mount(status) {
  root = createRoot(container);
  const toast = (msg, kind) => toasts.push({ msg, kind });
  await act(async () => {
    root.render(React.createElement(MemoryRouter, null,
      React.createElement(PlaylistBanner, { status, onChange: () => {}, toast }),
      React.createElement(PlaylistView, { sets: ${JSON.stringify(SETS)}, status, reloadStatus: () => {}, toast })));
  });
  await settle();
}
export async function settle(ms = 30) {
  for (let i = 0; i < 4; i += 1) await act(async () => { await new Promise((r) => setTimeout(r, ms)); });
}
export async function step(fn, ms = 20) { await act(async () => { fn(); await new Promise((r) => setTimeout(r, ms)); }); }
export function unmount() { act(() => root.unmount()); }
`;
const entryFile = join(tmpDir, 'entry.mjs');
writeFileSync(entryFile, entrySrc);
const outFile = join(tmpDir, 'out.cjs');
const build = await esbuild.build({
  entryPoints: [entryFile], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
  outfile: outFile, nodePaths: [join(repo, 'spectra/web/node_modules')], logLevel: 'silent',
  loader: { '.css': 'empty', '.svg': 'text' },
});
ok(build.errors.length === 0, 'PlaylistView.tsx + PlaylistRunCard.tsx + their real children bundle cleanly');
const { container, mount, step: act1, settle, unmount, ops } = require(outFile);

console.log('ONE — the pure helpers');
ok(ops.parseContext('https://open.spotify.com/playlist/37i9dQZF1?si=abc') === 'spotify:playlist:37i9dQZF1',
  'a pasted open.spotify.com playlist link becomes its URI');
ok(ops.parseContext('spotify:album:XyZ') === 'spotify:album:XyZ', 'a pasted album URI is kept');
ok(ops.parseContext('https://open.spotify.com/track/abc') === null, 'a track link is not a context');
const wire = ops.toWire(PL);
ok(!('problems' in wire) && !('summary' in wire.songs[0]) && !('title' in wire.songs[0].steps[0]),
  'the wire body drops the served-only fields (problems, summary, title)');
ok(wire.songs[0].steps[0].set_id === 'set-heavy' && wire.contexts[0] === CTX, 'and keeps what he authored');
const pasted = ops.copyEntrySteps(PL.songs[0].steps);
ok(pasted[0].id !== 's1' && pasted[0].set_id === 'set-heavy' && pasted[0].on === 'low',
  'a pasted entry keeps its steps with fresh ids');
ok(ops.outcomeLine(RUN.song_steps[0]) === 'Heavy Calm — armed for the Low Trigger', 'an armed step\'s line');
ok(ops.outcomeLine(RUN.song_steps[2]).startsWith('Show Mode — missed: its song ended'), 'a missed step names why');
ok(ops.runHeadline(RUN) === 'Following 40! Lightshow · song 3', 'the run headline');

await mount(STATUS);
const q = (sel, root = container) => root.querySelector(sel);
const qa = (sel, root = container) => [...root.querySelectorAll(sel)];
const click = async (el) => act1(() => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
const setInput = async (el, value) => act1(() => {
  const proto = Object.getPrototypeOf(el);
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
  el.dispatchEvent(new dom.window.Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
}, 300);
const button = (text, root = container) => qa('button', root).find((b) => b.textContent.trim().startsWith(text));

console.log('TWO — Build');
ok(qa('.light-show-sets li').some((li) => li.textContent.includes('40! Lightshow') && li.textContent.includes('2 songs')),
  'the program is listed with its song count');
ok(qa('.show-playlist-contexts li').length === 1 && q('.show-playlist-contexts li').textContent.includes('40! Lightshow'),
  'its Spotify playlist shows as a named chip');
await settle(50);
const offers = qa('.show-playlist-offers button').map((b) => b.textContent);
ok(offers.length === 1 && offers[0].includes('Tanner 2'),
  `recently played playlists it does not follow yet are offered (${offers.join(' | ')})`);
await click(button('+ Tanner 2'));
ok(qa('.show-playlist-contexts li').length === 2, 'tapping one adds it');
const cards = qa('li.show-playlist-song');
ok(cards.length === 2, 'one card per song');
ok(cards[0].textContent.includes('Yonaguni — Bad Bunny') && cards[0].textContent.includes('Heavy Calm — Low Trigger')
  && !q('.show-playlist-step', cards[0]), 'a song with steps is collapsed to a one-line summary');
ok(Boolean(q('.show-playlist-step', cards[1])) === false && Boolean(button('+ Step', cards[1])),
  'a song with no steps opens ready for one');
await click(q('.show-playlist-toggle', cards[0]));
const icons = qa('.show-playlist-step .show-seq-arm button', qa('li.show-playlist-song')[0]);
ok(icons.length === 4 && icons.every((b) => b.querySelector('svg path')), 'a step shows four timing icons, real SVG');
ok(icons[3].classList.contains('armed') && icons[3].getAttribute('aria-checked') === 'true',
  'the Low arrow is lit for a step on the Low');
ok(Boolean(qa('label', qa('li.show-playlist-song')[0]).find((l) => l.textContent.includes('finish on the mark'))),
  'a High/Low step offers finish on the mark');
await click(icons[1]);
ok(qa('.show-playlist-step .show-seq-arm button', qa('li.show-playlist-song')[0])[1].classList.contains('armed'),
  'tapping the bunny moves it to the next scene change');
await click(q('button[aria-label="Copy steps"]', qa('li.show-playlist-song')[0]));
await click(q('button[aria-label="Paste steps"]', qa('li.show-playlist-song')[1]));
ok(qa('.show-playlist-step', qa('li.show-playlist-song')[1]).length === 1, '📋 copy then ⎘ paste puts the steps on another song');
const search = q('.show-playlist-song-search input[type=search]');
await setInput(search, 'titi');
await settle(100);
await setInput(search, 'tití');
await settle(100);
const res = qa('.show-playlist-song-search .show-seq-song-results li');
ok(res.length === 1 && res[0].textContent.includes('Tití Me Preguntó — Bad Bunny'), 'the song search lists a match');
await click(q('button', res[0]));
ok(qa('li.show-playlist-song').length === 3, '+ Add puts the song on the program');
await click(button('Save'));
const saved = requests.filter((r) => r.method === 'POST' && r.path === '/spectra/api/light-show/playlists').pop();
ok(saved && saved.body.contexts.length === 2 && saved.body.context_names['spotify:playlist:tanner'] === 'Tanner 2',
  'Save posts both playlists with their names');
ok(saved && saved.body.songs.length === 3 && saved.body.songs[0].steps[0].on === 'scene_change'
  && saved.body.songs[1].steps.length === 1 && saved.body.songs[1].steps[0].id !== 's1'
  && !('summary' in saved.body.songs[0]), 'Save posts what the screen shows (served fields stripped)');
await click(button('▶ Follow now'));
const started = requests.filter((r) => r.path === '/spectra/api/light-show/playlist-run/start').pop();
ok(started && started.body.replace === true, 'Follow now posts the start, replacing the one following (after asking)');
await click(q('.show-playlist-follow input'));
const follow = requests.filter((r) => r.method === 'PUT' && r.path === '/spectra/api/light-show/playlists/follow').pop();
ok(follow && follow.body.enabled === false, 'the Follow playlists switch PUTs the global switch');

console.log('THREE — the Run card and the banner');
const card = q('.light-show-playlist-card');
ok(card && card.textContent.includes('Playing from: 40! Lightshow'), 'the card says where the music plays from');
ok(card.textContent.includes('Following 40! Lightshow · song 3'), 'and which program follows');
ok(card.textContent.includes('Now: Yonaguni — Bad Bunny') && card.textContent.includes('its own entry'),
  'the song playing and which entry it got');
const rows = qa('.light-show-playlist-step', card);
ok(rows.length === 3 && rows[0].classList.contains('armed') && rows[1].classList.contains('fired')
  && rows[2].classList.contains('missed'), 'each step shows armed / fired / missed');
ok(card.textContent.includes('Up next: Bad Bunny — Moscow Mule') && card.textContent.includes('will arm Show Mode — High Trigger'),
  'up next names the song and what its entry will arm');
await click(q('button[aria-label="Fire Heavy Calm now"]', card));
const fired = requests.filter((r) => r.path === '/spectra/api/light-show/playlist-run/fire-step').pop();
ok(fired && fired.body.step_id === 's1', 'Fire now posts that step');
await click(button('Skip this song', card));
ok(requests.some((r) => r.path === '/spectra/api/light-show/playlist-run/skip-song'), 'Skip posts skip-song');
await click(button('■ Stop following', card));
ok(requests.some((r) => r.path === '/spectra/api/light-show/playlist-run/stop'), 'Stop following posts stop');
const banner = q('.light-show-playlist-banner');
ok(banner && banner.textContent.includes('♫ Following 40! Lightshow · song 3 — Yonaguni — Bad Bunny'),
  'the banner names the program and the song');
const before = requests.filter((r) => r.path === '/spectra/api/light-show/playlist-run/stop').length;
await click(button('Stop following', banner));
ok(requests.filter((r) => r.path === '/spectra/api/light-show/playlist-run/stop').length === before + 1,
  'the banner\'s Stop following posts stop too');

unmount();
await mount({ ...STATUS, run: null, up_next: null, playing_from: { uri: 'spotify:playlist:x', type: 'playlist', name: 'Liked Songs', program: null } });
ok(!q('.light-show-playlist-banner'), 'no banner while nothing follows');
ok(q('.light-show-playlist-card').textContent.includes('Playing from: Liked Songs')
  && q('.light-show-playlist-card').textContent.includes('no program answers to it'),
  'with nothing following the card still says where the music plays from');
unmount();

if (failures) {
  console.log(`${failures} failed`);
  process.exit(1);
}
console.log('all passed');
process.exit(0);
