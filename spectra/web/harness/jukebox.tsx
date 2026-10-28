/** JUKEBOX HARNESS (phase 1 PR 1.3): the REAL chrome and the REAL /jukebox
 * page (jukebox/JukeboxPage.tsx) against a MOCKED backend — no network, no
 * SpotFX process, nothing a press here can reach. Built into harness-dist
 * with the other harness pages and served by a plain static server (never
 * the vite dev server, whose proxy would forward an unmocked request to the
 * live app on :8000). `scripts/render_jukebox_page.py` renders it at
 * 1400×876, 876×1400 and 412×891 into docs/evidence/jukebox-page/.
 *
 * Query flags:
 *   ?state=running  (default) a night on the set's 3rd song, Auto every
 *                   other, a song sent to Spotify and two waiting, and the
 *                   Spotify sign-in 9 days from running out.
 *   ?state=idle     the SHIPPED state: no set playlist, no night, a sign-in
 *                   whose date was never recorded.
 *   ?state=manual   no night; slots placed by hand after three songs.
 *
 * The mock's own little projection exists only to give the page plausible
 * `lap_items`; the real one is services/jukebox/program.py. A config PUT
 * merges in memory, so the editor can be clicked through. The Credits tab's
 * field table, presets and price checks are a SNAPSHOT of the real server's
 * answers (jukeboxShowSnapshot.json, written by `show.fields()` /
 * `show.presets()` / `show.price_check()`); regenerate it if those change.
 * The Simulate tab's night is a snapshot too (jukeboxSimSnapshot.json, the
 * real `POST /api/jukebox/simulate` answer for 20 guests under the shipped
 * settings, seed 1) — tests/test_jukebox_simulator.py holds it to the
 * server's own answer. The Live tab's report is a snapshot too
 * (jukeboxReportSnapshot.json — a three-guest night's report, held to
 * services/jukebox/night_report.py by tests/test_jukebox_report.py). */
import '../src/styles/tokens.css';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import AppChrome, { showsSongStrip } from '../src/components/AppChrome';
import JukeboxPage from '../src/jukebox/JukeboxPage';
import { ToastProvider } from '../src/components/Toast';
import SNAP from './jukeboxShowSnapshot.json';
import SIM from './jukeboxSimSnapshot.json';
import REPORT from './jukeboxReportSnapshot.json';
import type {
  JukeboxPreview, JukeboxStatus, ManualSlot, ProgramConfig, ProgramItem, SetItem,
} from '../src/jukebox/types';

const params = new URLSearchParams(window.location.search);
const STATE = params.get('state') ?? 'running';
const IDLE = STATE === 'idle';
const MANUAL = STATE === 'manual';
const RUNNING = !IDLE && !MANUAL;
const NOW = Date.now();
const MIN = 60_000;
const DAY = 86_400_000;
const PLAYLIST = 'spotify:playlist:37i9dQZF1DXjukeboxHarness';

const SONGS: [string, string, number][] = [
  ['Mr. Brightside', 'The Killers', 222], ['Dancing Queen', 'ABBA', 231],
  ['September', 'Earth, Wind & Fire', 215], ['Uptown Funk', 'Mark Ronson, Bruno Mars', 270],
  ['Superstition', 'Stevie Wonder', 266], ['Shut Up and Dance', 'WALK THE MOON', 199],
  ['Don\'t Stop Me Now', 'Queen', 209], ['Valerie', 'Mark Ronson, Amy Winehouse', 219],
  ['Hey Ya!', 'Outkast', 235], ['I Wanna Dance with Somebody', 'Whitney Houston', 291],
  ['Le Freak', 'CHIC', 330], ['Pompeii', 'Bastille', 214], ['Levitating', 'Dua Lipa', 203],
  ['Get Lucky', 'Daft Punk, Pharrell Williams, Nile Rodgers', 369],
];
const t = (n: number) => `spotify:track:jukeboxharness${String(n).padStart(6, '0')}`;
const SET: SetItem[] = SONGS.map(([title, artist, s], i) => ({ uri: t(i), title, artist, duration_ms: s * 1000 }));

let config: ProgramConfig = {
  playlist: IDLE ? '' : PLAYLIST,
  mode: MANUAL ? 'manual' : 'auto',
  every: 1, run: 1,
  manual: MANUAL ? [{ after_uri: t(1), count: 2 }, { after_uri: t(4), count: 1 }, { after_uri: t(8), count: 3 }] : [],
  run_out: 'again', commit_lead_s: 45,
};

function gapAfter(i: number, since: number): [number, number] {
  if (config.mode === 'jukebox_first') return [0, 0];
  if (config.mode === 'manual') return [config.manual.find((m) => m.after_uri === SET[i].uri)?.count ?? 0, 0];
  const s = since + 1;
  return s >= config.every ? [config.run, 0] : [0, s];
}

