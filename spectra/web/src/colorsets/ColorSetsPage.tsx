/** Colour Sets & Groups — SPECTRA-native authoring (day-one bar item §10,
 * docs/SPECTRA_SPEC.md). A Set is a reusable named palette; a Group is a
 * rotating/synced pool of Sets, picked one at a time (cycle/weighted) when
 * applied — see HelpLink topics below for the mechanics. Writes go through
 * spot-effects' own /api/color-sets (already general — accepts either
 * kind), the same surface the Colour Sets tab's opt-out toggle already
 * uses; SPECTRA's own backend only ever reads this storage.
 *
 * Deliberately NOT ported from the legacy editor: Dark/Light "mode lane"
 * variants (owner-retired, §36) and the LedFX-import modal (a set-only
 * convenience, not part of this gap). Drafts live locally until Save,
 * matching the Scenes page's own convention. */
import { useMemo, useState } from 'react';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';
import { uuid } from '../lib/uid';
import {
  useApplyColorSet, useDeleteColorSet, useGradients, useRegistry, useSaveColorSet,
  useSpotColorSets, useWheelPositions,
} from '../queries';
import type { SpotColorSetCard, SpotColorSetEntry, SpotGroupMember } from '../types';
import EntryRow from './EntryRow';

const emptyScope = () => ({ virtual_ids: [], categories: [], roles: [] });
const emptyEntry = (): SpotColorSetEntry => ({
  scope: emptyScope(), color_kind: null, color_value: null,
  bg_color: null, bg_mode: null, brightness: null, background_brightness: null,
});

function newCard(kind: 'set' | 'group'): SpotColorSetCard {
  return {
    id: uuid(), name: kind === 'group' ? 'New Group' : 'New Colour Set',
    color: '#FFD700', kind, labels: [], entries: [],
    ...(kind === 'group'
      ? { members: [], mode: 'cycle', cycle_behavior: 'wrap', exclude_current: true, palette_sync: false }
      : {}),
  };
}

