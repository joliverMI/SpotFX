/** AI Triggers modals: song picker, manage profiles, load-saved, cost confirm,
 * existing-triggers guard, manual add, analyze-learning result. */
import { useMemo, useState } from 'react';
import SearchSelect from '../components/forms/SearchSelect';
import { useLongPress } from '../lib/useLongPress';
import type { EventOption } from '../builder/types';
import type { CostEstimate, SavedSetSummary, SongInfo, TrainingProfile } from './types';
import { fmtTs, parseTsInput } from './types';

export function Modal({ width = 460, onClose, children }: {
  width?: number; onClose: () => void; children: React.ReactNode;
}) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{
        background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 8,
        width: `min(${width}px, 95vw)`, padding: 16, maxHeight: '85vh',
        display: 'flex', flexDirection: 'column',
      }}>
        {children}
      </div>
    </div>
  );
}

export function ModalHeader({ title, onClose, extra }: {
  title: string; onClose: () => void; extra?: React.ReactNode;
}) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
      <span style={{ fontWeight: 600 }}>{title}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {extra}
        <span style={{ cursor: 'pointer', color: 'var(--text-muted)' }} onClick={onClose}>✕</span>
      </div>
    </div>
  );
}

// ── Song picker (training / embedded / target modes) ─────────────────────────
export function SongPickerModal({ mode, songs, activeUris, matchesFilter, onPick, onClose }: {
  mode: 'training' | 'embedded' | 'target';
  songs: SongInfo[];
  activeUris: Set<string>;
  /** target mode only: genre-match + untrained + no-suggestions predicate, or null to hide the toggle */
  matchesFilter: ((s: SongInfo) => boolean) | null;
  onPick: (song: SongInfo) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState('');
  const [matchesOnly, setMatchesOnly] = useState(false);
  const title = mode === 'training' ? 'Add AI + Embedded Training Song'
    : mode === 'embedded' ? 'Add Embedded Only Training Song' : 'Add Target Song';

  let filtered = songs.filter((s) => (s.title + s.artist).toLowerCase().includes(q.toLowerCase()));
  if (matchesOnly && matchesFilter) filtered = filtered.filter(matchesFilter);

  return (
    <Modal onClose={onClose}>
      <ModalHeader title={title} onClose={onClose} />
      {mode === 'target' && matchesFilter && (
        <div style={{ marginBottom: 8 }}>
          <button className={`toggle-btn ${matchesOnly ? 'active' : ''}`} style={{ fontSize: 12 }}
            onClick={() => setMatchesOnly((m) => !m)}>
            Matches: {matchesOnly ? 'On' : 'Off'}
          </button>
        </div>
      )}
      <input type="text" placeholder="Search…" value={q} autoFocus
        style={{ width: '100%', marginBottom: 10 }} onChange={(e) => setQ(e.target.value)} />
      <div style={{ maxHeight: 320, overflowY: 'auto' }}>
        {!filtered.length && (
          <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: 8 }}>No songs found.</div>
        )}
        {filtered.map((s) => {
          const already = activeUris.has(s.uri);
          return (
            <div key={s.uri}
              style={{ padding: '8px 10px', borderRadius: 4, fontSize: 13, cursor: already ? 'default' : 'pointer', opacity: already ? 0.4 : 1 }}
              onClick={() => { if (!already) { onPick(s); } }}>
              <div>{s.artist} — {s.title}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                {s.trigger_count != null ? `${s.trigger_count} triggers · ` : ''}{s.mark_count ?? 0} marks
                {already ? ' · already added' : ''}
              </div>
            </div>
          );
        })}
      </div>
    </Modal>
  );
}

