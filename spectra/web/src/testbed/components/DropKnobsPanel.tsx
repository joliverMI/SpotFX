/** The Drops lane's controls (drop-detection plan, phase 2) — the two
 * thresholds the detector sorts its drops into tiers by, "Use as room
 * default", and the plan's own four-song table recomputed at the sliders on
 * every drag (spectra/services/testbed_drop_reference.py), so a threshold
 * is judged on all four songs at once: found and extra at each tier,
 * nothing false on the three EDM songs, the timing of the found drops, and
 * how near the placed lulls and charges sit to his.
 *
 * Shown only while a `drops` lane is selected in either A/B slot
 * (dropKnobs.ts::dropKnobsRelevant). Nothing here fires anything: the
 * thresholds tuned here decide which detections are confident, and only
 * those fire on their own (spectra/services/drop_firing.py). */
import HelpLink from '../../help/HelpLink';
import type { TestbedDropReferenceSet } from '../../types';
import {
  DEFAULT_CONFIDENT_SCORE, DEFAULT_DROP_FLOOR, DEFAULT_SUGGESTED_SCORE,
  MAX_DROP_FLOOR, MAX_DROP_SCORE, MIN_DROP_FLOOR, MIN_DROP_SCORE,
  dropDefaultsDiffer,
} from '../dropKnobs';
import type { DropKnobValues } from '../dropKnobs';

function ms(v: number | null | undefined): string {
  return v == null ? '—' : `${Math.round(v)} ms`;
}

function Slider({
  id, label, value, onChange, fallback, min, max,
}: {
  id: string; label: string; value: number; onChange: (v: number) => void; fallback: number;
  min: number; max: number;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <label htmlFor={id} style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        {label}: {value.toFixed(2)}
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={0.05}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ flex: 1, maxWidth: 180 }}
      />
      {Math.abs(value - fallback) > 1e-9 && (
        <button onClick={() => onChange(fallback)} style={{ fontSize: 11 }}>
          Reset ({fallback.toFixed(1)})
        </button>
      )}
    </div>
  );
}

export default function DropKnobsPanel({
  confident, suggested, floor, onConfidentChange, onSuggestedChange, onFloorChange,
  roomDefaults, onUseAsRoomDefault, useAsRoomDefaultPending, referenceSet, referenceSetLoading,
}: {
  confident: number;
  suggested: number;
  floor: number;
  onConfidentChange: (v: number) => void;
  onSuggestedChange: (v: number) => void;
  onFloorChange: (v: number) => void;
  roomDefaults: DropKnobValues | null | undefined;
  onUseAsRoomDefault: () => void;
  useAsRoomDefaultPending: boolean;
  referenceSet: TestbedDropReferenceSet | undefined;
  referenceSetLoading: boolean;
}) {
  const differs = dropDefaultsDiffer({ confident, suggested, floor }, roomDefaults);
  const edm = referenceSet?.edm_total;
  const total = referenceSet?.total;
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        Drop thresholds <HelpLink topic="testbed-drops" title="The Drops lane" />
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, marginBottom: 6 }}>
        <Slider id="testbed-drop-confident" label="Confident from" value={confident}
                onChange={onConfidentChange} fallback={DEFAULT_CONFIDENT_SCORE}
                min={MIN_DROP_SCORE} max={MAX_DROP_SCORE} />
        <Slider id="testbed-drop-suggested" label="Suggested from" value={suggested}
                onChange={onSuggestedChange} fallback={DEFAULT_SUGGESTED_SCORE}
                min={MIN_DROP_SCORE} max={MAX_DROP_SCORE} />
        <Slider id="testbed-drop-floor" label="Energy floor" value={floor}
                onChange={onFloorChange} fallback={DEFAULT_DROP_FLOOR}
                min={MIN_DROP_FLOOR} max={MAX_DROP_FLOOR} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Room's current settings:{' '}
          {roomDefaults ? (
            <span style={differs ? { color: 'var(--warn, #b45309)', fontWeight: 600 } : undefined}>
              confident {roomDefaults.confident.toFixed(2)} · suggested {roomDefaults.suggested.toFixed(2)}
              {' '}· energy floor {roomDefaults.floor.toFixed(2)}
            </span>
          ) : 'loading…'}
          {differs && ' — differs from the sliders above'}
        </span>
        <button
          onClick={onUseAsRoomDefault}
          disabled={useAsRoomDefaultPending || !differs}
          title={differs
            ? 'Write these settings as the room\'s own; each song is detected again the next time it plays'
            : 'The sliders already match the room\'s current settings'}
          style={{ fontSize: 11 }}
        >
          {useAsRoomDefaultPending ? 'Saving…' : 'Use as room default'}
        </button>
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
        Contra / Dopamine / Pop Off / 100 Millones at these thresholds — a drop is
        found within one beat of yours
      </div>
      {referenceSetLoading || !referenceSet ? (
        <p className="empty-note" style={{ fontSize: 12 }}>Loading…</p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="testbed-metrics-table">
            <thead>
              <tr>
                <th>Song</th>
                <th>Your drops</th>
                <th>Found</th>
                <th>Extra</th>
                <th>Confident found</th>
                <th>Confident extra</th>
                <th>Median miss</th>
                <th>Lull ≤ 1 beat</th>
                <th>Charge ≤ 2 beats</th>
              </tr>
            </thead>
            <tbody>
              {referenceSet.songs.map((r) => (
                <tr key={r.uri}>
                  <td title={r.edm ? 'EDM' : 'not EDM'}>{r.name}{r.edm ? '' : ' *'}</td>
                  {!r.available || !r.score ? (
                    <td colSpan={8} style={{ color: 'var(--text-muted)', textAlign: 'center' }}>
                      {r.reason ?? 'no analysis yet'}
                    </td>
                  ) : (
                    <>
                      <td>{r.score.his_drops}</td>
                      <td>{r.score.found}</td>
                      <td title={Object.entries(r.score.extras_by_kind).map(([k, n]) => `${n} on your ${k}`).join(', ')}>
                        {r.score.extra}
                      </td>
                      <td>{r.score.confident_found}</td>
                      <td style={r.edm && r.score.confident_extra > 0 ? { color: 'var(--danger)', fontWeight: 600 } : undefined}>
                        {r.score.confident_extra}
                      </td>
                      <td>{ms(r.score.median_abs_ms)}</td>
                      <td>{r.score.lull_within_1_beat} of {r.score.lull_compared}</td>
                      <td>{r.score.charge_within_2_beats} of {r.score.charge_compared}</td>
                    </>
                  )}
                </tr>
              ))}
              {total && (
                <tr style={{ fontWeight: 600 }}>
                  <td>All four</td>
                  <td>{total.his_drops}</td>
                  <td>{total.found}</td>
                  <td>{total.extra}</td>
                  <td>{total.confident_found}</td>
                  <td>{total.confident_extra}{edm ? ` (EDM: ${edm.confident_extra})` : ''}</td>
                  <td>{ms(total.median_abs_ms)}</td>
                  <td>{total.lull_within_1_beat} of {total.lull_compared}</td>
                  <td>{total.charge_within_2_beats} of {total.charge_compared}</td>
                </tr>
              )}
            </tbody>
          </table>
          <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
            * 100 Millones is not EDM: every chorus returns the bass after a break, and you
            chose which one is the drop — its extras sit on your own scene changes and flares.
          </p>
        </div>
      )}
    </div>
  );
}
