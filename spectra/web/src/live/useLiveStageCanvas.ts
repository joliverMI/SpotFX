/** The canvas + LiveStage renderer, as a hook — the one place that owns the
 * stage's lifecycle (construction, the draw loop, resize, frame intake,
 * disposal). Factored out of LiveView.tsx so the Live tab's Layout view and
 * the top-bar device-preview strip's expanded mode draw with the EXACT same
 * renderer and never two copies of this wiring that could drift apart
 * (captain's ask, 2026-10-06: "make the expanded preview... match the
 * layout and the format" of the Devices page's Live tab).
 *
 * Owns: the `LiveStage` instance, its rAF draw loop, a ResizeObserver, the
 * `onDevicePreviewFrame` subscription (gated on `live` so a paused/hidden
 * consumer never pushes stale frames into the stage), and `setPlan`/
 * `setSmooth` whenever those props change. Does NOT own solo, drag, the
 * link meter or anything else specific to the full Live view — those stay
 * in LiveView.tsx, called directly on the returned `stageRef`. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { onDevicePreviewFrame } from '../api/devicePreviewWs';
import { EMPTY_PLAN } from './positions';
import type { StagePlan } from './positions';
import { LiveStage } from './stage';

export interface UseLiveStageCanvasOptions {
  plan: StagePlan | null;
  /** Whether frames should actually reach the stage right now (paused/tab
   * hidden/disconnected consumers must not push stale colour). */
  live: boolean;
  smooth: boolean;
  /** Draw with the 2D canvas even where WebGL2 exists (the perf test). */
  forceCanvas?: boolean;
  /** The canvas element is actually mounted right now. Default true — a
   * caller (LiveView) that always renders its `<canvas>` never needs this;
   * one that mounts the canvas conditionally (the device-preview strip's
   * expanded mode) must flip it true only once the element exists, so the
   * stage is (re)built the moment it does. */
  active?: boolean;
  /** The plan's own layout is out of date for the stream it's receiving
   * (a cell count mismatch) — called at most once per 5s so a caller can
   * refetch without hammering the server. */
  onStale?: () => void;
}

export interface UseLiveStageCanvasResult {
  /** A CALLBACK ref, not a plain object one — a caller that mounts its
   * `<canvas>` conditionally (the device-preview strip's expanded mode,
   * gated behind data that loads after first render) needs this hook to
   * notice the moment the element actually appears. A plain `useRef`
   * object's `.current` is set by React before effects run, but mutating a
   * ref never re-triggers a dependency-array comparison — an effect that
   * found `canvasRef.current === null` on an earlier render (because the
   * element wasn't mounted THAT render) would never re-run once it
   * eventually does mount, if nothing else in its dependency array changed
   * meanwhile. Still usable exactly like a normal ref: `<canvas ref={...}>`
   * accepts a callback the same as an object. */
  canvasRef: (el: HTMLCanvasElement | null) => void;
  stageRef: React.RefObject<LiveStage | null>;
  mode: 'webgl' | 'canvas' | null;
}

export function useLiveStageCanvas(
  { plan, live, smooth, forceCanvas = false, active = true, onStale }: UseLiveStageCanvasOptions,
): UseLiveStageCanvasResult {
  const [canvasEl, setCanvasEl] = useState<HTMLCanvasElement | null>(null);
  const canvasRef = useCallback((el: HTMLCanvasElement | null) => setCanvasEl(el), []);
  const stageRef = useRef<LiveStage | null>(null);
  const liveRef = useRef(live);
  const onStaleRef = useRef(onStale);
  onStaleRef.current = onStale;
  const [mode, setMode] = useState<'webgl' | 'canvas' | null>(null);

  // The stage and its draw loop live as long as the canvas does — which, for
  // a conditionally-mounted canvas (`active`), means this effect must run
  // again once the element actually exists (hence `canvasEl`, not a ref
  // read, in the dependency array).
  useEffect(() => {
    if (!active || !canvasEl) return undefined;
    const canvas = canvasEl;
    const stage = new LiveStage(canvas, forceCanvas);
    stageRef.current = stage;
    setMode(stage.mode);
    stage.resize();
    const observer = new ResizeObserver(() => stage.resize());
    observer.observe(canvas);
    let raf = 0;
    const tick = (now: number) => {
      stage.draw(now);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    const stopFrames = onDevicePreviewFrame((frame) => {
      if (liveRef.current) stage.pushFrame(frame, performance.now());
    });
    let refetchedAt = 0;
    const staleTimer = window.setInterval(() => {
      // Frames that no longer fit the layout: ask the caller to read the
      // layout again (at most every few seconds — the old stream format
      // never fits a masked device).
      if (stage.stale && performance.now() - refetchedAt > 5000) {
        stage.stale = false;
        refetchedAt = performance.now();
        onStaleRef.current?.();
      }
    }, 500);
    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      stopFrames();
      window.clearInterval(staleTimer);
      stage.dispose();
      stageRef.current = null;
    };
  }, [forceCanvas, active, canvasEl]);

  useEffect(() => {
    stageRef.current?.setPlan(plan ?? EMPTY_PLAN);
  }, [plan, mode]);

  useEffect(() => {
    stageRef.current?.setSmooth(smooth);
  }, [smooth]);

  useEffect(() => {
    liveRef.current = live;
    if (!live) stageRef.current?.blank();
  }, [live]);

  return { canvasRef, stageRef, mode };
}
