/** SUNG WORDS HARNESS (lyrics plan, step 2): the REAL /testbed page against a
 * MOCKED backend, for scripts/render_testbed_lyrics_lane.py. No network, no
 * backend, nothing a press here can reach; built into harness-dist with the
 * other pages and served by a plain static server.
 *
 * The words are invented, not lyrics, so nothing of anyone's song is in the
 * repo. Four songs, one per state the lane can be in: a clean one with his
 * marks on it, one whose audio slips against its labels (flagged), one with
 * no word timeline, and one captured again after it was aligned (stale). */
import '../src/styles/tokens.css';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../src/components/Toast';
import TestbedPage from '../src/testbed/TestbedPage';

const json = (body: unknown) => new Response(JSON.stringify(body), {
  status: 200, headers: { 'content-type': 'application/json' },
});

const CLEAN = 'spotify:track:harnesscleansong00001';
const SLIP = 'spotify:track:harnessslipsong000002';
const NONE = 'spotify:track:harnessnowords0000003';
const STALE = 'spotify:track:harnessstalesong00004';

const HOOK = ['we', 'ran', 'the', 'red', 'light', 'home'];
const VERSES = [
  ['golden', 'windows', 'on', 'the', 'hill'],
  ['nothing', 'left', 'to', 'say', 'tonight'],
  ['azul', 'sobre', 'el', 'corazon', 'de', 'la', 'noche'],
  ['paper', 'boats', 'along', 'the', 'river', 'bend'],
];

interface W { word: string; line: number; ms: number; end_ms: number; score: number; features: Record<string, number> }

function buildWords(): W[] {
  const out: W[] = [];
  let t = 8_000;
  let line = 0;
  const addLine = (tokens: string[], hook: boolean) => {
    tokens.forEach((word, i) => {
      const last = i === tokens.length - 1;
      const held = last ? 0.9 : (word.length > 5 ? 0.3 : 0);
      const beat = i % 3 === 0 ? 0.9 : i % 3 === 1 ? 0.4 : 0;
      const loud = (i * 37 + line * 11) % 7 === 0 ? 0.8 : 0.1;
      const hookF = hook ? 0.7 : 0;
      const score = 0.3 * loud + 0.25 * held + 0.2 * beat + 0.1 * (last ? 1 : 0) + 0.15 * hookF;
      const dur = last ? 700 : 220 + word.length * 10;
      out.push({ word, line, ms: t, end_ms: t + dur, score: Number(score.toFixed(3)),
                 features: { loud, held, beat, line_end: last ? 1 : 0, hook: hookF } });
      t += dur + 90;
    });
    t += 800;
    line += 1;
  };
  for (let round = 0; round < 6; round += 1) {
    addLine(HOOK, true);
    addLine(VERSES[round % VERSES.length], false);
    addLine(HOOK, true);
  }
  return out;
}

const WORDS = buildWords();
const lastMs = WORDS[WORDS.length - 1].end_ms;

const engines = (lyrics: boolean) => ({
  librosa: { label: 'Current (librosa)', kinds: ['section_boundary', 'beat', 'downbeat'], available: false, computed_at: null, mark_count: null },
  lyrics: { label: 'Sung words', kinds: ['emphasis'], available: lyrics, computed_at: null, mark_count: null },
});

const song = (uri: string, title: string, lyrics: boolean) => ({
  uri, title, artist: 'Harness', n_transitions: 2, n_flares: 3, n_drops: 0, n_lulls: 0, n_charges: 0,
  n_generated: 0, n_promoted: 0, n_snapped: 0, n_unsnapped_generated: 0, snap_grid_counts: {},
  provenance: { found: true, ai_generated: false, verified: true, editor_trigger_count: 5 },
  audio: { pinned: false, pinned_at: null, has_source_wav: true, has_peaks: false },
  engines: engines(lyrics),
});

const SONGS = [song(CLEAN, 'A clean capture', true), song(SLIP, 'A capture that slips', true),
               song(NONE, 'No words yet', false), song(STALE, 'Captured again since', true)];

