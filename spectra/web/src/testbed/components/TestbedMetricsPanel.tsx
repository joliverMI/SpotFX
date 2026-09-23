/** P/R/F1 per engine, computed the same way as the spec report's own
 * methodology (spectra/services/testbed_metrics.py) — a live A/B table so
 * two engines can be visually compared on the same song without leaving
 * the page (report Part 3 item 5/6).
 *
 * Also carries the `edges` engine's own three knobs (window/sensitivity/
 * direction, spectra/services/rhythmic_edges.py, data/transition-alignment-plan/
 * report.md section 4) — shown next to the tolerance slider only while an
 * `edges` lane is active in either A/B slot, and re-scoring the exact way
 * the tolerance slider does: dragging/toggling one refetches /engine-marks
 * (a cheap single .librosa.json parse), the page recomputes P/R/F1 locally
 * with the same matcher tolerance already uses. */
import HelpLink from '../../help/HelpLink';
import {
  DEFAULT_DIRECTION, DEFAULT_SENSITIVITY, DEFAULT_WINDOW_BEATS, DIRECTIONS,
  MAX_SENSITIVITY, MAX_WINDOW_BEATS, MIN_SENSITIVITY, MIN_WINDOW_BEATS,
} from '../edgeKnobs';
import type { Direction } from '../edgeKnobs';
import type { TestbedMetrics } from '../../types';

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`;
}

export default function TestbedMetricsPanel({
  rows, toleranceMs, onToleranceChange, defaultToleranceMs, onResetToDefault, emptyNote,
  windowBeats, sensitivity, direction, onWindowBeatsChange, onSensitivityChange,
  onDirectionChange, showEdgeKnobs,
}: {
  rows: { key: string; label: string; metrics: TestbedMetrics | null | undefined; available: boolean }[];
  toleranceMs: number;
  onToleranceChange: (ms: number) => void;
  /** The default this song's active lanes would get — below half a beat
   * for a beat/downbeat lane, 500ms for section boundaries (data/
   * music-analysis-octave-scout/report.md, "Work that should ship" #2). */
  defaultToleranceMs: number;
  onResetToDefault: () => void;
  emptyNote?: string;
  windowBeats: number;
  sensitivity: number;
  direction: Direction;
  onWindowBeatsChange: (v: number) => void;
  onSensitivityChange: (v: number) => void;
  onDirectionChange: (v: Direction) => void;
  /** Only true while an `edges` lane is selected in either A/B slot — a
   * knob shown for an engine it does not touch would imply a control that
   * does nothing (spectra/web/src/testbed/edgeKnobs.ts::knobsRelevant). */
  showEdgeKnobs: boolean;
}) {
  const atDefault = toleranceMs === defaultToleranceMs;
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
        <label htmlFor="testbed-tolerance" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          Tolerance: {toleranceMs}ms
        </label>
        <input
          id="testbed-tolerance"
          type="range"
          min={100}
          max={3000}
          step={50}
          value={toleranceMs}
          onChange={(e) => onToleranceChange(Number(e.target.value))}
          style={{ flex: 1, maxWidth: 240 }}
        />
        {!atDefault && (
          <button onClick={onResetToDefault} style={{ fontSize: 11 }}>
            Reset to default ({defaultToleranceMs}ms)
          </button>
        )}
      </div>
      <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 0, marginBottom: 8 }}>
        Default for these lanes: {defaultToleranceMs}ms — below half a beat
        for a beat/downbeat lane, 500ms for section boundaries. The slider
        can still be set to any value, including 500ms.
      </p>
      {showEdgeKnobs && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <label htmlFor="testbed-window-beats" style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
              Window: {windowBeats} beat{windowBeats === 1 ? '' : 's'}
              <HelpLink topic="testbed-generator-and-edges" title="Window and sensitivity" />
            </label>
            <input
              id="testbed-window-beats"
              type="range"
              min={MIN_WINDOW_BEATS}
              max={MAX_WINDOW_BEATS}
              step={1}
              value={windowBeats}
              onChange={(e) => onWindowBeatsChange(Number(e.target.value))}
              style={{ flex: 1, maxWidth: 180 }}
            />
            {windowBeats !== DEFAULT_WINDOW_BEATS && (
              <button onClick={() => onWindowBeatsChange(DEFAULT_WINDOW_BEATS)} style={{ fontSize: 11 }}>
                Reset ({DEFAULT_WINDOW_BEATS})
              </button>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <label htmlFor="testbed-sensitivity" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Sensitivity: {sensitivity.toFixed(2)}
            </label>
            <input
              id="testbed-sensitivity"
              type="range"
              min={MIN_SENSITIVITY}
              max={MAX_SENSITIVITY}
              step={0.05}
              value={sensitivity}
              onChange={(e) => onSensitivityChange(Number(e.target.value))}
              style={{ flex: 1, maxWidth: 180 }}
            />
            {sensitivity !== DEFAULT_SENSITIVITY && (
              <button onClick={() => onSensitivityChange(DEFAULT_SENSITIVITY)} style={{ fontSize: 11 }}>
                Reset ({DEFAULT_SENSITIVITY})
              </button>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Direction:</span>
            <div role="group" aria-label="Direction" style={{ display: 'flex', gap: 4 }}>
              {DIRECTIONS.map((d) => (
                <button
                  key={d}
                  type="button"
                  aria-pressed={direction === d}
                  className={direction === d ? 'primary' : ''}
                  onClick={() => onDirectionChange(d)}
                  style={{ fontSize: 11, textTransform: 'capitalize' }}
                >
                  {d}
                </button>
              ))}
            </div>
            {direction !== DEFAULT_DIRECTION && (
              <button onClick={() => onDirectionChange(DEFAULT_DIRECTION)} style={{ fontSize: 11 }}>
                Reset ({DEFAULT_DIRECTION})
              </button>
            )}
          </div>
        </div>
      )}
      {emptyNote ? (
        <p className="empty-note" style={{ fontSize: 12 }}>
          {emptyNote} — precision/recall need at least one of your own marks to score against.
        </p>
      ) : (
      <table className="testbed-metrics-table">
        <thead>
          <tr>
            <th>Engine</th>
            <th>His marks</th>
            <th>Detected</th>
            <th>Matched</th>
            <th>Precision</th>
            <th>Recall</th>
            <th>F1</th>
            <th>Mean offset</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td>{r.label}</td>
              {!r.available || !r.metrics ? (
                <td colSpan={7} style={{ color: 'var(--text-muted)', textAlign: 'center' }}>
                  not computed for this song
                </td>
              ) : (
                <>
                  <td>{r.metrics.n_reference}</td>
                  <td>{r.metrics.n_estimate}</td>
                  <td>{r.metrics.n_matched}</td>
                  <td>{pct(r.metrics.precision)}</td>
                  <td>{pct(r.metrics.recall)}</td>
                  <td style={{ fontWeight: 600 }}>{pct(r.metrics.f1)}</td>
                  <td>{Math.round(r.metrics.mean_abs_offset_ms)}ms</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      )}
    </div>
  );
}
