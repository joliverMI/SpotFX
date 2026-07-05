/** Keyboard palettes: full 36-key grid (1-0 / q-p / a-l / z-m). Click a
 * palette to activate it (sticky), double-click to edit. Press a key (or
 * click one) to arm its event — right-click the timeline places it. */
import { useEffect, useState } from 'react';
import SearchSelect from '../../components/forms/SearchSelect';
import { useToast } from '../../components/Toast';
import { useSticky } from '../../lib/useSticky';
import { useBuilderStore } from '../store';
import { usePaletteMutations, usePalettes } from '../queries';
import { PALETTE_ROWS } from '../hooks/usePaletteKeyboard';
import type { EventOption, Palette } from '../types';

export default function PaletteCard({ events }: { events: EventOption[] }) {
  const { data: palettes } = usePalettes();
  const { create, update, remove } = usePaletteMutations();
  const toast = useToast();

  const armedKey = useBuilderStore((s) => s.armedKey);
  const setArmedKey = useBuilderStore((s) => s.setArmedKey);
  const activePaletteId = useBuilderStore((s) => s.activePaletteId);
  const setActivePaletteId = useBuilderStore((s) => s.setActivePaletteId);

  const [stickyPaletteId, setStickyPaletteId] = useSticky<string | null>('activePaletteId', null);

  // Restore the sticky palette once the list arrives (validated against it).
  useEffect(() => {
    if (!palettes) return;
    const valid = stickyPaletteId && palettes.some((p) => p.id === stickyPaletteId)
      ? stickyPaletteId : null;
    setActivePaletteId(valid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [palettes]);

  const [editing, setEditing] = useState<Palette | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const active = palettes?.find((p) => p.id === activePaletteId) ?? null;
  const armedEvent = armedKey && active ? events.find((e) => e.id === active.keys[armedKey]) : null;

  const pick = (id: string) => {
    const next = activePaletteId === id ? null : id;
    setActivePaletteId(next);
    setStickyPaletteId(next);
    if (!next) setArmedKey(null);
  };

  const grid = (pal: Palette, editMode: boolean) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 8 }}>
      {PALETTE_ROWS.map((row, ri) => (
        <div key={ri} style={{ display: 'flex', gap: 4, marginLeft: ri * 14 }}>
          {row.map((k) => {
            const evId = pal.keys[k];
            const ev = evId ? events.find((e) => e.id === evId) : null;
            const isArmed = !editMode && armedKey === k && pal.id === activePaletteId;
            const isSelected = editMode && selectedKey === k;
            return (
              <div
                key={k}
                title={ev ? `${k.toUpperCase()} → ${ev.name}` : k.toUpperCase()}
                onClick={() => {
                  if (editMode) setSelectedKey(k);
                  else if (pal.id === activePaletteId) setArmedKey(armedKey === k ? null : k);
                }}
                style={{
                  width: 34, height: 34, borderRadius: 6, cursor: 'pointer', userSelect: 'none',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                  border: `1px solid ${isArmed || isSelected ? 'var(--accent)' : 'var(--border)'}`,
                  background: isArmed ? 'rgba(29,185,84,0.18)' : 'var(--surface2)',
                  opacity: ev ? 1 : 0.4, fontSize: 12,
                }}
              >
                <span>{k.toUpperCase()}</span>
                <span style={{ width: 8, height: 8, borderRadius: '50%',
                               background: ev?.color ?? 'transparent' }} />
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        {(palettes ?? []).map((p) => (
          <button
            key={p.id}
            className={p.id === activePaletteId ? 'primary' : ''}
            style={{ borderLeft: `4px solid ${p.color}` }}
            title="Click: activate · double-click: edit"
            onClick={() => pick(p.id)}
            onDoubleClick={() => { setEditing(JSON.parse(JSON.stringify(p))); setSelectedKey(null); }}
          >
            {p.name}
          </button>
        ))}
        <button
          style={{ fontSize: 12 }}
          onClick={() =>
            create.mutate(
              { name: 'New Palette', color: '#1db954', keys: {} },
              { onSuccess: (p) => { setEditing(JSON.parse(JSON.stringify(p))); setSelectedKey(null); } },
            )
          }
        >
          + New
        </button>
        <span style={{ flex: 1 }} />
        {armedEvent && (
          <span className="chip accent" title="Right-click the timeline to place; Escape to disarm">
            {armedKey!.toUpperCase()} armed → {armedEvent.name}
          </span>
        )}
      </div>

      {!editing && active && grid(active, false)}
      {!editing && !active && (
        <p className="empty-note" style={{ marginTop: 8 }}>
          Activate a palette, press a key to arm its event, then right-click the timeline to place triggers.
        </p>
      )}

      {editing && (
        <div style={{ marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input type="text" value={editing.name} style={{ width: 180 }}
              onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
            <input type="color" value={editing.color}
              onChange={(e) => setEditing({ ...editing, color: e.target.value })}
              style={{ width: 34, height: 28, padding: 0, border: '1px solid var(--border)',
                       borderRadius: 4, background: 'none', cursor: 'pointer' }} />
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              click a key, then pick its event
            </span>
          </div>
          {grid(editing, true)}
          {selectedKey && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
              <span className="chip">{selectedKey.toUpperCase()}</span>
              <SearchSelect
                value={editing.keys[selectedKey] ?? ''}
                onChange={(v) => setEditing({
                  ...editing,
                  keys: { ...editing.keys, [selectedKey]: v || null },
                })}
                options={[...events].sort((a, b) => a.name.localeCompare(b.name))
                  .map((e) => ({ value: e.id, label: e.name }))}
                placeholder="— unassigned —"
                width={280}
              />
            </div>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className="primary"
              onClick={() => update.mutate(editing, {
                onSuccess: () => { setEditing(null); toast('Palette saved', 'success'); },
              })}>
              Save
            </button>
            <button onClick={() => setEditing(null)}>Cancel</button>
            <button onClick={() =>
              create.mutate(
                { name: `${editing.name} copy`, color: editing.color, keys: { ...editing.keys } },
                { onSuccess: () => toast('Palette duplicated', 'success') },
              )}>
              ⧉ Duplicate
            </button>
            <span style={{ flex: 1 }} />
            <button className="danger"
              onClick={() => {
                if (!confirm(`Delete palette “${editing.name}”?`)) return;
                remove.mutate(editing.id, {
                  onSuccess: () => {
                    if (activePaletteId === editing.id) pick(editing.id);
                    setEditing(null);
                  },
                });
              }}>
              Delete
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