// ── Manage training profiles ─────────────────────────────────────────────────
export function ManageProfilesModal({ profiles, onLoad, onDelete, onBackfill, onClose }: {
  profiles: TrainingProfile[];
  onLoad: (id: string) => void;
  onDelete: (id: string, name: string) => void;
  onBackfill: () => Promise<{ updated: number }>;
  onClose: () => void;
}) {
  const [q, setQ] = useState('');
  const [backfilling, setBackfilling] = useState(false);
  const filtered = q ? profiles.filter((p) => p.name.toLowerCase().includes(q.toLowerCase())) : profiles;
  return (
    <Modal width={480} onClose={onClose}>
      <ModalHeader title="Training Profiles" onClose={onClose}
        extra={
          <button disabled={backfilling}
            style={{ fontSize: 11, padding: '3px 8px' }}
            title="Fetch genres from Spotify for all captured shapes"
            onClick={async () => {
              setBackfilling(true);
              try {
                const r = await onBackfill();
                alert(`Updated ${r.updated} shape${r.updated !== 1 ? 's' : ''} with genres`);
              } catch {
                alert('Backfill failed — check the server log');
              } finally {
                setBackfilling(false);
              }
            }}>
            {backfilling ? 'Working…' : 'Backfill Genres'}
          </button>
        } />
      <input type="text" placeholder="Search…" value={q} style={{ width: '100%', marginBottom: 10 }}
        onChange={(e) => setQ(e.target.value)} />
      <div style={{ overflowY: 'auto', flex: 1 }}>
        {!filtered.length && (
          <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: 8 }}>No training profiles found.</div>
        )}
        {filtered.map((p) => (
          <div key={p.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, padding: '8px 10px', borderRadius: 4 }}>
            <div style={{ flex: 1, minWidth: 0, cursor: 'pointer' }} onClick={() => onLoad(p.id)}>
              <div>
                {p.name}
                {p.is_default && (
                  <span style={{ fontSize: 10, background: '#1565c0', color: '#fff', borderRadius: 8, padding: '1px 6px', marginLeft: 6 }}>default</span>
                )}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                {p.training_uris?.length ?? 0} training · {p.target_uris?.length ?? 0} target
                {(p.genres ?? []).length ? ` · ${p.genres!.join(', ')}` : ''}
              </div>
            </div>
            <button className="danger" style={{ flexShrink: 0, fontSize: 12, padding: '2px 8px' }}
              onClick={() => onDelete(p.id, p.name)}>✕</button>
          </div>
        ))}
      </div>
    </Modal>
  );
}

// ── Load saved suggestion sets ────────────────────────────────────────────────
type SavedFilter = 'all' | 'not-applied' | 'unreviewed' | 'reviewed' | 'applied';
const SAVED_TABS: { key: SavedFilter; label: string }[] = [
  { key: 'all', label: 'All' }, { key: 'not-applied', label: 'Not Applied' },
  { key: 'unreviewed', label: 'Unreviewed' }, { key: 'reviewed', label: 'Reviewed' },
  { key: 'applied', label: 'Applied' },
];

export function LoadSavedModal({ sets, onLoad, onClose }: {
  sets: SavedSetSummary[];
  onLoad: (trackId: string) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<SavedFilter>('all');
  const unreviewedCount = sets.filter((s) => !s.reviewed && !s.applied).length;

  const filtered = useMemo(() => {
    let f = sets;
    if (filter === 'not-applied') f = f.filter((s) => !s.applied);
    else if (filter === 'unreviewed') f = f.filter((s) => !s.reviewed && !s.applied);
    else if (filter === 'reviewed') f = f.filter((s) => s.reviewed && !s.applied);
    else if (filter === 'applied') f = f.filter((s) => s.applied);
    if (q) f = f.filter((s) => (s.title + s.artist).toLowerCase().includes(q.toLowerCase()));
    if (filter === 'all') {
      f = [...f].sort((a, b) => {
        const au = !a.reviewed && !a.applied ? 0 : 1;
        const bu = !b.reviewed && !b.applied ? 0 : 1;
        if (au !== bu) return au - bu;
        return (b.generated_at || '').localeCompare(a.generated_at || '');
      });
    }
    return f;
  }, [sets, q, filter]);

  return (
    <Modal width={520} onClose={onClose}>
      <ModalHeader title="Load Saved Suggestions" onClose={onClose} />
      <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
        {SAVED_TABS.map((t) => (
          <button key={t.key}
            style={{
              fontSize: 12, padding: '3px 10px', borderRadius: 12,
              background: filter === t.key ? '#7c4dff' : 'var(--surface)',
              color: filter === t.key ? '#fff' : 'var(--text-muted)',
              border: filter === t.key ? '1px solid transparent' : '1px solid var(--border)',
            }}
            onClick={() => setFilter(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      {unreviewedCount > 0 && (
        <button style={{ width: '100%', marginBottom: 10, padding: 5, fontSize: 12 }}
          onClick={() => {
            const next = sets.find((s) => !s.reviewed && !s.applied);
            if (next) onLoad(next.track_id);
          }}>
          Review Next Unreviewed ({unreviewedCount} left) →
        </button>
      )}
      <input type="text" placeholder="Search…" value={q} style={{ width: '100%', marginBottom: 10 }}
        onChange={(e) => setQ(e.target.value)} />
      <div style={{ overflowY: 'auto', flex: 1 }}>
        {!filtered.length && (
          <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: 8 }}>No saved sets found for this filter.</div>
        )}
        {filtered.map((s) => (
          <div key={s.track_id} style={{ padding: '8px 10px', borderRadius: 4, cursor: 'pointer' }}
            onClick={() => onLoad(s.track_id)}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', fontSize: 13 }}>
              <span>{s.artist} — {s.title}</span>
              {s.applied && <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 8, background: '#2e7d32', color: '#fff' }}>applied</span>}
              {s.reviewed && <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 8, background: '#1565c0', color: '#fff' }}>reviewed</span>}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {s.suggestion_count} suggestions · {s.generated_at ? new Date(s.generated_at).toLocaleString() : ''}
              {s.training_profile_name ? ` · ${s.training_profile_name}` : ''}
            </div>
          </div>
        ))}
      </div>
    </Modal>
  );
}

