/** Builder canvas layers — faithful ports of shape_canvas.js draw() sections,
 * plus the two NEW layers: intensityBackground and the trigger intensity
 * circles. Debug-only layers (live mirror, anchors, xcorr windows, spikes)
 * have data contracts in frame.ts and are implemented when debug migrates. */
import type { CanvasFrame, CanvasLayer, Hit } from './frame';
import { AVG_COLORS, MARK_ABBR, MARK_COLOR } from './data';
import type { MarkType } from '../types';

const TRI_H = 8;
const TRI_W = 7;
export const CIRCLE_R = 5;
// Buffered hit radius: clicks near the circle always mean "drag intensity",
// so a time-drag never starts right next to it.
const CIRCLE_HIT_R = 13;
const LINE_HIT_X = 5; // px either side of the scan-line grabs the trigger

function windowIndices(ts: number[], startMs: number, endMs: number): number[] {
  const out: number[] = [];
  for (let i = 0; i < ts.length; i++) if (ts[i] >= startMs && ts[i] <= endMs) out.push(i);
  return out;
}

function maxRmsFor(f: CanvasFrame, idx: number[]): number {
  const raw = f.view.maxRms ??
    Math.max(...idx.map((i) => f.data.shape!.rms_total[i]), 1e-9);
  return raw * f.view.scales.total * f.view.scaleOverall;
}

/** Legacy semantics (shape_canvas.js): the shape offset shifts the PLAYHEAD
 * (playhead layer draws at nowMs + offsetMs); RMS data, triggers, marks and
 * librosa overlays all draw at their raw timestamps. */
const dataX = (f: CanvasFrame, ms: number) => f.timeToX(ms);

// ── 0: intensity background — total RMS / bass RMS / section energy /
//      trigger-intensity polyline (hold-scroll the ⚡ button to pick) ─────────
function drawCurve(f: CanvasFrame, pts: { x: number; y: number }[], close = true) {
  const { ctx } = f;
  if (pts.length < 2) return;
  ctx.save();
  if (close) {
    ctx.beginPath();
    ctx.moveTo(pts[0].x, f.mainH);
    for (const p of pts) ctx.lineTo(p.x, p.y);
    ctx.lineTo(pts[pts.length - 1].x, f.mainH);
    ctx.closePath();
    ctx.fillStyle = 'rgba(29,185,84,0.13)';
    ctx.fill();
  }
  ctx.strokeStyle = 'rgba(29,185,84,0.55)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
  ctx.stroke();
  ctx.restore();
}

export const intensityBackground: CanvasLayer = {
  id: 'intensityBackground',
  z: 0,
  visible: (f) => f.view.intensityMode !== 'off',
  draw(f) {
    const mode = f.view.intensityMode;
    if (mode === 'total' || mode === 'bass') {
      const shape = f.data.shape;
      if (!shape) return;
      const series = mode === 'total' ? shape.avg_rms_1s : f.data.averages?.rms_low;
      if (!series?.length) return;
      const ts = shape.timestamps_ms;
      const idx = windowIndices(ts, f.win.startMs, f.win.endMs);
      if (!idx.length) return;
      const maxRms = maxRmsFor(f, idx);
      const y = (v: number) => f.mainH - (v / maxRms) * f.mainH * 0.9;
      drawCurve(f, idx.map((i) => ({ x: dataX(f, ts[i]), y: y(series[i] ?? 0) })));
      return;
    }
    if (mode === 'section') {
      const secs = f.data.librosa?.sections;
      if (!secs?.length) return;
      const off = f.view.librosaOffsetMs;
      const y = (v: number) => f.mainH - v * f.mainH * 0.9; // energy_rms is 0-1
      const pts: { x: number; y: number }[] = [];
      for (const sec of secs) {
        pts.push({ x: f.timeToX(sec.start_ms + off), y: y(sec.energy_rms) });
        pts.push({ x: f.timeToX(sec.end_ms + off), y: y(sec.energy_rms) });
      }
      drawCurve(f, pts);
      return;
    }
    // triggers: polyline through the intensity circles (0-1 → circle Y space)
    const trigs = [...f.data.triggers].sort((a, b) => a.timestamp_ms - b.timestamp_ms);
    if (trigs.length < 2) return;
    drawCurve(f, trigs.map((t) => ({
      x: f.timeToX(t.timestamp_ms + f.view.triggerOffsetMs),
      y: circleY(f.mainH, t.intensity ?? 0.5),
    })), false);
  },
};

