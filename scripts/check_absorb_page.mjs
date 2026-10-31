// Executable spec for the Absorb Music page (/absorb — spectra/web/src/
// absorb/, data/absorb-music-plan/report.md §10 and phase 4). The jsdom
// real-mount pattern of check_nav_menu.mjs: bundle the REAL source with
// esbuild, mount it under jsdom against a RECORDING fake of SpotFX's own
// /api/absorb routes (no network — every request lands in `world.requests`
// and nothing else), and drive real events.
//
// Five things proven:
//   1. The words (absorbSummary.ts) — the playlist-link parser accepts the
//      same three shapes the runner does and nothing else; a head rate with
//      nothing committed is "none", never 0 %; a silence the run never
//      proved is never a tick; force recapture's meaning names the
//      stronger "re-capture even the ones that pass"; the schedule's
//      refusals match the server's.
//   2. The page, mid-window: the three cards, the six counts, the head
//      rate, the silence proof, the parked list (head_unreachable among
//      them) and only the realigns that moved his triggers; and every
//      control reaches its route with the right body — Stop, Skip, Retry,
//      force recapture, the schedule switch, a window added and saved.
//   3. The shipped state: nothing linked, so Start is disabled and says
//      why; a pasted ALBUM link is refused with no write; a playlist link
//      is saved canonical; Start (once linked) asks before it presses.
//   4. The six help topics are real HELP_SECTIONS entries, the menu row's
//      "?" maps /absorb to `absorb-music`, /absorb carries its own icon in
//      the Engine group — and, behaviourally, hovering the page's own
//      controls actually opens each of the six topics (never a dead or
//      misdirected InfoTip): every control is hovered for real and the
//      portaled help panel's rendered <HelpLink> href is read back.
//   5. Sonic (phase 5): the page carries the floating Sonic chat, and
//      opening it shows the `sonic-absorb` topic — linked, not orphaned —
//      without calling a single Absorb route.
//
// Run: node scripts/check_absorb_page.mjs
import { mkdtempSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
const web = join(repo, 'spectra/web');
const require = createRequire(join(web, 'package.json'));
const esbuild = require('esbuild');

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.log(`  ✗ ${msg}`); failures += 1; }
};

async function bundle(entrySrc, name) {
  const tmp = mkdtempSync(join(tmpdir(), `absorb-${name}-`));
  const entry = join(tmp, 'entry.mjs');
  writeFileSync(entry, entrySrc);
  const out = join(tmp, 'out.cjs');
  const r = await esbuild.build({
    entryPoints: [entry], bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
    outfile: out, nodePaths: [join(web, 'node_modules')], logLevel: 'silent',
    loader: { '.css': 'empty' },
  });
  if (r.errors.length) throw new Error(r.errors.map((e) => e.text).join('; '));
  return require(out);
}

// A pure-data TS module with no runtime imports (helpContent.ts,
// routeTopics.ts, navGroups.ts — whose only import is `import type`, which
// erases — and iconRegistry.ts) needs no bundling, just the transform +
// require check_nav_menu.mjs's §1 already established for navGroups.ts.
function loadData(file, name) {
  const code = esbuild.transformSync(readFileSync(file, 'utf8'), { loader: 'ts', format: 'cjs' }).code;
  const tmp = mkdtempSync(join(tmpdir(), `absorb-${name}-`));
  const outFile = join(tmp, 'out.cjs');
  writeFileSync(outFile, code);
  return require(outFile);
}

