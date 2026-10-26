/** HOME DROPS PANEL HARNESS (predrop plan step 1): the REAL Quick
 * sequences / Quick actions cards and the REAL Drops card (home/
 * HomeQuickRuns.tsx, home/HomeDrops.tsx, home/HomeDropEditor.tsx) inside
 * Home's own `main.home-route`, against a MOCKED backend — no network, no
 * SpotFX process, nothing a press here can reach. Built into harness-dist
 * with the other harness pages and served by a plain static server (never
 * the vite dev server, whose proxy would forward an unmocked request to
 * the live app on :8000). `scripts/check_home_drops_layout.py` measures it
 * at 390 / 800 / 1180 px and screenshots it into docs/evidence/home-drops/.
 *
 * The song: four drops — a suggestion waiting for him, a confident
 * detection that plays on its own, a switched-off drop, and one of his own
 * hand-placed drops with the detection standing in for it — plus two
 * sequences and two Light Show sets for the cards beside it. The mock
 * answers the panel's POSTs in memory, so it can be clicked through. */
import '../src/styles/tokens.css';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import HomeQuickRuns from '../src/home/HomeQuickRuns';
import HomeDrops from '../src/home/HomeDrops';
import { SongTimelineViewProvider } from '../src/components/songTimelineView';
import { ToastProvider } from '../src/components/Toast';

const URI = 'spotify:track:harnessdrops';
const NOW = Date.now();
const parts = (charge: string, lull: string, drop: string) =>
  ({ charge, lull, pre_drop: 'absent', drop });
const seq = (over: Record<string, unknown>) => ({
  origin: 'detected', tier: 'suggested', detected_key: null, auto: null, moved: {},
  lull_off: false, charge_off: false, score: 1.1, break_beats: 3, step: 1, rise: 0.9,
  path: 'step', loud_before: true, capped: false, notes: [], needs_review: false,
  detection_lost: false, matches: [], his_marks_near: [], ...over,
});
const view = {
  uri: URI, status: 'ok', reason: null,
  detector: { version: '1', stamp: 'h', detected_at: NOW, confident_score: 1, suggested_score: 0.7 },
  song: { tempo_bpm: 120, beat_ms: 500, captured_from_ms: 0, captured_to_ms: 200000, duration_ms: 200000 },
  sequences: [
    seq({ key: 'drop:44000', state: 'suggested', charge_ms: 35000, lull_ms: 40000, drop_ms: 44000,
      parts: parts('waiting', 'waiting', 'waiting'), fires: false, fires_reason: 'waits_for_confirm' }),
    seq({ key: 'drop:90000', state: 'confident', tier: 'confident', charge_ms: 80000, lull_ms: 86000,
      drop_ms: 90000, parts: parts('waiting', 'on', 'on'), fires: true, fires_reason: 'his' }),
    seq({ key: 'drop:130000', state: 'suggested', charge_ms: null, lull_ms: 126000, drop_ms: 130000,
      parts: parts('absent', 'waiting', 'off'), fires: false, fires_reason: 'switched_off' }),
    seq({ key: 'drop:169980', state: 'matches_yours', tier: 'confident', charge_ms: 160000,
      lull_ms: 166000, drop_ms: 169980, parts: parts('waiting', 'waiting', 'waiting'), fires: true,
      fires_reason: 'analysed_show', matches: [{ id: 'h-drop', kind: 'drop', timestamp_ms: 170000 }] }),
  ],
  excluded: [], counts: {}, authored: [], authored_lone: [],
  yours: [{
    key: 'his:h-drop',
    charge: { id: 'h-charge', kind: 'charge', timestamp_ms: 160100, enabled: true },
    lull: { id: 'h-lull', kind: 'lull', timestamp_ms: 166100, enabled: true },
    drop: { id: 'h-drop', kind: 'drop', timestamp_ms: 170000, enabled: true },
    enabled: true, detections: ['drop:169980'], detection: 'drop:169980',
  }],
  firing: { effective_mode: 'analysed', has_authored: true, analysed_applies: true,
    his_applies: false, testing: false },
  windows: [],
};
const prov = { uri: URI, imported_profile: false, triggers: ['h-charge', 'h-lull', 'h-drop']
  .map((id) => ({ id, imported: false, why: 'by_hand', remove_would: 'delete' })) };
