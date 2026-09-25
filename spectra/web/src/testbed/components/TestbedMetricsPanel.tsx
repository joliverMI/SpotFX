/** P/R/F1 per engine, computed the same way as the spec report's own
 * methodology (spectra/services/testbed_metrics.py) — a live A/B table so
 * two engines can be visually compared on the same song without leaving
 * the page (report Part 3 item 5/6).
 *
 * Also carries the `edges` engine's own three knobs (window/sensitivity/
 * direction, spectra/services/rhythmic_edges.py, data/transition-alignment-plan/
 * report.md section 4) plus the "transitions per minute" density RATE
 * knob (2026-09-25) and the "Use as room default" button (section 5 task
 * 4) — shown next to the
 * tolerance slider only while an `edges` lane (or the generator's own
 * preview kind) is active in either A/B slot, and re-scoring the exact
 * way the tolerance slider does: dragging/toggling one refetches
 * /engine-marks (a cheap single .librosa.json parse), the page recomputes
 * P/R/F1 locally with the same matcher tolerance already uses. */
import HelpLink from '../../help/HelpLink';
import {
  DEFAULT_DIRECTION, DEFAULT_SENSITIVITY, DEFAULT_TRANSITIONS_PER_MINUTE, DEFAULT_WINDOW_BEATS, DIRECTIONS,
  MAX_SENSITIVITY, MAX_TRANSITIONS_PER_MINUTE, MAX_WINDOW_BEATS, MIN_SENSITIVITY,
  MIN_TRANSITIONS_PER_MINUTE, MIN_WINDOW_BEATS, transitionDefaultsDiffer,
} from '../edgeKnobs';
import type { Direction, TransitionKnobValues } from '../edgeKnobs';
import type { TestbedMetrics, TestbedReferenceSet } from '../../types';

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`;
}

export default function TestbedMetricsPanel({
  rows, toleranceMs, onToleranceChange, defaultToleranceMs, onResetToDefault, emptyNote,
  windowBeats, sensitivity, direction, transitionsPerMinute,
  onWindowBeatsChange, onSensitivityChange, onDirectionChange, onTransitionsPerMinuteChange,
  showEdgeKnobs, showTransitionsPerMinute, roomDefaults, onUseAsRoomDefault, useAsRoomDefaultPending,
  referenceSet, referenceSetLoading,
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
  transitionsPerMinute: number;
  onWindowBeatsChange: (v: number) => void;
  onSensitivityChange: (v: number) => void;
  onDirectionChange: (v: Direction) => void;
  onTransitionsPerMinuteChange: (v: number) => void;
  /** Only true while an `edges` lane is selected in either A/B slot — a
   * knob shown for an engine it does not touch would imply a control that
   * does nothing (spectra/web/src/testbed/edgeKnobs.ts::knobsRelevant). */
  showEdgeKnobs: boolean;
  /** Narrower than showEdgeKnobs — the density knob only means anything
   * for the generator's own preview kind (edgeKnobs.ts::transitionsPerMinuteRelevant). */
  showTransitionsPerMinute: boolean;
  /** The room's CURRENT transition_window_beats/_edge_sensitivity/
   * transitions_per_minute, for the "differs from room default" highlight.
   * `null`/undefined while GET /room-controls hasn't resolved yet. */
  roomDefaults: TransitionKnobValues | null | undefined;
  onUseAsRoomDefault: () => void;
  useAsRoomDefaultPending: boolean;
  /** The plan's own four-song acceptance table, recomputed at the current
   * knobs on every drag (report section 4/5 task 4). */
  referenceSet: TestbedReferenceSet | undefined;
  referenceSetLoading: boolean;
}) {
  const currentKnobs: TransitionKnobValues = { windowBeats, sensitivity, transitionsPerMinute };
  const differsFromRoom = transitionDefaultsDiffer(currentKnobs, roomDefaults);
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
          {showTransitionsPerMinute && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <label htmlFor="testbed-transitions-per-minute" style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
                Transitions per minute: {transitionsPerMinute}
                <HelpLink topic="testbed-generator-and-edges" title="Transitions per minute and Use as room default" />
              </label>
              <input
                id="testbed-transitions-per-minute"
                type="range"
                min={MIN_TRANSITIONS_PER_MINUTE}
                max={MAX_TRANSITIONS_PER_MINUTE}
                step={0.5}
                value={transitionsPerMinute}
                onChange={(e) => onTransitionsPerMinuteChange(Number(e.target.value))}
                style={{ flex: 1, maxWidth: 180 }}
              />
              {transitionsPerMinute !== DEFAULT_TRANSITIONS_PER_MINUTE && (
                <button onClick={() => onTransitionsPerMinuteChange(DEFAULT_TRANSITIONS_PER_MINUTE)} style={{ fontSize: 11 }}>
                  Reset ({DEFAULT_TRANSITIONS_PER_MINUTE})
                </button>
              )}
            </div>
          )}
        </div>
      )}
      {showEdgeKnobs && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            Room's current default:{' '}
            {roomDefaults ? (
              <span style={differsFromRoom ? { color: 'var(--warn, #b45309)', fontWeight: 600 } : undefined}>
                Window {roomDefaults.windowBeats} · Sensitivity {roomDefaults.sensitivity.toFixed(2)}{' '}
                · {roomDefaults.transitionsPerMinute}/min
              </span>
            ) : 'loading…'}
            {differsFromRoom && ' — differs from the sliders above'}
          </span>
          <button
            onClick={onUseAsRoomDefault}
            disabled={useAsRoomDefaultPending || !differsFromRoom}
            title={differsFromRoom
              ? 'Write Window/Sensitivity/Transitions-per-song as the room\'s own defaults'
              : 'The sliders above already match the room\'s current defaults'}
            style={{ fontSize: 11 }}
          >
            {useAsRoomDefaultPending ? 'Saving…' : 'Use as room default'}
          </button>
        </div>
      )}
      {showEdgeKnobs && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
            Reference set (Soy Peor / Contra / Dopamine / El Apagón) at these knobs — one-beat recall
          </div>
          {referenceSetLoading || !referenceSet ? (
            <p className="empty-note" style={{ fontSize: 12 }}>Loading…</p>
          ) : (
            <table className="testbed-metrics-table">
              <thead>
                <tr>
                  <th>Song</th>
                  <th>His marks</th>
                  <th>Matched</th>
                  <th>Recall</th>
                  <th>F1</th>
                </tr>
              </thead>
              <tbody>
                {referenceSet.songs.map((s) => (
                  <tr key={s.uri}>
                    <td>{s.name}</td>
                    {!s.available || !s.metrics ? (
                      <td colSpan={4} style={{ color: 'var(--text-muted)', textAlign: 'center' }}>
                        no analysis yet
                      </td>
                    ) : (
                      <>
                        <td>{s.metrics.n_reference}</td>
                        <td>{s.metrics.n_matched}</td>
                        <td>{pct(s.metrics.recall)}</td>
                        <td style={{ fontWeight: 600 }}>{pct(s.metrics.f1)}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
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
