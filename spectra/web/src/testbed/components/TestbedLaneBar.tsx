/** Read-only stacked lanes for the music-analysis test bed — the
 * ReviewLaneBar family (spectra/web/src/review/components/ReviewLaneBar.tsx)
 * generalized from one lane to N: a waveform/energy lane, his real marks
 * (transitions + flares), and one lane per selected candidate engine. No
 * drag/edit — this is a comparison surface, never an authoring one, per
 * data/spotfx-music-analysis-plan/report.md's own Part 3 "What it does
 * NOT do."
 *
 * Tint convention (the report's own Part 3 item 4: "tint each of his
 * marks green/yellow/red"): matched within half the tolerance = green
 * ("matched-tight"), matched but in the looser half = amber
 * ("matched-loose"), unmatched = red. An engine's own OVER-segmented marks
 * (no match to any of his) render dim/muted, not red — they aren't wrong,
 * just extra (report Part 1.2's own reading). A mark this page itself
 * pushed to his real triggers renders as its own "promoted" tint and is
 * labelled excluded-from-scoring: it sits at the suggesting engine's exact
 * time, so it is deliberately not in the matched set (see
 * spectra/services/testbed_marks.py).
 *
 * EVERY LANE IS THE SAME ms -> % SCALE. `durationMs` is the one timebase;
 * a lane that positioned its own content by index (the waveform's buckets)
 * instead of by TIME would drift against every mark lane beside it, which
 * is the one thing a comparison surface must not do.
 *
 * AND THE WAVEFORM'S OWN ZERO IS NOT THE SONG'S. A production capture
 * starts MID-SONG, so the pinned WAV's first sample sits at
 * `capture_offset_ms` in song time; drawing it from x=0 puts a real
 * transient EARLIER than the mark that names it, by the capture lag. When
 * the backend cannot establish that offset the lane SAYS SO rather than
 * implying an alignment it cannot justify.
 *
 * A MARK THAT CARRIES A GLYPH IS DRAWN AS ITS KIND (the Pre-drops lane,
 * predrop plan step 3: a spike and a vocal intro each get the glyph the
 * Drops panel draws for them), tinted like any other mark; a suggested one
 * is drawn fainter, as a suggested drop is. */
import { useMemo, useState } from 'react';
import Icon, { type IconName } from '../../components/Icon';
import { fmtMs } from '../../lib/time';
import { useLyricEvents } from '../../queries';
import type {
  TestbedEstimateMark, TestbedLyrics, TestbedMetrics, TestbedReferenceMark, TestbedWaveform,
} from '../../types';
import { wordEvents, wordEventText, type WordEvent } from '../lyricEvents';
import { inView, viewPct, wholeSong } from '../lyricsLane';
import type { LaneView } from '../lyricsLane';
import LyricEventsSection from './LyricEventsSection';
import LyricMatchesSection from './LyricMatchesSection';
import LyricsLane, { type LaneGuide } from './LyricsLane';

/** A glyph-carrying mark's icon: the pre-drop kinds (the Drops panel's own). */
export const MARK_GLYPH: Record<string, IconName> = { spike: 'preDrop', intro: 'preDropVoice' };

function tintFor(offsetMs: number | undefined, toleranceMs: number): string {
  if (offsetMs == null) return 'unmatched';
  return offsetMs <= toleranceMs / 2 ? 'matched-tight' : 'matched-loose';
}

/** Where the pinned WAV sits on the SONG's timebase: bucket i covers
 * `offset + (i / (n-1)) * spanMs` ms, the same ms -> % mapping every mark
 * lane uses. `offset` is the capture's own start in song time; `spanMs` is
 * the WAV's own length (an engine's beats can run past a capture that was
 * trimmed, so `dur` is often the longer one). A missing duration falls back
 * to the rest of the lane rather than collapsing it to nothing, and is
 * reported as unpositioned. */
