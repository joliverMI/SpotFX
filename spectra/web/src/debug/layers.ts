/** Debug-page canvas layers: saved-vs-live mirror, matcher's-view diff,
 * rolling-R confidence trace, xcorr window brackets, mismatch spikes.
 * Ports of the shape_canvas.js debug overlays onto the builder's layer stack. */
import type { CanvasLayer } from '../timeline/canvas/frame';

const SPIKE_COLOR = '#ff2d95';
const NEW_COLOR = '#00ff88';
const OLD_COLOR = '#3aa0ff';
const FAIL_COLOR = '#e74c3c';

export const MONITOR_MIN_R = 0.2; // xcorr_monitor_min_r default — below = mismatch evidence
export const MONITOR_GOOD_R = 0.5;

export function rColor(r: number | null): string {
  if (r === null) return '#888';
  if (r >= MONITOR_GOOD_R) return NEW_COLOR;
  if (r >= MONITOR_MIN_R) return '#ffb300';
  return '#ff5252';
}

function windowIndices(ts: number[], startMs: number, endMs: number): number[] {
  const out: number[] = [];
  for (let i = 0; i < ts.length; i++) if (ts[i] >= startMs && ts[i] <= endMs) out.push(i);
  return out;
}

// ── Saved shape (up) vs live capture (mirrored down) ─────────────────────────
// With live data the saved bands squeeze into the upper half; the live overlay
// mirrors below a dashed midline. Without live data the saved shape uses the
// full height (same as the builder's rmsBands, total band only here).
export const savedVsLive: CanvasLayer = {
  id: 'savedVsLive',
  z: 10,
  visible: (f) => !!f.data.shape?.timestamps_ms?.length || !!f.data.live?.timestamps_ms?.length,
  draw(f) {
    const { ctx, view } = f;
    const shape = f.data.shape;
    const live = f.data.live;
    const hasLive = !!live?.timestamps_ms?.length;
    const savedBase = hasLive ? f.mainH / 2 : f.mainH;

    if (shape?.timestamps_ms?.length) {
      const ts = shape.timestamps_ms;
      const idx = windowIndices(ts, f.win.startMs, f.win.endMs);
      if (idx.length) {
        const rawMax = view.maxRms ?? Math.max(...idx.map((i) => shape.rms_total[i]), 1e-9);
        const maxRms = rawMax * view.scales.total * view.scaleOverall;
        const rmsToY = (v: number) => savedBase - (v / maxRms) * savedBase * 0.9;
        const fill = (values: number[], scale: number, style: string) => {
          ctx.beginPath();
          ctx.moveTo(f.timeToX(ts[idx[0]]), savedBase);
          for (const i of idx) ctx.lineTo(f.timeToX(ts[i]), rmsToY((values[i] ?? 0) * scale * view.scaleOverall));
          ctx.lineTo(f.timeToX(ts[idx[idx.length - 1]]), savedBase);
          ctx.closePath();
          ctx.fillStyle = style;
          ctx.fill();
        };
        if (view.filters.total) fill(shape.rms_total, view.scales.total, 'rgba(150,150,150,0.4)');
        if (view.filters.bass) fill(shape.rms_low, view.scales.bass, 'rgba(46,204,113,0.45)');
        if (view.filters.mid) fill(shape.rms_mid, view.scales.mid, 'rgba(230,126,34,0.4)');
        if (view.filters.high) fill(shape.rms_high, view.scales.high, 'rgba(52,152,219,0.35)');
      }
    }

    if (!hasLive) return;
    // Midline divider so the eye separates saved (up) from live (down).
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.18)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(0, savedBase);
    ctx.lineTo(f.w, savedBase);
    ctx.stroke();
    ctx.restore();

    const lts = live.timestamps_ms;
    const lidx = windowIndices(lts, f.win.startMs, f.win.endMs);
    if (!lidx.length) return;
    // Live capture levels differ from the saved shape — own max, min-clamped
    // to the saved max so a quiet capture doesn't blow up visually.
    const savedIdx = shape ? windowIndices(shape.timestamps_ms, f.win.startMs, f.win.endMs) : [];
    const savedMax = shape && savedIdx.length
      ? (view.maxRms ?? Math.max(...savedIdx.map((i) => shape.rms_total[i]), 1e-9)) * view.scales.total * view.scaleOverall
      : 1e-9;
    const liveMax = Math.max(...lidx.map((i) => live.rms_total[i] ?? 0), savedMax, 1e-9);
    const lowerH = f.mainH - savedBase;
    const yDown = (v: number) => savedBase + (v / liveMax) * lowerH * 0.9;
    const fillDown = (values: number[], style: string) => {
      ctx.beginPath();
      ctx.moveTo(f.timeToX(lts[lidx[0]]), savedBase);
      for (const i of lidx) ctx.lineTo(f.timeToX(lts[i]), yDown(values[i] ?? 0));
      ctx.lineTo(f.timeToX(lts[lidx[lidx.length - 1]]), savedBase);
      ctx.closePath();
      ctx.fillStyle = style;
      ctx.fill();
    };
    const { filters } = view;
    if (filters.total) fillDown(live.rms_total, 'rgba(150,150,150,0.32)');
    if (filters.bass) fillDown(live.rms_low, 'rgba(46,204,113,0.36)');
    if (filters.mid) fillDown(live.rms_mid, 'rgba(230,126,34,0.32)');
    if (filters.high) fillDown(live.rms_high, 'rgba(52,152,219,0.30)');
  },
};