// ── Cost estimate confirm ─────────────────────────────────────────────────────
export function CostConfirmModal({ estimate, onRun, onRunEmbedded, onClose }: {
  estimate: CostEstimate;
  onRun: (model: string) => void;
  onRunEmbedded: () => void;
  onClose: () => void;
}) {
  const longPress = useLongPress(500);
  const fmtK = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
  const fmtC = (n: number) => `${(n * 100).toFixed(1)}¢`;
  const rows = estimate.per_song.map((s) =>
    s.error
      ? `  ${(s.title || s.uri).padEnd(30)}  ERROR: ${s.error}`
      : `  ${(`${s.artist} — ${s.title}`).padEnd(40)}  ${fmtK(s.input_tokens).padStart(6)} in  ${fmtK(s.output_tokens)} out`,
  ).join('\n');

  return (
    <Modal width={480} onClose={onClose}>
      <div style={{ fontWeight: 600, marginBottom: 10 }}>Estimated generation cost</div>
      <div style={{
        fontSize: 12, fontFamily: 'monospace', background: 'var(--surface)', borderRadius: 4,
        padding: 10, marginBottom: 12, whiteSpace: 'pre', overflowX: 'auto',
      }}>
        {rows}
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
        ~{fmtK(estimate.total_input_tokens)} in + {fmtK(estimate.total_output_tokens)} out tokens
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 14 }}>
        Hold a model button for 500ms to start generation. Output estimated at 1 000 tokens/song.
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <button className="primary" style={{ flex: 1, padding: '10px 6px' }}
          {...longPress(() => onRun('claude-haiku-4-5-20251001'))}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Haiku</div>
          <div style={{ fontSize: 11, opacity: 0.8 }}>{fmtC(estimate.total_haiku_cost_usd)}</div>
        </button>
        <button className="primary" style={{ flex: 1, padding: '10px 6px' }}
          {...longPress(() => onRun('claude-sonnet-4-6'))}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Sonnet</div>
          <div style={{ fontSize: 11, opacity: 0.8 }}>{fmtC(estimate.total_sonnet_cost_usd)}</div>
        </button>
        <button className="primary" style={{ flex: 1, padding: '10px 6px' }} onClick={onRunEmbedded}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Embedded</div>
          <div style={{ fontSize: 11 }}>free · local</div>
        </button>
      </div>
      <button style={{ width: '100%', padding: 8 }} onClick={onClose}>Cancel</button>
    </Modal>
  );
}

