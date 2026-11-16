/** THE LIVE PULSE of word colours (data/word-effect-highlight-options,
 * option E's live half — the Admiral's pick, 2026-11-12): the engine pushes
 * `{"type": "word_colour", ...lyric_events.fired_payload}` on SPECTRA's own
 * websocket the moment a matched word fires on its own or imprints on an
 * event (trigger_engine._push_lyric → engine._push_word_colour). The song
 * strip flashes the marker in the word's colour and the next-event box takes
 * it; the status poll is far too slow for a flash, and the show log stays
 * the record of what happened.
 *
 * `event_id` is the id the marker carries on /api/upcoming (a trigger id, or
 * `lyric:<word key>` for a word firing alone), so a page finds the marker by
 * identity, never by time. */
import { onSpectraMessage } from '../api/spectraWs';
import { shapeWords } from '../components/songStrip';
import type { WordColourPush } from '../types';

export function onWordColour(fn: (push: WordColourPush) => void): () => void {
  return onSpectraMessage((msg) => {
    if (msg.type !== 'word_colour') return;
    fn(msg as unknown as WordColourPush);
  });
}

/** How long the coloured flash stays on a marker or the box. */
export const WORD_FLASH_MS = 1100;

/** WORD SHAPES (W2.3): what became of a shape the moment it was told —
 * `trigger_engine._fire_lyric_shape`'s own `result`, as the pulse says it.
 * `fell_back_to_colour` is the one race the plan cannot see (the showing
 * scene changed inside the replan window), so it reads as the colour it
 * did instead rather than as a failure. An unlisted result is printed
 * verbatim rather than guessed at. */
const SHAPE_RESULT_WORDS: Record<string, string> = {
  applied: 'drew',
  fell_back_to_colour: 'colour instead',
  no_class: 'nothing could draw',
  no_band: 'nothing could draw',
  no_active_scene: 'nothing could draw',
};

/** THE PULSE'S WORDS: "love → ♥ heart · drew" for a shape, the word
 * and what landed for a colour. One pure function, so the next-event box
 * and the strip's marker flash can never say two different things about
 * the same push — and so the Test Bed's own check script can assert it
 * with no DOM. */
export function pulseWords(push: Pick<WordColourPush,
  'verdict' | 'phrase' | 'shape' | 'result' | 'landed' | 'set_name'>): string {
  if (push.verdict === 'shape') {
    const what = shapeWords(push.phrase, push.shape) ?? push.phrase;
    const result = push.result
      ? SHAPE_RESULT_WORDS[push.result] ?? (push.result === 'held' ? 'held' : push.result)
      : null;
    return result ? `${what} · ${result}` : what;
  }
  if (push.landed) {
    return push.set_name ? `${push.phrase} · ${push.set_name}` : push.phrase;
  }
  return `${push.phrase} · ${push.result ?? 'nothing'}`;
}

/** Flash one element in the word's colour: sets the `--word-flash` custom
 * property the `*-flash-word` rules read and re-arms the class so two words
 * in quick succession both show. */
export function flashInWordColour(el: Element & { style?: CSSStyleDeclaration }, cls: string,
                                  colour: string | null | undefined,
                                  words?: string | null): void {
  const target = el as HTMLElement;
  target.style.setProperty('--word-flash', colour || '#e879f9');
  // What the pulse SAYS (W2.3), beside the colour it shows: readable on
  // hover and to a screen reader for as long as the flash lasts, then
  // taken off again so a stale word never outlives its own pulse.
  if (words) {
    target.setAttribute('data-word-pulse', words);
    setTimeout(() => target.removeAttribute('data-word-pulse'), WORD_FLASH_MS);
  }
  target.classList.remove(cls);
  void target.getBoundingClientRect();
  target.classList.add(cls);
  setTimeout(() => target.classList.remove(cls), WORD_FLASH_MS);
}