const beats: [number, number][] = [];
for (let ms = 0; ms <= 200000; ms += 500) beats.push([ms, ms % 2000 === 0 ? 1 : 0]);
const rails = { uri: URI, status: 'ok', reason: null, beat_ms: 500, captured_from_ms: 0,
  spikes: [[44000, 0.9], [90000, 0.8], [130000, 0.7], [170000, 0.9], [40000, 0.3]], beats };
const ts: number[] = []; const rms: number[] = [];
for (let ms = 0; ms <= 200000; ms += 12) {
  ts.push(ms);
  const near = [44000, 90000, 130000, 170000].some((d) => ms >= d && ms < d + 4000);
  rms.push((near ? 0.8 : 0.25) + 0.15 * Math.sin(ms / 90));
}
const shape = { timestamps_ms: ts, rms_total: rms, rms_low: rms, rms_mid: rms, rms_high: rms };
const controls: Record<string, unknown> = { drop_testing: false, scene_change_mode: 'analysed' };
const status = {
  increment: 'S3', dark: false,
  bridge: { connected: true, track: { uri: URI, title: 'Harness song', artist: 'Harness',
    duration_ms: 200000, is_playing: true, position_ms: 30000 } },
  triggers: { track_uri: URI, position_ms: 30000, last_drop: null },
};
const sets = [
  { id: 'set-1', name: 'Blackout into the drop', actions: [] },
  { id: 'set-2', name: 'Strobe the singles', actions: [] },
];
const sequences = [{ id: 'seq-1', name: 'Friday warm-up', items: [{}, {}, {}] }];
const recent = [{ sequence_id: 'seq-1', name: 'Friday warm-up', last_started_ms: NOW - 6 * 60_000 }];
const arms = { armed: [], song: { uri: URI, phases: null } };

const answer = (result: unknown) => ({ result, view, before: { overrides: {}, added: [] },
  after: { overrides: {}, added: [] }, rev_before: 'r', rev_after: 'r', profile: [], said: '' });
const realFetch = window.fetch.bind(window);
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = new URL(String(input), window.location.href);
  const p = url.pathname;
  const method = (init?.method ?? 'GET').toUpperCase();
  const body = init?.body ? JSON.parse(String(init.body)) : undefined;
  const ok = (data: unknown) => new Response(JSON.stringify(data), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p === '/spectra/api/engine/status') return ok(status);
  if (p === '/spectra/api/room-controls') {
    if (method === 'PUT') Object.assign(controls, body);
    return ok(controls);
  }
  if (p === '/spectra/api/drop-sequences') return ok(view);
  if (p === '/spectra/api/drop-sequences/provenance') return ok(prov);
  if (p === '/spectra/api/drop-sequences/rails') return ok(rails);
  if (p.startsWith('/spectra/api/drop-sequences/')) return ok(answer(body?.key ?? null));
  if (p === '/api/audio-shape/data') return ok(shape);
  if (p === '/spectra/api/light-show/sets') return ok({ sets });
  if (p === '/spectra/api/light-show/sequences') return ok({ sequences });
  if (p === '/spectra/api/light-show/sequences/recent') return ok({ recent });
  if (p === '/spectra/api/light-show/sequence-run') return ok({ run: null });
  if (p === '/spectra/api/light-show/arms') return ok(arms);
  if (p.startsWith('/spectra/') || p.startsWith('/api/')) {
    return new Response(JSON.stringify({ detail: 'not in this harness' }), { status: 404 });
  }
  return realFetch(input, init);
};
// the SPECTRA websocket has nothing to talk to here
class QuietSocket { onopen = null; onclose = null; onmessage = null; onerror = null;
  readyState = 0; close() {} send() {} addEventListener() {} removeEventListener() {} }
(window as unknown as { WebSocket: unknown }).WebSocket = QuietSocket;

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
// ?kiosk=1: the wall kiosk's own frame (kiosk/KioskPage.tsx — `.kiosk-page`
// around `main.kiosk-main`), whose CSS gives every button in main its 44 px
// floor and the quick-run cards two columns
const KIOSK = new URLSearchParams(window.location.search).get('kiosk') === '1';
const cards = (
  <div className="home-page">
    <HomeQuickRuns><HomeDrops /></HomeQuickRuns>
  </div>
);
createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={qc}>
    <MemoryRouter initialEntries={['/']}>
      <ToastProvider>
        <SongTimelineViewProvider>
          {KIOSK
            ? <div className="kiosk-page"><main className="kiosk-main">{cards}</main></div>
            : <main className="home-route">{cards}</main>}
        </SongTimelineViewProvider>
      </ToastProvider>
    </MemoryRouter>
  </QueryClientProvider>,
);
