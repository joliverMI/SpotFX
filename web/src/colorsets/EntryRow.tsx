/** One Color Set entry: scope + FG color (gradient/solid) + BG color/mode +
 * brightness pair + third color + ramp. Reuses the events page's ScopeSelect. */
import { ScopeSelect } from '../components/forms/ScopePicker';
import type { ColorSetEntry, SavedGradient } from './types';

/** Checkbox that enables/disables a nullable field. */
function Toggle({ label, on, onChange }: { label: string; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--text-muted)', cursor: 'pointer' }}>
      <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export default function EntryRow({
  entry,
  gradients,
  onChange,
  onRemove,
  onEditGradient,
  selected = false,
  onToggleSelect,
}: {
  entry: ColorSetEntry;
  gradients: SavedGradient[];
  onChange: (e: ColorSetEntry) => void;
  onRemove: () => void;
  onEditGradient: () => void;
  selected?: boolean;
  onToggleSelect?: () => void;
}) {
  const fgEn = !!entry.color_value;
  const isSolid = (entry.color_kind ?? 'gradient') === 'solid';
  const inLib = gradients.some((g) => g.value === entry.color_value);
  const set = (patch: Partial<ColorSetEntry>) => onChange({ ...entry, ...patch });

  return (
    <div
      title={onToggleSelect ? 'Shift+click to select for copy' : undefined}
      onClick={(e) => {
        if (!e.shiftKey || !onToggleSelect) return;
        if ((e.target as HTMLElement).closest('input,select,button,textarea,label')) return;
        e.preventDefault();
        onToggleSelect();
      }}
      style={{
        background: 'var(--surface2)', padding: 8, borderRadius: 'var(--radius)', marginBottom: 8,
        boxShadow: selected ? 'inset 0 0 0 2px var(--accent)' : undefined,
      }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <ScopeSelect
          scope={entry.scope}
          onChange={(s) => set({ scope: s ?? { virtual_ids: [], categories: [], roles: [] } })}
          width={220}
        />
        <button className="danger" style={{ fontSize: 11, padding: '2px 8px', marginLeft: 'auto' }}
          title="Remove entry" onClick={onRemove}>✕</button>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 6 }}>
        <Toggle label="Color" on={fgEn}
          onChange={(on) => set(on
            ? { color_kind: entry.color_kind ?? 'gradient', color_value: isSolid ? '#ffffff' : gradients[0]?.value ?? '#ffffff' }
            : { color_kind: null, color_value: null })} />
        {fgEn && (
          <select value={isSolid ? 'solid' : 'gradient'} style={{ fontSize: 12 }}
            onChange={(e) => {
              const solid = e.target.value === 'solid';
              set({ color_kind: solid ? 'solid' : 'gradient', color_value: solid ? '#ffffff' : gradients[0]?.value ?? '' });
            }}>
            <option value="gradient">Gradient</option>
            <option value="solid">Solid</option>
          </select>
        )}
        {fgEn && !isSolid && (
          <>
            <select value={entry.color_value ?? ''} style={{ width: 180, fontSize: 12 }}
              onChange={(e) => set({ color_kind: 'gradient', color_value: e.target.value })}>
              {entry.color_value && !inLib && <option value={entry.color_value}>(unsaved)</option>}
              {gradients.map((g) => <option key={g.id} value={g.value}>{g.name}</option>)}
            </select>
            <button style={{ fontSize: 12, padding: '2px 8px' }} title="Edit / save gradient" onClick={onEditGradient}>✎</button>
          </>
        )}
        {fgEn && isSolid && (
          <input type="color" value={entry.color_value ?? '#ffffff'} style={{ width: 48, height: 30, padding: 1 }}
            onChange={(e) => set({ color_kind: 'solid', color_value: e.target.value })} />
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 6 }}>
        <Toggle label="BG Color" on={entry.bg_color != null}
          onChange={(on) => set({ bg_color: on ? '#000000' : null })} />
        {entry.bg_color != null && (
          <input type="color" value={entry.bg_color} style={{ width: 48, height: 30, padding: 1 }}
            onChange={(e) => set({ bg_color: e.target.value })} />
        )}
        <span style={{ marginLeft: 12 }} />
        <Toggle label="BG Mode" on={entry.bg_mode != null}
          onChange={(on) => set({ bg_mode: on ? 'overwrite' : null })} />
        {entry.bg_mode != null && (
          <select value={entry.bg_mode} style={{ fontSize: 12 }}
            onChange={(e) => set({ bg_mode: e.target.value as 'overwrite' | 'additive' })}>
            <option value="overwrite">Overwrite</option>
            <option value="additive">Additive</option>
          </select>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>Color ramp (ms)</span>
        <input type="number" min={0} step={50} placeholder="step default" style={{ width: 90 }}
          value={entry.ramp_ms ?? ''}
          onChange={(e) => set({ ramp_ms: e.target.value === '' ? null : parseInt(e.target.value) })} />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 6 }}>
        <Toggle label="Brightness" on={entry.brightness != null}
          onChange={(on) => set({ brightness: on ? 0.8 : null })} />
        {entry.brightness != null && (
          <SliderPair value={entry.brightness} onChange={(v) => set({ brightness: v })} />
        )}
        <span style={{ marginLeft: 12 }} />
        <Toggle label="BG Brightness" on={entry.background_brightness != null}
          onChange={(on) => set({ background_brightness: on ? 0.3 : null })} />
        {entry.background_brightness != null && (
          <SliderPair value={entry.background_brightness} onChange={(v) => set({ background_brightness: v })} />
        )}
        <span style={{ marginLeft: 12 }} />
        <Toggle label="Third Color" on={entry.accent_color != null}
          onChange={(on) => set({ accent_color: on ? '#000000' : null })} />
        {entry.accent_color != null && (
          <input type="color" value={entry.accent_color} style={{ width: 48, height: 30, padding: 1 }}
            onChange={(e) => set({ accent_color: e.target.value })} />
        )}
      </div>
    </div>
  );
}

function SliderPair({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <>
      <input type="range" min={0} max={1} step={0.01} value={value}
        style={{ width: 96, accentColor: 'var(--accent)' }}
        onChange={(e) => onChange(parseFloat(e.target.value))} />
      <input type="number" min={0} max={1} step={0.01} value={value.toFixed(2)} style={{ width: 72 }}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          if (!Number.isNaN(v)) onChange(Math.max(0, Math.min(1, v)));
        }} />
    </>
  );
}
