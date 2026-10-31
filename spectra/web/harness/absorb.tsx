/** ABSORB MUSIC HARNESS (2026-10-21): the REAL chrome and the REAL
 * /absorb page (absorb/AbsorbPage.tsx) against a MOCKED backend — no
 * network, no SpotFX process, nothing a press here can reach. Built into
 * harness-dist with the other harness pages and served by a plain static
 * server (never the vite dev server, whose proxy would forward an unmocked
 * request to the live app on :8000). `scripts/render_absorb_page.py`
 * screenshots it at 1440 / 1180 / 390 into docs/evidence/absorb-page/.
 *
 * Query flags:
 *   ?state=running  (default) a window mid-evening: capturing song 14 of
 *                   203, the counts, a head rate, the silence proven, the
 *                   lights standing down, parked and realigned songs.
 *   ?state=idle     the SHIPPED state: no playlist linked, the schedule
 *                   off with no window, nothing ever run.
 *   ?state=paused   his music took over: Absorb stepped aside, the house
 *                   volume given back, waiting for 20 minutes of quiet.
 *
 * The mock answers PUT/POST too (a config edit merges, Start/Stop/Skip
 * answer a status), in memory only, so the page can be clicked through. */
import '../src/styles/tokens.css';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import AppChrome, { showsSongStrip } from '../src/components/AppChrome';
import AbsorbPage from '../src/absorb/AbsorbPage';
import { ToastProvider } from '../src/components/Toast';
import type {
  AbsorbBrief, AbsorbConfig, AbsorbParkedSong, AbsorbPreview, AbsorbRun, AbsorbRunSummary,
  AbsorbSchedule,
} from '../src/absorb/types';

const params = new URLSearchParams(window.location.search);
const STATE = params.get('state') ?? 'running';
const IDLE = STATE === 'idle';
const PAUSED = STATE === 'paused';

const NOW = Date.now();
const MIN = 60_000;
const t = (n: number) => `spotify:track:harness${String(n).padStart(4, '0')}`;
const PLAYLIST = 'spotify:playlist:37i9dQZF1DXabsorbHarness';

