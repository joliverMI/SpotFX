/** Color Sets — sets + groups editor (port of frontend/color-sets.html).
 * Two-pane layout matching Devices; entries reuse the events page's
 * ScopeSelect; gradients share the /gradients library. Edits live in local
 * drafts until Save (legacy in-memory semantics). */
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { apiPost } from '../api/client';
import { useParamConfig } from '../api/queries';
import { useToast } from '../components/Toast';
import { LabelsInput } from '../components/forms/inputs';
import SearchSelect from '../components/forms/SearchSelect';
import HelpLink from '../help/HelpLink';
import { uuid } from '../lib/uid';
import { cloneForPaste, readClip, useClipboard, writeClip } from '../store/clipboard';
import EntryRow from './EntryRow';
import GradientModal from './GradientModal';
import { useColorSetCards, useDeleteColorSet, useGradients, useSaveColorSet } from './queries';
import { emptyEntry, newCard, type ColorSetCard, type ColorSetEntry } from './types';

export default function ColorSetsPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const { data: serverCards = [], isLoading } = useColorSetCards();
  const { data: gradients = [] } = useGradients();
  const { data: paramConfig } = useParamConfig();
  const saveMut = useSaveColorSet();
  const delMut = useDeleteColorSet();

  // ?id=<card id> deep-links to a set/group (used by the event editor's ↗).
  const [searchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get('id'));
  const [search, setSearch] = useState('');
  const [drafts, setDrafts] = useState<Record<string, ColorSetCard>>({});
  const [gradEntryIdx, setGradEntryIdx] = useState<number | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  // Shift-click multi-select of entry boxes (indices into the open card's
  // entries); Ctrl+C copies them to the shared clipboard, Ctrl+V pastes.
  const [selEntries, setSelEntries] = useState<Set<number>>(new Set());
  const clip = useClipboard();

  // Server cards overlaid with unsaved drafts (+ draft-only new cards).
  const cards = useMemo(() => {
    const merged = serverCards.map((c) => drafts[c.id] ?? c);
    const serverIds = new Set(serverCards.map((c) => c.id));
    for (const d of Object.values(drafts)) if (!serverIds.has(d.id)) merged.push(d);
    return merged;
  }, [serverCards, drafts]);

  const card = cards.find((c) => c.id === selectedId) ?? null;
  const setCard = (next: ColorSetCard) => setDrafts((d) => ({ ...d, [next.id]: next }));

  useEffect(() => setSelEntries(new Set()), [selectedId]);

  const toggleEntrySel = (i: number) => setSelEntries((s) => {
    const next = new Set(s);
    if (next.has(i)) next.delete(i); else next.add(i);
    return next;
  });

  const removeEntry = (i: number) => {
    if (!card) return;
    setCard({ ...card, entries: card.entries.filter((_, j) => j !== i) });
    setSelEntries((s) => new Set([...s].filter((x) => x !== i).map((x) => (x > i ? x - 1 : x))));
  };

  const copySelected = (): boolean => {
    if (!card || !selEntries.size) return false;
    const entries = [...selEntries].sort((a, b) => a - b)
      .map((i) => card.entries?.[i]).filter(Boolean);
    if (!entries.length) return false;
    writeClip('colorset_entries', entries,
      `${entries.length} color ${entries.length === 1 ? 'entry' : 'entries'} from “${card.name}”`);
    toast(`Copied ${entries.length} ${entries.length === 1 ? 'entry' : 'entries'}`, 'success');
    return true;
  };

  const pasteEntries = (): boolean => {
    const c = readClip();
    if (!card || c?.kind !== 'colorset_entries') return false;
    const pasted = (c.data as ColorSetEntry[]).map((e) => cloneForPaste(e));
    setCard({ ...card, entries: [...(card.entries ?? []), ...pasted] });
    toast(`Pasted ${pasted.length} ${pasted.length === 1 ? 'entry' : 'entries'}`, 'success');
    return true;
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c') {
        if (window.getSelection()?.toString()) return; // let native text copy win
        if (copySelected()) e.preventDefault();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') {
        if (pasteEntries()) e.preventDefault();
      } else if (e.key === 'Escape' && selEntries.size) {
        setSelEntries(new Set());
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const canPaste = clip?.kind === 'colorset_entries';
  const pasteCount = canPaste ? (clip?.data as ColorSetEntry[]).length : 0;

  const visible = useMemo(() => {
    const q = search.toLowerCase();
    return cards.filter((c) =>
      c.name.toLowerCase().includes(q) || (c.labels ?? []).some((l) => l.toLowerCase().includes(q)));
  }, [cards, search]);

  const save = async (c: ColorSetCard | null = card) => {
    if (!c) return;
    try {
      await saveMut.mutateAsync(c);
      setDrafts((d) => {
        const { [c.id]: _, ...rest } = d;
        return rest;
      });
      toast('Saved', 'success');
    } catch (e) {
      toast(`Save failed: ${e}`, 'error');
    }
  };

  const del = async () => {
    if (!card) return;
    if (!confirm(`Delete "${card.name}"?`)) return;
    try {
      if (serverCards.some((c) => c.id === card.id)) await delMut.mutateAsync(card.id);
      setDrafts((d) => {
        const { [card.id]: _, ...rest } = d;
        return rest;
      });
      setSelectedId(null);
    } catch (e) {
      toast(`Delete failed: ${e}`, 'error');
    }
  };

  const duplicate = () => {
    if (!card) return;
    const copy: ColorSetCard = JSON.parse(JSON.stringify(card));
    copy.id = uuid();
    copy.name = `${card.name} (copy)`;
    setDrafts((d) => ({ ...d, [copy.id]: copy }));
    setSelectedId(copy.id);
  };

  const preview = async () => {
    if (!card) return;
    await save();
    try {
      await apiPost(`/color-sets/${card.id}/fire`, {});
      toast('Fired', 'success');
    } catch (e) {
      toast(`Preview failed: ${e}`, 'error');
    }
  };

  const create = (kind: 'set' | 'group') => {
    const c = newCard(kind, uuid());
    setDrafts((d) => ({ ...d, [c.id]: c }));
    setSelectedId(c.id);
  };

  const allVirtuals = useMemo(() => {
    const cats = Object.keys(paramConfig?.categories ?? {});
    return cats.flatMap((cat) => (paramConfig?.categories[cat]?.virtuals ?? []).map((v) => ({ v, cat })));
  }, [paramConfig]);

  const sets = cards.filter((c) => c.kind === 'set');
  const setOptions = useMemo(
    () => cards.filter((c) => c.kind === 'set').map((s) => ({ value: s.id, label: s.name })),
    [cards],
  );

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16, alignItems: 'start' }}>
      {/* ── Card list ── */}
      <div className="card" style={{ minWidth: 0, maxHeight: 'calc(100vh - 80px)', display: 'flex', flexDirection: 'column' }}>
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          Color Sets
          <button style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 10px' }}
            title="Import current colors from LedFX devices"
            onClick={() => setImportOpen(true)}>
            ⤓ Import
          </button>
        </div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
          <button className="primary" style={{ fontSize: 11, padding: '3px 10px' }} onClick={() => create('set')}>+ Set</button>
          <button className="primary" style={{ fontSize: 11, padding: '3px 10px' }} onClick={() => create('group')}>+ Group</button>
        </div>
        <div className="field">
          <input type="text" placeholder="Search…" value={search} style={{ width: '100%' }}
            onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
          {isLoading && <div className="empty-note" style={{ padding: 10 }}>Loading…</div>}
          {!isLoading && !visible.length && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: 10 }}>No color sets yet.</div>
          )}
          {visible.map((c) => (
            <div key={c.id} className={`pane-row${c.id === selectedId ? ' selected' : ''}`}
              onClick={() => setSelectedId(c.id)}>
              <div style={{
                width: 18, height: 18, borderRadius: 4, border: '1px solid var(--border)',
                background: c.color || '#888', flexShrink: 0,
              }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>
                  {c.name}
                  {drafts[c.id] && <span title="Unsaved changes" style={{ color: 'var(--accent2)' }}> •</span>}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{(c.labels ?? []).join(', ')}</div>
              </div>
              <span style={{
                fontSize: 10, padding: '2px 6px', borderRadius: 10,
                background: c.kind === 'group' ? 'rgba(156,39,176,0.15)' : 'rgba(33,150,243,0.15)',
                color: c.kind === 'group' ? '#ba68c8' : '#64b5f6',
              }}>
                {c.kind}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Editor ── */}
      {card ? (
        <div className="card" style={{ maxHeight: 'calc(100vh - 80px)', overflowY: 'auto' }}>
          <div className="card-title">{card.kind === 'group' ? 'Edit Group' : 'Edit Color Set'}</div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
            <button className="primary" onClick={() => void save()}>Save</button>
            <button style={{ fontSize: 12 }} onClick={duplicate}>Duplicate</button>
            <button style={{ fontSize: 12 }} title="Apply now to LedFX"
              onClick={() => void preview()}>
              ▶ Preview
            </button>
            <button className="danger" style={{ fontSize: 12 }} onClick={() => void del()}>Delete</button>
          </div>

          <div className="field">
            <label>Name</label>
            <input type="text" placeholder="Color Set name" value={card.name} style={{ width: '100%' }}
              onChange={(e) => setCard({ ...card, name: e.target.value })} />
          </div>
          <div className="field" style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
            <div>
              <label>Marker Color</label>
              <input type="color" value={card.color || '#FFD700'} style={{ width: 48, height: 34, padding: 2 }}
                onChange={(e) => setCard({ ...card, color: e.target.value })} />
            </div>
            <div style={{ flex: 1 }}>
              <label>Labels (comma separated)</label>
              <LabelsInput value={card.labels ?? []} placeholder="e.g. warm, drop"
                onChange={(labels) => setCard({ ...card, labels })} />
            </div>
          </div>

          {card.kind === 'set' ? (
            <>
              <div className="card-title" style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 4 }}>
                Entries
                <HelpLink topic="colorsets-copy-entries" />
                <span style={{ fontWeight: 400, marginLeft: 2, fontSize: 11, textTransform: 'none', letterSpacing: 0 }}>
                  FG / BG color per device or category
                </span>
                {selEntries.size > 0 && (
                  <span style={{ fontWeight: 400, marginLeft: 8, fontSize: 11, textTransform: 'none', letterSpacing: 0, color: 'var(--accent)' }}>
                    {selEntries.size} selected — Ctrl+C to copy
                  </span>
                )}
                {canPaste && (
                  <button style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 10px' }}
                    title={`Paste ${clip?.summary ?? ''} (Ctrl+V)`} onClick={() => pasteEntries()}>
                    📋 Paste {pasteCount}
                  </button>
                )}
                <button style={{ marginLeft: canPaste ? 6 : 'auto', fontSize: 11, padding: '3px 10px' }}
                  onClick={() => setCard({ ...card, entries: [...(card.entries ?? []), emptyEntry()] })}>
                  + Entry
                </button>
              </div>
              {!(card.entries ?? []).length && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: 6 }}>
                  No entries. Add one with + Entry.
                </div>
              )}
              {(card.entries ?? []).map((entry, i) => (
                <EntryRow
                  key={i}
                  entry={entry}
                  gradients={gradients}
                  selected={selEntries.has(i)}
                  onToggleSelect={() => toggleEntrySel(i)}
                  onChange={(e) => setCard({ ...card, entries: card.entries.map((x, j) => (j === i ? e : x)) })}
                  onRemove={() => removeEntry(i)}
                  onEditGradient={() => setGradEntryIdx(i)}
                />
              ))}
            </>
          ) : (
            <>
              <div className="card-title" style={{ marginTop: 8 }}>Group Settings</div>
              <div className="field" style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                <label style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 0 }}>
                  Default mode
                  <select value={card.mode ?? 'cycle'}
                    onChange={(e) => setCard({ ...card, mode: e.target.value as 'cycle' | 'weighted' })}>
                    <option value="cycle">Cycle (sequential)</option>
                    <option value="weighted">Weighted random</option>
                  </select>
                </label>
                <label style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 0 }}>
                  Cycle behaviour
                  <select value={card.cycle_behavior ?? 'wrap'}
                    onChange={(e) => setCard({ ...card, cycle_behavior: e.target.value as 'wrap' | 'bounce' })}>
                    <option value="wrap">Wrap (back to top)</option>
                    <option value="bounce">Bounce (reverse at ends)</option>
                  </select>
                </label>
                <label style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 0, cursor: 'pointer' }}>
                  <input type="checkbox" checked={card.exclude_current !== false}
                    onChange={(e) => setCard({ ...card, exclude_current: e.target.checked })} />
                  Exclude current from next
                </label>
                <label style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 0, cursor: 'pointer' }}
                  title="Start picks from the member matching the room's current palette, instead of this group's own cycle position">
                  <input type="checkbox" checked={card.palette_sync === true}
                    onChange={(e) => setCard({ ...card, palette_sync: e.target.checked })} />
                  Palette Sync
                  <HelpLink topic="colorsets-palette-sync" />
                </label>
              </div>
              <div className="card-title" style={{ marginTop: 8, display: 'flex', alignItems: 'center' }}>
                Members
                <span style={{ fontWeight: 400, marginLeft: 6, fontSize: 11, textTransform: 'none', letterSpacing: 0 }}>
                  ordered for cycle; weighted for random
                </span>
                <button style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 10px' }}
                  onClick={() => {
                    if (!sets.length) { toast('Create a Color Set first', 'error'); return; }
                    setCard({ ...card, members: [...(card.members ?? []), { color_set_id: sets[0].id, weight: 1 }] });
                  }}>
                  + Member
                </button>
              </div>
              {!(card.members ?? []).length && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: 6 }}>
                  No members. Add one with + Member.
                </div>
              )}
              {(card.members ?? []).map((m, i) => (
                <div key={`m${i}`} style={{
                  background: 'var(--surface2)', padding: 8, borderRadius: 'var(--radius)', marginBottom: 8,
                  display: 'flex', alignItems: 'center', gap: 8,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <SearchSelect
                      value={m.color_set_id}
                      options={setOptions}
                      allowEmpty={false}
                      width="100%"
                      placeholder="Search sets…"
                      onChange={(v) => setCard({
                        ...card,
                        members: card.members.map((x, j) => (j === i ? { ...x, color_set_id: v } : x)),
                      })}
                    />
                  </div>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Wt</span>
                  <input type="number" min={0} step={0.1} value={m.weight ?? 1} style={{ width: 64 }}
                    onChange={(e) => setCard({
                      ...card,
                      members: card.members.map((x, j) => (j === i ? { ...x, weight: parseFloat(e.target.value) || 1 } : x)),
                    })} />
                  <button style={{ fontSize: 12 }} title="Move up" disabled={i === 0}
                    onClick={() => {
                      const ms = [...card.members];
                      [ms[i - 1], ms[i]] = [ms[i], ms[i - 1]];
                      setCard({ ...card, members: ms });
                    }}>↑</button>
                  <button style={{ fontSize: 12 }} title="Move down" disabled={i === card.members.length - 1}
                    onClick={() => {
                      const ms = [...card.members];
                      [ms[i], ms[i + 1]] = [ms[i + 1], ms[i]];
                      setCard({ ...card, members: ms });
                    }}>↓</button>
                  <button className="danger" style={{ fontSize: 12 }} title="Remove"
                    onClick={() => setCard({ ...card, members: card.members.filter((_, j) => j !== i) })}>✕</button>
                </div>
              ))}
              <div className="card-title" style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 4 }}>
                Overrides
                <HelpLink topic="colorsets-group-overrides" />
                <span style={{ fontWeight: 400, marginLeft: 2, fontSize: 11, textTransform: 'none', letterSpacing: 0 }}>
                  replace the picked Set's values per device/category
                </span>
                {selEntries.size > 0 && (
                  <span style={{ fontWeight: 400, marginLeft: 8, fontSize: 11, textTransform: 'none', letterSpacing: 0, color: 'var(--accent)' }}>
                    {selEntries.size} selected — Ctrl+C to copy
                  </span>
                )}
                {canPaste && (
                  <button style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 10px' }}
                    title={`Paste ${clip?.summary ?? ''} (Ctrl+V)`} onClick={() => pasteEntries()}>
                    📋 Paste {pasteCount}
                  </button>
                )}
                <button style={{ marginLeft: canPaste ? 6 : 'auto', fontSize: 11, padding: '3px 10px' }}
                  onClick={() => setCard({ ...card, entries: [...(card.entries ?? []), emptyEntry()] })}>
                  + Override
                </button>
              </div>
              {!(card.entries ?? []).length && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: 6 }}>
                  No overrides. Fields set here win over the picked Set for the scoped devices; unset fields keep the Set's values.
                </div>
              )}
              {(card.entries ?? []).map((entry, i) => (
                <EntryRow
                  key={i}
                  entry={entry}
                  gradients={gradients}
                  selected={selEntries.has(i)}
                  onToggleSelect={() => toggleEntrySel(i)}
                  onChange={(e) => setCard({ ...card, entries: card.entries.map((x, j) => (j === i ? e : x)) })}
                  onRemove={() => removeEntry(i)}
                  onEditGradient={() => setGradEntryIdx(i)}
                />
              ))}
            </>
          )}
        </div>
      ) : (
        <p className="empty-note" style={{ marginTop: 24 }}>Select a Color Set, or create one with + Set / + Group.</p>
      )}

      {/* ── Gradient editor modal ── */}
      {card && gradEntryIdx !== null && card.entries?.[gradEntryIdx] && (
        <GradientModal
          initialCss={card.entries[gradEntryIdx].color_value ?? ''}
          gradients={gradients}
          onApply={(css) => setCard({
            ...card,
            entries: card.entries.map((e, j) =>
              j === gradEntryIdx ? { ...e, color_kind: 'gradient', color_value: css } : e),
          })}
          onClose={() => setGradEntryIdx(null)}
        />
      )}

      {/* ── Import modal ── */}
      {importOpen && (
        <ImportModal
          virtuals={allVirtuals}
          onClose={() => setImportOpen(false)}
          onImported={(c) => {
            void qc.invalidateQueries({ queryKey: ['color-sets'] });
            setSelectedId(c.id);
            setImportOpen(false);
            toast('Imported', 'success');
          }}
        />
      )}
    </div>
  );
}