function waveformPlacement(waveform: TestbedWaveform, dur: number) {
  const waveDur = waveform.duration_ms ?? 0;
  const offsetMs = waveform.capture_offset_ms;
  const offsetKnown = offsetMs != null && Number.isFinite(offsetMs);
  const startMs = offsetKnown ? Math.max(0, Math.min(dur, offsetMs!)) : 0;
  const spanMs = waveDur > 0 ? Math.max(0, Math.min(dur - startMs, waveDur)) : dur - startMs;
  return { startMs, spanMs, offsetKnown, offsetMs: offsetKnown ? offsetMs! : 0 };
}

function WaveformLane({ waveform, durationMs, view }: {
  waveform: TestbedWaveform | undefined; durationMs: number; view?: LaneView;
}) {
  if (!waveform || waveform.source === 'none') {
    return (
      <div className="testbed-lane-row">
        <span className="testbed-lane-label">Waveform</span>
        <div className="testbed-lane-bar testbed-lane-waveform" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <span className="empty-note" style={{ fontSize: 11 }}>
            no waveform or coarse energy shape available for this song
          </span>
        </div>
      </div>
    );
  }
  const dur = Math.max(1, durationMs);
  const shown = view ?? wholeSong(dur);
  if (waveform.source === 'wav_peaks' && waveform.mins && waveform.maxs) {
    const n = waveform.mins.length;
    const { startMs, spanMs, offsetKnown, offsetMs } = waveformPlacement(waveform, dur);
    const points = waveform.mins.flatMap((min, i) => {
      const ms = startMs + (i / Math.max(1, n - 1)) * spanMs;
      if (!inView(shown, ms)) return [];
      return [{ x: viewPct(shown, ms), min, max: waveform.maxs![i] }];
    });
    return (
      <div className="testbed-lane-row">
        <span className="testbed-lane-label">
          {offsetKnown ? 'Waveform (retained WAV)' : 'Waveform (start time unknown)'}
        </span>
        <div
          className="testbed-lane-bar testbed-lane-waveform"
          title={offsetKnown
            ? `Retained WAV, starting at ${fmtMs(offsetMs)} in the song`
            : 'Retained WAV — this capture\'s start time in the song is unknown'}
        >
          {!offsetKnown && (
            <span className="testbed-waveform-caption">
              this capture&apos;s start time in the song is unknown — drawn from 0, so
              it is NOT aligned with the mark lanes
            </span>
          )}
          <svg className="testbed-waveform-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
            {points.map((p, i) => (
              <line
                key={i}
                x1={p.x} x2={p.x}
                y1={50 - p.max * 48} y2={50 - p.min * 48}
                stroke={offsetKnown ? 'var(--accent)' : 'var(--text-muted)'} strokeWidth="0.4"
              />
            ))}
          </svg>
        </div>
      </div>
    );
  }
  // npz RMS-envelope fallback — the report's own Methodology-named case.
  const ts = waveform.timestamps_ms ?? [];
  const rms = waveform.rms_total ?? [];
  const points = ts.flatMap((t, i) => (inView(shown, t)
    ? [`${viewPct(shown, t)},${100 - Math.min(1, rms[i] ?? 0) * 100}`] : [])).join(' ');
  return (
    <div className="testbed-lane-row">
      <span className="testbed-lane-label">Energy (coarse — no WAV)</span>
      <div className="testbed-lane-bar testbed-lane-waveform">
        <svg className="testbed-waveform-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polyline points={points} fill="none" stroke="var(--warning)" strokeWidth="0.6" />
        </svg>
      </div>
    </div>
  );
}

