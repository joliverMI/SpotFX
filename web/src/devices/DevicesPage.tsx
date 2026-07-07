/** Devices — device-category manager (port of frontend/devices.html).
 * Two-pane list/editor reusing the events-page card + chip styling. */
import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiDel, apiGet, apiPost } from '../api/client';
import { useToast } from '../components/Toast';
import { uuid } from '../lib/uid';

interface DeviceCategory {
  id: string;
  name: string;
  parent_id: string | null;
  role?: string | null;
  virtuals: string[];
  effects: string[];
  sort_order: number;
  [k: string]: unknown;
}

interface LedfxVirtual {
  id: string;
  pixel_count: number;
  effect_type: string;
  active: boolean;
}

function useCategories() {
  return useQuery({
    queryKey: ['device-categories'],
    queryFn: () => apiGet<DeviceCategory[]>('/device-categories'),
  });
}

export default function DevicesPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const { data: categories = [], isLoading } = useCategories();
  const { data: paramConfig } = useQuery({
    queryKey: ['effect-params-config-raw'],
    queryFn: () => apiGet<{ effects?: Record<string, unknown> }>('/effect-params/config'),
    staleTime: 60_000,
  });
  const allEffectTypes = Object.keys(paramConfig?.effects ?? {});

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [draft, setDraft] = useState<DeviceCategory | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  // Load the selected category into the editable draft (fresh server copy).
  const selected = categories.find((c) => c.id === selectedId) ?? null;
  useEffect(() => {
    setDraft(selected ? JSON.parse(JSON.stringify(selected)) as DeviceCategory : null);
    setImportOpen(false);
  }, [selectedId, selected]);

  const save = useMutation({
    mutationFn: (cat: DeviceCategory) => apiPost('/device-categories', cat),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['device-categories'] });
      toast('Saved', 'success');
    },
    onError: (e) => toast(`Save failed: ${e}`, 'error'),
  });

  const remove = async () => {
    if (!selectedId) return;
    if (!confirm('Delete this category? Child categories will become top-level.')) return;
    try {
      await apiDel(`/device-categories/${selectedId}`);
      setSelectedId(null);
      void qc.invalidateQueries({ queryKey: ['device-categories'] });
    } catch (e) {
      toast(`Delete failed: ${e}`, 'error');
    }
  };

  const createNew = async () => {
    const maxOrder = categories.reduce((m, c) => Math.max(m, c.sort_order), -1);
    const cat: DeviceCategory = {
      id: uuid(), name: 'New Category', parent_id: null,
      virtuals: [], effects: [], sort_order: maxOrder + 1,
    };
    await apiPost('/device-categories', cat);
    await qc.invalidateQueries({ queryKey: ['device-categories'] });
    setSelectedId(cat.id);
  };

  const duplicate = async () => {
    if (!draft) return;
    await apiPost('/device-categories', draft);
    const copy = { ...draft, id: uuid(), name: `${draft.name} (copy)` };
    await apiPost('/device-categories', copy);
    await qc.invalidateQueries({ queryKey: ['device-categories'] });
    setSelectedId(copy.id);
  };

  // ── Tree ordering for the list ─────────────────────────────────────────────
  const rows = useMemo(() => {
    const q = search.toLowerCase();
    const byParent = new Map<string, DeviceCategory[]>();
    for (const c of categories) {
      if (c.parent_id) {
        const arr = byParent.get(c.parent_id) ?? [];
        arr.push(c);
        byParent.set(c.parent_id, arr);
      }
    }
    const out: { cat: DeviceCategory; child: boolean }[] = [];
    const walk = (cat: DeviceCategory, child: boolean) => {
      if (!q || cat.name.toLowerCase().includes(q)) out.push({ cat, child });
      (byParent.get(cat.id) ?? []).sort((a, b) => a.sort_order - b.sort_order).forEach((c) => walk(c, true));
    };
    categories
      .filter((c) => !c.parent_id)
      .sort((a, b) => a.sort_order - b.sort_order)
      .forEach((c) => walk(c, false));
    return out;
  }, [categories, search]);

  const descendantIds = useMemo(() => {
    if (!draft) return new Set<string>();
    const result = new Set<string>();
    const walk = (pid: string) => {
      categories.filter((c) => c.parent_id === pid).forEach((c) => {
        result.add(c.id);
        walk(c.id);
      });
    };
    walk(draft.id);
    return result;
  }, [draft, categories]);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16, alignItems: 'start' }}>
      {/* ── Category list ── */}
      <div className="card" style={{ minWidth: 0, maxHeight: 'calc(100vh - 80px)', display: 'flex', flexDirection: 'column' }}>
        <div className="card-title" style={{ display: 'flex', alignItems: 'center' }}>
          Device Categories
          <button className="primary" style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 10px' }}
            onClick={() => void createNew()}>
            + New
          </button>
        </div>
        <div className="field">
          <input type="text" placeholder="Search categories…" value={search}
            onChange={(e) => setSearch(e.target.value)} style={{ width: '100%' }} />
        </div>
        <div style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
          {isLoading && <div className="empty-note" style={{ padding: 12 }}>Loading…</div>}
          {!isLoading && !rows.length && (
            <div style={{ color: 'var(--text-muted)', padding: 12, fontSize: 13 }}>No categories yet</div>
          )}
          {rows.map(({ cat, child }) => (
            <div key={cat.id}
              className={`pane-row${cat.id === selectedId ? ' selected' : ''}`}
              style={child ? { paddingLeft: cat.id === selectedId ? 21 : 24 } : undefined}
              onClick={() => setSelectedId(cat.id)}>
              <span>{cat.name}</span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>
                {cat.virtuals.length} virtual{cat.virtuals.length !== 1 ? 's' : ''}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Editor ── */}
      {draft && (
        <div className="card" style={{ maxHeight: 'calc(100vh - 80px)', overflowY: 'auto' }}>
          <div className="card-title">Edit Category</div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
            <button className="primary" onClick={() => save.mutate(draft)}>Save</button>
            <button className="danger" style={{ fontSize: 12 }} onClick={() => void remove()}>Delete</button>
            <button style={{ fontSize: 12 }} onClick={() => void duplicate()}>Duplicate</button>
          </div>

          <div className="field">
            <label>Name</label>
            <input type="text" value={draft.name} style={{ width: '100%' }}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </div>

          <div className="field" style={{ display: 'flex', gap: 12 }}>
            <div style={{ flex: 1 }}>
              <label>Parent Category</label>
              <select value={draft.parent_id ?? ''} style={{ width: '100%' }}
                onChange={(e) => setDraft({ ...draft, parent_id: e.target.value || null })}>
                <option value="">(None — top level)</option>
                {categories
                  .filter((c) => c.id !== draft.id && !descendantIds.has(c.id))
                  .map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div style={{ width: 140 }}>
              <label>Role</label>
              <select value={draft.role ?? ''} style={{ width: '100%' }}
                onChange={(e) => setDraft({ ...draft, role: e.target.value || null })}>
                <option value="">(none)</option>
                <option value="ambient">Ambient</option>
              </select>
            </div>
          </div>

          {/* Virtuals */}
          <div className="field">
            <label>Virtuals (LedFX virtual IDs)</label>
            <ChipList items={draft.virtuals}
              onRemove={(v) => setDraft({ ...draft, virtuals: draft.virtuals.filter((x) => x !== v) })} />
            <AddVirtualRow
              onAdd={(v) => {
                if (v && !draft.virtuals.includes(v)) setDraft({ ...draft, virtuals: [...draft.virtuals, v] });
              }}
              onImport={() => setImportOpen(true)}
            />
            {importOpen && (
              <ImportPanel
                categories={categories}
                current={draft}
                onClose={() => setImportOpen(false)}
                onAdd={(ids) => {
                  const merged = [...draft.virtuals];
                  for (const id of ids) if (!merged.includes(id)) merged.push(id);
                  setDraft({ ...draft, virtuals: merged });
                  setImportOpen(false);
                }}
              />
            )}
          </div>

          {/* Effects */}
          <div className="field">
            <label>Supported Effects</label>
            <ChipList items={draft.effects}
              onRemove={(e) => setDraft({ ...draft, effects: draft.effects.filter((x) => x !== e) })} />
            <AddEffectRow
              options={allEffectTypes.filter((e) => !draft.effects.includes(e))}
              onAdd={(e) => setDraft({ ...draft, effects: [...draft.effects, e] })}
            />
          </div>
        </div>
      )}
      {!draft && (
        <p className="empty-note" style={{ marginTop: 24 }}>Select a category to edit, or create a new one.</p>
      )}
    </div>
  );
}

function ChipList({ items, onRemove }: { items: string[]; onRemove: (v: string) => void }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
      {items.map((v) => (
        <span key={v} className="chip" style={{ gap: 4 }}>
          {v}
          <span style={{ cursor: 'pointer', fontWeight: 'bold', marginLeft: 4 }}
            onClick={() => onRemove(v)} title="Remove">×</span>
        </span>
      ))}
    </div>
  );
}