// ── 10: RMS fill bands ───────────────────────────────────────────────────────
export const rmsBands: CanvasLayer = {
  id: 'rmsBands',
  z: 10,
  visible: (f) => !!f.data.shape?.timestamps_ms?.length,
  draw(f) {
    const { ctx, view } = f;
    const shape = f.data.shape!;
    const ts = shape.timestamps_ms;
    const idx = windowIndices(ts, f.win.startMs, f.win.endMs);
    if (!idx.length) return;
    const maxRms = maxRmsFor(f, idx);
    const rmsToY = (v: number) => f.mainH - (v / maxRms) * f.mainH * 0.9;

    const fill = (values: number[], scale: number, style: string) => {
      ctx.beginPath();
      ctx.moveTo(dataX(f, ts[idx[0]]), f.mainH);
      for (const i of idx) ctx.lineTo(dataX(f, ts[i]), rmsToY((values[i] ?? 0) * scale * view.scaleOverall));
      ctx.lineTo(dataX(f, ts[idx[idx.length - 1]]), f.mainH);
      ctx.closePath();
      ctx.fillStyle = style;
      ctx.fill();
    };
    if (view.filters.total) fill(shape.rms_total, view.scales.total, 'rgba(150,150,150,0.4)');
    if (view.filters.bass) fill(shape.rms_low, view.scales.bass, 'rgba(46,204,113,0.45)');
    if (view.filters.mid) fill(shape.rms_mid, view.scales.mid, 'rgba(230,126,34,0.4)');
    if (view.filters.high) fill(shape.rms_high, view.scales.high, 'rgba(52,152,219,0.35)');
  },
};

