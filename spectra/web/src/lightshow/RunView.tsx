/** THE LIGHT SHOW's phone-first RUN VIEW (phase 3).
 *
 * Built for standing in the room with a phone, not sitting at the Build
 * view: a tap opens one set's three big actions (Fire now / Arm on scene
 * change / Arm on High / Arm on Low), the armed board is the same
 * `ArmBoard` the Build view shows (one countdown source, never two), the
 * Holding list is the same `ShowNowPanel`, and Disarm all / End show are
 * big, always-visible buttons — no editing happens here, only running
 * what the Build view already saved.
 */
import { useState } from 'react';
import { apiPost } from '../api/client';
import HelpLink from '../help/HelpLink';
import { ArmBoard } from './ArmBoard';
import { ShowNowPanel } from './LightShowPage';
import { endShowSummary, runSummary } from './showSummary';
import type { ArmsStatus, ArmTrigger, EndShowReport, ShowRun, ShowSet, ShowStatus } from './types';

export default function RunView({ sets, status, arms, onChangeArms, onEndShowDone, toast }: {
  sets: ShowSet[];
  status: ShowStatus | null;
  arms: ArmsStatus | null;
  onChangeArms: () => void;
  onEndShowDone: () => void;
  toast: (msg: string, kind?: 'success' | 'error') => void;
}) {
  const [openSet, setOpenSet] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastRun, setLastRun] = useState<ShowRun | null>(null);

  const fire = async (id: string) => {
    setBusy(true);
    try {
      const run = await apiPost<ShowRun>(`/light-show/sets/${id}/fire`);
      setLastRun(run);
      toast(runSummary(run), run.state === 'done' || run.state === 'running' ? 'success' : 'error');
    } catch (e) {
      toast(String(e), 'error');
    } finally {
      setBusy(false);
      setOpenSet(null);
    }
  };

  const arm = async (id: string, on: ArmTrigger) => {
    try {
      await apiPost('/light-show/arms', { set_id: id, on });
      toast(`Armed for the ${on === 'scene_change' ? 'next scene change'
        : on === 'high' ? 'next High Trigger' : 'next Low Trigger'}`, 'success');
      onChangeArms();
    } catch (e) {
      toast(String(e), 'error');
    } finally {
      setOpenSet(null);
    }
  };

  const disarmAll = async () => {
    await apiPost('/light-show/arms/disarm-all').catch((e) => toast(String(e), 'error'));
    onChangeArms();
  };

  const endShow = async () => {
    setBusy(true);
    try {
      const r = await apiPost<EndShowReport>('/light-show/end');
      toast(endShowSummary(r), r.failed.length ? 'error' : 'success');
      onEndShowDone();
    } catch (e) {
      toast(String(e), 'error');
    } finally {
      setBusy(false);
    }
  };

  const release = async (device: string) => {
    await apiPost(`/light-show/release/${encodeURIComponent(device)}`).catch((e) => toast(String(e), 'error'));
  };
  const endLevel = async (id: string) => {
    await apiPost(`/light-show/levels/${id}/end`).catch((e) => toast(String(e), 'error'));
  };

  const gate = status?.output.refusal ?? status?.output.standdown ?? null;

  return (
    <div className="light-show-run-view">
      {gate && <div className="light-show-gate" role="status">⏸ Standing down: {gate}</div>}

      <div className="light-show-run-controls">
        <button className="danger big" disabled={busy || !arms?.armed.length} onClick={() => void disarmAll()}>
          Disarm all
        </button>
        <button className="danger big" disabled={busy} onClick={() => void endShow()}>
          End show
        </button>
        <HelpLink topic="show-end-restore" />
      </div>

      <ArmBoard arms={arms} onChange={onChangeArms} toast={toast} />

      <ShowNowPanel status={status} onRelease={release} onEndLevel={endLevel} />

      <div className="card light-show-run-sets">
        <strong>Sets — tap to run</strong> <HelpLink topic="show-sets" />
        {sets.length === 0 && <p className="muted">No sets yet — build one on the Build view.</p>}
        <ul className="light-show-run-set-list">
          {sets.map((s) => (
            <li key={s.id}>
              <button className="big light-show-run-set-button" disabled={busy}
                onClick={() => setOpenSet(openSet === s.id ? null : (s.id ?? null))}>
                {s.name}
                {(s.problems?.length ?? 0) > 0 && <span title={s.problems?.join('\n')}> ⚠</span>}
              </button>
              {openSet === s.id && s.id && (
                <div className="light-show-run-sheet">
                  <button className="primary big" disabled={busy} onClick={() => void fire(s.id!)}>
                    ▶ Fire now
                  </button>
                  <button className="big" disabled={busy} onClick={() => void arm(s.id!, 'scene_change')}>
                    ⏱ Arm: next scene change
                  </button>
                  <button className="big" disabled={busy} onClick={() => void arm(s.id!, 'high')}>
                    ⏱ Arm: High Trigger
                  </button>
                  <button className="big" disabled={busy} onClick={() => void arm(s.id!, 'low')}>
                    ⏱ Arm: Low Trigger
                  </button>
                  <button onClick={() => setOpenSet(null)}>Cancel</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>

      {lastRun && (
        <div className="card light-show-run">
          <strong>{runSummary(lastRun)}</strong>
        </div>
      )}
    </div>
  );
}
