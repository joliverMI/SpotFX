/** Form for the `brightness` action: per-parameter keep / change / nudge on
 * the fg + bg brightness MULTIPLIERS (0..1, default 1) that scale whatever
 * the Color Set / Color Group pipeline writes. Change values and nudge
 * amounts are bindable (⚡ intensity / 🎲 random); nudges also carry an
 * intensity scale and a ± random-sign flip. */
import type { Action, BrightnessMode, NumericNudge } from '../../types/events';
import { Checkbox, NumberInput, Row, Select } from './inputs';
import { ParentScopeToggle, emptyScope } from './ScopePicker';
import { BindableNumber } from './BindingInput';
import HelpLink from '../../help/HelpLink';

type BrightnessAction = Extract<Action, { type: 'brightness' }>;
type Update = (fn: (a: Action) => void) => void;

const MODES = [
  { value: 'keep', label: '— keep —' },
  { value: 'absolute', label: 'change' },
  { value: 'nudge', label: 'nudge' },
];

const newNudge = (): NumericNudge =>
  ({ amount: 0.1, scale: 0, random_sign: false, wrap: false, lo: null, hi: null });

/** One multiplier parameter: mode select + the mode's inputs on one row. */
function ParamRow({ label, help, mode, value, nudge, set }: {
  label: string;
  help: string;
  mode: BrightnessMode;
  value: BrightnessAction['brightness_value'];
  nudge: NumericNudge | null;
  set: (patch: {
    mode?: BrightnessMode;
    value?: BrightnessAction['brightness_value'];
    nudge?: NumericNudge | null;
  }) => void;
}) {
  const n = nudge ?? null;
  return (
    <>
      <Row label={label} help={help}>
        <Select value={mode} width={110}
          onChange={(v) => {
            const m = v as BrightnessMode;
            set({
              mode: m,
              // Seed the mode's payload so the inputs appear populated.
              ...(m === 'absolute' && value == null ? { value: 1 } : {}),
              ...(m === 'nudge' && n == null ? { nudge: newNudge() } : {}),
            });
          }}
          options={MODES} />
        {mode === 'absolute' && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
            <span style={{ color: 'var(--text-muted)' }}
              title="Multiplier 0..1 — 1 = the Color Set value as authored; ⚡ maps it to a music signal, 🎲 rolls it fresh every fire">×</span>
            <BindableNumber value={value ?? 1} min={0} max={1} step={0.05} width={80}
              onChange={(v) => set({ value: v ?? 1 })} />
          </label>
        )}
        {mode === 'nudge' && n && (
          <>
            <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
              <span style={{ color: 'var(--text-muted)' }}
                title="Added to the current multiplier per fire (negative ok); ⚡ maps it to a music signal, 🎲 rolls it fresh every fire">amt</span>
              <BindableNumber value={n.amount} min={-1} max={1} step={0.05} width={72}
                onChange={(v) => set({ nudge: { ...n, amount: v ?? 0 } })} />
            </label>
            <button title="Random sign — nudge up or down by the same magnitude, 50/50 per fire"
              style={{
                padding: '2px 6px', fontSize: 12, flex: 'none',
                borderColor: n.random_sign ? 'var(--accent)' : 'var(--border)',
                color: n.random_sign ? 'var(--accent)' : 'var(--text-muted)',
              }}
              onClick={() => set({ nudge: { ...n, random_sign: !n.random_sign } })}>
              +/−
            </button>
            <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
              <span style={{ color: 'var(--text-muted)' }} title="0 = ignore beat intensity, 1 = full">scale</span>
              <NumberInput value={n.scale} min={0} max={1} step={0.05} width={72}
                onChange={(v) => set({ nudge: { ...n, scale: v ?? 0 } })} />
            </label>
            <Checkbox value={n.wrap} label="bounce"
              onChange={(v) => set({ nudge: { ...n, wrap: v } })} />
            <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
              <span style={{ color: 'var(--text-muted)' }} title="custom range within 0..1 (blank = 0..1)">lo</span>
              <NumberInput value={n.lo} nullable min={0} max={1} step={0.05} width={64}
                onChange={(v) => set({ nudge: { ...n, lo: v } })} />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
              <span style={{ color: 'var(--text-muted)' }}>hi</span>
              <NumberInput value={n.hi} nullable min={0} max={1} step={0.05} width={64}
                onChange={(v) => set({ nudge: { ...n, hi: v } })} />
            </label>
          </>
        )}
      </Row>
    </>
  );
}

export default function BrightnessForm({ action, update }: { action: BrightnessAction; update: Update }) {
  const set = (fn: (a: BrightnessAction) => void) =>
    update((a) => { if (a.type === 'brightness') fn(a); });
  const anyScaled =
    (action.brightness_mode === 'nudge' && !!action.brightness_nudge?.scale) ||
    (action.bg_mode === 'nudge' && !!action.bg_nudge?.scale);
  return (
    <>
      <p className="empty-note" style={{ marginTop: 0 }}>
        Multiplies the Color Set / Group brightness values (0..1, default 1) on
        the targeted devices — applies now and to every later Set Color.
        Resets to 1 on track change. <HelpLink topic="brightness-action" />
      </p>
      <Row label="Target" help="Devices/categories whose multipliers change; parent = inherit the nearest group/lane Target">
        <ParentScopeToggle scope={action.scope}
          onChange={(s) => set((a) => { a.scope = s ?? emptyScope(); })} />
      </Row>
      <ParamRow label="Brightness"
        help="Effect (foreground) brightness multiplier"
        mode={action.brightness_mode}
        value={action.brightness_value}
        nudge={action.brightness_nudge}
        set={(p) => set((a) => {
          if (p.mode !== undefined) a.brightness_mode = p.mode;
          if (p.value !== undefined) a.brightness_value = p.value;
          if (p.nudge !== undefined) a.brightness_nudge = p.nudge;
        })} />
      <ParamRow label="BG Brightness"
        help="Background brightness multiplier"
        mode={action.bg_mode}
        value={action.bg_value}
        nudge={action.bg_nudge}
        set={(p) => set((a) => {
          if (p.mode !== undefined) a.bg_mode = p.mode;
          if (p.value !== undefined) a.bg_value = p.value;
          if (p.nudge !== undefined) a.bg_nudge = p.nudge;
        })} />
      <Row label="Ramp (ms)" help="Blank = the global smooth-ramp default; 0 = instant">
        <BindableNumber value={action.ramp_ms} nullable onChange={(v) => set((a) => { a.ramp_ms = v; })} />
      </Row>
      {anyScaled && (
        <Row label="Intensity source" help="Beat signal feeding both nudges' intensity scale">
          <Select value={action.intensity_source} width={140}
            onChange={(v) => set((a) => { a.intensity_source = v as typeof a.intensity_source; })}
            options={[
              { value: 'rms_total', label: 'RMS Total' },
              { value: 'rms_bass', label: 'RMS Bass' },
              { value: 'onset_score', label: 'Onset Score' },
            ]} />
        </Row>
      )}
    </>
  );
}