function ImportModal({
  virtuals,
  onClose,
  onImported,
}: {
  virtuals: { v: string; cat: string }[];
  onClose: () => void;
  onImported: (card: ColorSetCard) => void;
}) {
  const toast = useToast();
  const [checked, setChecked] = useState<Set<string>>(new Set(virtuals.map((x) => x.v)));

  const doImport = async () => {
    const ids = [...checked];
    if (!ids.length) { toast('Select at least one device', 'error'); return; }
    try {
      const res = await apiPost<{ card: ColorSetCard }>('/color-sets/import', { virtual_ids: ids });
      onImported(res.card);
    } catch (e) {
      toast(`Import failed: ${e}`, 'error');
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
        padding: 16, maxWidth: 420, width: '90vw', maxHeight: '80vh', overflowY: 'auto',
      }}>
        <div className="card-title">Import colors from LedFX</div>
        <p style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Select which devices to read. Their current FG/BG colors and background mode become a new Color Set.
        </p>
        {!virtuals.length && <p className="empty-note" style={{ margin: '10px 0' }}>No devices configured.</p>}
        <div style={{ margin: '10px 0' }}>
          {virtuals.map(({ v, cat }) => (
            <label key={v} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 0', cursor: 'pointer', fontSize: 13 }}>
              <input type="checkbox" checked={checked.has(v)}
                onChange={(e) => {
                  const next = new Set(checked);
                  if (e.target.checked) next.add(v); else next.delete(v);
                  setChecked(next);
                }} />
              {v} <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>({cat})</span>
            </label>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button style={{ fontSize: 12 }} onClick={onClose}>Cancel</button>
          <button className="primary" style={{ fontSize: 12 }} onClick={() => void doImport()}>Import</button>
        </div>
      </div>
    </div>
  );
}