let config: AbsorbConfig = {
  enabled: !IDLE,
  source_playlist_uri: IDLE ? '' : PLAYLIST,
  captured_playlist_name: 'Recently Captured',
  force_recapture: false,
  head_max_ms: 1000,
  order: 'fresh_first',
  warm_up: true,
  windows: IDLE ? [] : [
    { days: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'], start: '21:30', end: '00:30' },
    { days: ['sat', 'sun'], start: '13:00', end: '16:00' },
  ],
  max_attempts: 3,
  play_window_size: 10,
  overrun_grace_min: 5,
  recently_captured_max: 200,
  recently_captured_includes_skipped: true,
  resume_after_quiet_min: 20,
  min_remaining_min: 20,
  max_resumes_per_window: 3,
  run_while_sleeping: true,
  use_capture_lane: !IDLE,
  silence_recheck_s: 60,
};

const counts = { captured: 11, failed: 4, requeued: 3, skipped: 344, parked: 1, head_missed: 2 };
const opened = NOW - 72 * MIN;

const run: AbsorbRun | null = IDLE ? null : {
  id: 'harness-run', state: PAUSED ? 'paused' : 'running',
  started_ms: opened - 20_000, ended_ms: 0, end_reason: '', end_detail: '',
  window: { start: opened - 20_000, end: NOW + 108 * MIN, scheduled_start: opened - 20_000, label: 'Tue 21:30–00:30' },
  started_by: 'schedule',
  pre_window: {
    snap_volume: 34, via: 'spectra',
    capture: { id: 'effects-host', name: 'Effects Host', percent: 100, muted: false, group_muted: false },
    muted: [],
  },
  queue: Array.from({ length: 189 }, (_, i) => t(100 + i)),
  now_playing: PAUSED ? null : {
    uri: t(14), title: 'Noah Kahan — Stick Season', started_ms: NOW - 95_000, attempt: 1, mode: 'recapture',
  },
  captured: [], failed: [], parked: [], skipped: [],
  counts,
  head_rate: { attempted: 13, with_head: 11, by_mode: { fresh: { attempted: 5, with_head: 5 }, recapture: { attempted: 8, with_head: 6 } } },
  realigned: [
    { uri: t(7), title: 'Bad Bunny — DtMF', status: 'applied', shift_ms: 240, r: 0.92, triggers: 6, at_ms: NOW - 31 * MIN },
    { uri: t(9), title: 'Rosalía — Malamente', status: 'applied', shift_ms: -118, r: 0.88, triggers: 14, at_ms: NOW - 12 * MIN },
    { uri: t(10), title: 'A song with no triggers', status: 'applied', shift_ms: 60, r: 0.9, triggers: 0, at_ms: NOW - 10 * MIN },
  ],
  sleeping_at_open: false,
  silence_checks: [
    { at_ms: NOW - 2 * MIN, ok: true, detail: 'silent' },
    { at_ms: NOW - 1 * MIN, ok: true, detail: 'silent' },
  ],
  yields: PAUSED ? [{ at_ms: NOW - 6 * MIN, foreign_uri: t(900), restored_ms: NOW - 6 * MIN + 2000 }] : [],
  resumes: PAUSED ? 1 : 0,
  log: [],
  opened_ms: opened,
  wait_reason: PAUSED ? 'foreign_playback' : '',
  wait_detail: PAUSED ? 'Other music started playing, so Absorb stepped aside.' : '',
  silent: !PAUSED,
  lights_held: !PAUSED,
  restore: PAUSED ? { at_ms: NOW - 6 * MIN + 2000, ok: true, detail: 'restored', why: 'yield' } : {},
  restore_pending: '',
  source_playlist_uri: PLAYLIST,
  source_playlist_name: 'Absorb — the backlog',
  stage: PAUSED ? 'yielded' : 'capturing',
};

const brief = (): AbsorbBrief => (run == null ? { state: 'idle' } : {
  state: run.state, stage: run.stage, run_id: run.id, started_ms: run.started_ms,
  ended_ms: run.ended_ms, end_reason: run.end_reason, end_detail: run.end_detail,
  started_by: run.started_by, source_playlist_uri: run.source_playlist_uri,
  source_playlist_name: run.source_playlist_name, now_playing: run.now_playing,
  queue_len: run.queue.length, counts: run.counts,
  head_rate: { attempted: run.head_rate.attempted, with_head: run.head_rate.with_head },
  lights_held: run.lights_held, silent: run.silent, restore_pending: run.restore_pending,
  sleeping_at_open: run.sleeping_at_open, yields: run.yields.length, resumes: run.resumes,
  window: run.window, opened_ms: run.opened_ms, wait_reason: run.wait_reason, wait_detail: run.wait_detail,
});

const earlier: AbsorbRunSummary[] = IDLE ? [] : [
  {
    id: 'harness-prev', state: 'ended', started_ms: NOW - 24 * 60 * MIN, ended_ms: NOW - 21 * 60 * MIN,
    end_reason: 'window_closed', end_detail: 'The window\'s time was up.', started_by: 'schedule',
    window: { label: 'Mon 21:30–00:30' }, opened_ms: NOW - 24 * 60 * MIN,
    source_playlist_uri: PLAYLIST, source_playlist_name: 'Absorb — the backlog',
    counts: { captured: 38, failed: 9, requeued: 7, skipped: 0, parked: 2, head_missed: 3 },
    head_rate: { attempted: 41, with_head: 38 }, parked: [], realigned: [
      { uri: t(3), title: 'Soy Peor — Bad Bunny', status: 'applied', shift_ms: 512, r: 0.81, triggers: 29, at_ms: NOW - 22 * 60 * MIN },
    ],
  },
  {
    id: 'harness-refused', state: 'refused', started_ms: NOW - 48 * 60 * MIN, ended_ms: NOW - 48 * 60 * MIN,
    end_reason: 'anchor_disabled', end_detail: 'Anchor detection is switched off (settings.anchor_enabled), and every re-capture would roll back without it.',
    started_by: 'press', window: {}, opened_ms: 0, source_playlist_uri: PLAYLIST, source_playlist_name: '',
    counts: { captured: 0, failed: 0, requeued: 0, skipped: 0, parked: 0, head_missed: 0 },
    head_rate: { attempted: 0, with_head: 0 }, parked: [], realigned: [],
  },
];

const preview = (): AbsorbPreview => (!config.source_playlist_uri ? { linked: false, detail: 'No playlist is linked — link one first.' } : {
  linked: true, resolved: true,
  playlist: { id: '37i9dQZF1DXabsorbHarness', name: 'Absorb — the backlog' },
  counts: config.force_recapture
    ? { total: 1767, skip: 0, fresh: 603, recapture: 1161, parked: 3 }
    : { total: 1767, skip: 344, fresh: 603, recapture: 817, parked: 3 },
  reasons: config.force_recapture
    ? { no_shape: 603, force_recapture: 1161 }
    : { no_shape: 603, headless: 706, no_librosa: 92, needs_recapture: 11, renders_nothing: 8 },
  force_recapture: config.force_recapture, head_max_ms: 1000,
});

const parked: AbsorbParkedSong[] = IDLE ? [] : [
  { uri: t(41), title: 'Fleetwood Mac — Dreams', reason: 'head_unreachable', parked_ms: NOW - 40 * MIN, lifetime_attempts: 3, last_failure: 'head_missed', last_attempt_ms: NOW - 40 * MIN },
  { uri: t(52), title: 'Daft Punk — Contact', reason: 'gap', parked_ms: NOW - 23 * 60 * MIN, lifetime_attempts: 4, last_failure: 'gap', last_attempt_ms: NOW - 23 * 60 * MIN },
  { uri: t(63), title: '', reason: 'too_short', parked_ms: NOW - 22 * 60 * MIN, lifetime_attempts: 3, last_failure: 'too_short', last_attempt_ms: NOW - 22 * 60 * MIN },
];

const schedule = (): AbsorbSchedule => ({
  enabled: config.enabled, active: config.enabled && config.windows.length > 0,
  house_tz: 'America/New_York',
  windows: config.windows.map((w, i) => ({ ...w, index: i, label: `${w.start}–${w.end}` })),
  open_now: run && !IDLE ? [{ start_ms: opened, end_ms: NOW + 108 * MIN, label: 'Tue 21:30–00:30', window_index: 0, fired: true }] : [],
  next: config.enabled && config.windows.length
    ? { start_ms: NOW + 22 * 60 * MIN, end_ms: NOW + 25 * 60 * MIN, label: 'Wed 21:30–00:30', window_index: 0, in_s: 22 * 3600 + 40 * 60 }
    : null,
  overrun_grace_min: 5,
  outcomes: IDLE ? [] : [
    { occurrence_start_ms: opened, occurrence_end_ms: NOW + 108 * MIN, label: 'Tue 21:30–00:30', at_ms: opened, outcome: 'opened', reason: '', detail: '', run_id: 'harness-run', run: { state: 'running', opened_ms: opened, counts, head_rate: { attempted: 13, with_head: 11 } } },
    { occurrence_start_ms: NOW - 24 * 60 * MIN, occurrence_end_ms: NOW - 21 * 60 * MIN, label: 'Mon 21:30–00:30', at_ms: NOW - 24 * 60 * MIN, outcome: 'opened', reason: '', detail: '', run_id: 'harness-prev', run: { state: 'ended', end_detail: 'The window\'s time was up.', opened_ms: NOW - 24 * 60 * MIN, counts: earlier[0]?.counts, head_rate: { attempted: 41, with_head: 38 } } },
    { occurrence_start_ms: NOW - 48 * 60 * MIN, occurrence_end_ms: NOW - 45 * 60 * MIN, label: 'Sun 21:30–00:30', at_ms: NOW - 48 * 60 * MIN, outcome: 'refused', reason: 'device_unreachable', detail: 'Serenity isn\'t available as a Spotify Connect device.', run_id: '', run: null },
  ],
});

/** A quiet chrome: nothing playing, nothing armed (the fidelity harness's
 * own empty state, trimmed to what the bar and the strip read). */
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
  status, headers: { 'Content-Type': 'application/json' },
});

