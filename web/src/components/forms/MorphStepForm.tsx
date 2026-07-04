/** Full-fidelity form for morph_step: scope + aspect + absolute values,
 * shape sub-fields (tri-state booleans, per-sub-field nudge specs),
 * scale overrides for brightness/reactivity, accent color override. */
import type {
  AspectValue,
  MorphAspect,
  MorphStepAction,
  MorphTarget,
  NumericNudge,
} from '../../types/events';
import { useMorphAspects } from '../../api/queries';
import { Checkbox, ColorInput, NumberInput, Row, Select, TextInput } from './inputs';
import { ParentScopeToggle } from './ScopePicker';
import SearchSelect from './SearchSelect';
import { BindableNumber, BindableTri } from './BindingInput';

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

const newNudge = (): NumericNudge => ({ amount: 0, scale: 0, wrap: false, lo: null, hi: null });

const NUMERIC_ASPECTS: MorphAspect[] = ['brightness', 'reactivity', 'blur'];
const OVERRIDE_ASPECTS: MorphAspect[] = ['brightness', 'reactivity'];

/** —/on/off/toggle selector for tri-state booleans (polygon, flip). */
function TriState({ value, onChange }: {
  value: boolean | 'toggle' | null | undefined;
  onChange: (v: boolean | 'toggle' | null) => void;
}) {
  const str = value === true ? 'on' : value === false ? 'off' : value === 'toggle' ? 'toggle' : '';
  return (
    <Select value={str} width={110}
      onChange={(v) => onChange(v === '' ? null : v === 'toggle' ? 'toggle' : v === 'on')}
      options={[
        { value: '', label: '— keep —' },
        { value: 'on', label: 'on' },
        { value: 'off', label: 'off' },
        { value: 'toggle', label: 'toggle' },
      ]} />
  );
}

/** One NumericNudge spec: amount/scale/wrap/lo/hi. */
function NudgeInput({ label, nudge, onChange }: {
  label: string;
  nudge: NumericNudge | null | undefined;
  onChange: (n: NumericNudge | null) => void;
}) {
  const n = nudge ?? null;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap', fontSize: 12 }}>
      <span style={{ width: 90, color: 'var(--text-muted)' }}>{label}</span>
      <Checkbox value={n !== null} label="nudge"
        onChange={(v) => onChange(v ? newNudge() : null)} />
      {n && (
        <>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ color: 'var(--text-muted)' }} title="magnitude in 0..1 space (negative ok)">amt</span>
            <NumberInput value={n.amount} min={-1} max={1} step={0.05} width={72}
              onChange={(v) => onChange({ ...n, amount: v ?? 0 })} />
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ color: 'var(--text-muted)' }} title="0 = ignore beat intensity, 1 = full">scale</span>
            <NumberInput value={n.scale} min={0} max={1} step={0.05} width={72}
              onChange={(v) => onChange({ ...n, scale: v ?? 0 })} />
          </label>
          <Checkbox value={n.wrap} label="bounce"
            onChange={(v) => onChange({ ...n, wrap: v })} />
          <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ color: 'var(--text-muted)' }} title="custom range (blank = param full range)">lo</span>
            <NumberInput value={n.lo} nullable width={72}
              onChange={(v) => onChange({ ...n, lo: v })} />
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ color: 'var(--text-muted)' }}>hi</span>
            <NumberInput value={n.hi} nullable width={72}
              onChange={(v) => onChange({ ...n, hi: v })} />
          </label>
        </>
      )}
    </div>
  );
}

