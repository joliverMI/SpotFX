/** Simplified first-pass form for morph_step: scope + aspect + absolute number/color/effect.
 * Nudge specs, shape sub-fields and scale overrides — via the JSON escape hatch until Phase D. */
import type { MorphAspect, MorphStepAction, MorphTarget } from '../../types/events';
import { useMorphAspects } from '../../api/queries';
import { ColorInput, NumberInput, Row, ScopeListInput, Select, TextInput } from './inputs';

const newTarget = (): MorphTarget => ({
  scope: { virtual_ids: [], categories: [], roles: [] },
  aspect: 'brightness',
  mode: 'absolute',
  absolute_value: {},
  nudge_amount: 0,
  intensity_scale: 0,
  intensity_source: 'rms_total',
  ramp_ms: null,
});

const NUMERIC_ASPECTS: MorphAspect[] = ['brightness', 'reactivity', 'blur'];

export default function MorphStepForm({
  action,
  update,
}: {
  action: MorphStepAction;
  update: (fn: (a: MorphStepAction) => void) => void;
}) {
  const { data: aspects } = useMorphAspects();
  const aspectOptions = (aspects?.aspect_ids ?? NUMERIC_ASPECTS).map((id) => ({
    value: id,
    label: aspects?.aspect_labels[id] ?? id,
  }));

  return (
    <div>
      <Row label="Ramp (ms)" help="Default for targets without their own ramp">
        <NumberInput value={action.ramp_ms} nullable onChange={(v) => update((a) => { a.ramp_ms = v; })} />
      </Row>
      <Row label="Intensity source">
        <Select
          value={action.intensity_source}
          onChange={(v) => update((a) => { a.intensity_source = v as MorphStepAction['intensity_source']; })}
          options={['rms_total', 'rms_bass', 'onset_score'].map((v) => ({ value: v, label: v }))}
          width={160}
        />
      </Row>

      <div className="card-title" style={{ marginTop: 10 }}>Targets</div>
      {action.targets.map((t, i) => (
        <div key={i} className="action-card" style={{ padding: 10, marginBottom: 8 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
            <Select
              value={t.aspect}
              onChange={(v) => update((a) => { a.targets[i].aspect = v as MorphAspect; a.targets[i].absolute_value = {}; })}
              options={aspectOptions}
              width={140}
            />
            <Select
              value={t.mode}
              onChange={(v) => update((a) => { a.targets[i].mode = v as MorphTarget['mode']; })}
              options={[
                { value: 'absolute', label: 'absolute' },
                { value: 'nudge', label: 'nudge' },
              ]}
              width={110}
            />
            <button className="danger" style={{ fontSize: 11, padding: '3px 8px', marginLeft: 'auto' }}
              onClick={() => update((a) => { a.targets.splice(i, 1); })}>✕</button>
          </div>

          <Row label="Virtuals"><ScopeListInput value={t.scope.virtual_ids} placeholder="ids, comma-separated (blank = any)"
            onChange={(v) => update((a) => { a.targets[i].scope.virtual_ids = v; })} /></Row>
          <Row label="Categories"><ScopeListInput value={t.scope.categories} placeholder="Matrix, Strips, Singles"
            onChange={(v) => update((a) => { a.targets[i].scope.categories = v; })} /></Row>
          <Row label="Roles"><ScopeListInput value={t.scope.roles} placeholder="roles"
            onChange={(v) => update((a) => { a.targets[i].scope.roles = v; })} /></Row>

          {t.mode === 'absolute' && NUMERIC_ASPECTS.includes(t.aspect) && (
            <Row label="Value (0–1)">
              <NumberInput value={t.absolute_value.number ?? null} nullable min={0} max={1} step={0.05}
                onChange={(v) => update((a) => { a.targets[i].absolute_value.number = v; })} />
            </Row>
          )}
          {t.mode === 'nudge' && (
            <>
              <Row label="Nudge amount">
                <NumberInput value={t.nudge_amount} min={-1} max={1} step={0.05}
                  onChange={(v) => update((a) => { a.targets[i].nudge_amount = v ?? 0; })} />
              </Row>
              <Row label="Intensity scale" help="0 = ignore beat intensity, 1 = full RMS scaling">
                <NumberInput value={t.intensity_scale} min={0} max={1} step={0.05}
                  onChange={(v) => update((a) => { a.targets[i].intensity_scale = v ?? 0; })} />
              </Row>
            </>
          )}
          {t.aspect === 'color' && t.mode === 'absolute' && (
            <>
              <Row label="Kind">
                <Select value={t.absolute_value.color_kind ?? 'solid'}
                  onChange={(v) => update((a) => { a.targets[i].absolute_value.color_kind = v as 'solid' | 'gradient'; })}
                  options={[{ value: 'solid', label: 'solid' }, { value: 'gradient', label: 'gradient' }]} width={120} />
              </Row>
              <Row label="Color">
                {t.absolute_value.color_kind === 'gradient' ? (
                  <TextInput value={t.absolute_value.color_value ?? ''} placeholder="CSS gradient"
                    onChange={(v) => update((a) => { a.targets[i].absolute_value.color_value = v || null; })} />
                ) : (
                  <ColorInput value={t.absolute_value.color_value ?? null} nullable
                    onChange={(v) => update((a) => { a.targets[i].absolute_value.color_value = v; })} />
                )}
              </Row>
            </>
          )}
          {t.aspect === 'bg_color' && t.mode === 'absolute' && (
            <Row label="BG color">
              <ColorInput value={t.absolute_value.bg_color ?? null} nullable
                onChange={(v) => update((a) => { a.targets[i].absolute_value.bg_color = v; })} />
            </Row>
          )}
          {t.aspect === 'effect' && (
            <Row label="Effect type">
              <Select value={t.absolute_value.effect_type ?? ''}
                onChange={(v) => update((a) => { a.targets[i].absolute_value.effect_type = v || null; })}
                options={[{ value: '', label: '—' }, ...(aspects?.supported_effects ?? []).map((e) => ({ value: e, label: e }))]}
                width={160} />
            </Row>
          )}
          {t.aspect === 'shape' && (
            <p className="empty-note" style={{ fontSize: 12 }}>
              Shape sub-fields (polygon/star/edges/twist/flip) — edit via “Edit as JSON” until the full form lands.
            </p>
          )}
          <Row label="Ramp override (ms)">
            <NumberInput value={t.ramp_ms} nullable onChange={(v) => update((a) => { a.targets[i].ramp_ms = v; })} />
          </Row>
        </div>
      ))}
      <button style={{ fontSize: 12 }} onClick={() => update((a) => { a.targets.push(newTarget()); })}>
        + Add target
      </button>
    </div>
  );
}
