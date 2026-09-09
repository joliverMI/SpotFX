/** P/R/F1 per engine, computed the same way as the spec report's own
 * methodology (spectra/services/testbed_metrics.py) — a live A/B table so
 * two engines can be visually compared on the same song without leaving
 * the page (report Part 3 item 5/6). */
import type { TestbedMetrics } from '../../types';

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`;
}

export default function TestbedMetricsPanel({
  rows, toleranceMs, onToleranceChange, emptyNote,
}: {
  rows: { key: string; label: string; metrics: TestbedMetrics | null | undefined; available: boolean }[];
  toleranceMs: number;
  onToleranceChange: (ms: number) => void;
  emptyNote?: string;
}) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
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
      </div>
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
                <td colSpan={6} style={{ color: 'var(--text-muted)', textAlign: 'center' }}>
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
