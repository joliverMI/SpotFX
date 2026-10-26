/** Home's quick-run cards (song-layout-plan, data/ui-layout-plan/
 * report.md §5): "Quick sequences" (his recent sequences, one tap to
 * run) and "Quick actions" (his sets, the Run view's own one-tap icons
 * ⚡🐇▲▼ plus its one phase-cycle button) side by side, capped width on
 * desktop/tablet — never full width. Deliberately self-contained rather
 * than literally extracting `QuickStartCard`/`SetRunRows` out of the
 * Light Show page's own `SequenceView.tsx`/`RunView.tsx` (the report's
 * own suggested names): those two files are large, stateful, and not
 * otherwise part of this slice's surface, so duplicating the small,
 * read-mostly bits here keeps this change's conflict surface small. A
 * later pass can extract the two shared components properly, which would
 * let the Light Show page's own Run view and this one share one
 * implementation. */
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { apiDel, apiGet, apiPost } from '../api/client';
import Icon from '../components/Icon';
import { cycleActions, phaseButtonLook } from '../lightshow/phaseArmCycle';
import { TRIGGER_LABEL } from '../lightshow/showSummary';
import type {
  ArmsStatus, ArmTrigger, RecentSequenceRun, SequenceRun, ShowRun, ShowSequence, ShowSet,
} from '../lightshow/types';

