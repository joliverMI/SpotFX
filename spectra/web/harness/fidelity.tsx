/** DESIGN-FIDELITY HARNESS (2026-10-14): mounts the REAL chrome — the
 * grouped menu, the global song timeline, the one consolidated bar — plus
 * the REAL Home page, against a MOCKED backend. No network, no SPECTRA
 * process, zero live-room risk, and the same canned song the approved
 * artifact's own mockups animate (MR. OCTOBER, the analysed plan read off
 * his live app at 13:07 on 2026-10-14), so a screenshot of this page is
 * directly comparable with a screenshot of the mockup frame beside it.
 *
 * `scripts/check_ui_fidelity.py` drives it: it serves `harness-dist`,
 * renders the mockup frames and these pages at the same widths, writes
 * the side-by-side pairs, and asserts the measurable parts.
 *
 * Query flags:
 *   ?nothing=1   nothing playing / nothing armed — the EMPTY STATE the
 *                live app used to unmount entirely (audit T1/B7/N2), and
 *                the state the Admiral actually reviewed the deploy in.
 *   ?kiosk=1     the kiosk's own chrome (no menu), via the real
 *                KioskPage.
 *   ?view=home     the Home page under the chrome (the default).
 *   ?view=settings the Settings page under the chrome.
 *   ?view=bar      chrome only, no page body (an ordinary page's route).
 *   ?view=timeline the Timeline page's own route, chrome only.
 *
 * Each view declares the ROUTE it stands for and asks the app's own
 * `showsSongStrip(pathname)` whether the global timeline is drawn there
 * — never its own idea of it. That is the bug this flag exists to make
 * impossible: the harness used to render the strip on every view, so the
 * Home pair image showed a row the real app has never drawn there. */
import '../src/styles/tokens.css';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import AppChrome, { showsSongStrip } from '../src/components/AppChrome';
import HomePage from '../src/home/HomePage';
import SettingsConsolePage from '../src/settings/SettingsConsolePage';
import KioskPage from '../src/kiosk/KioskPage';
import { ToastProvider } from '../src/components/Toast';

const params = new URLSearchParams(window.location.search);
const EMPTY = params.get('nothing') === '1';
const KIOSK = params.get('kiosk') === '1';
const VIEW = params.get('view') ?? 'home';

const DURATION_MS = 189_258;
const START_MS = 40_000;
const URI = 'spotify:track:fidelity';

/* The approved artifact's own SONG data, verbatim from its `SONG`/
 * `SCENES`/`FLARES`/`DROPSEQ`/`CUES` tables. */
const SCENES: [number, number][] = [
  [20549, 1], [47821, 7], [69021, 15], [79981, 14], [91869, 6],
  [106858, 3], [127512, 11], [145205, 8], [169726, 2],
];
const SCENE_ENERGY = [0.925, 1, 0.913, 0.881, 0.539, 0.836, 0.747, 0.867, 0.4];
const FLARES: [number, number][] = [
  [30928, 9], [55089, 12], [101169, 5], [138936, 13], [160449, 10], [176703, 4],
];
const DROPSEQ = { charge: 49764, lull: 60306, drop: 61990, num: 1 };
const CUES = { high: 20549, low: 169726 };
const BEAT = 708.215;

const EVENTS = [
  ...SCENES.map(([ms, rank]) => ({ ms, kind: 'scene', rank, rank_of: 15, source: 'planned' })),
  ...FLARES.map(([ms, rank]) => ({ ms, kind: 'flare', rank, rank_of: 15, source: 'analysed' })),
  { ms: DROPSEQ.charge, kind: 'charge', rank: null, rank_of: null, source: 'drop_sequence', num: 1 },
  { ms: DROPSEQ.lull, kind: 'lull', rank: null, rank_of: null, source: 'drop_sequence', num: 1 },
  { ms: DROPSEQ.drop, kind: 'drop', rank: null, rank_of: null, source: 'drop_sequence', num: 1 },
  { ms: CUES.high, kind: 'high', rank: null, rank_of: null, source: 'show_cue' },
  { ms: CUES.low, kind: 'low', rank: null, rank_of: null, source: 'show_cue' },
].sort((a, b) => a.ms - b.ms);