function ReferenceMarksLane({
  label, marks, scoredMarks, durationMs, view, metrics, toleranceMs, hover, setHover, emptyNote,
}: {
  label: string;
  marks: TestbedReferenceMark[];
  /** The exact array `metrics` was computed over — promoted marks already
   * dropped. `metrics.matches[].ref_index` indexes into THIS, not into
   * `marks`, so a tint is resolved by mark id rather than by position. */
  scoredMarks: TestbedReferenceMark[];
  durationMs: number;
  view?: LaneView;
  metrics: TestbedMetrics | null | undefined;
  toleranceMs: number;
  hover: { text: string; leftPct: string } | null;
  setHover: (h: { text: string; leftPct: string } | null) => void;
  emptyNote?: string;
}) {
  const shown = view ?? wholeSong(durationMs);
  const pct = (ms: number) => `${viewPct(shown, ms)}%`;
  const offsetById = new Map<string, number>();
  metrics?.matches.forEach((m) => {
    const scored = scoredMarks[m.ref_index];
    if (scored) offsetById.set(scored.id, m.abs_offset_ms);
  });
  if (marks.length === 0 && emptyNote) {
    return (
      <div className="testbed-lane-row">
        <span className="testbed-lane-label">{label}</span>
        <div className="testbed-lane-bar" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <span className="empty-note" style={{ fontSize: 11 }}>{emptyNote}</span>
        </div>
      </div>
    );
  }
  return (
    <div className="testbed-lane-row">
      <span className="testbed-lane-label">{label}</span>
      <div className="testbed-lane-bar">
        {hover && <div className="review-lane-tooltip" style={{ left: hover.leftPct }}>{hover.text}</div>}
        {marks.filter((m) => inView(shown, m.timestamp_ms)).map((m) => {
          const offset = offsetById.get(m.id);
          // 'unscored', never 'extra': the legend defines the dim/grey
          // swatch as an ENGINE mark with no match to any of his. With no
          // metrics (the selected engine has nothing precomputed for this
          // song) nothing has been compared at all, and painting his own
          // ground truth as the engine's over-segmentation is a lie.
          const tint = m.promoted ? 'promoted' : metrics ? tintFor(offset, toleranceMs) : 'unscored';
          const text = m.promoted
            ? `${fmtMs(m.timestamp_ms)} — ${m.kind} (pushed from this page — not scored)`
            : `${fmtMs(m.timestamp_ms)} — ${m.kind}${offset != null ? ` (matched, ${Math.round(offset)}ms off)` : metrics ? ' (no match)' : ''}`;
          return (
            <button
              key={m.id}
              type="button"
              className={`testbed-lane-marker ${tint}`}
              style={{ left: pct(m.timestamp_ms) }}
              onPointerEnter={() => setHover({ text, leftPct: pct(m.timestamp_ms) })}
              onPointerLeave={() => setHover(null)}
              aria-label={text}
            />
          );
        })}
      </div>
    </div>
  );
}

/** THE WORD EVENTS ROW (2026-11-12, data/word-effect-highlight-options; the
 * Admiral's answer to decision 5): the ENGINE'S OWN events a matched word
 * reaches — the same `TriggerEngine.preview_lyric_events` plan the Word
 * actions row below explains — each drawn as its kind the way the song
 * strip draws it, with a halo in the word's colour where a word imprints
 * on it, and a diamond in the word's colour where a word fires alone. It
 * REPLACES the two "His scene changes" / "His flares" rows, which drew his
 * stored marks: a different set from the events the plan can reach, so a
 * chip saying "→ scene" had no marker under it. The guide lines through
 * the Sung words lane above are these same events. */
