/** THE LIGHT SHOW's High/Low flags on the Timeline — pure placement and
 * drag arithmetic, kept out of React so scripts/check_show_cue_flags.mjs
 * can drive it with no DOM (the showSummary.ts precedent). */
import type { ShowCue, SongCues } from './types';

export interface CueFlag {
  level: 'high' | 'low';
  ms: number;
  /** where the analysis puts it, drawn faintly when he has moved the flag */
  autoMs: number | null;
  moved: boolean;
  fromDrop: boolean;
  alternates: { ms: number; close: boolean }[];
  title: string;
}

const SNAP_MS = 20;

export function cueFlags(cues: SongCues | null | undefined): CueFlag[] {
  const out: CueFlag[] = [];
  for (const c of [cues?.high, cues?.low]) {
    if (!c) continue;
    out.push(flagOf(c));
  }
  return out;
}

function flagOf(c: ShowCue): CueFlag {
  const name = c.level === 'high' ? 'High Trigger' : 'Low Trigger';
  const why = c.source === 'moved' ? 'moved by you — tap “auto” to put it back'
    : c.source === 'drop_mark' ? 'on your own drop mark'
      : `biggest ${c.level === 'high' ? 'rise' : 'fall'} in section energy`
        + (c.shift !== null ? ` (${c.shift > 0 ? '+' : ''}${c.shift.toFixed(2)})` : '');
  const close = c.runner_up_close ? ' — a runner-up is within 10%; tap a faint dot to move it there' : '';
  return {
    level: c.level,
    ms: c.timestamp_ms,
    autoMs: c.auto_ms,
    moved: c.source === 'moved',
    fromDrop: c.source === 'drop_mark',
    alternates: c.alternates.map((a) => ({ ms: a.timestamp_ms, close: a.close })),
    title: `${name}: ${why}${close}. Drag to move.`,
  };
}

/** Where a drag lands: the pointer's song position, snapped, clamped. */
export function dragMs(clientX: number, rect: { left: number; width: number },
                       durationMs: number): number {
  const dur = Math.max(1, durationMs);
  const ms = ((clientX - rect.left) / Math.max(1, rect.width)) * dur;
  return Math.round(Math.max(0, Math.min(dur, ms)) / SNAP_MS) * SNAP_MS;
}
