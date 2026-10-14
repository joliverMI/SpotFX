/** Home's quick-run cards (song-layout-plan, data/ui-layout-plan/
 * report.md §5): "Quick sequences" (his recent sequences, one tap to
 * run) and "Quick actions" (his sets, the Run view's own four one-tap
 * icons ⚡🐇▲▼) side by side, capped width on desktop/tablet — never
 * full width. Deliberately self-contained rather than literally
 * extracting `QuickStartCard`/`SetRunRows` out of the Light Show page's
 * own `SequenceView.tsx`/`RunView.tsx` (the report's own suggested
 * names): those two files are large, stateful, and not otherwise part
 * of this slice's surface, so duplicating the small, read-mostly bits
 * here keeps this change's conflict surface small. A later pass can
 * extract the two shared components properly, which would let the
 * Light Show page's own Run view and this one share one implementation. */
import { useCallback, useEffect, useState } from 'react';
import { apiDel, apiGet, apiPost } from '../api/client';
import Icon from '../components/Icon';
import type { ArmsStatus, ArmTrigger, RecentSequenceRun, ShowRun, ShowSequence, ShowSet } from '../lightshow/types';

function fmtAgo(ms: number): string {
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

const triggerLabel = (t: ArmTrigger | string): string => (
  t === 'scene_change' ? 'next scene change'
    : t === 'high' ? 'next High Trigger'
    : t === 'low' ? 'next Low Trigger' : String(t)
);

export default function HomeQuickRuns() {
  const [sequences, setSequences] = useState<ShowSequence[]>([]);
  const [recent, setRecent] = useState<RecentSequenceRun[]>([]);
  const [sets, setSets] = useState<ShowSet[]>([]);
  const [arms, setArms] = useState<ArmsStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const reloadArms = useCallback(() => void apiGet<ArmsStatus>('/light-show/arms').then(setArms).catch(() => undefined), []);
  useEffect(() => {
    void apiGet<{ sequences: ShowSequence[] }>('/light-show/sequences').then((r) => setSequences(r.sequences)).catch(() => undefined);
    void apiGet<{ recent: RecentSequenceRun[] }>('/light-show/sequences/recent').then((r) => setRecent(r.recent)).catch(() => undefined);
    void apiGet<{ sets: ShowSet[] }>('/light-show/sets').then((r) => setSets(r.sets)).catch(() => undefined);
    reloadArms();
  }, [reloadArms]);

  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const recentKnown = recent.filter((r) => sequences.some((s) => s.id === r.sequence_id));

  const startSequence = async (id: string, name: string, replace: boolean) => {
    if (replace && !window.confirm(`"${name}" is running. Stop it and start this one?`)) return;
    setBusy(true);
    try {
      await apiPost('/light-show/sequence-run/start', { sequence_id: id, replace });
      setToast(`Started "${name}"`);
    } catch (e) {
      setToast(String(e));
    } finally {
      setBusy(false);
    }
  };

  const fireSet = async (id: string, name: string) => {
    setBusy(true);
    try {
      const run = await apiPost<ShowRun>(`/light-show/sets/${id}/fire`);
      setToast(`Fired "${name}" — ${run.state}`);
    } catch (e) {
      setToast(String(e));
    } finally {
      setBusy(false);
    }
  };

  const arm = async (id: string, name: string, on: ArmTrigger) => {
    try {
      await apiPost('/light-show/arms', { set_id: id, on });
      setToast(`Armed "${name}" for the ${triggerLabel(on)}`);
      reloadArms();
    } catch (e) {
      setToast(String(e));
    }
  };

  const disarm = async (armId: string) => {
    await apiDel(`/light-show/arms/${armId}`).catch((e) => setToast(String(e)));
    reloadArms();
  };

  return (
    <div className="home-quick-runs">
      {toast && <div className="home-quick-toast" role="status">{toast}</div>}
      <div className="card home-quick-card">
        <strong>Quick sequences</strong>
        {recentKnown.length === 0 && <p className="muted">No sequences run yet.</p>}
        <ul className="home-quick-list">
          {recentKnown.map((r) => (
            <li key={r.sequence_id}>
              <button type="button" className="home-quick-run-btn" disabled={busy}
                onClick={() => void startSequence(r.sequence_id, r.name, false)}>
                <Icon name="bolt" size={18} />
                <span className="home-quick-run-name">{r.name}</span>
                <span className="muted home-quick-run-sub">last ran {fmtAgo(r.last_started_ms)}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="card home-quick-card">
        <strong>Quick actions</strong>
        {sets.length === 0 && <p className="muted">No sets yet.</p>}
        <ul className="home-quick-list">
          {sets.map((s) => {
            const armedForSet = s.id ? arms?.armed.filter((a) => a.set_id === s.id) ?? [] : [];
            const armedOn = new Set(armedForSet.map((a) => a.on));
            return (
              <li key={s.id} className="home-quick-action-row">
                <span className="home-quick-run-name">{s.name}</span>
                <div className="home-quick-action-icons">
                  <button type="button" className="home-quick-icon-btn" disabled={busy || !s.id}
                    title="Fire now" onClick={() => s.id && void fireSet(s.id, s.name)}>
                    <Icon name="bolt" size={18} />
                  </button>
                  <button type="button" className={`home-quick-icon-btn${armedOn.has('scene_change') ? ' armed' : ''}`}
                    disabled={busy || !s.id} title="Arm: next scene change"
                    onClick={() => s.id && void arm(s.id, s.name, 'scene_change')}>
                    <Icon name="rabbit" size={18} />
                  </button>
                  <button type="button" className={`home-quick-icon-btn${armedOn.has('high') ? ' armed' : ''}`}
                    disabled={busy || !s.id} title="Arm: next High Trigger"
                    onClick={() => s.id && void arm(s.id, s.name, 'high')}>
                    <Icon name="arrowUp" size={18} />
                  </button>
                  <button type="button" className={`home-quick-icon-btn${armedOn.has('low') ? ' armed' : ''}`}
                    disabled={busy || !s.id} title="Arm: next Low Trigger"
                    onClick={() => s.id && void arm(s.id, s.name, 'low')}>
                    <Icon name="arrowDown" size={18} />
                  </button>
                </div>
                {armedForSet.map((a) => (
                  <div key={a.id} className="home-quick-armed-tag">
                    <span>Armed for the {triggerLabel(a.on)}</span>
                    <button type="button" onClick={() => void disarm(a.id)}>Cancel</button>
                  </div>
                ))}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
