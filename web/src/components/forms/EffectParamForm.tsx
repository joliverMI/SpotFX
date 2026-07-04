/** Full-fidelity form for ledfx_effect_param — all six param kinds:
 * numeric (+flip_sign), toggle, color, gradient, polar, move_xy, move_polar. */
import type { EffectParamChange, LedFxEffectParamAction } from '../../types/events';
import { useParamLabels } from '../../api/queries';
import { Checkbox, ColorInput, NumberInput, Row, Select, TextInput } from './inputs';

const newParam = (label: string): EffectParamChange => ({
  param_label: label,
  target_value: 0,
  toggle_action: null,
  string_value: null,
  flip_sign: false,
  polar_angle: null,
  polar_radius: null,
  move_x: null,
  move_y: null,
  move_angle: null,
  move_radius: null,
});

export default function EffectParamForm({
  action,
  update,
}: {
  action: LedFxEffectParamAction;
  update: (fn: (a: LedFxEffectParamAction) => void) => void;
}) {
  const { data: labels } = useParamLabels();
  const labelInfo = (name: string) => labels?.find((l) => l.label === name);
  const setP = (i: number, fn: (p: EffectParamChange) => void) =>
    update((a) => { fn(a.params[i]); });

  return (
    <div>
      <Row label="Virtual (scope)" help="Blank = use category / global">
        <TextInput
          value={action.virtual_id ?? ''}
          onChange={(v) => update((a) => { a.virtual_id = v || null; })}
          placeholder="e.g. crystal-mapper (blank = all)"
        />
      </Row>
      <Row label="Category (scope)">
        <Select
          value={action.category ?? ''}
          onChange={(v) => update((a) => { a.category = v || null; })}
          options={[
            { value: '', label: '— all —' },
            { value: 'Matrix', label: 'Matrix' },
            { value: 'Strips', label: 'Strips' },
            { value: 'Singles', label: 'Singles' },
          ]}
        />
      </Row>
      <Row label="Ramp (ms)" help="Blank = settings default, 0 = instant">
        <NumberInput value={action.ramp_ms} nullable onChange={(v) => update((a) => { a.ramp_ms = v; })} />
      </Row>

      <div className="card-title" style={{ marginTop: 10 }}>Parameters</div>
      {action.params.map((p, i) => {
        const info = labelInfo(p.param_label);
        const kind = info?.type ?? 'numeric';
        return (
          <div key={i} className="action-card" style={{ padding: 8, marginBottom: 6 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <Select
                value={p.param_label}
                onChange={(v) => update((a) => { a.params[i] = newParam(v); })}
                options={(labels ?? [{ label: p.param_label, type: 'numeric', min: null, max: null }]).map((l) => ({
                  value: l.label,
                  label: l.label,
                }))}
                width={190}
              />
              <span className="chip">{kind}</span>

              {kind === 'numeric' && (
                <>
                  <NumberInput
                    value={p.target_value}
                    min={info?.min ?? undefined}
                    max={info?.max ?? undefined}
                    onChange={(v) => setP(i, (q) => { q.target_value = v ?? 0; })}
                  />
                  <Checkbox value={p.flip_sign} label="flip sign"
                    onChange={(v) => setP(i, (q) => { q.flip_sign = v; })} />
                </>
              )}
              {kind === 'toggle' && (
                <Select
                  value={p.toggle_action ?? 'toggle'}
                  onChange={(v) => setP(i, (q) => { q.toggle_action = v; })}
                  options={['on', 'off', 'toggle'].map((v) => ({ value: v, label: v }))}
                  width={110}
                />
              )}
              {kind === 'color' && (
                <ColorInput value={p.string_value}
                  onChange={(v) => setP(i, (q) => { q.string_value = v; })} />
              )}
              {kind === 'gradient' && (
                <TextInput
                  value={p.string_value ?? ''}
                  onChange={(v) => setP(i, (q) => { q.string_value = v || null; })}
                  placeholder="CSS gradient string"
                  width={280}
                />
              )}
              {kind === 'polar' && (
                <>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                    <span style={{ color: 'var(--text-muted)' }}>angle°</span>
                    <NumberInput value={p.polar_angle} nullable min={0} max={360} width={80}
                      onChange={(v) => setP(i, (q) => { q.polar_angle = v; })} />
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                    <span style={{ color: 'var(--text-muted)' }} title="0 = center, 1 = edge">radius</span>
                    <NumberInput value={p.polar_radius} nullable min={0} max={1} step={0.05} width={80}
                      onChange={(v) => setP(i, (q) => { q.polar_radius = v; })} />
                  </label>
                </>
              )}
              {kind === 'move_xy' && (
                <>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                    <span style={{ color: 'var(--text-muted)' }} title="delta x, −1..1">Δx</span>
                    <NumberInput value={p.move_x} nullable min={-1} max={1} step={0.05} width={80}
                      onChange={(v) => setP(i, (q) => { q.move_x = v; })} />
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                    <span style={{ color: 'var(--text-muted)' }} title="delta y, −1..1">Δy</span>
                    <NumberInput value={p.move_y} nullable min={-1} max={1} step={0.05} width={80}
                      onChange={(v) => setP(i, (q) => { q.move_y = v; })} />
                  </label>
                </>
              )}
              {kind === 'move_polar' && (
                <>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                    <span style={{ color: 'var(--text-muted)' }} title="delta degrees, + = clockwise">Δangle°</span>
                    <NumberInput value={p.move_angle} nullable step={5} width={80}
                      onChange={(v) => setP(i, (q) => { q.move_angle = v; })} />
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                    <span style={{ color: 'var(--text-muted)' }} title="delta radius, 0..1 space">Δradius</span>
                    <NumberInput value={p.move_radius} nullable step={0.05} width={80}
                      onChange={(v) => setP(i, (q) => { q.move_radius = v; })} />
                  </label>
                </>
              )}

              <span style={{ flex: 1 }} />
              <button className="danger" style={{ fontSize: 11, padding: '3px 8px' }}
                onClick={() => update((a) => { a.params.splice(i, 1); })}>✕</button>
            </div>
          </div>
        );
      })}
      <button
        style={{ fontSize: 12 }}
        onClick={() => update((a) => { a.params.push(newParam(labels?.[0]?.label ?? '')); })}
      >
        + Add parameter
      </button>
    </div>
  );
}