function lapItems(): ProgramItem[] {
  const out: ProgramItem[] = [];
  let since = 0;
  SET.forEach((it, i) => {
    out.push({ kind: 'set', uri: it.uri, title: it.title, artist: it.artist, duration_ms: it.duration_ms,
               set_index: i, entry_id: '', committed: false, starts_in_ms: null });
    const [gap, s] = gapAfter(i, since);
    since = s;
    for (let k = 0; k < gap; k++) {
      out.push({ kind: 'open', uri: '', title: '', artist: '', duration_ms: 0, set_index: null,
                 entry_id: '', committed: false, starts_in_ms: null });
    }
  });
  return out;
}

function manualEquivalent(): ManualSlot[] {
  const out: ManualSlot[] = [];
  let since = 0;
  SET.forEach((it, i) => {
    const [gap, s] = config.mode === 'jukebox_first' ? [1, 0] : gapAfter(i, since);
    since = s;
    if (gap > 0) out.push({ after_uri: it.uri, count: Math.min(gap, 3) });
  });
  return out;
}

let show = {
  preset: RUNNING ? 'medium' : null,
  approve_new_phones: false,
  economy: Object.fromEntries(SNAP.fields.map((f: { key: string; default: number | boolean }) => [f.key, f.default])),
  ...Object.fromEntries(SNAP.guest_fields.map((f: { key: string; default: string | number | boolean }) => [f.key, f.default])),
};

// tonight's phones (the Guests tab): one waiting for approval, one blocked
const PHONES = [
  { id: 'phoneAAAAAAAAAAAAAAAAA', name: 'Disco Ana', joined: true, created_ms: NOW - 50 * MIN, joined_ms: NOW - 50 * MIN, renames: 1, approved: true, blocked: false, name_locked: false, waiting: 1, played: 2, votes: 9, credits: 7 },
  { id: 'phoneBBBBBBBBBBBBBBBBB', name: 'Lucky Otter', joined: true, created_ms: NOW - 40 * MIN, joined_ms: NOW - 39 * MIN, renames: 0, approved: true, blocked: false, name_locked: true, waiting: 1, played: 1, votes: 6, jail_left: 2, jail_count: 6, jail_at: 6, jails: 1 },
  { id: 'phoneCCCCCCCCCCCCCCCCC', name: 'Velvet Moose', joined: true, created_ms: NOW - 6 * MIN, joined_ms: NOW - 5 * MIN, renames: 0, approved: false, blocked: false, name_locked: false, waiting: 0, played: 0, votes: 0 },
  { id: 'phoneDDDDDDDDDDDDDDDDD', name: 'Witty Gecko', joined: false, created_ms: NOW - 2 * MIN, joined_ms: null, renames: 0, approved: true, blocked: true, name_locked: false, waiting: 0, played: 0, votes: 1 },
];

const preview = (): JukeboxPreview => {
  if (!config.playlist) return { status: 'refused', reason: 'no_playlist', detail: 'No set playlist is linked — link one first.' };
  const lap = lapItems();
  const slots = lap.filter((x) => x.kind !== 'set').length;
  return {
    status: 'ok', playlist_name: 'Saturday set', playlist_uri: PLAYLIST, set_songs: SET.length,
    set: SET, lap_items: lap, next: [], manual_equivalent: manualEquivalent(),
    playhead: RUNNING ? 2 : null,
    lap: { set_songs: SET.length, slots, unbounded: config.mode === 'jukebox_first', notes: [] },
  };
};

const J = (n: number, title: string, artist: string, s: number, by = 'host', round = 1) => ({
  id: `entry${n}`, uri: `spotify:track:guestharness${String(n).padStart(8, '0')}`, title, artist,
  duration_ms: s * 1000, added_by: by, round,
});

