/** A footprint as a small heat grid — the Room Builder's "mapped vs not" at
 * a glance.
 *
 * It renders NUMBERS the server already computed (light_field.thumbnail: a
 * 16x9 grid normalized to the footprint's own peak), never an image and
 * never a camera frame. Normalized to its own peak on purpose: a thumbnail
 * answers "what SHAPE is this emitter's light", while "how much" is the
 * weight, shown as its own number beside it.
 *
 * Painted into a canvas rather than a grid of <span>s, the same reason
 * DevicePreviewStrip.tsx is: a per-cell DOM tree costs real time on a phone
 * and buys nothing for a static picture. */
import { useEffect, useRef } from 'react';

export default function HeatThumbnail({
  grid,
  width = 96,
  height = 54,
  title,
}: {
  grid: number[][];
  width?: number;
  height?: number;
  title?: string;
}) {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !grid.length) return;
    const rows = grid.length;
    const cols = grid[0]?.length ?? 0;
    if (!cols) return;
    canvas.width = cols;
    canvas.height = rows;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const img = ctx.createImageData(cols, rows);
    for (let y = 0; y < rows; y += 1) {
      for (let x = 0; x < cols; x += 1) {
        const v = Math.max(0, Math.min(1, grid[y][x] ?? 0));
        const i = (y * cols + x) * 4;
        // purple->white ramp, in the app's own accent family
        img.data[i] = Math.round(40 + 215 * v);
        img.data[i + 1] = Math.round(10 + 235 * v * v);
        img.data[i + 2] = Math.round(60 + 195 * v);
        img.data[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [grid]);

  if (!grid.length) {
    return (
      <div className="heat-thumb heat-thumb-empty" style={{ width, height }} title="not mapped">
        not mapped
      </div>
    );
  }
  return (
    <canvas
      ref={ref}
      className="heat-thumb"
      title={title}
      style={{ width, height, imageRendering: 'pixelated' }}
    />
  );
}