const TRACK = EMPTY ? null : {
  uri: URI, title: 'MR. OCTOBER', artist: 'Bad Bunny',
  duration_ms: DURATION_MS, is_playing: true,
  position_ms: START_MS, show_clock_ms: START_MS,
};

const SECTIONS = (() => {
  const bounds = [0, ...SCENES.map(([ms]) => ms), DURATION_MS];
  const lv = [0.45, ...SCENE_ENERGY];
  return bounds.slice(0, -1).map((start, i) => ({
    start_ms: start, end_ms: bounds[i + 1], label: `s${i}`,
    energy_rms: lv[i] ?? 0.5, onset_density_per_s: 2,
  }));
})();

/** The song's ENERGY timeline as GET /api/energy/timeline serves it
 * (spectra/services/energy.py): each section on the song's own 0..1 scale,
 * x 0.8 (an unmarked song at a 100% scale), capped at 0.75. */
const ENERGY = (() => {
  const raws = SECTIONS.map((sec) => sec.energy_rms);
  const lo = Math.min(...raws);
  const hi = Math.max(...raws);
  return {
    uri: URI, status: 'ok', factor: 1, marked: false, headroom: 0.8, cap: 0.75,
    capture_offset_ms: 0, look_ahead_ms: 2000,
    sections: SECTIONS.map((sec) => {
      const n = hi > lo ? (sec.energy_rms - lo) / (hi - lo) : 1;
      return { start_ms: sec.start_ms, end_ms: sec.end_ms, raw: sec.energy_rms,
               normalized: n, energy: Math.min(0.75, n * 0.8) };
    }),
  };
})();

const BEATS = (() => {
  const out: { ms: number; downbeat?: boolean }[] = [];
  for (let b = 0; b < DURATION_MS; b += BEAT) {
    out.push({ ms: Math.round(b), downbeat: Math.round(b / BEAT) % 4 === 0 });
  }
  return out;
})();

/** A synthetic but realistically shaped RMS trace — the mockup's own
 * `bands` generator (kick decay per beat, a break between the lull and
 * the drop, per-section level), so the shape under Home's canvas reads
 * like the drawing rather than a flat line. */
const SHAPE = (() => {
  const BIN = 50;
  const n = Math.ceil(DURATION_MS / BIN);
  const timestamps: number[] = [], total: number[] = [], low: number[] = [],
    mid: number[] = [], high: number[] = [];
  let seed = 7;
  const rnd = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };
  const bounds = [0, ...SCENES.map(([ms]) => ms), DURATION_MS];
  const lv = [0.45, ...SCENE_ENERGY];
  for (let i = 0; i < n; i += 1) {
    const ms = i * BIN;
    let sec = 0;
    while (sec < bounds.length - 2 && ms >= bounds[sec + 1]) sec += 1;
    const L = Math.max(0.2, lv[sec] ?? 0.5);
    const ph = (ms % BEAT) / BEAT;
    const kick = Math.exp(-ph * 7);
    const brk = ms > DROPSEQ.lull && ms < DROPSEQ.drop ? 0.25 : 1;
    const b = Math.min(1, (0.15 + 0.85 * kick) * L * brk * (0.8 + 0.4 * rnd()));
    const m = Math.min(1, (0.3 + 0.3 * Math.exp(-((ph + 0.5) % 1) * 6)) * L * brk * (0.7 + 0.5 * rnd()));
    const h = Math.min(1, 0.25 * L * brk * (0.4 + 0.9 * rnd()));
    timestamps.push(ms); low.push(b); mid.push(m); high.push(h);
    total.push(Math.min(1, 0.55 * b + 0.35 * m + 0.25 * h + 0.05));
  }
  return {
    timestamps_ms: timestamps, rms_total: total, rms_low: low, rms_mid: mid, rms_high: high,
    marks: [], captured_ms: DURATION_MS,
  };
})();

const SETS = [
  { id: 'set-mode', name: 'Show Mode', actions: [] },
  { id: 'set-drop', name: 'Show Drop', actions: [] },
  { id: 'set-pause', name: 'Pause Show', actions: [] },
  { id: 'set-heavy', name: 'Heavy Calm', actions: [] },
  { id: 'set-easy', name: 'Easy Calm', actions: [] },
];
const SEQUENCES = [
  { id: 'seq-start', name: 'Standard Start Test', items: [{}, {}, {}, {}, {}], loop: false },
  { id: 'seq-party', name: 'Party Ramp', items: [{}, {}, {}, {}, {}, {}, {}], loop: false },
];

