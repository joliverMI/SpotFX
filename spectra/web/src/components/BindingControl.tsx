/** The ⚡/🎲 affordance on every value — rebuilt in SPECTRA mirroring the
 * events page's component contract exactly (button semantics, map/steps/
 * fallback/± sign, steps-only for toggles and enums) plus the ONE growth:
 * a dice letter on 🎲 bindings, so values sharing a letter share one roll
 * per fire (correlated variants land as authored pairs).
 *
 * The ⚡ source menu here offers trigger intensity + random (the owner's
 * words for this page); agent-authored bindings on wider signals still
 * render, their signal shown read-only. */
import type { ReactNode } from 'react';
import type { BindingStep, SignalName, ValueBinding } from '../types';
import { isBinding } from '../types';
import { Checkbox, NumberInput, Select } from './inputs';

export type ValueKind = 'number' | 'toggle' | 'option';

const PAGE_SIGNALS: { value: SignalName; label: string }[] = [
  { value: 'trigger_intensity', label: 'Intensity' },
  { value: 'random', label: 'Random 🎲' },
];
const WIDE_SIGNALS: Record<string, string> = {
  rms_total: 'Beat RMS', rms_bass: 'Bass RMS', onset_score: 'Onset',
  section_energy: 'Section energy',
};
const DICE_LETTERS = ['a', 'b', 'c', 'd', 'e', 'f'];

export function newBinding(kind: ValueKind, outMin = 0, outMax = 1,
                           signal: SignalName = 'trigger_intensity',
                           firstOption?: string): ValueBinding {
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
    steps: kind === 'number' ? []
      : [{ threshold: 0.5, value: kind === 'toggle' ? true : firstOption ?? '' }],
    fallback: null,
    random_sign: false,
    dice: null,
  };
}

function StepValueInput({ kind, value, options, onChange }: {
  kind: ValueKind;
  value: number | boolean | string;
  options?: string[];
  onChange: (v: number | boolean | string) => void;
}) {
  if (kind === 'number') {
    return (
      <NumberInput value={typeof value === 'number' ? value : 0} width={80}
        onChange={(v) => onChange(v ?? 0)} />
    );
  }
  if (kind === 'toggle') {
    return (
      <Select value={value === true ? 'on' : 'off'} width={90}
        onChange={(v) => onChange(v === 'on')}
        options={[{ value: 'on', label: 'on' }, { value: 'off', label: 'off' }]} />
    );
  }
  return (
    <Select value={String(value)} width={130}
      onChange={(v) => onChange(v)}
      options={(options ?? [String(value)]).map((o) => ({ value: o, label: o }))} />
  );
}

export function BindingEditor({ binding, onChange, kind, options }: {
  binding: ValueBinding;
  onChange: (b: ValueBinding) => void;
  kind: ValueKind;
  options?: string[];
}) {
  const set = (patch: Partial<ValueBinding>) => onChange({ ...binding, ...patch });
  const setStep = (i: number, patch: Partial<BindingStep>) => {
    const steps = binding.steps.map((s, j) => (j === i ? { ...s, ...patch } : s));
    set({ steps });
  };
  const sortSteps = () => set({ steps: [...binding.steps].sort((a, b) => a.threshold - b.threshold) });
  const stepsOnly = kind !== 'number';
  const isRandom = binding.signal === 'random';
  const wideSignal = WIDE_SIGNALS[binding.signal];

  return (
    <div style={{ border: '1px solid var(--accent)', borderRadius: 8, padding: 8, marginTop: 4,
                  display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ color: 'var(--accent)' }}>{isRandom ? '🎲 random' : '⚡ signal'}</span>
        {wideSignal ? (
          <span className="chip" title="An agent-authored signal beyond this page's menu — edit via the agent">
            {wideSignal}
          </span>
        ) : (
          <Select value={binding.signal} width={130}
            onChange={(v) => set({ signal: v as SignalName, ...(v !== 'random' ? { dice: null } : {}) })}
            options={PAGE_SIGNALS} />
        )}
        {isRandom && (
          <>
            <span style={{ color: 'var(--text-muted)' }}
              title="Dice letter — 🎲 values sharing a letter share ONE roll per fire, so correlated variants land together. — keeps an independent roll.">
              dice
            </span>
            <Select value={binding.dice ?? ''} width={64}
              onChange={(v) => set({ dice: v === '' ? null : v })}
              options={[{ value: '', label: '—' },
                        ...DICE_LETTERS.map((l) => ({ value: l, label: l.toUpperCase() }))]} />
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
              <StepValueInput kind={kind} value={st.value} options={options}
                onChange={(v) => setStep(i, { value: v })} />
              <button className="danger" style={{ fontSize: 10, padding: '1px 6px' }}
                onClick={() => set({ steps: binding.steps.filter((_, j) => j !== i) })}>✕</button>
            </div>
          ))}
          <span>
            <button style={{ fontSize: 11 }}
              onClick={() => set({
                steps: [...binding.steps, {
                  threshold: 0.5,
                  value: kind === 'number' ? 0 : kind === 'toggle' ? true : options?.[0] ?? '',
                }],
              })}>
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
            onChange={(v) => set({
              fallback: v ? (kind === 'number' ? 0 : kind === 'toggle' ? false : options?.[0] ?? '') : null,
            })} />
          {binding.fallback !== null && (
            <StepValueInput kind={kind} value={binding.fallback} options={options}
              onChange={(v) => set({ fallback: v })} />
          )}
        </div>
      )}
    </div>
  );
}

