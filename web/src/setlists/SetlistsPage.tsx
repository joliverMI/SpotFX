/** Set Lists — playlist-context configs (port of frontend/setlist.html).
 * Two-pane list/editor with a draft model matching Devices/Color Sets. */
import { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiDel, apiGet, apiPost } from '../api/client';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';
import { uuid } from '../lib/uid';

interface Setlist {
  id: string;
  name: string;
  context_uri: string;
  auto_activate: boolean;
  auto_use_analyzed: boolean;
  genre_blending: 'global' | 'on' | 'off';
  xcorr_enabled?: boolean;
  xcorr_cut_buffer_ms: number | null;
  notes: string;
  [k: string]: unknown;
}

interface Discoverable {
  context_uri: string;
  name?: string;
}

interface DriftEntry {
  uri: string;
  title?: string;
  anti_corr_count: number;
}

const blankSetlist = (id: string): Setlist => ({
  id, name: 'New Set List', context_uri: '', auto_activate: false,
  auto_use_analyzed: false, genre_blending: 'global', xcorr_cut_buffer_ms: null, notes: '',
});

export default function SetlistsPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const { data: setlists = [], isLoading } = useQuery({
    queryKey: ['setlists'],
    queryFn: () => apiGet<Setlist[]>('/setlists'),
  });
  const { data: discoverable = [] } = useQuery({
    queryKey: ['setlists-discoverable'],
    queryFn: () => apiGet<Discoverable[]>('/setlists/discoverable'),
    retry: false,
  });

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [draft, setDraft] = useState<Setlist | null>(null);

  const selected = setlists.find((s) => s.id === selectedId) ?? null;
  useEffect(() => {
    setDraft(selected ? { ...selected } : null);
  }, [selectedId, selected]);

  const { data: drift = [] } = useQuery({
    queryKey: ['setlist-drift', selectedId],
    queryFn: () => apiGet<DriftEntry[]>(`/setlists/${selectedId}/drift`),
    enabled: !!selectedId,
    retry: false,
  });

  const visible = useMemo(() => {
    const q = search.toLowerCase();
    return q
      ? setlists.filter((s) =>
          (s.name || '').toLowerCase().includes(q) || (s.context_uri || '').toLowerCase().includes(q))
      : setlists;
  }, [setlists, search]);

  const invalidate = () => qc.invalidateQueries({ queryKey: ['setlists'] });

  const save = async () => {
    if (!draft) return;
    try {
      await apiPost('/setlists', {
        ...draft,
        name: draft.name.trim(),
        context_uri: draft.context_uri.trim(),
      });
      toast('Saved', 'success');
      await invalidate();
    } catch (e) {
      toast(`Error: ${e instanceof Error ? e.message : e}`, 'error');
    }
  };

  const del = async () => {
    if (!draft || !confirm(`Delete Set List "${draft.name}"?`)) return;
    await apiDel(`/setlists/${draft.id}`);
    setSelectedId(null);
    toast('Deleted', 'success');
    await invalidate();
  };

  const createNew = async (fromUri?: Discoverable) => {
    const sl = blankSetlist(uuid());
    if (fromUri) {
      sl.context_uri = fromUri.context_uri;
      sl.name = fromUri.name || fromUri.context_uri.split(':').pop() || 'New Set List';
    }
    await apiPost('/setlists', sl);
    toast(fromUri ? `Tracking "${sl.name}"` : 'Created', 'success');
    await invalidate();
    setSelectedId(sl.id);
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 16, alignItems: 'start' }}>
      {/* ── List ── */}
      <div className="card" style={{ maxHeight: 'calc(100vh - 80px)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
          <input type="text" placeholder="Search..." value={search} style={{ flex: 1 }}
            onChange={(e) => setSearch(e.target.value)} />
          <button className="primary" style={{ fontSize: 12 }} onClick={() => void createNew()}>+ New</button>
        </div>
        <div style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
          {isLoading && <div className="empty-note" style={{ padding: 8 }}>Loading…</div>}
          {!isLoading && !visible.length && (
            <div style={{ color: 'var(--text-muted)', padding: 8, fontSize: 13 }}>No Set Lists yet</div>
          )}
          {visible.map((s) => (
            <div key={s.id} className={`pane-row${s.id === selectedId ? ' selected' : ''}`}
              style={{ flexDirection: 'column', alignItems: 'stretch', gap: 2 }}
              onClick={() => setSelectedId(s.id)}>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{s.name || '(unnamed)'}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', wordBreak: 'break-all' }}>
                {s.context_uri || 'no context uri'}
              </div>
            </div>
          ))}
        </div>
        {!!discoverable.length && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Recently observed:</div>
            {discoverable.map((p) => (
              <span key={p.context_uri} className="chip" title={p.context_uri}
                style={{ cursor: 'pointer', margin: '2px 4px 2px 0' }}
                onClick={() => void createNew(p)}>
                {p.name || p.context_uri.split(':').pop()}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* ── Editor ── */}
      {draft ? (
        <div className="card" style={{ maxHeight: 'calc(100vh - 80px)', overflowY: 'auto' }}>
          <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
            <button className="primary" onClick={() => void save()}>Save</button>
            <button className="danger" onClick={() => void del()}>Delete</button>
          </div>

          <div className="field">
            <label>Name</label>
            <input type="text" placeholder="Friday Energy Mix" value={draft.name} style={{ width: '100%' }}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </div>
          <div className="field">
            <label>Spotify Context URI</label>
            <input type="text" placeholder="spotify:playlist:abc123" value={draft.context_uri} style={{ width: '100%' }}
              onChange={(e) => setDraft({ ...draft, context_uri: e.target.value })} />
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>
              Lookup key. Use the discovered list on the left to fill this in automatically.
            </div>
          </div>

          <SectionTitle>When this Set List is active</SectionTitle>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, cursor: 'pointer', fontSize: 13 }}>
            <input type="checkbox" checked={draft.auto_activate}
              onChange={(e) => setDraft({ ...draft, auto_activate: e.target.checked })} />
            Auto-activate (unpause if paused)
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, cursor: 'pointer', fontSize: 13 }}>
            <input type="checkbox" checked={draft.auto_use_analyzed}
              onChange={(e) => setDraft({ ...draft, auto_use_analyzed: e.target.checked })} />
            Force "Use Analyzed Triggers" on
          </label>
          <div className="field">
            <label>Genre blending</label>
            <select value={draft.genre_blending}
              onChange={(e) => setDraft({ ...draft, genre_blending: e.target.value as Setlist['genre_blending'] })}>
              <option value="global">Use global setting</option>
              <option value="on">Force on</option>
              <option value="off">Force off</option>
            </select>
          </div>

          <SectionTitle>xcorr / mix tolerance <HelpLink topic="setlists-xcorr" title="Timing options help" /></SectionTitle>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, cursor: 'pointer', fontSize: 13 }}>
            <input type="checkbox" checked={draft.xcorr_enabled !== false}
              onChange={(e) => setDraft({ ...draft, xcorr_enabled: e.target.checked })} />
            Run per-play xcorr while this Set List is active
          </label>
          <div className="field">
            <label>xcorr cut buffer (ms) — leave blank to use global default</label>
            <input type="number" min={0} step={500} placeholder="(global)" style={{ width: 110 }}
              value={draft.xcorr_cut_buffer_ms ?? ''}
              onChange={(e) => setDraft({
                ...draft,
                xcorr_cut_buffer_ms: e.target.value === '' ? null : Math.max(0, parseInt(e.target.value, 10) || 0),
              })} />
          </div>

          {!!drift.length && (
            <div style={{
              background: 'rgba(255,152,0,0.10)', border: '1px solid rgba(255,152,0,0.4)',
              padding: '8px 10px', borderRadius: 6, fontSize: 12, color: '#ff9800', marginBottom: 10,
            }}>
              <strong>{drift.length} song{drift.length > 1 ? 's' : ''} drifting</strong>
              {' '}— stored offset doesn't match recent playback:<br />
              {drift.slice(0, 5).map((d) => (
                <span key={d.uri}>• {d.title || d.uri.split(':').pop()} — {d.anti_corr_count}× anti-correlated<br /></span>
              ))}
              {drift.length > 5 && <>+ {drift.length - 5} more</>}
            </div>
          )}

          <SectionTitle>Notes</SectionTitle>
          <textarea rows={3} placeholder="Anything to remember about this set list..." value={draft.notes}
            style={{ width: '100%', resize: 'vertical' }}
            onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />
        </div>
      ) : (
        <p className="empty-note" style={{ marginTop: 24 }}>Select a Set List, or create one with + New.</p>
      )}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 13, fontWeight: 600, color: 'var(--text)', margin: '16px 0 8px 0',
      paddingBottom: 4, borderBottom: '1px solid var(--border)',
    }}>
      {children}
    </div>
  );
}
