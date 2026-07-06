/** The layered timeline canvas: DPR-aware, rAF-driven (fast-changing values —
 * playhead + follow window — are pulled via getter refs so React re-renders
 * only on slow state). Interactions are delegated to the `pointer` prop. */
import { useEffect, useRef } from 'react';
import type { CanvasFrame, CanvasLayer, Hit, LayerDataBag, ViewState, Win } from './frame';
import { BEAT_STRIP_H, stripCountFor } from './frame';

export interface PointerHandlers {
  onHit?: (hit: Hit, ev: PointerEvent, frame: FrameGeom) => void;
  onHoverMove?: (hit: Hit) => void;
  onDoubleClick?: (ms: number, y: number, hit: Hit, frame: FrameGeom) => void;
  /** Right-click. May return a trigger id to start an intensity drag on it
   * (hold-the-right-button-and-slide placement). */
  onContextMenu?: (ms: number, hit: Hit, y?: number, frame?: FrameGeom) => string | void;
  onDragMove?: (ev: PointerEvent, frame: FrameGeom) => void;
  onDragEnd?: (ev: PointerEvent, frame: FrameGeom) => void;
  onPan?: (deltaMs: number) => void;
}

/** Geometry snapshot handed to interaction callbacks. */
export interface FrameGeom {
  w: number;
  h: number;
  mainH: number;
  win: Win;
  timeToX(ms: number): number;
  xToTime(x: number): number;
}

