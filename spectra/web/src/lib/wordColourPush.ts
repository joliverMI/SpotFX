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
import type { WordColourPush } from '../types';

export function onWordColour(fn: (push: WordColourPush) => void): () => void {
  return onSpectraMessage((msg) => {
    if (msg.type !== 'word_colour') return;
    fn(msg as unknown as WordColourPush);
  });
}

/** How long the coloured flash stays on a marker or the box. */
export const WORD_FLASH_MS = 1100;

/** Flash one element in the word's colour: sets the `--word-flash` custom
 * property the `*-flash-word` rules read and re-arms the class so two words
 * in quick succession both show. */
export function flashInWordColour(el: Element & { style?: CSSStyleDeclaration }, cls: string,
                                  colour: string | null | undefined): void {
  const target = el as HTMLElement;
  target.style.setProperty('--word-flash', colour || '#e879f9');
  target.classList.remove(cls);
  void target.getBoundingClientRect();
  target.classList.add(cls);
  setTimeout(() => target.classList.remove(cls), WORD_FLASH_MS);
}