function fmtAgo(ms: number): string {
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/** The Light Show's own wording, so Home and the Run view can never
 * disagree about what an arm is waiting for (it carries the three phase
 * triggers too since 2026-10-19). */
const triggerLabel = (t: ArmTrigger | string): string => (
  TRIGGER_LABEL[t as ArmTrigger] ?? String(t)
);

/** `children` land as more cards in the same grid — Home's Drops panel
 * (./HomeDrops.tsx, predrop plan step 1), "beside Quick actions with the
 * same shape". */
export default function HomeQuickRuns({ children }: { children?: ReactNode }) {
  const [sequences, setSequences] = useState<ShowSequence[]>([]);
  const [recent, setRecent] = useState<RecentSequenceRun[]>([]);
  const [sets, setSets] = useState<ShowSet[]>([]);
  const [arms, setArms] = useState<ArmsStatus | null>(null);
  const [run, setRun] = useState<SequenceRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const reloadArms = useCallback(() => void apiGet<ArmsStatus>('/light-show/arms').then(setArms).catch(() => undefined), []);
  useEffect(() => {
    void apiGet<{ sequences: ShowSequence[] }>('/light-show/sequences').then((r) => setSequences(r.sequences)).catch(() => undefined);
    void apiGet<{ recent: RecentSequenceRun[] }>('/light-show/sequences/recent').then((r) => setRecent(r.recent)).catch(() => undefined);
    void apiGet<{ sets: ShowSet[] }>('/light-show/sets').then((r) => setSets(r.sets)).catch(() => undefined);
    void apiGet<{ run: SequenceRun | null }>('/light-show/sequence-run').then((r) => setRun(r.run)).catch(() => undefined);
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

  /** The one phase button's tap — ../lightshow/phaseArmCycle.ts owns the
   * rule (cancel this set's current phase arm first, then arm the next,
   * or nothing when the cycle comes back to off). */
  const cyclePhase = async (s: ShowSet, setArms: ArmsStatus['armed']) => {
    const { disarmIds, arm: next } = cycleActions(setArms);
    try {
      // Each disarm is BEST EFFORT: the common failure is a 404 for an
      // arm that already fired, which has achieved what the cancel
      // wanted anyway. Nothing is stranded by a real failure either —
      // `cycleActions` cancels EVERY phase arm on the set, so the next
      // tap clears whatever this one left behind.
      for (const id of disarmIds) {
        await apiDel(`/light-show/arms/${id}`).catch(() => undefined);
      }
      if (next) {
        await apiPost('/light-show/arms', { set_id: s.id, on: next });
        setToast(`Armed "${s.name}" for the ${triggerLabel(next)}`);
      } else {
        setToast(`"${s.name}" is no longer armed on a drop, lull or charge`);
      }
    } catch (e) {
      setToast(String(e));
    }
    reloadArms();
  };

  return (
    <div className="home-quick-runs">
      {toast && <div className="home-quick-toast" role="status">{toast}</div>}
      <div className="card home-quick-card">
        {/* THE MOCKUP'S OWN CARD (audit H6): a small-caps title with the
          * sparkle glyph; each row the name, "last ran 6m ago · 5 items",
          * and a big purple ▶ circle; then a "Running: … item 3 of 5"
          * line with segment progress. The live build was a plain title
          * over flat bolt-glyph buttons with no ▶, no item count and no
          * running line. */}
        <div className="home-quick-title"><Icon name="spark" size={14} /> Quick sequences</div>
        {recentKnown.length === 0 && <p className="muted">No sequences run yet.</p>}
        <ul className="home-quick-list">
          {recentKnown.map((r) => {
            const seq = sequences.find((q) => q.id === r.sequence_id);
            const count = seq?.items?.length ?? null;
            return (
              <li key={r.sequence_id}>
                <button type="button" className="home-quick-seq-row" disabled={busy}
                  title={`Start "${r.name}"`}
                  onClick={() => void startSequence(r.sequence_id, r.name, false)}>
                  <span className="home-quick-seq-text">
                    <b>{r.name}</b>
                    <span className="muted">
                      last ran {fmtAgo(r.last_started_ms)}
                      {count != null && ` · ${count} item${count === 1 ? '' : 's'}`}
                    </span>
                  </span>
                  <span className="home-quick-play" aria-hidden>
                    <Icon name="play" size={14} />
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        {run?.active && (
          <>
            <div className="home-quick-running">
              Running: <b>{run.name}</b>
              {run.items.length > 0 && ` · item ${run.index + 1} of ${run.items.length}`}
            </div>
            <div className="home-quick-seqdots" aria-hidden>
              {run.items.map((_, i) => (
                <i key={i}
                  className={i < run.index ? 'done' : i === run.index ? 'now' : undefined} />
              ))}
            </div>
          </>
        )}
      </div>

      <div className="card home-quick-card">
        <div className="home-quick-title"><Icon name="bolt" size={14} /> Quick actions</div>
        {sets.length === 0 && <p className="muted">No sets yet.</p>}
        <ul className="home-quick-list">
          {sets.map((s) => {
            const armedForSet = s.id ? arms?.armed.filter((a) => a.set_id === s.id) ?? [] : [];
            const armedOn = new Set(armedForSet.map((a) => a.on));
            const phase = phaseButtonLook(armedForSet, s.name, arms?.song.phases);
            return (
              <li key={s.id} className="home-quick-action-row">
                <b className="home-quick-action-name">{s.name}</b>
                <button type="button" className="home-quick-icon-btn home-quick-icon-fire"
                  disabled={busy || !s.id}
                  title="Fire now" aria-label={`Fire "${s.name}" now`}
                  onClick={() => s.id && void fireSet(s.id, s.name)}>
                  <Icon name="bolt" size={15} />
                </button>
                <button type="button" className={`home-quick-icon-btn${armedOn.has('scene_change') ? ' armed' : ''}`}
                  disabled={busy || !s.id} title="Arm: next scene change"
                  aria-label={`Arm "${s.name}" for the next scene change`}
                  onClick={() => s.id && void arm(s.id, s.name, 'scene_change')}>
                  <Icon name="rabbit" size={15} />
                </button>
                <button type="button" className={`home-quick-icon-btn${armedOn.has('high') ? ' armed' : ''}`}
                  disabled={busy || !s.id} title="Arm: next High Trigger"
                  aria-label={`Arm "${s.name}" for the next High Trigger`}
                  onClick={() => s.id && void arm(s.id, s.name, 'high')}>
                  <Icon name="arrowUp" size={15} />
                </button>
                <button type="button" className={`home-quick-icon-btn${armedOn.has('low') ? ' armed' : ''}`}
                  disabled={busy || !s.id} title="Arm: next Low Trigger"
                  aria-label={`Arm "${s.name}" for the next Low Trigger`}
                  onClick={() => s.id && void arm(s.id, s.name, 'low')}>
                  <Icon name="arrowDown" size={15} />
                </button>
                <button type="button" className={`home-quick-icon-btn phase${phase.phase ? ' armed' : ''}`}
                  disabled={busy || !s.id} aria-pressed={phase.phase !== null}
                  style={phase.color ? { color: phase.color, borderColor: phase.color } : undefined}
                  data-phase={phase.phase ?? 'off'}
                  title={phase.title} aria-label={phase.ariaLabel}
                  onClick={() => s.id && void cyclePhase(s, armedForSet)}>
                  <Icon name={phase.icon} size={15} />
                </button>
                {armedForSet.map((a) => (
                  <span key={a.id} className="home-quick-armed-tag">
                    Armed for the {triggerLabel(a.on)}
                    <button type="button" onClick={() => void disarm(a.id)}>Cancel</button>
                  </span>
                ))}
              </li>
            );
          })}
        </ul>
      </div>
      {children}
    </div>
  );
}
