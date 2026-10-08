/** THE LIGHT SHOW's HIGH / LOW TRIGGER FLAGS on the Timeline — one ▲ High
 * and one ▼ Low per song (spectra/services/show_cues.py). Drag a flag to
 * move it; the move is saved for this song and always wins. A moved flag
 * shows "auto" to put it back where the analysis has it. Faint dots are the
 * runners-up: tap one to move the flag there. Nothing here writes a
 * trigger — the cues are derived each play, only his moves are stored.
 *
 * ARMED STATE (2026-10-06, the Admiral: "I also want to see a marker
 * showing where the light show triggers are, even if they aren't
 * active") — a flag is drawn here REGARDLESS of whether anything is
 * armed on it (that part was already true); it is now also drawn SOLID,
 * with a ring, when an action set is currently armed to fire on it, and
 * muted/outlined otherwise — see ../lightShowMarkers.ts for the exact
 * armed-matching rule (the same one the audio-shape canvas's own light-
 * show layer uses, ./lightShowLayer.ts).
 *
 * TOUCH PRECISION (2026-10-08, the Admiral: "I'm having trouble precisely
 * moving the trigger on the large bar") — three fixes: (1) the drag grabs
 * wherever the finger actually lands and keeps that offset for the whole
 * gesture (cueFlags.rawMsAt), instead of snapping the flag to the raw
 * pointer position on the very first move; (2) the pointer-capturing hit
 * target (`.show-cue-bar-handle`) is wider than the drawn glyph — a bigger
 * invisible touch zone around the same visible ▲/▼, the CIRCLE_HIT_R
 * convention one surface over; (3) a drag now snaps to the nearest beat
 * first (cueFlags.snapCueMs), falling back to the flat 20ms grid, and a
 * live mm:ss readout plus ←/→ keyboard nudge (Shift = finer) give a
 * fine-adjust path a finger alone can't. */
import { useRef, useState } from 'react';
import { apiDel, apiPut } from '../../api/client';
import HelpLink from '../../help/HelpLink';
import { cueFlags, rawMsAt, snapCueMs } from '../../lightshow/cueFlags';
import { mmss } from '../../lightshow/showSummary';
import type { ArmsStatus, SongCues } from '../../lightshow/types';
import { LIGHT_SHOW_COLOR as COLOR, armAppliesToCue } from '../lightShowMarkers';

/** ←/→ nudge step; Shift = the fine step — mirrors dropEdit.ts's own
 *  NUDGE_MS convention for a keyboard fine-adjust. */
const NUDGE_MS = 20;
const FINE_NUDGE_MS = 5;

export default function ShowCueBar({ uri, durationMs, cues, arms, beats, onChanged }: {
  uri: string;
  durationMs: number;
  cues: SongCues | null | undefined;
  arms: ArmsStatus | null | undefined;
  /** song-time beats, for the drag's own beat-snap — absent = grid-only. */
  beats?: { ms: number }[] | null;
  onChanged: () => void;
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ level: 'high' | 'low'; ms: number } | null>(null);
  const flags = cueFlags(cues);
  const dur = Math.max(1, durationMs);
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (ms / dur) * 100))}%`;
  const armedFor = (level: 'high' | 'low') =>
    (arms?.armed ?? []).filter((a) => armAppliesToCue(a, level, uri));

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
    ev.stopPropagation();
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
    const bar = barRef.current;
    const flag = flags.find((f) => f.level === level);
    const startMs = flag?.ms ?? 0;
    // The grab offset: where the finger landed vs. the flag's own current
    // position — kept constant for the whole drag so the flag never jumps
    // to the raw touch point on the first move.
    const grabMs = startMs - rawMsAt(ev.clientX, bar.getBoundingClientRect(), dur);
    let last: number | null = null;
    const move = (e: PointerEvent) => {
      const rect = bar.getBoundingClientRect();
      const raw = rawMsAt(e.clientX, rect, dur) + grabMs;
      last = snapCueMs(raw, dur, rect.width, beats);
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

  const nudge = (level: 'high' | 'low', flagMs: number) => (ev: React.KeyboardEvent) => {
    if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
    ev.preventDefault();
    const step = (ev.shiftKey ? FINE_NUDGE_MS : NUDGE_MS) * (ev.key === 'ArrowLeft' ? -1 : 1);
    void save(level, Math.max(0, Math.min(dur, flagMs + step)));
  };

  return (
    <div className="show-cue-bar-row">
      <div ref={barRef} className="show-cue-bar"
        style={{ position: 'relative', height: 22, background: 'var(--surface2)',
                 border: '1px solid var(--border)', borderRadius: 6,
                 userSelect: 'none', touchAction: 'none' }}>
        {flags.map((f) => {
          const armed = armedFor(f.level);
          const isArmed = armed.length > 0;
          const title = isArmed
            ? `${f.title} Armed: ${armed.map((a) => a.label || 'an action').join(', ')} — fires here.`
            : `${f.title} Nothing armed on it.`;
          return (
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
              <span role="slider" aria-label={`${f.level} trigger${isArmed ? ' — armed' : ''}`}
                aria-valuenow={f.ms} tabIndex={0}
                title={title} onPointerDown={startDrag(f.level)} onKeyDown={nudge(f.level, f.ms)}
                className="show-cue-bar-handle"
                style={{ position: 'absolute', left: pct(drag?.level === f.level ? drag.ms : f.ms),
                         top: 0, bottom: 0,
                         // A touch-sized grab zone (wider than the drawn glyph —
                         // the CIRCLE_HIT_R convention one surface over) centred
                         // on the same visible ▲/▼; the glyph's own size/position
                         // is unchanged (lineHeight centres it within the box).
                         width: 32, marginLeft: -16, cursor: 'ew-resize',
                         color: COLOR[f.level], fontSize: 13, lineHeight: '20px', textAlign: 'center',
                         fontWeight: f.moved || isArmed ? 700 : 400,
                         opacity: isArmed ? 1 : (f.moved || f.fromDrop ? 0.85 : 0.6),
                         textShadow: isArmed ? `0 0 5px ${COLOR[f.level]}` : 'none',
                         borderRadius: 7, touchAction: 'none',
                         boxShadow: isArmed ? `0 0 0 1.5px ${COLOR[f.level]}66` : 'none' }}>
                {f.level === 'high' ? '▲' : '▼'}
              </span>
              {drag?.level === f.level && (
                <span style={{ position: 'absolute', left: pct(drag.ms), bottom: '100%',
                               transform: 'translate(-50%, -2px)', background: 'rgba(0,0,0,0.85)',
                               color: '#fff', fontSize: 11, padding: '2px 6px', borderRadius: 4,
                               whiteSpace: 'nowrap', pointerEvents: 'none', zIndex: 5 }}>
                  {mmss(drag.ms)}
                </span>
              )}
            </span>
          );
        })}
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
