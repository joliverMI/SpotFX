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