// ── 1. the words ─────────────────────────────────────────────────────────
console.log('§1 absorbSummary.ts — the words the page shows');
const S = await bundle(`export * from ${JSON.stringify(join(web, 'src/absorb/absorbSummary.ts'))};`, 'summary');
{
  const id = '37i9dQZF1DX4sWSpwq3LiO';
  ok(S.parsePlaylistLink(`spotify:playlist:${id}`) === `spotify:playlist:${id}`, 'a spotify:playlist: URI is kept');
  ok(S.parsePlaylistLink(`https://open.spotify.com/playlist/${id}?si=abc123`) === `spotify:playlist:${id}`,
    'an open.spotify.com URL (query string and all) becomes the canonical URI');
  ok(S.parsePlaylistLink(id) === `spotify:playlist:${id}`, 'a bare id is accepted (the runner accepts it too)');
  ok(S.parsePlaylistLink('https://open.spotify.com/album/1A2GTWGtFfWp7KSQTwWOyo') === null,
    'an ALBUM link is refused — Absorb plays a playlist');
  ok(S.parsePlaylistLink('  ') === null && S.parsePlaylistLink('hello') === null, 'empty or junk is refused');

  // the hidden player (phase 4, services/absorb_lane.py)
  ok(S.laneLine(null) === 'Reading the hidden player…', 'the hidden player line waits for its read');
  ok(S.laneLine({ enabled: false, state: 'off', reason: '', job: null, learned: [], failed: [], passed_over: [], log: [] })
    .startsWith('Off:'), 'off says so');
  ok(S.laneLine({ enabled: true, state: 'learning', reason: '', learned: [], failed: [], passed_over: [], log: [],
    job: { job_id: 'j', uri: 'u', title: 'September', artist: 'Earth, Wind & Fire', duration_ms: 1 } })
    === 'Learning Earth, Wind & Fire — September on the hidden player.', 'learning names the song');
  ok(S.laneLine({ enabled: true, state: 'resting', reason: 'The house is asleep, so the hidden player rests.', job: null,
    learned: [], failed: [], passed_over: [], log: [] }).includes('asleep'), 'resting gives the server\'s own reason');
  ok(S.laneTally({ enabled: true, state: 'idle', reason: '', job: null, learned: [{ uri: 'a', title: 'x', at_ms: 1 }],
    failed: [], passed_over: ['b', 'c'], log: [] }) === '1 song learned since SpotFX started · 2 passed over after using up their tries',
    'the tally counts what it learned and passed over, never invented');

  const none = S.headRateView({ attempted: 0, with_head: 0 });
  ok(none.pct === null && /No capture has committed/.test(none.text),
    'a head rate with nothing committed is "none yet", never 0 %');
  const h = S.headRateView({ attempted: 13, with_head: 11 });
  ok(h.pct === 85 && h.text.includes('11 of 13'), `13 committed, 11 with their head reads 85% (${h.pct}%)`);
  ok(/last window/.test(S.headRateView({ attempted: 2, with_head: 1 }, 'last').text), 'the last window is named as such');
  ok(S.recaptureHeadLine({ attempted: 3, with_head: 2, by_mode: { recapture: { attempted: 2, with_head: 1 } } })
    === 'Re-captures alone: 1 of 2 (50%).', 'the re-capture half is read straight off by_mode');
  ok(S.recaptureHeadLine({ attempted: 1, with_head: 1 }) === null, 'no split recorded → no re-capture line, never a guess');

  const brief = { state: 'running', stage: 'capturing', now_playing: { uri: 'u', title: 'T', started_ms: 0, attempt: 2, mode: 'recapture' },
    queue_len: 189, counts: { captured: 11, parked: 1, failed: 0, requeued: 0, skipped: 344, head_missed: 0 } };
  ok(S.progressLine(brief) === 'Song 13 of 202 · attempt 2', `progress counts done + this + the queue (${S.progressLine(brief)})`);
  ok(/Warm-up/.test(S.progressLine({ ...brief, now_playing: { ...brief.now_playing, mode: 'warmup' } })),
    'a warm-up song is not counted as work and says what it is');
  ok(S.stateView({ state: 'idle' }).label === 'Idle' && S.stateView(null).label === 'Idle', 'no run reads Idle');
  ok(S.stateView({ state: 'paused', stage: 'yielded', wait_detail: 'Other music started.' }, { resume_after_quiet_min: 20, max_resumes_per_window: 3 })
    .detail.includes('20 minutes'), 'a window that stepped aside names its quiet clock');
  ok(S.stateView({ state: 'refused', end_detail: 'No playlist is linked — link one first.' }).detail.includes('link one first'),
    'a refusal shows the runner\'s own sentence');

  const idleLines = S.silenceLines({ state: 'idle' }, null);
  ok(idleLines.length === 1 && idleLines[0].ok === null, 'with no window, the silence proof claims nothing');
  const refusedRun = { state: 'refused', opened_ms: 0, pre_window: {}, silence_checks: [], restore: {} };
  ok(S.silenceLines({ state: 'refused' }, refusedRun).every((l) => l.ok !== true),
    'a refused window (never opened) earns no tick');
  const openRun = { state: 'running', opened_ms: 5, pre_window: { snap_volume: 34, capture: { name: 'Effects Host', percent: 100, muted: false } },
    silence_checks: [{ at_ms: 1, ok: true, detail: 'silent' }], restore: {} };
  const lines = S.silenceLines({ state: 'running', silent: true }, openRun);
  ok(lines.length === 3 && lines.every((l) => l.ok === true), 'a proven window: rooms, capture client, volume — three ticks');
  ok(lines[0].text === 'Every room silent', 'the check\'s own "silent" detail is not repeated back');
  const badRestore = S.silenceLines({ state: 'ended', silent: false }, { ...openRun, state: 'ended', restore: { at_ms: 9, ok: false, detail: 'snap_volume reads 0, not 34' } });
  ok(badRestore.some((l) => l.ok === false && l.text.includes('did not read back')), 'a restore that did not read back is a problem, named');
  ok(S.silenceLines({ state: 'ended', restore_pending: 'restoring' }, openRun)[0].ok === false,
    'a pending restore leads the list as a problem');
  ok(S.lightsLine({ state: 'running', lights_held: true }).ok === true, 'lights held → the stand-down is shown proven');

  ok(/re-capture even the ones that pass/.test(S.forceRecaptureMeaning(true)),
    'force recapture ON says "re-capture even the ones that pass" (§8.6)');
  ok(/re-captured anyway/.test(S.forceRecaptureMeaning(false)),
    'force recapture OFF says the headless songs are re-captured anyway');

  ok(S.windowProblems([{ days: [], start: '21:30', end: '00:30' }])[0] === 'Window 1 has no days', 'a window with no days is refused by name');
  ok(S.windowProblems([{ days: ['mon'], start: '22:00', end: '22:00' }])[0] === 'Window 1 starts and ends at 22:00',
    'a zero-length window is refused (the server refuses it too)');
  ok(S.windowProblems([{ days: ['mon'], start: '25:00', end: '00:30' }]).length === 1, 'an impossible time is refused');
  ok(S.windowProblems([{ days: ['mon'], start: '21:30', end: '00:30' }]).length === 0, 'a window across midnight is fine');
  ok(S.daysLabel(['sat', 'sun']) === 'Weekends' && S.daysLabel([...S.DAYS]) === 'Every day'
    && S.daysLabel(['fri', 'mon']) === 'Mon, Fri', 'days read in his words, in week order');
  ok(/ends the next day/.test(S.windowLabel({ days: ['mon'], start: '21:30', end: '00:30' }))
    && S.windowLength({ days: ['mon'], start: '21:30', end: '00:30' }) === '3 h', 'a midnight-crossing window is 3 h and says so');

  const realigned = S.realignedSongs(
    { realigned: [
      { uri: 'a', title: 'A', status: 'applied', shift_ms: 240, r: 0.9, triggers: 6, at_ms: 30 },
      { uri: 'b', title: 'B', status: 'applied', shift_ms: 10, r: 0.9, triggers: 0, at_ms: 40 },
      { uri: 'c', title: 'C', status: 'low_confidence', shift_ms: 0, r: 0.2, triggers: 4, at_ms: 50 },
    ] },
    [{ realigned: [{ uri: 'a', title: 'A', status: 'applied', shift_ms: 100, r: 0.8, triggers: 6, at_ms: 10 }] }],
  );
  ok(realigned.length === 1 && realigned[0].uri === 'a' && realigned[0].shift_ms === 240,
    'only realigns that MOVED his triggers are listed, once per song, newest first');
  ok(S.realignLine(realigned[0]) === '6 of your triggers moved +240 ms (match 0.90)', 'a realign reads as triggers moved');
  ok(S.parkedLine({ reason: 'head_unreachable', lifetime_attempts: 3, last_failure: 'head_missed' })
    === 'its head never arrived · 3 attempts · last: committed without its head', 'a head_unreachable park reads in words');
  const refusedOutcome = S.outcomeLine({ label: 'Sun 21:30–00:30', outcome: 'refused', detail: 'Serenity isn\'t available.', run: null });
  ok(refusedOutcome.includes('refused') && refusedOutcome.includes('Serenity'), 'a refused evening names its reason');
  ok(S.lastOpenedRun({ id: 'x', state: 'running', opened_ms: 5 }, [{ id: 'y', state: 'ended', opened_ms: 3 }]).id === 'y',
    'the Playlist card\'s "last window" skips a window still open');
}

