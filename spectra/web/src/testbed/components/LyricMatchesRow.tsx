/** The matched words as a row on the Sung words lane: one chip per match, under
 * the words it sits on. His are solid, Claude's guesses dashed, and a match on
 * a word below the page's sensitivity is dimmer.
 *
 * Pure presentation (scripts/check_testbed_lyric_matches.mjs renders it with
 * react-dom/server); LyricMatchesSection.tsx holds the data and the panels. */
import { useEffect, useMemo, useState } from 'react';
import { fmtMsTenths } from '../../lib/time';
import type { LyricMatch } from '../../types';
import { chipText, isEmphasized, layoutMatches, provenanceWords } from '../lyricMatches';
import { viewPct } from '../lyricsLane';
import type { LaneView } from '../lyricsLane';

const FALLBACK_WIDTH_PX = 1000;
const ROW_PX = 19;

export default function LyricMatchesRow({
  matches, view, sensitivity, selectedId, onSelect,
}: {
  matches: LyricMatch[];
  view: LaneView;
  sensitivity: number;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
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

  const chips = useMemo(() => layoutMatches(matches, view, widthPx), [matches, view, widthPx]);

  return (
    <div className="testbed-lane-row">
      <span className="testbed-lane-label" title="Word matches">Word matches</span>
      <div ref={setBarEl} className="testbed-lane-bar testbed-match-lane">
        {chips.map(({ match, placement }) => {
          const swatch = match.targets[0]?.swatch ?? undefined;
          const title = `${fmtMsTenths(match.ms)} · ${match.phrase} → ${match.label} · ${provenanceWords(match)}`;
          const classes = ['testbed-match', match.source,
            isEmphasized(match, sensitivity) ? '' : 'dim',
            match.id === selectedId ? 'selected' : ''].filter(Boolean).join(' ');
          const leftPct = viewPct(view, match.ms);
          if (!placement) {
            return (
              <button
                key={match.id}
                type="button"
                className={`${classes} tick`}
                style={{ left: `${leftPct}%`, background: swatch }}
                data-ms={match.ms}
                title={title}
                aria-label={title}
                onClick={() => onSelect(match.id === selectedId ? null : match.id)}
              />
            );
          }
          return (
            <button
              key={match.id}
              type="button"
              className={classes}
              style={{ left: placement.leftPx, top: 2 + placement.row * ROW_PX, maxWidth: placement.widthPx }}
              data-ms={match.ms}
              title={title}
              onClick={() => onSelect(match.id === selectedId ? null : match.id)}
            >
              {swatch && <span className="testbed-match-swatch" style={{ background: swatch }} />}
              <span className="testbed-match-text">{chipText(match)}</span>
            </button>
          );
        })}
        {!chips.length && <span className="testbed-lane-empty-hint">No matches here</span>}
      </div>
    </div>
  );
}
