/** WORDS TAB HARNESS (Word Shapes row W2.1): the REAL Scenes → Words
 * response editor and the REAL flare preview overlay against a MOCKED
 * backend, for scripts/render_words_tab.py. Reaches nothing — no service,
 * no fixture, no light.
 *
 * THE CANNED TIMELINE IS THE SERVER'S OWN ANSWER, not an invention: the
 * numbers below are what `flare_preview.build_timeline` really returns for
 * a `word_shape` kind at these intensities on the plan's default room
 * settings (form 0.5 s loud / 0.633 s at Energy 0.5, hold 0.8 s — a preview
 * has no sung phrase, so the hold sits at `word_shape_hold_min_s` —
 * release 1.5x the form), and `tests/test_scenes_words_tab.py` pins the
 * same relationships against the real route. The preview's `shape` is
 * honoured here exactly as the API honours it, so a picker press really
 * changes what the next read returns.
 *
 * The scene lives in component state, so a drag, a detach, a power flip or
 * "+ Word Shape kind" really changes the page. */
import '../src/styles/tokens.css';
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../src/components/Toast';
import ResponseTab from '../src/scenes/tabs/ResponseTab';
import { emptyBand, emptyResponse, newScene } from '../src/types';
import type { SceneV2 } from '../src/types';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json' },
});

/** The shape library's own three, as GET /api/sung-labels returns them
 * (fx/effects/word_shapes.py's declaration order). */
const SHAPES = [
  { id: 'heart', name: 'Heart', labels: [] },
  { id: 'star', name: 'Star', labels: [] },
  { id: 'diamond', name: 'Diamond', labels: [] },
];

const ROUND = (n: number) => Math.round(n * 10000) / 10000;

/** word_shape_timing's own law (spectra/services/room_controls.py) on the
 * plan's defaults: the form paces 0.9 s at Energy 0 down to 0.5 s at 0.75
 * and above, the hold is the sung phrase clamped to [0.8, 2.0] (a preview
 * has no phrase, so 0.8), the release is 1.5x the form. */
function envelope(intensity: number) {
  const t = Math.min(1, Math.max(0, intensity) / 0.75);
  const form_s = ROUND(0.9 + (0.5 - 0.9) * t);
  return { form_s, hold_s: 0.8, release_s: ROUND(form_s * 1.5) };
}

function timeline(intensity: number, shape: string | null) {
  const env = envelope(intensity);
  const duration_s = 6.0;
  const anchor = Math.min(2.0, duration_s / 3);
  return {
    kind_name: 'Word Shape', kind_type: 'word_shape',
    intensity: ROUND(intensity), result: 'applied', overrode_disabled: false,
    animation_start_s: null, animation_end_s: null,
    effect_animation_ms: ROUND(1000 * (env.form_s + env.hold_s + env.release_s)),
    word_shape: { shape: shape || 'heart', ...env },
    duration_s,
    animation_anchor_s: anchor,
    // The Words section ignores a per-kind offset, so the mark IS the anchor.
    trigger_mark_s: anchor,
    lead_ms: Math.round(env.form_s * 1000),
    anchor_rule: 'switch_end', attached_classes: ['word'],
    fire_at_s: ROUND(anchor - env.form_s),
    // Empty until wave 1 wires an effect into WORD_SHAPE_EFFECTS — the
    // state this row must draw a truthful ruler in.
    writes: [],
  };
}

const state = { opens: [] as { intensity: number; shape: string | null }[],
                fires: [] as { intensity: number; shape: string | null }[] };
(window as unknown as { __harness: typeof state }).__harness = state;

window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(typeof input === 'string' ? input : (input as Request).url ?? input);
  const body = init?.body ? JSON.parse(String(init.body)) : {};
  if (url.includes('/flare-preview/open')) {
    state.opens.push({ intensity: body.intensity, shape: body.shape ?? null });
    return json(timeline(body.intensity ?? 1, body.shape ?? null));
  }
  if (url.includes('/flare-preview/fire')) {
    state.fires.push({ intensity: body.intensity, shape: body.shape ?? null });
    return json({ held: true });
  }
  if (url.includes('/flare-preview/heartbeat')) return json({ active: true, remaining_s: 30 });
  if (url.includes('/flare-preview/close')) return json({ active: false });
  if (url.includes('/sung-labels')) {
    return json({ color_sets: [], effects: [], shapes: SHAPES, labels_hash: 'h',
                  n_labels: 0, auto_read: false,
                  claude: { available: false, reason: null, backend: '', model: '' },
                  draft_batch_size: 8 });
  }
  return json({});
}) as typeof fetch;

/** The scene W2.5's data script writes: one Word Shape kind on one
 * full-range Words band, beside an ordinary colour kind pooled with it so
 * the lane rack shows what the plan's own mock shows. */
function seed(): SceneV2 {
  const scene = newScene('harness-scene');
  scene.name = 'Black Hole V2';
  scene.flare_kinds = [
    { name: 'Word Shape', type: 'word_shape', jump: null, params: {}, gain: 1,
      hold_ms: null, trigger_offset_ms: 0, enabled: true },
    { name: 'Colour Jump', type: 'drift_jump', jump: 'color_set', params: {}, gain: 1,
      hold_ms: null, trigger_offset_ms: 0, enabled: true },
  ];
  scene.responses = {
    word: {
      ...emptyResponse(),
      bands: [{ ...emptyBand(), kinds: { 'Word Shape': 1, 'Colour Jump': 0.6 } }],
    },
  };
  return scene;
}

/** ?bare=1: a scene with NO Words section and no kinds — the "+ respond to
 * words" state, which is what he sees before adding one. It is the SEED,
 * not a render-time strip, so pressing the button really builds the
 * section (a strip would rebuild the bare scene on every render and look
 * like the button did nothing). */
function bareSeed(): SceneV2 {
  const scene = newScene('harness-bare');
  scene.name = 'Black Hole V2';
  return scene;
}

function Harness() {
  const params = new URLSearchParams(window.location.search);
  const bare = params.get('bare') === '1';
  const [shown, setScene] = useState<SceneV2>(bare ? bareSeed : seed);
  const warnings = params.get('warn') === '1'
    ? ["flare kind 'Word Shape' is a word_shape — only the Words section fires "
       + 'a shape, so its attachment to flare does nothing']
    : undefined;
  return (
    <main style={{ padding: 12, maxWidth: 1100 }}>
      <div className="card">
        <div className="card-title">{shown.name} — Words</div>
        <ResponseTab scene={shown} setScene={setScene} classes={['word']}
          helpTopic="tab-words" warnings={warnings} />
      </div>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider>
      <MemoryRouter initialEntries={['/scenes']}>
        <Harness />
      </MemoryRouter>
    </ToastProvider>
  </QueryClientProvider>,
);
