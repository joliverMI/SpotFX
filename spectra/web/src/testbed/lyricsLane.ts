/** The Sung words lane's pure parts (spectra/services/lyrics_timeline.py is
 * the server half) and the zoom window every lane on the page shares. Kept
 * out of React so scripts/check_testbed_lyrics_lane.mjs can transpile and
 * drive them directly, the testbed/metrics.ts and edgeKnobs.ts convention.
 *
 * ONE ms -> % SCALE. viewPct is the only place a time becomes a position, so
 * zooming moves every lane together, and a word and a flare at the same time
 * stay on the same x at any zoom. */
import type { TestbedWordFeatures } from '../types';

export const ENGINE_LYRICS = 'lyrics';

/** spectra/services/lyrics_emphasis.py's own range. The server's
 * `default_sensitivity` is what the slider starts at once it is known. */
export const DEFAULT_EMPHASIS_SENSITIVITY = 0.6;
export const MIN_EMPHASIS_SENSITIVITY = 0;
export const MAX_EMPHASIS_SENSITIVITY = 1;

export function clampEmphasisSensitivity(v: number): number {
  if (!Number.isFinite(v)) return DEFAULT_EMPHASIS_SENSITIVITY;
  return Math.max(MIN_EMPHASIS_SENSITIVITY, Math.min(MAX_EMPHASIS_SENSITIVITY, v));
}

export function lyricsRelevant(slots: ({ engine: string } | null)[]): boolean {
  return slots.some((s) => s?.engine === ENGINE_LYRICS);
}

export interface LaneView {
  startMs: number;
  endMs: number;
}

/** A printed word needs about this much of the lane per second of song to
 * be readable, which is why the page opens zoomable: at the whole-song scale
 * a four-minute song gives each second about 4 px. */
export const ZOOM_CHOICES: { label: string; spanMs: number | null }[] = [
  { label: 'Whole song', spanMs: null },
  { label: '60 s', spanMs: 60_000 },
  { label: '30 s', spanMs: 30_000 },
  { label: '15 s', spanMs: 15_000 },
  { label: '8 s', spanMs: 8_000 },
];

export function wholeSong(durationMs: number): LaneView {
  return { startMs: 0, endMs: Math.max(1, durationMs) };
}

/** The window the lanes show: `spanMs` wide around `centerMs`, kept inside
 * the song. A span of null, or one at least as long as the song, is the
 * whole song. */
export function laneView(durationMs: number, spanMs: number | null, centerMs: number): LaneView {
  const dur = Math.max(1, durationMs);
  if (spanMs == null || spanMs >= dur) return wholeSong(dur);
  const start = Math.max(0, Math.min(dur - spanMs, centerMs - spanMs / 2));
  return { startMs: start, endMs: start + spanMs };
}

/** A time's position in the lane, 0..100, clamped to the lane's edges. */
export function viewPct(view: LaneView, ms: number): number {
  const span = Math.max(1, view.endMs - view.startMs);
  return Math.max(0, Math.min(100, ((ms - view.startMs) / span) * 100));
}

/** Whether a moment, or a span from `startMs` to `endMs`, shows in the lane. */
export function inView(view: LaneView, startMs: number, endMs: number = startMs): boolean {
  return endMs >= view.startMs && startMs <= view.endMs;
}

export const LABEL_ROWS = 3;
const LABEL_CHAR_PX = 8;
const LABEL_PAD_PX = 8;
const LABEL_GAP_PX = 4;

export function labelWidthPx(text: string): number {
  return text.length * LABEL_CHAR_PX + LABEL_PAD_PX;
}

export interface LabelInput {
  xPx: number;
  text: string;
  score: number;
}

export interface LabelPlacement {
  row: number;
  leftPx: number;
  widthPx: number;
}

/** Where each emphasized word's printed name goes, strongest word first so
 * that when the lane is too crowded it is the weakest labels that give way.
 * Returns one entry per input, in input order; null means this word keeps its
 * mark but has no room for its name (zooming in makes room). A label starts
 * at its mark and is nudged left only to stay inside the lane. */
export function layoutLabelRows(marks: LabelInput[], laneWidthPx: number,
                                rows: number = LABEL_ROWS): (LabelPlacement | null)[] {
  const order = marks.map((_, i) => i).sort(
    (a, b) => marks[b].score - marks[a].score || marks[a].xPx - marks[b].xPx,
  );
  const taken: [number, number][][] = Array.from({ length: rows }, () => []);
  const out: (LabelPlacement | null)[] = marks.map(() => null);
  for (const i of order) {
    const widthPx = labelWidthPx(marks[i].text);
    const leftPx = Math.max(0, Math.min(laneWidthPx - widthPx, marks[i].xPx));
    for (let row = 0; row < rows; row += 1) {
      const clear = taken[row].every(
        ([a, b]) => leftPx + widthPx + LABEL_GAP_PX <= a || leftPx >= b + LABEL_GAP_PX,
      );
      if (clear) {
        taken[row].push([leftPx, leftPx + widthPx]);
        out[i] = { row, leftPx, widthPx };
        break;
      }
    }
  }
  return out;
}

/** The faint words sit on two alternating rows, so a word's text has until
 * the word after next before it would touch anything on its own row. The
 * last two words of a song have the lane to themselves. */
export function faintWordReachMs(words: { ms: number }[], index: number): number {
  const next = words[index + 2];
  return next ? next.ms - words[index].ms : Number.POSITIVE_INFINITY;
}

/** Whether a faint word's own text fits in the room it has. */
export function faintWordFits(text: string, widthPx: number): boolean {
  return labelWidthPx(text) <= widthPx;
}

/** Why a word was picked, in the tooltip: the five things the score is made
 * of, each only where it counted. */
export function featureWords(features: TestbedWordFeatures | undefined): string {
  if (!features) return '';
  const parts: string[] = [];
  if (features.loud > 0) parts.push(`louder ${features.loud.toFixed(2)}`);
  if (features.held > 0) parts.push(`held ${features.held.toFixed(2)}`);
  if (features.beat > 0) parts.push(`on the beat ${features.beat.toFixed(2)}`);
  if (features.hook > 0) parts.push(`in the hook ${features.hook.toFixed(2)}`);
  if (features.line_end > 0) parts.push('end of line');
  return parts.join(', ');
}
