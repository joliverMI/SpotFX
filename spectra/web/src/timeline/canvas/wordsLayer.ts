/** THE WORD TRIGGER POINTS ON HOME'S AUDIO SHAPE (Word Shapes W5.2 — the
 * Admiral, 2026-11-18: "Show the word/effect details on the audio shape on
 * home page. Put the trigger point on the audio shape, not just to top
 * ticker. i should be able to tap the audio shape to learn more. make it
 * clean").
 *
 * ONE SOURCE, TWO SURFACES. The rows drawn here are the SAME
 * `/api/upcoming` rows the top ticker draws (`components/songStrip.ts`'s
 * `UpcomingEvent`) at the SAME moment (`eventFireMs`), in the SAME colour
 * (`wordColour`) and with the SAME glyph (`shapeGlyph`/`SHAPE_GLYPH_PX`,
 * `WORD_DIAMOND_R`) — nothing about a word is re-derived here, so the
 * shape and the ticker can never disagree about where a word fires or
 * what it is. `HomeTimeline.tsx` hands the layer the rows it already has
 * from `useUpcoming(uri)`; every other canvas in the app leaves
 * `data.words` unset and this layer draws and hit-tests nothing.
 *
 * TWO DRAWN THINGS, matching what the ticker already says about a word:
 *   • a WORD FIRING ALONE (`kind: "word"`) is its own marker — the colour
 *     diamond, or the shape's glyph where the word draws one (W2.3);
 *   • an event a word IMPRINTS on (a scene/flare/drop row carrying `word`)
 *     gets a small TICK in the word's colour on the word row, at that
 *     event's own x — the canvas's equivalent of the ticker's halo ring,
 *     which cannot be drawn here without redrawing the analysed marker
 *     this layer deliberately does not own.
 * Each one stands on a faint dashed STEM down to the waveform's floor:
 * that stem is "the trigger point" he asked to see, the same way the
 * analysed-marker and Light-Show layers draw theirs.
 *
 * THE Z IS ABOVE THE DROP-SEQUENCE LAYER, DELIBERATELY (z 66, between
 * `dropSeqRail` at 65 and `calibration` at 70). `TimelineCanvas` walks
 * `hitTest` by DESCENDING z, and `dropSeqLayer.ts`'s own `dropSeqBody`
 * (z 45) grabs anything within 4 px of a charge/lull/drop handle's
 * scan-line across the whole main area — so at a z beside the planned
 * markers (40/41) a word sitting near a drop handle would be unreachable.
 * W5.2's spec is explicit that "a word hit wins over a drop-sequence
 * hit", so the layer sits above it. Drawing is unaffected on Home, where
 * `triggers`/`events`/`calibration` are all empty and the drop rails are
 * off; the playhead (z 80) still draws over everything.
 *
 * Pure aside from the passed-in ctx, like every layer here — see
 * `scripts/check_home_words.mjs`, which drives both `draw` and `hitTest`
 * with a recording fake context and no DOM. */
import type { CanvasFrame, CanvasLayer, Hit } from './frame';
import {
  eventFireMs, HALO_GAP, KIND_COLOR, SHAPE_GLYPH_PX, shapeGlyph, WORD_DIAMOND_R, wordColour,
  type UpcomingEvent,
} from '../../components/songStrip';

/** The word row's own centre line: clear of the analysed scene tabs and the
 * Light Show flags (both 0–8 px from the top) and well above the analysed
 * flare dots (`mainH * 0.45`), so the words read as their own row rather
 * than as another kind of analysed marker. */
export const WORD_ROW_CY = 26;
/** ±px of a marker's x that counts as a tap on it (W5.2's spec). The whole
 * stem's column is grabbable, not just the glyph — the same scan-line
 * convention `layers.ts`'s triggers and `lightShowLayer.ts` already use. */
export const WORD_HIT_PX = 6;
/** A word already played is dimmed exactly as the ticker dims a passed
 * marker (`.song-strip-mk-past`, styles/tokens.css). */
export const WORD_PAST_ALPHA = 0.28;
/** ...and "already played" is the ticker's own 50 ms grace, so a marker is
 * not dimmed by the frame it fires on. */
export const WORD_PAST_GRACE_MS = 50;
/** The stem is a hint, not a second marker row. */
export const WORD_STEM_ALPHA = 0.4;
/** The imprint tick: half the diamond's height, 2 px wide. */
export const WORD_TICK_HALF_H = 4;
/** The ring on the marker the details card is open on — at the ticker's own
 * halo distance, so "selected" looks like the family it belongs to. */
export const WORD_SELECT_GAP = HALO_GAP;

/** A row's stable identity for selection: the trigger id `/api/upcoming`
 * carries for every row (`lyric_events.fire_id` for a word firing alone,
 * the imprinted event's own id otherwise), falling back to kind@time for a
 * row from an older server that carries none — never time alone, since a
 * flare's landing moment carries its lead and its mark does not. */