// ── 2-3. the page, mounted ───────────────────────────────────────────────
let jsdomMod;
let hasJsdom = false;
try {
  jsdomMod = require('jsdom');
} catch {
  console.log('\njsdom not installed in spectra/web/node_modules (dev-only) — skipping §2-4b.');
  report();
}
const { JSDOM } = jsdomMod;
hasJsdom = true;
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/absorb' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
for (const k of ['HTMLElement', 'HTMLInputElement', 'Node', 'Element', 'MouseEvent', 'KeyboardEvent', 'Event', 'getComputedStyle']) {
  globalThis[k] = dom.window[k];
}
globalThis.localStorage = dom.window.localStorage;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let confirmAnswer = true;
let confirmAsked = 0;
dom.window.confirm = () => { confirmAsked += 1; return confirmAnswer; };
globalThis.confirm = dom.window.confirm;

const PL = 'spotify:playlist:37i9dQZF1DX4sWSpwq3LiO';
const t = (n) => `spotify:track:t${n}`;
let world;
function newWorld(kind) {
  const linked = kind !== 'idle';
  const running = kind === 'running';
  const config = {
    enabled: false, source_playlist_uri: linked ? PL : '', captured_playlist_name: 'Recently Captured',
    force_recapture: false, head_max_ms: 1000, order: 'fresh_first', warm_up: true,
    windows: linked ? [{ days: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'], start: '21:30', end: '00:30' }] : [],
    max_attempts: 3, play_window_size: 10, overrun_grace_min: 5, recently_captured_max: 200,
    recently_captured_includes_skipped: true, resume_after_quiet_min: 20, min_remaining_min: 20,
    max_resumes_per_window: 3, run_while_sleeping: true, silence_recheck_s: 60,
  };
  const counts = { captured: 11, failed: 4, requeued: 3, skipped: 344, parked: 1, head_missed: 2 };
  const run = running ? {
    id: 'r1', state: 'running', started_ms: 1, ended_ms: 0, end_reason: '', end_detail: '', window: { start: 1, end: null },
    started_by: 'press', pre_window: { snap_volume: 34, capture: { name: 'Effects Host', percent: 100, muted: false } },
    queue: [t(2), t(3)], now_playing: { uri: t(1), title: 'Noah Kahan — Stick Season', started_ms: 2, attempt: 1, mode: 'recapture' },
    captured: [], failed: [], parked: [], skipped: [], counts,
    head_rate: { attempted: 13, with_head: 11, by_mode: { recapture: { attempted: 8, with_head: 6 } } },
    realigned: [
      { uri: t(7), title: 'Bad Bunny — DtMF', status: 'applied', shift_ms: 240, r: 0.92, triggers: 6, at_ms: 5 },
      { uri: t(8), title: 'Nothing Moved', status: 'applied', shift_ms: 60, r: 0.9, triggers: 0, at_ms: 6 },
    ],
    sleeping_at_open: false, silence_checks: [{ at_ms: 3, ok: true, detail: 'silent' }], yields: [], resumes: 0, log: [],
    opened_ms: 2, wait_reason: '', wait_detail: '', silent: true, lights_held: true, restore: {}, restore_pending: '',
    source_playlist_uri: PL, source_playlist_name: 'The backlog', stage: 'capturing',
  } : null;
  return {
    config,
    run,
    parked: running ? [
      { uri: t(41), title: 'Fleetwood Mac — Dreams', reason: 'head_unreachable', parked_ms: 1, lifetime_attempts: 3, last_failure: 'head_missed', last_attempt_ms: 1 },
    ] : [],
    requests: [],
  };
}
const briefOf = (run) => (run ? {
  state: run.state, stage: run.stage, run_id: run.id, started_ms: run.started_ms, now_playing: run.now_playing,
  queue_len: run.queue.length, counts: run.counts, head_rate: { attempted: run.head_rate.attempted, with_head: run.head_rate.with_head },
  lights_held: run.lights_held, silent: run.silent, restore_pending: '', sleeping_at_open: false, window: run.window,
  opened_ms: run.opened_ms, started_by: run.started_by, source_playlist_uri: run.source_playlist_uri,
  source_playlist_name: run.source_playlist_name,
} : { state: 'idle' });

globalThis.fetch = async (url, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const body = init.body ? JSON.parse(init.body) : undefined;
  world.requests.push({ method, url: String(url), body });
  const json = (b) => new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } });
  const u = String(url);
  if (u.startsWith('/api/absorb/config')) {
    if (method === 'PUT') world.config = { ...world.config, ...body };
    return json(world.config);
  }
  if (u.startsWith('/api/absorb/run')) return json({ brief: briefOf(world.run), run: world.run, earlier: [] });
  if (u.startsWith('/api/absorb/preview')) {
    return json(world.config.source_playlist_uri
      ? { linked: true, resolved: true, playlist: { id: 'x', name: 'The backlog' },
        counts: { total: 1764, skip: 344, fresh: 603, recapture: 817, parked: 0 }, reasons: { headless: 706, no_shape: 603 },
        force_recapture: world.config.force_recapture, head_max_ms: 1000 }
      : { linked: false });
  }
  if (u.startsWith('/api/absorb/schedule')) {
    return json({ enabled: world.config.enabled, active: world.config.enabled && world.config.windows.length > 0,
      house_tz: 'America/New_York', windows: [], open_now: [], next: null, overrun_grace_min: 5, outcomes: [] });
  }
  if (u.startsWith('/api/absorb/parked')) return json({ parked: world.parked });
  if (u.startsWith('/api/absorb/lane')) {
    return json(world.config.use_capture_lane
      ? { enabled: true, state: 'learning', reason: '', log: [], failed: [], passed_over: [t(77)],
          learned: [{ uri: t(70), title: 'ABBA — Dancing Queen', at_ms: 1 }],
          job: { job_id: 'j1', uri: t(71), title: 'September', artist: 'Earth, Wind & Fire', duration_ms: 215000 } }
      : { enabled: false, state: 'off', reason: 'Off: the hidden player only learns songs during a Jukebox night.',
          job: null, learned: [], failed: [], passed_over: [], log: [] });
  }
  if (u.startsWith('/api/absorb/retry')) return json({ uri: body.uri, unparked: true });
  if (u.startsWith('/api/absorb/start')) return json({ status: 'running', run: briefOf(world.run) });
  if (u.startsWith('/api/absorb/stop')) return json({ status: 'ended', run: briefOf(world.run) });
  if (u.startsWith('/api/absorb/skip-song')) return json({ status: 'skipped', run: briefOf(world.run) });
  if (u.startsWith('/api/spotify/contexts')) {
    return json({ playing: { context_uri: 'spotify:album:notaplaylist', type: 'album', name: 'An Album' }, recent: [
      { context_uri: 'spotify:playlist:chill0000000000000', type: 'playlist', name: 'Chill' },
    ] });
  }
  return json({});
};

