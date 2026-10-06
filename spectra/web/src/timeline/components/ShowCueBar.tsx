/** THE LIGHT SHOW's HIGH / LOW TRIGGER FLAGS on the Timeline — one ▲ High
 * and one ▼ Low per song (spectra/services/show_cues.py). Drag a flag to
 * move it; the move is saved for this song and always wins. A moved flag
 * shows "auto" to put it back where the analysis has it. Faint dots are the
 * runners-up: tap one to move the flag there. Nothing here writes a
 * trigger — the cues are derived each play, only his moves are stored. */
import { useRef, useState } from 'react';
import { apiDel, apiPut } from '../../api/client';
import HelpLink from '../../help/HelpLink';
import { cueFlags, dragMs } from '../../lightshow/cueFlags';
import type { SongCues } from '../../lightshow/types';

/** Warm white ▲ High and indigo ▼ Low — kept OFF the phase colours (gold
 * charge, sky-blue lull, magenta drop; timeline/dropSequences.ts
 * PHASE_COLOR). Until 2026-10-06 Low was the lull's own sky blue and High a
 * pink beside the drop's magenta (drop-detection plan, report section 9). */
const COLOR = { high: '#f5f5f4', low: '#818cf8' } as const;

export default function ShowCueBar({ uri, durationMs, cues, onChanged }: {
  uri: string;
  durationMs: number;
  cues: SongCues | null | undefined;
  onChanged: () => void;
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ level: 'high' | 'low'; ms: number } | null>(null);
  const flags = cueFlags(cues);
  const dur = Math.max(1, durationMs);
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (ms / dur) * 100))}%`;

  const save = async (level: 'high' | 'low', ms: number) => {
    await apiPut('/light-show/cues', { uri, level, timestamp_ms: ms }).catch(() => undefined);
    onChanged();
  };
  const revert = async (level: 'high' | 'low') => {
    await apiDel(`/light-show/cues?uri=${encodeURIComponent(uri)}&level=${level}`).catch(() => undefined);
    onChanged();
  };

  const startDrag = (level: 'high' | 'low') => (ev: React.PointerEvent) => {
    if (ev.button !== 0 || !barRef.current) return;
    ev.preventDefault();
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
    const bar = barRef.current;
    let last: number | null = null;
    const move = (e: PointerEvent) => {
      last = dragMs(e.clientX, bar.getBoundingClientRect(), dur);
      setDrag({ level, ms: last });
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      setDrag(null);
      if (last !== null) void save(level, last);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  return (
    <div className="show-cue-bar-row">
      <div ref={barRef} className="show-cue-bar"
        style={{ position: 'relative', height: 22, background: 'var(--surface2)',
                 border: '1px solid var(--border)', borderRadius: 6,
                 userSelect: 'none', touchAction: 'none' }}>
        {flags.map((f) => (
          <span key={f.level}>
            {f.alternates.map((a) => (
              <span key={`${f.level}-alt-${a.ms}`} role="button" tabIndex={0}
                title={`Move the ${f.level === 'high' ? 'High' : 'Low'} Trigger here${a.close ? ' (within 10%)' : ''}`}
                onClick={() => void save(f.level, a.ms)}
                style={{ position: 'absolute', left: pct(a.ms), top: 8, width: 6, height: 6,
                         marginLeft: -3, borderRadius: 3, background: COLOR[f.level],
                         opacity: a.close ? 0.55 : 0.25, cursor: 'pointer' }} />
            ))}
            {f.moved && f.autoMs !== null && (
              <span title="Where the analysis puts it" style={{
                position: 'absolute', left: pct(f.autoMs), top: 2, bottom: 2, width: 0,
                borderLeft: `1px dashed ${COLOR[f.level]}`, opacity: 0.5, pointerEvents: 'none' }} />
            )}
            <span role="slider" aria-label={`${f.level} trigger`} aria-valuenow={f.ms}
              title={f.title} onPointerDown={startDrag(f.level)}
              style={{ position: 'absolute', left: pct(drag?.level === f.level ? drag.ms : f.ms),
                       top: 0, bottom: 0, width: 14, marginLeft: -7, cursor: 'ew-resize',
                       color: COLOR[f.level], fontSize: 13, lineHeight: '20px', textAlign: 'center',
                       fontWeight: f.moved ? 700 : 400, opacity: f.moved || f.fromDrop ? 1 : 0.85 }}>
              {f.level === 'high' ? '▲' : '▼'}
            </span>
          </span>
        ))}
        {!flags.length && (
          <span className="muted" style={{ fontSize: 11, paddingLeft: 6, lineHeight: '20px' }}>
            {cues?.reason ?? 'no High/Low Trigger on this song yet'}
          </span>
        )}
      </div>
      <span className="show-cue-bar-tools">
        {flags.filter((f) => f.moved).map((f) => (
          <button key={f.level} onClick={() => void revert(f.level)}
            title={`Put the ${f.level === 'high' ? 'High' : 'Low'} Trigger back where the analysis has it`}>
            {f.level === 'high' ? '▲' : '▼'} auto
          </button>
        ))}
        <HelpLink topic="show-high-low-triggers" />
      </span>
    </div>
  );
}
