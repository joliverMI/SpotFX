/** WHAT A WORD WILL DO, ON A TAP (Word Shapes W5.2 — the Admiral,
 * 2026-11-18: "i should be able to tap the audio shape to learn more. make
 * it clean"). A small popover over Home's audio shape, placed at the word
 * marker it describes.
 *
 * THREE LINES AND A COUNTDOWN, in his order:
 *   1. WHAT IT WAS READ AS, first and largest — W5.3's own `wordReading`
 *      ("red", "sky blue", "heart", "heart · red"), never the phrase,
 *      with the word's swatch beside it when the row carries one.
 *   2. THE SUNG WORDS under it, muted and smaller — the phrase is where
 *      he checks a match, and W5.3 moved it out of the countdown box, so
 *      this is the one surface that still shows it on Home.
 *   3. WHAT FIRES — the shape's own sentence (`/api/upcoming`'s `words`,
 *      `lyric_events.describe`) for a shape word; whether the colour is
 *      momentary or holds to the next scene change for a colour word
 *      firing alone (the row's own `momentary`); and the event it lends
 *      its colour to, with that event's time, for an imprint.
 *   4. HOW FAR AWAY it is, `countdownParts` exactly as the ticker's
 *      next-event box counts (tenths to 99.9s, then m:ss), "away" before
 *      it fires and "ago" after.
 *
 * NO CHANCE LINE, AND THAT IS DELIBERATE. W5.2's spec asks for the word's
 * chance on this play with test mode off, and says in the same breath: if
 * a field is missing from `/api/upcoming`, say so and leave the line out
 * rather than inventing one. `chance` IS missing — a word row carries
 * `ms`/`end_ms`/`word`/`word_ms`/`swatch`/`word_key`/`momentary`/`shape`
 * (+ `shape_name`/`words`) and, since W5.3, `label`; the roll's own
 * numbers live on the Test Bed (`lyric_events.action_payload`'s `chance`/
 * `draw`/`won`, drawn by testbed/lyricEvents.ts). A row is on this feed
 * only because it WON this play's roll, so inventing a percentage here
 * would also be describing a decision already made. The line is left out;
 * the Test Bed stays the place the odds are read.
 *
 * READ-ONLY. Nothing here fires, holds or writes anything — W5.2's
 * "nothing moves in the room".
 *
 * A `position: fixed` portal clamped to the viewport with a 16 px gutter,
 * the house pattern for a popover escaping a clipping ancestor
 * (components/InfoTip.tsx's docstring; `.home-timeline-shape` is
 * `overflow: hidden`, so an absolutely-positioned card inside it would be
 * cut off at the shape's own edge). */
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  countdownParts, eventFireMs, fmtMMSS, kindLabel, shapeName, wordColour, wordReading,
  type UpcomingEvent,
} from '../components/songStrip';
import { getShowClockMs } from '../lib/showClock';

/** The card's own width, and the phone gutter W5.2 asks for. */
export const CARD_WIDTH = 248;
export const VIEWPORT_GUTTER = 16;
/** Clear of the word row (`wordsLayer.ts`'s WORD_ROW_CY) so the marker it
 * describes stays visible above the card. */
export const MARKER_GAP = 14;
/** The countdown ticks at the ticker's own tenth-of-a-second resolution. */
const TICK_MS = 100;

/** Where the card goes for a marker at viewport (x, y) — pure, so
 * `scripts/check_home_words.mjs` can assert the gutter with no layout. */
export function cardPosition(
  marker: { x: number; y: number }, viewport: { w: number; h: number },
): { left: number; top: number; width: number } {
  const width = Math.min(CARD_WIDTH, Math.max(120, viewport.w - VIEWPORT_GUTTER * 2));
  const left = Math.max(
    VIEWPORT_GUTTER,
    Math.min(marker.x - width / 2, viewport.w - VIEWPORT_GUTTER - width),
  );
  return { left, top: marker.y + MARKER_GAP, width };
}

/** The one line of what this row actually does, built ONLY from fields
 * `/api/upcoming` really sends. Null when the row says nothing usable —
 * the line is then left out rather than guessed at. */
export function doesLine(row: UpcomingEvent): string | null {
  if (row.kind === 'word') {
    if (row.shape) {
      // The shape's own sentence, as the Test Bed prints it
      // (`lyric_events.describe`), or the bare fact for a row from an
      // older server that carries no sentence.
      const name = shapeName(row.shape, row.shape_name);
      return row.words || (name ? `Draws the ${name} shape.` : null);
    }
    if (row.momentary === false) {
      return 'Its colour holds until the next scene change or matched word.';
    }
    if (row.momentary === true) {
      return 'Its colour arrives for a moment, then the room goes back.';
    }
    return null;
  }
  return `Gives its colour to the ${kindLabel(row.kind).toLowerCase()} `
    + `at ${fmtMMSS(eventFireMs(row))}.`;
}

/** "12.4s away" / "1:40 ago" — `countdownParts`, the ticker's own rule. */
export function awayLine(row: UpcomingEvent, nowMs: number | null): string | null {
  if (nowMs == null) return null;
  const delta = eventFireMs(row) - nowMs;
  const { value, unit } = countdownParts(Math.abs(delta));
  return `${value}${unit ?? ''} ${delta >= 0 ? 'away' : 'ago'}`;
}

export default function WordDetailsCard({
  row, marker, ignore, onClose,
}: {
  row: UpcomingEvent;
  /** The marker's own position in VIEWPORT coordinates. */
  marker: { x: number; y: number };
  /** The shape's own box — a pointer landing in there is the canvas's to
   * interpret (it may be opening this card on another word), so it must
   * never also be read here as an outside tap. */
  ignore?: HTMLElement | null;
  onClose: () => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [, setTick] = useState(0);

  // Escape, and a tap anywhere that is neither the card nor the shape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    const onDown = (e: Event) => {
      const t = e.target as Node | null;
      if (!t) return;
      if (cardRef.current?.contains(t)) return;
      if (ignore?.contains(t)) return;
      onClose();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onDown);
    };
  }, [onClose, ignore]);

  // The countdown moves; nothing else in the card does.
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), TICK_MS);
    return () => clearInterval(id);
  }, []);

  const pos = cardPosition(marker, { w: window.innerWidth, h: window.innerHeight });
  const reading = wordReading(row) ?? kindLabel(row.kind);
  const swatch = wordColour(row);
  const does = doesLine(row);
  const away = awayLine(row, getShowClockMs());

  return createPortal(
    <div
      ref={cardRef}
      className="home-word-card"
      role="dialog"
      aria-label={`What the word read as ${reading} will do`}
      style={{ left: pos.left, top: pos.top, width: pos.width }}
    >
      <div className="home-word-card-read">
        {swatch && <span className="home-word-card-swatch" style={{ background: swatch }} />}
        <span className="home-word-card-reading">{reading}</span>
      </div>
      {row.word && <div className="home-word-card-phrase">“{row.word}”</div>}
      {does && <div className="home-word-card-does">{does}</div>}
      {away && <div className="home-word-card-away">{away}</div>}
    </div>,
    document.body,
  );
}
