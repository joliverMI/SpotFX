/** THE LIGHT SHOW's High/Low Trigger markers on the audio-shape canvas —
 * see ../lightShowMarkers.ts's module docstring for what "armed" means
 * and why a cue is drawn whether or not anything is armed on it. A SOLID
 * line + filled flag is armed ("fires here"); a faint dashed line + outline
 * flag is not.
 *
 * DRAGGABLE SINCE 2026-10-08 (the Admiral: "i can't seem to move the marker
 * on the audio shape") — hitTest only ever returns a hit when NO trigger's
 * own scan-line is already there: the `triggers` layer (./layers.ts, z=60,
 * checked first since TimelineCanvas.tsx's hitTest walks layers by z
 * DESCENDING) still wins whenever a SPECTRA trigger sits under this flag,
 * so a trigger under it still drags exactly as before — this layer (z=41)
 * only ever gets a look when the triggers layer found nothing nearby. The
 * hit tolerance is touch-sized (FLAG_HIT_PX), well past the drawn glyph's
 * own width, mirroring the triggers layer's own scan-line convention (the
 * whole vertical line is grabbable, not just the small flag glyph). The
 * actual drag lives in ../hooks/useLightShowDrag.ts. */
import type { CanvasFrame, CanvasLayer } from './frame';
import { LIGHT_SHOW_COLOR } from '../lightShowMarkers';
import { mmss } from '../../lightshow/showSummary';

const MARKER_HOVER_PX = 6;
const FLAG_HALF_W = 5;
const FLAG_H = 7;
/** Touch-sized grab tolerance for the flag's scan-line — bigger than the
 *  drawn FLAG_HALF_W, matching the triggers layer's own LINE_HIT_X/
 *  CIRCLE_HIT_R touch-friendliness (see ./layers.ts). */
const FLAG_HIT_PX = 14;

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
    const drag = f.data.lightShowDrag;
    ctx.save();
    for (const m of f.data.lightShow!) {
      // While this flag is being dragged on the canvas, draw it at the
      // live ghost position instead of its still-unsaved stored ms.
      const ms = drag && drag.level === m.level ? drag.ms : m.ms;
      if (ms < f.win.startMs || ms > f.win.endMs) continue;
      drawFlag(f, f.timeToX(ms), m.level, m.armed);
    }
    if (drag) {
      const x = f.timeToX(drag.ms);
      ctx.globalAlpha = 1;
      ctx.fillStyle = '#ffffff';
      ctx.font = '10px monospace';
      ctx.fillText(mmss(drag.ms), x + FLAG_HALF_W + 4, FLAG_H + 11);
    }
    ctx.restore();
  },
  hitTest(x, y, f) {
    if (y > f.mainH) return null;
    let best: { d: number; level: 'high' | 'low'; ms: number } | null = null;
    for (const m of f.data.lightShow ?? []) {
      if (m.ms < f.win.startMs || m.ms > f.win.endMs) continue;
      const d = Math.abs(f.timeToX(m.ms) - x);
      if (d <= FLAG_HIT_PX && (!best || d < best.d)) best = { d, level: m.level, ms: m.ms };
    }
    return best ? { kind: 'light-show-flag', level: best.level, ms: best.ms } : null;
  },
  tooltipAt(x, _y, f) {
    if (f.data.lightShowDrag) return null; // the readout above speaks for it
    let best: { d: number; text: string } | null = null;
    for (const m of f.data.lightShow ?? []) {
      if (m.ms < f.win.startMs || m.ms > f.win.endMs) continue;
      const d = Math.abs(f.timeToX(m.ms) - x);
      if (d <= MARKER_HOVER_PX && (!best || d < best.d)) best = { d, text: m.title };
    }
    return best ? best.text : null;
  },
};
