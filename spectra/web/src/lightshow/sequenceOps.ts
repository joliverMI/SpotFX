/** Pure helpers for the Sequence tab (SequenceView.tsx), kept DOM-free so
 * scripts/check_show_sequence_ui.mjs can drive them directly. */
import type { SequenceArm, SequenceItem, SequenceWait, WaitKind } from './types';

export const ARM_ORDER: SequenceArm[] = ['instant', 'scene_change', 'high', 'low'];

/** The four arming icons — the same glyphs as the Run view's one-tap row. */
export const ARM_ICON: Record<SequenceArm, 'bolt' | 'rabbit' | 'arrowUp' | 'arrowDown'> = {
  instant: 'bolt', scene_change: 'rabbit', high: 'arrowUp', low: 'arrowDown',
};

export const ARM_LABEL: Record<SequenceArm, string> = {
  instant: 'Instant — fires as soon as it is its turn',
  scene_change: 'Next scene change',
  high: 'Next High Trigger',
  low: 'Next Low Trigger',
};

export const WAIT_LABEL: Record<WaitKind, string> = {
  duration: 'A fixed time',
  trigger_count: 'A number of triggers',
  songs: 'A number of songs',
  song_list: 'One of these songs',
};

export function newItemId(): string {
  return Math.random().toString(16).slice(2, 14);
}

export function defaultWait(kind: WaitKind = 'duration'): SequenceWait {
  return { kind, seconds: 60, trigger: 'scene_change', count: 1, songs: [] };
}

export function newSetItem(setId: string | null = null): SequenceItem {
  return { id: newItemId(), kind: 'set', set_id: setId, arm: 'instant' };
}

export function newWaitItem(): SequenceItem {
  return { id: newItemId(), kind: 'wait', arm: 'instant', wait: defaultWait() };
}

/** Move the item at `from` so it lands at `to` (a drag's drop, or ↑/↓). */
export function reorder<T>(list: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || from >= list.length) return list.slice();
  const out = list.slice();
  const [moved] = out.splice(from, 1);
  out.splice(Math.max(0, Math.min(out.length, to)), 0, moved);
  return out;
}

/** "<name> copy", or "<name> copy 2"… if taken (the server makes the real
 * copy; this is only used to predict the name for a toast). */
export function copyName(name: string, existing: string[]): string {
  const taken = new Set(existing.map((n) => n.trim().toLowerCase()));
  let out = `${name} copy`;
  for (let n = 2; taken.has(out.trim().toLowerCase()); n++) out = `${name} copy ${n}`;
  return out;
}

/** Seconds → "m:ss" (or "h:mm:ss"). */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
    : `${m}:${String(ss).padStart(2, '0')}`;
}

/** Where each item stands in a run: done, current or upcoming. */
export function itemPhase(index: number, current: number, active: boolean): 'done' | 'current' | 'upcoming' {
  if (index < current) return 'done';
  if (index === current && active) return 'current';
  return index === current ? 'done' : 'upcoming';
}

/** Where the row dragged from `from` lands when released at `y`: the
 * insertion point is how many rows' midpoints lie above `y`, then shifted
 * for the dragged row's own removal — the final index `reorder` takes. */
export function dropIndex(y: number, rows: { top: number; bottom: number }[], from: number): number {
  let ins = 0;
  for (const r of rows) if (y > (r.top + r.bottom) / 2) ins++;
  return ins > from ? ins - 1 : ins;
}

const LOG_WORDS: Record<string, string> = {
  started: 'Started', entered: 'Now on', completed: 'Done', counted: 'Counted',
  paused: 'Paused', resumed: 'Resumed', stopped: 'Stopped', skipped: 'Skipped',
  stepped_back: 'Stepped back', looped: 'Looped', finished: 'Finished',
};

export function logLine(e: { what: string; item: string; detail: string }): string {
  const word = LOG_WORDS[e.what] ?? e.what;
  return [word, e.item, e.detail].filter(Boolean).join(' · ');
}
