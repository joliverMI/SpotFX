/** THE VISUAL PLANE (canvas) — data/tv-display-plan/plan.html §7's
 * architecture table: "phase 1: colour haze; phase 2: beat-aware
 * background; phase 3+: looks · mirror · Milkdrop". Phase 1 draws only the
 * colour haze — a slow, gentle two-blob gradient drift, OLED-safe (near-
 * black background, nothing holds still for more than a few seconds,
 * nothing saturated) — with no real room-colour data yet (the feed that
 * would carry it is PR 1.2). The canvas itself, and the one draw loop that
 * resizes it to its container, are what later phases draw into; nothing
 * about this component's shape should need to change when they do. */
import { useEffect, useRef } from 'react';

const BLOBS: ReadonlyArray<{ hue: number; rx: number; ry: number; speed: number; phase: number }> = [
  { hue: 265, rx: 0.32, ry: 0.42, speed: 0.021, phase: 0 },
  { hue: 320, rx: 0.28, ry: 0.36, speed: 0.017, phase: 2.4 },
];

export default function VisualPlane() {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const maybeCanvas = ref.current;
    if (!maybeCanvas) return;
    const maybeCtx = maybeCanvas.getContext('2d');
    if (!maybeCtx) return;
    // Re-bound without `| null` — closures below capture these, and TS's
    // control-flow narrowing above doesn't carry into a nested function
    // declaration even for a `const`.
    const canvas: HTMLCanvasElement = maybeCanvas;
    const ctx: CanvasRenderingContext2D = maybeCtx;

    let raf = 0;
    let stopped = false;

    function resize() {
      const { clientWidth, clientHeight } = canvas;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.round(clientWidth * dpr));
      canvas.height = Math.max(1, Math.round(clientHeight * dpr));
    }
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    function draw(tMs: number) {
      if (stopped) return;
      const t = tMs / 1000;
      const w = canvas.width;
      const h = canvas.height;
      ctx.fillStyle = '#06040b';
      ctx.fillRect(0, 0, w, h);
      BLOBS.forEach((b) => {
        const cx = w * (0.5 + 0.18 * Math.cos(t * b.speed + b.phase));
        const cy = h * (0.5 + 0.18 * Math.sin(t * b.speed * 0.8 + b.phase));
        const r = Math.max(w * b.rx, h * b.ry);
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
        g.addColorStop(0, `hsla(${b.hue}, 70%, 45%, 0.35)`);
        g.addColorStop(1, 'hsla(0, 0%, 0%, 0)');
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);
      });
      raf = requestAnimationFrame(draw);
    }
    raf = requestAnimationFrame(draw);

    return () => {
      stopped = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, []);

  return <canvas ref={ref} className="tv-visual-plane" aria-hidden="true" />;
}