// ── Matcher's-view diff: live-louder above the midline, saved-louder below ──
export const diffBands: CanvasLayer = {
  id: 'diffBands',
  z: 10,
  visible: (f) => !!f.data.diff?.timestamps_ms?.length,
  draw(f) {
    const { ctx } = f;
    const d = f.data.diff!;
    const idx = windowIndices(d.timestamps_ms, f.win.startMs, f.win.endMs);
    const mid = f.mainH / 2;

    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.18)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(0, mid); ctx.lineTo(f.w, mid); ctx.stroke();
    ctx.restore();
    if (!idx.length) return;

    // Scale pinned at ±1 so a flat line genuinely means "in sync".
    const half = (series: number[], up: boolean, style: string) => {
      ctx.beginPath();
      ctx.moveTo(f.timeToX(d.timestamps_ms[idx[0]]), mid);
      for (const i of idx) {
        const v = Math.min(1, series[i] ?? 0);
        ctx.lineTo(f.timeToX(d.timestamps_ms[i]), mid + (up ? -1 : 1) * v * mid * 0.9);
      }
      ctx.lineTo(f.timeToX(d.timestamps_ms[idx[idx.length - 1]]), mid);
      ctx.closePath();
      ctx.fillStyle = style;
      ctx.fill();
    };
    half(d.pos, true, 'rgba(52,152,219,0.45)');   // live louder than expected
    half(d.neg, false, 'rgba(230,126,34,0.45)');  // saved louder
  },
};

