/** Word actions as a row on the Sung words lane: what each matched word would
 * do. Pure presentation; LyricEventsSection.tsx holds the data and the panels. */
import { useEffect, useMemo, useState } from 'react';
import { fmtMsTenths } from '../../lib/time';
import type { LyricEventAction } from '../../types';
import { actionChipLabel, layoutActions, satOut } from '../lyricEvents';
import { viewPct } from '../lyricsLane';
import type { LaneView } from '../lyricsLane';

const FALLBACK_WIDTH_PX = 1000;
const ROW_PX = 19;

export default function LyricEventsRow({
  actions, view, selectedKey, onSelect,
}: {
  actions: LyricEventAction[];
  view: LaneView;
  selectedKey: string | null;
  onSelect: (key: string | null) => void;
}) {
  const [barEl, setBarEl] = useState<HTMLDivElement | null>(null);
  const [widthPx, setWidthPx] = useState(FALLBACK_WIDTH_PX);

  useEffect(() => {
    if (!barEl || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver((entries) => {
      const width = entries[entries.length - 1]?.contentRect.width;
      if (width) setWidthPx(width);
    });
    observer.observe(barEl);
    return () => observer.disconnect();
  }, [barEl]);

  const chips = useMemo(() => layoutActions(actions, view, widthPx), [actions, view, widthPx]);

  return (
    <div className="testbed-lane-row">
      <span className="testbed-lane-label" title="What each word would do">Word actions</span>
      <div ref={setBarEl} className="testbed-lane-bar testbed-match-lane">
        {chips.map(({ action, placement }) => {
          const title = `${fmtMsTenths(action.ms)} · ${action.phrase} · ${action.words}`;
          const classes = ['testbed-word-action', action.verdict, satOut(action) ? 'sat-out' : '',
            action.key === selectedKey ? 'selected' : ''].filter(Boolean).join(' ');
          const select = () => onSelect(action.key === selectedKey ? null : action.key);
          if (!placement) {
            return (
              <button key={action.key} type="button" className={`${classes} tick`}
                      style={{ left: `${viewPct(view, action.ms)}%` }}
                      data-ms={action.ms} title={title} aria-label={title} onClick={select} />
            );
          }
          return (
            <button key={action.key} type="button" className={classes}
                    style={{ left: placement.leftPx, top: 2 + placement.row * ROW_PX, maxWidth: placement.widthPx }}
                    data-ms={action.ms} title={title} onClick={select}>
              <span className="testbed-match-text">{actionChipLabel(action)}</span>
            </button>
          );
        })}
        {!chips.length && <span className="testbed-lane-empty-hint">No matched words here</span>}
      </div>
    </div>
  );
}