const P = await bundle(`
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import AbsorbPage from ${JSON.stringify(join(web, 'src/absorb/AbsorbPage.tsx'))};
import { ToastProvider } from ${JSON.stringify(join(web, 'src/components/Toast.tsx'))};
let root = null;
const container = document.createElement('div');
document.body.appendChild(container);
export function mount() {
  if (root) act(() => { root.unmount(); });
  root = createRoot(container);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() => {
    root.render(React.createElement(QueryClientProvider, { client: qc },
      React.createElement(ToastProvider, null,
        React.createElement(MemoryRouter, { initialEntries: ['/absorb'] }, React.createElement(AbsorbPage)))));
  });
  return container;
}
export async function settle(ms = 30) {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => { await new Promise((r) => setTimeout(r, ms)); });
  }
}
export function actSync(fn) { act(fn); }
export function unmount() { if (root) act(() => { root.unmount(); }); root = null; }
`, 'page');

const $ = (c, sel) => c.querySelector(sel);
const text = (el) => (el ? el.textContent : '');
const click = async (el) => {
  P.actSync(() => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true, cancelable: true })));
  await P.settle();
};
const buttonByText = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent));
const typeInto = async (input, value) => {
  const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value').set;
  P.actSync(() => {
    setter.call(input, value);
    input.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  });
  await P.settle(10);
};
const writes = () => world.requests.filter((r) => r.method !== 'GET');
const lastWrite = () => writes().at(-1);

