/** P/R/F1 per engine, computed the same way as the spec report's own
 * methodology (spectra/services/testbed_metrics.py) — a live A/B table so
 * two engines can be visually compared on the same song without leaving
 * the page (report Part 3 item 5/6). */
import type { TestbedMetrics } from '../../types';

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`;
}

export default function TestbedMetricsPanel({
  rows, toleranceMs, onToleranceChange, defaultToleranceMs, onResetToDefault, emptyNote,
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