function AddVirtualRow({ onAdd, onImport }: { onAdd: (v: string) => void; onImport: () => void }) {
  const [val, setVal] = useState('');
  const add = () => { onAdd(val.trim()); setVal(''); };
  return (
    <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
      <input type="text" placeholder="Virtual ID…" value={val} style={{ flex: 1, minWidth: 0 }}
        onChange={(e) => setVal(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } }} />
      <button style={{ fontSize: 12 }} onClick={add}>+ Add</button>
      <button className="primary" style={{ fontSize: 12 }} onClick={onImport}>Import from LedFX</button>
    </div>
  );
}

function AddEffectRow({ options, onAdd }: { options: string[]; onAdd: (v: string) => void }) {
  const [val, setVal] = useState('');
  return (
    <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
      <select value={val} onChange={(e) => setVal(e.target.value)} style={{ flex: 1, minWidth: 0 }}>
        <option value="">Select effect…</option>
        {options.map((e) => <option key={e} value={e}>{e}</option>)}
      </select>
      <button style={{ fontSize: 12 }} onClick={() => { if (val) { onAdd(val); setVal(''); } }}>+ Add</button>
    </div>
  );
}

function ImportPanel({
  categories,
  current,
  onClose,
  onAdd,
}: {
  categories: DeviceCategory[];
  current: DeviceCategory;
  onClose: () => void;
  onAdd: (ids: string[]) => void;
}) {
  const [filter, setFilter] = useState('');
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const { data, isLoading, error } = useQuery({
    queryKey: ['ledfx-virtuals'],
    queryFn: () => apiGet<{ virtuals: LedfxVirtual[] }>('/device-categories/import/ledfx-virtuals'),
    staleTime: 30_000,
  });

  const assignedTo = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const c of categories) for (const vid of c.virtuals) {
      m.set(vid, [...(m.get(vid) ?? []), c.name]);
    }
    return m;
  }, [categories]);

  const all = useMemo(() => {
    const ledfx = data?.virtuals ?? [];
    const ledfxIds = new Set(ledfx.map((v) => v.id));
    const extra = [...new Set(categories.flatMap((c) => c.virtuals))]
      .filter((vid) => !ledfxIds.has(vid))
      .map((id) => ({ id, pixel_count: 0, effect_type: '', active: false, inLedfx: false }));
    return [...ledfx.map((v) => ({ ...v, inLedfx: true })), ...extra];
  }, [data, categories]);

  const visible = filter ? all.filter((v) => v.id.toLowerCase().includes(filter.toLowerCase())) : all;

  return (
    <div style={{
      background: 'var(--surface2)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: 12, marginTop: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
        <strong style={{ fontSize: 13 }}>Select virtuals to import</strong>
        <button style={{ marginLeft: 'auto', fontSize: 12 }} onClick={onClose}>Close</button>
      </div>
      <input type="text" placeholder="Filter virtuals…" value={filter}
        onChange={(e) => setFilter(e.target.value)} style={{ marginBottom: 8, width: '100%' }} />
      <div style={{ maxHeight: 300, overflowY: 'auto' }}>
        {isLoading && <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading…</div>}
        {!!error && <div style={{ color: 'var(--danger)', fontSize: 12 }}>Failed to fetch: {String(error)}</div>}
        {!isLoading && !visible.length && <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No matches</div>}
        {visible.map((v) => {
          const inCurrent = current.virtuals.includes(v.id);
          const cats = assignedTo.get(v.id);
          const details = v.inLedfx
            ? `${v.pixel_count ? `${v.pixel_count}px` : ''}${v.effect_type ? ` · ${v.effect_type}` : ''}${v.active ? ' · active' : ''}`
            : '(not in LedFX)';
          return (
            <label key={v.id} style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '6px 0',
              borderBottom: '1px solid var(--border)', fontSize: 13, cursor: 'pointer',
            }}>
              <input type="checkbox" checked={inCurrent || checked.has(v.id)} disabled={inCurrent}
                onChange={(e) => {
                  const next = new Set(checked);
                  if (e.target.checked) next.add(v.id); else next.delete(v.id);
                  setChecked(next);
                }} />
              <span>{v.id}</span>
              <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{details}</span>
              {cats && <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>[{cats.join(', ')}]</span>}
            </label>
          );
        })}
      </div>
      <button className="primary" style={{ marginTop: 8, fontSize: 12 }}
        onClick={() => onAdd([...checked])}>
        Add Selected
      </button>
    </div>
  );
}
