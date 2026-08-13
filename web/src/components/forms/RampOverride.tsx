/** Parent/Override toggle for a cascading ramp override (scenes, scene groups,
 * choosers). "parent" = no override at this level — the nearest ancestor
 * override applies, else each action keeps its own ramp. "override" = force
 * this ramp (ms) on every descendant action's ramps; the deepest override
 * wins (scene > scene group > chooser). The value is ⚡/🎲-bindable — e.g.
 * map trigger intensity 0→1500ms, 1→250ms so hard hits snap and quiet
 * sections glide. */
import { useEffect, useState, type CSSProperties } from 'react';
import type { Bindable } from '../../types/events';
import { BindableNumber } from './BindingInput';

export default function RampOverride({
  value,
  onChange,
  defaultMs = 250,
}: {
  value: Bindable<number> | null | undefined;
  onChange: (v: Bindable<number> | null) => void;
  defaultMs?: number;
}) {
  const [override, setOverride] = useState(value != null);
  useEffect(() => {
    if (value != null) setOverride(true);
  }, [value]);

  const btn = (active: boolean): CSSProperties => ({
    fontSize: 11, padding: '3px 10px', border: 'none', borderRadius: 0,
    background: active ? 'var(--accent)' : 'transparent',
    color: active ? '#06130a' : 'var(--text-muted)',
  });
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <span style={{ display: 'inline-flex', border: '1px solid var(--border)', borderRadius: 999, overflow: 'hidden' }}>
        <button style={btn(!override)}
          title="No override here — the nearest ancestor override applies, else each action's own ramp"
          onClick={() => { setOverride(false); onChange(null); }}>
          parent
        </button>
        <button style={btn(override)}
          title="Force this ramp (ms) on everything this fires — deeper overrides still win"
          onClick={() => { setOverride(true); if (value == null) onChange(defaultMs); }}>
          override
        </button>
      </span>
      {override && (
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
          <BindableNumber value={value ?? defaultMs} min={0} step={50} width={90}
            onChange={(v) => onChange(v ?? defaultMs)} />
          <span style={{ color: 'var(--text-muted)' }}>ms</span>
        </label>
      )}
    </span>
  );
}
