/** What each matched word would do, pure parts (spectra/services/lyric_events.py
 * is the server half and says the rules; the same plan drives the show). Every
 * chip is placed through lyricsLane's layoutLabelRows, so it sits under the word
 * it belongs to at any zoom. */
import type { LyricEventAction } from '../types';
import { inView, layoutLabelRows } from './lyricsLane';
import type { LabelPlacement, LaneView } from './lyricsLane';

export const ACTION_ROWS = 2;

export const ENERGY_CUTOFF = { min: 0, max: 1, step: 0.05 };
export const MIN_GAP_S = { min: 0, max: 30, step: 0.5 };
export const IMPRINT_WINDOW_S = { min: 0, max: 5, step: 0.25 };

const EVENT_WORDS: Record<string, string> = { drop: 'drop', scene: 'scene', flare: 'flare' };

/** What a chip prints. */
export function actionChipText(action: LyricEventAction): string {
  if (action.verdict === 'imprint' && action.event) {
    return `${action.phrase} → ${EVENT_WORDS[action.event.kind] ?? action.event.kind}`;
  }
  if (action.verdict === 'fire') {
    return `${action.phrase} · ${action.momentary ? 'momentary' : 'held'}`;
  }
  return action.phrase;
}

/** Which marks show first when a lane is crowded: what will really happen comes
 * before a word that will do nothing. */
function rank(action: LyricEventAction): number {
  return (action.verdict === 'nothing' ? 0 : 2) + action.strength;
}

export interface ShownAction {
  action: LyricEventAction;
  placement: LabelPlacement | null;
}

export function layoutActions(actions: LyricEventAction[], view: LaneView,
                              laneWidthPx: number): ShownAction[] {
  const shown = actions.filter((a) => inView(view, a.ms, a.end_ms));
  const span = Math.max(1, view.endMs - view.startMs);
  const placements = layoutLabelRows(
    shown.map((a) => ({
      xPx: ((Math.max(a.ms, view.startMs) - view.startMs) / span) * laneWidthPx,
      text: actionChipText(a),
      score: rank(a),
    })),
    laneWidthPx, ACTION_ROWS,
  );
  return shown.map((action, i) => ({ action, placement: placements[i] }));
}

/** The line above the chips: how many words do what. */
export function summaryWords(actions: LyricEventAction[]): string {
  const count = (verdict: LyricEventAction['verdict']) =>
    actions.filter((a) => a.verdict === verdict).length;
  const words = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  return [
    words(count('fire'), 'word fires alone', 'words fire alone'),
    words(count('imprint'), 'word imprints', 'words imprint'),
    words(count('nothing'), 'word does nothing', 'words do nothing'),
  ].join(', ');
}

/** The set the word would reach, as far as it can be known ahead of the song. */
export function reachWords(action: LyricEventAction): string {
  if (!action.set_names.length) return 'No colour set.';
  return `Colour from: ${action.set_names.join(', ')}`;
}

/** THE WORD EVENTS ROW (2026-11-12, data/word-effect-highlight-options): the
 * engine's own events a matched word reaches — drawn as their kind, with a
 * halo in the word's colour when a word imprints on one — plus a diamond
 * for every word firing alone. One row per distinct event (two words can
 * name the same event: the one that imprints wins the halo). Replaces the
 * Test Bed's two "His ..." rows, which drew a different mark set from the
 * events the plan can reach (his answer to decision 5). Pure. */
export interface WordEvent {
  id: string;
  kind: 'drop' | 'scene' | 'flare' | 'word';
  ms: number;
  label: string;
  /** set when a word gives this event its colour (or this IS a word) */
  word: string | null;
  swatch: string | null;
  imprinted: boolean;
  /** an event that cannot carry colour, and why */
  cannot: string | null;
}

export function wordEvents(actions: LyricEventAction[]): WordEvent[] {
  const byId = new Map<string, WordEvent>();
  for (const a of actions) {
    if (a.verdict === 'fire') {
      byId.set(`lyric:${a.key}`, {
        id: `lyric:${a.key}`, kind: 'word', ms: a.ms, label: `“${a.phrase}” fires alone`,
        word: a.phrase, swatch: a.swatch, imprinted: false, cannot: null,
      });
      continue;
    }
    const ev = a.event;
    if (!ev) continue;
    const prior = byId.get(ev.id);
    if (prior?.imprinted) continue;
    const imprinted = a.verdict === 'imprint';
    byId.set(ev.id, {
      id: ev.id, kind: ev.kind, ms: ev.ms, label: ev.label,
      word: imprinted ? a.phrase : null, swatch: imprinted ? a.swatch : null, imprinted,
      cannot: ev.can_carry ? null : (ev.why_not ?? 'cannot carry colour'),
    });
  }
  return [...byId.values()].sort((a, b) => a.ms - b.ms);
}

/** The tooltip for one event on the row. */
export function wordEventText(e: WordEvent, fmt: (ms: number) => string): string {
  const where = `${fmt(e.ms)} · ${e.label}`;
  if (e.kind === 'word') return where;
  if (e.imprinted && e.word) return `${where} — gets the colour of “${e.word}”`;
  if (e.cannot) return `${where} — cannot carry colour (${e.cannot})`;
  return `${where} — a word is near it but does nothing here`;
}
