/** Matcher's-view diff math — port of the inline helpers in frontend/debug.html.
 * Both signals are squared, binned to 25 ms, z-scored over the live span —
 * exactly what the xcorr Pearson correlator compares, so gain/volume cancel. */
import type { AudioShapeData } from '../timeline/types';
import type { DiffSeries, LiveShapeLayerData } from '../timeline/canvas/frame';

export const DIFF_BIN_MS = 25;      // mirrors _XCORR_BIN_MS server-side
const DIFF_SCALE_Z = 2.5;           // σ that maps to ±1
export const DIFF_MIN_SPAN_MS = 2000; // z-score unstable below this span
const RMS_BANDS = ['rms_total', 'rms_low', 'rms_mid', 'rms_high'] as const;

/** Linear-interpolate `values` (sampled at `ts`) at the times in `targetTs`.
 * O(n+m) forward sweep — both arrays are monotonically increasing. */
function interpAt(targetTs: number[], ts: number[], values: number[]): number[] {
  if (!ts?.length || !values?.length) return new Array(targetTs.length).fill(0);
  const out = new Array<number>(targetTs.length);
  let j = 0;
  for (let i = 0; i < targetTs.length; i++) {
    const t = targetTs[i];
    while (j < ts.length - 1 && ts[j + 1] < t) j++;
    if (t <= ts[0]) { out[i] = values[0]; continue; }
    if (t >= ts[ts.length - 1]) { out[i] = values[ts.length - 1]; continue; }
    const t0 = ts[j], t1 = ts[j + 1];
    const f = (t - t0) / (t1 - t0);
    out[i] = values[j] * (1 - f) + values[j + 1] * f;
  }
  return out;
}

/** Block-mean the ~11.6 ms capture frames onto the 25 ms grid xcorr consumes. */
export function binTo25ms(live: LiveShapeLayerData): LiveShapeLayerData {
  const ts = live.timestamps_ms;
  if (!ts?.length) return live;
  const out: LiveShapeLayerData = {
    timestamps_ms: [], rms_total: [], rms_low: [], rms_mid: [], rms_high: [],
  };
  let i = 0;
  for (let binStart = ts[0]; i < ts.length; binStart += DIFF_BIN_MS) {
    const binEnd = binStart + DIFF_BIN_MS;
    let n = 0;
    const sums = [0, 0, 0, 0];
    while (i < ts.length && ts[i] < binEnd) {
      RMS_BANDS.forEach((b, k) => { sums[k] += live[b]?.[i] ?? 0; });
      n++; i++;
    }
    if (!n) continue;
    out.timestamps_ms.push(binStart);
    RMS_BANDS.forEach((b, k) => out[b].push(sums[k] / n));
  }
  return out;
}

function zscore(arr: number[]): number[] {
  const n = arr.length;
  if (!n) return arr;
  let mean = 0;
  for (const v of arr) mean += v;
  mean /= n;
  let varSum = 0;
  for (const v of arr) varSum += (v - mean) * (v - mean);
  const std = Math.sqrt(varSum / n);
  if (std < 1e-6) return arr.map(() => 0);
  return arr.map((v) => (v - mean) / std);
}

/** Shift live frames into saved-shape time by the engine's shape offset. */
export function shiftLive(data: LiveShapeLayerData, offsetMs: number): LiveShapeLayerData {
  if (!data.timestamps_ms?.length || !offsetMs) return data;
  return { ...data, timestamps_ms: data.timestamps_ms.map((t) => t + offsetMs) };
}

/** Live − saved diff over the live span, normalized to ±1 (±1 ≡ ±2.5σ) with a
 * 3-bin (75 ms) centered moving average. Uses rms_total (the debug canvases
 * show total only); returns null while warming up (< DIFF_MIN_SPAN_MS). */
export function computeDiff(saved: AudioShapeData, live: LiveShapeLayerData): DiffSeries | null {
  const ts = live.timestamps_ms;
  if (!ts?.length) return null;
  if (ts[ts.length - 1] - ts[0] < DIFF_MIN_SPAN_MS) return null;

  const savedAt = interpAt(ts, saved.timestamps_ms, saved.rms_total ?? []);
  const zLive = zscore(ts.map((_, i) => (live.rms_total?.[i] ?? 0) ** 2));
  const zSaved = zscore(savedAt.map((v) => (v ?? 0) ** 2));
  const pos: number[] = [], neg: number[] = [];
  for (let i = 0; i < ts.length; i++) {
    const lo = Math.max(0, i - 1), hi = Math.min(ts.length - 1, i + 1);
    let d = 0;
    for (let j = lo; j <= hi; j++) d += (zLive[j] ?? 0) - (zSaved[j] ?? 0);
    d /= hi - lo + 1;
    d = Math.max(-1, Math.min(1, d / DIFF_SCALE_Z));
    pos.push(Math.max(0, d));
    neg.push(Math.max(0, -d));
  }
  return { timestamps_ms: ts, pos, neg };
}
