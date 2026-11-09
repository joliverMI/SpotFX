/** The Sung words lane's matches, pure parts (spectra/services/lyric_matches.py
 * is the server half). Kept out of React so scripts/check_testbed_lyric_matches.mjs
 * can drive them directly. Every chip is placed through lyricsLane's viewPct and
 * layoutLabelRows, so a match sits exactly under the word it is on at any zoom. */
import type { LyricMatch, LyricMatches, TestbedLyricWord } from '../types';
import { inView, layoutLabelRows } from './lyricsLane';
import type { LabelPlacement, LaneView } from './lyricsLane';

export const MATCH_ROWS = 2;
/** The add panel lists the words in view; past this the page says to zoom. */
export const MAX_PICKABLE_WORDS = 80;

/** What a chip prints. A phrase that is already its label prints once. */
export function chipText(match: Pick<LyricMatch, 'phrase' | 'label'>): string {
  return match.phrase.toLowerCase() === match.label.toLowerCase()
    ? match.phrase : `${match.phrase} → ${match.label}`;
}

export interface ShownChip {
  match: LyricMatch;
  placement: LabelPlacement | null;
}

/** The chips in view. His come first, then the most confident guess: when the
 * lane is crowded it is the weakest guess that loses its printed text. */
export function layoutMatches(matches: LyricMatch[], view: LaneView,
                              laneWidthPx: number): ShownChip[] {
  const shown = matches.filter((m) => inView(view, m.ms, m.end_ms));
  const span = Math.max(1, view.endMs - view.startMs);
  const placements = layoutLabelRows(
    shown.map((m) => ({
      xPx: ((Math.max(m.ms, view.startMs) - view.startMs) / span) * laneWidthPx,
      text: chipText(m),
      score: m.source === 'his' ? 2 : (m.confidence ?? 0),
    })),
    laneWidthPx, MATCH_ROWS,
  );
  return shown.map((match, i) => ({ match, placement: placements[i] }));
}

/** Whether a match's words reach the page's sensitivity right now. A match
 * below it is drawn dimmer: it exists, but it is on a word this setting does
 * not treat as emphasized. */
export function isEmphasized(match: Pick<LyricMatch, 'score'>, sensitivity: number): boolean {
  return match.score >= 1 - sensitivity;
}

export function provenanceWords(match: Pick<LyricMatch, 'source' | 'confidence'>): string {
  if (match.source === 'his') return 'Added by you';
  const confidence = match.confidence == null ? '' : `, confidence ${match.confidence.toFixed(2)}`;
  return `Claude's guess${confidence}`;
}

export function targetsWords(match: Pick<LyricMatch, 'targets' | 'n_targets' | 'targets_missing'>): string {
  if (!match.targets.length) {
    return match.targets_missing ? 'What this pointed at has since been deleted.' : 'Nothing carries this label.';
  }
  const names = match.targets.map((t) => t.name).join(', ');
  const more = match.n_targets - match.targets.length;
  return more > 0 ? `${names}, and ${more} more` : names;
}

/** The sentence above the chips: where this song's reading stands. */
export function readingWords(data: Pick<LyricMatches, 'state' | 'reading' | 'matches'>,
                             nowMs: number): string {
  if (data.state === 'none' || !data.reading) return 'Claude has not read this song.';
  const age = nowMs - data.reading.at_ms;
  const ago = age < 3_600_000 ? `${Math.max(1, Math.round(age / 60_000))} min ago`
    : age < 172_800_000 ? `${Math.round(age / 3_600_000)} h ago`
      : `${Math.round(age / 86_400_000)} days ago`;
  const guesses = data.matches.filter((m) => m.source === 'claude').length;
  const base = `Read ${ago}, ${guesses} ${guesses === 1 ? 'guess' : 'guesses'}`;
  if (data.state === 'labels_changed') return `${base}. The labels have changed since.`;
  if (data.state === 'words_changed') return `${base}. The words have changed since.`;
  return `${base}.`;
}

export function readButtonWords(state: LyricMatches['state']): string {
  return state === 'none' ? 'Read this song' : 'Read again';
}

/** The words the add panel offers: those in the lane's window, with their
 * index in the song, which is what a match is stored against. */
export function pickableWords(words: TestbedLyricWord[], view: LaneView):
{ word: TestbedLyricWord; index: number }[] {
  return words.map((word, index) => ({ word, index }))
    .filter(({ word }) => inView(view, word.ms, word.end_ms));
}

/** Picking: a first tap starts a phrase, a tap after it extends the phrase to
 * that word, and any other tap starts again. */
export interface PickState { first: number | null; last: number | null }

export function nextPick(state: PickState, index: number): PickState {
  if (state.first == null || state.last !== state.first || index <= state.first) {
    return { first: index, last: index };
  }
  return { first: state.first, last: index };
}

export function pickedPhrase(words: TestbedLyricWord[], state: PickState): string {
  if (state.first == null || state.last == null) return '';
  return words.slice(state.first, state.last + 1).map((w) => w.word).join(' ');
}
