/** Bindable field wrappers: a ⚡ toggle swaps a plain input for a compact
 * binding editor (signal + beat window + map/steps); its 🎲 sibling makes
 * the same binding but with the `random` signal — a fresh uniform roll per
 * fire, so map mode picks a random value in [out_min, out_max]. Mirrors
 * services/signal_resolver.py semantics — see models/value_binding.py. */
import type { ReactNode } from 'react';
import type { BindingStep, SignalName, ValueBinding } from '../../types/events';
import { isBinding } from '../../types/events';
import { Checkbox, NumberInput, Select } from './inputs';

export type ValueKind = 'number' | 'tri' | 'toggle';

const SIGNALS: { value: SignalName; label: string }[] = [
  { value: 'rms_total', label: 'Beat RMS' },
  { value: 'rms_bass', label: 'Bass RMS' },
  { value: 'onset_score', label: 'Onset' },
  { value: 'section_energy', label: 'Section energy' },
  { value: 'trigger_intensity', label: 'Trigger intensity' },
  { value: 'random', label: 'Random 🎲' },
];

export function newBinding(kind: ValueKind, outMin = 0, outMax = 1, signal: SignalName = 'rms_total'): ValueBinding {
  return {
    bind: 'signal',
    signal,
    window_beats: 0,
    window_dir: 'past',
    mode: kind === 'number' ? 'map' : 'steps',
    in_min: 0,
    in_max: 1,
    out_min: outMin,
    out_max: outMax,
    steps: kind === 'number' ? [] : [{ threshold: 0.5, value: kind === 'toggle' ? 'toggle' : true }],
    fallback: null,
    random_sign: false,
  };
}

function StepValueInput({ kind, value, onChange }: {
  kind: ValueKind;
  value: number | boolean | string;
  onChange: (v: number | boolean | string) => void;
}) {
  if (kind === 'number') {
    return (
      <NumberInput value={typeof value === 'number' ? value : 0} width={80}
        onChange={(v) => onChange(v ?? 0)} />
    );
  }
  if (kind === 'tri') {
    const str = value === true ? 'on' : value === false ? 'off' : 'toggle';
    return (
      <Select value={str} width={100}
        onChange={(v) => onChange(v === 'toggle' ? 'toggle' : v === 'on')}
        options={['on', 'off', 'toggle'].map((v) => ({ value: v, label: v }))} />
    );
  }
  return (
    <Select value={String(value)} width={100}
      onChange={(v) => onChange(v)}
      options={['on', 'off', 'toggle'].map((v) => ({ value: v, label: v }))} />
  );
}

