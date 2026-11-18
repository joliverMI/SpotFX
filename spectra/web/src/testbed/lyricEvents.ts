/** What each matched word would do, pure parts (spectra/services/lyric_events.py
 * is the server half and says the rules; the same plan drives the show). Every
 * chip is placed through lyricsLane's layoutLabelRows, so it sits under the word
 * it belongs to at any zoom. */
import { shapeGlyph, shapeName, shapeWords } from '../components/songStrip';
import type { LyricEventAction, LyricPin, LyricRoll } from '../types';
import { inView, layoutLabelRows } from './lyricsLane';
import type { LabelPlacement, LaneView } from './lyricsLane';

export const ACTION_ROWS = 2;

export const ENERGY_CUTOFF = { min: 0, max: 1, step: 0.05 };
export const MIN_GAP_S = { min: 0, max: 30, step: 0.5 };
export const IMPRINT_WINDOW_S = { min: 0, max: 5, step: 0.25 };

const EVENT_WORDS: Record<string, string> = { drop: 'drop', scene: 'scene', flare: 'flare' };

/** WORD SHAPES (W2.3): why a word that reaches a shape is doing its COLOUR
 * instead (`WordAction.shape_skipped`, lyric_events.py) — the short tail a
 * colour/imprint chip wears so a shaped word never silently looks like a
 * plain one. The full sentence is already in `action.words`. */
const SKIPPED_WORDS: Record<string, string> = {
  drop_wins: 'drop',
  nothing_can_draw: 'no Words band',
};

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

/** WORD SHAPES (W2.3): the tail a chip wears when its word reaches a shape
 * and is NOT drawing one — "♥ skipped: drop" / "♥ skipped: no Words band".
 * Empty for a word that is drawing, or that reaches no shape at all. */
export function skippedShapeTag(
  action: Pick<LyricEventAction, 'shape' | 'shape_skipped'>,
): string | null {
  if (!action.shape_skipped) return null;
  const why = SKIPPED_WORDS[action.shape_skipped] ?? action.shape_skipped;
  const glyph = shapeGlyph(action.shape);
  return `${glyph ? `${glyph} ` : ''}skipped: ${why}`;
}

/** What a chip prints. */
export function actionChipText(action: LyricEventAction): string {
  // WORD SHAPES (W2.3): a drawing word is "love → ♥ heart" — the word and
  // the shape, the same words the next-event box and the pulse use.
  if (action.verdict === 'shape') {
    return shapeWords(action.phrase, action.shape, action.shape_name) ?? action.phrase;
  }
  const skipped = skippedShapeTag(action);
  const tail = skipped ? ` · ${skipped}` : '';
  if (action.verdict === 'imprint' && action.event) {
    return `${action.phrase} → ${EVENT_WORDS[action.event.kind] ?? action.event.kind}${tail}`;
  }
  if (action.verdict === 'fire') {
    return `${action.phrase} · ${action.momentary ? 'momentary' : 'held'}${tail}`;
  }
  return `${action.phrase}${tail}`;
}

/** Which play the plan shows, in one sentence.
 *
 * WORD TEST MODE (2026-11-17, RoomControlState.word_test_mode): the counts
 * are ALREADY the test-mode counts — the roll ran with every chance at
 * 1.0 — so the only thing left to do is say why they read the way they
 * do, in the same sentence that states them. Without this, "22 of 22
 * words play" on a song full of 3% guesses looks like a bug. */
export function rollWords(roll: LyricRoll): string {
  const of = `${roll.n_won} of ${roll.n_words} ${roll.n_words === 1 ? 'word' : 'words'}`;
  const tail = roll.test_mode ? ' Word test mode is on: every word fires.' : '';
  switch (roll.state) {
    case 'playing':
      return (roll.kept || rollIsKept(roll) ? `This play, your kept roll #${roll.tag}: ${of} play.`
        : `This play #${roll.tag}: ${of} play.`) + tail;
    case 'kept':
      return `Kept roll #${roll.tag}: the same ${of} play every time.` + tail;
    case 'sample':
      return `Sample play #${roll.tag}: ${of} would play.` + tail;
    default:
      return 'Each play rolls which words act. Shown here as if every word plays.' + tail;
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
  const drawing = count('shape');
  return [
    // WORD SHAPES (W2.3): counted first and only when there are any, so a
    // song whose words reach no shape reads exactly as it does today.
    ...(drawing ? [words(drawing, 'word draws a shape', 'words draw a shape')] : []),
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
  /** WORD SHAPES (W2.3): on a `kind: "word"` row whose word DRAWS a shape,
   * the shape's id and name — the row then draws the shape's own glyph in
   * place of the colour diamond. Null on every other row. */
  shape: string | null;
  shape_name: string | null;
}

export function wordEvents(actions: LyricEventAction[]): WordEvent[] {
  const byId = new Map<string, WordEvent>();
  for (const a of actions) {
    // A SHAPE WORD IS THE SAME KIND OF MARK (W0.3's own `word_marks` rule):
    // one row, one idea — "a word did something here" — whether the
    // something was a colour or a shape; only the glyph differs.
    if (a.verdict === 'fire' || a.verdict === 'shape') {
      const drawing = a.verdict === 'shape';
      byId.set(`lyric:${a.key}`, {
        id: `lyric:${a.key}`,
        kind: 'word',
        ms: a.ms,
        label: drawing
          ? `“${a.phrase}” draws the ${shapeName(a.shape, a.shape_name) ?? 'shape'} shape`
          : `“${a.phrase}” fires alone`,
        word: a.phrase, swatch: a.swatch, imprinted: false, cannot: null,
        shape: drawing ? a.shape : null,
        shape_name: drawing ? a.shape_name : null,
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
      shape: null, shape_name: null,
    });
  }
  return [...byId.values()].sort((a, b) => a.ms - b.ms);
}

/** The tooltip for one event on the row. */
export function wordEventText(e: WordEvent, fmt: (ms: number) => string): string {
  const where = `${fmt(e.ms)} · ${e.label}`;
  // A word's own mark says what it does in its label (a colour fired alone,
  // or — W2.3 — the shape it draws), so it needs no tail of its own.
  if (e.kind === 'word') return where;
  if (e.imprinted && e.word) return `${where} — gets the colour of “${e.word}”`;
  if (e.cannot) return `${where} — cannot carry colour (${e.cannot})`;
  return `${where} — a word is near it but does nothing here`;
}
