/** Full-fidelity form for morph_step: scope + aspect + absolute values,
 * shape sub-fields (tri-state booleans, per-sub-field nudge specs),
 * scale overrides for brightness/reactivity, accent color override. */
import type {
  AspectValue,
  MorphAspect,
  MorphStepAction,
  MorphTarget,
  NumericNudge,
  ValueBinding,
} from '../../types/events';
import { useMorphAspects, type MorphAspectsInfo } from '../../api/queries';
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

const newNudge = (): NumericNudge => ({ amount: 0, scale: 0, random_sign: false, wrap: false, lo: null, hi: null });

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

/** One NumericNudge spec: amount (bindable ⚡/🎲) / ± / scale / wrap / lo / hi. */
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
            <span style={{ color: 'var(--text-muted)' }} title="magnitude in 0..1 space (negative ok); ⚡ maps it to a music signal, 🎲 rolls it fresh every fire">amt</span>
            <BindableNumber value={n.amount} min={-1} max={1} step={0.05} width={72}
              onChange={(v) => onChange({ ...n, amount: v ?? 0 })} />
          </label>
          <button title="Random sign — nudge up or down by the same magnitude, 50/50 per fire"
            style={{
              padding: '2px 6px', fontSize: 12, flex: 'none',
              borderColor: n.random_sign ? 'var(--accent)' : 'var(--border)',
              color: n.random_sign ? 'var(--accent)' : 'var(--text-muted)',
            }}
            onClick={() => onChange({ ...n, random_sign: !n.random_sign })}>
            +/−
          </button>
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

/** Union of reactivity-tagged params across all supported effects, for the
 * per-param Reactivity menu. Color params are excluded (accent color has its
 * own row); toggles (keybeat2d half_beat) render as tri-state. */
type ReactMenuEntry = {
  label: string;
  type: string;
  min: number | null;
  max: number | null;
  effects: string[];
};

function reactivityMenu(aspects?: MorphAspectsInfo): Map<string, ReactMenuEntry> {
  const map = new Map<string, ReactMenuEntry>();
  for (const [etype, params] of Object.entries(aspects?.param_meta ?? {})) {
    for (const [pname, m] of Object.entries(params)) {
      if (m.aspect !== 'reactivity' || m.type === 'color') continue;
      const cur = map.get(pname);
      if (cur) cur.effects.push(etype);
      else map.set(pname, { label: m.label, type: m.type, min: m.min, max: m.max, effects: [etype] });
    }
  }
  return map;
}

const stepFor = (m: ReactMenuEntry) =>
  m.type === 'integer' ? 1 : ((m.max ?? 1) - (m.min ?? 0)) > 10 ? 0.5 : 0.05;

const midVal = (m: ReactMenuEntry) => {
  const mid = ((m.min ?? 0) + (m.max ?? 1)) / 2;
  return m.type === 'integer' ? Math.round(mid) : Math.round(mid * 100) / 100;
};

/** Shape-style per-param editor for the Reactivity aspect: each added param can
 * be set exactly (or bound to a signal), nudged (in nudge mode), or removed
 * (= ignored). Params the target device's current effect lacks are ignored at
 * fire time, mirroring the Shape sub-field semantics. */