export function BindingEditor({ binding, onChange, kind }: {
  binding: ValueBinding;
  onChange: (b: ValueBinding) => void;
  kind: ValueKind;
}) {
  const set = (patch: Partial<ValueBinding>) => onChange({ ...binding, ...patch });
  const setStep = (i: number, patch: Partial<BindingStep>) => {
    const steps = binding.steps.map((s, j) => (j === i ? { ...s, ...patch } : s));
    set({ steps });
  };
  const sortSteps = () => set({ steps: [...binding.steps].sort((a, b) => a.threshold - b.threshold) });
  const stepsOnly = kind !== 'number';
  const isRandom = binding.signal === 'random';

  return (
    <div style={{ border: '1px solid var(--accent)', borderRadius: 8, padding: 8, marginTop: 4,
                  display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ color: 'var(--accent)' }}>{isRandom ? '🎲 random' : '⚡ signal'}</span>
        <Select value={binding.signal} width={140}
          onChange={(v) => set({ signal: v as SignalName })}
          options={SIGNALS} />
        {binding.signal !== 'section_energy' && binding.signal !== 'trigger_intensity' && !isRandom && (
          <>
            <span style={{ color: 'var(--text-muted)' }} title="0 = current beat; N = rolling mean over N beats">window</span>
            <NumberInput value={binding.window_beats} min={0} step={1} width={64}
              onChange={(v) => set({ window_beats: Math.max(0, Math.round(v ?? 0)) })} />
            {binding.window_beats > 0 && (
              <Select value={binding.window_dir} width={104}
                onChange={(v) => set({ window_dir: v as ValueBinding['window_dir'] })}
                options={['past', 'future', 'centered'].map((v) => ({ value: v, label: v }))} />
            )}
          </>
        )}
        {!stepsOnly && (
          <Select value={binding.mode} width={90}
            onChange={(v) => set({ mode: v as 'map' | 'steps' })}
            options={[{ value: 'map', label: 'map' }, { value: 'steps', label: 'steps' }]} />
        )}
        {kind === 'number' && (
          <button title="Random sign — the result flips to negative 50% of the time (per fire). Clamped fields still clamp after the flip."
            style={{
              padding: '2px 6px', fontSize: 12, flex: 'none',
              borderColor: binding.random_sign ? 'var(--accent)' : 'var(--border)',
              color: binding.random_sign ? 'var(--accent)' : 'var(--text-muted)',
            }}
            onClick={() => set({ random_sign: !binding.random_sign })}>
            +/−
          </button>
        )}
      </div>

      {binding.mode === 'map' && !stepsOnly && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          {!isRandom && (
            <>
              <span style={{ color: 'var(--text-muted)' }}>signal</span>
              <NumberInput value={binding.in_min} step={0.05} width={64} onChange={(v) => set({ in_min: v ?? 0 })} />
              <span style={{ color: 'var(--text-muted)' }}>–</span>
              <NumberInput value={binding.in_max} step={0.05} width={64} onChange={(v) => set({ in_max: v ?? 1 })} />
              <span style={{ color: 'var(--text-muted)' }}>→ value</span>
            </>
          )}
          {isRandom && <span style={{ color: 'var(--text-muted)' }} title="A fresh uniform pick between these two values on every fire">random value</span>}
          <NumberInput value={binding.out_min} width={80} onChange={(v) => set({ out_min: v ?? 0 })} />
          <span style={{ color: 'var(--text-muted)' }}>–</span>
          <NumberInput value={binding.out_max} width={80} onChange={(v) => set({ out_max: v ?? 1 })} />
        </div>
      )}

      {(binding.mode === 'steps' || stepsOnly) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {binding.steps.map((st, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ color: 'var(--text-muted)' }}>≥</span>
              <NumberInput value={st.threshold} step={0.05} width={72}
                onChange={(v) => setStep(i, { threshold: v ?? 0 })} />
              <span style={{ color: 'var(--text-muted)' }}>→</span>
              <StepValueInput kind={kind} value={st.value} onChange={(v) => setStep(i, { value: v })} />
              <button className="danger" style={{ fontSize: 10, padding: '1px 6px' }}
                onClick={() => set({ steps: binding.steps.filter((_, j) => j !== i) })}>✕</button>
            </div>
          ))}
          <span>
            <button style={{ fontSize: 11 }}
              onClick={() => set({ steps: [...binding.steps, { threshold: 0.5, value: kind === 'number' ? 0 : kind === 'toggle' ? 'on' : true }] })}>
              + step
            </button>
            {binding.steps.length > 1 && (
              <button style={{ fontSize: 11, marginLeft: 4 }} onClick={sortSteps}>sort</button>
            )}
          </span>
        </div>
      )}

      {!(isRandom && binding.mode === 'map') && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <Checkbox value={binding.fallback !== null}
            label={isRandom ? 'fallback (below first step)' : 'fallback (no signal / below first step)'}
            onChange={(v) => set({ fallback: v ? (kind === 'number' ? 0 : kind === 'toggle' ? 'off' : false) : null })} />
          {binding.fallback !== null && (
            <StepValueInput kind={kind} value={binding.fallback} onChange={(v) => set({ fallback: v })} />
          )}
        </div>
      )}
    </div>
  );
}

/** ⚡ / 🎲 toggle button shared by the wrappers. */
function BindButton({ icon, active, onClick, title }: { icon: string; active: boolean; onClick: () => void; title: string }) {
  return (
    <button title={title}
      style={{
        padding: '2px 6px', fontSize: 12, flex: 'none',
        borderColor: active ? 'var(--accent)' : 'var(--border)',
        color: active ? 'var(--accent)' : 'var(--text-muted)',
      }}
      onClick={onClick}>
      {icon}
    </button>
  );
}