// ── Existing-triggers guard ──────────────────────────────────────────────────
export function ExistingTriggersModal({ song, onKeep, onDeleteAll, onClose }: {
  song: SongInfo;
  onKeep: () => void;
  onDeleteAll: () => void;
  onClose: () => void;
}) {
  const longPress = useLongPress(2000);
  const [holding, setHolding] = useState(false);
  const lp = longPress(() => { setHolding(false); onDeleteAll(); });
  return (
    <Modal width={400} onClose={onClose}>
      <div style={{ fontWeight: 600, marginBottom: 6 }}>Song has existing triggers</div>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>
        "{song.title}" already has {song.trigger_count} trigger(s). How should we proceed?
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <button className="primary" style={{ width: '100%', padding: 9 }} onClick={onKeep}>
          Keep existing triggers
          <div style={{ fontSize: 11, fontWeight: 400, opacity: 0.75, marginTop: 2 }}>
            AI will suggest additions only — no duplicates
          </div>
        </button>
        <button className="danger"
          style={{
            width: '100%', padding: 9, position: 'relative', overflow: 'hidden', userSelect: 'none',
            backgroundImage: 'linear-gradient(rgba(255,255,255,0.18), rgba(255,255,255,0.18))',
            backgroundRepeat: 'no-repeat',
            backgroundSize: holding ? '100% 100%' : '0% 100%',
            transition: holding ? 'background-size 2000ms linear' : 'none',
          }}
          {...lp}
          onPointerDown={(e) => { setHolding(true); lp.onPointerDown(e); }}
          onPointerUp={() => { setHolding(false); lp.onPointerUp(); }}
          onPointerLeave={() => { setHolding(false); lp.onPointerLeave(); }}>
          {holding ? 'Hold…' : 'Hold to delete all triggers'}
        </button>
        <button style={{ width: '100%' }} onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

// ── Manual add trigger ────────────────────────────────────────────────────────
export function ManualAddModal({ prefillMs, events, defaultEventId, onAdd, onClose }: {
  prefillMs: number | null;
  events: EventOption[];
  defaultEventId: string;
  onAdd: (data: { ms: number; eventId: string; labels: string[]; comment: string }) => void;
  onClose: () => void;
}) {
  const [ts, setTs] = useState(prefillMs !== null ? fmtTs(prefillMs) : '');
  const [eventId, setEventId] = useState(defaultEventId);
  const [labels, setLabels] = useState('');
  const [comment, setComment] = useState('');
  return (
    <Modal width={380} onClose={onClose}>
      <ModalHeader title="Add Trigger Manually" onClose={onClose} />
      <div className="field">
        <label>Timestamp (m:ss.t)</label>
        <input type="text" placeholder="0:00.0" value={ts} style={{ width: '100%' }}
          onChange={(e) => setTs(e.target.value)} />
      </div>
      <div className="field">
        <label>Music Event</label>
        <SearchSelect value={eventId} onChange={setEventId} width="100%" allowEmpty={false}
          options={events.map((e) => ({ value: e.id, label: e.name }))} />
      </div>
      <div className="field">
        <label>Labels (comma-separated)</label>
        <input type="text" placeholder="e.g. blue, strobe" value={labels} style={{ width: '100%' }}
          onChange={(e) => setLabels(e.target.value)} />
      </div>
      <div className="field">
        <label>Why did you add this? (helps Analyze Learning)</label>
        <textarea rows={2} placeholder="e.g. Clear bass drop the AI missed" value={comment}
          style={{ width: '100%', resize: 'vertical' }}
          onChange={(e) => setComment(e.target.value)} />
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <button className="primary" onClick={() => {
          const ms = parseTsInput(ts);
          if (ms === null) { alert('Invalid timestamp. Use m:ss or m:ss.t format.'); return; }
          onAdd({
            ms, eventId,
            labels: labels.split(',').map((s) => s.trim()).filter(Boolean),
            comment,
          });
        }}>Add</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Modal>
  );
}

// ── Analyze Learning result ───────────────────────────────────────────────────
export function AnalyzeResultModal({ text, onApply, onClose }: {
  text: string;
  onApply: () => void;
  onClose: () => void;
}) {
  return (
    <Modal width={560} onClose={onClose}>
      <ModalHeader title="Refined Description" onClose={onClose} />
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
        Claude analyzed what you approved and rejected. Review the suggested refinement below,
        then click Apply to use it.
      </div>
      <textarea readOnly value={text} style={{ width: '100%', height: 120, resize: 'vertical', margin: '12px 0' }} />
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="primary" onClick={onApply}>Apply to Profile</button>
        <button onClick={onClose}>Discard</button>
      </div>
    </Modal>
  );
}
