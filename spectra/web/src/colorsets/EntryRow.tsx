/** One ColorSetEntry — a Set's own palette entry, or (on a Group card) a
 * field-level override layered onto whichever member gets picked. Scope
 * (which devices this entry touches) is virtual_ids ∪ categories ∪ roles,
 * union'd at resolve time (fx.device_model.resolve_scope) — this editor
 * lets you pick any combination, chip-style. */
import { LabelsInput } from '../components/inputs';
import ColorGradientPicker from '../components/ColorGradientPicker';
import type { Registry, SpotColorSetEntry } from '../types';

const chipRow: React.CSSProperties = { display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' };
const chip: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11,
  padding: '2px 6px', borderRadius: 10, background: 'var(--surface2)',
  border: '1px solid var(--border)',
};

function ChipPicker({ label, selected, options, onAdd, onRemove }: {
  label: string;
  selected: string[];
  options: string[];
  onAdd: (v: string) => void;
  onRemove: (v: string) => void;
}) {
  const remaining = options.filter((o) => !selected.includes(o));
  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
      <div style={chipRow}>
        {selected.map((s) => (
          <span key={s} style={chip}>
            {s}
            <button style={{ fontSize: 10, lineHeight: 1, padding: 0, border: 'none', background: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
              title={`Remove ${s}`} onClick={() => onRemove(s)}>✕</button>
          </span>
        ))}
        {remaining.length > 0 && (
          <select value="" style={{ fontSize: 11, padding: '1px 4px' }}
            onChange={(e) => { if (e.target.value) onAdd(e.target.value); }}>
            <option value="">+ {label.toLowerCase()}…</option>
            {remaining.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        )}
        {!options.length && !selected.length && (
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>none configured</span>
        )}
      </div>
    </div>
  );
}

export default function EntryRow({
  entry, registry, gradients, onChange, onRemove,
}: {
  entry: SpotColorSetEntry;
  registry: Registry | undefined;
  gradients: string[];
  onChange: (e: SpotColorSetEntry) => void;
  onRemove: () => void;
}) {
  const set = (patch: Partial<SpotColorSetEntry>) => onChange({ ...entry, ...patch });
  const setScope = (patch: Partial<SpotColorSetEntry['scope']>) =>
    set({ scope: { ...entry.scope, ...patch } });

  const categories = Object.keys(registry?.categories ?? {});
  const allVirtuals = [...new Set(categories.flatMap((c) => registry?.categories[c]?.virtuals ?? []))];

  return (
    <div style={{
      background: 'var(--surface2)', padding: 8, borderRadius: 'var(--radius)',
      marginBottom: 8, border: '1px solid var(--border)',
    }}>
      <ChipPicker label="Categories" selected={entry.scope.categories} options={categories}
        onAdd={(v) => setScope({ categories: [...entry.scope.categories, v] })}
        onRemove={(v) => setScope({ categories: entry.scope.categories.filter((x) => x !== v) })} />
      <ChipPicker label="Virtuals" selected={entry.scope.virtual_ids} options={allVirtuals}
        onAdd={(v) => setScope({ virtual_ids: [...entry.scope.virtual_ids, v] })}
        onRemove={(v) => setScope({ virtual_ids: entry.scope.virtual_ids.filter((x) => x !== v) })} />
      <div style={{ marginBottom: 6 }}>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>Roles</div>
        <LabelsInput value={entry.scope.roles} placeholder="role1, role2"
          onChange={(roles) => setScope({ roles })} />
      </div>
      {!entry.scope.categories.length && !entry.scope.virtual_ids.length && !entry.scope.roles.length && (
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 6 }}>
          Empty scope = every imported virtual.
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
          <input type="checkbox" checked={entry.color_value != null}
            onChange={(e) => set(e.target.checked
              ? { color_kind: 'solid', color_value: '#ffffff' }
              : { color_kind: null, color_value: null })} />
          FG
        </label>
        {entry.color_value != null && (
          <ColorGradientPicker gradient value={entry.color_value} defaultColors={gradients}
            swatchWidth={40} swatchHeight={26} title="Foreground colour or gradient"
            onChange={(v) => set({ color_value: v, color_kind: v.includes('linear-gradient') ? 'gradient' : 'solid' })} />
        )}

        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
          <input type="checkbox" checked={entry.bg_color != null}
            onChange={(e) => set({ bg_color: e.target.checked ? '#000000' : null })} />
          BG
        </label>
        {entry.bg_color != null && (
          <ColorGradientPicker value={entry.bg_color} swatchWidth={40} swatchHeight={26}
            title="Background colour" onChange={(v) => set({ bg_color: v })} />
        )}
        {entry.bg_color != null && (
          <select value={entry.bg_mode ?? ''} style={{ fontSize: 11 }}
            title="LedFX background_mode — unset leaves the device's own value"
            onChange={(e) => set({ bg_mode: (e.target.value || null) as SpotColorSetEntry['bg_mode'] })}>
            <option value="">bg mode: unset</option>
            <option value="additive">additive</option>
            <option value="overwrite">overwrite</option>
          </select>
        )}

        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }} title="0–1, blank = leave the device's own value">
          Bright
          <input type="number" min={0} max={1} step={0.01} value={entry.brightness ?? ''}
            placeholder="—" style={{ width: 56 }}
            onChange={(e) => set({ brightness: e.target.value === '' ? null : Number(e.target.value) })} />
        </label>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }} title="0–1, blank = leave the device's own value">
          BG Bright
          <input type="number" min={0} max={1} step={0.01} value={entry.background_brightness ?? ''}
            placeholder="—" style={{ width: 56 }}
            onChange={(e) => set({ background_brightness: e.target.value === '' ? null : Number(e.target.value) })} />
        </label>

        <button className="danger" style={{ fontSize: 11, marginLeft: 'auto' }} onClick={onRemove}>✕ Remove</button>
      </div>
    </div>
  );
}