/** The ⚡ + 🎲 button pair: ⚡ binds to a music signal, 🎲 binds to a random
 * roll. Clicking the active one unbinds; clicking the other while bound just
 * switches the binding's signal (keeping ranges / steps). */
function BindButtons({ value, kind, unbindValue, makeBinding, onChange }: {
  value: unknown;
  kind: ValueKind;
  unbindValue: () => unknown;
  makeBinding: (signal: SignalName) => ValueBinding;
  onChange: (v: never) => void;
}) {
  const bound = isBinding(value);
  const random = bound && (value as ValueBinding).signal === 'random';
  const setV = onChange as (v: unknown) => void;
  const stepsHint = kind === 'number' ? '' : ' (threshold steps)';
  return (
    <>
      <BindButton icon="⚡" active={bound && !random}
        title={bound && !random ? 'Unbind — back to a fixed value'
          : random ? 'Switch to a music signal' : `Bind to a music signal${stepsHint}`}
        onClick={() => setV(!bound ? makeBinding('rms_total')
          : random ? { ...(value as ValueBinding), signal: 'rms_total' }
          : unbindValue())} />
      <BindButton icon="🎲" active={random}
        title={random ? 'Unbind — back to a fixed value'
          : bound ? 'Switch to a random roll' : `Bind to a random roll — a fresh random value every fire${stepsHint}`}
        onClick={() => setV(!bound ? makeBinding('random')
          : !random ? { ...(value as ValueBinding), signal: 'random' }
          : unbindValue())} />
    </>
  );
}

export function BindableNumber({ value, onChange, min, max, step, nullable, width }: {
  value: number | ValueBinding | null;
  onChange: (v: number | ValueBinding | null) => void;
  min?: number;
  max?: number;
  step?: number;
  nullable?: boolean;
  width?: number;
}) {
  const bound = isBinding(value);
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, flex: bound ? 1 : undefined }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        {!bound && (
          <NumberInput value={value} min={min} max={max} step={step} nullable={nullable} width={width}
            onChange={(v) => onChange(v)} />
        )}
        <BindButtons value={value} kind="number" onChange={onChange}
          unbindValue={() => (typeof (value as ValueBinding).out_min === 'number' ? (value as ValueBinding).out_min : nullable ? null : 0)}
          makeBinding={(signal) => newBinding('number', min ?? 0, max ?? 1, signal)} />
      </span>
      {bound && <BindingEditor binding={value as ValueBinding} onChange={onChange} kind="number" />}
    </span>
  );
}

export function BindableTri({ value, onChange, renderScalar }: {
  value: boolean | 'toggle' | ValueBinding | null;
  onChange: (v: boolean | 'toggle' | ValueBinding | null) => void;
  renderScalar: (v: boolean | 'toggle' | null, set: (v: boolean | 'toggle' | null) => void) => ReactNode;
}) {
  const bound = isBinding(value);
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, flex: bound ? 1 : undefined }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        {!bound && renderScalar(value as boolean | 'toggle' | null, onChange)}
        <BindButtons value={value} kind="tri" onChange={onChange}
          unbindValue={() => null}
          makeBinding={(signal) => newBinding('tri', 0, 1, signal)} />
      </span>
      {bound && <BindingEditor binding={value as ValueBinding} onChange={onChange} kind="tri" />}
    </span>
  );
}

export function BindableToggle({ value, onChange, renderScalar }: {
  value: string | ValueBinding | null;
  onChange: (v: string | ValueBinding | null) => void;
  renderScalar: (v: string | null, set: (v: string | null) => void) => ReactNode;
}) {
  const bound = isBinding(value);
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, flex: bound ? 1 : undefined }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        {!bound && renderScalar(value as string | null, onChange)}
        <BindButtons value={value} kind="toggle" onChange={onChange}
          unbindValue={() => 'toggle'}
          makeBinding={(signal) => newBinding('toggle', 0, 1, signal)} />
      </span>
      {bound && <BindingEditor binding={value as ValueBinding} onChange={onChange} kind="toggle" />}
    </span>
  );
}
