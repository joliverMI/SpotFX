/** Canvas trigger interactions:
 *  - intensity circle drag → vertical only; snaps to 0.5 AND to the previous
 *    trigger's intensity when within 0.1; dragging a selected circle moves
 *    every selected circle by the same delta
 *  - clicking a circle selects it (canvas click elsewhere deselects)
 *  - triangle/scan-line drag → time (20ms grid + Y-region librosa snap),
 *    drag out of the canvas = delete
 *  - dblclick → edit near a trigger (10px), else create at snapped time
 *  - right-click → place the armed palette event: time snaps to the nearest
 *    bass onset, intensity starts at the SECTION ENERGY level (fallback:
 *    click Y); holding the right button slides the circle until release */
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
  baseIntensity: number;
  multi: boolean;
  outOfBounds: boolean;
  /** Intensity drags only commit after real movement (>3px), so a plain
   * press-release never nudges the value. */
  moved: boolean;
  startY: number | null;
}

const clamp01 = (v: number) => Math.max(0, Math.min(1, Math.round(v * 100) / 100));

export function useTriggerInteractions(opts: {
  getLibrosa: () => LibrosaAnalysis | null;
  getLibrosaOffsetMs: () => number;
  getArmedEventId: () => string | null;
  onBeatTip: (tip: { ms: number; values: Record<string, number> } | null) => void;
  onHover: (triggerId: string | null) => void;
}) {
  const drag = useRef<Drag | null>(null);
  const hoverRef = useRef<string | null>(null);
  const [draggingIntensity, setDraggingIntensity] =
    useState<{ triggerId: string; intensity: number; baseIntensity: number } | null>(null);

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

  /** Snap an intensity to the PREVIOUS trigger's value when within 0.1
   * (0.5 mid-snap stays as a fallback). */
  const snapIntensity = (v: number, triggerId: string): number => {
    const ts = [...useBuilderStore.getState().workingTriggers()]
      .sort((a, b) => a.timestamp_ms - b.timestamp_ms);
    const idx = ts.findIndex((t) => t.id === triggerId);
    if (idx > 0) {
      const prev = ts[idx - 1].intensity ?? 0.5;
      if (Math.abs(v - prev) <= 0.1) return clamp01(prev);
    }
    if (Math.abs(v - 0.5) <= 0.02) return 0.5;
    return clamp01(v);
  };

  /** Nearest bass onset (fallback: any onset, then raw) for right-click placement. */
  const snapToBassOnset = (rawMs: number): number => {
    const la = opts.getLibrosa();
    const off = opts.getLibrosaOffsetMs();
    const pools = [la?.bass_onsets as { ms: number }[] | undefined, la?.onsets];
    for (const pool of pools) {
      if (!pool?.length) continue;
      let best: number | null = null;
      let bestD = 1500; // cap the snap radius at 1.5s
      for (const o of pool) {
        const d = Math.abs(o.ms + off - rawMs);
        if (d < bestD) { bestD = d; best = o.ms + off; }
      }
      if (best !== null) return Math.round(best);
    }
    return Math.round(rawMs / 20) * 20;
  };

  /** Section energy (0-1) at a timestamp — the level the section curve draws. */
  const sectionEnergyAt = (ms: number): number | null => {
    const secs = opts.getLibrosa()?.sections;
    if (!secs?.length) return null;
    const off = opts.getLibrosaOffsetMs();
    for (const s of secs) {
      if (ms >= s.start_ms + off && ms <= s.end_ms + off) return clamp01(s.energy_rms);
    }
    return null;
  };

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
      const st = useBuilderStore.getState();
      if (hit?.kind === 'beat') {
        opts.onBeatTip({ ms: hit.beatMs, values: hit.values });
        return;
      }
      opts.onBeatTip(null);
      if (hit?.kind === 'trigger-intensity') {
        const t = st.workingTriggers().find((tt) => tt.id === hit.triggerId);
        const base = t?.intensity ?? 0.5;
        const inSelection = st.selectedIds.includes(hit.triggerId);
        if (!inSelection) st.setSelection([hit.triggerId], hit.triggerId);
        else st.setSelection(st.selectedIds, hit.triggerId);
        drag.current = {
          mode: 'intensity', triggerId: hit.triggerId, baseIntensity: base,
          multi: inSelection && st.selectedIds.length > 1, outOfBounds: false,
          moved: false, startY: null,
        };
      } else if (hit?.kind === 'trigger-triangle') {
        drag.current = { mode: 'time', triggerId: hit.triggerId, baseIntensity: 0,
          multi: false, outOfBounds: false, moved: false, startY: null };
      } else {
        // click on empty canvas clears the selection
        if (st.selectedIds.length) st.setSelection([]);
      }
    },

    onHoverMove: (hit: Hit) => {
      const id = hit && (hit.kind === 'trigger-intensity' || hit.kind === 'trigger-triangle')
        ? hit.triggerId : null;
      if (id !== hoverRef.current) {
        hoverRef.current = id;
        opts.onHover(id);
      }
    },

    onDragMove: (ev, g) => {
      const d = drag.current;
      if (!d) return;
      const { x, y } = rel(ev);
      if (d.mode === 'intensity') {
        if (d.startY === null) d.startY = y;
        if (!d.moved && Math.abs(y - d.startY) > 3) d.moved = true;
        if (!d.moved) return;
        setDraggingIntensity({
          triggerId: d.triggerId,
          intensity: clamp01(yToIntensity(g.mainH, y)),
          baseIntensity: d.baseIntensity,
        });
        return;
      }
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
        setDraggingIntensity(null);
        if (!d.moved) return; // plain press: keep the value it started with
        const { y } = rel(ev);
        const raw = clamp01(yToIntensity(g.mainH, y));
        const st = useBuilderStore.getState();
        if (d.multi) {
          // shift every selected circle by the drag delta
          const delta = raw - d.baseIntensity;
          const ids = new Set(st.selectedIds);
          mutateWorking((triggers) => {
            for (const t of triggers) {
              if (ids.has(t.id)) t.intensity = clamp01((t.intensity ?? 0.5) + delta);
            }
          });
        } else {
          const v = snapIntensity(raw, d.triggerId);
          mutateWorking((triggers) => {
            const t = triggers.find((tt) => tt.id === d.triggerId);
            if (t) t.intensity = v;
          });
        }
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

    onContextMenu: (ms, hit, y, g) => {
      const armed = opts.getArmedEventId();
      if (!armed) return;
      if (hit?.kind === 'trigger-triangle' || hit?.kind === 'trigger-intensity') {
        mutateWorking((triggers) => {
          const t = triggers.find((tt) => tt.id === hit.triggerId);
          if (t) t.event_id = armed;
        });
        return;
      }
      // Place: time snaps to the nearest bass onset; the circle starts at the
      // SECTION ENERGY level for that moment (fallback: click Y with the
      // previous-trigger snap).
      const placedMs = Math.max(0, snapToBassOnset(ms));
      const id = uuid();
      const secV = sectionEnergyAt(placedMs);
      let intensity = secV ?? (y !== undefined && g ? clamp01(yToIntensity(g.mainH, y)) : 0.5);
      mutateWorking((triggers) => {
        triggers.push({
          id, timestamp_ms: placedMs, event_id: armed,
          labels: [], enabled: true, intensity,
        });
      });
      if (secV === null) {
        // prev-trigger snap needs the trigger in place (previous = by time)
        const snapped = snapIntensity(intensity, id);
        if (snapped !== intensity) {
          intensity = snapped;
          mutateWorking((triggers) => {
            const t = triggers.find((tt) => tt.id === id);
            if (t) t.intensity = snapped;
          });
        }
      }
      // Select it (arrow keys / "." entry work immediately) and keep holding
      // the right button to slide the circle: hand the new trigger back to
      // the canvas as a live intensity drag.
      useBuilderStore.getState().setSelection([id], id);
      drag.current = {
        mode: 'intensity', triggerId: id, baseIntensity: intensity,
        multi: false, outOfBounds: false, moved: false, startY: null,
      };
      return id;
    },
  };

  return { pointer, draggingIntensity };
}
