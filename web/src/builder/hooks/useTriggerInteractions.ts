/** Canvas trigger interactions (Phase 2):
 *  - intensity circle drag → vertical only, live ghost + numeric, snap 0.5 ±0.02
 *  - triangle drag → time only (20ms grid + Y-region librosa snap), drag out = delete
 *  - dblclick → edit near a trigger (10px), else create at snapped time
 *  - right-click → reassign/place the armed palette event
 * Hit priority comes from layer z-order (circle > triangle > beat strip). */
import { useRef, useState } from 'react';
import type { PointerHandlers, FrameGeom } from '../canvas/TimelineCanvas';
import type { Hit } from '../canvas/frame';
import { yToIntensity } from '../canvas/layers';
import { snapTimestamp } from '../canvas/data';
import { useBuilderStore } from '../store';
import { uuid } from '../../lib/uid';
import type { LibrosaAnalysis } from '../types';

interface Drag {
  mode: 'intensity' | 'time';
  triggerId: string;
  outOfBounds: boolean;
}

export function useTriggerInteractions(opts: {
  getLibrosa: () => LibrosaAnalysis | null;
  getLibrosaOffsetMs: () => number;
  getArmedEventId: () => string | null;
  onBeatTip: (tip: { ms: number; values: Record<string, number> } | null) => void;
}) {
  const drag = useRef<Drag | null>(null);
  const [draggingIntensity, setDraggingIntensity] =
    useState<{ triggerId: string; intensity: number } | null>(null);

  const mutateWorking = useBuilderStore((s) => s.mutateWorking);
  const setEditingTrigger = useBuilderStore((s) => s.setEditingTrigger);

  const rel = (ev: PointerEvent) => {
    const r = (ev.target as HTMLElement).getBoundingClientRect();
    return { x: ev.clientX - r.left, y: ev.clientY - r.top };
  };

  const snap = (rawMs: number, y: number, g: FrameGeom) =>
    snapTimestamp(Math.round(rawMs / 20) * 20, y, {
      librosa: opts.getLibrosa(),
      librosaOffsetMs: opts.getLibrosaOffsetMs(),
      mainH: g.mainH,
      win: g.win,
      canvasW: g.w,
    });

  const nearTriggerId = (ms: number, g: FrameGeom): string | null => {
    const triggers = useBuilderStore.getState().workingTriggers();
    const x = g.timeToX(ms);
    let best: { id: string; d: number } | null = null;
    for (const t of triggers) {
      const d = Math.abs(g.timeToX(t.timestamp_ms) - x);
      if (d <= 10 && (!best || d < best.d)) best = { id: t.id, d };
    }
    return best?.id ?? null;
  };

  const pointer: PointerHandlers = {
    onHit: (hit: Hit) => {
      if (hit?.kind === 'beat') {
        opts.onBeatTip({ ms: hit.beatMs, values: hit.values });
        return;
      }
      opts.onBeatTip(null);
      if (hit?.kind === 'trigger-intensity') {
        drag.current = { mode: 'intensity', triggerId: hit.triggerId, outOfBounds: false };
      } else if (hit?.kind === 'trigger-triangle') {
        drag.current = { mode: 'time', triggerId: hit.triggerId, outOfBounds: false };
      }
    },

    onDragMove: (ev, g) => {
      const d = drag.current;
      if (!d) return;
      const { x, y } = rel(ev);
      if (d.mode === 'intensity') {
        setDraggingIntensity({ triggerId: d.triggerId, intensity: yToIntensity(g.mainH, y) });
        return;
      }
      // time drag: out of vertical bounds arms delete-on-release (legacy)
      d.outOfBounds = y < -24 || y > g.h + 24;
      const ms = Math.max(0, snap(g.xToTime(x), y, g));
      mutateWorking((triggers) => {
        const t = triggers.find((tt) => tt.id === d.triggerId);
        if (t) t.timestamp_ms = ms;
      });
    },

    onDragEnd: (ev, g) => {
      const d = drag.current;
      drag.current = null;
      if (!d) return;
      if (d.mode === 'intensity') {
        const { y } = rel(ev);
        let v = yToIntensity(g.mainH, y);
        if (Math.abs(v - 0.5) <= 0.02) v = 0.5; // snap mid
        v = Math.round(v * 100) / 100;
        setDraggingIntensity(null);
        mutateWorking((triggers) => {
          const t = triggers.find((tt) => tt.id === d.triggerId);
          if (t) t.intensity = v;
        });
        return;
      }
      if (d.outOfBounds) {
        mutateWorking((triggers) => {
          const i = triggers.findIndex((tt) => tt.id === d.triggerId);
          if (i >= 0) triggers.splice(i, 1);
        });
      }
    },

    onDoubleClick: (ms, y, _hit, g) => {
      const near = nearTriggerId(ms, g);
      if (near) {
        setEditingTrigger(near);
        return;
      }
      setEditingTrigger(`new:${Math.max(0, snap(ms, y, g))}`);
    },

    onContextMenu: (ms, hit) => {
      const armed = opts.getArmedEventId();
      if (!armed) return;
      if (hit?.kind === 'trigger-triangle' || hit?.kind === 'trigger-intensity') {
        mutateWorking((triggers) => {
          const t = triggers.find((tt) => tt.id === hit.triggerId);
          if (t) t.event_id = armed;
        });
        return;
      }
      mutateWorking((triggers) => {
        triggers.push({
          id: uuid(), timestamp_ms: Math.max(0, Math.round(ms / 20) * 20),
          event_id: armed, labels: [], enabled: true, intensity: 0.5,
        });
      });
    },
  };

  return { pointer, draggingIntensity };
}
