/** THE RMS BAND SERIES — one shared definition of which audio-shape bands
 * exist, their colours, and how a band's raw values become a height
 * fraction, so the canvas's own `rmsBands` layer (./layers.ts, the main
 * audio shape on every page) and Home's drop-sequence editor dialog
 * (../../home/HomeDropEditor.tsx) can never draw a different idea of
 * "bass is green, mid is orange, high is blue, total is grey" or a
 * different denominator.
 *
 * His ask (2026-10-29, verbatim): "On the drop sequence edit dialog on
 * home page, make it so the audio shape matches the settings that show
 * in the main audio shape, so it includes the colored mids, highs, and
 * bass (and total if it's on). Right now it just shows one." The dialog
 * drew ONE trace (`rms_total` alone, unconditionally) with no regard for
 * which bands the main shape shows, or what colour they're in — this
 * module is what both now read from, so a change to one can never drift
 * from the other.
 *
 * THE DENOMINATOR IS THE TOTAL BAND'S OWN PEAK, scaled by the total
 * scale and the overall scale — exactly `canvas/layers.ts::maxRmsFor`'s
 * rule (the `rmsBands`/`avgLines` layers already share it): a band's
 * fraction is `(value * its-own-scale * scaleOverall) / (totalPeak *
 * totalScale * scaleOverall)`, so bass/mid/high read smaller than total
 * at the shipped 1/1/1/1 scales — matching what the main shape has
 * always drawn, not a fresh idea of proportion for the dialog. */
import type { AudioShapeData } from '../types';
import type { ShapeScales } from '../../lib/shapeScales';

export const RMS_BAND_KEYS = ['total', 'bass', 'mid', 'high'] as const;
export type RmsBandKey = (typeof RMS_BAND_KEYS)[number];

export type RmsBandVisibility = Record<RmsBandKey, boolean>;

/** Which `AudioShapeData` field backs each band — "bass" is stored as
 * `rms_low` (the capture pipeline's own field name); the rest match. */
export const RMS_BAND_FIELD: Record<RmsBandKey, 'rms_total' | 'rms_low' | 'rms_mid' | 'rms_high'> = {
  total: 'rms_total',
  bass: 'rms_low',
  mid: 'rms_mid',
  high: 'rms_high',
};

/** The ONE fill colour per band — `canvas/layers.ts`'s `rmsBands` layer
 * reads these verbatim rather than carrying its own copy of the same
 * four rgba strings. */
export const RMS_BAND_FILL: Record<RmsBandKey, string> = {
  total: 'rgba(150,150,150,0.4)',
  bass: 'rgba(46,204,113,0.45)',
  mid: 'rgba(230,126,34,0.4)',
  high: 'rgba(52,152,219,0.35)',
};

/** A brighter outline of the same hue — for a renderer (the dialog's
 * SVG) that wants a visible edge on a small, overlapping fill; the main
 * canvas layer draws no stroke of its own, so this has no counterpart
 * to stay in sync with there. */
export const RMS_BAND_STROKE: Record<RmsBandKey, string> = {
  total: 'rgba(190,190,190,0.6)',
  bass: 'rgba(74,222,150,0.7)',
  mid: 'rgba(245,158,70,0.65)',
  high: 'rgba(96,180,235,0.65)',
};

/** Indices of samples whose timestamp lies within `[startMs, endMs]`. */
export function rmsBandWindowIndices(ts: number[], startMs: number, endMs: number): number[] {
  const out: number[] = [];
  for (let i = 0; i < ts.length; i++) if (ts[i] >= startMs && ts[i] <= endMs) out.push(i);
  return out;
}

/** The TOTAL band's own peak over `idx`, scaled by the total scale and
 * the overall scale — restated from `canvas/layers.ts::maxRmsFor` (which
 * needs a `CanvasFrame` this module does not have) so both renderers
 * divide every band by the identical number. */
export function rmsBandPeak(
  shape: AudioShapeData, idx: number[], scales: ShapeScales, scaleOverall: number,
): number {
  const raw = Math.max(...idx.map((i) => shape.rms_total[i] ?? 0), 1e-9);
  return raw * scales.total * scaleOverall;
}

/** One band's height FRACTION at every index in `idx` — already carrying
 * the `* 0.9` headroom the canvas's own `rmsBands`/`avgLines` layers draw
 * with, so a caller maps it to its own coordinate system with
 * `top = H - frac * H` and never re-derives the 0.9. */
export function rmsBandFraction(
  shape: AudioShapeData, band: RmsBandKey, idx: number[],
  scales: ShapeScales, scaleOverall: number, peak: number,
): number[] {
  const values = shape[RMS_BAND_FIELD[band]];
  const scale = scales[band] * scaleOverall;
  return idx.map((i) => ((values[i] ?? 0) * scale) / peak * 0.9);
}