function BindButton({ icon, active, onClick, title }: {
  icon: string; active: boolean; onClick: () => void; title: string;
}) {
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

/** The ⚡ + 🎲 pair. Clicking the active one unbinds; clicking the other
 * while bound just switches the binding's signal (keeping ranges/steps). */
export function BindButtons({ value, kind, unbindValue, makeBinding, onChange }: {
  value: unknown;
  kind: ValueKind;
  unbindValue: () => unknown;
  makeBinding: (signal: SignalName) => ValueBinding;
  onChange: (v: never) => void;
}) {
  const bound = isBinding(value);
  const random = bound && value.signal === 'random';
  const setV = onChange as (v: unknown) => void;
  const stepsHint = kind === 'number' ? '' : ' (threshold steps)';
  return (
    <>
      <BindButton icon="⚡" active={bound && !random}
        title={bound && !random ? 'Unbind — back to a fixed value'
          : random ? 'Switch to the intensity signal' : `Map intensity to this value${stepsHint}`}
        onClick={() => setV(!bound ? makeBinding('trigger_intensity')
          : random ? { ...value, signal: 'trigger_intensity', dice: null }
          : unbindValue())} />
      <BindButton icon="🎲" active={random}
        title={random ? 'Unbind — back to a fixed value'
          : bound ? 'Switch to a random roll' : `Random per fire${stepsHint}`}
        onClick={() => setV(!bound ? makeBinding('random')
          : !random ? { ...value, signal: 'random' }
          : unbindValue())} />
    </>
  );
}

/** Bindable number: slider + number box when fixed; binding panel when bound. */
export function BindableNumber({ value, onChange, min, max, step, slider, width }: {
  value: number | ValueBinding | null;
  onChange: (v: number | ValueBinding | null) => void;
  min?: number;
  max?: number;
  step?: number;
  slider?: boolean;
  width?: number;
}) {
  const bound = isBinding(value);
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, flex: 1, minWidth: 0 }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        {!bound && slider && typeof value === 'number' && min !== undefined && max !== undefined && (
          <input type="range" min={min} max={max} step={step ?? (max - min) / 100}
            value={value}
            onChange={(e) => onChange(Number(e.target.value))} />
        )}
        {!bound && (
          <NumberInput value={typeof value === 'number' ? value : null} min={min} max={max}
            step={step} width={width ?? 76}
            onChange={(v) => onChange(v)} />
        )}
        <BindButtons value={value} kind="number" onChange={onChange}
          unbindValue={() => (isBinding(value) && typeof value.fallback === 'number' ? value.fallback
            : isBinding(value) ? value.out_min : 0)}
          makeBinding={(signal) => {
            const b = newBinding('number', min ?? 0, max ?? 1, signal);
            if (typeof value === 'number') b.fallback = value;
            return b;
          }} />
      </span>
      {bound && <BindingEditor binding={value} onChange={onChange} kind="number" />}
    </span>
  );
}

export function BindableToggle({ value, onChange, renderScalar }: {
  value: boolean | ValueBinding | null;
  onChange: (v: boolean | ValueBinding | null) => void;
  renderScalar: (v: boolean | null, set: (v: boolean) => void) => ReactNode;
}) {
  const bound = isBinding(value);
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, flex: bound ? 1 : undefined }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        {!bound && renderScalar(value as boolean | null, onChange)}
        <BindButtons value={value} kind="toggle" onChange={onChange}
          unbindValue={() => (isBinding(value) && typeof value.fallback === 'boolean' ? value.fallback : false)}
          makeBinding={(signal) => {
            const b = newBinding('toggle', 0, 1, signal);
            if (typeof value === 'boolean') b.fallback = value;
            return b;
          }} />
      </span>
      {bound && <BindingEditor binding={value} onChange={onChange} kind="toggle" />}
    </span>
  );
}

/** Bindable enum/string option (e.g. dance style) — steps-only. */
export function BindableOption({ value, onChange, options }: {
  value: string | ValueBinding | null;
  onChange: (v: string | ValueBinding | null) => void;
  options: string[];
}) {
  const bound = isBinding(value);
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2, flex: 1, minWidth: 0 }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        {!bound && (
          <Select value={typeof value === 'string' ? value : ''} width={150}
            onChange={(v) => onChange(v)}
            options={[
              ...(typeof value === 'string' || !options.length ? [] : [{ value: '', label: '—' }]),
              ...options.map((o) => ({ value: o, label: o })),
            ]} />
        )}
        <BindButtons value={value} kind="option" onChange={onChange}
          unbindValue={() => (isBinding(value) && typeof value.fallback === 'string' ? value.fallback : options[0] ?? '')}
          makeBinding={(signal) => {
            const b = newBinding('option', 0, 1, signal, options[0]);
            if (typeof value === 'string') b.fallback = value;
            return b;
          }} />
      </span>
      {bound && <BindingEditor binding={value} onChange={onChange} kind="option" options={options} />}
    </span>
  );
}