const ARMS = EMPTY ? { armed: [], song: { position_ms: null } } : {
  armed: [
    { id: 'arm-1', set_id: 'set-easy', set_name: 'Easy Calm', label: 'Easy Calm',
      on: 'scene_change', due_ms: 47821, state: 'armed' },
    { id: 'arm-2', set_id: 'set-heavy', set_name: 'Heavy Calm', label: 'Heavy Calm',
      on: 'low', due_ms: 169726, state: 'armed' },
  ],
  song: { position_ms: START_MS, expected_scene_change_s: 7.8, expected_scene_change_is_floor: true },
};

const STATUS = {
  dark: false,
  bridge: {
    connected: true, ws_url: 'ws://127.0.0.1:8000/ws',
    intensity: EMPTY ? null : 0.62,
    track: TRACK,
    // "Up next" (approved idea 7) — the mockup's own
    // `title="Up next: Bad Bunny — CYBERTRUCK"`.
    next_track: EMPTY ? null : { uri: 'spotify:track:next', title: 'CYBERTRUCK' },
    last_event: null,
  },
  conductor: {
    active_scene: EMPTY ? null : { id: 'sc-orbits', name: 'Orbits V2' },
    journey: { active_set_id: EMPTY ? null : 'cs-blackhole-cyan', custody: 'room' },
    virtuals: [], mechanisms: [], last_leg: null,
  },
  ambient: { intent: 'off', phase: 'off', mode: 'off', groups: [], held: false },
  lighting: {
    enabled: true, mode: { id: 'm-standard', name: 'Standard' }, source: 'ha',
    manual: false, phase: EMPTY ? 'resting' : 'music', overrides_display_mode: false,
  },
  light_show: EMPTY ? { active: false } : {
    active: true, armed: 2, running_sets: 0, holds: 9, levels: 0,
    pulse_mods: 0, flare_blocks: 0, changed_settings: 6,
  },
  executor: { recent_writes: [] },
};

const ROOM_CONTROLS = {
  brightness_multiplier: 1, global_transition_ms: 0,
  ambient_enabled: false, ambient_on_music_pause: false,
  ambient_color: '#ffe392', ambient_color_dark: '#ffe392', ambient_hue_group_ids: [],
  display_mode: 'dark', display_light_bg_color: '#201830', display_light_bg_brightness: 0.3,
  background_fade_s: 1, scene_change_mode: 'full',
  force_scene_enabled: false, force_scene_scene_id: null,
  force_color_enabled: false, force_color_target_id: null,
  scene_transition_ms_gentle: 300, scene_transition_ms_hard: 200,
  lull_dark_max_s: 3, lull_breath_hold_s: 0.4, strip_phase_strength: 1,
  drop_timing_offset_ms: -400, drop_shock_enabled: true, drop_shock_min_energy: 0.7,
  pulse_flash_min_energy: 0.8, drop_switch_enabled: true,
  drop_switch_after_previous_drop: 1, drop_switch_stale_margin_s: 8,
  drop_switch_drops_in_a_row: 2, drop_switch_hit_threshold: 0.5,
  drop_switch_swallow_delay_s: 1.2, transition_programs_enabled: true,
  transition_program_ms: 1400, midsong_snap_to_beat: true,
  transition_window_beats: 8, transition_edge_sensitivity: 0.5,
  transitions_per_minute: 8, scene_changes_per_minute: 0,
  rainbow_select_limit: 0.9, active_gradient_id: null,
  gradient_x_period_s: 300, gradient_y_slew_s: 20,
  music_device_allowlist: ['Serenity', 'Serenity guest'],
  av_sync_lead_ms: null, known_buffer_floor_ms: 500,
};

const COLOR_SETS = [
  {
    id: 'cs-blackhole-cyan', name: 'Black Hole - Cyan', kind: 'set', color: '#22d3ee',
    entries: [{ color_value: 'linear-gradient(90deg, #22d3ee, #0ea5e9 45%, #1e3a8a)' }],
  },
  { id: 'cs-hype-3', name: 'Hype 3', kind: 'set', color: '#ec4899', entries: [{ color_value: '#ec4899' }] },
];

