/** The Sung words lane's matches, with everything he does to them: read the
 * song, select a match and delete it, add one by picking words. Matches reach
 * the lights only on a show with Word colours turned on (LyricEventsSection).
 * spectra/services/lyric_matches.py is the binding statement. */
import { useEffect, useMemo, useState } from 'react';
import SearchSelect from '../../components/forms/SearchSelect';
import type { SearchOption } from '../../components/forms/SearchSelect';
import { useToast } from '../../components/Toast';
import HelpLink from '../../help/HelpLink';
import {
  useAddLyricMatch, useDeleteLyricMatch, useLyricMatches, useReadLyrics,
  useRestoreDeletedLyricMatches, useSetLyricMatchPin, useSungLabels,
} from '../../queries';
import type { SungLabelsPageData, TestbedLyricWord } from '../../types';
import {
  MAX_PICKABLE_WORDS, nextPick, pickableWords, pickedPhrase, provenanceWords, readButtonWords,
  readingWords, targetsWords,
} from '../lyricMatches';
import type { PickState } from '../lyricMatches';
import type { LaneView } from '../lyricsLane';
import LyricMatchesRow from './LyricMatchesRow';
import PinControl from './PinControl';

function targetOptions(page: SungLabelsPageData | undefined): SearchOption[] {
  if (!page) return [];
  return [
    ...page.color_sets.map((c) => ({
      value: `color_set|${c.id}`, label: `${c.kind === 'group' ? '▤ ' : ''}${c.name}`,
      group: 'Colour set', keywords: c.labels.map((l) => l.text).join(' '),
    })),
    ...page.effects.map((e) => ({
      value: `effect|${e.id}`, label: e.name, group: 'Effect',
      keywords: e.labels.map((l) => l.text).join(' '),
    })),
  ];
}

export default function LyricMatchesSection({
  uri, words, view, sensitivity,
}: {
  uri: string;
  words: TestbedLyricWord[];
  view: LaneView;
  sensitivity: number;
}) {
  const toast = useToast();
  const { data } = useLyricMatches(uri, true);
  const read = useReadLyrics();
  const add = useAddLyricMatch();
  const del = useDeleteLyricMatch();
  const restore = useRestoreDeletedLyricMatches();
  const pin = useSetLyricMatchPin();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [pick, setPick] = useState<PickState>({ first: null, last: null });
  const [target, setTarget] = useState('');
  const { data: labels } = useSungLabels(adding);

  useEffect(() => {
    setSelectedId(null);
    setAdding(false);
    setPick({ first: null, last: null });
    setTarget('');
  }, [uri]);

  const pickable = useMemo(() => pickableWords(words, view), [words, view]);
  const options = useMemo(() => targetOptions(labels), [labels]);
  const selected = data?.matches.find((m) => m.id === selectedId) ?? null;

  if (!data || data.status !== 'ok') return null;

  const report = (err: unknown) => toast((err as Error)?.message ?? 'That did not work', 'error');
  const readSong = () => read.mutate(uri, { onError: report });
  const removeSelected = () => {
    if (!selected) return;
    del.mutate({ uri, id: selected.id }, { onSuccess: () => setSelectedId(null), onError: report });
  };
  const addPicked = () => {
    if (pick.first == null || pick.last == null || !target) return;
    const [kind, id] = target.split('|') as ['color_set' | 'effect', string];
    add.mutate({ uri, first_word: pick.first, last_word: pick.last, target: { kind, id } }, {
      onSuccess: () => { setAdding(false); setPick({ first: null, last: null }); setTarget(''); },
      onError: report,
    });
  };

  return (
    <div className="testbed-match-section">
      <div className="testbed-lane-row">
        <span className="testbed-lane-label" />
        <div className="testbed-match-status">
          <span>{readingWords(data, Date.now())}</span>
          {data.claude.available ? (
            <button type="button" onClick={readSong} disabled={read.isPending}>
              {read.isPending ? 'Reading…' : readButtonWords(data.state)}
            </button>
          ) : (
            <span className="testbed-match-unavailable">{data.claude.reason}</span>
          )}
          <button type="button" onClick={() => { setAdding(!adding); setSelectedId(null); }}>
            {adding ? 'Cancel' : '+ Add a match'}
          </button>
          {data.n_deleted > 0 && (
            <button type="button" className="testbed-match-link"
                    onClick={() => restore.mutate(uri, { onError: report })}>
              Bring back {data.n_deleted} deleted
            </button>
          )}
          <span className="testbed-match-note">Guesses only. They reach your lights only on a show you turn on below.</span>
          <HelpLink topic="testbed-lyric-matches" title="Word matches" />
        </div>
      </div>

      <LyricMatchesRow
        matches={data.matches}
        view={view}
        sensitivity={sensitivity}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />

      {data.unplaced.length > 0 && (
        <div className="testbed-lane-row">
          <span className="testbed-lane-label" />
          <p className="testbed-lyrics-flag">
            {data.unplaced.length === 1 ? 'One of your matches is' : `${data.unplaced.length} of your matches are`}{' '}
            on words this capture no longer has ({data.unplaced.map((u) => `"${u.phrase}"`).join(', ')}).
            They are kept, and come back if the words do.
          </p>
        </div>
      )}

      {selected && (
        <div className="testbed-lane-row">
          <span className="testbed-lane-label" />
          <div className="testbed-match-panel">
            <div><strong>{selected.phrase}</strong> → {selected.label}</div>
            <div className="testbed-match-detail">{provenanceWords(selected)}</div>
            {selected.why && <div className="testbed-match-detail">{selected.why}</div>}
            <div className="testbed-match-detail">Would reach: {targetsWords(selected)}</div>
            <PinControl
              pin={selected.pin}
              chance={selected.source === 'his' ? 1 : selected.confidence}
              busy={pin.isPending}
              onPin={(choice) => pin.mutate({ uri, id: selected.id, pin: choice }, { onError: report })}
            />
            <button type="button" onClick={removeSelected} disabled={del.isPending}>Delete this match</button>
          </div>
        </div>
      )}

      {adding && (
        <div className="testbed-lane-row">
          <span className="testbed-lane-label" />
          <div className="testbed-match-panel">
            <div className="testbed-match-detail">
              Tap the first word, then the last word of a phrase, from what the lanes are showing.
              {pickable.length > MAX_PICKABLE_WORDS && ' Zoom in to reach them all.'}
            </div>
            <div className="testbed-match-words">
              {pickable.slice(0, MAX_PICKABLE_WORDS).map(({ word, index }) => {
                const on = pick.first != null && pick.last != null && index >= pick.first && index <= pick.last;
                return (
                  <button
                    key={`${index}:${word.word}`}
                    type="button"
                    className={on ? 'on' : ''}
                    aria-pressed={on}
                    onClick={() => setPick(nextPick(pick, index))}
                  >
                    {word.word}
                  </button>
                );
              })}
              {!pickable.length && <span className="testbed-match-detail">No words sung in this window.</span>}
            </div>
            {pick.first != null && (
              <div className="testbed-match-add">
                <span>"{pickedPhrase(words, pick)}" means</span>
                <SearchSelect value={target} onChange={setTarget} options={options}
                              placeholder="Pick a colour set or effect" width={260} />
                <button type="button" onClick={addPicked} disabled={!target || add.isPending}>Add</button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