console.log('\n§2 a window mid-evening — the cards, and every control reaches its route');
{
  world = newWorld('running');
  const c = P.mount();
  await P.settle();
  ok(['Run', 'Playlist', 'Needs attention'].every((n) => c.querySelector(`section[aria-label="${n}"]`)),
    'the three cards render: Run, Playlist, Needs attention');
  ok(text($(c, '[data-testid="absorb-state"]')) === 'Capturing', 'the badge reads Capturing');
  ok(text($(c, '[data-testid="absorb-now"]')).includes('Stick Season')
    && text($(c, '[data-testid="absorb-now"]')).includes('Song 13 of 15 · attempt 1'),
    `now capturing names the song and where it is (${text($(c, '[data-testid="absorb-now"]'))})`);
  const tiles = ['captured', 'skipped', 'failed', 'requeued', 'head_missed', 'parked']
    .map((k) => text($(c, `[data-testid="absorb-count-${k}"] .absorb-tile-value`)));
  ok(tiles.join(',') === '11,344,4,3,2,1', `the six live counts (${tiles.join(',')})`);
  ok(text($(c, '[data-testid="absorb-headrate"]')).includes('85%')
    && text($(c, '[data-testid="absorb-headrate"]')).includes('Re-captures alone: 6 of 8'),
    'the head-success rate and the re-capture half');
  const proof = text($(c, '[data-testid="absorb-proof"]'));
  ok(proof.includes('Effects Host') && proof.includes('34') && proof.includes('Lights standing down'),
    'the silence proof names the capture client, the volume it will restore, and the light stand-down');
  ok(text($(c, '[data-testid="absorb-parked"]')).includes('Fleetwood Mac — Dreams')
    && text($(c, '[data-testid="absorb-parked"]')).includes('its head never arrived'),
    'a head_unreachable park is listed in words');
  const realign = text($(c, '[data-testid="absorb-realigned"]'));
  ok(realign.includes('DtMF') && !realign.includes('Nothing Moved'), 'only the realign that moved his triggers is listed');
  ok(!buttonByText(c, /Start now/), 'Start is not offered while a window is open');
  ok(text($(c, '[data-testid="absorb-preview-skip"]')).includes('344')
    && text($(c, '[data-testid="absorb-preview-recapture"]')).includes('817')
    && text($(c, '[data-testid="absorb-preview-fresh"]')).includes('603'), 'the playlist split: 344 / 817 / 603');

  ok(/^Off:/.test(text($(c, '[data-testid="absorb-force-meaning"]'))), 'force recapture starts OFF and says what that means');
  confirmAsked = 0;
  await click($(c, 'button[aria-label="Enable force recapture"]'));
  ok(confirmAsked === 1, 'turning force recapture ON asks first');
  ok(lastWrite()?.method === 'PUT' && lastWrite().url === '/api/absorb/config'
    && JSON.stringify(lastWrite().body) === '{"force_recapture":true}', 'and writes exactly {force_recapture: true}');
  ok(/re-capture even the ones that pass/.test(text($(c, '[data-testid="absorb-force-meaning"]'))),
    'the meaning beside the switch changes to "re-capture even the ones that pass"');

  await click(buttonByText(c, /^Retry$/));
  ok(lastWrite()?.url === '/api/absorb/retry' && lastWrite().body.uri === t(41), 'Retry posts the parked song\'s uri');

  await click(buttonByText(c, /Skip this song/));
  ok(lastWrite()?.url === '/api/absorb/skip-song', 'Skip this song reaches /skip-song');

  await click($(c, 'button[aria-label="Enable the Absorb schedule"]'));
  ok(lastWrite()?.url === '/api/absorb/config' && JSON.stringify(lastWrite().body) === '{"enabled":true}',
    'the schedule switch writes exactly {enabled: true}');

  await click($(c, 'button[aria-label="Disable running while the house sleeps"]'));
  ok(JSON.stringify(lastWrite()?.body) === '{"run_while_sleeping":false}', 'the sleeping switch writes run_while_sleeping');

  const before = writes().length;
  await click(buttonByText(c, /Add a window/));
  ok(writes().length === before, 'adding a window is a draft — nothing written yet');
  const days = [...c.querySelectorAll('[data-testid="absorb-window"]')][1].querySelectorAll('.absorb-day');
  for (const d of [...days]) {
    if (d.getAttribute('aria-pressed') === 'true' && !/Sat|Sun/.test(d.getAttribute('aria-label'))) await click(d);
  }
  await click(buttonByText(c, /Save schedule/));
  const saved = lastWrite();
  ok(saved?.url === '/api/absorb/config' && Array.isArray(saved.body.windows) && saved.body.windows.length === 2
    && JSON.stringify(saved.body.windows[1].days) === '["sat","sun"]' && Object.keys(saved.body).length === 1,
    `Save schedule writes the windows only (${JSON.stringify(saved?.body)})`);

  await click(buttonByText(c, /Add a window/));
  const third = [...c.querySelectorAll('[data-testid="absorb-window"]')][2];
  for (const d of [...third.querySelectorAll('.absorb-day')]) await click(d);
  const save = buttonByText(c, /Save schedule/);
  ok(save?.disabled === true && /Window 3 has no days/.test(text($(c, '.absorb-problems'))),
    'a window with no days is refused by name and Save is disabled');
  await click(buttonByText(c, /^Cancel$/));

  // the hidden player card (phase 4): off, says so; the switch writes that one setting
  const hp = $(c, '[data-testid="absorb-hidden-player"]');
  ok(!!hp && text($(c, '[data-testid="absorb-lane-line"]')).startsWith('Off:'),
    'the hidden player card renders, off by default, saying what it does instead');
  const sw = hp?.querySelector('button[aria-label*="hidden player"]');
  await click(sw);
  ok(lastWrite()?.url === '/api/absorb/config' && JSON.stringify(lastWrite().body) === '{"use_capture_lane":true}',
    `its switch writes use_capture_lane alone (${JSON.stringify(lastWrite()?.body)})`);
  await P.settle(60);
  ok(text($(c, '[data-testid="absorb-lane-line"]')).includes('Learning Earth, Wind & Fire — September'),
    `on, it names the song the hidden player is learning (${text($(c, '[data-testid="absorb-lane-line"]'))})`);

  await click(buttonByText(c, /^\s*Stop$/));
  ok(lastWrite()?.url === '/api/absorb/stop', 'Stop reaches /stop');
  ok(writes().every((w) => w.url.startsWith('/api/absorb/')), 'every write the page made went to /api/absorb');
  P.unmount();
}

