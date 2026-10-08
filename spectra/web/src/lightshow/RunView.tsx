/** THE LIGHT SHOW's phone-first RUN VIEW (phase 3).
 *
 * Built for standing in the room with a phone, not sitting at the Build
 * view: the Holding list is the same `ShowNowPanel`, the armed board is
 * the same `ArmBoard` the Build view shows (one countdown source, never
 * two), and Disarm all / End show are big, always-visible buttons — no
 * editing happens here, only running what the Build view already saved.
 *
 * "Sets — tap to run" is ONE TAP, no menu (his ask, 2026-10-08, verbatim:
 * "make each row instead have buttons for each thing with an icon ...
 * i just tap it and it happens"). Each row shows the set's name plus four
 * icon buttons, each already the complete action for one of the four
 * timings the backend has always supported (`ArmTrigger` =
 * 'scene_change' | 'high' | 'low', plus the separate fire-now call) — no
 * new backend semantics were needed, so there is nothing here to flag as
 * a needs-decision. His own glyph choices: ⚡ bolt = fire now, 🐇 bunny =
 * arm on the next scene change, ▲ up arrow = arm on the next High
 * Trigger, ▼ down arrow = arm on the next Low Trigger — drawn as inline
 * SVG via `iconRegistry.ts` (never a raw Unicode glyph; see that file's
 * own "appears as an X" docstring for why). The previous tap-to-open
 * sheet (name button → a second screen of four labeled buttons → Cancel)
 * is gone; a tap now IS the action. */
import { apiDel, apiPost } from '../api/client';
import Icon from '../components/Icon';
import HelpLink from '../help/HelpLink';
import { ArmBoard } from './ArmBoard';
import { ShowNowPanel } from './LightShowPage';
import { endShowSummary, runSummary, triggerLabel } from './showSummary';
import type { ArmsStatus, ArmTrigger, EndShowReport, ShowRun, ShowSet, ShowStatus } from './types';
import { useState } from 'react';

export default function RunView({ sets, status, arms, onChangeArms, onEndShowDone, toast }: {
  sets: ShowSet[];
  status: ShowStatus | null;
  arms: ArmsStatus | null;
  onChangeArms: () => void;
  onEndShowDone: () => void;
  toast: (msg: string, kind?: 'success' | 'error') => void;
}) {
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
    }
  };

  const arm = async (id: string, on: ArmTrigger) => {
    try {
      await apiPost('/light-show/arms', { set_id: id, on });
      toast(`Armed for the ${triggerLabel(on)}`, 'success');
      onChangeArms();
    } catch (e) {
      toast(String(e), 'error');
    }
  };

  const disarm = async (armId: string) => {
    await apiDel(`/light-show/arms/${armId}`).catch((e) => toast(String(e), 'error'));
    onChangeArms();
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
  const endHold = async (kind: 'pulse-mods' | 'flare-blocks', id: string) => {
    await apiPost(`/light-show/${kind}/${id}/end`).catch((e) => toast(String(e), 'error'));
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

      <ShowNowPanel status={status} onRelease={release} onEndLevel={endLevel} onEndHold={endHold} />

      <div className="card light-show-run-sets">
        <strong>Sets — tap to run</strong> <HelpLink topic="show-sets" />
        {sets.length === 0 && <p className="muted">No sets yet — build one on the Build view.</p>}
        <ul className="light-show-run-set-list">
          {sets.map((s) => {
            const armedForSet = s.id ? arms?.armed.find((a) => a.set_id === s.id) ?? null : null;
            return (
              <li key={s.id} className="light-show-run-set-row">
                <div className="light-show-run-set-main">
                  <span className="light-show-run-set-name">
                    {s.name}
                    {(s.problems?.length ?? 0) > 0 && <span title={s.problems?.join('\n')}> ⚠</span>}
                  </span>
                  <div className="light-show-run-set-actions">
                    <button type="button" className="light-show-run-set-icon-btn fire" disabled={busy || !s.id}
                      title="Fire now" aria-label={`Fire ${s.name} now`} onClick={() => s.id && void fire(s.id)}>
                      <Icon name="bolt" size={22} />
                    </button>
                    <button type="button" className="light-show-run-set-icon-btn" disabled={busy || !s.id}
                      title="Arm: next scene change" aria-label={`Arm ${s.name} for the next scene change`}
                      onClick={() => s.id && void arm(s.id, 'scene_change')}>
                      <Icon name="rabbit" size={22} />
                    </button>
                    <button type="button" className="light-show-run-set-icon-btn" disabled={busy || !s.id}
                      title="Arm: next High Trigger" aria-label={`Arm ${s.name} for the next High Trigger`}
                      onClick={() => s.id && void arm(s.id, 'high')}>
                      <Icon name="arrowUp" size={22} />
                    </button>
                    <button type="button" className="light-show-run-set-icon-btn" disabled={busy || !s.id}
                      title="Arm: next Low Trigger" aria-label={`Arm ${s.name} for the next Low Trigger`}
                      onClick={() => s.id && void arm(s.id, 'low')}>
                      <Icon name="arrowDown" size={22} />
                    </button>
                  </div>
                </div>
                {armedForSet && (
                  <div className="light-show-run-set-armed-tag">
                    <span>⏱ Armed for the {triggerLabel(armedForSet.on)}</span>
                    <button type="button" onClick={() => void disarm(armedForSet.id)}>Cancel</button>
                  </div>
                )}
              </li>
            );
          })}
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
