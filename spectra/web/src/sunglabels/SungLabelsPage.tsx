/** One page for correcting what every colour set and effect answers to when it
 * is sung (lyrics plan step 3, his ruling: "Claude drafts meanings ... he
 * corrects on one page, his edits kept"). Nothing here reaches the lights.
 * spectra/services/sung_labels.py is the binding statement. */
import { useMemo, useState } from 'react';
import PowerButton from '../components/PowerButton';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';
import { useDraftMeanings, useSungLabelEdit, useSungLabelSettings, useSungLabels } from '../queries';
import type { SungChip, SungColorSet, SungEffect, SungListName, SungMeaningKind } from '../types';
import {
  SOURCE_WORDS, batches, draftButtonWords, draftableIds, filterCards, filterEffects, undraftedIds,
} from './sungLabels';

const MEANINGS: { key: SungMeaningKind; title: string }[] = [
  { key: 'things', title: 'Things' },
  { key: 'moods', title: 'Moods' },
  { key: 'places', title: 'Places' },
];

function WordList({
  title, chips, onAdd, onRemove,
}: {
  title: string;
  chips: SungChip[];
  onAdd: (text: string) => void;
  onRemove: (text: string) => void;
}) {
  const [text, setText] = useState('');
  const commit = () => {
    if (!text.trim()) return;
    onAdd(text.trim());
    setText('');
  };
  return (
    <div className="sung-list">
      <span className="sung-list-title">{title}</span>
      <div className="sung-chips">
        {chips.map((chip) => (
          <span key={chip.text} className={`sung-chip ${chip.source}`} title={SOURCE_WORDS[chip.source]}>
            {chip.text}
            <button type="button" aria-label={`Remove ${chip.text}`} onClick={() => onRemove(chip.text)}>×</button>
          </span>
        ))}
        <input
          className="sung-add"
          type="text"
          value={text}
          placeholder="add…"
          aria-label={`Add to ${title}`}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } }}
          onBlur={commit}
        />
      </div>
    </div>
  );
}

function ColourCard({
  card, edit, onDraft, canDraft, drafting,
}: {
  card: SungColorSet;
  edit: (list: SungListName, op: 'add' | 'remove', text: string) => void;
  onDraft: () => void;
  canDraft: boolean;
  drafting: boolean;
}) {
  return (
    <div className="card sung-card">
      <div className="sung-card-head">
        <span className="sung-swatch" style={{ background: card.swatch }} />
        <strong>{card.name}</strong>
        {card.kind === 'group' && <span className="sung-tag">Group</span>}
        {card.disabled && <span className="sung-tag">Off</span>}
        {!card.has_colours && <span className="sung-tag">No colours of its own</span>}
        {card.has_colours && (
          <button type="button" className="sung-redraft" disabled={!canDraft || drafting} onClick={onDraft}>
            {card.drafted_ms == null ? 'Draft' : 'Draft again'}
          </button>
        )}
      </div>
      <WordList title="Sung labels" chips={card.labels}
                onAdd={(t) => edit('labels', 'add', t)} onRemove={(t) => edit('labels', 'remove', t)} />
      {card.has_colours && MEANINGS.map(({ key, title }) => (
        <WordList key={key} title={title} chips={card.meanings[key]}
                  onAdd={(t) => edit(key, 'add', t)} onRemove={(t) => edit(key, 'remove', t)} />
      ))}
    </div>
  );
}

function EffectCard({ effect, edit }: {
  effect: SungEffect;
  edit: (op: 'add' | 'remove', text: string) => void;
}) {
  return (
    <div className="card sung-card">
      <div className="sung-card-head"><strong>{effect.name}</strong></div>
      <WordList title="Sung labels" chips={effect.labels}
                onAdd={(t) => edit('add', t)} onRemove={(t) => edit('remove', t)} />
    </div>
  );
}