window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(typeof input === 'string' ? input : (input as Request).url ?? input);
  const method = (init?.method ?? 'GET').toUpperCase();
  const body = init?.body ? JSON.parse(String(init.body)) : undefined;
  if (url.includes('/api/absorb/config')) {
    if (method === 'PUT') config = { ...config, ...body };
    return json(config);
  }
  if (url.includes('/api/absorb/run')) return json({ brief: brief(), run, earlier });
  if (url.includes('/api/absorb/preview')) return json(preview());
  if (url.includes('/api/absorb/schedule')) return json(schedule());
  if (url.includes('/api/absorb/parked')) return json({ parked });
  // the backlog on the hidden player (phase 4): switched on with a window
  // open, so it rests and says why; off when idle
  if (url.includes('/api/absorb/lane')) {
    return json(!IDLE
      ? { enabled: true, state: 'resting', reason: 'An Absorb window is open; it captures the playlist itself.',
          job: null, log: [], failed: [], passed_over: [],
          learned: [{ uri: 'spotify:track:a', title: 'ABBA — Dancing Queen', at_ms: 1 },
                    { uri: 'spotify:track:b', title: 'Queen — Don\'t Stop Me Now', at_ms: 2 }] }
      : { enabled: false, state: 'off', reason: 'Off: the hidden player only learns songs during a Jukebox night.',
          job: null, learned: [], failed: [], passed_over: [], log: [] });
  }
  if (url.includes('/api/absorb/retry')) return json({ uri: body?.uri, unparked: true });
  if (url.includes('/api/absorb/start')) return json({ status: 'refused', reason: 'harness', detail: 'This is the mocked harness — nothing was started.', run: brief() });
  if (url.includes('/api/absorb/stop')) return json({ status: 'ended', run: brief() });
  if (url.includes('/api/absorb/skip-song')) return json({ status: 'skipped', run: brief() });
  if (url.includes('/api/spotify/contexts')) {
    return json({ playing: null, recent: [
      { context_uri: 'spotify:playlist:wilkins0000000000', type: 'playlist', name: 'Wilkins' },
      { context_uri: 'spotify:album:notaplaylist00000', type: 'album', name: 'An album (not offered)' },
      { context_uri: PLAYLIST, type: 'playlist', name: 'Absorb — the backlog' },
      { context_uri: 'spotify:playlist:chill00000000000', type: 'playlist', name: 'Chill' },
    ] });
  }
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
// The page's Start / force-recapture confirms: answer "yes" so a click in
// the harness reaches the (mocked) route.
window.confirm = () => true;

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider>
      <MemoryRouter initialEntries={['/absorb']}>
        <AppChrome showSongStrip={showsSongStrip('/absorb')}>
          <main><AbsorbPage /></main>
        </AppChrome>
      </MemoryRouter>
    </ToastProvider>
  </QueryClientProvider>,
);