// ── 20: rolling-average lines ────────────────────────────────────────────────
export const avgLines: CanvasLayer = {
  id: 'avgLines',
  z: 20,
  visible: (f) => !!f.data.averages && !!f.data.shape,
  draw(f) {
    const { ctx, view } = f;
    const shape = f.data.shape!;
    const av = f.data.averages!;
    const ts = shape.timestamps_ms;
    const idx = windowIndices(ts, f.win.startMs, f.win.endMs);
    if (!idx.length) return;
    const maxRms = maxRmsFor(f, idx);
    const rmsToY = (v: number) => f.mainH - (v / maxRms) * f.mainH * 0.9;
    const line = (values: number[], scale: number, color: string) => {
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      let first = true;
      for (const i of idx) {
        const x = dataX(f, ts[i]);
        const y = rmsToY((values[i] ?? 0) * scale * view.scaleOverall);
        if (first) { ctx.moveTo(x, y); first = false; } else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.restore();
    };
    if (view.filters.total && view.avgFilters.total) line(av.rms_total, view.scales.total, AVG_COLORS.total);
    if (view.filters.bass && view.avgFilters.bass) line(av.rms_low, view.scales.bass, AVG_COLORS.bass);
    if (view.filters.mid && view.avgFilters.mid) line(av.rms_mid, view.scales.mid, AVG_COLORS.mid);
    if (view.filters.high && view.avgFilters.high) line(av.rms_high, view.scales.high, AVG_COLORS.high);
  },
};

// ── 30: 15s/60s diamonds ─────────────────────────────────────────────────────
export const diamonds: CanvasLayer = {
  id: 'diamonds',
  z: 30,
  visible: () => true,
  draw(f) {
    const { ctx } = f;
    const cy = f.mainH / 2;
    const diamond = (x: number, rw: number, rh: number) => {
      ctx.beginPath();
      ctx.moveTo(x, cy - rh); ctx.lineTo(x + rw, cy);
      ctx.lineTo(x, cy + rh); ctx.lineTo(x - rw, cy);
      ctx.closePath(); ctx.fill();
    };
    ctx.save();
    ctx.fillStyle = 'rgba(255,255,255,0.15)';
    for (let t = Math.ceil(f.win.startMs / 15000) * 15000; t <= f.win.endMs; t += 15000) {
      if (t % 60000 === 0) continue;
      diamond(f.timeToX(t), 3, 5);
    }
    ctx.fillStyle = 'rgba(255,255,255,0.28)';
    for (let t = Math.ceil(f.win.startMs / 60000) * 60000; t <= f.win.endMs; t += 60000) {
      diamond(f.timeToX(t), 5, 8);
    }
    ctx.restore();
  },
};

// ── 40: librosa overlays ─────────────────────────────────────────────────────
export const librosaOverlays: CanvasLayer = {
  id: 'librosa',
  z: 40,
  visible: (f) => !!f.data.librosa,
  draw(f) {
    const { ctx, view } = f;
    const la = f.data.librosa!;
    const off = view.librosaOffsetMs;
    const lx = (ms: number) => f.timeToX(ms + off);
    const inWin = (ms: number) => ms + off >= f.win.startMs && ms + off <= f.win.endMs;

    if (view.librosaFilters.sections && la.sections?.length) {
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.font = '9px monospace';
      la.sections.forEach((sec, si) => {
        if (!inWin(sec.start_ms)) return;
        const x = lx(sec.start_ms);
        ctx.globalAlpha = 0.45;
        ctx.strokeStyle = '#4488ff';
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, f.mainH); ctx.stroke();
        ctx.globalAlpha = 0.65;
        ctx.fillStyle = '#4488ff';
        ctx.fillText(`S${si}`, x + 2, f.mainH - 3);
      });
      ctx.restore();
    }

    const ticksFromTop = (
      events: { ms: number }[] | undefined, get: (e: never) => number,
      minFrac: number, maxFrac: number, color: string, aBase: number, aScale: number, lw: number,
    ) => {
      if (!events?.length) return;
      const tickMin = Math.round(f.mainH * minFrac);
      const tickMax = Math.round(f.mainH * maxFrac);
      ctx.save();
      ctx.lineWidth = lw;
      ctx.strokeStyle = color;
      for (const e of events) {
        if (!inWin(e.ms)) continue;
        const v = get(e as never);
        ctx.globalAlpha = aBase + v * aScale;
        const x = lx(e.ms);
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, tickMin + Math.round((tickMax - tickMin) * v)); ctx.stroke();
      }
      ctx.restore();
    };

    type Strength = { ms: number; strength?: number };
    type Novelty = { ms: number; novelty?: number };
    if (view.librosaFilters.harmonic)
      ticksFromTop(la.harmonic_changes as Novelty[], (e: Novelty) => e.novelty ?? 0, 0.06, 0.22, '#cc66ff', 0.45, 0.4, 1.5);
    if (view.librosaFilters.mfcc && f.data.mfccDistances && la.beats?.length) {
      const md = f.data.mfccDistances;
      const tickMin = Math.round(f.mainH * 0.04);
      const tickMax = Math.round(f.mainH * 0.25);
      ctx.save();
      ctx.lineWidth = 2;
      ctx.strokeStyle = '#ff6633';
      la.beats.forEach((b, i) => {
        const d = md[i] ?? 0;
        if (d < 0.15 || !inWin(b.ms)) return;
        ctx.globalAlpha = 0.3 + d * 0.6;
        const x = lx(b.ms);
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, tickMin + Math.round((tickMax - tickMin) * d)); ctx.stroke();
      });
      ctx.restore();
    }
    if (view.librosaFilters.bass)
      ticksFromTop(la.bass_onsets as Strength[], (e: Strength) => e.strength ?? 0, 0.03, 0.16, '#44dd88', 0.25, 0.6, 1.5);
    if (view.librosaFilters.snare)
      ticksFromTop(la.snare_onsets as Strength[], (e: Strength) => e.strength ?? 0, 0.03, 0.16, '#ffdd33', 0.25, 0.6, 1.5);
    if (view.librosaFilters.onsets)
      ticksFromTop(la.onsets as Strength[], (e: Strength) => e.strength ?? 0, 0.04, 0.20, '#ff8800', 0.2, 0.55, 1);

    if (view.librosaFilters.beats && la.beats?.length) {
      ctx.save();
      ctx.lineWidth = 1;
      ctx.strokeStyle = '#ffffff';
      for (const b of la.beats) {
        if (!inWin(b.ms)) continue;
        const x = lx(b.ms);
        const tickH = Math.round(f.mainH * (b.is_downbeat ? 0.18 : 0.09));
        ctx.globalAlpha = b.is_downbeat ? 0.55 : 0.25;
        ctx.beginPath(); ctx.moveTo(x, f.mainH); ctx.lineTo(x, f.mainH - tickH); ctx.stroke();
      }
      ctx.restore();
    }
  },
};