function ReactivityParams({ av, set, nudgeMode, menu }: {
  av: AspectValue;
  set: (fn: (v: AspectValue) => void) => void;
  nudgeMode: boolean;
  menu: Map<string, ReactMenuEntry>;
}) {
  const keys = [...new Set([
    ...Object.keys(av.reactivity_values ?? {}),
    ...Object.keys(av.reactivity_nudges ?? {}),
  ])];
  const addable = [...menu.entries()]
    .filter(([k]) => !keys.includes(k))
    .map(([k, m]) => ({ value: k, label: `${m.label} — ${m.effects.join(', ')}` }));

  const removeKey = (k: string) => set((x) => {
    const rv = { ...(x.reactivity_values ?? {}) };
    delete rv[k];
    const rn = { ...(x.reactivity_nudges ?? {}) };
    delete rn[k];
    x.reactivity_values = Object.keys(rv).length ? rv : null;
    x.reactivity_nudges = Object.keys(rn).length ? rn : null;
  });

  const addKey = (k: string) => {
    const m = menu.get(k);
    if (!m) return;
    if (m.type !== 'toggle' && nudgeMode) {
      set((x) => { x.reactivity_nudges = { ...(x.reactivity_nudges ?? {}), [k]: newNudge() }; });
    } else {
      set((x) => {
        x.reactivity_values = {
          ...(x.reactivity_values ?? {}),
          [k]: m.type === 'toggle' ? 'toggle' : midVal(m),
        };
      });
    }
  };

  return (
    <div style={{ marginTop: 6 }}>
      <div className="card-title" style={{ marginBottom: 4 }}>
        Per-param reactivity
        <span style={{ textTransform: 'none', letterSpacing: 0, marginLeft: 8 }}>
          (exact values in the param's own range; wins over the spread slider)
        </span>
      </div>
      {keys.map((k) => {
        const m = menu.get(k);
        const label = m?.label ?? k;
        const effectsHint = m ? `${k} — ${m.effects.join(', ')}` : k;
        const nudge = av.reactivity_nudges?.[k];
        if (m?.type === 'toggle') {
          return (
            <div key={k} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 6, fontSize: 12 }}>
              <span style={{ width: 110, color: 'var(--text-muted)', paddingTop: 4 }} title={effectsHint}>{label}</span>
              <BindableTri
                value={(av.reactivity_values?.[k] as boolean | 'toggle' | ValueBinding | undefined) ?? null}
                onChange={(v) => (v === null ? removeKey(k) : set((x) => {
                  x.reactivity_values = { ...(x.reactivity_values ?? {}), [k]: v };
                }))}
                renderScalar={(v, setV) => <TriState value={v} onChange={setV} />} />
              <button className="danger" style={{ fontSize: 11, padding: '2px 7px' }} onClick={() => removeKey(k)}>✕</button>
            </div>
          );
        }
        if (nudge) {
          return (
            <div key={k} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 12 }}>
              <div style={{ flex: 1 }}>
                <NudgeInput label={label} nudge={nudge}
                  onChange={(n) => (n === null ? removeKey(k) : set((x) => {
                    x.reactivity_nudges = { ...(x.reactivity_nudges ?? {}), [k]: n };
                  }))} />
              </div>
              <button className="danger" style={{ fontSize: 11, padding: '2px 7px' }} onClick={() => removeKey(k)}>✕</button>
            </div>
          );
        }
        return (
          <div key={k} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 6, fontSize: 12 }}>
            <span style={{ width: 110, color: 'var(--text-muted)', paddingTop: 4 }} title={effectsHint}>
              {label}
              {m && <span style={{ display: 'block', fontSize: 10 }}>{m.min}–{m.max}</span>}
            </span>
            <BindableNumber
              value={(av.reactivity_values?.[k] as number | ValueBinding | undefined) ?? null}
              nullable min={m?.min ?? undefined} max={m?.max ?? undefined} step={m ? stepFor(m) : 0.05} width={90}
              onChange={(v) => (v === null ? removeKey(k) : set((x) => {
                x.reactivity_values = { ...(x.reactivity_values ?? {}), [k]: v };
              }))} />
            <button className="danger" style={{ fontSize: 11, padding: '2px 7px' }} onClick={() => removeKey(k)}>✕</button>
          </div>
        );
      })}
      <SearchSelect value="" width={260} options={addable}
        placeholder={nudgeMode ? '+ add param nudge' : '+ add param'}
        onChange={(k) => { if (k) addKey(k); }} />
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
  const reactMenu = reactivityMenu(aspects);

  return (
    <div>
      <Row label="Name" help="Optional display name — shown in summaries and the Now Playing next-changes preview">
        <TextInput value={action.name ?? ''} placeholder="e.g. Punch"
          onChange={(v) => update((a) => { a.name = v; })} />
      </Row>
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
            {t.aspect === 'reactivity' && (
              <ReactivityParams av={av} set={setAV} nudgeMode={nudgeMode} menu={reactMenu} />
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
                <Row label="Flip" help="tri-state: on / off / toggle current. Melt reverses its motion direction (continuous, no restart); power mirrors the strip; radial flips spin; eq2d toggles ring">
                  <BindableTri value={av.flip ?? null} onChange={(v) => setAV((x) => { x.flip = v; })}
                    renderScalar={(v, set) => <TriState value={v} onChange={set} />} />
                </Row>
                <Row label="Reverse" help="Blackhole: flow direction; Orbits: spin direction — tri-state on / off / toggle current">
                  <BindableTri value={av.reverse ?? null} onChange={(v) => setAV((x) => { x.reverse = v; })}
                    renderScalar={(v, set) => <TriState value={v} onChange={set} />} />
                </Row>
                {!nudgeMode && (
                  <>
                    <Row label="Star (0–1)">
                      <BindableNumber value={av.star ?? null} nullable min={0} max={1} step={0.05}
                        onChange={(v) => setAV((x) => { x.star = v; })} />
                    </Row>
                    <Row label="Edge / particle count" help="Radial: polygon edges (0–8); Orbits: particle count (1–16, count changes animate — removed particles fly off, new ones fly in; Orbits Strip: new ones explode in); Fireworks: burst size (3–30 particles per firework)">
                      <BindableNumber value={av.edges ?? null} nullable min={0} step={1}
                        onChange={(v) => setAV((x) => { x.edges = typeof v === 'number' ? Math.round(v) : v; })} />
                    </Row>
                    <Row label="Twist">
                      <BindableNumber value={av.twist ?? null} nullable step={0.05}
                        onChange={(v) => setAV((x) => { x.twist = v; })} />
                    </Row>
                    <Row label="X offset (−1..1)" help="Center point X — radial, blackhole and orbits; strip variants rotate the pattern around the strip">
                      <BindableNumber value={av.x_offset ?? null} nullable min={-1} max={1} step={0.05}
                        onChange={(v) => setAV((x) => { x.x_offset = v; })} />
                    </Row>
                    <Row label="Y offset (−1..1)" help="Center point Y — radial, blackhole and orbits">
                      <BindableNumber value={av.y_offset ?? null} nullable min={-1} max={1} step={0.05}
                        onChange={(v) => setAV((x) => { x.y_offset = v; })} />
                    </Row>
                    <Row label="Swirl (−6..6)" help="Blackhole (2D and Strip): swirl amount, sign = direction">
                      <BindableNumber value={av.swirl ?? null} nullable min={-6} max={6} step={0.1}
                        onChange={(v) => setAV((x) => { x.swirl = v; })} />
                    </Row>
                    <Row label="Horizon size" help="Blackhole: event-horizon radius (0 disables); Orbits: tether ring radius (2D only)">
                      <BindableNumber value={av.horizon_scale ?? null} nullable min={0} max={0.8} step={0.05}
                        onChange={(v) => setAV((x) => { x.horizon_scale = v; })} />
                    </Row>
                    <Row label="Field radius" help="Blackhole/orbits: overall field scale as a fraction of the panel edge (0.2–2); Blackhole Strip: sample-ring radius along the fall">
                      <BindableNumber value={av.radius_scale ?? null} nullable min={0.2} max={2} step={0.05}
                        onChange={(v) => setAV((x) => { x.radius_scale = v; })} />
                    </Row>
                    <Row label="Blob size" help="Blackhole: blob size; Orbits: particle size (0.5–6)">
                      <BindableNumber value={av.blob_size ?? null} nullable min={0.5} max={6} step={0.1}
                        onChange={(v) => setAV((x) => { x.blob_size = v; })} />
                    </Row>
                  </>
                )}
                {nudgeMode && (
                  <div style={{ marginTop: 6 }}>
                    <div className="card-title">Per-sub-field nudges</div>
                    <NudgeInput label="star" nudge={av.star_nudge}
                      onChange={(n) => setAV((x) => { x.star_nudge = n; })} />
                    <NudgeInput label="edge / particle count" nudge={av.edges_nudge}
                      onChange={(n) => setAV((x) => { x.edges_nudge = n; })} />
                    <NudgeInput label="twist" nudge={av.twist_nudge}
                      onChange={(n) => setAV((x) => { x.twist_nudge = n; })} />
                    <NudgeInput label="x offset" nudge={av.x_offset_nudge}
                      onChange={(n) => setAV((x) => { x.x_offset_nudge = n; })} />
                    <NudgeInput label="y offset" nudge={av.y_offset_nudge}
                      onChange={(n) => setAV((x) => { x.y_offset_nudge = n; })} />
                    <NudgeInput label="swirl" nudge={av.swirl_nudge}
                      onChange={(n) => setAV((x) => { x.swirl_nudge = n; })} />
                    <NudgeInput label="horizon size" nudge={av.horizon_scale_nudge}
                      onChange={(n) => setAV((x) => { x.horizon_scale_nudge = n; })} />
                    <NudgeInput label="field radius" nudge={av.radius_scale_nudge}
                      onChange={(n) => setAV((x) => { x.radius_scale_nudge = n; })} />
                    <NudgeInput label="blob size" nudge={av.blob_size_nudge}
                      onChange={(n) => setAV((x) => { x.blob_size_nudge = n; })} />
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