const status = (): JukeboxStatus => {
  const sign = IDLE
    ? { state: 'unknown' as const, warning: 'When SpotFX last signed in to Spotify isn\'t recorded, so its 6-month expiry can\'t be predicted — sign in again before a party to start a known clock.' }
    : RUNNING
      ? { state: 'soon' as const, warning: `SpotFX's Spotify sign-in runs out by ${new Date(NOW + 9 * DAY).toISOString().slice(0, 10)} (9 days left) — sign in again before then.`, days_left: 9 }
      : { state: 'ok' as const, warning: null, days_left: 120 };
  if (!RUNNING) {
    return { night: null, running: false, now: null, next: [], line: [], warnings: sign.warning ? [sign.warning] : [],
             spotify_auth: sign, log: [], history: [] };
  }
  const line = [
    { ...J(1, 'Bad Romance', 'Lady Gaga', 294), state: 'committed' as const, doomed: false, commit_check: 'next' as const },
    { ...J(2, 'Take On Me', 'a-ha', 225, PHONES[0].id), state: 'queued' as const, doomed: false, commit_check: '' as const },
    { ...J(3, 'Murder on the Dancefloor', 'Sophie Ellis-Bextor', 230, PHONES[1].id, 2), state: 'queued' as const, doomed: false, commit_check: '' as const, held: true },
  ];
  let at = 38_000;
  const nextItems: ProgramItem[] = [];
  const push = (it: Omit<ProgramItem, 'starts_in_ms'>) => { nextItems.push({ ...it, starts_in_ms: at }); at += it.duration_ms; };
  push({ kind: 'jukebox', uri: line[0].uri, title: line[0].title, artist: line[0].artist, duration_ms: line[0].duration_ms, set_index: null, entry_id: line[0].id, committed: true });
  for (let i = 3; nextItems.length < 20; i++) {
    const s = SET[i % SET.length];
    push({ kind: 'set', uri: s.uri, title: s.title, artist: s.artist, duration_ms: s.duration_ms, set_index: i % SET.length, entry_id: '', committed: false });
    const fill = line[nextItems.filter((x) => x.kind === 'jukebox').length];
    if (nextItems.length >= 20) break;
    if (fill) push({ kind: 'jukebox', uri: fill.uri, title: fill.title, artist: fill.artist, duration_ms: fill.duration_ms, set_index: null, entry_id: fill.id, committed: false });
    else nextItems.push({ kind: 'open', uri: '', title: '', artist: '', duration_ms: 0, set_index: null, entry_id: '', committed: false, starts_in_ms: at });
  }
  return {
    night: { id: 'harness-night', state: 'running', started_ms: NOW - 52 * MIN, started_by: 'press', ended_ms: null,
             end_reason: '', end_detail: '', playlist_name: 'Saturday set', playlist_uri: PLAYLIST, played: 9, jukebox_played: 4 },
    running: true,
    now: { kind: 'set', uri: SET[2].uri, title: 'September', set_index: 2, entry_id: '', started_ms: NOW - 3 * MIN },
    remaining_ms: 38_000, next: nextItems, line, warnings: sign.warning ? [sign.warning] : [], spotify_auth: sign,
    log: ['20:04:11 night started (press) on Saturday set: 14 set songs, 1 jukebox slot(s) after every 1 set song(s), when the set runs out: again; playing from song 1',
          '20:41:52 sent Bad Romance to Spotify\'s queue (plays after September)'],
    history: [],
  };
};

const STATUS = {
  dark: false,
  bridge: { connected: true, ws_url: 'ws://127.0.0.1:8000/ws', intensity: null, track: null, next_track: null, last_event: null },
  conductor: { active_scene: null, journey: { active_set_id: null, custody: 'room' }, virtuals: [], mechanisms: [], last_leg: null },
  ambient: { intent: 'off', phase: 'off', mode: 'off', groups: [], held: false },
  lighting: { enabled: true, mode: { id: 'm-standard', name: 'Standard' }, source: 'ha', manual: false, phase: 'resting', overrides_display_mode: false },
  light_show: { active: false },
  executor: { recent_writes: [] },
};
const ROOM_CONTROLS = {
  brightness_multiplier: 1, global_transition_ms: 0, ambient_enabled: false, ambient_on_music_pause: false,
  ambient_color: '#ffe392', ambient_color_dark: '#ffe392', ambient_hue_group_ids: [], display_mode: 'dark',
  display_light_bg_color: '#201830', display_light_bg_brightness: 0.3, background_fade_s: 1,
  scene_change_mode: 'full', force_scene_enabled: false, force_scene_scene_id: null,
  force_color_enabled: false, force_color_target_id: null, music_device_allowlist: ['Serenity', 'Serenity guest'],
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json' },
});

