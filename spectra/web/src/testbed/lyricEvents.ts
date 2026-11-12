/** What each matched word would do, pure parts (spectra/services/lyric_events.py
 * is the server half and says the rules; the same plan drives the show). Every
 * chip is placed through lyricsLane's layoutLabelRows, so it sits under the word
 * it belongs to at any zoom. */
import type { LyricEventAction, LyricPin, LyricRoll } from '../types';
import { inView, layoutLabelRows } from './lyricsLane';
import type { LabelPlacement, LaneView } from './lyricsLane';

export const ACTION_ROWS = 2;

export const ENERGY_CUTOFF = { min: 0, max: 1, step: 0.05 };
export const MIN_GAP_S = { min: 0, max: 30, step: 0.5 };
export const IMPRINT_WINDOW_S = { min: 0, max: 5, step: 0.25 };

const EVENT_WORDS: Record<string, string> = { drop: 'drop', scene: 'scene', flare: 'flare' };

/** A share of plays as a page prints it. */
export function percentWords(chance: number | null): string {
  return chance == null ? '–' : `${Math.round(chance * 100)}%`;
}

/** The small chance a chip carries (THE ROLL, lyric_events.py): only for a
 * word that does not play every time. */
export function chanceTag(action: Pick<LyricEventAction, 'chance' | 'pin'>): string | null {
  if (action.pin === 'never') return 'never';
  if (action.chance == null || action.chance >= 1) return null;
  return percentWords(action.chance);
}

/** A word sitting out this play: rolled, and it did not come up. */
export function satOut(action: Pick<LyricEventAction, 'why'>): boolean {
  return action.why === 'sat_out';
}

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

/** Which play the plan shows, in one sentence. */
export function rollWords(roll: LyricRoll): string {
  const of = `${roll.n_won} of ${roll.n_words} ${roll.n_words === 1 ? 'word' : 'words'}`;
  switch (roll.state) {
    case 'playing':
      return roll.kept || rollIsKept(roll) ? `This play, your kept roll #${roll.tag}: ${of} play.`
        : `This play #${roll.tag}: ${of} play.`;
    case 'kept':
      return `Kept roll #${roll.tag}: the same ${of} play every time.`;
    case 'sample':
      return `Sample play #${roll.tag}: ${of} would play.`;
    default:
      return 'Each play rolls which words act. Shown here as if every word plays.';
  }
}

/** Is the play shown the one he has kept? */
export function rollIsKept(roll: LyricRoll): boolean {
  return roll.seed != null && roll.kept_seed === roll.seed;
}

/** A fresh throwaway play number for "Sample a play" (0 to 2^32 - 1). */
export function samplePlayNumber(random: () => number = Math.random): number {
  return Math.floor(random() * 0x1_0000_0000) >>> 0;
}

/** The three ways a match can play, as the pin control offers them. */
export const PIN_CHOICES: { pin: LyricPin | null; words: (chance: number | null) => string }[] = [
  { pin: 'always', words: () => 'Always' },
  { pin: null, words: (chance) => `Chance ${percentWords(chance)}` },
  { pin: 'never', words: () => 'Never' },
];

/** Which marks show first when a lane is crowded: what will really happen comes
 * before a word that will do nothing. */
function rank(action: LyricEventAction): number {
  return (action.verdict === 'nothing' ? 0 : 2) + action.strength;
}

/** The chip's full printed text, with its chance when it has one. */
export function actionChipLabel(action: LyricEventAction): string {
  const tag = chanceTag(action);
  return tag ? `${actionChipText(action)} · ${tag}` : actionChipText(action);
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
      text: actionChipLabel(a),
      score: rank(a),
    })),
    laneWidthPx, ACTION_ROWS,
  );
  return shown.map((action, i) => ({ action, placement: placements[i] }));
}

/** The line above the chips: how many words do what. */
export function summaryWords(actions: LyricEventAction[]): string {
  const count = (verdict: LyricEventAction['verdict']) =>
    actions.filter((a) => a.verdict === verdict && !satOut(a)).length;
  const out = actions.filter(satOut).length;
  const words = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  return [
    words(count('fire'), 'word fires alone', 'words fire alone'),
    words(count('imprint'), 'word imprints', 'words imprint'),
    words(count('nothing'), 'word does nothing', 'words do nothing'),
    ...(out ? [words(out, 'word sits out this play', 'words sit out this play')] : []),
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