const JSON_BY_URL: [RegExp, unknown][] = [
  [/\/api\/engine\/status/, STATUS],
  [/\/api\/upcoming/, { uri: URI, effective_mode: 'analysed', has_authored: false, events: EMPTY ? [] : EVENTS }],
  [/\/api\/room-controls/, ROOM_CONTROLS],
  [/\/api\/scenes(\?|$)/, [{
    id: 'sc-orbits', name: 'Orbits V2', disabled: false, labels: [], devices: [],
    flare_kinds: [], responses: [],
  }]],
  [/\/api\/ownership/, { owner: 'spectra', activation: null, dark_fixtures: null, hue_stream_refusals: {} }],
  [/\/api\/liveness/, { healthy: true }],
  [/\/api\/registry/, { categories: { Matrix: { virtuals: ['crystal-mapper'] }, Strips: { virtuals: ['tv-mapper', 'sconces'] }, Singles: { virtuals: ['hues', 'porch-rail'] } } }],
  [/\/device-preview\/favorites/, { effective_virtual_ids: ['crystal-mapper', 'tv-mapper', 'sconces', 'hues'], virtual_ids: [] }],
  [/\/device-preview\/layout/, { virtuals: [], width: 100, height: 50 }],
  [/\/device-preview\/status/, { connected: false, paused: false, source: 'none', viewers: 0 }],
  [/\/intensity-scale\/mark/, EMPTY ? { uri: null, mark: null, auto_factor: 1, effective_factor: 1, manual_min: 0, manual_max: 2 }
    : { uri: URI, mark: 0.89, auto_factor: 0.74, effective_factor: 0.89, manual_min: 0, manual_max: 2 }],
  [/\/light-show\/arms/, ARMS],
  [/\/light-show\/sequence-run$/, { run: null }],
  [/\/light-show\/sequences\/recent/, { recent: EMPTY ? [] : [
    { sequence_id: 'seq-start', name: 'Standard Start Test', last_started_ms: Date.now() - 6 * 60_000 },
    { sequence_id: 'seq-party', name: 'Party Ramp', last_started_ms: Date.now() - 2 * 86_400_000 },
  ] }],
  [/\/light-show\/sequences/, { sequences: SEQUENCES }],
  [/\/light-show\/sets/, { sets: SETS }],
  [/\/api\/gradients2d/, {}],
  [/\/api\/color-sets/, COLOR_SETS],
  // `AnalysedPlan`'s own wire shape (debug/plannedEvents.ts): separate
  // `scene_changes` / `flares` arrays of `{timestamp_ms, intensity, rank,
  // rank_of}`, and `show_cues` is a `SongCues` OBJECT with `high`/`low`,
  // not a list.
  [/\/api\/analysed-plan/, {
    uri: URI, applies: !EMPTY, reason: null, effective_mode: 'analysed',
    has_authored: false, scene_source: 'planned', show_clock_shift_ms: 0, rank_of: 15,
    scene_changes: EMPTY ? [] : SCENES.map(([ms, rank]) => ({
      timestamp_ms: ms, intensity: 0.8, rank, rank_of: 15,
    })),
    flares: EMPTY ? [] : FLARES.map(([ms, rank]) => ({
      timestamp_ms: ms, intensity: 0.6, rank, rank_of: 15,
    })),
    show_cues: EMPTY ? null : {
      uri: URI, reason: null, duration_ms: DURATION_MS,
      high: {
        level: 'high', timestamp_ms: CUES.high, source: 'auto', shift: null,
        auto_ms: CUES.high, auto_shift: null, drop_mark_ms: null, alternates: [],
      },
      low: {
        level: 'low', timestamp_ms: CUES.low, source: 'auto', shift: null,
        auto_ms: CUES.low, auto_shift: null, drop_mark_ms: null, alternates: [],
      },
    },
  }],
  [/\/api\/drop-sequences\/rails/, { status: 'none', beat_ms: BEAT }],
  [/\/api\/drop-sequences/, {
    uri: URI, status: EMPTY ? 'not_detected' : 'ok', reason: null, detector: null,
    song: {
      tempo_bpm: 84.7, beat_ms: BEAT, captured_from_ms: 0,
      captured_to_ms: DURATION_MS, duration_ms: DURATION_MS,
    },
    authored: [],
    sequences: EMPTY ? [] : [{
      key: `drop:${DROPSEQ.drop}`, state: 'confirmed', num: 1,
      charge: { ms: DROPSEQ.charge }, lull: { ms: DROPSEQ.lull }, drop: { ms: DROPSEQ.drop },
      charge_ms: DROPSEQ.charge, lull_ms: DROPSEQ.lull, drop_ms: DROPSEQ.drop,
      score: 0.9, detected_ms: DROPSEQ.drop, fires: true,
    }],
  }],
  [/\/audio-shape\/meta/, { uri: URI, timestamp_offset_ms: 0, captured_ms: DURATION_MS, complete: true }],
  [/\/audio-shape\/librosa/, { tempo_bpm: 84.7, librosa_offset_ms: 0, beats: BEATS, onsets: [], sections: SECTIONS }],
  [/\/energy\/timeline/, ENERGY],
  [/\/audio-shape\/data/, SHAPE],
  [/\/settings-console\/registry/, { settings: [] }],
  [/\/settings-console\/log/, []],
  [/\/api\/settings/, { shape_average_window_ms: 4000 }],
  [/\/api\/profiles/, {}],
];

