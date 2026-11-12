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

// A local run can inject a real song's words (window.__LYRICS_FIXTURE__) to
// look at real density. Real lyrics are never committed: the repo's own
// render uses the invented words above.
const FIXTURE = (window as unknown as {
  __LYRICS_FIXTURE__?: { words: W[]; transitions: unknown[]; flares: unknown[] };
}).__LYRICS_FIXTURE__;
const WORDS = FIXTURE?.words ?? buildWords();
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
const alignedWord = WORDS.filter((w) => w.score >= 0.4)[1] ?? WORDS[0];
const marks = (uri: string) => ({
  uri, title: 'x', artist: 'Harness',
  transitions: FIXTURE?.transitions ?? [{ id: 't1', timestamp_ms: 8000, kind: 'fire_scene', enabled: true, promoted: false, event_class: null },
                { id: 't2', timestamp_ms: 41_000, kind: 'fire_scene', enabled: true, promoted: false, event_class: null }],
  flares: FIXTURE?.flares ?? [{ id: 'f1', timestamp_ms: alignedWord.ms, kind: 'fire_response', enabled: true, promoted: false, event_class: 'flare' },
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

// WORD COLOURS (lyrics plan step 4): what each matched word would do, the
// shape GET /api/testbed/lyric-events returns — one word imprinting on the
// scene change at 8 s (haloed in its colour on the Word events row and the
// lane's guide lines), one firing on its own, one sitting out this play
// (THE ROLL, 2026-11-12), and one naming a flare that cannot carry colour.
// The song is "playing", so the plan is this play's roll; a kept roll and a
// sample play are kept in memory, so the page's own presses change it.
const WORD_EVENTS = [
  { id: 'analysed-scene:k1', kind: 'scene', ms: 8000, label: 'scene change', can_carry: true, why_not: null },
  // on an emphasized word, so a test can read that a word and a flare with
  // the same time share an x
  { id: 'analysed-flare:k7', kind: 'flare', ms: alignedWord.ms, label: 'flare', can_carry: false, why_not: 'no colour jump' },
];
let keptSeed: number | null = null;
const PLAY_SEED = 0x51c3a7f;
const pinsByMatch: Record<string, 'always' | 'never'> = {};
function wordAction(over: Record<string, unknown>) {
  const strength = (over.strength as number | undefined) ?? 0.9;
  const matchId = (over.match_id as string | undefined) ?? 'g1';
  const pin = pinsByMatch[matchId] ?? null;
  const chance = pin === 'always' ? 1 : pin === 'never' ? 0 : strength;
  return {
    key: '0-0', first_word: 0, last_word: 0, phrase: 'red', label: 'red', ms: 7600, end_ms: 7900,
    source: 'claude', strength, match_id: matchId, pin, chance, draw: 0.31, won: true,
    chance_words: pin === 'always' ? 'Pinned to play every time.' : pin === 'never' ? 'Pinned to never play.'
      : `Plays on about ${Math.round(chance * 100)}% of plays (Claude's confidence).`,
    set_names: ['Blood Red'], set_ids: ['red1'], swatch: '#c81e1e',
    verdict: 'imprint', why: null, words: 'Gives its colour to the scene change at 0:08.0 (+0.4 s from the word).',
    energy: 0.3, momentary: false, transition_ms: 1800, blocked_by: null, event: WORD_EVENTS[0], ...over,
  };
}
function roll(uri: string, sample: number | null, actions: { won: boolean | null }[]) {
  const playing = uri === CLEAN;
  const seed = playing ? PLAY_SEED : sample ?? keptSeed;
  const state = playing ? 'playing' : sample != null ? 'sample' : keptSeed != null ? 'kept' : 'none';
  return {
    state, seed, tag: seed == null ? null : (seed & 0xffff).toString(16).padStart(4, '0'),
    started_ms: playing ? Date.now() - 95_000 : null, kept: false, kept_seed: keptSeed, playing,
    n_words: actions.length, n_won: state === 'none' ? 0 : actions.filter((a) => a.won).length,
  };
}
function lyricEvents(uri: string, sample: number | null) {
  if (uri === NONE || uri === STALE) {
    return { uri, status: 'none', note: 'No sung words.', clock_flagged: false, enabled: false,
             settings: { energy_cutoff: 0.5, min_gap_s: 8, imprint_window_s: 2 }, n_events: 0, shows_on: 0,
             roll: roll(uri, null, []), actions: [] };
  }
  const actions = lyricActions();
  return {
    uri, status: 'ok', note: null, clock_flagged: uri === SLIP, enabled: true,
    settings: { energy_cutoff: 0.5, min_gap_s: 8, imprint_window_s: 2 }, n_events: 2, shows_on: 1,
    roll: roll(uri, sample, actions), actions,
  };
}
function lyricActions() {
  return [
      wordAction({ strength: 0.91 }),
      wordAction({ key: '40-40', first_word: 40, last_word: 40, phrase: 'blue', label: 'blue', ms: 25_000, end_ms: 25_400,
                   match_id: 'g2', strength: 0.84,
                   set_names: ['Deep Blue'], set_ids: ['blue1'], swatch: '#1e40c8', verdict: 'fire', event: null,
                   words: 'Fires on its own: low energy (0.30), so it holds until the next scene change or matched word, changing over 1.8 s.' }),
      wordAction({ key: '60-60', first_word: 60, last_word: 60, phrase: 'dull', label: 'dull', ms: 33_000, end_ms: 33_300,
                   match_id: 'g3', strength: 0.35, draw: 0.62, won: false, verdict: 'nothing', why: 'sat_out', event: null,
                   words: 'Sits out this play: its chance is 35% and it did not come up this time.' }),
      wordAction({ key: '70-70', first_word: 70, last_word: 70, phrase: 'gold', label: 'gold', ms: alignedWord.ms - 200, end_ms: alignedWord.ms + 100,
                   match_id: 'g4', strength: 0.75,
                   set_names: ['Gold'], set_ids: ['gold1'], swatch: '#d9a441', verdict: 'nothing', why: 'event_cannot_carry',
                   event: WORD_EVENTS[1], words: 'The flare cannot carry colour (no colour jump), so nothing fires.' }),
  ];
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

// The Word matches row (lyrics plan step 3): an in-memory store, so a press on
// the page really changes what the next read returns.
const CLAUDE = { available: true, reason: null, backend: 'api', model: 'harness-model' };
const TARGETS = {
  red: { kind: 'color_set', id: 'red1', name: 'Blood Red', swatch: '#ff0000' },
  blue: { kind: 'color_set', id: 'blue1', name: 'Mid - Ice', swatch: '#00aaff' },
  fish: { kind: 'effect', id: 'fish', name: 'Fish', swatch: null },
};
interface M { id: string; source: 'claude' | 'his'; first_word: number; last_word: number; phrase: string; label: string; confidence: number | null; why: string; target: typeof TARGETS.red }

const matchWords = FIXTURE?.words ?? WORDS;
const redAt = matchWords.findIndex((w) => w.word === 'red');
const azulAt = matchWords.findIndex((w) => w.word === 'azul');
let matchRows: M[] = [
  { id: 'g1', source: 'claude', first_word: redAt, last_word: redAt + 1, phrase: 'red light', label: 'red', confidence: 0.91, why: 'names the colour', target: TARGETS.red },
  { id: 'g2', source: 'claude', first_word: azulAt, last_word: azulAt, phrase: 'azul', label: 'blue', confidence: 0.84, why: 'blue, in Spanish', target: TARGETS.blue },
];
let deleted = 0;
let nextHis = 1;
const matchPayload = (uri: string) => ({
  uri, status: 'ok', note: null, state: 'fresh', claude: CLAUDE,
  reading: { at_ms: Date.now() - 180_000, model: 'harness-model', n_refused: 0 },
  n_his: matchRows.filter((m) => m.source === 'his').length, n_deleted: deleted, unplaced: [],
  n_pinned: Object.keys(pinsByMatch).length,
  matches: uri === CLEAN ? matchRows.map((m) => ({
    id: m.id, source: m.source, provenance: m.source === 'his' ? 'his' : 'claude_guess',
    first_word: m.first_word, last_word: m.last_word, phrase: m.phrase, label: m.label,
    confidence: m.confidence, why: m.why, pin: pinsByMatch[m.id] ?? null,
    targets: [m.target], n_targets: 1, targets_missing: 0,
    ms: matchWords[m.first_word].ms, end_ms: matchWords[m.last_word].end_ms,
    score: Math.max(...matchWords.slice(m.first_word, m.last_word + 1).map((w) => w.score)),
  })) : [],
});
const labelsPage = {
  color_sets: [
    { id: 'red1', name: 'Blood Red', kind: 'set', disabled: false, swatch: '#ff0000', has_colours: true, labels: [{ text: 'red', source: 'seed' }], meanings: { things: [], moods: [], places: [] }, drafted_ms: null, draft_model: null },
    { id: 'blue1', name: 'Mid - Ice', kind: 'set', disabled: false, swatch: '#00aaff', has_colours: true, labels: [{ text: 'blue', source: 'seed' }], meanings: { things: [], moods: [], places: [] }, drafted_ms: null, draft_model: null },
  ],
  effects: [{ id: 'fish', name: 'Fish', labels: [{ text: 'fish', source: 'seed' }] }],
  labels_hash: 'h', n_labels: 3, auto_read: false, claude: CLAUDE, draft_batch_size: 10,
};

const realFetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(typeof input === 'string' ? input : (input as Request).url ?? input);
  const q = new URL(url, 'http://x').searchParams;
  const uri = q.get('uri') ?? '';
  const body = init?.body ? JSON.parse(String(init.body)) : {};
  if (url.includes('/sung-labels')) return json(labelsPage);
  if (url.includes('/lyric-matches/delete')) {
    matchRows = matchRows.filter((m) => m.id !== body.id);
    deleted += 1;
    return json(matchPayload(body.uri));
  }
  if (url.includes('/lyric-matches/add')) {
    const span = matchWords.slice(body.first_word, body.last_word + 1);
    const target = body.target.kind === 'effect' ? TARGETS.fish
      : body.target.id === 'red1' ? TARGETS.red : TARGETS.blue;
    matchRows.push({ id: `h${nextHis++}`, source: 'his', first_word: body.first_word, last_word: body.last_word,
                     phrase: span.map((w) => w.word).join(' '), label: target.name, confidence: null, why: '', target });
    return json(matchPayload(body.uri));
  }
  if (url.includes('/lyric-matches/pin')) {
    if (body.pin === 'chance') delete pinsByMatch[body.id]; else pinsByMatch[body.id] = body.pin;
    return json(matchPayload(body.uri));
  }
  if (url.includes('/lyric-matches')) return json(matchPayload(uri));
  if (url.includes('/testbed/lyric-events/keep')) {
    keptSeed = body.seed ?? null;
    return json({ uri: body.uri, kept_seed: keptSeed });
  }
  if (url.includes('/testbed/lyric-events')) {
    return json(lyricEvents(uri, q.get('sample') == null ? null : Number(q.get('sample'))));
  }
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
};
window.fetch = realFetch as typeof fetch;

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider>
      <MemoryRouter initialEntries={['/testbed']}>
        <main style={{ padding: 12 }}><TestbedPage /></main>
      </MemoryRouter>
    </ToastProvider>
  </QueryClientProvider>,
);