// A flare exactly on an emphasized word, so a test can read that a word and
// a flare with the same time share an x.
const alignedWord = WORDS.filter((w) => w.score >= 0.4)[1];
const marks = (uri: string) => ({
  uri, title: 'x', artist: 'Harness',
  transitions: [{ id: 't1', timestamp_ms: 8000, kind: 'fire_scene', enabled: true, promoted: false, event_class: null },
                { id: 't2', timestamp_ms: 41_000, kind: 'fire_scene', enabled: true, promoted: false, event_class: null }],
  flares: [{ id: 'f1', timestamp_ms: alignedWord.ms, kind: 'fire_response', enabled: true, promoted: false, event_class: 'flare' },
           { id: 'f2', timestamp_ms: 17_000, kind: 'fire_response', enabled: true, promoted: false, event_class: 'flare' },
           { id: 'f3', timestamp_ms: 33_000, kind: 'fire_response', enabled: true, promoted: false, event_class: 'drop' }],
  n_generated: 0, n_promoted: 0, n_snapped: 0, n_unsnapped_generated: 0, snap_grid_counts: {},
  provenance: { found: true, ai_generated: false, verified: true, editor_trigger_count: 5 }, tempo_bpm: 120,
});

function lyrics(uri: string) {
  const base = { uri, lang: 'eng', provenance: 'lrclib_synced', mode: 'line_anchored', default_sensitivity: 0.6 };
  const clock = { lane_clock: 'capture_label', max_slip_ms: 12.5, flagged: false, note: null };
  if (uri === NONE) return { ...base, status: 'none', note: 'No sung words have been imported for this song.', clock, words: [] };
  if (uri === STALE) return { ...base, status: 'stale', note: 'This song was captured again after its words were aligned, so the word times no longer apply (npz_changed).', clock, words: [] };
  const words = WORDS.map(({ features: _f, ...w }) => w);
  if (uri === SLIP) {
    return { ...base, status: 'ok', note: null, words,
             clock: { lane_clock: 'capture_label', max_slip_ms: 1840, flagged: true,
                      note: 'This capture\'s audio slips against its time labels by up to 1.8 s, so your marks and the words below cannot be compared here: a mark was placed by the audio, and fires by the labels. The words are drawn where they are sung, the waveform and beat lanes are not, and no scores are shown.' } };
  }
  return { ...base, status: 'ok', note: null, clock, words };
}

function engineMarks(uri: string, engine: string, kind: string, sensitivity: number) {
  if (engine !== 'lyrics' || uri === NONE || uri === STALE) {
    return { uri, engine, mark_kind: kind, available: false, estimate: [] };
  }
  const threshold = 1 - sensitivity;
  return {
    uri, engine, mark_kind: kind, available: true,
    estimate: WORDS.filter((w) => w.score >= threshold).map((w) => ({
      time_ms: w.ms, label: w.word, score: w.score,
      detail: { end_ms: w.end_ms, line: w.line, features: w.features, matched_label: null },
    })),
  };
}

window.fetch = (async (input: RequestInfo | URL) => {
  const url = String(typeof input === 'string' ? input : (input as Request).url ?? input);
  const q = new URL(url, 'http://x').searchParams;
  const uri = q.get('uri') ?? '';
  if (url.includes('/testbed/songs')) return json(SONGS);
  if (url.includes('/testbed/marks')) return json(marks(uri));
  if (url.includes('/testbed/waveform')) {
    const timestamps_ms = Array.from({ length: 400 }, (_, i) => (i / 399) * lastMs);
    return json({ uri, source: 'npz_rms_fallback', timestamps_ms, duration_ms: lastMs,
                  rms_total: timestamps_ms.map((_, i) => 0.4 + 0.3 * Math.sin(i / 11)) });
  }
  if (url.includes('/testbed/lyrics')) return json(lyrics(uri));
  if (url.includes('/testbed/engine-marks')) {
    return json(engineMarks(uri, q.get('engine') ?? '', q.get('mark_kind') ?? '',
                            Number(q.get('emphasis_sensitivity') ?? 0.6)));
  }
  if (url.includes('/testbed/promotions')) return json([]);
  if (url.includes('/testbed/reference-set')) return json({ songs: [] });
  if (url.includes('/testbed/drop-reference-set')) return json({ songs: [], total: null, edm_total: null });
  if (url.includes('/room-controls')) {
    return json({ transition_window_beats: 8, transition_edge_sensitivity: 0.5, transitions_per_minute: 8,
                  drop_confident_score: 1.2, drop_suggested_score: 0.9, drop_floor: 0.5 });
  }
  return json({});
}) as typeof fetch;

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider>
      <MemoryRouter initialEntries={['/testbed']}>
        <main style={{ padding: 12 }}><TestbedPage /></main>
      </MemoryRouter>
    </ToastProvider>
  </QueryClientProvider>,
);
