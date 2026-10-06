/** THE LIGHT SHOW's High/Low Trigger markers on the audio-shape canvas —
 * see ../lightShowMarkers.ts's module docstring for what "armed" means
 * and why a cue is drawn whether or not anything is armed on it. A SOLID
 * line + filled flag is armed ("fires here"); a faint dashed line + outline
 * flag is not. Never a click target (tooltipAt only), so a trigger under
 * it still drags. */
import type { CanvasFrame, CanvasLayer } from './frame';
import { LIGHT_SHOW_COLOR } from '../lightShowMarkers';

const MARKER_HOVER_PX = 6;
const FLAG_HALF_W = 5;
const FLAG_H = 7;

function drawFlag(f: CanvasFrame, x: number, level: 'high' | 'low', armed: boolean): void {
  const { ctx } = f;
  const color = LIGHT_SHOW_COLOR[level];
  ctx.globalAlpha = armed ? 0.95 : 0.4;
  ctx.strokeStyle = color;
  ctx.lineWidth = armed ? 2 : 1.25;
  ctx.setLineDash(armed ? [] : [4, 3]);
  ctx.beginPath();
  ctx.moveTo(x, 0);
  ctx.lineTo(x, f.mainH);
  ctx.stroke();
  ctx.setLineDash([]);

  // ▲ up for High, ▼ down for Low — the exact glyph ShowCueBar.tsx draws
  // on its own strip, so the two surfaces read as one feature.
  ctx.beginPath();
  if (level === 'high') {
    ctx.moveTo(x - FLAG_HALF_W, FLAG_H);
    ctx.lineTo(x + FLAG_HALF_W, FLAG_H);
    ctx.lineTo(x, 0);
  } else {
    ctx.moveTo(x - FLAG_HALF_W, 0);
    ctx.lineTo(x + FLAG_HALF_W, 0);
    ctx.lineTo(x, FLAG_H);
  }
  ctx.closePath();
  if (armed) {
    ctx.fillStyle = color;
    ctx.fill();
  } else {
    ctx.globalAlpha = 0.7;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.25;
    ctx.stroke();
  }
}

export const lightShowMarkers: CanvasLayer = {
  id: 'lightShowMarkers',
  z: 41,
  visible: (f) => !!f.data.lightShow?.length,
  draw(f) {
    const { ctx } = f;
    ctx.save();
    for (const m of f.data.lightShow!) {
      if (m.ms < f.win.startMs || m.ms > f.win.endMs) continue;
      drawFlag(f, f.timeToX(m.ms), m.level, m.armed);
    }
    ctx.restore();
  },
  tooltipAt(x, _y, f) {
    let best: { d: number; text: string } | null = null;
    for (const m of f.data.lightShow ?? []) {
      if (m.ms < f.win.startMs || m.ms > f.win.endMs) continue;
      const d = Math.abs(f.timeToX(m.ms) - x);
      if (d <= MARKER_HOVER_PX && (!best || d < best.d)) best = { d, text: m.title };
    }
    return best ? best.text : null;
  },
};
