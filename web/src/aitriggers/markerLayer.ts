/** Suggestion-marker canvas layer (port of shape_canvas.js setCustomMarkers):
 * a vertical line + top triangle per suggestion, colored by review state,
 * with an event-color dot under the triangle. Hit-testing returns the
 * suggestion index so ReviewPanel can drag/highlight. */
import type { CanvasLayer, Hit } from '../builder/canvas/frame';

const HIT_X = 6;

export const aiMarkers: CanvasLayer = {
  id: 'aiMarkers',
  z: 65,
  visible: (f) => !!f.data.aiMarkers?.length,
  draw(f) {
    const { ctx } = f;
    ctx.save();
    f.data.aiMarkers!.forEach((m) => {
      if (m.ms < f.win.startMs || m.ms > f.win.endMs) return;
      const x = f.timeToX(m.ms);
      ctx.globalAlpha = m.highlighted ? 1 : 0.75;
      ctx.strokeStyle = m.color;
      ctx.lineWidth = m.highlighted ? 2 : 1;
      ctx.beginPath();
      ctx.moveTo(x, 8);
      ctx.lineTo(x, f.mainH);
      ctx.stroke();
      // Top triangle in state color
      ctx.fillStyle = m.color;
      ctx.beginPath();
      ctx.moveTo(x - 5, 0);
      ctx.lineTo(x + 5, 0);
      ctx.lineTo(x, 8);
      ctx.closePath();
      ctx.fill();
      // Event-color dot under the triangle
      if (m.eventColor) {
        ctx.globalAlpha = 1;
        ctx.fillStyle = m.eventColor;
        ctx.beginPath();
        ctx.arc(x, 14, 3, 0, Math.PI * 2);
        ctx.fill();
      }
    });
    ctx.restore();
  },
  hitTest(x, y, f): Hit {
    if (!f.data.aiMarkers?.length || y > f.mainH) return null;
    let best: { index: number; d: number } | null = null;
    f.data.aiMarkers.forEach((m, i) => {
      if (m.ms < f.win.startMs || m.ms > f.win.endMs) return;
      const d = Math.abs(f.timeToX(m.ms) - x);
      if (d <= HIT_X && (!best || d < best.d)) best = { index: i, d };
    });
    return best ? { kind: 'ai-marker', index: (best as { index: number }).index } : null;
  },
};