// ── 50: music marks ──────────────────────────────────────────────────────────
export const musicMarks: CanvasLayer = {
  id: 'musicMarks',
  z: 50,
  visible: (f) => f.view.filters.marks && !!f.data.meta?.music_marks?.length,
  draw(f) {
    const { ctx, view } = f;
    ctx.save();
    ctx.font = '9px monospace';
    for (const mark of f.data.meta!.music_marks) {
      const ms = Number((mark as Record<string, unknown>).timestamp_ms ?? mark.ms ?? 0);
      const mtype = String((mark as Record<string, unknown>).mark_type ?? mark.type) as MarkType;
      if (ms < f.win.startMs || ms > f.win.endMs) continue;
      if (view.markFilters[mtype] === false) continue;
      const x = f.timeToX(ms);
      const color = MARK_COLOR[mtype] || '#fff';
      ctx.globalAlpha = 0.8;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, f.mainH); ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillStyle = color;
      ctx.fillText(MARK_ABBR[mtype] || '?', x + 2, 18);
    }
    ctx.restore();
  },
};

// ── 60: triggers (scan-lines + triangles + NEW intensity circles) ───────────
export const triggers: CanvasLayer = {
  id: 'triggers',
  z: 60,
  visible: (f) => f.data.triggers.length > 0,
  draw(f) {
    const { ctx } = f;
    for (const t of f.data.triggers) {
      const tMs = t.timestamp_ms + f.view.triggerOffsetMs;
      if (tMs < f.win.startMs || tMs > f.win.endMs) continue;
      const x = f.timeToX(tMs);
      const ev = f.data.events.find((e) => e.id === t.event_id);
      const evColor = ev?.color || '#888';

      ctx.save();
      ctx.globalAlpha = 0.45;
      ctx.strokeStyle = evColor;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, TRI_H); ctx.lineTo(x, f.mainH); ctx.stroke();
      ctx.restore();

      ctx.globalAlpha = 0.9;
      ctx.fillStyle = evColor;
      ctx.beginPath();
      ctx.moveTo(x - TRI_W / 2, 0);
      ctx.lineTo(x + TRI_W / 2, 0);
      ctx.lineTo(x, TRI_H);
      ctx.closePath();
      ctx.fill();
      ctx.globalAlpha = 1;

      // Intensity circle: y ∝ intensity on the scan-line. Drag ghosts: the
      // anchor circle follows the pointer; other SELECTED circles shift by
      // the same delta. Selected circles get an accent ring.
      const dg = f.data.draggingIntensity;
      const selected = f.data.selectedIds.includes(t.id);
      let intensity = t.intensity ?? 0.5;
      let dragging = false;
      if (dg) {
        if (dg.triggerId === t.id) {
          intensity = dg.intensity;
          dragging = true;
        } else if (selected && f.data.selectedIds.includes(dg.triggerId)) {
          intensity = Math.max(0, Math.min(1, intensity + (dg.intensity - dg.baseIntensity)));
          dragging = true;
        }
      }
      const cy = circleY(f.mainH, intensity);
      ctx.save();
      ctx.beginPath();
      ctx.arc(x, cy, dragging || selected ? CIRCLE_R + 1 : CIRCLE_R, 0, Math.PI * 2);
      ctx.fillStyle = evColor;
      ctx.globalAlpha = dragging || selected ? 1 : 0.85;
      ctx.fill();
      ctx.lineWidth = selected ? 2.5 : 1.5;
      ctx.strokeStyle = selected ? '#1db954' : '#ffffff';
      ctx.globalAlpha = dragging || selected ? 1 : 0.7;
      ctx.stroke();
      if (dragging || selected) {
        ctx.globalAlpha = 1;
        ctx.fillStyle = '#ffffff';
        ctx.font = '10px monospace';
        ctx.fillText(intensity.toFixed(2), x + CIRCLE_R + 4, cy + 3);
      }
      if (f.data.hoverTriggerId === t.id && !dragging) {
        ctx.globalAlpha = 1;
        ctx.font = '11px sans-serif';
        const name = ev?.name ?? t.event_id;
        const tw = ctx.measureText(name).width;
        const lx = Math.min(Math.max(2, x + 6), f.w - tw - 6);
        ctx.fillStyle = 'rgba(0,0,0,0.75)';
        ctx.fillRect(lx - 3, TRI_H + 4, tw + 6, 15);
        ctx.fillStyle = '#ffffff';
        ctx.fillText(name, lx, TRI_H + 15);
      }
      ctx.restore();
    }
  },
  hitTest(x, y, f): Hit {
    // Circles first (buffered radius), then anywhere on the trigger's
    // scan-line — triangle and line both start a time drag.
    for (const t of f.data.triggers) {
      const tMs = t.timestamp_ms + f.view.triggerOffsetMs;
      if (tMs < f.win.startMs || tMs > f.win.endMs) continue;
      const tx = f.timeToX(tMs);
      const cy = circleY(f.mainH, t.intensity ?? 0.5);
      if ((x - tx) ** 2 + (y - cy) ** 2 <= CIRCLE_HIT_R ** 2)
        return { kind: 'trigger-intensity', triggerId: t.id };
    }
    if (y <= f.mainH) {
      const tol = y <= TRI_H + 4 ? 6 : LINE_HIT_X; // triangle slightly wider
      let best: { id: string; d: number } | null = null;
      for (const t of f.data.triggers) {
        const tMs = t.timestamp_ms + f.view.triggerOffsetMs;
        if (tMs < f.win.startMs || tMs > f.win.endMs) continue;
        const d = Math.abs(f.timeToX(tMs) - x);
        if (d <= tol && (!best || d < best.d)) best = { id: t.id, d };
      }
      if (best) return { kind: 'trigger-triangle', triggerId: best.id };
    }
    return null;
  },
};

