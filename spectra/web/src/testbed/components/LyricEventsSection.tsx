/** Word colours on this show: the switch, the three tuning sliders, and what
 * each matched word would do. spectra/services/lyric_events.py is the binding
 * statement. Off for every show until it is turned on here. */
import { useEffect, useState } from 'react';
import { useToast } from '../../components/Toast';
import HelpLink from '../../help/HelpLink';
import { useLyricEvents, useSetLyricEventSettings, useSetLyricEventsShow } from '../../queries';
import type { LyricEventSettings } from '../../types';
import { ENERGY_CUTOFF, IMPRINT_WINDOW_S, MIN_GAP_S, reachWords, summaryWords } from '../lyricEvents';
import type { LaneView } from '../lyricsLane';
import LyricEventsRow from './LyricEventsRow';

function Slider({
  label, value, range, unit, onCommit,
}: {
  label: string;
  value: number;
  range: { min: number; max: number; step: number };
  unit?: string;
  onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => { if (draft !== value) onCommit(draft); };
  return (
    <label className="testbed-word-slider">
      <span>{label}</span>
      <input type="range" min={range.min} max={range.max} step={range.step} value={draft}
             onChange={(e) => setDraft(Number(e.target.value))}
             onPointerUp={commit} onKeyUp={commit} onBlur={commit} />
      <span className="testbed-word-slider-value">{draft}{unit ?? ''}</span>
    </label>
  );
}

export default function LyricEventsSection({ uri, view }: { uri: string; view: LaneView }) {
  const toast = useToast();
  const { data } = useLyricEvents(uri, true);
  const setShow = useSetLyricEventsShow();
  const setSettings = useSetLyricEventSettings();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  useEffect(() => setSelectedKey(null), [uri]);

  if (!data || data.status !== 'ok') return null;
  const report = (err: unknown) => toast((err as Error)?.message ?? 'That did not work', 'error');
  const selected = data.actions.find((a) => a.key === selectedKey) ?? null;
  const tune = (patch: Partial<LyricEventSettings>) =>
    setSettings.mutate(patch, { onError: report });

  return (
    <div className="testbed-match-section">
      <div className="testbed-lane-row">
        <span className="testbed-lane-label" />
        <div className="testbed-match-status">
          <label className="testbed-word-switch">
            <input type="checkbox" checked={data.enabled} disabled={setShow.isPending}
                   onChange={(e) => setShow.mutate({ uri, enabled: e.target.checked }, { onError: report })} />
            Word colours on this show
          </label>
          <span className={data.enabled ? 'testbed-word-state on' : 'testbed-word-state'}>
            {data.enabled ? 'On: these words change colours in the room' : 'Off: nothing reaches your lights'}
          </span>
          <span>{summaryWords(data.actions)}. Events in this song: {data.n_events}.</span>
          {data.clock_flagged && (
            <span className="testbed-match-unavailable">
              This capture&apos;s clock is flagged: these chips are right, the waveform above is not.
            </span>
          )}
          <HelpLink topic="testbed-word-colours" title="Word colours" />
        </div>
      </div>
      <div className="testbed-lane-row">
        <span className="testbed-lane-label" />
        <div className="testbed-word-sliders">
          <Slider label="Energy cut-off" value={data.settings.energy_cutoff} range={ENERGY_CUTOFF}
                  onCommit={(energy_cutoff) => tune({ energy_cutoff })} />
          <Slider label="Minimum gap" value={data.settings.min_gap_s} range={MIN_GAP_S} unit=" s"
                  onCommit={(min_gap_s) => tune({ min_gap_s })} />
          <Slider label="Imprint window" value={data.settings.imprint_window_s} range={IMPRINT_WINDOW_S} unit=" s"
                  onCommit={(imprint_window_s) => tune({ imprint_window_s })} />
        </div>
      </div>
      <LyricEventsRow actions={data.actions} view={view} selectedKey={selectedKey} onSelect={setSelectedKey} />
      {selected && (
        <div className="testbed-lane-row">
          <span className="testbed-lane-label" />
          <div className="testbed-match-panel">
            <div><strong>{selected.phrase}</strong> → {selected.label}</div>
            <div className="testbed-match-detail">{selected.words}</div>
            <div className="testbed-match-detail">{reachWords(selected)}</div>
            {selected.verdict !== 'nothing' && (
              <div className="testbed-match-detail">
                Whether a colour lands also depends on the scene showing at that moment and on what
                is holding the room&apos;s colours, which the show log records each time.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
