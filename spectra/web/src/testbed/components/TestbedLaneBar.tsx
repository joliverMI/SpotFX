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
 * just extra (report Part 1.2's own reading). */
import { useState } from 'react';
import { fmtMs } from '../../lib/time';
import type { TestbedEstimateMark, TestbedMetrics, TestbedReferenceMark, TestbedWaveform } from '../../types';

function tintFor(offsetMs: number | undefined, toleranceMs: number): string {
  if (offsetMs == null) return 'unmatched';
  return offsetMs <= toleranceMs / 2 ? 'matched-tight' : 'matched-loose';
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
    const points = waveform.mins.map((min, i) => {
      const max = waveform.maxs![i];
      const x = (i / Math.max(1, n - 1)) * 100;
      return { x, min, max };
    });
    return (
      <div className="testbed-lane-row">
        <span className="testbed-lane-label">Waveform (retained WAV)</span>
        <div className="testbed-lane-bar testbed-lane-waveform">
          <svg className="testbed-waveform-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
            {points.map((p, i) => (
              <line
                key={i}
                x1={p.x} x2={p.x}
                y1={50 - p.max * 48} y2={50 - p.min * 48}
                stroke="var(--accent)" strokeWidth="0.4"
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
  label, marks, durationMs, metrics, toleranceMs, hover, setHover,
}: {
  label: string;
  marks: TestbedReferenceMark[];
  durationMs: number;
  metrics: TestbedMetrics | null | undefined;
  toleranceMs: number;
  hover: { text: string; leftPct: string } | null;
  setHover: (h: { text: string; leftPct: string } | null) => void;
}) {
  const dur = Math.max(1, durationMs);
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (ms / dur) * 100))}%`;
  const offsetByRefIndex = new Map<number, number>();
  metrics?.matches.forEach((m) => offsetByRefIndex.set(m.ref_index, m.abs_offset_ms));
  return (
    <div className="testbed-lane-row">
      <span className="testbed-lane-label">{label}</span>
      <div className="testbed-lane-bar">
        {hover && <div className="review-lane-tooltip" style={{ left: hover.leftPct }}>{hover.text}</div>}
        {marks.map((m, i) => {
          const offset = offsetByRefIndex.get(i);
          const tint = metrics ? tintFor(offset, toleranceMs) : 'extra';
          const text = `${fmtMs(m.timestamp_ms)} — ${m.kind}${offset != null ? ` (matched, ${Math.round(offset)}ms off)` : metrics ? ' (no match)' : ''}`;
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
  durationMs, waveform, transitions, flares, reference, referenceLabel,
  engineLanes, toleranceMs, onEstimateMarkClick,
}: {
  durationMs: number;
  waveform: TestbedWaveform | undefined;
  transitions: TestbedReferenceMark[];
  flares: TestbedReferenceMark[];
  reference: 'transitions' | 'flares';
  referenceLabel: string;
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
        durationMs={durationMs}
        metrics={activeMetrics}
        toleranceMs={toleranceMs}
        hover={hover}
        setHover={setHover}
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