/** Editor for AspectValue.scale_overrides: "{effect}.{param}" → weight rows. */
function ScaleOverrides({ av, set }: {
  av: AspectValue;
  set: (fn: (v: AspectValue) => void) => void;
}) {
  const entries = Object.entries(av.scale_overrides ?? {});
  return (
    <div style={{ marginTop: 4 }}>
      <div className="card-title" style={{ marginBottom: 4 }}>
        Per-param weight overrides
        <span style={{ textTransform: 'none', letterSpacing: 0, marginLeft: 8 }}>
          (key “effect.param”, replaces the catalog aspect_scale)
        </span>
      </div>
      {entries.map(([key, weight], i) => (
        <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
          <TextInput value={key} width={220} placeholder="power.brightness"
            onChange={(v) => set((x) => {
              const so = { ...(x.scale_overrides ?? {}) };
              delete so[key];
              if (v) so[v] = weight;
              x.scale_overrides = Object.keys(so).length ? so : null;
            })} />
          <NumberInput value={weight} min={0} step={0.1} width={80}
            onChange={(v) => set((x) => {
              x.scale_overrides = { ...(x.scale_overrides ?? {}), [key]: v ?? 0 };
            })} />
          <button className="danger" style={{ fontSize: 11, padding: '2px 7px' }}
            onClick={() => set((x) => {
              const so = { ...(x.scale_overrides ?? {}) };
              delete so[key];
              x.scale_overrides = Object.keys(so).length ? so : null;
            })}>✕</button>
        </div>
      ))}
      <button style={{ fontSize: 11 }} onClick={() => set((x) => {
        x.scale_overrides = { ...(x.scale_overrides ?? {}), '': 1.0 };
      })}>+ Add override</button>
    </div>
  );
}

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
        <BindableNumber value={action.ramp_ms} nullable onChange={(v) => update((a) => { a.ramp_ms = v; })} />
      </Row>
      <Row label="Intensity source" help="Beat signal feeding every nudge in this step">
        <Select
          value={action.intensity_source}
          onChange={(v) => update((a) => { a.intensity_source = v as MorphStepAction['intensity_source']; })}
          options={['rms_total', 'rms_bass', 'onset_score'].map((v) => ({ value: v, label: v }))}
          width={160}
        />
      </Row>

      <div className="card-title" style={{ marginTop: 10 }}>Targets</div>
      {action.targets.map((t, i) => {
        const setT = (fn: (tt: MorphTarget) => void) => update((a) => { fn(a.targets[i]); });
        const setAV = (fn: (v: AspectValue) => void) => setT((tt) => { fn(tt.absolute_value); });
        const av = t.absolute_value;
        const nudgeMode = t.mode === 'nudge';
        return (
          <div key={i} className="action-card" style={{ padding: 10, marginBottom: 8 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
              <Select
                value={t.aspect}
                onChange={(v) => setT((tt) => { tt.aspect = v as MorphAspect; tt.absolute_value = {}; })}
                options={aspectOptions}
                width={140}
              />
              <Select
                value={t.mode}
                onChange={(v) => setT((tt) => { tt.mode = v as MorphTarget['mode']; })}
                options={[
                  { value: 'absolute', label: 'absolute' },
                  { value: 'nudge', label: 'nudge' },
                ]}
                width={110}
              />
              <button className="danger" style={{ fontSize: 11, padding: '3px 8px', marginLeft: 'auto' }}
                onClick={() => update((a) => { a.targets.splice(i, 1); })}>✕</button>
            </div>

            <Row label="Target" help="parent = inherit the nearest group/lane Target (or all devices)">
              <ParentScopeToggle scope={t.scope}
                onChange={(s) => setT((tt) => { tt.scope = s ?? { virtual_ids: [], categories: [], roles: [] }; })} />
            </Row>

            {/* ── numeric aspects: brightness / reactivity / blur ── */}
            {NUMERIC_ASPECTS.includes(t.aspect) && !nudgeMode && (
              <Row label="Value (0–1)">
                <BindableNumber value={av.number ?? null} nullable min={0} max={1} step={0.05}
                  onChange={(v) => setAV((x) => { x.number = v; })} />
              </Row>
            )}
            {NUMERIC_ASPECTS.includes(t.aspect) && nudgeMode && (
              <>
                <Row label="Nudge amount">
                  <NumberInput value={t.nudge_amount} min={-1} max={1} step={0.05}
                    onChange={(v) => setT((tt) => { tt.nudge_amount = v ?? 0; })} />
                </Row>
                <Row label="Intensity scale" help="0 = ignore beat intensity, 1 = full RMS scaling">
                  <NumberInput value={t.intensity_scale} min={0} max={1} step={0.05}
                    onChange={(v) => setT((tt) => { tt.intensity_scale = v ?? 0; })} />
                </Row>
              </>
            )}
            {OVERRIDE_ASPECTS.includes(t.aspect) && (
              <ScaleOverrides av={av} set={setAV} />
            )}

            {/* ── color / bg_color ── */}
            {t.aspect === 'color' && !nudgeMode && (
              <>
                <Row label="Kind">
                  <Select value={av.color_kind ?? 'solid'}
                    onChange={(v) => setAV((x) => { x.color_kind = v as 'solid' | 'gradient'; })}
                    options={[{ value: 'solid', label: 'solid' }, { value: 'gradient', label: 'gradient' }]} width={120} />
                </Row>
                <Row label="Color">
                  {av.color_kind === 'gradient' ? (
                    <TextInput value={av.color_value ?? ''} placeholder="CSS gradient"
                      onChange={(v) => setAV((x) => { x.color_value = v || null; })} />
                  ) : (
                    <ColorInput value={av.color_value ?? null} nullable
                      onChange={(v) => setAV((x) => { x.color_value = v; })} />
                  )}
                </Row>
              </>
            )}
            {t.aspect === 'bg_color' && !nudgeMode && (
              <Row label="BG color">
                <ColorInput value={av.bg_color ?? null} nullable
                  onChange={(v) => setAV((x) => { x.bg_color = v; })} />
              </Row>
            )}

            {/* ── effect switch ── */}
            {t.aspect === 'effect' && (
              <Row label="Effect type">
                <SearchSelect value={av.effect_type ?? ''}
                  onChange={(v) => setAV((x) => { x.effect_type = v || null; })}
                  options={(aspects?.supported_effects ?? []).map((e) => ({ value: e, label: e }))}
                  placeholder="— keep current —" width={200} />
              </Row>
            )}

            {/* ── shape sub-fields ── */}
            {t.aspect === 'shape' && (
              <>
                <Row label="Polygon" help="tri-state: on / off / toggle current">
                  <BindableTri value={av.polygon ?? null} onChange={(v) => setAV((x) => { x.polygon = v; })}
                    renderScalar={(v, set) => <TriState value={v} onChange={set} />} />
                </Row>
                <Row label="Flip">
                  <BindableTri value={av.flip ?? null} onChange={(v) => setAV((x) => { x.flip = v; })}
                    renderScalar={(v, set) => <TriState value={v} onChange={set} />} />
                </Row>
                {!nudgeMode && (
                  <>
                    <Row label="Star (0–1)">
                      <BindableNumber value={av.star ?? null} nullable min={0} max={1} step={0.05}
                        onChange={(v) => setAV((x) => { x.star = v; })} />
                    </Row>
                    <Row label="Edges">
                      <BindableNumber value={av.edges ?? null} nullable min={0} step={1}
                        onChange={(v) => setAV((x) => { x.edges = typeof v === 'number' ? Math.round(v) : v; })} />
                    </Row>
                    <Row label="Twist">
                      <BindableNumber value={av.twist ?? null} nullable step={0.05}
                        onChange={(v) => setAV((x) => { x.twist = v; })} />
                    </Row>
                    <Row label="X offset (−1..1)">
                      <BindableNumber value={av.x_offset ?? null} nullable min={-1} max={1} step={0.05}
                        onChange={(v) => setAV((x) => { x.x_offset = v; })} />
                    </Row>
                    <Row label="Y offset (−1..1)">
                      <BindableNumber value={av.y_offset ?? null} nullable min={-1} max={1} step={0.05}
                        onChange={(v) => setAV((x) => { x.y_offset = v; })} />
                    </Row>
                  </>
                )}
                {nudgeMode && (
                  <div style={{ marginTop: 6 }}>
                    <div className="card-title">Per-sub-field nudges</div>
                    <NudgeInput label="star" nudge={av.star_nudge}
                      onChange={(n) => setAV((x) => { x.star_nudge = n; })} />
                    <NudgeInput label="edges" nudge={av.edges_nudge}
                      onChange={(n) => setAV((x) => { x.edges_nudge = n; })} />
                    <NudgeInput label="twist" nudge={av.twist_nudge}
                      onChange={(n) => setAV((x) => { x.twist_nudge = n; })} />
                    <NudgeInput label="x offset" nudge={av.x_offset_nudge}
                      onChange={(n) => setAV((x) => { x.x_offset_nudge = n; })} />
                    <NudgeInput label="y offset" nudge={av.y_offset_nudge}
                      onChange={(n) => setAV((x) => { x.y_offset_nudge = n; })} />
                  </div>
                )}
              </>
            )}

            {/* ── accent color override (any aspect) ── */}
            <Row label="Accent color" help="Third/accent color on effect switch (sparks/peak). Blank = derive from BG color">
              <ColorInput value={av.accent_color ?? null} nullable
                onChange={(v) => setAV((x) => { x.accent_color = v; })} />
            </Row>
            <Row label="Ramp override (ms)">
              <BindableNumber value={t.ramp_ms} nullable onChange={(v) => setT((tt) => { tt.ramp_ms = v; })} />
            </Row>
          </div>
        );
      })}
      <button style={{ fontSize: 12 }} onClick={() => update((a) => { a.targets.push(newTarget()); })}>
        + Add target
      </button>
    </div>
  );
}