// ── Rolling-R confidence trace (the lock-quality signal) ─────────────────────
// Drawn over the diff canvas: r=1 at the top, r=0 at the midline (mirroring
// "no correlation" with "no diff"), colored by threshold. Gaps where the
// monitor reported null (flat/quiet span — neutral evidence).
export const rollingR: CanvasLayer = {
  id: 'rollingR',
  z: 45,
  visible: (f) => !!f.data.monitorHistory?.length,
  draw(f) {
    const { ctx } = f;
    const hist = f.data.monitorHistory!;
    const mid = f.mainH / 2;
    const yFor = (r: number) => mid - Math.max(-0.25, Math.min(1, r)) * mid * 0.9;

    // Threshold guide at min_r.
    ctx.save();
    ctx.strokeStyle = 'rgba(255,82,82,0.35)';
    ctx.setLineDash([2, 4]);
    ctx.beginPath();
    ctx.moveTo(0, yFor(MONITOR_MIN_R));
    ctx.lineTo(f.w, yFor(MONITOR_MIN_R));
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.lineWidth = 2;
    let prev: { x: number; y: number; r: number } | null = null;
    for (const p of hist) {
      if (p.ms < f.win.startMs || p.ms > f.win.endMs) { if (p.r === null) prev = null; continue; }
      if (p.r === null) { prev = null; continue; }
      const x = f.timeToX(p.ms);
      const y = yFor(p.r);
      if (prev) {
        ctx.strokeStyle = rColor(p.r);
        ctx.globalAlpha = 0.9;
        ctx.beginPath();
        ctx.moveTo(prev.x, prev.y);
        ctx.lineTo(x, y);
        ctx.stroke();
      }
      prev = { x, y, r: p.r };
    }
    // Current-value dot + label at the newest visible point.
    if (prev) {
      ctx.globalAlpha = 1;
      ctx.fillStyle = rColor(prev.r);
      ctx.beginPath();
      ctx.arc(prev.x, prev.y, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = '10px monospace';
      ctx.fillText(`r=${prev.r.toFixed(2)}`, Math.min(prev.x + 6, f.w - 52), prev.y - 5);
    }
    ctx.restore();
  },
};

// ── Per-window xcorr brackets (green NEW / blue OLD / red failed) ───────────
export const xcorrWins: CanvasLayer = {
  id: 'xcorrWins',
  z: 50,
  visible: (f) => !!f.data.xcorrWindows?.length,
  draw(f) {
    const { ctx } = f;
    ctx.save();
    for (const w of f.data.xcorrWindows!) {
      if (w.win_end < f.win.startMs || w.win_start > f.win.endMs) continue;
      const xs = f.timeToX(Math.max(w.win_start, f.win.startMs));
      const xe = f.timeToX(Math.min(w.win_end, f.win.endMs));
      const color = w.failed ? FAIL_COLOR : w.winner === 'new' ? NEW_COLOR : w.winner === 'old' ? OLD_COLOR : '#888';
      const yTop = 36;
      ctx.globalAlpha = 0.7;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(xs, yTop);
      ctx.lineTo(xs, yTop + 6);
      ctx.lineTo(xe, yTop + 6);
      ctx.lineTo(xe, yTop);
      ctx.stroke();
      if (!w.failed && w.new_offset_ms != null) {
        ctx.fillStyle = color;
        ctx.font = '9px monospace';
        const r = w.new_r != null ? Number(w.new_r).toFixed(2) : '—';
        ctx.fillText(`${w.new_offset_ms >= 0 ? '+' : ''}${w.new_offset_ms}ms r=${r}`, xs + 2, yTop + 17);
      }
    }
    ctx.restore();
  },
};

// ── Mismatch spikes: magenta recovery band + spike line ─────────────────────
export const spikes: CanvasLayer = {
  id: 'spikes',
  z: 55,
  visible: (f) => !!f.data.spikes?.length,
  draw(f) {
    const { ctx } = f;
    ctx.save();
    for (const sp of f.data.spikes!) {
      if (sp.win_end >= f.win.startMs && sp.win_start <= f.win.endMs) {
        const xs = f.timeToX(Math.max(sp.win_start, f.win.startMs));
        const xe = f.timeToX(Math.min(sp.win_end, f.win.endMs));
        ctx.globalAlpha = 0.12;
        ctx.fillStyle = SPIKE_COLOR;
        ctx.fillRect(xs, 0, Math.max(1, xe - xs), f.mainH);
        ctx.globalAlpha = 0.6;
        ctx.strokeStyle = SPIKE_COLOR;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(xs, 0); ctx.lineTo(xs, f.mainH);
        ctx.moveTo(xe, 0); ctx.lineTo(xe, f.mainH);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      if (sp.spike_ms >= f.win.startMs && sp.spike_ms <= f.win.endMs) {
        const x = f.timeToX(sp.spike_ms);
        ctx.globalAlpha = 0.95;
        ctx.strokeStyle = SPIKE_COLOR;
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, f.mainH); ctx.stroke();
        ctx.fillStyle = SPIKE_COLOR;
        ctx.font = '10px monospace';
        ctx.fillText(`spike s=${sp.strength.toFixed(2)}`, x + 3, 22);
      }
    }
    ctx.restore();
  },
};