function WordEventsRow({ events, view }: { events: WordEvent[]; view: LaneView }) {
  const [hover, setHover] = useState<{ text: string; leftPct: string } | null>(null);
  const pct = (ms: number) => `${viewPct(view, ms)}%`;
  const shown = events.filter((e) => inView(view, e.ms));
  return (
    <div className="testbed-lane-row">
      <span className="testbed-lane-label"
            title="The engine's own events near a matched word — haloed in the word's colour where a word gives it its colour">
        Word events
      </span>
      <div className="testbed-lane-bar">
        {hover && <div className="review-lane-tooltip" style={{ left: hover.leftPct }}>{hover.text}</div>}
        {shown.map((e) => {
          const text = wordEventText(e, fmtMs);
          const halo = e.swatch ?? undefined;
          return (
            <span
              key={e.id}
              role="img"
              aria-label={text}
              className={`testbed-word-event ${e.kind}${e.imprinted ? ' imprinted' : ''}${e.cannot ? ' cannot' : ''}`}
              style={{ left: pct(e.ms), ...(halo ? { '--halo': halo } as React.CSSProperties : {}) }}
              data-ms={e.ms}
              data-event-id={e.id}
              onPointerEnter={() => setHover({ text, leftPct: pct(e.ms) })}
              onPointerLeave={() => setHover(null)}
            />
          );
        })}
        {!shown.length && <span className="testbed-lane-empty-hint">No events near a matched word here</span>}
      </div>
    </div>
  );
}

/** The Sung words slot: the lane, the Word events row under it, then the
 * Word matches and Word actions sections. One `useLyricEvents` read serves
 * the lane's guide lines and the row; LyricEventsSection shares the cache. */
function LyricsGroup({ label, lane, lyrics, shown }: {
  label: string;
  lane: { estimate: TestbedEstimateMark[]; metrics: TestbedMetrics | null | undefined };
  lyrics: LyricsLaneInput;
  shown: LaneView;
}) {
  const ok = lyrics.data?.status === 'ok';
  const uri = lyrics.data?.uri ?? null;
  const { data: plan } = useLyricEvents(uri, ok);
  const events = useMemo(() => wordEvents(plan?.status === 'ok' ? plan.actions : []), [plan]);
  const guides = useMemo<LaneGuide[]>(
    () => events.map((e) => ({ id: e.id, ms: e.ms, cls: e.kind, halo: e.imprinted || e.kind === 'word' ? e.swatch : null })),
    [events]);
  const flagged = !!lyrics.data?.clock.flagged;
  return (
    <>
      <LyricsLane
        label={label}
        data={lyrics.data}
        estimate={lane.estimate}
        view={shown}
        metrics={lane.metrics}
        guides={guides}
      />
      {ok && !flagged && <WordEventsRow events={events} view={shown} />}
      {ok && lyrics.data && (
        <LyricMatchesSection
          uri={lyrics.data.uri}
          words={lyrics.data.words}
          view={shown}
          sensitivity={lyrics.sensitivity}
        />
      )}
      {ok && lyrics.data && <LyricEventsSection uri={lyrics.data.uri} view={shown} />}
    </>
  );
}