console.log('\n§3 the shipped state — nothing linked, nothing ever run');
{
  world = newWorld('idle');
  const c = P.mount();
  await P.settle();
  const start = buttonByText(c, /Start now/);
  ok(start && start.disabled, 'Start now is shown, and disabled with nothing linked');
  ok(/Link a playlist first/.test(text($(c, '[data-testid="absorb-link-first"]'))), 'and the card says why');
  ok(text($(c, '[data-testid="absorb-count-captured"] .absorb-tile-value')) === '—',
    'the counts read "—" before any window has run, not zeros');
  const offers = text($(c, '[data-testid="absorb-link"]'));
  ok(offers.includes('Chill') && !offers.includes('An Album'), 'the quick picks offer playlists only, never an album');
  const input = $(c, 'input[aria-label="Spotify playlist link"]');
  await typeInto(input, 'https://open.spotify.com/album/1A2GTWGtFfWp7KSQTwWOyo');
  await click(buttonByText(c, /^Link$/));
  ok(writes().length === 0, 'a pasted ALBUM link writes nothing');
  await typeInto(input, 'https://open.spotify.com/playlist/37i9dQZF1DX4sWSpwq3LiO?si=zzz');
  await click(buttonByText(c, /^Link$/));
  ok(lastWrite()?.url === '/api/absorb/config' && lastWrite().body.source_playlist_uri === PL,
    'a playlist link is saved as the canonical spotify:playlist: URI');
  ok(text($(c, '[data-testid="absorb-linked"]')).includes('The backlog'), 'the linked playlist then shows by NAME');
  const start2 = buttonByText(c, /Start now/);
  ok(start2 && !start2.disabled, 'once linked, Start is enabled');
  confirmAnswer = false;
  confirmAsked = 0;
  const n = writes().length;
  await click(start2);
  ok(confirmAsked === 1 && writes().length === n, 'Start asks first — and a No presses nothing');
  confirmAnswer = true;
  await click(start2);
  ok(lastWrite()?.url === '/api/absorb/start' && lastWrite().body?.started_by === 'press',
    'a Yes posts /start as his press');
  P.unmount();
}
await report();

