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
/** Pixel radius (at the drag surface's current scale) within which a drag
 *  snaps to the nearest beat instead of the flat SNAP_MS grid — the same
 *  two-tier convention the canvas trigger editor's own snapTimestamp uses
 *  (canvas/data.ts), so a Light Show flag drag feels as precise as a
 *  SPECTRA trigger drag ("snap-to-beat as the mouse has", the Admiral,
 *  2026-10-08). */
const BEAT_SNAP_PX = 10;

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

/** The pointer's own song position, clamped — UNSNAPPED, so a caller can
 *  compute a stable grab offset (drag start's ms minus this) and keep
 *  applying it on every move, instead of jumping the flag to wherever the
 *  finger lands (a touch rarely lands exactly on the flag's own pixel). */
export function rawMsAt(clientX: number, rect: { left: number; width: number },
                        durationMs: number): number {
  const dur = Math.max(1, durationMs);
  const ms = ((clientX - rect.left) / Math.max(1, rect.width)) * dur;
  return Math.max(0, Math.min(dur, ms));
}

/** Snap a raw drag position to the nearest beat within BEAT_SNAP_PX of
 *  the drag surface's current scale, else the flat SNAP_MS grid. `beats`
 *  absent/empty = grid-only (today's behaviour, unchanged).
 *
 *  `widthPx` is assumed to span `durationMs` — true for the full-song bar
 *  (ShowCueBar.tsx) but NOT for a zoomed canvas view, whose pixel width
 *  spans only the current window. `scaleDurationMs`, when given, is the
 *  span `widthPx` actually covers, used for the snap-radius conversion
 *  only; `durationMs` still governs the clamp (the song's real length). */
export function snapCueMs(rawMs: number, durationMs: number, widthPx: number,
                          beats?: { ms: number }[] | null, scaleDurationMs?: number): number {
  const dur = Math.max(1, durationMs);
  const clamped = Math.max(0, Math.min(dur, rawMs));
  if (beats?.length) {
    const scaleDur = Math.max(1, scaleDurationMs ?? dur);
    const radiusMs = (BEAT_SNAP_PX / Math.max(1, widthPx)) * scaleDur;
    let best: number | null = null;
    let bestD = radiusMs;
    for (const b of beats) {
      const d = Math.abs(b.ms - clamped);
      if (d < bestD) { bestD = d; best = b.ms; }
    }
    if (best !== null) return Math.round(best);
  }
  return Math.round(clamped / SNAP_MS) * SNAP_MS;
}

/** Where a plain (no grab-offset) drag lands: the pointer's song
 *  position, beat-or-grid snapped, clamped. */
export function dragMs(clientX: number, rect: { left: number; width: number },
                       durationMs: number, beats?: { ms: number }[] | null): number {
  return snapCueMs(rawMsAt(clientX, rect, durationMs), durationMs, rect.width, beats);
}
