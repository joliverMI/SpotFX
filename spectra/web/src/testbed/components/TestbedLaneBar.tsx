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
 * implying an alignment it cannot justify. */
import { useState } from 'react';
import { fmtMs } from '../../lib/time';
import type { TestbedEstimateMark, TestbedMetrics, TestbedReferenceMark, TestbedWaveform } from '../../types';

function tintFor(offsetMs: number | undefined, toleranceMs: number): string {
  if (offsetMs == null) return 'unmatched';
  return offsetMs <= toleranceMs / 2 ? 'matched-tight' : 'matched-loose';
}

/** Where the pinned WAV sits on the SONG's timebase: bucket i covers
 * `offset + (i / (n-1)) * waveDur` ms, the same ms -> % mapping every mark
 * lane uses. `offset` is the capture's own start in song time; `spanPct` is
 * the WAV's own length as a share of the lane (an engine's beats can run
 * past a capture that was trimmed, so `dur` is often the longer one).
 * A missing duration falls back to the full width rather than collapsing
 * the lane to nothing, and is reported as unpositioned. */
function waveformPlacement(waveform: TestbedWaveform, dur: number) {
  const waveDur = waveform.duration_ms ?? 0;
  const offsetMs = waveform.capture_offset_ms;
  const offsetKnown = offsetMs != null && Number.isFinite(offsetMs);
  const startPct = offsetKnown ? Math.max(0, Math.min(100, (offsetMs! / dur) * 100)) : 0;
  const spanPct = waveDur > 0
    ? Math.max(0, Math.min(100 - startPct, (waveDur / dur) * 100))
    : 100 - startPct;
  return { startPct, spanPct, offsetKnown, offsetMs: offsetKnown ? offsetMs! : 0 };
}

function WaveformLane({ waveform, durationMs }: { waveform: TestbedWaveform | undefined; durationMs: number }) {
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
  if (waveform.source === 'wav_peaks' && waveform.mins && waveform.maxs) {
    const n = waveform.mins.length;
    const { startPct, spanPct, offsetKnown, offsetMs } = waveformPlacement(waveform, dur);
    const points = waveform.mins.map((min, i) => {
      const max = waveform.maxs![i];
      const x = startPct + (i / Math.max(1, n - 1)) * spanPct;
      return { x, min, max };
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
  const points = ts.map((t, i) => `${(t / dur) * 100},${100 - Math.min(1, rms[i] ?? 0) * 100}`).join(' ');
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
  label, marks, scoredMarks, durationMs, metrics, toleranceMs, hover, setHover, emptyNote,
}: {
  label: string;
  marks: TestbedReferenceMark[];
  /** The exact array `metrics` was computed over — promoted marks already
   * dropped. `metrics.matches[].ref_index` indexes into THIS, not into
   * `marks`, so a tint is resolved by mark id rather than by position. */
  scoredMarks: TestbedReferenceMark[];
  durationMs: number;
  metrics: TestbedMetrics | null | undefined;
  toleranceMs: number;
  hover: { text: string; leftPct: string } | null;
  setHover: (h: { text: string; leftPct: string } | null) => void;
  emptyNote?: string;
}) {
  const dur = Math.max(1, durationMs);
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (ms / dur) * 100))}%`;
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
        {marks.map((m) => {
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

export function EngineLane({
  label, estimate, durationMs, metrics, onMarkClick,
}: {
  label: string;
  estimate: TestbedEstimateMark[];
  durationMs: number;
  metrics: TestbedMetrics | null | undefined;
  toleranceMs: number;
  onMarkClick?: (mark: TestbedEstimateMark) => void;
}) {
  const [hover, setHover] = useState<{ text: string; leftPct: string } | null>(null);
  const dur = Math.max(1, durationMs);
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (ms / dur) * 100))}%`;
  const matchedEstIndices = new Set(metrics?.matches.map((m) => m.est_index) ?? []);
  return (
    <div className="testbed-lane-row">
      <span className="testbed-lane-label">{label}</span>
      <div className="testbed-lane-bar">
        {hover && <div className="review-lane-tooltip" style={{ left: hover.leftPct }}>{hover.text}</div>}
        {estimate.map((m, i) => {
          const matched = matchedEstIndices.has(i);
          const text = `${fmtMs(m.time_ms)}${matched ? ' (matched)' : ' (extra — no match to his marks)'}`;
          return (
            <button
              key={i}
              type="button"
              className={`testbed-lane-marker ${matched ? 'matched-tight' : 'extra'}`}
              style={{ left: pct(m.time_ms) }}
              onPointerEnter={() => setHover({ text, leftPct: pct(m.time_ms) })}
              onPointerLeave={() => setHover(null)}
              onClick={() => onMarkClick?.(m)}
              aria-label={text}
              title={onMarkClick ? 'Click to review pushing this mark to your real triggers' : undefined}
            />
          );
        })}
      </div>
    </div>
  );
}

export default function TestbedLaneBar({
  durationMs, waveform, transitions, flares, scoredMarks, reference, referenceLabel,
  referenceEmptyNote, engineLanes, toleranceMs, onEstimateMarkClick,
}: {
  durationMs: number;
  waveform: TestbedWaveform | undefined;
  transitions: TestbedReferenceMark[];
  flares: TestbedReferenceMark[];
  /** The scored subset of the ACTIVE reference set — see ReferenceMarksLane. */
  scoredMarks: TestbedReferenceMark[];
  reference: 'transitions' | 'flares';
  referenceLabel: string;
  referenceEmptyNote?: string;
  engineLanes: { key: string; label: string; estimate: TestbedEstimateMark[];
                metrics: TestbedMetrics | null | undefined }[];
  toleranceMs: number;
  onEstimateMarkClick?: (engineKey: string, mark: TestbedEstimateMark) => void;
}) {
  const [hover, setHover] = useState<{ text: string; leftPct: string } | null>(null);
  const activeReferenceMarks = reference === 'transitions' ? transitions : flares;
  const activeMetrics = engineLanes[0]?.metrics; // the primary engine's own compare tints his marks
  return (
    <div className="testbed-lane-stack">
      <WaveformLane waveform={waveform} durationMs={durationMs} />
      <ReferenceMarksLane
        label={`His ${referenceLabel}`}
        marks={activeReferenceMarks}
        scoredMarks={scoredMarks}
        durationMs={durationMs}
        metrics={activeMetrics}
        toleranceMs={toleranceMs}
        hover={hover}
        setHover={setHover}
        emptyNote={referenceEmptyNote}
      />
      {engineLanes.map((lane) => (
        <EngineLane
          key={lane.key}
          label={lane.label}
          estimate={lane.estimate}
          durationMs={durationMs}
          metrics={lane.metrics}
          toleranceMs={toleranceMs}
          onMarkClick={onEstimateMarkClick ? (mark) => onEstimateMarkClick(lane.key, mark) : undefined}
        />
      ))}
      <div className="testbed-lane-times">
        <span>{fmtMs(0)}</span>
        <span>{fmtMs(durationMs)}</span>
      </div>
    </div>
  );
}
