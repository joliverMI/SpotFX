/** The Sung words lane (lyrics plan, step 2): every sung word drawn faintly,
 * the emphasized ones as marks with the word printed on them, and his flares
 * and scene changes as guide lines through it, all at their stored times on
 * the capture's label clock, so a word and a flare that happen together in
 * the room share one x. spectra/services/lyrics_timeline.py's module
 * docstring is the binding statement for the clock.
 *
 * READ-ONLY, deliberately not clickable: unlike every other engine lane
 * there is no push-to-real here, because this lane has no effect on the room.
 *
 * WHERE THE CLOCK CANNOT BE TRUSTED IT SAYS SO. A flagged song keeps its
 * words but loses the guides, and the words go grey. A song with no usable
 * timeline says which of the reasons it is instead of showing an empty lane.
 *
 * `matched_label` on a mark is the chip's place: the label step of the plan
 * fills it, nothing does yet.
 *
 * The bar's width is measured with a state-backed callback ref rather than a
 * plain useRef (AGENTS.md: an element mounted conditionally can be null on the
 * render its measuring effect depends on, and nothing would retry). */
import { useEffect, useMemo, useState } from 'react';
import { fmtMsTenths } from '../../lib/time';
import type {
  TestbedEstimateMark, TestbedLyrics, TestbedMetrics, TestbedReferenceMark,
} from '../../types';
import {
  faintWordFits, faintWordReachMs, featureWords, inView, layoutLabelRows, viewPct,
} from '../lyricsLane';
import type { LaneView } from '../lyricsLane';

const FALLBACK_LANE_WIDTH_PX = 1000;
const LABEL_ROW_PX = 15;

function EmptyLyricsLane({ label, note }: { label: string; note: string }) {
  return (
    <div className="testbed-lane-row">
      <span className="testbed-lane-label" title={label}>{label}</span>
      <div className="testbed-lane-bar testbed-lane-note">
        <span className="empty-note" style={{ fontSize: 11 }}>{note}</span>
      </div>
    </div>
  );
}

export default function LyricsLane({
  label, data, estimate, view, metrics, transitions, flares,
}: {
  label: string;
  data: TestbedLyrics | undefined;
  /** The emphasized words at the page's sensitivity, from /engine-marks. */
  estimate: TestbedEstimateMark[];
  view: LaneView;
  metrics: TestbedMetrics | null | undefined;
  transitions: TestbedReferenceMark[];
  flares: TestbedReferenceMark[];
}) {
  const [barEl, setBarEl] = useState<HTMLDivElement | null>(null);
  const [laneWidthPx, setLaneWidthPx] = useState(FALLBACK_LANE_WIDTH_PX);
  const [hover, setHover] = useState<{ text: string; leftPct: string } | null>(null);

  useEffect(() => {
    if (!barEl || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver((entries) => {
      const width = entries[entries.length - 1]?.contentRect.width;
      if (width) setLaneWidthPx(width);
    });
    observer.observe(barEl);
    return () => observer.disconnect();
  }, [barEl]);

  const words = data?.words ?? [];
  const flagged = !!data?.clock.flagged;
  const shownWords = useMemo(
    () => words
      .map((w, i) => ({ w, row: i % 2, reachMs: faintWordReachMs(words, i) }))
      .filter(({ w }) => inView(view, w.ms, w.end_ms)),
    [words, view],
  );
  const matched = useMemo(
    () => new Set(metrics?.matches.map((m) => m.est_index) ?? []),
    [metrics],
  );
  const shownMarks = useMemo(
    () => estimate
      .map((m, index) => ({ m, index }))
      .filter(({ m }) => inView(view, m.time_ms, m.detail?.end_ms ?? m.time_ms)),
    [estimate, view],
  );
  const placements = useMemo(
    () => layoutLabelRows(
      shownMarks.map(({ m }) => ({
        xPx: (viewPct(view, m.time_ms) / 100) * laneWidthPx,
        text: m.label ?? '',
        score: m.score ?? 0,
      })),
      laneWidthPx,
    ),
    [shownMarks, view, laneWidthPx],
  );

  if (!data) return <EmptyLyricsLane label={label} note="Loading the sung words…" />;
  if (data.status !== 'ok') {
    return <EmptyLyricsLane label={label} note={data.note ?? 'No sung words for this song.'} />;
  }

  const pct = (ms: number) => `${viewPct(view, ms)}%`;
  const msPerPx = (view.endMs - view.startMs) / Math.max(1, laneWidthPx);
  const guides = flagged ? [] : [
    ...transitions.map((m) => ({ id: m.id, ms: m.timestamp_ms, cls: 'scene' })),
    ...flares.map((m) => ({ id: m.id, ms: m.timestamp_ms, cls: 'flare' })),
  ].filter((g) => inView(view, g.ms));

  return (
    <>
    {flagged && (
      <div className="testbed-lane-row">
        <span className="testbed-lane-label" />
        <p className="testbed-lyrics-flag">{data.clock.note}</p>
      </div>
    )}
    <div className="testbed-lane-row">
      <span className="testbed-lane-label" title={label}>{label}</span>
      <div
        ref={setBarEl}
        className={`testbed-lane-bar testbed-lyrics-lane${flagged ? ' flagged' : ''}`}
      >
        {hover && <div className="review-lane-tooltip" style={{ left: hover.leftPct }}>{hover.text}</div>}
        {guides.map((g) => (
          <span key={g.id} className={`testbed-lyric-guide ${g.cls}`} style={{ left: pct(g.ms) }} data-ms={g.ms} />
        ))}
        {shownWords.map(({ w, reachMs, row }) => {
          const showText = faintWordFits(w.word, reachMs / msPerPx);
          return (
            <span key={`${w.ms}:${w.word}`}>
              <span
                className="testbed-lyric-word"
                style={{ left: pct(w.ms), width: `${Math.max(1, (w.end_ms - w.ms) / msPerPx)}px` }}
                title={w.word}
              />
              {showText && (
                <span className={`testbed-lyric-word-text row-${row}`} style={{ left: pct(w.ms) }}>
                  {w.word}
                </span>
              )}
            </span>
          );
        })}
        {shownMarks.map(({ m, index }, i) => {
          const placed = placements[i];
          const why = featureWords(m.detail?.features);
          const text = `${fmtMsTenths(m.time_ms)} · ${m.label ?? ''}`
            + ` · score ${(m.score ?? 0).toFixed(2)}${why ? ` — ${why}` : ''}`;
          return (
            <div
              key={`${m.time_ms}:${m.label}`}
              className={`testbed-lyric-mark${matched.has(index) ? ' matched' : ''}`}
              style={{ left: pct(m.time_ms) }}
              data-ms={m.time_ms}
              role="img"
              aria-label={text}
              onPointerEnter={() => setHover({ text, leftPct: pct(m.time_ms) })}
              onPointerLeave={() => setHover(null)}
            >
              {placed && (
                <span
                  className="testbed-lyric-label"
                  style={{
                    top: placed.row * LABEL_ROW_PX,
                    left: placed.leftPx - (viewPct(view, m.time_ms) / 100) * laneWidthPx,
                  }}
                >
                  {m.label}
                  {m.detail?.matched_label && (
                    <span className="testbed-lyric-chip">{m.detail.matched_label}</span>
                  )}
                </span>
              )}
            </div>
          );
        })}
        {!placements.length && !shownWords.length && (
          <span className="testbed-lane-empty-hint">No words sung here</span>
        )}
      </div>
    </div>
    </>
  );
}