export function wordRowKey(e: Pick<UpcomingEvent, 'id' | 'kind' | 'ms' | 'fire_ms'>): string {
  return e.id || `${e.kind}@${eventFireMs(e)}`;
}

/** Is this row a word firing ON ITS OWN (its own marker), rather than an
 * event a word merely imprints its colour on (a tick)? */
export function firesAlone(e: Pick<UpcomingEvent, 'kind'>): boolean {
  return e.kind === 'word';
}

/** THE ROWS THIS LAYER DRAWS, out of everything `/api/upcoming` sent: a
 * word firing alone, and every event a matched word gives its colour to.
 * Exported so `HomeTimeline` feeds the bag through exactly this rule and
 * the check can assert it against the same list the ticker filters. */
export function wordRowsOf(events: readonly UpcomingEvent[] | undefined | null): UpcomingEvent[] {
  return (events ?? []).filter((e) => firesAlone(e) || !!e.word);
}

/** The nearest word row to `x`, or null — the shared body of `hitTest` and
 * of anything else that needs to resolve a tap to a word. */
export function wordHitAt(x: number, f: CanvasFrame): Hit {
  const rows = f.data.words;
  if (!rows?.length) return null;
  let best: { d: number; row: UpcomingEvent; ms: number } | null = null;
  for (const row of rows) {
    const ms = eventFireMs(row);
    if (ms < f.win.startMs || ms > f.win.endMs) continue;
    const d = Math.abs(f.timeToX(ms) - x);
    if (d <= WORD_HIT_PX && (!best || d < best.d)) best = { d, row, ms };
  }
  return best ? { kind: 'word-marker', key: wordRowKey(best.row), ms: best.ms } : null;
}

function isPast(f: CanvasFrame, ms: number): boolean {
  return f.nowMs != null && ms < f.nowMs - WORD_PAST_GRACE_MS;
}

export const wordMarkers: CanvasLayer = {
  id: 'wordMarkers',
  // See the module docstring: above dropSeqLayer's own hit tolerance,
  // below the playhead.
  z: 66,
  visible: (f) => !!f.data.words?.length,
  draw(f) {
    const { ctx } = f;
    const selected = f.data.wordSelected ?? null;
    ctx.save();
    for (const row of f.data.words!) {
      const ms = eventFireMs(row);
      if (ms < f.win.startMs || ms > f.win.endMs) continue;
      const x = f.timeToX(ms);
      const colour = wordColour(row) ?? KIND_COLOR.word;
      const base = isPast(f, ms) ? WORD_PAST_ALPHA : 1;

      // THE TRIGGER POINT: a faint stem from the marker to the waveform's
      // floor, so the moment is readable against the shape itself.
      ctx.globalAlpha = base * WORD_STEM_ALPHA;
      ctx.strokeStyle = colour;
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(x, WORD_ROW_CY + WORD_DIAMOND_R + 1);
      ctx.lineTo(x, f.mainH);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.globalAlpha = base;
      if (!firesAlone(row)) {
        // An imprint: a small tick in the word's colour at the event's x.
        ctx.fillStyle = colour;
        ctx.fillRect(x - 1, WORD_ROW_CY - WORD_TICK_HALF_H, 2, WORD_TICK_HALF_H * 2);
      } else {
        const glyph = shapeGlyph(row.shape);
        ctx.fillStyle = colour;
        if (glyph) {
          ctx.font = `${SHAPE_GLYPH_PX}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(glyph, x, WORD_ROW_CY);
        } else {
          ctx.beginPath();
          ctx.moveTo(x, WORD_ROW_CY - WORD_DIAMOND_R);
          ctx.lineTo(x + WORD_DIAMOND_R, WORD_ROW_CY);
          ctx.lineTo(x, WORD_ROW_CY + WORD_DIAMOND_R);
          ctx.lineTo(x - WORD_DIAMOND_R, WORD_ROW_CY);
          ctx.closePath();
          ctx.fill();
        }
      }

      // The one the details card is open on wears the ticker's own halo
      // ring, so the card's subject is never in doubt.
      if (selected && selected === wordRowKey(row)) {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = colour;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(x, WORD_ROW_CY, WORD_DIAMOND_R + WORD_SELECT_GAP, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
    ctx.restore();
  },
  hitTest(x, y, f) {
    // `TimelineCanvas.hitTest` does not consult `visible`, so the guard
    // belongs here too: every other canvas in the app leaves `words` unset
    // and must never have a tap stolen by this layer.
    if (!f.data.words?.length) return null;
    if (y < 0 || y > f.mainH) return null;
    return wordHitAt(x, f);
  },
};