window.fetch = (async (input: RequestInfo | URL) => {
  const url = String(typeof input === 'string' ? input : (input as Request).url ?? input);
  const hit = JSON_BY_URL.find(([re]) => re.test(url));
  return new Response(JSON.stringify(hit ? hit[1] : {}), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  });
}) as typeof fetch;

/** The clock push `lib/showClock.ts` listens for — FROZEN at START_MS, so
 * every screenshot of this page lands on the same frame (a moving
 * playhead would make a side-by-side pair unreproducible).
 *
 * `is_playing: false` is what freezes it: `getShowClockMs()` extrapolates
 * from its anchor with `performance.now()` ONLY while playing, and returns
 * the anchor verbatim otherwise. And the push REPEATS on a short interval
 * rather than firing once at mount — the one-shot version raced the real
 * WS client's own connect on the heavier Home view and left the whole page
 * with no clock at all (measured: the next-event box read "—" with a song
 * loaded). Repeating an IDENTICAL anchor is still frozen. */
class FakeSocket {
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  private timer: ReturnType<typeof setInterval> | null = null;
  constructor() {
    setTimeout(() => this.onopen?.(), 0);
    if (EMPTY) return;
    const push = () => this.onmessage?.({
      data: JSON.stringify({
        type: 'clock', show_clock_ms: START_MS, position_ms: START_MS,
        is_playing: false, server_ms: Date.now(),
      }),
    });
    setTimeout(push, 0);
    this.timer = setInterval(push, 250);
  }
  close() { if (this.timer) clearInterval(this.timer); }
  send() {}
}
(window as unknown as { WebSocket: unknown }).WebSocket = FakeSocket;

/** THE REAL CHROME, not a copy of it — `components/AppChrome.tsx` is the
 * one composition App.tsx and the kiosk render too, so this gate measures
 * the order and the markup the app actually has (that is exactly what
 * drifted: the app rendered the bar BEFORE the strip while this harness
 * drew the mockup's own menu/timeline/bar order, and the pair images
 * looked fine because the harness was right and the app was not). The
 * page body is its CHILDREN, which is also what puts the shared
 * song-timeline view state over both the timeline row and Home's shape
 * — rendering them as siblings here would give the harness a Home that
 * cannot drive the row, i.e. the same class of drift again. */
/** The route each view stands for — what the real app's own rule is
 * asked about below. */
const PATHNAME = VIEW === 'home' ? '/'
  : VIEW === 'settings' ? '/settings'
  : VIEW === 'timeline' ? '/timeline'
  : '/scenes';

const Chrome = () => (
  <AppChrome showSongStrip={showsSongStrip(PATHNAME)}>
    {VIEW === 'home' && (
      <main className="home-route"><HomePage /></main>
    )}
    {VIEW === 'settings' && (
      <main><SettingsConsolePage /></main>
    )}
  </AppChrome>
);

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider>
      <MemoryRouter initialEntries={[KIOSK ? '/?kiosk=1' : PATHNAME]}>
        {KIOSK ? <KioskPage /> : <Chrome />}
      </MemoryRouter>
    </ToastProvider>
  </QueryClientProvider>,
);
