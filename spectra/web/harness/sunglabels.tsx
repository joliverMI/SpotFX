/** SUNG LABELS HARNESS (lyrics plan step 3): the REAL /sung-labels page against
 * a MOCKED backend, for scripts/render_sung_labels.py. An in-memory store, so a
 * press on the page really changes what the next read returns. Reaches nothing. */
import '../src/styles/tokens.css';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../src/components/Toast';
import SungLabelsPage from '../src/sunglabels/SungLabelsPage';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json' },
});

type Chip = { text: string; source: 'seed' | 'claude' | 'his' };
const chips = (source: Chip['source'], words: string[]): Chip[] => words.map((text) => ({ text, source }));
const noMeanings = () => ({ things: [] as Chip[], moods: [] as Chip[], places: [] as Chip[] });
const RED = ['blood', 'red', 'rojo', 'crimson', 'scarlet', 'ruby', 'cherry', 'fire', 'rose', 'heart'];

const cards = [
  { id: 'red1', name: 'Blood Red', kind: 'set', disabled: false, swatch: '#b00000', has_colours: true,
    labels: chips('seed', RED),
    meanings: { things: chips('claude', ['volcano', 'embers', 'wine']), moods: chips('claude', ['rage', 'desire']), places: chips('claude', ['the desert']) },
    drafted_ms: Date.now() - 86_400_000, draft_model: 'harness-model' },
  { id: 'ice', name: 'Mid - Ice', kind: 'set', disabled: false, swatch: '#00d0ff', has_colours: true,
    labels: chips('seed', ['ice', 'cyan', 'turquoise', 'turquesa', 'teal', 'aqua', 'lagoon', 'glacier', 'pool', 'blue', 'azul']),
    meanings: noMeanings(), drafted_ms: null, draft_model: null },
  { id: 'hype', name: 'Hype', kind: 'group', disabled: false, swatch: '#ff4000', has_colours: true,
    labels: chips('seed', ['hype', 'rainbow', 'arcoiris']), meanings: noMeanings(), drafted_ms: null, draft_model: null },
  { id: 'night', name: 'Night Light', kind: 'set', disabled: true, swatch: '#3a1e8c', has_colours: true,
    labels: chips('seed', ['night light', 'purple', 'morado', 'violet']), meanings: noMeanings(), drafted_ms: null, draft_model: null },
  { id: 'b', name: 'Bass Drop Brightness', kind: 'set', disabled: false, swatch: '#ffffff', has_colours: false,
    labels: [], meanings: noMeanings(), drafted_ms: null, draft_model: null },
];
const effects = [
  { id: 'blackhole', name: 'Black Hole', labels: chips('seed', ['black hole', 'agujero negro', 'void', 'abyss', 'gravity']) },
  { id: 'fish', name: 'Fish', labels: chips('seed', ['fish', 'pez', 'swim']) },
];

const state = { auto_read: false, drafted: [] as string[][], claude: true };

const page = () => ({
  color_sets: cards, effects, labels_hash: 'h', auto_read: state.auto_read,
  n_labels: new Set([...cards.flatMap((c) => c.labels.map((l) => l.text))]).size,
  claude: state.claude ? { available: true, reason: null, backend: 'api', model: 'harness-model' }
    : { available: false, reason: 'No Claude API key is set up on this machine.', backend: 'api', model: 'x' },
  draft_batch_size: 2,
});

function applyEdit(body: { kind: string; id: string; list: string; op: string; text: string }) {
  const row: { labels: Chip[]; meanings?: Record<string, Chip[]> } | undefined = body.kind === 'effect'
    ? effects.find((e) => e.id === body.id) : cards.find((c) => c.id === body.id);
  if (!row) return;
  const key = body.list as string;
  const list = key === 'labels' ? row.labels : row.meanings![key];
  if (body.op === 'remove') {
    const i = list.findIndex((c) => c.text === body.text);
    if (i >= 0) list.splice(i, 1);
  } else {
    list.push({ text: body.text, source: 'his' });
  }
}

(window as unknown as { __harness: typeof state }).__harness = state;
window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(typeof input === 'string' ? input : (input as Request).url ?? input);
  const body = init?.body ? JSON.parse(String(init.body)) : {};
  if (url.endsWith('/sung-labels/edit')) { applyEdit(body); return json(page()); }
  if (url.endsWith('/sung-labels/settings')) { state.auto_read = body.auto_read; return json(page()); }
  if (url.endsWith('/sung-labels/draft')) {
    state.drafted.push(body.ids);
    for (const id of body.ids as string[]) {
      const card = cards.find((c) => c.id === id);
      if (card) { card.drafted_ms = Date.now(); card.draft_model = 'harness-model'; card.meanings.things = chips('claude', ['snowfall']); }
    }
    return json({ drafted: body.ids.length, ids: body.ids, skipped: [] });
  }
  if (url.includes('/sung-labels')) return json(page());
  return json({});
}) as typeof fetch;

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider>
      <MemoryRouter initialEntries={['/sung-labels']}>
        <main style={{ padding: 12 }}><SungLabelsPage /></main>
      </MemoryRouter>
    </ToastProvider>
  </QueryClientProvider>,
);
