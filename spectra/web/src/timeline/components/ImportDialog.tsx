/** Import triggers: pull from the AI analysis service (scenes / flares / both)
 * or copy from another setlist slot. Merge = append with same-timestamp
 * overwrite (classic _mergeAddTriggers semantics), into the WORKING list. */
import { useState } from 'react';
import { apiGet } from '../../api/spotfx';
import { useToast } from '../../components/Toast';
import { uuid } from '../../lib/uid';
import { useBuilderStore } from '../store';
import type { MusicTrigger, Setlist } from '../types';

// Keep in lockstep with components/ModeBar.tsx's SETLIST_SLOTS_ENABLED —
// per-song Set List "slot" overrides retired 2026-08-17 (docs/SPECTRA_SPEC.md
// OQ-5/§41). His setlist_triggers data is untouched on disk; this just stops
// slot lists from being offered as an import source.
const SETLIST_SLOTS_ENABLED = false;

interface AnalyzeResp {
  triggers?: { timestamp_ms: number; event_id: string; intensity?: number | null }[];
  training_profile?: string;
}

export default function ImportDialog({
  uri,
  setlists,
  onClose,
}: {
  uri: string | null;
  setlists: Setlist[];
  onClose: () => void;
}) {
  const toast = useToast();
  const profile = useBuilderStore((s) => s.profile);
  const slotId = useBuilderStore((s) => s.slotId);
  const [busy, setBusy] = useState(false);
  const [copyFrom, setCopyFrom] = useState('');

  const mergeIn = (incoming: MusicTrigger[]) => {
    let added = 0;
    useBuilderStore.getState().mutateWorking((ts) => {
      const byTs = new Map(ts.map((t) => [t.timestamp_ms, t]));
      for (const t of incoming) byTs.set(t.timestamp_ms, t);
      added = byTs.size - ts.length;
      ts.splice(0, ts.length, ...[...byTs.values()].sort((a, b) => a.timestamp_ms - b.timestamp_ms));
    });
    return added;
  };

  const pull = async (category: 'scenes' | 'flares' | 'both') => {
    if (!uri) return;
    const cats = category === 'both' ? (['scenes', 'flares'] as const) : ([category] as const);
    setBusy(true);
    try {
      for (const cat of cats) {
        const resp = await apiGet<AnalyzeResp>(
          `/ai-triggers/analyze-triggers?uri=${encodeURIComponent(uri)}&category=${cat}`);
        if (!resp.triggers?.length) {
          toast(`No ${cat} triggers generated`);
          continue;
        }
        const added = mergeIn(resp.triggers.map((t) => ({
          id: uuid(), timestamp_ms: t.timestamp_ms, event_id: t.event_id,
          labels: [], enabled: true, intensity: t.intensity ?? 0.5,
        })));
        toast(`Added ${added} ${cat}${resp.training_profile ? ` (profile: ${resp.training_profile})` : ''}`,
          'success');
      }
      onClose();
    } catch (e) {
      toast(`Analyze failed: ${e instanceof Error ? e.message : e}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  // Slots that actually hold a list, minus the one being edited.
  const sources = [
    { id: '', name: 'Default', has: !!profile?.triggers.length },
    ...(SETLIST_SLOTS_ENABLED ? setlists.map((sl) => ({
      id: sl.id, name: sl.name, has: !!profile?.setlist_triggers[sl.id]?.length,
    })) : []),
  ].filter((s) => s.has && s.id !== slotId);
  const sel = sources.some((s) => s.id === copyFrom) ? copyFrom : sources[0]?.id ?? '';

  const copy = () => {
    if (!profile) return;
    const src = sel === '' ? profile.triggers : profile.setlist_triggers[sel];
    if (!src?.length) return;
    const added = mergeIn(src.map((t) => ({ ...JSON.parse(JSON.stringify(t)) as MusicTrigger, id: uuid() })));
    toast(`Copied ${src.length} triggers (${added} new timestamps)`, 'success');
    onClose();
  };

  return (
    <div onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
               display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div className="card" onClick={(e) => e.stopPropagation()} style={{ width: 380, margin: 0 }}>
        <h3 style={{ marginTop: 0 }}>Import triggers</h3>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: -6 }}>
          Merges into {slotId ? 'the current slot' : 'Default'} — same-timestamp triggers are overwritten.
        </p>

        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Pull from Analysis</div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
          <button disabled={busy || !uri} onClick={() => pull('scenes')}>+ Scenes</button>
          <button disabled={busy || !uri} onClick={() => pull('flares')}>+ Flares</button>
          <button disabled={busy || !uri} onClick={() => pull('both')}>+ Both</button>
          {busy && <span style={{ fontSize: 12, color: 'var(--text-muted)', alignSelf: 'center' }}>analyzing…</span>}
        </div>

        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Copy from</div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
          <select value={sel} onChange={(e) => setCopyFrom(e.target.value)} style={{ flex: 1 }}>
            {sources.length === 0 && <option value="">— no other lists —</option>}
            {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <button disabled={!sources.length} onClick={copy}>
            Copy
          </button>
        </div>

        <div style={{ textAlign: 'right' }}>
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