export function circleY(mainH: number, intensity: number): number {
  const pad = CIRCLE_R + 2;
  return pad + (1 - intensity) * (mainH - 2 * pad);
}

export function yToIntensity(mainH: number, y: number): number {
  const pad = CIRCLE_R + 2;
  const v = 1 - (y - pad) / Math.max(1, mainH - 2 * pad);
  return Math.max(0, Math.min(1, v));
}

// ── 70: calibration targets ──────────────────────────────────────────────────
export const calibration: CanvasLayer = {
  id: 'calibration',
  z: 70,
  visible: (f) => f.data.calibrationTargetsMs.length > 0,
  draw(f) {
    const { ctx } = f;
    ctx.save();
    for (const raw of f.data.calibrationTargetsMs) {
      // Legacy: calibration targets live in capture-data time → shape offset applies.
      const ms = raw + f.view.offsetMs;
      if (ms < f.win.startMs || ms > f.win.endMs) continue;
      const x = f.timeToX(ms);
      ctx.fillStyle = '#00e5ff';
      ctx.globalAlpha = 0.9;
      ctx.beginPath();
      ctx.moveTo(x - 6, f.mainH);
      ctx.lineTo(x + 6, f.mainH);
      ctx.lineTo(x, f.mainH - 10);
      ctx.closePath();
      ctx.fill();
      ctx.globalAlpha = 0.4;
      ctx.strokeStyle = '#00e5ff';
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, f.mainH); ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.restore();
  },
};

// ── 80: playhead ─────────────────────────────────────────────────────────────
export const playhead: CanvasLayer = {
  id: 'playhead',
  z: 80,
  visible: (f) => f.nowMs !== null,
  draw(f) {
    const { ctx } = f;
    const ms = f.nowMs! + f.view.offsetMs;
    if (ms >= f.win.startMs && ms <= f.win.endMs) {
      const x = f.timeToX(ms);
      ctx.save();
      ctx.globalAlpha = 0.85;
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, f.mainH); ctx.stroke();
      ctx.restore();
    } else {
      const offRight = ms > f.win.endMs;
      const dir = offRight ? 1 : -1;
      const tipX = offRight ? f.w - 1 : 1;
      ctx.save();
      ctx.globalAlpha = 0.5;
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(tipX, 0); ctx.lineTo(tipX, f.mainH); ctx.stroke();
      ctx.setLineDash([]);
      const ay = f.mainH / 2;
      ctx.globalAlpha = 0.9;
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.moveTo(tipX, ay);
      ctx.lineTo(tipX - dir * 8, ay - 6);
      ctx.lineTo(tipX - dir * 8, ay + 6);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }
  },
};