async function report() {
  // ── 4. the seven help topics: content, route mapping, and the page's own
  //      controls actually opening them ─────────────────────────────────
  console.log('\n§4 the seven help topics: HELP_SECTIONS, the route\'s "?", and every control');
  const topics = ['absorb-music', 'absorb-silence', 'absorb-failures', 'absorb-schedule',
    'absorb-already-captured', 'absorb-sleeping', 'absorb-hidden-player'];

  const { HELP_SECTIONS } = loadData(join(web, 'src/help/helpContent.ts'), 'help');
  const knownIds = new Set();
  for (const section of HELP_SECTIONS) {
    knownIds.add(section.id);
    for (const e of section.entries ?? []) knownIds.add(e.id);
    for (const sub of section.subsections ?? []) {
      knownIds.add(sub.id);
      for (const e of sub.entries ?? []) knownIds.add(e.id);
    }
  }
  for (const id of topics) ok(knownIds.has(id), `"${id}" is a real section/entry in HELP_SECTIONS`);

  const { topicForPath } = loadData(join(web, 'src/help/routeTopics.ts'), 'routes');
  ok(topicForPath('/absorb') === 'absorb-music', 'the menu row\'s "?" opens absorb-music on /absorb');

  const { NAV_GROUPS, activeGroupId } = loadData(join(web, 'src/nav/navGroups.ts'), 'nav');
  const { ICONS } = loadData(join(web, 'src/components/iconRegistry.ts'), 'icons');
  const engine = NAV_GROUPS.find((g) => g.id === 'engine');
  const absorbItem = engine?.items?.find((it) => it.to === '/absorb');
  ok(!!absorbItem && absorbItem.icon === 'absorb', '/absorb is in the Engine menu with icon "absorb"');
  ok(activeGroupId('/absorb') === 'engine', 'activeGroupId("/absorb") === "engine"');
  ok(typeof ICONS.absorb === 'string' && ICONS.absorb.length > 0, 'ICONS.absorb is a real, non-empty icon path');

  if (hasJsdom) {
    // Behaviour, not text: hover every real InfoTip-wrapped control on the
    // mounted page and read back the HelpLink <a href> its open panel
    // actually renders — proving each topic is reachable from the page
    // itself, not merely present in a string nearby. A dead/commented-out/
    // misdirected InfoTip would leave its topic missing from `reached`.
    world = newWorld('running');
    const c = P.mount();
    await P.settle();
    const tips = [...c.querySelectorAll('.info-tip')];
    ok(tips.length > 0, 'the page renders InfoTip-wrapped controls to hover');
    for (const tip of tips) {
      P.actSync(() => tip.dispatchEvent(new dom.window.MouseEvent('mouseover', { bubbles: true, cancelable: true })));
    }
    const reached = new Set(
      [...document.querySelectorAll('.info-tip-panel a.help-link')]
        .map((a) => new URLSearchParams((a.getAttribute('href') || '').split('?')[1] || '').get('topic'))
        .filter(Boolean),
    );
    ok(topics.every((id) => reached.has(id)) && topics.length === reached.size,
      `hovering the page's own controls opens exactly the seven absorb topics (${[...reached].sort().join(', ')})`);
    P.unmount();
  } else {
    console.log('  (jsdom unavailable — skipping the hover-behaviour half of §4)');
  }

  // ── 5. Sonic (phase 5): the page carries the chat, and its own "?" opens
  //      the absorb topic — the topic is linked from the page, not orphaned
  console.log('\n§5 Sonic on the Absorb page');
  ok(knownIds.has('sonic-absorb'), '"sonic-absorb" is a real section/entry in HELP_SECTIONS');
  if (hasJsdom) {
    world = newWorld('running');
    const c = P.mount();
    await P.settle();
    const fab = $(c, 'button.sonic-popover-fab');
    ok(!!fab, 'the page renders the floating Sonic button');
    const before = world.requests.length;
    // jsdom lays nothing out, so it has no Element.scrollTo — the panel
    // scrolls its message list to the bottom when it opens
    if (!dom.window.HTMLElement.prototype.scrollTo) {
      dom.window.HTMLElement.prototype.scrollTo = () => {};
    }
    if (fab) await click(fab);
    const helpTopics = [...c.querySelectorAll('.sonic-popover-panel a.help-link')]
      .map((a) => new URLSearchParams((a.getAttribute('href') || '').split('?')[1] || '').get('topic'));
    ok(helpTopics.includes('sonic-absorb'),
      `opening it shows the sonic-absorb help topic (${helpTopics.join(', ')})`);
    ok(world.requests.length === before, 'opening the chat calls no Absorb route');
    P.unmount();
  }

  console.log(failures === 0 ? '\nPASS' : `\nFAIL (${failures})`);
  process.exit(failures === 0 ? 0 : 1);
}
