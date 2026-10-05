/** THE LIGHT SHOW's ARMED BOARD and ARM CONTROL (phase 2).
 *
 * The board lists every set waiting for its trigger — with a countdown when
 * its High/Low is ahead on this song, and the reason when it waited out a
 * trigger because the room was not SPECTRA's — plus this song's High and
 * Low and what recently fired, missed or expired. The control arms the set
 * being edited. What an arm does is the server's business
 * (spectra/services/show_arms.py); this page only shows it. */
import { useState } from 'react';
import { apiDel, apiPost } from '../api/client';
import HelpLink from '../help/HelpLink';
import { armHistoryLine, armLine, cueLine, TRIGGER_LABEL } from './showSummary';
import type { ArmsStatus, ArmTrigger } from './types';

export function ArmBoard({ arms, onChange, toast }: {
  arms: ArmsStatus | null;
  onChange: () => void;
  toast: (msg: string, kind?: 'success' | 'error') => void;
}) {
  if (!arms) return null;
  const pos = arms.song.position_ms;
  const cues = arms.song.cues;
  const disarm = async (id: string) => {
    await apiDel(`/light-show/arms/${id}`).catch((e) => toast(String(e), 'error'));
    onChange();
  };
  const disarmAll = async () => {
    await apiPost('/light-show/arms/disarm-all').catch((e) => toast(String(e), 'error'));
    onChange();
  };
  return (
    <div className="card light-show-armed">
      <div className="light-show-armed-head">
        <strong>Armed</strong> <HelpLink topic="show-arming" />
        {arms.armed.length > 1 && <button className="danger" onClick={() => void disarmAll()}>Disarm all</button>}
      </div>
      {arms.song.uri && (
        <p className="light-show-cues">
          <span>▲ High: {cueLine(cues?.high ?? null, pos)}</span>
          <span>▼ Low: {cueLine(cues?.low ?? null, pos)}</span>
          {cues?.reason && <span className="muted">{cues.reason}</span>}
          <HelpLink topic="show-high-low-triggers" />
        </p>
      )}
      {arms.armed.length === 0 && <p className="muted">Nothing armed.</p>}
      <ul>
        {arms.armed.map((a) => (
          <li key={a.id} className={a.last_outcome?.status === 'waiting' ? 'waiting' : ''}>
            <span>{armLine(a, pos)}</span>
            <button onClick={() => void disarm(a.id)}>Disarm</button>
          </li>
        ))}
      </ul>
      {arms.refusal && arms.armed.length > 0 && (
        <p className="muted">Armed sets wait while: {arms.refusal}</p>
      )}
      {arms.history.length > 0 && (
        <details>
          <summary className="muted">Recent ({arms.history.length})</summary>
          <ul className="muted">
            {arms.history.slice(0, 10).map((a) => <li key={a.id}>{armHistoryLine(a)}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}

export function ArmControl({ setId, disabled, onArmed, toast }: {
  setId: string | undefined;
  disabled: boolean;
  onArmed: () => void;
  toast: (msg: string, kind?: 'success' | 'error') => void;
}) {
  const [on, setOn] = useState<ArmTrigger>('high');
  const [repeat, setRepeat] = useState(false);
  const [thisSong, setThisSong] = useState(false);
  const [finish, setFinish] = useState(true);
  const arm = async () => {
    if (!setId) return;
    try {
      const r = await apiPost<{ label: string; refusal: string | null; lead_ms: number }>('/light-show/arms', {
        set_id: setId, on, repeat, this_song_only: thisSong, finish_on_mark: finish,
      });
      toast(`Armed ${r.label} for the ${TRIGGER_LABEL[on]}`
        + (r.refusal ? ` — it will wait: ${r.refusal}` : ''), 'success');
      onArmed();
    } catch (e) {
      toast(String(e), 'error');
    }
  };
  return (
    <div className="light-show-arm">
      <select value={on} aria-label="Arm on" onChange={(e) => setOn(e.target.value as ArmTrigger)}>
        {(Object.keys(TRIGGER_LABEL) as ArmTrigger[]).map((k) => (
          <option key={k} value={k}>{TRIGGER_LABEL[k]}</option>
        ))}
      </select>
      <label title="Stay armed after firing, and fire again every time"><input type="checkbox"
        checked={repeat} onChange={(e) => setRepeat(e.target.checked)} /> repeat</label>
      <label title="Only on the song playing now — otherwise it carries to the next song"><input
        type="checkbox" checked={thisSong} onChange={(e) => setThisSong(e.target.checked)} /> this song only</label>
      {on !== 'scene_change' && (
        <label title="Start early so this set's fades complete ON the trigger"><input type="checkbox"
          checked={finish} onChange={(e) => setFinish(e.target.checked)} /> finish on the mark</label>
      )}
      <button disabled={disabled || !setId} onClick={() => void arm()}>⏱ Arm</button>
      <HelpLink topic="show-arming" />
    </div>
  );
}