export default function TimelineCanvas({
  layers,
  data,
  view,
  getWin,
  getNowMs,
  height,
  pointer,
}: {
  layers: CanvasLayer[];
  data: LayerDataBag;
  view: ViewState;
  getWin: () => Win;
  getNowMs: () => number | null;
  height: number;
  pointer?: PointerHandlers;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef({ layers, data, view, getWin, getNowMs, pointer });
  stateRef.current = { layers, data, view, getWin, getNowMs, pointer };

  const geom = (): FrameGeom | null => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const s = stateRef.current;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const stripCount = stripCountFor(s.data, s.view.librosaFilters);
    const mainH = h - stripCount * BEAT_STRIP_H;
    const win = s.getWin();
    const span = Math.max(1, win.endMs - win.startMs);
    return {
      w, h, mainH, win,
      timeToX: (ms) => ((ms - win.startMs) / span) * w,
      xToTime: (x) => win.startMs + (x / Math.max(1, w)) * span,
    };
  };

  // rAF draw loop
  useEffect(() => {
    let raf = 0;
    const loop = () => {
      const canvas = canvasRef.current;
      const s = stateRef.current;
      if (canvas) {
        const dpr = window.devicePixelRatio || 1;
        const w = canvas.clientWidth;
        const h = canvas.clientHeight;
        if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
          canvas.width = Math.round(w * dpr);
          canvas.height = Math.round(h * dpr);
        }
        const ctx = canvas.getContext('2d');
        if (ctx && w > 0) {
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          ctx.clearRect(0, 0, w, h);
          const g = geom()!;
          const frame: CanvasFrame = {
            ctx, w, h,
            mainH: g.mainH,
            stripH: BEAT_STRIP_H,
            stripCount: stripCountFor(s.data, s.view.librosaFilters),
            win: g.win,
            timeToX: g.timeToX,
            xToTime: g.xToTime,
            nowMs: s.getNowMs(),
            data: s.data,
            view: s.view,
          };
          for (const layer of s.layers) {
            if (layer.visible(frame)) {
              try { layer.draw(frame); } catch { /* one bad layer must not kill the loop */ }
            }
          }
        }
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  const hitTest = (x: number, y: number): Hit => {
    const s = stateRef.current;
    const g = geom();
    if (!g) return null;
    const frame = {
      ...g,
      ctx: null as unknown as CanvasRenderingContext2D,
      stripH: BEAT_STRIP_H,
      stripCount: stripCountFor(s.data, s.view.librosaFilters),
      nowMs: s.getNowMs(),
      data: s.data,
      view: s.view,
    } as CanvasFrame;
    const ordered = [...s.layers].sort((a, b) => b.z - a.z);
    for (const layer of ordered) {
      const hit = layer.hitTest?.(x, y, frame);
      if (hit) return hit;
    }
    return null;
  };

  // Pointer plumbing — semantic interpretation lives in the page (interactions.ts).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rel = (ev: PointerEvent | MouseEvent) => {
      const r = canvas.getBoundingClientRect();
      return { x: ev.clientX - r.left, y: ev.clientY - r.top };
    };
    let dragging = false;
    let panStart: { x: number; winStart: number; winEnd: number } | null = null;

    const down = (ev: PointerEvent) => {
      const s = stateRef.current;
      const g = geom();
      if (!g) return;
      const { x, y } = rel(ev);
      if (ev.button === 1) {
        // middle-drag pan
        panStart = { x, winStart: g.win.startMs, winEnd: g.win.endMs };
        canvas.setPointerCapture(ev.pointerId);
        ev.preventDefault();
        return;
      }
      if (ev.button === 2) {
        // Context action fires on press (not the contextmenu event) so a
        // placed trigger can be intensity-dragged while the button is held.
        const dragId = s.pointer?.onContextMenu?.(g.xToTime(x), hitTest(x, y), y, g);
        if (typeof dragId === 'string') {
          dragging = true;
          canvas.setPointerCapture(ev.pointerId);
        }
        ev.preventDefault();
        return;
      }
      if (ev.button !== 0) return;
      const hit = hitTest(x, y);
      s.pointer?.onHit?.(hit, ev, g);
      if (hit && (hit.kind === 'trigger-intensity' || hit.kind === 'trigger-triangle')) {
        dragging = true;
        canvas.setPointerCapture(ev.pointerId);
      }
    };
    const move = (ev: PointerEvent) => {
      const s = stateRef.current;
      const g = geom();
      if (!g) return;
      if (panStart) {
        const { x } = rel(ev);
        const span = panStart.winEnd - panStart.winStart;
        // Drag right → window moves right (reversed per user preference).
        const deltaMs = ((x - panStart.x) / Math.max(1, g.w)) * span;
        s.pointer?.onPan?.(deltaMs);
        panStart = { ...panStart, x };
        return;
      }
      if (dragging) {
        s.pointer?.onDragMove?.(ev, g);
        return;
      }
      // idle hover (no buttons) — trigger name labels
      if (ev.buttons === 0) {
        const { x, y } = rel(ev);
        s.pointer?.onHoverMove?.(hitTest(x, y));
      }
    };
    const up = (ev: PointerEvent) => {
      const s = stateRef.current;
      const g = geom();
      panStart = null;
      if (dragging && g) {
        dragging = false;
        s.pointer?.onDragEnd?.(ev, g);
      }
    };
    const dbl = (ev: MouseEvent) => {
      const s = stateRef.current;
      const g = geom();
      if (!g) return;
      const { x, y } = rel(ev);
      s.pointer?.onDoubleClick?.(g.xToTime(x), y, hitTest(x, y), g);
    };
    // The action already ran on pointerdown; just keep the menu suppressed.
    const ctxMenu = (ev: MouseEvent) => ev.preventDefault();

    canvas.addEventListener('pointerdown', down);
    canvas.addEventListener('pointermove', move);
    canvas.addEventListener('pointerup', up);
    canvas.addEventListener('dblclick', dbl);
    canvas.addEventListener('contextmenu', ctxMenu);
    return () => {
      canvas.removeEventListener('pointerdown', down);
      canvas.removeEventListener('pointermove', move);
      canvas.removeEventListener('pointerup', up);
      canvas.removeEventListener('dblclick', dbl);
      canvas.removeEventListener('contextmenu', ctxMenu);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{
        width: '100%',
        height,
        display: 'block',
        background: '#101010',
        borderRadius: 6,
        touchAction: 'none',
      }}
    />
  );
}