// ── 90: beat-energy heat strips ──────────────────────────────────────────────
export const beatStrips: CanvasLayer = {
  id: 'beatStrips',
  z: 90,
  visible: (f) => f.stripCount > 0,
  draw(f) {
    const { ctx, view } = f;
    const la = f.data.librosa!;
    const off = view.librosaOffsetMs;
    const minCellH = 5;
    const stripH = f.stripH - 1;
    type StripDef = { get: (b: Record<string, unknown>, i: number) => number; color: string; dbColor: string };
    const strips: StripDef[] = [
      { get: (b) => Number(b.rms_total ?? 0), color: '#ffffff', dbColor: '#aaccff' },
      { get: (b) => Number(b.rms_bass ?? 0), color: '#00ccdd', dbColor: '#66eeff' },
      { get: (b) => Number(b.onset_score ?? 0), color: '#ff8800', dbColor: '#ffbb44' },
      { get: (b) => Number(b.bass_onset_score ?? 0), color: '#44dd88', dbColor: '#88ffbb' },
      { get: (b) => Number(b.harmonic_score ?? 0), color: '#cc66ff', dbColor: '#ee99ff' },
    ];
    const hasSnare = la.beats.some((b) => (b.snare_onset_score ?? 0) > 0);
    if (view.librosaFilters.snare && hasSnare)
      strips.push({ get: (b) => Number(b.snare_onset_score ?? 0), color: '#ffdd33', dbColor: '#ffee88' });
    if (view.librosaFilters.mfcc) {
      const md = f.data.mfccDistances;
      strips.push({ get: (_b, i) => md?.[i] ?? 0.5, color: '#ff6633', dbColor: '#ff9966' });
    }

    ctx.save();
    for (let s = 0; s < strips.length; s++) {
      const baseY = f.mainH + s * f.stripH;
      const stripY = baseY + 1;
      ctx.globalAlpha = 0.25;
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, baseY); ctx.lineTo(f.w, baseY); ctx.stroke();
      ctx.globalAlpha = 0.2;
      ctx.fillStyle = '#000000';
      ctx.fillRect(0, stripY, f.w, stripH);

      const { get, color, dbColor } = strips[s];
      for (let i = 0; i < la.beats.length; i++) {
        const b = la.beats[i];
        const x0 = f.timeToX(b.ms + off);
        const x1 = i + 1 < la.beats.length
          ? f.timeToX(la.beats[i + 1].ms + off)
          : x0 + f.w / la.beats.length;
        if (x1 < 0 || x0 > f.w) continue;
        const cx0 = Math.max(0, x0);
        const cx1 = Math.min(f.w, x1 - 1);
        if (cx1 <= cx0) continue;
        const val = get(b as Record<string, unknown>, i);
        ctx.globalAlpha = 0.15 + val * 0.75;
        ctx.fillStyle = b.is_downbeat ? dbColor : color;
        ctx.fillRect(cx0, stripY, cx1 - cx0, Math.round(minCellH + val * (stripH - minCellH)));
      }
    }
    ctx.restore();
  },
  hitTest(x, y, f): Hit {
    if (y < f.mainH || !f.data.librosa?.beats?.length) return null;
    const ms = f.xToTime(x) - f.view.librosaOffsetMs;
    const la = f.data.librosa;
    let best = la.beats[0];
    for (const b of la.beats) if (Math.abs(b.ms - ms) < Math.abs(best.ms - ms)) best = b;
    return {
      kind: 'beat',
      beatMs: best.ms,
      values: {
        rms_total: best.rms_total, rms_bass: best.rms_bass,
        onset: best.onset_score, bass_onset: best.bass_onset_score ?? 0,
        harmonic: best.harmonic_score ?? 0, snare: best.snare_onset_score ?? 0,
      },
    };
  },
};

export const BUILDER_LAYERS: CanvasLayer[] = [
  intensityBackground, rmsBands, avgLines, diamonds, librosaOverlays,
  musicMarks, triggers, calibration, playhead, beatStrips,
];