export function EngineLane({
  label, estimate, durationMs, view, metrics, onMarkClick,
}: {
  label: string;
  estimate: TestbedEstimateMark[];
  durationMs: number;
  view?: LaneView;
  metrics: TestbedMetrics | null | undefined;
  toleranceMs: number;
  onMarkClick?: (mark: TestbedEstimateMark) => void;
}) {
  const [hover, setHover] = useState<{ text: string; leftPct: string } | null>(null);
  const shown = view ?? wholeSong(durationMs);
  const pct = (ms: number) => `${viewPct(shown, ms)}%`;
  const matchedEstIndices = new Set(metrics?.matches.map((m) => m.est_index) ?? []);
  return (
    <div className="testbed-lane-row">
      <span className="testbed-lane-label" title={label}>{label}</span>
      <div className="testbed-lane-bar">
        {hover && <div className="review-lane-tooltip" style={{ left: hover.leftPct }}>{hover.text}</div>}
        {estimate.map((m, i) => {
          if (!inView(shown, m.time_ms)) return null;
          const matched = matchedEstIndices.has(i);
          // An engine's own label (a section name, a drop's tier) rides in
          // the tooltip; a drops-lane suggestion is drawn fainter.
          const text = `${fmtMs(m.time_ms)}${m.label ? ` · ${m.label}` : ''}`
            + `${matched ? ' (matched)' : ' (extra — no match to his marks)'}`;
          const glyph = m.glyph ? MARK_GLYPH[m.glyph] : undefined;
          const suggested = m.label === 'suggested' || m.tier === 'suggested';
          return (
            <button
              key={i}
              type="button"
              className={`testbed-lane-marker ${matched ? 'matched-tight' : 'extra'}`
                + `${suggested ? ' est-suggested' : ''}${glyph ? ' est-glyph' : ''}`}
              style={{ left: pct(m.time_ms) }}
              onPointerEnter={() => setHover({ text, leftPct: pct(m.time_ms) })}
              onPointerLeave={() => setHover(null)}
              onClick={() => onMarkClick?.(m)}
              aria-label={text}
              data-glyph={m.glyph}
              title={onMarkClick ? 'Click to review pushing this mark to your real triggers' : undefined}
            >
              {glyph && <Icon name={glyph} size={14} />}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export interface LyricsLaneInput {
  data: TestbedLyrics | undefined;
  /** The page's emphasis sensitivity, which dims matches on quieter words. */
  sensitivity: number;
}

export default function TestbedLaneBar({
  durationMs, view, waveform, referenceMarks, scoredMarks, referenceLabel,
  referenceEmptyNote, engineLanes, toleranceMs, onEstimateMarkClick,
}: {
  durationMs: number;
  /** The window every lane shows (the page's zoom); absent = the whole song. */
  view?: LaneView;
  waveform: TestbedWaveform | undefined;
  /** His marks of the ACTIVE reference set (transitions, flares, or his
   * drops / lulls / charges) — the page picks, this lane draws. */
  referenceMarks: TestbedReferenceMark[];
  /** The scored subset of the ACTIVE reference set — see ReferenceMarksLane. */
  scoredMarks: TestbedReferenceMark[];
  referenceLabel: string;
  referenceEmptyNote?: string;
  engineLanes: { key: string; label: string; estimate: TestbedEstimateMark[];
                metrics: TestbedMetrics | null | undefined;
                /** Set on a Sung words slot: it draws LyricsLane instead. */
                lyrics?: LyricsLaneInput }[];
  toleranceMs: number;
  onEstimateMarkClick?: (engineKey: string, mark: TestbedEstimateMark) => void;
}) {
  const [hover, setHover] = useState<{ text: string; leftPct: string } | null>(null);
  const activeMetrics = engineLanes[0]?.metrics; // the primary engine's own compare tints his marks
  const shown = view ?? wholeSong(durationMs);
  return (
    <div className="testbed-lane-stack">
      <WaveformLane waveform={waveform} durationMs={durationMs} view={shown} />
      <ReferenceMarksLane
        label={`His ${referenceLabel}`}
        marks={referenceMarks}
        scoredMarks={scoredMarks}
        durationMs={durationMs}
        view={shown}
        metrics={activeMetrics}
        toleranceMs={toleranceMs}
        hover={hover}
        setHover={setHover}
        emptyNote={referenceEmptyNote}
      />
      {engineLanes.map((lane) => (lane.lyrics ? (
        <div key={lane.key} className="testbed-lane-stack testbed-lyrics-group">
          <LyricsGroup label={lane.label} lane={lane} lyrics={lane.lyrics} shown={shown} />
        </div>
      ) : (
        <EngineLane
          key={lane.key}
          label={lane.label}
          estimate={lane.estimate}
          durationMs={durationMs}
          view={shown}
          metrics={lane.metrics}
          toleranceMs={toleranceMs}
          onMarkClick={onEstimateMarkClick ? (mark) => onEstimateMarkClick(lane.key, mark) : undefined}
        />
      )))}
      <div className="testbed-lane-times">
        <span>{fmtMs(shown.startMs)}</span>
        <span>{fmtMs(shown.endMs)}</span>
      </div>
    </div>
  );
}