window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(typeof input === 'string' ? input : (input as Request).url ?? input);
  const method = (init?.method ?? 'GET').toUpperCase();
  const body = init?.body ? JSON.parse(String(init.body)) : undefined;
  if (url.includes('/api/jukebox/config')) {
    if (method === 'PUT') config = { ...config, ...body };
    return json(method === 'PUT' ? { dry_run: false, config } : config);
  }
  if (url.includes('/api/jukebox/status')) return json(status());
  if (url.includes('/api/jukebox/preview')) return json(preview());
  if (url.includes('/api/jukebox/show/preset')) {
    show = { ...show, preset: body?.preset ?? null, approve_new_phones: body?.preset === 'large' };
    return json({ show, fields: SNAP.fields, guest_fields: SNAP.guest_fields, presets: SNAP.presets, config });
  }
  if (url.includes('/api/jukebox/show')) {
    if (method === 'PUT') {
      const { economy, ...rest } = body ?? {};
      show = { ...show, ...rest, economy: { ...show.economy, ...(economy ?? {}) } };
    }
    return json({ show, fields: SNAP.fields, guest_fields: SNAP.guest_fields, presets: SNAP.presets });
  }
  if (url.includes('/api/jukebox/bonus-codes')) return json({ codes: [], unused: 0, used: 0 });
  if (url.includes('/api/jukebox/economy')) {
    return json(RUNNING ? {
      running: true, play_mode: 'credits', crowd: 4, joined: 3, jailed: 1, votes: 41, time_outs: 1,
      credits: { minted: 112, held: 38, held_per_guest: 12.7, unspent_share: 0.339, by_kind: {}, adds: 5,
                 skips_hr: 0.8, nexts_hr: null, tips_hr: 2.4, add_price_median: 5, votes: 41, free: 32 },
      prices: { add_first: 4, add_back: 9, back_wait_min: 31.6, skip_now: 21, next_from: 11, jail_fee: 10 },
      events: [
        { at_ms: NOW - 2 * MIN, kind: 'tip', who: 'Velvet Moose', what: 'tipped Disco Ana 2 on “Take On Me” (+2 bonus)', credits: -2 },
        { at_ms: NOW - 9 * MIN, kind: 'add', who: 'Lucky Otter', what: 'added “Murder on the Dancefloor”', credits: -6 },
        { at_ms: NOW - 14 * MIN, kind: 'host_gift', who: 'the host', what: 'gave 3 guests 2 each', credits: 2, phones: 3 },
        { at_ms: NOW - 20 * MIN, kind: 'skip', who: 'Disco Ana', what: 'skipped “Rasputin”', credits: -16 },
      ],
    } : { running: false, play_mode: 'credits' });
  }
  if (url.includes('/api/jukebox/guests')) {
    return json(RUNNING ? { running: true, phones: PHONES, pending: 1, jailed: 1, crowd: 4 } : { running: false, phones: [] });
  }
  if (url.includes('/api/jukebox/line/')) return json({ status: 'refused', reason: 'harness', detail: 'This is the mocked harness — nothing changed.' });
  if (url.includes('/api/jukebox/price-check')) {
    const g = new URL(url, 'http://x').searchParams.get('guests') ?? '15';
    return json((SNAP.price_check as Record<string, unknown>)[g] ?? SNAP.price_check['15']);
  }
  if (url.includes('/api/jukebox/simulate')) return json(SIM);
  if (url.includes('/api/jukebox/report')) return json(REPORT);
  if (url.includes('/api/jukebox/set/move')) return json({ status: 'refused', reason: 'harness', detail: 'This is the mocked harness — nothing was moved.' });
  if (/\/api\/engine\/status/.test(url)) return json(STATUS);
  if (/\/api\/room-controls/.test(url)) return json(ROOM_CONTROLS);
  if (/\/api\/ownership/.test(url)) return json({ owner: 'spectra', activation: null, dark_fixtures: null, hue_stream_refusals: {} });
  if (/\/api\/liveness/.test(url)) return json({ healthy: true });
  if (/\/api\/upcoming/.test(url)) return json({ uri: null, effective_mode: 'analysed', has_authored: false, events: [] });
  if (/\/api\/scenes/.test(url)) return json([]);
  if (/\/api\/color-sets/.test(url)) return json([]);
  if (/\/light-show\/arms/.test(url)) return json({ armed: [], song: { position_ms: null } });
  if (/\/light-show\/sequence-run/.test(url)) return json({ run: null });
  if (/\/light-show\/sequences\/recent/.test(url)) return json({ recent: [] });
  if (/\/light-show\/sequences/.test(url)) return json({ sequences: [] });
  if (/\/light-show\/sets/.test(url)) return json({ sets: [] });
  if (/\/device-preview\/favorites/.test(url)) return json({ effective_virtual_ids: [], virtual_ids: [] });
  if (/\/device-preview\/status/.test(url)) return json({ connected: false, paused: false, source: 'none', viewers: 0 });
  if (/\/device-preview\/layout/.test(url)) return json({ virtuals: [], width: 100, height: 50 });
  if (/\/intensity-scale\/mark/.test(url)) return json({ uri: null, mark: null, auto_factor: 1, effective_factor: 1, manual_min: 0, manual_max: 2 });
  if (/\/api\/registry/.test(url)) return json({ categories: {} });
  if (/\/api\/gradients2d/.test(url)) return json({});
  return json({});
}) as typeof fetch;

class FakeSocket {
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  constructor() { setTimeout(() => this.onopen?.(), 0); }
  close() {}
  send() {}
}
(window as unknown as { WebSocket: unknown }).WebSocket = FakeSocket;

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider>
      <MemoryRouter initialEntries={['/jukebox']}>
        <AppChrome showSongStrip={showsSongStrip('/jukebox')}>
          <main><JukeboxPage /></main>
        </AppChrome>
      </MemoryRouter>
    </ToastProvider>
  </QueryClientProvider>,
);