export default function ColorSetsPage() {
  const toast = useToast();
  const { data: serverCards = [], isLoading } = useSpotColorSets();
  const { data: gradients = [] } = useGradients();
  const { data: registry } = useRegistry();
  const { data: wheel = {} } = useWheelPositions();
  const saveMut = useSaveColorSet();
  const delMut = useDeleteColorSet();
  const applyMut = useApplyColorSet();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [drafts, setDrafts] = useState<Record<string, SpotColorSetCard>>({});

  const cards = useMemo(() => {
    const merged = serverCards.map((c) => drafts[c.id] ?? c);
    const serverIds = new Set(serverCards.map((c) => c.id));
    for (const d of Object.values(drafts)) if (!serverIds.has(d.id)) merged.push(d);
    return merged;
  }, [serverCards, drafts]);

  const card = cards.find((c) => c.id === selectedId) ?? null;
  const setCard = (next: SpotColorSetCard) => setDrafts((d) => ({ ...d, [next.id]: next }));

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return cards;
    return cards.filter((c) =>
      c.name.toLowerCase().includes(q) || (c.labels ?? []).some((l) => l.toLowerCase().includes(q)));
  }, [cards, search]);

  const sets = useMemo(() => cards.filter((c) => c.kind === 'set'), [cards]);

  const save = async (c: SpotColorSetCard | null = card) => {
    if (!c) return;
    try {
      await saveMut.mutateAsync(c);
      setDrafts((d) => {
        const { [c.id]: _omit, ...rest } = d;
        return rest;
      });
      toast('Saved', 'success');
    } catch (e) {
      toast(`Save failed: ${e}`, 'error');
    }
  };

  const del = async () => {
    if (!card) return;
    if (!confirm(`Delete "${card.name}"? This cannot be undone.`)) return;
    try {
      if (serverCards.some((c) => c.id === card.id)) await delMut.mutateAsync(card.id);
      setDrafts((d) => {
        const { [card.id]: _omit, ...rest } = d;
        return rest;
      });
      setSelectedId(null);
    } catch (e) {
      toast(`Delete failed: ${e}`, 'error');
    }
  };

  const duplicate = () => {
    if (!card) return;
    const copy: SpotColorSetCard = { ...JSON.parse(JSON.stringify(card)), id: uuid(), name: `${card.name} (copy)` };
    setDrafts((d) => ({ ...d, [copy.id]: copy }));
    setSelectedId(copy.id);
  };

  const create = (kind: 'set' | 'group') => {
    const c = newCard(kind);
    setDrafts((d) => ({ ...d, [c.id]: c }));
    setSelectedId(c.id);
  };

  // The actual §10 proof surface: POST /room-color/apply — a Set lands
  // directly, a Group advances its cursor and applies whichever member it
  // picked (merged with the group's own overrides). Pressing this
  // repeatedly on a Group is how "author a group, use it, watch it
  // rotate" is demonstrated without touching the live room.
  const apply = async () => {
    if (!card) return;
    if (drafts[card.id]) await save();
    try {
      const result = await applyMut.mutateAsync(card.id) as { applied?: string; set_name?: string };
      const memberNote = card.kind === 'group' && result.applied !== card.id
        ? ` → picked "${result.set_name ?? result.applied}"` : '';
      toast(`Applied${memberNote}`, 'success');
    } catch (e) {
      toast(`Apply failed: ${e}`, 'error');
    }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16, alignItems: 'start' }}>
      <div className="card" style={{ minWidth: 0, maxHeight: 'calc(100vh - 80px)', display: 'flex', flexDirection: 'column' }}>
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          Colour Sets & Groups <HelpLink topic="colorsets-groups-page" />
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
            <div className="empty-note" style={{ padding: 10 }}>No colour sets yet — create one with + Set / + Group.</div>
          )}
          {visible.map((c) => {
            const w = wheel[c.id];
            return (
              <div key={c.id} className={`pane-row${c.id === selectedId ? ' selected' : ''}`}
                onClick={() => setSelectedId(c.id)}>
                <div style={{
                  width: 16, height: 16, borderRadius: 4, border: '1px solid var(--border)',
                  background: c.color || '#888', flexShrink: 0,
                }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.name}
                    {drafts[c.id] && <span title="Unsaved changes" style={{ color: 'var(--accent2)' }}> •</span>}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {c.kind === 'group' ? `${c.members?.length ?? 0} member${(c.members?.length ?? 0) === 1 ? '' : 's'}` : (c.labels ?? []).join(', ')}
                  </div>
                </div>
                {c.kind === 'set' && w?.rainbow && <span title="Rainbow — no single wheel position">🌈</span>}
                {c.kind === 'set' && w && !w.rainbow && w.position_deg != null && (
                  <span title={`Wheel position ${w.position_deg}°`} style={{
                    width: 12, height: 12, borderRadius: '50%', flexShrink: 0,
                    border: '1px solid var(--border)', background: `hsl(${w.position_deg}, 85%, 55%)`,
                  }} />
                )}
                <span style={{
                  fontSize: 10, padding: '2px 6px', borderRadius: 10, flexShrink: 0,
                  background: c.kind === 'group' ? 'rgba(156,39,176,0.15)' : 'rgba(33,150,243,0.15)',
                  color: c.kind === 'group' ? '#ba68c8' : '#64b5f6',
                }}>
                  {c.kind}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {card ? (
        <div className="card" style={{ maxHeight: 'calc(100vh - 80px)', overflowY: 'auto' }}>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <input type="text" value={card.name} style={{ fontSize: 15, fontWeight: 600, width: 220 }}
              onChange={(e) => setCard({ ...card, name: e.target.value })} />
            <button className="primary" onClick={() => void save()}>Save{drafts[card.id] ? ' •' : ''}</button>
            <button style={{ fontSize: 12 }} onClick={duplicate}>⧉ Duplicate</button>
            <button style={{ fontSize: 12, borderColor: 'var(--accent)' }}
              title="Apply this Set (or a Group's next picked member) to the room right now — the same live surface POST /room-color/apply uses"
              onClick={() => void apply()}>
              ▶ Apply to room
            </button>
            <button className="danger" style={{ fontSize: 12, marginLeft: 'auto' }} onClick={() => void del()}>✕ Delete</button>
          </div>

          <div className="field" style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
            <div>
              <label>Swatch</label>
              <input type="color" value={card.color || '#FFD700'} style={{ width: 44, height: 32, padding: 2 }}
                onChange={(e) => setCard({ ...card, color: e.target.value })} />
            </div>
            <div style={{ flex: 1 }}>
              <label>Labels</label>
              <input type="text" defaultValue={(card.labels ?? []).join(', ')} key={`labels-${card.id}`}
                placeholder="e.g. warm, drop" style={{ width: '100%' }}
                onBlur={(e) => setCard({
                  ...card,
                  labels: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                })} />
            </div>
          </div>

          {card.kind === 'set' ? (
            <>
              <div className="card-title" style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 4 }}>
                Entries
                <span style={{ fontWeight: 400, marginLeft: 2, fontSize: 11, textTransform: 'none', letterSpacing: 0 }}>
                  FG / BG colour per device or category
                </span>
                <button style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 10px' }}
                  onClick={() => setCard({ ...card, entries: [...(card.entries ?? []), emptyEntry()] })}>
                  + Entry
                </button>
              </div>
              {!(card.entries ?? []).length && (
                <div className="empty-note" style={{ padding: 6 }}>No entries. Add one with + Entry.</div>
              )}
              {(card.entries ?? []).map((entry, i) => (
                <EntryRow key={i} entry={entry} registry={registry} gradients={gradients.map((g) => g.value)}
                  onChange={(e) => setCard({ ...card, entries: (card.entries ?? []).map((x, j) => (j === i ? e : x)) })}
                  onRemove={() => setCard({ ...card, entries: (card.entries ?? []).filter((_, j) => j !== i) })} />
              ))}
            </>
          ) : (
            <>
              <div className="card-title" style={{ marginTop: 8 }}>Group Settings <HelpLink topic="colorsets-groups-page" /></div>
              <div className="field" style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                <label style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 0 }}>
                  Pick mode
                  <select value={card.mode ?? 'cycle'}
                    onChange={(e) => setCard({ ...card, mode: e.target.value as 'cycle' | 'weighted' })}>
                    <option value="cycle">Cycle (sequential)</option>
                    <option value="weighted">Weighted random</option>
                  </select>
                </label>
                {(card.mode ?? 'cycle') === 'cycle' && (
                  <label style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 0 }}>
                    Cycle behaviour
                    <select value={card.cycle_behavior ?? 'wrap'}
                      onChange={(e) => setCard({ ...card, cycle_behavior: e.target.value as 'wrap' | 'bounce' })}>
                      <option value="wrap">Wrap (back to top)</option>
                      <option value="bounce">Bounce (reverse at ends)</option>
                    </select>
                  </label>
                )}
                {(card.mode ?? 'cycle') === 'weighted' && (
                  <label style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 0, cursor: 'pointer' }}
                    title="Weighted mode only — cycle never repeats the showing member by construction">
                    <input type="checkbox" checked={card.exclude_current !== false}
                      onChange={(e) => setCard({ ...card, exclude_current: e.target.checked })} />
                    Exclude current from next roll
                  </label>
                )}
                <label style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 0, cursor: 'pointer' }}
                  title="Start picks from the member matching the room's current colour, instead of this group's own private cycle position">
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
                    if (!sets.length) { toast('Create a Colour Set first', 'error'); return; }
                    const members: SpotGroupMember[] = [...(card.members ?? []), { color_set_id: sets[0].id, weight: 1 }];
                    setCard({ ...card, members });
                  }}>
                  + Member
                </button>
              </div>
              {!(card.members ?? []).length && (
                <div className="empty-note" style={{ padding: 6 }}>No members. Add one with + Member.</div>
              )}
              {(card.members ?? []).map((m, i) => {
                const members = card.members ?? [];
                const setMember = (patch: Partial<SpotGroupMember>) =>
                  setCard({ ...card, members: members.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
                return (
                  <div key={i} style={{
                    background: 'var(--surface2)', padding: 8, borderRadius: 'var(--radius)', marginBottom: 8,
                    display: 'flex', alignItems: 'center', gap: 8,
                  }}>
                    <select value={m.color_set_id} style={{ flex: 1, minWidth: 0, fontSize: 12 }}
                      onChange={(e) => setMember({ color_set_id: e.target.value })}>
                      {!sets.some((s) => s.id === m.color_set_id) && (
                        <option value={m.color_set_id}>{m.color_set_id} (missing)</option>
                      )}
                      {sets.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                    {(card.mode ?? 'cycle') === 'weighted' && (
                      <>
                        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Wt</span>
                        <input type="number" min={0} step={0.1} value={m.weight ?? 1} style={{ width: 60 }}
                          onChange={(e) => setMember({ weight: parseFloat(e.target.value) || 0 })} />
                      </>
                    )}
                    <button style={{ fontSize: 12 }} title="Move up" disabled={i === 0}
                      onClick={() => {
                        const ms = [...members];
                        [ms[i - 1], ms[i]] = [ms[i], ms[i - 1]];
                        setCard({ ...card, members: ms });
                      }}>↑</button>
                    <button style={{ fontSize: 12 }} title="Move down" disabled={i === members.length - 1}
                      onClick={() => {
                        const ms = [...members];
                        [ms[i], ms[i + 1]] = [ms[i + 1], ms[i]];
                        setCard({ ...card, members: ms });
                      }}>↓</button>
                    <button className="danger" style={{ fontSize: 12 }} title="Remove"
                      onClick={() => setCard({ ...card, members: members.filter((_, j) => j !== i) })}>✕</button>
                  </div>
                );
              })}

              <div className="card-title" style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 4 }}>
                Overrides <HelpLink topic="colorsets-group-overrides" />
                <span style={{ fontWeight: 400, marginLeft: 2, fontSize: 11, textTransform: 'none', letterSpacing: 0 }}>
                  replace the picked Set's values per device/category
                </span>
                <button style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 10px' }}
                  onClick={() => setCard({ ...card, entries: [...(card.entries ?? []), emptyEntry()] })}>
                  + Override
                </button>
              </div>
              {!(card.entries ?? []).length && (
                <div className="empty-note" style={{ padding: 6 }}>
                  No overrides. Fields set here win over the picked Set for the scoped devices; unset fields keep the Set's values.
                </div>
              )}
              {(card.entries ?? []).map((entry, i) => (
                <EntryRow key={i} entry={entry} registry={registry} gradients={gradients.map((g) => g.value)}
                  onChange={(e) => setCard({ ...card, entries: (card.entries ?? []).map((x, j) => (j === i ? e : x)) })}
                  onRemove={() => setCard({ ...card, entries: (card.entries ?? []).filter((_, j) => j !== i) })} />
              ))}
            </>
          )}
        </div>
      ) : (
        <p className="empty-note" style={{ marginTop: 24 }}>Select a Colour Set, or create one with + Set / + Group.</p>
      )}
    </div>
  );
}