export default function SungLabelsPage() {
  const toast = useToast();
  const { data, error } = useSungLabels();
  const editLabel = useSungLabelEdit();
  const draft = useDraftMeanings();
  const settings = useSungLabelSettings();
  const [query, setQuery] = useState('');
  const [onlyUndrafted, setOnlyUndrafted] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);

  const cards = useMemo(() => filterCards(data?.color_sets ?? [], query, onlyUndrafted),
    [data, query, onlyUndrafted]);
  const effects = useMemo(() => filterEffects(data?.effects ?? [], query), [data, query]);

  if (error) return <div className="card"><p className="empty-note">{(error as Error).message}</p></div>;
  if (!data) return <div className="card"><p className="empty-note">Loading…</p></div>;

  const report = (err: unknown) => toast((err as Error)?.message ?? 'That did not work', 'error');
  const edit = (kind: 'color_set' | 'effect', id: string, list: SungListName, op: 'add' | 'remove', text: string) =>
    editLabel.mutate({ kind, id, list, op, text }, { onError: report });

  const draftIds = async (ids: string[]) => {
    const rounds = batches(ids, data.draft_batch_size);
    setProgress({ done: 0, total: ids.length });
    try {
      let done = 0;
      for (const ids_ of rounds) {
        await draft.mutateAsync(ids_);
        done += ids_.length;
        setProgress({ done, total: ids.length });
      }
    } catch (err) {
      report(err);
    } finally {
      setProgress(null);
    }
  };

  const undrafted = undraftedIds(data.color_sets);
  const draftable = draftableIds(data.color_sets);
  const pressDraft = () => {
    if (undrafted.length) { void draftIds(undrafted); return; }
    if (window.confirm(`Ask Claude to draft all ${draftable.length} colour sets again? Your own edits are kept.`)) {
      void draftIds(draftable);
    }
  };
  const drafting = progress != null;

  return (
    <div>
      <div className="card">
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          Sung labels <HelpLink topic="sung-labels" />
        </div>
        <p className="sung-intro">
          What each colour set and effect answers to when it is sung. Claude reads a song's lyrics against
          this list and guesses which words are about what. Nothing here reaches your lights yet.
        </p>
        <div className="sung-toolbar">
          <input
            type="text"
            value={query}
            placeholder="Search names and words"
            aria-label="Search names and words"
            onChange={(e) => setQuery(e.target.value)}
          />
          <label className="sung-check">
            <input type="checkbox" checked={onlyUndrafted} onChange={(e) => setOnlyUndrafted(e.target.checked)} />
            Only sets waiting for a draft
          </label>
          <button type="button" onClick={pressDraft} disabled={!data.claude.available || drafting || !draftable.length}>
            {progress ? `Drafting… ${progress.done} of ${progress.total}` : draftButtonWords(undrafted.length, draftable.length)}
          </button>
          <span className="sung-count">{data.n_labels} distinct words</span>
        </div>
        {!data.claude.available && <p className="sung-unavailable">{data.claude.reason}</p>}
        <div className="sung-auto">
          <PowerButton
            on={data.auto_read}
            onChange={(on) => settings.mutate({ auto_read: on }, { onError: report })}
            ariaLabel="reading songs automatically"
            title={data.auto_read ? 'Reading songs automatically' : 'Songs are read only when you press Read'}
          />
          <span>
            Read songs automatically when these words change. Off, Claude reads a song only when you press Read on
            the test bed. On, it goes through one song a minute, which spends your Claude allowance.
          </span>
          <HelpLink topic="sung-labels-reading" title="Reading songs" />
        </div>
        <div className="sung-legend">
          <span className="sung-chip seed">from its colours and name</span>
          <span className="sung-chip claude">drafted by Claude</span>
          <span className="sung-chip his">yours</span>
          <HelpLink topic="sung-labels-page" title="Correcting the words" />
        </div>
      </div>

      <h2 className="sung-heading">Colour sets ({cards.length})</h2>
      {cards.map((card) => (
        <ColourCard
          key={card.id}
          card={card}
          edit={(list, op, text) => edit('color_set', card.id, list, op, text)}
          onDraft={() => void draftIds([card.id])}
          canDraft={data.claude.available}
          drafting={drafting}
        />
      ))}
      {!cards.length && <p className="empty-note">Nothing matches.</p>}

      <h2 className="sung-heading">Effects ({effects.length})</h2>
      {effects.map((effect) => (
        <EffectCard key={effect.id} effect={effect}
                    edit={(op, text) => edit('effect', effect.id, 'labels', op, text)} />
      ))}
    </div>
  );
}
