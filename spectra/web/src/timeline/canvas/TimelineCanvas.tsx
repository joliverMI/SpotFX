/** The layered timeline canvas: DPR-aware, rAF-driven (fast-changing values —
 * playhead + follow window — are pulled via getter refs so React re-renders
 * only on slow state). Interactions are delegated to the `pointer` prop. */
import { useEffect, useRef } from 'react';
import type { CanvasFrame, CanvasLayer, Hit, LayerDataBag, ViewState, Win } from './frame';
import { BEAT_STRIP_H, snapRailHFor, stripCountFor } from './frame';
import { panDeltaMs, resolveTouchPanLock } from './touchPan';

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
  /** The pointer moving with no button down, anywhere on the canvas (the
   *  drop-sequence layer's add-a-drop preview). */
  onIdleMove?: (x: number, y: number, frame: FrameGeom) => void;
  /** The cursor for a hover hit (undefined = the default). */
  cursorFor?: (hit: Hit) => string | undefined;
}

/** Geometry snapshot handed to interaction callbacks. */
export interface FrameGeom {
  w: number;
  h: number;
  mainH: number;
  /** the drop-sequence snap-rail band under the main area (0 when off) */
  railH: number;
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
    const railH = snapRailHFor(s.data);
    const mainH = h - stripCount * BEAT_STRIP_H - railH;
    const win = s.getWin();
    const span = Math.max(1, win.endMs - win.startMs);
    return {
      w, h, mainH, railH, win,
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
            railH: g.railH,
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

  // A hover name for a spot no layer hit-tests (layer.tooltipAt — e.g. the
  // planned-event markers' rank), shown as the canvas's own title.
  const tooltipAt = (x: number, y: number): string | null => {
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
    for (const layer of [...s.layers].sort((a, b) => b.z - a.z)) {
      if (!layer.tooltipAt || !layer.visible(frame)) continue;
      const text = layer.tooltipAt(x, y, frame);
      if (text) return text;
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
    // The pointer actually driving the current drag — a second, unrelated
    // pointer's own move/up/cancel (a resting palm beside a panning finger)
    // must never touch state that belongs to this one.
    let draggingPointerId: number | null = null;
    let panStart: { pointerId: number; x: number; winStart: number; winEnd: number } | null = null;
    // A single-finger touch that lands on nothing draggable is a PAN
    // CANDIDATE until it's moved enough to say which way (see touchPan.ts).
    // Only ever armed when the hit test came back empty, so it can never
    // fight a marker drag — that branch below never reaches this one.
    let touchCandidate: { pointerId: number; x: number; y: number; winStart: number; winEnd: number } | null = null;

    const down = (ev: PointerEvent) => {
      const s = stateRef.current;
      const g = geom();
      if (!g) return;
      const { x, y } = rel(ev);
      if (ev.button === 1) {
        // middle-drag pan
        panStart = { pointerId: ev.pointerId, x, winStart: g.win.startMs, winEnd: g.win.endMs };
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
          draggingPointerId = ev.pointerId;
          canvas.setPointerCapture(ev.pointerId);
        }
        ev.preventDefault();
        return;
      }
      if (ev.button !== 0) return;
      const hit = hitTest(x, y);
      s.pointer?.onHit?.(hit, ev, g);
      if (hit && (hit.kind === 'trigger-intensity' || hit.kind === 'trigger-triangle' || hit.kind === 'ai-marker'
                  || hit.kind === 'light-show-flag' || (hit.kind === 'drop-seq' && !hit.chip))) {
        dragging = true;
        draggingPointerId = ev.pointerId;
        canvas.setPointerCapture(ev.pointerId);
        // The canvas is touch-action: pan-y (so an empty-graph vertical
        // swipe can scroll the page — see the touch pan candidate below);
        // a marker drag must still own every move of ITS OWN gesture, or
        // a vertical intensity drag would race the browser's native pan.
        ev.preventDefault();
        return;
      }
      if (ev.pointerType === 'touch' && !hit) {
        touchCandidate = { pointerId: ev.pointerId, x, y, winStart: g.win.startMs, winEnd: g.win.endMs };
      }
    };
    const move = (ev: PointerEvent) => {
      const s = stateRef.current;
      const g = geom();
      if (!g) return;
      if (panStart && ev.pointerId === panStart.pointerId) {
        const { x } = rel(ev);
        const deltaMs = panDeltaMs(x, panStart.x, g.w, panStart.winStart, panStart.winEnd);
        s.pointer?.onPan?.(deltaMs);
        panStart = { ...panStart, x };
        return;
      }
      if (dragging && ev.pointerId === draggingPointerId) {
        s.pointer?.onDragMove?.(ev, g);
        return;
      }
      if (touchCandidate && ev.pointerId === touchCandidate.pointerId) {
        const { x, y } = rel(ev);
        const lock = resolveTouchPanLock(x - touchCandidate.x, y - touchCandidate.y);
        if (lock === 'pan') {
          // Lock in: apply this move's own delta right away (no dead zone)
          // and hand off to the ordinary panStart path from here on.
          ev.preventDefault();
          canvas.setPointerCapture(touchCandidate.pointerId);
          const deltaMs = panDeltaMs(x, touchCandidate.x, g.w, touchCandidate.winStart, touchCandidate.winEnd);
          s.pointer?.onPan?.(deltaMs);
          panStart = { pointerId: touchCandidate.pointerId, x, winStart: touchCandidate.winStart, winEnd: touchCandidate.winEnd };
          touchCandidate = null;
        } else if (lock === 'vertical') {
          // Resolved to a page scroll — never call preventDefault, and
          // stop checking; the browser (touch-action: pan-y) takes it.
          touchCandidate = null;
        }
        return;
      }
      // idle hover (no buttons) — trigger name labels
      if (ev.buttons === 0) {
        const { x, y } = rel(ev);
        const hit = hitTest(x, y);
        s.pointer?.onHoverMove?.(hit);
        s.pointer?.onIdleMove?.(x, y, g);
        const cursor = s.pointer?.cursorFor?.(hit) ?? '';
        if (canvas.style.cursor !== cursor) canvas.style.cursor = cursor;
        const tip = hit ? null : tooltipAt(x, y);
        if ((canvas.title || null) !== tip) canvas.title = tip ?? '';
      }
    };
    const up = (ev: PointerEvent) => {
      const s = stateRef.current;
      const g = geom();
      if (panStart && ev.pointerId === panStart.pointerId) panStart = null;
      if (touchCandidate && ev.pointerId === touchCandidate.pointerId) touchCandidate = null;
      if (dragging && ev.pointerId === draggingPointerId && g) {
        dragging = false;
        draggingPointerId = null;
        s.pointer?.onDragEnd?.(ev, g);
      }
    };
    // A touch gesture the browser takes over (e.g. mid-drag, if it ever
    // decides to) fires this instead of pointerup — without it `dragging`
    // (or a pan) could stick forever with no pointerup to clear it.
    const cancel = (ev: PointerEvent) => up(ev);
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
    canvas.addEventListener('pointercancel', cancel);
    canvas.addEventListener('dblclick', dbl);
    canvas.addEventListener('contextmenu', ctxMenu);
    return () => {
      canvas.removeEventListener('pointerdown', down);
      canvas.removeEventListener('pointermove', move);
      canvas.removeEventListener('pointerup', up);
      canvas.removeEventListener('pointercancel', cancel);
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
        // 'pan-y' (not 'none'): a single-finger touch on empty graph pans
        // the window horizontally (JS, see touchPan.ts) OR is left to the
        // browser's own vertical page scroll, decided by direction lock in
        // move() above. Every drag branch (markers, flares, the mouse pans)
        // calls preventDefault() itself, so this never races an in-progress
        // drag — it only ever governs an UNDECIDED empty-graph touch.
        touchAction: 'pan-y',
      }}
    />
  );
}
