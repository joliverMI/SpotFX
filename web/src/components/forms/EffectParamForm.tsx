/** Simplified first-pass form for ledfx_effect_param: label + numeric/toggle/color values.
 * Polar / move params keep their stored values — edit via the JSON escape hatch. */
import type { EffectParamChange, LedFxEffectParamAction } from '../../types/events';
import { useParamLabels } from '../../api/queries';
import { NumberInput, Row, Select, TextInput } from './inputs';

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
          <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6, flexWrap: 'wrap' }}>
            <Select
              value={p.param_label}
              onChange={(v) => update((a) => { a.params[i] = newParam(v); })}
              options={(labels ?? [{ label: p.param_label, type: 'numeric', min: null, max: null }]).map((l) => ({
                value: l.label,
                label: l.label,
              }))}
              width={190}
            />
            {kind === 'numeric' && (
              <NumberInput
                value={p.target_value}
                min={info?.min ?? undefined}
                max={info?.max ?? undefined}
                onChange={(v) => update((a) => { a.params[i].target_value = v ?? 0; })}
              />
            )}
            {kind === 'toggle' && (
              <Select
                value={p.toggle_action ?? 'toggle'}
                onChange={(v) => update((a) => { a.params[i].toggle_action = v; })}
                options={['on', 'off', 'toggle'].map((v) => ({ value: v, label: v }))}
                width={110}
              />
            )}
            {(kind === 'color' || kind === 'gradient') && (
              <TextInput
                value={p.string_value ?? ''}
                onChange={(v) => update((a) => { a.params[i].string_value = v || null; })}
                placeholder={kind === 'color' ? '#rrggbb' : 'CSS gradient'}
                width={220}
              />
            )}
            {!['numeric', 'toggle', 'color', 'gradient'].includes(kind) && (
              <span className="chip" title="Edit via JSON until the full form lands">{kind} — use JSON editor</span>
            )}
            <button className="danger" style={{ fontSize: 11, padding: '3px 8px' }}
              onClick={() => update((a) => { a.params.splice(i, 1); })}>✕</button>
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
