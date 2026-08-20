/** Summary — a read-only overview of the whole scene; each card jumps to
 * its tab. Labels edit here (they're identity, not configuration). */
import { LabelsInput } from '../../components/inputs';
import HelpLink from '../../help/HelpLink';
import { useRoomJourney, useSequencerConfig } from '../../queries';
import type { SceneV2 } from '../../types';
import { isBinding, RESPONSE_CLASSES, sceneDiceLetters } from '../../types';
import type { TabName } from '../ScenesPage';

function Card({ title, onClick, children }: {
  title: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <div onClick={onClick}
      style={{ background: 'var(--surface2)', padding: 10, borderRadius: 'var(--radius)', fontSize: 12, cursor: 'pointer', minWidth: 0 }}
      title={`Open the ${title} tab`}>
      <div className="card-title" style={{ marginBottom: 6 }}>{title}</div>
      {children}
    </div>
  );
}

export default function SummaryTab({ scene, setScene, goTo }: {
  scene: SceneV2;
  setScene: (s: SceneV2) => void;
  goTo: (t: TabName) => void;
}) {
  const { data: seqConfig } = useSequencerConfig();
  const { data: room } = useRoomJourney();
  const dice = sceneDiceLetters(scene);
  const boundCount = scene.devices.reduce((n, d) =>
    n + Object.values(d.params).filter(isBinding).length
      + (isBinding(d.brightness) ? 1 : 0)
      + (isBinding(d.background_brightness) ? 1 : 0), 0);
  const driftCount = scene.devices.reduce((n, d) => n + Object.keys(d.drift ?? {}).length, 0);
  const entry = seqConfig?.entries?.[scene.id];

  return (
    <div>
      <div className="field" style={{ maxWidth: 420 }}>
        <label>Labels (comma separated)</label>
        <LabelsInput value={scene.labels ?? []} placeholder="e.g. mid-group, particle"
          onChange={(labels) => setScene({ ...scene, labels })} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 }}>
        <Card title="Initial Set" onClick={() => goTo('Initial Set')}>
          {scene.devices.length === 0 && <span className="empty-note">no device entries</span>}
          {scene.devices.map((d) => (
            <div key={d.id} style={{ marginBottom: 3 }}>
              <b>{d.target_kind === 'all' ? 'All Devices' : d.target || '—'}</b>
              {' → '}{d.effect_type || 'no effect'}
              <span style={{ color: 'var(--text-muted)' }}> · {Object.keys(d.params).length} params</span>
            </div>
          ))}
          <div style={{ color: 'var(--text-muted)', marginTop: 4 }}>
            {boundCount} bound value{boundCount === 1 ? '' : 's'}
            {dice.length > 0 && ` · dice ${dice.map((l) => l.toUpperCase()).join(' ')}`}
          </div>
        </Card>

        <Card title="Responses" onClick={() => goTo(scene.responses.flare ? 'Flares' : 'Charges/Lulls/Drops')}>
          {RESPONSE_CLASSES.map((cls) => {
            const spec = scene.responses[cls];
            const kindCount = spec
              ? new Set(spec.bands.flatMap((b) => Object.keys(b.kinds ?? {}))).size
              : 0;
            return (
              <div key={cls} style={{ color: spec ? undefined : 'var(--text-muted)' }}>
                {cls}: {spec
                  ? `${spec.bands.length} band${spec.bands.length === 1 ? '' : 's'} · ${kindCount} kind${kindCount === 1 ? '' : 's'}`
                  : '—'}
              </div>
            );
          })}
        </Card>

        <Card title="Drift" onClick={() => goTo('Drift')}>
          {driftCount === 0
            ? <span className="empty-note">no parameter drift declared</span>
            : <span>{driftCount} drifting value{driftCount === 1 ? '' : 's'}</span>}
          <div style={{ marginTop: 4 }}>
            {scene.color_journey.mode === 'override' ? (
              <span className="badge badge-purple"
                title="This scene overrides the room's colour journey while it shows">
                journey OVERRIDE {scene.color_journey.journey?.degrees_per_min}°/min
              </span>
            ) : (
              <span style={{ color: 'var(--text-muted)' }}>
                rides the room journey ({room?.journey.degrees_per_min ?? '…'}°/min
                {scene.color_journey.pace_factor !== 1 && ` ×${scene.color_journey.pace_factor}`})
              </span>
            )}
          </div>
        </Card>

        <Card title="Phase Choreography" onClick={() => goTo('Phase Choreography')}>
          {scene.choreography.enabled
            ? <span>{scene.choreography.transition_ms} ms {scene.choreography.transition_mode}, anchor {Math.round(scene.choreography.anchor_frac * 100)}%</span>
            : <span className="empty-note">off — instant switch</span>}
        </Card>

        <Card title="Override Blend" onClick={() => goTo('Phase Choreography')}>
          {scene.entry_ramp_ms === 0 ? (
            <span className="empty-note">charge/lull auto-stretch to the trigger gap, instant entry</span>
          ) : (
            <span>{`entry blend ${scene.entry_ramp_ms}ms`}</span>
          )}
        </Card>

        <Card title="Sequencing" onClick={() => goTo('Sequencing')}>
          {!entry && <span className="empty-note">not sequenced</span>}
          {entry && (
            <span>
              {entry.curve_ref ? 'named curve' : entry.inline_points ? 'inline curve' : 'flat 1.0'}
            </span>
          )}
          <div style={{ marginTop: 4, color: 'var(--text-muted)' }}>
            min dwell {scene.dwell_curve
              ? (scene.dwell_curve.curve_ref ? 'named curve'
                : scene.dwell_curve.inline_points ? 'inline curve' : 'flat')
              : '16s → 4s (default)'}
          </div>
        </Card>

        <Card title="Colour Sets" onClick={() => goTo('Colour Sets')}>
          {scene.accept_all_sets
            ? <span>accepts every set (minus global opt-outs)</span>
            : <span>narrowed to {scene.accepted_set_ids.length} set{scene.accepted_set_ids.length === 1 ? '' : 's'}</span>}
          {scene.preferred_color_set_mode && scene.preferred_color_set_mode !== 'default' && (
            <span> · prefers {scene.preferred_color_set_mode}</span>
          )}
        </Card>
      </div>
      <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 10 }}>
        A scene is initial conditions (every value fixed, ⚡-mapped, or 🎲-rolled) plus
        declared mechanisms — drift, responses, colour journey. <HelpLink topic="concept-scene" />
      </p>
    </div>
  );
}
