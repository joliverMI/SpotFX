/** Pure data helpers ported from frontend/js/shape_canvas.js. */
import type { AudioShapeData, LibrosaAnalysis, MarkType, MusicTrigger } from '../types';

/** One Override Blend region: from a blend trigger to the next enabled
 * trigger (or song end). Mirrors trigger_engine._blend_factor_for. */
export interface BlendSpan {
  startMs: number;
  endMs: number;
  triggerId: string;
  eventId: string;
}

export function computeBlendSpans(triggers: MusicTrigger[], durationMs: number): BlendSpan[] {
  const enabled = triggers
    .filter((t) => t.enabled !== false)
    .sort((a, b) => a.timestamp_ms - b.timestamp_ms);
  const spans: BlendSpan[] = [];
  for (const t of enabled) {
    if (!t.override_blend) continue;
    const next = enabled.find((n) => n.timestamp_ms > t.timestamp_ms);
    spans.push({
      startMs: t.timestamp_ms,
      endMs: next ? next.timestamp_ms : durationMs,
      triggerId: t.id,
      eventId: t.event_id,
    });
  }
  return spans;
}

export const MARK_COLOR: Record<MarkType, string> = {
  bass_drop: '#e74c3c', bass_start: '#2ecc71', bass_end: '#e67e22',
  power_up: '#f39c12', power_down: '#9b59b6',
  quiet: '#3498db', charging: '#f1c40f', tempo_change: '#9b59b6',
};

export const MARK_ABBR: Record<MarkType, string> = {
  bass_drop: 'BD', bass_start: 'BS', bass_end: 'BE',
  power_up: 'PU', power_down: 'PD', quiet: 'Q', charging: 'CH', tempo_change: 'TC',
};

export const AVG_COLORS = {
  total: 'rgba(255,255,255,0.7)',
  bass: 'rgba(20,160,70,0.85)',
  mid: 'rgba(180,90,10,0.85)',
  high: 'rgba(25,100,180,0.85)',
};

export const SCALE_LABELS = { total: 'Total', bass: 'Bass', mid: 'Mids', high: 'Highs' };

/** Past-only rolling-average RMS arrays (port of computeAverages). */
export function computeAverages(data: AudioShapeData, windowMs: number) {
  const ts = data.timestamps_ms;
  const n = ts.length;
  if (!n) return null;
  const keys = ['rms_total', 'rms_low', 'rms_mid', 'rms_high'] as const;
  const result = {} as Record<(typeof keys)[number], number[]>;
  for (const k of keys) {
    const src = data[k] || [];
    const out = new Array<number>(n);
    let lo = 0, hi = -1, sum = 0;
    for (let i = 0; i < n; i++) {
      const wlo = ts[i] - windowMs, whi = ts[i];
      while (hi + 1 < n && ts[hi + 1] <= whi) { hi++; sum += src[hi] || 0; }
      while (lo <= hi && ts[lo] < wlo) { sum -= src[lo] || 0; lo++; }
      out[i] = hi >= lo ? sum / (hi - lo + 1) : 0;
    }
    result[k] = out;
  }
  return result;
}

/** Per-beat MFCC timbral distances, 0-1 normalized (WINDOW=4 lag). */
export function computeMfccDistances(librosa: LibrosaAnalysis | null): number[] | null {
  const beats = librosa?.beats;
  if (!beats?.length) return null;
  const first = beats[0] as { mfcc?: number[] };
  if (!first.mfcc?.length) return null;
  const WINDOW = 4;
  const dists = new Array<number>(beats.length).fill(0);
  for (let i = WINDOW; i < beats.length; i++) {
    const a = (beats[i] as { mfcc?: number[] }).mfcc!;
    const b = (beats[i - WINDOW] as { mfcc?: number[] }).mfcc!;
    let sum = 0;
    for (let c = 0; c < a.length; c++) sum += (a[c] - b[c]) ** 2;
    dists[i] = Math.sqrt(sum);
  }
  const mx = Math.max(...dists);
  if (mx > 1e-9) for (let i = 0; i < dists.length; i++) dists[i] /= mx;
  return dists;
}

/** Y-position-dependent snapping (port of snapTimestamp): beat strip / bottom
 * third → beats; top third → nearest onset or harmonic; middle → no snap. */
export function snapTimestamp(
  rawMs: number,
  clickY: number,
  opts: {
    librosa: LibrosaAnalysis | null;
    librosaOffsetMs: number;
    mainH: number;
    win: { startMs: number; endMs: number };
    canvasW: number;
  },
): number {
  const la = opts.librosa;
  if (!la?.beats?.length) return rawMs;
  const off = opts.librosaOffsetMs;
  const radiusMs = (10 * (opts.win.endMs - opts.win.startMs)) / Math.max(1, opts.canvasW);

  const nearest = (events: { ms: number }[] | undefined): number | null => {
    if (!events?.length) return null;
    let best: number | null = null;
    let bestDist = radiusMs;
    for (const ev of events) {
      const d = Math.abs(ev.ms + off - rawMs);
      if (d < bestDist) { bestDist = d; best = ev.ms + off; }
    }
    return best;
  };

  if (clickY >= opts.mainH) return nearest(la.beats) ?? rawMs;
  const yFrac = clickY / Math.max(1, opts.mainH);
  if (yFrac < 1 / 3) {
    const ho = nearest(la.harmonic_changes as { ms: number }[] | undefined);
    const on = nearest(la.onsets);
    if (ho !== null && on !== null) return Math.abs(ho - rawMs) <= Math.abs(on - rawMs) ? ho : on;
    return ho ?? on ?? rawMs;
  }
  if (yFrac >= 2 / 3) return nearest(la.beats) ?? rawMs;
  return rawMs;
}
